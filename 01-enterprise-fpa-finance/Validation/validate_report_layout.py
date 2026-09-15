# -*- coding: utf-8 -*-
"""Validate the written report pages: navigation, layout and presentation rules.

Reads the PBIR files as Power BI will read them (not the generator's in-memory
objects), so it also catches anything a hand edit or a Power BI save changed.

Per page:
  navigation  8 buttons in the fixed order with the fixed labels; each targets the
              real page it names; exactly one selected, and it is this page;
              148 x 36 px, 3-6 px apart, inside the 168 px rail
  layout      nothing off-canvas, nothing overlapping, no content under the rail
  titles      every data visual carries a title
  ranked      a chart titled 'Top N' carries a sort and a Top N filter
  tab order   unique
  interaction every visualInteraction names visuals on the page
  fixed window a trailing-twelve-month measure never sits on a date axis: it is
              anchored to the as-of date and would read the same in every category
              (PROJECT_STATE D22)

Usage:  python Validation/validate_report_layout.py
"""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "PowerBI" / "EnterpriseFPA.Report" / "definition" / "pages"
EXPECTED = ["Executive", "Income Statement", "Budget Variance", "Cost Centres", "Scenario",
            "Working Capital", "Cash & FX", "Data & Method"]
TARGET = {"Executive": "Executive Summary", "Income Statement": "Income Statement",
          "Budget Variance": "Budget Variance", "Cost Centres": "Cost Centres", "Scenario": "Scenario",
          "Working Capital": "Working Capital", "Cash & FX": "Cash & FX", "Data & Method": "Data & Method"}
NAV_W, BTN_W, BTN_H, GAP_MIN, GAP_MAX = 168, 148, 36, 3, 6
DEFAULT_BG, PANEL, MUTED = "#141922", "#151A23", "#9AA4B6"
# The theme is a rotation, not one accent: every page opens on its own hue, its rail
# button is painted in it, and its cards walk forward through the wheel from there. A
# page whose button or cards fall outside this is a page whose theme has drifted.
SPECTRUM = ["#F5A524", "#818CF8", "#A3E635", "#C084FC", "#22D3EE", "#F472B6", "#60A5FA", "#4ADE80"]
PAGE_ACCENT = dict(zip(EXPECTED, SPECTRUM))
STATIC = {"textbox", "actionButton", "shape", "image"}
FIXED_WINDOW_MEASURES = {"Revenue TTM", "Operating Expense TTM", "Operating Profit TTM"}


def lit(o):
    v = (o or {}).get("expr", {}).get("Literal", {}).get("Value") if isinstance(o, dict) else None
    return v.strip("'") if isinstance(v, str) else None


def props(objects, name):
    merged = {}
    for entry in (objects or {}).get(name, []):
        merged.update(entry.get("properties", {}))
    return merged


def projections(v):
    """(measures, date columns) a visual projects."""
    measures, dates = set(), set()
    for spec in v["visual"].get("query", {}).get("queryState", {}).values():
        for p in spec.get("projections", []):
            f = p.get("field", {})
            if "Measure" in f:
                measures.add(f["Measure"]["Property"])
            elif "Column" in f:
                c = f["Column"]
                if c["Expression"]["SourceRef"].get("Entity") == "DimDate":
                    dates.add(c["Property"])
    return measures, dates


