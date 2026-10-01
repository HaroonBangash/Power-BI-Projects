# Dashboard Guide, Analytical Findings & Recommendations

All figures were calculated from the cleaned dataset (1,000 transactions, 1 Jan – 30 Mar 2022). They are reproduced by `scripts/03_validate_kpis.py` ([`outputs/kpi_validation.csv`](../outputs/kpi_validation.csv)) and match the Power BI measures exactly. Currency is $ as stated in the data description; sales include the 5% tax.

## 1. Dashboard pages

| Page | Audience question | Visuals |
|---|---|---|
| **1 · Executive Overview** | How is the business performing overall? | 6 KPI cards (Total Sales, Gross Income, Transactions, Quantity, Avg Transaction Value, Avg Rating) with dynamic subtitles · daily sales + 7-day moving average · monthly sales (MoM in title, per-day in tooltip) · Key Insights panel (3 dynamic insights) · sales by branch · sales by product line · gross income by product line · customer-type contribution donut |
| **2 · Product & Branch** | What sells, where, and is it profitable? | 4 dynamic "leader" cards (top product by sales / gross income / units, top branch) · units by product line · Branch × Product Line heat-map · Product Line scorecard (sales, share, units, gross income, margin, basket, rating) · Branch scorecard (incl. rank) |
| **3 · Customer Behaviour** | Who buys, how they pay, when, and how satisfied? | Member share, most-used payment, peak hour, highest-rated branch cards · sales by customer type × gender · transactions by payment · transactions by hour coloured by Morning/Afternoon/Evening · rating by branch · rating by product line · Customer Type × Product heat-map |
| **4 · Predictive Segments** | Which customer groups matter, and what to do? | K, silhouette, stability and "sales at risk" cards · elbow curve · silhouette by k · segment sizes · spend-vs-rating segment map · live segment profile table · persona actions table |

Every page shares a header with page tabs and a left icon rail (page navigation buttons). It has six **synced dropdown slicers** (Branch, Product line, Month, Customer type, Gender, Payment) and a dynamic line that states the active filters. All visuals cross-filter each other. Titles marked "·" (e.g. "Sales by Branch · Z · Ballarat leads", "Transactions by Hour · peak at 19:00") are **DAX-driven** and update with the slicers.

## 2. Findings

### 2.1 Overall performance
* **Total sales $325,722**, gross income $15,517 (gross margin 4.76%), COGS $310,205, 1,000 transactions, 5,510 units.
* **Average transaction value $325.72**; 5.5 units per transaction; average unit price $56.17.
* **Average rating 6.97/10**; only **32.9%** of transactions are rated 8 or higher.

### 2.2 Trend across the three months
| Month | Sales | Transactions | Trading days | Sales / day | MoM sales | MoM sales / day |
|---|---|---|---|---|---|---|
| Jan 2022 | $117,274 | 352 | 31 | $3,783 | – | – |
| Feb 2022 | $98,046 | 303 | 28 | $3,502 | −16.4% | −7.4% |
| Mar 2022 | $110,401 | 345 | 30 | $3,680 | +12.6% | +5.1% |

Sales are **not on a clear upward or downward trend**: February dipped and March partly recovered, but stayed below January. About half of February's fall is the shorter month (per-day sales fell 7.4% vs 16.4% in total). Three months cannot separate trend from seasonality.

### 2.3 Branches
| Branch | Sales | Share | Transactions | Avg basket | Gross income | Avg rating |
|---|---|---|---|---|---|---|
| **Z · Ballarat** | **$111,484** | **34.2%** | 328 (fewest) | **$339.89** | **$5,311** | **7.07** |
| X · Geelong | $107,130 | 32.9% | 340 (most) | $315.09 | $5,104 | 7.03 |
| Y · Melbourne | $107,108 | 32.9% | 332 | $322.61 | $5,103 | **6.82 (lowest)** |

Branch Z leads in both revenue and gross income, **despite the fewest transactions**, because of the largest average basket. X and Y are virtually tied. Y has the lowest satisfaction.

