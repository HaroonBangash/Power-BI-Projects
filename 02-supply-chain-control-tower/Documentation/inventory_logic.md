# Inventory & Replenishment Logic

The analytical layer behind **Page 7 — Stockout & Replenishment Risk**.

Every threshold here is an absolute business rule. Each was fixed *before*
counting how many rows it would classify, so the resulting distribution is a
finding about the data rather than an artefact of tuning.

---

## What the data actually says

Measured at the product × warehouse grain (3,000 lines) before any measure was
written:

| | |
|---|---:|
| Median weeks of supply | **115 weeks** |
| Median reorder point | 108 units |
| Median inventory position | 1,968 units |
| Median average weekly demand | 17.2 units |
| Lines below reorder point | 178 (5.9%) |
| Lines below safety stock | 116 (3.9%) |

**This operation is heavily overstocked while specific lines still run short.**
Both facts matter, and the measures are built to surface both rather than let
the aggregate surplus mask the line-level shortages.

---

## The chain

```
Average Weekly Demand      mean weekly demand, 13 weeks ending at the as-of date
        x
Lead Time Weeks            DimProduct[LeadTimeDays] / 7
        =
Expected Demand During Lead Time
        +
Safety Stock Units         DimProduct[SafetyStockUnits]
        =
Reorder Point

Current On Hand + Current Inbound = Current Inventory Position

Reorder Point - Inventory Position = Reorder Gap
MAX(0, Reorder Gap)                = Suggested Reorder Quantity
Inventory Position / Avg Weekly Demand = Weeks of Supply
```

### Why a 13-week demand window

It matches `ModelConfig[ForecastHorizonWeeks]` and is a standard planning
quarter — long enough to smooth weekly noise, short enough to reflect current
demand rather than two-year-old history. The window is anchored to
`[As Of Date]` and applies `REMOVEFILTERS(DimDate)`, so replenishment figures do
not change when a user filters the calendar. Reorder advice that shifts with a
date slicer would be worse than useless.

### Why the supplied safety stock

`DimProduct[SafetyStockUnits]` is used as given. A statistical alternative —
demand variability × lead time × a service-level factor — is defensible, but it
requires *assuming* a service level the dataset does not state. The supplied
figure rests on given data. Recorded as a candidate refinement.

### Why lead time comes from DimProduct

`DimProduct[LeadTimeDays]` is the **planning** assumption. Observed supplier
performance is a separate measure, `[Average Supplier Lead Time]`, which ranges
5–47 days against a planning range of 5–30. The two must never be conflated:
one is what you plan with, the other is what actually happened.

---

## Replenishment status

| Status | Rule | Lines | % |
|---|---|---:|---:|
| **Critical** | Position < Safety Stock | 116 | 3.9% |
| **Reorder Required** | Position < Reorder Point | 62 | 2.1% |
| **Monitor** | Position < 2 × Reorder Point | 54 | 1.8% |
| **Healthy** | everything else | 166 | 5.5% |
| **Overstock** | Weeks of Supply > 26 | 2,602 | 86.7% |

The 26-week horizon is a conventional six-month excess-stock threshold, chosen
before counting what it would capture. **86.7% classified Overstock is a fact
about this dataset, not a reason to move the threshold.**

Excess inventory value — stock beyond 26 weeks of cover, priced at unit cost —
is **266,538,643 of 334,826,306, or 79.6%**. Roughly four fifths of the working
capital in stock will not turn over within six months.

---

## Why roll-ups iterate the grain

Reorder point is a per-product-per-warehouse concept. Portfolio totals are built
with `SUMX` over `SUMMARIZE(FactInventorySnapshot, DimProduct[ProductID],
DimWarehouse[WarehouseID])`.

Summing the components first would compare a portfolio-wide reorder point
against a portfolio-wide position — and since the portfolio holds a vast
surplus, **every line-level shortage would vanish inside it**. The model would
report zero products needing reorder while 178 lines were genuinely short.

Verified: `[Products Requiring Reorder]` returns 178 both evaluated whole and
summed across the six warehouses. Additivity across the grain holds.

Recorded as a performance watch item for the optimisation phase: 3,000
iterations with context transition is correct but not cheap.

---

## Replenishment status as a chart axis

Status is a measure, so it cannot be a chart axis. A disconnected
`ReplenishmentStatus` dimension holds the five values, and `[Lines at Status]`
counts grain rows matching the status in context. Verified to return identical
counts to a direct evaluation of the status measure.

Its columns are declared explicitly in TMDL because a calculated table's columns
do not materialise until Power BI processes it.

---

## Validation

`22 reconciliation checks against independently written SQL, 22 passed.`

Line-level arithmetic verified end to end on P00001 / W01:

