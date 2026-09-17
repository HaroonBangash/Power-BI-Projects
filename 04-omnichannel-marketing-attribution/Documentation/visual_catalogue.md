# Visual Catalogue — Omnichannel Marketing Attribution

Every page and visual in the report, the question each answers, why that visual type
fits the question, and the figure it shows — each figure reconciled to SQL. Generated
by `Python/04_generate_report.py`. The data is synthetic.

**7 pages · 154 visuals · 23 visual types.** Project 1 used four chart types.

## How a visual counts as proven

A visual passes only when all three hold:

1. **Its query returns data.** `Validation/validate_visuals.ps1` rebuilds each visual's
   DAX query from its PBIR definition and runs it against the live model: **154 of 154**.
2. **Its figures are right.** `Validation/reconcile_measures.ps1` compares what each
   visual shows, at the grain it shows it (quarter × channel, segment × channel group,
   campaign…), with an independent SQL query — including the colour every cell and
   campaign receives.
3. **It renders.** Each page was opened alone, captured with `PrintWindow`, and inspected
   (`Validation/evidence/phase4/`). Query checks alone are not enough: the renders found
   20 presentation defects that every query check had passed — 13 in the first design and
   7 after the client's theme was applied (see *Review*).

## Pages

### 1 · Executive Summary — is marketing producing revenue, and is the spend defensible?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Six KPIs | `card` | One number each, full precision | Channel cost $1.09bn · Revenue booked $30.87M · Leads 50,000 · Customers 6,350 · Lead to customer 12.7% · Revenue YTD vs last year +8.5% |
| Revenue YTD vs same days last year | `kpi` | Value, like-for-like goal and running trend together | $8,300,947 vs $7,651,834 (+8.48%) |
| Leads and mature-cohort conversion | `lineStackedColumnComboChart` | Volume and rate need two axes | ~1,560 leads a month; conversion line stops at June 2026, the last mature cohort |
| Channel cost by channel group | `donutChart` | Part-to-whole, six parts | Paid Social 31.9% |
| Revenue by month vs same month last year | `lineChart` | Two series over time | Shows how noisy single months are; January 2024 is the ramp-up month |

### 2 · Channels & Budget — where does the budget go, and does credit follow it?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Paid media KPIs | `card` | Rates reported in total only (D36) | $652.20M · CTR 4.23% · CPC $4.29 · CPM $181.43 · click to lead 0.020% |
| Share of cost vs share of attributed revenue | `clusteredColumnChart` | Two shares side by side; scale-free | LinkedIn Ads 12.3% of cost, 11.3% of revenue — the largest gap, still within chance (z = −1.8) |
| Cost per lead by month, per region | `lineChart` small multiples | Same trend, five regions, no overplotting | Five panels, whole period visible |
| Cost by region, then channel | `treemap` | Hierarchical part-to-whole | 5 regions × 7 channels |
| Channel rank, complete quarters | `ribbonChart` | Rank changes over time | Meta Ads 1st in 9 of 10 booking quarters; Display ranges 1st–6th |

### 3 · Funnel & Pipeline — how do leads become revenue, and how fast?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Pipeline KPIs | `card` | — | Opportunities 10,908 · Customers 6,350 · Win rate 73.8% · Open pipeline $11.05M · 20.3 days lead → opportunity · 9.9 days to close |
| Lead funnel | `funnel` | Nested stage attrition | 50,000 → 32,589 → 20,148 → 10,908 → 6,350 (12.7%) |
| Conversion from previous stage | `clusteredColumnChart` | Where the funnel leaks | 65.2% · 61.8% · 54.1% · 58.2% |
| Segment × channel group | `pivotTable` heatmap | Two-way comparison; colour = beyond chance (D37) | Every cell unshaded: the largest deviation is \|z\| = 1.54 |
| Conversion by cohort month | `lineChart` | Trend of mature cohorts only (D35) | January 2024 – June 2026 |
| Days opportunity → close | `clusteredColumnChart` histogram | Sales-cycle distribution | 1–19 days |

### 4 · Attribution Models — which model, and where does the choice matter?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Model selector | `advancedSlicerVisual` | Discoverable single choice | Drives every attributed figure in the report |
| Share by channel under each model | `clusteredColumnChart` | Five models side by side; ignores the selector | Channel shares move at most 1.26 points |
| $ by channel × model | `pivotTable` | Exact figures; ignores the selector | Total row $30,867,506 under every model (no across-model total: models are never summed) |
| Top 10 by model sensitivity | `clusteredBarChart` Top N | Ranking with long names | 115.2% at the top; 161 of 300 campaigns move > 25% |
| Credit shift vs Last Touch | `waterfallChart` | Signed moves that net to zero | Position-Based moves Display +$216K, Referral −$227K |
| Journey position by channel | `hundredPercentStackedBarChart` | Composition — why channel shares agree | ~24% first / 48% middle / 24% last in every channel |

### 5 · Customer Journeys — how do buyers reach us before they become leads?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Journey KPIs | `card` | — | 174,938 touches · 3.50 per journey · 80.3% multi-channel · 32.5 days first touch → lead |
| Journey length × channels | `columnChart` (stacked) | Two distributions in one view | 1–6 touches, evenly spread |
| Touches by days before lead | `areaChart` (zero-based) | Timing across the journey | About 3,900 touches on every day from 0 to 44 before the lead |
| Leads by channels in journey | `donutChart` | Part-to-whole | 19.7% single-channel |
| Conversion by journey length | `clusteredColumnChart` | The question behind multi-touch models | 12.2%–13.2%: longer journeys do not convert better here |

