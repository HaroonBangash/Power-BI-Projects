# Predictive Analytics: K-Means Transaction Segmentation

Script: [`scripts/02_customer_segmentation.py`](../scripts/02_customer_segmentation.py) · Outputs: [`outputs/cluster_evaluation.csv`](../outputs/cluster_evaluation.csv), [`outputs/cluster_profiles.csv`](../outputs/cluster_profiles.csv), [`outputs/model_results.csv`](../outputs/model_results.csv), [`outputs/kmeans_elbow_silhouette.png`](../outputs/kmeans_elbow_silhouette.png), [`outputs/kmeans_cluster_scatter.png`](../outputs/kmeans_cluster_scatter.png). Report page: **4 · Predictive Segments**.

## 1. Why K-Means (and not forecasting or satisfaction scoring)
* **Demand forecasting** would rest on 89 daily points from a single quarter. There is no seasonality to learn and no hold-out period long enough to validate a forecast, so any forecast would carry little credibility.
* **Predicting satisfaction (Rating)** was screened: Rating is essentially uncorrelated with spend, quantity and unit price (|r| ≤ 0.04). A supervised model would have almost no signal.
* **Segmentation** suits the data: it needs no future period, it uses every transaction, and it turns spend and satisfaction into groups that directors can act on.

## 2. Method
1. **Data**: the cleaned extract (`outputs/cleaned_retail_sales.csv`, 1,000 rows), produced by the same rules as the Power Query ETL.
2. **Feature selection**: `TotalSales` (spend), `Quantity` (basket size), `Rating` (satisfaction).
   * *Gross income* excluded: it is exactly 5% of pre-tax sales (r = 1.00 with Total) and would double-weight spend.
   * *Unit price* excluded as a feature (Total already embeds price × quantity) but used to profile clusters.
   * *Categorical variables* (customer type, gender, payment, branch, product) were **not** one-hot encoded. K-Means' Euclidean distance treats binary dummies poorly. They are used afterwards to describe the clusters.
   * Feature sets compared by silhouette at k = 4: {Total, Qty, Rating} 0.319 · {Total, Qty, UnitPrice, Rating} 0.281 · {Qty, UnitPrice, Rating} 0.284. The first was chosen.
3. **Standardisation**: z-scores (`StandardScaler`) so each feature contributes equally.
4. **Choice of k** (k = 1–10, `n_init = 20`, `random_state = 42`):

| k | Inertia | Silhouette | Davies-Bouldin |
|---|---|---|---|
| 2 | 1,775.5 | **0.358** | 1.135 |
| 3 | 1,327.0 | 0.320 | 1.013 |
| **4** | **1,030.3** | **0.320** | 1.095 |
| 5 | 833.4 | 0.318 | 0.977 |
| 6 | 720.1 | 0.306 | 1.018 |
| 8 | 587.0 | 0.298 | 1.010 |
| 10 | 484.1 | 0.296 | 1.010 |

   k = 2 has the highest silhouette but only separates "big vs small basket", which is not actionable. Silhouette is flat at ≈0.32 for k = 3–5, and the elbow curve shows diminishing gains after k = 4–5. **k = 4** was selected because it scores as well as k = 3 and gives a clean, interpretable 2 × 2 structure (spend × satisfaction).
5. **Stability**: the final model was re-fitted with 10 other random seeds. The minimum Adjusted Rand Index was **1.000**, so the clusters are identical on every run.
6. **Labelling rule** (applied only after inspecting the profiles): a centroid with z(Total) > 0 is "High-Value", otherwise "Low-Spend"; z(Rating) > 0 is "Satisfied", otherwise "At-Risk" / "Dissatisfied". Clusters are numbered C1–C4 by descending average spend.
7. **Deployment into BI**: each transaction's cluster (`model_results.csv`, keyed by SalesKey + Invoice ID) is merged into FactSales. Cluster profiles become `DimCluster`, so every measure and slicer works by segment.

## 3. Results

| Segment | Transactions | Avg spend | Units / tx | Avg unit price | Avg rating | Share of sales | Member share | Top product line | Top payment |
|---|---|---|---|---|---|---|---|---|---|
| **C1 · At-Risk High-Value Shoppers** | 213 (21.3%) | $574.80 | 8.35 | $66.91 | **5.40** | **37.6%** | 51.6% | Electronic accessories | Ewallet |
| **C2 · Satisfied High-Value Shoppers** | 246 (24.6%) | $476.02 | 7.93 | $58.96 | 8.40 | 36.0% | 51.2% | Fashion accessories | Cash |
| **C3 · Dissatisfied Low-Spend Shoppers** | 295 (29.5%) | $160.90 | 3.36 | $50.00 | 5.62 | 14.6% | 49.5% | Fashion accessories | Ewallet |
| **C4 · Satisfied Low-Spend Shoppers** | 246 (24.6%) | $157.41 | 3.21 | $51.49 | 8.53 | 11.9% | 48.4% | Food and beverages | Credit card |

Silhouette = 0.320 · Davies-Bouldin = 1.095 · stability ARI = 1.000.

### Business interpretation
* **C1 is the key finding**: the highest-spending transactions (avg $575, 8.4 items, highest unit price) carry the *lowest* satisfaction (5.4/10). This one segment holds 37.6% of all sales.
* **C2** spends almost as much and is very satisfied. These are the shoppers to protect and reward.
* **C3** is the largest group by count (29.5%) with small baskets and low ratings.
* **C4** is happy but buys little. The opportunity here is basket growth, not service recovery.
* **Membership does not distinguish the segments** (48–52% members in every cluster). The member card does not currently identify high-value or satisfied shoppers.

Recommended actions per segment are stored in `DimCluster[Recommended Action]` and shown on the dashboard.

## 4. Limitations
* A silhouette of 0.32 means **weak-to-moderate** separation. The data is close to uniformly spread, so the clusters partition a continuum rather than reveal natural groups. They are useful for targeting, not as evidence of distinct customer "types".
* Clusters are formed from **transactions, not customers** (no customer ID exists). A customer may appear in several segments.
* Rating is captured per transaction; segment differences in rating show **association, not causation** (high spend does not cause low ratings).
* The model segments past transactions. New transactions could be assigned to the nearest centroid by re-running the script, but the segment definitions rest on one quarter of data and should be re-fitted as history grows.
