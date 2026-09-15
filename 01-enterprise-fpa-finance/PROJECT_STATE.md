# Project State — Enterprise FP&A Finance

Change-control record, updated at every phase boundary. Project 3 of a five-project
Power BI portfolio. The dataset is **synthetic** (the fictional "Northstar" group) and
must never be presented as real company data.

## Completed

- **Phase 1 — Repository, data audit and SQL platform.** ✅
  - `Python/01_data_audit.py`: **5 ERROR, 10 ANOMALY, 5 EXCEPTION, 4 INFO** —
    see `Documentation/data_quality_report.md`. Money measured in `Decimal` with the
    build's own rounding rule, so every expected value is exact.
  - `FinancePlanningBI` built by `SQL/run_all.ps1` in 13.5 s: 14 files staged at their
    published row counts; typed star schema with 39 trusted foreign keys; every GL line
    translated to AUD; one plan-and-actual fact (`FactFinancials`, 168,782 rows);
    receivables and payables stated as of the as-of date; 17 analytics views.
  - `SQL/09_validation.sql`: **108 of 108** checks against independently measured values.

- **Phase 2 — Semantic model.** ✅
  - `Python/02_generate_semantic_model.py` generates the whole PBIP as code: 20 tables +
    **2 calculation groups** (11 items), 153 columns, 23 relationships (19 active), 1 role
    with 6 table filters, **130 measures** in 11 folders. See `Documentation/semantic_model.md`.
  - SQL extended for the model: `DimPLLine` (the statement layout) and
    `analytics.vw_DataQualityMetric` (15 metrics computed live from `dbo`);
    `09_validation.sql` now runs **116 of 116** checks.
  - `Validation/parse_tmdl.ps1`: the TMDL folder is parsed by the Tabular deserialiser
    before Power BI ever opens it.
  - `Validation/verify_semantic_model.py`: **784 of 784** static checks, including every
    column against its live SQL view.
  - Refreshed through the engine with no manual step (≈9 s): all 19 tables equal their
    SQL row counts and both calculation groups load.
  - `Validation/reconcile_measures.ps1`: **521 of 521** live checks — every measure swept,
    then the income statement by year, version, entity, department and account, both
    calculation groups (including precedence), FX and constant currency, working capital
    as of two different dates with its ageing buckets, cash, the scenario outlook, the
    data-quality metrics, and security.
  - `Documentation/dax_measure_dictionary.md`, with each measure's value taken from the
    live model.

- **Phase 3 — Visual lab and the client's theme.** ✅
  - `Python/04_generate_report.py` generates 3 lab pages: **53 visuals of 24 types**, each
    bound to a measure it will show in the report, checked against the PBIR schemas and the
    model's fields before writing.
  - The client's reference design applied as a registered custom theme plus matching
    generator colours: `NorthstarSpectrum.json` (see D36 — the first cut read as one
    static amber accent and was reworked into a rotation).
  - Every page rendered and inspected (`Validation/evidence/phase3/`), with
    `Validation/render_pages.ps1` writing one page at a time because Desktop cannot be told
    which page to open.
  - Proven in the lab: the Plan Version calculation group on a matrix's columns (including
    variance signs and percentage-point margins), a calculation group filtered to four items,
    the dead-zone variance heatmap, the gauge against a real target, the scenario and
    sensitivity visuals over disconnected driver tables, and the live data-quality view.

- **Phase 4 — Domain review and report pages.** ✅
  - The data was cross-checked the way an FP&A lead would before any page was built:
    year-on-year and constant-currency growth, variance signals by department-month,
    working-capital speed, cash, the scenario outlook and every figure quoted in page
    text. The review found **five model defects** that every query check had passed
    (D28–D31) and they were fixed and re-checked.
  - Report: **8 pages, 193 visuals of 23 types** — see `Documentation/visual_catalogue.md`.
  - Evidence: SQL **116 of 116**; static **797 of 797**; live **868 of 868** — every
    measure, every report figure at its visual's grain (including the variance
    z-scores, the ageing buckets as of two dates, the scenario outlook and the
    month-end balance series), and security; visual queries **193 of 193**; layout and
    navigation **0 issues**. Every page was inspected in a capture across two render
    passes: 13 defects were found and fixed (`Validation/evidence/phase4/`).