### 6 · Campaign Scorecard — which campaigns earn more than their share, beyond chance?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Cost vs attributed revenue | `scatterChart` (bubble) | Two metrics plus volume across 300 campaigns | Bubble = customers credited |
| Attributed revenue breakdown | `decompositionTreeVisual` | User-chosen drill path | Root $30,867,506 |
| Scorecard | `tableEx` | Detail with the signal beside the ranking | Index shaded only beyond chance: 2 clearly above, 14 possibly above, 3 possibly below, 281 within noise |

### 7 · Data & Method — what was fixed, assumed and flagged?

| Visual | Type | Why this type | Shows (reconciled) |
|---|---|---|---|
| Data-quality KPIs | `card` | — | 900 aliases resolved · 0 mismatches · 2,428 stale labels · 35,409 contradicting sequences · 33,739 spend lines before start · 209 bookings after as-of |
| Alias resolution | `gauge` | A rate against a genuine 100% target | 100.0% |
| Aliases by naming style | `clusteredColumnChart` | Every style handled by rules R1–R4 | 300 each |
| Planning FX rates | `tableEx` | The one currency assumption, in full | AUD 0.66 · EUR 1.08 · GBP 1.27 · USD 1.00 |
| Scale cards and method notes | `card`, `textbox` | The context every figure needs | 5,092 clicks per lead · 35.3 cost per $ revenue · $888.61K after as-of · 58-day window |

**Theme.** All pages use the client's reference colour scheme (D39): near-black canvas,
dark panels outlined in green with a faint neon glow, lime-neon accents, headline numbers
in a monospaced face. It is a registered custom theme
(`StaticResources/RegisteredResources/OmnichannelNeon.json`) plus matching explicit colours
in the generator.

Every page also carries the navigation rail (7 `actionButton`s), a title, the
context line ("Data as of 31 Aug 2026 | Attribution: … | USD at planning FX"),
dropdown `slicer`s where filtering makes sense, and a note on how to read the page.

## Review: defects the renders found, and the fixes

Captures of the first render are kept in `Validation/evidence/phase4/review_v1_*.png`.

| # | Found in the render | Fix |
|---|---|---|
| 1 | Model selector drew five **empty** buttons at 48 px | 72 px, as the Phase 3 lab had it |
| 2 | Heatmap and scorecard **gradients tinted differences chance explains** (\|z\| ≈ 1.5 half-coloured) | Colour measures with a dead zone: unshaded inside \|z\| < 2 |
| 3 | Area chart's axis started at 3,600, **dramatising ±4% noise** | Value axis pinned to zero |
| 4 | Scorecard columns cut off ("Clear…", "Possi…") | Region dropped (it is in the campaign name), short headers and labels |
| 5 | Dropdown slicers clipped at 44 px | 58 px |
| 6 | Cards rounded hard ($1bn, 11K) | Money to two decimals of its unit; counts in full |
| 7 | 32 text month labels truncated and scrolled | Date axis |
| 8 | Journey length 1–6 labelled only 2 / 4 / 6 | Categorical axis |
| 9 | Donut labels truncated ("$… (…)") | Percent of total |
| 10 | Small multiples lost their region titles; then each panel scrolled its quarters | 2 × 3 layout and a monthly date axis |
| 11 | Cost-vs-revenue bars scrolled Organic Search out of view | Column chart |
| 12 | Model matrix cut off Time-Decay, then showed a misleading "Total" across models | Wider, and the column subtotal switched off |
| 13 | Top 10 campaign names truncated | Wider category-axis labels |
| 14 | *Theme:* context line truncated — it picked up the monospaced number face | Context line kept in Segoe UI |
| 15 | *Theme:* pale conversion line lost over neon columns (the combo ignores a column colour override) | Near-white line |
| 16 | *Theme:* the panel outline clipped the slicer dropdowns | Slicers 62 px |
| 17 | *Theme:* white treemap labels on pale-lime tiles (about 1.2:1 contrast) | Dark tile labels |
| 18 | *Theme:* a theme-wide white data-label colour overrode Power BI's automatic contrast — white on neon funnel bars | Theme-wide label colour removed; in-bar labels now dark, outside labels light |
| 19 | *Theme:* model-selector text clipped, and the Top 10 scrolled | Label beside an untitled 68 px selector; axis titles and value axis dropped from the Top 10 (its data labels carry the values) |
| 20 | *Theme:* a two-line card label pushed its value down | Shorter label |

The data review found three more, fixed in the model rather than the page: outcomes
recorded after the as-of date leaking into the funnel (D33), attributed revenue dated by
touch rather than booking (D34), and one chart description that was wrong on the final
basis (D38).

## Deliberately not used

- **Maps.** Five regions: a bar or treemap reads five values more precisely, and
  Desktop's map visuals need an opt-in and an online tile service.
- **Pie.** The donut does the same job with room for labels.
- **AI visuals** (Q&A, smart narrative, key influencers). Their output cannot be
  reproduced or tested from the files.
- **Channel rankings of CTR, CPC or CPM.** The rates are identical on every channel in
  this data (D36).

The Phase 3 visual lab that first proved each visual type is in git history (commit
`197f398`), with its captures in `Validation/evidence/phase3/`.
