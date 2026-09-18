# Healthcare Claims & Revenue Cycle

An end-to-end Power BI project on a 100,000-claim provider group: SQL Server star
schema, a tabular model written as code, and an eight-page report — with the data
audited first, and the analysis cut back to what the data will actually support.

**The dataset is synthetic.** It is a portfolio dataset for a fictional Australian
provider group and is never presented as real patient, provider or payer data.

![Executive Summary](Validation/evidence/listing/exec.png)

---

## What the audit changed

The brief that ships with this dataset asks for first-pass acceptance, clean-claim
rate, AR ageing, denial root-cause analysis by payer, facility, provider, diagnosis and
procedure, and dynamic row-level security. Phase 1 measured whether the data supports
any of it. Five findings redirected the whole build.

**1. The money closes exactly, and that identity became the spine of the model.**

```
Allowed $72,713,182 = collected $46,414,738 + patient responsibility $3,768,666
                    + open AR $16,831,000 + denied $5,698,778        residual $0.00
```

Billed is $98.9M, but 26.5% of that is a contractual adjustment agreed before the claim
was sent. It is not a loss and it is never shown as one. **Allowed** is the contracted
expectation, and every dollar of it ends up in exactly one of four buckets — on every
row, and therefore at every level of every aggregation.

**2. "Pending" is a permanent state, not an ageing tail.** 23.1% of claims, and the
pending share is 20.6–25.0% in *every one* of the 44 complete submission months — a
claim from January 2023 is as likely to be pending as one from last month. The median
pending claim is 737 days old and 77% of the receivable is past any payer's filing
limit. The ageing is built in full, with the buckets, the days in AR and the value at
risk, and the page says this rather than leaving an executive to conclude the billing
office has collapsed.

**3. A denial never recovers.** 0 of 7,824 denied claims were ever paid — including all
1,913 marked *Corrected* and 1,946 marked *Appealed* — and the denial date equals the
adjudication date on every one, so there is no appeal timeline either. Appeal yield,
overturn rate and recovery days are the four numbers a denials manager actually works
to, and none of them is computable here. The recovery rate is published reading
**0.00%**, so that this is stated rather than quietly omitted.

**4. Nothing predicts a denial except who is paying.** Self Pay denies at 2.95% against
8.79% for the five insurers; among those five the spread is 0.66 points. Every other
candidate — facility type, specialty, chronic risk band, gender, state, procedure,
diagnosis, patient age, claim size, line count — is inside chance. A chi-square test of
all ten dimensions is computed **in SQL on every refresh**, and nine of them score
Cramér's V below 0.015 against the payer's 0.081.

Provider denial rates run 3% to 14% across 500 providers, which looks like a league
table. It is noise: **23 providers sit beyond two standard errors — 4.6%, against the
4.55% a normal distribution predicts** — and the most extreme is z = 3.3, about the
maximum 500 draws produce. The report publishes the distribution against its own chance
baseline instead of ranking names.

**5. The procedure code does not price the procedure.** Every one of the ten CPT codes
averages between $391.76 and $397.46 per line, across codes that in practice run from a
venipuncture to an MRI of the brain with contrast. Case mix, cost per procedure and
service-line profitability are therefore off the table, and no page ranks a procedure by
revenue.

Plus one trap: **the supplied calendar stops at the last SERVICE date**, leaving 4,807
adjudication, payment and denial dates outside it. Joined to it, those rows would land
on a blank date and vanish from any measure sliced by adjudication or payment month —
while the totals still looked right. The build generates its own calendar and keeps a
flag so the gap stays visible in the data.

---

## Evidence

| Check | Result |
|---|---|
| SQL build and validation (`SQL/08_validation.sql`) | **121 of 121** |
| Semantic model vs the live SQL views (`verify_semantic_model.py`) | **966 of 966** |
| Every measure vs independently written SQL (`reconcile_measures.ps1`) | **700 of 700** |
| Every visual's own query returns data (`validate_visuals.ps1`) | **210 of 210** |
| Layout, navigation and theme (`validate_report_layout.py`) | **0 issues** |
| Interaction: slicers, calculation groups, field parameter, RLS (`test_interactions.ps1`) | **46 of 46** |
| Query folding to SQL Server (`check_query_folding.sql`) | **24 of 24 views folded** |
| Eight Power BI Desktop open-and-refresh cycles | **306 files, 0 changed** |

Every figure above was re-measured against the finished, hand-formatted report and a
database rebuilt from `Data/raw` — not carried over from the generated version.

The two identities the project rests on hold exactly:

```
allowed       = collected + patient responsibility + open AR + denied      (every row)
AR(m)         = AR(m-1) + submitted - collected - patient resp - denied    (all 47 months)
```

Open AR read from the 670,151-row snapshot agrees with open AR read from the claim
header **to the cent** — two entirely separate routes to the same number.

