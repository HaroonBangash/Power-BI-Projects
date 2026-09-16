# Publish Readiness — SaaS Revenue, Retention & Churn

What was tested before this report would be handed to anyone, how it was tested, and
what the tests actually returned. Every figure here was produced by a script in
`Validation/` that can be re-run; nothing is typed from memory. The data is synthetic.

| Check | Script | Result |
|---|---|---|
| A genuine Power BI save changes no project file | `save_round_trip.ps1` | **268 files compared, 0 changed, 0 added, 0 removed** |
| Every measure evaluates, and agrees with independent SQL | `reconcile_measures.ps1` | **876 of 876** |
| The model matches the SQL views it reads | `verify_semantic_model.py` | **623 of 623** |
| Every visual's own query returns data | `validate_visuals.ps1` | **204 of 204** |
| Interaction: slicers, calculation group, field parameter, cross-filter | `test_interactions.ps1` | **26 of 26** |
| Query folding to SQL Server | `check_query_folding.sql` | **19 of 19 views folded, 0 unfolded** |
| Performance and storage | `measure_performance.ps1` | refresh 2.1 s; slowest page query 50 ms; model 8.8 MB |
| Layout, navigation and theme | `validate_report_layout.py` | **0 issues** |
| The database build itself | `SQL/09_validation.sql` | **95 of 95** |

## 1. The save round trip

The generator writes TMDL and PBIR in Power BI's own format, so opening the project and
pressing Ctrl+S must leave the repository untouched — otherwise every save produces a
meaningless Git diff and the generator stops being the source of truth.

The test snapshots the `PowerBI` folder, activates Desktop, sends Ctrl+S, waits, and
compares byte for byte. **268 files, none changed.** The save is real, not skipped:
Power BI rewrote `cache.abf` and its own settings files in the same window — those are
per-machine state and are git-ignored.

Most of it held on the first run because the generator already carries what a previous
project learned the hard way: visual `position` is written **height before width**; a
measure writes `formatString` before `isHidden`; a calculation item takes a blank line
before its `formatStringDefinition` and no `ordinal:` at all; and `cultures/en-US.tmdl`
belongs to Power BI, which generates the Q&A linguistic schema into it and must not be
overwritten.

Two constructs new to this project were rewritten by the first save, and the generator
was corrected until a second run changed nothing:

- **A field parameter's `extendedProperty` takes a blank line before it** — the same rule
  a calculation item's `formatStringDefinition` follows.
- **A calculation item whose expression is a single line stays on the item's own line**
  (`calculationItem 'Selected period' = SELECTEDMEASURE ()`). Power BI only breaks to an
  indented continuation when the expression needs more than one line.

Neither changes what the model does, which is exactly why they matter: left alone they
would put a diff in Git every time anyone opened the file and pressed Ctrl+S.

## 2. Interaction

A rendered page proves a visual draws. These tests prove the page still tells the truth
when a reader uses it: each interactive state is reproduced as the query that state
produces and compared with SQL.

- **Slicers** — country, segment, plan, industry, billing cycle and status, alone and
  two at once.
- **A plan filter reaches the facts that hang off the customer** — tickets, acquisition
  cost and usage, not just the subscription. This is the check that would have caught
  the model defect described below.
- **The calculation group** — every Time Comparison item, and one applied *under* a
  slicer, where a comparison must respect the selection.
- **The field parameter** — all six cuts the Customer Cut parameter offers.
- **Cross-filtering** — selecting a plan filters the cohort matrix.
- **The data boundary** — MRR, churn and cohort retention are all BLANK beyond the as-of
  month, whatever is selected. A month the file does not reach must not read 0%.

**Stated limit.** Whether the field *parameter* resolves its chosen column inside a
visual happens when Power BI builds the visual's query, not in a query this script can
write. It is proven by rendering the page and reading the axis, not asserted here.

## 3. Two defects that only interaction and rendering could find

Both were the same mistake in two places, and both passed every static check, every
schema check and all 876 reconciliation checks.

**`FactSubscription` was being used as a dimension.** Its descriptive columns — plan,
billing cycle, status — were sliced while the measures came from
`FactSubscriptionMonth`. A filter never travels from one fact to another, so:

