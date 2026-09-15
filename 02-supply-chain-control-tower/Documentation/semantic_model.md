# Semantic Model

Power BI semantic model for the Supply Chain Control Tower.

> **Status.** Phases 4-6 complete and signed off: connection layer, star-schema
> relationships, and the core measure layer. Calculation groups, time
> intelligence, field parameters and row-level security belong to later phases
> and are documented here as they are built.

---

## Project format

| Item | Value |
|---|---|
| Format | PBIP with TMDL semantic model and PBIR report |
| Power BI Desktop | 2.148.1477.0 (25.10) |
| Compatibility level | 1550 |
| Compatibility mode | `powerBI` |
| Storage mode | Import |
| Location | `PowerBI/SupplyChainControlTower.pbip` |

Both the model and the report are plain text on disk, so the whole solution is
diffable and reviewable in git rather than locked inside a binary.

---

## Source contract

The model reads **only** from the `analytics` schema of `SupplyChainBI`. It never
touches `dbo` or `stg`. Every table is a two-step Power Query: connect, then
navigate to a view.

```m
let
    Source = Sql.Database("localhost\SQLEXPRESS", "SupplyChainBI"),
    analytics_vw_SalesOrders = Source{[Schema="analytics",Item="vw_SalesOrders"]}[Data]
in
    analytics_vw_SalesOrders
```

There is no third step in any of the eleven queries. That is deliberate: the SQL
layer already performs every clean, type and business transformation, so Power
Query has nothing to do beyond connecting. It also keeps the folding surface as
wide as possible for the incremental refresh policy in Phase 21.

### Tables

| Model table | Source view | Rows | Role |
|---|---|---:|---|
| `DimDate` | `analytics.vw_DimDate` | 2,007 | Dimension |
| `DimProduct` | `analytics.vw_DimProduct` | 1,000 | Dimension |
| `DimSupplier` | `analytics.vw_DimSupplier` | 120 | Dimension |
| `DimWarehouse` | `analytics.vw_DimWarehouse` | 6 | Dimension |
| `FactSalesOrders` | `analytics.vw_SalesOrders` | 80,000 | Fact |
| `FactPurchaseOrders` | `analytics.vw_PurchaseOrders` | 25,000 | Fact |
| `FactShipments` | `analytics.vw_Shipments` | 80,000 | Fact |
| `FactWeeklyDemand` | `analytics.vw_WeeklyDemand` | 315,000 | Fact |
| `FactInventorySnapshot` | `analytics.vw_InventorySnapshot` | 315,000 | Fact (semi-additive) |
| `SecurityUserAccess` | `analytics.vw_SecurityUserAccess` | 7 | Security |
| `ModelConfig` | `analytics.vw_ModelConfig` | 6 | Configuration |
| **Total** | | **818,146** | |

The model total exceeds the 817,837 rows in the source CSVs by 309, and the
difference is fully explained: `DimDate` is generated rather than imported, so it
carries 2,007 days instead of the supplied 1,704 (+303), and `ModelConfig` is a
new table with no CSV equivalent (+6).

`ModelConfig` is small but load-bearing. It carries `AsOfDate = 2026-08-31`, so
DAX can read the anchor date rather than hard-coding it across dozens of measures.

---

## Model authoring approach

Structural changes are made by script rather than by hand, using Tabular Editor 2
against the TMDL folder:

```
TabularEditor.exe <definition folder> -S <script.csx> -TMDL <definition folder>
```

The script lives at `PowerBI/TabularEditorScripts/phase4_model_transform.csx` and
is committed, so every model change is reviewable, repeatable and attributable.
Tabular Editor owns TMDL serialisation, which keeps file naming and object
references consistent — hand-editing the text risks a model that no longer opens.

**Power BI Desktop must be closed** while these scripts run. Desktop holds the
model in memory and overwrites external file changes on its next save.

Validation after every scripted change:

1. Reload the output with Tabular Editor — proves the TMDL parses
2. Run Best Practice Analyzer (`-A`) — proves the model is structurally sound
3. Run `Python/02_verify_semantic_model.py` — proves the model matches the SQL source

---

## Auto date/time is disabled

`__PBI_TimeIntelligenceEnabled = 0`.

Power BI's auto date/time is on by default and silently builds a hidden calendar
table for **every** date column. This model has eighteen date columns, so it
produced eighteen `LocalDateTable_*` tables plus a `DateTableTemplate_*`,
nineteen tables in total, wired up with eighteen relationships and a `variation`
on every date column.