def main():
    pages = {}
    for d in sorted(p for p in PAGES.iterdir() if p.is_dir()):
        pages[d.name] = json.loads((d / "page.json").read_text(encoding="utf-8-sig"))
    order = json.loads((PAGES / "pages.json").read_text(encoding="utf-8-sig"))["pageOrder"]
    display = {k: v["displayName"] for k, v in pages.items()}
    issues = []
    if sorted(order) != sorted(pages):
        issues.append("pages.json pageOrder does not match the page folders")
    print(f"{len(pages)} page(s)")
    for pid in order:
        page, name = pages[pid], display[pid]
        vis = [json.loads(vj.read_text(encoding="utf-8-sig"))
               for vj in sorted((PAGES / pid / "visuals").glob("*/visual.json"))]
        pi = []
        buttons = sorted([v for v in vis if v["visual"]["visualType"] == "actionButton"],
                         key=lambda v: v["position"]["y"])
        labels, selected, prev = [], [], None
        for b in buttons:
            o = b["visual"].get("objects", {})
            label = lit(props(o, "text").get("text"))
            labels.append(label)
            bg = lit((props(o, "fill").get("fillColor") or {}).get("solid", {}).get("color"))
            if bg != DEFAULT_BG:
                selected.append(label)
                if bg != PAGE_ACCENT.get(label):
                    pi.append(f"{label}: selected fill {bg}, expected {PAGE_ACCENT.get(label)}")
            link = props(b["visual"].get("visualContainerObjects", {}), "visualLink")
            target = lit(link.get("navigationSection"))
            if lit(link.get("type")) != "PageNavigation":
                pi.append(f"{label}: not a page-navigation button")
            elif target not in display:
                # With --only a single page is written for a rendering check, so the
                # other targets legitimately do not exist; report, do not fail.
                if len(pages) > 1:
                    pi.append(f"{label}: target {target} is not a page")
            elif display[target] != TARGET.get(label):
                pi.append(f"{label}: goes to '{display[target]}', expected '{TARGET.get(label)}'")
            p = b["position"]
            if (p["width"], p["height"]) != (BTN_W, BTN_H):
                pi.append(f"{label}: {p['width']}x{p['height']}, expected {BTN_W}x{BTN_H}")
            if p["x"] + p["width"] > NAV_W:
                pi.append(f"{label}: extends past the rail")
            if prev is not None and not GAP_MIN <= p["y"] - prev <= GAP_MAX:
                pi.append(f"{label}: spacing {p['y'] - prev}px outside {GAP_MIN}-{GAP_MAX}")
            prev = p["y"] + p["height"]
        if labels != EXPECTED:
            pi.append(f"button labels/order {labels}")
        hues = []
        # In tab order, not folder order: the rotation is what the reader walks along.
        for c in sorted([v for v in vis if v["visual"]["visualType"] == "card"],
                        key=lambda v: v["position"].get("tabOrder", 0)):
            o, vco = c["visual"].get("objects", {}), c["visual"]["visualContainerObjects"]
            hue = lit((props(o, "labels").get("color") or {}).get("solid", {}).get("color"))
            if hue == MUTED:                     # the report-context card is deliberately quiet
                continue
            hues.append(hue)
            if hue not in SPECTRUM:
                pi.append(f"card value colour {hue} is outside the rotation")
            bg = lit((props(vco, "background").get("color") or {}).get("solid", {}).get("color"))
            if bg is None or bg == PANEL:
                pi.append(f"card in {hue} sits on an untinted panel ({bg})")
        if len(hues) != len(set(hues)):
            pi.append(f"two cards share a hue: {hues}")
        own = PAGE_ACCENT.get([l for l, d in TARGET.items() if d == name][0])
        if hues and own in SPECTRUM:
            start = SPECTRUM.index(own)
            want = [SPECTRUM[(start + i) % len(SPECTRUM)] for i in range(len(hues))]
            if hues != want:
                pi.append(f"card rotation {hues}, expected {want}")
        want = [l for l, d in TARGET.items() if d == name]
        if selected != want:
            pi.append(f"selected {selected}, expected {want}")
        for v in vis:
            vt, p = v["visual"]["visualType"], v["position"]
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > 1280 or p["y"] + p["height"] > 720:
                pi.append(f"{vt} off-canvas")
            if vt not in STATIC and p["x"] < NAV_W:
                pi.append(f"{vt} under the rail (x={p['x']})")
            t = props(v["visual"].get("visualContainerObjects", {}), "title")
            title = lit(t.get("text")) or ""
            if vt not in STATIC and vt not in ("slicer", "advancedSlicerVisual", "card", "multiRowCard", "kpi") \
                    and not (lit(t.get("show")) == "true" and title):
                pi.append(f"{vt} has no title")
            if title.lower().startswith("top "):
                q = v["visual"].get("query", {})
                ftypes = [f.get("type") for f in v.get("filterConfig", {}).get("filters", [])]
                if not q.get("sortDefinition") or "VisualTopN" not in ftypes:
                    pi.append(f"ranked chart '{title}' lacks sort or Top N")
            measures, dates = projections(v)
            fixed = measures & FIXED_WINDOW_MEASURES
            if fixed and dates:
                pi.append(f"{vt} '{title}': fixed-window measure {sorted(fixed)} on a date axis {sorted(dates)}")
        for a, b in itertools.combinations(vis, 2):
            pa, pb = a["position"], b["position"]
            ix = min(pa["x"] + pa["width"], pb["x"] + pb["width"]) - max(pa["x"], pb["x"])
            iy = min(pa["y"] + pa["height"], pb["y"] + pb["height"]) - max(pa["y"], pb["y"])
            if ix > 0 and iy > 0:
                pi.append(f"overlap {a['visual']['visualType']} / {b['visual']['visualType']}")
        tabs = [v["position"].get("tabOrder", 0) for v in vis]
        if len(tabs) != len(set(tabs)):
            pi.append("duplicate tabOrder")
        names = {v["name"] for v in vis}
        for i in page.get("visualInteractions", []):
            if i["source"] not in names or i["target"] not in names:
                pi.append("visualInteraction names a visual not on the page")
        print(f"  {name:<22} {len(vis):>3} visuals, {len(buttons)} nav buttons, selected={selected}  "
              f"{'OK' if not pi else str(len(pi)) + ' ISSUE(S)'}")
        for i in pi:
            print(f"      - {i}")
        issues += pi
    print(f"TOTAL LAYOUT/NAVIGATION ISSUES: {len(issues)}")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
