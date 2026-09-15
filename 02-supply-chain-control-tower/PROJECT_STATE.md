# Project State — Supply Chain Control Tower

Lightweight change-control record. Updated at every phase boundary.

## Completed
- **Phase 1 — Environment & Project Setup.** Power BI Desktop 2.148.1477.0 (25.10), SQL Server 2025 Express 17.0.1000.7, SSMS 22.1.0, Python 3.13.3, DAX Studio 3.6.1.1250, Tabular Editor 2.28.0, Git 2.47.0. PBIP + TMDL + PBIR enabled.
- **Phase 2 — Data Audit.** 817,837 rows across 10 files. **6 ERROR, 0 ANOMALY, 7 EXCEPTION, 52 INFO.** See `Documentation/data_quality_report.md`.
- **Phase 3 — SQL Data Platform.** `SupplyChainBI` with `stg`/`dbo`/`analytics`. 817,837 rows loaded in 2.4 s. 25 foreign keys + 12 check constraints, all engine-trusted. 11 analytics views. **66 validation checks, 66 passed.** See `SQL/README.md`.
- **Phase 4 — Power Query / Connection Layer.** ✅ **SIGNED OFF.** 11 tables imported from `analytics.vw_*` in Import mode. **207 verification checks, 207 passed.**
- **Phase 5 — Semantic Model Architecture.** ✅ **SIGNED OFF.** 24 relationships (16 active, 8 inactive role-playing dates), 0 bidirectional, 0 fact-to-fact, 0 snowflake. DimDate marked as date table; 9 sort-by columns; 4 hierarchies; 23 technical columns hidden. **23 structural checks passed**, plus live filter-propagation and `USERELATIONSHIP` tests against the running model.
- **Phase 7A — Report Pages.** 7 pages, 119 visuals, generated as PBIR code and validated against the official Microsoft schemas.
- **Phase 8 — Replenishment & Stockout Risk.** ✅ **VALIDATED.** 17 measures + a ReplenishmentStatus dimension. **22 reconciliation checks against independent SQL, 22 passed.** See `Documentation/inventory_logic.md`.
- **Phase 9 — ABC/XYZ Inventory Strategy (Page 8).** ✅ **SIGNED OFF.** 103 live checks with Pages 7 and 9.
- **Phase 10 — Supplier Performance (Page 9).** ✅ **SIGNED OFF.** Three-component score, 45/35/20, four per-class line tests exact.
- **Phase 11 — Demand Forecasting (Page 10).** ✅ **SIGNED OFF.** 17 measures, 21 visuals, **30 live checks, 30 passed.** See `Documentation/forecast_logic.md`.
- **Phase 6 — Core DAX & Measure Layer.** ✅ **SIGNED OFF.** 47 measures in `_Measures` across 8 folders. **73 reconciliation checks against independently written SQL, 73 passed.** See `Documentation/dax_measure_dictionary.md`.

