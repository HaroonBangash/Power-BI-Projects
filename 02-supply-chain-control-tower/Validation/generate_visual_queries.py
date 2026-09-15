# -*- coding: utf-8 -*-
"""
Reconstruct, for every visual on a report page, the DAX query that visual issues,
so each one can be executed against the live model and judged rendered / blank.

A visual is judged BLANK if its query returns no rows, or returns rows in which
every measure column is null. That is exactly the condition that makes Power BI
draw an empty chart.
"""
import json, os, sys

from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
RPT = str(ROOT / "PowerBI" / "SupplyChainControlTower.Report" / "definition" / "pages")

GROUPING_ROLES = {"Category", "Rows", "Columns", "Series", "Axis", "Values", "Group",
                  "Details", "Legend", "Y2", "Column", "Row"}


def title_of(v):
    vco = v.get("visual", {}).get("visualContainerObjects", {}) or {}
    t = vco.get("title")
    if isinstance(t, list) and t:
        props = t[0].get("properties", {})
        txt = props.get("text", {})
        expr = txt.get("expr", {}) if isinstance(txt, dict) else {}
        lit = expr.get("Literal", {}).get("Value")
        if lit:
            return lit.strip("'")
    # textboxes carry their text in general.paragraphs
    o = v.get("visual", {}).get("objects", {}) or {}
    g = o.get("general")
    if isinstance(g, list) and g:
        paras = g[0].get("properties", {}).get("paragraphs", [])
        for p in paras:
            for tr in p.get("textRuns", []):
                if tr.get("value"):
                    return tr["value"][:60]
    return ""


def dax_escape_measure(name):
    return "[" + name.replace("]", "]]") + "]"


def col_ref(ent, prop):
    return "'%s'[%s]" % (ent, prop)


def build(page_dir):
    out = []
    pj = json.load(open(os.path.join(page_dir, "page.json"), encoding="utf-8-sig"))
    page_name = pj.get("displayName")
    vdir = os.path.join(page_dir, "visuals")
    for vd in sorted(os.listdir(vdir)):
        vj = os.path.join(vdir, vd, "visual.json")
        if not os.path.isfile(vj):
            continue
        v = json.load(open(vj, encoding="utf-8-sig"))
        vis = v.get("visual", {})
        vtype = vis.get("visualType", "?")
        title = title_of(v)
        cols, measures = [], []
        qs = vis.get("query", {}).get("queryState", {})
        for role, spec in qs.items():
            for p in spec.get("projections", []):
                f = p.get("field", {})
                if "Column" in f:
                    c = f["Column"]
                    ent = c.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    cols.append(col_ref(ent, c.get("Property")))
                elif "Measure" in f:
                    m = f["Measure"]
                    measures.append(m.get("Property"))
                elif "Aggregation" in f:
                    a = f["Aggregation"].get("Expression", {}).get("Column", {})
                    ent = a.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    cols.append(col_ref(ent, a.get("Property")))
        meta = "%s || %s || %s || %s" % (page_name, vd[:8], vtype, title)
        if not cols and not measures:
            out.append(("// NOFIELDS " + meta, None))
            continue
        if cols and measures:
            parts = ", ".join(cols)
            mp = ", ".join('"M%d", %s' % (i, dax_escape_measure(m)) for i, m in enumerate(measures))
            q = "EVALUATE TOPN ( 50, SUMMARIZECOLUMNS ( %s, %s ) )" % (parts, mp)
        elif cols:
            q = "EVALUATE TOPN ( 50, SUMMARIZECOLUMNS ( %s ) )" % ", ".join(cols)
        else:
            mp = ", ".join('"M%d", %s' % (i, dax_escape_measure(m)) for i, m in enumerate(measures))
            q = "EVALUATE ROW ( %s )" % mp
        out.append(("// " + meta, q))
    return out


if __name__ == "__main__":
    wanted = sys.argv[1:]
    blocks = []
    for d in sorted(os.listdir(RPT)):
        pd = os.path.join(RPT, d)
        if not os.path.isdir(pd):
            continue
        pj = json.load(open(os.path.join(pd, "page.json"), encoding="utf-8-sig"))
        nm = pj.get("displayName", "")
        if wanted and not any(w.lower() in nm.lower() for w in wanted):
            continue
        for label, q in build(pd):
            if q is None:
                blocks.append(label + "\nEVALUATE ROW ( \"nofields\", 1 )")
            else:
                blocks.append(label + "\n" + q)
    sys.stdout.write("\n---\n".join(blocks))
