# Visual Catalogue — Enterprise FP&A Finance

Every page and visual in the report, the question each answers, why that visual type
fits the question, and the figure it shows — each figure reconciled to SQL. Generated
by `Python/04_generate_report.py`. The data is synthetic.

**8 pages · 193 visuals · 22 visual types.**

## How a visual counts as proven

A visual passes only when all three hold:

1. **Its query returns data.** `Validation/validate_visuals.ps1` rebuilds each visual's
   DAX query from its PBIR definition — including the page and visual filters — and runs
   it against the live model: **193 of 193**.
2. **Its figures are right.** `Validation/reconcile_measures.ps1` compares what each
   visual shows, at the grain it shows it (year × version, department × month, ageing
   bucket, scenario…), with an independent SQL query: **868 of 868**.
3. **It renders.** Each page was written alone, opened, captured with `PrintWindow` and
   inspected (`Validation/evidence/phase4/`). Query checks are not enough: the renders
   found defects every query check had passed — including five in the model itself.

## Pages

### 1 · Executive Summary — where did the year land, and what is the outlook?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Six KPIs | `card` | One number each, and each names its own window | Revenue 12 months $17.40M · Operating profit 12 months −$14.53M · Revenue FY27 to date $2.65M · Cash $25.49M · Receivables $40.20M · FY27 outlook −$14.71M |
| How FY26 revenue became a loss | `waterfallChart` | Signed contributions that net to the total | Revenue +$17.32M, COGS −$9.85M, opex −$22.40M, other −$2.09M, tax −$1.83M → −$18.84M |
| Revenue by month against budget | `lineChart` | Two series over time, zero-based | The gap never closes: actual tracks ~70% of plan from 2022 to 2026 |
| Operating profit against budget by year | `clusteredColumnChart` | Two versions side by side per year | A loss in the plan as well as the ledger, every year |
| Gross margin by entity | `clusteredColumnChart` | Currency-neutral comparison; columns fit six entities | Holdings 52.5% down to SG 32.2% |
| Revenue by stream | `columnChart` (stacked) | Composition over time | Product, Services and Subscription hold the same shares every year |

### 2 · Income Statement — the statement itself, line by line

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Four KPIs | `card` | The four subtotals | Revenue $17.32M · Gross profit $7.48M · Operating profit −$14.92M · Net profit −$18.84M |
| The statement | `pivotTable` × `Plan Version` | One measure under four calculation items | Revenue −30.0% vs budget; operating expense +32.1% favourable; operating profit +$1.60M; margins in percentage points; no variance below operating profit |
| Account detail | `pivotTable` | Every account against its plan, in natural signs | 21 accounts; COGS over plan, every opex account under |
| By month, July to June | `lineClusteredColumnComboChart` | Two money series and a rate on a second axis | Financial-year order, gross margin on the right |
| Cost mix by entity | `hundredPercentStackedColumnChart` | Composition, scale-free | Cost only — revenue excluded, or the mix would be meaningless |
| The margins | `multiRowCard` | Three ratios in one panel | Gross 43.2% · Operating −86.1% · Net −108.8% |

### 3 · Budget Variance — where plan and ledger differ, and what is unusual

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Five KPIs | `card` | Favourable-positive throughout | Revenue −$7.44M · Underspend +$10.60M · Operating profit +$1.60M · Revenue 70.0% of budget · Underspend 32.1% |
| Underspend by department | `clusteredBarChart` | Ranked comparison with long names | 25.3% (Legal) to 37.5% (Operations) — the same gap everywhere |
| Unusual months (z) | `pivotTable` + colour measure | Two-way, with a dead zone | 11 of 120 department-months reach \|z\| ≥ 2, against about 6 expected by chance |
| Which cost centres are under budget | `waterfallChart` | Contributions to one total | Every department adds to the underspend; none offsets it |
| Budget against actual | `scatterChart` | Two measures plus volume | Every department below the line: a plan-wide gap |
| Revenue against budget | `gauge` | A rate against a real target | 70.0% of plan |

### 4 · Cost Centres — what the departments spend, and with whom

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Five KPIs | `card` | — | Operating expense $22.40M · 129.3% of revenue · COGS 56.8% of revenue · 24.9% of lines accrued · 500 vendors |
| Operating expense by cost centre and account | `treemap` | Hierarchical part-to-whole | 10 departments × 11 accounts |
| Where the operating expense sits | `decompositionTreeVisual` | A drill path the reader chooses | Entity, department, account or vendor category, in any order |
| Cost-centre scorecard | `tableEx` | The numbers, with the plan beside them | 10 departments: actual, budget, underspend, % of revenue |

