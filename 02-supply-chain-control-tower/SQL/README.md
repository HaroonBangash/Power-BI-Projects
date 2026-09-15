# SQL Data Platform — `SupplyChainBI`

The relational layer beneath the Supply Chain Control Tower. It ingests ten source
CSVs, types and validates them, resolves two genuine modelling problems in the
source data, and exposes a stable contract that Power BI consumes.

---

## Architecture

```
Data/Raw/*.csv
      │  BULK INSERT
      ▼
   stg.*          Raw landing. Every column nvarchar(4000).
      │           Nothing is rejected; ingestion and validation stay separate.
      │  TRY_CONVERT + business rules
      ▼
   dbo.*          Typed, keyed, constrained core. 25 foreign keys,
      │           12 check constraints, all engine-trusted.
      │  thin projections
      ▼
 analytics.vw_*   The ONLY objects Power BI is permitted to consume.
      ▼
   Power BI
```

**Why three layers.** Staging absorbs whatever the file contains, so a malformed
value never blocks a load. `dbo` is the trusted relational truth. The view layer
decouples the report from the tables: a column can be renamed or retyped in `dbo`
and absorbed by editing one view, without the semantic model or any report page
noticing. Pointing Power BI at `dbo` directly would make every physical change a
breaking change.

---

## Environment

| Item | Value |
|---|---|
| Instance | `.\SQLEXPRESS` |
| Version | SQL Server 2025 RTM 17.0.1000.7, Express Edition |
| Database | `SupplyChainBI` |
| Recovery model | SIMPLE |
| Collation | `SQL_Latin1_General_CP1_CI_AS` |
| Authentication | Windows only |
| Size after load | 200 MB data, 136 MB log |

Express caps a database at 10 GB and the buffer pool at roughly 1.4 GB. Neither
binds at this volume, but any performance figure measured here is
Express-constrained and must be reported as such.

---

## Execution order

Run in sequence. Each script is idempotent and safe to re-run.

| # | Script | Purpose |
|---|---|---|
| 01 | `01_create_database.sql` | Database, three schemas, `dbo.ModelConfig`, `stg.LoadLog` |
| 02 | `02_create_staging_tables.sql` | Ten landing tables mirroring the CSVs |
| 03 | `03_load_data.sql` | `BULK INSERT` all files, audit each load |
| 04 | `04_create_core_tables.sql` | Typed core tables with primary keys |
| 05 | `05_transform_and_clean.sql` | Type, clean, generate the calendar, split the ambiguous dates |
| 06 | `06_create_views.sql` | Eleven `analytics.vw_*` views |
| 07 | `07_indexes_and_constraints.sql` | 25 foreign keys, 12 check constraints, 12 indexes |
| 08 | `08_validation.sql` | 66 checks and the phase quality gate |

```powershell
# From the repository root
$i = ".\SQLEXPRESS"
# The path must be readable by the SQL Server service account, and the quotes must
# be INSIDE the argument - sqlcmd rejects -v DataRoot=<path with spaces> otherwise.
$arg = 'DataRoot="' + (Resolve-Path .\Data\Raw).Path + '"'
Get-ChildItem SQL\0*.sql | Sort-Object Name | ForEach-Object {
    Write-Host "--- $($_.Name)"
    sqlcmd -S $i -E -C -b -i $_.FullName -v $arg
    if ($LASTEXITCODE -ne 0) { throw "Failed: $($_.Name)" }
}
```

`DataRoot` is read by `03_load_data.sql`; the other scripts ignore it. No
machine-specific path is committed to the repository.

Verified from a clean rebuild: 10 files, 817,837 rows, 0 untrusted constraints,
66 / 66 validation checks pass.

---

## Load method

Native `BULK INSERT`, chosen over an external Python loader because it is
server-side, needs no runtime outside SQL Server, and keeps ingestion in the SQL
scripts where a reviewer expects it. Python is reserved for forecasting, where it
earns its place.

