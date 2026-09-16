# Semantic Model - SaaS Revenue, Retention & Churn

Generated from `Python/02_generate_semantic_model.py` and `Python/model_measures.py`.
Nothing is authored in the Power BI interface, so the model is reviewable as code and a
re-run produces byte-identical files.

**20 tables + 1 calculation group + 1 field parameter · 142 columns · 24 relationships ·
87 measures · row-level security by country.**

Verified by `Validation/verify_semantic_model.py` (**605 of 605** static checks against
the live SQL views) and `Validation/reconcile_measures.ps1` (**870 of 870** checks
against independently written SQL, on the live model).

---

## The shape, and why it is this shape

Two fact tables carry the story and they are deliberately at different grains.

| | Grain | Rows | Answers |
|---|---|---:|---|
| `FactSubscriptionMonth` | subscription × month it is live at month end | 320,294 | *What was on the books?* |
| `FactMRRMovement` | customer × month its MRR changed, classified | 14,292 | *What changed, and which way?* |

A snapshot and a ledger of changes are two views of the same truth, so they can be made
to check each other - and `SQL/09_validation.sql` does exactly that, every month:

```
MRR(month) = MRR(month - 1) + SUM(movements in month)
customers(month) = customers(month - 1) + new - churned
```

Zero violations across all 56 months. That identity is what makes the waterfall on the
Revenue Movement page evidence rather than decoration.

### MRR is a stock

The single most common way to be confidently wrong about a SaaS business is to sum MRR
over time. January's MRR plus February's MRR is the same subscription counted twice.

Every point-in-time measure therefore goes through one hidden measure:

```dax
Snapshot Month =
VAR AsOfMonth = [As-Of Month]
VAR LastInContext = MAX ( DimDate[MonthStart] )
VAR FirstInContext = MIN ( DimDate[MonthStart] )
RETURN
    IF ( FirstInContext <= AsOfMonth, MIN ( LastInContext, AsOfMonth ) )
```

It reads the last month in the current filter, caps it at the as-of date, and returns
BLANK when the whole selection lies beyond the data. Selecting January to August gives
MRR **at the end of August**, which is what MRR means. Selecting a month the data does
not reach gives nothing, rather than yesterday's number drawn flat into the future.

### The two axes of a cohort matrix are dimensions

`DimCohort` (54 signup months, each with its size and opening MRR) and `DimTenureMonth`
(M0 to M55) exist so the retention matrix sorts by time and by tenure. Held as fact
columns they would sort alphabetically - "Apr 2022" before "Aug 2022", "M10" before
"M2" - and the matrix would be unreadable.

`[Cohort Retention %]` returns BLANK where a cohort has not yet lived that long, so the
matrix renders as the triangle it really is instead of showing 0% for a future that has
not happened.

### One fact answers two questions about time

`FactSubscription` has two relationships to the calendar:

- **`StartDate` → `DimDate[Date]`, active.** Filtering the calendar selects the
  customers that *arrived* in the period.
- **`EndDate` → `DimDate[Date]`, inactive.** Reached with `USERELATIONSHIP` where churn
  timing is the question.

One table, both questions, no duplicated fact.

---

## Tables

| Table | Source view | Rows | Role |
|---|---|---:|---|
| `DimDate` | `vw_DimDate` | 2,007 | Calendar to 30 Jun 2027; the source stops on the as-of date, so it was extended to complete FY27 and the added days are flagged |
| `DimCustomer` | `vw_DimCustomer` | 12,000 | Accounts. Acquisition channel and attribution live here - they describe the customer. Secured by country |
| `DimPlan` | `vw_DimPlan` | 4 | The price book. The one strong churn driver |
| `DimSeverity` | `vw_DimSeverity` | 4 | Ticket severity, ordered Low to Critical |
| `DimMovementType` | `vw_DimMovementType` | 5 | The five MRR movements, each carrying whether it can occur in this data and why not |
| `DimTenureBand` | `vw_DimTenureBand` | 5 | Tenure grouped and ordered |
| `DimCohort` | `vw_DimCohort` | 54 | Signup months with size and opening MRR |
| `DimTenureMonth` | `vw_DimTenureMonth` | 56 | Months since signup, M0 first |
| `FactSubscription` | `vw_FactSubscription` | 12,000 | One subscription, which here is one customer |
| `FactSubscriptionMonth` | `vw_FactSubscriptionMonth` | 320,294 | The monthly snapshot |
| `FactMRRMovement` | `vw_FactMRRMovement` | 14,292 | The movement ledger |
| `FactInvoice` | `vw_FactInvoice` | 177,236 | Billing. A flow, and lumpy: annual customers bill twelve months at once |
| `FactUsageMonthly` | `vw_FactUsageMonthly` | 113,038 | Product usage - a sample covering ~40% of paying customers |
| `FactSupportTicket` | `vw_FactSupportTicket` | 45,000 | Support |
| `FactAcquisition` | `vw_FactAcquisition` | 12,000 | What each customer cost |
| `ChurnDriverStrength` | `vw_ChurnDriverStrength` | 11 | The measured correlation between each candidate driver and churn, computed in SQL. Disconnected on purpose |
| `DataQualityMetric` | `vw_DataQualityMetric` | 15 | Coverage and consistency figures, computed live |
| `ModelConfig` | `vw_ModelConfig` | 6 | Every assumption, as data. Hidden |
| `SecurityUserAccess` | `vw_SecurityUserAccess` | 8 | The RLS mapping. Hidden |
| `_Measures` | — | 0 | Every measure |

