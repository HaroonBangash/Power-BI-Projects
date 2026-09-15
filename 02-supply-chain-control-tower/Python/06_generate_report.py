"""
06_generate_report.py
=====================
Generates the PBIR report definition for the Supply Chain Control Tower.

PBIR is a documented format with public JSON schemas, so the report is built as
code and validated statically before Power BI opens it.

Hard-won facts, each verified against output Power BI wrote itself
-------------------------------------------------------------------
1. SourceRef is an anyOf of TWO shapes and the distinction is critical:
       StandaloneSourceRefExpression -> requires `Entity`, a table in the data
       QuerySourceRefExpression      -> requires `Source`, an alias declared in
                                        a query's From clause
   A visual projection has no From clause, so it must use `Entity`. `Source`
   produces a dangling alias; Power BI resolves it to undefined and the report
   fails to load with "Cannot set properties of undefined (setting
   'dataSourceVariables')". BOTH forms pass JSON Schema validation, so no
   static check catches this.

2. The visual schema is visualContainer/2.3.0. `reportVersionAtImport` in
   report.json is NOT the file schema version - it reports page 2.3.0 while
   Power BI's own page.json uses page/2.0.0.

3. A visual's TITLE lives in `visualContainerObjects.title`, not `objects.title`.
   Placed in `objects` it is silently ignored and Power BI shows its generated
   default, e.g. "Total Revenue by YearMonthLabel".

4. Formatting property shapes cannot be schema-validated:
   DataViewObjectPropertyDefinitions is `additionalProperties: {}`, so the
   schema accepts anything. Formatting correctness is only ever empirical.

5. Built-in visual type names do not all carry a "stacked" prefix.
   `stackedColumnChart` is NOT a built-in - Power BI reports it as a missing
   custom visual. Verified rendering: card, slicer, lineChart,
   clusteredBarChart, pageNavigator.

Usage
-----
    python Python/06_generate_report.py [--check]

    --check   validate only; write nothing
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "PowerBI" / "SupplyChainControlTower.Report" / "definition"
TMDL = ROOT / "PowerBI" / "SupplyChainControlTower.SemanticModel" / "definition"
SCHEMAS = ROOT / "PowerBI" / "schemas"

BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
VISUAL_SCHEMA = BASE + "visualContainer/2.3.0/schema.json"
PAGE_SCHEMA = BASE + "page/2.0.0/schema.json"
PAGES_SCHEMA = BASE + "pagesMetadata/1.0.0/schema.json"

LOCAL_SCHEMAS = {
    VISUAL_SCHEMA: "visualContainer-2.3.0.json",
    PAGE_SCHEMA: "page-2.0.0.json",
    PAGES_SCHEMA: "pagesMetadata-1.0.0.json",
    BASE + "report/3.0.0/schema.json": "report-3.0.0.json",
    BASE + "visualConfiguration/2.2.0/schema-embedded.json": "visualConfiguration-2.2.0-schema-embedded.json",
    BASE + "semanticQuery/1.3.0/schema.json": "semanticQuery-1.3.0.json",
    BASE + "formattingObjectDefinitions/1.4.0/schema.json": "formattingObjectDefinitions-1.4.0.json",
    BASE + "filterConfiguration/1.2.0/schema-embedded.json": "filterConfiguration-1.2.0-embedded.json",
}

# --------------------------------------------------------------------------- #
# Design tokens
# --------------------------------------------------------------------------- #

CANVAS_W, CANVAS_H = 1280, 720
NAV_W = 168                         # was 132: ten page buttons need real width
MARGIN = 16
CX = NAV_W + MARGIN                 # content x = 148
CW = CANVAS_W - CX - MARGIN         # content width = 1116
GAP = 12

INK, MUTED = "#1F2937", "#6B7280"

# --- the finished dashboard's styling, reconstructed from the published screenshots.
# Every page carries the same dusty-pink banner; the accent below it changes page by
# page and is applied to the KPI cards, the chart title bars and the slicers. PAGE_STYLE
# is keyed by page id and is defined at the foot of this file, after the ids exist.
BANNER_FILL, BANNER_INK = "#E8B4B8", "#1F2937"
BANNER_Y, BANNER_H = 8, 46
_STYLE = None                       # the page currently being built


def use_style(pid):
    """Set the palette for the page being built. Read by card(), slicer() and
    container_title(), so a page's visuals pick it up without threading it through
    every call site."""
    global _STYLE
    _STYLE = PAGE_STYLE.get(pid)
    return _STYLE


def style_of(part):
    return (_STYLE or {}).get(part)
ACCENT, NEUTRAL = "#0E7490", "#94A3B8"
GOOD, BAD = "#15803D", "#B91C1C"

SLICER_Y, SLICER_H = 58, 84
KPI_Y, KPI_H = 150, 78


def index_model() -> tuple[dict[str, set[str]], set[str]]:
    tables: dict[str, set[str]] = {}
    measures: set[str] = set()
    for p in sorted((TMDL / "tables").glob("*.tmdl")):
        txt = p.read_text(encoding="utf-8")
        t = re.search(r"^table\s+(\S+)", txt, re.M).group(1).strip("'")
        tables[t] = {b.split("\n")[0].strip().strip("'")
                     for b in re.split(r"\n\tcolumn ", txt)[1:]}
        for m in re.findall(r"^\tmeasure (.+?)\s*=", txt, re.M):
            measures.add(m.strip().strip("'"))
    return tables, measures


# --------------------------------------------------------------------------- #
# Field references - Entity, never Source. See fact 1.
# --------------------------------------------------------------------------- #


def measure_ref(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}},
                        "Property": name}}


def column_ref(table, column):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}},
                       "Property": column}}


def m_proj(name):
    return {"field": measure_ref(name), "queryRef": f"_Measures.{name}",
            "nativeQueryRef": name}


def c_proj(table, column):
    return {"field": column_ref(table, column), "queryRef": f"{table}.{column}",
            "nativeQueryRef": column}


def lit_s(v): return {"expr": {"Literal": {"Value": f"'{v}'"}}}
def lit_n(v): return {"expr": {"Literal": {"Value": f"{v}D"}}}
def lit_b(v): return {"expr": {"Literal": {"Value": "true" if v else "false"}}}


def container_title(text, size=11, show=True, bar=None):
    """Titles live in visualContainerObjects - see fact 3.

    `bar` paints the title strip in the page's accent and centres it, which is how the
    finished pages label each chart. Without it the title is plain left-aligned ink."""
    if bar is None:
        bar = style_of("bar")           # page default
    if bar is False:
        bar = None                      # explicit opt-out: cards and slicers
    props = {
        "show": lit_b(show), "text": lit_s(text), "fontSize": lit_n(size),
        "fontColor": {"solid": {"color": lit_s(INK)}},
        "alignment": lit_s("center" if bar else "left"),
    }
    if bar:
        props["background"] = {"solid": {"color": lit_s(bar)}}
    return [{"properties": props}]


def banner(seed, text, tab):
    """The pink title bar across the top of every page."""
    return visual(seed, "textbox", CX, BANNER_Y, CW, BANNER_H, tab,
                  objects={"general": [{"properties": {"paragraphs": [{
                      "horizontalTextAlignment": "center",
                      "textRuns": [{"value": text, "textStyle": {
                          "fontSize": "20pt", "fontWeight": "bold",
                          "color": BANNER_INK}}]}]}}]},
                  bg=BANNER_FILL, alt=text, title_bar=False)


def alt_text(text):
    return [{"properties": {"altText": lit_s(text)}}]


def sid(seed): return hashlib.sha1(seed.encode()).hexdigest()[:20]


def visual(seed, vtype, x, y, w, h, tab, query=None, objects=None,
           title=None, alt=None, title_size=11, bg=None, title_bar=None):
    v = {
        "$schema": VISUAL_SCHEMA,
        "name": sid(seed),
        "position": {"x": x, "y": y, "z": 0, "width": w, "height": h,
                     "tabOrder": tab},
        "visual": {"visualType": vtype},
    }
    if query:
        v["visual"]["query"] = query
    if objects:
        v["visual"]["objects"] = objects
    vco = {}
    if bg:
        vco["background"] = [{"properties": {
            "show": lit_b(True), "color": {"solid": {"color": lit_s(bg)}},
            "transparency": lit_n(0)}}]
    if title is not None:
        vco["title"] = container_title(title or "", title_size, show=bool(title),
                                       bar=title_bar)
    if alt:
        vco["general"] = alt_text(alt)
    if vco:
        v["visual"]["visualContainerObjects"] = vco
    v["visual"]["drillFilterOtherVisuals"] = True
    return v


def card(seed, measure, label, x, y, w, h, tab):
    return visual(
        seed, "card", x, y, w, h, tab, bg=style_of("card"), title_bar=False,
        query={"queryState": {"Values": {"projections": [m_proj(measure)]}}},
        objects={
            "labels": [{"properties": {"fontSize": lit_n(20),
                                       "color": {"solid": {"color": lit_s(INK)}}}}],
            "categoryLabels": [{"properties": {
                "show": lit_b(True), "fontSize": lit_n(9),
                "color": {"solid": {"color": lit_s(MUTED)}}}}],
        },
        title=label, title_size=9, alt=f"{label}: {measure}")


def top_n_filter(seed, cat, count):
    """Visual-level Top N. QueryExpressionContainer.VisualTopN takes ItemCount;
    the ordering comes from the visual's own sortDefinition, so a Top N chart
    must also set sort_desc."""
    table, column = cat
    return {"filters": [{
        "name": sid(seed + ".topn"),
        "field": column_ref(table, column),
        "type": "VisualTopN",
        "filter": {
            "Version": 2,
            "From": [{"Name": table[0].lower(), "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"VisualTopN": {"ItemCount": count}}}],
        },
    }]}


def chart(seed, vtype, cat, measures, title, x, y, w, h, tab,
          colours=None, sort_desc=None, top_n=None, sort_asc=None,
          data_labels=False):
    q = {"queryState": {
        "Category": {"projections": [c_proj(*cat)]},
        "Y": {"projections": [m_proj(m) for m in measures]},
    }}
    if sort_desc:
        q["sortDefinition"] = {
            "sort": [{"field": measure_ref(sort_desc), "direction": "Descending"}],
            "isDefaultSort": False}
    elif sort_asc:
        # Ascending + Top N is how a "worst N" chart is expressed: VisualTopN
        # carries the count, the visual sortDefinition decides which end.
        q["sortDefinition"] = {
            "sort": [{"field": measure_ref(sort_asc), "direction": "Ascending"}],
            "isDefaultSort": False}
    objs = {}
    if data_labels:
        # The finished Delivery Performance chart prints the value on each column.
        objs["labels"] = [{"properties": {
            "show": lit_b(True), "fontSize": lit_n(9),
            "color": {"solid": {"color": lit_s(INK)}}}}]
    if colours:
        objs["dataPoint"] = [
            {"properties": {"fill": {"solid": {"color": lit_s(c)}}},
             "selector": {"metadata": f"_Measures.{m}"}}
            for m, c in zip(measures, colours)]
    v = visual(seed, vtype, x, y, w, h, tab, query=q, objects=objs or None,
               title=title, alt=f"{title}, by {cat[1]}")
    if top_n:
        v["filterConfig"] = top_n_filter(seed, cat, top_n)
    return v


def table_visual(seed, cols, measures, title, x, y, w, h, tab):
    projections = [c_proj(*c) for c in cols] + [m_proj(m) for m in measures]
    return visual(seed, "tableEx", x, y, w, h, tab,
                  query={"queryState": {"Values": {"projections": projections}}},
                  title=title, alt=title)


def slicer(seed, table, column, label, x, y, w, h, tab):
    return visual(
        seed, "slicer", x, y, w, h, tab, bg=style_of("slicer"), title_bar=False,
        query={"queryState": {"Values": {"projections": [c_proj(table, column)]}}},
        objects={"header": [{"properties": {
            "show": lit_b(True), "text": lit_s(label), "fontSize": lit_n(9),
            "fontColor": {"solid": {"color": lit_s(MUTED)}}}}]},
        title="", alt=f"{label} slicer")


# Sidebar geometry. Ten buttons, readable horizontal labels, no rotation.
SB_PAD = 10
SB_BTN_W = NAV_W - 2 * SB_PAD        # 148
SB_BTN_H = 38                        # within the 36-42 px brief
SB_GAP = 5                           # within the 4-6 px brief
SB_TOP = 60
SB_FONT = 10

SB_BG_DEFAULT = "#F1F5F9"            # light neutral
SB_FG_DEFAULT = INK
SB_BG_SELECTED = ACCENT              # existing report accent
SB_FG_SELECTED = "#FFFFFF"

# label -> the build function whose page it targets. Order is fixed and is the
# same on every page; only the highlighted entry changes.
NAV_ITEMS = [
    ("Executive",     "page.executive"),
    ("Inventory",     "page.inventory"),
    ("Procurement",   "page.procurement"),
    ("Logistics",     "page.logistics"),
    ("Warehouse",     "page.warehouse"),
    ("Product / SKU", "page.skudetail"),
    ("Replenishment", "page.replenishment"),
    ("ABC / XYZ",     "page.abcxyz"),
    ("Suppliers",     "page.supplier"),
    ("Forecasting",   "page.forecast"),
]


def nav_page_id(key):
    """Page 1 keeps the id Power BI originally created; the rest are derived."""
    return "daa04013fee895df17a7" if key == "page.executive" else sid(key)


def nav_button(seed, label, target_page_id, selected, x, y, tab):
    """One navigation button.

    Shape follows a real Power BI-authored actionButton: formatting lives in
    objects as a list of {properties, selector} entries, where selector
    {"id": "default"} addresses the button's default state. Navigation is
    visual.visualLink.
    """
    bg = SB_BG_SELECTED if selected else SB_BG_DEFAULT
    fg = SB_FG_SELECTED if selected else SB_FG_DEFAULT
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(False)}}],
        "fill": [
            {"properties": {"show": lit_b(True)}},
            {"properties": {"fillColor": {"solid": {"color": lit_s(bg)}}},
             "selector": {"id": "default"}},
        ],
        "text": [
            {"properties": {"show": lit_b(True)}},
            {"properties": {"text": lit_s(label),
                            "fontColor": {"solid": {"color": lit_s(fg)}},
                            "fontSize": lit_n(SB_FONT),
                            "bold": lit_b(bool(selected))},
             "selector": {"id": "default"}},
        ],
    }
    v = visual(seed, "actionButton", x, y, SB_BTN_W, SB_BTN_H, tab,
               objects=objects, title="", alt=f"Go to {label}")
    v["visual"]["visualContainerObjects"]["visualLink"] = [{
        "properties": {
            "show": lit_b(True),
            "type": lit_s("PageNavigation"),
            "navigationSection": lit_s(target_page_id),
        }
    }]
    return v


def navigator(seed, tab, current=None):
    """The whole left rail: a heading plus one button per page.

    Returns a list. `current` is the page key that should render selected.
    """
    out = [textbox(f"{seed}.hdr", "SUPPLY CHAIN BI", SB_PAD, 14,
                   SB_BTN_W, 28, tab, size=10)]
    tab += 1
    for i, (label, key) in enumerate(NAV_ITEMS):
        out.append(nav_button(f"{seed}.btn.{key}", label, nav_page_id(key),
                              key == current, SB_PAD,
                              SB_TOP + i * (SB_BTN_H + SB_GAP), tab))
        tab += 1
    return out



def matrix_visual(seed, rows, cols, measures, title, x, y, w, h, tab):
    """Power BI's matrix. Roles: Rows, Columns, Values."""
    q = {"queryState": {
        "Rows": {"projections": [c_proj(*r) for r in rows]},
        "Columns": {"projections": [c_proj(*c) for c in cols]},
        "Values": {"projections": [m_proj(m) for m in measures]},
    }}
    return visual(seed, "pivotTable", x, y, w, h, tab, query=q,
                  title=title, alt=title)


