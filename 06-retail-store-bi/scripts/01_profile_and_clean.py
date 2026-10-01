"""
01_profile_and_clean.py
-----------------------
Profiles the raw ICT701 RetailStore workbook and produces a cleaned, typed
extract that mirrors the Power Query (M) ETL in the Power BI semantic model.

The cleaned file is used by the K-Means script and by 03_validate_kpis.py to
reconcile the Power BI measures. Power BI itself loads the raw Excel workbook
and applies the same rules in Power Query, so the BI model never depends on
this CSV.

Outputs
  outputs/cleaned_retail_sales.csv
  outputs/data_quality_profile.csv
"""
from pathlib import Path
import datetime as dt

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ICT701 Assignment1_RetailStore_Dataset (1).xlsx"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

SHEET = "RetailStore Dataset "  # note: the source sheet name has a trailing space

RENAME = {
    "Invoice ID": "InvoiceID",
    "Branch": "Branch",
    "City": "City",
    "Customer type": "CustomerType",
    "Gender": "Gender",
    "Product line": "ProductLine",
    "Unit price": "UnitPrice",
    "Quantity": "Quantity",
    "Tax 5%": "Tax",
    "Total": "TotalSales",
    "Date": "Date",
    "Time": "Time",
    "Payment": "PaymentMethod",
    "cogs": "COGS",
    "gross margin percentage": "GrossMarginPctSource",
    "gross income": "GrossIncome",
    "Rating": "Rating",
}


def fix_date(v):
    """Source dates are mixed.
    * Text cells ("1/27/2022") are US month/day/year.
    * True Excel date cells were mis-parsed day-first at entry, so month and
      day are swapped (e.g. 2022-05-01 is really 5 Jan 2022). Swapping them
      puts every value inside the documented Jan-Mar 2022 period.
    """
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return dt.date(v.year, v.day, v.month)
    if isinstance(v, str):
        m, d, y = v.strip().split("/")
        return dt.date(int(y), int(m), int(d))
    raise ValueError(f"Unexpected date value {v!r}")


def main():
    raw = pd.read_excel(SOURCE, sheet_name=SHEET, dtype=object)
    raw.columns = [c.strip() for c in raw.columns]

    # ---------------- profile ----------------
    prof = []
    for c in raw.columns:
        s = raw[c]
        prof.append({
            "column": c,
            "python_types": "; ".join(f"{k}:{v}" for k, v in s.map(lambda x: type(x).__name__).value_counts().items()),
            "nulls": int(s.isna().sum()),
            "distinct": int(s.nunique()),
        })
    pd.DataFrame(prof).to_csv(OUT / "data_quality_profile.csv", index=False)

    # ---------------- clean ----------------
    df = raw.rename(columns=RENAME).copy()
    df.insert(0, "SalesKey", np.arange(1, len(df) + 1))  # surrogate key = source row order
    for c in ["InvoiceID", "Branch", "City", "CustomerType", "Gender", "ProductLine", "PaymentMethod"]:
        df[c] = df[c].astype(str).str.strip()
    for c in ["UnitPrice", "Tax", "TotalSales", "COGS", "GrossMarginPctSource", "GrossIncome", "Rating"]:
        df[c] = df[c].astype(float)
    df["Quantity"] = df["Quantity"].astype(int)
    df["Date"] = df["Date"].map(fix_date)
    df["Time"] = df["Time"].map(lambda t: t.strftime("%H:%M:%S"))
    df["Hour"] = df["Time"].str[:2].astype(int)
    df["DateKey"] = pd.to_datetime(df["Date"]).dt.strftime("%Y%m%d").astype(int)

    # ---------------- checks ----------------
    assert len(df) == 1000, "row loss"
    assert df["Date"].min() >= dt.date(2022, 1, 1) and df["Date"].max() <= dt.date(2022, 3, 31)
    assert not df.duplicated(subset=[c for c in df.columns if c != "SalesKey"]).any(), "true duplicate rows found"
    assert np.allclose(df.TotalSales, df.COGS + df.Tax)
    assert np.allclose(df.GrossIncome, df.Tax)

    df.to_csv(OUT / "cleaned_retail_sales.csv", index=False)

    dup_ids = df.InvoiceID.value_counts()
    print(f"rows={len(df)}  distinct InvoiceID={df.InvoiceID.nunique()}  ids repeated={(dup_ids > 1).sum()}")
    print(f"date range {df.Date.min()} .. {df.Date.max()}  distinct dates={df.Date.nunique()}")
    print("cleaned extract written to", OUT / "cleaned_retail_sales.csv")


if __name__ == "__main__":
    main()
