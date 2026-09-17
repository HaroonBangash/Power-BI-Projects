# Project State — Omnichannel Marketing Attribution

Change-control record, updated at every phase boundary. Project 2 of a five-project
Power BI portfolio. The dataset is **synthetic** and must never be presented as
real client data.

## Completed

- **Phase 1 — Repository, data audit and SQL platform.**
  - `Python/01_data_audit.py`: **4 ERROR, 6 ANOMALY, 4 EXCEPTION, 2 INFO** —
    see `Documentation/data_quality_report.md`.
  - `MarketingAttributionBI` built by `SQL/run_all.ps1`: 10 files staged at their
    published row counts; typed star schema with 25 trusted foreign keys; FX
    planning rates; 874,690-row attribution credit table; 17 analytics views.
  - `SQL/09_validation.sql`: **70 of 70** checks against independently measured values.
  - `Validation/validate_attribution.py`: all 874,690 weights match an independent
    pandas implementation (max difference 6.7 × 10⁻¹⁶).
- **Phase 2 — Power Query and semantic model.** ✅
  - `Python/02_generate_semantic_model.py` generates the whole PBIP as code: 12 tables,
    111 columns, 12 relationships (9 active, 3 inactive), 1 RLS role, 59 measures in
    8 folders. See `Documentation/semantic_model.md`.
  - `Validation/verify_semantic_model.py`: **294 of 294** static checks, including every
    column against its live SQL view.
  - Refreshed through the engine with no manual step: all **11 data tables equal their
    SQL row counts** (874,690 credit rows, 174,938 touches, 80,000 spend lines, …).
  - `Validation/reconcile_measures.ps1`: **157 of 157** live checks — every measure
    evaluated alone, then compared with an independent SQL query, including all five
    attribution models per channel, the date roles and the security role.
  - Campaign aliases: **900 of 900** resolved by Power Query rules R1–R4, 0 mismatched.
  - `Documentation/dax_measure_dictionary.md`, with each measure's value taken from the
    live model.
- **Phase 3 — Phase 1 issues resolved; visual lab.** ✅
  - Open issues 1, 2 and 4 resolved by decisions D24–D26: constant-currency planning
    rates; the spend/revenue gap diagnosed as an ad-vs-CRM scale mismatch (click-to-lead
    0.0196%) and never rescaled; the attribution story told at campaign level.
  - Model extended for the visuals: `DimFunnelStage`, persisted `PositionBand`, 8 new
    measures — now 13 tables, 116 columns, 67 measures.
  - `Python/04_generate_report.py` generates 3 lab pages: **20 visuals of 19 types**, each
    bound to the measure it will show in the report, checked against the PBIR schemas
    and the model's fields before writing. See `Documentation/visual_catalogue.md`.
  - Evidence: SQL **70 of 70**; static **325 of 325**; live **475 of 475** (318 new Phase 3
    checks, including attribution sensitivity for all 300 campaigns); visual queries
    **20 of 20**; every visual inspected in a `PrintWindow` capture
    (`Validation/evidence/phase3/`).
  - Defects the lab caught and fixed: the KPI showed blank (D29); tables with `active`
    flags drew nothing (D32). The canary disproved save-diff as a role check (D31).

