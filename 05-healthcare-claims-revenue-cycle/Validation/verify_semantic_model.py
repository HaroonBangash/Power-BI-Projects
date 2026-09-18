# -*- coding: utf-8 -*-
"""
Static verification of the generated semantic model, BEFORE Power BI opens it.

Parses the TMDL files and checks them against the live SQL views, so a column
that would silently vanish or change type on refresh is caught here:

  files       CRLF, no BOM, tab indentation
  columns     every imported column exists in its SQL view with a compatible type,
              and every view column is imported
  refs        sortByColumn, hierarchy levels, relationship columns all resolve
  model       date table marked; relationships single direction, no fact-to-fact,
              at most one active path per table pair; implicit measures discouraged
  measures    every [ref] resolves; folder, format and description present;
              no reserved-word VAR names (they broke project 1's whole model)
  calc groups precedence unique, Name/Ordinal columns present, items in reporting order,
              and no calculation item references a measure (which could be applied
              twice)

Usage:  python Validation/verify_semantic_model.py [--server localhost\\SQLEXPRESS]
"""
import argparse
import re
import sys
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
DEF = ROOT / "PowerBI" / "HealthcareRCM.SemanticModel" / "definition"
DATABASE = "HealthcareRCMBI"
RESERVED = {"this", "visible", "order", "set", "value", "name", "current", "filter", "not", "and", "or",
            "case", "when", "then", "else", "end", "table", "column", "row", "all", "measure", "define",
            "evaluate", "return", "var", "true", "false", "blank", "date", "time", "year", "month", "day",
            "sign", "min", "max", "sum", "average", "count", "format", "left", "right", "mid",
            # found live in this project: VAR Group made the whole model script fail
            "group", "before", "after", "rank", "sample", "start", "end", "month", "week", "day"}
SQL_TO_TMDL = {"nvarchar": "string", "varchar": "string", "nchar": "string", "char": "string",
               "int": "int64", "smallint": "int64", "tinyint": "int64", "bigint": "int64",
               "decimal": "double", "numeric": "double", "float": "double", "real": "double",
               "date": "dateTime", "datetime2": "dateTime", "datetime": "dateTime", "bit": "boolean"}
FACTS = {"FactClaim", "FactClaimLine", "FactPayment", "FactDenial",
         "FactARSnapshot", "FactARMovement"}
# The dimensions that must reach EVERY fact directly. A filter never travels from one
# fact to another, so a dimension that reaches only the claim header would leave a
# "denials by specialty" or "line volume by payer" question filtering one table and
# not the other - a shrinking denominator against a full numerator. This is the single
# defect that took longest to find in the previous project in this series, so it is a
# test here rather than a comment.
CONFORMED = {"DimPayer", "DimFacility", "DimProvider", "DimPatient"}
# Text measures: a format string would mean nothing for them.
# The order each calculation group must present its items in. Power BI takes it from
# the order they are written in the TMDL, so it is worth stating once and checking.
CALC_ITEM_ORDER = {
    "Date Basis": ["Service date", "Submission date", "Adjudication date", "Resolution date"],
    "Time Comparison": ["Selected period", "Prior month", "Month over month", "Month over month %",
                        "Prior year", "Trailing 12 months"],
}
# Time Comparison must sit OUTSIDE Date Basis, so "prior month on submission date" means
# the month before, measured on submission - and not the other way round.
CALC_PRECEDENCE = {"Date Basis": 10, "Time Comparison": 20}
# Text measures: a format string would mean nothing for them.
NO_FORMAT_OK = {"Currency", "AR Carried At", "As-Of Label", "Strongest Signal Dimension",
                "Data Quality Value", "Signal Verdict", "AR Bucket Colour", "Movement Colour", "Signal Colour",
                "Chance Band Colour", "Payer Colour", "AR Headline", "Denial Headline",
                "Collection Headline", "Method Headline"}

results = []