All of it was removed. `DimDate` already provides ISO weeks, ISO year, financial
year, week-start dates and proper sort keys — none of which the auto tables have.
Keeping both would mean two competing calendars and a model carrying nineteen
tables nobody designed.

This must stay off. Re-enabling it, in the file or globally, recreates all
nineteen on the next refresh.

---

## Parameters

| Parameter | Type | Development value |
|---|---|---|
| `RangeStart` | DateTime | 2026-01-01 00:00:00 |
| `RangeEnd` | DateTime | 2026-09-01 00:00:00 |

```
expression RangeStart = #datetime(2026, 1, 1, 0, 0, 0) meta [IsParameterQuery=true, Type="DateTime", IsParameterQueryRequired=true]
expression RangeEnd   = #datetime(2026, 9, 1, 0, 0, 0) meta [IsParameterQuery=true, Type="DateTime", IsParameterQueryRequired=true]
```

The `meta` record is what makes Power BI treat these as parameters rather than
plain expressions, and `Type="DateTime"` is required before an incremental
refresh policy can bind to them.

**Neither is applied as a filter to any table yet.** They exist so Phase 21 can
attach a policy without restructuring queries. The values are development-time
only; the Power BI Service overrides them per partition at refresh.

---

## Column types

Types come from the SQL Server connector's own mapping of the view schema. All
109 columns were verified against `INFORMATION_SCHEMA.COLUMNS`.

| SQL type | Model type |
|---|---|
| `date` | `dateTime` |
| `int`, `smallint`, `tinyint` | `int64` |
| `bit` | `boolean` |
| `varchar`, `nvarchar` | `string` |
| `decimal(18,2)` | `double` — see below |
| `decimal(9,6)` | `double` |

### Why money is `double` and not Fixed Decimal

Conventional Power BI guidance is to type currency as Fixed Decimal. The seven
money columns were set that way in TMDL, and **Power BI reverted every one to
`double` on the next refresh.**

That is not a bug. The engine reconciles each model column's type to whatever the
M query returns, and a TMDL-only change has no anchor in M. Making it durable
would require a `Table.TransformColumnTypes` cast in Power Query.

That cast was deliberately not added:

- It is not established that a Currency cast folds against this source. Introducing an unverified folding risk ahead of the Phase 21 incremental refresh design is a genuine cost.
- There is no precision benefit to buy with it. Values reach at most ~184,297 with two decimals — roughly seven significant digits — against the fifteen to seventeen a double carries. Exact precision is held where the data lives: the SQL layer types these `decimal(18,2)`.

Revisit in Phase 21, where folding gets measured empirically. Recorded as decision
**D18**.

### Summarisation

Twenty-three numeric columns that are not additive were set to
`summarizeBy: none`: every numeric column on `DimDate`, the unit cost and price
attributes on `DimProduct`, and the delay, lead-time, transit and defect-rate
columns on the facts.

Left at the default `sum`, dragging `DimDate[Year]` onto a card reports
**4,058,127**. Aggregation for these belongs in explicit measures.

Genuinely additive columns keep `sum`: `Revenue`, `POValue`, `FreightCost`,
`PurchasePriceVariance`, `ExpectedPOValue` and the unit counts.

### Date formatting

All eighteen date columns use `yyyy-mm-dd` rather than the default `Long Date`.
The solution spans Australia, New Zealand, Singapore and the UAE, so an ISO
format removes any dd/mm versus mm/dd ambiguity.

---

## Query folding

Folding matters here because incremental refresh depends on `RangeStart` and
`RangeEnd` reaching the database as a `WHERE` clause. If the filter is applied in
Power Query instead, every refresh reads the whole table.

Two properties support it:

**The queries are thin.** Two steps, no transformations, nothing that would
force local evaluation.

**The predicates seek.** Measured with `SET STATISTICS IO` over the actual
parameter window (2026-01-01 to 2026-09-01):

| Table | Filter column | Rows full → filtered | Logical reads full → filtered |
|---|---|---|---|
| `FactSalesOrders` | `OrderDate` | 80,000 → 14,493 | 240 → **91** |
| `FactWeeklyDemand` | `WeekStart` | 315,000 → 105,000 | 1,253 → **460** |
| `FactInventorySnapshot` | `SnapshotDate` | 315,000 → 105,000 | 1,253 → **460** |

Read cost scales with rows returned rather than table size, which is what
distinguishes a seek from a scan followed by a filter. `FactSalesOrders` is served
by `IX_FactSalesOrders_OrderDate`; the two weekly facts by their clustered primary
keys, which lead on the date column.

