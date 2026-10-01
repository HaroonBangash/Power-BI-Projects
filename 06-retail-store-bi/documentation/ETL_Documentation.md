# ETL & Data Quality Documentation

## 1. Source inspection (Phase 1)

| Item | Finding |
|---|---|
| Workbook | `ICT701 Assignment1_RetailStore_Dataset (1).xlsx` |
| Sheets | `Data Description` (attribute dictionary, 3 branches × 3 months, Jan–Mar 2022) and `RetailStore Dataset ` (**note the trailing space in the sheet name**) |
| Rows × columns | 1,000 data rows × 17 columns (header in row 1) |
| Nulls / blank rows | 0 nulls in every column; 0 fully blank rows |
| Fully duplicated rows | 0 |
| Invoice ID | **Not unique**: 575 distinct values over 1,000 rows; 298 IDs repeat (up to 6 times) |
| Categorical text | No leading/trailing spaces or casing variants. Branch (X 340, Y 332, Z 328), City (Geelong, Melbourne, Ballarat; 1:1 with Branch), Customer type (Member 501, Normal 499), Gender (Female 501, Male 499), 6 product lines, 3 payment methods |
| Date | **Mixed types**: 413 true Excel dates + 587 text strings (`M/d/yyyy`) |
| Time | 1,000 true time values, 10:00–20:59, no seconds |
| Numeric types | Unit price, Tax, Total, cogs, gross income and Rating mix int/float storage (cosmetic only) |
| Ranges | Unit price 10.58–100.46; Quantity 1–10; Total 11.18–1,047.65; Rating 4.0–10.0. Unit price, Quantity and Rating have no IQR outliers; Total has 9 high-value IQR outliers, which are genuine large baskets (high price × high quantity) and are retained |
| gross margin percentage | Constant 4.761904762 for every row |

Profile output: [`outputs/data_quality_profile.csv`](../outputs/data_quality_profile.csv). Script: [`scripts/01_profile_and_clean.py`](../scripts/01_profile_and_clean.py).

### 1.1 The date problem (most important issue)
The 413 true date cells have **day and month swapped**. For example, `2022-05-01` (1 May) is really 5 January. Evidence:
* every true-date cell has a "day" of 1, 2 or 3 and a "month" of 1–12. That is the signature of `d/m` text being parsed as `m/d`;
* after swapping, all 413 dates fall inside 1 Jan – 30 Mar 2022, exactly the period stated on the Data Description sheet;
* the 587 text cells are unambiguous US `M/d/yyyy` strings (e.g. `1/27/2022`).

After repair, the data spans **1 Jan 2022 – 30 Mar 2022, 89 distinct trading days** (31 Jan + 28 Feb + 30 Mar; no sales recorded on 31 Mar).

### 1.2 The Invoice ID problem
Repeated Invoice IDs never share the same branch, date and time (0 of 298 groups), so they are **not** multi-line baskets. They are recycled or anonymised IDs on unrelated transactions. Removing "duplicate" invoice IDs would have deleted 425 legitimate transactions. Decision:
* keep all 1,000 rows;
* create a surrogate key `SalesKey` (source row order);
* count transactions with `COUNTROWS(FactSales)`, never `DISTINCTCOUNT(Invoice ID)`. The distinct count (575) is kept only as a data-quality measure.

### 1.3 Arithmetic integrity checks (all rows verified)
| Rule | Result |
|---|---|
| Tax = 5% × Unit price × Quantity | true for 1,000/1,000 |
| COGS = Quantity × (Unit price − 0.025) | true for 1,000/1,000 (the source applies a fixed 2.5¢ per-unit reduction) |
| Total = COGS + Tax | true for 1,000/1,000 |
| gross income = Tax | true for 1,000/1,000 |
| gross income ÷ Total = stated gross margin % | **false**: the actual ratio ranges 4.7630%–4.7726%, not the constant 4.7619% |

Consequences: the source `gross margin percentage` column is dropped and Gross Margin % is recalculated as a DAX measure. Gross income is reported **as supplied**. Its being equal to the tax amount is documented as a dataset limitation; values are not altered.