## Current
- **10 report pages, 282 visuals, 121 measures — all validated against the live model.**
  - 282 / 282 visuals return data (each visual's own query executed against the running model)
  - 121 / 121 measures evaluate without error (118 non-blank; 3 blank at the grand
    total by design, being per-row ranking and classification measures)
  - Pages 7/8/9: 103 / 103 value checks pass
  - Page 10: 30 / 30 value checks pass
  - Layout QA across all 10 pages: 0 overlaps, 0 out-of-canvas, 0 missing titles
  - Left navigation rebuilt: 10 buttons per page, 275 visuals total, 0 navigation issues

## Next
- Phase 14 Python forecasting (LightGBM / ETS) to produce a genuine forward
  horizon — Page 10 currently scores the supplied in-sample baseline only (D35).
- Confirm the page palette. The styling pass was done by hand in Power BI Desktop
  and then lost when the report generator was re-run over the edited files; there
  was no stash, no AutoRecovery and no other copy. It has been RECONSTRUCTED in
  `Python/06_generate_report.py` from the published screenshots (banner, per-page
  accent, slicer and KPI geometry). The colours are read off images, not the
  originals, and still need checking against them.
- Treat `PowerBI/` as hand-maintained from here on. Do not run
  `Python/06_generate_report.py` over it again without an explicit decision to do so.
- Phase 21 performance: `Supplier Rank` and `Product Revenue Rank` are correct
  but evaluate the full population per row and are not yet timed (Open Issue 9).

## Phase 4 measured results

### Row reconciliation — SQL view vs expected
| Table | Expected | Measured | Status |
|---|---:|---:|---|
| DimDate | 2,007 | 2,007 | PASS |
| DimProduct | 1,000 | 1,000 | PASS |
| DimSupplier | 120 | 120 | PASS |
| DimWarehouse | 6 | 6 | PASS |
| FactSalesOrders | 80,000 | 80,000 | PASS |
| FactPurchaseOrders | 25,000 | 25,000 | PASS |
| FactShipments | 80,000 | 80,000 | PASS |
| FactWeeklyDemand | 315,000 | 315,000 | PASS |
| FactInventorySnapshot | 315,000 | 315,000 | PASS |
| SecurityUserAccess | 7 | 7 | PASS |
| ModelConfig | (measure) | **6** | PASS |
| **Total** | | **818,146** | |

818,146 vs 817,837 source rows: +303 because `DimDate` is generated to 2,007 days
rather than the supplied 1,704, and +6 for `ModelConfig`, which has no CSV origin.

### Folding readiness — `SET STATISTICS IO`, window 2026-01-01 to 2026-09-01
| Table | Column | Rows full → filtered | Logical reads full → filtered |
|---|---|---|---|
| FactSalesOrders | OrderDate | 80,000 → 14,493 | 240 → **91** |
| FactWeeklyDemand | WeekStart | 315,000 → 105,000 | 1,253 → **460** |
| FactInventorySnapshot | SnapshotDate | 315,000 → 105,000 | 1,253 → **460** |

Read cost scales with rows returned, not table size — a seek, not a scan plus
filter. Proves the *database* side; Power Query emission is confirmed in Phase 21
via View Native Query.

## Key findings carried forward

### The as-of date: 2026-08-31
Latest transaction date across all facts. Every `Open` sales order (435) and
purchase order (368) is scheduled beyond it, and only those are. Stored in
`dbo.ModelConfig` and imported as the `ModelConfig` table so DAX reads it rather
than hard-coding. `GETDATE()` is never used for business logic.

**Open records must be excluded from OTIF** — not yet due, so scoring them
on-time or late is arithmetically wrong.

### The catalogue is not Pareto-distributed
513 of 1,000 products (51.3%) generate 80% of revenue. Textbook ABC thresholds
would place half the catalogue in class A. Disclose; do not engineer away.

### Demand variability is extremely narrow
Per-series CV runs p10 = 0.257 to p90 = 0.365. Textbook XYZ cut-offs (X < 0.5)
classify **100% of SKUs as X**. Use percentile terciles at 0.283 / 0.323.

### Baseline forecast benchmark — locked
**MAE 2.575 units, WAPE 13.04%, bias −2.52%.** Computed in Python (Phase 2),
independently re-derived in T-SQL (Phase 3) at the same 13.04%.

## Open Issues
| # | Issue | Impact | Status |
|---|-------|--------|--------|
| 1 | Calendar ended before the facts | RI blanks | **RESOLVED (P3)** — regenerated to 2027-06-30; 13 date FKs prevent recurrence |
| 2 | 500 of 1,000 products have no demand signal | Inventory/XYZ blank for half the catalogue | **RESOLVED (P3)** — `DimProduct.HasDemandSignal`; must be surfaced in the report |
| 3 | `fact_shipments` has no `ProductID` | Req 13 needs OTIF by product | **RESOLVED (P3)** — derived in `analytics.vw_Shipments` |
| 4 | `InboundUnits` max 29 vs on-hand max 4,186 | Inbound barely moves reorder logic | **Open** — document; do not compensate |
| 5 | Weekly demand totals 40.7× sales-order units | Independent series | **Open** — never present demand as derived from sales |
| 6 | Power BI Service licence tier unknown | Gates Phase 25 | **Open** — awaiting user |
| 7 | Money columns revert to `double` on refresh | Cosmetic; no precision risk at these magnitudes | **Accepted** — see D18; revisit in Phase 21 |
| 8 | Three evaluation-context defect families across 17 measures | Page 8 subtotals read 500; contribution read 100% per row; supplier scores blank | **RESOLVED & VALIDATED LIVE** — D30–D32; 103/103 checks pass |
| 10 | Reserved words `This` / `Visible` used as DAX VAR names | 17 measures failed to compile; 6 visuals had their bindings destroyed by Power BI | **RESOLVED & VALIDATED LIVE** — D33/D34; all 121 measures evaluate |
| 11 | Demand grew on 432 of 500 products, declined on 2 | The "Steepest Demand Decline" visual is legitimately near-empty | **Open — a finding, not a defect.** Document; do not tune the ±5% band to manufacture a balanced split |
| 12 | Forecast accuracy varies only 0.58pp across categories | The category chart is honest but low-contrast | **Open** — do not present any category as harder to forecast |
| 9 | `Supplier Rank` / `Product Revenue Rank` are O(n²) | Each rank evaluates the full population per row | **Open** — correct but not yet performance-tested; measure in Phase 21 |

## Decisions Log
| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Import mode, not DirectQuery | 816k rows compress small; DQ on Express would be slower and restrict DAX. Req 29 met by written evaluation. |
| D2 | Three SQL schemas | Text landing prevents load failures; views are the sole Power BI contract. |
| D3 | LightGBM + statsmodels ETS; **no Prophet** | 105 weekly points per series; intermittency 0.35%. |
| D4 | Calendar regenerated to 2027-06-30 | Covers furthest fact date, 13-week horizon, completes FY27. |
| D5 | Repo outside the dataset pack | Keeps the read-only pack pristine. |
| D6 | Raw CSVs committed; scaled files gitignored | Reproducibility without bloat. |
| D7 | Split `Actual*Date` into actual + scheduled | One column cannot mean both a fact and a forecast. |
| D8 | Derive OTIF in DAX, not from `DeliveryStatus` | The flag judges 435 deliveries that have not happened. |
| D9 | XYZ thresholds from CV percentiles | Textbook cut-offs classify everything as X. |
| D10 | `BULK INSERT`, not a Python loader | Server-side, no external runtime. |
| D11 | Lineage in `stg.LoadLog`, not per-row columns | Msg 7301; and 315,000 copies of one filename carry no information. |
| D12 | `ProductID` resolved in the shipments view | Keeps `dbo` normalised, presents Power BI a clean star. |
| D13 | `InventoryValue` dropped from `dbo` | Exactly derivable; removes a 237,846-cardinality column. |
| D14 | Completion derived from dates, not status labels | The date is the fact; the label describes it. Agreement then verified. |
| D15 | 13 date foreign keys to `DimDate` | The columns that overflowed were delivery/receipt dates, not order dates. |
| D16 | `ScheduledDeliveryDate` populated only while open | Avoids a column identical to `PromisedDeliveryDate` on 99.5% of rows. **User-approved.** |
| D17 | Page compression not applied | No benefit to an Import model; well inside the Express limit. |
| **D18** | **Money columns left as `double`** | Power BI reconciles column type to the M output on refresh, so Fixed Decimal reverts without an M cast. That cast carries unverified folding risk ahead of Phase 21 and buys no precision: values reach ~184,297 (7 significant digits) against a double's 15–17. Exact precision is held in SQL as `decimal(18,2)`. |
| **D19** | **Auto date/time disabled; 19 hidden tables removed** | It built one hidden calendar per date column — 19 tables, 18 relationships. `DimDate` already provides ISO weeks, financial year and sort keys they lack. Two competing calendars is worse than one good one. |
| **D20** | **Model edited by committed Tabular Editor script, not by hand** | TE owns TMDL serialisation, keeping file naming and references consistent. Every change is reviewable, repeatable and attributable. |
| **D21** | **Power Query kept to exactly two steps per table** | The SQL layer does all cleaning. Zero transformations keeps the folding surface maximal for incremental refresh. |

| **D22** | **No OTIF measure** | The model holds no delivered or received quantity - only ordered quantities and inventory/demand units - so "in full" cannot be demonstrated. `[On-Time Delivery %]` and `[On-Time Receipt %]` are named for what they actually measure. **Needs raising with the client:** the brief specifies OTIF in Requirements 10, 13 and 17. |
| **D23** | **All measures in `_Measures`, none on fact tables** | A measure parked on a fact table implies it concerns only that fact, which stops being true as soon as it references another. |
| **D24** | **Current inventory anchored to `[As Of Date]`, not to slicers** | `REMOVEFILTERS(DimDate)` on every current-inventory measure. Verified: holds at 5,640,283 under a Year=2023 slicer, before inventory history even begins. A period-relative variant is a separate, separately named measure for a later phase. |
| **D25** | **Date-role measures carry `NOT ISBLANK` on their role column** | Found in validation: `USERELATIONSHIP` restricts nothing without a date filter, so "Sales Orders by Scheduled Delivery Date" reported 80,000 against the 435 orders that hold one. No-op under a date filter, honest without one. |
| **D26** | **No currency symbol on money formats** | The source states no currency. `#,0.00` is used; a symbol can be applied project-wide once one is chosen. |

| **D27** | **Replenishment thresholds are absolute business rules, not fitted** | Each was fixed before counting what it would classify. 86.7% Overstock and 79.6% of value as excess are findings about the data, not artefacts of tuning. |
| **D28** | **Portfolio roll-ups iterate the product-warehouse grain** | Summing components first would compare a portfolio reorder point against a portfolio position, hiding all 178 line shortages inside the aggregate surplus. Verified additive across warehouses. |
| **D29** | **Supplied SafetyStockUnits used, not a statistical formula** | A statistical safety stock requires assuming a service level the dataset does not state. Recorded as a candidate refinement. |

| **D30** | **Class-membership measures test the visible class set, not `SELECTEDVALUE`** | `SELECTEDVALUE` returns BLANK whenever more than one value is in scope, which is exactly what a matrix subtotal is. The old fallback branch then counted the entire classified population, so every subtotal and the grand total read 500. Membership in `VALUES(ClassTable[Class])` is scope-aware by construction: `{AX}` in a cell, `{AX,AY,AZ}` on the A subtotal, all nine at the grand total. Applies to all 8 `at Class` / `at Status` measures. |
| **D31** | **Comparison populations use `ALLSELECTED(<table>)`, never `ALLSELECTED(<key column>)`** | The visuals group by `ProductName` / `SupplierName`, but the population was `ALLSELECTED(DimProduct[ProductID])`. Context transition re-applies only `ProductID`, so the row's `ProductName` filter survived and the population collapsed to the current row - every product showed 100% contribution and rank 1. Removing filters at table level lifts the visual's filters on every column while preserving outer slicer selections, which is the documented intent. |
| **D32** | **A filter modifier must wrap `ADDCOLUMNS`, not sit inside it** | `ADDCOLUMNS ( CALCULATETABLE ( VALUES(k), REMOVEFILTERS() ), "@V", [m] )` applies the modifier only to `VALUES(k)`; the extension column `[m]` is still evaluated in the outer context. Under a per-row filter 119 of 120 suppliers returned BLANK, so `Lo = Hi` and the min-max normalisation degenerated to `DIVIDE(0,0)` = BLANK - every supplier score went blank. Corrected to `CALCULATETABLE ( ADDCOLUMNS ( VALUES(k), "@V", [m] ), REMOVEFILTERS() )`. The same defect silently collapsed the XYZ P33/P66 thresholds to each row's own CV. |
| **D33** | **`This` and `Visible` are reserved and must never be DAX variable names** | The engine accepts them at write time - TMDL, Tabular Editor and JSON Schema all pass - and fails only when the model calculation script is COMPILED, reporting `MdxScript(Model) (345, 43) Failed to resolve name 'SYNTAXERROR'`. Every measure downstream of the offender inherits that error, which is why supplier visuals rendered blank rather than wrong. `This` came in with the Phase 10 NORM helper and had been latent since; `Visible` was introduced by the Phase 8/9 subtotal repair. Renamed to `Cur` and `ClassSet`, and the whole model is now swept for reserved-word VAR names. |
| **D34** | **Opening a report whose measures do not compile silently DESTROYS visual bindings** | Power BI Desktop dropped the unresolvable measure projections from six visuals, left `"projections": []` behind, and saved that to the PBIR files on disk. The blank charts the client saw were not a DAX symptom - the fields were physically gone. Lesson recorded as process: never open the .pbip until a full measure sweep proves every measure evaluates, and treat PBIR as regenerable from `Python/06_generate_report.py` rather than as hand-maintained state. |
| **D35** | **Page 10 reports forecast QUALITY, not a forward forecast** | `FactWeeklyDemand` holds 105 weeks ending exactly at the as-of date with ZERO weeks beyond it, so `BaselineForecastUnits` is a supplied in-sample baseline, not a projection. Every Page 10 visual scores the baseline against actuals that exist; nothing is captioned as a prediction. A genuine forward forecast requires the Python modelling phase (D3) and is not fabricated to fill the page. |
| **D36** | **WAPE, not MAPE, is the headline forecast accuracy metric** | 1,096 product-weeks carry zero actual demand, where MAPE is undefined, and many more carry single digits, where it explodes. A MAPE here would describe intermittency rather than forecast quality. WAPE divides one total by another, stays defined, and weights each product-week by volume. MAE is published alongside because a percentage hides how small these weekly quantities are (2.57 units). |
| **D37** | **The built-in `pageNavigator` replaced by ten explicit `actionButton` visuals** | One `pageNavigator` was asked to lay out ten pages inside a 132 px rail, so it compressed each entry to roughly 13 px and rendered them as unreadable vertical slivers. The visual has no per-button control worth relying on at that width. Ten explicit buttons give fixed 148x38 geometry, horizontal labels, an explicit selected state, and a target page that can be asserted in a test. The rail widened 132 -> 168 px and all content shifted right with it, since every page derives its geometry from `CX`/`CW`. |
| **D38** | **Navigation lives in `visualContainerObjects.visualLink`, not on `visual`** | The first attempt put `visualLink` directly on `visual` and JSON Schema validation rejected it — `visualConfiguration/2.2.0` allows only visualType, autoSelectVisualType, query, expansionStates, objects, visualContainerObjects, syncGroup and drillFilterOtherVisuals. `visualLink` is a container formatting object: an array of `{selector?, properties}` whose properties are `show`, `type` and `navigationSection`. Unlike the `SourceRef` incident, the schema caught this one before it ever reached Power BI. |

## Honesty Register
| Item | Status | Evidence |
|------|--------|----------|
| Environment versions | **Verified** | Registry and `--version` |
| Python → SQL connection | **Verified** | Live `pyodbc` connect |
| Data audit findings | **Verified** | `Python/01_data_audit.py` |
| Baseline forecast accuracy | **Verified** | Python, re-derived in T-SQL |
| SQL load 817,837 rows / 2.4 s | **Verified** | `stg.LoadLog` |
| 66 SQL validation checks | **Verified** | `SQL/08_validation.sql` |
| 207 model verification checks | **Verified** | `Python/02_verify_semantic_model.py` |
| TMDL validity after transform | **Verified** | Reloaded by Tabular Editor + BPA clean |
| SQL-side seek on date ranges | **Verified** | `SET STATISTICS IO` |
| **Power Query emits the folded WHERE** | **NOT yet verified** | Requires View Native Query; Phase 21 |
| **Imported row counts in the model** | **Verified (Phase 5)** | Measured against the live model via DMV: 818,146 rows, matching SQL exactly |
| 47 measures reconciled to SQL | **Verified** | `Python/04_reconcile_measures.py` — 73 checks, 73 passed, against independently written SQL |
| Semi-additive inventory anchoring | **Verified** | Holds at 5,640,283 under Year=2025 and Year=2023 slicers |
| Date-role fix | **Verified** | Global values corrected to 79,565 / 80,000 / 435 / 24,632 / 368; Year=2026 values unchanged |
| **True OTIF** | **NOT possible** | No delivered or received quantity exists in the source. Not claimed anywhere. |
| Page 8 / 9 expected values | **Verified (SQL side only)** | Derived independently in `Validation/expected_*.sql`: ABC 512/279/209 at 79.99/14.98/5.04%; XYZ 167/166/167 + 500 unclassified; P33 0.129674, P66 0.170917; matrix 87/80/93, 47/51/43, 33/35/31 summing to 500; suppliers 9/32/63/16 at 6.65/25.48/55.57/12.30% of spend |
| **Page 8 / 9 DAX reproduces those values** | **Verified live** | `Validation/validate_pages_7_8_9.ps1` executed against the running model: **103 checks, 103 passed** — ABC 512/279/209, XYZ 167/166/167, matrix subtotals 260/141/99 and 167/166/167, grand total 500, suppliers 9/32/63/16, four per-class line tests exact. |
| **Page 9 visual failures** | **Resolved and confirmed** | Root cause was D33/D34, not evaluation context: reserved-word VAR names stopped the measures compiling, and Power BI then stripped the bindings from 6 visuals. Bindings regenerated; **175 of 175 visuals across all 10 pages return data**. |
| **All 121 measures evaluate without error** | **Verified live** | Every measure queried individually against the running model: 118 non-blank, 3 legitimately blank at the grand total (per-product measures), 0 errors. |
| **Page 10 forecasting figures** | **Verified live** | `Validation/validate_page_10.ps1`: **30 checks, 30 passed**, against `Validation/expected_forecast.sql`. WAPE 13.0408%, accuracy 86.9592%, bias −2.518%, MAE 2.574784, growth +14.4696%, 432/2/66 reconciling to 500. |
| **A forward demand forecast** | **NOT possible from this data** | `FactWeeklyDemand` stops at the as-of date; there are zero future weeks. Page 10 scores a supplied in-sample baseline and claims nothing more. See D35 and `Documentation/forecast_logic.md`. |
| **Left navigation sidebar** | **Verified structurally, live-loaded** | `Validation/validate_navigation.py`: 10 pages x 10 buttons, correct order and labels, every `navigationSection` resolves to the right page, exactly one selected button per page matching that page, geometry within brief, 0 overlaps, 0 off-canvas, 0 legacy `pageNavigator` left. Power BI Desktop opened the report and rewrote **0** of 275 visual.json files, and all 100 buttons retained their `visualLink`. |
| **Navigation buttons actually change page when clicked** | **NOT verified** | The link is structurally correct and Power BI preserved it, but no click was performed. This needs one manual click-through. |
| **Rendered pixel appearance** | **NOT verified** | Validation is by executing each visual's own query against the live model and by geometry checks on the PBIR. No screenshot was taken and no rendered image was inspected. |
| Indexes speeding up Power BI refresh | **Explicitly NOT claimed** | Import refresh scans |
| Dataset provenance | **Synthetic** | Recorded in `dbo.ModelConfig` |
| Incremental refresh | **Planned** | Phase 21 |
| Replenishment measures | **Verified** | 22 checks against independent SQL, 22 passed |
| Page 7 rendering | **NOT yet verified** | Generated and committed; needs visual confirmation |
| Pages 8, 9, 10 | **Not built** | Require ABC/XYZ, supplier score, and the Python forecasting pipeline |
| Power BI Service deployment | **Planned** | Blocked on licence |
