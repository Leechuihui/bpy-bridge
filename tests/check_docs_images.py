# -*- coding: utf-8 -*-
"""Check the documentation images: size budget, and that the GIF is animated.

Why this is a script and not a YAML heredoc
-------------------------------------------
Both checks lived inline in the workflow first. That made them impossible to run
locally without copying logic out of YAML, which is how a check quietly stops
matching what it claims to verify. As a script it runs the same way on a
developer's machine and in CI.

Two invariants:

1. **Size budget.** Screenshots and the demo GIF are build artifacts
   (``tools/render_terminal.py``, ``tools/render_demo_gif.py``). They cannot be
   regenerated in CI -- that needs a live Blender -- but committing a 10 MB PNG
   is a mistake worth failing on.

2. **The GIF is actually animated.** A single-frame GIF, or one whose frames are
   identical, renders as a still image and silently breaks the README's most
   prominent visual. This happened for real: the first orbit demo came out as
   eight near-identical frames (mean pixel difference 0.04-0.12) because
   ``bpy.ops.render.opengl`` defaults to ``view_context=True`` and was rendering
   the viewport instead of the scene camera. Nothing else in the suite would have
   caught it.

Pillow is required, and is a docs-only dependency -- the package itself has none.

Run: ``python tests/check_docs_images.py``
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGE_DIR = os.path.join(ROOT, "docs", "images")

#: Per-extension size limits. A GIF gets a larger budget: an animated demo is
#: inherently bigger than a still, and a megabyte of demo GIF earns its place.
SIZE_LIMITS = {
    ".png": 1_500_000,
    ".gif": 2_500_000,
}

#: A GIF with fewer frames than this is not a demo.
MIN_GIF_FRAMES = 3

#: Mean per-pixel difference below which two consecutive frames are considered
#: identical. Well under the ~9-11 the real orbit demo produces, well above the
#: ~0.05 the broken one produced.
MIN_FRAME_DIFF = 1.0

DEMO_GIF = os.path.join(IMAGE_DIR, "demo.gif")


def check_size_budget():
    """Every doc image exists and is within its size limit."""
    if not os.path.isdir(IMAGE_DIR):
        return ["docs/images is missing"]

    problems = []
    total = 0
    print("%-30s %10s" % ("file", "size"))
    print("-" * 42)
    for name in sorted(os.listdir(IMAGE_DIR)):
        extension = os.path.splitext(name)[1].lower()
        if extension not in SIZE_LIMITS:
            continue
        size = os.path.getsize(os.path.join(IMAGE_DIR, name))
        total += size
        limit = SIZE_LIMITS[extension]
        note = ""
        if size > limit:
            note = "  OVER LIMIT (%.1f MB)" % (limit / 1e6)
            problems.append(
                "%s is %.2f MB (limit %.2f MB)" % (name, size / 1e6, limit / 1e6)
            )
        print("%-30s %8.1f KB%s" % (name, size / 1024.0, note))

    print("-" * 42)
    print("total: %.2f MB" % (total / 1e6))
    return problems


def check_gif_is_animated(path=DEMO_GIF):
    """The demo GIF must have several frames, and they must actually differ."""
    if not os.path.exists(path):
        return ["docs/images/demo.gif is missing"]

    try:
        from PIL import Image, ImageChops
    except ImportError:
        return ["Pillow is required for the GIF check: pip install pillow"]

    image = Image.open(path)
    frames = getattr(image, "n_frames", 1)
    problems = []

    if frames < MIN_GIF_FRAMES:
        problems.append(
            "demo.gif has %d frame(s); an animated demo needs at least %d"
            % (frames, MIN_GIF_FRAMES)
        )

    print()
    print("demo.gif: %dx%d, %d frames" % (image.size[0], image.size[1], frames))
    previous = None
    for index in range(frames):
        image.seek(index)
        current = image.convert("RGB")
        if previous is not None:
            diff = ImageChops.difference(previous, current).convert("L")
            histogram = diff.histogram()
            mean = sum(value * count for value, count in enumerate(histogram)) / float(
                current.width * current.height
            )
            flag = ""
            if mean < MIN_FRAME_DIFF:
                flag = "  IDENTICAL"
                problems.append(
                    "frame %d barely differs from frame %d (mean diff %.2f < %.1f)"
                    % (index, index - 1, mean, MIN_FRAME_DIFF)
                )
            print("  frame %d -> %d: mean diff %5.2f%s" % (index - 1, index, mean, flag))
        previous = current

    return problems


def check_images_are_referenced():
    """Every committed image must actually appear in a document.

    This exists because one did not. ``architecture.png`` was generated, committed
    and shipped, but the README kept its old ASCII diagram, so the image was dead
    weight that nobody ever saw -- and no existing check could notice, because
    they all verified that *referenced* paths resolve, not that files are
    referenced at all.

    An unreferenced image is either a forgotten diagram or a leftover from a
    deleted section. Both are worth failing on: one is a documentation gap, the
    other is a repository getting quietly heavier.
    """
    if not os.path.isdir(IMAGE_DIR):
        return ["docs/images is missing"]

    # Every markdown file that can render an image.
    documents = []
    for directory, _subdirs, filenames in os.walk(ROOT):
        # Skip anything that is not documentation.
        if os.sep + "." in directory or os.sep + "build" in directory:
            continue
        for filename in filenames:
            if filename.lower().endswith(".md"):
                documents.append(os.path.join(directory, filename))

    if not documents:
        return ["no markdown documents found to check image references"]

    problems = []
    print()
    print("image references:")
    for name in sorted(os.listdir(IMAGE_DIR)):
        if os.path.splitext(name)[1].lower() not in SIZE_LIMITS:
            continue
        referencing = []
        for path in documents:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    if name in handle.read():
                        referencing.append(os.path.relpath(path, ROOT))
            except (OSError, UnicodeDecodeError):
                continue
        if referencing:
            print("  %-28s %s" % (name, ", ".join(sorted(referencing))))
        else:
            print("  %-28s NOT REFERENCED" % name)
            problems.append(
                "%s is committed but no document references it -- either show it "
                "somewhere or delete it" % name
            )
    return problems


def main():
    problems = check_size_budget()
    problems.extend(check_gif_is_animated())
    problems.extend(check_images_are_referenced())

    print()
    if problems:
        for problem in problems:
            print("FAIL: %s" % problem)
        return 1
    print("OK: doc images within budget, the GIF is animated, and every image is used")
    return 0


if __name__ == "__main__":
    sys.exit(main())
