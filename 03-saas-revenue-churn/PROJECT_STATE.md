# Project State - SaaS Revenue, Retention & Churn

Where the build is, what was decided and why, and what is and is not yet verified.
The dataset is **synthetic** - a portfolio dataset for a fictional SaaS business - and is
never presented as a real customer base.

| | |
|---|---|
| Source | `PowerBI_Hard_Portfolio_Dataset_Pack/powerbi_hard_portfolio_datasets/03_saas_revenue_churn` |
| Database | `SaaSRevenueBI` on `localhost\SQLEXPRESS` - rebuild with `SQL\run_all.ps1` |
| As-of date | **31 Aug 2026** - every point-in-time figure is stated on it |
| Financial year | Starts 1 July (the source's own convention), so FY27 = Jul 2026 - Jun 2027 |

## Phases

- **Phase 1 - Data audit and the SQL platform.** ✅
  - `Python/01_data_audit.py` answers, before anything is built, what the data can
    support: it writes `Documentation/data_quality_report.md` and
    `Validation/audit_metrics.json` (75 measured figures, nothing typed from memory).
  - `SQL/01`-`09` build `SaaSRevenueBI`: 9 staging tables, 9 dimensions, 7 facts,
    19 analytics views. **91 of 91 validation checks pass.**
  - Two derived tables carry the project: `FactSubscriptionMonth` (320,294 rows - one
    per subscription per month it is live at month end) and `FactMRRMovement` (14,292
    rows - one per customer per month its MRR changed, with the change classified).
  - Both reconciling identities hold exactly, every month:
    `MRR = prior MRR + movements` and `customers = prior + new - churn`.

- **Phase 2 - Semantic model as code.** ✅
  - `Python/02_generate_semantic_model.py` + `Python/model_measures.py` write the whole
    PBIP semantic model in TMDL: **20 tables + 1 calculation group + 1 field parameter,
    142 columns, 24 relationships, 87 measures**, RLS by country.
  - **605 of 605** static checks (`verify_semantic_model.py`) against the live SQL views.
  - **870 of 870** live checks (`reconcile_measures.ps1`): every measure evaluated alone,
    then compared with independently written SQL - MRR and customers month by month, the
    movement ledger, both retention bases, 54 cohorts, the cuts, usage, support, billing,
    unit economics, the calculation group and the field parameter.
  - Security: the secure default (an unmapped user sees nothing) plus all eight users'
    scopes and their visible MRR against SQL.

- **Phases 3-4 - The report.** ✅
  - `Python/04_generate_report.py` wrote 8 pages, **204 visuals of 22 types**, on the
    client's light crimson-and-pink theme (see `Documentation/visual_catalogue.md`).
  - The report was then finished by hand in Power BI Desktop and now carries **188
    visuals of 22 types**; `PowerBI/` is hand-maintained from here on and must not be
    regenerated. **188 of 188** visual queries return data. `validate_report_layout.py`
    reports 17 deviations from the generator's conventions, all of them deliberate
    hand-finishing (slicers moved into the rail, gain/loss colouring, one overflowing
    caption).
  - Fourteen defects found by rendering and fixed - including one model defect that no
    query check could have caught (see D13).

- **Phase 5 - Publish readiness.** ✅ See `Documentation/publish_readiness.md`.
  - **Save round trip:** a genuine Ctrl+S in Desktop changed **0 of 268** project files,
    first time - the generator carries the format lessons from the previous project.
  - **Interaction: 26 of 26** - slicers, the calculation group under a slicer, all six
    field-parameter cuts, cross-filtering, and the data boundary.
  - **Query folding: 19 of 19** analytics views read with a folded column-list SELECT.
  - **Performance:** full refresh 2.1 s; slowest page query 50 ms; model 8.8 MB.
  - **Why the snapshot exists, measured:** MRR at all 56 month ends takes **6 ms** from
    the snapshot against **60 ms** computed from dates at query time.
  - **Listing screenshots:** `Validation/evidence/listing/` - eight canvas-only crops.

## Next

- Nothing outstanding. Publishing to the Power BI Service (scheduled refresh, gateway,
  workspace security) is out of scope and untested by definition.

## What the data does and does not support

These came out of Phase 1 and they shape everything after it.

| # | Finding | Consequence |
|---|---|---|
| **F1** | **MRR is one static value per subscription**, and all 12,000 subscriptions bill exactly one invoice amount for life | A full MRR waterfall is impossible. New and Churn are real; **Expansion, Contraction and Reactivation are structurally nil** |
| **F2** | **One subscription per customer, ever** | No customer can leave and return, so reactivation cannot occur even in principle |
| **F3** | F1 + F2 mean **NRR = GRR**, always | Any net revenue retention above 100% on this data would be an arithmetic error, not good news |
| **F4** | **The newest subscription starts 30 Jun 2026**; churn runs to 30 Aug 2026 | The last two months show losses and no wins. MRR peaks at $2.80M in Jun 2026 and reads $2.76M at the as-of date - an artefact of where the extract ends, not a decline |
| **F5** | **Usage covers ~40% of paying customers** in any month (median 9 months observed per customer) | Adoption, seats and logins are reported as a sample, never as a rate over the customer base and never as a denominator for revenue |
| **F6** | **Product usage is statistically independent of churn** - adoption, logins, seats, utilisation and errors all sit inside \|r\| < 0.02 | The churn model the brief asks for would fit noise. A tested driver view is built instead, with the measured strengths shown on the page |
| **F7** | **Raw counts measure tenure, not behaviour.** Raw ticket count r = -0.00 and raw failed-invoice count r = -0.09; per month of tenure the contact rate becomes +0.15 | Support and payment behaviour are only ever expressed as rates. Both the raw and the adjusted figure are shown, because the contrast is the lesson |
| **F8** | **Price point is the one strong, real driver**: Starter churns at 26.1%, Growth 18.4%, Business 12.9%, Enterprise 7.8%, and the gradient holds inside every segment | The risk view is built on plan tier and contact rate - smaller than the brief asked for, and the part that is true |
| **F9** | Segment, industry, country and acquisition channel are **flat** (0.9-5.5 pp spread); CAC is flat across channels too (~$120 on a ~$2,017 base) | Those cuts are shown because a reader will ask for them, and labelled as having no signal |
| **F10** | **No cost of service anywhere in the data** | Lifetime value and CAC payback cannot be derived, only modelled. Gross margin is a stated assumption held in `ModelConfig` and shown beside every figure that uses it |
| **F11** | **Unresolved tickets carry a resolution time** (all 18,142 of them), drawn from the same distribution as resolved ones | Mean time to resolve uses resolved tickets only, and no claim is made anywhere that escalation takes longer to fix |

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | MRR is held as a **monthly snapshot**, not computed from dates in DAX | MRR is a stock. A snapshot makes a point-in-time read trivial, makes a cohort matrix a pivot instead of a window function, and is what lets the identities in `09_validation.sql` be checked at all |
| **D2** | The movement ledger **classifies all five movement types** even though three cannot occur | The logic is visible and tested rather than quietly omitted; the report shows the three empty components and says why |
| **D3** | A subscription ending on the 30th is **not live at the 31st** | MRR is read at month end. Phase 1 checked no subscription starts and ends inside one month (the shortest lives 90 days), so nothing is lost by the rule |
| **D4** | Acquisition **source and attribution live on the customer**; only the **cost** is a fact | They describe the customer, not an event. The cost is a number that sums |
| **D5** | `DimCohort` and `DimTenureMonth` are real dimensions, not fact columns | A fact column would sort "Apr 2022" before "Aug 2022" and "M10" before "M2" - a retention matrix needs both axes in time order |
| **D6** | The calendar is **extended to 30 Jun 2027** | The source calendar stops on the as-of date, two months into FY27, so a year-to-date would run off the end of the date table. Added days are flagged and never counted as data |
| **D7** | The churn-driver correlations are **computed in SQL** (`vw_ChurnDriverStrength`), not typed into a text box | The claim that usage does not predict churn is the project's biggest, so it is recomputed on every refresh and re-checked in `09_validation.sql` |
| **D8** | Every assumption lives in **`dbo.ModelConfig`** | The gross-margin assumption in particular must be visible and adjustable, never buried in a measure |
| **D9** | MRR is read through one hidden **`[Snapshot Month]`** measure | A stock summed over months counts the same subscription twice. One definition of "now", used by every point-in-time measure, means they cannot disagree |
| **D10** | `FactSubscription` carries an **inactive** relationship on `EndDate` | One fact answers both "who arrived this month" and "who left this month" without a second copy of it |
| **D11** | A **field parameter** drives the "by" visuals | The brief asked for one, and it is better for the reader than six near-identical charts. Its extended property is checked statically, because losing it fails silently |
| **D13** | **Plan, billing cycle and status are CUSTOMER attributes**, not subscription ones | `FactSubscription` was being used as a dimension - its descriptive columns sliced while the measures came from `FactSubscriptionMonth`. A filter never travels fact to fact, so "contact rate by plan" divided ALL 45,000 tickets by one plan's exposure (1.68 for Enterprise against 0.43 for Starter), and a billing-cycle slicer returned the whole $2.76M of MRR. Sound to move them because every customer has exactly one subscription, for life - and `09_validation.sql` now checks that premise, because the day it stops holding the model is wrong again |
| **D14** | The waterfall uses a measure that returns **0, not blank**, for an impossible movement | A blank component vanishes from the axis, which defeats the point of showing that expansion, contraction and reactivation cannot occur here |
| **D15** | Retention cards use explicit **latest-month** measures | A retention rate has no meaning over all time - there is no month before the first one. A visual-level date filter would have been shorter and wrong: the active date relationship on `FactSubscription` is its START date, so it would have redefined "median tenure" as "of customers who signed up in August 2026" |
| **D16** | The theme is **ink on paper**, and the cards do not rotate through a spectrum | Taken from the client's reference: a light ground, white cards, a solid crimson rail, and two tones of crimson. One hero card per page carries that page's tone; the rest are white with a crimson figure, which is a quieter hierarchy than eight hues in a row |
| **D17** | The navigation buttons are **inverted** relative to every other project in this series | All of them used filled slate rectangles on a dark rail. Here the rail is the block of colour and the selected page is a white block on it - so the series does not read as one report re-skinned eight times |
| **D18** | The dead-zone colour measures were **rewritten for a light ground**, not ported | "Paint the insignificant cells the panel colour so they disappear" means WHITE here. Ported from the dark theme it would have painted every quiet cell a dark block - the opposite of what the trick is for |
| **D12** | `ChurnDriverStrength` is **disconnected** | It describes the whole customer base. A slicer that filtered it would change the population the correlation was computed over, and the number would quietly stop meaning what it says |

## Verified so far

| Claim | Status | Evidence |
|---|---|---|
| The CSVs load without loss and every row is typed | **Verified** | `09_validation.sql` rows and typing sections |
| The star joins - no orphans, no duplicate keys | **Verified** | `09_validation.sql` integrity section |
| Billing ties to MRR exactly (annual = 12x, monthly = 1x) | **Verified** | 177,236 invoices, 0 exceptions |
| The movement ledger explains the change in MRR every month | **Verified** | Identity check, 0 violations |
| The customer count equals prior + new - churn every month | **Verified** | Identity check, 0 violations |
| Expansion, contraction and reactivation are nil | **Verified** | 0 rows each, from derived classification |
| Usage does not predict churn; price point does | **Verified** | `vw_ChurnDriverStrength`, re-checked by 8 named checks |
| Every measure evaluates, and agrees with independent SQL | **Verified** | `reconcile_measures.ps1`, 870 of 870 |
| The model matches the SQL views it reads | **Verified** | `verify_semantic_model.py`, 605 of 605 |
| Row-level security, including the secure default | **Verified** | Role logic per user vs SQL; impersonation is a stated limit |
| Every visual's own query returns data | **Verified** | `validate_visuals.ps1`, 188 of 188 |
| Interaction: slicers, calculation group, field parameter, cross-filter | **Verified** | `test_interactions.ps1`, 26 of 26 |
| Query folding to SQL Server | **Verified** | `check_query_folding.sql`, 19 of 19 views |
| A genuine Power BI save changes nothing | **Verified** | `save_round_trip.ps1`, 268 files, 0 changed |
| Performance and storage | **Verified** | `measure_performance.ps1` |
| Desktop's "View as other user" | **Not verified** | A UI action; impersonation needs a real Windows account |
| That the field parameter resolves its column inside a visual | **Verified by rendering only** | It resolves when Power BI builds the visual's query, so no script can assert it - read the axis in `Validation/evidence/` |
| Anything in the Power BI Service | **Not verified** | Out of scope; nothing is published |
