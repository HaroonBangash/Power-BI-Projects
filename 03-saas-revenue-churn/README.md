# SaaS Revenue, Retention & Churn

An end-to-end Power BI project on a 12,000-account SaaS business: SQL Server star
schema, a tabular model written as code, and an eight-page report — with the data
audited first, and the analysis cut back to what the data will actually support.

![Executive Summary](Validation/evidence/listing/exec.png)

---

## What the audit changed

The brief that ships with this dataset asks for an MRR waterfall with five movement
types, a churn model trained on usage and support history, and customer health scoring.
Phase 1 measured whether the data supports any of that. Three findings redirected the
whole build:

**1. Three of the five waterfall components cannot exist here.** MRR is one static value
per subscription, every subscription bills a single invoice amount for life, and every
customer has exactly one subscription ever. So there is New and there is Churn;
expansion, contraction and reactivation are structurally nil. The model computes all
five anyway — the logic is written and tested — and the report shows the three empty
bars with the reason beside them rather than quietly dropping them.

It follows that **net revenue retention can never exceed gross**, and in fact they are
identical. Both are published side by side, because quoting NRR alone would imply an
expansion motion that does not exist.

**2. Product usage does not predict churn.** Feature adoption, logins, licensed seats,
seat utilisation and critical errors all correlate with churning at |r| < 0.02, and the
averages for customers who left and customers who stayed are the same to three decimal
places. A churn model trained on those features would be fitting noise, so none is
built. What is built instead is a driver view whose correlations are **computed in SQL
on every refresh** (`analytics.vw_ChurnDriverStrength`) and shown on the page.

**3. Raw counts measure tenure, not behaviour.** Raw ticket count correlates −0.00 with
churn and raw failed-invoice count −0.09 — flat or backwards — because a customer who
stays longer accumulates more of everything. Per month of tenure, support contact rate
becomes the second real signal at +0.15; per invoice, payment failure vanishes entirely.
Both are on the page, because the contrast is the lesson.

The one strong, real driver is **price point**: Starter churns at 26.1% and Enterprise
at 7.8%, and the gradient holds inside every customer segment.

---

## Evidence

| Check | Result |
|---|---|
| SQL build and validation (`SQL/09_validation.sql`) | **95 of 95** |
| Semantic model vs the live SQL views (`verify_semantic_model.py`) | **623 of 623** |
| Every measure vs independently written SQL (`reconcile_measures.ps1`) | **876 of 876** |
| Every visual's own query returns data (`validate_visuals.ps1`) | **188 of 188** |
| Interaction: slicers, calculation group, field parameter (`test_interactions.ps1`) | **26 of 26** |
| Query folding to SQL Server (`check_query_folding.sql`) | **19 of 19 views folded** |
| Eight Power BI Desktop open-and-refresh cycles | **300 files, 0 changed** |

`validate_report_layout.py` reports **17 deviations** from the generator's own layout
conventions. All seventeen come from the hand-finishing pass in Desktop and are
deliberate: twelve are the Country, Segment and Time-comparison slicers moved inside
the navigation rail, four are gain/loss figures coloured green and red instead of the
theme crimson, and one is a caption in Data & Method that overflows its scrollable
box. They are listed rather than silently suppressed — the script encodes what the
generator produced, not what the finished report should look like.

The two identities the project rests on hold exactly, in all 56 months:

```
MRR(month)       = MRR(month - 1) + SUM(movements in month)
customers(month) = customers(month - 1) + new - churned
```

Every page was also opened and inspected as a rendered capture
(`Validation/evidence/`), which is how defects that every query check passes get found —
including the one that mattered most. "Support contact rate by plan" read 1.68 for
Enterprise against 0.43 for Starter: four times the support contacts from the customers
who churn least. `DimPlan` reached only the subscription-shaped facts, so a plan filter
shrank the denominator while all 45,000 tickets stayed in the numerator. Nothing caught
it but a rendered number that could not be true.

---

## The eight pages

| | |
|---|---|
| **Revenue Movement** — where MRR moved, and the three bars that cannot exist | **Retention & Cohorts** — the triangle, and both retention bases |
| ![Revenue Movement](Validation/evidence/listing/movement.png) | ![Retention and Cohorts](Validation/evidence/listing/retention.png) |
| **Churn Drivers** — what was tested, what was found, what was not | **Customer Base** — who the accounts are, cut six ways |
| ![Churn Drivers](Validation/evidence/listing/drivers.png) | ![Customer Base](Validation/evidence/listing/customers.png) |
| **Unit Economics** — LTV and payback, with the assumption on screen | **Product & Support** — adoption and tickets, as rates not counts |
| ![Unit Economics](Validation/evidence/listing/economics.png) | ![Product and Support](Validation/evidence/listing/product.png) |
| **Data & Method** — what the data will not support, and the traps in it | |
| ![Data and Method](Validation/evidence/listing/method.png) | |

---

## How it is built

| Layer | What |
|---|---|
| Data | 9 CSVs → `SaaSRevenueBI` on SQL Server: 9 staging tables, 9 dimensions, 7 facts, 19 analytics views. Rebuild with `SQL\run_all.ps1` |
| Derived | `FactSubscriptionMonth` — a monthly snapshot, 320,294 rows — and `FactMRRMovement` — a ledger of classified changes, 14,292 rows. A snapshot and a ledger check each other |
| Model | 20 tables + 1 calculation group + 1 field parameter, 93 measures, RLS by country — generated by `Python/02_generate_semantic_model.py` |
| Report | 8 pages behind a navigation rail, 188 visuals of 22 types, on a light crimson-and-pink theme taken from the client's reference design — generated by `Python/04_generate_report.py` |
| Validation | Nine scripts in `Validation/`, from TMDL parsing to a Power BI save round trip |

Nothing is authored in the Power BI interface. The whole PBIP is written by Python in
Power BI's own save format, so the model is reviewable as code and a genuine Ctrl+S in
Desktop leaves the repository untouched.

### Two ideas worth a closer look

**MRR is a stock, and the model refuses to let you sum it.** Every point-in-time measure
goes through one hidden `[Snapshot Month]` measure that takes the last month in context,
caps it at the as-of date, and returns BLANK beyond the data. Selecting January to August
gives MRR *at the end of August*. Selecting a month the file does not reach gives
nothing, rather than drawing yesterday's number flat into the future.

**The cohort matrix is a triangle on purpose.** `[Cohort Retention %]` returns BLANK
where a cohort has not lived that long yet, so the matrix shows the shape of the data
instead of 0% for a future that has not happened.

---

## Layout

| Folder | Contents |
|---|---|
| `SQL` | `01`–`09`, in order, plus `run_all.ps1` |
| `Python` | Data audit, semantic model, measure dictionary, report |
| `PowerBI` | The PBIP: semantic model and report definitions |
| `Validation` | The test harness and its evidence |
| `Documentation` | Data quality report, semantic model, DAX dictionary, visual catalogue, publish readiness |

## Licence

[MIT](LICENSE) — the code. The dataset is a synthetic portfolio dataset, included in
`Data/raw` so the build is reproducible from a clone.

## Status

See [PROJECT_STATE.md](PROJECT_STATE.md) for phase status, the decision log, and what is
and is not verified.
