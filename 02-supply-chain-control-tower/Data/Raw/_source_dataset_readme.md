# Supply Chain Control Tower Dataset

Supports inventory optimisation, supplier scorecards, logistics, ABC/XYZ classification and demand forecasting.

## Purpose
This dataset is **synthetic and portfolio-safe**. It is designed for an advanced Power BI project rather than a beginner dashboard.

## Suggested Architecture
Raw CSVs → SQL database / Fabric Lakehouse → Power Query / Dataflow → Semantic Model → Power BI Service

## Tables
- **fact_sales_orders.csv** — 80k sales orders
- **fact_purchase_orders.csv** — 25k purchase orders
- **fact_shipments.csv** — Shipment execution data
- **fact_weekly_demand.csv** — Weekly actual and baseline forecast demand
- **fact_inventory_snapshot.csv** — Weekly stock and inbound position
- **dim_product.csv** — 1,000 products with costs/prices/lead times
- **dim_supplier.csv** — 120 suppliers
- **dim_warehouse.csv** — 6 warehouses
- **security_user_access.csv** — Warehouse-level dynamic RLS

## Suggested Relationships
- dim_product[ProductID] 1:* order, PO, demand and inventory facts
- dim_warehouse[WarehouseID] 1:* all warehouse facts
- dim_supplier[SupplierID] 1:* fact_purchase_orders
- fact_sales_orders[SalesOrderID] 1:1 fact_shipments[SalesOrderID]

## Advanced Tasks to Implement
1. Calculate ABC and XYZ classifications dynamically.
2. Create OTIF, lead-time variance, defect rate and supplier score.
3. Train a Python forecasting model and compare it with BaselineForecastUnits.
4. Calculate safety stock, reorder point, excess stock and stockout risk.
5. Build a control-tower alert page with drill-through from region → warehouse → SKU.
6. Use incremental refresh on weekly demand/inventory after scaling.

## Scaling Notes
Scale demand/inventory to millions of rows by increasing products, warehouses and history in the generator. Keep the starter dataset responsive while developing the model.
