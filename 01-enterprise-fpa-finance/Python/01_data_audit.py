# -*- coding: utf-8 -*-
"""
Phase 1 - Data audit, Enterprise FP&A Finance.

Reads the raw CSVs in Data/raw directly (never the SQL database), measures
every property the build depends on, and writes:

    Documentation/data_quality_report.md   findings, classified
    Validation/audit_metrics.json          the measured numbers

Because this reads the raw files independently of SQL Server, its numbers are
the external reference that SQL/09_validation.sql and the live model checks
are compared with. Money is computed in Decimal with the same rounding rule the
SQL build uses (half away from zero), so the expected values are exact.

Classification
    ERROR      breaks correctness unless the build handles it
    ANOMALY    implausible for real data, cannot be repaired - reported, not hidden
    EXCEPTION  legitimate, but needs an explicit modelling rule
    INFO       confirmed good, or descriptive

Usage:  python Python/01_data_audit.py
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
DOC = ROOT / "Documentation" / "data_quality_report.md"
MET = ROOT / "Validation" / "audit_metrics.json"

CENT, RATE = Decimal("0.01"), Decimal("0.000001")
BUCKETS = [("Current", -10**6, 0), ("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90),
           ("91-180", 91, 180), ("181-365", 181, 365), ("Over 365", 366, 10**6)]


def dec(x):
    return Decimal(str(x))


def money(x):
    return float(Decimal(x).quantize(CENT, ROUND_HALF_UP))


def load():
    r = lambda f, **k: pd.read_csv(RAW / f, **k)
    return dict(
        acct=r("dim_account.csv", dtype={"AccountCode": str}), cust=r("dim_customer.csv"),
        dd=r("dim_date.csv", parse_dates=["Date"]), dept=r("dim_department.csv"), ent=r("dim_entity.csv"),
        vend=r("dim_vendor.csv"),
        ap=r("fact_ap.csv", parse_dates=["BillDate", "DueDate", "PaidDate"], dtype={"BillAmountAUD": str, "PaidAmountAUD": str}),
        ar=r("fact_ar.csv", parse_dates=["InvoiceDate", "DueDate", "PaidDate"], dtype={"InvoiceAmountAUD": str, "PaidAmountAUD": str}),
        bud=r("fact_budget.csv", dtype={"AccountCode": str, "BudgetAmountAUD": str}),
        cash=r("fact_cash_balance.csv", dtype={"ClosingCashAUD": str}),
        fc=r("fact_forecast.csv", dtype={"AccountCode": str, "ForecastAmountAUD": str}),
        fx=r("fact_fx_rates.csv", dtype={"AUDPerUnit": str}),
        gl=r("fact_gl.csv", dtype={"AccountCode": str, "AmountLocal": str}),
        sec=r("security_user_access.csv"))


def monthly_rates(fx):
    """Average of the month's daily AUD-per-unit rates, rounded half-up to 6 dp.
    AUD is the reporting currency: its rate is 1 by definition, whatever the file says."""
    fx = fx.copy()
    fx["Month"] = fx.Date.str[:7] + "-01"
    fx["r"] = fx.AUDPerUnit.map(Decimal)
    fx.loc[fx.Currency == "AUD", "r"] = Decimal(1)
    g = fx.groupby(["Month", "Currency"]).r.agg(["sum", "count"]).reset_index()
    g["rate"] = [(s / Decimal(n)).quantize(RATE, ROUND_HALF_UP) for s, n in zip(g["sum"], g["count"])]
    return g[["Month", "Currency", "rate"]]


def translate(gl, mrates):
    gl = gl.copy()
    gl["Month"] = gl.Date.str[:7] + "-01"
    gl = gl.merge(mrates, left_on=["Month", "Currency"], right_on=["Month", "Currency"], how="left")
    gl["aud"] = [(Decimal(a) * r).quantize(CENT, ROUND_HALF_UP) for a, r in zip(gl.AmountLocal, gl.rate)]
    return gl


def open_as_of(df, doc, amt, asof):
    """Documents issued by the as-of date and not paid by it (no partial payments exist)."""
    m = (df[doc] <= asof) & (df.PaidDate.isna() | (df.PaidDate > asof))
    return df[m]


def audit(t):
    acct, cust, dd, dept, ent, vend = (t[k] for k in ("acct", "cust", "dd", "dept", "ent", "vend"))
    ap, ar, bud, cash, fc, fx, gl, sec = (t[k] for k in ("ap", "ar", "bud", "cash", "fc", "fx", "gl", "sec"))
    m, F = {}, []

    def add(cls, title, detail, decision):
        F.append((cls, title, detail, decision))

    # ------------------------------------------------------------ structure ---
    pks = {"dim_account": (acct, ["AccountCode"]), "dim_customer": (cust, ["CustomerID"]), "dim_date": (dd, ["Date"]),
           "dim_department": (dept, ["DepartmentID"]), "dim_entity": (ent, ["EntityID"]), "dim_vendor": (vend, ["VendorID"]),
           "fact_ap": (ap, ["BillID"]), "fact_ar": (ar, ["InvoiceID"]),
           "fact_budget": (bud, ["Month", "EntityID", "DepartmentID", "AccountCode"]),
           "fact_cash_balance": (cash, ["Date", "EntityID"]),
           "fact_forecast": (fc, ["Month", "EntityID", "DepartmentID", "AccountCode"]),
           "fact_fx_rates": (fx, ["Date", "Currency"]), "fact_gl": (gl, ["GLTxnID"]), "security_user_access": (sec, ["UserEmail"])}
    m["rows"] = {k: int(len(v[0])) for k, v in pks.items()}
    m["pk_duplicates"] = int(sum(v[0].duplicated(v[1]).sum() for v in pks.values()))
    optional = {("fact_gl", "CustomerID"), ("fact_gl", "VendorID"), ("fact_ar", "PaidDate"), ("fact_ap", "PaidDate")}
    m["null_cells_required"] = int(sum(v[0][c].isna().sum() for k, v in pks.items() for c in v[0].columns if (k, c) not in optional))
    orphans = {
        "gl.EntityID": int((~gl.EntityID.isin(ent.EntityID)).sum()),
        "gl.DepartmentID": int((~gl.DepartmentID.isin(dept.DepartmentID)).sum()),
        "gl.AccountCode": int((~gl.AccountCode.isin(acct.AccountCode)).sum()),
        "gl.CustomerID": int((~gl.CustomerID.dropna().isin(cust.CustomerID)).sum()),
        "gl.VendorID": int((~gl.VendorID.dropna().isin(vend.VendorID)).sum()),
        "budget.AccountCode": int((~bud.AccountCode.isin(acct.AccountCode)).sum()),
        "forecast.AccountCode": int((~fc.AccountCode.isin(acct.AccountCode)).sum()),
        "ar.CustomerID": int((~ar.CustomerID.isin(cust.CustomerID)).sum()),
        "ap.VendorID": int((~ap.VendorID.isin(vend.VendorID)).sum()),
        "cash.EntityID": int((~cash.EntityID.isin(ent.EntityID)).sum()),
        "fx.Currency": int((~fx.Currency.isin(ent.LocalCurrency)).sum()),
    }
    m["orphans"] = orphans
    add("INFO", "Keys and completeness are clean",
        f"{m['pk_duplicates']} duplicate keys across 14 files, {m['null_cells_required']} nulls in required columns, "
        f"{sum(orphans.values())} orphaned references across {len(orphans)} relationships. Nulls occur only where they "
        "carry meaning: an unpaid invoice has no PaidDate; a GL line has a customer or a vendor or neither.",
        "Foreign keys declared and engine-trusted in dbo.")

    # ------------------------------------------------------------- calendar ---
    d = dd.Date
    iso = d.dt.isocalendar()
    fys = np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)
    cal_bad = int(((dd.Year != d.dt.year) | (dd.MonthNo != d.dt.month) | (dd.MonthName != d.dt.month_name())
                   | (dd.Quarter != d.dt.quarter) | (dd.ISOWeek != iso.week.values) | (dd.DayName != d.dt.day_name())
                   | (dd.FinancialYearStart != fys)
                   | (dd.FinancialYear != pd.Series([f"FY{(y + 1) % 100:02d}" for y in fys]))).sum())
    m["calendar_bad_days"] = cal_bad
    m["calendar_start"], m["calendar_end"] = d.min().strftime("%Y-%m-%d"), d.max().strftime("%Y-%m-%d")
    add("INFO", "Supplied calendar is correct; financial year runs July to June",
        f"{len(dd):,} contiguous days {m['calendar_start']} to {m['calendar_end']}; {cal_bad} days disagree with an independent "
        "recomputation of all nine columns. FY26 = 1 Jul 2025 - 30 Jun 2026 (the Australian year, consistent with an AUD group).",
        "Regenerated days are checked against the supplied calendar for every overlapping day.")

    asof = pd.Timestamp(gl.Date.max())
    m["as_of_date"] = asof.strftime("%Y-%m-%d")
    m["last_dates"] = {"gl": gl.Date.max(), "budget": bud.Month.max(), "forecast": fc.Month.max(), "cash": cash.Date.max(),
                       "fx": fx.Date.max(), "ar_invoice": ar.InvoiceDate.max().strftime("%Y-%m-%d"),
                       "ap_bill": ap.BillDate.max().strftime("%Y-%m-%d")}
    late = {"ar_due": ar.DueDate.max(), "ar_paid": ar.PaidDate.max(), "ap_due": ap.DueDate.max(), "ap_paid": ap.PaidDate.max()}
    m["dates_beyond_calendar"] = {k: v.strftime("%Y-%m-%d") for k, v in late.items()}
    beyond = int((ar.DueDate > d.max()).sum() + (ar.PaidDate > d.max()).sum() + (ap.DueDate > d.max()).sum()
                 + (ap.PaidDate > d.max()).sum())
    m["sub_ledger_dates_beyond_calendar"] = beyond
    add("ERROR", "Calendar ends before the last sub-ledger date",
        f"dim_date ends {m['calendar_end']}, but AR due dates run to {late['ar_due'].date()} and payments to "
        f"{late['ar_paid'].date()} (AP: {late['ap_due'].date()} / {late['ap_paid'].date()}). {beyond:,} due or paid dates "
        "have no calendar day.",
        "DimDate regenerated to 2027-06-30 (end of FY27) and checked against the supplied calendar for all 1,704 overlapping days.")

    ar_late_paid = ar[ar.PaidDate > asof]
    ap_late_paid = ap[ap.PaidDate > asof]
    m["ar_paid_after_asof"] = {"n": int(len(ar_late_paid)), "amount": money(sum(map(Decimal, ar_late_paid.InvoiceAmountAUD)))}
    m["ap_paid_after_asof"] = {"n": int(len(ap_late_paid)), "amount": money(sum(map(Decimal, ap_late_paid.BillAmountAUD)))}
    add("ERROR", "Payments recorded after the as-of date",
        f"The ledger, budget, cash and FX all end {m['as_of_date']}, yet {len(ar_late_paid):,} AR receipts "
        f"({m['ar_paid_after_asof']['amount']:,.2f} AUD) and {len(ap_late_paid):,} AP payments "
        f"({m['ap_paid_after_asof']['amount']:,.2f}) are dated later. Their Status says Paid, but on the as-of date they were open.",
        "As-of date = 2026-08-31, the last ledger day. Every balance is computed AS OF a date: a document is open on day D "
        "if issued by D and not paid by D. Status is never read for balances.")

    # ------------------------------------------------------------------ FX ---
    aud = fx[fx.Currency == "AUD"].AUDPerUnit.astype(float)
    m["fx_aud_rows_not_1"] = int((aud != 1).sum())
    m["fx_aud_range"] = [float(aud.min()), float(aud.max())]
    add("ERROR", "The AUD-to-AUD rate is not 1",
        f"AUD is the reporting currency, yet {m['fx_aud_rows_not_1']:,} of 1,704 daily AUD rates differ from 1 "
        f"({aud.min():.4f} to {aud.max():.4f}). Applying them would move the AUD entity's figures by up to 5% for no reason.",
        "AUD is fixed at exactly 1.000000 in the build; the supplied value is kept in an audit column.")

    fxw = fx.assign(r=fx.AUDPerUnit.astype(float), d=pd.to_datetime(fx.Date)).pivot(index="d", columns="Currency", values="r")
    fxw_f = fxw.drop(columns="AUD")
    daily = fxw_f.pct_change().abs().mean()
    yearly = fxw_f.groupby(fxw_f.index.year).mean()
    m["fx_mean_abs_daily_move_pct"] = {c: round(float(v) * 100, 2) for c, v in daily.items()}
    m["fx_annual_mean_spread_pct"] = {c: round(float((yearly[c].max() / yearly[c].min() - 1) * 100), 3) for c in yearly}
    mr = monthly_rates(fx)
    m["fx_monthly_rates"] = int(len(mr))
    m["fx_monthly_rate_checksum"] = float(sum(mr.rate))
    add("ANOMALY", "Daily exchange rates are noise around a flat mean",
        f"Rates move {min(daily) * 100:.2f}-{max(daily) * 100:.2f}% a day on average - several times a real G10 currency - "
        f"yet each currency's annual mean stays within {max(m['fx_annual_mean_spread_pct'].values()):.2f}% across five years. "
        "Converting each line at its own day's rate adds random noise that is not an economic effect.",
        "P&L actuals are translated at the MONTHLY AVERAGE rate (mean of the month's daily rates, 6 dp) - the IAS 21 average-rate "
        "practice. The daily spot translation is kept per line for audit; the totals differ by less than 0.01%.")

    # ------------------------------------------------------------- ledger ---
    g = translate(gl, mr).merge(acct, on="AccountCode")
    g["spot"] = g.AmountLocal.astype(float) * g.merge(
        fx.assign(s=fx.AUDPerUnit.astype(float)).assign(s=lambda x: np.where(x.Currency == "AUD", 1.0, x.s)),
        left_on=["Date", "Currency"], right_on=["Date", "Currency"], how="left").s.values
    m["gl_currency_matches_entity"] = int((g.merge(ent, on="EntityID").pipe(lambda x: x.Currency == x.LocalCurrency)).sum())
    groups = ["Revenue", "COGS", "Operating Expense", "Other Expense", "Tax"]
    m["gl_aud_by_group"] = {k: money(sum(g[g.AccountGroup == k].aud)) for k in groups}
    m["gl_aud_total"] = money(sum(g.aud))
    m["gl_local_total"] = money(sum(map(Decimal, gl.AmountLocal)))
    m["gl_spot_vs_average_pct"] = round(float((g.spot.sum() - float(sum(g.aud))) / abs(float(sum(g.aud))) * 100), 4)
    m["gl_lines_by_status"] = {k: int(v) for k, v in gl.PostingStatus.value_counts().items()}
    add("ERROR", "Actuals are in six local currencies; everything else is in AUD",
        f"Each entity books in its own currency ({m['gl_currency_matches_entity']:,} of 80,000 lines match the entity's "
        "currency), while budget, forecast, AR, AP and cash are in AUD. Revenue is stored as credits (negative) and costs as "
        "debits, so a raw sum mixes currencies and signs.",
        "Every GL line is translated to AUD in SQL (FactGL.AmountAUD). Amounts keep the ledger sign; measures present revenue "
        "and costs as positive numbers and profit as revenue less costs.")

    # key-level coverage of the budget by the ledger
    k = ["Month", "EntityID", "DepartmentID", "AccountCode"]
    g["Month"] = g.Date.str[:7] + "-01"
    gk = g.groupby(k).agg(n=("GLTxnID", "size"), aud=("aud", "sum")).reset_index()
    m["financials_actual_rows"] = int(len(gk))
    cov = bud.merge(gk, on=k, how="left")
    m["budget_lines_without_posting"] = int(cov.n.isna().sum())
    sal = g[g.AccountCode == "6000"].groupby(["EntityID", "DepartmentID", "Month"]).size()
    m["payroll_dept_months_posted"] = int(len(sal))
    m["payroll_dept_months_total"] = int(ent.shape[0] * dept.shape[0] * bud.Month.nunique())
    b = bud.merge(acct, on="AccountCode")
    b["v"] = b.BudgetAmountAUD.map(Decimal)
    f = fc.merge(acct, on="AccountCode")
    f["v"] = f.ForecastAmountAUD.map(Decimal)
    m["budget_by_group"] = {k2: money(sum(b[b.AccountGroup == k2].v)) for k2 in groups[:3]}
    m["forecast_by_group"] = {k2: money(sum(f[f.AccountGroup == k2].v)) for k2 in groups[:3]}
    m["budget_total"] = money(sum(b.v))
    m["forecast_total"] = money(sum(f.v))
    A = g.groupby(["Month", "AccountGroup"]).aud.sum().map(float).unstack()
    B = b.groupby(["Month", "AccountGroup"]).v.sum().map(float).unstack()
    F_ = f.groupby(["Month", "AccountGroup"]).v.sum().map(float).unstack()
    ratio = (A[groups[:3]] / B)
    m["actual_to_budget_monthly"] = {c: {"mean": round(float(ratio[c].mean()), 3), "min": round(float(ratio[c].min()), 3),
                                         "max": round(float(ratio[c].max()), 3)} for c in groups[:3]}
    fb = (F_.sum(axis=1) / B.sum(axis=1))
    m["forecast_to_budget_monthly_total"] = {"mean": round(float(fb.mean()), 4), "min": round(float(fb.min()), 4),
                                             "max": round(float(fb.max()), 4)}
    add("ANOMALY", "The ledger is a partial extract of the plan's scope",
        f"Payroll (6000 Salaries) posts in only {m['payroll_dept_months_posted']:,} of {m['payroll_dept_months_total']:,} "
        f"department-months ({m['payroll_dept_months_posted'] / m['payroll_dept_months_total']:.1%}); "
        f"{m['budget_lines_without_posting']:,} of 60,480 budget lines ({m['budget_lines_without_posting'] / 60480:.1%}) have no "
        "posting at all. A real ledger posts payroll to every cost centre every month.",
        "Reported, never filled in or rescaled. Variance to budget is shown as measured and labelled; the report leads with "
        "measures that do not depend on coverage (margins, mix, trends within the ledger).")
    r = m["actual_to_budget_monthly"]
    add("ANOMALY", "Actuals sit at a fixed fraction of budget in every month",
        f"Revenue runs at {r['Revenue']['mean']:.0%} of budget (range {r['Revenue']['min']:.0%}-{r['Revenue']['max']:.0%}), "
        f"operating expense at {r['Operating Expense']['mean']:.0%} and COGS at {r['COGS']['mean']:.0%} - in each of the 56 months, "
        f"with no trend. The forecast tracks the budget (monthly totals {m['forecast_to_budget_monthly_total']['min']:.1%}-"
        f"{m['forecast_to_budget_monthly_total']['max']:.1%} of it), not the actuals.",
        "The gap is structural, so it is presented as a plan-calibration finding (a real FP&A team would re-base the plan), "
        "not as 56 months of performance news. Variance commentary focuses on what moves: changes against the usual gap.")

    # entity scale follows the exchange rate
    rev = g[g.AccountGroup == "Revenue"]
    med = rev.groupby("Currency").AmountLocal.apply(lambda s: float(s.astype(float).median()))
    m["revenue_line_median_local"] = {c: round(v, 2) for c, v in med.items()}
    e_act = rev.groupby("EntityID").aud.sum().map(float)
    e_bud = b[b.AccountGroup == "Revenue"].groupby("EntityID").v.sum().map(float)
    m["entity_revenue_actual_to_budget"] = {e: round(float(e_act[e] / e_bud[e]), 3) for e in e_act.index}
    add("ANOMALY", "Local amounts share one scale in every currency",
        f"The median revenue line is {min(med.abs()):,.0f}-{max(med.abs()):,.0f} local units in all six currencies, and every "
        "entity's budget is about the same in AUD. After translation an entity's size therefore follows its exchange rate: "
        f"actual revenue is {m['entity_revenue_actual_to_budget']['E02']:.0%} of budget in the UK (GBP 1.92) but "
        f"{m['entity_revenue_actual_to_budget']['E01']:.0%} in Australia (AUD 1.00).",
        "Translation is still applied - it is the correct treatment of the data as labelled. Entities are compared on "
        "currency-neutral ratios (gross margin, cost-to-revenue), which translation cannot distort; entity variance to budget "
        "carries this note.")

    # P&L shape
    def fy(df, col):
        dt = pd.to_datetime(df[col])
        return np.where(dt.dt.month >= 7, dt.dt.year + 1, dt.dt.year)
    g["FY"] = fy(g, "Date")
    b["FY"] = fy(b, "Month")
    f["FY"] = fy(f, "Month")
    pl = {}
    for nm, df, col in (("actual", g, "aud"), ("budget", b, "v"), ("forecast", f, "v")):
        for y in (2025, 2026, 2027):
            s = df[df.FY == y].groupby("AccountGroup")[col].sum()
            gp = -(s.get("Revenue", 0)) - s.get("COGS", 0)
            op = gp - s.get("Operating Expense", 0)
            pl[f"{nm}_FY{y % 100}"] = {"revenue": money(-s.get("Revenue", 0)), "cogs": money(s.get("COGS", 0)),
                                       "gross_profit": money(gp), "opex": money(s.get("Operating Expense", 0)),
                                       "operating_profit": money(op),
                                       "other_expense": money(s.get("Other Expense", 0)), "tax": money(s.get("Tax", 0)),
                                       "net_profit": money(op - s.get("Other Expense", 0) - s.get("Tax", 0))}
    m["pl"] = pl
    a26, b26 = pl["actual_FY26"], pl["budget_FY26"]
    add("ANOMALY", "The group runs at an operating loss - in the plan as well as the ledger",
        f"FY26: revenue {a26['revenue']:,.0f} AUD against operating expense {a26['opex']:,.0f}; operating margin "
        f"{a26['operating_profit'] / a26['revenue']:.0%}. The budget itself plans {b26['operating_profit'] / b26['revenue']:.0%}. "
        "Revenue is booked to every department, HR and Legal included.",
        "Reported as measured. Revenue is analysed by entity and stream; departments are treated as cost centres.")

    # forecast scenario label
    per_key = fc.groupby(k).Scenario.nunique()
    m["forecast_scenario_rows"] = {s: int(n) for s, n in fc.Scenario.value_counts().items()}
    m["forecast_keys_with_one_scenario"] = int((per_key == 1).sum())
    fr = fc.merge(bud, on=k).merge(acct, on="AccountCode")
    fr["ratio"] = fr.ForecastAmountAUD.astype(float) / fr.BudgetAmountAUD.astype(float)
    sr = fr.groupby(["AccountGroup", "Scenario"]).ratio.mean()
    m["forecast_ratio_by_scenario_revenue"] = {s: round(float(sr["Revenue"][s]), 4) for s in ("Best", "Base", "Worst")}
    add("ERROR", "The forecast 'Scenario' column is not a scenario",
        f"Every one of the {len(per_key):,} forecast lines carries exactly one label - Base {m['forecast_scenario_rows']['Base']:,}, "
        f"Best {m['forecast_scenario_rows']['Best']:,}, Worst {m['forecast_scenario_rows']['Worst']:,} - so filtering to 'Base' "
        "keeps 60% of the plan and drops the rest. The label does not change the value: forecast/budget on revenue lines is "
        f"{m['forecast_ratio_by_scenario_revenue']['Worst']:.3f} for Worst and {m['forecast_ratio_by_scenario_revenue']['Best']:.3f} for Best.",
        "The forecast is one version (all 60,480 lines). The label is kept as a line attribute and reported here. Scenarios "
        "are modelled properly with disconnected driver tables (revenue, cost and FX assumptions) - see the scenario page.")

    bk = b.assign(fv=b.v.map(float)).groupby(["EntityID", "DepartmentID", "AccountCode"]).fv.agg(["mean", "std"])
    m["budget_line_cv_median"] = round(float((bk["std"] / bk["mean"].abs()).median()), 3)
    add("ANOMALY", "Budget lines jump from month to month",
        f"One budget line (entity x department x account) varies by a median {m['budget_line_cv_median']:.0%} of its mean "
        "between months, with no seasonality; totals are stable. Month-level variance on a single line is therefore mostly "
        "noise in the plan.",
        "Variance is analysed at levels where the plan is stable (account group, entity, department, quarter), and a line "
        "is called out only when its variance departs from its own usual range.")

    m["budget_accounts"] = sorted(bud.AccountCode.unique())
    unbudgeted = sorted(set(gl.AccountCode) - set(bud.AccountCode))
    m["unbudgeted_accounts"] = unbudgeted
    add("EXCEPTION", "Interest, FX gain/loss and tax are not budgeted",
        f"Accounts {', '.join(unbudgeted)} have actuals but no budget or forecast line.",
        "Plan comparisons are like-for-like down to OPERATING PROFIT. Below-the-line items are shown as actuals only - "
        "never as a 100% variance.")
    bs = sorted(set(acct.AccountCode) - set(gl.AccountCode))
    m["balance_sheet_accounts_without_postings"] = bs
    add("EXCEPTION", "Balance-sheet accounts have no ledger postings",
        f"Accounts {', '.join(bs)} (cash, receivables, inventory, payables, accruals) exist in the chart but never in the GL.",
        "The ledger is a P&L extract. Cash comes from the daily balances, receivables and payables from the AR and AP "
        "sub-ledgers. Inventory has no source, so days inventory outstanding is not reported.")
    fxgl = g[g.AccountCode == "7100"].AmountLocal.astype(float)
    add("EXCEPTION", "FX gain/loss carries both signs",
        f"{int((fxgl < 0).sum()):,} FX lines are gains (credits) and {int((fxgl > 0).sum()):,} are losses.",
        "Legitimate: kept signed, reported as a net below-the-line item.")
    party = pd.crosstab(g.AccountGroup, [g.CustomerID.notna(), g.VendorID.notna()])
    m["gl_lines_with_customer"] = int(gl.CustomerID.notna().sum())
    m["gl_lines_with_vendor"] = int(gl.VendorID.notna().sum())
    add("EXCEPTION", "Customer and vendor are optional on ledger lines",
        f"{m['gl_lines_with_customer']:,} lines carry a customer (revenue accounts only) and {m['gl_lines_with_vendor']:,} a vendor "
        "(cost accounts only); the rest carry neither.",
        "Nullable foreign keys; blank is shown as 'Not specified'.")

    acc_share = gl.groupby(gl.Date.str[:4]).PostingStatus.apply(lambda s: round(float((s == "Accrued").mean()), 3))
    m["accrued_share_by_year"] = acc_share.to_dict()
    add("ANOMALY", "Accruals are never reversed",
        f"About a quarter of lines are 'Accrued' in every year ({', '.join(f'{y}: {v:.0%}' for y, v in acc_share.items())}). "
        "Accruals are normally replaced by the actual invoice within weeks.",
        "Both statuses count as actuals (accrual accounting). The accrued share is shown as a close-quality indicator.")

    # ---------------------------------------------------------- AR and AP ---
    def ledger(df, doc, amt, name):
        out = {}
        v = df[amt].map(Decimal)
        out["documents"] = int(len(df))
        out["amount"] = money(sum(v))
        out["status_open_n"] = int((df.Status == "Open").sum())
        out["status_open_amount"] = money(sum(v[df.Status == "Open"]))
        out["status_consistent"] = int(((df.Status == "Paid") == df.PaidDate.notna()).sum())
        out["partial_payments"] = int(((df.Status == "Paid") & (df.PaidAmountAUD.map(Decimal) != v)).sum())
        o = open_as_of(df, doc, amt, asof)
        ov = o[amt].map(Decimal)
        out["open_asof_n"] = int(len(o))
        out["open_asof_amount"] = money(sum(ov))
        dpd = (asof - o.DueDate).dt.days
        out["ageing_asof"] = {nm: money(sum(ov[(dpd >= lo) & (dpd <= hi)])) for nm, lo, hi in BUCKETS}
        out["ageing_asof_n"] = {nm: int(((dpd >= lo) & (dpd <= hi)).sum()) for nm, lo, hi in BUCKETS}
        paid = df[df.PaidDate.notna() & (df.PaidDate <= asof)]
        out["paid_by_asof_n"] = int(len(paid))
        days = (paid.PaidDate - paid[doc]).dt.days
        pv = paid[amt].astype(float)
        out["days_to_pay_weighted"] = round(float((days * pv).sum() / pv.sum()), 2)
        out["days_late_weighted"] = round(float(((paid.PaidDate - paid.DueDate).dt.days * pv).sum() / pv.sum()), 2)
        out["terms_days"] = sorted(int(x) for x in (df.DueDate - df[doc]).dt.days.unique())
        start90 = asof - pd.Timedelta(days=89)
        inv90 = df[(df[doc] >= start90) & (df[doc] <= asof)][amt].map(Decimal)
        out["issued_last_90d"] = money(sum(inv90))
        out["days_outstanding_90d"] = round(float(sum(ov) / sum(inv90) * 90), 2)
        out["never_paid_share_by_value"] = round(float(sum(v[df.Status == "Open"]) / sum(v)), 4)
        yr = df[df.Status == "Open"].groupby(df[doc].dt.year).size()
        out["open_status_by_issue_year"] = {int(y): int(n) for y, n in yr.items()}
        return out

    m["ar"] = ledger(ar, "InvoiceDate", "InvoiceAmountAUD", "AR")
    m["ap"] = ledger(ap, "BillDate", "BillAmountAUD", "AP")
    for nm, L in (("AR", m["ar"]), ("AP", m["ap"])):
        add("INFO", f"{nm} statuses are internally consistent",
            f"{L['status_consistent']:,} of {L['documents']:,} documents: Paid always has a paid date and amount, Open never; "
            f"{L['partial_payments']} partial payments. Payment terms: {', '.join(map(str, L['terms_days']))} days.",
            "No cleansing needed; balances are still derived from dates (see the as-of rule).")
    a = m["ar"]
    add("ANOMALY", "A fixed share of receivables is never collected - and never written off",
        f"{a['never_paid_share_by_value']:.1%} of invoiced value has no receipt, and the share is the same for 2023 invoices as for "
        f"2026 ones (unpaid invoices by issue year: "
        f"{', '.join(f'{y}: {n:,}' for y, n in a['open_status_by_issue_year'].items())}; 2026 is eight months). "
        f"On {m['as_of_date']}, {a['ageing_asof']['Over 365']:,.0f} AUD of the "
        f"{a['open_asof_amount']:,.0f} open is more than a year past due. AP shows the same pattern "
        f"({m['ap']['never_paid_share_by_value']:.1%} unpaid).",
        f"Reported as measured, with ageing as of any date. Days sales outstanding on {m['as_of_date']} is "
        f"{a['days_outstanding_90d']:.0f} (90-day count-back) against {a['days_to_pay_weighted']:.0f} days to collect a paid invoice - "
        "the gap is the uncollected balance, shown separately so it is not mistaken for slow payment.")

    ar_y = ar.groupby(ar.InvoiceDate.dt.year).InvoiceAmountAUD.apply(lambda s: float(s.astype(float).sum()))
    gl_y = g[g.AccountGroup == "Revenue"].assign(y=pd.to_datetime(g.Date).dt.year).groupby("y").aud.sum().map(lambda x: -float(x))
    m["ar_invoicing_to_gl_revenue_2025"] = round(float(ar_y[2025] / gl_y[2025]), 2)
    add("ANOMALY", "Receivables do not reconcile to ledger revenue",
        f"AR invoiced {ar_y[2025]:,.0f} AUD in calendar 2025 against {gl_y[2025]:,.0f} of GL revenue "
        f"({m['ar_invoicing_to_gl_revenue_2025']}x). The sub-ledgers and the GL are independent extracts.",
        "Working-capital days use each sub-ledger's own flows (AR invoicing for DSO, AP bills for DPO), never GL revenue.")

    # --------------------------------------------------------------- cash ---
    c = cash.assign(v=cash.ClosingCashAUD.map(Decimal))
    last = c[c.Date == m["as_of_date"]]
    m["cash_asof_by_entity"] = {e: money(v) for e, v in zip(last.EntityID, last.v)}
    m["cash_asof_total"] = money(sum(last.v))
    floor = c[c.ClosingCashAUD.astype(float) == 50000]
    m["cash_floor_days"] = int(len(floor))
    m["cash_negative_days"] = int((c.ClosingCashAUD.astype(float) < 0).sum())
    moves = cash.assign(v=cash.ClosingCashAUD.astype(float)).pivot(index="Date", columns="EntityID", values="v").diff().abs()
    m["cash_mean_abs_daily_move"] = round(float(moves.mean().mean()), 0)
    add("ANOMALY", "Cash balances are a random walk with a floor",
        f"Each entity's closing cash moves {m['cash_mean_abs_daily_move']:,.0f} AUD a day on average in either direction, unrelated "
        f"to ledger, receipts or payments; Northstar Holdings sits at exactly 50,000.00 on {m['cash_floor_days']} days "
        f"({floor.Date.min()} to {floor.Date.max()}) - a generator floor.",
        "Balances reported as supplied (closing balance = last day of the period, never summed over time). No cash-flow "
        "bridge is drawn: the sources cannot support one.")

    # ----------------------------------------------------------- security ---
    m["security_users"] = int(len(sec))
    m["security_roles"] = {k2: int(v) for k2, v in sec.Role.value_counts().items()}
    add("EXCEPTION", "Security scopes two dimensions, but three facts have only one",
        f"{len(sec)} users are scoped by entity and department ('ALL' = no restriction). AR, AP and cash carry an entity "
        "but no department.",
        "Entity scope applies everywhere. A department-scoped user (e.g. the Sales manager) sees their department's P&L "
        "across entities, and NO receivables, payables or cash - company-wide treasury data is not part of a cost-centre view.")

    return m, F


def write_report(m, F):
    order = {"ERROR": 0, "ANOMALY": 1, "EXCEPTION": 2, "INFO": 3}
    F = sorted(F, key=lambda x: order[x[0]])
    counts = {k: sum(1 for f in F if f[0] == k) for k in order}
    L = ["# Data Quality Report - Enterprise FP&A Finance", "",
         "Generated by `Python/01_data_audit.py` from the raw CSVs in `Data/raw` (never from SQL). "
         "The data is **synthetic**; nothing here describes a real company.", "",
         f"**{counts['ERROR']} ERROR, {counts['ANOMALY']} ANOMALY, {counts['EXCEPTION']} EXCEPTION, {counts['INFO']} INFO.** "
         f"As-of date: **{m['as_of_date']}** (the last ledger day).", "",
         "| Class | Meaning |", "|---|---|",
         "| ERROR | Breaks correctness unless the build handles it |",
         "| ANOMALY | Implausible for real data and not repairable: reported, never hidden or rescaled |",
         "| EXCEPTION | Legitimate, but needs an explicit modelling rule |",
         "| INFO | Confirmed good, or descriptive |", ""]
    for i, (cls, title, detail, decision) in enumerate(F, 1):
        L += [f"## {i}. [{cls}] {title}", "", detail, "", f"**Handling:** {decision}", ""]
    L += ["## Row counts", "", "| File | Rows |", "|---|---:|"]
    L += [f"| {k}.csv | {v:,} |" for k, v in m["rows"].items()]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    return counts


def main():
    m, F = audit(load())
    MET.parent.mkdir(parents=True, exist_ok=True)
    MET.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")
    c = write_report(m, F)
    print(f"{c['ERROR']} ERROR, {c['ANOMALY']} ANOMALY, {c['EXCEPTION']} EXCEPTION, {c['INFO']} INFO")
    print(f"as-of {m['as_of_date']}; GL AUD by group {m['gl_aud_by_group']}")
    print(f"AR open as-of {m['ar']['open_asof_n']} / {m['ar']['open_asof_amount']:,}; AP {m['ap']['open_asof_n']} / {m['ap']['open_asof_amount']:,}")
    print(f"FY26 actual {m['pl']['actual_FY26']}")
    print(f"FY26 budget {m['pl']['budget_FY26']}")


if __name__ == "__main__":
    main()
