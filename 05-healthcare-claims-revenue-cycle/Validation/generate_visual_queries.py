# -*- coding: utf-8 -*-
"""
Reconstructs, for every visual on every report page, the DAX query that visual
issues, so each can be executed against the live model by validate_visuals.ps1.

A visual is judged BLANK if its query returns no rows, or rows in which every
measure is null - exactly the condition that makes Power BI draw an empty chart.
(Carried over from projects 1 and 2, where it found every blank visual.)

PAGE AND VISUAL FILTERS ARE INCLUDED. Without them the reconstruction is not the
query the visual issues: the variance heatmap's z-score needs one month per cell,
which only the page's financial-year filter produces, and the check reported a
blank visual that in fact renders perfectly well.

Usage:  python Validation/generate_visual_queries.py > queries.dax
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "PowerBI" / "HealthcareRCM.Report" / "definition" / "pages"


def title_of(v):
    t = (v.get("visual", {}).get("visualContainerObjects", {}) or {}).get("title")
    if isinstance(t, list) and t:
        lit = t[0].get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
        if lit:
            return lit.strip("'").replace("''", "'")
    return ""


def dax_filters(filter_config):
    """Categorical filters as DAX predicates. A Top N filter needs none: the query
    already takes TOPN, and the check only asks whether data comes back."""
    out = []
    for f in (filter_config or {}).get("filters", []):
        if f.get("type") != "Categorical":
            continue
        col = f["field"]["Column"]
        table = col["Expression"]["SourceRef"]["Entity"]
        prop = col["Property"]
        values = []
        for cond in f.get("filter", {}).get("Where", []):
            for vals in cond.get("Condition", {}).get("In", {}).get("Values", []):
                for val in vals:
                    literal = val.get("Literal", {}).get("Value")
                    if literal is None:
                        continue
                    # PBIR quotes a string with SINGLE quotes; in DAX that is a table
                    # name, so it has to be re-quoted or every filter errors.
                    if len(literal) >= 2 and literal.startswith("'") and literal.endswith("'"):
                        inner = literal[1:-1].replace("''", "'").replace('"', '""')
                        literal = f'"{inner}"'
                    values.append(literal)
        if values:
            out.append(f"'{table}'[{prop}] IN {{{', '.join(values)}}}")
    return out


def main():
    blocks = []
    for pdir in sorted(p for p in PAGES.iterdir() if p.is_dir()):
        page = json.loads((pdir / "page.json").read_text(encoding="utf-8-sig"))
        page_filters = dax_filters(page.get("filterConfig"))
        for vj in sorted((pdir / "visuals").glob("*/visual.json")):
            v = json.loads(vj.read_text(encoding="utf-8-sig"))
            vis = v.get("visual", {})
            cols, measures = [], []
            for role, spec in vis.get("query", {}).get("queryState", {}).items():
                for p in spec.get("projections", []):
                    f = p.get("field", {})
                    if "Column" in f:
                        c = f["Column"]
                        cols.append(f"'{c['Expression']['SourceRef']['Entity']}'[{c['Property']}]")
                    elif "Measure" in f:
                        measures.append(f["Measure"]["Property"])
            cols = list(dict.fromkeys(cols))
            filters = page_filters + dax_filters(v.get("filterConfig"))
            meta = f"{page['displayName']} || {vj.parent.name[:8]} || {vis.get('visualType')} || {title_of(v)}"
            mp = ", ".join(f'"M{i}", [{m.replace("]", "]]")}]' for i, m in enumerate(measures))
            if not cols and not measures:
                blocks.append(f"// NOFIELDS {meta}\nEVALUATE ROW ( \"nofields\", 1 )")
                continue
            if cols and measures:
                body = f"TOPN ( 50, SUMMARIZECOLUMNS ( {', '.join(cols)}, {mp} ) )"
            elif cols:
                body = f"TOPN ( 50, SUMMARIZECOLUMNS ( {', '.join(cols)} ) )"
            else:
                body = f"ROW ( {mp} )"
            if filters:
                body = f"CALCULATETABLE ( {body}, {', '.join(filters)} )"
            blocks.append(f"// {meta}\nEVALUATE {body}")
    sys.stdout.write("\n---\n".join(blocks))


if __name__ == "__main__":
    main()