def textbox(seed, text, x, y, w, h, tab, size=16):
    """Page heading. Text lives in objects.general.paragraphs, which is a
    structural array rather than a wrapped literal."""
    return visual(
        seed, "textbox", x, y, w, h, tab,
        objects={"general": [{"properties": {"paragraphs": [{
            "textRuns": [{"value": text,
                          "textStyle": {"fontSize": f"{size}pt",
                                        "fontWeight": "bold",
                                        "color": INK}}]}]}}]},
        title="")


def page_shell(pid, slicers, kpis, per_row=4):
    """Nav rail, banner, as-of card, slicers, KPI cards. Returns (visuals, tab, next_y)."""
    use_style(pid)
    vis, tab = [], 0
    vis.extend(navigator(f"{pid}.nav", tab, current=PAGE_KEY_BY_ID.get(pid)))
    tab += 1 + len(NAV_ITEMS)
    vis.append(banner(f"{pid}.banner", BANNER_TITLE.get(pid, ""), tab)); tab += 1
    # The as-of card sits level with the slicer row and is tall enough for its date.
    vis.append(card(f"{pid}.asof", "As Of Date", "Data as of",
                    CANVAS_W - MARGIN - 200, SLICER_Y, 200, SLICER_H, tab)); tab += 1

    x = CX
    for tbl, col, label, w in slicers:
        vis.append(slicer(f"{pid}.sl.{tbl}.{col}", tbl, col, label, x, SLICER_Y,
                          w, SLICER_H, tab))
        x += w + GAP
        tab += 1

    cw = (CW - (per_row - 1) * GAP) // per_row
    rows = (len(kpis) + per_row - 1) // per_row
    for i, (measure, label) in enumerate(kpis):
        r, c = divmod(i, per_row)
        vis.append(card(f"{pid}.kpi.{measure}", measure, label,
                        CX + c * (cw + GAP), KPI_Y + r * (KPI_H + GAP),
                        cw, KPI_H, tab))
        tab += 1
    return vis, tab, KPI_Y + rows * (KPI_H + GAP) + 8