- **Phase 5 — Publish readiness.** ✅ See `Documentation/publish_readiness.md`.
  - **Save round trip:** a genuine Ctrl+S in Desktop changed **0 of 257** project files
    (the save is real: `cache.abf` and the settings files were rewritten).
  - **Security: 77 of 77** — the secure default (an unmapped user sees nothing), every
    one of the 18 users' scopes, what each would see against SQL, and treasury hidden
    from department-scoped users.
  - **Interaction: 18 of 18** — slicers, both calculation groups together, scenario
    buttons, cross-filtering, drill, and the as-of guard under selection.
  - **Query folding: 19 of 19** analytics views read with a folded column-list SELECT,
    0 unfolded, proven from Query Store.
  - **Performance:** full refresh 2.1 s; slowest page query 381 ms; model 6.2 MB.
  - **Scale:** at a generated 1,000,000-line ledger the same question takes 269 ms
    line-level against 23 ms on the monthly fact, which stays at 168,782 rows.
  - **Listing screenshots:** `Validation/evidence/listing/` - eight canvas-only crops.

## Next

- Nothing outstanding for this project. Publishing to the Power BI Service (scheduled
  refresh, gateway, workspace security) is out of scope and untested by definition.

## Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | Three SQL schemas: `stg` text landing, `dbo` typed star, `analytics` views | A bad value can never abort a load; typing failures fail loudly in `dbo`; the views are the sole Power BI contract. |
| D2 | Data path passed to `sqlcmd` as an environment variable | No machine-specific path in Git. |
| D3 | Calendar regenerated to 2027-06-30 (end of FY27); financial year July–June | The supplied calendar ends on the as-of date, but AR/AP due and payment dates run to January 2027. Regenerated days match the supplied calendar on all 1,704 overlapping days. The supplied FY columns show an Australian year (FY26 = Jul 2025 – Jun 2026), consistent with an AUD group. |
| D4 | **As-of date = the last ledger day, 2026-08-31; balances are computed from dates** | Never `GETDATE()`. A document is open on day D if issued by D and unpaid on D. The source `Status` reflects an extract taken later: 769 receipts (7.38M) and 395 payments (2.33M) are dated after the as-of date, so those documents were open on it. |
| D5 | **AUD fixed at exactly 1** | AUD is the reporting currency, yet 1,697 of 1,704 supplied AUD rates differ from 1 (0.95–1.05). The supplied value is kept in `FxRateDaily.AUDPerUnitSupplied`. |
| D6 | **P&L actuals translated at the monthly average rate** | IAS 21 average-rate practice. The daily rates are noise (1.7% a day around a mean flat to 0.3% over five years); spot translation would add random error to every line. Totals differ by 0.005%. The day's spot amount and the prior year's monthly rate are kept per line, the latter for constant-currency analysis. |
| D7 | **Ledger sign in the data, presentation sign in the model** | Every table keeps debit + / credit − (revenue negative). Measures show revenue and costs as positive numbers and profit as revenue − costs; a variance is positive when favourable. |
| D8 | **One plan-and-actual fact, `FactFinancials`** (version × month × entity × department × account) | Actual vs budget vs forecast is one measure under three versions — exactly what a calculation group does. Actual rows are the ledger summed to the month (47,822 rows for 80,000 lines), equal to `FactGL` to the cent at every grain (checked). The line-level `FactGL` stays for drill-through. |
| D9 | **The forecast is one version; its `Scenario` column is not a scenario** | Every forecast line has exactly one label, split 60/20/20, and the label does not change the value (Worst revenue lines sit at 1.001 × budget). Filtering to "Base" would drop 40% of the plan. The label is kept as an attribute; scenarios are modelled with disconnected driver tables (`DimScenario`) holding labelled, illustrative assumptions. |
| D10 | **Plan comparisons stop at operating profit** | Interest, FX gain/loss and tax have actuals but no budget or forecast. Below-the-line items are shown as actuals only — never as a 100% variance. |
| D11 | **The actual-vs-plan gap is structural: reported as measured, never rescaled** | Actual revenue is 69% of budget, opex 67%, COGS 117%, in every one of 56 months with no trend, and payroll posts in only 68% of department-months: the ledger is a partial extract. Filling or rescaling would fabricate data. The report shows the variance, labels it as plan calibration, and leads with measures coverage cannot distort. |
| D12 | **Entities are compared on currency-neutral ratios** | Local amounts share one scale in every currency, so after (correct) translation an entity's size follows its exchange rate (UK revenue 96% of budget, Australia 54%). Gross margin and cost-to-revenue are unaffected by translation. |
| D13 | **Working-capital days use each sub-ledger's own flows** | AR invoicing is 2.9× GL revenue: the sub-ledgers and the GL are independent extracts. DSO = open AR on the date ÷ last-90-day invoicing × 90 (DPO likewise from bills). Because 18% of invoiced value is never collected and never written off, DSO (314) is shown beside days-to-collect on paid invoices (74) and the over-365 balance, so the uncollected stock is not mistaken for slow payment. |
| D14 | Unknown members `C-NONE` / `V-NONE` in the views | A ledger line with no customer or vendor shows "Not specified", never a blank member; `dbo` keeps the true NULL. |
| D15 | **Security: entity scope everywhere, department scope on the P&L** | AR, AP and cash have no department. A department-scoped user sees their department's P&L across entities and no receivables, payables or cash — group treasury data is not part of a cost-centre view. |
| D16 | Query Store enabled on the database | Records the statements Power BI sends during refresh, so query folding can be proven from the server side (Phase 5). |
| **D17** | **The whole PBIP is generated as code** | Declarative spec → TMDL matching Power BI's own output (tabs, CRLF, `///` descriptions). Lineage tags are uuid5 of the object path, so a re-run is byte-identical. |
| **D18** | **Two calculation groups: Plan Version (precedence 20) and Period View (10)** | Plan Version is applied outermost, so "Var % vs Budget" of a year-to-date figure divides two year-to-date figures. Verified, not assumed: the reconciliation compares the calculation group against the same arithmetic written by hand for every period item. |
| **D19** | **A measure with no version filter means ACTUAL** | `ISFILTERED ( FactFinancials[VersionID] )` decides, so versions are never summed and a visual without the calculation group still reads the actuals. |
| **D20** | **Variance is favourable-positive; no plan means no variance** | For a cost, plan less actual (an underspend is favourable). The sign comes from the measure, the statement line or the account. Interest, FX and tax have no budget, so their variance is blank rather than a 100% miss. Margins vary in percentage points and "Var %" is blank on them. |
| **D21** | **Period windows are capped at the as-of date BEFORE they are shifted** | FY27 holds two months of actuals; an uncapped `SAMEPERIODLASTYEAR` would compare them with a full FY26. |
| **D22** | **"Trailing 12 months" is a measure, not a calculation item** | A calculation item whose window REPLACES the date filter (`DATESINPERIOD`, or a hand-built `DATESBETWEEN`) makes `SUMMARIZECOLUMNS` emit an extra blank-year row when the visual also groups by a date column — seen, not theorised. `DATESYTD` and `SAMEPERIODLASTYEAR` do not. Trailing-twelve-month figures are explicit measures anchored to the as-of date and documented as card-only. |
| **D23** | **Balances and ageing are computed from dates, and ageing is dynamic** | `[Balance Date]` is the last day in context capped at the as-of date. `[AR Ageing Amount]` ages each document against that date rather than reading the stored as-of bucket, so the ageing is correct for any period a user selects. |
| **D25** | **A page-level filter sets a default period; a slicer cannot** | A default selection written onto a slicer as a visual-level filter does NOT preselect anything (lab 1: the slicer still read "All"). A page-level `filterConfig` does work. Since a page filter and a year slicer on the same page would intersect - pick another year and the page empties - report pages state their window in as-of-anchored measures instead, and keep slicers for dimensions. |
| **D26** | **Sizing rules taken from the lab renders** | Gauge ≥ 110 px or the arc is clipped; multi-row card ≥ 110 px for three values; decomposition tree ≥ 260 px; a table ≥ 180 px; a button slicer ≈ 120 px per option ("Downside" truncated at 100); a calculation group on columns fits four items in a half-width matrix, not seven. |
| **D28** | **A balance is blank for a period that starts after the as-of date** | Found in a render: cash and receivables ran flat into 2027, because `[Balance Date]` capped at the as-of date and so repeated that balance for every future month. |
| **D29** | **A BLANK date passes a "<= as-of" filter in DAX** | Found in the domain review: days-to-collect read 59.7 against a measured 73.8, because unpaid invoices (no paid date) counted in collections. Every paid-date filter now carries `NOT ISBLANK`, and the reconciliation checks the unfiltered grain — the only grain that exposes it. |
| **D30** | **A prior-year figure is blank unless the ledger covers the earlier window** | FY22 holds six months (the ledger starts January 2022), so FY23 showed +101% growth. The guard applies to the measures and to the Period View items. |
| **D31** | **Constant currency is blank unless every row in the period has a prior-year rate** | FY23 was half-covered, which produced a +105 pp "FX effect". |
| **D33** | **A short entity name for chart axes** | "Northstar UK" truncates to "Northstar..." on a narrow axis, which identifies nothing; `EntityShort` gives axes "UK", "US", "Holdings", while slicers and tables keep the full name. |
| **D34** | **The KPI visual was rejected after rendering it** | Below goal it fills the whole panel with the goal-distance colour and buries its own number on a dark canvas. Muting the theme's "bad" colour fixed the panel but dulled the waterfall's decrease bars, which share it. A stacked column of revenue by stream took its place. |
| **D35** | **RLS is proven by the role's own logic, not by impersonation** | The engine's `EffectiveUserName` needs a real Windows account, so synthetic addresses cannot be impersonated locally. The role's filter expressions are evaluated per user instead, and each user's visible revenue is compared with SQL. Desktop's "View as other user" stays a manual check. |
| **D37** | **The save round trip only tests what Power BI thinks is dirty** | Through Phase 5 the model had not changed since Desktop last saved, so a save rewrote almost nothing and "0 of 257" passed over six generator defects. Adding one measure made the model dirty and Desktop rewrote the project properly: three properties it does not accept (slicer `header.fontSize`, gauge `dataPoint.fillColor`/`targetColor`, tableEx `total.show`) were stripped, `height` was moved before `width` in every visual, the calculation groups lost their redundant `ordinal:` lines, and 1,280 lines of Q&A linguistic schema were regenerated in a file the generator had been overwriting with a stub. All six fixed; the re-run is 0 of 257 on a genuinely re-serialised project. |
| **D36** | **The theme is a rotation, not an accent** | The first cut read the reference design as charcoal plus one amber highlight, and on review it was exactly that: gold on black on every page. The reference varies its colour instead, so the theme was reworked - each card wears its own hue and tints its own panel, each page opens on its own hue (which the rail wears), and each chart takes its subject's hue against an always-indigo plan. Checked mechanically by `validate_report_layout.py`, so it cannot collapse back. |
| **D32** | **"Budget lines with no posting" compares KEYS, not a posting count** | Every plan row has a blank posting count, so the first version counted all 60,480 budget lines instead of 19,468 — caught on the rendered card, not by any query check. |
| **D27** | **Two lab visuals were rejected on the evidence** | The ribbon chart of department spend is spaghetti - ten departments whose ranks barely move; and a "cost mix" built on every account group silently included revenue. Both are replaced in Phase 4 rather than carried over because they render. |
| **D24** | **The TMDL is parsed before Power BI opens it** | A malformed TMDL makes Desktop open a blank "Untitled" document with no error on screen; the refresh then "succeeds" against an empty model. `Validation/parse_tmdl.ps1` reports the document, line and text instead, and `open_powerbi.ps1` now fails when the model loads with no tables. |