- "Support contact rate by plan" read **1.68 for Enterprise against 0.43 for Starter** —
  four times the support contacts from the customers who churn least. The plan filter
  shrank the denominator (months of customer life) while the numerator (all 45,000
  tickets, which hang off the customer) stayed whole. Found by looking at a rendered
  number that could not be true.
- A slicer on billing cycle returned **the whole $2.76M of MRR** instead of the $1.41M
  that bills annually. Found by `test_interactions.ps1`.

The fix is a modelling decision the Phase 1 audit already justified: this source gives
every customer exactly one subscription, for life, on one plan and one billing cycle, so
**those are customer attributes**. They moved onto `DimCustomer` and now filter
everything through the customer — one path, reaching tickets, usage, invoices and
acquisition. `09_validation.sql` checks the premise still holds, because the day a
customer could change plan, the model would be wrong again.

The contact rate now reads a flat 0.13–0.15 across plans.

## 4. Query folding

Query Store is switched on in `01_create_database.sql`, so the statements Power BI sends
during a refresh are recorded without tracing. Every one of the 19 analytics views is
read with a folded, column-listed `SELECT`:

```
select [$Table].[MonthStart] as [MonthStart], [$Table].[SubscriptionID] as [SubscriptionID], …
from [analytics].[vw_FactSubscriptionMonth] as [$Table]
```

No `select *`, and no shaping left to the mashup engine: the work happens in SQL Server,
which is what makes import time independent of how the views are written.

## 5. Performance

| | |
|---|---|
| Full refresh of every table through the engine | **2.1 s** |
| Slowest page query (the calculation group over every month) | 50 ms |
| The cohort matrix, 54 cohorts × 56 months, 1,593 cells | 18 ms |
| Everything else on every page | 2–23 ms |
| Model size in memory | **8.8 MB** across 755 segments |
| Largest tables | FactInvoice 3.18 MB · FactSubscriptionMonth 2.40 MB · FactUsageMonthly 0.97 MB |

### Why the snapshot earns its 2.4 MB

`FactSubscriptionMonth` turns 12,000 subscriptions into 320,294 rows, which looks like a
poor trade until you ask for MRR at every month end. Without it, every month has to scan
every subscription and test its start and end dates:

| | Asking for MRR at all 56 month ends |
|---|---:|
| From the snapshot (320,294 rows) | **6 ms** |
| Computed from dates at query time (12,000 subscriptions) | **60 ms** |

Ten times faster, for 2.4 MB — and the snapshot is also what makes the cohort matrix a
pivot instead of a window function, and what lets `09_validation.sql` check that the
movement ledger reconciles to it every month.

## 6. Row-level security

Tested in `reconcile_measures.ps1` (19 checks):

| Test | Result |
|---|---|
| Secure default: connect **as the role** with no impersonation | 0 countries, 0 MRR, 0 customers |
| Every mapped user's scope (8 users) | Revenue Operations and the CFO see 6 countries; each CS manager sees 1 |
| What each user would see, against SQL | MRR under each user's scope matches the database exactly |

**Stated limit.** The engine's `EffectiveUserName` needs a real Windows account, so the
synthetic `@northstar.demo` addresses cannot be impersonated on this machine. The role's
own filter expressions are evaluated directly for each user instead, which tests the
same logic; Desktop's **View as → Other user** remains a manual check.

## 7. Listing screenshots

`Validation/crop_captures.py` finds the canvas in each window capture by its colour and
crops Desktop's ribbon and panes away, writing `Validation/evidence/listing/*.png` — one
clean 1516 × 922 image per page.

## What is still not verified

- **Desktop's "View as → Other user"** — a UI action; the role's logic is tested instead
  (section 6).
- **The Power BI Service** — nothing here has been published to a workspace, so
  scheduled refresh, gateway behaviour and workspace-level security are untested by
  definition.
- **Incremental refresh** — the model imports in full; no refresh policy is defined,
  because a 2.1 s refresh does not need one at this volume.
- **Behaviour at much larger volume** — this dataset is 12,000 customers and 177,236
  invoices. The snapshot grows with customers × months, so a 100,000-customer business
  would produce roughly 2.7M snapshot rows; that has not been tested here and is not
  claimed.
