# -*- coding: utf-8 -*-
"""
Phase 1 - Data audit, Omnichannel Marketing Attribution.

Reads the raw CSVs in Data/raw directly (never the SQL database), measures
every property the build depends on, and writes:

    Documentation/data_quality_report.md   findings, classified
    Validation/audit_metrics.json          the measured numbers

Because this reads the raw files independently of SQL Server, its numbers are
the external reference that SQL/09_validation.sql is checked against.

Classification
    ERROR      breaks correctness unless the build handles it
    ANOMALY    implausible for real data, cannot be repaired - reported, not hidden
    EXCEPTION  legitimate, but needs an explicit modelling rule
    INFO       confirmed good, or descriptive

Usage:  python Python/01_data_audit.py      (from the repository root or anywhere)
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
DOC = ROOT / "Documentation" / "data_quality_report.md"
MET = ROOT / "Validation" / "audit_metrics.json"


def load():
    r = lambda f, **k: pd.read_csv(RAW / f, **k)
    return dict(
        ch=r("dim_channel.csv"), cam=r("dim_campaign.csv", parse_dates=["StartDate"]),
        mp=r("campaign_name_mapping.csv"), dd=r("dim_date.csv", parse_dates=["Date"]),
        ad=r("fact_ad_spend.csv", parse_dates=["Date"]), ld=r("fact_leads.csv", parse_dates=["CreatedDate"]),
        tp=r("fact_touchpoints.csv", parse_dates=["TouchDate"]),
        op=r("fact_opportunities.csv", parse_dates=["CreatedDate"]),
        rv=r("fact_revenue.csv", parse_dates=["RevenueDate"]), sec=r("security_user_access.csv"))


def audit(t):
    ch, cam, mp, dd, ad, ld, tp, op, rv, sec = (t[k] for k in
        ("ch", "cam", "mp", "dd", "ad", "ld", "tp", "op", "rv", "sec"))
    m, F = {}, []   # metrics, findings

    def add(cls, title, detail, decision):
        F.append((cls, title, detail, decision))

    # ------------------------------------------------------------ structure ---
    pks = {"dim_channel": (ch, "ChannelID"), "dim_campaign": (cam, "CampaignID"),
           "campaign_name_mapping": (mp, "RawCampaignKey"), "dim_date": (dd, "Date"),
           "fact_ad_spend": (ad, "AdRowID"), "fact_leads": (ld, "LeadID"),
           "fact_touchpoints": (tp, "TouchpointID"), "fact_opportunities": (op, "OpportunityID"),
           "fact_revenue": (rv, "RevenueID")}
    m["rows"] = {k: int(len(v[0])) for k, v in pks.items()} | {"security_user_access": int(len(sec))}
    m["pk_duplicates"] = int(sum(v[0][v[1]].duplicated().sum() for v in pks.values()))
    m["null_cells"] = int(sum(v[0].isna().sum().sum() for v in pks.values()))
    orphans = {
        "ad_spend.CampaignID": int((~ad.CampaignID.isin(cam.CampaignID)).sum()),
        "ad_spend.ChannelID": int((~ad.ChannelID.isin(ch.ChannelID)).sum()),
        "leads.CampaignID": int((~ld.CampaignID.isin(cam.CampaignID)).sum()),
        "touchpoints.CampaignID": int((~tp.CampaignID.isin(cam.CampaignID)).sum()),
        "touchpoints.LeadID": int((~tp.LeadID.isin(ld.LeadID)).sum()),
        "opportunities.LeadID": int((~op.LeadID.isin(ld.LeadID)).sum()),
        "revenue.OpportunityID": int((~rv.OpportunityID.isin(op.OpportunityID)).sum()),
    }
    m["orphans"] = orphans
    add("INFO", "Keys and completeness are clean",
        f"{m['pk_duplicates']} duplicate primary keys, {m['null_cells']} null cells, "
        f"{sum(orphans.values())} orphaned foreign keys across {len(orphans)} relationships.",
        "Foreign keys declared and engine-trusted in dbo.")

    # ------------------------------------------------------------ calendar ---
    asof = max(ad.Date.max(), ld.CreatedDate.max(), tp.TouchDate.max())
    m["as_of_date"] = asof.strftime("%Y-%m-%d")
    m["calendar_end"] = dd.Date.max().strftime("%Y-%m-%d")
    out_opp = int((~op.CreatedDate.isin(dd.Date)).sum())
    out_rev = int((~rv.RevenueDate.isin(dd.Date)).sum())
    m["opportunities_outside_calendar"], m["revenue_outside_calendar"] = out_opp, out_rev
    add("ERROR", "Calendar ends before the last fact date",
        f"dim_date ends {m['calendar_end']}; opportunities run to {op.CreatedDate.max().date()} "
        f"and revenue to {rv.RevenueDate.max().date()}. {out_opp} opportunity and {out_rev} revenue rows have no calendar day.",
        "DimDate regenerated to 2027-06-30 (end of FY27) and checked against the supplied calendar for every overlapping day.")

    late_opp = op[op.CreatedDate > asof]
    late_rev = rv[rv.RevenueDate > asof]
    m["opportunities_after_asof"] = int(len(late_opp))
    m["revenue_rows_after_asof"] = int(len(late_rev))
    m["revenue_after_asof"] = round(float(late_rev.RevenueAmount.sum()), 2)
    add("ANOMALY", "Revenue dated after the as-of date",
        f"Marketing activity stops at {m['as_of_date']}, yet {len(late_opp)} opportunities and {len(late_rev)} revenue rows "
        f"({m['revenue_after_asof']:,.2f}, {late_rev.RevenueAmount.sum() / rv.RevenueAmount.sum():.1%} of revenue) are dated later.",
        "Loaded and flagged IsAfterAsOf. EVERY figure anchors to the as-of date - the funnel included: an opportunity "
        "counts once opened and a customer once revenue is booked, by the as-of date. Post-period records appear only "
        "as data-quality figures.")

    # The funnel as it stood on the as-of date: expected values for SQL 09 section 8.
    opp_by = op[op.CreatedDate <= asof]
    won_by = rv[rv.RevenueDate <= asof]
    open_by = opp_by[~opp_by.OpportunityID.isin(won_by.OpportunityID) & (opp_by.Status != "Closed Lost")]
    m["as_of_funnel"] = {
        "opportunities": int(len(opp_by)), "customers": int(len(won_by)),
        "revenue": round(float(won_by.RevenueAmount.sum()), 2),
        "closed_lost": int((opp_by.Status == "Closed Lost").sum()),
        "open": int(len(open_by)), "open_pipeline": round(float(open_by.OpportunityValue.sum()), 2),
        "open_but_won_later": int((open_by.Status == "Closed Won").sum())}
    ytd_start = pd.Timestamp(asof.year, 1, 1)
    m["revenue_ytd"] = round(float(rv[(rv.RevenueDate >= ytd_start) & (rv.RevenueDate <= asof)].RevenueAmount.sum()), 2)
    m["revenue_pytd"] = round(float(rv[(rv.RevenueDate >= ytd_start - pd.DateOffset(years=1))
                                       & (rv.RevenueDate <= asof - pd.DateOffset(years=1))].RevenueAmount.sum()), 2)

    # -------------------------------------------------------------- journey ---
    s = tp.sort_values(["LeadID", "TouchSequence"])
    contradict = s.groupby("LeadID").TouchDate.apply(lambda x: bool((x.diff().dt.days < 0).any()))
    m["leads_sequence_contradicts_date"] = int(contradict.sum())
    first_types = s.groupby("LeadID").head(1).TouchType.value_counts(normalize=True)
    add("ERROR", "TouchSequence contradicts TouchDate",
        f"For {contradict.sum():,} of {ld.shape[0]:,} leads ({contradict.mean():.0%}) a later sequence number carries an earlier date. "
        f"Each touch type holds {first_types.min():.1%}-{first_types.max():.1%} of first positions, so the sequence has no behavioural signal.",
        "JourneyPosition orders by TouchDate, tie-break TouchSequence. Time-decay is defined in days and needs a real timeline.")

    lead_cam = ld.set_index("LeadID").CampaignID
    first = s.groupby("LeadID").head(1).set_index("LeadID").CampaignID
    last = s.groupby("LeadID").tail(1).set_index("LeadID").CampaignID
    m["lead_campaign_matches_first_touch"] = round(float((first == lead_cam.reindex(first.index)).mean()), 4)
    m["lead_campaign_matches_last_touch"] = round(float((last == lead_cam.reindex(last.index)).mean()), 4)
    add("ANOMALY", "A lead's own campaign is unrelated to its journey",
        f"leads.CampaignID matches the first touch {m['lead_campaign_matches_first_touch']:.1%} and the last touch "
        f"{m['lead_campaign_matches_last_touch']:.1%} of the time.",
        "Attribution uses touchpoints only. The lead campaign is reported as 'lead source' for cost per lead.")

    tl = tp.merge(ld[["LeadID", "CreatedDate"]], on="LeadID")
    m["touches_after_lead_created"] = int((tl.TouchDate > tl.CreatedDate).sum())
    m["touches_same_day_as_another"] = int(tp.duplicated(["LeadID", "TouchDate"], keep=False).sum())
    per = tp.groupby("LeadID").size()
    m["touches_per_lead"] = {int(k): int(v) for k, v in per.value_counts().sort_index().items()}
    m["multichannel_leads"] = int((tp.groupby("LeadID").ChannelID.nunique() > 1).sum())
    add("INFO", "Journeys are complete and pre-conversion",
        f"Every lead has 1-6 touches; {m['multichannel_leads']:,} ({m['multichannel_leads'] / len(ld):.0%}) span 2+ channels; "
        f"{m['touches_after_lead_created']} touches fall after lead creation.",
        "The conversion event for attribution is lead creation.")
    add("EXCEPTION", "Same-day touches",
        f"{m['touches_same_day_as_another']:,} touches share a date with another touch of the same lead.",
        "Ties broken by the source TouchSequence; time-decay gives same-day touches equal weight.")
    tt = tp.merge(ch, on="ChannelID")
    shares = tt.groupby("ChannelName").TouchType.value_counts(normalize=True)
    m["email_open_touches_on_paid_search"] = int(((tt.ChannelGroup == "Paid Search") & (tt.TouchType == "Email Open")).sum())
    add("ANOMALY", "Touch type is independent of channel",
        f"Every channel carries all {tt.TouchType.nunique()} touch types in near-equal shares ({shares.min():.1%}-"
        f"{shares.max():.1%}) - for example {m['email_open_touches_on_paid_search']:,} 'Email Open' touches on Paid Search.",
        "Touch type is not analysed by channel; journeys are analysed by position and channel only.")

    # --------------------------------------------------------------- funnel ---
    won = set(rv.LeadID)
    m["funnel"] = {
        "leads": int(len(ld)),
        "mql_plus": int(ld.LatestStage.isin(["MQL", "SQL", "Opportunity", "Customer"]).sum()),
        "sql_plus": int(ld.LatestStage.isin(["SQL", "Opportunity", "Customer"]).sum()),
        "opportunities": int(op.LeadID.nunique()), "won": int(len(won))}
    stale = ld[ld.LeadID.isin(won) & (ld.LatestStage != "Customer")]
    m["stale_stage_labels"] = int(len(stale))
    add("ERROR", "Funnel stage labels are stale",
        f"{len(stale):,} leads with booked revenue are labelled '{stale.LatestStage.mode()[0]}'. "
        f"The label counts {int((ld.LatestStage == 'Customer').sum()):,} customers; revenue shows {len(won):,}.",
        "DerivedStage from evidence: revenue -> Customer, opportunity -> Opportunity, otherwise the CRM label.")
    rw = rv.merge(op, on="OpportunityID")
    m["revenue_equals_opportunity_value"] = bool((rw.RevenueAmount.round(2) == rw.OpportunityValue.round(2)).all())
    m["total_revenue"] = round(float(rv.RevenueAmount.sum()), 2)
    lr = rv.merge(ld[["LeadID", "CreatedDate", "Segment"]], on="LeadID")
    m["max_days_lead_to_revenue"] = int((lr.RevenueDate - lr.CreatedDate).dt.days.max())
    newest = ld[(ld.CreatedDate.dt.year == asof.year) & (ld.CreatedDate.dt.month == asof.month)]
    add("EXCEPTION", "The newest lead cohorts are still converting",
        f"Lead to booked revenue takes up to {m['max_days_lead_to_revenue']} days. Leads created in {asof:%B %Y} show "
        f"{won_by.LeadID.isin(newest.LeadID).sum() / len(newest):.1%} conversion by the as-of date against "
        f"{rv.LeadID.isin(newest.LeadID).sum() / len(newest):.1%} once every recorded outcome is in.",
        "Conversion trends leave out cohorts younger than the conversion window (Lead to Customer % (Mature Cohorts)); "
        "totals are stated 'by the as-of date'.")
    seg_deal = lr.groupby("Segment").RevenueAmount.mean()
    seg_conv = ld.assign(w=ld.LeadID.isin(won)).groupby("Segment").w.mean()
    m["average_deal_by_segment"] = {k: round(float(v), 2) for k, v in seg_deal.items()}
    add("INFO", "Segments do not differ in deal size or conversion",
        "Average deal " + ", ".join(f"{k} ${v:,.0f}" for k, v in seg_deal.items())
        + f"; lead-to-customer {seg_conv.min():.1%}-{seg_conv.max():.1%}. An Enterprise deal is no larger than an SMB "
        "deal, unlike real B2B data.",
        "Segment stays available as a slicer and heatmap axis. No segment-value story is told, and the heatmap colours "
        "only statistically significant differences.")

    # ------------------------------------------------------------ spend/FX ---
    m["currencies"] = {k: int(v) for k, v in ad.Currency.value_counts().items()}
    m["spend_local_total"] = round(float(ad.SpendLocal.sum()), 2)
    add("ERROR", "Four currencies, no exchange rates",
        f"Spend arrives in {', '.join(sorted(m['currencies']))} with no FX table; revenue carries no currency column.",
        "dbo.FxRate holds labelled static PLANNING rates to USD (not market data); revenue treated as USD.")
    reg_cur = ad.merge(cam[["CampaignID", "Region"]], on="CampaignID").groupby("Region").Currency.agg(
        lambda x: x.value_counts(normalize=True).max())
    add("ANOMALY", "Billing currency is unrelated to campaign region",
        f"In every region the most common currency covers only {reg_cur.min():.0%}-{reg_cur.max():.0%} of spend rows.",
        "Converted row by row on each row's own currency; no region-based currency is assumed.")
    m["spend_to_revenue_ratio_local"] = round(m["spend_local_total"] / m["total_revenue"], 1)
    m["clicks_total"] = int(ad.Clicks.sum())
    m["click_to_lead_pct"] = round(100 * len(ld) / m["clicks_total"], 4)
    m["ctr_pct"] = round(100 * ad.Clicks.sum() / ad.Impressions.sum(), 3)
    add("ANOMALY", "Ad data and CRM data are on different scales",
        f"The ad data records {m['clicks_total']:,} clicks; the CRM holds {len(ld):,} leads - one lead per "
        f"{m['clicks_total'] // len(ld):,} clicks ({m['click_to_lead_pct']}%), against the 2-5% typical of B2B landing "
        f"pages. The ad side is internally consistent - clicks, impressions and spend move together (CTR "
        f"{m['ctr_pct']}%) - so the CRM extract covers a small fraction of the traffic the spend bought. Consequence: spend is about "
        f"{m['spend_to_revenue_ratio_local']}x revenue ({m['spend_local_total']:,.0f} local vs {m['total_revenue']:,.2f}).",
        "Never rescaled. Media efficiency (CTR, CPC, CPM) and funnel conversion are reported as measured; commercial "
        "return leads with the scale-free Revenue-to-Spend Index; absolute ROAS and CAC appear only under a data "
        "note; the Click-to-Lead % measure makes the gap visible.")
    a2 = ad.merge(ch, on="ChannelID")
    unpaid = a2[~a2.ChannelGroup.str.startswith("Paid")]
    m["spend_on_unpaid_channels_local"] = round(float(unpaid.SpendLocal.sum()), 2)
    add("ANOMALY", "Organic, owned and referral channels carry 'ad spend'",
        f"{unpaid.ChannelName.nunique()} non-paid channels hold {unpaid.SpendLocal.sum():,.0f} of local spend.",
        "Kept and labelled 'channel cost'; ROAS on these channels carries a caveat.")
    per_ch = a2.groupby("ChannelName")[["Clicks", "Impressions"]].sum()
    ctr_ch = per_ch.Clicks / per_ch.Impressions
    m["ctr_by_channel_pct"] = {k: round(100 * float(v), 3) for k, v in ctr_ch.items()}
    add("ANOMALY", "Media rates are the same on every channel",
        f"CTR runs {100 * ctr_ch.min():.2f}%-{100 * ctr_ch.max():.2f}% on all {len(ctr_ch)} channels - Display included, "
        "where 0.1-0.5% is typical - and owned, organic and referral channels record impressions and clicks as if bought.",
        "Media rates are reported for paid media in total and never ranked by channel: there is no signal to rank.")
    k = ["Date", "CampaignID", "ChannelID"]
    grp = ad[ad.duplicated(k, keep=False)].groupby(k)
    m["shared_grain_groups"] = int(grp.ngroups)
    m["exact_duplicate_ad_rows"] = int(ad.drop(columns="AdRowID").duplicated().sum())
    add("EXCEPTION", "Several spend lines share Date x Campaign x Channel",
        f"{grp.ngroups:,} groups hold 2+ lines; {m['exact_duplicate_ad_rows']} are exact duplicates and "
        f"{(grp.Currency.nunique() > 1).sum():,} mix currencies.",
        "Treated as separate billing lines and summed after conversion. Not deduplicated.")
    ac = ad.merge(cam[["CampaignID", "StartDate"]], on="CampaignID")
    pre = ac[ac.Date < ac.StartDate]
    m["spend_rows_before_campaign_start"] = int(len(pre))
    add("ANOMALY", "Activity before the campaign StartDate",
        f"{len(pre):,} spend rows ({pre.SpendLocal.sum() / ad.SpendLocal.sum():.0%} of spend) predate their campaign's StartDate, "
        f"median {int((pre.StartDate - pre.Date).dt.days.median())} days early.",
        "StartDate is recorded but never used as a filter; flagged IsBeforeCampaignStart.")

    # ------------------------------------------------------------- campaigns ---
    aliases = mp.groupby("CampaignID").size()
    m["aliases_per_campaign"] = {int(k): int(v) for k, v in aliases.value_counts().items()}
    m["ambiguous_raw_names"] = int((mp.groupby("RawCampaignName").CampaignID.nunique() > 1).sum())
    normalised = mp.RawCampaignName.str.lower().str.replace(r"[\s_\-]+", " ", regex=True).str.strip()
    m["aliases_region_spelled_au_nz"] = int(normalised.str.startswith("au nz ").sum())
    add("EXCEPTION", "Messy campaign aliases",
        f"{len(mp)} raw names resolve to {mp.CampaignID.nunique()} campaigns, "
        f"{' or '.join(str(a) for a in sorted(m['aliases_per_campaign']))} aliases each, {m['ambiguous_raw_names']} ambiguous. "
        f"Styles differ in case and separators, and {m['aliases_region_spelled_au_nz']} aliases spell the ANZ region "
        f"'AU-NZ'. Example: {mp[mp.CampaignID == 'CAM0002'].RawCampaignName.tolist()}.",
        "Power Query rules in CampaignAliasResolution: R1 ignore case, R2 space/hyphen/underscore are one separator, "
        "R3 collapse separator runs, R4 AU-NZ = ANZ. Every alias checked against the supplied mapping.")

    # -------------------------------------------------------------- security ---
    ctry = ld.merge(cam[["CampaignID", "Region"]], on="CampaignID").groupby("Country").Region.agg(
        lambda x: x.value_counts(normalize=True).max())
    add("EXCEPTION", "Lead country is independent of campaign region",
        f"Within each country the most common campaign region covers only {ctry.min():.0%}-{ctry.max():.0%} of leads.",
        "Row-level security filters by campaign Region: a regional team sees the credit its own campaigns earned.")
    return m, F


def write(m, F):
    order = {"ERROR": 0, "ANOMALY": 1, "EXCEPTION": 2, "INFO": 3}
    F = sorted(F, key=lambda f: order[f[0]])
    counts = {c: sum(1 for f in F if f[0] == c) for c in order}
    lines = ["# Data Quality Report - Omnichannel Marketing Attribution", "",
             "Generated by `Python/01_data_audit.py` from the raw CSVs in `Data/raw`. "
             "The dataset is **synthetic** and must never be presented as real client data.", "",
             f"**{counts['ERROR']} ERROR, {counts['ANOMALY']} ANOMALY, {counts['EXCEPTION']} EXCEPTION, {counts['INFO']} INFO.** "
             f"As-of date: **{m['as_of_date']}**.", "",
             "| Class | Finding | Measured | Decision |", "|---|---|---|---|"]
    for c, t, d, dec in F:
        lines.append(f"| {c} | {t} | {d} | {dec} |")
    lines += ["", "## Row counts", "", "| File | Rows |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in m["rows"].items()]
    f = m["funnel"]
    lines += ["", "## Funnel (from evidence)", "",
              f"{f['leads']:,} leads -> {f['mql_plus']:,} MQL -> {f['sql_plus']:,} SQL -> "
              f"{f['opportunities']:,} opportunities -> {f['won']:,} won."]
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    MET.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return counts


if __name__ == "__main__":
    metrics, findings = audit(load())
    c = write(metrics, findings)
    print(f"{c['ERROR']} ERROR, {c['ANOMALY']} ANOMALY, {c['EXCEPTION']} EXCEPTION, {c['INFO']} INFO")
    print(f"wrote {DOC.relative_to(ROOT)} and {MET.relative_to(ROOT)}")
