# Supply Chain Control Tower

Inventory, procurement, logistics, supplier performance and demand — one Power BI
model over a SQL Server star schema, built end to end as code.

> **Synthetic data.** Every table in this project is synthetic and portfolio-safe.
> It must never be presented as a real company's operational data.

![Executive Control Tower](Validation/evidence/listing/executive.png)

## What it answers

- Where is the inventory, what is it worth, and how much of it is excess?
- Which lines need reordering today, and how many units?
- Which suppliers deliver on time, and which are slow *and* unpredictable?
- Which products carry the value, and which of those have volatile demand?
- How close does the demand baseline actually run to what shipped?

## The ten pages

| | |
|---|---|
| **Inventory Overview** — on hand, inbound, position, value | **Procurement Overview** — POs, receipts, spend by supplier |
| ![Inventory](Validation/evidence/listing/inventory.png) | ![Procurement](Validation/evidence/listing/procurement.png) |
| **Logistics & Delivery** — carriers, freight, on-time rate | **Warehouse Performance** — the six sites side by side |
| ![Logistics](Validation/evidence/listing/logistics.png) | ![Warehouse](Validation/evidence/listing/warehouse.png) |
| **Product / SKU Detail** — demand, supply and stock per product | **Stockout & Replenishment Risk** — what to order today |
| ![Product](Validation/evidence/listing/product.png) | ![Replenishment](Validation/evidence/listing/replenishment.png) |
| **ABC/XYZ Inventory Strategy** — value class against volatility | **Supplier Performance** — a scored, ranked supplier base |
| ![ABC/XYZ](Validation/evidence/listing/abcxyz.png) | ![Suppliers](Validation/evidence/listing/suppliers.png) |
| **Demand Forecasting** — accuracy, bias and drift of the baseline | |
| ![Forecasting](Validation/evidence/listing/forecasting.png) | |

## The numbers

| | |
|---|---|
| **Stack** | SQL Server → Power Query → semantic model (TMDL) → report (PBIR) |
| **Source** | 817,837 rows across 10 synthetic files |
| **Model** | 17 tables, 121 measures, 24 relationships (16 active, 8 inactive role-playing dates), 0 bidirectional, 0 fact-to-fact |
| **Report** | 10 pages, 282 visuals |

## Verified

Every number is re-derived by independently written SQL and compared against what
the model returns. Nothing below is a self-report from the model alone.

| Check | Count | Result |
|---|---:|---|
| SQL platform validation | 66 | pass |
| Power Query / connection layer | 207 | pass |
| Semantic model structure | 23 | pass |
| Core DAX vs independent SQL | 73 | pass |
| Replenishment logic vs SQL | 22 | pass |
| Pages 7–9 live value checks | 103 | pass |
| Page 10 live value checks | 30 | pass |
| Visuals returning data, live model | 282 | 282 pass, 0 blank |
| Measures evaluating without error | 121 | 121 pass, 0 error |
| **Total** | **927** | **0 failures** |

Layout QA reports 0 overlaps, 0 out-of-canvas visuals and 0 missing titles across
all ten pages; navigation QA reports 10 buttons per page and 0 issues.

## What it is careful about

**Current inventory is a stock, not a flow.** On-hand, inbound and position are read
at one snapshot date and never summed across snapshots. The snapshot date is shown
on the page so it is never ambiguous which day is on screen.

**The forecast page scores a supplied in-sample baseline.** `BaselineForecastUnits`
is a baseline that ships with the dataset, not a model trained here and projected
forward. Accuracy, bias and MAE are therefore measures of that baseline against
actuals over history — useful, and labelled for what it is rather than presented as
a forward prediction. See [`Documentation/forecast_logic.md`](Documentation/forecast_logic.md).

**Role-playing dates are explicit.** Order date, ship date, delivery date and
snapshot date each reach `DimDate` through their own relationship; eight of them are
inactive and switched with `USERELATIONSHIP` rather than duplicating the calendar.

**No filter crosses between facts.** Each fact carries its own conformed dimension
keys, so a warehouse selection reaches shipments, sales, purchases and inventory
independently rather than by chaining through a fact table.

## Architecture

```
Data/Raw/*.csv            synthetic source extracts
   ↓ SQL/01–08            staging → dbo → analytics views, constraints, indexes
   ↓ Power Query          Import mode over analytics.vw_*
PowerBI/…SemanticModel    TMDL: tables, relationships, measures
PowerBI/…Report           PBIR: 10 pages
Validation/               reconciliation, layout, navigation and live-model checks
Documentation/            logic notes and the measure dictionary
```

## Documentation

- [`Documentation/semantic_model.md`](Documentation/semantic_model.md) — tables, grain, relationships
- [`Documentation/dax_measure_dictionary.md`](Documentation/dax_measure_dictionary.md) — every measure, what it means
- [`Documentation/inventory_logic.md`](Documentation/inventory_logic.md) — reorder point, safety stock, status
- [`Documentation/forecast_logic.md`](Documentation/forecast_logic.md) — accuracy, bias and their limits
- [`Documentation/data_quality_report.md`](Documentation/data_quality_report.md) — what the audit found in the source
- [`SQL/README.md`](SQL/README.md) — how to build the database from a clone

## Licence

[MIT](LICENSE) — the code. The dataset is a synthetic portfolio dataset, included so
the build is reproducible from a clone.

## Status

See [PROJECT_STATE.md](PROJECT_STATE.md).