PAGE_KEY_BY_ID = {nav_page_id(k): k for _, k in NAV_ITEMS}


def make_page(pid, display):
    return {"$schema": PAGE_SCHEMA, "name": pid, "displayName": display,
            "displayOption": "FitToPage", "height": CANVAS_H, "width": CANVAS_W}


# --------------------------------------------------------------------------- #
# PAGE 1 - Executive Control Tower
# Folder/object name kept exactly as Power BI created it: renaming folders needs
# a Desktop restart per the docs, and there is no reason to risk it for a label.
# --------------------------------------------------------------------------- #

P1 = "daa04013fee895df17a7"


def build_p1():
    vis, tab, y = page_shell(
        P1,
        [("DimWarehouse", "WarehouseName", "Warehouse", 220),
         ("DimProduct", "Category", "Product Category", 220),
         ("DimDate", "Year", "Year", 160)],
        [("Total Revenue", "Revenue"), ("Sales Orders", "Sales Orders"),
         ("Current Inventory Value", "Inventory Value"),
         ("Purchase Order Value", "PO Value"), ("Units Sold", "Units Sold"),
         ("Freight Cost", "Freight Cost"),
         ("On-Time Delivery %", "On-Time Delivery"),
         ("Current On Hand Units", "On Hand Units")])

    w = (CW - GAP) // 2
    h = (CANVAS_H - y - MARGIN - GAP) // 2
    vis.append(chart(f"{P1}.trend", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Total Revenue"], "Revenue Trend", CX, y, w, h, tab,
                     colours=[ACCENT])); tab += 1
    vis.append(chart(f"{P1}.invwh", "clusteredBarChart",
                     ("DimWarehouse", "WarehouseName"), ["Current Inventory Value"],
                     "Current Inventory Value by Warehouse",
                     CX + w + GAP, y, w, h, tab, colours=[ACCENT],
                     sort_desc="Current Inventory Value")); tab += 1
    # clusteredColumnChart, not stackedColumnChart - see fact 5.
    vis.append(chart(f"{P1}.deliv", "clusteredColumnChart",
                     ("DimWarehouse", "WarehouseName"),
                     ["On-Time Deliveries", "Late Deliveries"],
                     "Delivery Performance", CX, y + h + GAP, w, h, tab,
                     colours=[GOOD, BAD], data_labels=True)); tab += 1
    vis.append(chart(f"{P1}.supp", "clusteredBarChart",
                     ("DimSupplier", "SupplierName"), ["Purchase Order Value"],
                     "Top 10 Suppliers by Purchase Order Value",
                     CX + w + GAP, y + h + GAP, w, h, tab, colours=[NEUTRAL],
                     sort_desc="Purchase Order Value", top_n=10)); tab += 1
    return make_page(P1, "Executive Control Tower"), vis


# --------------------------------------------------------------------------- #
# PAGE 2 - Inventory Overview
# No snapshot-date slicer: current inventory is anchored to [As Of Date] and a
# snapshot slicer would make "current" ambiguous. The snapshot-date card shows
# which date is in play instead.
# --------------------------------------------------------------------------- #

P2 = sid("page.inventory")


