# Publish Readiness — Enterprise FP&A Finance

What was tested before this report would be handed to anyone, how it was tested, and
what the tests actually returned. Every figure here was produced by a script in
`Validation/` that can be re-run; nothing is typed from memory. The data is synthetic.

| Check | Script | Result |
|---|---|---|
| A genuine Power BI save changes no project file | `save_round_trip.ps1` | **257 files compared, 0 changed, 0 added, 0 removed** |
| Row-level security | `test_security.ps1` | **77 of 77** |
| Interaction: slicers, calculation groups, cross-filter, drill | `test_interactions.ps1` | **18 of 18** |
| Query folding to SQL Server | `check_query_folding.sql` | **19 of 19 views folded, 0 unfolded** |
| Performance and storage | `measure_performance.ps1` | refresh 2.1 s; slowest page query 381 ms; model 6.2 MB |
| Behaviour at enterprise volume | `SQL/10_scale_test.sql` | 1,000,000 ledger lines: **269 ms line-level vs 23 ms** on the monthly fact |

## 1. The save round trip

The generator writes TMDL and PBIR in Power BI's own format, so opening the project
and pressing Ctrl+S must leave the repository untouched — otherwise every save would
produce a meaningless Git diff and the generator would stop being the source of truth.

The test snapshots the `PowerBI` folder, activates Desktop, sends Ctrl+S, waits, and
compares byte for byte. **257 files, none changed.** The save is real, not skipped:
Power BI rewrote `cache.abf` (9 MB of model data) and its own settings files during
the same window — those are per-machine state and are git-ignored.

### What this test caught, and what it had been hiding

Power BI only re-serialises what it considers dirty. Through Phase 5 the model had not
changed since Desktop last saved it, so Desktop rewrote almost nothing and the test
passed over six real defects sitting underneath. Adding a single measure made the model
dirty, Desktop rewrote the project properly, and all six surfaced at once:

| What Power BI did on save | What it meant |
|---|---|
| Deleted `header.fontSize` from every slicer | Not a property a slicer header has. The size had never applied — the header draws at the theme's label size |
| Emptied the gauge's `dataPoint` | `fillColor` and `targetColor` are not gauge properties either; the arc follows the palette |
| Deleted `total.show` from a table | Not a tableEx property. That table has no total row regardless: every column on it is a dimension column, and columns do not total |
| Rewrote `"width"` and `"height"` in every visual it touched | Power BI writes **height before width**. The generator wrote width first, so the first real save would have rewritten all 193 visuals |
| Moved `formatString` above `isHidden`, put a blank line before each `formatStringDefinition`, and deleted every `ordinal:` from both calculation groups | Its own canonical order. An explicit ordinal only repeats the order the items are written in |
| Regenerated 1,280 lines of Q&A linguistic schema in `cultures/en-US.tmdl` | The generator had been overwriting that file with a stub on every run — its own comment said "copy once, never rewrite", and the code did the opposite |

All six are fixed in the generators, and the round trip re-run is the **257 / 0** above —
now on a model Desktop had genuinely re-serialised, which is a stronger result than the
one it replaces. The verifier's calculation-group check was rewritten to match: it reads
the items themselves and checks they are written in the reporting order, rather than
reading an `ordinal:` line that Power BI deletes.

## 2. Row-level security

| Test | Result |
|---|---|
| Secure default: connect **as the role** with no impersonation | 0 entities, 0 departments, no revenue, no receivables, no cash |
| Every mapped user's scope (18 users) | CFO and Finance Director see 6 entities × 10 departments; an entity manager 1 × 10; a department manager 6 × 1 |
| What each user would see, against SQL | revenue under each user's scope matches the database exactly |
| Treasury separation | every department-scoped user: receivables, payables and cash hidden |

**Stated limit.** The engine's `EffectiveUserName` impersonation needs a real Windows
account, so the synthetic `@northstar.demo` addresses cannot be impersonated on this
machine ("The name provided is not a properly formed account name"). The role's own
filter expressions are therefore evaluated directly against the model for each user,
which tests the same logic; Desktop's **View as → Other user** remains a manual check.

## 3. Interaction

A rendered page proves a visual draws. These tests prove the page still tells the truth
when a reader uses it: each interactive state is reproduced as the query that state
produces and compared with SQL.

- **Slicers** — entity, department, and both at once.
- **Calculation groups** — Plan Version (Budget, Var vs Budget) with a slicer set;
  Period View (year to date) inside FY27; and **both groups at once**, where
  "Var % vs Budget of the year to date" must divide two year-to-date figures.
- **Scenario buttons** — Downside, Base and Upside each drive the outlook.
- **Cross-filtering** — selecting a department, or an ageing bucket, filters the next visual.
- **Drill** — the chart of accounts, group then account.
- **The as-of guard** — a balance stays blank after the as-of date whatever is selected,
  and the balance date follows the selection (FY26 → 30 June 2026).

## 4. Query folding

Query Store is switched on in `01_create_database.sql`, so the statements Power BI sends
during a refresh are recorded without tracing. Every one of the 19 analytics views is
read with a folded, column-listed `SELECT`:

```
select [$Table].[VersionID] as [VersionID], [$Table].[MonthStart] as [MonthStart], …
from [analytics].[vw_FactFinancials] as [$Table]
```

No `select *`, and no shaping left to the mashup engine: the work happens in SQL Server,
which is what makes the model's import time independent of how the views are written.

## 5. Performance

| | |
|---|---|
| Full refresh of every table through the engine | **2.1 s** |
| Slowest page query (statement × four calculation items) | 381 ms |
| Receivables balance at every month end | 159 ms |
| Variance z-score heatmap (10 departments × 12 months) | 24 ms |
| Everything else on every page | 4–27 ms |
| Model size in memory | **6.2 MB** across 783 segments |
| Largest tables | FactGL 2.93 MB · FactFinancials 2.12 MB · FactARInvoice 0.51 MB |
| Largest columns | the relationship indexes, then `AmountAUD` |

## 6. Behaviour at enterprise volume

The starter ledger is 80,000 lines, where a line-level scan and the monthly fact are
equally fast (7 ms and 6 ms) — so the aggregation earns its place only at volume, and
that is what the scale test measures. `Python/scale_ledger.py` generates a million-line
ledger by sampling the real one (same entities, departments, accounts and currencies),
and `SQL/10_scale_test.sql` asks both tables the same question:

| | Rows | Same question: operating expense by department and month |
|---|---:|---:|
| Line-level ledger | 1,000,000 | **269 ms** |
| `FactFinancials` (monthly) | 168,782 | **23 ms** |

The monthly fact does not grow with transactions — it grows with months — so a ledger
ten times larger leaves every P&L page reading the same 168,782 rows. `FactGL` stays in
the model for drill-through and ledger detail, where line-level IS the question.

## 7. Listing screenshots

`Validation/crop_captures.py` finds the canvas in each window capture by its colour and
crops Desktop's ribbon and panes away, writing `Validation/evidence/listing/*.png` — one
clean 1516 × 922 image per page.

## What is still not verified

- **Desktop's "View as → Other user"** — a UI action; the role's logic is tested instead
  (section 2).
- **The Power BI Service** — nothing here has been published to a workspace, so scheduled
  refresh, gateway behaviour and workspace-level security are untested by definition.
- **Incremental refresh** — the model imports in full; no refresh policy is defined,
  because a 2.1 s refresh does not need one at this volume.
