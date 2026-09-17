# Semantic Model — Omnichannel Marketing Attribution

The Power BI model, generated as code by `Python/02_generate_semantic_model.py` and
verified statically (`Validation/verify_semantic_model.py`) and live
(`Validation/reconcile_measures.ps1`). The data is synthetic.

## Shape

```
                         DimDate (marked date table)
        ┌────────────┬──────────┼────────────┬──────────────┐
        │            │          │ (+2 inactive)│ (+1 inactive)│
  FactAdSpend  FactLeadFunnel  FactTouchpoint  FactAttributionCredit
        │            │          │              │
        └────────────┴──── DimCampaign ────────┴── CampaignAliasResolution
                          (campaign + channel + region; RLS here)

  Disconnected: DimAttributionModel (selector) · DimFunnelStage (funnel axis) · ModelConfig · FxRate · SecurityUserAccess · _Measures
```

**13 tables, 123 columns, 12 relationships (9 active, 3 inactive), 1 role, 83 measures.**
Every relationship is one-to-many and single-direction. There are no bidirectional
filters, no fact-to-fact relationships and no snowflakes.

## Tables and grain

| Table | Grain | Rows | Why it has this shape |
|---|---|---|---|
| `DimDate` | day, 2022-01-01 → 2027-06-30 | 2,007 | Regenerated in SQL: the supplied calendar ended before the last revenue date |
| `DimCampaign` | campaign | 300 | **One marketing dimension.** Channel is a level of it, because every fact row's channel equals its campaign's channel (SQL check: 0 mismatches) |
| `FactAdSpend` | billing line | 80,000 | Spend in local currency and in USD at constant planning rates |
| `FactLeadFunnel` | lead | 50,000 | **Accumulating snapshot**: the lead with its opportunity and revenue milestones, so the funnel needs no fact-to-fact join |
| `FactTouchpoint` | touch | 174,938 | Journey analysis; `JourneyPosition` ordered by date; `PositionBand` First / Middle / Last / Only touch |
| `FactAttributionCredit` | touch × model | 874,690 | Precomputed credit weights for five models |
| `CampaignAliasResolution` | alias | 900 | The Power Query cleansing showcase (below) |
| `DimFunnelStage` | stage | 5 | Funnel axis; each stage counts leads that reached AT LEAST it |

## Role-playing dates

`FactLeadFunnel` carries three dates. `CreatedDate` is active; `OpportunityCreatedDate`
and `RevenueDate` are inactive and are switched on with `USERELATIONSHIP`. Count
measures on an inactive date also require `NOT ISBLANK` on that date, otherwise with
no date filter they would count every lead (project 1, decision D25).
`FactAttributionCredit` works the same way: `TouchDate` active, `RevenueDate` inactive.
**Attributed revenue is dated by booking date** (D34): its measures activate
`RevenueDate`, so any period's attributed revenue — under any model — equals the revenue
booked in it, and ties to finance. Credit rows of leads that never converted carry no
booking date and are excluded explicitly; otherwise they would draw a "(Blank)" category
with value 0 on every date axis. Prior-year measures return blank for periods after the
as-of date, so a KPI or trend ends at the last real month (decision D29).

## One as-of date

Every figure counts only what happened on or before the as-of date, 31 Aug 2026 (D33).
The source records outcomes seven weeks later; they are excluded everywhere except the
explicitly named `Post-Period …` measures on the Data & Method page.

| Column (`FactLeadFunnel`) | Meaning on the as-of date |
|---|---|
| `IsOpportunityByAsOf` | the opportunity had been opened |
| `IsWonByAsOf` | revenue had been booked |
| `OpportunityStatusAsOf` | Closed Won if booked; Open if won later or still open; Closed Lost (no loss date exists, so a lost deal opened by then is taken as lost by then) |
| `StageRankAsOf` | furthest stage: 5 won, 4 opportunity, else the CRM stage capped at SQL |

`OpportunityStatus` (extract-time) is hidden. `DimDate[IsAfterAsOf]` and
`DimDate[IsQuarterComplete]` keep charts to complete periods (D35).

## Statistical signal

Two measures stop the report presenting noise as insight (D37):

- `Lead to Customer z vs Portfolio` — binomial z of a cell's conversion against the rate
  of everything selected; it colours the funnel heatmap.
- `Campaign Index z` / `Campaign Index Signal` — a campaign's attributed revenue against
  what its cost share would earn, in standard errors, with the variance taken under that
  fair-share hypothesis: expected revenue × the model's campaign dispersion
  (`DimAttributionModel[CampaignDispersionUSD]`, Σv²/Σv of per-lead credited revenue,
  computed in SQL 07). |z| ≥ 3 is a clear signal, 2–3 possible.