`ChurnDriverStrength` is disconnected deliberately. It describes the customer base as a
whole; if a slicer could filter it, the correlation shown would no longer be the
correlation that was computed.

---

## The calculation group

**Time Comparison** (precedence 10) applies to whatever measure a visual is showing, so
one selection replaces six copies of every measure.

| Item | Does |
|---|---|
| Selected period | The measure as it stands |
| Prior month | The same measure one month earlier |
| Month over month | This month less last month |
| Month over month % | The change as a share of last month |
| Prior year | The same measure twelve months earlier |
| Year over year % | Growth on the same month a year earlier |

Every comparison is BLANK where the model has no data to compare against - a year the
ledger does not reach is blank, not infinite growth, and a percentage of zero is
unanswerable rather than infinite.

## The field parameter

**Customer Cut** lets a reader change the question instead of the page: Segment,
Industry, Country, Plan, Acquisition channel or Billing cycle. One slicer drives every
"by" visual, which is both better for the reader and six fewer charts to maintain.

Its middle column carries the `ParameterMetadata` extended property. Without it the
column is ordinary text, the slicer silently stops switching anything, and nothing
anywhere reports an error - so `verify_semantic_model.py` checks for it, and that every
field it names still exists.

---

## Measures

87 measures in 12 folders. Full DAX and measured values in
[dax_measure_dictionary.md](dax_measure_dictionary.md).

| Folder | What it holds |
|---|---|
| 00 Model Context | The as-of date, the snapshot month, the gross-margin assumption, the page header |
| 01 Revenue | MRR, ARR, opening MRR, ARPA, realised price against list, invoiced and collected |
| 02 MRR Movement | The five components, the net, and whether each can occur here |
| 03 Customers | Counts, arrivals, departures, tenure |
| 04 Retention & Churn | Logo and revenue churn, GRR, NRR, the gap between them, annualised and trailing-twelve-month views |
| 05 Cohorts | Cohort size, retained customers and MRR, retention %, months to half retained |
| 06 Unit Economics | CAC blended and median, gross profit per account, payback, LTV, LTV:CAC |
| 07 Product Usage | Coverage, seats, utilisation, adoption, logins, errors |
| 08 Support | Tickets, contact rate, urgency, mean time to resolve |
| 09 Billing | Invoices, failures, failure rate, days to pay |
| 10 Churn Drivers | Measured correlation, its strength in words, churn rate by any cut |
| 11 Data Quality / 12 Report Formatting | Live data-quality figures, and the colour measures the report reads |

### Three measures worth reading closely

**`Net Revenue Retention %`** is published beside `Gross Revenue Retention %` and they
are identical, because this data has no expansion or contraction. `NRR less GRR (pp)`
exists to show that gap is exactly zero. Quoting NRR alone would imply an expansion
motion that does not exist here.

**`Tickets per Customer per Month`** divides by months of customer life. The raw ticket
count correlates with churn at −0.00 because it mostly measures how long somebody has
been a customer; the rate correlates at +0.15. Both are on the page, because the
contrast is the lesson.

**`LTV`** states its assumptions in its own description: a gross margin that is not in
the data, and a churn rate assumed constant. It is a planning number and the page says
so next to it.

---

## Row-level security

Role **Country Access**, by `USERPRINCIPALNAME()` against `SecurityUserAccess`.

| Scope | Users | Sees |
|---|---|---|
| `ALL` | Revenue Operations, CFO | Every country |
| One country | 6 customer success managers | Their own country |
| Unmapped | anyone else | **Nothing** |

The filter is applied to `DimCustomer` alone. Every one of the seven fact tables reaches
a customer, so filtering the one dimension secures all of them - and
`verify_semantic_model.py` checks that each fact really does have that path, because a
fact that could be read around the dimension would be a hole.

`reconcile_measures.ps1` tests the secure default by connecting *as the role* with no
identity (0 countries, 0 MRR, 0 customers) and then evaluates the role's own filter
expression for all eight users, comparing each one's visible MRR with SQL.

**Stated limit.** The engine's `EffectiveUserName` needs a real Windows account, so the
synthetic `@northstar.demo` addresses cannot be impersonated on this machine. The role's
logic is tested instead; Desktop's *View as → Other user* stays a manual check.