def build_p2():
    vis, tab, y = page_shell(
        P2,
        [("DimWarehouse", "WarehouseName", "Warehouse", 220),
         ("DimProduct", "Category", "Product Category", 220),
         ("DimProduct", "ProductName", "Product", 200)],
        [("Current On Hand Units", "On Hand Units"),
         ("Current Inbound Units", "Inbound Units"),
         ("Current Inventory Position", "Inventory Position"),
         ("Current Inventory Value", "Inventory Value"),
         ("Current Inventory Snapshot Date", "Snapshot Date")],
        per_row=5)

    w3 = (CW - 2 * GAP) // 3
    h1 = 176
    vis.append(chart(f"{P2}.wh", "clusteredBarChart",
                     ("DimWarehouse", "WarehouseName"), ["Current Inventory Value"],
                     "Inventory Value by Warehouse", CX, y, w3, h1, tab,
                     colours=[ACCENT], sort_desc="Current Inventory Value")); tab += 1
    vis.append(chart(f"{P2}.cat", "clusteredBarChart",
                     ("DimProduct", "Category"), ["Current Inventory Value"],
                     "Inventory Value by Category", CX + w3 + GAP, y, w3, h1, tab,
                     colours=[ACCENT], sort_desc="Current Inventory Value")); tab += 1
    vis.append(chart(f"{P2}.units", "clusteredBarChart",
                     ("DimProduct", "Category"), ["Current On Hand Units"],
                     "On Hand Units by Category", CX + 2 * (w3 + GAP), y, w3, h1,
                     tab, colours=[NEUTRAL],
                     sort_desc="Current On Hand Units")); tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    w2 = (CW - GAP) // 2
    vis.append(chart(f"{P2}.top", "clusteredBarChart",
                     ("DimProduct", "ProductName"), ["Current Inventory Value"],
                     "Top 15 Products by Inventory Value", CX, y2, w2, h2, tab,
                     colours=[ACCENT], sort_desc="Current Inventory Value",
                     top_n=15)); tab += 1
    vis.append(table_visual(f"{P2}.tbl",
                            [("DimProduct", "ProductName"), ("DimProduct", "Category"),
                             ("DimWarehouse", "WarehouseName")],
                            ["Current On Hand Units", "Current Inbound Units",
                             "Current Inventory Value"],
                            "Inventory by Product and Warehouse",
                            CX + w2 + GAP, y2, w2, h2, tab)); tab += 1
    return make_page(P2, "Inventory Overview"), vis


# --------------------------------------------------------------------------- #
# PAGE 3 - Procurement Overview
# The supplier slicer belongs here: every visual on this page is procurement, so
# supplier filtering behaves as a user expects. On the executive page it would
# move one visual and leave seven untouched, which reads as a bug.
# --------------------------------------------------------------------------- #

P3 = sid("page.procurement")


def build_p3():
    vis, tab, y = page_shell(
        P3,
        [("DimSupplier", "SupplierName", "Supplier", 220),
         ("DimWarehouse", "WarehouseName", "Warehouse", 220),
         ("DimDate", "Year", "Year", 160)],
        [("Purchase Orders", "Purchase Orders"),
         ("Purchase Order Value", "PO Value"),
         ("Units Ordered", "Units Ordered"),
         ("Average Purchase Order Value", "Avg PO Value"),
         ("Open Purchase Orders", "Open POs"),
         ("Received Purchase Orders", "Received POs"),
         ("On-Time Receipt %", "On-Time Receipt")])

    w3 = (CW - 2 * GAP) // 3
    h1 = 168
    vis.append(chart(f"{P3}.supp", "clusteredBarChart",
                     ("DimSupplier", "SupplierName"), ["Purchase Order Value"],
                     "PO Value by Supplier", CX, y, w3, h1, tab,
                     colours=[ACCENT], sort_desc="Purchase Order Value")); tab += 1
    vis.append(chart(f"{P3}.wh", "clusteredBarChart",
                     ("DimWarehouse", "WarehouseName"), ["Purchase Order Value"],
                     "PO Value by Warehouse", CX + w3 + GAP, y, w3, h1, tab,
                     colours=[ACCENT], sort_desc="Purchase Order Value")); tab += 1
    vis.append(chart(f"{P3}.trend", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Purchase Order Value"], "Purchase Order Trend",
                     CX + 2 * (w3 + GAP), y, w3, h1, tab, colours=[ACCENT])); tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    w3b = (CW - 2 * GAP) // 3
    vis.append(chart(f"{P3}.openrec", "clusteredColumnChart",
                     ("DimWarehouse", "WarehouseName"),
                     ["Open Purchase Orders", "Received Purchase Orders"],
                     "Open vs Received Purchase Orders",
                     CX, y2, w3b, h2, tab, colours=[NEUTRAL, ACCENT])); tab += 1
    vis.append(chart(f"{P3}.status", "clusteredColumnChart",
                     ("DimWarehouse", "WarehouseName"),
                     ["On-Time Receipts", "Late Receipts"],
                     "On-Time vs Late Receipts",
                     CX + w3b + GAP, y2, w3b, h2, tab, colours=[GOOD, BAD])); tab += 1
    vis.append(table_visual(f"{P3}.tbl", [("DimSupplier", "SupplierName")],
                            ["Purchase Orders", "Purchase Order Value",
                             "Units Ordered", "Open Purchase Orders",
                             "On-Time Receipt %", "Average Receipt Delay Days"],
                            "Supplier Detail", CX + 2 * (w3b + GAP), y2, w3b,
                            h2, tab))
    tab += 1
    return make_page(P3, "Procurement Overview"), vis


# --------------------------------------------------------------------------- #
# PAGE 4 - Logistics & Delivery
# Carrier is used directly from FactShipments: four values, no attributes of its
# own, so a DimCarrier would be a one-column table adding a join for nothing.
# Nothing here is labelled OTIF - the dataset records no delivered quantity, so
# "in full" cannot be demonstrated.
# --------------------------------------------------------------------------- #

P4 = sid("page.logistics")


def build_p4():
    vis, tab, y = page_shell(
        P4,
        [("FactShipments", "Carrier", "Carrier", 200),
         ("DimWarehouse", "WarehouseName", "Warehouse", 220),
         ("DimDate", "Year", "Year", 160)],
        [("Total Shipments", "Shipments"), ("Freight Cost", "Freight Cost"),
         ("Average Freight Cost per Shipment", "Freight / Shipment"),
         ("Completed Deliveries", "Completed"),
         ("On-Time Deliveries", "On-Time"), ("Late Deliveries", "Late"),
         ("On-Time Delivery %", "On-Time %"),
         ("Average Delivery Delay Days", "Avg Delay (days)")])

    w2 = (CW - GAP) // 2
    h1 = 168
    vis.append(chart(f"{P4}.frcar", "clusteredBarChart",
                     ("FactShipments", "Carrier"), ["Freight Cost"],
                     "Freight Cost by Carrier", CX, y, w2, h1, tab,
                     colours=[ACCENT], sort_desc="Freight Cost")); tab += 1
    vis.append(chart(f"{P4}.frwh", "clusteredBarChart",
                     ("DimWarehouse", "WarehouseName"), ["Freight Cost"],
                     "Freight Cost by Warehouse", CX + w2 + GAP, y, w2, h1, tab,
                     colours=[ACCENT], sort_desc="Freight Cost")); tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    w3 = (CW - 2 * GAP) // 3
    vis.append(chart(f"{P4}.otcar", "clusteredBarChart",
                     ("FactShipments", "Carrier"), ["On-Time Delivery %"],
                     "On-Time Delivery % by Carrier", CX, y2, w3, h2, tab,
                     colours=[ACCENT], sort_desc="On-Time Delivery %")); tab += 1
    vis.append(chart(f"{P4}.otwh", "clusteredBarChart",
                     ("DimWarehouse", "WarehouseName"), ["On-Time Delivery %"],
                     "On-Time Delivery % by Warehouse",
                     CX + w3 + GAP, y2, w3, h2, tab, colours=[ACCENT],
                     sort_desc="On-Time Delivery %")); tab += 1
    vis.append(chart(f"{P4}.trend", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Total Shipments"], "Shipment Trend",
                     CX + 2 * (w3 + GAP), y2, w3, h2, tab, colours=[ACCENT]))
    tab += 1
    return make_page(P4, "Logistics & Delivery"), vis


