# -*- coding: utf-8 -*-
"""Render terminal-style PNGs from *real* captured command output.

Why this exists
---------------
Screenshots in documentation rot. Someone takes a terminal screenshot, the CLI
gains a flag, and the image silently lies for a year. The fix is to make the
images a build artifact: run the real command, capture its real stdout/stderr and
exit code, then draw that into a PNG. Re-running this script regenerates every
image in ``docs/images/`` from whatever the code does today.

It is deliberately not part of the test suite -- it needs Pillow, which the
package itself must never depend on -- but it lives in the repo so the docs stay
reproducible instead of hand-maintained.

Usage
-----
    python tools/render_terminal.py            # regenerate all screenshots
    python tools/render_terminal.py --list     # show what would be rendered

The input is a JSON manifest (``tools/screenshots.json``) of *commands to run*
and *how to frame them*. Nothing in this file hardcodes command output; if the
CLI changes, the screenshots change with it.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "screenshots.json")
OUTPUT_DIR = os.path.join(ROOT, "docs", "images")

# --------------------------------------------------------------------- palette
# A restrained dark theme: enough contrast to read on a phone, no rainbow.
BG = (24, 26, 33)
TITLEBAR = (33, 36, 45)
TITLEBAR_TEXT = (140, 146, 160)
BORDER = (48, 52, 64)
PROMPT_USER = (120, 200, 160)
PROMPT_PATH = (110, 160, 230)
COMMAND = (226, 230, 240)
OUTPUT = (176, 182, 196)
MUTED = (110, 116, 130)
STDOUT = (200, 205, 218)
SUCCESS = (120, 200, 160)
ERROR = (235, 120, 120)
WARNING = (230, 190, 110)
ACCENT = (150, 170, 240)

FONT_CANDIDATES = (
    ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolab.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Menlo.ttc"),
)


def _load_fonts(size):
    """Return (regular, bold) fonts, falling back to Pillow's default."""
    from PIL import ImageFont

    for regular_path, bold_path in FONT_CANDIDATES:
        if os.path.exists(regular_path):
            regular = ImageFont.truetype(regular_path, size)
            bold = ImageFont.truetype(bold_path, size) if os.path.exists(bold_path) else regular
            return regular, bold
    return ImageFont.load_default(), ImageFont.load_default()


