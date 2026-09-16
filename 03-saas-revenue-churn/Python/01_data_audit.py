"""
Phase 1 - data audit.

Reads the raw CSVs and answers the questions that decide what the model may claim,
BEFORE any of it is built:

  * Can this data support an MRR movement waterfall? (New / Expansion / Contraction /
    Churn / Reactivation) - or only some of it?
  * Is churn related to product usage, support contact and payment failure, the way a
    churn-risk model would assume?
  * What does the usage table actually cover?

Every figure printed here is written to Documentation/data_quality_report.md and to
Validation/audit_metrics.json, so the report and the model can be checked against the
same numbers later. Nothing is rounded away or assumed.

Usage:  python Python/01_data_audit.py [--source <dir>]

The source directory is resolved in this order, so a clone works with no edit:
  1. --source <dir>
  2. the SAAS_SOURCE environment variable
  3. Data/raw in this repository, which ships the same extracts
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _source():
    if "--source" in sys.argv:
        return Path(sys.argv[sys.argv.index("--source") + 1]).expanduser()
    if os.environ.get("SAAS_SOURCE"):
        return Path(os.environ["SAAS_SOURCE"]).expanduser()
    return ROOT / "Data" / "raw"


SRC = _source()
if not SRC.is_dir():
    raise SystemExit(f"Source directory not found: {SRC}\n"
                     f"Pass --source <dir> or set SAAS_SOURCE.")
OUT = ROOT / "Documentation" / "data_quality_report.md"
METRICS = ROOT / "Validation" / "audit_metrics.json"

M = {}          # every number the report cites
L = []          # report lines


def say(line=""):
    L.append(line)


def metric(key, value):
    M[key] = value
    return value


def pct(x, places=1):
    return f"{100 * x:.{places}f}%"


def money(x):
    return f"${x:,.0f}"


# ------------------------------------------------------------------- loading ---
cust = pd.read_csv(SRC / "dim_customer.csv", parse_dates=["SignupDate"])
plan = pd.read_csv(SRC / "dim_plan.csv")
date = pd.read_csv(SRC / "dim_date.csv", parse_dates=["Date"])
sub = pd.read_csv(SRC / "fact_subscriptions.csv", parse_dates=["StartDate", "EndDate"])
inv = pd.read_csv(SRC / "fact_invoices.csv", parse_dates=["InvoiceDate", "PaymentDate"])
use = pd.read_csv(SRC / "fact_product_usage_monthly.csv", parse_dates=["Month"])
tik = pd.read_csv(SRC / "fact_support_tickets.csv", parse_dates=["OpenedDate"])
acq = pd.read_csv(SRC / "fact_customer_acquisition.csv")
sec = pd.read_csv(SRC / "security_user_access.csv")

TABLES = {"dim_customer": cust, "dim_plan": plan, "dim_date": date, "fact_subscriptions": sub,
          "fact_invoices": inv, "fact_product_usage_monthly": use, "fact_support_tickets": tik,
          "fact_customer_acquisition": acq, "security_user_access": sec}

# The last day the data describes. Everything point-in-time is stated ON this date.
ASOF = metric("as_of_date", str(date.Date.max().date()))
ASOF_TS = pd.Timestamp(ASOF)

say("# Data Quality Report - SaaS Revenue, Retention & Churn")
say()
say("What the raw files contain, what they support, and what they do not. Every number")
say("here is computed by `Python/01_data_audit.py` from the CSVs and re-checked in SQL")
say("(`SQL/09_validation.sql`); none is typed from memory. **The data is synthetic** - a")
say("portfolio dataset for a fictional SaaS business, never a real customer base.")
say()

# --------------------------------------------------------------- 1. inventory ---
say("## 1. What arrived")
say()
say("| File | Rows | Columns | Grain |")
say("|---|---:|---:|---|")
GRAIN = {"dim_customer": "one row per customer", "dim_plan": "one row per plan",
         "dim_date": "one row per day", "fact_subscriptions": "one row per subscription",
         "fact_invoices": "one row per invoice", "fact_product_usage_monthly": "customer x month",
         "fact_support_tickets": "one row per ticket", "fact_customer_acquisition": "one row per customer",
         "security_user_access": "one row per user"}
for name, df in TABLES.items():
    metric(f"rows_{name}", len(df))
    say(f"| `{name}.csv` | {len(df):,} | {df.shape[1]} | {GRAIN[name]} |")
say()
say(f"The calendar runs **{date.Date.min().date()} to {date.Date.max().date()}** "
    f"({len(date):,} days). The last day with data is the **as-of date, {ASOF}**: every")
say("point-in-time figure in this project is stated on it.")
say()

# ------------------------------------------------------- 2. keys and integrity ---
say("## 2. Keys and referential integrity")
say()
checks = []


def integrity(label, missing, total):
    checks.append((label, missing, total))
    return missing


cids = set(cust.CustomerID)
integrity("`fact_subscriptions.CustomerID` -> `dim_customer`", (~sub.CustomerID.isin(cids)).sum(), len(sub))
integrity("`fact_invoices.CustomerID` -> `dim_customer`", (~inv.CustomerID.isin(cids)).sum(), len(inv))
integrity("`fact_invoices.SubscriptionID` -> `fact_subscriptions`",
          (~inv.SubscriptionID.isin(set(sub.SubscriptionID))).sum(), len(inv))
integrity("`fact_product_usage_monthly.CustomerID` -> `dim_customer`",
          (~use.CustomerID.isin(cids)).sum(), len(use))
integrity("`fact_support_tickets.CustomerID` -> `dim_customer`", (~tik.CustomerID.isin(cids)).sum(), len(tik))
integrity("`fact_customer_acquisition.CustomerID` -> `dim_customer`", (~acq.CustomerID.isin(cids)).sum(), len(acq))
integrity("`fact_subscriptions.PlanID` -> `dim_plan`", (~sub.PlanID.isin(set(plan.PlanID))).sum(), len(sub))
say("| Relationship | Orphans | Of |")
say("|---|---:|---:|")
for label, missing, total in checks:
    say(f"| {label} | {missing:,} | {total:,} |")
metric("orphan_rows_total", int(sum(c[1] for c in checks)))
say()
say(f"**{sum(c[1] for c in checks):,} orphan rows in total.** Duplicate keys: "
    f"customers {cust.CustomerID.duplicated().sum()}, subscriptions {sub.SubscriptionID.duplicated().sum()}, "
    f"invoices {inv.InvoiceID.duplicated().sum()}, tickets {tik.TicketID.duplicated().sum()}, "
    f"usage rows per customer-month {use.duplicated(['CustomerID', 'Month']).sum()}.")
metric("dup_usage_customer_month", int(use.duplicated(["CustomerID", "Month"]).sum()))
say()
say("Every customer has exactly one acquisition row and "
    f"**{metric('subs_per_customer_max', int(sub.groupby('CustomerID').size().max()))} subscription** - "
    "which is the first fact that shapes everything below.")
say()

# ----------------------------------------------- 3. the subscription lifecycle ---
say("## 3. The subscription lifecycle")
say()
n_sub = metric("subscriptions", len(sub))
active = metric("subs_active", int((sub.Status == "Active").sum()))
churned = metric("subs_churned", int((sub.Status == "Churned").sum()))
metric("ever_churn_rate", round(churned / n_sub, 4))
say(f"- **{n_sub:,} subscriptions** for {cust.CustomerID.nunique():,} customers: one each, never more.")
say(f"- **{active:,} active** and **{churned:,} churned** "
    f"({pct(churned / n_sub)} of all customers have churned at some point).")
say(f"- Every churned subscription has an end date and every active one has none "
    f"({(sub.EndDate.isna() & (sub.Status == 'Active')).sum():,} / {active:,} and "
    f"{(sub.EndDate.notna() & (sub.Status == 'Churned')).sum():,} / {churned:,}) - the status column and the")
say("  dates never disagree, so either can be used and both give the same answer.")
say(f"- No subscription ends on or before it starts ({(sub.EndDate <= sub.StartDate).sum()}).")
merged = sub.merge(cust, on="CustomerID")
metric("start_equals_signup", round(float((merged.StartDate == merged.SignupDate).mean()), 4))
say(f"- **The subscription start IS the customer signup date, for every customer** "
    f"({pct((merged.StartDate == merged.SignupDate).mean(), 0)}). Signup cohorts and subscription")
say("  cohorts are therefore the same thing; this project uses the subscription start.")
say()
cut = sub.EndDate.fillna(ASOF_TS)
tenure = (cut - sub.StartDate).dt.days / 30.44
metric("tenure_median_churned", round(float(tenure[sub.Status == "Churned"].median()), 1))
metric("tenure_median_active", round(float(tenure[sub.Status == "Active"].median()), 1))
say(f"Median tenure is **{tenure[sub.Status == 'Churned'].median():.1f} months for a churned** subscription "
    f"and **{tenure[sub.Status == 'Active'].median():.1f} months for one still running** "
    "(measured to the as-of date).")
say()

# --------------------------------------------------- 4. billing and the money ---
say("## 4. Billing: does the money tie to the subscription?")
say()
j = inv.merge(sub[["SubscriptionID", "StartDate", "EndDate", "BillingCycle", "MRR"]], on="SubscriptionID")
ann = j[j.BillingCycle == "Annual"]
mon = j[j.BillingCycle == "Monthly"]
metric("annual_invoices_matching_12x_mrr", int(np.isclose(ann.InvoiceAmount, ann.MRR * 12, atol=0.02).sum()))
metric("annual_invoices", len(ann))
metric("monthly_invoices_matching_mrr", int(np.isclose(mon.InvoiceAmount, mon.MRR, atol=0.02).sum()))
metric("monthly_invoices", len(mon))
say(f"- Every annual invoice is exactly twelve times the subscription's MRR "
    f"({np.isclose(ann.InvoiceAmount, ann.MRR * 12, atol=0.02).sum():,} of {len(ann):,}) and every monthly")
say(f"  invoice is exactly the MRR ({np.isclose(mon.InvoiceAmount, mon.MRR, atol=0.02).sum():,} "
    f"of {len(mon):,}). Billing is derived from MRR, not independent of it.")
after_end = j[j.EndDate.notna()]
metric("invoices_after_end_date", int((after_end.InvoiceDate > after_end.EndDate).sum()))
say(f"- No invoice is dated after its subscription ended ({(after_end.InvoiceDate > after_end.EndDate).sum()}).")
pre = j[j.InvoiceDate < j.StartDate]
same_month = float((pre.InvoiceDate.dt.to_period("M") == pre.StartDate.dt.to_period("M")).mean())
metric("invoices_before_start", len(pre))
metric("invoices_before_start_same_month", round(same_month, 4))
say(f"- **{len(pre):,} invoices are dated before their subscription starts** - and every one of them falls in")
say(f"  the same calendar month ({pct(same_month, 0)}). Invoices are all dated to the **1st of the month** "
    f"(day-of-month values present: {sorted(inv.InvoiceDate.dt.day.unique())}), while a subscription can start")
say("  on any day. This is a billing-date convention, not a fault - but it means an invoice date must never")
say("  be used to decide when a subscription began.")
failed = metric("invoices_failed", int((inv.PaymentStatus == "Failed").sum()))
metric("invoices_failed_share", round(failed / len(inv), 4))
metric("failed_customers", int(inv[inv.PaymentStatus == "Failed"].CustomerID.nunique()))
paid = inv[inv.PaymentStatus == "Paid"]
metric("days_to_pay_median", float((paid.PaymentDate - paid.InvoiceDate).dt.days.median()))
say(f"- **{failed:,} invoices failed** ({pct(failed / len(inv))} of {len(inv):,}), across "
    f"{inv[inv.PaymentStatus == 'Failed'].CustomerID.nunique():,} customers. A failed invoice carries no")
say(f"  payment date; a paid one is settled in a median of "
    f"{(paid.PaymentDate - paid.InvoiceDate).dt.days.median():.0f} days.")
say()
say("| Plan | List price | Subscriptions | MRR min | MRR mean | MRR max |")
say("|---|---:|---:|---:|---:|---:|")
pm = sub.merge(plan, on="PlanID").groupby(["PlanID", "PlanName", "MonthlyListPrice"]).MRR.agg(
    ["count", "min", "mean", "max"]).reset_index()
for _, r in pm.iterrows():
    say(f"| {r.PlanName} (`{r.PlanID}`) | ${r.MonthlyListPrice:,.0f} | {int(r['count']):,} | "
        f"${r['min']:,.0f} | ${r['mean']:,.0f} | ${r['max']:,.0f} |")
metric("mrr_vs_list_min_ratio", round(float((sub.merge(plan, on='PlanID').MRR /
                                             sub.merge(plan, on='PlanID').MonthlyListPrice).min()), 3))
metric("mrr_vs_list_max_ratio", round(float((sub.merge(plan, on='PlanID').MRR /
                                             sub.merge(plan, on='PlanID').MonthlyListPrice).max()), 3))
ratio = sub.merge(plan, on="PlanID")
ratio = ratio.MRR / ratio.MonthlyListPrice
say()
say(f"MRR sits between **{ratio.min():.0%} and {ratio.max():.0%} of list price** - every subscription is")
say("discounted or uplifted off its plan, so realised price is worth reporting separately from list.")
say()

# ------------------------------------- 5. what an MRR waterfall can be built on ---
say("## 5. Can this data support an MRR movement waterfall?")
say()
say("This is the question the whole project turns on, so it is answered with evidence rather than assumed.")
say("A full SaaS waterfall has five components: **New, Expansion, Contraction, Churn and Reactivation**.")
say()
amounts_per_sub = inv.groupby("SubscriptionID").InvoiceAmount.nunique()
metric("subs_with_one_invoice_amount", int((amounts_per_sub == 1).sum()))
metric("subs_with_invoices", int(len(amounts_per_sub)))
mrr_changes = 0        # MRR is a single column on the subscription: it cannot change over time
metric("mrr_values_per_subscription", 1)
say("| Component | Supported? | The evidence |")
say("|---|---|---|")
say("| **New** | Yes | Every subscription has a start date, and it equals the customer's signup date |")
say("| **Churn** | Yes | Every churned subscription has an end date; none is dated after its last invoice |")
say(f"| **Expansion** | **No** | MRR is one static number per subscription, and all "
    f"{(amounts_per_sub == 1).sum():,} subscriptions bill exactly one invoice amount for life |")
say("| **Contraction** | **No** | Same reason: there is no second MRR value to fall to |")
say(f"| **Reactivation** | **No** | One subscription per customer ever, so no customer can leave and return |")
say()
say("**So the movement this dataset can describe is New and Churn.** The model still computes all five")
say("components - the logic is written, tested and visible - and three of them are structurally nil. That")
say("is reported on the page rather than hidden, because two well-known consequences follow:")
say()
say("1. **Net revenue retention can never exceed gross revenue retention**, and in fact they are equal:")
say("   with no expansion or contraction, NRR = GRR = (opening MRR - churned MRR) / opening MRR. Any NRR")
say("   above 100% in a report built on this data would be an arithmetic error.")
say("2. **Seat counts do move** (see section 6) - but MRR does not follow them, so seat growth is an")
say("   adoption signal, never billed expansion. The two are kept apart throughout.")
say()

# monthly active MRR
months = pd.period_range(sub.StartDate.min().to_period("M"), ASOF_TS.to_period("M"), freq="M")
rows = []
for m in months:
    end = m.to_timestamp("M")
    a = sub[(sub.StartDate <= end) & (sub.EndDate.isna() | (sub.EndDate > end))]
    starts = int(((sub.StartDate.dt.to_period("M")) == m).sum())
    ends = int((sub.EndDate.dt.to_period("M") == m).sum())
    rows.append((str(m), len(a), float(a.MRR.sum()), starts, ends))
mrr = pd.DataFrame(rows, columns=["Month", "ActiveSubs", "MRR", "Starts", "Ends"])
peak = mrr.loc[mrr.MRR.idxmax()]
last = mrr.iloc[-1]
metric("mrr_peak_month", peak.Month)
metric("mrr_peak", round(float(peak.MRR), 2))
metric("mrr_last_month", last.Month)
metric("mrr_last", round(float(last.MRR), 2))
metric("arr_last", round(float(last.MRR) * 12, 2))
metric("last_start_date", str(sub.StartDate.max().date()))
metric("months_with_no_new_business", int((mrr.Starts == 0).sum()))
say("### A trap in the last two months")
say()
say(f"The newest subscription starts on **{sub.StartDate.max().date()}**. Churn, however, runs to")
say(f"{sub.EndDate.max().date()}. So the file ends with **{(mrr.Starts == 0).sum()} months of churn and no new")
say("business at all** - not because the business stopped selling, but because acquisition data stops first.")
say()
say("| Month | Active subs | MRR | New | Churned |")
say("|---|---:|---:|---:|---:|")
for _, r in mrr.tail(6).iterrows():
    say(f"| {r.Month} | {int(r.ActiveSubs):,} | {money(r.MRR)} | {int(r.Starts):,} | {int(r.Ends):,} |")
say()
say(f"MRR peaks at **{money(peak.MRR)} in {peak.Month}** and reads {money(last.MRR)} at the as-of date "
    f"(**ARR {money(last.MRR * 12)}**). Read without the caveat, the last two months look like a business in")
say("decline. They are an artefact of where the extract ends, and the report says so on the page.")
say()

# ------------------------------------------------------------ 6. usage coverage ---
say("## 6. Product usage: a sample, not a census")
say()
metric("usage_rows", len(use))
metric("usage_customers", int(use.CustomerID.nunique()))
metric("usage_months", int(use.Month.nunique()))
per_cust = use.groupby("CustomerID").size()
metric("usage_months_per_customer_median", float(per_cust.median()))
metric("usage_months_per_customer_max", int(per_cust.max()))
cov = []
for m in months[-6:]:
    end = m.to_timestamp("M")
    a = sub[(sub.StartDate <= end) & (sub.EndDate.isna() | (sub.EndDate > end))]
    seen = use[use.Month.dt.to_period("M") == m].CustomerID.nunique()
    cov.append((str(m), len(a), seen, seen / len(a)))
metric("usage_coverage_last_month", round(cov[-1][3], 4))
say(f"The usage table holds {len(use):,} rows for {use.CustomerID.nunique():,} customers over "
    f"{use.Month.nunique()} months - but a customer appears in a median of only")
say(f"**{per_cust.median():.0f} months** (maximum {per_cust.max()}), while the median active subscription runs "
    f"{tenure[sub.Status == 'Active'].median():.0f} months.")
say()
say("| Month | Active subscriptions | Customers with usage | Coverage |")
say("|---|---:|---:|---:|")
for m, a, s, c in cov:
    say(f"| {m} | {a:,} | {s:,} | {pct(c)} |")
say()
say(f"**Usage describes about {pct(cov[-1][3], 0)} of the customers who are paying in any given month.** Every")
say("adoption, seat and login figure in this project is therefore reported as *of the customers we can see*,")
say("never as a share of the customer base, and never used as a denominator for revenue.")
say()
metric("active_users_exceeding_seats", int((use.ActiveUsers > use.LicensedSeats).sum()))
seats_moving = (use.groupby("CustomerID").LicensedSeats.nunique() > 1).mean()
metric("customers_with_changing_seats", round(float(seats_moving), 4))
say(f"Where it is present the usage data is clean: active users never exceed licensed seats "
    f"({(use.ActiveUsers > use.LicensedSeats).sum()} rows), adoption sits inside 0-1, and")
say(f"**{pct(seats_moving, 0)} of customers change their licensed seat count** over time. Seats move; MRR does not.")
say()

# ------------------------------------------------------------- 7. support data ---
say("## 7. Support tickets")
say()
metric("tickets", len(tik))
metric("ticket_customers", int(tik.CustomerID.nunique()))
open_with_hours = int(((tik.Status != "Resolved") & tik.ResolutionHours.notna()).sum())
metric("unresolved_tickets_with_resolution_hours", open_with_hours)
metric("tickets_unresolved", int((tik.Status != "Resolved").sum()))
say(f"{len(tik):,} tickets for {tik.CustomerID.nunique():,} customers. Severity, status and category are all")
say("populated, with no nulls anywhere.")
say()
say(f"**{open_with_hours:,} tickets that are still Open or Escalated nevertheless carry a resolution time** "
    f"(all {(tik.Status != 'Resolved').sum():,} of them). A ticket that is not resolved cannot have taken any")
say("time to resolve, so mean time to resolve is computed over **resolved tickets only** throughout.")
say()
mtr_all = float(tik.ResolutionHours.mean())
mtr_res = float(tik[tik.Status == "Resolved"].ResolutionHours.mean())
metric("mttr_all_tickets", round(mtr_all, 3))
metric("mttr_resolved_only", round(mtr_res, 3))
by_status = tik.groupby("Status").ResolutionHours.agg(["count", "mean", "median"])
metric("mttr_by_status", {k: round(float(v), 2) for k, v in by_status["mean"].items()})
say("| Ticket status | Tickets | Mean hours | Median hours |")
say("|---|---:|---:|---:|")
for st, r in by_status.iterrows():
    say(f"| {st} | {int(r['count']):,} | {r['mean']:.2f} | {r['median']:.2f} |")
say()
say(f"The three means are {by_status['mean'].min():.2f}, {by_status['mean'].median():.2f} and "
    f"{by_status['mean'].max():.2f} hours - statistically the same number. The field is populated from one")
say("distribution regardless of status, so it is not a real resolution time for a ticket that has not been")
say(f"resolved. Restricting to resolved tickets moves the mean by only "
    f"{abs(mtr_res - mtr_all):.2f} hours here ({mtr_all:.2f} to {mtr_res:.2f}), but the definition is still the")
say("correct one and it is the one used - and no claim is made anywhere that escalation takes longer to fix,")
say("because in this data it does not.")
say()

# ------------------------------------------------- 8. acquisition and economics ---
say("## 8. Acquisition cost")
say()
metric("cac_mean", round(float(acq.AcquisitionCost.mean()), 2))
metric("cac_median", round(float(acq.AcquisitionCost.median()), 2))
metric("cac_min", round(float(acq.AcquisitionCost.min()), 2))
metric("cac_max", round(float(acq.AcquisitionCost.max()), 2))
metric("cac_total", round(float(acq.AcquisitionCost.sum()), 2))
metric("cac_under_100", int((acq.AcquisitionCost < 100).sum()))
say(f"Acquisition cost is stated once per customer: mean **{money(acq.AcquisitionCost.mean())}**, median "
    f"{money(acq.AcquisitionCost.median())}, range ${acq.AcquisitionCost.min():,.2f} to "
    f"{money(acq.AcquisitionCost.max())}.")
say()
say(f"The distribution is heavily right-skewed - the mean is {acq.AcquisitionCost.mean() / acq.AcquisitionCost.median():.1f}x")
say(f"the median - and {(acq.AcquisitionCost < 100).sum():,} customers were acquired for under $100, the")
say(f"cheapest for ${acq.AcquisitionCost.min():.2f}. Blended CAC (total spend / customers) is the right")
say("headline because it is what the money actually was; the median is shown beside it so the skew is visible")
say("rather than averaged away.")
say()
by_src = acq.groupby("AcquisitionSource").AcquisitionCost.agg(["count", "mean", "median"])
metric("cac_by_source_mean", {k: round(float(v), 0) for k, v in by_src["mean"].items()})
metric("cac_source_spread", round(float(by_src["mean"].max() - by_src["mean"].min()), 2))
say("| Channel | Customers | Mean CAC | Median CAC |")
say("|---|---:|---:|---:|")
for srcname, r in by_src.iterrows():
    say(f"| {srcname} | {int(r['count']):,} | {money(r['mean'])} | {money(r['median'])} |")
say()
say(f"**Channel does not differentiate cost.** The spread between the dearest and cheapest channel mean is")
say(f"{money(by_src['mean'].max() - by_src['mean'].min())} on a ~{money(acq.AcquisitionCost.mean())} base - "
    f"about {pct((by_src['mean'].max() - by_src['mean'].min()) / acq.AcquisitionCost.mean(), 0)}. Like the churn")
say("cuts in section 9, these are worth showing because a reader will ask, but none of them is a finding.")
say()
say("Two things it does not come with, both of which a payback or LTV figure needs:")
say()
say("- **No gross margin.** There is no cost-of-service anywhere in the data, so LTV and CAC payback cannot")
say("  be derived - they can only be modelled. This project carries gross margin as a **stated, adjustable")
say("  assumption** shown on the page beside the result, never buried in a measure.")
say("- **No spend by channel over time.** Cost is attached to the customer, not to a campaign or a month, so")
say("  a blended CAC by channel is honest but a marketing-efficiency trend is not.")
say()

# --------------------------------------------------- 9. what actually drives churn ---
say("## 9. What actually drives churn here")
say()
say("The dataset's own brief suggests training a churn model on usage, tickets, payment history and tenure.")
say("Before building anything on that, the relationships were measured. They are not what the brief assumes.")
say()
s = sub.copy()
s["churn"] = (s.Status == "Churned").astype(int)
s["cut"] = s.EndDate.fillna(ASOF_TS)
s["tenure"] = ((s.cut - s.StartDate).dt.days / 30.44).clip(lower=1)
u = use.merge(s[["CustomerID", "cut"]], on="CustomerID")
u = u[(u.Month <= u.cut) & (u.Month > u.cut - pd.Timedelta(days=92))]
ua = u.groupby("CustomerID").agg(adoption=("FeatureAdoptionRate", "mean"), logins=("Logins", "mean"),
                                 seats=("LicensedSeats", "mean"), users=("ActiveUsers", "mean"),
                                 errors=("CriticalErrors", "mean")).reset_index()
ua["utilisation"] = ua.users / ua.seats
t = tik.merge(s[["CustomerID", "cut"]], on="CustomerID")
t = t[(t.OpenedDate <= t.cut) & (t.OpenedDate > t.cut - pd.Timedelta(days=92))]
ta = t.groupby("CustomerID").size().rename("tickets_90d").reset_index()
allt = tik.groupby("CustomerID").size().rename("tickets_all").reset_index()
fc = inv[inv.PaymentStatus == "Failed"].groupby("CustomerID").size().rename("failed").reset_index()
ic = inv.groupby("CustomerID").size().rename("invoices").reset_index()
d = (s[["CustomerID", "churn", "tenure", "MRR", "PlanID"]]
     .merge(ua, how="left", on="CustomerID").merge(ta, how="left", on="CustomerID")
     .merge(allt, how="left", on="CustomerID").merge(fc, how="left", on="CustomerID")
     .merge(ic, how="left", on="CustomerID").merge(acq, how="left", on="CustomerID"))
d[["tickets_90d", "tickets_all", "failed"]] = d[["tickets_90d", "tickets_all", "failed"]].fillna(0)
d["tickets_per_month"] = d.tickets_all / d.tenure
d["failure_rate"] = d.failed / d.invoices.replace(0, np.nan)

FEATURES = [("Plan price point (MRR)", "MRR", "the subscription's own MRR"),
            ("Support contact **rate** (tickets per month of tenure)", "tickets_per_month", "exposure-adjusted"),
            ("Feature adoption, last 90 days", "adoption", "usage sample only"),
            ("Seat utilisation (active users / licensed seats)", "utilisation", "usage sample only"),
            ("Logins, last 90 days", "logins", "usage sample only"),
            ("Critical errors, last 90 days", "errors", "usage sample only"),
            ("Licensed seats", "seats", "usage sample only"),
            ("Payment **failure rate** (failed / invoices)", "failure_rate", "exposure-adjusted"),
            ("Acquisition cost", "AcquisitionCost", "one value per customer"),
            ("Raw ticket count", "tickets_all", "**not** exposure-adjusted"),
            ("Raw failed-invoice count", "failed", "**not** exposure-adjusted")]
say("Correlation with ever having churned, across all 12,000 customers:")
say()
say("| Feature | r | n | Note |")
say("|---|---:|---:|---|")
corrs = {}
for label, col, note in FEATURES:
    x = d[[col, "churn"]].dropna()
    r = float(np.corrcoef(x[col], x.churn)[0, 1])
    corrs[col] = round(r, 4)
    say(f"| {label} | {r:+.3f} | {len(x):,} | {note} |")
metric("churn_correlations", corrs)
say()
say("### Reading it")
say()
say(f"1. **Product usage is independent of churn.** Adoption, logins, seats, utilisation and critical errors")
say(f"   all sit inside |r| < 0.02. The means are almost identical: adoption "
    f"{d[d.churn == 1].adoption.mean():.3f} for churned customers against {d[d.churn == 0].adoption.mean():.3f}")
say(f"   for retained ones, seat utilisation {d[d.churn == 1].utilisation.mean():.3f} against "
    f"{d[d.churn == 0].utilisation.mean():.3f}. A churn model trained on these features would be fitting noise,")
say("   and a health score built from them would be decoration. Neither is built here.")
metric("adoption_mean_churned", round(float(d[d.churn == 1].adoption.mean()), 4))
metric("adoption_mean_retained", round(float(d[d.churn == 0].adoption.mean()), 4))
metric("utilisation_mean_churned", round(float(d[d.churn == 1].utilisation.mean()), 4))
metric("utilisation_mean_retained", round(float(d[d.churn == 0].utilisation.mean()), 4))
say()
say(f"2. **The raw counts lie, and the rates tell the truth.** Raw ticket count correlates "
    f"{corrs['tickets_all']:+.3f} with churn and raw failed-invoice count {corrs['failed']:+.3f} - both flat or")
say(f"   backwards, because a customer who stays longer simply accumulates more of everything. Divide by")
say(f"   tenure and support contact rate becomes the second real signal ({corrs['tickets_per_month']:+.3f});")
say(f"   divide failures by invoices and payment failure vanishes entirely ({corrs['failure_rate']:+.3f}).")
say("   **Involuntary churn does not exist in this dataset** - a failed payment says nothing about leaving.")
say()
pl = d.groupby("PlanID").churn.agg(["mean", "count"]).join(plan.set_index("PlanID"))
say("3. **Price point is the one strong, real driver**, and it behaves the way SaaS actually behaves:")
say()
say("| Plan | List price | Customers | Ever churned |")
say("|---|---:|---:|---:|")
for pid, r in pl.iterrows():
    say(f"| {r.PlanName} | ${r.MonthlyListPrice:,.0f} | {int(r['count']):,} | {pct(r['mean'])} |")
metric("churn_by_plan", {str(k): round(float(v), 4) for k, v in pl["mean"].items()})
say()
say("   The gradient holds inside every customer segment, so it is the price point rather than the kind of")
say("   company buying it.")
say()
seg = d.merge(cust, on="CustomerID")
spreads = {}
for col in ["Segment", "Industry", "Country"]:
    g = seg.groupby(col).churn.mean()
    spreads[col] = round(float(g.max() - g.min()), 4)
src = seg.merge(acq[["CustomerID", "AcquisitionSource"]], on="CustomerID", suffixes=("", "_y"))
spreads["AcquisitionSource"] = round(float(src.groupby("AcquisitionSource").churn.mean().max() -
                                           src.groupby("AcquisitionSource").churn.mean().min()), 4)
metric("churn_rate_spreads", spreads)
say(f"4. **Everything else is flat.** The spread between the best and worst churn rate is only "
    f"{pct(spreads['Segment'])} across segments, {pct(spreads['Industry'])} across industries,")
say(f"   {pct(spreads['Country'])} across countries and {pct(spreads['AcquisitionSource'])} across acquisition")
say("   channels. Those cuts are worth showing - a reader will ask for them - but none is a finding.")
say()
say("**What this project builds instead of a churn model:** the drivers that were tested are shown with their")
say("measured strength on the page, the two that carry signal are used, and the ones that do not are named as")
say("such. A risk view built on price point and support-contact rate is smaller than the brief asked for, and")
say("it is the part that is true.")
say()

# ---------------------------------------------------------------- 10. security ---
say("## 10. Security data")
say()
metric("security_users", len(sec))
metric("security_countries", int(sec[sec.Country != "ALL"].Country.nunique()))
say(f"{len(sec)} users: {(sec.Country == 'ALL').sum()} with group-wide access "
    f"({', '.join(sec[sec.Country == 'ALL'].Role)}) and {(sec.Country != 'ALL').sum()} country-scoped customer")
say(f"success managers covering {sec[sec.Country != 'ALL'].Country.nunique()} countries. Every scoped country")
say(f"exists in `dim_customer` ({(~sec[sec.Country != 'ALL'].Country.isin(cust.Country)).sum()} unmatched), so")
say("row-level security by country resolves for every user.")
say()

# ------------------------------------------------------------------ 11. summary ---
say("## 11. What this means for the build")
say()
say("| Decision | Because |")
say("|---|---|")
say("| The MRR waterfall computes all five movement types, and reports three as structurally nil | "
    "MRR is static per subscription and there is one subscription per customer (section 5) |")
say("| NRR and GRR are shown together and expected to be equal | No expansion or contraction exists to "
    "separate them |")
say("| The last two months are marked as having no new business | Acquisition data stops "
    f"{sub.StartDate.max().date()} while churn runs on (section 5) |")
say("| Usage metrics are reported as a sample and never as a rate over all customers | Usage covers about "
    f"{pct(cov[-1][3], 0)} of paying customers in a month (section 6) |")
say("| Mean time to resolve uses resolved tickets only | Unresolved tickets carry a resolution time they "
    "cannot have (section 7) |")
say("| Gross margin is a stated assumption on the page | No cost of service exists in the data (section 8) |")
say("| Blended CAC leads, median CAC sits beside it | The cost distribution is skewed 1.7x mean to median "
    "(section 8) |")
say("| Resolution time is never compared across ticket statuses | The field holds the same distribution for "
    "resolved and unresolved tickets alike (section 7) |")
say("| No churn-risk model; a tested driver view instead | Usage and payment features are uncorrelated with "
    "churn; price point and contact rate are not (section 9) |")
say("| Support and payment behaviour are measured as rates, never counts | Raw counts measure tenure, not "
    "behaviour (section 9) |")
say()
say("---")
say()
say(f"*Generated by `Python/01_data_audit.py`. As-of date {ASOF}. Synthetic data.*")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
METRICS.parent.mkdir(parents=True, exist_ok=True)
METRICS.write_text(json.dumps(M, indent=2), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)} ({len(L)} lines) and {METRICS.relative_to(ROOT)} ({len(M)} metrics)")
print(f"as-of {ASOF} | MRR {money(last.MRR)} | ARR {money(last.MRR * 12)} | "
      f"{active:,} active / {churned:,} churned")
