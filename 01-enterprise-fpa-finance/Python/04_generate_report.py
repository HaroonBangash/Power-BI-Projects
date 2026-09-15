# -*- coding: utf-8 -*-
"""
Phase 4 - Report pages (PBIR as code).

Eight pages, each answering one question a CFO's pack has to answer, behind a left
navigation rail. Every visual type was first proven in the Phase 3 visual lab
(Validation/evidence/phase3, git history); the lab pages are replaced by these.

  Executive        Where did the year land, and what is the outlook?
  Income Statement The statement itself: actual, budget and variance, line by line
  Budget Variance  Where the plan and the ledger differ - and what is unusual
  Cost Centres     What the departments spend it on, and with whom
  Scenario         What the rest of the year looks like under stated assumptions
  Working Capital  What is owed, how old it is, and how fast it moves
  Cash & FX        What the group holds, and what the exchange rate did
  Data & Method    What was assumed, fixed and flagged

DOMAIN RULES THE PAGES OBEY (PROJECT_STATE D4-D13, D19-D23, D28-D30)
  * One as-of date (31 Aug 2026). A balance is stated ON a date; an invoice paid
    after it was open on it.
  * Plan comparisons stop at operating profit: interest, FX and tax have no budget,
    so their variance is blank, never a 100% miss.
  * Variance is favourable-positive, and margins vary in percentage points.
  * A prior-year comparison is blank where the ledger does not cover the earlier
    window (FY22 is half a year, so FY23 has no honest growth rate).
  * Constant currency is blank unless every row in the period has a prior-year rate.
  * Entities are compared on currency-neutral ratios; absolute entity size follows
    the exchange rate, which is a property of the source, not performance.
  * A variance is called out only when it leaves that line's own usual range
    (|z| >= 2), through colour measures with a dead zone.
  * The actual-to-plan gap is structural (the ledger is a partial extract): it is
    shown as measured and labelled, never rescaled.

PRESENTATION RULES LEARNED FROM THE LAB RENDERS (Validation/evidence/phase3)
  * Gauge >= 110 px or the arc is clipped; multi-row card >= 110 px for three rows;
    decomposition tree >= 260 px; a table >= 180 px; a button slicer ~120 px an option.
  * A calculation group on a matrix's columns fits four items at half width.
  * Money axes start at zero; a table whose rows are not additive has totals off.
  * A page-level filter sets the period; a slicer default selection does not work.

Usage:  python Python/04_generate_report.py [--only KEY] [--check]
        --only   write ONE page for a rendering check: Power BI Desktop does not
                 reliably open a requested page
        --check  validate only, write nothing
"""
import argparse
import hashlib
import itertools
import json
import re
import shutil
import sys
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "PowerBI"
RP = PBI / "EnterpriseFPA.Report"
PAGES_DIR = RP / "definition" / "pages"
DEF = PBI / "EnterpriseFPA.SemanticModel" / "definition"
SCHEMAS = PBI / "schemas"
MANIFEST = ROOT / "Validation" / "report_manifest.json"

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

# ------------------------------------------------------------ design tokens ---
W, H = 1280, 720
NAV_W, MARGIN, GAP = 168, 16, 12
CX = NAV_W + MARGIN
CW = W - CX - MARGIN
HEADER_Y, HEADER_H = 8, 40
SLICER_Y, SLICER_H = 52, 62
KPI_Y, KPI_H = 122, 74
ROW2_Y, ROW2_H = 206, 244
ROW3_Y, ROW3_H = 462, 196
NOTE_Y, NOTE_H = 668, 44

# The client's reference design: a charcoal canvas and dark slate panels, and on top of
# them a palette that MOVES. Nothing in the reference is painted in a single accent -
# each figure carries its own hue and tints the card it sits in. So here: a card takes
# the next hue in a rotation, each page starts that rotation on its own signature hue
# (which the navigation rail also wears), and a chart takes its subject's colour. The
# plan is always indigo, so actual-against-budget reads the same way on every page.
# Applied twice: a registered custom theme sets what every visual inherits, and the
# explicit colours here win where a visual carries its own format.
PAGE_BG, PANEL, PANEL_ALT = "#0B0D12", "#151A23", "#1B212C"
BORDER, GRID = "#262E3B", "#1E2531"
INK, MUTED, NEUTRAL = "#E7EAF0", "#9AA4B6", "#6B7688"
HEADER_INK = "#AEBBD1"                  # table and matrix headers: cool, quiet, legible
AMBER = "#F5A524"
POSITIVE, NEGATIVE = "#22C55E", "#EF4444"
# Fill hues (500-level): a fill sits behind nothing, so it needs less contrast than text.
BLUE, PURPLE, PINK, CYAN = "#3B82F6", "#A855F7", "#EC4899", "#22D3EE"
GREEN, INDIGO, TEAL, LIME = "#22C55E", "#818CF8", "#2DD4BF", "#A3E635"
# Text hues (400-level): bright enough for a number read against a dark panel.
T_AMBER, T_GREEN, T_BLUE, T_PURPLE = "#F5A524", "#4ADE80", "#60A5FA", "#C084FC"
T_PINK, T_CYAN, T_ORANGE, T_INDIGO, T_LIME = "#F472B6", "#22D3EE", "#FB923C", "#818CF8", "#A3E635"
# The rotation. Consecutive hues sit far apart on the colour wheel, so no two cards in a
# row read as the same colour and no two pages open on the same sequence.
SPECTRUM = [T_AMBER, T_INDIGO, T_LIME, T_PURPLE, T_CYAN, T_PINK, T_BLUE, T_GREEN]
ACCENT = T_AMBER
DATA_COLOURS = ["#F5A524", "#60A5FA", "#A3E635", "#C084FC", "#22D3EE", "#F472B6",
                "#4ADE80", "#FB923C", "#818CF8", "#2DD4BF"]
THEME_FILE = "NorthstarSpectrum.json"

SB_PAD, SB_BTN_H, SB_GAP, SB_TOP, SB_FONT = 10, 36, 4, 60, 9
SB_BTN_W = NAV_W - 2 * SB_PAD
SB_BG_DEFAULT = "#141922"
SB_FG_DEFAULT, SB_FG_SELECTED = INK, "#12161D"
NAV_ITEMS = [("Executive", "exec"), ("Income Statement", "statement"), ("Budget Variance", "variance"),
             ("Cost Centres", "costs"), ("Scenario", "scenario"), ("Working Capital", "workingcapital"),
             ("Cash & FX", "cashfx"), ("Data & Method", "method")]
# A page's signature hue: the selected rail button is painted in it, the rail's brand
# line is written in it, and the page's cards start their rotation there. Eight pages,
# eight starting points, so the palette shifts as the reader moves through the report.
PAGE_ACCENT = {key: SPECTRUM[i % len(SPECTRUM)] for i, (_, key) in enumerate(NAV_ITEMS)}

DATE, ENT, DEPT, ACCT = "DimDate", "DimEntity", "DimDepartment", "DimAccount"
PLLINE, BUCKET, SCEN, STEP = "DimPLLine", "DimAgeingBucket", "DimScenario", "DimSensitivityStep"
CUST, VEND, DQ = "DimCustomer", "DimVendor", "DataQualityMetric"
FX, VERSION, PERIOD = "FxRateMonthly", "Plan Version", "Period View"
MANIFEST_ROWS = []
REPORTING_YEAR = "FY26"          # the last complete financial year on the as-of date


# ------------------------------------------------------------------ helpers ---
def sid(seed):
    return hashlib.sha1(seed.encode()).hexdigest()[:20]


def page_id(key):
    return sid("page." + key)


