"""
05_diagrams.py
--------------
Renders the BI architecture and the star-schema diagrams (evidence for the report).
Outputs: outputs/diagram_bi_architecture.png, outputs/diagram_star_schema.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / "outputs"
BG, CARD, BORDER, TEXT, MUTED, LAV, PINK = "#0A0A0F", "#16161F", "#2E2E3E", "#F4F3FF", "#A3A1B8", "#A99BFF", "#FF8FC7"


def box(ax, x, y, w, h, title, lines=(), edge=BORDER, title_color=TEXT):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=CARD, ec=edge, lw=1.4))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", color=title_color, fontsize=10.5, weight="bold")
    for i, l in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.55 - i * 0.26, l, ha="center", va="top", color=MUTED, fontsize=8)


def arrow(ax, x1, y1, x2, y2, color=LAV):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, color=color, lw=1.6))


def architecture():
    fig, ax = plt.subplots(figsize=(15, 7.2), facecolor=BG)
    ax.set_xlim(0, 15); ax.set_ylim(0, 7.2); ax.axis("off")
    ax.text(0.3, 6.85, "Retail Store BI — System Architecture", color=TEXT, fontsize=15, weight="bold", va="top")
    ax.text(0.3, 6.45, "Source → ETL → Staging → Data warehouse (star schema) → Semantic model → Reports → Decision makers",
            color=MUTED, fontsize=9, va="top")
    layers = [
        ("1 · Source systems", ["Branch POS / tills (X, Y, Z)", "Loyalty (member card)", "Payment gateways",
                                "Prototype: Excel extract"]),
        ("2 · ETL — Power Query", ["Extract workbook", "Fix swapped / text dates", "Type, trim, de-duplicate",
                                  "Surrogate keys, attributes"]),
        ("3 · Staging layer", ["Raw_RetailSales (as-is)", "Stg_RetailSales (clean)", "Not loaded to model",
                               "DQ checks (rows, keys)"]),
        ("4 · Data warehouse", ["FactSales (grain: 1 txn)", "DimDate · DimTime", "DimBranch · DimProduct",
                                "DimCustomer · DimPayment", "DimCluster"]),
        ("5 · Semantic model", ["Power BI / VertiPaq (import)", "1:* single-direction joins", "91 DAX measures",
                                "Date table marked"]),
        ("6 · Delivery", ["4-page dashboard", "Slicers synced across pages", "Power BI Service app",
                          "Retail Store Directors"]),
    ]
    w, h, y = 2.15, 2.15, 3.3
    for i, (t, ls) in enumerate(layers):
        x = 0.3 + i * 2.45
        box(ax, x, y, w, h, t, ls, edge=LAV if i in (3, 4) else BORDER)
        if i:
            arrow(ax, x - 0.28, y + h / 2, x - 0.02, y + h / 2)
    box(ax, 0.3 + 2 * 2.45, 0.55, 2.15, 1.75, "Python · K-Means", ["scripts/02_customer_", "segmentation.py",
                                                               "→ outputs/*.csv"], edge=PINK, title_color=PINK)
    arrow(ax, 0.3 + 2 * 2.45 + 1.07, 3.3, 0.3 + 2 * 2.45 + 1.07, 2.32, PINK)
    arrow(ax, 0.3 + 2 * 2.45 + 2.17, 1.4, 0.3 + 3 * 2.45 + 0.6, 3.28, PINK)
    gov = ("Cross-cutting:  Scheduled refresh (gateway, daily)  ·  Data-quality rules & reconciliation (scripts/03)  ·  "
           "Row-level security by branch  ·  Workspace roles  ·  Certified dataset & version control (PBIP/Git)")
    ax.add_patch(FancyBboxPatch((7.7, 0.55), 6.95, 1.75, boxstyle="round,pad=0.02,rounding_size=0.12", fc=CARD, ec=BORDER))
    ax.text(7.9, 2.15, "Governance, security & operations", color=TEXT, fontsize=10.5, weight="bold", va="top")
    for i, l in enumerate(["Refresh: scheduled via on-premises gateway; incremental refresh on Date when volumes grow",
                           "Data quality: row-count & total reconciliation, key integrity, date-range checks",
                           "Security: RLS role per branch manager; directors see all branches",
                           "Scalability: star schema, import mode, aggregations; swap Excel for a SQL warehouse",
                           "Governance: certified dataset, documented measures, PBIP files under version control"]):
        ax.text(7.9, 1.8 - i * 0.25, "• " + l, color=MUTED, fontsize=8, va="top")
    fig.savefig(OUT / "diagram_bi_architecture.png", dpi=150, facecolor=BG, bbox_inches="tight")


def star():
    fig, ax = plt.subplots(figsize=(13, 8.6), facecolor=BG)
    ax.set_xlim(0, 13); ax.set_ylim(0, 8.6); ax.axis("off")
    ax.text(0.3, 8.35, "Star Schema — Retail Sales Data Mart", color=TEXT, fontsize=15, weight="bold", va="top")
    ax.text(0.3, 7.95, "Fact grain: one row per sales transaction (1,000 rows)  ·  all relationships 1 : * single-direction, dimension → fact",
            color=MUTED, fontsize=9, va="top")
    fx, fy, fw, fh = 4.9, 2.6, 3.2, 3.6
    box(ax, fx, fy, fw, fh, "FactSales", ["PK SalesKey · Invoice ID (degenerate)", "FK DateKey · HourKey · BranchKey",
                                          "FK ProductKey · CustomerKey", "FK PaymentKey · ClusterKey", "",
                                          "Purchase Time · Unit Price · Quantity", "Tax · Sales · COGS",
                                          "Gross Income · Rating"], edge=LAV, title_color=LAV)
    dims = [
        ("DimDate (90)", ["PK DateKey · Date (marked)", "Year · Quarter · Month", "Day name · Weekday/Weekend"], 0.3, 5.6),
        ("DimTime (24)", ["PK HourKey · Hour", "Time of Day (Morning /", "Afternoon / Evening)"], 0.3, 3.3),
        ("DimBranch (3)", ["PK BranchKey", "Branch · City", "Branch Label"], 0.3, 1.0),
        ("DimProduct (6)", ["PK ProductKey", "Product Line"], 9.5, 5.6),
        ("DimCustomer (4)", ["PK CustomerKey", "Customer Type · Gender", "Customer Segment"], 9.5, 3.3),
        ("DimPayment (3)", ["PK PaymentKey", "Payment Method", "Payment Channel"], 9.5, 1.0),
        ("DimCluster (4)", ["PK ClusterKey · Persona", "Centroids · Action", "(K-Means output)"], 4.9, 0.1),
    ]
    for t, ls, x, y in dims:
        w, h = 3.2, 1.75
        box(ax, x, y, w, h, t, ls, edge=PINK if t.startswith("DimCluster") else BORDER)
        cx, cy = x + w / 2, y + h / 2
        tx = fx if x < fx else (fx + fw if x > fx else fx + fw / 2)
        ty = fy + fh / 2 if x != fx else fy
        sx = x + w if x < fx else (x if x > fx else cx)
        sy = cy if x != fx else y + h
        arrow(ax, sx, sy, tx, ty)
        ax.text((sx + tx) / 2, (sy + ty) / 2 + 0.12, "1 : *", color=MUTED, fontsize=8, ha="center")
    fig.savefig(OUT / "diagram_star_schema.png", dpi=150, facecolor=BG, bbox_inches="tight")


if __name__ == "__main__":
    architecture()
    star()
    print("diagrams written")
