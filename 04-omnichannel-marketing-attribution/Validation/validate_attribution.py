# -*- coding: utf-8 -*-
"""
Independent check of the SQL attribution engine (SQL/07_build_attribution.sql).

Recomputes all five attribution models from the RAW CSVs with pandas - no SQL
involved - then compares every one of the 874,690 weights and attributed
revenue amounts against analytics.vw_FactAttributionCredit.

Two implementations written separately, in different languages, agreeing row
by row is far stronger evidence than either one checking itself.

Usage:  python Validation/validate_attribution.py [--server localhost\\SQLEXPRESS]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
HALF_LIFE, PB_FIRST, PB_LAST = 7.0, 0.40, 0.40     # must match dbo.ModelConfig
MODELS = {1: "First Touch", 2: "Last Touch", 3: "Linear", 4: "Position-Based", 5: "Time-Decay"}


def expected_credit():
    tp = pd.read_csv(RAW / "fact_touchpoints.csv", parse_dates=["TouchDate"])
    ld = pd.read_csv(RAW / "fact_leads.csv", parse_dates=["CreatedDate"])
    rv = pd.read_csv(RAW / "fact_revenue.csv")

    tp = tp.sort_values(["LeadID", "TouchDate", "TouchSequence"]).reset_index(drop=True)
    g = tp.groupby("LeadID")
    k = (g.cumcount() + 1).astype(float)
    n = g.TouchpointID.transform("size").astype(float)
    days = (tp.LeadID.map(ld.set_index("LeadID").CreatedDate) - tp.TouchDate).dt.days.astype(float)
    raw = np.power(0.5, days / HALF_LIFE)
    decay = raw / raw.groupby(tp.LeadID).transform("sum")
    middle = (1.0 - PB_FIRST - PB_LAST) / (n - 2).where(n > 2, 1.0)
    position = np.select([n == 1, n == 2, k == 1, k == n], [1.0, 0.5, PB_FIRST, PB_LAST], default=middle)

    weights = {1: (k == 1).astype(float), 2: (k == n).astype(float), 3: 1.0 / n,
               4: pd.Series(position, index=tp.index), 5: decay}
    revenue = tp.LeadID.map(rv.groupby("LeadID").RevenueAmount.sum()).fillna(0.0)
    frames = [pd.DataFrame({"TouchpointID": tp.TouchpointID, "ChannelID": tp.ChannelID, "ModelKey": mk,
                            "ExpWeight": w.values, "ExpRevenue": (w * revenue).values})
              for mk, w in weights.items()]
    return pd.concat(frames, ignore_index=True)


def actual_credit(server):
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server") if d in drivers), drivers[-1])
    cn = pyodbc.connect(f"DRIVER={{{driver}}};SERVER={server};DATABASE=MarketingAttributionBI;"
                        "Trusted_Connection=yes;TrustServerCertificate=yes;")
    q = ("SELECT TouchpointID, ModelKey, CAST(CreditWeight AS FLOAT) AS CreditWeight, "
         "CAST(AttributedRevenueUSD AS FLOAT) AS AttributedRevenueUSD FROM analytics.vw_FactAttributionCredit")
    rows = cn.cursor().execute(q).fetchall()
    cn.close()
    return pd.DataFrame.from_records([tuple(r) for r in rows],
                                     columns=["TouchpointID", "ModelKey", "CreditWeight", "AttributedRevenueUSD"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=r"localhost\SQLEXPRESS")
    args = ap.parse_args()

    exp, act = expected_credit(), actual_credit(args.server)
    j = exp.merge(act, on=["TouchpointID", "ModelKey"], how="outer", indicator=True)
    missing = int((j._merge != "both").sum())
    j = j[j._merge == "both"]
    dw = (j.ExpWeight - j.CreditWeight).abs()
    dr = (j.ExpRevenue - j.AttributedRevenueUSD).abs()

    checks = [
        ("rows compared (5 x 174,938)", 874690, len(j), 0),
        ("rows present on only one side", 0, missing, 0),
        ("weights differing by more than 1e-12", 0, int((dw > 1e-12).sum()), 0),
        ("attributed revenue differing by more than 0.000001", 0, int((dr > 1e-6).sum()), 0),
    ]
    fails = 0
    print(f"max weight difference   {dw.max():.3e}")
    print(f"max revenue difference  {dr.max():.3e}\n")
    for name, expected, actual, tol in checks:
        ok = abs(expected - actual) <= tol
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:52s} expected {expected:<9} got {actual}")

    ch = pd.read_csv(RAW / "dim_channel.csv").set_index("ChannelID").ChannelName
    share = (j.assign(Channel=j.ChannelID.map(ch), Model=j.ModelKey.map(MODELS))
              .pivot_table(index="Channel", columns="Model", values="AttributedRevenueUSD", aggfunc="sum"))
    share = (share / share.sum()).mul(100).round(2)[list(MODELS.values())]
    print("\nShare of attributed revenue by channel, % (SQL values, confirmed above):")
    print(share.to_string())
    print(f"\nRESULT: {len(checks) - fails} of {len(checks)} checks passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
