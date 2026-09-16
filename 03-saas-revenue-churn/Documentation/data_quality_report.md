# Data Quality Report - SaaS Revenue, Retention & Churn

What the raw files contain, what they support, and what they do not. Every number
here is computed by `Python/01_data_audit.py` from the CSVs and re-checked in SQL
(`SQL/09_validation.sql`); none is typed from memory. **The data is synthetic** - a
portfolio dataset for a fictional SaaS business, never a real customer base.

## 1. What arrived

| File | Rows | Columns | Grain |
|---|---:|---:|---|
| `dim_customer.csv` | 12,000 | 6 | one row per customer |
| `dim_plan.csv` | 4 | 3 | one row per plan |
| `dim_date.csv` | 1,704 | 9 | one row per day |
| `fact_subscriptions.csv` | 12,000 | 8 | one row per subscription |
| `fact_invoices.csv` | 177,236 | 7 | one row per invoice |
| `fact_product_usage_monthly.csv` | 113,038 | 7 | customer x month |
| `fact_support_tickets.csv` | 45,000 | 7 | one row per ticket |
| `fact_customer_acquisition.csv` | 12,000 | 4 | one row per customer |
| `security_user_access.csv` | 8 | 3 | one row per user |

The calendar runs **2022-01-01 to 2026-08-31** (1,704 days). The last day with data is the **as-of date, 2026-08-31**: every
point-in-time figure in this project is stated on it.

## 2. Keys and referential integrity

| Relationship | Orphans | Of |
|---|---:|---:|
| `fact_subscriptions.CustomerID` -> `dim_customer` | 0 | 12,000 |
| `fact_invoices.CustomerID` -> `dim_customer` | 0 | 177,236 |
| `fact_invoices.SubscriptionID` -> `fact_subscriptions` | 0 | 177,236 |
| `fact_product_usage_monthly.CustomerID` -> `dim_customer` | 0 | 113,038 |
| `fact_support_tickets.CustomerID` -> `dim_customer` | 0 | 45,000 |
| `fact_customer_acquisition.CustomerID` -> `dim_customer` | 0 | 12,000 |
| `fact_subscriptions.PlanID` -> `dim_plan` | 0 | 12,000 |

**0 orphan rows in total.** Duplicate keys: customers 0, subscriptions 0, invoices 0, tickets 0, usage rows per customer-month 0.

Every customer has exactly one acquisition row and **1 subscription** - which is the first fact that shapes everything below.

## 3. The subscription lifecycle

- **12,000 subscriptions** for 12,000 customers: one each, never more.
- **9,708 active** and **2,292 churned** (19.1% of all customers have churned at some point).
- Every churned subscription has an end date and every active one has none (9,708 / 9,708 and 2,292 / 2,292) - the status column and the
  dates never disagree, so either can be used and both give the same answer.
- No subscription ends on or before it starts (0).
- **The subscription start IS the customer signup date, for every customer** (100%). Signup cohorts and subscription
  cohorts are therefore the same thing; this project uses the subscription start.

Median tenure is **13.2 months for a churned** subscription and **28.6 months for one still running** (measured to the as-of date).

## 4. Billing: does the money tie to the subscription?

- Every annual invoice is exactly twelve times the subscription's MRR (16,243 of 16,243) and every monthly
  invoice is exactly the MRR (160,993 of 160,993). Billing is derived from MRR, not independent of it.
- No invoice is dated after its subscription ended (0).
- **11,599 invoices are dated before their subscription starts** - and every one of them falls in
  the same calendar month (100%). Invoices are all dated to the **1st of the month** (day-of-month values present: [np.int32(1)]), while a subscription can start
  on any day. This is a billing-date convention, not a fault - but it means an invoice date must never
  be used to decide when a subscription began.
- **6,041 invoices failed** (3.4% of 177,236), across 3,781 customers. A failed invoice carries no
  payment date; a paid one is settled in a median of 4 days.

| Plan | List price | Subscriptions | MRR min | MRR mean | MRR max |
|---|---:|---:|---:|---:|---:|
| Starter (`PL01`) | $49 | 4,238 | $42 | $51 | $61 |
| Growth (`PL02`) | $149 | 4,232 | $127 | $157 | $186 |
| Business (`PL03`) | $399 | 2,573 | $339 | $420 | $499 |
| Enterprise (`PL04`) | $1,200 | 957 | $1,020 | $1,267 | $1,500 |

MRR sits between **85% and 125% of list price** - every subscription is
discounted or uplifted off its plan, so realised price is worth reporting separately from list.

## 5. Can this data support an MRR movement waterfall?

This is the question the whole project turns on, so it is answered with evidence rather than assumed.
A full SaaS waterfall has five components: **New, Expansion, Contraction, Churn and Reactivation**.

| Component | Supported? | The evidence |
|---|---|---|
| **New** | Yes | Every subscription has a start date, and it equals the customer's signup date |
| **Churn** | Yes | Every churned subscription has an end date; none is dated after its last invoice |
| **Expansion** | **No** | MRR is one static number per subscription, and all 12,000 subscriptions bill exactly one invoice amount for life |
| **Contraction** | **No** | Same reason: there is no second MRR value to fall to |
| **Reactivation** | **No** | One subscription per customer ever, so no customer can leave and return |

