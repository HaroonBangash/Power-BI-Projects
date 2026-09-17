# -*- coding: utf-8 -*-
"""Validate the written report pages: navigation, layout and presentation rules.

Reads the PBIR files as Power BI will read them (not the generator's in-memory
objects), so it also catches anything a hand edit or a Power BI save changed.
Adapted from project 1's validate_navigation.py and validate_layout.py.

Per page:
  navigation  7 buttons in the fixed order with the fixed labels; each targets the
              real page it names; exactly one selected, and it is this page;
              148 x 38 px, 4-6 px apart, inside the 168 px rail
  layout      nothing off-canvas, nothing overlapping, no content under the rail
  titles      every data visual carries a title
  ranked      a chart titled 'Top N' carries a sort and a Top N filter
  tab order   unique
  interaction every visualInteraction names visuals on the page

Usage:  python Validation/validate_report_layout.py
"""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "PowerBI" / "OmnichannelAttribution.Report" / "definition" / "pages"
EXPECTED = ["Executive", "Channels", "Funnel", "Attribution", "Journeys", "Campaigns", "Data & Method"]
TARGET = {"Executive": "Executive Summary", "Channels": "Channels & Budget", "Funnel": "Funnel & Pipeline",
          "Attribution": "Attribution Models", "Journeys": "Customer Journeys", "Campaigns": "Campaign Scorecard",
          "Data & Method": "Data & Method"}
NAV_W, BTN_W, BTN_H, GAP_MIN, GAP_MAX = 168, 148, 38, 4, 6
SELECTED_BG, DEFAULT_BG = "#9AE62E", "#0C150C"     # the client's dark neon theme
STATIC = {"textbox", "actionButton", "shape", "image"}


def lit(o):
    v = (o or {}).get("expr", {}).get("Literal", {}).get("Value") if isinstance(o, dict) else None
    return v.strip("'") if isinstance(v, str) else None


def props(objects, name):
    merged = {}
    for entry in (objects or {}).get(name, []):
        merged.update(entry.get("properties", {}))
    return merged


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
        vis = []
        for vj in sorted((PAGES / pid / "visuals").glob("*/visual.json")):
            v = json.loads(vj.read_text(encoding="utf-8-sig"))
            vis.append(v)
        pi = []
        buttons = sorted([v for v in vis if v["visual"]["visualType"] == "actionButton"], key=lambda v: v["position"]["y"])
        labels, selected, prev = [], [], None
        for b in buttons:
            o = b["visual"].get("objects", {})
            label = lit(props(o, "text").get("text"))
            labels.append(label)
            bg = lit((props(o, "fill").get("fillColor") or {}).get("solid", {}).get("color"))
            if bg == SELECTED_BG:
                selected.append(label)
            elif bg != DEFAULT_BG:
                pi.append(f"{label}: unexpected fill {bg}")
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
            if vt not in STATIC and vt not in ("slicer", "advancedSlicerVisual", "card") \
                    and not (lit(t.get("show")) == "true" and title):
                pi.append(f"{vt} has no title")
            if title.lower().startswith("top "):
                q = v["visual"].get("query", {})
                ftypes = [f.get("type") for f in v.get("filterConfig", {}).get("filters", [])]
                if not q.get("sortDefinition") or "VisualTopN" not in ftypes:
                    pi.append(f"ranked chart '{title}' lacks sort or Top N")
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
        print(f"  {name:<22} {len(vis):>2} visuals, {len(buttons)} nav buttons, selected={selected}  "
              f"{'OK' if not pi else str(len(pi)) + ' ISSUE(S)'}")
        for i in pi:
            print(f"      - {i}")
        issues += pi
    print(f"TOTAL LAYOUT/NAVIGATION ISSUES: {len(issues)}")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