### 5 · Scenario & Full-Year Outlook — what the rest of the year looks like

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Scenario selector | `advancedSlicerVisual` | A discoverable three-way choice | Downside · Base · Upside |
| Six KPIs | `card` | — | Outlook revenue $17.15M · opex $22.23M · operating profit −$14.71M · +$214K against FY26 · run-rate $1.45M a month · 10 months projected |
| Outlook against FY26 | `clusteredBarChart` | The difference is the story, and each bar takes its colour from its own sign (`[Outlook Variance Colour]`) | Downside −$0.41M in red · Base +$0.21M · Upside +$0.36M in green |
| Profit sensitivity to revenue | `lineChart` | One driver swept across a range | −20% to +20% moves operating profit from −$16.0M to −$13.4M |
| The assumptions, stated | `tableEx` | Drivers are data, not hidden arithmetic | Revenue, opex and AUD drivers per scenario |
| The run rate the outlook is built on | `lineChart` | The basis, in full | Monthly actual revenue, 2022 to 2026 |
| Outlook by entity | `clusteredColumnChart` | Where the currency driver bites | The five non-AUD entities only |

### 6 · Working Capital — what is owed, how old, how fast

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Six KPIs | `card` | — | Receivables $40.20M · DSO 314 days · days to collect 73.8 · over a year $23.00M · payables $10.49M · DPO 204 days |
| Receivables by age / Payables by age | `columnChart` | Ordered buckets, aged as of the balance date | Over-365 dominates both |
| Balances at each month end | `lineChart` | A balance stated on every month end | The uncollected stock only grows |
| Largest outstanding customer balances | `tableEx` + Top N | Who the receivable sits with | Ten customers, with the over-a-year share |
| Collection and payment days by entity | `clusteredColumnChart` | Two measures across six entities | The funding gap, entity by entity |
| Receivables by entity | `donutChart` | Part-to-whole, six parts | Legend below, or six entity names truncate |

### 7 · Cash & Currency — what the group holds, and what the rate did

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Five KPIs | `card` | — | Cash $25.49M · lowest daily balance $14.62M · 87.1% of revenue outside AUD · rates move 1.41% a day · spot vs average $4,354 |
| Group closing cash | `areaChart` | A stock over time, zero-based | Month-end balances, never summed |
| Cash by entity | `lineChart` small multiples | Six entities without six overlapping lines | One panel each, titles kept |
| Monthly average rates | `lineChart` | The rates the ledger was translated at | Flat lines: noise around a constant mean |
| Revenue growth, reported and constant currency | `clusteredColumnChart` | Two bars that should differ — and do not | FY24 −1.0% · FY25 +3.4% · FY26 −1.4%; FX under 0.05 pp |
| Revenue by currency | `pieChart` | The model's only genuine two-part split | 87.1% foreign, 12.9% reporting currency |

### 8 · Data & Method — what was assumed, fixed and flagged

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Five KPIs | `card` | The exceptions, counted | 19,468 budget lines with no posting · 769 receipts and 395 payments after the as-of date · 33 days at the cash floor · 80,000 ledger lines |
| Data quality, computed live in SQL | `pivotTable` | Row headers that render (a table left the text column blank) | Fifteen properties measured from `dbo` on every refresh |
| Rules, limits, scenarios and security | `textbox` | Prose is the right control for prose | The as-of rule, translation, plan scope, what the data will not support |

**Theme.** The reference design's canvas is charcoal, but its colour does not stand
still, and neither does this one. Three rules carry it:

| Rule | Where it shows |
|---|---|
| **A card wears its own hue.** The figure is written in it and the panel is tinted 13% toward it, with the outline at 50%. | Every `card`: no two in a row are the same colour |
| **A page opens on its own hue**, and its cards walk forward around an eight-hue wheel from there. The selected rail button and the rail's brand line wear it too. | Executive amber → Income Statement indigo → Variance lime → Cost Centres violet → Scenario cyan → Working Capital pink → Cash & FX blue → Data & Method green. The rail changes colour as the reader moves |
| **A chart takes its subject's hue, and the plan is always indigo.** | Revenue amber, profit teal, margin green, operating expense lime, cash blue, receivables pink, payables cyan, the outlook cyan and violet — against an indigo budget on every page |

Consecutive hues sit far apart on the wheel (`SPECTRUM` in the generator), so neither a
row of cards nor two adjacent pages read as the same colour. Tables and matrices stay
deliberately quiet — cool grey headers, white totals — because the colour belongs to the
figures and the charts, not to eight headers repeating an accent. Categorical visuals
(treemap, stacked columns, donut, pie, the currency lines) draw from the theme's ten-hue
`dataColors`, ordered for the same adjacent contrast.

It is applied twice: a registered custom theme
(`StaticResources/RegisteredResources/NorthstarSpectrum.json`) sets what every visual
inherits, and explicit colours in the generator win where a visual carries its own
formatting. `Validation/validate_report_layout.py` checks the rotation on every page —
that each rail button carries its page's hue, that no two cards share one, and that no
card sits on an untinted panel — so a later edit cannot quietly collapse it back to one
accent.

