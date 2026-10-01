# Data Warehouse Framework & Dimensional Model

Diagram: [`outputs/diagram_star_schema.png`](../outputs/diagram_star_schema.png). Model source: [`RetailStore_BI.SemanticModel/definition`](../RetailStore_BI.SemanticModel/definition) (TMDL).

## 1. Design approach
A Kimball-style **star schema** (sales data mart) with one transactional fact table surrounded by conformed dimensions. The flat Excel extract was decomposed so that:
* descriptive attributes live once in small dimensions;
* measures are additive numeric columns in the fact table;
* every relationship is **one-to-many, single-direction (dimension filters fact)**, with no bi-directional or many-to-many relationships;
* a dedicated calendar table is **marked as the Date table**.

## 2. Grain
**One row in FactSales = one retail sales transaction (one source row).**

Verified against the data: the source has 1,000 rows and no fully duplicated rows. Invoice ID cannot be the grain key because it repeats across unrelated transactions (575 distinct IDs; repeated IDs never share branch, date and time). Each source row is therefore a distinct transaction, identified by the surrogate key `SalesKey`. Invoice ID is kept as a **degenerate dimension** for traceability.

## 3. Tables

| Table | Type | Rows | Primary key | Purpose / key attributes |
|---|---|---|---|---|
| **FactSales** | Fact | 1,000 | SalesKey | FKs: DateKey, HourKey, BranchKey, ProductKey, CustomerKey, PaymentKey, ClusterKey. Measures: Unit Price, Quantity, Tax Amount, Sales Amount (Total), COGS Amount, Gross Income Amount, Rating. Also Invoice ID (degenerate) and Purchase Time |
| **DimDate** | Conformed dimension (marked Date table) | 90 | DateKey (`yyyymmdd`); `Date` is the date-table key | Year, Quarter, Month Number/Name/Short, Month (e.g. "Jan 2022", sorted by Year-Month), Month Start, Day, Day of Week Number, Day Name, Weekday or Weekend, Week of Year |
| **DimTime** | Dimension (hour grain) | 24 | HourKey (0–23) | Hour ("13:00"), Hour 12h, Time of Day (Morning/Afternoon/Evening), Time of Day Range |
| **DimBranch** | Dimension | 3 | BranchKey | Branch (X/Y/Z), City (Geelong/Melbourne/Ballarat), Branch Label |
| **DimProduct** | Dimension | 6 | ProductKey | Product Line |
| **DimCustomer** | Segment (junk) dimension | 4 | CustomerKey | Customer Type × Gender, Customer Segment. The source has no customer identifier, so this dimension describes customer *segments*, not individual customers |
| **DimPayment** | Dimension | 3 | PaymentKey | Payment Method, Payment Channel (Cash / Cashless) |
| **DimCluster** | Dimension (analytics output) | 4 | ClusterKey | K-Means segment code, persona name, profile text, recommended action, centroid z-scores |
| **ClusterEvaluation** | Disconnected helper table | 10 | K | Inertia, Silhouette, Davies-Bouldin per k (model-selection evidence only) |
| **Key Measures** | Measure table | – | – | Home of all 91 DAX measures ([DAX_Measures.md](DAX_Measures.md)) |

## 4. Relationships

| From (many) | To (one) | Cardinality | Cross-filter |
|---|---|---|---|
| FactSales[DateKey] | DimDate[DateKey] | * : 1 | Single |
| FactSales[HourKey] | DimTime[HourKey] | * : 1 | Single |
| FactSales[BranchKey] | DimBranch[BranchKey] | * : 1 | Single |
| FactSales[ProductKey] | DimProduct[ProductKey] | * : 1 | Single |
| FactSales[CustomerKey] | DimCustomer[CustomerKey] | * : 1 | Single |
| FactSales[PaymentKey] | DimPayment[PaymentKey] | * : 1 | Single |
| FactSales[ClusterKey] | DimCluster[ClusterKey] | * : 1 | Single |

Referential integrity was verified after refresh: 0 fact rows have a blank or unmatched key.

## 5. Modelling decisions
* **Surrogate integer keys** in every dimension. They keep the fact table narrow and would support slowly changing dimensions if the warehouse were extended.
* **City kept in DimBranch** (Branch → City is 1:1), so there is no separate City dimension (no snowflaking).
* **Customer Type and Gender combined** into one 4-row segment dimension rather than two tiny dimensions.
* **Gross Margin %** is a measure (ratio of sums), not a stored column, so it aggregates correctly at any level.
* **Numeric fact columns hidden**: report authors must use the explicit measures.
* **Sort-by columns** give months, weekdays, hours and time bands a natural order.
* **Time intelligence** uses the marked DimDate (`PREVIOUSMONTH`, `DATESYTD`, `DATESINPERIOD`). Only month-over-month, cumulative and 7-day moving-average logic is provided; year-over-year is impossible with one quarter of data.
* **Python output** is integrated as a proper dimension (DimCluster) rather than a calculated column, so segments slice every measure.

## 6. Production data warehouse (target state)
The Power BI model is the prototype of the warehouse. In production the same design would be materialised in a relational warehouse (e.g. Azure SQL / Fabric Warehouse):

* **Staging schema** (`stg.RetailSales`): raw daily POS extracts, truncated and reloaded.
* **Warehouse schema** (`dw.FactSales`, `dw.Dim*`): loaded by the same rules as the Power Query steps. It would add SCD Type 2 on DimBranch/DimProduct, an audit column per load, and a `LoadBatchID`.
* **Semantic layer**: this Power BI model switches its source from Excel to the warehouse tables (only the `Raw_RetailSales` query changes).
