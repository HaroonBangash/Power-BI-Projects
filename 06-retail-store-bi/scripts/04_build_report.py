"""
04_build_report.py
------------------
Generates the Power BI report (PBIR format) for RetailStore_BI.pbip:
  * DashFlow-style dark theme (StaticResources/RegisteredResources/DashFlowTheme.json)
  * page background image with a soft violet glow (bg_dashflow.png)
  * four report pages with all visuals, slicers (synced) and page navigation

Re-run after layout changes:  python scripts/04_build_report.py
The semantic model (TMDL) is maintained separately and is not touched.
"""
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "RetailStore_BI.Report"
DEF = REPORT / "definition"
RES = REPORT / "StaticResources" / "RegisteredResources"
M = "Key Measures"

# ------------------------------------------------------------------ palette
BG_PAGE = "#0A0A0F"      # app frame
BG_CARD = "#13131B"      # cards
BG_INPUT = "#1B1B26"     # slicer boxes / table headers
BORDER = "#262633"
TEXT = "#F4F3FF"
TEXT_2 = "#A3A1B8"
TEXT_3 = "#6E6C84"
LAVENDER = "#A99BFF"     # primary single-series accent (from the reference image)
VIOLET = "#7B61FF"
PINK = "#FF8FC7"
GREEN = "#3DDC97"
WALLPAPER = "#9B93CC"    # lavender backdrop around the canvas
CATEGORICAL = ["#8E7CF6", "#DC6299", "#2E9BD0", "#D3753A", "#5A57D6", "#1F9A80"]  # validated for dark mode
FONT = "Segoe UI"
FONT_SB = "Segoe UI Semibold"
FONT_B = "Segoe UI Bold"

W, H = 1280, 720
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json"


# ------------------------------------------------------------------ expression helpers
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + str(text).replace("'", "''") + "'")


def n(x):
    return lit(f"{x}D")


def b(x):
    return lit("true" if x else "false")


def color(hexv):
    return {"solid": {"color": s(hexv)}}


def measure(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": M}}, "Property": name}}


def column(table, col):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}}


def mexpr(name):
    return {"expr": measure(name)}


def proj(field, display=None):
    kind = "Measure" if "Measure" in field else "Column"
    ent = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    p = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def qref(field):
    kind = "Measure" if "Measure" in field else "Column"
    return f'{field[kind]["Expression"]["SourceRef"]["Entity"]}.{field[kind]["Property"]}'


# ------------------------------------------------------------------ container formatting
def container(title=None, subtitle=None, subtitle_measure=None, title_measure=None, bg=True, border=True,
              title_align="left", title_size=11, title_color=TEXT, padding=None, radius=14, bg_color=BG_CARD,
              bg_transparency=0, link=None):
    o = {}
    if title or title_measure:
        o["title"] = [{"properties": {
            "show": b(True),
            "text": mexpr(title_measure) if title_measure else s(title),
            "fontColor": color(title_color), "fontSize": n(title_size), "fontFamily": s(FONT_SB),
            "alignment": s(title_align), "titleWrap": b(False)}}]
    else:
        o["title"] = [{"properties": {"show": b(False)}}]
    if subtitle or subtitle_measure:
        o["subTitle"] = [{"properties": {
            "show": b(True),
            "text": mexpr(subtitle_measure) if subtitle_measure else s(subtitle),
            "fontColor": color(TEXT_2), "fontSize": n(9), "fontFamily": s(FONT), "alignment": s(title_align)}}]
    o["background"] = [{"properties": {"show": b(bg), "color": color(bg_color), "transparency": n(bg_transparency)}}]
    o["border"] = [{"properties": {"show": b(border), "color": color(BORDER), "radius": n(radius), "width": n(1)}}]
    o["dropShadow"] = [{"properties": {"show": b(False)}}]
    pad = padding or (12, 14, 10, 14)
    o["padding"] = [{"properties": {"top": n(pad[0]), "right": n(pad[1]), "bottom": n(pad[2]), "left": n(pad[3])}}]
    o["visualHeader"] = [{"properties": {"show": b(bg and (title is not None or title_measure is not None))}}]
    if link:
        o["visualLink"] = [{"properties": link}]
    return o


class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals, self.z = name, display, [], 0

    def add(self, vname, x, y, w, h, visual, hidden=False):
        self.z += 1
        vc = {"$schema": VC_SCHEMA, "name": vname,
              "position": {"x": x, "y": y, "z": self.z * 1000, "height": h, "width": w, "tabOrder": self.z * 1000},
              "visual": visual}
        if hidden:
            vc["isHidden"] = True
        self.visuals.append(vc)
        return vc


# ------------------------------------------------------------------ visual builders
def textbox(paragraphs, vco):
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": vco, "drillFilterOtherVisuals": True}


def para(runs, align="left"):
    p = {"textRuns": [{"value": t, "textStyle": st} for t, st in runs]}
    if align != "left":
        p["horizontalTextAlignment"] = align
    return p


def style(size, col=TEXT, family=FONT, weight=None):
    st = {"fontFamily": family, "fontSize": f"{size}pt", "color": col}
    if weight:
        st["fontWeight"] = weight
    return st


def card(mname, title, subtitle_measure=None, value_size=22, value_color=TEXT, title_align="right", wrap=False,
         bg=True, border=True, padding=(10, 14, 8, 14), title_size=8, family=FONT_SB):
    objs = {
        "labels": [{"properties": {"color": color(value_color), "fontSize": n(value_size), "fontFamily": s(family)}}],
        "categoryLabels": [{"properties": {"show": b(False)}}],
    }
    if wrap:
        objs["wordWrap"] = [{"properties": {"show": b(True)}}]
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(measure(mname))]}}},
            "objects": objs,
            "visualContainerObjects": container(title=title, subtitle_measure=subtitle_measure, title_align=title_align,
                                                title_size=title_size, title_color=TEXT_2, bg=bg, border=border,
                                                padding=padding),
            "drillFilterOtherVisuals": True}