def lit_s(v): return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}
def lit_n(v): return {"expr": {"Literal": {"Value": f"{v}D"}}}
def lit_l(v): return {"expr": {"Literal": {"Value": f"{v}L"}}}
def lit_b(v): return {"expr": {"Literal": {"Value": "true" if v else "false"}}}


def measure_ref(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def column_ref(table, column):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def pm(name, display=None):
    p = {"field": measure_ref(name), "queryRef": f"_Measures.{name}", "nativeQueryRef": name}
    if display:
        p["displayName"] = display
    return p


def pc(table, column, display=None):
    p = {"field": column_ref(table, column), "queryRef": f"{table}.{column}", "nativeQueryRef": column, "active": True}
    if display:
        p["displayName"] = display
    return p


def query(roles, sort=None, desc=True):
    q = {"queryState": {r: {"projections": p} for r, p in roles.items()}}
    if sort:
        field = measure_ref(sort) if isinstance(sort, str) else column_ref(*sort)
        q["sortDefinition"] = {"sort": [{"field": field, "direction": "Descending" if desc else "Ascending"}],
                               "isDefaultSort": False}
    return q


def colours(pairs):
    return {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit_s(c)}}},
                           "selector": {"metadata": f"_Measures.{m}"}} for m, c in pairs]}


def one_colour(measure, colour, by=None):
    """One hue for a single-series chart. A bar or column chart colours by CATEGORY, so
    the measure-keyed selector `colours()` writes is ignored there and the chart falls
    back to the palette's first hue - which is how a whole report ends up one colour.
    `defaultColor` is what those visuals actually read. The keyed entry stays for the
    ones that read it instead: lines, areas and small multiples honour it.

    `by` names a measure returning a hex colour, which paints each bar from the number
    it draws and wins over the flat colour; the flat colour then says plainly, in a
    render, whether the expression took."""
    dp = [{"properties": {"defaultColor": {"solid": {"color": lit_s(colour)}}}},
          {"properties": {"fill": {"solid": {"color": lit_s(colour)}}},
           "selector": {"metadata": f"_Measures.{measure}"}}]
    if by:
        dp.append({"properties": {"fill": {"solid": {"color": {"expr": measure_ref(by)}}}},
                   "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}})
    return {"dataPoint": dp}


DATA_LABELS = {"labels": [{"properties": {"show": lit_b(True)}}]}
CATEGORICAL_AXIS = {"categoryAxis": [{"properties": {"axisType": lit_s("Categorical")}}]}
ZERO_BASED = {"valueAxis": [{"properties": {"start": lit_n(0)}}]}
DONUT_PERCENT = {"labels": [{"properties": {"labelStyle": lit_s("Percent of total")}}]}
NO_SUBTOTALS = {"subTotals": [{"properties": {"columnSubtotals": lit_b(False), "rowSubtotals": lit_b(False)}}]}
NO_LEGEND = {"legend": [{"properties": {"show": lit_b(False)}}]}
# A narrow panel truncates every entity name in a right-hand legend.
LEGEND_BOTTOM = {"legend": [{"properties": {"show": lit_b(True), "position": lit_s("Bottom")}}]}
WIDE_LABELS = {"categoryAxis": [{"properties": {"maxMarginFactor": lit_l(45)}}]}

CHROMELESS = {"textbox", "actionButton"}


def blend(base, accent, weight):
    """`accent` mixed into `base`. A card is tinted toward its own hue this way, which
    colours the panel without lifting it off the charcoal canvas the design is built on."""
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    a = [int(accent[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(b[i] + (a[i] - b[i]) * weight):02X}" for i in range(3))


def container(panel, accent=None):
    if not panel:
        return {"background": [{"properties": {"show": lit_b(False)}}],
                "border": [{"properties": {"show": lit_b(False)}}]}
    fill = PANEL if accent is None else blend(PANEL, accent, 0.13)
    edge = BORDER if accent is None else blend(BORDER, accent, 0.5)
    return {"background": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(fill)}},
                                           "transparency": lit_n(0)}}],
            "border": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(edge)}},
                                       "radius": lit_n(8)}}]}


def visual(seed, vtype, box, tab, q=None, objects=None, title=None, filters=None, why="", title_size=10,
           panel=None, accent=None):
    x, y, w, h = box
    position = {"x": x, "y": y, "z": 0, "height": h, "width": w}   # Power BI's own key order
    if tab:
        position["tabOrder"] = tab
    v = {"$schema": VISUAL_SCHEMA, "name": sid(seed), "position": position, "visual": {"visualType": vtype}}
    if q:
        q = json.loads(json.dumps(q))
        q.get("sortDefinition", {}).pop("isDefaultSort", None)
        qs = q["queryState"]
        if vtype == "scatterChart":
            for p in qs.get("X", {}).get("projections", []):
                p["active"] = True
        if vtype == "tableEx":
            for p in qs.get("Values", {}).get("projections", []):
                p.pop("active", None)
        v["visual"]["query"] = q
    if vtype == "decompositionTreeVisual" and not objects:
        objects = {"tree": [{"properties": {"effectiveBarsPerLevel": lit_l(3)}}]}
    if objects:
        v["visual"]["objects"] = objects
    vco = container(vtype not in CHROMELESS if panel is None else panel, accent)
    if title is not None:
        vco["title"] = [{"properties": {
            "show": lit_b(bool(title)), "text": lit_s(title), "fontSize": lit_n(title_size),
            "fontColor": {"solid": {"color": lit_s(INK)}}, "alignment": lit_s("left")}}]
    v["visual"]["visualContainerObjects"] = vco
    v["visual"]["drillFilterOtherVisuals"] = True
    if filters:
        v["filterConfig"] = {"filters": filters}
    MANIFEST_ROWS.append({"name": v["name"], "visualType": vtype, "title": title or "", "demonstrates": why})
    return v


def field_colour(colour_measure, shown_measure):
    """Cell background from a measure that returns a hex colour. The colour measures
    keep a dead zone: inside |z| < 2 a cell stays the panel colour, so noise is never
    shaded as if it were news."""
    return [{"properties": {"backColor": {"solid": {"color": {"expr": measure_ref(colour_measure)}}}},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                          "metadata": f"_Measures.{shown_measure}"}}]