def strip_isselectedmeasure(dax):
    """Remove every ISSELECTEDMEASURE ( ... ) call, matching parentheses properly:
    measure names such as [Other Expense (Net)] contain brackets of their own."""
    out, i = [], 0
    while True:
        j = dax.find("ISSELECTEDMEASURE", i)
        if j < 0:
            out.append(dax[i:])
            return "".join(out)
        out.append(dax[i:j])
        k = dax.find("(", j)
        if k < 0:
            return "".join(out)
        depth = 0
        while k < len(dax):
            if dax[k] == "(":
                depth += 1
            elif dax[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 1


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
        view = re.search(r"(?m)^\s+analytics_(vw_\w+) = Source\{", txt)
        measures = []
        pattern = (r"(?ms)^(?:\t/// (.*?)\n)?\tmeasure ('([^']+)'|\S+) =(.*?)"
                   r"(?=^\t\t(?:isHidden|formatString|displayFolder|lineageTag))(.*?)"
                   r"(?=^\t(?:measure|column|///|partition)|\Z)")
        for mm in re.finditer(pattern, txt):
            props = mm.group(5)
            measures.append({"name": mm.group(3) or mm.group(2), "desc": mm.group(1), "dax": mm.group(4),
                             "fmt": re.search(r"formatString: (.+)", props),
                             "folder": re.search(r"displayFolder: (.+)", props),
                             "hidden": "isHidden" in props})
        items = []
        # An item runs to the next item, the group's own columns, or the end of file.
        # There is no `ordinal:` to stop at: Power BI strips those on save, because the
        # order the items are WRITTEN in is the order the group presents them.
        item_pattern = (r"(?ms)^\t\tcalculationItem ('([^']+)'|\S+) ="
                        r"(.*?)(?=^\t\tcalculationItem |^\tcolumn |\Z)")
        for i, im in enumerate(re.finditer(item_pattern, txt)):
            items.append({"name": im.group(2) or im.group(1), "dax": im.group(3), "ordinal": i})
        levels = re.findall(r"(?m)^\t\t\tcolumn: ('([^']+)'|\S+)", txt)
        is_group = "\tcalculationGroup" in txt
        tables[tname] = {"file": f, "text": txt, "cols": cols, "view": view.group(1) if view else None,
                         "measures": measures, "items": items,
                         "precedence": int(re.search(r"precedence: (\d+)", txt).group(1)) if is_group else None,
                         "levels": [l[1] or l[0] for l in levels],
                         "is_date": "\tdataCategory: Time" in txt, "is_calc_group": is_group}
    return tables


def sql_columns(server):
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server") if d in drivers),
                  drivers[-1])
    cn = pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE={DATABASE};"
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
        check("Files", f"{f.relative_to(DEF)} CRLF, no BOM",
              b[:3] != b"\xef\xbb\xbf" and b.count(b"\n") == b.count(b"\r\n"))

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

    # ---------------------------------------------------------------- model ---
    rel_txt = (DEF / "relationships.tmdl").read_text(encoding="utf-8")
    rels = []
    for blk in re.split(r"(?m)^relationship ", rel_txt)[1:]:
        f = re.search(r"fromColumn: (\w+)\.(\w+)", blk).groups()
        to = re.search(r"toColumn: (\w+)\.(\w+)", blk).groups()
        rels.append((f, to, "isActive: false" not in blk, "crossFilteringBehavior" in blk))
    for (ft, fc), (tt, tc), active, bidi in rels:
        check("Model", f"{ft}.{fc} -> {tt}.{tc}: columns exist",
              fc in tables.get(ft, {}).get("cols", {}) and tc in tables.get(tt, {}).get("cols", {}))
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
    model_txt = (DEF / "model.tmdl").read_text(encoding="utf-8")
    check("Model", "implicit measures discouraged (required by calculation groups)",
          "discourageImplicitMeasures" in model_txt)
    for tn in tables:
        check("Model", f"{tn} referenced in model.tmdl",
              f"ref table {tn}" in model_txt or f"ref table '{tn}'" in model_txt)

    # ------------------------------------------------------------- measures ---
    ms = tables["_Measures"]["measures"]
    names = {x["name"] for x in ms}
    allcols = {c for t in tables.values() for c in t["cols"]}
    role_txt = "\n".join(p.read_text(encoding="utf-8") for p in (DEF / "roles").glob("*.tmdl"))
    ref_pattern = r"(?<![\w'\]])\[([^\]]+)\]"
    for x in ms:
        refs = set(re.findall(ref_pattern, x["dax"]))
        unresolved = [r for r in refs if r not in names and r not in allcols and not r.startswith("@")]
        check("Measures", f"[{x['name']}] references resolve", not unresolved, ", ".join(unresolved))
        check("Measures", f"[{x['name']}] has folder and description", x["folder"] and x["desc"])
        if not x["hidden"]:
            check("Measures", f"[{x['name']}] has a format string",
                  bool(x["fmt"]) or x["name"] in NO_FORMAT_OK)
        vars_ = [v for v in re.findall(r"\bVAR\s+(\w+)\s*=", x["dax"]) if v.lower() in RESERVED]
        check("Measures", f"[{x['name']}] no reserved-word VAR names", not vars_, ", ".join(vars_))
        # An odd number of double quotes means a string literal was left open. Such a
        # measure still parses as TMDL and still passes every other check here; it fails
        # only when the ENGINE evaluates it. The cause is mundane - a DAX expression that
        # ends in a quote, written inside a Python triple-quoted string, loses that quote
        # to the closing delimiter - and it cost a full model load to find once.
        check("Measures", f"[{x['name']}] double quotes are balanced",
              x["dax"].count(chr(34)) % 2 == 0, f"{x['dax'].count(chr(34))} quote(s)")

    # --------------------------------------------------------- calc groups ---
    groups = {tn: t for tn, t in tables.items() if t["is_calc_group"]}
    check("CalcGroups", "two calculation groups", len(groups) == 2, ", ".join(groups))
    for tn, want in CALC_PRECEDENCE.items():
        check("CalcGroups", f"{tn}: precedence {want}",
              tn in groups and groups[tn]["precedence"] == want,
              str(groups.get(tn, {}).get("precedence")))
    check("CalcGroups", "Time Comparison outranks Date Basis",
          groups.get("Time Comparison", {}).get("precedence", 0)
          > groups.get("Date Basis", {}).get("precedence", 99))
    check("CalcGroups", "precedences are distinct",
          len({t["precedence"] for t in groups.values()}) == len(groups),
          str({tn: t["precedence"] for tn, t in groups.items()}))
    for tn, t in groups.items():
        check("CalcGroups", f"{tn}: Name and Ordinal columns present",
              "Ordinal" in t["cols"] and "sourceColumn: Name" in t["text"])
        # The reporting order is the written order, so this checks the written order
        # is the one the report expects - a reordered item would silently reorder a
        # slicer and every matrix column that follows it.
        check("CalcGroups", f"{tn}: items in reporting order",
              [i["name"] for i in t["items"]] == CALC_ITEM_ORDER[tn],
              str([i["name"] for i in t["items"]]))
        check("CalcGroups", f"{tn}: has items", len(t["items"]) > 0)
        for item in t["items"]:
            # ISSELECTEDMEASURE takes measure references as arguments without
            # evaluating them, so they carry no recursion risk.
            evaluated = strip_isselectedmeasure(item["dax"])
            refs = set(re.findall(ref_pattern, item["dax"]))
            measure_refs = [r for r in set(re.findall(ref_pattern, evaluated)) if r in names]
            check("CalcGroups", f"{tn}/{item['name']}: references no measure (it could be applied twice)",
                  not measure_refs, ", ".join(measure_refs))
            unresolved = [r for r in refs if r not in names and r not in allcols and not r.startswith("@")]
            check("CalcGroups", f"{tn}/{item['name']}: column references resolve", not unresolved, ", ".join(unresolved))
        check("CalcGroups", f"{tn}: no partition (a calculation group has none)", "\tpartition" not in t["text"])

    # ------------------------------------------------------------- security ---
    role_vars = [v for v in re.findall(r"VAR\s+(\w+)\s*=", role_txt) if v.lower() in RESERVED]
    check("Security", "RLS role has no reserved-word VAR names", not role_vars, ", ".join(role_vars))
    # Security is by FACILITY, and because every provider bills only at their own
    # facility, provider and facility are one hierarchy - so both dimensions are
    # filtered. Filtering only the facility would leave 500 provider names visible in a
    # slicer with nothing behind them.
    for tbl in ("DimFacility", "DimProvider", "ProviderChance", "SecurityUserAccess"):
        check("Security", f"RLS filters {tbl}", f"tablePermission {tbl}" in role_txt)
    check("Security", "RLS reads the user from USERPRINCIPALNAME", role_txt.count("USERPRINCIPALNAME") >= 4)
    check("Security", "RLS honours the ALL scope", '"ALL" IN UserFacilities' in role_txt)
    check("Security", "the patient dimension is deliberately NOT filtered",
          "tablePermission DimPatient" not in role_txt)
    # Every fact must reach the secured dimension directly, or a scoped user could read
    # around the filter through a fact that has no path to it.
    unsecured = sorted(f for f in FACTS
                       if not any(fr[0] == f and to[0] == "DimFacility" for fr, to, _, _ in rels))
    check("Security", "every fact reaches DimFacility", not unsecured, ", ".join(unsecured))

    # ------------------------------------------------------ conformed dimensions ---
    for dim in sorted(CONFORMED):
        missing = sorted(f for f in FACTS
                         if not any(fr[0] == f and to[0] == dim for fr, to, _, _ in rels))
        check("Conformed", f"{dim} reaches every fact directly", not missing, ", ".join(missing))

    # ------------------------------------------------------ field parameters ---
    # A field parameter is a calculated table whose middle column carries a
    # ParameterMetadata extended property. Without it the column is ordinary text
    # and the slicer silently stops switching anything, with no error anywhere.
    for f in sorted(DEF.glob("tables/*.tmdl")):
        txt = f.read_text(encoding="utf-8")
        if "NAMEOF(" not in txt:
            continue
        fname = f.stem
        check("FieldParam", f"{fname}: is a calculated table", "= calculated" in txt)
        check("FieldParam", f"{fname}: carries ParameterMetadata", "extendedProperty ParameterMetadata" in txt)
        check("FieldParam", f"{fname}: sorts by its order column", "sortByColumn" in txt)
        fields = re.findall(r"NAMEOF\('([^']+)'\[([^\]]+)\]\)", txt)
        check("FieldParam", f"{fname}: has fields", len(fields) >= 2, str(len(fields)))
        for tname, cname in fields:
            check("FieldParam", f"{fname}: {tname}[{cname}] exists",
                  tname in tables and cname in tables[tname]["cols"])

    # --------------------------------------------------------------- report ---
    fails = [r for r in results if not r[2]]
    areas = {}
    for a, _, ok, _ in results:
        areas.setdefault(a, [0, 0])
        areas[a][0 if ok else 1] += 1
    for a, (p, f) in areas.items():
        print(f"  {a:11s} {p:4d} passed  {f:3d} failed")
    for a, n, _, d in fails:
        print(f"  FAIL [{a}] {n}  {d}")
    print(f"\nRESULT: {len(results) - len(fails)} of {len(results)} checks passed "
          f"({len(tables)} tables, {sum(len(t['cols']) for t in tables.values())} columns, "
          f"{len(rels)} relationships, {len(ms)} measures, "
          f"{sum(len(t['items']) for t in groups.values())} calculation items)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