**Scope of this evidence.** It proves the *database* resolves these predicates
efficiently. It does not by itself prove Power Query emits them. Confirming that
means **Transform data → select the query → right-click the last step → View
Native Query** and checking the `WHERE` clause appears. That is done in Phase 21,
when the filters are actually applied.

---

## Relationships

**None.** The model deliberately has zero relationships at the end of Phase 4.

Two mechanisms would otherwise have created them, and both were suppressed:

- **Auto date/time** created eighteen. Removed, and the feature disabled.
- **Foreign key import** creates relationships from source FK metadata. The SQL layer declares twenty-five foreign keys, but the model reads *views*, and views carry no FK metadata — so this could never have fired regardless of the setting.

Relationships are designed in Phase 5: single-direction filtering, deliberate
handling of the role-playing date columns, and no ambiguous paths.

---

## Verification

`Python/02_verify_semantic_model.py` compares the TMDL on disk against the live
SQL views and asserts the Phase 4 constraints. It is read-only and re-runnable.

Checks: table inventory, source binding, query thinness, column parity, data
types, relationship count, parameter definitions, and auto date/time removal.

**Result: 207 checks, 207 passed.**

---

# Measure Layer (Phase 6)

47 measures, all in a dedicated `_Measures` calculated table. None sit on fact
tables: a measure parked on `FactSalesOrders` implies it only concerns sales,
which stops being true the moment it references another table.

| Folder | Measures |
|---|---:|
| 01 Core KPIs | 7 |
| 02 Sales | 5 |
| 03 Inventory & Demand | 8 |
| 04 Procurement | 7 |
| 05 Logistics | 3 |
| 06 Delivery Performance | 10 |
| 07 Date Roles | 5 |
| 08 Model Controls | 2 |

Full detail in `Documentation/dax_measure_dictionary.md`, generated from the
TMDL so it cannot drift out of step with the model.

## There is no OTIF measure

Requirements 10, 13 and 17 of the brief specify OTIF. It is not calculable here.

Every quantity column in the model was examined: `Quantity` (ordered),
`QuantityOrdered`, `SafetyStockUnits`, `OnHandUnits`, `InboundUnits`,
`ActualDemandUnits`, `BaselineForecastUnits`. **Nothing records what was
actually delivered or received.**

"On Time" is measurable from promised versus actual dates. "In Full" requires
delivered quantity against ordered quantity, and delivered quantity does not
exist. `[On-Time Delivery %]` and `[On-Time Receipt %]` are named for what they
actually measure. Resolving this needs either a delivered-quantity column from
the client or an explicitly labelled proxy with the assumption stated on the page.

## The as-of date

`[As Of Date]` reads `ModelConfig` and parses the ISO text explicitly rather
than through locale-dependent `DATEVALUE`. `TODAY()` is never used for business
logic: today is already past the 2026-08-31 extract, so a system-date anchor
would reclassify in-flight orders as overdue and drift further every day.

## Semi-additive inventory

Summing `OnHandUnits` across all 105 snapshots returns **334,301,020** units — a
figure that existed at no point in reality — against **5,640,283** actually held.

Every current-inventory measure resolves one snapshot date and applies
`REMOVEFILTERS(DimDate)`. Measured: under a `Year = 2025` slicer, and even under
`Year = 2023` (before inventory history begins), `[Current On Hand Units]` holds
at 5,640,283. A date slicer cannot blank out current stock.

`[Current Inventory Value]` iterates at row grain via
`SUMX(FactInventorySnapshot, OnHandUnits * RELATED(UnitCost))`. Multiplying
total units by an average unit cost would be wrong across any product mix.

## Date-role measures — a defect found in validation

Evaluating every measure with no filters exposed a fault the filtered tests
could not have caught. `USERELATIONSHIP` swaps which relationship is active but
restricts nothing when no date filter is present, so every row counted whether
or not it held that date:

| Measure | Reported | Rows holding that date |
|---|---:|---:|
| Sales Orders by Scheduled Delivery Date | 80,000 | 435 |
| Purchase Orders by Scheduled Receipt Date | 25,000 | 368 |

Correct DAX, badly misleading number. All five now carry `NOT ISBLANK` on their
role column — a no-op under a date filter, and honest without one. Verified: the
global values became 79,565 / 80,000 / 435 / 24,632 / 368 while every value
under `Year = 2026` stayed identical.

## Validation

- `Python/03_verify_relationships.py` — 23 structural checks, 23 passed
- `Python/04_reconcile_measures.py` — **73 reconciliation checks against independently written SQL, 73 passed**
- `Python/05_generate_measure_dictionary.py` — regenerates the dictionary from TMDL

Reconciliation compares DAX against SQL, never against another DAX measure that
could share the same flawed assumption.
