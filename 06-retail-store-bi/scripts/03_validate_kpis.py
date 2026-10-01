"""
03_validate_kpis.py
-------------------
Independent recalculation of every headline KPI and analytical finding from the
cleaned extract. These values are the reconciliation baseline for the DAX
measures in the Power BI model (Evidence: "calculations validated").

Output: outputs/kpi_validation.csv  (Area, Metric, Dimension, Value)
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def time_of_day(h):
    # Store trading hours are 10:00-21:00 (last purchase 20:59)
    if h < 12:
        return "Morning (10:00-11:59)"
    if h < 17:
        return "Afternoon (12:00-16:59)"
    return "Evening (17:00-20:59)"


def main():
    df = pd.read_csv(OUT / "cleaned_retail_sales.csv", parse_dates=["Date"])
    cl = pd.read_csv(OUT / "model_results.csv")[["SalesKey", "ClusterID"]]
    prof = pd.read_csv(OUT / "cluster_profiles.csv")[["ClusterID", "ClusterName"]]
    df = df.merge(cl, on="SalesKey").merge(prof, on="ClusterID")
    df["Month"] = df.Date.dt.strftime("%Y-%m")
    df["TimeOfDay"] = df.Hour.map(time_of_day)
    df["DayName"] = df.Date.dt.day_name()

    rows = []

    def add(area, metric, value, dim=""):
        rows.append({"Area": area, "Metric": metric, "Dimension": dim, "Value": value})

    sales = df.TotalSales.sum()
    core = {
        "Total Sales": sales,
        "Total Gross Income": df.GrossIncome.sum(),
        "Total COGS": df.COGS.sum(),
        "Total Tax": df.Tax.sum(),
        "Total Quantity Sold": df.Quantity.sum(),
        "Total Transactions": len(df),
        "Distinct Invoice IDs": df.InvoiceID.nunique(),
        "Average Transaction Value": sales / len(df),
        "Average Unit Price": df.UnitPrice.mean(),
        "Average Rating": df.Rating.mean(),
        "Gross Margin %": df.GrossIncome.sum() / sales,
        "Quantity per Transaction": df.Quantity.sum() / len(df),
        "Gross Income per Transaction": df.GrossIncome.sum() / len(df),
        "Member Sales": df.loc[df.CustomerType == "Member", "TotalSales"].sum(),
        "Normal Customer Sales": df.loc[df.CustomerType == "Normal", "TotalSales"].sum(),
        "Member Sales %": df.loc[df.CustomerType == "Member", "TotalSales"].sum() / sales,
        "Female Customer Sales %": df.loc[df.Gender == "Female", "TotalSales"].sum() / sales,
        "Male Customer Sales %": df.loc[df.Gender == "Male", "TotalSales"].sum() / sales,
        "High Rating % (>=8)": (df.Rating >= 8).mean(),
        "Trading Days": df.Date.nunique(),
    }
    for k, v in core.items():
        add("Core KPI", k, round(v, 4))

    def by(dim, area):
        g = df.groupby(dim).agg(Sales=("TotalSales", "sum"), GrossIncome=("GrossIncome", "sum"),
                                Quantity=("Quantity", "sum"), Transactions=("SalesKey", "size"),
                                AvgRating=("Rating", "mean"))
        g["ATV"] = g.Sales / g.Transactions
        g["SalesShare"] = g.Sales / sales
        g["GM%"] = g.GrossIncome / g.Sales
        for idx, r in g.sort_values("Sales", ascending=False).iterrows():
            for m in g.columns:
                add(area, m, round(r[m], 4), str(idx))
        return g

    by("Branch", "Branch")
    by("City", "City")
    by("ProductLine", "Product Line")
    by("CustomerType", "Customer Type")
    by("Gender", "Gender")
    by("PaymentMethod", "Payment")
    by("TimeOfDay", "Time of Day")
    by("Hour", "Hour")
    by("DayName", "Day of Week")
    by("ClusterName", "Cluster")

    m = df.groupby("Month").agg(Sales=("TotalSales", "sum"), Transactions=("SalesKey", "size"),
                                Days=("Date", "nunique"))
    m["PrevMonthSales"] = m.Sales.shift(1)
    m["MoM %"] = m.Sales / m.PrevMonthSales - 1
    m["AvgDailySales"] = m.Sales / m.Days
    m["Cumulative"] = m.Sales.cumsum()
    for idx, r in m.iterrows():
        for c in m.columns:
            add("Month", c, None if pd.isna(r[c]) else round(r[c], 4), idx)

    bp = df.pivot_table(index="Branch", columns="ProductLine", values="TotalSales", aggfunc="sum")
    for b in bp.index:
        for p in bp.columns:
            add("Branch x Product", "Sales", round(bp.loc[b, p], 2), f"{b} | {p}")
    cp = df.pivot_table(index="CustomerType", columns="ProductLine", values="TotalSales", aggfunc="sum")
    for c in cp.index:
        for p in cp.columns:
            add("CustomerType x Product", "Sales", round(cp.loc[c, p], 2), f"{c} | {p}")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "kpi_validation.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