**The path is server-side.** `BULK INSERT` resolves paths on the SQL Server host,
not the client. The service account `NT Service\MSSQL$SQLEXPRESS` must be able to
read the source directory. `03_load_data.sql` takes that directory as the sqlcmd
variable `DataRoot`, so the one machine-specific value in the entire SQL layer is
supplied at run time rather than committed.

Per-row lineage columns were considered and rejected. `BULK INSERT` cannot
populate them without a format file per table — verified, it raises *Msg 7301
"Cannot obtain the required interface IID_IColumnsInfo"* — and stamping the same
file name onto 315,000 identical rows carries no information. Lineage is recorded
once per load in `stg.LoadLog`, which is also what the reconciliation report reads.

Full load: **817,837 rows in 2.4 seconds**, ten files, zero failures.

---

## The as-of date

`dbo.ModelConfig` holds `AsOfDate = 2026-08-31`. It is the latest date on which
any transaction was raised, and therefore the date the extract was taken.

This is not a convenience constant. Every `Open` record in the source — 435 sales
orders and 368 purchase orders — is scheduled beyond it, and **only** those
records are. Status is a deterministic restatement of "scheduled in the future".

`GETDATE()` is deliberately never referenced anywhere in this layer. Today is
already later than the extract, so a system-date rule would reclassify every
in-flight order as overdue, and would drift further every day the report is
opened. A fixed anchor keeps results reproducible.

Other configuration values: `CalendarStartDate`, `CalendarEndDate`,
`ForecastHorizonWeeks`, `FinancialYearStartMonth`, `DatasetProvenance`.

---

## Transformation rules

### Splitting the ambiguous date columns

The source stores one column that means two different things. `ActualDeliveryDate`
holds a real delivery date on completed orders and a forward expectation on open
ones. Left alone it would silently corrupt every on-time metric built on it.

Each is split into two columns that are mutually exclusive by construction:

| Source column | Becomes | Populated when |
|---|---|---|
| `fact_sales_orders.ActualDeliveryDate` | `ActualDeliveryDate` | delivered on or before the as-of date |
| | `ScheduledDeliveryDate` | still open |
| `fact_purchase_orders.ActualReceiptDate` | `ActualReceiptDate` | received on or before the as-of date |
| | `ScheduledReceiptDate` | still open |
| `fact_shipments.DeliveryDate` | `ActualDeliveryDate` | delivered |
| | `ScheduledDeliveryDate` | in transit |

`CK_*_DateExclusivity` enforces the invariant at database level, so
`COALESCE(Actual, Scheduled)` always yields the best known date and neither
column is ever ambiguous.

**A deliberate departure from the original specification.** The brief asked for
`ScheduledDeliveryDate` to be populated for delivered orders too, sourced from
the promised date. That would make it an exact copy of `PromisedDeliveryDate` on
99.5% of rows — a redundant column, which the same brief asks us to avoid.
Populating it only while the record is open keeps every column meaning exactly
one thing. Easily reversed if the original behaviour is preferred.

### Completion is derived from dates, not status labels

`IsDelivered`, `IsOpenOrder`, `IsReceived` and `IsOpenPO` are computed by
comparing dates to the as-of date rather than by reading `OrderStatus`. The date
is the physical fact; the status is a label describing it. Script 08 then verifies
the two agree — across all 105,000 sales and purchase orders, **zero
disagreements**. Had they diverged, that would be a finding rather than something
silently absorbed.

### Consequence for OTIF

Open records must be excluded from on-time calculations. An order due next week is
neither on-time nor late — it is not yet due. `IsDelivered` / `IsReceived` are the
flags that make the exclusion explicit in DAX. `DeliveryDelayDays` and
`ActualLeadTimeDays` are left NULL on open records: zero would understate
lateness, and a negative would invent earliness.

### The calendar is regenerated, not imported

The supplied `dim_date.csv` ends at 2026-08-31, but fact dates reach 2026-10-07.
Importing it would leave 1,938 fact rows unable to join, surfacing in Power BI as
unexplained blanks.