### 2.4 Product lines
| Product line | Sales | Share | Units | Gross income | Avg rating |
|---|---|---|---|---|---|
| **Food and beverages** | **$56,621** | 17.4% | 952 | **$2,697** | **7.11** |
| Sports and travel | $55,583 | 17.1% | 920 | $2,648 | 6.92 |
| Electronic accessories | $54,823 | 16.8% | **971** | $2,612 | 6.92 |
| Fashion accessories | $54,757 | 16.8% | 902 | $2,609 | 7.03 |
| Home and lifestyle | $54,317 | 16.7% | 911 | $2,588 | 6.84 |
| **Health and beauty** | $49,621 | **15.2%** | **854** | $2,364 | 7.00 |

* Food and beverages is the top line for **both sales and gross income**. Electronic accessories sells the **most units**.
* Health and beauty **underperforms**: lowest sales, units and gross income, 12.4% below the leader.
* **Strong sales but weak profitability?** No product line shows this. Gross income is a uniform ~4.76% of sales in every category (the source computes it as 5% of pre-tax sales), so profitability rankings mirror sales rankings exactly. Category-level profit differences cannot be assessed until true cost data is available.
* Fashion accessories has the **most transactions (178) but the smallest basket ($307.62)**.

### 2.5 Branch × product combinations
* Strongest cells: **Z · Food and beverages $23,951**, X · Home and lifestyle $22,603, Z · Fashion accessories $21,731.
* Weakest cells: **X · Health and beauty $12,726**, Z · Home and lifestyle $14,018, Y · Food and beverages $15,350.
* Product strength clearly **differs by branch**. Health and beauty is strong in Y ($20,141) but weak in X. Home and lifestyle is X's best line but Z's weakest.

### 2.6 Customers
* **Members generate 50.8% of sales** ($165,616 vs $160,106 for normal customers) with a basket only **3.0% larger** ($330.57 vs $320.85). There is no meaningful spending difference.
* Members over-index on Food and beverages ($31,611 vs $25,010). Normal customers over-index on Electronic accessories ($30,110 vs $24,713).
* Female customers account for 52.0% of sales with a larger average basket ($337.96 vs $313.44 for male customers).

### 2.7 Payment
* **E-wallet (345 transactions) and cash (344) are effectively tied** as the most common methods; credit card is used least (311).
* Cash brings the highest sales value ($113,155, 34.7%). **Cashless payments account for 65.3% of sales.**
* Ratings barely differ by payment method (6.95–7.00).

### 2.8 When customers shop
* **Peak hour is 19:00** (113 transactions, $40,024). Next are 13:00 (103), 15:00 (102) and 10:00 (101). The quietest hours are 17:00 (74), 20:00 (75) and 16:00 (77).
* By band: Afternoon 454 transactions (45.8% of sales), Evening 355 (35.0%), Morning 191 (19.1%). **Per trading hour the bands are similar** (Morning 95.5, Afternoon 90.8, Evening 88.8 transactions per hour slot). The afternoon's total is mainly a result of its length.
* **Wednesday is the strongest day** ($56,580; $4,352 per Wednesday). Friday is the weakest ($38,218; $3,185 per Friday). Weekday totals are normalised because the period contains 13 of Saturday–Wednesday but 12 of Thursday and Friday.

### 2.9 Satisfaction
* Highest-rated branch **Z (7.07)**, lowest **Y (6.82)**. Highest-rated line **Food and beverages (7.11)**, lowest **Home and lifestyle (6.84)**. The spread is small: ratings vary much more *within* groups than between them.

### 2.10 Predictive segments (K-Means, k = 4)
* **C1 At-Risk High-Value Shoppers**: 21.3% of transactions, **37.6% of sales**, avg spend $575, **avg rating 5.40**.
* C2 Satisfied High-Value: 24.6% of transactions, 36.0% of sales, rating 8.40.
* C3 Dissatisfied Low-Spend: 29.5% / 14.6% / 5.62. C4 Satisfied Low-Spend: 24.6% / 11.9% / 8.53.
* Membership share is ~50% in every segment. See [Predictive_Model.md](Predictive_Model.md).

