"""Draw packaging/openwrtgui.ico: the header's Wi-Fi glyph on a dark rounded square.

Run: uv run --extra build python packaging/make_icon.py   (the .ico is committed)

The geometry copies the header SVG (viewBox 0 0 24 24): arcs from (5,12.5) to (19,12.5) r=10 and
from (8,15.5) to (16,15.5) r=6, a dot at (12,19) r=1.4, stroke 2 with round caps.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "openwrtgui.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
GLYPH = "#7FD1A8"
TILE = "#15181C"
WORK = 1024  # drawn large, then downsampled for clean edges

# Header SVG units: the glyph spans x 4..20 and y ~8.6..20.4; centre it at 70% of the tile width.
_SCALE = 0.70 * WORK / 16
_ORIGIN = (12.0, 14.5)
_STROKE = 2.0


def _pt(x: float, y: float) -> tuple[float, float]:
    return (WORK / 2 + (x - _ORIGIN[0]) * _SCALE, WORK / 2 + (y - _ORIGIN[1]) * _SCALE)


def _arc(draw: ImageDraw.ImageDraw, half_chord: float, radius: float, chord_y: float) -> None:
    centre_y = chord_y + math.sqrt(radius**2 - half_chord**2)
    cx, cy = _pt(12.0, centre_y)
    r = radius * _SCALE
    w = _STROKE * _SCALE
    sweep = math.degrees(math.asin(half_chord / radius))
    start, end = 270 - sweep, 270 + sweep  # PIL angles run clockwise from 3 o'clock
    outer = r + w / 2
    draw.arc((cx - outer, cy - outer, cx + outer, cy + outer), start, end, fill=GLYPH, width=round(w))
    for angle in (start, end):  # round caps
        ex = cx + r * math.cos(math.radians(angle))
        ey = cy + r * math.sin(math.radians(angle))
        draw.ellipse((ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2), fill=GLYPH)


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (WORK, WORK), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, WORK - 1, WORK - 1), radius=round(WORK * 0.22), fill=TILE)
    _arc(draw, half_chord=7.0, radius=10.0, chord_y=12.5)
    _arc(draw, half_chord=4.0, radius=6.0, chord_y=15.5)
    dx, dy = _pt(12.0, 19.0)
    dot = 1.4 * _SCALE
    draw.ellipse((dx - dot, dy - dot, dx + dot, dy + dot), fill=GLYPH)
    return img


def main() -> None:
    big = draw_icon()
    frames = [big.resize((s, s), Image.Resampling.LANCZOS) for s in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print(f"wrote {OUT} ({', '.join(str(s) for s in SIZES)} px)")


if __name__ == "__main__":
    main()
