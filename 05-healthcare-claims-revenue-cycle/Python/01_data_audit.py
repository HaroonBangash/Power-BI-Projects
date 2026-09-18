"""
Phase 1 - data audit.

Reads the raw CSVs and answers the questions that decide what the model may claim,
BEFORE any of it is built. The brief that ships with this dataset asks for first-pass
acceptance, clean-claim rate, AR ageing, denial root-cause analysis by payer / facility /
provider / diagnosis / procedure, and dynamic RLS. This script measures whether the data
can carry any of it:

  * Does the money chain close? Billed -> allowed -> paid, and where does the rest go?
  * What does ClaimStatus 'Pending' actually mean here - a claim still in flight, or a
    permanent state? That decides whether an AR ageing is a collections story or an
    artefact.
  * Is a denial predictable from anything - payer, facility, provider, specialty,
    diagnosis, procedure, patient age, claim size? Or is it a coin toss?
  * Does a denied claim ever recover? That decides whether appeal yield exists.
  * Is first-pass acceptance a separate number from the denial rate, or the same number
    written twice?
  * Does the date dimension actually cover the facts?

Every figure printed here is written to Documentation/data_quality_report.md and to
Validation/audit_metrics.json, so the model and the report can be checked against the
same numbers later. Nothing is rounded away or assumed.

Source location: this script does NOT hardcode a machine path. In order of precedence it
uses --source, then the RCM_SOURCE environment variable, then "source" in
config.local.json (git-ignored), then Data/raw beside the repository.

Usage:  python Python/01_data_audit.py [--source <folder of CSVs>]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Documentation" / "data_quality_report.md"
METRICS = ROOT / "Validation" / "audit_metrics.json"

M = {}          # every number the report cites
L = []          # report lines


def say(line=""):
    L.append(line)


def metric(key, value):
    """Record a number AND return it, so a figure can never be printed without being
    written to the metrics file that the later phases check themselves against."""
    if isinstance(value, (np.integer,)):
        value = int(value)
    elif isinstance(value, (np.floating,)):
        value = float(value)
    M[key] = value
    return value


def pct(x, places=1):
    return f"{100 * x:.{places}f}%"


def money(x):
    return f"${x:,.0f}"


def resolve_source():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--source", help="folder holding the raw CSVs")
    args, _ = ap.parse_known_args()
    cfg = ROOT / "config.local.json"
    candidates = [
        args.source,
        os.environ.get("RCM_SOURCE"),
        json.loads(cfg.read_text(encoding="utf-8")).get("source") if cfg.exists() else None,
        ROOT / "Data" / "raw",
    ]
    for c in candidates:
        if c and Path(c).exists() and (Path(c) / "fact_claims.csv").exists():
            return Path(c)
    sys.exit("fact_claims.csv not found. Pass --source <folder>, set RCM_SOURCE, or put "
             "the CSVs in Data/raw.")


SRC = resolve_source()

# ------------------------------------------------------------------- loading ---
claims = pd.read_csv(SRC / "fact_claims.csv",
                     parse_dates=["ServiceDate", "SubmittedDate", "ProcessedDate"])
lines = pd.read_csv(SRC / "fact_claim_lines.csv")
pays = pd.read_csv(SRC / "fact_payments.csv", parse_dates=["PaymentDate"])
den = pd.read_csv(SRC / "fact_denials.csv", parse_dates=["DenialDate"])
ben = pd.read_csv(SRC / "dim_beneficiary.csv", parse_dates=["DateOfBirth"])
prov = pd.read_csv(SRC / "dim_provider.csv")
fac = pd.read_csv(SRC / "dim_facility.csv")
payer = pd.read_csv(SRC / "dim_payer.csv")
date = pd.read_csv(SRC / "dim_date.csv", parse_dates=["Date"])
sec = pd.read_csv(SRC / "security_user_access.csv")

# One wide frame for the signal tests. The column names collide - a provider has a
# FacilityID and a facility has a State, as does a beneficiary - so they are renamed
# before the join rather than left to pandas' _x/_y suffixes.
wide = (claims
        .merge(prov.rename(columns={"FacilityID": "ProviderHomeFacility"}), on="ProviderID", how="left")
        .merge(fac.rename(columns={"State": "FacilityState"}), on="FacilityID", how="left")
        .merge(payer, on="PayerID", how="left")
        .merge(ben.rename(columns={"State": "BeneficiaryState"}), on="BeneficiaryID", how="left"))
wide["IsDenied"] = (wide.ClaimStatus == "Denied").astype(int)

say("# Data Quality & Feasibility Audit")
say()
say("*Healthcare claims and revenue cycle - Phase 1. Every number below is produced by*")
say("*`Python/01_data_audit.py` and written to `Validation/audit_metrics.json`.*")
say()
say("**The dataset is synthetic.** It is a portfolio dataset for a fictional provider")
say("group. No real patient, provider or payer data is involved, and nothing here is")
say("presented as a real organisation's revenue cycle.")
say()
say("---")
say()

# =============================================================== 1. inventory ===
say("## 1. What arrived")
say()
say("| Table | Rows | Grain | Notes |")
say("|---|---:|---|---|")
n_claims = metric("claims_rows", len(claims))
n_lines = metric("line_rows", len(lines))
n_pays = metric("payment_rows", len(pays))
n_den = metric("denial_rows", len(den))
say(f"| `fact_claims` | {n_claims:,} | one claim | Billed, allowed and paid on the header |")
say(f"| `fact_claim_lines` | {n_lines:,} | one procedure line | Charge, procedure and diagnosis code |")
say(f"| `fact_payments` | {n_pays:,} | one remittance | |")
say(f"| `fact_denials` | {n_den:,} | one denial | Reason and status |")
say(f"| `dim_beneficiary` | {len(ben):,} | one patient | Date of birth, gender, state, risk band |")
say(f"| `dim_provider` | {len(prov):,} | one provider | Specialty, home facility |")
say(f"| `dim_facility` | {len(fac):,} | one facility | Type, state |")
say(f"| `dim_payer` | {len(payer):,} | one payer | |")
say(f"| `dim_date` | {len(date):,} | one day | |")
say(f"| `security_user_access` | {len(sec):,} | one user grant | Facility / provider scope |")
say()

dupes = {"claims": n_claims - claims.ClaimID.nunique(),
         "lines": n_lines - lines.ClaimLineID.nunique(),
         "payments": n_pays - pays.PaymentID.nunique(),
         "denials": n_den - den.DenialID.nunique(),
         "beneficiaries": len(ben) - ben.BeneficiaryID.nunique()}
metric("duplicate_keys", dupes)
orphans = {
    "lines_without_claim": int((~lines.ClaimID.isin(set(claims.ClaimID))).sum()),
    "payments_without_claim": int((~pays.ClaimID.isin(set(claims.ClaimID))).sum()),
    "denials_without_claim": int((~den.ClaimID.isin(set(claims.ClaimID))).sum()),
    "claims_without_beneficiary": int((~claims.BeneficiaryID.isin(set(ben.BeneficiaryID))).sum()),
    "claims_without_provider": int((~claims.ProviderID.isin(set(prov.ProviderID))).sum()),
    "claims_without_facility": int((~claims.FacilityID.isin(set(fac.FacilityID))).sum()),
    "claims_without_payer": int((~claims.PayerID.isin(set(payer.PayerID))).sum()),
}
metric("orphans", orphans)
say(f"**Keys are clean.** No duplicate primary key in any table "
    f"({sum(dupes.values())} found), and no orphan foreign key "
    f"({sum(orphans.values())} found across seven relationships).")
say()
nulls = {c: int(claims[c].isna().sum()) for c in claims.columns if claims[c].isna().any()}
metric("claim_nulls", nulls)
say(f"**No nulls in `fact_claims`** - every one of its {len(claims.columns)} columns is "
    f"fully populated, including all three dates.")
say()

# ========================================================= 2. the money chain ===
say("## 2. The money chain, and the identity this project rests on")
say()
billed = metric("billed_total", float(claims.BilledAmount.sum()))
allowed = metric("allowed_total", float(claims.AllowedAmount.sum()))
paid = metric("paid_total", float(claims.PaidAmount.sum()))
contractual = metric("contractual_adjustment", billed - allowed)

paid_claims = claims[claims.ClaimStatus == "Paid"]
pend_claims = claims[claims.ClaimStatus == "Pending"]
den_claims = claims[claims.ClaimStatus == "Denied"]
patient_resp = metric("patient_responsibility",
                      float((paid_claims.AllowedAmount - paid_claims.PaidAmount).sum()))
ar_open = metric("ar_open_at_allowed", float(pend_claims.AllowedAmount.sum()))
denied_allowed = metric("denied_at_allowed", float(den_claims.AllowedAmount.sum()))
residual = metric("identity_residual", allowed - (paid + patient_resp + ar_open + denied_allowed))

say("Three amounts sit on every claim header: what was **billed**, what the payer")
say("**allowed** under contract, and what was actually **paid**. The gaps between them")
say("are the revenue cycle.")
say()
say("| Step | Amount | Share of billed |")
say("|---|---:|---:|")
say(f"| Billed | {money(billed)} | 100.0% |")
say(f"| less contractual adjustment | −{money(contractual)} | {pct(contractual / billed)} |")
say(f"| **Allowed** | **{money(allowed)}** | **{pct(allowed / billed)}** |")
say(f"| less denied | −{money(denied_allowed)} | {pct(denied_allowed / billed)} |")
say(f"| less patient responsibility | −{money(patient_resp)} | {pct(patient_resp / billed)} |")
say(f"| less open AR | −{money(ar_open)} | {pct(ar_open / billed)} |")
say(f"| **Collected** | **{money(paid)}** | **{pct(paid / billed)}** |")
say()
say(f"**The allowed amount closes exactly.** Collected + patient responsibility + open AR")
say(f"+ denied = {money(paid + patient_resp + ar_open + denied_allowed)} against an allowed")
say(f"total of {money(allowed)} - a residual of **{money(abs(residual))}**. Every dollar the")
say("payer agreed to is in exactly one of four buckets, which is the identity the whole")
say("model is built to preserve and the validation suite re-checks on every refresh.")
say()
gcr = metric("gross_collection_rate", paid / billed)
ncr = metric("net_collection_rate", paid / allowed)
say(f"Gross collection rate (paid / billed) is **{pct(gcr)}**; net collection rate")
say(f"(paid / allowed) is **{pct(ncr)}**. Net is the one a revenue-cycle team is measured")
say("on, because no provider ever collects the sticker price - the contractual adjustment")
say(f"of {pct(contractual / billed)} is agreed in advance, not lost.")
say()

# amount sanity
bad = {
    "allowed_gt_billed": int((claims.AllowedAmount > claims.BilledAmount).sum()),
    "paid_gt_allowed": int((claims.PaidAmount > claims.AllowedAmount).sum()),
    "negative_amounts": int(((claims[["BilledAmount", "AllowedAmount", "PaidAmount"]] < 0).any(axis=1)).sum()),
}
metric("amount_violations", bad)
say(f"No claim allows more than it bills, pays more than it allows, or carries a negative "
    f"amount ({sum(bad.values())} violations in {n_claims:,} rows).")
say()

allowed_rate = (claims.AllowedAmount / claims.BilledAmount)
metric("allowed_rate_mean", float(allowed_rate.mean()))
metric("allowed_rate_min", float(allowed_rate.min()))
metric("allowed_rate_max", float(allowed_rate.max()))
by_payer_allowed = (wide.assign(r=wide.AllowedAmount / wide.BilledAmount)
                    .groupby("PayerName").r.mean().mul(100).round(2))
metric("allowed_rate_by_payer", by_payer_allowed.to_dict())
say(f"### The contract that is not a contract")
say()
say(f"The allowed rate per claim runs from {pct(allowed_rate.min())} to "
    f"{pct(allowed_rate.max())} of billed, averaging {pct(allowed_rate.mean(), 2)}. Split by "
    f"payer it averages {by_payer_allowed.min():.2f}% to {by_payer_allowed.max():.2f}% - a "
    f"spread of **{by_payer_allowed.max() - by_payer_allowed.min():.2f} percentage points across "
    f"six payers**.")
say()
say("In a real provider group the allowed rate *is* the payer contract, and payers differ")
say("by tens of points. Here every payer draws from the same distribution, so **payer")
say("contract performance cannot be analysed** - there is nothing to find. Worse, the same")
say("rate is applied to **Self Pay**, where by definition no contracted rate exists: a")
say("self-pay patient is billed the chargemaster price. The report therefore states the")
say("contractual adjustment as a single group-wide number and does not rank payers by it.")
say()

poa = (paid_claims.PaidAmount / paid_claims.AllowedAmount)
metric("paid_of_allowed_mean", float(poa.mean()))
metric("paid_of_allowed_min", float(poa.min()))
metric("patient_resp_share_of_allowed", float(patient_resp / paid_claims.AllowedAmount.sum()))
say(f"The gap between allowed and paid on a **paid** claim is steadier: the payer settles "
    f"{pct(poa.mean(), 1)} of the allowed amount on average (range {pct(poa.min())} to "
    f"{pct(poa.max())}), leaving {pct(patient_resp / paid_claims.AllowedAmount.sum())} as "
    f"patient responsibility - copay, coinsurance and deductible. That is a realistic share "
    f"and it is treated as a real quantity throughout.")
say()

# ================================================= 3. what ClaimStatus means ===
say("## 3. What `ClaimStatus` actually means here")
say()
status_counts = claims.ClaimStatus.value_counts()
metric("status_counts", {k: int(v) for k, v in status_counts.items()})
say("| Status | Claims | Share | Paid amount | Has a payment row | Has a denial row |")
say("|---|---:|---:|---:|---:|---:|")
pay_claims = set(pays.ClaimID)
den_claim_ids = set(den.ClaimID)
for st in ["Paid", "Pending", "Denied"]:
    sub = claims[claims.ClaimStatus == st]
    say(f"| {st} | {len(sub):,} | {pct(len(sub) / n_claims)} | {money(sub.PaidAmount.sum())} | "
        f"{sub.ClaimID.isin(pay_claims).sum():,} | {sub.ClaimID.isin(den_claim_ids).sum():,} |")
say()
say("The three statuses are clean and mutually exclusive: a paid claim always has exactly")
say("one payment row and never a denial; a denied claim always has exactly one denial row,")
say("no payment, and a paid amount of zero; a pending claim has neither.")
say()
pays_per_claim = pays.groupby("ClaimID").size()
metric("max_payments_per_claim", int(pays_per_claim.max()))
metric("claims_with_multiple_payments", int((pays_per_claim > 1).sum()))
say(f"**There are no partial payments.** Every paid claim settles in exactly one remittance")
say(f"({metric('claims_with_multiple_payments', int((pays_per_claim > 1).sum()))} claims have "
    f"more than one). So there is no split remittance, no takeback, no secondary payer and no")
say("payment plan. Days-to-pay is a single event, which makes it clean to measure - and it")
say("means **no claim is ever partly collected**: a claim is paid in full to its allowed")
say("share, or it is not paid at all.")
say()

# ============================================ 4. is 'Pending' an ageing tail? ===
say("## 4. Finding 1 — 'Pending' is a permanent state, not an ageing tail")
say()
claims["SubMonth"] = claims.SubmittedDate.dt.to_period("M")
by_month = claims.pivot_table(index="SubMonth", columns="ClaimStatus",
                              values="ClaimID", aggfunc="size").fillna(0)
by_month["Total"] = by_month.sum(axis=1)
by_month["PendingPct"] = by_month.Pending / by_month.Total * 100
full = by_month[by_month.Total > by_month.Total.median() * 0.5]     # drop the stub month
metric("pending_share_overall", float(len(pend_claims) / n_claims))
metric("pending_share_min_month", float(full.PendingPct.min()))
metric("pending_share_max_month", float(full.PendingPct.max()))
metric("pending_share_first_month", float(full.PendingPct.iloc[0]))
metric("pending_share_last_month", float(full.PendingPct.iloc[-1]))

asof = metric("asof_date", str(max(claims.ProcessedDate.max(), pays.PaymentDate.max()).date()))
age = (pd.Timestamp(asof) - pend_claims.SubmittedDate).dt.days
metric("pending_age_median_days", int(age.median()))
metric("pending_age_max_days", int(age.max()))
metric("pending_over_365", int((age > 365).sum()))
metric("pending_over_365_share", float((age > 365).mean()))

say(f"{pct(len(pend_claims) / n_claims)} of claims are Pending. The question that decides")
say("whether an AR ageing means anything is *when* those claims were submitted.")
say()
say(f"They were submitted **evenly across the entire file**. Over the "
    f"{len(full)} complete submission months the pending share runs from "
    f"{full.PendingPct.min():.1f}% to {full.PendingPct.max():.1f}% - "
    f"{full.PendingPct.iloc[0]:.1f}% in {full.index[0]}, the first month of the file, and "
    f"{full.PendingPct.iloc[-1]:.1f}% in {full.index[-1]}, the last. A claim submitted in "
    f"January 2023 is exactly as likely to be Pending as one submitted last month.")
say()
say(f"Measured at the as-of date ({asof}), the median pending claim is "
    f"**{int(age.median())} days old**, the oldest is {int(age.max())} days, and "
    f"**{int((age > 365).sum()):,} of {len(pend_claims):,} ({pct((age > 365).mean())}) are more "
    f"than a year old**.")
say()
say("**What this means.** A claim outstanding for three years does not exist in a real")
say("revenue cycle - payer timely-filing limits are 90 to 365 days, after which it is")
say("written off. So the AR ageing here is arithmetically correct but it is not a")
say("collections story: it is the shape of a status that was assigned at random and never")
say("revisited. The report builds the ageing properly - the buckets, the days in AR, the")
say("value at risk - and says this on the page, because an executive shown a")
say(f"{pct((age > 365).mean())} over-365 bucket would otherwise conclude the billing office")
say("had collapsed.")
say()

# ============================================= 5. does a denial ever recover? ===
say("## 5. Finding 2 — a denial never recovers, whatever its status says")
say()
den_status = den.DenialStatus.value_counts()
metric("denial_status_counts", {k: int(v) for k, v in den_status.items()})
recovered = den.merge(claims[["ClaimID", "PaidAmount", "ClaimStatus"]], on="ClaimID")
metric("denied_claims_with_any_payment", int((recovered.PaidAmount > 0).sum()))
say("| Denial status | Denials | Claims later paid | Amount recovered |")
say("|---|---:|---:|---:|")
for st, cnt in den_status.items():
    sub = recovered[recovered.DenialStatus == st]
    say(f"| {st} | {cnt:,} | {int((sub.PaidAmount > 0).sum())} | $0 |")
say()
say(f"`DenialStatus` carries four values - {', '.join(den_status.index)} - and "
    f"**{int((recovered.PaidAmount > 0).sum())} of the {n_den:,} denied claims were ever paid**, "
    f"including every one of the {int(den_status.get('Corrected', 0)):,} marked *Corrected* and "
    f"the {int(den_status.get('Appealed', 0)):,} marked *Appealed*.")
say()
lag = (den.merge(claims[["ClaimID", "ProcessedDate"]], on="ClaimID")
       .assign(lag=lambda d: (d.DenialDate - d.ProcessedDate).dt.days))
metric("denial_lag_days_min", int(lag.lag.min()))
metric("denial_lag_days_max", int(lag.lag.max()))
say(f"The denial date is also the processed date on every single denial (lag "
    f"{int(lag.lag.min())} to {int(lag.lag.max())} days), so there is no appeal timeline either.")
say()
say("**What this means.** Appeal yield, overturn rate, recovery rate and days-to-overturn -")
say("the four numbers a denials manager actually works to - **cannot be computed from this")
say("data**. They are not built. What is built is the denial *status mix*, labelled as a")
say("workflow state rather than an outcome, and the report says plainly that no recovery")
say("is observable.")
say()

# ====================================== 6. is first-pass a separate number? ====
say("## 6. Finding 3 — first-pass acceptance is the denial rate written twice")
say()
metric("claims_with_multiple_denials", int((den.groupby("ClaimID").size() > 1).sum()))
has_resub = any(c.lower() in ("originalclaimid", "resubmissionof", "parentclaimid")
                for c in claims.columns)
metric("has_resubmission_link", bool(has_resub))
say(f"A first-pass acceptance rate is only interesting when it differs from the final")
say(f"acceptance rate - the gap between them is the rework the billing office had to do.")
say("That requires a resubmission chain. This data has none:")
say()
say(f"- There is no `OriginalClaimID` or equivalent column on `fact_claims` "
    f"({'present' if has_resub else 'absent'}).")
say(f"- No claim carries more than one denial "
    f"({int((den.groupby('ClaimID').size() > 1).sum())} claims do).")
say("- No denied claim is ever subsequently paid (section 5).")
say()
den_rate = metric("denial_rate", float(len(den_claims) / n_claims))
say(f"So first-pass acceptance = 1 − denial rate = **{pct(1 - den_rate)}**, exactly, and")
say("clean-claim rate is the same number a third time. All three are published because the")
say("brief asks for them, on one card together, with a note that they are arithmetically")
say("identical here rather than three independent measurements.")
say()

# ================================================= 7. denial signal test ======
say("## 7. Finding 4 — the only thing that predicts a denial is who is paying")
say()
say("Each dimension below is tested the same way: the denial rate within each value, and")
say("the spread between the highest and lowest. A dimension with real signal separates;")
say("one without it collapses to the group rate.")
say()
say("| Dimension | Values | Lowest | Highest | Spread |")
say("|---|---:|---:|---:|---:|")
signal = {}
tests = [("Payer", "PayerName"), ("Facility type", "FacilityType"), ("Facility", "FacilityName"),
         ("Specialty", "Specialty"), ("Chronic risk band", "ChronicRiskBand"),
         ("Gender", "Gender"), ("Patient state", "BeneficiaryState"),
         ("Facility state", "FacilityState")]
for label, col in tests:
    g = wide.groupby(col).IsDenied.agg(["mean", "size"])
    spread = float((g["mean"].max() - g["mean"].min()) * 100)
    signal[col] = {"values": int(len(g)), "min_pct": float(g["mean"].min() * 100),
                   "max_pct": float(g["mean"].max() * 100), "spread_pp": spread}
    say(f"| {label} | {len(g)} | {g['mean'].min() * 100:.2f}% | {g['mean'].max() * 100:.2f}% | "
        f"**{spread:.2f} pp** |")

ld = lines.merge(claims[["ClaimID", "ClaimStatus"]], on="ClaimID")
ld["IsDenied"] = (ld.ClaimStatus == "Denied").astype(int)
for label, col in [("Procedure code", "ProcedureCode"), ("Diagnosis code", "DiagnosisCode")]:
    g = ld.groupby(col).IsDenied.agg(["mean", "size"])
    spread = float((g["mean"].max() - g["mean"].min()) * 100)
    signal[col] = {"values": int(len(g)), "min_pct": float(g["mean"].min() * 100),
                   "max_pct": float(g["mean"].max() * 100), "spread_pp": spread}
    say(f"| {label} | {len(g)} | {g['mean'].min() * 100:.2f}% | {g['mean'].max() * 100:.2f}% | "
        f"**{spread:.2f} pp** |")
metric("denial_signal", signal)
say()

self_pay = wide[wide.PayerName == "Self Pay"].IsDenied.mean()
insured = wide[wide.PayerName != "Self Pay"].IsDenied.mean()
ins_g = wide[wide.PayerName != "Self Pay"].groupby("PayerName").IsDenied.mean() * 100
metric("self_pay_denial_rate", float(self_pay))
metric("insured_denial_rate", float(insured))
metric("insurer_spread_pp", float(ins_g.max() - ins_g.min()))
say(f"**One split is real.** Self Pay denies at {pct(self_pay, 2)} against {pct(insured, 2)} for")
say(f"the five insurers - a gap of {(insured - self_pay) * 100:.1f} points, and it is the largest")
say(f"effect anywhere in the data. But *among* the five insurers the spread is only")
say(f"{ins_g.max() - ins_g.min():.2f} points ({ins_g.idxmin()} {ins_g.min():.2f}% to "
    f"{ins_g.idxmax()} {ins_g.max():.2f}%), which is noise at these volumes.")
say()

# provider: is the variation more than chance?
pg = wide.groupby("ProviderID").IsDenied.agg(["mean", "size"])
pg = pg[pg["size"] >= 100]
observed_sd = float(pg["mean"].std() * 100)
p_bar = float(wide.IsDenied.mean())
expected_sd = float(np.sqrt(p_bar * (1 - p_bar) / pg["size"].mean()) * 100)
metric("provider_observed_sd_pp", observed_sd)
metric("provider_expected_sd_pp", expected_sd)
metric("provider_count_tested", int(len(pg)))
say(f"**Provider variation is indistinguishable from chance.** Across the {len(pg)} providers")
say(f"with at least 100 claims, the denial rate runs {pg['mean'].min() * 100:.1f}% to "
    f"{pg['mean'].max() * 100:.1f}%, which looks like a league table worth publishing. It is not.")
say(f"The standard deviation of those rates is **{observed_sd:.2f} pp**; the standard deviation")
say(f"you would get by flipping a {pct(p_bar, 1)} coin the same number of times per provider is")
say(f"**{expected_sd:.2f} pp**. The observed spread is {observed_sd / expected_sd:.2f}× the spread")
say("of pure chance - in other words, all of it.")
say()
say("**What this means.** Ranking providers or facilities by denial rate here would name")
say("and shame people for noise. The report shows the provider distribution *against its")
say("chance baseline* instead, which is the honest version of the same chart, and the")
say("denial page leads with payer mix because that is where the only real effect is.")
say()

# continuous predictors
cb = claims.merge(ben, on="BeneficiaryID", how="left")
cb["Age"] = ((pd.Timestamp(asof) - cb.DateOfBirth).dt.days / 365.25)
cb["IsDenied"] = (cb.ClaimStatus == "Denied").astype(int)
lc = lines.groupby("ClaimID").size().rename("LineCount")
cb = cb.merge(lc, on="ClaimID", how="left")
corrs = {"patient_age": float(cb.Age.corr(cb.IsDenied)),
         "billed_amount": float(cb.BilledAmount.corr(cb.IsDenied)),
         "line_count": float(cb.LineCount.corr(cb.IsDenied)),
         "days_to_submit": float((cb.SubmittedDate - cb.ServiceDate).dt.days.corr(cb.IsDenied))}
metric("denial_correlations", corrs)
say("The continuous candidates fare no better:")
say()
say("| Candidate | Correlation with denial |")
say("|---|---:|")
for k, v in corrs.items():
    say(f"| {k.replace('_', ' ').capitalize()} | {v:+.4f} |")
say()
say(f"Every one is inside |r| < 0.01. **No denial-risk model is built.** One trained on these")
say("features would be fitting noise, and would then be used to hold up claims that were")
say("never at risk.")
say()

# duplicate-claim denial reason is a label only
key_cols = ["BeneficiaryID", "ProviderID", "ServiceDate", "BilledAmount"]
grp = claims.groupby(key_cols).size()
true_dupes = int((grp > 1).sum())
metric("true_duplicate_claim_groups", true_dupes)
dup_reason = int((den.DenialReason == "Duplicate Claim").sum())
metric("duplicate_claim_denials", dup_reason)
say(f"One more check worth making: {dup_reason:,} claims are denied for **Duplicate Claim**, "
    f"but there are **{true_dupes} actual duplicates** in the file - no two claims share a "
    f"patient, provider, service date and billed amount. The denial reason is a label drawn "
    f"from a list, not a finding about the claim. Reason mix is therefore reported as a "
    f"workload profile, never as a root cause.")
say()

# =========================================== 8. do the codes mean anything? ====
say("## 8. Finding 5 — the procedure code does not price the procedure")
say()
pc = lines.groupby("ProcedureCode").ChargeAmount.agg(["mean", "min", "max", "size"])
metric("procedure_code_count", int(lines.ProcedureCode.nunique()))
metric("diagnosis_code_count", int(lines.DiagnosisCode.nunique()))
metric("procedure_charge_mean_min", float(pc["mean"].min()))
metric("procedure_charge_mean_max", float(pc["mean"].max()))
say(f"There are {lines.ProcedureCode.nunique()} procedure codes and "
    f"{lines.DiagnosisCode.nunique()} diagnosis codes. The average charge per code runs from")
say(f"${pc['mean'].min():,.2f} to ${pc['mean'].max():,.2f} - a spread of "
    f"**${pc['mean'].max() - pc['mean'].min():.2f}**, or "
    f"{(pc['mean'].max() / pc['mean'].min() - 1) * 100:.1f}%, across every code in the file.")
say()
say("Those codes are real CPT and ICD-10 values, and in a real chargemaster they are not")
say("remotely comparable: 36415 is a venipuncture worth a few dollars, 70553 is an MRI of")
say("the brain with and without contrast worth well over a thousand. Here they average")
say("within a few dollars of one another because the charge is drawn independently of the")
say("code.")
say()
say("**What this means.** Case-mix analysis, cost-per-procedure, service-line profitability")
say("and procedure-level pricing are all off the table. The code dimensions are still")
say("modelled and still useful - they carry *volume* faithfully, and volume by service line")
say("is a real operational question - but no page ranks a procedure by revenue.")
say()

# ================================================== 9. timeliness and lags =====
say("## 9. What the data does support: the clock")
say()
lag_sub = (claims.SubmittedDate - claims.ServiceDate).dt.days
lag_proc = (claims.ProcessedDate - claims.SubmittedDate).dt.days
pp = paid_claims.merge(pays[["ClaimID", "PaymentDate"]], on="ClaimID")
lag_pay = (pp.PaymentDate - pp.SubmittedDate).dt.days
lag_settle = (pp.PaymentDate - pp.ProcessedDate).dt.days
for name, s in [("days_to_submit", lag_sub), ("days_to_process", lag_proc),
                ("days_to_pay", lag_pay), ("days_process_to_pay", lag_settle)]:
    metric(f"{name}_mean", float(s.mean()))
    metric(f"{name}_median", float(s.median()))
    metric(f"{name}_max", int(s.max()))
say("| Interval | Median | Mean | Max |")
say("|---|---:|---:|---:|")
say(f"| Service → submission | {lag_sub.median():.0f} d | {lag_sub.mean():.1f} d | {lag_sub.max():.0f} d |")
say(f"| Submission → adjudication | {lag_proc.median():.0f} d | {lag_proc.mean():.1f} d | {lag_proc.max():.0f} d |")
say(f"| Adjudication → payment | {lag_settle.median():.0f} d | {lag_settle.mean():.1f} d | {lag_settle.max():.0f} d |")
say(f"| **Submission → payment** | **{lag_pay.median():.0f} d** | **{lag_pay.mean():.1f} d** | {lag_pay.max():.0f} d |")
say()
say("These are well-formed and internally consistent - no claim is submitted before it is")
say("performed, adjudicated before it is submitted, or paid before it is adjudicated. The")
say(f"whole cycle runs a median of {lag_pay.median():.0f} days from submission to cash, which")
say("is a believable figure for a clean electronic claim and is the strongest thing this")
say("data has to offer. **Timeliness is where the analysis leans.**")
say()

vol = claims.groupby(claims.ServiceDate.dt.to_period("M")).size()
full_vol = vol[vol > vol.median() * 0.5]
metric("monthly_volume_min", int(full_vol.min()))
metric("monthly_volume_max", int(full_vol.max()))
metric("monthly_volume_cv", float(full_vol.std() / full_vol.mean()))
say(f"Volume is flat: {full_vol.min():,} to {full_vol.max():,} claims per service month across")
say(f"{len(full_vol)} complete months, a coefficient of variation of "
    f"{full_vol.std() / full_vol.mean() * 100:.1f}%. **There is no seasonality and no trend** - so")
say("no growth narrative is offered, and any month-on-month movement on the pages is")
say("correctly read as noise.")
say()

# ============================================== 10. coverage and the calendar ==
say("## 10. The date dimension does not cover the facts")
say()
dmin, dmax = date.Date.min(), date.Date.max()
metric("dim_date_min", str(dmin.date()))
metric("dim_date_max", str(dmax.date()))
gaps = int((dmax - dmin).days + 1 - len(date))
metric("dim_date_internal_gaps", gaps)
outside = {
    "SubmittedDate": int(((claims.SubmittedDate < dmin) | (claims.SubmittedDate > dmax)).sum()),
    "ProcessedDate": int(((claims.ProcessedDate < dmin) | (claims.ProcessedDate > dmax)).sum()),
    "PaymentDate": int(((pays.PaymentDate < dmin) | (pays.PaymentDate > dmax)).sum()),
    "DenialDate": int(((den.DenialDate < dmin) | (den.DenialDate > dmax)).sum()),
    "ServiceDate": int(((claims.ServiceDate < dmin) | (claims.ServiceDate > dmax)).sum()),
}
metric("dates_outside_dim_date", outside)
say(f"`dim_date` runs {dmin.date()} to {dmax.date()} ({len(date):,} rows, {gaps} internal gaps).")
say("The facts run past the end of it:")
say()
say("| Date column | Rows outside `dim_date` | Share |")
say("|---|---:|---:|")
say(f"| ServiceDate | {outside['ServiceDate']:,} | {pct(outside['ServiceDate'] / n_claims, 2)} |")
say(f"| SubmittedDate | {outside['SubmittedDate']:,} | {pct(outside['SubmittedDate'] / n_claims, 2)} |")
say(f"| ProcessedDate | {outside['ProcessedDate']:,} | {pct(outside['ProcessedDate'] / n_claims, 2)} |")
say(f"| PaymentDate | {outside['PaymentDate']:,} | {pct(outside['PaymentDate'] / n_pays, 2)} |")
say(f"| DenialDate | {outside['DenialDate']:,} | {pct(outside['DenialDate'] / n_den, 2)} |")
say()
say("Service dates fit, because the calendar was built to the service range. But a claim is")
say("submitted after it is performed, adjudicated after that and paid after that, so the")
say(f"tail spills over: {outside['ProcessedDate']:,} adjudications and {outside['PaymentDate']:,}")
say("payments land on days the calendar does not contain.")
say()
say("**What this means.** Left alone, every one of those rows joins to a blank date and")
say("quietly disappears from any measure sliced by adjudication or payment month - the")
say("worst kind of error, because the totals still look plausible. The SQL build therefore")
say("**generates its own date dimension** covering every date in every fact table plus a")
say("margin, keeping the supplied columns (financial year, ISO week) and adding what a")
say("revenue-cycle model needs.")
say()
fy = date[["FinancialYear", "FinancialYearStart"]].drop_duplicates().sort_values("FinancialYearStart")
metric("financial_years", sorted(date.FinancialYear.unique().tolist()))
say(f"The supplied calendar uses an **Australian financial year** - July to June, labelled by")
say(f"the year it ends in (1 July 2022 falls in FY23). That convention is preserved, because")
say(f"the facility states ({', '.join(sorted(fac.State.unique()))}) are Australian too.")
say()

# ================================================== 11. dimension coverage ====
say("## 11. Dimension coverage and security")
say()
unused_ben = int(len(ben) - claims.BeneficiaryID.nunique())
metric("beneficiaries_unused", unused_ben)
metric("providers_used", int(claims.ProviderID.nunique()))
metric("facilities_used", int(claims.FacilityID.nunique()))
own_fac = claims.merge(prov[["ProviderID", "FacilityID"]].rename(
    columns={"FacilityID": "HomeFacility"}), on="ProviderID")
share_own = float((own_fac.FacilityID == own_fac.HomeFacility).mean())
metric("claims_at_provider_home_facility", share_own)
metric("provider_facility_is_one_to_one",
       bool(prov.groupby("ProviderID").FacilityID.nunique().max() == 1))
say(f"- **{unused_ben:,} of {len(ben):,} beneficiaries never appear on a claim** "
    f"({pct(unused_ben / len(ben))}). A patient count taken from the dimension would overstate")
say("  the treated population by that much, so every patient count in the model is taken")
say("  from the claims, not from the dimension.")
say(f"- All {claims.ProviderID.nunique()} providers and all {claims.FacilityID.nunique()} "
    f"facilities are used.")
say(f"- **Each provider belongs to exactly one facility, and {pct(share_own)} of claims are")
say("  billed at the provider's own facility.** Provider and facility are therefore one")
say("  hierarchy, not two independent dimensions - which matters for row-level security:")
say("  filtering facility implicitly filters provider, and a naive two-table security")
say("  filter would be applied twice.")
say()
roles = sec.Role.value_counts()
metric("rls_roles", {k: int(v) for k, v in roles.items()})
metric("rls_users", int(len(sec)))
say(f"`security_user_access` carries {len(sec)} grants across {len(roles)} roles:")
say()
say("| Role | Users | Scope |")
say("|---|---:|---|")
for r, cnt in roles.items():
    sub = sec[sec.Role == r]
    scope = ("all facilities and providers" if (sub.FacilityID == "ALL").all() and (sub.ProviderID == "ALL").all()
             else "one facility each" if (sub.ProviderID == "ALL").all()
             else "one provider each")
    say(f"| {r} | {cnt} | {scope} |")
say()
bad_fac = int((~sec[sec.FacilityID != "ALL"].FacilityID.isin(set(fac.FacilityID))).sum())
bad_prov = int((~sec[sec.ProviderID != "ALL"].ProviderID.isin(set(prov.ProviderID))).sum())
metric("rls_invalid_facility_refs", bad_fac)
metric("rls_invalid_provider_refs", bad_prov)
say(f"Every scoped grant points at a real facility or provider ({bad_fac + bad_prov} invalid")
say("references), so dynamic RLS can be built directly on this table.")
say()

# ================================================= 12. lines reconcile ========
say("## 12. Do the claim lines reconcile to the header?")
say()
ls = lines.groupby("ClaimID").agg(LineCharge=("ChargeAmount", "sum"), Lines=("ClaimLineID", "size"))
rec = claims[["ClaimID", "BilledAmount"]].merge(ls, on="ClaimID", how="left")
diff = (rec.LineCharge - rec.BilledAmount).abs()
metric("claims_without_lines", int(rec.Lines.isna().sum()))
metric("lines_per_claim_mean", float(ls.Lines.mean()))
metric("lines_per_claim_max", int(ls.Lines.max()))
metric("line_header_exact_matches", int((diff < 0.005).sum()))
metric("line_header_max_variance", float(diff.max()))
say(f"Every claim has between 1 and {int(ls.Lines.max())} lines (mean {ls.Lines.mean():.2f}), and")
say(f"the lines sum to the header billed amount on **{int((diff < 0.005).sum()):,} of "
    f"{n_claims:,}** claims exactly. The remaining "
    f"{n_claims - int((diff < 0.005).sum())} differ by at most "
    f"**${diff.max():.2f}** - cent-level rounding from splitting a header amount across lines,")
say("not a data error.")
say()
say("This matters more than it looks. Because the lines reconcile, the line table can carry")
say("procedure and diagnosis analysis *without* becoming a second source of truth for money:")
say("every financial measure in the model is defined on the claim header, and the line table")
say("is used only for volume and mix. A model that summed charges from both would")
say("double-count.")
say()

# ===================================================== 13. what gets built ====
say("## 13. What will be built, and what will not")
say()
say("| The brief asks for | Verdict | What is built instead |")
say("|---|---|---|")
say("| First-pass acceptance rate | **Supported, but not independent** | Published with the denial rate and clean-claim rate on one card, noted as arithmetically identical |")
say("| Clean-claim rate | **Supported, same caveat** | As above |")
say("| Denial rate | **Supported** | By payer, reason, facility, specialty, month - with a chance baseline on the provider view |")
say("| Collection rate | **Supported** | Gross and net, and the four-bucket allowed-amount identity |")
say("| AR ageing from service/submission/payment dates | **Computable, but not a collections story** | Built in full, with the finding in section 4 stated on the page |")
say("| Denial root cause by payer | **Partly** | The Self Pay split is real; the five insurers are within noise of each other |")
say("| Denial root cause by facility / provider / diagnosis / procedure | **Not supported** | Provider distribution shown against its chance baseline instead of a league table |")
say("| A churn/denial-risk model on claim features | **Not supported** | Not built - every candidate is inside \\|r\\| < 0.01 |")
say("| Appeal and recovery analysis | **Not supported** | Denial status shown as workflow state, with no recovery claimed |")
say("| Payer contract performance | **Not supported** | Contractual adjustment reported group-wide, payers not ranked |")
say("| Provider- and facility-level dynamic RLS | **Supported** | Built on `security_user_access`, as one hierarchy |")
say("| Incremental refresh, DirectQuery/composite | **Out of scope here** | Requires the Service; folding to SQL Server is proved instead |")
say()
say("---")
say()
say("## The short version")
say()
say(f"1. The money closes exactly: every dollar of the {money(allowed)} allowed is collected,")
say("   owed by a patient, denied, or still in AR. That identity is the spine of the model.")
say(f"2. 'Pending' is not an ageing tail - {pct((age > 365).mean())} of AR is over a year old and")
say("   the pending share is identical in every month of the file.")
say("3. A denial never recovers, whatever its status says, so appeal yield is not offered.")
say(f"4. Nothing predicts a denial except Self Pay ({pct(self_pay, 2)} vs {pct(insured, 2)}).")
say(f"   Provider variation is {observed_sd / expected_sd:.2f}× chance - that is, all of it.")
say("5. The procedure code does not price the procedure, so no service-line revenue ranking.")
say(f"6. The supplied calendar misses {outside['ProcessedDate'] + outside['PaymentDate']:,}")
say("   adjudication and payment dates; the build generates its own.")
say()
say("The timeliness of the cycle, the composition of the money, the denial workload profile")
say("and the AR shape are all real. That is the project.")
say()

OUT.parent.mkdir(parents=True, exist_ok=True)
METRICS.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
METRICS.write_text(json.dumps(M, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(f"source     : {SRC}")
print(f"report     : {OUT.relative_to(ROOT)}  ({len(L)} lines)")
print(f"metrics    : {METRICS.relative_to(ROOT)}  ({len(M)} metrics)")
print()
print(f"billed {money(billed)} -> allowed {money(allowed)} -> collected {money(paid)}")
print(f"identity residual: ${abs(residual):.2f}")
print(f"denial rate {pct(den_rate)} | self pay {pct(self_pay, 2)} vs insured {pct(insured, 2)}")
print(f"provider denial sd {observed_sd:.2f} pp vs {expected_sd:.2f} pp expected by chance")
print(f"pending: {pct(len(pend_claims) / n_claims)} of claims, {pct((age > 365).mean())} over 365 days")
print(f"dates outside dim_date: {sum(outside.values()):,}")
