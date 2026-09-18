# Data Quality & Feasibility Audit

*Healthcare claims and revenue cycle - Phase 1. Every number below is produced by*
*`Python/01_data_audit.py` and written to `Validation/audit_metrics.json`.*

**The dataset is synthetic.** It is a portfolio dataset for a fictional provider
group. No real patient, provider or payer data is involved, and nothing here is
presented as a real organisation's revenue cycle.

---

## 1. What arrived

| Table | Rows | Grain | Notes |
|---|---:|---|---|
| `fact_claims` | 100,000 | one claim | Billed, allowed and paid on the header |
| `fact_claim_lines` | 249,905 | one procedure line | Charge, procedure and diagnosis code |
| `fact_payments` | 69,111 | one remittance | |
| `fact_denials` | 7,824 | one denial | Reason and status |
| `dim_beneficiary` | 30,000 | one patient | Date of birth, gender, state, risk band |
| `dim_provider` | 500 | one provider | Specialty, home facility |
| `dim_facility` | 30 | one facility | Type, state |
| `dim_payer` | 6 | one payer | |
| `dim_date` | 1,704 | one day | |
| `security_user_access` | 82 | one user grant | Facility / provider scope |

**Keys are clean.** No duplicate primary key in any table (0 found), and no orphan foreign key (0 found across seven relationships).

**No nulls in `fact_claims`** - every one of its 12 columns is fully populated, including all three dates.

## 2. The money chain, and the identity this project rests on

Three amounts sit on every claim header: what was **billed**, what the payer
**allowed** under contract, and what was actually **paid**. The gaps between them
are the revenue cycle.

| Step | Amount | Share of billed |
|---|---:|---:|
| Billed | $98,876,591 | 100.0% |
| less contractual adjustment | −$26,163,408 | 26.5% |
| **Allowed** | **$72,713,182** | **73.5%** |
| less denied | −$5,698,778 | 5.8% |
| less patient responsibility | −$3,768,666 | 3.8% |
| less open AR | −$16,831,000 | 17.0% |
| **Collected** | **$46,414,738** | **46.9%** |

**The allowed amount closes exactly.** Collected + patient responsibility + open AR
+ denied = $72,713,182 against an allowed
total of $72,713,182 - a residual of **$0**. Every dollar the
payer agreed to is in exactly one of four buckets, which is the identity the whole
model is built to preserve and the validation suite re-checks on every refresh.

Gross collection rate (paid / billed) is **46.9%**; net collection rate
(paid / allowed) is **63.8%**. Net is the one a revenue-cycle team is measured
on, because no provider ever collects the sticker price - the contractual adjustment
of 26.5% is agreed in advance, not lost.

No claim allows more than it bills, pays more than it allows, or carries a negative amount (0 violations in 100,000 rows).

### The contract that is not a contract

The allowed rate per claim runs from 55.0% to 92.0% of billed, averaging 73.52%. Split by payer it averages 73.42% to 73.63% - a spread of **0.21 percentage points across six payers**.

In a real provider group the allowed rate *is* the payer contract, and payers differ
by tens of points. Here every payer draws from the same distribution, so **payer
contract performance cannot be analysed** - there is nothing to find. Worse, the same
rate is applied to **Self Pay**, where by definition no contracted rate exists: a
self-pay patient is billed the chargemaster price. The report therefore states the
contractual adjustment as a single group-wide number and does not rank payers by it.

The gap between allowed and paid on a **paid** claim is steadier: the payer settles 92.5% of the allowed amount on average (range 85.0% to 100.0%), leaving 7.5% as patient responsibility - copay, coinsurance and deductible. That is a realistic share and it is treated as a real quantity throughout.

## 3. What `ClaimStatus` actually means here

| Status | Claims | Share | Paid amount | Has a payment row | Has a denial row |
|---|---:|---:|---:|---:|---:|
| Paid | 69,111 | 69.1% | $46,414,738 | 69,111 | 0 |
| Pending | 23,065 | 23.1% | $0 | 0 | 0 |
| Denied | 7,824 | 7.8% | $0 | 0 | 7,824 |

The three statuses are clean and mutually exclusive: a paid claim always has exactly
one payment row and never a denial; a denied claim always has exactly one denial row,
no payment, and a paid amount of zero; a pending claim has neither.

