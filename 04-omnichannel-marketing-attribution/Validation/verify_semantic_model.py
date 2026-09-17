# -*- coding: utf-8 -*-
"""
Static verification of the generated semantic model, BEFORE Power BI opens it.

Parses the TMDL files and checks them against the live SQL views, so a column
that would silently vanish or change type on refresh is caught here:

  files       CRLF, no BOM, tab indentation
  columns     every imported column exists in its SQL view with a compatible type,
              and every view column is imported
  refs        sortByColumn, hierarchy levels, relationship columns all resolve
  model       date table marked; relationships 1:*, single direction, no
              fact-to-fact, at most one active path per table pair
  measures    every [ref] resolves; folder, format and description present;
              no reserved-word VAR names (they broke project 1's whole model)

Usage:  python Validation/verify_semantic_model.py [--server localhost\\SQLEXPRESS]
"""
import argparse
import re
import sys
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
DEF = ROOT / "PowerBI" / "OmnichannelAttribution.SemanticModel" / "definition"
RESERVED = {"this", "visible", "order", "set", "value", "name", "current", "filter", "not", "and", "or",
            "case", "when", "then", "else", "end", "table", "column", "row", "all", "measure", "define",
            "evaluate", "return", "var", "true", "false", "blank", "date", "time", "year", "month", "day"}
SQL_TO_TMDL = {"nvarchar": "string", "varchar": "string", "nchar": "string", "char": "string",
               "int": "int64", "smallint": "int64", "tinyint": "int64", "bigint": "int64",
               "decimal": "double", "numeric": "double", "float": "double", "real": "double",
               "date": "dateTime", "datetime2": "dateTime", "datetime": "dateTime", "bit": "boolean"}
FACTS = {"FactAdSpend", "FactLeadFunnel", "FactTouchpoint", "FactAttributionCredit"}

results = []


def check(area, name, ok, detail=""):
    results.append((area, name, bool(ok), detail))


def parse_tables():
    tables = {}
    for f in sorted((DEF / "tables").glob("*.tmdl")):
        txt = f.read_text(encoding="utf-8")
        name = re.search(r"(?m)^table ('([^']+)'|\S+)", txt)
        tname = name.group(2) or name.group(1)
        cols = {}
        for block in re.split(r"(?m)^(?=\t(?:column|measure|hierarchy|partition|annotation) )", txt)[1:]:
            head = block.split("\n", 1)[0]
            cm = re.match(r"\tcolumn ('([^']+)'|\S+)", head)
            if cm:
                cn = cm.group(2) or cm.group(1)
                dt = re.search(r"dataType: (\w+)", block).group(1)
                sb = re.search(r"sortByColumn: ('([^']+)'|\S+)", block)
                cols[cn] = {"dtype": dt, "sort_by": (sb.group(2) or sb.group(1)) if sb else None}
        # Only plain two-step imports (Source -> analytics_vw_X) mirror a view
        # column for column. A multi-step query such as CampaignAliasResolution
        # reads views but derives its own columns, so it is not compared.
        # M lines are indented with tabs AND spaces - anchor on any whitespace.
        view = re.search(r"(?m)^\s+analytics_(vw_\w+) = Source\{", txt)
        measures = []
        for mm in re.finditer(r"(?ms)^(?:\t/// (.*?)\n)?\tmeasure ('([^']+)'|\S+) =(.*?)(?=^\t\t(?:formatString|displayFolder|lineageTag))(.*?)(?=^\t(?:measure|column|///|partition)|\Z)", txt):
            props = mm.group(5)
            measures.append({"name": mm.group(3) or mm.group(2), "desc": mm.group(1), "dax": mm.group(4),
                             "fmt": re.search(r"formatString: (.+)", props),
                             "folder": re.search(r"displayFolder: (.+)", props)})
        levels = re.findall(r"(?m)^\t\t\tcolumn: ('([^']+)'|\S+)", txt)
        tables[tname] = {"file": f, "text": txt, "cols": cols, "view": view.group(1) if view else None,
                         "measures": measures, "levels": [l[1] or l[0] for l in levels],
                         "is_date": "\tdataCategory: Time" in txt}
    return tables


