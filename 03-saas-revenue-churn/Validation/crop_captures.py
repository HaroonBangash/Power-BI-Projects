# -*- coding: utf-8 -*-
"""
Crops the report canvas out of each window capture, so the listing shows the
report rather than Power BI Desktop's ribbon and panes.

The canvas is found, not guessed: the theme paints the page and the space around
it in one colour (#F7E4E8, the pink ground), which nothing in Desktop's chrome
uses, so the largest run of that colour IS the canvas. A neutral light grey would
NOT work here - Desktop's own chrome is one.

Usage:  python Validation/crop_captures.py [--phase phase4]
"""
import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PAGE_BG = (0xF7, 0xE4, 0xE8)      # the pink ground: nothing in Desktop's chrome uses it
TOLERANCE = 6
CANVAS_W, NAV_W = 1280, 168      # report units: the canvas, and the rail down its left


def canvas_box(img):
    """Bounding box of the page colour, ignoring stray pixels: a row or column
    counts only when a real share of it is the page colour."""
    px = img.convert("RGB").load()
    w, h = img.size

    def is_bg(x, y):
        r, g, b = px[x, y]
        return (abs(r - PAGE_BG[0]) <= TOLERANCE and abs(g - PAGE_BG[1]) <= TOLERANCE
                and abs(b - PAGE_BG[2]) <= TOLERANCE)

    step = 2
    rows = [y for y in range(0, h, step)
            if sum(is_bg(x, y) for x in range(0, w, step)) > 0.30 * (w / step)]
    cols = [x for x in range(0, w, step)
            if sum(is_bg(x, y) for y in range(0, h, step)) > 0.30 * (h / step)]
    if not rows or not cols:
        return None
    return min(cols), min(rows), max(cols) + step, max(rows) + step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="phase4")
    args = ap.parse_args()

    src = ROOT / "Validation" / "evidence" / args.phase
    dst = ROOT / "Validation" / "evidence" / "listing"
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.png")):
        img = Image.open(f)
        box = canvas_box(img)
        if not box:
            print(f"  {f.name}: no canvas found, skipped")
            continue
        # The rail is crimson, so it is NOT part of the pink ground the box was found
        # from - and a listing screenshot without its navigation is half a report. The
        # canvas is 1280 units wide with a 168-unit rail, so the pink region is 1112 of
        # them: scale from that and reach back to pick the rail up.
        x0, y0, x1, y1 = box
        rail_px = round((x1 - x0) * NAV_W / (CANVAS_W - NAV_W))
        box = (max(0, x0 - rail_px), y0, x1, y1)
        crop = img.crop(box)
        out = dst / f.name
        crop.save(out)
        print(f"  {f.name}: {img.size[0]}x{img.size[1]} -> {crop.size[0]}x{crop.size[1]}  {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