| | |
|---|---:|
| Average weekly demand | 7.69 |
| Lead time weeks | 4.14 (29 days) |
| Expected demand during lead time | 31.87 |
| Safety stock | 109 |
| **Reorder point** | **140.87** |
| On hand + inbound | 2,796 + 20 = 2,816 |
| Reorder gap | −2,675.13 |
| Suggested reorder quantity | 0 (floored) |
| Weeks of supply | 366.08 |
| **Status** | **Overstock** |

Filter propagation confirmed across warehouse, category, product, and
product+warehouse combinations.

---

# ABC / XYZ Segmentation (Page 8)

## Grain — and why it changes the answer

**Both classifications are product level.** Demand is stored at
product × warehouse × week, so the XYZ measures sum to product × week *first*.

This is not tidiness. Product-warehouse CV runs roughly **twice** product-level
CV, because summing six warehouses smooths the noise:

| Grain | P33 | P66 |
|---|---:|---:|
| Product × warehouse | 0.259 | 0.316 |
| **Product (used)** | **0.129674** | **0.170917** |

Pairing product-level ABC with product-warehouse XYZ would have been a silent
grain mismatch — the combined classes could not have been formed honestly.

## ABC

Revenue contribution, all 1,000 products with sales.

| Class | Products | % catalogue | Revenue | % revenue |
|---|---:|---:|---:|---:|
| A | 512 | 51.2% | 46,143,755 | 79.99% |
| B | 279 | 27.9% | 8,640,173 | 14.98% |
| C | 209 | 20.9% | 2,904,656 | 5.04% |

**513 products are needed to reach 80% of revenue**, matching the Phase 2 audit.
Cumulative contribution closes at 1.000000.

The 80/95 boundaries describe **value contribution, not a target share of
products**. Class A holding 51.2% of the catalogue is the real distribution.
Forcing a 20/30/50 split would fabricate a Pareto curve this data does not have.

## XYZ

Coefficient of variation of product-level weekly demand over the 13 weeks ending
at the as-of date. 500 products carry demand history; CV ranges 0.0560 to 0.3512.

Boundaries are **computed terciles**, not constants, and use `REMOVEFILTERS` so a
Category slicer cannot silently redefine what X, Y and Z mean. Generic cut-offs
such as X < 0.5 would classify every product here as X.

## Combined matrix

```
        X     Y     Z
   A   87    80    93
   B   47    51    43
   C   33    35    31
```

Nine cells total **500** — no double-counting. The other **500 products carry no
demand history and remain explicitly Unclassified**, never defaulted into X,
which would invent predictability from absent data.

**AZ = 93 products**: high financial importance with volatile demand, needing the
closest forecasting and inventory attention. This is a *strategy* segment — it
does not mean those products are currently at stockout risk. ABC/XYZ and
replenishment risk are separate analyses.

---

# Supplier Performance Score (Page 9)

## Three components, not four

The dataset records **no received or fulfilled quantity**, so fulfilment
performance cannot be measured. Rather than invent a fourth component, its
weight is redistributed and the omission stated. Nothing is labelled OTIF.

## Weights — 45 / 35 / 20

| Component | Weight | Raw spread across 120 suppliers |
|---|---:|---|
| On-Time Receipt Performance | 45% | 0.286 – 0.520 |
| Lead-Time Reliability | 35% | 3.49 – 10.40 days std dev |
| Quality (defect rate) | 20% | 0.0294 – 0.0364 |

The suggested 40/30/30 was **not** used. Defect rate varies by only 0.7
percentage points across the entire supplier base, so min-max normalisation
stretches near-noise across a full 0–1 range. A 30% weight would let that noise
drive nearly a third of the score. It keeps a real 20% — quality is a genuine
obligation — but should not outvote delivery performance that varies twenty
times more widely.

**Reliability is consistency, not speed.** The component scores the *standard
deviation* of actual lead time, not its average. A long but predictable lead time
can be planned around; an erratic one cannot. Average lead time is reported
alongside as description, not scored.

Normalisation is min-max across the whole supplier population via
`REMOVEFILTERS`, so a slicer cannot rescale the score and change what
"Excellent" means. Every component is oriented so higher is better.

## Class distribution

| Class | Score | Suppliers | % | Share of PO spend |
|---|---|---:|---:|---:|
| Excellent | ≥ 70 | 9 | 7.5% | 6.6% |
| Good | 55–69 | 32 | 26.7% | 25.5% |
| Needs Improvement | 40–54 | 63 | 52.5% | 55.6% |
| High Risk | < 40 | 16 | 13.3% | 12.3% |

Cut points are round values on the normalised scale, deliberately **not**
percentiles — percentiles would force equal group sizes and hide the fact that
most of this supplier base performs moderately.

**68% of procurement spend sits with suppliers rated Needs Improvement or
High Risk.**

The supplied `SupplierTier` does not track measured performance: a *Watchlist*
supplier scores second best (80.6) while a *Strategic* one falls in the bottom
five (32.5). Tier appears to be a commercial designation rather than a
performance rating.
