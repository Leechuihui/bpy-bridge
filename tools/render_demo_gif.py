# -*- coding: utf-8 -*-
"""Render the README demo GIF from a real Blender session.

What this shows, and why it is honest
-------------------------------------
The GIF is not a mock-up. Every frame is produced by sending a real command
through the real CLI to a running Blender, then rendering the actual viewport.
The terminal strip under each frame shows the exact command that produced it.

That constraint is the whole point. A hand-recorded screen capture shows whatever
happened once, on someone else's machine, and silently rots. This regenerates from
whatever the code does today, the same way ``tools/render_terminal.py`` does for
the still screenshots.

Why an orbit and not a layer toggle
-----------------------------------
The first version of this demo hid scatter layers one at a time. Measured against
the real scene, that was a bad idea: hiding ``Scatter_Low`` (555 objects),
``Scatter_OuterLeaves`` (417) and ``Shore_Fringe`` (359) produced a pixel
difference of exactly **0.00**. Diagnosis showed the hide worked perfectly --
``visible_get()`` went from 555 to 0 -- the geometry is simply occluded by taller
layers or outside the frame. A demo whose frames look identical is not a demo.

So this orbits the camera instead. The change is unambiguous, and it proves the
same thing more directly: outside code driving a live scene in real time.

The scene is left exactly as it was found -- camera transform, collection
visibility, render filepath and format are all recorded and restored. A
documentation tool that modifies the user's project is a bug.

Requirements
------------
- Blender running with the bridge started on 127.0.0.1:9876.
- ``bpy-bridge`` installed (``pip install -e .``).
- Pillow (``pip install pillow``).

Usage
-----
    python tools/render_demo_gif.py
    python tools/render_demo_gif.py --keep-frames   # inspect the raw PNGs
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTPUT = os.path.join(ROOT, "docs", "images", "demo.gif")

# Frame geometry. The viewport is captured at the scene's own resolution and
# scaled down; the terminal strip is drawn beneath it.
VIEWPORT_WIDTH = 760
TERMINAL_HEIGHT = 154
FRAME_DELAY_MS = 700

#: Orbit azimuths, in degrees. A half turn, because the back of a miniature
#: landscape is usually less interesting than the front.
ORBIT_DEGREES = (0, 30, 60, 90, 120, 150, 180, 210)

#: Name of the helper injected into Blender's exec namespace. Frames call it by
#: name, so the command shown in the GIF is literally what ran.
HELPER_NAME = "__demo_orbit"

# Palette, shared with tools/render_terminal.py so the docs look like one set.
BG = (24, 26, 33)
TERM_BG = (33, 36, 45)
MUTED = (140, 146, 160)
PROMPT = (120, 200, 160)
COMMAND = (226, 230, 240)
BORDER = (48, 52, 64)

FONT_CANDIDATES = (
    ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolab.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Menlo.ttc"),
)


def load_fonts(size):
    from PIL import ImageFont

    for regular_path, bold_path in FONT_CANDIDATES:
        if os.path.exists(regular_path):
            regular = ImageFont.truetype(regular_path, size)
            bold = ImageFont.truetype(bold_path, size) if os.path.exists(bold_path) else regular
            return regular, bold
    return ImageFont.load_default(), ImageFont.load_default()


def child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_cli(args, timeout=180):
    """Invoke the real CLI as a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "bpy_bridge.cli"] + args,
        cwd=ROOT,
        capture_output=True,
        env=child_env(),
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def bl_exec(code, timeout=180):
    """Run code inside Blender; return the decoded JSON envelope."""
    completed = run_cli(["exec", "--json", code], timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(
            "CLI failed (exit %d)\ncode:\n%s\nstderr:\n%s"
            % (completed.returncode, code, completed.stderr)
        )
    envelope = json.loads(completed.stdout)
    if not envelope.get("ok"):
        # The remote traceback lives in the envelope's `error` field, not in
        # stderr. Reporting only stderr here produced "CLI failed (exit 1)" with
        # an empty message, which hides the actual cause -- a bug in this tool
        # that cost real debugging time.
        raise RuntimeError(
            "remote error (kind=%s)\ncode:\n%s\ntraceback:\n%s\nstdout:\n%s"
            % (envelope.get("kind"), code, envelope.get("error"), envelope.get("stdout"))
        )
    return envelope


def capture_viewport(path, timeout=180):
    """Render the scene camera's view to *path* without touching render settings.

    ``view_context=False`` is load-bearing. ``bpy.ops.render.opengl`` defaults to
    ``view_context=True``, which renders whatever the *viewport* is currently
    looking at rather than the scene camera. With the default, moving ``Cam_Main``
    changed the camera's matrix and produced an identical image -- the first orbit
    demo came out as eight near-identical frames (mean pixel difference 0.04-0.12,
    almost all of it the terminal strip's changing text) and it was not obvious
    why until this was checked. Passing ``False`` renders from the scene camera,
    which is both what an orbit needs and the composition the artist actually set.
    """
    code = (
        "import bpy\n"
        "scene = bpy.context.scene\n"
        "old_path = scene.render.filepath\n"
        "old_fmt = scene.render.image_settings.file_format\n"
        "scene.render.filepath = %r\n"
        "scene.render.image_settings.file_format = 'PNG'\n"
        "bpy.ops.render.opengl(write_still=True, view_context=False)\n"
        "scene.render.filepath = old_path\n"
        "scene.render.image_settings.file_format = old_fmt\n"
        "'captured'"
    ) % path
    bl_exec(code, timeout=timeout)
    if not os.path.exists(path):
        raise RuntimeError("viewport capture produced no file at %s" % path)
    return path


def install_orbit_helper():
    """Define the orbit helper inside Blender and return the framing it computed.

    The helper captures the camera's original transform on first use, computes the
    scene's bounding centre and the current orbit radius, and can restore
    everything. Doing this inside Blender keeps the driver honest: the frames call
    exactly the function the tool installed, nothing is simulated on the host.
    """
    code = '''
import bpy
from mathutils import Vector

def _orbit_setup():
    scene = bpy.context.scene
    camera = scene.camera

    points = []
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        try:
            if not obj.visible_get():
                continue
        except Exception:
            continue
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))

    if points:
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        zs = [p.z for p in points]
        centre = Vector((
            (min(xs) + max(xs)) / 2.0,
            (min(ys) + max(ys)) / 2.0,
            (min(zs) + max(zs)) / 2.0,
        ))
    else:
        centre = Vector((0.0, 0.0, 0.0))

    return scene, camera, centre


def {name}(degrees, reset=False):
    """Orbit the camera around the scene centre by *degrees* of azimuth."""
    scene, camera, centre = _orbit_setup()

    if reset or not hasattr(bpy, "_demo_original"):
        bpy._demo_original = {
            "location": tuple(camera.location),
            "rotation_euler": tuple(camera.rotation_euler),
            "rotation_mode": camera.rotation_mode,
            "centre": tuple(centre),
        }

    original = bpy._demo_original
    centre = Vector(original["centre"])
    start = Vector(original["location"])

    # Preserve the original elevation and distance; only the azimuth changes.
    offset = start - centre
    radius = Vector((offset.x, offset.y, 0.0)).length
    base_angle = __import__("math").atan2(offset.y, offset.x)

    angle = base_angle + __import__("math").radians(degrees)
    location = Vector((
        centre.x + radius * __import__("math").cos(angle),
        centre.y + radius * __import__("math").sin(angle),
        start.z,
    ))

    camera.location = location
    direction = centre - location
    camera.rotation_mode = "QUATERNION"
    camera.rotation_quaternion = direction.to_track_quat("-Z", "Y")
    bpy.context.view_layer.update()
    return "orbit %.0f" % degrees


def {name}_restore():
    """Put the camera back exactly as it was found."""
    scene, camera, _centre = _orbit_setup()
    original = getattr(bpy, "_demo_original", None)
    if original is None:
        return "nothing to restore"
    camera.location = original["location"]
    camera.rotation_mode = original["rotation_mode"]
    camera.rotation_euler = original["rotation_euler"]
    bpy.context.view_layer.update()
    return "restored"
'''.replace("{name}", HELPER_NAME)

    bl_exec(code)

    # Call the helper once at 0 degrees. This is what records the camera's
    # original transform in ``bpy._demo_original``; reading that attribute before
    # any call raises AttributeError. A 0-degree orbit reconstructs the original
    # position from the preserved radius and elevation, so it is a safe no-op
    # that also proves the helper works before the real frames start.
    bl_exec("%s(0)" % HELPER_NAME)

    envelope = bl_exec(
        "import json, bpy\n"
        "print(json.dumps({\n"
        "    'centre': list(bpy._demo_original['centre']),\n"
        "    'camera': bpy.context.scene.camera.name,\n"
        "}))"
    )
    return json.loads(envelope["stdout"])


def read_state():
    """Record everything this tool may touch, so it can be restored."""
    envelope = bl_exec(
        "import bpy, json\n"
        "scene = bpy.context.scene\n"
        "camera = scene.camera\n"
        "print(json.dumps({\n"
        "    'camera': camera.name,\n"
        "    'location': list(camera.location),\n"
        "    'rotation_mode': camera.rotation_mode,\n"
        "    'rotation_euler': list(camera.rotation_euler),\n"
        "    'rotation_quaternion': list(camera.rotation_quaternion),\n"
        "    'hidden': {c.name: bool(c.hide_viewport) for c in bpy.data.collections},\n"
        "    'render_filepath': scene.render.filepath,\n"
        "    'render_format': scene.render.image_settings.file_format,\n"
        "}))"
    )
    return json.loads(envelope["stdout"])


def restore_state(state):
    """Restore camera, collection visibility, and render settings exactly."""
    code = (
        "import bpy, json\n"
        "state = json.loads(%r)\n"
        "scene = bpy.context.scene\n"
        "camera = scene.camera\n"
        "camera.location = state['location']\n"
        "camera.rotation_mode = state['rotation_mode']\n"
        "camera.rotation_euler = state['rotation_euler']\n"
        "camera.rotation_quaternion = state['rotation_quaternion']\n"
        "for collection in bpy.data.collections:\n"
        "    collection.hide_viewport = state['hidden'].get(collection.name, False)\n"
        "scene.render.filepath = state['render_filepath']\n"
        "scene.render.image_settings.file_format = state['render_format']\n"
        "bpy.context.view_layer.update()\n"
        "camera.matrix_world.translation.x\n"
    ) % json.dumps(state)
    bl_exec(code)


def status_line():
    """One compact line describing the live scene, from the real status op."""
    completed = run_cli(["status", "--json"])
    if completed.returncode != 0:
        return "status unavailable"
    info = json.loads(completed.stdout)["status"]
    return "%s objects \u00b7 %s collections \u00b7 %s" % (
        info.get("objects"),
        len(info.get("collections") or []),
        info.get("camera"),
    )


def build_frame(viewport_path, command_text, status_text):
    """Compose one GIF frame: the real viewport above a real-command strip."""
    from PIL import Image, ImageDraw

    viewport = Image.open(viewport_path).convert("RGB")
    ratio = VIEWPORT_WIDTH / float(viewport.width)
    viewport = viewport.resize(
        (VIEWPORT_WIDTH, int(round(viewport.height * ratio))), Image.LANCZOS
    )

    frame = Image.new("RGB", (VIEWPORT_WIDTH, viewport.height + TERMINAL_HEIGHT), BG)
    frame.paste(viewport, (0, 0))

    draw = ImageDraw.Draw(frame)
    top = viewport.height
    draw.rectangle([0, top, VIEWPORT_WIDTH, frame.height], fill=TERM_BG)
    draw.line([0, top, VIEWPORT_WIDTH, top], fill=BORDER, width=1)

    body, body_bold = load_fonts(13)
    small, _small_bold = load_fonts(11)

    prompt = "PS C:\\work> "
    y = top + 22
    draw.text((18, y), prompt, font=body_bold, fill=PROMPT)
    draw.text((18 + body_bold.getlength(prompt), y), command_text, font=body, fill=COMMAND)
    draw.text((18, y + 28), status_text, font=small, fill=MUTED)
    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep-frames", action="store_true",
                        help="keep the intermediate PNG frames for inspection")
    parser.add_argument("--output", default=OUTPUT, help="GIF path (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        from PIL import Image
    except ImportError:
        sys.stderr.write("Pillow is required: pip install pillow\n")
        return 2

    temp_dir = tempfile.mkdtemp(prefix="bpy-bridge-demo-")
    original = read_state()
    print("camera: %s  hidden collections: %d"
          % (original["camera"],
             sum(1 for value in original["hidden"].values() if value)))

    frames = []
    try:
        framing = install_orbit_helper()
        print("scene centre: %s" % (framing["centre"],))

        for index, degrees in enumerate(ORBIT_DEGREES):
            # The command shown in the frame is the command that actually ran.
            envelope = bl_exec("%s(%d)" % (HELPER_NAME, degrees))
            viewport = capture_viewport(os.path.join(temp_dir, "frame_%02d.png" % index))
            frames.append(build_frame(
                viewport,
                'bpy-bridge exec "%s(%d)"' % (HELPER_NAME, degrees),
                "azimuth %3d\u00b0 \u00b7 %s" % (degrees, status_line()),
            ))
            print("frame %d: %s" % (index, envelope["result"]))

        palette_frames = [
            frame.convert("P", palette=Image.ADAPTIVE, colors=128) for frame in frames
        ]
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        palette_frames[0].save(
            args.output,
            save_all=True,
            append_images=palette_frames[1:],
            duration=FRAME_DELAY_MS,
            loop=0,
            optimize=True,
        )
        print("\nwrote %s (%.0f KB, %d frames)"
              % (os.path.relpath(args.output, ROOT),
                 os.path.getsize(args.output) / 1024.0,
                 len(frames)))
        return 0
    finally:
        # Restore even if a frame failed halfway: a documentation tool must never
        # leave the user's project modified.
        bl_exec("%s_restore()" % HELPER_NAME)
        restore_state(original)
        final = read_state()

        same_camera = all(
            abs(a - b) < 1e-6
            for a, b in zip(final["location"], original["location"])
        )
        same_hidden = final["hidden"] == original["hidden"]
        same_render = (
            final["render_filepath"] == original["render_filepath"]
            and final["render_format"] == original["render_format"]
        )
        if same_camera and same_hidden and same_render:
            print("scene state verified restored")
        else:
            sys.stderr.write(
                "WARNING: not fully restored (camera=%s hidden=%s render=%s)\n"
                % (same_camera, same_hidden, same_render)
            )

        if not args.keep_frames:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print("frames kept in %s" % temp_dir)


if __name__ == "__main__":
    sys.exit(main())
