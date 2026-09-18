# Project state

Healthcare Claims & Revenue Cycle — a five-phase Power BI build on a synthetic
dataset. This file is the running record: what is done, what each decision was and
why, and what is verified as opposed to merely written.

**The dataset is synthetic.** A portfolio dataset for a fictional Australian provider
group. Nothing here is real patient, provider or payer data, and nothing is presented
as a real organisation's revenue cycle.

---

## Phase status

| Phase | What | Status |
|---|---|---|
| 1 | Data audit and feasibility | **Complete** |
| 2 | SQL Server star schema, derived tables, validation | **Complete** |
| 3 | Semantic model as code (TMDL) | **Complete** |
| 4 | Report as code (PBIR) | **Complete** |
| 5 | Publish readiness | **Complete** |

---

## Phase 1 — data audit

`Python/01_data_audit.py` → `Documentation/data_quality_report.md` and
`Validation/audit_metrics.json` (93 metrics). The script takes its source folder from
`--source`, `RCM_SOURCE`, or `config.local.json`; **no machine path is committed.**

Five findings redirected the build. Each is retested by the SQL suite on every
rebuild, so none can quietly stop being true:

1. **The money closes exactly.** Allowed $72,713,182 = collected $46,414,738 +
   patient responsibility $3,768,666 + open AR $16,831,000 + denied $5,698,778.
   Residual **$0.00**. That identity is the spine of the model.
2. **'Pending' is a permanent state, not an ageing tail.** 23.1% of claims, and the
   pending share is 20.6–25.0% in *every one* of the 44 complete submission months.
   Median age 737 days; 77.2% of open AR is over a year old.
3. **A denial never recovers.** 0 of 7,824 denied claims were ever paid — including
   all 1,913 marked *Corrected* and 1,946 marked *Appealed*. Denial date always
   equals adjudication date, so there is no appeal timeline either.
