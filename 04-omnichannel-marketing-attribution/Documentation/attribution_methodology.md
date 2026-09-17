# Attribution Methodology

How revenue credit is divided across a lead's marketing touches, and why each
choice was made. Implemented in `SQL/07_build_attribution.sql`; verified against
an independent pandas implementation in `Validation/validate_attribution.py`.

## The conversion event

A **journey** is every touchpoint a lead received up to its creation. All 174,938
touches in the source fall on or before their lead's `CreatedDate` (0 after,
measured), so lead creation is the conversion event. Revenue is booked later —
lead to opportunity takes at most 39 days, opportunity to revenue at most 19 —
and is attributed back through the same journey.

## Journey order

The source carries a `TouchSequence` number, but for **71% of leads** a later
sequence number carries an earlier date, and each touch type occupies ~20% of
every position, so the number holds no behavioural signal. Journeys are ordered
by `TouchDate`, with same-day ties broken by `TouchSequence`
(`FactTouchpoint.JourneyPosition`). Time-decay is defined in days, so it
cannot use an order that contradicts the calendar. The source value is kept as
`SourceTouchSequence` for audit.

## The five models

With `n` = journey length and `k` = position (1 = earliest):

| Model | Credit to touch k | Rationale |
|---|---|---|
| First Touch | 1 if k = 1, else 0 | Credits whatever created awareness |
| Last Touch | 1 if k = n, else 0 | Credits whatever closed the conversion |
| Linear | 1 / n | No position is assumed to matter more |
| Position-Based | n = 1: 1 · n = 2: 0.5 each · n ≥ 3: 0.40 first, 0.40 last, 0.20 ÷ (n − 2) each middle | The industry-standard U-shape: opener and closer weighted, middle still counted |
| Time-Decay | 0.5 ^ (days before lead ÷ 7), normalised so the lead sums to 1 | Recent touches matter more; 7-day half-life is the common default |

All parameters (half-life, 40/40 split, default model) live in `dbo.ModelConfig`,
not in code.

## Conservation

Every lead's credit sums to exactly 1 under every model (checked to 1e-12 for all
250,000 lead × model pairs). Each model therefore re-divides the same revenue —
**31,756,120.64** — rather than creating or losing any. Attributed revenue per touch
is `CreditWeight × the lead's revenue`.

## Why precomputed in SQL

Five models over 174,938 touches is 874,690 weights. Computing positions and decay
at query time would re-sort every journey on every visual refresh. Stored weights
are computed once, auditable row by row, and leave the report's model selector as
a simple filter.

## Verification

| Check | Result |
|---|---|
| Rows, SQL vs pandas | 874,690 = 874,690, none one-sided |
| Largest weight difference | 6.7 × 10⁻¹⁶ |
| Largest attributed-revenue difference | 5 × 10⁻⁷ |

## Reporting basis (Phase 4)

The weights above cover every recorded conversion. The report reads them on the
basis an analyst would reconcile against:

- **As of 31 Aug 2026.** Only revenue booked by the as-of date is attributed —
  **30,867,505.68** under every model. The 209 bookings dated later stay in the table
  (flagged `IsRevenueAfterAsOf`) but are counted only as post-period records.
- **Dated by booking date.** Attributed revenue activates the booking-date
  relationship, so any month's attributed revenue under any model equals the
  revenue booked that month. The live reconciliation ties all 5 models × 32 months
  to finance (165 checks). By touch date, credit would fall in Nov–Dec 2023, before
  any spend, and both ends of the timeline would be truncated.
- **Campaign signal.** A campaign's Revenue-to-Spend Index is read with a test: its
  attributed revenue is compared with what its cost share would earn, with variance
  under that fair-share hypothesis — expected revenue × Σv²/Σv of per-lead credited
  revenue (compound Poisson; computed per model in `07`). Deal sizes are skewed
  (standard deviation 1.26× the mean), and a naive plug-in variance would have
  flagged 27 campaigns below fair share and none above; the fair-share test finds 2
  clearly and 14 possibly above and 3 possibly below, against about 14 expected
  beyond |z| = 2 by chance among 300 campaigns.

## What the models show on this dataset

Share of attributed revenue by channel (%), revenue booked by the as-of date:

| Channel | First Touch | Last Touch | Linear | Position-Based | Time-Decay | Spread (pts) |
|---|---|---|---|---|---|---|
| Meta Ads | 20.70 | 19.55 | 19.91 | 20.06 | 19.51 | 1.18 |
| Referral | 14.97 | 16.23 | 15.44 | 15.49 | 15.73 | 1.26 |
| Google Ads | 15.19 | 14.24 | 15.26 | 14.93 | 15.11 | 1.02 |
| Email | 14.24 | 14.64 | 14.14 | 14.31 | 14.12 | 0.52 |
| Display | 13.49 | 12.30 | 13.07 | 13.00 | 12.75 | 1.19 |
| LinkedIn Ads | 10.75 | 11.89 | 11.33 | 11.30 | 11.55 | 1.14 |
| Organic Search | 10.67 | 11.15 | 10.86 | 10.91 | 11.22 | 0.54 |

**The model choice moves channel credit by at most 1.26 percentage points here.**
That is a property of the synthetic data — channels are spread evenly across
journey positions — not a flaw in the models. On real data, where awareness
channels cluster early and conversion channels late, the same models diverge
sharply. The report presents the spread as measured and does not exaggerate it.
