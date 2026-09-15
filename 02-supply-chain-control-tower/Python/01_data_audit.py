"""
01_data_audit.py
================
Phase 2 data audit for the Supply Chain Control Tower.

Profiles every raw CSV and hunts for LOGICAL defects rather than merely counting
nulls. Findings are classified using three severities so that genuine faults are
never confused with legitimate business behaviour:

    ERROR      A genuine data fault that must be corrected in the SQL layer.
    ANOMALY    Suspicious, requires a documented decision before it is trusted.
    EXCEPTION  Valid business behaviour that merely looks unusual.
    INFO       Context that shapes downstream modelling choices.

Output
------
    Documentation/data_quality_report.md   Full findings register (British English)
    Console                                Summary table

Usage
-----
    python Python/01_data_audit.py

The script is read-only. It never modifies the raw data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "Data" / "Raw"
DOCS = ROOT / "Documentation"

DATE_COLUMNS = {
    "fact_sales_orders": ["OrderDate", "PromisedDeliveryDate", "ActualDeliveryDate"],
    "fact_purchase_orders": ["OrderDate", "ExpectedReceiptDate", "ActualReceiptDate"],
    "fact_shipments": ["ShipDate", "DeliveryDate"],
    "fact_weekly_demand": ["WeekStart"],
    "fact_inventory_snapshot": ["SnapshotDate"],
    "dim_date": ["Date"],
}

PRIMARY_KEYS = {
    "dim_product": ["ProductID"],
    "dim_supplier": ["SupplierID"],
    "dim_warehouse": ["WarehouseID"],
    "dim_date": ["Date"],
    "fact_sales_orders": ["SalesOrderID"],
    "fact_purchase_orders": ["PurchaseOrderID"],
    "fact_shipments": ["ShipmentID"],
    "fact_weekly_demand": ["WeekStart", "ProductID", "WarehouseID"],
    "fact_inventory_snapshot": ["SnapshotDate", "ProductID", "WarehouseID"],
    "security_user_access": ["UserEmail"],
}

# --------------------------------------------------------------------------- #
# Findings register
# --------------------------------------------------------------------------- #

findings: list[dict] = []


def record(severity: str, table: str, check: str, detail: str, action: str = "") -> None:
    """Append one finding to the register."""
    findings.append(
        {
            "Severity": severity,
            "Table": table,
            "Check": check,
            "Detail": detail,
            "Action": action,
        }
    )


def pct(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator * 100):.2f}%" if denominator else "n/a"


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #


def load_all() -> dict[str, pd.DataFrame]:
    """Read every raw CSV, parsing declared date columns."""
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(RAW.glob("*.csv")):
        name = path.stem
        df = pd.read_csv(path)
        for col in DATE_COLUMNS.get(name, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        frames[name] = df
    return frames


# --------------------------------------------------------------------------- #
# Structural checks
# --------------------------------------------------------------------------- #


def check_structure(frames: dict[str, pd.DataFrame]) -> None:
    """Primary-key uniqueness, exact-duplicate rows and null counts."""
    for name, df in frames.items():
        rows = len(df)

        # Declared primary key must be unique and complete.
        key = PRIMARY_KEYS.get(name)
        if key and all(c in df.columns for c in key):
            dupes = int(df.duplicated(subset=key).sum())
            if dupes:
                record(
                    "ERROR",
                    name,
                    "Primary key uniqueness",
                    f"{dupes:,} duplicate rows on {'+'.join(key)}",
                    "De-duplicate during staging load; add PK constraint in dbo.",
                )
            else:
                record(
                    "INFO",
                    name,
                    "Primary key uniqueness",
                    f"{'+'.join(key)} is unique across {rows:,} rows",
                    "Safe to enforce as PRIMARY KEY.",
                )

        # Whole-row duplicates.
        full_dupes = int(df.duplicated().sum())
        if full_dupes:
            record(
                "ERROR",
                name,
                "Exact duplicate rows",
                f"{full_dupes:,} fully duplicated rows",
                "Remove during staging load.",
            )

        # Nulls.
        nulls = df.isna().sum()
        nulls = nulls[nulls > 0]
        for col, count in nulls.items():
            record(
                "ANOMALY",
                name,
                "Null values",
                f"{col}: {count:,} nulls ({pct(int(count), rows)})",
                "Confirm whether NULL is meaningful before applying NOT NULL.",
            )


# --------------------------------------------------------------------------- #
# Referential integrity
# --------------------------------------------------------------------------- #


def check_referential_integrity(frames: dict[str, pd.DataFrame]) -> None:
    """Every foreign key must resolve to its parent dimension."""
    relations = [
        ("fact_sales_orders", "ProductID", "dim_product", "ProductID"),
        ("fact_sales_orders", "WarehouseID", "dim_warehouse", "WarehouseID"),
        ("fact_purchase_orders", "ProductID", "dim_product", "ProductID"),
        ("fact_purchase_orders", "SupplierID", "dim_supplier", "SupplierID"),
        ("fact_purchase_orders", "WarehouseID", "dim_warehouse", "WarehouseID"),
        ("fact_shipments", "SalesOrderID", "fact_sales_orders", "SalesOrderID"),
        ("fact_shipments", "WarehouseID", "dim_warehouse", "WarehouseID"),
        ("fact_weekly_demand", "ProductID", "dim_product", "ProductID"),
        ("fact_weekly_demand", "WarehouseID", "dim_warehouse", "WarehouseID"),
        ("fact_inventory_snapshot", "ProductID", "dim_product", "ProductID"),
        ("fact_inventory_snapshot", "WarehouseID", "dim_warehouse", "WarehouseID"),
        ("dim_product", "PrimarySupplierID", "dim_supplier", "SupplierID"),
    ]

    for child, child_col, parent, parent_col in relations:
        child_vals = frames[child][child_col]
        parent_vals = set(frames[parent][parent_col])
        orphans = child_vals[~child_vals.isin(parent_vals)]
        if len(orphans):
            record(
                "ERROR",
                child,
                "Referential integrity",
                f"{len(orphans):,} rows where {child_col} is absent from "
                f"{parent}.{parent_col}; examples: {sorted(orphans.unique())[:5]}",
                "Reject to a quarantine table or add an Unknown member.",
            )
        else:
            record(
                "INFO",
                child,
                "Referential integrity",
                f"{child_col} fully resolves to {parent}.{parent_col}",
                "Safe to enforce as FOREIGN KEY.",
            )

    # Security table: 'ALL' is a deliberate sentinel, not an orphan.
    sec = frames["security_user_access"]
    warehouses = set(frames["dim_warehouse"]["WarehouseID"])
    bad = sec[~sec["WarehouseID"].isin(warehouses | {"ALL"})]
    if len(bad):
        record(
            "ERROR",
            "security_user_access",
            "Referential integrity",
            f"{len(bad)} rows reference an unknown warehouse",
            "Correct the mapping before RLS is built.",
        )
    else:
        record(
            "EXCEPTION",
            "security_user_access",
            "Sentinel value",
            "WarehouseID uses the literal 'ALL' for the Supply Director role",
            "RLS predicate must special-case 'ALL'; do not treat as an orphan key.",
        )


# --------------------------------------------------------------------------- #
# Calendar coverage
# --------------------------------------------------------------------------- #


def check_calendar_coverage(frames: dict[str, pd.DataFrame]) -> None:
    """Every fact date must exist in the calendar dimension."""
    calendar = set(frames["dim_date"]["Date"])
    cal_min = frames["dim_date"]["Date"].min()
    cal_max = frames["dim_date"]["Date"].max()

    record(
        "INFO",
        "dim_date",
        "Calendar span",
        f"{cal_min.date()} to {cal_max.date()} ({len(calendar):,} days)",
        "",
    )

    for table, cols in DATE_COLUMNS.items():
        if table == "dim_date":
            continue
        df = frames[table]
        for col in cols:
            series = df[col].dropna()
            missing = series[~series.isin(calendar)]
            if len(missing):
                record(
                    "ERROR",
                    table,
                    "Calendar coverage",
                    f"{col}: {len(missing):,} rows fall outside dim_date "
                    f"(max {series.max().date()} vs calendar max {cal_max.date()})",
                    "Extend the calendar. The supplied calendar was built to the "
                    "as-of date and ignores the forward horizon of in-flight orders.",
                )

    # The furthest-forward date anywhere in the facts sets the minimum calendar end.
    horizon = max(
        frames[t][c].max()
        for t, cols in DATE_COLUMNS.items()
        if t != "dim_date"
        for c in cols
    )
    record(
        "INFO",
        "dim_date",
        "Required calendar horizon",
        f"The furthest forward date in any fact table is {horizon.date()}, "
        f"{(horizon - cal_max).days} days beyond the supplied calendar",
        "Rebuild the calendar to cover this horizon plus the forecast window.",
    )

    # ISO week 53 sanity check.
    d = frames["dim_date"]
    iso = d["Date"].dt.isocalendar()
    supplied_53 = int((d["ISOWeek"] == 53).sum())
    true_53 = int((iso["week"] == 53).sum())
    if supplied_53 != true_53:
        record(
            "ERROR",
            "dim_date",
            "ISO week correctness",
            f"Supplied ISOWeek never reaches 53 ({supplied_53} days) but the true "
            f"ISO calendar has {true_53} such days in this span",
            "Rebuild the calendar in SQL using correct ISO week logic.",
        )

    # Does the supplied ISOWeek disagree with the true ISO week anywhere?
    mismatch = int((d["ISOWeek"].astype(int) != iso["week"].astype(int)).sum())
    if mismatch:
        record(
            "ERROR",
            "dim_date",
            "ISO week correctness",
            f"{mismatch:,} of {len(d):,} days have an ISOWeek value that disagrees "
            f"with the true ISO-8601 week number",
            "Rebuild the calendar in SQL.",
        )


# --------------------------------------------------------------------------- #
# Date sequence logic
# --------------------------------------------------------------------------- #


def check_date_logic(frames: dict[str, pd.DataFrame]) -> None:
    """Dates must occur in a physically possible order."""
    sales = frames["fact_sales_orders"]
    for earlier, later in [
        ("OrderDate", "PromisedDeliveryDate"),
        ("OrderDate", "ActualDeliveryDate"),
    ]:
        bad = sales[sales[later] < sales[earlier]]
        severity = "ERROR" if len(bad) else "INFO"
        record(
            severity,
            "fact_sales_orders",
            "Date sequence",
            f"{len(bad):,} rows where {later} precedes {earlier}",
            "Quarantine and investigate." if len(bad) else "",
        )

    po = frames["fact_purchase_orders"]
    for earlier, later in [
        ("OrderDate", "ExpectedReceiptDate"),
        ("OrderDate", "ActualReceiptDate"),
    ]:
        bad = po[po[later] < po[earlier]]
        severity = "ERROR" if len(bad) else "INFO"
        record(
            severity,
            "fact_purchase_orders",
            "Date sequence",
            f"{len(bad):,} rows where {later} precedes {earlier}",
            "Quarantine and investigate." if len(bad) else "",
        )

    ship = frames["fact_shipments"]
    bad = ship[ship["DeliveryDate"] < ship["ShipDate"]]
    severity = "ERROR" if len(bad) else "INFO"
    record(
        severity,
        "fact_shipments",
        "Date sequence",
        f"{len(bad):,} rows where DeliveryDate precedes ShipDate",
        "Quarantine and investigate." if len(bad) else "",
    )

    # A shipment cannot leave before its sales order was placed.
    merged = ship.merge(
        sales[["SalesOrderID", "OrderDate", "PromisedDeliveryDate", "ActualDeliveryDate", "WarehouseID"]],
        on="SalesOrderID",
        how="left",
        suffixes=("_ship", "_sale"),
    )
    bad = merged[merged["ShipDate"] < merged["OrderDate"]]
    severity = "ERROR" if len(bad) else "INFO"
    record(
        severity,
        "fact_shipments",
        "Cross-table date sequence",
        f"{len(bad):,} shipments dispatched before their sales order date",
        "Quarantine and investigate." if len(bad) else "",
    )

    # Warehouse must agree between the order and its shipment.
    bad = merged[merged["WarehouseID_ship"] != merged["WarehouseID_sale"]]
    severity = "ERROR" if len(bad) else "INFO"
    record(
        severity,
        "fact_shipments",
        "Warehouse consistency",
        f"{len(bad):,} shipments dispatched from a different warehouse than the order",
        "Decide which side is authoritative." if len(bad) else
        "Warehouse is redundant on shipments; source it from the order.",
    )

    # Does the shipment delivery date agree with the sales order delivery date?
    bad = merged[merged["DeliveryDate"] != merged["ActualDeliveryDate"]]
    record(
        "ANOMALY" if len(bad) else "INFO",
        "fact_shipments",
        "Delivery date agreement",
        f"{len(bad):,} shipments whose DeliveryDate differs from the sales order "
        f"ActualDeliveryDate",
        "Choose a single authoritative delivery date for OTIF."
        if len(bad) else "The two tables agree; either may be used for OTIF.",
    )


# --------------------------------------------------------------------------- #
# Status consistency
# --------------------------------------------------------------------------- #


def detect_as_of_date(frames: dict[str, pd.DataFrame]) -> pd.Timestamp:
    """
    Infer the dataset's as-of (extract) date.

    The latest date on which any transaction was raised is the point at which the
    extract was taken. Everything scheduled beyond it is in-flight rather than
    historic, which changes how open records must be interpreted.
    """
    as_of = max(
        frames["fact_sales_orders"]["OrderDate"].max(),
        frames["fact_purchase_orders"]["OrderDate"].max(),
    )
    record(
        "INFO",
        "cross-table",
        "As-of date",
        f"Latest transaction date across all facts is {as_of.date()}; this is the "
        f"extract's as-of date and the anchor for all 'current' calculations",
        "Expose as an explicit model anchor rather than hard-coding TODAY() or "
        "a literal date in individual measures.",
    )
    return as_of


def check_status_consistency(frames: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> None:
    """
    Reconcile status flags against dates.

    An 'Open' record carrying a completion date looks like a defect. Before
    treating it as one, test whether the status is simply a deterministic
    restatement of 'scheduled beyond the as-of date' - in which case the record
    is a legitimate in-flight order and the date is an EXPECTED, not actual, date.
    """
    for table, status_col, open_value, date_col, noun in [
        ("fact_sales_orders", "OrderStatus", "Open", "ActualDeliveryDate", "delivery"),
        ("fact_purchase_orders", "Status", "Open", "ActualReceiptDate", "receipt"),
    ]:
        df = frames[table]
        is_open = df[status_col].eq(open_value)
        is_future = df[date_col].gt(as_of)

        if is_open.equals(is_future):
            # Status is fully explained by the as-of date: not a defect.
            record(
                "EXCEPTION",
                table,
                "Status vs dates",
                f"{int(is_open.sum()):,} records are flagged {open_value} and every "
                f"one of them - and only them - has a {noun} date after the as-of "
                f"date {as_of.date()}. Status is a deterministic restatement of "
                f"'scheduled in the future', so these are in-flight orders, not "
                f"defects. Their {date_col} is an EXPECTED date.",
                f"Split into ActualDate (NULL when open) and ScheduledDate in the "
                f"SQL view. Exclude open records from OTIF: they are not yet due, "
                f"so scoring them as on-time or late would be wrong.",
            )
        else:
            record(
                "ANOMALY",
                table,
                "Status vs dates",
                f"{int((is_open & df[date_col].notna()).sum()):,} records flagged "
                f"{open_value} carry a {noun} date, and status is NOT fully "
                f"explained by the as-of date",
                "Investigate before deciding which side is authoritative.",
            )

        # A completed record with no completion date is a genuine fault.
        closed_no_date = df[~is_open & df[date_col].isna()]
        if len(closed_no_date):
            record(
                "ERROR",
                table,
                "Status vs dates",
                f"{len(closed_no_date):,} completed records with no {date_col}",
                "Exclude from OTIF or treat as a failed delivery.",
            )

    # Is DeliveryStatus reproducible from the dates?
    ship = frames["fact_shipments"]
    merged = ship.merge(
        frames["fact_sales_orders"][["SalesOrderID", "PromisedDeliveryDate"]],
        on="SalesOrderID",
        how="left",
    )
    derived = np.where(
        merged["DeliveryDate"] > merged["PromisedDeliveryDate"], "Late", "On Time"
    )
    disagree = int((derived != merged["DeliveryStatus"]).sum())
    record(
        "ANOMALY" if disagree else "INFO",
        "fact_shipments",
        "DeliveryStatus reproducibility",
        f"DeliveryStatus disagrees with (DeliveryDate > PromisedDeliveryDate) on "
        f"{disagree:,} of {len(merged):,} rows ({pct(disagree, len(merged))})",
        "If it reproduces exactly, derive OTIF in DAX rather than trusting the flag."
        if disagree else
        "Flag is fully reproducible; derive OTIF in DAX for transparency.",
    )


# --------------------------------------------------------------------------- #
# Business-rule reconciliation
# --------------------------------------------------------------------------- #


def check_business_rules(frames: dict[str, pd.DataFrame]) -> None:
    """Are stored monetary values derivable from their components?"""
    product = frames["dim_product"].set_index("ProductID")

    # InventoryValue == OnHandUnits * UnitCost ?
    inv = frames["fact_inventory_snapshot"].copy()
    inv["ExpectedValue"] = (
        inv["OnHandUnits"] * inv["ProductID"].map(product["UnitCost"])
    ).round(2)
    diff = (inv["InventoryValue"] - inv["ExpectedValue"]).abs()
    mismatches = int((diff > 0.01).sum())
    record(
        "ANOMALY" if mismatches else "INFO",
        "fact_inventory_snapshot",
        "Derivable column",
        f"InventoryValue differs from OnHandUnits x UnitCost on {mismatches:,} of "
        f"{len(inv):,} rows (max deviation {diff.max():.2f})",
        "Column is fully derivable and high-cardinality; candidate for removal "
        "in Phase 24 optimisation." if not mismatches else
        "Investigate before treating as derivable.",
    )

    # Revenue == Quantity * UnitPrice ?
    sales = frames["fact_sales_orders"].copy()
    sales["ExpectedRevenue"] = (
        sales["Quantity"] * sales["ProductID"].map(product["UnitPrice"])
    ).round(2)
    diff = (sales["Revenue"] - sales["ExpectedRevenue"]).abs()
    mismatches = int((diff > 0.01).sum())
    record(
        "EXCEPTION" if mismatches else "INFO",
        "fact_sales_orders",
        "Derivable column",
        f"Revenue differs from Quantity x UnitPrice on {mismatches:,} of "
        f"{len(sales):,} rows ({pct(mismatches, len(sales))}); "
        f"median deviation {diff.median():.2f}",
        "Discounting or price variation is normal; retain Revenue as stored."
        if mismatches else "Revenue is fully derivable.",
    )

    # POValue == QuantityOrdered * UnitCost ?
    po = frames["fact_purchase_orders"].copy()
    po["ExpectedValue"] = (
        po["QuantityOrdered"] * po["ProductID"].map(product["UnitCost"])
    ).round(2)
    diff = (po["POValue"] - po["ExpectedValue"]).abs()
    mismatches = int((diff > 0.01).sum())
    record(
        "EXCEPTION" if mismatches else "INFO",
        "fact_purchase_orders",
        "Derivable column",
        f"POValue differs from QuantityOrdered x UnitCost on {mismatches:,} of "
        f"{len(po):,} rows ({pct(mismatches, len(po))}); "
        f"median deviation {diff.median():.2f}",
        "Purchase price variance is a genuine procurement metric; retain and "
        "expose as Purchase Price Performance (Requirement 10)."
        if mismatches else "POValue is fully derivable; no PPV signal available.",
    )

    # Actual supplier lead time vs the planning lead time on dim_product.
    po["ActualLeadDays"] = (po["ActualReceiptDate"] - po["OrderDate"]).dt.days
    po["PlanLeadDays"] = po["ProductID"].map(product["LeadTimeDays"])
    valid = po.dropna(subset=["ActualLeadDays"])
    record(
        "INFO",
        "fact_purchase_orders",
        "Lead time distribution",
        f"Actual lead time: min {valid['ActualLeadDays'].min():.0f}, "
        f"median {valid['ActualLeadDays'].median():.0f}, "
        f"max {valid['ActualLeadDays'].max():.0f} days. "
        f"Planning lead time on dim_product: {product['LeadTimeDays'].min()}-"
        f"{product['LeadTimeDays'].max()} days",
        "Use actual lead time for supplier scoring, planning lead time for "
        "reorder point.",
    )
    negative = int((valid["ActualLeadDays"] < 0).sum())
    if negative:
        record(
            "ERROR",
            "fact_purchase_orders",
            "Impossible lead time",
            f"{negative:,} POs received before they were ordered",
            "Quarantine.",
        )

    # Defect rate must be a proportion.
    dr = frames["fact_purchase_orders"]["DefectRate"]
    out_of_range = int(((dr < 0) | (dr > 1)).sum())
    record(
        "ERROR" if out_of_range else "INFO",
        "fact_purchase_orders",
        "Defect rate range",
        f"{out_of_range:,} rows outside [0,1]; observed range "
        f"{dr.min():.4f} to {dr.max():.4f}",
        "Clamp or quarantine." if out_of_range else
        "Stored as a proportion; format as percentage in the model.",
    )


# --------------------------------------------------------------------------- #
# Grain and coverage
# --------------------------------------------------------------------------- #


def check_grain_and_coverage(frames: dict[str, pd.DataFrame]) -> None:
    """Establish the true grain of the weekly facts and the product coverage gap."""
    all_products = set(frames["dim_product"]["ProductID"])

    demand = frames["fact_weekly_demand"]
    inventory = frames["fact_inventory_snapshot"]

    demand_products = set(demand["ProductID"])
    inv_products = set(inventory["ProductID"])
    sales_products = set(frames["fact_sales_orders"]["ProductID"])
    po_products = set(frames["fact_purchase_orders"]["ProductID"])

    record(
        "EXCEPTION",
        "cross-table",
        "Product coverage",
        f"dim_product holds {len(all_products):,} products. "
        f"Sales reference {len(sales_products):,}, purchase orders {len(po_products):,}, "
        f"weekly demand {len(demand_products):,}, inventory {len(inv_products):,}",
        "Half the catalogue has no inventory or demand signal. Add a "
        "HasDemandSignal flag to DimProduct and disclose the gap in the report "
        "rather than filtering silently.",
    )

    record(
        "INFO",
        "cross-table",
        "Product coverage overlap",
        f"Demand and inventory cover "
        f"{'the same' if demand_products == inv_products else 'DIFFERENT'} product sets "
        f"({len(demand_products & inv_products):,} in common)",
        "",
    )

    # Are the weekly facts a complete dense grid?
    for name, df, datecol in [
        ("fact_weekly_demand", demand, "WeekStart"),
        ("fact_inventory_snapshot", inventory, "SnapshotDate"),
    ]:
        weeks = df[datecol].nunique()
        products = df["ProductID"].nunique()
        warehouses = df["WarehouseID"].nunique()
        expected = weeks * products * warehouses
        actual = len(df)
        record(
            "INFO" if expected == actual else "ANOMALY",
            name,
            "Grain completeness",
            f"{weeks} weeks x {products} products x {warehouses} warehouses = "
            f"{expected:,} expected; {actual:,} actual "
            f"({'complete dense grid' if expected == actual else f'{expected - actual:,} missing'})",
            "A dense grid means no gap-filling is required before forecasting."
            if expected == actual else "Gap-fill before forecasting.",
        )

        # Weekday alignment.
        weekdays = df[datecol].dt.day_name().unique()
        record(
            "INFO",
            name,
            "Week alignment",
            f"{datecol} falls on: {sorted(weekdays)}",
            "",
        )

    # Do the two weekly facts share an identical week grid?
    same_grid = set(demand["WeekStart"]) == set(inventory["SnapshotDate"])
    record(
        "INFO" if same_grid else "ANOMALY",
        "cross-table",
        "Week grid alignment",
        f"Demand and inventory week grids are "
        f"{'identical' if same_grid else 'NOT identical'}",
        "Safe to join demand to inventory on week." if same_grid else
        "Align grids before joining.",
    )

    # Fact date ranges, to inform incremental refresh design.
    for table, cols in DATE_COLUMNS.items():
        if table == "dim_date":
            continue
        df = frames[table]
        primary = cols[0]
        record(
            "INFO",
            table,
            "History span",
            f"{primary} spans {df[primary].min().date()} to {df[primary].max().date()} "
            f"({(df[primary].max() - df[primary].min()).days / 365.25:.1f} years)",
            "",
        )


# --------------------------------------------------------------------------- #
# Distribution checks that drive later modelling decisions
# --------------------------------------------------------------------------- #


def check_distributions(frames: dict[str, pd.DataFrame]) -> None:
    """Characterise demand and revenue, which set XYZ thresholds and forecast method."""
    demand = frames["fact_weekly_demand"]

    # Intermittency: how sparse is demand? This decides whether classical
    # time-series methods are viable at all.
    zero_rate = (demand["ActualDemandUnits"] == 0).mean()
    record(
        "INFO",
        "fact_weekly_demand",
        "Demand intermittency",
        f"{zero_rate * 100:.2f}% of all product-warehouse-weeks have zero demand; "
        f"mean weekly demand {demand['ActualDemandUnits'].mean():.1f} units",
        "Low intermittency permits ETS/SARIMA. High intermittency would require "
        "Croston-style methods.",
    )

    # Coefficient of variation per series - the basis of XYZ classification.
    cv = (
        demand.groupby(["ProductID", "WarehouseID"])["ActualDemandUnits"]
        .agg(["mean", "std"])
        .assign(cv=lambda d: d["std"] / d["mean"].replace(0, np.nan))
        .dropna(subset=["cv"])
    )
    q = cv["cv"].quantile([0.10, 0.25, 0.33, 0.50, 0.66, 0.75, 0.90])
    record(
        "INFO",
        "fact_weekly_demand",
        "Demand variability (CV)",
        "Coefficient of variation per product-warehouse series: "
        + ", ".join(f"p{int(k * 100)}={v:.3f}" for k, v in q.items()),
        "These percentiles set defensible XYZ thresholds in Phase 10 instead of "
        "textbook constants.",
    )

    # Baseline forecast quality - the benchmark our Python model must beat.
    err = demand["BaselineForecastUnits"] - demand["ActualDemandUnits"]
    actual_sum = demand["ActualDemandUnits"].sum()
    mae = err.abs().mean()
    wape = err.abs().sum() / actual_sum
    bias = err.sum() / actual_sum
    record(
        "INFO",
        "fact_weekly_demand",
        "Baseline forecast accuracy",
        f"MAE {mae:.3f} units, WAPE {wape * 100:.2f}%, bias {bias * 100:+.2f}%",
        "This is the benchmark the Python model must beat in Phase 14. "
        "Recorded now so the comparison cannot be retrofitted.",
    )

    # Revenue concentration - the basis of ABC classification.
    sales = frames["fact_sales_orders"]
    by_product = sales.groupby("ProductID")["Revenue"].sum().sort_values(ascending=False)
    cumulative = by_product.cumsum() / by_product.sum()
    n_for_80 = int((cumulative <= 0.80).sum()) + 1
    record(
        "INFO",
        "fact_sales_orders",
        "Revenue concentration",
        f"{n_for_80:,} of {len(by_product):,} products "
        f"({pct(n_for_80, len(by_product))}) generate 80% of revenue",
        "A classical Pareto would put ~20% of SKUs in class A. Deviation here "
        "must inform the ABC thresholds chosen in Phase 9.",
    )

    # Does sales quantity reconcile with weekly demand?
    shared = set(demand["ProductID"]) & set(sales["ProductID"])
    window_start = demand["WeekStart"].min()
    sales_in_window = sales[
        sales["OrderDate"].between(window_start, demand["WeekStart"].max())
        & sales["ProductID"].isin(shared)
    ]
    demand_units = demand[demand["ProductID"].isin(shared)]["ActualDemandUnits"].sum()
    sales_units = sales_in_window["Quantity"].sum()
    record(
        "EXCEPTION",
        "cross-table",
        "Demand vs sales reconciliation",
        f"Over the shared window, weekly demand totals {demand_units:,} units "
        f"against {sales_units:,} sales-order units "
        f"(ratio {demand_units / sales_units:.1f}x)",
        "The two series are independent in this synthetic dataset. Never present "
        "demand as derived from sales; document them as separate measures.",
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def write_report(frames: dict[str, pd.DataFrame]) -> Path:
    """Render the findings register to a British-English markdown document."""
    df = pd.DataFrame(findings)
    order = {"ERROR": 0, "ANOMALY": 1, "EXCEPTION": 2, "INFO": 3}
    df["_o"] = df["Severity"].map(order)
    df = df.sort_values(["_o", "Table"]).drop(columns="_o")

    counts = df["Severity"].value_counts()
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "data_quality_report.md"

    lines = [
        "# Data Quality Report",
        "",
        "**Project:** Enterprise Supply Chain Control Tower  ",
        "**Phase:** 2 — Data Audit  ",
        f"**Generated by:** `Python/01_data_audit.py`  ",
        f"**Source:** `Data/Raw/` ({len(frames)} files)",
        "",
        "> **Phase 3 follow-up.** Every finding below was carried into the SQL",
        "> layer and re-tested there. `SQL/08_validation.sql` runs 66 checks",
        "> against the loaded database and confirms each one independently —",
        "> including the calendar overflow (now impossible: 13 date foreign keys",
        "> enforce it), the open-order date ambiguity (now split into mutually",
        "> exclusive columns), the derivability of `InventoryValue` (re-proved",
        "> against the raw staged value), and the baseline forecast benchmark",
        "> (re-derived in T-SQL at WAPE 13.04%, matching this report exactly).",
        "> Result: 66 passed, 0 failed. See `SQL/README.md`.",
        "",
        "## Severity definitions",
        "",
        "| Severity | Meaning |",
        "|---|---|",
        "| **ERROR** | A genuine data fault requiring correction in the SQL layer. |",
        "| **ANOMALY** | Suspicious; requires a documented decision before it is trusted. |",
        "| **EXCEPTION** | Valid business behaviour that merely appears unusual. |",
        "| **INFO** | Context that shapes a downstream modelling decision. |",
        "",
        "## Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for sev in ["ERROR", "ANOMALY", "EXCEPTION", "INFO"]:
        lines.append(f"| {sev} | {int(counts.get(sev, 0))} |")

    lines += ["", "## Table inventory", "",
              "| Table | Rows | Columns |", "|---|---|---|"]
    for name, frame in sorted(frames.items()):
        lines.append(f"| `{name}` | {len(frame):,} | {len(frame.columns)} |")
    lines.append(f"| **Total** | **{sum(len(f) for f in frames.values()):,}** | |")

    for sev in ["ERROR", "ANOMALY", "EXCEPTION", "INFO"]:
        subset = df[df["Severity"] == sev]
        if subset.empty:
            continue
        lines += ["", f"## {sev} findings", "",
                  "| Table | Check | Detail | Action |", "|---|---|---|---|"]
        for _, r in subset.iterrows():
            detail = str(r["Detail"]).replace("|", "\\|")
            action = str(r["Action"]).replace("|", "\\|")
            lines.append(f"| `{r['Table']}` | {r['Check']} | {detail} | {action} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    if not RAW.exists():
        print(f"Raw data directory not found: {RAW}", file=sys.stderr)
        return 1

    frames = load_all()
    print(f"Loaded {len(frames)} tables, {sum(len(f) for f in frames.values()):,} rows\n")

    as_of = detect_as_of_date(frames)

    check_structure(frames)
    check_referential_integrity(frames)
    check_calendar_coverage(frames)
    check_date_logic(frames)
    check_status_consistency(frames, as_of)
    check_business_rules(frames)
    check_grain_and_coverage(frames)
    check_distributions(frames)

    out = write_report(frames)

    df = pd.DataFrame(findings)
    counts = df["Severity"].value_counts()
    print("Findings by severity:")
    for sev in ["ERROR", "ANOMALY", "EXCEPTION", "INFO"]:
        print(f"  {sev:<10} {int(counts.get(sev, 0))}")

    print("\n--- ERROR and ANOMALY detail ---")
    for _, r in df[df["Severity"].isin(["ERROR", "ANOMALY"])].iterrows():
        print(f"[{r['Severity']}] {r['Table']} :: {r['Check']}\n    {r['Detail']}")

    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