4. **Nothing predicts a denial except who is paying.** Self Pay 2.95% vs 8.79% for
   the five insurers. Every other dimension is inside chance (Cramér's V ≤ 0.015);
   provider variation is 1.95 pp against 1.90 pp expected from coin-flipping.
5. **The procedure code does not price the procedure.** Average charge per CPT code
   spans $391.76–$397.46 — a $5.70 spread across codes that in reality range from a
   venipuncture to an MRI.

Plus: the supplied `dim_date` stops at the last **service** date, leaving 4,807
adjudication, payment and denial dates outside the calendar.

## Phase 2 — SQL

`SQL/01`–`08` plus `run_all.ps1` build `HealthcareRCMBI`: 10 staging tables, 15
dimensions, 6 facts, 25 analytics views. **Whole build 37.5 s, validation 121 of 121
checks.**

Derived, not in the source:

| Table | Rows | What it is |
|---|---:|---|
| `dim.DimDate` | 1,826 | Generated, not loaded — covers every fact date plus a margin |
| `fact.FactARSnapshot` | 670,151 | A **stock**: every claim still outstanding at each of 47 month ends, with its age |
| `fact.FactARMovement` | 246,040 | A **flow**: every event that moved the receivable, signed |

The two AR tables check each other in every month:
`AR(m) = AR(m−1) + submitted − collected − patient responsibility − denied`.


## Phase 3 — semantic model

`Python/02_generate_semantic_model.py` + `Python/model_measures.py` write the whole
PBIP semantic model as TMDL. **28 tables** (25 loaded, 2 calculation groups, 1 field
parameter), **226 columns**, **44 relationships** (39 active), **118 measures** in 11
folders, **1 RLS role** filtering 4 tables.

- Static verification **966 of 966** (`verify_semantic_model.py`), run against the live
  SQL views rather than the generator's idea of them.
- The model loads and refreshes in **12.4 s**; every table row count matches the SQL.
- The four-bucket identity holds **live**: allowed $72,713,182.33 = collected
  $46,414,738.26 + patient responsibility $3,768,666.11 + open AR $16,830,999.94 +
  denied $5,698,778.02. Open AR read independently from the 670,151-row snapshot agrees
  to the cent with the claim header.
- The AR roll-forward returns **zero in all 47 months** and at every grain.

Details in [Documentation/semantic_model.md](Documentation/semantic_model.md).


## Phase 4 — report

`Python/04_generate_report.py` writes 8 pages, **218 visuals of 22 types**, on a dark
teal operations-console theme behind a **top navigation bar** — the first project in
this series not to use a left rail. Schema, field, geometry and overlap checks: **0
errors**. Static model verification after the report's new measures: **851 of 851**.

Nine defects were found by rendering each page and looking at it, none of which a query
check would have caught — including three clocks plotted on two different calendars, a
bar chart hiding the four dimensions that failed the test behind a scrollbar, and a
reference table summing counts, dollars and percentages into one total. All nine are
listed with their fixes in
[Documentation/visual_catalogue.md](Documentation/visual_catalogue.md).


## Phase 5 — publish readiness

| Check | Result |
|---|---|
| SQL build and validation | **121 of 121** |
| Semantic model vs the live SQL views | **966 of 966** |
| Every measure vs independently written SQL | **700 of 700** |
| Every visual's own query returns data | **210 of 210** |
| Layout, navigation and theme | **0 issues** |
| Interaction: slicers, calculation groups, field parameter, RLS | **46 of 46** |
| Query folding to SQL Server | **24 of 24 views folded, 0 unfolded** |
| A genuine Power BI save | **288 files, 0 changed** |

Performance: full refresh **4.6 s**, model **42.5 MB**, every page query under **72 ms**.
Open AR at every month end reads **20 ms** from the snapshot against **339 ms** computed
from dates at query time.

Details in [Documentation/publish_readiness.md](Documentation/publish_readiness.md).

---

## Decision log

| # | Decision | Why |
|---|---|---|
| **D1** | The **allowed** amount, not billed, is the spine of the model | Billed is a sticker price no one ever pays; 26.5% of it is a contractual adjustment agreed in advance. Allowed is the contracted expectation, and it splits cleanly into four buckets that must sum back to it |
| **D2** | `dim.DimDate` is **generated**, and the supplied `dim_date.csv` is used only to verify it | The supplied calendar stops on the last service date. 4,807 adjudication, payment and denial dates fall past it and would have joined to a blank date — vanishing from any measure sliced by adjudication or payment month, while the totals still looked right |
| **D3** | `InSuppliedCalendar` is kept as a column | The gap becomes visible in the data rather than being silently patched |
| **D4** | **Every fact carries its own dimension keys** | A filter never travels from one fact to another. Keys only on the claim header would leave "line volume by payer" and "denials by specialty" filtering one table and not the other — the defect that took longest to find in the previous project in this series |
| **D5** | **No relationship between `FactClaim` and `FactClaimLine`** | With the dimensions conformed, a header-to-line relationship would give the engine two paths from `DimPayer` to the line table. `ClaimID` is a degenerate key on every fact for drill-through instead |
| **D6** | Money is defined **once**, on the claim header | The line table's `ChargeAmount` sums to the header billed amount. Used for mix and volume only; no measure ever adds the two |
| **D7** | AR is carried at the **allowed** amount, and aged from the **submission** date | Carrying at billed would overstate the receivable by the contractual adjustment. Ageing from submission is the revenue-cycle convention: the payer's clock starts when the claim reaches them |
| **D8** | Patient responsibility is treated as **leaving AR on the payer's payment date** | Stated as an assumption in `06_build_ar_snapshot.sql`. The source records no patient payment events; in reality this would begin a second, slower AR |
| **D9** | A snapshot **and** a ledger, not one or the other | A snapshot can drift unnoticed; a ledger cannot be aged. Built together each proves the other, and the identity is re-run for all 47 months on every build |
| **D10** | `DimPayer` carries a **PayerType** and `IsSelfPay` | The Self Pay split is the only real signal in the data, so it is a first-class attribute, not something a reader has to spot in a slicer |
| **D11** | Denial **signal strength is computed in SQL**, with a chi-square test and Cramér's V | A finding typed into a text box goes stale. `vw_DenialSignalStrength` recomputes it on every refresh, applying the same stated rule (V < 0.02 = no usable signal) to every dimension including the one that passes |
| **D12** | `vw_ProviderDenialChance` publishes each provider's rate **next to its own standard error** | A 500-row league table from 3% to 14% is the first thing anyone asks for and is entirely noise. 23 providers sit beyond 2 SE — 4.6%, against the 4.55% a normal distribution predicts. The most extreme is z = 3.3, which is what 500 draws produce |
| **D13** | `DimDenialStatus` values are labelled **workflow state**, never outcome | No denied claim in this file recovers. Calling *Corrected* an outcome would imply money came back |
| **D14** | First-pass acceptance, clean-claim rate and (1 − denial rate) are published **together on one card** | They are arithmetically the same number here. Publishing them on three separate cards would imply three independent measurements |
| **D15** | Procedure and diagnosis dimensions carry **real code meanings and groupings**, but no page ranks a procedure by revenue | The descriptions are published metadata about real CPT/ICD-10 codes. The charges are not tied to them, so case-mix and service-line profitability are off the table |
| **D16** | Currency is **AUD** | Every facility state is Australian and the payers are Medicare, Bupa, Medibank, HCF and NIB |
| **D17** | The audit script reads its source from **config, not a hardcoded path** | Carried forward from project 4, where a local path reached the repository |
| **D18** | Two calculation groups, with **Time Comparison outranking Date Basis** | The comparison has to wrap the basis, so "prior month on submission date" means the month before measured on submission - not the submission-date version of last month's service figure, which is not a question anybody asks. The verifier checks both precedences and the ordering, because a silent swap would change every comparison and break nothing visible |
| **D19** | Four date relationships on one fact, three of them inactive | A claim has four clocks - service, submission, adjudication, resolution - and they answer different questions. Four copies of the fact would be the alternative |
| **D20** | Open AR goes through one hidden `[Snapshot Month End]` measure | A stock must never be summed across months. Capping it at the as-of month and returning BLANK beyond it stops a chart drawing today's receivable flat into next year |
| **D21** | `[Days in AR]` caps its 91-day window at the **last submission date** | Claims stop being submitted on 7 Sep 2026 while cash arrives until 3 Nov. Uncapped, the measure divided a full receivable by seven days of business and reported a DSO of **8,700 days**. Caught by reading the number, not by any test |
| **D22** | `[AR Roll-Forward Check]` is anchored to the snapshot month | The plain movement measure follows the visual's date filter, which is right for a flow and wrong for checking a balance: with no date filter it spanned four years while the opening balance was one month back. Anchoring all three terms makes it zero at every grain |
| **D23** | Net collection rate is quoted on **resolved claims**, with the all-claims figure beside it | A revenue-cycle team is not accountable for claims the payer has not answered. 83.1% resolved against 63.8% all-claims - and in this source, where a pending claim never resolves, the gap between the two IS the story |
| **D24** | `[Denial Recovery Rate %]` is published even though it is zero | So the page can say appeal yield is unmeasurable here, rather than leaving a reader to assume it was overlooked |
| **D25** | `ProviderChance` is disconnected **and** carries its own RLS filter | Disconnected because the group rate it compares against is computed over all claims. That means no relationship carries the facility filter to it either, so a facility manager would otherwise read the whole group's provider distribution |
| **D26** | `DimPatient` is deliberately **not** filtered by RLS, and the verifier asserts it | A patient may be treated at more than one facility, so a patient filter would be wrong in both directions - and unnecessary, because the facility filter already restricts every claim a scoped user can reach |
| **D27** | VAR names that shadow a DAX function are banned, and `All` is now on the list | `VAR All = ...` failed the WHOLE model script with "Failed to resolve name 'SYNTAXERROR'" - an error naming neither the measure nor the variable |
| **D28** | Navigation is a **top bar of tabs**, not a left rail | Every other project in this series used a column of buttons down the left. A row of tabs with a mint underline is a different device in a different place, and it hands 168 px of width back to the content |
| **D29** | A rectangle is an **action button**, never a textbox | An empty textbox is forced to a ~24 px minimum height, so a 3 px tab indicator rendered as a blob - and a textbox draws a text caret in Desktop that lands in every capture |
| **D30** | The **ageing ramp is the only ordered colour scale** in the report | Age is the only quantity here that genuinely has an order. Everything else is the accent or a muted tone, so colour never implies a ranking that does not exist |
| **D31** | Hierarchy on a dark ground is carried by **elevation, not hue** | Filling a card with colour on a dark theme buries its own number. The hero card is lifted one shade and writes its figure in mint |
| **D32** | A claim-basis days-to-cash measure exists so three intervals can share one axis | The payment-fact version is active on the PAYMENT date while the other two are active on the SERVICE date. Plotted together they put two different months on one axis and the line ran off the chart. The two agree exactly at the grand total |
| **D33** | Both reference tables are **matrices with subtotals off**, with text as a MEASURE | A table cannot drop its total row, and the findings table was summing counts, dollar amounts and percentages into 128,912.5482 |
| **D34** | Every gauge carries an **explicit maximum** | Without one a gauge scales to twice its own value, which puts any number in the middle of the dial |
| **D35** | An all-buckets AR measure adds zero so an **empty ageing bucket still draws** | The two freshest buckets are empty at the as-of month end, and that is exactly the thing worth seeing: nothing has been submitted for 84 days |
| **D36** | Query Store is set to `QUERY_CAPTURE_MODE = ALL` **unconditionally**, and cleared on each build | SQL Server turns Query Store on by default in AUTO mode, which discards cheap queries - so the six-row dimension reads never appeared and only the nine expensive fact queries did. That looks exactly like partial folding and is not. A guard on `actual_state_desc` skipped the ALTER entirely, because the store was already on |
| **D37** | The generator **strips** each measure body and every line's trailing whitespace | A DAX expression that begins or ends with a double quote needs a space between it and Python's triple-quote delimiter, or the delimiter swallows the quote - but Power BI TRIMS the expression on save, so leaving that space made every Ctrl+S rewrite the measure |
| **D38** | The verifier checks that every measure's **double quotes are balanced** | An unbalanced quote still parses as TMDL and still passes every other static check; it fails only when the engine evaluates it. It cost a full model load to find once |
| **D39** | `FactClaim` is **not** related to `DimARBucket` | The key is null on every resolved claim, and a nullable foreign key gives the dimension a blank member - which then drew as a phantom row on the ageing ladder. No visual reaches the bucket through the claim header anyway: the ageing is read from the snapshot, the only table that can carry an age |

---

## Verified vs asserted

| Claim | Status | Evidence |
|---|---|---|
| Row counts match the source exactly | **Verified** | `03_load_staging.sql` fails the build on any mismatch; 121-check suite re-counts |
| The allowed-amount identity holds on every row and in total | **Verified** | `08_validation.sql`, residual $0.00 |
| The AR roll-forward holds in all 47 months | **Verified** | Checked in `06` at build time and again in `08` |
| No denied claim ever recovers | **Verified** | `08_validation.sql` |
| Payer is the only dimension with denial signal | **Verified** | `vw_DenialSignalStrength`, computed live |
| Provider variation is chance | **Verified** | `vw_ProviderDenialChance`; 4.6% beyond 2 SE vs 4.55% expected |
| Query folding to SQL Server | Not yet tested | Phase 5 |
| Semantic model verified against the live SQL views | **Verified** | `verify_semantic_model.py`, 832 of 832 |
| The four-bucket identity holds in the live model | **Verified** | Measured through ADOMD: gap $0.00 |
| AR roll-forward is zero in all 47 months | **Verified** | Queried month by month in the live model |
| Every conformed dimension reaches every fact | **Verified** | `verify_semantic_model.py`, Conformed 4 of 4 |
| Measures reconciled against independent SQL | Not yet tested | Phase 5 |
| Report renders, every page inspected | **Verified** | `Validation/evidence/phase4`, 8 captures |
| Report schema, fields, geometry, overlap | **Verified** | `04_generate_report.py --check`, 0 errors |
| Every visual's own query returns data | **Verified** | `validate_visuals.ps1`, 218 of 218 |
| Every measure against independently written SQL | **Verified** | `reconcile_measures.ps1`, 700 of 700 |
| A filter reaches every fact, not just the claim header | **Verified** | `test_interactions.ps1`, six cross-fact questions |
| Both calculation groups, applied together | **Verified** | `test_interactions.ps1` |
| Row-level security, including the secure default | **Verified** | 167 checks over all 82 mapped users |
| Query folding to SQL Server | **Verified** | 24 of 24 views, proved from Query Store |
| A genuine Power BI save changes nothing | **Verified** | `save_round_trip.ps1`, 288 files, 0 changed |
| Publishing to the Power BI Service | **Not done** | Local PBIP project; out of scope |
| Incremental refresh, DirectQuery, composite | **Not done** | Requires the Service. Folding, its precondition, is proved |

## Published

Published to `HaroonBangash/Power-BI-Projects` as `05-healthcare-claims-revenue-cycle`
on 2026-09-19.

The report was finished by hand in Power BI Desktop after the generator last ran and now
carries **210 visuals of 21 types** (was 218). **`PowerBI/` is hand-maintained from here
on: do not run `Python/04_generate_report.py` over it.**

Every figure was re-measured against that finished report, and against a database
rebuilt from the repository's own `Data/raw` (now tracked, so the build is reproducible
from a clone):

| Check | Result |
|---|---|
| SQL build and validation | 121 of 121 |
| Semantic model vs the live SQL views | 966 of 966 |
| Every measure vs independently written SQL | 700 of 700 |
| Every visual's own query returns data | 210 of 210 |
| Layout, navigation and theme | 0 issues |
| Interaction: slicers, calculation groups, field parameter, RLS | 46 of 46 |
| Query folding to SQL Server | 24 of 24 views folded |
| Eight Desktop open-and-refresh cycles | 306 files, 0 changed |

Captures were taken from a copy of `PowerBI/` so Desktop never opened the repository.
`config.local.json` stays untracked; it holds the local source path and SQL instance.
