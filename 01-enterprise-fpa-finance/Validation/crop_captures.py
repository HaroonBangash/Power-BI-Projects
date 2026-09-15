# -*- coding: utf-8 -*-
"""
Crops the report canvas out of each window capture, so the listing shows the
report rather than Power BI Desktop's ribbon and panes.

The canvas is found, not guessed: the theme paints the page and the space around
it in one colour (#0B0D12), which nothing in Desktop's chrome uses, so the
largest run of that colour IS the canvas.

Usage:  python Validation/crop_captures.py [--phase phase4]
"""
import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PAGE_BG = (0x0B, 0x0D, 0x12)
TOLERANCE = 6


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
        crop = img.crop(box)
        out = dst / f.name
        crop.save(out)
        print(f"  {f.name}: {img.size[0]}x{img.size[1]} -> {crop.size[0]}x{crop.size[1]}  {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