## Open issues

| # | Issue | Status |
|---|---|---|
| 1 | Actuals run at a fixed fraction of plan (D11) | **Accepted** — reported as measured and labelled; to be presented as plan calibration |
| 2 | Group operating loss in both plan and actuals (FY26 margin −86% actual, −67% budget) | **Accepted** — reported as measured |
| 3 | 18% of receivables never collected, none written off | **Accepted** — ageing, DSO and days-to-collect reported side by side (D13) |
| 4 | Cash balances are an unlinked random walk with a 50,000 floor | **Accepted** — closing balances only; no cash-flow bridge |

## Honesty register

| Item | Status | Evidence |
|---|---|---|
| Raw file format (CRLF, no quotes, rectangular) | **Verified** | CR count = LF count in all 14 files; staging loads every published row count |
| Data-quality findings | **Verified** | `Python/01_data_audit.py` from the raw CSVs |
| SQL build and 108 validation checks | **Verified** | Clean end-to-end `run_all.ps1`, 108 of 108 (`09` throws on any failure); literals measured independently by the pandas audit |
| FX translation (monthly average, AUD = 1) | **Verified** | Monthly-rate checksum and all five account-group totals equal pandas to the cent |
| Receivable and payable balances and ageing on the as-of date | **Verified** | Counts, balances and all seven ageing buckets equal pandas to the cent |
| Semantic model: TMDL parses, loads and refreshes | **Verified** | `parse_tmdl.ps1`; engine refresh in ≈9 s with all 19 tables at their SQL row counts |
| Model files vs SQL views (names, types) | **Verified** | `verify_semantic_model.py`, 784 of 784, against the live views |
| Every measure evaluates, and every figure matches independent SQL | **Verified** | `reconcile_measures.ps1`, 521 of 521, including both calculation groups and their precedence |
| Security: secure default and every mapped user's scope | **Verified** | An unmapped user sees no entities and no revenue; all 18 mappings evaluated |
| Visual lab: 53 visuals, 24 types render | **Verified** | Every lab page inspected in a `PrintWindow` capture (`evidence/phase3`) |
| Report: 8 pages, 193 visuals, every figure vs independent SQL | **Verified** | `reconcile_measures.ps1` 868 of 868 on the finished report; `validate_visuals.ps1` 193 of 193; layout 0 issues; every page inspected in a capture (`evidence/phase4`) |
| Every figure quoted in page text | **Verified (re-measured)** | Each number in a note was measured in the live model during the domain review |
| Save round trip: Power BI's own save changes nothing | **Verified** | `save_round_trip.ps1`: 257 files compared, 0 changed, with `cache.abf` rewritten in the same window |
| Row-level security, including what each user would see | **Verified** | `test_security.ps1`, 77 of 77 |
| Interaction: slicers, calculation groups, cross-filter, drill | **Verified** | `test_interactions.ps1`, 18 of 18 |
| Query folding to SQL Server | **Verified** | `check_query_folding.sql`: 19 of 19 views folded, 0 unfolded, from Query Store |
| Performance and behaviour at volume | **Verified** | `measure_performance.ps1`; `SQL/10_scale_test.sql` at 1,000,000 ledger lines |
| Desktop's "View as other user" | **Not verified** | A UI action; impersonation needs a real Windows account (D35) |
| Anything in the Power BI Service | **Not verified** | Never published: scheduled refresh, gateway and workspace security are out of scope |