**There are no partial payments.** Every paid claim settles in exactly one remittance
(0 claims have more than one). So there is no split remittance, no takeback, no secondary payer and no
payment plan. Days-to-pay is a single event, which makes it clean to measure - and it
means **no claim is ever partly collected**: a claim is paid in full to its allowed
share, or it is not paid at all.

## 4. Finding 1 — 'Pending' is a permanent state, not an ageing tail

23.1% of claims are Pending. The question that decides
whether an AR ageing means anything is *when* those claims were submitted.

They were submitted **evenly across the entire file**. Over the 44 complete submission months the pending share runs from 20.6% to 25.0% - 24.1% in 2023-01, the first month of the file, and 22.3% in 2026-08, the last. A claim submitted in January 2023 is exactly as likely to be Pending as one submitted last month.

Measured at the as-of date (2026-11-03), the median pending claim is **737 days old**, the oldest is 1402 days, and **17,808 of 23,065 (77.2%) are more than a year old**.

**What this means.** A claim outstanding for three years does not exist in a real
revenue cycle - payer timely-filing limits are 90 to 365 days, after which it is
written off. So the AR ageing here is arithmetically correct but it is not a
collections story: it is the shape of a status that was assigned at random and never
revisited. The report builds the ageing properly - the buckets, the days in AR, the
value at risk - and says this on the page, because an executive shown a
77.2% over-365 bucket would otherwise conclude the billing office
had collapsed.

## 5. Finding 2 — a denial never recovers, whatever its status says

| Denial status | Denials | Claims later paid | Amount recovered |
|---|---:|---:|---:|
| Open | 2,008 | 0 | $0 |
| Written Off | 1,957 | 0 | $0 |
| Appealed | 1,946 | 0 | $0 |
| Corrected | 1,913 | 0 | $0 |

`DenialStatus` carries four values - Open, Written Off, Appealed, Corrected - and **0 of the 7,824 denied claims were ever paid**, including every one of the 1,913 marked *Corrected* and the 1,946 marked *Appealed*.

The denial date is also the processed date on every single denial (lag 0 to 0 days), so there is no appeal timeline either.

**What this means.** Appeal yield, overturn rate, recovery rate and days-to-overturn -
the four numbers a denials manager actually works to - **cannot be computed from this
data**. They are not built. What is built is the denial *status mix*, labelled as a
workflow state rather than an outcome, and the report says plainly that no recovery
is observable.

## 6. Finding 3 — first-pass acceptance is the denial rate written twice

A first-pass acceptance rate is only interesting when it differs from the final
acceptance rate - the gap between them is the rework the billing office had to do.
That requires a resubmission chain. This data has none:

- There is no `OriginalClaimID` or equivalent column on `fact_claims` (absent).
- No claim carries more than one denial (0 claims do).
- No denied claim is ever subsequently paid (section 5).

So first-pass acceptance = 1 − denial rate = **92.2%**, exactly, and
clean-claim rate is the same number a third time. All three are published because the
brief asks for them, on one card together, with a note that they are arithmetically
identical here rather than three independent measurements.

## 7. Finding 4 — the only thing that predicts a denial is who is paying

Each dimension below is tested the same way: the denial rate within each value, and
the spread between the highest and lowest. A dimension with real signal separates;
one without it collapses to the group rate.

| Dimension | Values | Lowest | Highest | Spread |
|---|---:|---:|---:|---:|
| Payer | 6 | 2.95% | 9.08% | **6.13 pp** |
| Facility type | 4 | 7.76% | 7.90% | **0.14 pp** |
| Facility | 30 | 7.07% | 8.48% | **1.41 pp** |
| Specialty | 8 | 7.51% | 8.06% | **0.54 pp** |
| Chronic risk band | 3 | 7.73% | 7.90% | **0.17 pp** |
| Gender | 3 | 7.72% | 7.88% | **0.16 pp** |
| Patient state | 6 | 7.61% | 8.14% | **0.53 pp** |
| Facility state | 5 | 7.66% | 7.98% | **0.32 pp** |
| Procedure code | 10 | 7.68% | 8.03% | **0.36 pp** |
| Diagnosis code | 10 | 7.47% | 8.24% | **0.77 pp** |