Every page was also opened and inspected as a rendered capture
(`Validation/evidence/`), which is how defects that every query check passes get found.
Nine of them did: the sharpest was three "clocks" plotted on two different calendars —
days to submit and days to adjudicate read the claim table, active on the *service*
date, while days to cash read the payment table, active on the *payment* date. On one
axis that put service months and payment months together, and the line ran off the top
of the chart in the last two months, when cash was still arriving for care delivered
earlier.

---

## The eight pages

| | |
|---|---|
| **Revenue Cycle** — billed to allowed to collected, month by month | **Accounts Receivable** — the ageing, and what is past filing |
| ![Revenue Cycle](Validation/evidence/listing/cycle.png) | ![Accounts Receivable](Validation/evidence/listing/ar.png) |
| **Denials** — reasons, payers, and a recovery rate that reads 0.00% | **What Predicts a Denial** — ten dimensions tested, one signal |
| ![Denials](Validation/evidence/listing/denials.png) | ![What Predicts a Denial](Validation/evidence/listing/evidence.png) |
| **Timeliness** — three clocks, each on its own calendar | **Service & Patient Mix** — volume and value by service and cohort |
| ![Timeliness](Validation/evidence/listing/timeliness.png) | ![Service and Patient Mix](Validation/evidence/listing/mix.png) |
| **Data & Method** — the audit findings, and what each one cost | |
| ![Data and Method](Validation/evidence/listing/method.png) | |

---

## How it is built

| Layer | What |
|---|---|
| Data | 10 CSVs → `HealthcareRCMBI` on SQL Server: 10 staging tables, 15 dimensions, 6 facts, 25 analytics views. Rebuild with `SQL\run_all.ps1` in 36 s |
| Derived | `DimDate` — **generated**, not loaded — plus `FactARSnapshot` (a monthly stock, 670,151 rows) and `FactARMovement` (a signed ledger, 246,040 rows). A snapshot and a ledger check each other |
| Model | 28 tables, 44 relationships, 118 measures, **two calculation groups** and a field parameter, RLS by facility — generated by `Python/02_generate_semantic_model.py` |
| Report | 8 pages behind a **top navigation bar**, 210 visuals of 21 types, on a dark teal operations-console theme — first generated by `Python/04_generate_report.py`, then finished by hand |
| Validation | Ten scripts in `Validation/`, from TMDL parsing to a Power BI save round trip |

The whole PBIP was written by Python in Power BI's own save format, which is what makes
the model reviewable as code and leaves a genuine Ctrl+S in Desktop with nothing to
rewrite — eight open-and-refresh cycles changed 0 of 306 files.

> **The report is now hand-maintained.** Its layout and formatting were finished in
> Power BI Desktop after the generator last ran, so `Python/04_generate_report.py` no
> longer knows about it and **would overwrite it**. Treat the committed PBIR as source
> and edit it in Desktop; run the generator only on a copy, or to rebuild the report
> from scratch on purpose. Every other script here is safe to re-run — the semantic
> model, the SQL build and all ten validation scripts.

### Three ideas worth a closer look

**Every fact carries its own dimension keys, and the verifier enforces it.** A filter
never travels from one fact table to another. If payer, facility, provider and patient
lived only on the claim header, then *"line volume by payer"* or *"denials by
specialty"* would filter the claim table and leave the other one whole — a full
numerator over a shrinking denominator, which reads as a plausible number and is wrong.
That costs four integers per row. `verify_semantic_model.py` fails the build if any
conformed dimension stops reaching any fact, and `test_interactions.ps1` reconciles six
such questions against SQL.

**Four dates, one fact table.** A claim has four clocks — when the care happened, when
the claim was submitted, when the payer adjudicated, when it resolved into cash or a
denial — and they answer different questions. Rather than four copies of the fact there
are four relationships, one active, and a **Date Basis** calculation group that switches
between them with `USERELATIONSHIP`. A second group, **Time Comparison**, sits at higher
precedence so it wraps the first: *"prior month on submission date"* means the month
before, measured on submission — not the submission-date version of last month's service
figure. Both precedences are tested.

**The snapshot earns its 670,151 rows.** Open AR at every month end takes **20 ms** from
the snapshot against **339 ms** computed from dates at query time — and the snapshot is
also what makes the receivable *ageable* at all, because a receivable's age is a
property of a date, not of a claim.

---

## Layout

| Folder | Contents |
|---|---|
| `SQL` | `01`–`08`, in order, plus `run_all.ps1` |
| `Python` | Data audit, semantic model, measure dictionary, report |
| `PowerBI` | The PBIP: semantic model and report definitions |
| `Validation` | The test harness and its evidence |
| `Documentation` | Data quality report, semantic model, DAX dictionary, visual catalogue, publish readiness |

The audit script takes its source folder from `--source`, the `RCM_SOURCE` environment
variable, or a git-ignored `config.local.json`. **No machine-specific path is
committed**, and no credentials: the SQL connection uses Windows authentication.

## Licence

[MIT](LICENSE) — the code. The dataset is a synthetic portfolio dataset, included in
`Data/raw` so the build is reproducible from a clone.

## Status

See [PROJECT_STATE.md](PROJECT_STATE.md) for phase status, the decision log, and what
is and is not verified.
