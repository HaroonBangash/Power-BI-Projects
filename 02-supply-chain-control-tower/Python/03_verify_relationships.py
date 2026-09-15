"""
03_verify_relationships.py
==========================
Phase 5 sign-off verification for the Supply Chain Control Tower.

Parses the PBIP TMDL semantic model and asserts the star-schema design
constraints, then prints the relationship register.

Checks
------
    1. Relationship count, active/inactive split
    2. Cardinality is many-to-one on every relationship
    3. Cross-filter direction is single on every relationship
    4. No fact-to-fact relationship
    5. No ambiguous paths - at most one ACTIVE relationship per table pair
    6. Every relationship resolves to a column that exists
    7. DimDate is marked as the date table
    8. Sort-by columns are configured
    9. Hierarchies exist
   10. Technical columns are hidden
   11. No measures yet (Phase 6)

A note on parsing: TMDL omits properties that sit at their default, so an
absent `fromCardinality` means `many`, an absent `crossFilteringBehavior` means
`oneDirection`, and an absent `isActive` means active. This script treats
absence as the default rather than as missing data.

Read-only. Modifies nothing.

Usage
-----
    python Python/03_verify_relationships.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFN = ROOT / "PowerBI" / "SupplyChainControlTower.SemanticModel" / "definition"

DIMENSIONS = {"DimDate", "DimProduct", "DimSupplier", "DimWarehouse"}
FACTS = {
    "FactSalesOrders",
    "FactPurchaseOrders",
    "FactShipments",
    "FactWeeklyDemand",
    "FactInventorySnapshot",
}
DISCONNECTED = {"ModelConfig", "SecurityUserAccess"}

EXPECTED_SORT_BY = {
    ("DimDate", "MonthName"): "MonthNumber",
    ("DimDate", "MonthShortName"): "MonthNumber",
    ("DimDate", "DayName"): "DayOfWeekISO",
    ("DimDate", "DayShortName"): "DayOfWeekISO",
    ("DimDate", "YearMonthLabel"): "YearMonthKey",
    ("DimDate", "YearQuarterLabel"): "YearQuarterKey",
    ("DimDate", "ISOYearWeekLabel"): "ISOYearWeekKey",
    ("DimDate", "QuarterLabel"): "Quarter",
    ("DimDate", "FinancialYear"): "FinancialYearNumber",
}

EXPECTED_HIERARCHIES = {
    ("DimDate", "Calendar"),
    ("DimDate", "Financial Calendar"),
    ("DimProduct", "Product"),
    ("DimWarehouse", "Geography"),
}

results: list[tuple[str, str, str, str, str]] = []


def check(section: str, name: str, expected, actual) -> None:
    results.append(
        (section, name, str(expected), str(actual),
         "PASS" if str(expected) == str(actual) else "FAIL")
    )


def role(table: str) -> str:
    if table in DIMENSIONS:
        return "dim"
    if table in FACTS:
        return "fact"
    return "other"


def parse_relationships() -> list[dict]:
    path = DEFN / "relationships.tmdl"
    if not path.exists():
        return []
    rels = []
    # Anchor to line start: splitting on "\nrelationship " silently drops the
    # first block, which has no preceding newline.
    for block in re.split(r"^relationship ", path.read_text(encoding="utf-8"),
                          flags=re.M)[1:]:
        frm = re.search(r"fromColumn: (\S+)\.(\S+)", block)
        to = re.search(r"toColumn: (\S+)\.(\S+)", block)
        if not (frm and to):
            continue
        rels.append({
            "id": block.split("\n")[0].strip(),
            "from_table": frm.group(1), "from_col": frm.group(2),
            "to_table": to.group(1), "to_col": to.group(2),
            # Absent property == TMDL default.
            "active": "isActive: false" not in block,
            "from_card": (re.search(r"fromCardinality: (\w+)", block) or [None, "many"])[1],
            "to_card": (re.search(r"toCardinality: (\w+)", block) or [None, "one"])[1],
            "xfilter": (re.search(r"crossFilteringBehavior: (\w+)", block)
                        or [None, "oneDirection"])[1],
        })
    return rels


def parse_tables() -> dict[str, dict]:
    tables = {}
    for p in sorted((DEFN / "tables").glob("*.tmdl")):
        txt = p.read_text(encoding="utf-8")
        name = re.search(r"^table\s+(\S+)", txt, re.M).group(1).strip("'")
        cols = {}
        for b in re.split(r"\n\tcolumn ", txt)[1:]:
            col = b.split("\n")[0].strip().strip("'")
            sbc = re.search(r"sortByColumn: (\S+)", b)
            cols[col] = {
                "hidden": bool(re.search(r"^\t\tisHidden", b, re.M)),
                "sort_by": sbc.group(1) if sbc else None,
                "is_key": bool(re.search(r"^\t\tisKey", b, re.M)),
                "summarize_by": (re.search(r"summarizeBy: (\w+)", b) or [None, "?"])[1],
            }
        tables[name] = {
            "columns": cols,
            "data_category": (re.search(r"^\tdataCategory: (\w+)", txt, re.M) or [None, None])[1],
            # TMDL quotes object names containing spaces, so 'Financial
            # Calendar' arrives with its quotes attached.
            "hierarchies": [h.strip().strip("'")
                            for h in re.findall(r"^\thierarchy (.+)$", txt, re.M)],
            "measures": [m.strip().strip("'").split(" =")[0]
                         for m in re.findall(r"^\tmeasure (.+)$", txt, re.M)],
        }
    return tables


def main() -> int:
    if not DEFN.exists():
        print(f"Semantic model not found: {DEFN}", file=sys.stderr)
        return 1

    rels = parse_relationships()
    tables = parse_tables()

    active = [r for r in rels if r["active"]]
    inactive = [r for r in rels if not r["active"]]

    # ---- 1. Counts ---------------------------------------------------------
    check("Counts", "Total relationships", 24, len(rels))
    check("Counts", "Active", 16, len(active))
    check("Counts", "Inactive", 8, len(inactive))

    # ---- 2/3. Cardinality and direction ------------------------------------
    bad_card = [r for r in rels if r["from_card"] != "many" or r["to_card"] != "one"]
    check("Cardinality", "All many-to-one", 0, len(bad_card))
    bidi = [r for r in rels if r["xfilter"] != "oneDirection"]
    check("Cardinality", "Bidirectional relationships", 0, len(bidi))

    # ---- 4. No fact-to-fact ------------------------------------------------
    f2f = [r for r in rels if role(r["from_table"]) == "fact" and role(r["to_table"]) == "fact"]
    check("Star schema", "Fact-to-fact relationships", 0, len(f2f))
    d2d = [r for r in rels
           if role(r["from_table"]) == "dim" and role(r["to_table"]) == "dim"]
    check("Star schema", "Dimension-to-dimension (snowflake)", 0, len(d2d))
    conn_disc = [r for r in rels
                 if r["from_table"] in DISCONNECTED or r["to_table"] in DISCONNECTED]
    check("Star schema", "Disconnected tables still disconnected", 0, len(conn_disc))

    # ---- 5. Ambiguity ------------------------------------------------------
    # Two ACTIVE relationships between the same pair of tables would give the
    # engine two ways to propagate a filter.
    pairs = defaultdict(int)
    for r in active:
        pairs[(r["from_table"], r["to_table"])] += 1
    dupes = {k: v for k, v in pairs.items() if v > 1}
    check("Ambiguity", "Table pairs with >1 active relationship", 0, len(dupes))
    if dupes:
        for k, v in dupes.items():
            print(f"    AMBIGUOUS: {k[0]} -> {k[1]} has {v} active relationships")

    # ---- 6. Column resolution ----------------------------------------------
    unresolved = []
    for r in rels:
        for t, c in ((r["from_table"], r["from_col"]), (r["to_table"], r["to_col"])):
            if t not in tables or c not in tables[t]["columns"]:
                unresolved.append(f"{t}[{c}]")
    check("Integrity", "Unresolved relationship columns", 0, len(unresolved))
    if unresolved:
        print("    UNRESOLVED:", ", ".join(unresolved))

    # ---- 7. Date table -----------------------------------------------------
    check("Date table", "DimDate dataCategory", "Time", tables["DimDate"]["data_category"])
    check("Date table", "DimDate[Date] isKey", True, tables["DimDate"]["columns"]["Date"]["is_key"])
    # Every active fact date must point at DimDate[Date].
    date_rels = [r for r in rels if r["to_table"] == "DimDate"]
    check("Date table", "All date relationships target DimDate[Date]",
          0, len([r for r in date_rels if r["to_col"] != "Date"]))
    check("Date table", "Facts with an active date relationship", 5,
          len([r for r in active if r["to_table"] == "DimDate"]))

    # ---- 8. Sort-by --------------------------------------------------------
    bad_sort = []
    for (t, c), by in EXPECTED_SORT_BY.items():
        actual = tables.get(t, {}).get("columns", {}).get(c, {}).get("sort_by")
        if actual != by:
            bad_sort.append(f"{t}[{c}] -> {actual}")
    check("Sort-by", "Configured sort-by columns", 0, len(bad_sort))
    if bad_sort:
        print("    MISSING SORT-BY:", "; ".join(bad_sort))

    # ---- 9. Hierarchies ----------------------------------------------------
    found = {(t, h) for t, d in tables.items() for h in d["hierarchies"]}
    check("Hierarchies", "Expected hierarchies present", 0,
          len(EXPECTED_HIERARCHIES - found))
    check("Hierarchies", "Unexpected hierarchies", 0, len(found - EXPECTED_HIERARCHIES))

    # ---- 10. Hidden columns ------------------------------------------------
    # Every fact-side foreign key must be hidden: the dimension supplies the
    # attribute, and a visible duplicate invites report authors to slice on the
    # wrong one.
    fk_visible = []
    for f in FACTS:
        for c in ("ProductID", "WarehouseID", "SupplierID"):
            col = tables[f]["columns"].get(c)
            if col and not col["hidden"]:
                fk_visible.append(f"{f}[{c}]")
    check("Visibility", "Visible fact foreign keys", 0, len(fk_visible))
    if fk_visible:
        print("    STILL VISIBLE:", ", ".join(fk_visible))

    hidden_total = sum(1 for t in tables.values() for c in t["columns"].values() if c["hidden"])
    check("Visibility", "Total hidden columns", 23, hidden_total)

    # Degenerate transaction identifiers must stay visible for drill-through.
    for t, c in (("FactSalesOrders", "SalesOrderID"),
                 ("FactPurchaseOrders", "PurchaseOrderID"),
                 ("FactShipments", "ShipmentID")):
        check("Visibility", f"{t}[{c}] visible (degenerate key)",
              False, tables[t]["columns"][c]["hidden"])

    # ---- 11. No measures ---------------------------------------------------
    measures = sum(len(t["measures"]) for t in tables.values())
    check("Scope", "Measures defined", 0, measures)

    # ---- Register ----------------------------------------------------------
    print("\n" + "=" * 100)
    print("  RELATIONSHIP REGISTER")
    print("=" * 100)
    print(f"{'FROM (many)':<42}{'TO (one)':<26}{'CARD':<8}{'FILTER':<10}{'STATE'}")
    print("-" * 100)
    for r in sorted(rels, key=lambda x: (not x["active"], x["to_table"], x["from_table"])):
        frm = f"{r['from_table']}[{r['from_col']}]"
        to = f"{r['to_table']}[{r['to_col']}]"
        card = "*:1"
        state = "ACTIVE" if r["active"] else "inactive"
        print(f"{frm:<42}{to:<26}{card:<8}{'single':<10}{state}")

    # ---- Summary -----------------------------------------------------------
    width = max(len(r[1]) for r in results) + 2
    current = None
    print()
    for section, name, expected, actual, status in results:
        if section != current:
            print(f"\n--- {section} " + "-" * (70 - len(section)))
            current = section
        flag = " " if status == "PASS" else ">"
        print(f"{flag} {name:<{width}} {status:<5} expected={expected:<10} actual={actual}")

    passed = sum(1 for r in results if r[4] == "PASS")
    failed = sum(1 for r in results if r[4] == "FAIL")
    print("\n" + "=" * 78)
    print(f"  TOTAL {len(results)}   PASSED {passed}   FAILED {failed}")
    print(f"  PHASE 5 STRUCTURAL VERIFICATION: {'PASS' if failed == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