def categorical_filter(seed, table, column, values):
    alias = table[0].lower()
    return {"name": sid(seed + "." + column), "field": column_ref(table, column), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": alias, "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}},
                                                       "Property": column}}],
                           "Values": [[{"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}] for v in values]}}}]}}


def top_n(seed, table, column, n):
    return {"name": sid(seed + ".topn"), "field": column_ref(table, column), "type": "VisualTopN",
            "filter": {"Version": 2, "From": [{"Name": table[0].lower(), "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"VisualTopN": {"ItemCount": n}}}]}}


def year_filter(seed, year=REPORTING_YEAR):
    return categorical_filter(seed + ".year", DATE, "FinancialYear", [year])


def split(weights, y, h, x0=CX, total=CW):
    if isinstance(weights, int):
        weights = [1] * weights
    avail = total - GAP * (len(weights) - 1)
    boxes, x = [], x0
    for i, wt in enumerate(weights):
        w = round(avail * wt / sum(weights)) if i < len(weights) - 1 else x0 + total - x
        boxes.append((x, y, w, h))
        x += w + GAP
    return boxes


def textbox(seed, paragraphs, box, tab, size=10, colour=INK):
    paras = []
    for p in paragraphs:
        runs = [(p, False)] if isinstance(p, str) else p
        paras.append({"textRuns": [{"value": r[0], "textStyle": {"fontSize": f"{size}pt",
                                                                 "color": r[2] if len(r) > 2 else colour,
                                                                 **({"fontWeight": "bold"} if r[1] else {})}}
                                   for r in runs]})
    return visual(seed, "textbox", box, tab, objects={"general": [{"properties": {"paragraphs": paras}}]})


def card(seed, measure, label, box, tab, size=18, colour=ACCENT, kind=None, font="Consolas", panel=None,
         filters=None, tint=True):
    """A headline figure. The number is written in the card's own hue and the panel is
    tinted toward it, so a row of cards reads as a row of colours."""
    labels = {"fontSize": lit_n(size), "color": {"solid": {"color": lit_s(colour)}}}
    if font:
        labels["fontFamily"] = lit_s(font)
    if kind == "money":
        labels |= {"labelDisplayUnits": lit_n(0), "labelPrecision": lit_l(2)}
    elif kind == "count":
        labels |= {"labelDisplayUnits": lit_n(1)}
    objects = {"labels": [{"properties": labels}], "categoryLabels": [{"properties": {"show": lit_b(False)}}]}
    return visual(seed, "card", box, tab, query({"Values": [pm(measure)]}), objects, title=label, title_size=9,
                  why=f"Headline figure: {measure}", panel=panel, filters=filters,
                  accent=colour if tint else None)


def slicer(seed, table, column, label, box, tab):
    objects = {"data": [{"properties": {"mode": lit_s("Dropdown")}}],
               # No fontSize: Power BI strips it from a slicer header, so it never applied.
               # The header takes the theme's label class instead.
               "header": [{"properties": {"show": lit_b(True), "text": lit_s(label),
                                          "fontColor": {"solid": {"color": lit_s(MUTED)}}}}]}
    return visual(seed, "slicer", box, tab, query({"Values": [pc(table, column)]}), objects, title="",
                  why=f"Filter by {label}")


def nav_button(seed, label, target, selected, y, tab, accent=ACCENT):
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(not selected)}},
                    {"properties": {"lineColor": {"solid": {"color": lit_s(BORDER)}}}, "selector": {"id": "default"}}],
        "fill": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"fillColor": {"solid": {"color": lit_s(accent if selected else SB_BG_DEFAULT)}},
                                 "transparency": lit_n(0)},
                  "selector": {"id": "default"}}],
        "text": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"text": lit_s(label),
                                 "fontColor": {"solid": {"color": lit_s(SB_FG_SELECTED if selected else SB_FG_DEFAULT)}},
                                 "fontSize": lit_n(SB_FONT), "bold": lit_b(selected)},
                  "selector": {"id": "default"}}],
    }
    v = visual(seed, "actionButton", (SB_PAD, y, SB_BTN_W, SB_BTN_H), tab, objects=objects, title="",
               why=f"Navigate to {label}")
    v["visual"]["visualContainerObjects"]["visualLink"] = [{"properties": {
        "show": lit_b(True), "type": lit_s("PageNavigation"), "navigationSection": lit_s(target)}}]
    return v


def shell(key, title):
    accent = PAGE_ACCENT[key]
    v = [textbox(f"{key}.rail.hdr", [[("NORTHSTAR", True, INK)], [("GROUP FP&A", True, accent)]],
                 (SB_PAD, 10, SB_BTN_W, 44), 0, size=10)]
    for i, (label, target) in enumerate(NAV_ITEMS):
        v.append(nav_button(f"{key}.nav.{target}", label, page_id(target), target == key,
                            SB_TOP + i * (SB_BTN_H + SB_GAP), len(v), accent=accent))
    v.append(textbox(f"{key}.rail.ftr", ["Synthetic portfolio dataset", "- not client data"],
                     (SB_PAD, 668, SB_BTN_W, 40), len(v), size=8, colour=MUTED))
    v.append(textbox(f"{key}.title", [[(title, True)]], (CX, HEADER_Y, 520, HEADER_H), len(v), size=16))
    v.append(card(f"{key}.context", "Report Context", "", (W - MARGIN - 540, HEADER_Y, 540, HEADER_H), len(v),
                  size=9, colour=MUTED, font="Segoe UI", panel=False, tint=False))
    return v


def kpis(key, items, v, y=KPI_Y, height=KPI_H, filters=None):
    """items: (measure, label, kind). Each card takes the next hue after the page's own,
    so every card on a page is a different colour and no two pages open the same way."""
    start = SPECTRUM.index(PAGE_ACCENT[key])
    for i, ((measure, label, kind), box) in enumerate(zip(items, split(len(items), y, height))):
        v.append(card(f"{key}.kpi.{measure}", measure, label, box, len(v), kind=kind, filters=filters,
                      colour=SPECTRUM[(start + i) % len(SPECTRUM)]))


def note(key, lead, text, v):
    v.append(textbox(f"{key}.note", [[(lead + "  ", True), (text, False)]], (CX, NOTE_Y, CW, NOTE_H), len(v),
                     size=9, colour=MUTED))


def slicers(key, specs, v):
    for i, (table, column, label) in enumerate(specs):
        v.append(slicer(f"{key}.sl.{column}", table, column, label, (CX + i * 212, SLICER_Y, 200, SLICER_H), len(v)))


# ------------------------------------------------------------------- pages ---
def page_exec():
    """Anchored to the as-of date rather than to a selection: every card names its
    own window, so the page means the same thing however it is opened."""
    k = "exec"
    v = shell(k, "Executive Summary")
    slicers(k, [(ENT, "EntityName", "Entity")], v)
    kpis(k, [("Revenue TTM", "Revenue, 12 months to Aug 2026", "money"),
             ("Operating Profit TTM", "Operating profit, 12 months", "money"),
             ("Revenue Current FY to Date", "Revenue, FY27 to date", "money"),
             ("Cash Balance", "Cash at 31 Aug 2026", "money"),
             ("AR Balance", "Receivables outstanding", "money"),
             ("Outlook Operating Profit", "FY27 outlook, base case", "money")], v)
    b = split([46, 60], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.bridge", "waterfallChart", b[0], len(v),
                    query({"Category": [pc(PLLINE, "LineName", "Statement line")],
                           "Y": [pm("P&L Bridge Amount", "Contribution to profit")]}),
                    filters=[year_filter(f"{k}.bridge"),
                             categorical_filter(f"{k}.bridge.type", PLLINE, "LineType", ["Group"])],
                    title=f"How {REPORTING_YEAR} revenue became a loss",
                    why="waterfall: revenue less each cost group, netting to net profit"))
    v.append(visual(f"{k}.trend", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Revenue Actual", "Actual"), pm("Revenue Budget", "Budget")]}),
                    objects=colours([("Revenue Actual", AMBER), ("Revenue Budget", INDIGO)]) | ZERO_BASED,
                    title="Revenue by month against budget, since 2022",
                    why="the gap to plan is a level, not a trend: it never closes and never widens"))
    b = split([38, 34, 34], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.byyear", "clusteredColumnChart", b[0], len(v),
                    query({"Category": [pc(DATE, "FinancialYear", "Financial year")],
                           "Y": [pm("Operating Profit Actual", "Actual"), pm("Operating Profit Budget", "Budget")]}),
                    objects=colours([("Operating Profit Actual", TEAL), ("Operating Profit Budget", INDIGO)]),
                    title="Operating profit against budget by year",
                    why="the result is a loss in the plan as well as the ledger"))
    v.append(visual(f"{k}.margin", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(ENT, "EntityShort", "Entity")],
                           "Y": [pm("Gross Margin %", "Gross margin")]}, sort="Gross Margin %"),
                    objects=one_colour("Gross Margin %", GREEN) | DATA_LABELS,
                    filters=[year_filter(f"{k}.margin")],
                    title=f"Gross margin by entity, {REPORTING_YEAR}",
                    why="currency-neutral: translation moves revenue and COGS by the same rate; columns because "
                        "six entities do not fit a short bar chart"))
    # The kpi visual was tried here and rejected on the evidence: below goal it paints
    # the WHOLE panel in the goal-distance colour, which buries its own number on a
    # dark canvas - see the visual catalogue.
    v.append(visual(f"{k}.streams", "columnChart", b[2], len(v),
                    query({"Category": [pc(DATE, "FinancialYear", "Financial year")],
                           "Series": [pc(ACCT, "AccountName", "Stream")],
                           "Y": [pm("Revenue", "Revenue")]}),
                    filters=[categorical_filter(f"{k}.streams", ACCT, "AccountGroup", ["Revenue"])],
                    title="Revenue by stream",
                    why="stacked column: the three revenue streams hold the same shares year after year"))
    note(k, "How to read this.",
         "Cards are anchored to the as-of date (31 Aug 2026) and name their own window. Revenue has run at about 70% "
         "of budget in all 56 months on record - a plan-calibration finding, not news about the year, because the "
         "ledger is a partial extract (Data & Method). FY26 operating profit still beat budget by $1.6M: operating "
         "expense came in $10.6M under.", v)
    return {"name": page_id(k), "displayName": "Executive Summary"}, v, []


