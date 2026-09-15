"""
02_verify_semantic_model.py
===========================
Phase 4 sign-off verification for the Supply Chain Control Tower.

Compares the PBIP semantic model (TMDL on disk) against the SQL analytical
views it consumes, and asserts the Phase 4 design constraints.

Checks
------
    1. Table inventory          Exactly the 11 approved tables, no strays
    2. Source binding           Every partition reads only analytics.vw_*
    3. Query thinness           No Power Query steps beyond Source + Navigation
    4. Column parity            Model columns match the view, name for name
    5. Data types               Model type matches the SQL type under the
                                documented mapping policy
    6. Relationships            None (Phase 5 designs them deliberately)
    7. Parameters               RangeStart / RangeEnd present, DateTime typed,
                                correct development values, and NOT yet applied
                                as a filter to any table
    8. Auto date/time           Disabled, with no LocalDateTable_* remaining

Read-only. Modifies nothing.

Usage
-----
    python Python/02_verify_semantic_model.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pyodbc

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
DEFN = ROOT / "PowerBI" / "SupplyChainControlTower.SemanticModel" / "definition"

CONN = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=localhost\\SQLEXPRESS;DATABASE=SupplyChainBI;"
    "Trusted_Connection=yes;TrustServerCertificate=yes;"
)

# Model table -> the analytics view it must read from.
EXPECTED_TABLES = {
    "DimDate": "vw_DimDate",
    "DimProduct": "vw_DimProduct",
    "DimSupplier": "vw_DimSupplier",
    "DimWarehouse": "vw_DimWarehouse",
    "FactSalesOrders": "vw_SalesOrders",
    "FactPurchaseOrders": "vw_PurchaseOrders",
    "FactShipments": "vw_Shipments",
    "FactWeeklyDemand": "vw_WeeklyDemand",
    "FactInventorySnapshot": "vw_InventorySnapshot",
    "SecurityUserAccess": "vw_SecurityUserAccess",
    "ModelConfig": "vw_ModelConfig",
}

# Base SQL -> TMDL type mapping.
TYPE_MAP = {
    "date": "dateTime",
    "int": "int64",
    "smallint": "int64",
    "tinyint": "int64",
    "bit": "boolean",
    "varchar": "string",
    "nvarchar": "string",
    "decimal": "decimal",   # currency: exact arithmetic, no float drift
}

# Documented deviations from the base mapping, with the reason each exists.
#
# The money columns are the interesting case. They were set to `decimal`
# (Fixed Decimal) in TMDL and Power BI reverted every one of them to `double`
# on the next refresh: the engine reconciles a model column's type to whatever
# the M query returns, and a TMDL-only change has no anchor in M. Making it
# durable would require a Table.TransformColumnTypes cast in Power Query.
#
# That cast is deliberately NOT added, for two reasons:
#
#   1. It is not established that a Currency cast folds against this source.
#      An unverified folding risk ahead of the Phase 21 incremental refresh
#      design is a real cost.
#   2. There is no precision benefit to buy with it. Values here reach at most
#      ~184,297 with two decimals - about seven significant digits - while a
#      double carries fifteen to seventeen. Exact precision is held where the
#      data actually lives: the SQL layer types these decimal(18,2).
#
# Revisit in Phase 21, where folding is measured empirically anyway.
MONEY_NOTE = (
    "Power BI reconciles column type to the M output on refresh; Fixed Decimal "
    "does not persist without an M cast. Accepted - see PROJECT_STATE.md D18."
)
TYPE_EXCEPTIONS = {
    ("FactPurchaseOrders", "DefectRate"): (
        "double",
        "Rate, not currency. Fixed Decimal caps at 4 dp and is designed for "
        "money; a proportion that will be averaged belongs in a floating type.",
    ),
    ("DimProduct", "UnitCost"): ("double", MONEY_NOTE),
    ("DimProduct", "UnitPrice"): ("double", MONEY_NOTE),
    ("FactSalesOrders", "Revenue"): ("double", MONEY_NOTE),
    ("FactPurchaseOrders", "POValue"): ("double", MONEY_NOTE),
    ("FactPurchaseOrders", "ExpectedPOValue"): ("double", MONEY_NOTE),
    ("FactPurchaseOrders", "PurchasePriceVariance"): ("double", MONEY_NOTE),
    ("FactShipments", "FreightCost"): ("double", MONEY_NOTE),
}

RANGE_PARAMS = {
    "RangeStart": "#datetime(2026, 1, 1, 0, 0, 0)",
    "RangeEnd": "#datetime(2026, 9, 1, 0, 0, 0)",
}

# --------------------------------------------------------------------------- #
# Results register
# --------------------------------------------------------------------------- #

results: list[tuple[str, str, str, str, str]] = []


def check(section: str, name: str, expected: str, actual: str) -> None:
    status = "PASS" if str(expected) == str(actual) else "FAIL"
    results.append((section, name, str(expected), str(actual), status))


# --------------------------------------------------------------------------- #
# TMDL parsing
# --------------------------------------------------------------------------- #


def parse_table(path: Path) -> dict:
    """Extract table name, columns, partition source and M steps from a TMDL file."""
    txt = path.read_text(encoding="utf-8")

    name = re.search(r"^table\s+(\S+)", txt, re.M).group(1).strip("'")

    columns: dict[str, dict] = {}
    for block in re.split(r"\n\tcolumn ", txt)[1:]:
        col = block.split("\n")[0].strip().strip("'")
        columns[col] = {
            "dataType": (re.search(r"dataType: (\w+)", block) or [None, "?"])[1],
            "summarizeBy": (re.search(r"summarizeBy: (\w+)", block) or [None, "?"])[1],
        }

    # The M expression sits inside the partition block.
    m = re.search(r"partition (\S+) = m\n\t\tmode: (\w+)\n\t\tsource =\n(.*?)(?=\n\tannotation|\Z)",
                  txt, re.S)
    partition_name, mode, source = (m.group(1), m.group(2), m.group(3)) if m else ("?", "?", "")

    view = re.search(r'Item="(vw_[A-Za-z]+)"', source)
    # A `let ... in` query's steps are its assignments; anything past Source and
    # the navigation step is a transformation that could break folding.
    steps = re.findall(r"^\s{4,}(\w+)\s*=", source, re.M)

    return {
        "name": name,
        "columns": columns,
        "partition": partition_name,
        "mode": mode,
        "view": view.group(1) if view else None,
        "steps": steps,
        "source": source,
    }


def sql_columns(cur, view: str) -> dict[str, str]:
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM   INFORMATION_SCHEMA.COLUMNS
        WHERE  TABLE_SCHEMA = 'analytics' AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        view,
    )
    return {r[0]: r[1] for r in cur.fetchall()}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    if not DEFN.exists():
        print(f"Semantic model not found: {DEFN}", file=sys.stderr)
        return 1

    tables = {}
    for p in sorted((DEFN / "tables").glob("*.tmdl")):
        t = parse_table(p)
        tables[t["name"]] = t

    # ---- 1. Table inventory ------------------------------------------------
    check("Inventory", "Table count", 11, len(tables))
    strays = sorted(set(tables) - set(EXPECTED_TABLES))
    missing = sorted(set(EXPECTED_TABLES) - set(tables))
    check("Inventory", "Unexpected tables", "none", ", ".join(strays) or "none")
    check("Inventory", "Missing tables", "none", ", ".join(missing) or "none")
    autodate = [t for t in tables if t.startswith(("LocalDateTable_", "DateTableTemplate_"))]
    check("Inventory", "Auto date/time tables", 0, len(autodate))

    model_txt = (DEFN / "model.tmdl").read_text(encoding="utf-8")
    ti = re.search(r"__PBI_TimeIntelligenceEnabled = (\d)", model_txt)
    check("Inventory", "__PBI_TimeIntelligenceEnabled", "0", ti.group(1) if ti else "absent")

    # ---- 2/3. Source binding and query thinness ----------------------------
    for name, view in EXPECTED_TABLES.items():
        if name not in tables:
            continue
        t = tables[name]
        check("Source binding", f"{name} reads", view, t["view"] or "NOT FOUND")
        check("Source binding", f"{name} mode", "import", t["mode"])
        check("Source binding", f"{name} partition name", name, t["partition"])
        # Exactly two steps: Sql.Database source, then the view navigation.
        check("Query thinness", f"{name} M steps", 2, len(t["steps"]))
        # No RangeStart/RangeEnd filter should be applied yet.
        applied = "yes" if ("RangeStart" in t["source"] or "RangeEnd" in t["source"]) else "no"
        check("Query thinness", f"{name} range filter applied", "no", applied)

    # ---- 4/5. Column parity and data types ---------------------------------
    with pyodbc.connect(CONN, timeout=15) as cn:
        cur = cn.cursor()
        for name, view in EXPECTED_TABLES.items():
            if name not in tables:
                continue
            model_cols = tables[name]["columns"]
            src_cols = sql_columns(cur, view)

            check("Column parity", f"{name} column count", len(src_cols), len(model_cols))
            only_model = sorted(set(model_cols) - set(src_cols))
            only_sql = sorted(set(src_cols) - set(model_cols))
            check("Column parity", f"{name} model-only columns", "none",
                  ", ".join(only_model) or "none")
            check("Column parity", f"{name} source-only columns", "none",
                  ", ".join(only_sql) or "none")

            for col, sql_type in src_cols.items():
                if col not in model_cols:
                    continue
                override = TYPE_EXCEPTIONS.get((name, col))
                expected = override[0] if override else TYPE_MAP.get(sql_type, "?")
                check("Data types", f"{name}.{col} ({sql_type})",
                      expected, model_cols[col]["dataType"])

    # ---- 6. Relationships --------------------------------------------------
    rel_file = DEFN / "relationships.tmdl"
    rel_count = len(re.findall(r"^relationship ", rel_file.read_text(encoding="utf-8"), re.M)) \
        if rel_file.exists() else 0
    check("Relationships", "Relationship count", 0, rel_count)

    # ---- 7. Parameters -----------------------------------------------------
    expr_file = DEFN / "expressions.tmdl"
    if not expr_file.exists():
        check("Parameters", "expressions.tmdl", "present", "MISSING")
    else:
        expr_txt = expr_file.read_text(encoding="utf-8")
        for pname, pvalue in RANGE_PARAMS.items():
            m = re.search(rf"^expression {pname} = (.+)$", expr_txt, re.M)
            body = m.group(1) if m else ""
            check("Parameters", f"{pname} value", pvalue,
                  body.split(" meta")[0] if body else "MISSING")
            check("Parameters", f"{pname} is DateTime parameter", "yes",
                  "yes" if 'IsParameterQuery=true' in body and 'Type="DateTime"' in body else "no")

    # ---- Output ------------------------------------------------------------
    width = max(len(r[1]) for r in results) + 2
    current = None
    for section, name, expected, actual, status in results:
        if section != current:
            print(f"\n--- {section} " + "-" * (72 - len(section)))
            current = section
        flag = " " if status == "PASS" else ">"
        print(f"{flag} {name:<{width}} {status:<5} expected={expected:<24} actual={actual}")

    passed = sum(1 for r in results if r[4] == "PASS")
    failed = sum(1 for r in results if r[4] == "FAIL")
    print("\n" + "=" * 78)
    print(f"  TOTAL {len(results)}   PASSED {passed}   FAILED {failed}")
    print(f"  PHASE 4 MODEL VERIFICATION: {'PASS' if failed == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
