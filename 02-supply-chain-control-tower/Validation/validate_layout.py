# -*- coding: utf-8 -*-
"""Layout / formatting QA for the report pages: canvas bounds, overlap, titles,
sort definitions on ranked charts, and Top-N filters."""
import json, os, sys, itertools

from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
RPT = str(ROOT / "PowerBI" / "SupplyChainControlTower.Report" / "definition" / "pages")
STATIC = {"textbox", "pageNavigator", "image", "shape", "actionButton"}


def title_of(v):
    vco = v.get("visual", {}).get("visualContainerObjects", {}) or {}
    t = vco.get("title")
    if isinstance(t, list) and t:
        lit = t[0].get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
        if lit:
            return lit.strip("'")
    return ""


def rects_overlap(a, b, tol=1.0):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = min(ax + aw, bx + bw) - max(ax, bx)
    iy = min(ay + ah, by + bh) - max(ay, by)
    if ix <= tol or iy <= tol:
        return 0.0
    return ix * iy


def run(page_filter):
    issues = 0
    for d in sorted(os.listdir(RPT)):
        pd = os.path.join(RPT, d)
        if not os.path.isdir(pd):
            continue
        pj = json.load(open(os.path.join(pd, "page.json"), encoding="utf-8-sig"))
        nm = pj.get("displayName", "")
        if page_filter and not any(w.lower() in nm.lower() for w in page_filter):
            continue
        pw = pj.get("width", 1280); ph = pj.get("height", 720)
        print("\n=== %s   canvas %sx%s ===" % (nm, pw, ph))
        vis = []
        vdir = os.path.join(pd, "visuals")
        for vd in sorted(os.listdir(vdir)):
            vj = os.path.join(vdir, vd, "visual.json")
            if not os.path.isfile(vj):
                continue
            v = json.load(open(vj, encoding="utf-8-sig"))
            p = v.get("position", {})
            vis.append({
                "id": vd[:8],
                "type": v.get("visual", {}).get("visualType"),
                "title": title_of(v),
                "rect": (p.get("x", 0), p.get("y", 0), p.get("width", 0), p.get("height", 0)),
                "sort": v.get("visual", {}).get("query", {}).get("sortDefinition", {}).get("sort", []),
                "filters": [f.get("type") for f in (v.get("filterConfig", {}) or {}).get("filters", [])],
                "tab": p.get("tabOrder"),
            })
        # bounds
        for v in vis:
            x, y, w, h = v["rect"]
            if x < 0 or y < 0 or x + w > pw + 0.5 or y + h > ph + 0.5:
                print("  OUT OF CANVAS: %s %-22s rect=%s" % (v["id"], v["type"], v["rect"])); issues += 1
        # overlap
        for a, b in itertools.combinations(vis, 2):
            if a["type"] in STATIC and b["type"] in STATIC:
                continue
            ov = rects_overlap(a["rect"], b["rect"])
            if ov > 0:
                amin = a["rect"][2] * a["rect"][3]; bmin = b["rect"][2] * b["rect"][3]
                pct = 100.0 * ov / max(1, min(amin, bmin))
                if pct > 2:
                    print("  OVERLAP %5.1f%%: %s(%s) %s  <->  %s(%s) %s"
                          % (pct, a["id"], a["type"], a["title"][:24], b["id"], b["type"], b["title"][:24]))
                    issues += 1
        # ranked charts should carry a sort definition
        for v in vis:
            t = (v["title"] or "").lower()
            ranked = any(k in t for k in ("top ", "least ", "worst", "highest", "lowest", "biggest"))
            if ranked and not v["sort"]:
                print("  RANKED CHART WITHOUT SORT: %s %s" % (v["id"], v["title"])); issues += 1
            if ranked and "VisualTopN" not in v["filters"]:
                print("  RANKED CHART WITHOUT TOP-N FILTER: %s %s" % (v["id"], v["title"])); issues += 1
        # titles
        for v in vis:
            if v["type"] in STATIC or v["type"] == "slicer":
                continue
            if not v["title"]:
                print("  MISSING TITLE: %s %s" % (v["id"], v["type"])); issues += 1
        # tab order duplicates
        tabs = [v["tab"] for v in vis if v["tab"] is not None]
        if len(tabs) != len(set(tabs)):
            print("  DUPLICATE tabOrder values"); issues += 1
        print("  %d visuals, %d issue(s) on this page" % (len(vis), issues))
    print("\nTOTAL LAYOUT ISSUES: %d" % issues)
    return issues


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1:]) == 0 else 0)