def page_statement():
    k = "statement"
    v = shell(k, f"Income Statement - {REPORTING_YEAR}")
    slicers(k, [(ENT, "EntityName", "Entity"), (DEPT, "DepartmentName", "Department")], v)
    kpis(k, [("Revenue", "Revenue", "money"), ("Gross Profit", "Gross profit", "money"),
             ("Operating Profit", "Operating profit", "money"), ("Net Profit", "Net profit", "money")], v)
    b = split([50, 56], ROW2_Y, 300)
    v.append(visual(f"{k}.statement", "pivotTable", b[0], len(v),
                    query({"Rows": [pc(PLLINE, "LineName", "Statement line")],
                           "Columns": [pc(VERSION, "Version")],
                           "Values": [pm("P&L Line Value", "Value")]}),
                    objects=NO_SUBTOTALS,
                    filters=[categorical_filter(f"{k}.statement.v", VERSION, "Version",
                                                ["Actual", "Budget", "Var vs Budget", "Var % vs Budget"])],
                    title="The statement: actual, budget and variance",
                    why="one measure under the Plan Version calculation group; margins vary in percentage points, "
                        "and the unbudgeted lines carry no variance at all"))
    v.append(visual(f"{k}.accounts", "pivotTable", b[1], len(v),
                    query({"Rows": [pc(ACCT, "AccountGroup", "Group"), pc(ACCT, "AccountLabel", "Account")],
                           "Columns": [pc(VERSION, "Version")],
                           "Values": [pm("Account Amount", "Amount")]}),
                    objects=NO_SUBTOTALS,
                    filters=[categorical_filter(f"{k}.accounts.v", VERSION, "Version",
                                                ["Actual", "Budget", "Var vs Budget"])],
                    title="Account detail, in natural signs",
                    why="every account against its plan; revenue and costs both read positive"))
    b = split([46, 32, 28], 518, 140)
    v.append(visual(f"{k}.combo", "lineClusteredColumnComboChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthShort", "Month")],
                           "Y": [pm("Revenue Actual", "Actual"), pm("Revenue Budget", "Budget")],
                           "Y2": [pm("Gross Margin %", "Gross margin")]}),
                    objects=colours([("Revenue Actual", AMBER), ("Revenue Budget", INDIGO),
                                     ("Gross Margin %", GREEN)]) | CATEGORICAL_AXIS,
                    title="By month, July to June, with gross margin on the right",
                    why="the financial year reads July first; margin sits on its own axis"))
    v.append(visual(f"{k}.mix", "hundredPercentStackedColumnChart", b[1], len(v),
                    query({"Category": [pc(ENT, "EntityShort", "Entity")],
                           "Series": [pc(ACCT, "AccountGroup", "Cost group")],
                           "Y": [pm("Account Amount", "Amount")]}),
                    filters=[categorical_filter(f"{k}.mix.g", ACCT, "AccountGroup",
                                                ["COGS", "Operating Expense", "Other Expense", "Tax"])],
                    title="Cost mix by entity",
                    why="composition of cost only - revenue is excluded, or the mix would be meaningless"))
    v.append(visual(f"{k}.margins", "multiRowCard", b[2], len(v),
                    query({"Values": [pm("Gross Margin %", "Gross margin"),
                                      pm("Operating Margin %", "Operating margin"),
                                      pm("Net Margin %", "Net margin")]}),
                    accent=T_INDIGO,
                    title="", why="multiRowCard: the three margins in one panel, at a height that fits them"))
    note(k, "Scope.",
         "Actual, budget and forecast are the same measure under the Plan Version calculation group. The plan covers "
         "revenue, COGS and operating expense only, so interest, FX and tax show an actual and no variance, and the "
         "budget has no net profit at all. Margin lines vary in percentage points; a percentage of a percentage is "
         "left blank.", v)
    return {"name": page_id(k), "displayName": "Income Statement"}, v, []


def page_variance():
    k = "variance"
    v = shell(k, f"Budget Variance - {REPORTING_YEAR}")
    slicers(k, [(ENT, "EntityName", "Entity")], v)
    kpis(k, [("Revenue vs Budget", "Revenue vs budget", "money"),
             ("Operating Expense vs Budget", "Operating expense underspend", "money"),
             ("Operating Profit vs Budget", "Operating profit vs budget", "money"),
             ("Revenue Achievement %", "Revenue as % of budget", None),
             ("Operating Expense vs Budget %", "Underspend as % of budget", None)], v)
    b = split([44, 62], ROW2_Y, 244)
    v.append(visual(f"{k}.deptbar", "clusteredColumnChart", b[0], len(v),
                    query({"Category": [pc(DEPT, "DepartmentName", "Department")],
                           "Y": [pm("Operating Expense vs Budget %", "Underspend %")]}, sort="Operating Expense vs Budget %"),
                    objects=one_colour("Operating Expense vs Budget %", LIME) | DATA_LABELS,
                    title="Underspend as a share of each department's budget",
                    why="the gap is the same size everywhere: 25-38% in every cost centre. Columns, because ten bars "
                        "do not fit even the taller row - a matrix does, a bar chart does not"))
    v.append(visual(f"{k}.heatmap", "pivotTable", b[1], len(v),
                    query({"Rows": [pc(DEPT, "DepartmentName", "Department")],
                           "Columns": [pc(DATE, "MonthShort", "Month")],
                           "Values": [pm("Opex vs Budget Z-Score", "z")]}),
                    objects=NO_SUBTOTALS | {"values": field_colour("Opex Variance Colour", "Opex vs Budget Z-Score")},
                    title="Unusual months: variance against each department's own range (z)",
                    why="dead-zone colour: only |z| >= 2 is shaded. The page is one financial year, so the short "
                        "month name is unique and twelve columns fit"))
    b = split([44, 34, 28], 462, 196)
    v.append(visual(f"{k}.waterfall", "waterfallChart", b[0], len(v),
                    query({"Category": [pc(DEPT, "DepartmentName", "Department")],
                           "Y": [pm("Operating Expense vs Budget", "Underspend")]}),
                    title="Which cost centres are under budget",
                    why="waterfall: every department contributes to the underspend, none offsets it"),)
    v.append(visual(f"{k}.scatter", "scatterChart", b[1], len(v),
                    query({"Category": [pc(DEPT, "DepartmentName", "Department")],
                           "X": [pm("Operating Expense Budget", "Budget")],
                           "Y": [pm("Operating Expense Actual", "Actual")],
                           "Size": [pm("GL Lines", "Ledger lines")]}),
                    objects=one_colour("Operating Expense Actual", PURPLE),
                    title="Budget against actual, by department",
                    why="every department sits well below the line: a plan-wide gap, not a department's overspend"))
    v.append(visual(f"{k}.gauge", "gauge", b[2], len(v),
                    query({"Y": [pm("Revenue Actual", "Actual")], "TargetValue": [pm("Revenue Budget", "Budget")]}),
                    title="Revenue against budget", title_size=9,
                    why="achievement against a real target; 196 px gives the arc room"))
    note(k, "What counts as unusual.",
         "Every department is under budget by 25-38%, in every month: that is the plan's calibration, not performance. "
         "So a month is called out only when it leaves that department's own usual range - 11 of the 120 "
         f"department-months in {REPORTING_YEAR} reach |z| >= 2, against about 6 expected by chance. Positive is "
         "favourable throughout.", v)
    return {"name": page_id(k), "displayName": "Budget Variance"}, v, []


