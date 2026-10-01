# Evidence Checklist for the Assessment Report

Pre-made evidence is in `outputs/`. Items marked **Capture in Desktop** need a screenshot from Power BI Desktop after opening `RetailStore_BI.pbip` and refreshing.

| # | Evidence | Where to get it | Ready-made file | Status |
|---|---|---|---|---|
| 1 | **Raw dataset** | Open the Excel workbook, sheet `RetailStore Dataset `. Show the mixed Date column (some right-aligned real dates, some left-aligned text) | – | Capture in Excel |
| 1b | Data profile | `outputs/data_quality_profile.csv` (types / nulls / distinct per column); ETL_Documentation §1 table | data_quality_profile.csv | Ready |
| 2 | **Power Query transformations** | Desktop → *Transform data* → select `Stg_RetailSales` → screenshot the **Applied Steps** pane (RenamedColumns … FixedDate, FixedTime, Typed). Also show `FactSales` merge steps | – | Capture in Desktop |
| 3 | **Final cleaned dataset** | Desktop → *Table view* → FactSales (1,000 rows, keys + measures), or `outputs/cleaned_retail_sales.csv` | cleaned_retail_sales.csv | Capture / Ready |
| 4 | **Data model / star schema** | Desktop → *Model view* (arrange FactSales in the centre) | diagram_star_schema.png | Ready + Capture |
| 5 | **DAX measures** | Desktop → Data pane → *Key Measures* (display folders expanded) + select one measure (e.g. `Latest Month Sales MoM %`) to show the formula bar | documentation/DAX_Measures.md | Capture in Desktop |
| 6 | **Executive dashboard** | Page 1 | screenshots/page1_executive_overview.png | Ready |
| 7 | **Product / branch dashboard** | Page 2 | screenshots/page2_product_branch.png | Ready |
| 8 | **Customer dashboard** | Page 3 | screenshots/page3_customer_behaviour.png | Ready |
| 9 | **Predictive model process** | Elbow + silhouette chart; feature/k table in Predictive_Model.md §2; code `scripts/02_customer_segmentation.py` | kmeans_elbow_silhouette.png | Ready |
| 10 | **Predictive model result** | Page 4 + cluster scatter + profile table | screenshots/page4_predictive_segments.png, kmeans_cluster_scatter.png, cluster_profiles.csv | Ready |
| 11 | **BI architecture** | Architecture diagram | diagram_bi_architecture.png | Ready |
| 12 | **Data warehouse framework** | Star schema diagram + table/relationship tables in Data_Warehouse_Design.md | diagram_star_schema.png | Ready |
| 13 | Calculation validation | `outputs/kpi_validation.csv` vs a KPI card (e.g. Total Sales $325,722) | kpi_validation.csv | Ready |
| 14 | Interactivity (optional) | Page 1 with Branch = Z selected, showing the dynamic "Filtered: Branch Z" line and updated titles | – | Capture in Desktop |

## Suggested mapping to report sections (~2,000 words)
1. **Introduction & business problem** (~150 words)
2. **BI system architecture**: diagram #11 + BI_Architecture.md (~300)
3. **Data warehouse & dimensional model**: #4, #12, grain statement (~300)
4. **ETL & data quality**: #1, #2, #3, date/invoice issues (~300)
5. **Descriptive & visual analytics**: #6–#8, Dashboard_Insights §2 (~450)
6. **Predictive analytics**: #9, #10, Predictive_Model.md (~300)
7. **Recommendations & limitations**: Dashboard_Insights §3–4 (~200)
