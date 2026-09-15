# -*- coding: utf-8 -*-
r"""Validate the left navigation sidebar across every report page.

Checks, per page:
  * the legacy pageNavigator visual is gone
  * exactly 10 navigation buttons exist, in the required order, with the
    required labels
  * every button's navigationSection resolves to a real page folder, and to the
    page whose display name it claims
  * exactly one button is in the selected state, and it is the current page
  * button geometry matches the brief (width, height, spacing, font)
  * nothing overlaps, nothing leaves the canvas, nothing sits under the sidebar
"""
import json, os, sys, itertools

from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
RPT = str(ROOT / "PowerBI" / "SupplyChainControlTower.Report" / "definition" / "pages")

EXPECTED = ["Executive", "Inventory", "Procurement", "Logistics", "Warehouse",
            "Product / SKU", "Replenishment", "ABC / XYZ", "Suppliers", "Forecasting"]

TARGET_DISPLAY = {
    "Executive": "Executive Control Tower",
    "Inventory": "Inventory Overview",
    "Procurement": "Procurement Overview",
    "Logistics": "Logistics & Delivery",
    "Warehouse": "Warehouse Performance",
    "Product / SKU": "Product / SKU Detail",
    "Replenishment": "Stockout & Replenishment Risk",
    "ABC / XYZ": "ABC/XYZ Inventory Strategy",
    "Suppliers": "Supplier Performance",
    "Forecasting": "Demand Forecasting",
}

NAV_W, BTN_W, BTN_H, GAP_MIN, GAP_MAX = 168, 148, 38, 4, 6
SELECTED_BG = "#0E7490"
DEFAULT_BG = "#F1F5F9"

issues = []


def lit(o):
    """Unwrap {"expr":{"Literal":{"Value":"'x'"}}} to x."""
    if not isinstance(o, dict):
        return None
    v = o.get("expr", {}).get("Literal", {}).get("Value")
    return v.strip("'") if isinstance(v, str) else None


def obj_props(objects, name):
    """Merge every properties bag for a formatting object into one dict."""
    merged = {}
    for entry in (objects or {}).get(name, []):
        merged.update(entry.get("properties", {}))
    return merged


# page id -> display name
pages = {}
for d in sorted(os.listdir(RPT)):
    pj = os.path.join(RPT, d, "page.json")
    if os.path.isfile(pj):
        pages[d] = json.load(open(pj, encoding="utf-8-sig"))["displayName"]

print("Pages found: %d\n" % len(pages))