def page_costs():
    k = "costs"
    v = shell(k, f"Cost Centres - {REPORTING_YEAR}")
    slicers(k, [(ENT, "EntityName", "Entity"), (DEPT, "DepartmentName", "Department")], v)
    kpis(k, [("Operating Expense", "Operating expense", "money"),
             ("Opex % of Revenue", "Operating expense to revenue", None),
             ("COGS % of Revenue", "COGS to revenue", None),
             ("Accrued Share of Lines", "Ledger lines still accrued", None),
             ("Active Vendors", "Vendors used", "count")], v)
    b = split([46, 60], ROW2_Y, 244)
    v.append(visual(f"{k}.treemap", "treemap", b[0], len(v),
                    query({"Group": [pc(DEPT, "DepartmentName", "Department")],
                           "Details": [pc(ACCT, "AccountName", "Account")],
                           "Values": [pm("Operating Expense", "Operating expense")]}),
                    title="Operating expense by cost centre and account",
                    why="treemap: ten departments and eleven accounts in one view"))
    v.append(visual(f"{k}.tree", "decompositionTreeVisual", b[1], len(v),
                    query({"Analyze": [pm("Operating Expense", "Operating expense")],
                           "ExplainBy": [pc(ENT, "EntityName", "Entity"), pc(DEPT, "DepartmentName", "Department"),
                                         pc(ACCT, "AccountName", "Account"),
                                         pc(VEND, "VendorCategory", "Vendor category")]}),
                    title="Where the operating expense sits - choose the path",
                    why="decomposition tree: entity, department, account or vendor category, in any order"))
    v.append(visual(f"{k}.table", "tableEx", (CX, 462, CW, 196), len(v),
                    query({"Values": [pc(DEPT, "DepartmentName", "Department"),
                                      pm("Operating Expense", "Actual"), pm("Operating Expense Budget", "Budget"),
                                      pm("Operating Expense vs Budget", "Underspend"),
                                      pm("Operating Expense vs Budget %", "Underspend %"),
                                      pm("Opex % of Revenue", "% of revenue")]}, sort="Operating Expense"),
                    title="Cost-centre scorecard",
                    why="the numbers behind the treemap, with the plan beside them; full width fits ten departments"))
    note(k, "Reading the cost base.",
         "Operating expense runs above revenue in every entity (116-138% of it), which is why the group makes an "
         "operating loss in the plan as well as the ledger. About a quarter of ledger lines are still marked accrued "
         "in every year, including 2022: accruals are never reversed in this source, so both statuses count as "
         "actuals here.", v)
    return {"name": page_id(k), "displayName": "Cost Centres"}, v, []


def page_scenario():
    k = "scenario"
    v = shell(k, "Scenario & Full-Year Outlook")
    v.append(visual(f"{k}.selector", "advancedSlicerVisual", (CX, SLICER_Y, 380, 68), len(v),
                    query({"Values": [pc(SCEN, "ScenarioName")]}), title="",
                    why="the scenario selector: three stated driver sets"))
    v.append(slicer(f"{k}.sl.entity", ENT, "EntityName", "Entity", (CX + 392, SLICER_Y, 200, SLICER_H), len(v)))
    kpis(k, [("Outlook Revenue", "FY27 outlook revenue", "money"),
             ("Outlook Operating Expense", "FY27 outlook operating expense", "money"),
             ("Outlook Operating Profit", "FY27 outlook operating profit", "money"),
             ("Outlook vs Last FY Operating Profit", "Against FY26", "money"),
             ("Run-Rate Revenue (Monthly)", "Run-rate revenue a month", "money"),
             ("Months Remaining in FY", "Months projected", "count")], v, y=134)
    b = split([40, 32, 34], 218, 232)
    v.append(visual(f"{k}.byscenario", "clusteredBarChart", b[0], len(v),
                    query({"Category": [pc(SCEN, "ScenarioName", "Scenario")],
                           "Y": [pm("Outlook vs Last FY Operating Profit", "Against FY26")]}),
                    objects=one_colour("Outlook vs Last FY Operating Profit", CYAN,
                                       by="Outlook Variance Colour") | DATA_LABELS | WIDE_LABELS,
                    title="Outlook against FY26, by scenario",
                    why="the difference is the story: the absolute outlooks differ by only a few per cent - and each "
                        "bar takes its colour from its own sign, so downside reads red and upside green"))
    v.append(visual(f"{k}.sensitivity", "lineChart", b[1], len(v),
                    query({"Category": [pc(STEP, "StepLabel", "Revenue change")],
                           "Y": [pm("Sensitivity Operating Profit", "Operating profit")]}),
                    objects=colours([("Sensitivity Operating Profit", TEAL)]) | CATEGORICAL_AXIS,
                    title="Profit sensitivity to revenue",
                    why="how far the outlook moves when revenue moves, on top of the selected scenario"))
    v.append(visual(f"{k}.drivers", "tableEx", b[2], len(v),
                    query({"Values": [pc(SCEN, "ScenarioName", "Scenario"),
                                      pc(SCEN, "RevenueChangePct", "Revenue"),
                                      pc(SCEN, "OpexChangePct", "Opex"),
                                      pc(SCEN, "AUDChangePct", "AUD")]}),
                    title="The assumptions, stated",
                    why="drivers are data, not hidden arithmetic - and they are illustrative, not supplied"))
    b = split([60, 46], 462, 196)
    v.append(visual(f"{k}.runrate", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Revenue Actual", "Actual revenue")]}),
                    objects=colours([("Revenue Actual", AMBER)]) | ZERO_BASED,
                    title="The run rate the outlook is built on",
                    why="the projection is the trailing twelve months, which this shows in full"))
    v.append(visual(f"{k}.entity", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(ENT, "EntityShort", "Entity")],
                           "Y": [pm("Outlook Operating Profit", "Outlook operating profit")]}, sort="Outlook Operating Profit"),
                    objects=one_colour("Outlook Operating Profit", PURPLE),
                    title="Outlook by entity",
                    why="the exchange-rate driver applies only to the foreign-currency entities"))
    note(k, "A projection, not a forecast.",
         "Months after 31 Aug 2026 are carried at the trailing-twelve-month average, then flexed by the drivers shown; "
         "the currency driver touches only the five non-AUD entities. The drivers are illustrative assumptions held in "
         "the model - the source's own forecast carries a random label per line.", v)
    return {"name": page_id(k), "displayName": "Scenario"}, v, []