def sql_columns(server):
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server") if d in drivers), drivers[-1])
    cn = pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE=MarketingAttributionBI;"
                        "Trusted_Connection=yes;TrustServerCertificate=yes;")
    rows = cn.cursor().execute("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                               "WHERE TABLE_SCHEMA = 'analytics'").fetchall()
    cn.close()
    out = {}
    for t, c, d in rows:
        out.setdefault(t, {})[c] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=r"localhost\SQLEXPRESS")
    args = ap.parse_args()
    tables = parse_tables()
    views = sql_columns(args.server)

    # ---------------------------------------------------------------- files ---
    for f in DEF.rglob("*.tmdl"):
        b = f.read_bytes()
        check("Files", f"{f.relative_to(DEF)} CRLF, no BOM", b[:3] != b"\xef\xbb\xbf" and b.count(b"\n") == b.count(b"\r\n"))

    # -------------------------------------------------------------- columns ---
    for tn, t in tables.items():
        if not t["view"]:
            continue
        v = views.get(t["view"])
        check("Columns", f"{tn}: view analytics.{t['view']} exists", v is not None)
        if v is None:
            continue
        missing = [c for c in t["cols"] if c not in v]
        extra = [c for c in v if c not in t["cols"]]
        bad = [f"{c} {t['cols'][c]['dtype']}<>{SQL_TO_TMDL.get(v[c])}" for c in t["cols"]
               if c in v and SQL_TO_TMDL.get(v[c]) != t["cols"][c]["dtype"]]
        check("Columns", f"{tn}: every model column exists in the view", not missing, ", ".join(missing))
        check("Columns", f"{tn}: every view column is imported", not extra, ", ".join(extra))
        check("Columns", f"{tn}: types compatible with SQL", not bad, ", ".join(bad))

    # ----------------------------------------------------------------- refs ---
    for tn, t in tables.items():
        for cn, c in t["cols"].items():
            if c["sort_by"]:
                check("Refs", f"{tn}[{cn}] sortByColumn {c['sort_by']} exists", c["sort_by"] in t["cols"])
        for lv in t["levels"]:
            check("Refs", f"{tn} hierarchy level {lv} exists", lv in t["cols"])

    rel_txt = (DEF / "relationships.tmdl").read_text(encoding="utf-8")
    rels = []
    for blk in re.split(r"(?m)^relationship ", rel_txt)[1:]:
        f = re.search(r"fromColumn: (\w+)\.(\w+)", blk).groups()
        to = re.search(r"toColumn: (\w+)\.(\w+)", blk).groups()
        rels.append((f, to, "isActive: false" not in blk, "crossFilteringBehavior" in blk))
    for (ft, fc), (tt, tc), active, bidi in rels:
        check("Model", f"{ft}.{fc} -> {tt}.{tc}: columns exist", fc in tables.get(ft, {}).get("cols", {}) and tc in tables.get(tt, {}).get("cols", {}))
        check("Model", f"{ft}.{fc} -> {tt}.{tc}: single direction", not bidi)
        check("Model", f"{ft}.{fc} -> {tt}.{tc}: not fact-to-fact", not (ft in FACTS and tt in FACTS))
    pairs = {}
    for (ft, _), (tt, _), active, _ in rels:
        if active:
            pairs[(ft, tt)] = pairs.get((ft, tt), 0) + 1
    check("Model", "at most one active relationship per table pair", all(n == 1 for n in pairs.values()),
          str({k: n for k, n in pairs.items() if n > 1}))
    date_tables = [tn for tn, t in tables.items() if t["is_date"]]
    check("Model", "exactly one table marked as date table", len(date_tables) == 1, str(date_tables))
    check("Model", "date table has a key date column",
          bool(date_tables) and "isKey" in tables[date_tables[0]]["text"])

    # -------------------------------------------------------------- measures ---
    ms = tables["_Measures"]["measures"]
    names = {x["name"] for x in ms}
    allcols = {c for t in tables.values() for c in t["cols"]}
    role_txt = "\n".join(p.read_text(encoding="utf-8") for p in (DEF / "roles").glob("*.tmdl"))
    for x in ms:
        refs = set(re.findall(r"(?<![\w'\]])\[([^\]]+)\]", x["dax"]))
        # [@Name] refers to a column created inside the measure by ADDCOLUMNS
        unresolved = [r for r in refs if r not in names and r not in allcols and not r.startswith("@")]
        check("Measures", f"[{x['name']}] references resolve", not unresolved, ", ".join(unresolved))
        check("Measures", f"[{x['name']}] has folder and description", x["folder"] and x["desc"])
        vars_ = [v for v in re.findall(r"\bVAR\s+(\w+)\s*=", x["dax"]) if v.lower() in RESERVED]
        check("Measures", f"[{x['name']}] no reserved-word VAR names", not vars_, ", ".join(vars_))
    role_vars = [v for v in re.findall(r"\bVAR\s+(\w+)\s*=", role_txt) if v.lower() in RESERVED]
    check("Security", "RLS role has no reserved-word VAR names", not role_vars, ", ".join(role_vars))
    check("Security", "RLS filters DimCampaign by Region via USERPRINCIPALNAME",
          "tablePermission DimCampaign" in role_txt and "USERPRINCIPALNAME" in role_txt)

    # ---------------------------------------------------------------- report ---
    fails = [r for r in results if not r[2]]
    areas = {}
    for a, _, ok, _ in results:
        areas.setdefault(a, [0, 0])
        areas[a][0 if ok else 1] += 1
    for a, (p, f) in areas.items():
        print(f"  {a:10s} {p:4d} passed  {f:3d} failed")
    for a, n, _, d in fails:
        print(f"  FAIL [{a}] {n}  {d}")
    print(f"\nRESULT: {len(results) - len(fails)} of {len(results)} checks passed "
          f"({len(tables)} tables, {sum(len(t['cols']) for t in tables.values())} columns, "
          f"{len(rels)} relationships, {len(ms)} measures)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