# ------------------------------------------------------------------ execution
def run_command(command, cwd, env_extra=None, timeout=120):
    """Run *command* and capture everything a terminal would show.

    Returns a dict with the command line, stdout, stderr, and exit code. The
    exit code is captured rather than raised on: documenting ``exit=3`` is the
    point of several screenshots.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    if env_extra:
        env.update(env_extra)

    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        env=env,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=isinstance(command, str),
    )
    return {
        "command": command if isinstance(command, str) else " ".join(command),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }


# --------------------------------------------------------------------- drawing
def _classify(line, context):
    """Pick a colour for one output line.

    Heuristic, not parsing: enough to make tracebacks red and warnings amber
    without pretending to understand the CLI's grammar.
    """
    stripped = line.strip()
    if not stripped:
        return OUTPUT
    lowered = stripped.lower()
    if stripped.startswith(("Traceback", "  File \"", "bpy-bridge:")) or "error" in lowered:
        return ERROR
    if stripped.startswith("warning") or "warning" in lowered[:12]:
        return WARNING
    if stripped.startswith(("OK", "pong", "clean")):
        return SUCCESS
    if context == "stdout":
        return STDOUT
    return OUTPUT


def render_screenshot(spec, result, out_path, scale=2):
    """Draw one terminal window containing *result* and save it as PNG."""
    from PIL import Image, ImageDraw

    font_size = spec.get("font_size", 15)
    line_height = int(font_size * 1.55)
    padding = 20
    titlebar_height = 34

    regular, bold = _load_fonts(font_size)
    small, _ = _load_fonts(max(11, font_size - 4))

    # Build the list of (text, colour) lines first so the canvas can be sized.
    rows = []

    prompt = spec.get("prompt", "PS C:\\project>")
    if spec.get("show_command", True):
        rows.append((prompt + " " + result["command"], COMMAND))

    body = result["stdout"]
    if spec.get("show_stderr", True) and result["stderr"]:
        if body and not body.endswith("\n"):
            body += "\n"
        body += result["stderr"]
    for line in body.splitlines():
        rows.append((line, _classify(line, "stdout")))

    exit_code = result["returncode"]
    if spec.get("show_exit_code", False):
        colour = SUCCESS if exit_code == 0 else ERROR
        rows.append(("exit=%d" % exit_code, colour))

    if not rows:
        rows.append(("(no output)", MUTED))

    # Longest line drives the width, within a sensible cap.
    char_width = regular.getlength("M") or 8
    longest = max(len(text) for text, _ in rows)
    width = int(min(max(longest, 34) * char_width + padding * 2, spec.get("max_width", 1180)))
    height = titlebar_height + padding * 2 + len(rows) * line_height + 6

    image = Image.new("RGB", (width * scale, height * scale), BG)
    draw = ImageDraw.Draw(image)

    def box(x0, y0, x1, y1, colour):
        draw.rectangle([x0 * scale, y0 * scale, x1 * scale, y1 * scale], fill=colour)

    # Title bar with three window dots and a caption.
    box(0, 0, width, titlebar_height, TITLEBAR)
    for index, dot_colour in enumerate(((235, 106, 94), (245, 191, 79), (98, 197, 84))):
        cx = (padding - 4 + index * 18) * scale
        cy = (titlebar_height // 2) * scale
        radius = 5 * scale
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=dot_colour)
    caption = spec.get("caption", "")
    if caption:
        draw.text(((padding + 58) * scale, (titlebar_height // 2 - 8) * scale),
                  caption, font=small, fill=TITLEBAR_TEXT)
    draw.line([0, titlebar_height * scale, width * scale, titlebar_height * scale],
              fill=BORDER, width=scale)

    # Body text.
    y = titlebar_height + padding
    for text, colour in rows:
        x = padding
        if text.startswith(prompt):
            draw.text((x * scale, y * scale), prompt, font=bold, fill=PROMPT_USER)
            x += regular.getlength(prompt)
            remainder = text[len(prompt):]
            draw.text((x * scale, y * scale), remainder, font=regular, fill=COMMAND)
        else:
            # Soft-wrap rather than clip; a truncated command is worse than a
            # taller image.
            available = width - padding * 2
            chunk = text
            while chunk:
                fitted = chunk
                while fitted and regular.getlength(fitted) > available:
                    fitted = fitted[:-1]
                draw.text((x * scale, y * scale), fitted, font=regular, fill=colour)
                chunk = chunk[len(fitted):]
                if chunk:
                    y += line_height
        y += line_height

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path


# ------------------------------------------------------------------------ main
def load_manifest(path=MANIFEST):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def render_all(manifest, only=None):
    rendered = []
    for spec in manifest["screenshots"]:
        name = spec["name"]
        if only and name not in only:
            continue
        result = run_command(
            spec["command"],
            cwd=os.path.join(ROOT, spec.get("cwd", ".")),
            env_extra=spec.get("env"),
            timeout=spec.get("timeout", 120),
        )
        out_path = os.path.join(OUTPUT_DIR, name + ".png")
        render_screenshot(spec, result, out_path, scale=spec.get("scale", 2))
        rendered.append((name, out_path, result["returncode"]))
    return rendered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list screenshot names and exit")
    parser.add_argument("--only", nargs="+", help="render only these screenshots")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    if args.list:
        for spec in manifest["screenshots"]:
            print("%-28s %s" % (spec["name"], spec["command"]))
        return 0

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "Pillow is required to render screenshots: pip install pillow\n"
            "(This is a docs-only dependency; the package itself has none.)\n"
        )
        return 2

    rendered = render_all(manifest, only=args.only)
    for name, path, code in rendered:
        print("%-28s exit=%-3d %s" % (name, code, os.path.relpath(path, ROOT)))
    print("\n%d screenshot(s) rendered into %s" % (len(rendered), os.path.relpath(OUTPUT_DIR, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
