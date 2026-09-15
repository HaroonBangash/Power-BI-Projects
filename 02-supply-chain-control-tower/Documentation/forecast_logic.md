# Demand Forecasting Logic — Page 10

Every number in this document was measured. The SQL that produces the expected
values is `Validation/expected_forecast.sql`; the live check against the model is
`Validation/validate_page_10.ps1` (30 checks, 30 passed).

---

## 1. What the data actually contains

| Fact | Value |
|------|-------|
| Table | `FactWeeklyDemand` |
| Grain | product × warehouse × week |
| Rows | 315,000 |
| Weeks | 105 |
| Range | 2024-09-02 → 2026-08-31 |
| Products | 500 (of 1,000 in the catalogue) |
| Nulls in `ActualDemandUnits` / `BaselineForecastUnits` | 0 |
| Product-weeks with zero actual demand | 1,096 |
| **Weeks beyond the as-of date** | **0** |

### The honest statement about "forecast"

`BaselineForecastUnits` is a **supplied in-sample baseline forecast**. It exists
for the same historical weeks as the actuals and stops at the as-of date. It is
**not a forward projection**, and the dataset contains no future period.

Page 10 therefore measures **forecast quality against actuals that exist**. No
visual on the page projects beyond 2026-08-31, and no visual is captioned as if
it did. Producing a genuine forward forecast requires the Python modelling phase
(LightGBM / ETS per D3); until that runs, nothing on this page should be
presented to a client as a prediction of future demand.

The 500 products with no demand history at all remain out of scope here for the
same reason they are Unclassified in XYZ — see `inventory_logic.md`.

---

## 2. Why WAPE and not MAPE

MAPE divides the absolute error by the actual. 1,096 product-weeks have zero
actual demand, where that division is undefined, and many more have single-digit
demand, where it explodes. A MAPE on this dataset would be a statement about
**intermittency**, not about forecast quality.

**WAPE** divides one total by another:

```
Forecast WAPE = SUM( |actual - forecast| ) / SUM( actual )
```

It stays defined, and it weights each product-week by its volume, so a 2-unit
miss on a high-volume line counts for more than a 2-unit miss on a line that
barely moves. `Forecast Accuracy %` is simply `1 - WAPE`.

MAE is reported alongside because a percentage on its own hides how small these
weekly quantities are — the average absolute error is **2.57 units per
product-week**.

---

## 3. Measured results

### Headline forecast quality

| Metric | Value |
|--------|-------|
| Actual demand | 6,219,403 units |
| Baseline forecast | 6,062,796 units |
| **WAPE** | **13.0408 %** |
| **Forecast accuracy (1 − WAPE)** | **86.9592 %** |
| Forecast bias | **−156,607 units (−2.518 %)** |
| MAE | 2.574784 units per product-week |
| Over-forecast product-weeks | 112,853 |
| Under-forecast product-weeks | 157,393 |
| Weeks of history | 105 |

**Reading it.** The baseline runs slightly *low*: it under-forecasts on 157,393
product-weeks against 112,853 over-forecasts, and the signed bias is −2.5 %.
Bias and WAPE are deliberately reported as separate measures — a forecast can be
wrong every single week and still show almost no bias if the misses offset, so
one number cannot stand in for the other.

### Demand growth, 13 weeks vs the preceding 13

| Metric | Value |
|--------|-------|
| Recent 13 weeks | 723,181 units |
| Prior 13 weeks | 631,767 units |
| Portfolio growth | **+14.4696 %** |
| Growing products (> +5 %) | 432 |
| Declining products (< −5 %) | 2 |
| Stable products (within ±5 %) | 66 |
| Reconciliation | 432 + 2 + 66 = **500** ✓ |

**A finding, not a defect.** The split is extremely lopsided: 432 of 500 products
grew by more than 5 % while only 2 declined. Demand rose broadly across the
portfolio in the final quarter of the dataset. This is a property of the
synthetic data and should be stated plainly rather than smoothed — a "declining
products" visual on this dataset will legitimately be near-empty.

The ±5 % band is an absolute business rule fixed before counting how many
products it would classify, consistent with D27.

### Forecast accuracy by category

| Category | Accuracy | Actual units |
|----------|----------|--------------|
| Outdoor | 87.2837 % | 855,562 |
| Electronics | 87.0453 % | 1,167,007 |
| Industrial | 87.0398 % | 917,726 |
| Personal Care | 87.0121 % | 793,737 |
| Office | 86.8522 % | 822,737 |
| Home | 86.7239 % | 791,483 |
| Automotive | 86.7072 % | 871,151 |

The spread is only **0.58 percentage points** across all seven categories. The
category chart is honest but low-contrast: no category is meaningfully harder to
forecast than another, and it should not be presented as if one were.

---

## 4. Window definitions

Both growth windows are anchored to `[As Of Date]` and wrapped in
`REMOVEFILTERS ( DimDate )`, exactly like the replenishment and ABC/XYZ layers.
A user changing a date slicer does **not** move the comparison windows — the
growth figure always means "the last 13 weeks against the 13 before them".

```
Recent 13W Demand : WeekStart > AsOf - 91  and WeekStart <= AsOf
Prior  13W Demand : WeekStart > AsOf - 182 and WeekStart <= AsOf - 91
```

13 weeks matches `ModelConfig[ForecastHorizonWeeks]`.

---

## 5. Page 10 visual inventory

| Visual | Type | Shows |
|--------|------|-------|
| Actual Demand, Baseline Forecast, Forecast Accuracy, Forecast Bias, MAE | cards | headline quality |
| Demand Growth 13W, Growing, Declining, Volatile (Z), Weeks of History | cards | movement and coverage |
| Demand Trend: Actual vs Baseline Forecast | line, 24 months | history and the baseline against it |
| Forecast Accuracy by Category | column | where accuracy varies (barely) |
| Fastest Growing Products | bar, top 15 desc | high-growth SKUs |
| Steepest Demand Decline | bar, top 15 asc | declining SKUs |
| Demand & Forecast Detail | table | per-product actual, forecast, bias, WAPE, growth, CV, XYZ |
| Category / Product / Year | slicers | filtering |

Volatility is carried by `Volatile Products` (the XYZ Z class, 167 products),
`Product Demand CV` and `XYZ Class` in the detail table, so the forecasting page
and the segmentation page agree on a single definition of volatility rather than
inventing a second one.
