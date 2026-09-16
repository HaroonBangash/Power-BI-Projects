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
PAGES = ROOT / "PowerBI" / "SaaSRevenue.Report" / "definition" / "pages"
EXPECTED = ["Executive", "Revenue Movement", "Retention & Cohorts", "Churn Drivers",
            "Customer Base", "Unit Economics", "Product & Support", "Data & Method"]
TARGET = {"Executive": "Executive Summary", "Revenue Movement": "Revenue Movement",
          "Retention & Cohorts": "Retention & Cohorts", "Churn Drivers": "Churn Drivers",
          "Customer Base": "Customer Base", "Unit Economics": "Unit Economics",
          "Product & Support": "Product & Support", "Data & Method": "Data & Method"}
NAV_W, BTN_W, BTN_H, GAP_MIN, GAP_MAX = 168, 148, 36, 3, 6
RAIL, PANEL, MUTED, HERO_INK, CRIMSON = "#A4132C", "#FFFFFF", "#6E686B", "#6E1023", "#9E1B32"
# Ink on paper: white cards, a crimson figure, and ONE hero card per page filled in that
# page's own tone. The page you are on is a white block on the crimson rail; every other
# page is the rail itself. A page that breaks any of that has drifted from the design.
SPECTRUM = ["#F2A0AC", "#F7C59F", "#E0B0C8", "#F3B3A7", "#CDB4DB", "#F5D5A0", "#F0A8B8", "#BFD0D8"]
PAGE_ACCENT = dict(zip(EXPECTED, SPECTRUM))
STATIC = {"textbox", "actionButton", "shape", "image"}
# Measures whose window is fixed to the as-of date whatever the page filter says, so a
# title claiming a selection would be a lie.
FIXED_WINDOW_MEASURES = {"Annualised Logo Churn %", "Trailing 12m Revenue Retention %",
                         "Monthly Churn Rate (TTM)"}


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
            # On this report the SELECTED page is white and every other is the rail.
            if bg == "#FFFFFF":
                selected.append(label)
            elif bg != RAIL:
                pi.append(f"{label}: fill {bg}, expected the rail colour or white")
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
        # In tab order, not folder order: the hero is the FIRST card a reader meets.
        own = PAGE_ACCENT.get([l for l, d in TARGET.items() if d == name][0])
        kpis = []
        for c in sorted([v for v in vis if v["visual"]["visualType"] == "card"],
                        key=lambda v: v["position"].get("tabOrder", 0)):
            o, vco = c["visual"].get("objects", {}), c["visual"]["visualContainerObjects"]
            hue = lit((props(o, "labels").get("color") or {}).get("solid", {}).get("color"))
            if hue == MUTED:                     # the report-context card is deliberately quiet
                continue
            bg = lit((props(vco, "background").get("color") or {}).get("solid", {}).get("color"))
            kpis.append((hue, bg))
        if kpis:
            hero_hue, hero_bg = kpis[0]
            if hero_bg != own:
                pi.append(f"the hero card is filled {hero_bg}, expected the page tone {own}")
            if hero_hue != HERO_INK:
                pi.append(f"the hero card's figure is {hero_hue}, expected deep crimson on its fill")
            for hue, bg in kpis[1:]:
                if bg != PANEL:
                    pi.append(f"a supporting card is filled {bg}, expected white")
                if hue != CRIMSON:
                    pi.append(f"a supporting card's figure is {hue}, expected crimson")
        want = [l for l, d in TARGET.items() if d == name]
        if selected != want:
            pi.append(f"selected {selected}, expected {want}")
        for v in vis:
            vt, p = v["visual"]["visualType"], v["position"]
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > 1280 or p["y"] + p["height"] > 720:
                pi.append(f"{vt} off-canvas")
            if p.get("z", 1) == 0:
                continue
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
        # The rail backdrop is meant to sit under the rail's contents: it is the one
        # visual whose z is 0, so it identifies itself rather than needing a name list.
        for a, b in itertools.combinations(vis, 2):
            if a["position"].get("z", 1) == 0 or b["position"].get("z", 1) == 0:
                continue
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