**One split is real.** Self Pay denies at 2.95% against 8.79% for
the five insurers - a gap of 5.8 points, and it is the largest
effect anywhere in the data. But *among* the five insurers the spread is only
0.66 points (Bupa 8.42% to NIB 9.08%), which is noise at these volumes.

**Provider variation is indistinguishable from chance.** Across the 500 providers
with at least 100 claims, the denial rate runs 2.8% to 14.2%, which looks like a league table worth publishing. It is not.
The standard deviation of those rates is **1.95 pp**; the standard deviation
you would get by flipping a 7.8% coin the same number of times per provider is
**1.90 pp**. The observed spread is 1.03× the spread
of pure chance - in other words, all of it.

**What this means.** Ranking providers or facilities by denial rate here would name
and shame people for noise. The report shows the provider distribution *against its
chance baseline* instead, which is the honest version of the same chart, and the
denial page leads with payer mix because that is where the only real effect is.

The continuous candidates fare no better:

| Candidate | Correlation with denial |
|---|---:|
| Patient age | -0.0019 |
| Billed amount | -0.0001 |
| Line count | -0.0003 |
| Days to submit | -0.0031 |

Every one is inside |r| < 0.01. **No denial-risk model is built.** One trained on these
features would be fitting noise, and would then be used to hold up claims that were
never at risk.

One more check worth making: 1,117 claims are denied for **Duplicate Claim**, but there are **0 actual duplicates** in the file - no two claims share a patient, provider, service date and billed amount. The denial reason is a label drawn from a list, not a finding about the claim. Reason mix is therefore reported as a workload profile, never as a root cause.

## 8. Finding 5 — the procedure code does not price the procedure

There are 10 procedure codes and 10 diagnosis codes. The average charge per code runs from
$391.76 to $397.46 - a spread of **$5.69**, or 1.5%, across every code in the file.

Those codes are real CPT and ICD-10 values, and in a real chargemaster they are not
remotely comparable: 36415 is a venipuncture worth a few dollars, 70553 is an MRI of
the brain with and without contrast worth well over a thousand. Here they average
within a few dollars of one another because the charge is drawn independently of the
code.

**What this means.** Case-mix analysis, cost-per-procedure, service-line profitability
and procedure-level pricing are all off the table. The code dimensions are still
modelled and still useful - they carry *volume* faithfully, and volume by service line
is a real operational question - but no page ranks a procedure by revenue.

## 9. What the data does support: the clock

| Interval | Median | Mean | Max |
|---|---:|---:|---:|
| Service → submission | 4 d | 3.5 d | 7 d |
| Submission → adjudication | 29 d | 29.0 d | 54 d |
| Adjudication → payment | 5 d | 4.5 d | 9 d |
| **Submission → payment** | **33 d** | **33.5 d** | 63 d |

These are well-formed and internally consistent - no claim is submitted before it is
performed, adjudicated before it is submitted, or paid before it is adjudicated. The
whole cycle runs a median of 33 days from submission to cash, which
is a believable figure for a clean electronic claim and is the strongest thing this
data has to offer. **Timeliness is where the analysis leans.**

Volume is flat: 2,067 to 2,383 claims per service month across
44 complete months, a coefficient of variation of 3.4%. **There is no seasonality and no trend** - so
no growth narrative is offered, and any month-on-month movement on the pages is
correctly read as noise.

## 10. The date dimension does not cover the facts

`dim_date` runs 2022-01-01 to 2026-08-31 (1,704 rows, 0 internal gaps).
The facts run past the end of it:

| Date column | Rows outside `dim_date` | Share |
|---|---:|---:|
| ServiceDate | 0 | 0.00% |
| SubmittedDate | 260 | 0.26% |
| ProcessedDate | 2,443 | 2.44% |
| PaymentDate | 1,905 | 2.76% |
| DenialDate | 199 | 2.54% |

Service dates fit, because the calendar was built to the service range. But a claim is
submitted after it is performed, adjudicated after that and paid after that, so the
tail spills over: 2,443 adjudications and 1,905
payments land on days the calendar does not contain.