## 2. ETL flow (Power Query, Phase 2)

```
Excel workbook ──► Raw_RetailSales ──► Stg_RetailSales ──► DimDate / DimTime / DimBranch / DimProduct /
 (source)           (raw, not loaded)    (clean, not loaded)     DimCustomer / DimPayment ──► FactSales ──► measures ──► report
outputs/model_results.csv ─► Src_ClusterAssignments ─┘ (merged into FactSales as ClusterKey)
outputs/cluster_profiles.csv ─► DimCluster      outputs/cluster_evaluation.csv ─► ClusterEvaluation
```

All queries live in the semantic model ([`expressions.tmdl`](../RetailStore_BI.SemanticModel/definition/expressions.tmdl) and each table's partition in `definition/tables/*.tmdl`). Parameter `ProjectFolder` holds the folder path.

### Stg_RetailSales: applied steps
| # | Step | Purpose |
|---|---|---|
| 1 | `TrimmedHeaders`, `RenamedColumns` | Standardise column names (e.g. `Tax 5%` → `Tax`, `Total` → `TotalSales`, `cogs` → `COGS`) |
| 2 | `RemovedBlankRows` | Defensive rule; removes nothing in the supplied file |
| 3 | `AddedSalesKey` | Surrogate key in source row order (also the join key for K-Means results) |
| 4 | `RemovedExactDuplicates` | `Table.Distinct` on all source columns: removes only genuine duplicates (0 found); repeated Invoice IDs are preserved |
| 5 | `CleanedText` | Trim + consistent casing (Branch upper, City proper, other categories sentence case) |
| 6 | `FixedDate` | Swap day/month for true-date cells; parse text with `M/d/yyyy`, en-US |
| 7 | `FixedTime` | Convert any time representation (time / datetime / number / text) to `time` |
| 8 | `Typed` | Fixed-decimal currency for money columns, Int64 quantity, decimal rating |
| 9 | `AddedDateKey`, `AddedHourKey` | Conformed keys (`yyyymmdd`, hour 0–23) |

### Dimension and fact build
* **Dimensions** are `Table.Distinct` projections of the staging query, sorted, with integer surrogate keys (`Table.AddIndexColumn`). DimDate is generated as a contiguous calendar from the first to the last month of sales (90 days). DimTime is generated for hours 0–23 with Time-of-Day bands.
* **FactSales** resolves every surrogate key with left-outer merges to the dimensions. It merges the K-Means cluster on `SalesKey` **and** `Invoice ID`, an integrity check that the cluster file lines up with the source rows. It then keeps only keys and additive measures.

### Time-of-day definition (documented banding)
Store trading hours are 10:00–21:00 (Data Description). Bands: **Morning 10:00–11:59** (2 h), **Afternoon 12:00–16:59** (5 h), **Evening 17:00–20:59** (4 h). Because band lengths differ, compare bands using hourly transactions as well as totals; the report shows both.

## 3. Reconciliation (no accidental row loss, no fabricated data)
These figures were checked in the refreshed Power BI model with DAX queries run against Power BI Desktop's engine. They match the independent Python recalculation ([`outputs/kpi_validation.csv`](../outputs/kpi_validation.csv)) exactly:

| Check | Python | Power BI |
|---|---|---|
| FactSales rows | 1,000 | 1,000 |
| Rows with an unmatched key (date, branch, product, customer, payment, cluster, time) | 0 | 0 |
| Total Sales | 325,721.749 | 325,721.749 |
| Total Gross Income | 15,517.119 | 15,517.119 |
| Total COGS | 310,204.630 | 310,204.630 |
| Quantity | 5,510 | 5,510 |
| Average Rating | 6.9727 | 6.9727 |
| Jan / Feb / Mar sales | 117,274.37 / 98,046.37 / 110,401.01 | identical |
| DimDate range | – | 1 Jan 2022 – 31 Mar 2022 (90 days) |
