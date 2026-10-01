# DAX Measure Catalogue

Generated from `RetailStore_BI.SemanticModel/definition/tables/Key Measures.tmdl` (the model's single measures table). All measures are explicit; numeric fact columns are hidden so report authors cannot fall back on implicit aggregation.

**91 measures** in six display folders.


## 01 Core KPIs

### Total Sales
Sum of transaction totals including 5% tax (source column Total).  
Format: `$#,0;($#,0);$#,0`

```dax
Total Sales = SUM ( FactSales[Sales Amount] )
```

### Total Gross Income
Sum of gross income as supplied in the source.  
Format: `$#,0;($#,0);$#,0`

```dax
Total Gross Income = SUM ( FactSales[Gross Income Amount] )
```

### Total COGS
Sum of cost of goods sold.  
Format: `$#,0;($#,0);$#,0`

```dax
Total COGS = SUM ( FactSales[COGS Amount] )
```

### Total Tax
Sum of the 5% tax collected.  
Format: `$#,0;($#,0);$#,0`

```dax
Total Tax = SUM ( FactSales[Tax Amount] )
```

### Total Quantity Sold
Units sold.  
Format: `#,0`

```dax
Total Quantity Sold = SUM ( FactSales[Quantity] )
```

### Total Transactions
Count of sales transactions (fact rows). Used instead of a distinct count of Invoice ID because Invoice IDs repeat across unrelated transactions.  
Format: `#,0`

```dax
Total Transactions = COUNTROWS ( FactSales )
```

### Distinct Invoice IDs
Data-quality evidence only: distinct Invoice ID values (575 vs 1,000 transactions).  
Format: `#,0`

```dax
Distinct Invoice IDs = DISTINCTCOUNT ( FactSales[Invoice ID] )
```

### Average Transaction Value
Sales per transaction (average basket value).  
Format: `$#,0.00;($#,0.00);$#,0.00`

```dax
Average Transaction Value = DIVIDE ( [Total Sales], [Total Transactions] )
```

### Average Unit Price
Simple mean of unit price across transactions.  
Format: `$#,0.00;($#,0.00);$#,0.00`

```dax
Average Unit Price = AVERAGE ( FactSales[Unit Price] )
```

### Average Rating
Mean customer satisfaction rating (1-10).  
Format: `0.00`

```dax
Average Rating = AVERAGE ( FactSales[Rating] )
```

### Gross Margin %
Gross income / sales. Recomputed from the facts; the source 'gross margin percentage' column is a constant (4.7619%) and is not used.  
Format: `0.00%;-0.00%;0.00%`

```dax
Gross Margin % = DIVIDE ( [Total Gross Income], [Total Sales] )
```

### Quantity per Transaction
Average units per transaction.  
Format: `0.00`

```dax
Quantity per Transaction = DIVIDE ( [Total Quantity Sold], [Total Transactions] )
```

### Gross Income per Transaction
Average gross income per transaction.  
Format: `$#,0.00;($#,0.00);$#,0.00`

```dax
Gross Income per Transaction = DIVIDE ( [Total Gross Income], [Total Transactions] )
```


## 02 Mix & Share

### Branch Sales Share %
Share of sales across all branches (other filters respected).  
Format: `0.0%;-0.0%;0.0%`

```dax
Branch Sales Share % = DIVIDE ( [Total Sales], CALCULATE ( [Total Sales], REMOVEFILTERS ( DimBranch ) ) )
```

### Product Line Sales Share %
Share of sales across all product lines (other filters respected).  
Format: `0.0%;-0.0%;0.0%`

```dax
Product Line Sales Share % = DIVIDE ( [Total Sales], CALCULATE ( [Total Sales], REMOVEFILTERS ( DimProduct ) ) )
```

### Sales Share of Selection %
Share of the sales currently visible in the visual/page selection.  
Format: `0.0%;-0.0%;0.0%`

```dax
Sales Share of Selection % = DIVIDE ( [Total Sales], CALCULATE ( [Total Sales], ALLSELECTED () ) )
```

### Transaction Share of Selection %
Share of the transactions currently visible in the visual/page selection.  
Format: `0.0%;-0.0%;0.0%`

```dax
Transaction Share of Selection % = DIVIDE ( [Total Transactions], CALCULATE ( [Total Transactions], ALLSELECTED () ) )
```

### Branch Sales Rank
Rank of a branch by sales (1 = highest).  
Format: `0`

```dax
Branch Sales Rank =
IF (
    HASONEVALUE ( DimBranch[BranchKey] ),
    RANKX ( ALL ( DimBranch ), [Total Sales], , DESC, DENSE )
)
```

### Product Line Sales Rank
Rank of a product line by sales (1 = highest).  
Format: `0`

```dax
Product Line Sales Rank =
IF (
    HASONEVALUE ( DimProduct[ProductKey] ),
    RANKX ( ALL ( DimProduct ), [Total Sales], , DESC, DENSE )
)
```

### Product Line Gross Income Rank
Rank of a product line by gross income (1 = highest).  
Format: `0`

```dax
Product Line Gross Income Rank =
IF (
    HASONEVALUE ( DimProduct[ProductKey] ),
    RANKX ( ALL ( DimProduct ), [Total Gross Income], , DESC, DENSE )
)
```

### Sales vs Product Line Average %
How far a product line's sales sit above/below the average product line.  
Format: `+0.0%;-0.0%;0.0%`

```dax
Sales vs Product Line Average % =
VAR AvgLine = AVERAGEX ( ALL ( DimProduct ), [Total Sales] )
RETURN
    IF ( HASONEVALUE ( DimProduct[ProductKey] ), DIVIDE ( [Total Sales] - AvgLine, AvgLine ) )
```


## 03 Customer & Behaviour

### Member Sales
Sales from loyalty-card members.  
Format: `$#,0;($#,0);$#,0`

```dax
Member Sales = CALCULATE ( [Total Sales], DimCustomer[Customer Type] = "Member" )
```

### Normal Customer Sales
Sales from customers without a member card.  
Format: `$#,0;($#,0);$#,0`

```dax
Normal Customer Sales = CALCULATE ( [Total Sales], DimCustomer[Customer Type] = "Normal" )
```

### Member Sales %
Members' share of sales.  
Format: `0.0%;-0.0%;0.0%`

```dax
Member Sales % = DIVIDE ( [Member Sales], CALCULATE ( [Total Sales], REMOVEFILTERS ( DimCustomer[Customer Type] ) ) )
```

### Female Customer Sales %
Female customers' share of sales.  
Format: `0.0%;-0.0%;0.0%`

```dax
Female Customer Sales % =
DIVIDE (
    CALCULATE ( [Total Sales], DimCustomer[Gender] = "Female" ),
    CALCULATE ( [Total Sales], REMOVEFILTERS ( DimCustomer[Gender] ) )
)
```

### Male Customer Sales %
Male customers' share of sales.  
Format: `0.0%;-0.0%;0.0%`

```dax
Male Customer Sales % =
DIVIDE (
    CALCULATE ( [Total Sales], DimCustomer[Gender] = "Male" ),
    CALCULATE ( [Total Sales], REMOVEFILTERS ( DimCustomer[Gender] ) )
)
```

### Member ATV
Average transaction value for members.  
Format: `$#,0.00;($#,0.00);$#,0.00`

```dax
Member ATV = CALCULATE ( [Average Transaction Value], DimCustomer[Customer Type] = "Member" )
```

### Normal ATV
Average transaction value for normal customers.  
Format: `$#,0.00;($#,0.00);$#,0.00`

```dax
Normal ATV = CALCULATE ( [Average Transaction Value], DimCustomer[Customer Type] = "Normal" )
```

### Member ATV Premium %
How much more (or less) members spend per transaction than normal customers.  
Format: `+0.0%;-0.0%;0.0%`

```dax
Member ATV Premium % = DIVIDE ( [Member ATV] - [Normal ATV], [Normal ATV] )
```

### High Rating % (8+)
Share of transactions rated 8 or higher.  
Format: `0.0%;-0.0%;0.0%`

```dax
High Rating % (8+) = DIVIDE ( CALCULATE ( [Total Transactions], FactSales[Rating] >= 8 ), [Total Transactions] )
```

### Low Rating % (below 6)
Share of transactions rated below 6.  
Format: `0.0%;-0.0%;0.0%`

```dax
Low Rating % (below 6) = DIVIDE ( CALCULATE ( [Total Transactions], FactSales[Rating] < 6 ), [Total Transactions] )
```

### Cashless Sales %
Share of sales paid by credit card or e-wallet.  
Format: `0.0%;-0.0%;0.0%`

```dax
Cashless Sales % =
DIVIDE (
    CALCULATE ( [Total Sales], DimPayment[Payment Channel] = "Cashless" ),
    CALCULATE ( [Total Sales], REMOVEFILTERS ( DimPayment ) )
)
```

### Average Transactions per Hour Slot
Transactions per trading day for an hour slot (normalises for the number of trading days).  
Format: `0.0`

```dax
Average Transactions per Hour Slot = DIVIDE ( [Total Transactions], [Trading Days] )
```


## 04 Time Intelligence

### Trading Days
Number of days with at least one sale.  
Format: `0`

```dax
Trading Days = DISTINCTCOUNT ( FactSales[DateKey] )
```

### Average Daily Sales
Sales per trading day. Fairer month comparison because Jan has 31, Feb 28 and Mar 30 trading days in the data.  
Format: `$#,0;($#,0);$#,0`

```dax
Average Daily Sales = DIVIDE ( [Total Sales], [Trading Days] )
```

### Previous Month Sales
Sales in the previous calendar month.  
Format: `$#,0;($#,0);$#,0`

```dax
Previous Month Sales = CALCULATE ( [Total Sales], PREVIOUSMONTH ( DimDate[Date] ) )
```

### MoM Sales Change
Month-over-month change in sales (blank for the first month).  
Format: `+$#,0;-$#,0;$0`

```dax
MoM Sales Change =
VAR PrevSales = [Previous Month Sales]
VAR CurSales = [Total Sales]
RETURN
    IF ( NOT ISBLANK ( PrevSales ) && NOT ISBLANK ( CurSales ), CurSales - PrevSales )
```

### MoM Sales %
Month-over-month % change in sales.  
Format: `+0.0%;-0.0%;0.0%`

```dax
MoM Sales % = DIVIDE ( [MoM Sales Change], [Previous Month Sales] )
```

### MoM Average Daily Sales %
Month-over-month % change in sales per trading day (removes the month-length effect).  
Format: `+0.0%;-0.0%;0.0%`

```dax
MoM Average Daily Sales % =
VAR PrevDaily = CALCULATE ( [Average Daily Sales], PREVIOUSMONTH ( DimDate[Date] ) )
RETURN
    IF ( NOT ISBLANK ( PrevDaily ), DIVIDE ( [Average Daily Sales] - PrevDaily, PrevDaily ) )
```

### Cumulative Sales
Running total of sales from the start of the year (the data covers one quarter), stopped at the last sales date.  
Format: `$#,0;($#,0);$#,0`

```dax
Cumulative Sales =
VAR LastSaleDate = CALCULATE ( MAX ( DimDate[Date] ), REMOVEFILTERS ( DimDate ), FactSales )
RETURN
    IF ( MIN ( DimDate[Date] ) <= LastSaleDate, CALCULATE ( [Total Sales], DATESYTD ( DimDate[Date] ) ) )
```

### Sales 7-Day Moving Average
Average daily sales over the trailing 7 days (days without sales are ignored).  
Format: `$#,0;($#,0);$#,0`

```dax
Sales 7-Day Moving Average =
VAR CurrentDate = MAX ( DimDate[Date] )
RETURN
    IF (
        NOT ISBLANK ( [Total Sales] ),
        AVERAGEX ( DATESINPERIOD ( DimDate[Date], CurrentDate, -7, DAY ), [Total Sales] )
    )
```

### Latest Month Sales MoM %
Sales change of the latest month in the current selection vs the month before.  
Format: `+0.0%;-0.0%;0.0%`

```dax
Latest Month Sales MoM % =
VAR LastSaleDate = CALCULATE ( MAX ( DimDate[Date] ), FactSales )
VAR CurStart = DATE ( YEAR ( LastSaleDate ), MONTH ( LastSaleDate ), 1 )
VAR PrevStart = EDATE ( CurStart, -1 )
VAR CurSales = CALCULATE ( [Total Sales], DATESBETWEEN ( DimDate[Date], CurStart, EOMONTH ( CurStart, 0 ) ) )
VAR PrevSales = CALCULATE ( [Total Sales], DATESBETWEEN ( DimDate[Date], PrevStart, EOMONTH ( PrevStart, 0 ) ) )
RETURN
    IF ( NOT ISBLANK ( PrevSales ) && NOT ISBLANK ( CurSales ), DIVIDE ( CurSales - PrevSales, PrevSales ) )
```


## 05 Predictive (K-Means)

### Cluster Sales Share %
Share of sales generated by a K-Means segment.  
Format: `0.0%;-0.0%;0.0%`

```dax
Cluster Sales Share % = DIVIDE ( [Total Sales], CALCULATE ( [Total Sales], REMOVEFILTERS ( DimCluster ) ) )
```

### Cluster Transaction Share %
Share of transactions in a K-Means segment.  
Format: `0.0%;-0.0%;0.0%`

```dax
Cluster Transaction Share % = DIVIDE ( [Total Transactions], CALCULATE ( [Total Transactions], REMOVEFILTERS ( DimCluster ) ) )
```

### Selected K
Number of clusters chosen for the final model.  
Format: `0`

```dax
Selected K = CALCULATE ( MAX ( ClusterEvaluation[K] ), ClusterEvaluation[Is Selected K] = TRUE () )
```

### Model Silhouette Score
Silhouette score of the selected model (-1 to 1; higher = better separated).  
Format: `0.000`

```dax
Model Silhouette Score = CALCULATE ( MAX ( ClusterEvaluation[Silhouette] ), ClusterEvaluation[Is Selected K] = TRUE () )
```

### Model Stability ARI
Minimum Adjusted Rand Index between the final model and 10 re-runs with different random seeds (1 = identical clusters).  
Format: `0.000`

```dax
Model Stability ARI = CALCULATE ( MAX ( DimCluster[Model Stability ARI] ), REMOVEFILTERS ( DimCluster ) )
```

### Elbow Inertia
Within-cluster sum of squares for each k (elbow method).  
Format: `#,0`

```dax
Elbow Inertia = SUM ( ClusterEvaluation[Inertia] )
```

### Silhouette Score by K
Silhouette score for each k.  
Format: `0.000`

```dax
Silhouette Score by K = SUM ( ClusterEvaluation[Silhouette] )
```

### Segments Modelled
Number of K-Means segments present in the model.  
Format: `0`

```dax
Segments Modelled = CALCULATE ( DISTINCTCOUNT ( DimCluster[ClusterKey] ), REMOVEFILTERS ( DimCluster ) )
```

### Top Segment by Sales
Segment with the highest sales in the current selection.

```dax
Top Segment by Sales = CONCATENATEX ( TOPN ( 1, VALUES ( DimCluster[Cluster Label] ), [Total Sales], DESC ), DimCluster[Cluster Label], ", " )
```

### Top Segment Detail
Sales share and rating of the top segment.

```dax
Top Segment Detail =
VAR TopSeg = TOPN ( 1, VALUES ( DimCluster[ClusterKey] ), [Total Sales], DESC )
VAR SegSales = CALCULATE ( [Total Sales], TopSeg )
VAR SegTx = CALCULATE ( [Total Transactions], TopSeg )
RETURN
    FORMAT ( DIVIDE ( SegSales, [Total Sales] ), "0.0%" ) & " of sales from " & FORMAT ( DIVIDE ( SegTx, [Total Transactions] ), "0%" )
        & " of transactions · avg rating " & FORMAT ( CALCULATE ( [Average Rating], TopSeg ), "0.0" )
```

### High-Value Low-Rating Sales %
Share of sales from segments with above-average spend but below-average satisfaction (positive spend centroid, negative rating centroid).  
Format: `0.0%;-0.0%;0.0%`

```dax
High-Value Low-Rating Sales % =
DIVIDE (
    CALCULATE ( [Total Sales], DimCluster[Centroid Z Total] > 0, DimCluster[Centroid Z Rating] < 0 ),
    CALCULATE ( [Total Sales], REMOVEFILTERS ( DimCluster ) )
)
```


## 06 Narrative & Titles

### Report Period
Date range of the sales in the current selection.

```dax
Report Period =
VAR PeriodStart = CALCULATE ( MIN ( DimDate[Date] ), FactSales )
VAR PeriodEnd = CALCULATE ( MAX ( DimDate[Date] ), FactSales )
RETURN
    IF (
        ISBLANK ( PeriodStart ),
        "No sales in selection",
        FORMAT ( PeriodStart, "d mmm yyyy" ) & " – " & FORMAT ( PeriodEnd, "d mmm yyyy" ) & "  ·  " & FORMAT ( [Trading Days], "0" ) & " trading days  ·  " & FORMAT ( [Total Transactions], "#,0" ) & " transactions"
    )
```

### Selection Label
Plain-language description of the active slicer selection.

```dax
Selection Label =
VAR Parts = {
    IF ( ISFILTERED ( DimBranch ), "Branch " & CONCATENATEX ( VALUES ( DimBranch[Branch] ), DimBranch[Branch], "/" ) ),
    IF ( ISFILTERED ( DimProduct ), CONCATENATEX ( VALUES ( DimProduct[Product Line] ), DimProduct[Product Line], ", " ) ),
    IF ( ISFILTERED ( DimCustomer[Customer Type] ), CONCATENATEX ( VALUES ( DimCustomer[Customer Type] ), DimCustomer[Customer Type], "/" ) ),
    IF ( ISFILTERED ( DimCustomer[Gender] ), CONCATENATEX ( VALUES ( DimCustomer[Gender] ), DimCustomer[Gender], "/" ) ),
    IF ( ISFILTERED ( DimPayment ), CONCATENATEX ( VALUES ( DimPayment[Payment Method] ), DimPayment[Payment Method], "/" ) ),
    IF ( ISFILTERED ( DimDate ), CONCATENATEX ( SUMMARIZE ( DimDate, DimDate[Month], DimDate[Month Start] ), DimDate[Month], "/", DimDate[Month Start], ASC ) )
}
VAR Txt = CONCATENATEX ( FILTER ( Parts, NOT ISBLANK ( [Value] ) ), [Value], "  ·  " )
RETURN
    IF ( Txt = "", "Showing all branches, products, customers and months", "Filtered: " & Txt )
```

### Top Branch by Sales
Branch with the highest sales in the current selection.

```dax
Top Branch by Sales = CONCATENATEX ( TOPN ( 1, VALUES ( DimBranch[Branch Label] ), [Total Sales], DESC ), DimBranch[Branch Label], ", " )
```

### Top Branch Detail
Sales and share of the top branch.

```dax
Top Branch Detail =
VAR TopB = TOPN ( 1, VALUES ( DimBranch[BranchKey] ), [Total Sales], DESC )
VAR S = CALCULATE ( [Total Sales], TopB )
RETURN
    FORMAT ( S, "$#,0" ) & " · " & FORMAT ( DIVIDE ( S, [Total Sales] ), "0.0%" ) & " of sales"
```

### Top Branch by Gross Income
Branch with the highest gross income.

```dax
Top Branch by Gross Income = CONCATENATEX ( TOPN ( 1, VALUES ( DimBranch[Branch Label] ), [Total Gross Income], DESC ), DimBranch[Branch Label], ", " )
```

### Top Product Line by Sales
Product line with the highest sales.

```dax
Top Product Line by Sales = CONCATENATEX ( TOPN ( 1, VALUES ( DimProduct[Product Line] ), [Total Sales], DESC ), DimProduct[Product Line], ", " )
```

### Top Product Line Detail
Sales and share of the top product line.

```dax
Top Product Line Detail =
VAR TopP = TOPN ( 1, VALUES ( DimProduct[ProductKey] ), [Total Sales], DESC )
VAR S = CALCULATE ( [Total Sales], TopP )
RETURN
    FORMAT ( S, "$#,0" ) & " · " & FORMAT ( DIVIDE ( S, [Total Sales] ), "0.0%" ) & " of sales"
```

### Top Product Line by Gross Income
Product line with the highest gross income.

```dax
Top Product Line by Gross Income = CONCATENATEX ( TOPN ( 1, VALUES ( DimProduct[Product Line] ), [Total Gross Income], DESC ), DimProduct[Product Line], ", " )
```

### Top Product Line by Gross Income Detail
Gross income and margin of the top product line by gross income.

```dax
Top Product Line by Gross Income Detail =
VAR TopP = TOPN ( 1, VALUES ( DimProduct[ProductKey] ), [Total Gross Income], DESC )
RETURN
    FORMAT ( CALCULATE ( [Total Gross Income], TopP ), "$#,0" ) & " gross income · margin " & FORMAT ( CALCULATE ( [Gross Margin %], TopP ), "0.00%" )
```

### Top Product Line by Quantity
Product line with the most units sold.

```dax
Top Product Line by Quantity = CONCATENATEX ( TOPN ( 1, VALUES ( DimProduct[Product Line] ), [Total Quantity Sold], DESC ), DimProduct[Product Line], ", " )
```

### Top Product Line by Quantity Detail
Units of the top product line by quantity.

```dax
Top Product Line by Quantity Detail =
VAR TopP = TOPN ( 1, VALUES ( DimProduct[ProductKey] ), [Total Quantity Sold], DESC )
RETURN
    FORMAT ( CALCULATE ( [Total Quantity Sold], TopP ), "#,0" ) & " units · " & FORMAT ( CALCULATE ( [Total Transactions], TopP ), "#,0" ) & " transactions"
```

### Lowest Product Line by Sales
Product line with the lowest sales.

```dax
Lowest Product Line by Sales = CONCATENATEX ( TOPN ( 1, VALUES ( DimProduct[Product Line] ), [Total Sales], ASC ), DimProduct[Product Line], ", " )
```

### Lowest Product Line Detail
Gap between the lowest and highest product line.

```dax
Lowest Product Line Detail =
VAR LowP = TOPN ( 1, VALUES ( DimProduct[ProductKey] ), [Total Sales], ASC )
VAR TopP = TOPN ( 1, VALUES ( DimProduct[ProductKey] ), [Total Sales], DESC )
VAR LowS = CALCULATE ( [Total Sales], LowP )
VAR TopS = CALCULATE ( [Total Sales], TopP )
RETURN
    FORMAT ( LowS, "$#,0" ) & " · " & FORMAT ( DIVIDE ( TopS - LowS, TopS ), "0.0%" ) & " below the leader"
```

### Insight Weakest Product Line
Lowest-selling product line with its gap to the leader.

```dax
Insight Weakest Product Line = [Lowest Product Line by Sales] & " · " & [Lowest Product Line Detail]
```

### Top Branch-Product Combination
Strongest Branch x Product Line cell by sales.

```dax
Top Branch-Product Combination =
VAR Combos = SUMMARIZE ( FactSales, DimBranch[Branch], DimProduct[Product Line] )
VAR TopC = TOPN ( 1, Combos, [Total Sales], DESC )
RETURN
    CONCATENATEX ( TopC, "Branch " & DimBranch[Branch] & " · " & DimProduct[Product Line] & " (" & FORMAT ( [Total Sales], "$#,0" ) & ")", ", " )
```

### Most Used Payment Method
Payment method with the most transactions.

```dax
Most Used Payment Method = CONCATENATEX ( TOPN ( 1, VALUES ( DimPayment[Payment Method] ), [Total Transactions], DESC ), DimPayment[Payment Method], ", " )
```

### Most Used Payment Detail
Share of transactions for the most used payment method.

```dax
Most Used Payment Detail =
VAR TopPay = TOPN ( 1, VALUES ( DimPayment[PaymentKey] ), [Total Transactions], DESC )
RETURN
    FORMAT ( DIVIDE ( CALCULATE ( [Total Transactions], TopPay ), [Total Transactions] ), "0.0%" ) & " of transactions · cashless " & FORMAT ( [Cashless Sales %], "0.0%" ) & " of sales"
```

### Peak Hour
Hour slot with the most transactions.

```dax
Peak Hour = CONCATENATEX ( TOPN ( 1, VALUES ( DimTime[Hour] ), [Total Transactions], DESC ), DimTime[Hour], ", " )
```

### Peak Hour Detail
Transactions and sales in the peak hour.

```dax
Peak Hour Detail =
VAR TopH = TOPN ( 1, VALUES ( DimTime[HourKey] ), [Total Transactions], DESC )
RETURN
    FORMAT ( CALCULATE ( [Total Transactions], TopH ), "#,0" ) & " transactions · " & FORMAT ( CALCULATE ( [Total Sales], TopH ), "$#,0" ) & " sales"
```

### Busiest Day of Week
Weekday with the highest sales.

```dax
Busiest Day of Week = CONCATENATEX ( TOPN ( 1, VALUES ( DimDate[Day Name] ), [Total Sales], DESC ), DimDate[Day Name], ", " )
```

### Highest Rated Branch
Branch with the highest average rating.

```dax
Highest Rated Branch = CONCATENATEX ( TOPN ( 1, VALUES ( DimBranch[Branch Label] ), [Average Rating], DESC ), DimBranch[Branch Label], ", " )
```

### Highest Rated Branch Detail
Rating of the highest and lowest rated branch.

```dax
Highest Rated Branch Detail =
VAR TopB = TOPN ( 1, VALUES ( DimBranch[BranchKey] ), [Average Rating], DESC )
VAR LowB = TOPN ( 1, VALUES ( DimBranch[BranchKey] ), [Average Rating], ASC )
RETURN
    "Avg " & FORMAT ( CALCULATE ( [Average Rating], TopB ), "0.00" ) & " vs lowest " & CALCULATE ( SELECTEDVALUE ( DimBranch[Branch Label] ), LowB ) & " " & FORMAT ( CALCULATE ( [Average Rating], LowB ), "0.00" )
```

### Highest Rated Product Line
Product line with the highest average rating.

```dax
Highest Rated Product Line = CONCATENATEX ( TOPN ( 1, VALUES ( DimProduct[Product Line] ), [Average Rating], DESC ), DimProduct[Product Line], ", " )
```

### Member vs Normal Spend
Members' vs normal customers' average transaction value.

```dax
Member vs Normal Spend = "Members " & FORMAT ( [Member ATV], "$#,0" ) & " vs Normal " & FORMAT ( [Normal ATV], "$#,0" ) & " per transaction (" & FORMAT ( [Member ATV Premium %], "+0.0%;-0.0%" ) & ")"
```

### KPI Sales Subtitle
KPI card subtitle: latest month vs the month before.

```dax
KPI Sales Subtitle =
VAR Chg = [Latest Month Sales MoM %]
VAR LastSaleDate = CALCULATE ( MAX ( DimDate[Date] ), FactSales )
RETURN
    IF (
        ISBLANK ( Chg ),
        "Total for selected period",
        IF ( Chg >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( Chg ), "0.0%" ) & "  " & FORMAT ( LastSaleDate, "mmm" ) & " vs " & FORMAT ( EDATE ( LastSaleDate, -1 ), "mmm" )
    )
```

### KPI Gross Income Subtitle
KPI card subtitle for gross income.

```dax
KPI Gross Income Subtitle = "Gross margin " & FORMAT ( [Gross Margin %], "0.00%" )
```

### KPI Transactions Subtitle
KPI card subtitle for transactions.

```dax
KPI Transactions Subtitle = FORMAT ( DIVIDE ( [Total Transactions], [Trading Days] ), "0.0" ) & " per trading day"
```

### KPI Quantity Subtitle
KPI card subtitle for quantity.

```dax
KPI Quantity Subtitle = FORMAT ( [Quantity per Transaction], "0.0" ) & " units / transaction"
```

### KPI ATV Subtitle
KPI card subtitle for average transaction value.

```dax
KPI ATV Subtitle = "Avg unit price " & FORMAT ( [Average Unit Price], "$#,0.00" )
```

### KPI Rating Subtitle
KPI card subtitle for rating.

```dax
KPI Rating Subtitle = FORMAT ( [High Rating % (8+)], "0%" ) & " of visits rated 8+"
```

### KPI Member Subtitle
KPI card subtitle: member vs normal basket value.

```dax
KPI Member Subtitle = "Member basket " & FORMAT ( [Member ATV Premium %], "+0.0%;-0.0%" ) & " vs normal"
```

### KPI Payment Subtitle
KPI card subtitle: share of transactions for the most used payment method.

```dax
KPI Payment Subtitle =
VAR TopPay = TOPN ( 1, VALUES ( DimPayment[PaymentKey] ), [Total Transactions], DESC )
RETURN
    FORMAT ( DIVIDE ( CALCULATE ( [Total Transactions], TopPay ), [Total Transactions] ), "0.0%" ) & " of transactions"
```

### Title Gross Income Product
Dynamic title.

```dax
Title Gross Income Product = "Gross Income  ·  " & FORMAT ( [Gross Margin %], "0.00%" ) & " margin"
```

### Title Branch Sales
Dynamic title.

```dax
Title Branch Sales = "Sales by Branch  ·  " & [Top Branch by Sales] & " leads"
```

### Title Product Sales
Dynamic title.

```dax
Title Product Sales = "Sales by Product Line  ·  " & [Top Product Line by Sales] & " leads"
```

### Title Monthly Sales
Dynamic title.

```dax
Title Monthly Sales =
VAR Chg = [Latest Month Sales MoM %]
RETURN
    "Monthly Sales" & IF ( NOT ISBLANK ( Chg ), "  ·  " & FORMAT ( Chg, "+0.0%;-0.0%" ) & " MoM" )
```

### Title Hourly
Dynamic title.

```dax
Title Hourly = "Transactions by Hour  ·  peak at " & [Peak Hour]
```

### Title Daily Trend
Dynamic title.

```dax
Title Daily Trend = "Daily Sales Trend  ·  " & [Busiest Day of Week] & " strongest"
```