## 3. Recommendations for Retail Store Directors

1. **Launch a service-recovery programme for high-value, low-satisfaction shoppers (segment C1).** Evidence: C1 delivers 37.6% of sales but rates the experience 5.4/10 (lowest of all segments), with the largest baskets (8.4 items, highest unit prices). Actions: follow up every low rating on baskets above ~$450, review checkout and carry-out service for large baskets, and offer retention incentives. Track the segment's average rating monthly.
2. **Raise Branch Y (Melbourne) service standards using Branch Z practices.** Evidence: Y has the lowest rating (6.82) and is tied lowest on sales, while Z combines the highest rating (7.07) with the largest basket ($339.89) on the fewest transactions. Benchmark Z's staffing, assisted selling and layout, and set a branch rating target.
3. **Allocate inventory and promotions by branch-level product strength.** Evidence (heat-map): Z leads in Food and beverages ($23,951) and Fashion ($21,731); X in Home and lifestyle ($22,603); Y in Health and beauty ($20,141) and Sports ($20,149). Weight replenishment and space toward these lines in each branch. Test local promotions where a line is weak: Health and beauty at X ($12,726), Home and lifestyle at Z ($14,018), Food and beverages at Y ($15,350).
4. **Run a targeted recovery plan for Health and beauty.** Evidence: it has the lowest sales ($49,621, 12.4% below the leader) and units (854), yet a mid-table rating (7.00). The problem looks like range or visibility, not satisfaction. Use cross-merchandising with Food and beverages, the top line for members.
5. **Redesign the membership programme so it changes behaviour.** Evidence: members are 50.8% of sales but spend only 3.0% more per basket, and member share is ~50% in every K-Means segment. The card currently identifies no valuable group. Introduce spend-tiered rewards (e.g. bonuses above the $326 average basket). Use member Food and beverages affinity, and normal customers' Electronics affinity, for sign-up offers at the point of sale.
6. **Roster staff to the hourly demand curve.** Evidence: transactions peak at 19:00 (113) with secondary peaks at 13:00, 15:00 and 10:00, and dip at 16:00–17:00 and 20:00. Wednesday is the strongest day and Friday the weakest per occurrence. Add checkout cover from 18:30–19:30 and over lunch, schedule breaks and replenishment at 16:00–17:30, and review Friday staffing.
7. **Prioritise fast, reliable cashless checkout while still supporting cash.** Evidence: 65.3% of sales are cashless and e-wallet is (jointly) the most-used method. Cash still brings the single highest sales value (34.7%). Ensure e-wallet/tap terminals at every till during peak hours, monitor payment-failure rates, and keep cash handling for the third of revenue that relies on it.
8. **Capture real cost and margin data before making margin-based decisions.** Evidence: gross income is a fixed ~4.76% of sales in every category and equals the tax amount in every row, so the current data cannot show which products are more profitable. Load supplier cost by SKU into the warehouse so the dashboard's margin views become decision-grade.

## 4. Limitations
* **Short history**: one quarter (89 trading days). No seasonality or year-over-year comparison is possible, and month-over-month changes are indicative only. No long-term forecast is presented.
* **Dataset artefacts**: gross income equals tax in every row; the stated gross margin % is a constant that does not match the data; COGS = quantity × (unit price − $0.025). Profitability analysis is therefore limited (Recommendation 8).
* **Invoice IDs are not unique** and there is **no customer ID**. Analysis is at transaction level; customer lifetime value, repeat-purchase and churn analysis are not possible.
* **Date repair assumption**: true-date cells were corrected by swapping day and month. This is strongly supported (all values fall in the documented period) but is an inference.
* **Correlation, not causation**: differences by branch, segment, gender or hour are associations in observational data. Many differences (e.g. ratings 6.82–7.07, member basket +3%) are small and may not be statistically meaningful at n = 1,000.
* **Segmentation strength**: silhouette 0.32 means weak-to-moderate separation (see [Predictive_Model.md](Predictive_Model.md)).