# --------------------------------------------------------------------------- #
# PAGE 5 - Warehouse Performance
# Built entirely from measures already validated in Phase 6. No new business
# logic: this page compares warehouses on figures that already reconcile to SQL.
# --------------------------------------------------------------------------- #

P5 = sid("page.warehouse")


def build_p5():
    vis, tab, y = page_shell(
        P5,
        [("DimWarehouse", "WarehouseName", "Warehouse", 220),
         ("DimProduct", "Category", "Product Category", 220),
         ("DimDate", "Year", "Year", 160)],
        [("Total Revenue", "Revenue"), ("Sales Orders", "Orders"),
         ("Units Sold", "Units Shipped"),
         ("Current Inventory Value", "Inventory Value"),
         ("Freight Cost", "Freight Cost"),
         ("On-Time Delivery %", "On-Time Delivery"),
         ("Completed Deliveries", "Completed Deliveries"),
         ("Average Delivery Delay Days", "Avg Delay (days)")])

    w4 = (CW - 3 * GAP) // 4
    h1 = 180
    for i, (measure, title, colour) in enumerate([
            ("Total Revenue", "Revenue by Warehouse", ACCENT),
            ("Current Inventory Value", "Inventory Value by Warehouse", ACCENT),
            ("On-Time Delivery %", "On-Time Delivery % by Warehouse", GOOD),
            ("Freight Cost", "Freight Cost by Warehouse", NEUTRAL)]):
        vis.append(chart(f"{P5}.c{i}", "clusteredBarChart",
                         ("DimWarehouse", "WarehouseName"), [measure], title,
                         CX + i * (w4 + GAP), y, w4, h1, tab,
                         colours=[colour], sort_desc=measure))
        tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    vis.append(table_visual(f"{P5}.tbl",
                            [("DimWarehouse", "Region"),
                             ("DimWarehouse", "WarehouseName")],
                            ["Total Revenue", "Sales Orders", "Units Sold",
                             "Current Inventory Value", "Current On Hand Units",
                             "Freight Cost", "On-Time Delivery %",
                             "Average Delivery Delay Days"],
                            "Warehouse Comparison", CX, y2, CW, h2, tab))
    tab += 1
    return make_page(P5, "Warehouse Performance"), vis


# --------------------------------------------------------------------------- #
# PAGE 6 - Product / SKU Detail
# A filterable detail page, not yet a drill-through target: the brief defers
# drill-through configuration to a later phase. Slicers give the same reach in
# the meantime.
#
# There is deliberately no inventory trend here. Current inventory is anchored
# to [As Of Date] via REMOVEFILTERS(DimDate), so plotting it over time would
# return the same value for every month. A period-relative inventory measure is
# a separate piece of analytical work, not something to improvise in a report.
# --------------------------------------------------------------------------- #

P6 = sid("page.skudetail")


def build_p6():
    vis, tab, y = page_shell(
        P6,
        [("DimProduct", "ProductName", "Product", 240),
         ("DimProduct", "Category", "Category", 200),
         ("DimWarehouse", "WarehouseName", "Warehouse", 200)],
        [("Current On Hand Units", "On Hand"),
         ("Current Inventory Position", "Inventory Position"),
         ("Current Inventory Value", "Inventory Value"),
         ("Actual Demand Units", "Actual Demand"),
         ("Total Revenue", "Revenue"), ("Sales Orders", "Sales Orders")],
        per_row=6)

    w2 = (CW - GAP) // 2
    h1 = 229
    # Actual against the supplied baseline. The Phase 14 model forecast will
    # join this chart once it exists.
    vis.append(chart(f"{P6}.demand", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Actual Demand Units", "Baseline Forecast Units"],
                     "Demand: Actual vs Baseline Forecast",
                     CX, y, w2, h1, tab, colours=[ACCENT, NEUTRAL])); tab += 1
    vis.append(chart(f"{P6}.rev", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Total Revenue"], "Revenue Trend",
                     CX + w2 + GAP, y, w2, h1, tab, colours=[ACCENT])); tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    vis.append(table_visual(f"{P6}.prod",
                            [("DimProduct", "ProductName"),
                             ("DimProduct", "Category"),
                             ("DimWarehouse", "WarehouseName")],
                            ["Current On Hand Units", "Current Inbound Units",
                             "Current Inventory Value", "Actual Demand Units"],
                            "Stock and Demand by Product",
                            CX, y2, w2, h2, tab)); tab += 1
    vis.append(table_visual(f"{P6}.po", [("DimSupplier", "SupplierName")],
                            ["Purchase Orders", "Units Ordered",
                             "Purchase Order Value", "Average Supplier Lead Time",
                             "On-Time Receipt %"],
                            "Supply: Purchase Orders for Selection",
                            CX + w2 + GAP, y2, w2, h2, tab)); tab += 1
    return make_page(P6, "Product / SKU Detail"), vis


# --------------------------------------------------------------------------- #
# PAGE 7 - Stockout & Replenishment Risk
# The operational heart of the solution: what should purchasing order today.
#
# Every figure rests on measures validated in Phase 8. Thresholds are absolute
# business rules documented on the Replenishment Status measure, not values
# fitted to produce a pleasing spread of colours.
# --------------------------------------------------------------------------- #

P7 = sid("page.replenishment")


def build_p7():
    vis, tab, y = page_shell(
        P7,
        [("DimWarehouse", "WarehouseName", "Warehouse", 200),
         ("DimProduct", "Category", "Category", 190),
         ("ReplenishmentStatus", "Status", "Replenishment Status", 210)],
        [("Products Requiring Reorder", "Lines to Reorder"),
         ("Critical Products", "Critical Lines"),
         ("Suggested Reorder Units", "Units to Order"),
         ("Average Weeks of Supply", "Avg Weeks of Supply"),
         ("Current Inventory Value", "Inventory Value"),
         ("Current Inventory Position", "Inventory Position"),
         ("Excess Inventory Value", "Excess Value"),
         ("Excess Inventory Units", "Excess Units")])

    w4 = (CW - 3 * GAP) // 4
    h1 = 170
    vis.append(chart(f"{P7}.status", "clusteredBarChart",
                     ("ReplenishmentStatus", "Status"), ["Lines at Status"],
                     "Lines by Replenishment Status", CX, y, w4, h1, tab,
                     colours=[ACCENT])); tab += 1
    vis.append(chart(f"{P7}.qty", "clusteredBarChart",
                     ("DimProduct", "ProductName"), ["Suggested Reorder Quantity"],
                     "Top 15 by Suggested Reorder Quantity",
                     CX + (w4 + GAP), y, w4, h1, tab, colours=[BAD],
                     sort_desc="Suggested Reorder Quantity", top_n=15)); tab += 1
    # Position against reorder point: the shortage gap is the visible distance
    # between the two bars.
    vis.append(chart(f"{P7}.gap", "clusteredBarChart",
                     ("DimProduct", "ProductName"),
                     ["Current Inventory Position", "Reorder Point"],
                     "Inventory Position vs Reorder Point",
                     CX + 2 * (w4 + GAP), y, w4, h1, tab,
                     colours=[ACCENT, BAD], sort_desc="Reorder Point",
                     top_n=15)); tab += 1
    vis.append(chart(f"{P7}.risk", "clusteredColumnChart",
                     ("DimWarehouse", "WarehouseName"),
                     ["Products Requiring Reorder", "Critical Products"],
                     "Replenishment Risk by Warehouse",
                     CX + 3 * (w4 + GAP), y, w4, h1, tab,
                     colours=[NEUTRAL, BAD])); tab += 1

    y2 = y + h1 + GAP
    h2 = CANVAS_H - y2 - MARGIN
    vis.append(table_visual(f"{P7}.action",
                            [("DimProduct", "ProductName"),
                             ("DimProduct", "Category"),
                             ("DimWarehouse", "WarehouseName")],
                            ["Current On Hand Units", "Current Inbound Units",
                             "Average Weekly Demand", "Lead Time Weeks",
                             "Safety Stock Units", "Reorder Point",
                             "Current Inventory Position",
                             "Suggested Reorder Quantity", "Weeks of Supply",
                             "Replenishment Status"],
                            "Replenishment Action List - what to order today",
                            CX, y2, CW, h2, tab)); tab += 1
    return make_page(P7, "Stockout & Replenishment Risk"), vis