- **Phase 4 — Domain review and report pages.** ✅
  - The data was cross-checked the way a marketing-analytics lead would, before any page
    was built: media rates by channel, CRM status against revenue, period completeness,
    cohort maturity, year-on-year, segments, touch types. The findings drove D33–D38:
    outcomes after the as-of date leaking into the funnel, touch-date attribution,
    partial periods and immature cohorts, identical media rates, noise presented as
    signal, and page text re-measured. The pandas audit now lists **4 ERROR, 8 ANOMALY,
    5 EXCEPTION, 3 INFO**.
  - Model: as-of milestone columns, `DimDate` period flags, a per-model campaign
    dispersion; **85 measures** (like-for-like YTD, mature cohorts, binomial and
    fair-share z-tests, dead-zone colour measures).
  - Report: **7 pages** behind the navigation rail, **154 visuals of 23 types** — see
    `Documentation/visual_catalogue.md`.
  - Evidence: SQL **82 of 82**; static **379 of 379**; all 12 tables' row counts equal SQL
    after the engine refresh; live **2,552 of 2,552** — every measure, every report figure
    at its visual's grain, the booking-month tie-out for all 5 models, the signal tests
    and colours recomputed from the credit rows, security; visual queries **154 of 154**;
    layout and navigation **0 issues**. Every page was inspected in a capture across four
    render passes: 13 presentation defects were found and fixed
    (`Validation/evidence/phase4/`).
  - **Client theme (D39):** the client's reference colour scheme — near-black canvas, dark
    panels outlined in green, lime-neon accents — applied to all 7 pages as a registered
    custom theme plus matching generator colours, visuals and content unchanged. Every page
    was re-rendered and inspected in the theme; 7 theme-specific defects (truncation,
    contrast, clipping) were found and fixed, and the signal colours were re-reconciled.

- **Phase 5 — Publish readiness.** Partly done, on 2026-09-17.
  - The report was finished by hand in Power BI Desktop after the generator last ran.
    It now carries **148 visuals of 23 types** (was 154). **`PowerBI/` is hand-maintained
    from here on: do not run `Python/04_generate_report.py` over it.**
  - **Save round trip: 198 files, 0 changed** across seven Desktop open-and-refresh
    cycles — measured on a copy so the repository was never opened by Desktop.
  - Re-measured against the finished report and a database rebuilt from `Data/raw`:
    SQL **82 of 82**; static **379 of 379**; live **2,552 of 2,552**; visual queries
    **148 of 148**; attribution weights **4 of 4** against independent pandas; layout
    and navigation **0 issues**.
  - **Listing screenshots:** `Validation/evidence/listing/` — seven canvas-only crops
    of the finished, hand-formatted report.
  - Published to `HaroonBangash/Power-BI-Projects` as `04-omnichannel-marketing-attribution`.

## Next

- Still outstanding from Phase 5: interaction testing (slicers, the model selector,
  cross-filtering, drill), RLS *View as* for a mapped user, and query folding
  (*View Native Query*). None of these has been run on this project.

## Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | Three SQL schemas: `stg` text landing, `dbo` typed star, `analytics` views | A bad value can never abort a load; typing failures are counted, not truncated; the views are the sole Power BI contract. |
| D2 | Data path passed to `sqlcmd` as an environment variable | No machine-specific path in Git. `-v` with a spaced path fails under PowerShell 5.1. |
| D3 | Calendar regenerated to 2027-06-30 (end of FY27) | Supplied calendar ends 2026-08-31; opportunities and revenue run to 2026-10-21. Regenerated days are checked against the supplied calendar for all 1,704 overlapping days. |
| D4 | As-of date derived as the last day of marketing activity: **2026-08-31** | Never `GETDATE()`. The 244 opportunities and 209 revenue rows (888,614.96) dated later are loaded and flagged `IsAfterAsOf`, not dropped. |
| D5 | Journeys ordered by `TouchDate`, same-day ties by `TouchSequence` | The supplied sequence contradicts the calendar for 71% of leads and carries no behavioural signal. Time-decay is defined in days. |
| D6 | Funnel stage derived from evidence | 2,428 leads with booked revenue are still labelled "Opportunity". Revenue → Customer, opportunity → Opportunity, otherwise the CRM label. |
| D7 | **Static planning FX rates:** USD 1.00, EUR 1.08, GBP 1.27, AUD 0.66 | The source has four spend currencies and no rates. Labelled NOT market data in `dbo.FxRate.Source`. The table is dated so a real feed can replace it. |
| D8 | Spend is **not rescaled**, although it is ~34× revenue | Rescaling would fabricate the data. ROAS is reported as measured; storytelling leads with the scale-free Revenue-to-Spend Index. |
| D9 | Spend lines sharing Date × Campaign × Channel are kept as separate lines | 9,275 such groups, 0 exact duplicates, 77% mixing currencies — billing lines, not duplicates. |
| D10 | Campaign `StartDate` is recorded but never used as a filter | 42% of spend, 20,984 leads and 77,260 touches predate it. |
| D11 | Row-level security by **campaign Region** | Lead country is independent of campaign region. A regional team sees the spend and attributed credit of the campaigns it owns. |
| D12 | Attribution precomputed in SQL; conversion event = lead creation | 874,690 weights computed once, auditable per row, independently verified. 7-day time-decay half-life; 40/40/20 position split — all in `ModelConfig`. |
| D13 | Attributed revenue carries `IsRevenueAfterAsOf` rather than excluding late revenue | Every model conserves the full 31,756,120.64; the measure layer applies the as-of anchor. |
| **D14** | **The whole PBIP is generated as code** | Declarative spec → TMDL matching Power BI's own output (tabs, CRLF, `///` descriptions, `UnderlyingDateTimeDataType`). Power BI-authored scaffold (database, culture, report.json, theme) copied once. Lineage tags are uuid5 of the object path, so a re-run is byte-identical. Project 1 needed a manual "create project" step; this one needs none. |
| **D15** | **Refresh triggered through the engine** (TMSL over ADOMD) | Removes the "open Power BI and click Refresh" step. Windows authentication to the local SQL instance needed no credential prompt. |
| **D16** | **One marketing dimension:** channel and region folded into `DimCampaign` | Channel is functionally dependent on campaign (SQL: 0 mismatches), so a separate channel dimension would add an ambiguous second filter path. Gives a Channel Group → Channel → Campaign hierarchy and slicers that cross-filter. |
| **D17** | **`FactLeadFunnel` accumulating snapshot** | One row per lead with its opportunity and revenue milestones. Lead → opportunity → revenue is 1:1:1 (enforced by unique keys), so the join cannot fan out, and the model needs no fact-to-fact relationship. |
| **D18** | **Attribution selector disconnected; never sums across models** | One model selected (or on an axis) → that model; none or several → the default, Position-Based. Five models describe the same revenue, so adding them would count it five times. |
| **D19** | **Two lenses: lead source vs attributed; CPA vs CAC** | CPL and CAC use the lead's own campaign; attributed revenue, ROAS and CPA use touched campaigns. CPA (attributed) equals CAC (blended) at the grand total by construction — each customer's credit sums to 1 — and diverges by channel. |
| **D20** | **RLS on `DimCampaign[Region]` via `USERPRINCIPALNAME()`** | Filter reaches every fact through the campaign relationships. Unmapped users see nothing; users see only their own mapping row. |
| **D21** | **Power Query: two-step imports, one deliberate exception** | All shaping lives in SQL. `CampaignAliasResolution` applies rules R1–R4. R4 (`AU-NZ` = `ANZ`) was found by measurement: R1–R3 resolved 839 and left exactly the 61 AU-NZ aliases. |
| **D22** | **Money columns imported as `double`** | As in project 1 (D18): exact values stay in SQL `decimal`; every money measure reconciles to the cent. |
| **D23** | **Generator output matches Power BI's own save format byte for byte** | Power BI's first save changed no column, type, measure, relationship, query or role filter — only formatting (TMDL ends with a blank line; JSON has no final newline) and a role `PBI_Id`. The generator now writes exactly that, with a stable `PBI_Id`. **Verified:** open → refresh → save, then a trusted `diff -r` against a fresh generation shows 0 differences. A Power BI save of an unchanged model is a no-op in Git, so any future diff is a real change. |
| **D24** | **Constant-currency reporting at planning rates** (resolves open issue 1) | Standard finance practice for performance reporting: one rate per currency keeps period comparisons free of exchange-rate noise. With no rate data in the source it is also the only honest option. Rates stay labelled as planning assumptions and the dated table accepts a real feed unchanged. |
| **D25** | **Scale mismatch diagnosed, never rescaled** (resolves open issue 2) | Measured: 254,585,358 clicks against 50,000 leads — 0.0196% click-to-lead against the 2–5% typical of B2B landing pages — while CTR (4.2%), CPC ($4.28) and CPM ($181) are internally plausible. The CRM extract is a small fraction of the traffic the spend bought, which is why spend is ~34× revenue. Media efficiency and funnel conversion are reported as measured; commercial return leads with the scale-free Revenue-to-Spend Index; absolute ROAS/CAC appear only under a data note; `Click-to-Lead %` makes the gap visible. |
| **D26** | **The attribution story is told at campaign level** (resolves open issue 4) | Measured: every channel sits ~24% first / 48% middle / 24% last in journeys, so channel-level models converge (≤ 1.3 points). At campaign level — where budgets are actually set — the spread across models averages 37% and 161 of 300 campaigns move > 25% between First and Last Touch (up to $139,648). `Attribution Sensitivity %` ranks them; a 100% position chart explains the channel-level convergence instead of hiding it. |
| **D27** | **`PositionBand` is a persisted computed column in `dbo`** | First / Middle / Last / Only touch is exactly what separates the models; one rule in one place, exposed through the view. |
| **D28** | **`DimFunnelStage` is a disconnected funnel axis** | Each stage counts leads that reached AT LEAST it, so the bars nest by construction. `Funnel Stage Leads` is blank at a total on purpose — a funnel total has no meaning. |
| **D29** | **Prior-year measures are blank after the as-of date** | Found in the visual lab: the KPI visual showed "(Blank)" against a goal, because PY kept returning values for future months. With the guard it shows $1,259,634 vs $827,363 (+52.25%) for Aug 2026. |
| **D30** | **Visual types are chosen from the question — and maps are deliberately omitted** | 19 types, each answering a specific question (see `Documentation/visual_catalogue.md`). A map adds nothing for five countries, and Desktop's map visuals need an opt-in and an online tile service; a bar or donut reads five values more precisely. |
| **D31** | **Visual evidence = rendered capture + query check; a save-diff proves only format** | A canary visual with a fake role survived Power BI's save untouched, so a save-diff cannot validate roles. Each visual is proven by `PrintWindow` capture of the rendered page and by executing its query. Power BI's save normalisations are mirrored in the generator; a genuine save (cache rewritten) left 0 files changed. |
| **D32** | **Tables carry no `active` projection flags** | Found only by the rendered capture: the campaign scorecard drew a title and nothing else, although its query returned 50 rows. A controlled experiment on one page — the same table three ways — isolated the cause: with `active` flags it is blank; without them it renders in its sorted order (the gradient column lies past the lab visual's width, so the colour scale itself is not yet seen). The generator now strips them from every `tableEx`. |
| **D33** | **One as-of date for every figure — the funnel included** | The source records outcomes seven weeks past the as-of date (244 opportunities, 209 bookings). Revenue measures already excluded them but the funnel counted them, so "Customers 6,559" sat beside revenue that left out 209 of those customers' bookings and the implied deal size did not reconcile. Now an opportunity counts once opened and a customer once revenue is booked, by the as-of date: 10,908 opportunities, 6,350 customers, $30,867,505.68 — each measured independently by pandas and checked in SQL. A deal won after the as-of date was still Open on it. **One assumption:** the source has no loss date, so a lost deal opened by the as-of date is taken as lost by then. Post-period records appear only on the Data & Method page. |
| **D34** | **Attributed revenue is dated by booking date** | By touch date, credit landed in Nov–Dec 2023 — before any spend — and both ends of the timeline were truncated. By booking date, any model's attributed revenue in any month equals the revenue booked that month: the live check ties all 5 models × 32 months to finance (165 checks). Attributed Leads alone keeps the touch date, where its conversion event lives. Re-measured on this basis, campaign sensitivity still averages 37% and 161 of 300 campaigns still move > 25% between First and Last Touch (largest move now $141,715; D26's $139,648 was on the all-revenue basis). |
| **D35** | **Trends keep to complete periods and mature cohorts** | 2026 Q3 holds two of its three months, so a quarterly count would read as a collapse: `DimDate[IsQuarterComplete]` filters quarterly charts. Lead to revenue takes up to 58 days and the August 2026 cohort shows 2.1% conversion by the as-of date against 13.5% eventually: `Lead to Customer % (Mature Cohorts)` blanks cohorts younger than that window, which is computed from the data. The headline comparison is like-for-like year to date (+8.48%), not one month (Aug 2026's +52% is deal-timing noise; monthly revenue swings $0.77M–$1.26M after the January 2024 ramp-up month). |
| **D36** | **Media rates are shown for paid media in total and never ranked by channel** | CTR is 4.21–4.25% on all seven channels — Display included, where 0.1–0.5% is typical — and CPC and CPM are equally flat; owned, organic and referral channels record impressions and clicks as if bought. There is no signal to rank, so ranking it would present generator noise as insight. Refines D25: the ad side is internally consistent, not realistic channel by channel. |
| **D37** | **Differences are called out only when larger than chance** | Segments, channel groups and most campaigns differ by less than sampling noise. The heatmap colours a binomial z against the portfolio rate (no cell reaches \|z\| = 2). The campaign scorecard tests each campaign's attributed revenue against what its cost share would earn, with the variance taken under that fair-share hypothesis — compound Poisson with the portfolio's deal-size dispersion, because deals are skewed (standard deviation 1.26× the mean). A plug-in variance flagged 27 campaigns below and none above, an artefact of skew; the fair-share test finds 2 clearly and 14 possibly above, and 3 possibly below — against about 14 expected beyond \|z\| = 2 by chance among 300. No channel differs significantly (LinkedIn Ads z = −1.8). |
| **D38** | **Every figure in page text is re-measured before it ships** | Page notes and chart descriptions quote numbers, so each was re-measured on the final basis. One earlier claim — the ribbon's "Meta Ads leads every quarter, Display 2nd–7th" — was wrong on booking-date quarters and was corrected: Meta Ads leads 9 of 10 complete quarters, Display ranges 1st–6th. |

| **D39** | **Dark neon theme from the client's reference design, applied as a registered custom theme plus generator colours** | The client supplied a reference ("command centre": near-black canvas, dark panels outlined in green, lime-neon accents) and asked for its colour scheme on every page, with visuals and content unchanged. `OmnichannelNeon.json` is registered in `report.json` on top of the base theme, so every visual inherits the canvas, panel, text, axis, gridline, table and slicer colours; the generator's explicit colours were changed to match, because a visual's own formatting overrides the theme. Series use greens of clearly different lightness plus a teal- and a yellow-green, so seven channels stay distinguishable. Headline numbers use Consolas like the reference; titles and notes stay Segoe UI so nothing overflows. Signal shading keeps its dead zone: within noise = the panel colour, green above, red below. |

## Open issues

| # | Issue | Status |
|---|---|---|
| 1 | FX planning rates are assumptions | **Resolved (D24)** — constant-currency reporting; rates stay labelled as planning assumptions and a real feed can replace them |
| 2 | Spend ~34× revenue: ROAS 0.029, CPL $21,782, CAC $166,047 | **Resolved (D25)** — diagnosed as an ad-vs-CRM scale mismatch; reported as measured, never rescaled; the report leads with the Revenue-to-Spend Index and shows `Click-to-Lead %` |
| 3 | Organic, Email and Referral carry 435M of local "ad spend" | **Accepted** — labelled "channel cost", ROAS caveated |
| 4 | Attribution models move channel credit by ≤ 1.3 points on this data | **Resolved (D26)** — explained by journey position (~24/48/24 in every channel) and told at campaign level, where 161 of 300 campaigns move > 25% |
| 5 | Card visual values truncate ("$3…") at lab size; 4th card needs a scroll | **Resolved (Phase 4)** — one classic card per KPI with explicit units: money to two decimals of its unit ($1.09bn), counts in full (10,908); seen in every page capture |

## Honesty register

| Item | Status | Evidence |
|---|---|---|
| Raw file format (CRLF, no quotes, rectangular) | **Verified** | Byte-level inspection before writing `03` |
| Data-quality findings | **Verified** | `Python/01_data_audit.py` from raw CSVs |
| SQL build and 82 validation checks | **Verified** | Clean end-to-end `run_all.ps1`, 82 of 82 (`09` throws on any failure); the 12 as-of literals are measured independently by the pandas audit |
| Attribution weights | **Verified** | 874,690 rows match independent pandas, max diff 6.7 × 10⁻¹⁶ |
| Model files vs SQL views (names, types) | **Verified** | `verify_semantic_model.py`, 379 of 379, run against the live views |
| Imported row counts | **Verified** | `open_powerbi.ps1` prints every table's count after each engine refresh: all 12 equal SQL (874,690 credit rows, 174,938 touches, 80,000 spend lines, 50,000 leads, 2,007 dates, …) |
| Every measure and every report figure vs independent SQL | **Verified** | `reconcile_measures.ps1`, 2,552 of 2,552, on the finished report |
| Visual lab: 20 visuals, 19 types render | **Verified** | 20 of 20 reconstructed queries return data; every visual inspected in a `PrintWindow` capture |
| Ribbon rank story | **Verified (re-measured)** | On the report's basis — booking-date, complete quarters: Meta Ads 1st in 9 of 10, Display 1st–6th. The Phase 3 wording (touch-date, 12 quarters) was superseded (D38) |
| Scorecard colour scale on the index column | **Verified** | Phase 4 capture: the index is shaded by its signal (two "Clearly above" strong, "Possibly above" muted, noise unshaded); the colour of all 300 campaigns reconciles to SQL |
| Every figure quoted in page text | **Verified** | Each number in a note or chart description was re-measured on the final basis (D38): 5,092 clicks per lead, 35.3× cost to revenue, CTR 4.21–4.25%, 58-day window, +8.48% YTD |
| Genuine Power BI save of the Phase 4 report | **Not verified** | Every session closed without saving. The generator mirrors Power BI's save format (D23, D31), but no save round trip was run on these pages — nor after the table fix (D32) |
| Report interactions (slicer clicks, model selector, cross-filter, drill) | **Not verified by interaction** | Captures show each page's default state only. The selector's no-filter interaction is written to `page.json` and schema-valid; the measures behind every model are reconciled for all five models |
| A `pages.json` change seen during one Lab C session | **Superseded** | Never inspected; the lab pages were replaced by the Phase 4 report |
| RLS secure default, engine-enforced | **Verified** | Connected as the role with an unmapped identity: 0 campaigns, 0 spend |
| RLS for a mapped user, engine-enforced | **Not verified** | The predicate is checked for all 7 users, but impersonating a mapped user (e.g. *View as* in the Service) has not been run |
| Query folding of the two-step imports | **Not verified** | Needs *View Native Query* in Power BI Desktop |
| Model as seen in the Power BI UI (field list, hierarchies) | **Partly** | The table list shows in every page capture; hierarchies and folders were not inspected |
| FX rates are real market rates | **No — by design** | Planning assumptions, labelled as such |
| Final report pages render correctly | **Verified** | All 7 pages captured and inspected in the client's theme after the last change to each (`Validation/evidence/phase4/page*.png`) |