**So the movement this dataset can describe is New and Churn.** The model still computes all five
components - the logic is written, tested and visible - and three of them are structurally nil. That
is reported on the page rather than hidden, because two well-known consequences follow:

1. **Net revenue retention can never exceed gross revenue retention**, and in fact they are equal:
   with no expansion or contraction, NRR = GRR = (opening MRR - churned MRR) / opening MRR. Any NRR
   above 100% in a report built on this data would be an arithmetic error.
2. **Seat counts do move** (see section 6) - but MRR does not follow them, so seat growth is an
   adoption signal, never billed expansion. The two are kept apart throughout.

### A trap in the last two months

The newest subscription starts on **2026-06-30**. Churn, however, runs to
2026-08-30. So the file ends with **2 months of churn and no new
business at all** - not because the business stopped selling, but because acquisition data stops first.

| Month | Active subs | MRR | New | Churned |
|---|---:|---:|---:|---:|
| 2026-03 | 9,650 | $2,682,993 | 262 | 100 |
| 2026-04 | 9,778 | $2,729,636 | 236 | 108 |
| 2026-05 | 9,865 | $2,765,003 | 222 | 135 |
| 2026-06 | 9,960 | $2,803,036 | 203 | 108 |
| 2026-07 | 9,824 | $2,783,733 | 0 | 136 |
| 2026-08 | 9,708 | $2,759,496 | 0 | 116 |

MRR peaks at **$2,803,036 in 2026-06** and reads $2,759,496 at the as-of date (**ARR $33,113,950**). Read without the caveat, the last two months look like a business in
decline. They are an artefact of where the extract ends, and the report says so on the page.

## 6. Product usage: a sample, not a census

The usage table holds 113,038 rows for 11,802 customers over 56 months - but a customer appears in a median of only
**9 months** (maximum 28), while the median active subscription runs 29 months.

| Month | Active subscriptions | Customers with usage | Coverage |
|---|---:|---:|---:|
| 2026-03 | 9,650 | 3,547 | 36.8% |
| 2026-04 | 9,778 | 3,694 | 37.8% |
| 2026-05 | 9,865 | 3,756 | 38.1% |
| 2026-06 | 9,960 | 3,841 | 38.6% |
| 2026-07 | 9,824 | 3,783 | 38.5% |
| 2026-08 | 9,708 | 3,848 | 39.6% |

**Usage describes about 40% of the customers who are paying in any given month.** Every
adoption, seat and login figure in this project is therefore reported as *of the customers we can see*,
never as a share of the customer base, and never used as a denominator for revenue.

Where it is present the usage data is clean: active users never exceed licensed seats (0 rows), adoption sits inside 0-1, and
**95% of customers change their licensed seat count** over time. Seats move; MRR does not.

## 7. Support tickets

45,000 tickets for 11,720 customers. Severity, status and category are all
populated, with no nulls anywhere.

**18,142 tickets that are still Open or Escalated nevertheless carry a resolution time** (all 18,142 of them). A ticket that is not resolved cannot have taken any
time to resolve, so mean time to resolve is computed over **resolved tickets only** throughout.

| Ticket status | Tickets | Mean hours | Median hours |
|---|---:|---:|---:|
| Escalated | 9,022 | 6.43 | 4.75 |
| Open | 9,120 | 6.48 | 4.75 |
| Resolved | 26,858 | 6.52 | 4.79 |

The three means are 6.43, 6.48 and 6.52 hours - statistically the same number. The field is populated from one
distribution regardless of status, so it is not a real resolution time for a ticket that has not been
resolved. Restricting to resolved tickets moves the mean by only 0.03 hours here (6.49 to 6.52), but the definition is still the
correct one and it is the one used - and no claim is made anywhere that escalation takes longer to fix,
because in this data it does not.

## 8. Acquisition cost

Acquisition cost is stated once per customer: mean **$2,017**, median $1,202, range $0.33 to $5,232.

The distribution is heavily right-skewed - the mean is 1.7x
the median - and 384 customers were acquired for under $100, the
cheapest for $0.33. Blended CAC (total spend / customers) is the right
headline because it is what the money actually was; the median is shown beside it so the skew is visible
rather than averaged away.

| Channel | Customers | Mean CAC | Median CAC |
|---|---:|---:|---:|
| Event | 1,732 | $1,962 | $1,174 |
| Google Ads | 1,687 | $2,077 | $1,214 |
| LinkedIn Ads | 1,732 | $1,996 | $1,196 |
| Organic Search | 1,660 | $2,039 | $1,223 |
| Outbound | 1,714 | $2,029 | $1,208 |
| Partner | 1,734 | $1,957 | $1,183 |
| Referral | 1,741 | $2,065 | $1,222 |

**Channel does not differentiate cost.** The spread between the dearest and cheapest channel mean is
$120 on a ~$2,017 base - about 6%. Like the churn
cuts in section 9, these are worth showing because a reader will ask, but none of them is a finding.

