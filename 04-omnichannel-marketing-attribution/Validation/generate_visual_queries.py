# -*- coding: utf-8 -*-
"""
Reconstructs, for every visual on every report page, the DAX query that visual
issues, so each can be executed against the live model by validate_visuals.ps1.

A visual is judged BLANK if its query returns no rows, or rows in which every
measure is null - exactly the condition that makes Power BI draw an empty chart.
(Carried over from project 1, where it found every blank visual.)

Usage:  python Validation/generate_visual_queries.py > queries.dax
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "PowerBI" / "OmnichannelAttribution.Report" / "definition" / "pages"


def title_of(v):
    t = (v.get("visual", {}).get("visualContainerObjects", {}) or {}).get("title")
    if isinstance(t, list) and t:
        lit = t[0].get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
        if lit:
            return lit.strip("'").replace("''", "'")
    return ""


def main():
    blocks = []
    for pdir in sorted(p for p in PAGES.iterdir() if p.is_dir()):
        page = json.loads((pdir / "page.json").read_text(encoding="utf-8-sig"))["displayName"]
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
            meta = f"{page} || {vj.parent.name[:8]} || {vis.get('visualType')} || {title_of(v)}"
            mp = ", ".join(f'"M{i}", [{m.replace("]", "]]")}]' for i, m in enumerate(measures))
            if not cols and not measures:
                blocks.append(f"// NOFIELDS {meta}\nEVALUATE ROW ( \"nofields\", 1 )")
            elif cols and measures:
                blocks.append(f"// {meta}\nEVALUATE TOPN ( 50, SUMMARIZECOLUMNS ( {', '.join(cols)}, {mp} ) )")
            elif cols:
                blocks.append(f"// {meta}\nEVALUATE TOPN ( 50, SUMMARIZECOLUMNS ( {', '.join(cols)} ) )")
            else:
                blocks.append(f"// {meta}\nEVALUATE ROW ( {mp} )")
    sys.stdout.write("\n---\n".join(blocks))


if __name__ == "__main__":
    main()