## Two lenses, kept apart

| Lens | Path | Used for |
|---|---|---|
| **Lead source** | `DimCampaign → FactLeadFunnel` through the lead's own campaign | Funnel, CPL, cost per MQL/SQL/opportunity, CAC |
| **Attributed** | `DimCampaign → FactAttributionCredit` through the touched campaigns | Attributed revenue, ROAS, CPA, credit shift, attribution sensitivity |

A lead's own campaign matches its first or last touch only 0.3% of the time, so the
two lenses genuinely differ. Measure names say which lens they use.

## Attribution model selector

`DimAttributionModel` is **deliberately disconnected**. Attributed measures read the
model in use and filter `FactAttributionCredit[ModelKey]` to it:

- one model selected, or one model on a visual's axis → that model
- nothing selected, or several → the configured default (**Position-Based**)

Measures never add credit across models. Five models describe the same revenue five
ways, so summing them would count it five times. Verified live: with the model on an
axis, every model re-divides exactly the same total.

**Where the model choice matters.** Every channel sits about 24% first / 48% middle /
24% last in journeys, so at channel level the models agree within 1.3 points. At
campaign level the spread across models averages 37% of a campaign's credit and 161 of
300 campaigns move more than 25% between First and Last Touch. `Attribution
Sensitivity %` measures that spread per campaign (zero at the grand total, since
every model conserves revenue).

## Row-level security

Role **Regional Marketing** filters `DimCampaign` to the regions mapped to
`USERPRINCIPALNAME()` in `SecurityUserAccess` (`ALL` sees everything). The filter
reaches every fact through the campaign relationships. A user may also see only their
own row of the mapping table. **Secure default:** an unmapped user sees nothing —
verified live by connecting as the role (0 campaigns, 0 spend) — and the predicate is
checked against SQL for all 7 mapped users.

## Power Query

- **Parameters** `SqlServer` and `SqlDatabase` are the only place the source is named.
- Every table except one is a **two-step import** (Source → view). All shaping lives in
  SQL, so the queries stay fully foldable.
- **`CampaignAliasResolution`** is the one intentional exception. It resolves 900 messy
  aliases to canonical campaigns with four documented rules:

  | Rule | Does |
  |---|---|
  | R1 | ignore case |
  | R2 | treat space, hyphen and underscore as one separator |
  | R3 | collapse runs of separators and trim |
  | R4 | region synonym: `AU-NZ` = `ANZ` (61 aliases spell it that way) |

  Each alias is checked against the supplied mapping: **900 resolved, 0 unresolved,
  0 mismatched**. Rule R4 was found by measurement — the first three rules alone
  resolved 839 and left exactly the 61 AU-NZ aliases.
- Auto date/time is disabled (`__PBI_TimeIntelligenceEnabled = 0`); `DimDate` is the only calendar.

## Measures

83 measures in 8 folders, all in `_Measures` — see `dax_measure_dictionary.md`.
Definitions that are easy to confuse:

| Measure | Definition |
|---|---|
| CPL | spend ÷ leads created (lead-source lens) |
| CPA | spend ÷ **attributed** customers — changes with the attribution model |
| CAC | spend ÷ customers won — blended, independent of attribution; equals CPA at the grand total by construction |
| ROAS | attributed revenue ÷ spend — shown under a data note (decision D25) |
| Revenue-to-Spend Index | attributed revenue share ÷ spend share — above 1 earns more than its share of budget; independent of scale |
| Click-to-Lead % | leads ÷ clicks — 0.02% here, the visible evidence that ad data and CRM are on different scales |
| Win Rate % | won ÷ **closed** opportunities; open ones are not counted as lost |

## Validation

| Stage | Script | Checks |
|---|---|---|
| Static, before Power BI opens | `verify_semantic_model.py` | Every column against its live SQL view; references; relationships; measure refs; reserved-word variable names — 379 checks |
| Load | `open_powerbi.ps1` row counts after the engine refresh | All 12 data tables equal their SQL counts, table by table |
| Live | `reconcile_measures.ps1` | Every measure evaluated alone, then compared with an independent SQL query; every report visual's figures at the visual's own grain; the booking-month tie-out for all 5 models; the signal tests and colours recomputed from the credit rows; security — 2,552 checks |
| Round trip | open → refresh → save, then `diff -r` against a fresh generation | Power BI's save changes nothing the generator writes |
