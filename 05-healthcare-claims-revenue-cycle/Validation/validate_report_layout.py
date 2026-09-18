# -*- coding: utf-8 -*-
"""Validate the written report pages: navigation, layout and presentation rules.

Reads the PBIR files as Power BI will read them (not the generator's in-memory
objects), so it also catches anything a hand edit or a Power BI save changed.

Per page:
  navigation  8 tabs in the fixed order with the fixed labels, across the TOP bar;
              each targets the real page it names; exactly one selected, and it is
              this page; fixed size, fixed spacing, inside the 56 px bar
  theme       the hero card is LIFTED and writes its figure in the accent; every
              other card sits on the panel colour and writes in ink
  layout      nothing off-canvas, nothing overlapping, nothing under the top bar
  titles      every data visual carries a title
  ranked      a chart titled 'Top N' carries a sort and a Top N filter
  tab order   unique
  interaction every visualInteraction names visuals on the page
  disconnected a measure from a DISCONNECTED table never sits on a date axis. It
              cannot respond to one, so it would draw a flat line that looks like a
              finding and is not (PROJECT_STATE D11, D12)

Usage:  python Validation/validate_report_layout.py
"""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "PowerBI" / "HealthcareRCM.Report" / "definition" / "pages"

EXPECTED = ["Executive", "Revenue Cycle", "Receivables", "Denials",
            "What Predicts", "Timeliness", "Service Mix", "Data & Method"]
TARGET = {"Executive": "Executive Summary", "Revenue Cycle": "Revenue Cycle",
          "Receivables": "Accounts Receivable", "Denials": "Denials",
          "What Predicts": "What Predicts a Denial", "Timeliness": "Timeliness",
          "Service Mix": "Service & Patient Mix", "Data & Method": "Data & Method"}

# The bar runs across the top, so the tabs are checked along X, not down Y.
W, H, TOPBAR_H = 1280, 720, 56
BRAND_W, TAB_H, TAB_GAP = 236, 32, 4
TAB_W = (W - BRAND_W - 16 - TAB_GAP * 7) // 8

# The dark operations console. One accent, one panel colour, and a hero card that is
# LIFTED rather than recoloured - filling a card with colour on a dark ground buries
# its own number. A page that breaks any of this has drifted from the design.
ACCENT, MUTED, INK = "#37C9A8", "#8FA9AD", "#E6F1F2"
PANEL, PANEL_HI = "#10292F", "#143840"
STATIC = {"textbox", "actionButton", "shape", "image"}