`dbo.DimDate` is generated from a tally over `ModelConfig` boundaries, spanning
**2022-01-01 to 2027-06-30** (2,007 days). That end date covers the furthest fact
date, the 13-week forecast horizon, and completes FY27 on a July–June financial
year.

ISO handling is `@@DATEFIRST`-independent: `1900-01-01` was a Monday, so
`(DATEDIFF(day, '1900-01-01', d) % 7) + 1` yields 1 for Monday through 7 for
Sunday regardless of session settings. The ISO year is the year of the Thursday
in the same ISO week. The generated calendar correctly produces **ISO week 53 at
the 2026/27 boundary** — a case the supplied calendar never had to face because
it stopped in August.

### Resolving the shipment ProductID

`fact_shipments` carries no `ProductID`, yet OTIF and freight must be analysable
by product and category. Three options were weighed:

| Option | Verdict |
|---|---|
| Bidirectional filter `DimProduct → FactSalesOrders → FactShipments` | Rejected — ambiguous filter paths, documented anti-pattern |
| Store `ProductID` physically on `dbo.FactShipments` | Rejected — duplicates data the relational model already holds |
| **Resolve it in `analytics.vw_Shipments`** | **Chosen** |

`dbo` stays normalised while Power BI is presented a clean star: a direct
`DimProduct → FactShipments` relationship, single-direction, no ambiguity. The
`INNER JOIN` is provably safe because `FK_FactShipments_SalesOrder` guarantees
every shipment has a parent order. Script 08 verifies the row count regardless —
80,000 in, 80,000 out, 1,000 distinct products resolved.

The view also carries `PromisedDeliveryDate` across, because carrier on-time
performance cannot be measured without the commitment and the shipment fact has
no promise date of its own.

### InventoryValue is dropped

It equals `OnHandUnits × UnitCost` on all 315,000 rows with **zero deviation**, so
it is fully recoverable from `DimProduct`. Carrying it would hand VertiPaq a
237,846-distinct-value column to compress in exchange for information the model
already holds. The raw value stays in `stg` and script 08 re-proves the identity
against it — the claim is verified, not assumed.

### Derived attributes

| Column | Table | Rationale |
|---|---|---|
| `HasDemandSignal` | `DimProduct` | Only 500 of 1,000 products have inventory or demand history. Flagged, not hidden. |
| `Region` | `DimWarehouse` | Derived grouping over the four source countries; supports the Region → Warehouse → Category → SKU drill. Not source data. |
| `IsAllWarehouses` | `SecurityUserAccess` | Turns the literal `'ALL'` sentinel into an explicit boolean so the RLS predicate is a flag test, not a magic string. |
| `PurchasePriceVariance` | `vw_PurchaseOrders` | `POValue` genuinely diverges from `QuantityOrdered × UnitCost` on 24,998 of 25,000 rows. That divergence is real purchase price variance. |

---

## Where logic lives

| Layer | Owns | Because |
|---|---|---|
| **SQL** | Typing, cleaning, date splitting, delay-day arithmetic, status normalisation, referential validation | Stable row-level facts that never vary with filter context |
| **Power Query** | Thin passthrough only | Anything heavier breaks folding |
| **DAX** | OTIF %, turnover, ABC, XYZ, supplier score, stockout risk, forecast accuracy, all time intelligence | Must respond dynamically to filter context |
| **Python** | Demand forecasting | Prediction, not aggregation |

No KPI is pre-computed in SQL. Fixing ABC classes in the database would freeze
them against whatever filters the user applies, which defeats the purpose.

---

## Indexes

Twelve non-clustered indexes.

**They do not speed up Power BI refresh.** An Import-mode refresh scans each table
once, and no index improves a scan. Claiming otherwise in documentation would be
false. They exist for foreign key validation, the Python forecasting extract,
ad-hoc SQL analysis, and any future DirectQuery evaluation.