# --------------------------------------------------------------------------- #
# PAGE 8 - ABC / XYZ Inventory Strategy
#
# Both classifications are PRODUCT level. No warehouse slicer: ABC and XYZ are
# global product properties, so filtering to one warehouse would show local
# stock beside a class derived from the whole portfolio - a mismatch that reads
# as a defect. Category and Product slicers only.
# --------------------------------------------------------------------------- #

P8 = sid("page.abcxyz")


def build_p8():
    use_style(P8)
    vis, tab = [], 0
    vis.extend(navigator(f"{P8}.nav", tab, current="page.abcxyz"))
    tab += 1 + len(NAV_ITEMS)
    vis.append(banner(f"{P8}.banner", BANNER_TITLE[P8], tab)); tab += 1
    vis.append(card(f"{P8}.asof", "As Of Date", "Data as of",
                    CANVAS_W - MARGIN - 200, SLICER_Y, 200, SLICER_H, tab)); tab += 1

    vis.append(slicer(f"{P8}.sl.cat", "DimProduct", "Category", "Product Category",
                      CX, SLICER_Y, 260, SLICER_H, tab)); tab += 1
    vis.append(slicer(f"{P8}.sl.prod", "DimProduct", "ProductName", "Product",
                      CX + 272, SLICER_Y, 260, SLICER_H, tab)); tab += 1

    kpis = [("A-Class Products", "A-Class Products"),
            ("X-Class Products", "X-Class (predictable)"),
            ("Z-Class Products", "Z-Class (volatile)"),
            ("AZ Products", "AZ - high value, volatile"),
            ("A-Class Inventory Value", "A-Class Inventory Value"),
            ("Unclassified Products", "No Demand History")]
    cw = (CW - 5 * GAP) // 6
    for i, (m, lbl) in enumerate(kpis):
        vis.append(card(f"{P8}.kpi.{m}", m, lbl, CX + i * (cw + GAP), 150, cw, 78, tab))
        tab += 1

    yA, hA = 240, 226
    # The centrepiece: ABC down the rows, XYZ across the columns, product count
    # in each cell. AZ becomes immediately visible.
    vis.append(matrix_visual(f"{P8}.matrix",
                             [("ABCXYZClass", "ABC")], [("ABCXYZClass", "XYZ")],
                             ["Products at ABCXYZ Class"],
                             "ABC x XYZ Matrix - product count",
                             CX, yA, 430, hA, tab)); tab += 1
    vis.append(chart(f"{P8}.abcrev", "clusteredColumnChart",
                     ("ABCClass", "Class"), ["Revenue at ABC Class"],
                     "Revenue Contribution by ABC Class",
                     CX + 442, yA, 330, hA, tab, colours=[ACCENT])); tab += 1
    vis.append(chart(f"{P8}.xyzcnt", "clusteredColumnChart",
                     ("XYZClass", "Class"), ["Products at XYZ Class"],
                     "Demand Predictability - X most stable, Z most volatile",
                     CX + 784, yA, CW - 784, hA, tab, colours=[NEUTRAL])); tab += 1

    yB = yA + hA + GAP
    hB = CANVAS_H - yB - MARGIN
    vis.append(chart(f"{P8}.invcls", "clusteredBarChart",
                     ("ABCXYZClass", "Class"), ["Inventory Value at ABCXYZ Class"],
                     "Inventory Value by ABC/XYZ Class",
                     CX, yB, 430, hB, tab, colours=[ACCENT],
                     sort_desc="Inventory Value at ABCXYZ Class")); tab += 1
    vis.append(table_visual(f"{P8}.strategy",
                            [("DimProduct", "ProductName"), ("DimProduct", "Category")],
                            ["Total Revenue", "Product Revenue Contribution %",
                             "Cumulative Revenue %", "ABC Class",
                             "Product Average Weekly Demand", "Product Demand CV",
                             "XYZ Class", "ABC XYZ Class", "Current Inventory Value"],
                            "ABC/XYZ Product Strategy",
                            CX + 442, yB, CW - 442, hB, tab)); tab += 1
    return make_page(P8, "ABC/XYZ Inventory Strategy"), vis


# --------------------------------------------------------------------------- #
# PAGE 9 - Supplier Performance
#
# Procurement Overview answers "what are we buying". This answers "who is
# reliable, who creates risk, and where is spend concentrated".
#
# Nothing here is labelled OTIF. The composite score has three components, not
# four: the dataset records no received quantity, so fulfilment performance
# cannot be measured and is not invented.
#
# "PO Value vs Supplier Score" is rendered as spend-by-performance-class rather
# than a scatter. scatterChart is an unproven visual type in this report, and
# the class view answers the same question - is spend concentrated among strong
# or weak suppliers - more directly.
# --------------------------------------------------------------------------- #

P9 = sid("page.supplier")


