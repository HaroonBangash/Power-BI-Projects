# -*- coding: utf-8 -*-
"""
Builds a larger copy of the general ledger for the scale test, into Data/Scaled
(git-ignored). Self-contained: it samples the real ledger in Data/raw, so no
machine-specific path and no second source are needed.

Each generated line keeps a real combination of entity, department, account and
currency - only the identifier and the date move - so the scaled ledger has the
same shape and the same joins as the real one. It is a VOLUME test, not a new
dataset: nothing generated here ever reaches the report.

Usage:  python Python/scale_ledger.py --rows 1000000
"""
import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Data" / "raw" / "fact_gl.csv"
OUT_DIR = ROOT / "Data" / "Scaled"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=20260911)
    args = ap.parse_args()

    random.seed(args.seed)
    with SOURCE.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    print(f"sampling {len(rows):,} real ledger lines")

    # The date window of the real ledger, so every generated line still joins to
    # the calendar and to a monthly exchange rate.
    dates = sorted({r[1] for r in rows})
    first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    span = (last - first).days

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"fact_gl_{args.rows // 1000}k.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(header)
        for i in range(1, args.rows + 1):
            r = list(random.choice(rows))
            r[0] = f"GX{i:09d}"
            r[1] = (first + timedelta(days=random.randint(0, span))).isoformat()
            w.writerow(r)
    print(f"wrote {out.relative_to(ROOT)}: {args.rows:,} lines, {out.stat().st_size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