| Index | Purpose |
|---|---|
| `IX_FactSalesOrders_OrderDate` | Incremental-refresh partition column. Covering, so a `RangeStart`/`RangeEnd` predicate seeks rather than scans — measured at **37 logical reads** for a three-month range over 80,000 rows |
| `IX_FactPurchaseOrders_Supplier` | Covering index for supplier scorecard aggregation |
| `IX_FactShipments_SalesOrder` | Supports the `vw_Shipments` join and its foreign key |
| `IX_FactWeeklyDemand_Series` | Inverts the clustered key order to serve per-series reads by the forecasting extract |
| `IX_FactInventorySnapshot_Series` | As above, for inventory history |
| Remaining | Foreign key support on dimension columns |

Page compression was considered and not applied. It would reduce storage and I/O
but delivers nothing to an Import-mode model, and the database is comfortably
inside the Express size limit.

---

## Validation

`08_validation.sql` runs **66 checks** across eleven sections and ends with an
explicit gate.

| Section | Checks |
|---|---|
| Reconciliation | 30 |
| Sales date logic | 6 |
| Date dimension | 6 |
| Purchase date logic | 5 |
| Primary keys | 4 |
| Referential integrity | 4 |
| As-of logic | 3 |
| Weekly demand | 3 |
| Inventory | 2 |
| Security | 2 |
| Product coverage | 1 |

Reconciliation is four-way: **independent source count → staging → core → view**.
The expected counts come from `Python/01_data_audit.py` reading the CSVs with
pandas. Using an independent count matters — reconciling the load against itself
would prove nothing.

Two checks are worth singling out. Foreign keys are tested for being **trusted**,
not merely present: a constraint created `WITH NOCHECK` guarantees nothing about
existing rows. And the baseline forecast WAPE is re-derived in SQL, returning
**13.04%** against the Python figure of 13.04% — two engines, one answer,
confirming the Phase 14 benchmark survived the load untouched.

**Result: 66 passed, 0 failed.**

---

## Power BI connection contract

| Setting | Value |
|---|---|
| Connector | SQL Server database |
| Server | `.\SQLEXPRESS` |
| Database | `SupplyChainBI` |
| Mode | Import |
| Objects | `analytics.vw_*` **only** |
| Authentication | Windows |

Do not connect to `stg` or `dbo`. The views are the contract; everything behind
them is free to change.

Eleven views: `vw_DimDate`, `vw_DimProduct`, `vw_DimSupplier`, `vw_DimWarehouse`,
`vw_SalesOrders`, `vw_PurchaseOrders`, `vw_Shipments`, `vw_WeeklyDemand`,
`vw_InventorySnapshot`, `vw_SecurityUserAccess`, `vw_ModelConfig`.

### Folding readiness

Views are thin projections — no window functions, no scalar UDFs, no aggregation
— so Power Query can push filters straight through. Candidate incremental-refresh
partition columns are plain `date` columns on the base tables with no expression
wrapped around them:

| View | Column |
|---|---|
| `vw_SalesOrders` | `OrderDate` |
| `vw_WeeklyDemand` | `WeekStart` |
| `vw_InventorySnapshot` | `SnapshotDate` |

Incremental refresh is **not** configured yet — that is Phase 21. This layer only
guarantees it will fold when it is.

---

## Known constraints

- **The dataset is synthetic.** `ModelConfig.DatasetProvenance` records this. It must never be presented as real client data.
- **`BULK INSERT` paths are server-side**, so the load scripts are inherently machine-specific. `@SourceRoot` isolates that to one line.
- **Express Edition** caps the database at 10 GB and the buffer pool at ~1.4 GB. Any timing measured here is Express-constrained.
- **Half the catalogue has no demand signal** — 500 of 1,000 products carry no inventory or demand history. `HasDemandSignal` exposes this rather than hiding it.
- **`InboundUnits` maxes at 29** against on-hand reaching 4,186, so inbound stock barely moves reorder arithmetic. A characteristic of the dataset, documented rather than compensated for.
- **Weekly demand and sales orders are independent series** — demand totals 40.7× sales-order units over the shared window. Demand must never be presented as derived from sales.