for pid, display in sorted(pages.items(), key=lambda kv: kv[1]):
    vdir = os.path.join(RPT, pid, "visuals")
    buttons, others, legacy = [], [], []
    for vd in sorted(os.listdir(vdir)):
        vj = os.path.join(vdir, vd, "visual.json")
        if not os.path.isfile(vj):
            continue
        v = json.load(open(vj, encoding="utf-8-sig"))
        vt = v.get("visual", {}).get("visualType")
        pos = v.get("position", {})
        if vt == "pageNavigator":
            legacy.append(vd[:8])
        elif vt == "actionButton":
            buttons.append((vd, v, pos))
        else:
            others.append((vd, v, pos, vt))

    page_issues = []
    if legacy:
        page_issues.append("legacy pageNavigator still present: %s" % legacy)
    if len(buttons) != 10:
        page_issues.append("expected 10 nav buttons, found %d" % len(buttons))

    buttons.sort(key=lambda b: b[2].get("y", 0))
    labels, selected = [], []
    prev_bottom = None
    for vd, v, pos in buttons:
        vis = v["visual"]
        objs = vis.get("objects", {})
        text = obj_props(objs, "text")
        fill = obj_props(objs, "fill")
        label = lit(text.get("text"))
        labels.append(label)
        fg = (text.get("fontColor") or {}).get("solid", {}).get("color")
        bg = (fill.get("fillColor") or {}).get("solid", {}).get("color")
        bg_hex = lit(bg)
        if bg_hex == SELECTED_BG:
            selected.append(label)
        elif bg_hex != DEFAULT_BG:
            page_issues.append("%s: unexpected fill %s" % (label, bg_hex))
        if lit(fg) is None:
            page_issues.append("%s: no font colour" % label)
        size = text.get("fontSize", {}).get("expr", {}).get("Literal", {}).get("Value")
        if size not in ("10D", "11D"):
            page_issues.append("%s: font size %s outside 10-11pt" % (label, size))

        # navigation target
        vco = vis.get("visualContainerObjects", {})
        link = obj_props(vco, "visualLink")
        if not link:
            page_issues.append("%s: NO visualLink - button does not navigate" % label)
        else:
            if lit(link.get("type")) != "PageNavigation":
                page_issues.append("%s: link type is %s" % (label, lit(link.get("type"))))
            target = lit(link.get("navigationSection"))
            if target not in pages:
                page_issues.append("%s: navigationSection '%s' is not a real page" % (label, target))
            elif pages[target] != TARGET_DISPLAY.get(label):
                page_issues.append("%s: navigates to '%s', expected '%s'"
                                   % (label, pages[target], TARGET_DISPLAY.get(label)))

        # geometry
        if pos.get("width") != BTN_W or pos.get("height") != BTN_H:
            page_issues.append("%s: size %sx%s, expected %sx%s"
                               % (label, pos.get("width"), pos.get("height"), BTN_W, BTN_H))
        if pos.get("x", 0) + pos.get("width", 0) > NAV_W:
            page_issues.append("%s: extends past the sidebar" % label)
        if prev_bottom is not None:
            gap = pos.get("y", 0) - prev_bottom
            if not (GAP_MIN <= gap <= GAP_MAX):
                page_issues.append("%s: spacing %s px outside %d-%d" % (label, gap, GAP_MIN, GAP_MAX))
        prev_bottom = pos.get("y", 0) + pos.get("height", 0)

    if labels != EXPECTED:
        page_issues.append("label order wrong:\n      got      %s\n      expected %s" % (labels, EXPECTED))
    want_selected = [l for l, dn in TARGET_DISPLAY.items() if dn == display]
    if len(selected) != 1:
        page_issues.append("expected exactly 1 selected button, found %d %s" % (len(selected), selected))
    elif want_selected and selected[0] != want_selected[0]:
        page_issues.append("selected '%s' but this page is '%s'" % (selected[0], want_selected[0]))

    # nothing else may sit under the rail, and nothing off-canvas
    for vd, v, pos, vt in others:
        if pos.get("x", 0) < NAV_W and vt not in ("textbox",):
            page_issues.append("%s %s overlaps the sidebar (x=%s)" % (vd[:8], vt, pos.get("x")))
        if pos.get("x", 0) + pos.get("width", 0) > 1280.5 or pos.get("y", 0) + pos.get("height", 0) > 720.5:
            page_issues.append("%s %s off-canvas" % (vd[:8], vt))

    # button-vs-button and button-vs-content overlap
    allv = [(vd, pos) for vd, v, pos in buttons] + [(vd, pos) for vd, v, pos, vt in others]
    for (a_id, a), (b_id, b) in itertools.combinations(allv, 2):
        ix = min(a.get("x", 0) + a.get("width", 0), b.get("x", 0) + b.get("width", 0)) - max(a.get("x", 0), b.get("x", 0))
        iy = min(a.get("y", 0) + a.get("height", 0), b.get("y", 0) + b.get("height", 0)) - max(a.get("y", 0), b.get("y", 0))
        if ix > 1 and iy > 1:
            page_issues.append("overlap: %s <-> %s" % (a_id[:8], b_id[:8]))

    status = "OK" if not page_issues else "%d ISSUE(S)" % len(page_issues)
    print("%-32s %2d buttons, selected=%-14s %s"
          % (display, len(buttons), (selected[0] if len(selected) == 1 else "?"), status))
    for i in page_issues:
        print("      - %s" % i)
    issues.extend(page_issues)

print("\nTOTAL NAVIGATION ISSUES: %d" % len(issues))
sys.exit(1 if issues else 0)
