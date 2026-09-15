"""
04_reconcile_measures.py
========================
Phase 6 reconciliation: DAX measure results versus independent SQL.

Reads the DAX evaluation output produced by the Tabular Editor script
(SECTION|LABEL|VALUE lines) and compares each comparable figure against a SQL
query written independently against the analytics views.

The point of the independence matters: comparing one DAX measure against
another that shares the same assumption proves nothing. Each expected value
below is computed from SQL, not from the model.

Read-only. Modifies nothing.

Usage
-----
    python Python/04_reconcile_measures.py [path-to-eval-file]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pyodbc

CONN = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=localhost\\SQLEXPRESS;DATABASE=SupplyChainBI;"
    "Trusted_Connection=yes;TrustServerCertificate=yes;"
)

DEFAULT_EVAL = Path(os.environ.get("TEMP", "/tmp")) / "phase6_eval.txt"

# (section, measure) -> (SQL scalar expression, tolerance)
# Tolerance covers float representation only; 0 means exact.
CHECKS = [
    # ---- Global sales -----------------------------------------------------
    ("GLOBAL", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders", 0.01),
    ("GLOBAL", "Sales Orders",
     "SELECT COUNT(DISTINCT SalesOrderID) FROM analytics.vw_SalesOrders", 0),
    ("GLOBAL", "Units Sold",
     "SELECT SUM(Quantity) FROM analytics.vw_SalesOrders", 0),
    ("GLOBAL", "Open Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE IsOpenOrder=1", 0),
    ("GLOBAL", "Delivered Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE IsDelivered=1", 0),
    ("GLOBAL", "Sales Orders Due As Of Date",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE PromisedDeliveryDate <= "
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate')", 0),
    ("GLOBAL", "Average Order Value",
     "SELECT SUM(Revenue)/COUNT(DISTINCT SalesOrderID) FROM analytics.vw_SalesOrders", 0.0001),
    ("GLOBAL", "Average Selling Price",
     "SELECT SUM(Revenue)/SUM(CAST(Quantity AS decimal(18,6))) FROM analytics.vw_SalesOrders", 0.0001),

    # ---- Global procurement ----------------------------------------------
    ("GLOBAL", "Purchase Order Value",
     "SELECT SUM(POValue) FROM analytics.vw_PurchaseOrders", 0.01),
    ("GLOBAL", "Purchase Orders",
     "SELECT COUNT(DISTINCT PurchaseOrderID) FROM analytics.vw_PurchaseOrders", 0),
    ("GLOBAL", "Units Ordered",
     "SELECT SUM(QuantityOrdered) FROM analytics.vw_PurchaseOrders", 0),
    ("GLOBAL", "Open Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE IsOpenPO=1", 0),
    ("GLOBAL", "Received Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1", 0),
    ("GLOBAL", "Average Supplier Lead Time",
     "SELECT AVG(CAST(ActualLeadTimeDays AS decimal(18,8))) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1", 0.0001),

    # ---- Global logistics -------------------------------------------------
    ("GLOBAL", "Total Shipments",
     "SELECT COUNT(*) FROM analytics.vw_Shipments", 0),
    ("GLOBAL", "Freight Cost",
     "SELECT SUM(FreightCost) FROM analytics.vw_Shipments", 0.01),
    ("GLOBAL", "Average Freight Cost per Sales Order",
     "SELECT SUM(FreightCost)/COUNT(DISTINCT SalesOrderID) FROM analytics.vw_Shipments", 0.0001),

    # ---- Global delivery / receipt performance ---------------------------
    ("GLOBAL", "Completed Deliveries",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE IsDelivered=1", 0),
    ("GLOBAL", "On-Time Deliveries",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE IsDelivered=1 AND DeliveryDelayDays<=0", 0),
    ("GLOBAL", "Late Deliveries",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE IsDelivered=1 AND DeliveryDelayDays>0", 0),
    ("GLOBAL", "On-Time Delivery %",
     "SELECT CAST(COUNT(CASE WHEN DeliveryDelayDays<=0 THEN 1 END) AS decimal(18,10))/COUNT(*) "
     "FROM analytics.vw_SalesOrders WHERE IsDelivered=1", 0.000001),
    ("GLOBAL", "Average Delivery Delay Days",
     "SELECT AVG(CAST(DeliveryDelayDays AS decimal(18,8))) FROM analytics.vw_SalesOrders WHERE IsDelivered=1", 0.0001),
    ("GLOBAL", "Completed Receipts",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1", 0),
    ("GLOBAL", "On-Time Receipts",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1 AND ReceiptDelayDays<=0", 0),
    ("GLOBAL", "Late Receipts",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1 AND ReceiptDelayDays>0", 0),
    ("GLOBAL", "On-Time Receipt %",
     "SELECT CAST(COUNT(CASE WHEN ReceiptDelayDays<=0 THEN 1 END) AS decimal(18,10))/COUNT(*) "
     "FROM analytics.vw_PurchaseOrders WHERE IsReceived=1", 0.000001),
    ("GLOBAL", "Average Receipt Delay Days",
     "SELECT AVG(CAST(ReceiptDelayDays AS decimal(18,8))) FROM analytics.vw_PurchaseOrders WHERE IsReceived=1", 0.0001),

    # ---- Global inventory (semi-additive) --------------------------------
    ("GLOBAL", "Current On Hand Units",
     "SELECT SUM(OnHandUnits) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("GLOBAL", "Current Inbound Units",
     "SELECT SUM(InboundUnits) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("GLOBAL", "Current Inventory Position",
     "SELECT SUM(OnHandUnits)+SUM(InboundUnits) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("GLOBAL", "Current Inventory Value",
     "SELECT SUM(CAST(i.OnHandUnits AS decimal(18,6))*p.UnitCost) "
     "FROM analytics.vw_InventorySnapshot i JOIN analytics.vw_DimProduct p ON p.ProductID=i.ProductID "
     "WHERE i.SnapshotDate=(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0.01),

    # ---- Global demand ----------------------------------------------------
    ("GLOBAL", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand", 0),
    ("GLOBAL", "Baseline Forecast Units",
     "SELECT SUM(BaselineForecastUnits) FROM analytics.vw_WeeklyDemand", 0),
    ("GLOBAL", "Demand Variance Units",
     "SELECT SUM(BaselineForecastUnits)-SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand", 0),
    ("GLOBAL", "Demand Variance %",
     "SELECT (SUM(CAST(BaselineForecastUnits AS decimal(18,8)))-SUM(ActualDemandUnits))/SUM(ActualDemandUnits) "
     "FROM analytics.vw_WeeklyDemand", 0.000001),

    # ---- Product filter: P00001 ------------------------------------------
    ("PRODUCT_P00001", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders WHERE ProductID='P00001'", 0.01),
    ("PRODUCT_P00001", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE ProductID='P00001'", 0),
    ("PRODUCT_P00001", "Units Sold",
     "SELECT SUM(Quantity) FROM analytics.vw_SalesOrders WHERE ProductID='P00001'", 0),
    ("PRODUCT_P00001", "Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE ProductID='P00001'", 0),
    ("PRODUCT_P00001", "Total Shipments",
     "SELECT COUNT(*) FROM analytics.vw_Shipments WHERE ProductID='P00001'", 0),
    ("PRODUCT_P00001", "Current On Hand Units",
     "SELECT SUM(OnHandUnits) FROM analytics.vw_InventorySnapshot WHERE ProductID='P00001' AND SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("PRODUCT_P00001", "Current Inventory Value",
     "SELECT SUM(CAST(i.OnHandUnits AS decimal(18,6))*p.UnitCost) "
     "FROM analytics.vw_InventorySnapshot i JOIN analytics.vw_DimProduct p ON p.ProductID=i.ProductID "
     "WHERE i.ProductID='P00001' AND i.SnapshotDate=(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot "
     "WHERE SnapshotDate<=(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0.01),
    ("PRODUCT_P00001", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand WHERE ProductID='P00001'", 0),

    # ---- Warehouse filter: W01 -------------------------------------------
    ("WAREHOUSE_W01", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders WHERE WarehouseID='W01'", 0.01),
    ("WAREHOUSE_W01", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE WarehouseID='W01'", 0),
    ("WAREHOUSE_W01", "Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE WarehouseID='W01'", 0),
    ("WAREHOUSE_W01", "Freight Cost",
     "SELECT SUM(FreightCost) FROM analytics.vw_Shipments WHERE WarehouseID='W01'", 0.01),
    ("WAREHOUSE_W01", "Current On Hand Units",
     "SELECT SUM(OnHandUnits) FROM analytics.vw_InventorySnapshot WHERE WarehouseID='W01' AND SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("WAREHOUSE_W01", "Current Inventory Value",
     "SELECT SUM(CAST(i.OnHandUnits AS decimal(18,6))*p.UnitCost) "
     "FROM analytics.vw_InventorySnapshot i JOIN analytics.vw_DimProduct p ON p.ProductID=i.ProductID "
     "WHERE i.WarehouseID='W01' AND i.SnapshotDate=(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot "
     "WHERE SnapshotDate<=(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0.01),
    ("WAREHOUSE_W01", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand WHERE WarehouseID='W01'", 0),

    # ---- Product + warehouse ---------------------------------------------
    ("PROD_WH", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders WHERE ProductID='P00001' AND WarehouseID='W01'", 0.01),
    ("PROD_WH", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE ProductID='P00001' AND WarehouseID='W01'", 0),
    ("PROD_WH", "Current On Hand Units",
     "SELECT SUM(OnHandUnits) FROM analytics.vw_InventorySnapshot WHERE ProductID='P00001' AND WarehouseID='W01' "
     "AND SnapshotDate=(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),
    ("PROD_WH", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand WHERE ProductID='P00001' AND WarehouseID='W01'", 0),

    # ---- Supplier filter: must move procurement ONLY ----------------------
    ("SUPPLIER_S0001", "Purchase Order Value",
     "SELECT SUM(POValue) FROM analytics.vw_PurchaseOrders WHERE SupplierID='S0001'", 0.01),
    ("SUPPLIER_S0001", "Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE SupplierID='S0001'", 0),
    ("SUPPLIER_S0001", "Units Ordered",
     "SELECT SUM(QuantityOrdered) FROM analytics.vw_PurchaseOrders WHERE SupplierID='S0001'", 0),
    # These MUST equal the unfiltered totals: no path exists from supplier.
    ("SUPPLIER_S0001", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders", 0.01),
    ("SUPPLIER_S0001", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders", 0),
    ("SUPPLIER_S0001", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand", 0),

    # ---- Active date relationship, 2025 ----------------------------------
    ("YEAR_2025", "Total Revenue",
     "SELECT SUM(Revenue) FROM analytics.vw_SalesOrders WHERE YEAR(OrderDate)=2025", 0.01),
    ("YEAR_2025", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE YEAR(OrderDate)=2025", 0),
    ("YEAR_2025", "Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE YEAR(OrderDate)=2025", 0),
    ("YEAR_2025", "Total Shipments",
     "SELECT COUNT(*) FROM analytics.vw_Shipments WHERE YEAR(ShipDate)=2025", 0),
    ("YEAR_2025", "Actual Demand Units",
     "SELECT SUM(ActualDemandUnits) FROM analytics.vw_WeeklyDemand WHERE YEAR(WeekStart)=2025", 0),
    # Anchored: a date slicer must NOT move current inventory.
    ("YEAR_2025", "Current On Hand Units",
     "SELECT SUM(OnHandUnits) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate="
     "(SELECT MAX(SnapshotDate) FROM analytics.vw_InventorySnapshot WHERE SnapshotDate<="
     "(SELECT TRY_CONVERT(date,ConfigValue,23) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))", 0),

    # ---- Inactive date roles, 2026 ---------------------------------------
    ("YEAR_2026", "Sales Orders",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE YEAR(OrderDate)=2026", 0),
    ("YEAR_2026", "Sales Orders by Actual Delivery Date",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE YEAR(ActualDeliveryDate)=2026", 0),
    ("YEAR_2026", "Sales Orders by Promised Delivery Date",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE YEAR(PromisedDeliveryDate)=2026", 0),
    ("YEAR_2026", "Sales Orders by Scheduled Delivery Date",
     "SELECT COUNT(*) FROM analytics.vw_SalesOrders WHERE YEAR(ScheduledDeliveryDate)=2026", 0),
    ("YEAR_2026", "Purchase Orders",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE YEAR(OrderDate)=2026", 0),
    ("YEAR_2026", "Purchase Orders by Actual Receipt Date",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE YEAR(ActualReceiptDate)=2026", 0),
    ("YEAR_2026", "Purchase Orders by Scheduled Receipt Date",
     "SELECT COUNT(*) FROM analytics.vw_PurchaseOrders WHERE YEAR(ScheduledReceiptDate)=2026", 0),
]


def parse_eval(path: Path) -> dict[tuple[str, str], str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            out[(parts[0], parts[1])] = parts[2]
    return out


def to_float(v: str):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    eval_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVAL
    if not eval_path.exists():
        print(f"Evaluation output not found: {eval_path}", file=sys.stderr)
        return 1

    dax = parse_eval(eval_path)
    cn = pyodbc.connect(CONN, timeout=30)
    cur = cn.cursor()

    print(f"{'CONTEXT':<16}{'MEASURE':<40}{'DAX':>20}{'SQL':>20}  STATUS")
    print("-" * 104)
    passed = failed = missing = 0
    current = None
    for section, measure, sql, tol in CHECKS:
        if section != current:
            if current is not None:
                print()
            current = section
        key = (section, measure)
        if key not in dax:
            print(f"{section:<16}{measure:<40}{'--':>20}{'--':>20}  NOT EVALUATED")
            missing += 1
            continue
        cur.execute(sql)
        sql_val = cur.fetchone()[0]
        d = to_float(dax[key])
        s = float(sql_val) if sql_val is not None else None
        if d is None or s is None:
            status = "NON-NUMERIC"
            failed += 1
        else:
            ok = abs(d - s) <= tol
            status = "PASS" if ok else "*** FAIL ***"
            if ok:
                passed += 1
            else:
                failed += 1
        print(f"{section:<16}{measure:<40}{d:>20,.4f}{s:>20,.4f}  {status}"
              if d is not None and s is not None
              else f"{section:<16}{measure:<40}{dax[key]:>20}{str(sql_val):>20}  {status}")

    cn.close()

    print("\n" + "=" * 78)
    print(f"  RECONCILIATION  checks {len(CHECKS)}   passed {passed}   "
          f"failed {failed}   not evaluated {missing}")
    print(f"  RESULT: {'PASS' if failed == 0 and missing == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if failed == 0 and missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
