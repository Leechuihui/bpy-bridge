# -*- coding: utf-8 -*-
"""Render the architecture diagram.

The single most important thing this project has to communicate is *why* it is
thread-safe: socket worker threads never touch ``bpy``, and a timer pump moves
work onto Blender's main thread. A wall of prose does not land; a diagram does.

Generated rather than hand-drawn so it can be regenerated when the design
changes, and so the text stays crisp instead of being a scaled-up screenshot.

    python tools/render_architecture.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTPUT = os.path.join(ROOT, "docs", "images", "architecture.png")

# Palette shared with tools/render_terminal.py so the docs look like one set.
BG = (24, 26, 33)
PANEL = (33, 36, 45)
PANEL_EDGE = (58, 63, 78)
TEXT = (226, 230, 240)
MUTED = (140, 146, 160)
ACCENT = (110, 160, 230)
SUCCESS = (120, 200, 160)
WARNING = (230, 190, 110)
BOUNDARY = (235, 120, 120)

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


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.stderr.write("Pillow is required: pip install pillow\n")
        return 2

    scale = 2
    width, height = 1180, 620
    image = Image.new("RGB", (width * scale, height * scale), BG)
    draw = ImageDraw.Draw(image)

    body, body_bold = load_fonts(15)
    small, small_bold = load_fonts(12)
    title, title_bold = load_fonts(19)
    code, code_bold = load_fonts(13)

    def rect(x0, y0, x1, y1, fill=PANEL, outline=PANEL_EDGE, radius=8, width_px=2):
        draw.rounded_rectangle(
            [x0 * scale, y0 * scale, x1 * scale, y1 * scale],
            radius=radius * scale, fill=fill, outline=outline, width=width_px * scale,
        )

    def text(x, y, value, font=None, fill=TEXT, anchor="la"):
        draw.text((x * scale, y * scale), value, font=font or body, fill=fill, anchor=anchor)

    def arrow(x0, y0, x1, y1, colour=ACCENT, width_px=2):
        draw.line([x0 * scale, y0 * scale, x1 * scale, y1 * scale],
                  fill=colour, width=width_px * scale)
        # Arrow head, oriented along the line. Only horizontal/vertical arrows are
        # used here, which keeps this trivial and correct.
        size = 9
        if abs(x1 - x0) >= abs(y1 - y0):
            direction = 1 if x1 > x0 else -1
            points = [
                (x1 * scale, y1 * scale),
                ((x1 - direction * size) * scale, (y1 - size * 0.6) * scale),
                ((x1 - direction * size) * scale, (y1 + size * 0.6) * scale),
            ]
        else:
            direction = 1 if y1 > y0 else -1
            points = [
                (x1 * scale, y1 * scale),
                ((x1 - size * 0.6) * scale, (y1 - direction * size) * scale),
                ((x1 + size * 0.6) * scale, (y1 - direction * size) * scale),
            ]
        draw.polygon(points, fill=colour)

    def dashed_vertical(x, y0, y1, colour=BOUNDARY):
        y = y0
        while y < y1:
            draw.line([x * scale, y * scale, x * scale, min(y + 8, y1) * scale],
                      fill=colour, width=2 * scale)
            y += 15

    # -- heading ---------------------------------------------------------
    text(40, 26, "bpy-bridge", title_bold, TEXT)
    text(40, 52, "how a request crosses the thread boundary", body, MUTED)

    # -- column headers --------------------------------------------------
    text(40, 96, "YOUR PROCESS", small_bold, ACCENT)
    text(660, 96, "BLENDER PROCESS", small_bold, ACCENT)

    # -- left column: the client ----------------------------------------
    rect(40, 120, 380, 186)
    text(60, 134, "BridgeClient", body_bold, TEXT)
    text(60, 156, "socket + json only", small, MUTED)

    rect(40, 214, 380, 286)
    text(60, 228, "encode request", body_bold, TEXT)
    text(60, 250, '{"op":"exec","code":...}', code, ACCENT)

    # -- right column: inside Blender ------------------------------------
    rect(660, 120, 1140, 196)
    text(680, 134, "socket worker thread", body_bold, WARNING)
    text(680, 156, "never touches bpy", small, BOUNDARY)

    rect(660, 240, 1140, 316)
    text(680, 254, "queue.put((code, box, event))", code, TEXT)
    text(680, 278, "worker blocks on threading.Event", small, MUTED)

    rect(660, 360, 1140, 448)
    text(680, 374, "bpy.app.timers  ->  MAIN THREAD", body_bold, SUCCESS)
    text(680, 396, "eval/exec in a persistent namespace", small, TEXT)
    text(680, 416, "capture stdout, stderr, traceback", small, TEXT)

    rect(660, 492, 1140, 560)
    text(680, 506, "encode response", body_bold, TEXT)
    text(680, 528, '{"ok":true,"result":"5757",...}', code, ACCENT)

    # -- the thread boundary --------------------------------------------
    dashed_vertical(566, 110, 590)
    text(576, 300, "thread boundary", small_bold, BOUNDARY)
    text(576, 318, "bpy never crosses it", small, BOUNDARY)

    # -- request path (down the left, across, down the right) ------------
    arrow(210, 186, 210, 214, ACCENT)
    arrow(210, 286, 210, 306, ACCENT)
    arrow(210, 306, 660, 306, ACCENT)
    text(300, 290, '{"op":"exec", ...}\\n', code, MUTED)
    arrow(900, 196, 900, 240, ACCENT)
    arrow(900, 316, 900, 360, ACCENT)

    # -- response path (back up) ----------------------------------------
    arrow(900, 448, 900, 492, SUCCESS)
    arrow(900, 560, 900, 584, SUCCESS)
    arrow(900, 584, 380, 584, SUCCESS)
    arrow(380, 584, 380, 380, SUCCESS)
    text(470, 566, '{"ok":true,"result":"5757", ...}\\n', code, MUTED)

    text(60, 372, "response arrives,", body, TEXT)
    text(60, 394, "event.set() releases", body, TEXT)
    text(60, 416, "the blocked worker", body, TEXT)

    # -- footer note -----------------------------------------------------
    text(40, 592, "One connection carries one request and one response, then closes.",
         small, MUTED)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    image.save(OUTPUT, "PNG", optimize=True)
    print("wrote %s" % os.path.relpath(OUTPUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