def axis_objects(show_value_axis=True, labels=True, label_units=None):
    o = {
        "categoryAxis": [{"properties": {"labelColor": color(TEXT_2), "fontSize": n(8), "showAxisTitle": b(False),
                                         "gridlineShow": b(False)}}],
        "valueAxis": [{"properties": {"show": b(show_value_axis), "labelColor": color(TEXT_3), "fontSize": n(8),
                                      "showAxisTitle": b(False), "gridlineShow": b(show_value_axis),
                                      "gridlineColor": color(BORDER), "gridlineStyle": s("dotted")}}],
        "labels": [{"properties": {"show": b(labels), "color": color(TEXT), "fontSize": n(8)}}],
    }
    if label_units is not None:
        o["labels"][0]["properties"]["labelDisplayUnits"] = n(label_units)
    return o


def bar(cat, mname, title=None, title_measure=None, subtitle=None, fill=LAVENDER, tooltips=(), sort_desc=True,
        vtype="clusteredBarChart", series=None, label_units=None, show_value_axis=False):
    qs = {"Category": {"projections": [proj(cat)]}, "Y": {"projections": [proj(measure(mname))]}}
    if series is not None:
        qs["Series"] = {"projections": [proj(series)]}
    if tooltips:
        qs["Tooltips"] = {"projections": [proj(measure(t)) for t in tooltips]}
    q = {"queryState": qs}
    if sort_desc:
        q["sortDefinition"] = {"sort": [{"field": measure(mname), "direction": "Descending"}], "isDefaultSort": True}
    else:
        q["sortDefinition"] = {"sort": [{"field": cat, "direction": "Ascending"}], "isDefaultSort": True}
    objs = axis_objects(show_value_axis=show_value_axis, label_units=label_units)
    if vtype == "clusteredBarChart":
        objs["categoryAxis"][0]["properties"]["maxMarginFactor"] = n(45)
        objs["categoryAxis"][0]["properties"]["innerPadding"] = n(28)
    if series is None:
        objs["dataPoint"] = [{"properties": {"fill": color(fill)}}]
    else:
        objs["legend"] = [{"properties": {"show": b(True), "position": s("TopRight"), "labelColor": color(TEXT_2),
                                          "fontSize": n(8)}}]
    return {"visualType": vtype, "query": q, "objects": objs,
            "visualContainerObjects": container(title=title, title_measure=title_measure, subtitle=subtitle),
            "drillFilterOtherVisuals": True}


def slicer(field, header, group):
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj(field)]}}},
            "objects": {
                "data": [{"properties": {"mode": s("Dropdown")}}],
                "header": [{"properties": {"show": b(True), "text": s(header), "fontColor": color(TEXT_2),
                                           "textSize": n(8), "fontFamily": s(FONT)}}],
                "items": [{"properties": {"fontColor": color(TEXT), "background": color(BG_INPUT), "textSize": n(9),
                                          "fontFamily": s(FONT)}}],
                "selection": [{"properties": {"selectAllCheckboxEnabled": b(True), "singleSelect": b(False)}}],
            },
            "visualContainerObjects": container(bg=False, border=False, padding=(0, 0, 0, 0)),
            "syncGroup": {"groupName": group, "fieldChanges": True, "filterChanges": True},
            "drillFilterOtherVisuals": True}


def nav_button(text, target, active, size=10, glyph=False, tooltip=None):
    fc = LAVENDER if active else (TEXT_2 if glyph else TEXT_3)
    fill = "#24243A" if (active and glyph) else BG_CARD
    objs = {
        "icon": [{"properties": {"show": b(False)}}],
        "text": [{"properties": {"show": b(True)}},
                 {"properties": {"text": s(text), "fontColor": color(fc), "fontSize": n(size),
                                 "fontFamily": s("Segoe UI Symbol" if glyph else (FONT_SB if active else FONT)),
                                 "horizontalAlignment": s("center"), "verticalAlignment": s("middle")},
                  "selector": {"id": "default"}},
                 {"properties": {"fontColor": color(TEXT)}, "selector": {"id": "hover"}}],
        "fill": [{"properties": {"show": b(True)}},
                 {"properties": {"fillColor": color(fill), "transparency": n(0 if (active and glyph) else 100)},
                  "selector": {"id": "default"}},
                 {"properties": {"fillColor": color("#24243A"), "transparency": n(0)}, "selector": {"id": "hover"}}],
        "outline": [{"properties": {"show": b(False)}}],
        "shape": [{"properties": {"tileShape": s("rectangleRounded"), "rectangleRoundedCurve": lit("12L")}}],
    }
    link = {"show": b(True), "type": s("PageNavigation"), "navigationSection": s(target)}
    if tooltip:
        link["tooltip"] = s(tooltip)
    vco = container(bg=False, border=False, padding=(0, 0, 0, 0), link=link)
    return {"visualType": "actionButton", "objects": objs, "visualContainerObjects": vco, "drillFilterOtherVisuals": True}