**What this means.** Left alone, every one of those rows joins to a blank date and
quietly disappears from any measure sliced by adjudication or payment month - the
worst kind of error, because the totals still look plausible. The SQL build therefore
**generates its own date dimension** covering every date in every fact table plus a
margin, keeping the supplied columns (financial year, ISO week) and adding what a
revenue-cycle model needs.

The supplied calendar uses an **Australian financial year** - July to June, labelled by
the year it ends in (1 July 2022 falls in FY23). That convention is preserved, because
the facility states (NSW, QLD, SA, VIC, WA) are Australian too.

## 11. Dimension coverage and security

- **1,034 of 30,000 beneficiaries never appear on a claim** (3.4%). A patient count taken from the dimension would overstate
  the treated population by that much, so every patient count in the model is taken
  from the claims, not from the dimension.
- All 500 providers and all 30 facilities are used.
- **Each provider belongs to exactly one facility, and 100.0% of claims are
  billed at the provider's own facility.** Provider and facility are therefore one
  hierarchy, not two independent dimensions - which matters for row-level security:
  filtering facility implicitly filters provider, and a naive two-table security
  filter would be applied twice.

`security_user_access` carries 82 grants across 4 roles:

| Role | Users | Scope |
|---|---:|---|
| Provider | 50 | one provider each |
| Facility Manager | 30 | one facility each |
| Executive | 1 | all facilities and providers |
| Revenue Cycle | 1 | all facilities and providers |

Every scoped grant points at a real facility or provider (0 invalid
references), so dynamic RLS can be built directly on this table.

## 12. Do the claim lines reconcile to the header?

Every claim has between 1 and 4 lines (mean 2.50), and
the lines sum to the header billed amount on **75,835 of 100,000** claims exactly. The remaining 24165 differ by at most **$0.02** - cent-level rounding from splitting a header amount across lines,
not a data error.

This matters more than it looks. Because the lines reconcile, the line table can carry
procedure and diagnosis analysis *without* becoming a second source of truth for money:
every financial measure in the model is defined on the claim header, and the line table
is used only for volume and mix. A model that summed charges from both would
double-count.

## 13. What will be built, and what will not

| The brief asks for | Verdict | What is built instead |
|---|---|---|
| First-pass acceptance rate | **Supported, but not independent** | Published with the denial rate and clean-claim rate on one card, noted as arithmetically identical |
| Clean-claim rate | **Supported, same caveat** | As above |
| Denial rate | **Supported** | By payer, reason, facility, specialty, month - with a chance baseline on the provider view |
| Collection rate | **Supported** | Gross and net, and the four-bucket allowed-amount identity |
| AR ageing from service/submission/payment dates | **Computable, but not a collections story** | Built in full, with the finding in section 4 stated on the page |
| Denial root cause by payer | **Partly** | The Self Pay split is real; the five insurers are within noise of each other |
| Denial root cause by facility / provider / diagnosis / procedure | **Not supported** | Provider distribution shown against its chance baseline instead of a league table |
| A churn/denial-risk model on claim features | **Not supported** | Not built - every candidate is inside \|r\| < 0.01 |
| Appeal and recovery analysis | **Not supported** | Denial status shown as workflow state, with no recovery claimed |
| Payer contract performance | **Not supported** | Contractual adjustment reported group-wide, payers not ranked |
| Provider- and facility-level dynamic RLS | **Supported** | Built on `security_user_access`, as one hierarchy |
| Incremental refresh, DirectQuery/composite | **Out of scope here** | Requires the Service; folding to SQL Server is proved instead |

---

## The short version

1. The money closes exactly: every dollar of the $72,713,182 allowed is collected,
   owed by a patient, denied, or still in AR. That identity is the spine of the model.
2. 'Pending' is not an ageing tail - 77.2% of AR is over a year old and
   the pending share is identical in every month of the file.
3. A denial never recovers, whatever its status says, so appeal yield is not offered.
4. Nothing predicts a denial except Self Pay (2.95% vs 8.79%).
   Provider variation is 1.03× chance - that is, all of it.
5. The procedure code does not price the procedure, so no service-line revenue ranking.
6. The supplied calendar misses 4,348
   adjudication and payment dates; the build generates its own.

The timeliness of the cycle, the composition of the money, the denial workload profile
and the AR shape are all real. That is the project.