def build_p9():
    use_style(P9)
    vis, tab = [], 0
    vis.extend(navigator(f"{P9}.nav", tab, current="page.supplier"))
    tab += 1 + len(NAV_ITEMS)
    vis.append(banner(f"{P9}.banner", BANNER_TITLE[P9], tab)); tab += 1
    vis.append(card(f"{P9}.asof", "As Of Date", "Data as of",
                    CANVAS_W - MARGIN - 200, SLICER_Y, 200, SLICER_H, tab)); tab += 1

    vis.append(slicer(f"{P9}.sl.sup", "DimSupplier", "SupplierName", "Supplier",
                      CX, SLICER_Y, 240, SLICER_H, tab)); tab += 1
    vis.append(slicer(f"{P9}.sl.tier", "DimSupplier", "SupplierTier", "Supplier Tier",
                      CX + 252, SLICER_Y, 220, SLICER_H, tab)); tab += 1
    vis.append(slicer(f"{P9}.sl.cls", "SupplierClass", "Class", "Performance Class",
                      CX + 484, SLICER_Y, 220, SLICER_H, tab)); tab += 1

    kpis = [("Total Suppliers", "Suppliers"),
            ("Purchase Order Value", "PO Value"),
            ("Average Supplier Lead Time", "Avg Lead Time (days)"),
            ("On-Time Receipt %", "On-Time Receipt"),
            ("Average Defect Rate", "Avg Defect Rate"),
            ("Average Supplier Score", "Avg Supplier Score"),
            ("Excellent Suppliers", "Excellent"),
            ("High-Risk Suppliers", "High Risk")]
    cw = (CW - 3 * GAP) // 4
    for i, (m, lbl) in enumerate(kpis):
        r, c = divmod(i, 4)
        vis.append(card(f"{P9}.kpi.{m}", m, lbl,
                        CX + c * (cw + GAP), 150 + r * 86, cw, 78, tab))
        tab += 1

    yA, hA = 326, 190
    w3 = (CW - 2 * GAP) // 3
    vis.append(chart(f"{P9}.rank", "clusteredBarChart",
                     ("DimSupplier", "SupplierName"), ["Supplier Performance Score"],
                     "Top 15 Suppliers by Performance Score", CX, yA, w3, hA, tab,
                     colours=[GOOD], sort_desc="Supplier Performance Score",
                     top_n=15)); tab += 1
    vis.append(chart(f"{P9}.ontime", "clusteredBarChart",
                     ("DimSupplier", "SupplierName"), ["On-Time Receipt %"],
                     "Top 15 by On-Time Receipt %", CX + w3 + GAP, yA, w3, hA, tab,
                     colours=[ACCENT], sort_desc="On-Time Receipt %",
                     top_n=15)); tab += 1
    # Highest variability first: these are the suppliers that cannot be planned
    # around, which is the operational risk worth seeing.
    vis.append(chart(f"{P9}.var", "clusteredBarChart",
                     ("DimSupplier", "SupplierName"), ["Supplier Lead Time Variability"],
                     "Least Reliable Lead Times (highest variability)",
                     CX + 2 * (w3 + GAP), yA, w3, hA, tab, colours=[BAD],
                     sort_desc="Supplier Lead Time Variability", top_n=15)); tab += 1

    yB = yA + hA + GAP
    hB = CANVAS_H - yB - MARGIN
    vis.append(chart(f"{P9}.spend", "clusteredColumnChart",
                     ("SupplierClass", "Class"), ["PO Value at Supplier Class"],
                     "Spend by Supplier Performance Class",
                     CX, yB, 330, hB, tab, colours=[ACCENT])); tab += 1
    vis.append(table_visual(f"{P9}.detail", [("DimSupplier", "SupplierName"),
                                             ("DimSupplier", "SupplierTier")],
                            ["Purchase Orders", "Purchase Order Value",
                             "Average Supplier Lead Time", "Supplier Lead Time Variability",
                             "On-Time Receipt %", "Average Defect Rate",
                             "Supplier Performance Score", "Supplier Performance Class"],
                            "Supplier Performance Detail",
                            CX + 342, yB, CW - 342, hB, tab)); tab += 1
    return make_page(P9, "Supplier Performance"), vis


# --------------------------------------------------------------------------- #
# PAGE 10 - Demand Forecasting
#
# WHAT THIS PAGE HONESTLY SHOWS. FactWeeklyDemand holds 105 weeks ending exactly
# at the as-of date, with ZERO weeks beyond it. BaselineForecastUnits is
# therefore an in-sample baseline forecast, not a forward projection. Every
# visual here measures forecast QUALITY against actuals that exist; nothing
# projects past 2026-08-31 and nothing is labelled as if it did. A genuine
# forward forecast needs the Python modelling phase and is not invented here.
#
# WAPE, not MAPE, is the headline accuracy metric - 1,096 product-weeks carry
# zero actual demand, where MAPE is undefined.
# --------------------------------------------------------------------------- #

P10 = sid("page.forecast")


def build_p10():
    use_style(P10)
    vis, tab = [], 0
    vis.extend(navigator(f"{P10}.nav", tab, current="page.forecast"))
    tab += 1 + len(NAV_ITEMS)
    vis.append(banner(f"{P10}.banner", BANNER_TITLE[P10], tab)); tab += 1
    vis.append(card(f"{P10}.asof", "As Of Date", "Data as of",
                    CANVAS_W - MARGIN - 200, SLICER_Y, 200, SLICER_H, tab)); tab += 1

    vis.append(slicer(f"{P10}.sl.cat", "DimProduct", "Category", "Category",
                      CX, SLICER_Y, 240, SLICER_H, tab)); tab += 1
    vis.append(slicer(f"{P10}.sl.prod", "DimProduct", "ProductName", "Product",
                      CX + 252, SLICER_Y, 240, SLICER_H, tab)); tab += 1
    vis.append(slicer(f"{P10}.sl.yr", "DimDate", "Year", "Year",
                      CX + 504, SLICER_Y, 180, SLICER_H, tab)); tab += 1

    kpis = [("Actual Demand Units", "Actual Demand"),
            ("Baseline Forecast Units", "Baseline Forecast"),
            ("Forecast Accuracy %", "Forecast Accuracy"),
            ("Forecast Bias %", "Forecast Bias"),
            ("Forecast MAE", "MAE (units/week)"),
            ("Demand Growth %", "Demand Growth 13W"),
            ("Growing Products", "Growing"),
            ("Declining Products", "Declining"),
            ("Volatile Products", "Volatile (Z)"),
            ("Demand Weeks Covered", "Weeks of History")]
    per_row = 5
    cw = (CW - (per_row - 1) * GAP) // per_row
    for i, (m, lbl) in enumerate(kpis):
        r, c = divmod(i, per_row)
        vis.append(card(f"{P10}.kpi.{m}", m, lbl,
                        CX + c * (cw + GAP), 150 + r * 86, cw, 78, tab))
        tab += 1

    # Row A - the trend, and where accuracy breaks down by category
    yA, hA = 326, 170
    wA = 740
    vis.append(chart(f"{P10}.trend", "lineChart", ("DimDate", "YearMonthLabel"),
                     ["Actual Demand Units", "Baseline Forecast Units"],
                     "Demand Trend: Actual vs Baseline Forecast",
                     CX, yA, wA, hA, tab, colours=[ACCENT, NEUTRAL])); tab += 1
    vis.append(chart(f"{P10}.acccat", "clusteredColumnChart",
                     ("DimProduct", "Category"), ["Forecast Accuracy %"],
                     "Forecast Accuracy by Category",
                     CX + wA + GAP, yA, CW - wA - GAP, hA, tab,
                     colours=[GOOD])); tab += 1

    # Row B - the movers, and the detail grid behind them
    yB = yA + hA + GAP
    hB = CANVAS_H - yB - MARGIN
    w3 = (CW - 2 * GAP) // 3
    vis.append(chart(f"{P10}.grow", "clusteredBarChart",
                     ("DimProduct", "ProductName"), ["Demand Growth %"],
                     "Fastest Growing Products (13W vs prior 13W)",
                     CX, yB, w3, hB, tab, colours=[GOOD],
                     sort_desc="Demand Growth %", top_n=15)); tab += 1
    vis.append(chart(f"{P10}.decline", "clusteredBarChart",
                     ("DimProduct", "ProductName"), ["Demand Growth %"],
                     "Steepest Demand Decline (13W vs prior 13W)",
                     CX + w3 + GAP, yB, w3, hB, tab, colours=[BAD],
                     sort_asc="Demand Growth %", top_n=15)); tab += 1
    vis.append(table_visual(f"{P10}.detail",
                            [("DimProduct", "ProductName"), ("DimProduct", "Category")],
                            ["Actual Demand Units", "Baseline Forecast Units",
                             "Forecast Bias %", "Forecast WAPE",
                             "Demand Growth %", "Product Demand CV", "XYZ Class"],
                            "Demand & Forecast Detail",
                            CX + 2 * (w3 + GAP), yB, w3, hB, tab)); tab += 1
    return make_page(P10, "Demand Forecasting"), vis


