# Adventure Works Sales

Bike-retailer sales, returns and profitability - and a working notebook of DAX techniques.

![Executive Summary](screenshots/01-executive-summary.png)

---

## About

Two things share one file. The first four pages are a sales dashboard: an executive
summary with total sales, quantity and profit, a country view over a map, and a
product-category breakdown with return rates and a profit ranking.

The remaining nineteen pages are a **DAX and Power BI technique workbook**, and the page
names say so - `Calculate`, `ALL`, `IF Switch`, `Ranking`, `YTD QTD MTD`,
`LD LM LY LQ MOM`, `Bookmarks`, `Smart Narrative`, `Q & A`, `Shape Map`,
`Decomposition Tree`, `Radar`, `Comic`, `Plotly Waterfall`. Each isolates one idea and
shows it working against real data - for instance four different `Rank Analysis` measures
side by side (plain, `ALL`, `ALLSELECTED`, `CROSSJOIN`), and `GER and FRA sales using
(AND)` against `... using (OR)` to show how the filter arguments differ.

It is the widest file here: 51 measures and 25 distinct visual types, including a KPI, a
ribbon chart, a waterfall, a radar, a shape map and two custom visuals.

---

## Contents

| | |
|---|---|
| **Pages** | 23 documented of 25 (tooltip pages excluded) |
| **Visual types** | 31 - card, tableEx, slicer, actionButton, lineChart, textbox, scatterChart, areaChart, ... |
| **Model** | 8 tables, 51 DAX measures, 72 distinct fields on the pages |
| **File** | [`Adventure_work PBI (1).pbix`](Adventure_work%20PBI%20%281%29.pbix) - 8.5 MB |

> **The data is inside the file.** The model is imported, so the report opens and
> renders in Power BI Desktop without the original source dataset, which is not
> included here.

---

## Every page

**1. Executive Summary** - 13 visuals

![Executive Summary](screenshots/01-executive-summary.png)

**2. Sales** - 11 visuals

![Sales](screenshots/02-sales.png)

**3. Country Wise** - 13 visuals

![Country Wise](screenshots/03-country-wise.png)

**4. Moving Sales** - 4 visuals

![Moving Sales](screenshots/04-moving-sales.png)

**5. Cards Visual** - 11 visuals

![Cards Visual](screenshots/05-cards-visual.png)

**6. Decomposition Tre** - 1 visuals

![Decomposition Tre](screenshots/06-decomposition-tre.png)

**7. LD LM LY LQ MOM** - 3 visuals

![LD LM LY LQ MOM](screenshots/07-ld-lm-ly-lq-mom.png)

**8. Forcasting** - 1 visuals

![Forcasting](screenshots/08-forcasting.png)

**9. YTD QTD MTD ** - 3 visuals

![YTD QTD MTD ](screenshots/09-ytd-qtd-mtd.png)

**10. Bookmarks** - 9 visuals

![Bookmarks](screenshots/10-bookmarks.png)

**11. Calculate** - 3 visuals

![Calculate](screenshots/11-calculate.png)

**12. Smart Narrative** - 6 visuals

![Smart Narrative](screenshots/12-smart-narrative.png)

**13. Radar** - 4 visuals

![Radar](screenshots/13-radar.png)

**14. Scater plot** - 1 visuals

![Scater plot](screenshots/14-scater-plot.png)

**15. ALL** - 8 visuals

![ALL](screenshots/15-all.png)

**16. IF Switch** - 1 visuals

![IF Switch](screenshots/16-if-switch.png)

**17. Shape Map** - 2 visuals

![Shape Map](screenshots/17-shape-map.png)

**18. Tree Map** - 1 visuals

![Tree Map](screenshots/18-tree-map.png)

**19. Comic** - 3 visuals

![Comic](screenshots/19-comic.png)

**20. Plotly Waterfall** - 2 visuals

![Plotly Waterfall](screenshots/20-plotly-waterfall.png)

**21. Q & A** - 1 visuals

![Q & A](screenshots/21-q-a.png)

**22. Cards** - 2 visuals

![Cards](screenshots/22-cards.png)

**23. Filters** - 2 visuals

![Filters](screenshots/23-filters.png)

---

## DAX measures

Read out of the report definition, so this is what the pages actually use:

```
% Change in Product Sales (ALL), % Change in Product Sales (AllSelected), 7days Moving Average, Actual Total Sales, Average moving sales, Country Name, Country Sales All, Emotional Status, France Sales, GER C and FRA region sales, GER C and GER Region, GER and FRA sales using (AND), GER and FRA sales using (OR), Germany Red Sales (TS), Germany Red Sales(ger sales), Germany Sales, Germany Sales using filters, Germany Sales-keeping filters, Germany and France Sales, If Analysis, Last Day Sales, Last Month Profit, Last Month Returns, Last Month Sales, Last Month Transactions, Last Quarter Sales, Last Year Sales, MTD Sales, Month on Month Sales, Moving Avg 7Days, Pose Status, Product Sales All, Product Sales AllSelected, Profit Margin, Profits, QTD Sales, Quantity Return, Quantity Sold, Rank Analysis, Rank Analysis removing spaces, Rank Analysis using ALL, Rank Analysis using AllSelected, Rank Analysis using CrossJoin, Return Rate, Sales All, Switch Analysis, Total Cost, Total Returns, Total Sales, Total Transactions, YTD Sales
```

## Status

Earlier work, kept for the record. There is no build script, no automated
validation and no reproducible data pipeline here - unlike the five projects in
the root of this repository. What is documented above was read directly out of
the `.pbix`, and every screenshot is the report rendering its own embedded data.