Two things it does not come with, both of which a payback or LTV figure needs:

- **No gross margin.** There is no cost-of-service anywhere in the data, so LTV and CAC payback cannot
  be derived - they can only be modelled. This project carries gross margin as a **stated, adjustable
  assumption** shown on the page beside the result, never buried in a measure.
- **No spend by channel over time.** Cost is attached to the customer, not to a campaign or a month, so
  a blended CAC by channel is honest but a marketing-efficiency trend is not.

## 9. What actually drives churn here

The dataset's own brief suggests training a churn model on usage, tickets, payment history and tenure.
Before building anything on that, the relationships were measured. They are not what the brief assumes.

Correlation with ever having churned, across all 12,000 customers:

| Feature | r | n | Note |
|---|---:|---:|---|
| Plan price point (MRR) | -0.124 | 12,000 | the subscription's own MRR |
| Support contact **rate** (tickets per month of tenure) | +0.151 | 12,000 | exposure-adjusted |
| Feature adoption, last 90 days | -0.012 | 8,216 | usage sample only |
| Seat utilisation (active users / licensed seats) | -0.001 | 8,216 | usage sample only |
| Logins, last 90 days | +0.004 | 8,216 | usage sample only |
| Critical errors, last 90 days | +0.006 | 8,216 | usage sample only |
| Licensed seats | +0.006 | 8,216 | usage sample only |
| Payment **failure rate** (failed / invoices) | +0.000 | 12,000 | exposure-adjusted |
| Acquisition cost | -0.006 | 12,000 | one value per customer |
| Raw ticket count | -0.003 | 12,000 | **not** exposure-adjusted |
| Raw failed-invoice count | -0.088 | 12,000 | **not** exposure-adjusted |

### Reading it

1. **Product usage is independent of churn.** Adoption, logins, seats, utilisation and critical errors
   all sit inside |r| < 0.02. The means are almost identical: adoption 0.594 for churned customers against 0.600
   for retained ones, seat utilisation 0.699 against 0.700. A churn model trained on these features would be fitting noise,
   and a health score built from them would be decoration. Neither is built here.

2. **The raw counts lie, and the rates tell the truth.** Raw ticket count correlates -0.003 with churn and raw failed-invoice count -0.088 - both flat or
   backwards, because a customer who stays longer simply accumulates more of everything. Divide by
   tenure and support contact rate becomes the second real signal (+0.151);
   divide failures by invoices and payment failure vanishes entirely (+0.000).
   **Involuntary churn does not exist in this dataset** - a failed payment says nothing about leaving.

3. **Price point is the one strong, real driver**, and it behaves the way SaaS actually behaves:

| Plan | List price | Customers | Ever churned |
|---|---:|---:|---:|
| Starter | $49 | 4,238 | 26.1% |
| Growth | $149 | 4,232 | 18.4% |
| Business | $399 | 2,573 | 12.9% |
| Enterprise | $1,200 | 957 | 7.8% |

   The gradient holds inside every customer segment, so it is the price point rather than the kind of
   company buying it.

4. **Everything else is flat.** The spread between the best and worst churn rate is only 0.9% across segments, 2.9% across industries,
   1.8% across countries and 5.5% across acquisition
   channels. Those cuts are worth showing - a reader will ask for them - but none is a finding.

**What this project builds instead of a churn model:** the drivers that were tested are shown with their
measured strength on the page, the two that carry signal are used, and the ones that do not are named as
such. A risk view built on price point and support-contact rate is smaller than the brief asked for, and
it is the part that is true.

## 10. Security data

8 users: 2 with group-wide access (Revenue Operations, CFO) and 6 country-scoped customer
success managers covering 6 countries. Every scoped country
exists in `dim_customer` (0 unmatched), so
row-level security by country resolves for every user.

## 11. What this means for the build

| Decision | Because |
|---|---|
| The MRR waterfall computes all five movement types, and reports three as structurally nil | MRR is static per subscription and there is one subscription per customer (section 5) |
| NRR and GRR are shown together and expected to be equal | No expansion or contraction exists to separate them |
| The last two months are marked as having no new business | Acquisition data stops 2026-06-30 while churn runs on (section 5) |
| Usage metrics are reported as a sample and never as a rate over all customers | Usage covers about 40% of paying customers in a month (section 6) |
| Mean time to resolve uses resolved tickets only | Unresolved tickets carry a resolution time they cannot have (section 7) |
| Gross margin is a stated assumption on the page | No cost of service exists in the data (section 8) |
| Blended CAC leads, median CAC sits beside it | The cost distribution is skewed 1.7x mean to median (section 8) |
| Resolution time is never compared across ticket statuses | The field holds the same distribution for resolved and unresolved tickets alike (section 7) |
| No churn-risk model; a tested driver view instead | Usage and payment features are uncorrelated with churn; price point and contact rate are not (section 9) |
| Support and payment behaviour are measured as rates, never counts | Raw counts measure tenure, not behaviour (section 9) |

---

*Generated by `Python/01_data_audit.py`. As-of date 2026-08-31. Synthetic data.*