# --------------------------------------------------------------------------- #
# The finished dashboard's palette, read off the published screenshots.
#
# One dusty-pink banner on every page; the accent below it changes page by page and
# is applied to the KPI cards, the chart title bars and the slicers. Executive and
# Procurement carry a pale wash and plain chart titles; the later pages each take a
# stronger hue. Forecasting is the odd one out - grey tiles with yellow slicers.
#
# These are a RECONSTRUCTION from the images, not the original values.
# --------------------------------------------------------------------------- #
PAGE_STYLE = {
    P1:  {"card": "#EAF0F7", "bar": False,     "slicer": "#FFFFFF"},
    P2:  {"card": "#EAF0F7", "bar": "#BDD7EE", "slicer": "#FFFFFF"},
    P3:  {"card": "#EAF0F7", "bar": "#DCE6F2", "slicer": "#FFFFFF"},
    P4:  {"card": "#B4B4D8", "bar": "#B4B4D8", "slicer": "#EFEFF7"},
    P5:  {"card": "#C6E0B4", "bar": "#C6E0B4", "slicer": "#CFE7F5"},
    P6:  {"card": "#9DC3E6", "bar": "#9DC3E6", "slicer": "#CFE2F3"},
    P7:  {"card": "#B1B0D8", "bar": "#B1B0D8", "slicer": "#C5C4E4"},
    P8:  {"card": "#F4C7A8", "bar": "#F4C7A8", "slicer": "#FFFFFF"},
    P9:  {"card": "#F2B6C6", "bar": "#F2B6C6", "slicer": "#F7D6DE"},
    P10: {"card": "#E7E6E6", "bar": "#D9D9D9", "slicer": "#FFE699"},
}

# The banner wording as it appears on the finished pages, which is not always the
# page's own displayName.
BANNER_TITLE = {
    P1:  "Executive Control Tower",
    P2:  "Inventory Overview",
    P3:  "Procurement Overview",
    P4:  "Logistic & Delivery",
    P5:  "Warehouse Performance",
    P6:  "Product Detail",
    P7:  "Stock & Replenishment Risk",
    P8:  "ABC/XYZ Inventory Strategy",
    P9:  "Supplier Performance",
    P10: "Demand Forecasting",
}

PAGES = [build_p1, build_p2, build_p3, build_p4, build_p5, build_p6, build_p7,
         build_p8, build_p9, build_p10]


def collect_refs(node, out):
    if isinstance(node, dict):
        if isinstance(node.get("Measure"), dict):
            m = node["Measure"]
            out.append(("measure", m["Expression"]["SourceRef"]["Entity"], m["Property"]))
        if isinstance(node.get("Column"), dict):
            c = node["Column"]
            out.append(("column", c["Expression"]["SourceRef"]["Entity"], c["Property"]))
        for v in node.values():
            collect_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_refs(v, out)


def build_registry():
    reg = Registry()
    for uri, f in LOCAL_SCHEMAS.items():
        reg = reg.with_resource(uri, Resource.from_contents(
            json.loads((SCHEMAS / f).read_text(encoding="utf-8")),
            default_specification=DRAFT7))
    return reg


def main() -> int:
    check_only = "--check" in sys.argv
    tables, measures = index_model()
    print(f"Semantic model: {len(tables)} tables, {len(measures)} measures\n")

    built = [fn() for fn in PAGES]
    reg = build_registry()
    vs = json.loads((SCHEMAS / LOCAL_SCHEMAS[VISUAL_SCHEMA]).read_text(encoding="utf-8"))
    ps = json.loads((SCHEMAS / LOCAL_SCHEMAS[PAGE_SCHEMA]).read_text(encoding="utf-8"))
    vval, pval = Draft7Validator(vs, registry=reg), Draft7Validator(ps, registry=reg)

    total_v = errors = bad_refs = 0
    all_ids: list[str] = []
    types: dict[str, int] = {}
    for page, vis in built:
        total_v += len(vis)
        refs: list = []
        collect_refs(vis, refs)
        for kind, table, prop in refs:
            if kind == "measure" and prop not in measures:
                print(f"  INVALID measure [{prop}]"); bad_refs += 1
            elif kind == "column" and (table not in tables or prop not in tables[table]):
                print(f"  INVALID column {table}[{prop}]"); bad_refs += 1
        for e in pval.iter_errors(page):
            print(f"  PAGE {page['name']}: {list(e.path)}: {e.message}"); errors += 1
        for v in vis:
            all_ids.append(v["name"])
            types[v["visual"]["visualType"]] = types.get(v["visual"]["visualType"], 0) + 1
            for e in vval.iter_errors(v):
                print(f"  VISUAL {v['visual']['visualType']}: {list(e.path)}: {e.message}")
                errors += 1
            p = v["position"]
            if p["x"] < 0 or p["x"] + p["width"] > CANVAS_W or \
               p["y"] < 0 or p["y"] + p["height"] > CANVAS_H:
                print(f"  OVERFLOW {v['name']} {p}"); errors += 1
        print(f"  {page['displayName']:<28} {len(vis):>2} visuals")

    blob = json.dumps([v for _, vis in built for v in vis])
    src = blob.count('"Source"')
    print(f"\nVisual types used: " + ", ".join(f"{k}={v}" for k, v in sorted(types.items())))
    print(f"\nPages {len(built)}, visuals {total_v}")
    print(f"Field references invalid : {bad_refs}")
    print(f"Schema/geometry errors   : {errors}")
    print(f"Duplicate visual ids     : {len(all_ids) - len(set(all_ids))}")
    print(f"SourceRef using 'Source' : {src}  (must be 0)")
    print(f"stackedColumnChart used  : {blob.count('stackedColumnChart')}  (must be 0)")
    if bad_refs or errors or src or len(all_ids) != len(set(all_ids)):
        return 1

    if check_only:
        print("\n--check: nothing written")
        return 0

    pages_dir = REPORT / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    written = 0
    for page, vis in built:
        pdir = pages_dir / page["name"]
        (pdir / "visuals").mkdir(parents=True, exist_ok=True)
        (pdir / "page.json").write_text(json.dumps(page, indent=2) + "\n", encoding="utf-8")
        written += 1
        for v in vis:
            d = pdir / "visuals" / v["name"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "visual.json").write_text(json.dumps(v, indent=2) + "\n", encoding="utf-8")
            written += 1
    meta = {"$schema": PAGES_SCHEMA,
            "pageOrder": [p["name"] for p, _ in built],
            "activePageName": built[0][0]["name"]}
    (pages_dir / "pages.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    written += 1
    print(f"\nWritten {written} files across {len(built)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