def page_working_capital():
    k = "workingcapital"
    v = shell(k, "Working Capital")
    slicers(k, [(ENT, "EntityName", "Entity")], v)
    kpis(k, [("AR Balance", "Receivables at 31 Aug 2026", "money"),
             ("DSO (Days)", "Days sales outstanding", None),
             ("Days to Collect", "Days to collect a paid invoice", None),
             ("AR Over 365 Days", "More than a year past due", "money"),
             ("AP Balance", "Payables", "money"),
             ("DPO (Days)", "Days payable outstanding", None)], v)
    b = split([34, 34, 38], ROW2_Y, 244)
    v.append(visual(f"{k}.arage", "columnChart", b[0], len(v),
                    query({"Category": [pc(BUCKET, "BucketName", "Age")],
                           "Y": [pm("AR Ageing Amount", "Receivables")]}, sort=(BUCKET, "BucketName"), desc=False),
                    objects=one_colour("AR Ageing Amount", PINK) | CATEGORICAL_AXIS,
                    title="Receivables by age",
                    why="ageing computed as of the balance date, not read from a stored bucket"))
    v.append(visual(f"{k}.apage", "columnChart", b[1], len(v),
                    query({"Category": [pc(BUCKET, "BucketName", "Age")],
                           "Y": [pm("AP Ageing Amount", "Payables")]}, sort=(BUCKET, "BucketName"), desc=False),
                    objects=one_colour("AP Ageing Amount", CYAN) | CATEGORICAL_AXIS,
                    title="Payables by age",
                    why="the same rule on the other side of the balance sheet"))
    v.append(visual(f"{k}.trend", "lineChart", b[2], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("AR Balance", "Receivables"), pm("AP Balance", "Payables")]}),
                    objects=colours([("AR Balance", PINK), ("AP Balance", CYAN)]) | ZERO_BASED,
                    title="Balances at each month end",
                    why="a balance stated on every month end: the uncollected stock only grows"))
    b = split([44, 32, 30], 462, 196)
    v.append(visual(f"{k}.customers", "tableEx", b[0], len(v),
                    query({"Values": [pc(CUST, "CustomerName", "Customer"), pc(CUST, "Country", "Country"),
                                      pm("AR Balance", "Outstanding"), pm("AR Over 365 Days", "Over a year"),
                                      pm("AR Past Due %", "Past due")]}, sort="AR Balance"),
                    filters=[top_n(f"{k}.customers", CUST, "CustomerName", 10)],
                    title="Largest outstanding customer balances",
                    why="who the receivable actually sits with"),)
    v.append(visual(f"{k}.entity", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(ENT, "EntityShort", "Entity")],
                           "Y": [pm("DSO (Days)", "DSO"), pm("DPO (Days)", "DPO")]}),
                    objects=colours([("DSO (Days)", PINK), ("DPO (Days)", CYAN)]),
                    title="Collection and payment days by entity",
                    why="the funding gap between collecting and paying, entity by entity"))
    v.append(visual(f"{k}.donut", "donutChart", b[2], len(v),
                    query({"Category": [pc(ENT, "EntityShort", "Entity")], "Y": [pm("AR Balance", "Receivables")]}),
                    objects=DONUT_PERCENT | LEGEND_BOTTOM,
                    title="Receivables by entity",
                    why="donut: which entity carries the outstanding balance"))
    note(k, "Why DSO is so high.",
         "88% of the receivable is already past due and $23.0M of the $40.2M is more than a year old: in this source "
         "18% of invoiced value is never collected and nothing is ever written off. So days sales outstanding (314) "
         "measures the uncollected stock, while a paid invoice still takes 74 days to collect - read the two together, "
         "and never one as the other.", v)
    return {"name": page_id(k), "displayName": "Working Capital"}, v, []


def page_cash_fx():
    k = "cashfx"
    v = shell(k, "Cash & Currency")
    slicers(k, [(ENT, "EntityName", "Entity")], v)
    kpis(k, [("Cash Balance", "Cash at 31 Aug 2026", "money"),
             ("Minimum Daily Cash", "Lowest daily balance on record", "money"),
             ("Foreign-Currency Revenue Share", "Revenue booked outside AUD", None),
             ("FX Mean Daily Move %", "Average daily move in the rates", None),
             ("Spot vs Average Translation Difference", "Spot vs average translation", "money")], v)
    b = split([56, 50], ROW2_Y, 244)
    v.append(visual(f"{k}.cash", "areaChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Cash Balance", "Closing cash")]}),
                    objects=colours([("Cash Balance", BLUE)]) | ZERO_BASED,
                    title="Group closing cash at each month end",
                    why="a stock, never summed over time; the axis starts at zero"))
    v.append(visual(f"{k}.entities", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Cash Balance", "Cash")],
                           "Rows": [pc(ENT, "EntityShort", "Entity")]}),
                    objects={"smallMultiplesLayout": [{"properties": {"rowCount": lit_l(2), "columnCount": lit_l(3)}}]}
                            | colours([("Cash Balance", BLUE)]),
                    title="Cash by entity",
                    why="small multiples: six entities without six overlapping lines"))
    b = split([38, 40, 28], 462, 196)
    v.append(visual(f"{k}.rates", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Series": [pc(FX, "CurrencyCode", "Currency")],
                           "Y": [pm("Average FX Rate", "AUD per unit")]}),
                    title="Monthly average rates, AUD per unit",
                    why="the rates the ledger was translated at"))
    v.append(visual(f"{k}.growth", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(DATE, "FinancialYear", "Financial year")],
                           "Y": [pm("Revenue YoY %", "Reported"),
                                 pm("Revenue YoY % (Constant Currency)", "Constant currency")]}),
                    objects=colours([("Revenue YoY %", AMBER),
                                     ("Revenue YoY % (Constant Currency)", TEAL)]) | DATA_LABELS,
                    title="Revenue growth: reported and at last year's rates",
                    why="the two bars are all but identical - the exchange rate is not the story here"))
    v.append(visual(f"{k}.pie", "pieChart", b[2], len(v),
                    query({"Category": [pc(ENT, "CurrencyRole", "Currency")], "Y": [pm("Revenue", "Revenue")]}),
                    objects=DONUT_PERCENT | LEGEND_BOTTOM,
                    title="Revenue by currency",
                    why="pie: the model's only genuine two-part split"))
    note(k, "Currency treatment.",
         "Translated at each month's average rate, AUD fixed at 1 (the source's own AUD rate wanders 0.95-1.05); "
         "day-rate translation would move the ledger by 0.005%. 87% of revenue is booked outside AUD, yet the rate "
         "moves growth by under 0.05 pp. FY22 and FY23 show no growth: the ledger starts in 2022.", v)
    return {"name": page_id(k), "displayName": "Cash & FX"}, v, []