Every page also carries the navigation rail (8 `actionButton`s), a title, the context
line ("As of 31 Aug 2026 | FY26 | AUD at monthly average rates | Synthetic data"),
dropdown `slicer`s where filtering makes sense, and a note on how to read the page.

## Review: what the renders and the domain review found

| # | Found | Fix |
|---|---|---|
| 1 | *Model:* a balance repeated the as-of figure for every future month, so cash and receivables ran flat into 2027 | `[Balance Date]` is blank when the period starts after the as-of date |
| 2 | *Model:* "budget lines with no posting" read 60,480 — every plan row has a blank posting count | The measure compares plan KEYS against posted keys: 19,468 |
| 3 | *Model:* days-to-collect read 59.7 against 73.8 — a BLANK date passes a `<= as-of` filter, so unpaid invoices counted as collected | `NOT ISBLANK` on every paid-date filter; checked at the unfiltered grain, the only grain that exposes it |
| 4 | *Model:* constant-currency growth for FY23 was arithmetic on half a year of rates | Blank unless every row in the period has a prior-year rate |
| 5 | *Model:* FY23 showed +101% growth because FY22 holds six months of ledger | A prior-year comparison is blank where the ledger does not cover the earlier window |
| 6 | The decomposition tree drew almost nothing in a 196 px band | Moved to the 244 px row; the scorecard took the full-width row |
| 7 | Six entities did not fit a 196 px bar chart (three pages) | Columns instead of bars |
| 8 | Ten department bars and twelve month columns overflowed their panels | Bars moved to the taller row; the heatmap uses short month names, unique inside a filtered year |
| 9 | The multi-row card and gauge were clipped in a 74 px band | Moved to rows that give them 110 px and 196 px |
| 10 | The KPI's trend area filled its panel with alarm red | Trend muted to 75% transparency |
| 11 | Entity names truncated in the donut's and pie's side legends | Legend moved below |
| 12 | The data-quality table rendered its text column blank | A matrix, whose row headers render |
| 13 | Ten department bars did not fit even the 244 px row, though a matrix of ten rows does | Columns instead of bars |
| 14 | The data-quality matrix nested the unit as a second row level, costing a row per metric | The unit became a text measure, so each metric is one row |
| 15 | Entity names truncated to "Northstar..." on every axis | A short entity name (`EntityShort`) in the view, used on axes; slicers and tables keep the full name |
| 16 | The `kpi` visual painted its whole panel in the goal-distance colour, burying its own number; muting the theme's "bad" colour fixed the panel but dulled the waterfall, which shares it | The KPI was replaced by a stacked column of revenue by stream, and the signal red kept for the waterfall |
| 17 | *Validation:* the query check called the variance heatmap blank | The reconstruction now includes page and visual filters — and re-quotes PBIR's single-quoted literals, which DAX reads as table names |
| 18 | **Seven charts drew in amber that were never meant to be amber** — receivables, payables, gross margin, the underspend columns, the outlook and the scatter. A chart with ONE measure and a category axis colours by category, so a colour keyed to the measure (`selector.metadata`) never reaches it and it falls back to `dataColors[0]`. Lines, areas and small multiples honour the same key, which is why the defect hid: half the report obeyed. | `one_colour()` writes `dataPoint.defaultColor` as well as the keyed fill. Found only by rendering — the JSON was correct on every one of them |
| 19 | The multi-row card ignored a `dataLabels` colour and drew its margins in the fallback text colour | Colour reaches it through the panel instead: the container is tinted toward the page's hue, like a card. A property Power BI does not read is not an error it reports |
| 20 | **Power BI silently deletes properties a visual does not have** — and a save is what reveals it. `header.fontSize` on a slicer, `dataPoint.fillColor`/`targetColor` on a gauge and `total.show` on a table were all stripped out the first time Desktop re-serialised the project, which means none of them had ever applied | All three removed from the generator. They are also why the multi-row card ignored its colour (19): the same silence, with no error to notice |

## Deliberately not used

- **Maps.** Six entities in four regions: a bar reads them more precisely, and Desktop's
  map visuals need an opt-in and an online tile service.
- **Ribbon chart.** Tried in the lab: ten departments whose ranks barely move is
  spaghetti, and the reader learns nothing from it.
- **The KPI visual.** Tried on the executive page and rejected on the rendered
  evidence: below goal it fills the entire panel with the goal-distance colour, which
  on a dark canvas leaves the number unreadable. The theme's "bad" colour could be
  muted, but the waterfall's decrease bars share it and went muddy.
- **AI visuals** (Q&A, smart narrative, key influencers). Their output cannot be
  reproduced or tested from the files.
- **A cash-flow bridge.** Daily cash never ties to the ledger, receipts or payments in
  this source, so no bridge is drawn.
- **Days inventory outstanding.** The chart of accounts has an inventory account with no
  postings at all.

The Phase 3 visual lab that first proved each visual type is in git history, with its
captures in `Validation/evidence/phase3/`.