# Measures that live on a DISCONNECTED table. They cannot respond to a date filter, so
# on a date axis they would draw a flat line that looks like a finding and is not.
DISCONNECTED_MEASURES = {
    "Signal Strength", "Strongest Signal", "Strongest Signal Dimension", "Dimensions Tested",
    "Dimensions with Signal", "Denial Rate Spread (pp)", "Signal Verdict",
    "Providers Measured", "Providers Beyond 2 SE", "Providers Beyond 2 SE %",
    "Largest Provider Z-Score", "Provider Denial Rate", "Provider Standard Error",
    "Group Denial Rate", "Data Quality Value", "Findings Recorded",
    "Expected Beyond 2 SE %", "Rate Scale Max", "Net Collection Benchmark",
}


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

        # --- the navigation bar. A TAB is a button that carries a page link; the
        #     wordmark and the bar backdrop are buttons too, and are not tabs.
        navtabs = sorted([v for v in vis if v["visual"]["visualType"] == "actionButton"
                          and props(v["visual"].get("visualContainerObjects", {}), "visualLink")],
                         key=lambda v: v["position"]["x"])
        labels, selected, prev = [], [], None
        for b in navtabs:
            o = b["visual"].get("objects", {})
            label = lit(props(o, "text").get("text"))
            labels.append(label)
            # Selected and unselected tabs share a fill colour and differ only in
            # transparency, so the TEXT colour is what identifies the current page -
            # which is also what a reader goes by.
            fg = lit((props(o, "text").get("fontColor") or {}).get("solid", {}).get("color"))
            if fg == ACCENT:
                selected.append(label)
            elif fg != MUTED:
                pi.append(f"{label}: text {fg}, expected the accent or the muted tone")
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
            if (p["width"], p["height"]) != (TAB_W, TAB_H):
                pi.append(f"{label}: {p['width']}x{p['height']}, expected {TAB_W}x{TAB_H}")
            if p["y"] + p["height"] > TOPBAR_H:
                pi.append(f"{label}: extends below the top bar")
            if p["x"] < BRAND_W:
                pi.append(f"{label}: overlaps the wordmark")
            if prev is not None and p["x"] - prev != TAB_GAP:
                pi.append(f"{label}: spacing {p['x'] - prev}px, expected {TAB_GAP}")
            prev = p["x"] + p["width"]
        if labels != EXPECTED:
            pi.append(f"tab labels/order {labels}")
        want = [l for l, d in TARGET.items() if d == name]
        if selected != want:
            pi.append(f"selected {selected}, expected {want}")

        # --- the cards, in TAB order: the hero is the FIRST card a reader meets.
        kpis = []
        for c in sorted([v for v in vis if v["visual"]["visualType"] == "card"],
                        key=lambda v: v["position"].get("tabOrder", 0)):
            o, vco = c["visual"].get("objects", {}), c["visual"]["visualContainerObjects"]
            hue = lit((props(o, "labels").get("color") or {}).get("solid", {}).get("color"))
            if hue == MUTED:                     # the as-of context card is deliberately quiet
                continue
            bg = lit((props(vco, "background").get("color") or {}).get("solid", {}).get("color"))
            kpis.append((hue, bg))
        if kpis:
            hero_hue, hero_bg = kpis[0]
            if hero_bg != PANEL_HI:
                pi.append(f"the hero card is filled {hero_bg}, expected the lifted panel {PANEL_HI}")
            if hero_hue != ACCENT:
                pi.append(f"the hero card's figure is {hero_hue}, expected the accent")
            for hue, bg in kpis[1:]:
                if bg != PANEL:
                    pi.append(f"a supporting card is filled {bg}, expected the panel colour")
                if hue != INK:
                    pi.append(f"a supporting card's figure is {hue}, expected ink")

        # --- geometry, titles and the disconnected-measure rule
        for v in vis:
            vt, p = v["visual"]["visualType"], v["position"]
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > W or p["y"] + p["height"] > H:
                pi.append(f"{vt} off-canvas")
            if p.get("z", 1) == 0:
                continue
            if vt not in STATIC and p["y"] < TOPBAR_H:
                pi.append(f"{vt} under the top bar (y={p['y']})")
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
            stuck = measures & DISCONNECTED_MEASURES
            if stuck and dates:
                pi.append(f"{vt} '{title}': disconnected measure {sorted(stuck)} on a date axis {sorted(dates)}")

        # --- overlap. The bar backdrop and the tab indicator are MEANT to sit under
        #     what stands on them: they are the visuals whose z is 0, so they identify
        #     themselves rather than needing a name list.
        for a, b in itertools.combinations(vis, 2):
            if a["position"].get("z", 1) == 0 or b["position"].get("z", 1) == 0:
                continue
            pa, pb = a["position"], b["position"]
            ix = min(pa["x"] + pa["width"], pb["x"] + pb["width"]) - max(pa["x"], pb["x"])
            iy = min(pa["y"] + pa["height"], pb["y"] + pb["height"]) - max(pa["y"], pb["y"])
            if ix > 0 and iy > 0:
                pi.append(f"overlap {a['visual']['visualType']} / {b['visual']['visualType']}")
        tab_order = [v["position"].get("tabOrder", 0) for v in vis]
        if len(tab_order) != len(set(tab_order)):
            pi.append("duplicate tabOrder")
        names = {v["name"] for v in vis}
        for i in page.get("visualInteractions", []):
            if i["source"] not in names or i["target"] not in names:
                pi.append("visualInteraction names a visual not on the page")
        print(f"  {name:<24} {len(vis):>3} visuals, {len(navtabs)} nav tabs, selected={selected}  "
              f"{'OK' if not pi else str(len(pi)) + ' ISSUE(S)'}")
        for i in pi:
            print(f"      - {i}")
        issues += pi
    print(f"TOTAL LAYOUT/NAVIGATION ISSUES: {len(issues)}")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