def page_method():
    k = "method"
    v = shell(k, "Data & Method")
    kpis(k, [("Budget Lines Without Posting", "Budget lines with no posting", "count"),
             ("Receipts After As-Of", "Receipts dated after the as-of date", "count"),
             ("Payments After As-Of", "Payments dated after the as-of date", "count"),
             ("Cash Floor Days", "Days at the 50,000 cash floor", "count"),
             ("GL Lines", "Ledger lines", "count")], v, y=SLICER_Y + 8)
    b = split([52, 54], 190, 250)
    v.append(visual(f"{k}.dq", "pivotTable", b[0], len(v),
                    query({"Rows": [pc(DQ, "Metric", "Measured property")],
                           "Values": [pm("DQ Metric Value", "Value"), pm("DQ Metric Unit", "Unit")]}),
                    objects=NO_SUBTOTALS,
                    title="Data quality, computed live in SQL",
                    why="fifteen properties measured from dbo on every refresh, so the page cannot drift. A matrix, "
                        "not a table: in a table the text column rendered blank"))
    v.append(textbox(f"{k}.rules", [
        [("The rules every figure obeys", True, T_CYAN)],
        [("As of 31 Aug 2026. ", True), ("The last ledger day. A balance is stated ON a date: an invoice is open if "
                                         "it was issued by then and unpaid then. 769 receipts and 395 payments are "
                                         "dated later - those documents were open.", False)],
        [("One currency. ", True), ("Each entity books in its own; the ledger is translated at each month's average "
                                    "rate, AUD fixed at 1. Spot translation would move the total by 0.005%.", False)],
        [("Plan scope. ", True), ("The budget covers revenue, COGS and operating expense. Interest, FX and tax have "
                                  "actuals and no variance - never a 100% miss.", False)],
        [("Favourable is positive. ", True), ("For a cost that means an underspend; margins vary in percentage points.",
                                              False)],
    ], b[1], len(v), size=9))
    b = split([52, 54], 452, 206)
    v.append(textbox(f"{k}.findings", [
        [("What the data will not support", True, T_ORANGE)],
        [("A partial ledger. ", True), ("Payroll posts in only 68% of department-months and 19,468 budget lines have "
                                        "no posting at all, so actuals sit at about 70% of plan in every month. "
                                        "Reported as measured; never rescaled or filled in.", False)],
        [("Sub-ledgers stand alone. ", True), ("Receivables invoicing is 2.9x ledger revenue, so DSO and DPO use each "
                                               "sub-ledger's own flows, never GL revenue.", False)],
        [("No cash bridge. ", True), ("Daily cash moves about 51,000 a day at random and never ties to the ledger, "
                                      "receipts or payments, so no cash-flow statement is drawn.", False)],
        [("No inventory. ", True), ("The chart has an inventory account with no postings: days inventory outstanding "
                                    "is not reported.", False)],
    ], b[0], len(v), size=9))
    v.append(textbox(f"{k}.scenario", [
        [("Scenarios and security", True, T_PINK)],
        [("The forecast is one version. ", True), ("Its Scenario column is a random label per line - filtering to "
                                                   "'Base' would drop 40% of the plan - so scenarios are modelled "
                                                   "from stated drivers instead.", False)],
        [("The outlook is a projection. ", True), ("Remaining months at the trailing-twelve-month run rate, flexed by "
                                                   "the driver set; illustrative assumptions, not source data.", False)],
        [("Security. ", True), ("Row-level security by entity and department from the signed-in user. A "
                                "department-scoped user sees that cost centre across entities and no receivables, "
                                "payables or cash.", False)],
        [("Synthetic data. ", True), ("A portfolio dataset for the fictional Northstar group - never client data.",
                                      False)],
    ], b[1], len(v), size=9))
    return {"name": page_id(k), "displayName": "Data & Method"}, v, []


PAGES = [page_exec, page_statement, page_variance, page_costs, page_scenario, page_working_capital,
         page_cash_fx, page_method]
# Pages whose subject IS one financial year carry it as a page filter. A slicer
# cannot hold a default selection, and a year slicer beside a page filter would
# empty the page as soon as the two disagreed (Phase 3 finding, D25).
PAGE_FILTERS = {"statement": REPORTING_YEAR, "variance": REPORTING_YEAR, "costs": REPORTING_YEAR}


# -------------------------------------------------------------------- theme ---
def solid(colour):
    return {"solid": {"color": colour}}


PAGE_OBJECTS = {"background": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}],
                "outspace": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}]}