def heat_matrix(rows, cols, mname, title, subtitle=None, lo="#1A1A26", hi=VIOLET, row_label=None, pad=6):
    rule = {"FillRule": {"Input": measure(mname),
                         "FillRule": {"linearGradient2": {
                             "min": {"color": {"Literal": {"Value": f"'{lo}'"}}},
                             "max": {"color": {"Literal": {"Value": f"'{hi}'"}}},
                             "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}
    return {"visualType": "pivotTable",
            "query": {"queryState": {"Rows": {"projections": [proj(rows, row_label)]},
                                     "Columns": {"projections": [proj(cols)]},
                                     "Values": {"projections": [proj(measure(mname))]}}},
            "objects": {
                "values": [{"properties": {"backColor": {"solid": {"color": {"expr": rule}}}},
                            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": qref(measure(mname))}},
                           {"properties": {"fontColorPrimary": color(TEXT), "fontColorSecondary": color(TEXT),
                                           "fontSize": n(9)}}],
                "columnHeaders": [{"properties": {"fontColor": color(TEXT_2), "backColor": color(BG_CARD), "fontSize": n(8),
                                                  "wordWrap": b(True), "alignment": s("Center")}}],
                "rowHeaders": [{"properties": {"fontColor": color(TEXT), "backColor": color(BG_CARD), "fontSize": n(9)}}],
                "grid": [{"properties": {"gridVertical": b(True), "gridVerticalColor": color(BG_CARD), "gridVerticalWeight": n(2),
                                         "gridHorizontal": b(True), "gridHorizontalColor": color(BG_CARD),
                                         "gridHorizontalWeight": n(2), "rowPadding": n(pad)}}],
                "subTotals": [{"properties": {"rowSubtotals": b(False), "columnSubtotals": b(False)}}],
                "total": [{"properties": {"fontColor": color(TEXT), "backColor": color(BG_INPUT)}}],
            },
            "visualContainerObjects": container(title=title, subtitle=subtitle),
            "drillFilterOtherVisuals": True}


def table(fields, title, subtitle=None, sort_field=None, wrap=False, font=9, row_pad=2, widths=None):
    q = {"queryState": {"Values": {"projections": [proj(f, d) for f, d in fields]}}}
    if sort_field is not None:
        q["sortDefinition"] = {"sort": [{"field": sort_field, "direction": "Descending"}], "isDefaultSort": True}
    return {"visualType": "tableEx", "query": q,
            "objects": {
                "values": [{"properties": {"fontColorPrimary": color(TEXT), "fontColorSecondary": color(TEXT),
                                           "backColorPrimary": color(BG_CARD), "backColorSecondary": color("#171722"),
                                           "fontSize": n(font), "wordWrap": b(wrap)}}],
                "columnHeaders": [{"properties": {"fontColor": color(TEXT_2), "backColor": color(BG_INPUT),
                                                  "fontSize": n(8), "wordWrap": b(True), "bold": b(False)}}],
                "grid": [{"properties": {"gridHorizontal": b(True), "gridHorizontalColor": color(BORDER),
                                         "gridVertical": b(False), "rowPadding": n(row_pad),
                                         "outlineColor": color(BORDER)}}],
                "total": [{"properties": {"totals": b(False)}}],
                **({"columnWidth": [{"properties": {"value": n(wd)}, "selector": {"metadata": qref(f)}} for f, wd in widths]}
                   if widths else {}),
            },
            "visualContainerObjects": container(title=title, subtitle=subtitle),
            "drillFilterOtherVisuals": True}


# ------------------------------------------------------------------ page scaffolding
PAGES = [("ExecutiveOverview", "1 · Executive Overview", "Executive Sales Overview",
          "How are sales, gross income and customer satisfaction tracking across the three branches?", "⌂"),
         ("ProductBranch", "2 · Product & Branch", "Product & Branch Analysis",
          "What is selling, where it sells, and whether strong sellers are also the most profitable.", "▥"),
         ("CustomerBehaviour", "3 · Customer Behaviour", "Customer & Behaviour Analysis",
          "Who buys, how they pay, when they shop and how satisfied they are.", "◉"),
         ("PredictiveSegments", "4 · Predictive Segments", "Predictive Analytics · K-Means Segmentation",
          "Transactions clustered on standardised spend, basket size and rating into four actionable segments.", "✦")]
TAB_LABELS = ["Executive Overview", "Product & Branch", "Customer Behaviour", "Predictive Segments"]

SLICERS = [(column("DimBranch", "Branch Label"), "Branch", "Branch"),
           (column("DimProduct", "Product Line"), "Product line", "ProductLine"),
           (column("DimDate", "Month"), "Month", "Month"),
           (column("DimCustomer", "Customer Type"), "Customer type", "CustomerType"),
           (column("DimCustomer", "Gender"), "Gender", "Gender"),
           (column("DimPayment", "Payment Method"), "Payment", "Payment")]

X0, CW = 100, 1164   # content left edge and width (ends at 1264)


def scaffold(page, idx):
    pid, _, title, question, _ = PAGES[idx]
    # left navigation rail
    page.add("navRail", 12, 12, 72, 696, textbox([para([("", style(8))])], container(radius=18)))
    page.add("navLogo", 24, 24, 48, 48, textbox(
        [para([("✦", style(18, "#14141D", "Segoe UI Symbol"))], "center")],
        container(bg=True, border=False, bg_color=LAVENDER, radius=14, padding=(9, 0, 0, 0))))
    for i, (p_id, _, _, _, glyph) in enumerate(PAGES):
        page.add(f"navIcon{i + 1}", 24, 96 + i * 56, 48, 46,
                 nav_button(glyph, p_id, i == idx, size=16, glyph=True, tooltip=TAB_LABELS[i]))
    page.add("navDivider", 30, 334, 36, 1, textbox([para([("", style(1))])],
                                                    container(bg=True, border=False, bg_color=BORDER, radius=0, padding=(0, 0, 0, 0))))
    # brand + period pill
    page.add("brand", X0, 8, 520, 36, textbox(
        [para([("Retail Store BI", style(14, TEXT, FONT_B)), ("   ICT701 · Business Intelligence Case Study", style(9, TEXT_3))])],
        container(bg=False, border=False, padding=(6, 0, 0, 2))))
    page.add("reportPeriod", 820, 10, 444, 30, card("Report Period", None, value_size=9, value_color=TEXT_2,
                                                     padding=(0, 8, 0, 8), family=FONT, border=True, bg=True))
    # hero panel (transparent so the background glow shows through)
    page.add("heroPanel", X0, 50, CW, 128, textbox([para([("", style(8))])],
                                                   container(bg=True, bg_color=BG_CARD, bg_transparency=55, radius=18)))
    page.add("heroTitle", 112, 58, 600, 70, textbox(
        [para([(title, style(21, TEXT, FONT_B))]), para([(question, style(9.5, TEXT_2))])],
        container(bg=False, border=False, padding=(4, 4, 0, 4))))
    for i, (p_id, _, _, _, _) in enumerate(PAGES):
        x = 116 + i * 150
        page.add(f"tab{i + 1}", x, 136, 146, 30, nav_button(TAB_LABELS[i], p_id, i == idx, size=9.5))
    page.add("tabUnderline", 116 + idx * 150 + 20, 166, 106, 2, textbox(
        [para([("", style(1))])], container(bg=True, border=False, bg_color=LAVENDER, radius=1, padding=(0, 0, 0, 0))))
    # synced slicers: 2 rows x 3
    for i, (f, header, group) in enumerate(SLICERS):
        r, c = divmod(i, 3)
        page.add(f"slicer{group}", 742 + c * 174, 56 + r * 48, 166, 46, slicer(f, header, group))
    page.add("selectionLabel", 742, 152, 514, 22, card("Selection Label", None, value_size=8, value_color=LAVENDER,
                                                       padding=(0, 0, 0, 0), family=FONT, bg=False, border=False))


def kpi_row(page, items, y=190, h=86, icons=True):
    """items: (visualName, measure, title, subtitleMeasure, glyph, tileColour, valueSize)"""
    k = len(items)
    gap = 12
    w = (CW - gap * (k - 1)) / k
    for i, (vname, mname, title, sub, glyph, tile, vsize) in enumerate(items):
        x = round(X0 + i * (w + gap))
        page.add(vname, x, y, round(w), h, card(mname, title, sub, value_size=vsize, wrap=vsize < 16,
                                                padding=(10, 14, 8, 52 if icons else 14)))
        if icons:
            page.add(vname + "Icon", x + 12, y + 12, 30, 30, textbox(
                [para([(glyph, style(12, "#FFFFFF", "Segoe UI Symbol"))], "center")],
                container(bg=True, border=False, bg_color=tile, radius=9, padding=(4, 0, 0, 0))))


# ------------------------------------------------------------------ pages
def page_executive():
    p = Page(*PAGES[0][:2])
    scaffold(p, 0)
    kpi_row(p, [
        ("kpiTotalSales", "Total Sales", "TOTAL SALES", "KPI Sales Subtitle", "$", VIOLET, 22),
        ("kpiGrossIncome", "Total Gross Income", "GROSS INCOME", "KPI Gross Income Subtitle", "◈", "#E8794E", 22),
        ("kpiTransactions", "Total Transactions", "TRANSACTIONS", "KPI Transactions Subtitle", "⇄", "#D65A93", 22),
        ("kpiQuantity", "Total Quantity Sold", "QUANTITY SOLD", "KPI Quantity Subtitle", "▦", "#2E9BD0", 22),
        ("kpiATV", "Average Transaction Value", "AVG TRANSACTION", "KPI ATV Subtitle", "≈", "#1F9A80", 22),
        ("kpiRating", "Average Rating", "AVG RATING (1-10)", "KPI Rating Subtitle", "★", "#C9902E", 22),
    ])
    # Row A
    line = {"visualType": "lineChart",
            "query": {"queryState": {
                "Category": {"projections": [proj(column("DimDate", "Date"))]},
                "Y": {"projections": [proj(measure("Total Sales"), "Daily sales"),
                                      proj(measure("Sales 7-Day Moving Average"), "7-day moving average")]}},
                "sortDefinition": {"sort": [{"field": column("DimDate", "Date"), "direction": "Ascending"}], "isDefaultSort": True}},
            "objects": {
                **axis_objects(show_value_axis=True, labels=False),
                "dataPoint": [{"properties": {"fill": color("#6A6597")}, "selector": {"metadata": qref(measure("Total Sales"))}},
                              {"properties": {"fill": color(LAVENDER)}, "selector": {"metadata": qref(measure("Sales 7-Day Moving Average"))}}],
                "lineStyles": [{"properties": {"strokeWidth": n(1)}, "selector": {"metadata": qref(measure("Total Sales"))}},
                               {"properties": {"strokeWidth": n(2.5)}, "selector": {"metadata": qref(measure("Sales 7-Day Moving Average"))}}],
                "legend": [{"properties": {"show": b(True), "position": s("TopRight"), "labelColor": color(TEXT_2), "fontSize": n(8)}}],
            },
            "visualContainerObjects": container(title_measure="Title Daily Trend",
                                                subtitle="Daily sales (muted) with trailing 7-day average (lavender)"),
            "drillFilterOtherVisuals": True}
    p.add("chartDailyTrend", X0, 288, 452, 206, line)
    p.add("chartMonthlySales", 564, 288, 260, 206, bar(
        column("DimDate", "Month"), "Total Sales", title_measure="Title Monthly Sales",
        subtitle="Hover for sales per trading day", vtype="clusteredColumnChart", sort_desc=False,
        tooltips=("MoM Sales %", "Average Daily Sales", "MoM Average Daily Sales %", "Cumulative Sales"), label_units=1000))
    # key insights panel
    p.add("insightsPanel", 836, 288, 428, 206, textbox(
        [para([("Key Insights", style(11, TEXT, FONT_SB))])], container(padding=(10, 14, 0, 14))))
    insights = [("insightCombo", "Strongest branch × product line", "Top Branch-Product Combination", VIOLET, "▲"),
                ("insightMembers", "Members vs normal customers", "Member vs Normal Spend", "#D65A93", "◉"),
                ("insightWeakest", "Weakest product line", "Insight Weakest Product Line", "#E8794E", "▼")]
    for i, (vn, ttl, mn, tile, glyph) in enumerate(insights):
        y = 322 + i * 56
        p.add(vn + "Bg", 846, y, 408, 50, textbox([para([("", style(8))])],
                                                  container(bg=True, bg_color=BG_INPUT, radius=12, border=False)))
        p.add(vn + "Icon", 856, y + 11, 28, 28, textbox(
            [para([(glyph, style(10, "#FFFFFF", "Segoe UI Symbol"))], "center")],
            container(bg=True, border=False, bg_color=tile, radius=8, padding=(5, 0, 0, 0))))
        p.add(vn, 892, y + 2, 356, 46, card(mn, ttl, value_size=10, title_align="left", wrap=True, bg=False,
                                             border=False, padding=(2, 4, 0, 4), family=FONT_SB))
    # Row B
    p.add("chartBranchSales", X0, 506, 283, 202, bar(
        column("DimBranch", "Branch Label"), "Total Sales", title_measure="Title Branch Sales",
        tooltips=("Branch Sales Share %", "Total Transactions", "Average Transaction Value", "Total Gross Income"), label_units=1000))
    p.add("chartProductSales", 395, 506, 283, 202, bar(
        column("DimProduct", "Product Line"), "Total Sales", title="Sales by Product Line",
        tooltips=("Product Line Sales Share %", "Total Quantity Sold", "Total Gross Income"), label_units=1000))
    p.add("chartProductGrossIncome", 690, 506, 283, 202, bar(
        column("DimProduct", "Product Line"), "Total Gross Income", title_measure="Title Gross Income Product", fill=PINK,
        tooltips=("Gross Margin %", "Product Line Gross Income Rank"), label_units=1000))
    donut = {"visualType": "donutChart",
             "query": {"queryState": {"Category": {"projections": [proj(column("DimCustomer", "Customer Type"))]},
                                      "Y": {"projections": [proj(measure("Total Sales"))]},
                                      "Tooltips": {"projections": [proj(measure("Average Transaction Value")),
                                                                   proj(measure("Total Transactions"))]}}},
             "objects": {"legend": [{"properties": {"show": b(False)}}],
                         "labels": [{"properties": {"show": b(True), "labelStyle": s("Category, percent of total"),
                                                    "color": color(TEXT), "fontSize": n(9)}}],
                         "slices": [{"properties": {"innerRadiusRatio": n(68)}}],
                         "dataPoint": [{"properties": {"borderShow": b(True), "borderColor": color(BG_CARD), "borderSize": n(2)}}]},
             "visualContainerObjects": container(title="Sales Contribution by Customer Type", subtitle="Member card holders vs normal"),
             "drillFilterOtherVisuals": True}
    p.add("chartCustomerTypeMix", 985, 506, 279, 202, donut)
    return p


def page_product():
    p = Page(*PAGES[1][:2])
    scaffold(p, 1)
    kpi_row(p, [
        ("kpiTopProductSales", "Top Product Line by Sales", "TOP PRODUCT LINE · SALES", "Top Product Line Detail", "$", VIOLET, 14),
        ("kpiTopProductIncome", "Top Product Line by Gross Income", "TOP PRODUCT LINE · GROSS INCOME", "Top Product Line by Gross Income Detail", "◈", "#E8794E", 14),
        ("kpiTopProductQty", "Top Product Line by Quantity", "TOP PRODUCT LINE · UNITS", "Top Product Line by Quantity Detail", "▦", "#2E9BD0", 14),
        ("kpiTopBranch", "Top Branch by Sales", "TOP BRANCH · SALES", "Top Branch Detail", "⌂", "#1F9A80", 14),
    ])
    pl = column("DimProduct", "Product Line")
    p.add("tableProductScorecard", X0, 506, 640, 202, table([
        (pl, "Product line"), (measure("Total Sales"), "Sales"), (measure("Product Line Sales Share %"), "Share"),
        (measure("Total Quantity Sold"), "Units"), (measure("Total Gross Income"), "Gross income"),
        (measure("Gross Margin %"), "Margin"), (measure("Average Transaction Value"), "Avg basket"),
        (measure("Average Rating"), "Rating")],
        "Product Line Scorecard  ·  compare Margin with Sales",
        sort_field=measure("Total Sales"), font=8.5))
    p.add("chartProductQuantity", X0, 288, 380, 206, bar(
        pl, "Total Quantity Sold", title="Units Sold by Product Line", fill=CATEGORICAL[2],
        tooltips=("Total Transactions", "Quantity per Transaction", "Average Unit Price")))
    p.add("matrixBranchProduct", 492, 288, 772, 206, heat_matrix(
        column("DimBranch", "Branch Label"), pl, "Total Sales", "Branch × Product Line Sales Heatmap",
        subtitle="Darker violet = higher sales · does product strength differ by branch?", row_label="Branch"))
    p.add("tableBranchScorecard", 752, 506, 512, 202, table([
        (column("DimBranch", "Branch Label"), "Branch"), (measure("Total Sales"), "Sales"),
        (measure("Branch Sales Share %"), "Share"), (measure("Total Transactions"), "Transactions"),
        (measure("Average Transaction Value"), "Avg basket"), (measure("Total Gross Income"), "Gross income"),
        (measure("Average Rating"), "Rating"), (measure("Branch Sales Rank"), "Rank")],
        "Branch Performance Scorecard", subtitle="Ranked by sales · rank is across all branches",
        sort_field=measure("Total Sales")))
    return p


def page_customer():
    p = Page(*PAGES[2][:2])
    scaffold(p, 2)
    kpi_row(p, [
        ("kpiMemberShare", "Member Sales %", "MEMBER SHARE OF SALES", "KPI Member Subtitle", "◉", VIOLET, 22),
        ("kpiTopPayment", "Most Used Payment Method", "MOST USED PAYMENT", "KPI Payment Subtitle", "⇄", "#D65A93", 14),
        ("kpiPeakHour", "Peak Hour", "PEAK HOUR · TRANSACTIONS", "Peak Hour Detail", "◷", "#2E9BD0", 14),
        ("kpiTopRatedBranch", "Highest Rated Branch", "HIGHEST RATED BRANCH", "Highest Rated Branch Detail", "★", "#C9902E", 14),
    ])
    p.add("chartCustomerGender", X0, 288, 380, 206, bar(
        column("DimCustomer", "Customer Type"), "Total Sales", title="Sales by Customer Type and Gender",
        vtype="clusteredColumnChart", series=column("DimCustomer", "Gender"), sort_desc=False,
        tooltips=("Average Transaction Value", "Total Transactions"), label_units=1000))
    p.add("chartPayment", 492, 288, 300, 206, bar(
        column("DimPayment", "Payment Method"), "Total Transactions", title="Transactions by Payment Method",
        fill=CATEGORICAL[1], tooltips=("Total Sales", "Average Transaction Value", "Transaction Share of Selection %")))
    p.add("chartHourly", 804, 288, 460, 206, bar(
        column("DimTime", "Hour"), "Total Transactions", title_measure="Title Hourly",
        subtitle="Morning 10–12 · Afternoon 12–17 · Evening 17–21", vtype="columnChart",
        series=column("DimTime", "Time of Day"), sort_desc=False,
        tooltips=("Total Sales", "Average Transaction Value", "Average Transactions per Hour Slot")))
    p.add("chartRatingBranch", X0, 506, 283, 202, bar(
        column("DimBranch", "Branch Label"), "Average Rating", title="Average Rating by Branch", fill=CATEGORICAL[5],
        tooltips=("High Rating % (8+)", "Low Rating % (below 6)", "Total Transactions")))
    p.add("chartRatingProduct", 395, 506, 380, 202, bar(
        column("DimProduct", "Product Line"), "Average Rating", title="Average Rating by Product Line (1–10)",
        fill=CATEGORICAL[5],
        tooltips=("High Rating % (8+)", "Low Rating % (below 6)")))
    p.add("matrixCustomerProduct", 787, 506, 477, 202, heat_matrix(
        column("DimProduct", "Product Line"), column("DimCustomer", "Customer Type"), "Total Sales",
        "Customer Type × Product Line Sales  ·  darker = higher", row_label="Product line", pad=1))
    return p


def page_predictive():
    p = Page(*PAGES[3][:2])
    scaffold(p, 3)
    kpi_row(p, [
        ("kpiSelectedK", "Selected K", "SEGMENTS (K)", None, "✦", VIOLET, 22),
        ("kpiSilhouette", "Model Silhouette Score", "SILHOUETTE SCORE", None, "◎", "#D65A93", 22),
        ("kpiStability", "Model Stability ARI", "STABILITY (MIN ARI, 10 SEEDS)", None, "≡", "#2E9BD0", 22),
        ("kpiAtRiskValue", "High-Value Low-Rating Sales %", "SALES AT RISK · HIGH SPEND, LOW RATING", "Top Segment by Sales", "!", "#E8794E", 22),
    ])
    ev_k = column("ClusterEvaluation", "K")

    def eval_line(mname, title, sub, col_):
        return {"visualType": "lineChart",
                "query": {"queryState": {"Category": {"projections": [proj(ev_k)]},
                                         "Y": {"projections": [proj(measure(mname))]}},
                          "sortDefinition": {"sort": [{"field": ev_k, "direction": "Ascending"}], "isDefaultSort": True}},
                "objects": {**axis_objects(show_value_axis=True, labels=False),
                            "categoryAxis": [{"properties": {"axisType": s("Categorical"), "labelColor": color(TEXT_2),
                                                             "fontSize": n(8), "showAxisTitle": b(True),
                                                             "titleText": s("k (number of clusters)"),
                                                             "titleColor": color(TEXT_3), "titleFontSize": n(8)}}],
                            "dataPoint": [{"properties": {"fill": color(col_)}}],
                            "lineStyles": [{"properties": {"strokeWidth": n(2), "showMarker": b(True), "markerSize": n(4)}}]},
                "visualContainerObjects": container(title=title, subtitle=sub),
                "drillFilterOtherVisuals": True}
    p.add("chartElbow", X0, 288, 283, 206, eval_line("Elbow Inertia", "Elbow Method · Inertia by k",
                                                     "Diminishing gains in inertia beyond k = 4–5", LAVENDER))
    p.add("chartSilhouette", 395, 288, 283, 206, eval_line("Silhouette Score by K", "Silhouette Score by k",
                                                           "k = 3–5 all ≈ 0.32 · k = 4 chosen", PINK))
    cl = column("DimCluster", "Cluster Label")
    p.add("chartClusterDistribution", 690, 288, 283, 206, bar(
        column("DimCluster", "Cluster Code"), "Total Transactions", title="Segment Size · Transactions",
        subtitle="C1–C4 as profiled below", fill=LAVENDER, sort_desc=False,
        tooltips=("Cluster Transaction Share %", "Cluster Sales Share %")))
    scatter = {"visualType": "scatterChart",
               "query": {"queryState": {"Category": {"projections": [proj(column("DimCluster", "Cluster Code"))]},
                                        "Series": {"projections": [proj(column("DimCluster", "Cluster Code"))]},
                                        "X": {"projections": [proj(measure("Average Transaction Value"))]},
                                        "Y": {"projections": [proj(measure("Average Rating"))]},
                                        "Size": {"projections": [proj(measure("Total Transactions"))]},
                                        "Tooltips": {"projections": [proj(measure("Cluster Sales Share %")),
                                                                     proj(measure("Quantity per Transaction"))]}}},
               "objects": {**axis_objects(show_value_axis=True, labels=False),
                           "categoryAxis": [{"properties": {"labelColor": color(TEXT_2), "fontSize": n(8), "showAxisTitle": b(True),
                                                            "titleText": s("Avg spend per transaction"), "titleColor": color(TEXT_3), "titleFontSize": n(8),
                                                            "gridlineShow": b(False)}}],
                           "valueAxis": [{"properties": {"labelColor": color(TEXT_2), "fontSize": n(8), "showAxisTitle": b(True),
                                                         "titleText": s("Avg rating"), "titleColor": color(TEXT_3), "titleFontSize": n(8),
                                                         "gridlineColor": color(BORDER), "gridlineStyle": s("dotted")}}],
                           "categoryLabels": [{"properties": {"show": b(True), "color": color(TEXT), "fontSize": n(8)}}],
                           "legend": [{"properties": {"show": b(False)}}],
                           "bubbles": [{"properties": {"bubbleSize": n(10)}}]},
               "visualContainerObjects": container(title="Segment Map · Spend vs Rating", subtitle="Bubble size = transactions"),
               "drillFilterOtherVisuals": True}
    p.add("chartClusterMap", 985, 288, 279, 206, scatter)
    p.add("tableClusterProfile", X0, 506, 676, 202, table([
        (cl, "Segment"), (measure("Total Transactions"), "Transactions"),
        (measure("Average Transaction Value"), "Avg spend"), (measure("Quantity per Transaction"), "Units / tx"),
        (measure("Average Rating"), "Avg rating"),
        (measure("Cluster Sales Share %"), "Share of sales"), (measure("Member Sales %"), "Member %")],
        "Segment Profiles  ·  live, respond to slicers"))
    p.add("tablePersonas", 788, 506, 476, 202, table([
        (column("DimCluster", "Cluster Code"), "Segment"), (column("DimCluster", "Recommended Action"), "Recommended action")],
        "Business Interpretation & Actions", wrap=True, font=8,
        widths=[(column("DimCluster", "Cluster Code"), 56), (column("DimCluster", "Recommended Action"), 384)]))
    return p


# ------------------------------------------------------------------ theme + background
def theme():
    return {
        "name": "DashFlow Dark",
        "dataColors": CATEGORICAL + ["#B4A9FF", "#F2A3C9", "#7FC4E8", "#E9A77C", "#8F8CE6", "#6CC6B0"],
        "foreground": TEXT, "foregroundNeutralSecondary": TEXT_2, "foregroundNeutralTertiary": TEXT_3,
        "background": BG_CARD, "backgroundLight": BG_INPUT, "backgroundNeutral": BORDER, "secondaryBackground": BG_INPUT,
        "tableAccent": LAVENDER, "good": GREEN, "neutral": "#E0B84F", "bad": PINK,
        "maximum": VIOLET, "center": "#4A4470", "minimum": "#1A1A26", "null": "#2A2A38",
        "hyperlink": LAVENDER, "visitedHyperlink": VIOLET,
        "textClasses": {
            "callout": {"fontSize": 22, "fontFace": FONT_SB, "color": TEXT},
            "title": {"fontSize": 11, "fontFace": FONT_SB, "color": TEXT},
            "header": {"fontSize": 11, "fontFace": FONT_SB, "color": TEXT},
            "label": {"fontSize": 9, "fontFace": FONT, "color": TEXT_2},
            "largeTitle": {"fontSize": 20, "fontFace": FONT_B, "color": TEXT},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": {"solid": {"color": BG_CARD}}, "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": BORDER}}, "radius": 14, "width": 1}],
                "dropShadow": [{"show": False}],
                "title": [{"fontColor": {"solid": {"color": TEXT}}, "fontSize": 11, "fontFamily": FONT_SB}],
                "subTitle": [{"fontColor": {"solid": {"color": TEXT_2}}, "fontSize": 9}],
                "visualHeader": [{"background": {"solid": {"color": BG_CARD}}, "foreground": {"solid": {"color": TEXT_2}},
                                  "border": {"solid": {"color": BORDER}}, "transparency": 0}],
                "visualTooltip": [{"background": {"solid": {"color": BG_INPUT}}, "titleFontColor": {"solid": {"color": TEXT_2}},
                                   "valueFontColor": {"solid": {"color": TEXT}}}],
                "categoryAxis": [{"labelColor": {"solid": {"color": TEXT_2}}, "titleColor": {"solid": {"color": TEXT_3}},
                                  "gridlineColor": {"solid": {"color": BORDER}}}],
                "valueAxis": [{"labelColor": {"solid": {"color": TEXT_3}}, "titleColor": {"solid": {"color": TEXT_3}},
                               "gridlineColor": {"solid": {"color": BORDER}}, "gridlineStyle": "dotted"}],
                "legend": [{"labelColor": {"solid": {"color": TEXT_2}}, "fontSize": 8}],
                "labels": [{"color": {"solid": {"color": TEXT}}}],
            }},
            "page": {"*": {
                "background": [{"color": {"solid": {"color": BG_PAGE}}, "transparency": 0}],
                "outspace": [{"color": {"solid": {"color": WALLPAPER}}, "transparency": 0}],
                "outspacePane": [{"backgroundColor": {"solid": {"color": BG_CARD}}, "foregroundColor": {"solid": {"color": TEXT}},
                                  "borderColor": {"solid": {"color": BORDER}}, "inputBoxColor": {"solid": {"color": BG_INPUT}},
                                  "transparency": 0}],
                "filterCard": [{"$id": "Available", "backgroundColor": {"solid": {"color": BG_INPUT}},
                                "foregroundColor": {"solid": {"color": TEXT}}, "transparency": 0},
                               {"$id": "Applied", "backgroundColor": {"solid": {"color": "#24243A"}},
                                "foregroundColor": {"solid": {"color": TEXT}}, "transparency": 0}],
            }},
            "slicer": {"*": {
                "items": [{"fontColor": {"solid": {"color": TEXT}}, "background": {"solid": {"color": BG_INPUT}}}],
                "header": [{"fontColor": {"solid": {"color": TEXT_2}}}],
            }},
            "tableEx": {"*": {
                "grid": [{"gridHorizontalColor": {"solid": {"color": BORDER}}, "outlineColor": {"solid": {"color": BORDER}}}],
                "columnHeaders": [{"fontColor": {"solid": {"color": TEXT_2}}, "backColor": {"solid": {"color": BG_INPUT}}}],
                "values": [{"fontColorPrimary": {"solid": {"color": TEXT}}, "backColorPrimary": {"solid": {"color": BG_CARD}},
                            "fontColorSecondary": {"solid": {"color": TEXT}}, "backColorSecondary": {"solid": {"color": "#171722"}}}],
            }},
            "pivotTable": {"*": {
                "columnHeaders": [{"fontColor": {"solid": {"color": TEXT_2}}, "backColor": {"solid": {"color": BG_CARD}}}],
                "rowHeaders": [{"fontColor": {"solid": {"color": TEXT}}, "backColor": {"solid": {"color": BG_CARD}}}],
                "values": [{"fontColorPrimary": {"solid": {"color": TEXT}}, "backColorPrimary": {"solid": {"color": BG_CARD}}}],
            }},
        },
    }


def background_png(path):
    """Near-black canvas with a soft violet glow behind the hero panel (echoes the reference design)."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.array([10, 10, 15], np.float32)
    glow1 = np.exp(-(((xx - 820) / 430) ** 2 + ((yy - 30) / 150) ** 2))
    glow2 = np.exp(-(((xx - 330) / 380) ** 2 + ((yy - 120) / 120) ** 2)) * 0.45
    g = np.clip(glow1 + glow2, 0, 1)[..., None]
    violet = np.array([92, 64, 200], np.float32)
    img = base + (violet - base) * g * 0.55
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path, optimize=True)


# ------------------------------------------------------------------ write
def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    import sys
    if DEF.exists():
        # The committed report was finished by hand in Power BI Desktop after generation.
        # Regenerating replaces that work, so it only happens when asked for explicitly.
        if "--force" not in sys.argv:
            sys.exit("RetailStore_BI.Report/definition already exists and contains hand-finished edits.\n"
                     "Re-run with --force to regenerate the base layout (this discards those edits).")
        shutil.rmtree(DEF)
    RES.mkdir(parents=True, exist_ok=True)
    dump(RES / "DashFlowTheme.json", theme())
    background_png(RES / "bg_dashflow.png")

    dump(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../RetailStore_BI.SemanticModel"}}})
    dump(DEF / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"})
    dump(DEF / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {"customTheme": {"name": "DashFlowTheme.json",
                                            "reportVersionAtImport": {"visual": "2.4.0", "page": "2.0.0", "report": "3.0.0"},
                                            "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [
            {"name": "DashFlowTheme.json", "path": "DashFlowTheme.json", "type": "CustomTheme"},
            {"name": "bg_dashflow.png", "path": "bg_dashflow.png", "type": "Image"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })

    pages = [page_executive(), page_product(), page_customer(), page_predictive()]
    dump(DEF / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name})
    bg_obj = {"background": [{"properties": {
        "image": {"image": {"name": s("bg_dashflow.png"),
                            "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1,
                                                                     "ItemName": "bg_dashflow.png"}}},
                            "scaling": s("Fill")}},
        "color": color(BG_PAGE), "transparency": n(0)}}],
        "outspace": [{"properties": {"color": color(WALLPAPER), "transparency": n(0)}}]}
    for p in pages:
        dump(DEF / "pages" / p.name / "page.json", {
            "$schema": PAGE_SCHEMA, "name": p.name, "displayName": p.display, "displayOption": "FitToPage",
            "height": H, "width": W, "objects": bg_obj})
        names = set()
        for v in p.visuals:
            assert v["name"] not in names, v["name"]
            names.add(v["name"])
            dump(DEF / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)
        print(f"{p.name}: {len(p.visuals)} visual containers")


if __name__ == "__main__":
    main()
