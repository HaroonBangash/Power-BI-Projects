"""
02_customer_segmentation.py
---------------------------
Transaction segmentation with K-Means (predictive / AI component).

Method
  1. Load the cleaned extract produced by 01_profile_and_clean.py.
  2. Features: TotalSales (spend), Quantity (basket size), Rating (satisfaction).
     - Gross income is excluded: it is exactly 5% of pre-tax sales (r = 1.00
       with TotalSales), so it would double-weight spend.
     - Unit price is excluded as a feature (TotalSales already embeds it) but is
       kept for profiling.
     - Categorical fields (customer type, gender, payment, branch) are NOT
       one-hot encoded: K-Means uses Euclidean distance, which is a poor fit
       for binary dummies. They are used afterwards to profile the clusters.
  3. Standardise features (z-scores) so each contributes equally.
  4. Evaluate k = 2..10 with inertia (elbow), silhouette and Davies-Bouldin.
  5. Fit the final model (k = 4, n_init = 20, random_state = 42) and check
     stability across 10 further seeds with the Adjusted Rand Index.
  6. Profile clusters and name them from their standardised centroids.

Outputs (outputs/)
  cluster_evaluation.csv   k, inertia, silhouette, davies_bouldin
  model_results.csv        SalesKey -> ClusterID (loaded into Power BI)
  cluster_profiles.csv     one row per cluster (DimCluster in Power BI)
  kmeans_elbow_silhouette.png, kmeans_cluster_scatter.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
FEATURES = ["TotalSales", "Quantity", "Rating"]
FINAL_K = 4
SEED = 42

# Theme colours (match the Power BI theme)
BG, CARD, GRID, TEXT, MUTED = "#0B0B10", "#14141D", "#2A2A38", "#F4F3FF", "#9A98B0"
CAT = ["#8E7CF6", "#DC6299", "#2E9BD0", "#D3753A"]


def name_cluster(z_total, z_rating):
    """Persona naming rule, applied to the standardised centroid.
    Chosen after inspecting the k=4 profiles, which separate cleanly on
    spend (above/below average) x satisfaction (above/below average)."""
    spend = "High-Value" if z_total > 0 else "Low-Spend"
    if z_rating > 0:
        return f"Satisfied {spend} Shoppers"
    return f"At-Risk {spend} Shoppers" if z_total > 0 else "Dissatisfied Low-Spend Shoppers"


ACTIONS = {
    "Satisfied High-Value Shoppers": "Protect and reward: VIP/loyalty perks, early access, premium-range bundles.",
    "At-Risk High-Value Shoppers": "Priority service recovery: follow up low ratings, review service at checkout, targeted retention offers.",
    "Satisfied Low-Spend Shoppers": "Grow basket size: cross-sell and multi-buy offers to happy but light shoppers.",
    "Dissatisfied Low-Spend Shoppers": "Diagnose experience gaps (feedback prompts) before spending on promotions.",
}


def style(ax):
    ax.set_facecolor(CARD)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTED)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def main():
    df = pd.read_csv(OUT / "cleaned_retail_sales.csv")
    scaler = StandardScaler()
    X = scaler.fit_transform(df[FEATURES])

    # ---- model selection ----
    rows = []
    for k in range(1, 11):
        km = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit(X)
        rows.append({
            "K": k,
            "Inertia": round(km.inertia_, 2),
            "Silhouette": round(silhouette_score(X, km.labels_), 4) if k > 1 else None,
            "DaviesBouldin": round(davies_bouldin_score(X, km.labels_), 4) if k > 1 else None,
            "Selected": k == FINAL_K,
        })
    ev = pd.DataFrame(rows)
    ev.to_csv(OUT / "cluster_evaluation.csv", index=False)

    # ---- final model ----
    km = KMeans(n_clusters=FINAL_K, n_init=20, random_state=SEED).fit(X)
    aris = [adjusted_rand_score(km.labels_, KMeans(FINAL_K, n_init=20, random_state=s).fit(X).labels_)
            for s in range(1, 11)]

    # Re-number clusters 1..k by descending average spend so IDs are stable
    order = pd.Series(df["TotalSales"].values).groupby(km.labels_).mean().sort_values(ascending=False).index
    remap = {old: new for new, old in enumerate(order, start=1)}
    df["ClusterID"] = [remap[l] for l in km.labels_]
    centroids_z = {remap[i]: c for i, c in enumerate(km.cluster_centers_)}

    df[["SalesKey", "InvoiceID", "ClusterID"]].to_csv(OUT / "model_results.csv", index=False)

    # ---- profiles ----
    sil = silhouette_score(X, km.labels_)
    prof = []
    for cid, g in df.groupby("ClusterID"):
        z = centroids_z[cid]
        name = name_cluster(z[0], z[2])
        prof.append({
            "ClusterID": cid,
            "ClusterCode": f"C{cid}",
            "ClusterName": name,
            "Transactions": len(g),
            "SharePct": round(len(g) / len(df), 4),
            "AvgSpend": round(g.TotalSales.mean(), 2),
            "AvgQuantity": round(g.Quantity.mean(), 2),
            "AvgUnitPrice": round(g.UnitPrice.mean(), 2),
            "AvgRating": round(g.Rating.mean(), 2),
            "RatingRange": f"{g.Rating.min():.1f}-{g.Rating.max():.1f}",
            "SpendRange": f"${g.TotalSales.min():,.0f}-${g.TotalSales.max():,.0f}",
            "TotalSales": round(g.TotalSales.sum(), 2),
            "SalesSharePct": round(g.TotalSales.sum() / df.TotalSales.sum(), 4),
            "MemberPct": round((g.CustomerType == "Member").mean(), 4),
            "FemalePct": round((g.Gender == "Female").mean(), 4),
            "TopProductLine": g.ProductLine.value_counts().idxmax(),
            "TopPayment": g.PaymentMethod.value_counts().idxmax(),
            "CentroidZ_Total": round(z[0], 3),
            "CentroidZ_Quantity": round(z[1], 3),
            "CentroidZ_Rating": round(z[2], 3),
            "Profile": (f"{len(g)} transactions ({len(g)/len(df):.0%}); avg spend ${g.TotalSales.mean():,.0f} "
                        f"for {g.Quantity.mean():.1f} items; avg rating {g.Rating.mean():.1f}/10."),
            "RecommendedAction": ACTIONS[name],
            "ModelSilhouette": round(sil, 4),
            "ModelStabilityARI": round(min(aris), 4),
        })
    prof = pd.DataFrame(prof)
    prof.to_csv(OUT / "cluster_profiles.csv", index=False)

    # ---- charts (evidence for the report) ----
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), facecolor=BG)
    for ax in axes:
        style(ax)
    axes[0].plot(ev.K, ev.Inertia, color=CAT[0], lw=2, marker="o")
    axes[0].set_title("Elbow method: inertia by k", color=TEXT, loc="left")
    s = ev.dropna()
    axes[1].plot(s.K, s.Silhouette, color=CAT[1], lw=2, marker="o")
    axes[1].set_title("Silhouette score by k (higher is better)", color=TEXT, loc="left")
    for ax in axes:
        ax.axvline(FINAL_K, color=MUTED, ls="--", lw=1)
        ax.set_xlabel("k (number of clusters)", color=MUTED)
    fig.tight_layout()
    fig.savefig(OUT / "kmeans_elbow_silhouette.png", dpi=150, facecolor=BG)

    fig, ax = plt.subplots(figsize=(7.5, 5), facecolor=BG)
    style(ax)
    for cid, g in df.groupby("ClusterID"):
        ax.scatter(g.TotalSales, g.Rating, s=10, color=CAT[cid - 1], alpha=0.8,
                   label=f"C{cid} {prof.loc[prof.ClusterID == cid, 'ClusterName'].iat[0]}")
    ax.set_xlabel("Transaction total ($)", color=MUTED)
    ax.set_ylabel("Customer rating (1-10)", color=MUTED)
    ax.set_title(f"K-Means segments (k={FINAL_K}, silhouette {sil:.3f})", color=TEXT, loc="left")
    leg = ax.legend(facecolor=CARD, edgecolor=GRID, fontsize=8)
    for t in leg.get_texts():
        t.set_color(TEXT)
    fig.tight_layout()
    fig.savefig(OUT / "kmeans_cluster_scatter.png", dpi=150, facecolor=BG)

    print(ev.to_string(index=False))
    print(f"\nFinal k={FINAL_K}  silhouette={sil:.4f}  stability ARI min={min(aris):.4f}")
    print(prof[["ClusterCode", "ClusterName", "Transactions", "AvgSpend", "AvgQuantity", "AvgUnitPrice",
                "AvgRating", "SalesSharePct", "MemberPct", "FemalePct", "TopProductLine", "TopPayment"]].to_string(index=False))


if __name__ == "__main__":
    main()