THEME = {
    "name": "Northstar Spectrum",
    "dataColors": DATA_COLOURS,
    "foreground": INK, "foregroundNeutralSecondary": MUTED, "foregroundNeutralTertiary": NEUTRAL,
    "background": PANEL, "backgroundLight": PANEL_ALT, "backgroundNeutral": BORDER,
    "tableAccent": T_BLUE, "good": POSITIVE, "neutral": INDIGO, "bad": NEGATIVE,
    "maximum": PINK, "center": PURPLE, "minimum": "#1E3A8A", "null": NEUTRAL,
    "hyperlink": T_BLUE, "visitedHyperlink": T_PURPLE,
    "textClasses": {
        # Every card names its own colour; this is only what an unstyled one falls back to.
        "callout": {"fontSize": 26, "fontFace": "Consolas", "color": INK},
        "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": MUTED}},
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": solid(PANEL), "transparency": 0}],
            "border": [{"show": True, "color": solid(BORDER), "radius": 8, "width": 1}],
            "title": [{"fontColor": solid(INK), "titleWrap": True}],
            "categoryAxis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED), "gridlineColor": solid(GRID),
                              "gridlineStyle": "dotted", "showAxisTitle": True, "concatenateLabels": False}],
            "valueAxis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED), "gridlineColor": solid(GRID),
                           "gridlineStyle": "dotted", "showAxisTitle": True}],
            "y2Axis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED)}],
            "legend": [{"labelColor": solid(MUTED), "titleColor": solid(INK)}],
            # No theme-wide data-label colour: it overrides Power BI's automatic
            # contrast and puts light labels on light bars (project 2, defect 18).
            "wordWrap": [{"show": True}],
            "outspacePane": [{"backgroundColor": solid(PAGE_BG), "foregroundColor": solid(INK), "transparency": 0,
                              "border": True, "borderColor": solid(BORDER)}],
            "filterCard": [{"$id": "Applied", "transparency": 0, "backgroundColor": solid(PANEL),
                            "foregroundColor": solid(INK), "border": True, "borderColor": solid(BORDER)},
                           {"$id": "Available", "transparency": 0, "backgroundColor": solid(PANEL),
                            "foregroundColor": solid(INK), "border": True, "borderColor": solid(BORDER)}]}},
        "page": {"*": {"background": [{"color": solid(PAGE_BG), "transparency": 0}],
                       "outspace": [{"color": solid(PAGE_BG), "transparency": 0}]}},
        "tableEx": {"*": {
            "columnHeaders": [{"fontColor": solid(HEADER_INK), "backColor": solid(PANEL_ALT), "columnAdjustment": "growToFit"}],
            "values": [{"fontColorPrimary": solid(INK), "backColorPrimary": solid(PANEL),
                        "fontColorSecondary": solid(INK), "backColorSecondary": solid(PANEL_ALT)}],
            "total": [{"fontColor": solid(INK), "backColor": solid(PANEL_ALT)}],
            "grid": [{"gridHorizontalColor": solid(GRID), "gridVerticalColor": solid(GRID), "outlineColor": solid(BORDER)}]}},
        "pivotTable": {"*": {
            "columnHeaders": [{"fontColor": solid(HEADER_INK), "backColor": solid(PANEL_ALT)}],
            "rowHeaders": [{"fontColor": solid(INK), "backColor": solid(PANEL), "showExpandCollapseButtons": True,
                            "legacyStyleDisabled": True}],
            "values": [{"fontColorPrimary": solid(INK), "backColorPrimary": solid(PANEL),
                        "fontColorSecondary": solid(INK), "backColorSecondary": solid(PANEL_ALT)}],
            "subTotals": [{"fontColor": solid(INK), "backColor": solid(PANEL_ALT)}],
            "total": [{"fontColor": solid(INK), "backColor": solid(PANEL_ALT)}],
            "grid": [{"gridHorizontalColor": solid(GRID), "gridVerticalColor": solid(GRID), "outlineColor": solid(BORDER)}]}},
        "slicer": {"*": {"items": [{"fontColor": solid(INK), "background": solid(PANEL_ALT), "padding": 4}],
                         "header": [{"fontColor": solid(MUTED)}]}},
        "advancedSlicerVisual": {"*": {"value": [{"$id": "default", "fontColor": solid(INK)}],
                                       "shapeCustomRectangle": [{"$id": "default", "tileShape": "rectangleRoundedByPixel",
                                                                 "rectangleRoundedCurve": 6}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
        "actionButton": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
    },
}


def themed_report_json(validator):
    path = RP / "definition" / "report.json"
    rj = json.loads(path.read_text(encoding="utf-8-sig"))
    tc = rj["themeCollection"]
    tc["customTheme"] = {"name": THEME_FILE, "reportVersionAtImport": tc["baseTheme"]["reportVersionAtImport"],
                         "type": "RegisteredResources"}
    rj["resourcePackages"] = [p for p in rj.get("resourcePackages", []) if p["name"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources",
         "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]}]
    errors = [e.message for e in validator.iter_errors(rj)]
    return path, rj, errors


# ---------------------------------------------------------------- validation ---
def model_index():
    cols, measures = {}, set()
    for f in (DEF / "tables").glob("*.tmdl"):
        txt = f.read_text(encoding="utf-8")
        t = re.search(r"(?m)^table ('([^']+)'|\S+)", txt)
        tname = t.group(2) or t.group(1)
        cols[tname] = {(m.group(2) or m.group(1)) for m in re.finditer(r"(?m)^\tcolumn ('([^']+)'|\S+)", txt)}
        measures |= {(m.group(2) or m.group(1)) for m in re.finditer(r"(?m)^\tmeasure ('([^']+)'|[^\s=]+)", txt)}
    return cols, measures


def refs(node, out):
    if isinstance(node, dict):
        for k in ("Measure", "Column"):
            if k in node and isinstance(node[k], dict) and "Property" in node[k]:
                src = node[k]["Expression"]["SourceRef"]
                out.append((k, src.get("Entity") or src.get("Source"), node[k]["Property"], "Source" in src))
        for val in node.values():
            refs(val, out)
    elif isinstance(node, list):
        for val in node:
            refs(val, out)


def registry():
    reg = Registry()
    for uri, f in LOCAL_SCHEMAS.items():
        reg = reg.with_resource(uri, Resource.from_contents(json.loads((SCHEMAS / f).read_text(encoding="utf-8")),
                                                            default_specification=DRAFT7))
    return reg


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=[k for _, k in NAV_ITEMS])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    built = [fn() for fn in PAGES]
    cols, measures = model_index()
    reg = registry()
    vval = Draft7Validator(json.loads((SCHEMAS / LOCAL_SCHEMAS[VISUAL_SCHEMA]).read_text(encoding="utf-8")), registry=reg)
    pval = Draft7Validator(json.loads((SCHEMAS / LOCAL_SCHEMAS[PAGE_SCHEMA]).read_text(encoding="utf-8")), registry=reg)
    rval = Draft7Validator(json.loads((SCHEMAS / "report-3.0.0.json").read_text(encoding="utf-8")), registry=reg)
    report_path, report_json, report_errors = themed_report_json(rval)
    errors = len(report_errors)
    for e in report_errors:
        print(f"  REPORT.JSON: {e}")

    pages = []
    for meta, vis, inter in built:
        key = next(k for _, k in NAV_ITEMS if page_id(k) == meta["name"])
        page = {"$schema": PAGE_SCHEMA, **meta, "displayOption": "FitToPage", "height": H, "width": W,
                "objects": PAGE_OBJECTS}
        if PAGE_FILTERS.get(key):
            page["filterConfig"] = {"filters": [categorical_filter(f"page.{key}", DATE, "FinancialYear",
                                                                   [PAGE_FILTERS[key]])]}
        if inter:
            page["visualInteractions"] = inter
        pages.append((page, vis))
        for e in pval.iter_errors(page):
            print(f"  PAGE {meta['displayName']}: {e.message}"); errors += 1
        names = {v["name"] for v in vis}
        if len(names) != len(vis):
            print(f"  DUPLICATE visual names on {meta['displayName']}"); errors += 1
        for v in vis:
            for e in vval.iter_errors(v):
                print(f"  VISUAL {v['visual']['visualType']}: {list(e.path)}: {e.message}"); errors += 1
            p = v["position"]
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > W or p["y"] + p["height"] > H:
                print(f"  OFF-CANVAS {v['visual']['visualType']} {p}"); errors += 1
            rr = []
            refs({k2: v[k2] for k2 in v if k2 != "filterConfig"}, rr)
            for kind, ent, prop, via_source in rr:
                if via_source:
                    print(f"  PROJECTION uses SourceRef.Source (crashes the report load): {prop}"); errors += 1
                elif kind == "Measure" and prop not in measures:
                    print(f"  UNKNOWN MEASURE [{prop}]"); errors += 1
                elif kind == "Column" and prop not in cols.get(ent, set()):
                    print(f"  UNKNOWN COLUMN {ent}[{prop}]"); errors += 1
            for f in v.get("filterConfig", {}).get("filters", []):
                fld = f["field"]["Column"]
                if fld["Property"] not in cols.get(fld["Expression"]["SourceRef"]["Entity"], set()):
                    print(f"  UNKNOWN FILTER COLUMN {fld['Property']}"); errors += 1
        for a, b in itertools.combinations(vis, 2):
            pa, pb = a["position"], b["position"]
            ix = min(pa["x"] + pa["width"], pb["x"] + pb["width"]) - max(pa["x"], pb["x"])
            iy = min(pa["y"] + pa["height"], pb["y"] + pb["height"]) - max(pa["y"], pb["y"])
            if ix > 0 and iy > 0:
                print(f"  OVERLAP on {meta['displayName']}: {a['visual']['visualType']} / {b['visual']['visualType']}"); errors += 1
        tabs = [v["position"].get("tabOrder", 0) for v in vis]
        if len(tabs) != len(set(tabs)):
            print(f"  DUPLICATE tabOrder on {meta['displayName']}"); errors += 1
        # A page note has a 44 px band: two lines of 9 pt text, about 185 characters a line.
        for v in vis:
            if v["visual"]["visualType"] == "textbox" and v["position"]["height"] == NOTE_H:
                chars = sum(len(r["value"]) for p in v["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
                            for r in p["textRuns"])
                if chars * 5.7 > 2 * v["position"]["width"]:
                    print(f"  NOTE TOO LONG on {meta['displayName']}: {chars} characters"); errors += 1

    types = sorted({v["visual"]["visualType"] for _, vis in pages for v in vis})
    print(f"{len(pages)} pages, {sum(len(v) for _, v in pages)} visuals, {len(types)} visual types: {', '.join(types)}")
    print(f"schema / field / geometry / overlap errors: {errors}")
    if errors:
        sys.exit(1)
    if args.check:
        print("--check: nothing written")
        return

    res = RP / "StaticResources" / "RegisteredResources"
    write_json(res / THEME_FILE, THEME)
    for stale in res.glob("*.json"):
        if stale.name != THEME_FILE:
            stale.unlink()
    write_json(report_path, report_json)
    if args.only:
        pages = [p for p in pages if p[0]["name"] == page_id(args.only)]
    if PAGES_DIR.exists():
        shutil.rmtree(PAGES_DIR)
    for page, vis in pages:
        write_json(PAGES_DIR / page["name"] / "page.json", page)
        for v in vis:
            write_json(PAGES_DIR / page["name"] / "visuals" / v["name"] / "visual.json", v)
    order = [p["name"] for p, _ in pages]
    write_json(PAGES_DIR / "pages.json", {"$schema": PAGES_SCHEMA, "pageOrder": order, "activePageName": order[0]})
    if not args.only:
        MANIFEST.write_text(json.dumps(MANIFEST_ROWS, indent=2), encoding="utf-8")
    print(f"written: {', '.join(p['displayName'] for p, _ in pages)}")


if __name__ == "__main__":
    main()
