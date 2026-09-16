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
RP = PBI / "SaaSRevenue.Report"
PAGES_DIR = RP / "definition" / "pages"
DEF = PBI / "SaaSRevenue.SemanticModel" / "definition"
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

# The client's reference design: INK ON PAPER. A light canvas, white cards with a
# hairline edge, a solid crimson rail down the left, and a two-tone crimson-and-pink
# data palette. The hierarchy is carried by one highlighted card rather than by giving
# every card its own colour - which is quieter, and is what the reference does.
# Applied twice: a registered custom theme sets what every visual inherits, and the
# explicit colours here win where a visual carries its own format.
PAGE_BG, PANEL, PANEL_ALT = "#F7E4E8", "#FFFFFF", "#FBF6F7"   # pink ground, white cards
BORDER, GRID = "#E4D6D9", "#EFE6E8"
INK, MUTED, NEUTRAL = "#1C1B1D", "#6E686B", "#948C8F"
HEADER_INK = "#8A5560"                  # table and matrix headers: crimson, muted
# The two tones the whole report is drawn in.
CRIMSON, PINK = "#9E1B32", "#F2A0AC"
CRIMSON_DEEP, CRIMSON_MID, ROSE = "#6E1023", "#C13B52", "#E0788C"
PINK_PALE, PINK_WASH = "#F8CDD4", "#FCEBEE"
RAIL = "#A4132C"                        # the rail, and the one solid block of colour
# Supporting hues, used ONLY where a chart genuinely has more categories than a two-tone
# palette can separate - a six-slice pie, a seven-channel treemap. Muted on purpose, so
# a categorical chart never out-shouts the crimson the page is built on.
PLUM, TERRACOTTA, SLATE = "#7B3F61", "#C4714C", "#5C6B84"
OLIVE, TEAL, MAUVE = "#7A7C4B", "#3F7C77", "#A8788F"
# A page's signature tone: the fill of its ONE hero card. Every one is light, because a
# filled card has to carry a dark figure on top of it - a crimson fill buries its own
# number, which is the first thing the render showed.
SPECTRUM = ["#F2A0AC", "#F7C59F", "#E0B0C8", "#F3B3A7", "#CDB4DB", "#F5D5A0", "#F0A8B8", "#BFD0D8"]
ACCENT = "#F2A0AC"
DATA_COLOURS = ["#9E1B32", "#F2A0AC", "#C13B52", "#7B3F61", "#E0788C", "#C4714C",
                "#5C6B84", "#3F7C77", "#A8788F", "#7A7C4B"]
THEME_FILE = "NorthstarCrimson.json"

SB_PAD, SB_BTN_H, SB_GAP, SB_TOP, SB_FONT = 10, 36, 4, 60, 9
SB_BTN_W = NAV_W - 2 * SB_PAD
# The rail is one solid crimson column and the buttons sit ON it: the selected page is a
# white block with crimson text, the rest are transparent with a hairline outline. No
# filled slate rectangles, which is what every previous project in this series used.
SB_LINE = "#C4667A"                     # hairline on the crimson rail
SB_FG_DEFAULT, SB_FG_SELECTED = "#FFFFFF", RAIL
NAV_ITEMS = [("Executive", "exec"), ("Revenue Movement", "movement"),
             ("Retention & Cohorts", "retention"), ("Churn Drivers", "drivers"),
             ("Customer Base", "customers"), ("Unit Economics", "economics"),
             ("Product & Support", "product"), ("Data & Method", "method")]
PAGE_ACCENT = {key: SPECTRUM[i % len(SPECTRUM)] for i, (_, key) in enumerate(NAV_ITEMS)}

DATE, CUST, PLAN, SEV = "DimDate", "DimCustomer", "DimPlan", "DimSeverity"
MOVE, BAND, COHORT, TENURE = "DimMovementType", "DimTenureBand", "DimCohort", "DimTenureMonth"
SUB, SUBM, MOV = "FactSubscription", "FactSubscriptionMonth", "FactMRRMovement"
INV, USE, TICK, ACQ = "FactInvoice", "FactUsageMonthly", "FactSupportTicket", "FactAcquisition"
DRIVER, DQ = "ChurnDriverStrength", "DataQualityMetric"
# The calculation group and the field parameter are tables too, and a slicer over
# either of them is how the reader changes the question instead of the page.
TIMEGRP, CUT = "Time Comparison", "Customer Cut"
ASOF_MONTH = (2026, 8)           # the month the data ends: used to build a trailing window
MANIFEST_ROWS = []
# The rail backdrop is the one visual that is SUPPOSED to sit under others, so the
# overlap check has to know about it by name rather than guess from geometry.
BACKDROPS = set()


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
    """`accent` mixed into `base`. Used for the hero card's edge, and for the retention
    matrix's ramp, so a tint is always derived rather than eyeballed."""
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    a = [int(accent[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(b[i] + (a[i] - b[i]) * weight):02X}" for i in range(3))


def container(panel, accent=None):
    if not panel:
        return {"background": [{"properties": {"show": lit_b(False)}}],
                "border": [{"properties": {"show": lit_b(False)}}]}
    # A plain panel is white with a hairline edge. A HERO panel is filled with its
    # accent outright - on paper a 13% tint disappears, where on charcoal it read.
    fill = PANEL if accent is None else accent
    edge = BORDER if accent is None else blend(accent, INK, 0.12)
    return {"background": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(fill)}},
                                           "transparency": lit_n(0)}}],
            "border": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(edge)}},
                                       "radius": lit_n(8)}}]}


def visual(seed, vtype, box, tab, q=None, objects=None, title=None, filters=None, why="", title_size=10,
           panel=None, accent=None, z=1):
    x, y, w, h = box
    # Everything sits at z = 1 except the rail backdrop, which is 0. Equal z would leave
    # the stacking order to the folder listing, which is a hash - so the one visual that
    # has to be underneath says so explicitly.
    position = {"x": x, "y": y, "z": z, "height": h, "width": w}   # Power BI's own key order
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


def recent_months(seed, n):
    """Trim a chart to the last `n` months of data. Built from the as-of month rather
    than from "today", so the window is the same whenever the report is opened - and
    stated as month labels, which a categorical filter can hold."""
    y, mth = ASOF_MONTH
    labels = []
    for i in range(n):
        yy, mm = divmod((y * 12 + mth - 1) - i, 12)
        labels.append(f"{MONTHS[mm]} {yy}")
    return categorical_filter(seed + ".recent", DATE, "YearMonthLabel", list(reversed(labels)))


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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
         filters=None, hero=None):
    """A headline figure: a crimson number on a white card. The FIRST card in a row is
    the hero - filled in its page's tone, with the figure written in ink on top of it -
    so a row of cards has one thing the eye lands on rather than six competing hues."""
    labels = {"fontSize": lit_n(size), "color": {"solid": {"color": lit_s(colour)}}}
    if font:
        labels["fontFamily"] = lit_s(font)
    if kind == "money":
        labels |= {"labelDisplayUnits": lit_n(0), "labelPrecision": lit_l(2)}
    elif kind == "count":
        labels |= {"labelDisplayUnits": lit_n(1)}
    objects = {"labels": [{"properties": labels}], "categoryLabels": [{"properties": {"show": lit_b(False)}}]}
    return visual(seed, "card", box, tab, query({"Values": [pm(measure)]}), objects, title=label, title_size=9,
                  why=f"Headline figure: {measure}", panel=panel, filters=filters, accent=hero)


def slicer(seed, table, column, label, box, tab):
    objects = {"data": [{"properties": {"mode": lit_s("Dropdown")}}],
               # No fontSize: Power BI strips it from a slicer header, so it never applied.
               # The header takes the theme's label class instead.
               "header": [{"properties": {"show": lit_b(True), "text": lit_s(label),
                                          "fontColor": {"solid": {"color": lit_s(MUTED)}}}}]}
    return visual(seed, "slicer", box, tab, query({"Values": [pc(table, column)]}), objects, title="",
                  why=f"Filter by {label}")


def nav_button(seed, label, target, selected, y, tab, accent=ACCENT):
    """Text on the crimson rail. The page you are on is a solid white block with crimson
    text; every other page is the rail itself, outlined with a hairline. The previous
    projects in this series all used filled slate rectangles on a dark rail, so this is
    deliberately the other way round."""
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(not selected)}},
                    {"properties": {"lineColor": {"solid": {"color": lit_s(SB_LINE)}},
                                    "weight": lit_n(1)}, "selector": {"id": "default"}}],
        "fill": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"fillColor": {"solid": {"color": lit_s("#FFFFFF" if selected else RAIL)}},
                                 "transparency": lit_n(0 if selected else 100)},
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
    # The rail is a real block of colour, not a column of buttons on the page background,
    # so it needs something behind it. A chromeless textbox given a background is the
    # cheapest honest way to draw a rectangle in PBIR, and z = 0 keeps it underneath.
    BACKDROPS.add(sid(f"{key}.rail.bg"))
    v = [visual(f"{key}.rail.bg", "textbox", (0, 0, NAV_W, H), 0,
                objects={"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": ""}]}]}}]},
                panel=True, accent=RAIL, title=None, z=0, why="The navigation rail")]
    v.append(textbox(f"{key}.rail.hdr", [[("NORTHSTAR", True, "#FFFFFF")], [("SAAS REVOPS", True, PINK)]],
                     (SB_PAD, 10, SB_BTN_W, 44), len(v), size=10))
    for i, (label, target) in enumerate(NAV_ITEMS):
        v.append(nav_button(f"{key}.nav.{target}", label, page_id(target), target == key,
                            SB_TOP + i * (SB_BTN_H + SB_GAP), len(v), accent=accent))
    v.append(textbox(f"{key}.rail.ftr", ["Synthetic portfolio dataset", "- not client data"],
                     (SB_PAD, 668, SB_BTN_W, 40), len(v), size=8, colour=PINK_PALE))
    v.append(textbox(f"{key}.title", [[(title, True, CRIMSON_DEEP)]], (CX, HEADER_Y, 520, HEADER_H), len(v),
                     size=16))
    v.append(card(f"{key}.context", "Report Context", "", (W - MARGIN - 540, HEADER_Y, 540, HEADER_H), len(v),
                  size=9, colour=MUTED, font="Segoe UI", panel=False))
    return v


def kpis(key, items, v, y=KPI_Y, height=KPI_H, filters=None):
    """items: (measure, label, kind). The FIRST card is the hero - filled in the page's
    own tone with its figure in ink - and the rest are white with a crimson figure. One
    thing to land on, then the supporting numbers."""
    accent = PAGE_ACCENT[key]
    for i, ((measure, label, kind), box) in enumerate(zip(items, split(len(items), y, height))):
        v.append(card(f"{key}.kpi.{measure}", measure, label, box, len(v), kind=kind, filters=filters,
                      colour=CRIMSON_DEEP if i == 0 else CRIMSON, hero=accent if i == 0 else None))


def note(key, lead, text, v):
    v.append(textbox(f"{key}.note", [[(lead + "  ", True), (text, False)]], (CX, NOTE_Y, CW, NOTE_H), len(v),
                     size=9, colour=MUTED))


def slicers(key, specs, v):
    for i, (table, column, label) in enumerate(specs):
        v.append(slicer(f"{key}.sl.{column}", table, column, label, (CX + i * 212, SLICER_Y, 200, SLICER_H), len(v)))


# ------------------------------------------------------------------- pages ---
def page_exec():
    """What a board asks first: how big, how fast, how much of it stays. Every card is
    anchored to the as-of date and names its own window, so the page means the same
    thing however it is opened."""
    k = "exec"
    v = shell(k, "Executive Summary")
    slicers(k, [(CUST, "Country", "Country"), (CUST, "Segment", "Segment")], v)
    kpis(k, [("ARR", "ARR at 31 Aug 2026", "money"),
             ("MRR", "MRR at 31 Aug 2026", "money"),
             ("Customers", "Paying customers", "count"),
             ("ARPA", "Average revenue per account", None),
             ("Annualised Logo Churn %", "Logo churn, trailing 12 months", None),
             ("Trailing 12m Revenue Retention %", "Revenue retention, 12 months", None)], v)
    b = split([62, 44], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.trend", "areaChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("MRR", "MRR")]}),
                    objects=one_colour("MRR", CRIMSON) | ZERO_BASED,
                    title="MRR at each month end, since January 2022",
                    why="a stock read at each month end, never summed; the axis starts at zero because the "
                        "question is how big, not how noisy"))
    v.append(visual(f"{k}.segment", "donutChart", b[1], len(v),
                    query({"Category": [pc(CUST, "Segment", "Segment")], "Y": [pm("MRR", "MRR")]}),
                    objects=DONUT_PERCENT | LEGEND_BOTTOM,
                    title="MRR by customer segment",
                    why="donut: three shares of one whole, at the as-of date"))
    b = split([36, 36, 34], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.plan", "columnChart", b[0], len(v),
                    query({"Category": [pc(DATE, "Year", "Year")], "Series": [pc(PLAN, "PlanName", "Plan")],
                           "Y": [pm("Customers", "Customers")]}),
                    title="Customers by plan, at each year end",
                    why="stacked column: the plan mix barely moves, which is itself the finding"))
    v.append(visual(f"{k}.flow", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("New Customers", "Arrived"), pm("Churned Customers", "Left")]}),
                    objects=colours([("New Customers", ROSE), ("Churned Customers", CRIMSON)]),
                    title="Customers arriving and leaving each month",
                    why="the two flows behind the stock; arrivals stop in June 2026 where the extract ends"))
    v.append(visual(f"{k}.margins", "multiRowCard", b[2], len(v),
                    query({"Values": [pm("Gross Revenue Retention % (Latest Month)", "Gross revenue"),
                                      pm("Net Revenue Retention % (Latest Month)", "Net revenue"),
                                      pm("Logo Retention % (Latest Month)", "Logo")]}),
                    accent=PINK_WASH,
                    title="", why="multiRowCard: the three retention figures in one panel, at a height that fits"))
    note(k, "How to read this.",
         "Cards are anchored to the as-of date, 31 Aug 2026. Net and gross revenue retention are IDENTICAL here "
         "because this source has no expansion or contraction - see Revenue Movement. The last two months show "
         "customers leaving and none arriving: the newest subscription in the file starts 30 Jun 2026, so that is "
         "where the data stops, not where the business did.", v)
    return {"name": page_id(k), "displayName": "Executive Summary"}, v, []


def page_movement():
    """The waterfall, and the honest account of what this data can and cannot put in it."""
    k = "movement"
    v = shell(k, "Revenue Movement")
    slicers(k, [(CUST, "Country", "Country"), (TIMEGRP, "Comparison", "Time comparison")], v)
    kpis(k, [("Opening MRR", "MRR at 31 Aug 2025", "money"),
             ("New MRR", "Won in 12 months", "money"),
             ("Churned MRR", "Lost in 12 months", "money"),
             ("Net MRR Movement", "Net change", "money"),
             ("MRR", "MRR at 31 Aug 2026", "money")], v)
    b = split([46, 60], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.waterfall", "waterfallChart", b[0], len(v),
                    query({"Category": [pc(MOVE, "MovementType", "Movement")],
                           "Y": [pm("MRR Movement (All Components)", "Change in MRR")]}),
                    title="Where MRR moved, 12 months to Aug 2026",
                    why="waterfall: the five components of a SaaS book. Three of them are empty here and the "
                        "page says why rather than dropping them"))
    v.append(visual(f"{k}.bymonth", "lineClusteredColumnComboChart", b[1], len(v),
                    query({"Category": [pc(DATE, "YearMonthLabel", "Month")],
                           "Y": [pm("New MRR", "Won"), pm("Churned MRR", "Lost")],
                           "Y2": [pm("MRR", "MRR")]}),
                    objects=colours([("New MRR", ROSE), ("Churned MRR", CRIMSON),
                                     ("MRR", SLATE)]) | CATEGORICAL_AXIS,
                    filters=[recent_months(f"{k}.bymonth", 18)],
                    title="Won and lost each month, with MRR on the right",
                    why="combo: the flows as columns and the stock as a line, because they are different kinds of "
                        "number and must not share an axis"))
    b = split([68, 38], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.detail", "tableEx", b[0], len(v),
                    query({"Values": [pc(MOVE, "MovementType", "Movement"),
                                      pc(MOVE, "SupportLabel", "In this data"),
                                      pm("MRR Movement", "MRR"),
                                      pm("Movement Supported", "Why not")]}),
                    title="The five movements, and which of them this source can show",
                    why="the empty components explained in the same table that reports them"))
    v.append(visual(f"{k}.churnmix", "clusteredBarChart", b[1], len(v),
                    query({"Category": [pc(PLAN, "PlanName", "Plan")],
                           "Y": [pm("Churned MRR", "MRR lost")]}, sort="Churned MRR", desc=False),
                    objects=one_colour("Churned MRR", CRIMSON) | DATA_LABELS | WIDE_LABELS,
                    title="MRR lost by plan",
                    why="where the churn actually costs: Starter churns most often, Enterprise costs most per loss"))
    note(k, "Why three bars are empty.",
         "MRR is one static value per subscription, so nobody can grow or shrink: expansion and contraction cannot "
         "occur. Every customer has exactly one subscription ever, so reactivation cannot either. All five "
         "components are computed and checked; three are structurally nil, and that is the source, not the model.", v)
    return {"name": page_id(k), "displayName": "Revenue Movement"}, v, []


def page_retention():
    """Cohorts, which is the only way to see retention without survivorship bias."""
    k = "retention"
    v = shell(k, "Retention & Cohorts")
    slicers(k, [(CUST, "Country", "Country"), (PLAN, "PlanName", "Plan")], v)
    kpis(k, [("Logo Retention % (Latest Month)", "Logo retention, Aug 2026", None),
             ("Gross Revenue Retention % (Latest Month)", "Gross revenue retention, Aug 2026", None),
             ("Net Revenue Retention % (Latest Month)", "Net revenue retention, Aug 2026", None),
             ("NRR less GRR (Latest Month, pp)", "Expansion contribution (pp)", None),
             ("Median Tenure (Months)", "Median tenure, months", None)], v)
    v.append(visual(f"{k}.matrix", "pivotTable", (CX, ROW2_Y, CW, ROW2_H), len(v),
                    query({"Rows": [pc(COHORT, "CohortLabel", "Signed up")],
                           "Columns": [pc(TENURE, "TenureLabel", "Month of life")],
                           "Values": [pm("Cohort Retention %", "Retained")]}),
                    objects=NO_SUBTOTALS | {"values": field_colour("Retention Colour", "Cohort Retention %")},
                    filters=[categorical_filter(f"{k}.matrix.c", COHORT, "CohortLabel",
                                                [f"{m} 2025" for m in
                                                 ["Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                                  "Sep", "Oct", "Nov", "Dec"]]),
                             categorical_filter(f"{k}.matrix.t", TENURE, "TenureLabel",
                                                [f"M{i}" for i in range(13)])],
                    title="Cohort retention: ten 2025 cohorts, their first twelve months",
                    why="the matrix is a triangle because a cohort cannot have a month it has not lived yet - "
                        "blank, never 0%"))
    b = split([28, 24, 24, 24], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.curve", "lineChart", b[0], len(v),
                    query({"Category": [pc(TENURE, "TenureMonth", "Month of life")],
                           "Y": [pm("Cohort Retention %", "Retained")]}),
                    # A CONTINUOUS axis here, not categorical: thirteen tenure months in a
                    # quarter-row scrolled, and a survival curve is a curve over a number
                    # anyway - the months-since-signup is a quantity, not a label.
                    objects=one_colour("Cohort Retention %", CRIMSON),
                    filters=[categorical_filter(f"{k}.curve.t", TENURE, "TenureLabel",
                                                [f"M{i}" for i in range(13)])],
                    title="The survival curve, all cohorts",
                    why="the matrix collapsed to one line: how retention decays with age rather than with date"))
    v.append(visual(f"{k}.sizes", "columnChart", b[2], len(v),
                    query({"Category": [pc(DATE, "Year", "Year")],
                           "Y": [pm("New Customers", "Customers")]}),
                    objects=one_colour("New Customers", ROSE) | DATA_LABELS,
                    title="Customers acquired by year",
                    why="a retention rate means little without the size behind it; by year because eighteen month "
                        "labels do not fit a quarter of a row"))
    v.append(visual(f"{k}.band", "clusteredBarChart", b[1], len(v),
                    query({"Category": [pc(BAND, "TenureBand", "Tenure")],
                           "Y": [pm("Customers Ever Churned", "Churned")]}),
                    objects=one_colour("Customers Ever Churned", CRIMSON) | DATA_LABELS | WIDE_LABELS,
                    title="Where customers are lost, by tenure",
                    why="churn concentrates in the first year and a half, which is where onboarding pays"))
    v.append(visual(f"{k}.churntrend", "lineChart", b[3], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Logo Churn %", "Logo"), pm("Revenue Churn %", "Revenue")]}),
                    objects=colours([("Logo Churn %", CRIMSON), ("Revenue Churn %", ROSE)]),
                    title="Monthly churn: logo against revenue",
                    why="revenue churn runs BELOW logo churn: the customers leaving are the small ones"))
    note(k, "Reading the matrix.",
         "Each row is a signup month, each column a month of life, so a diagonal is a calendar date. Blank means the "
         "cohort has not lived that long yet: the triangle is honest, not missing. Revenue retention tracks logo "
         "retention exactly, because MRR never changes inside a subscription.", v)
    return {"name": page_id(k), "displayName": "Retention & Cohorts"}, v, []


def page_drivers():
    """The page the brief did not ask for, and the one the data supports."""
    k = "drivers"
    v = shell(k, "Churn Drivers")
    slicers(k, [(CUST, "Country", "Country")], v)
    # The field parameter's own slicer, up beside the country slicer where it is wide
    # enough to show "Acquisition channel" without truncating it.
    # A DROPDOWN, not a button slicer: six values - one of them "Acquisition channel" -
    # wrapped into two rows of a 68 px band and rendered with no labels at all.
    # No default is set: a filter on a slicer restricts the slicer's own items rather
    # than pre-selecting one, which would trap the reader on a single cut.
    v.append(slicer(f"{k}.cutslicer", CUT, "Customer Cut", "Cut the base by",
                    (CX + 212, SLICER_Y, 260, SLICER_H), len(v)))
    kpis(k, [("Ever-Churn Rate", "Customers ever churned", None),
             ("Customers Ever Churned", "Customers lost, all time", "count"),
             ("Tickets per Customer per Month", "Support contacts per month", None),
             ("Payment Failure Rate", "Invoices that failed", None),
             ("Median Tenure (Months)", "Median tenure, months", None)], v)
    # Eleven drivers do not fit a 244 px row - a bar chart of that height holds about
    # seven - so the evidence chart takes a full-height column of its own and the rest
    # of the page stacks beside it.
    LEFT_W = 463
    RIGHT_X, RIGHT_W = CX + LEFT_W + GAP, CW - LEFT_W - GAP
    v.append(visual(f"{k}.corr", "clusteredBarChart", (CX, ROW2_Y, LEFT_W, 452), len(v),
                    query({"Category": [pc(DRIVER, "Driver", "Candidate driver")],
                           "Y": [pm("Driver Correlation", "Correlation with churning")]},
                          sort="Driver Correlation"),
                    objects=one_colour("Driver Correlation", CRIMSON,
                                       by="Driver Bar Colour") | DATA_LABELS | WIDE_LABELS,
                    title="What actually predicts churn, measured",
                    why="computed in SQL on every refresh, not asserted. A bar drawn in the panel colour is inside "
                        "|r| < 0.05 - which is to say, not a driver at all"))
    v.append(visual(f"{k}.table", "pivotTable", (RIGHT_X, ROW2_Y, RIGHT_W, 244), len(v),
                    query({"Rows": [pc(DRIVER, "Driver", "Candidate driver")],
                           "Values": [pm("Driver Group", "Group"), pm("Driver Correlation", "r"),
                                      pm("Driver Strength", "Verdict"), pm("Driver Customers", "Measured over")]}),
                    objects=NO_SUBTOTALS,
                    title="The same evidence, with its verdict in words",
                    why="a matrix, not a table: a table totals its columns, and there is no such thing as the sum of "
                        "eleven correlations. A decimal invites interpretation, so the verdict states the conclusion"))
    half = (RIGHT_W - GAP) // 2
    v.append(visual(f"{k}.plan", "clusteredColumnChart", (RIGHT_X, ROW3_Y, half, ROW3_H), len(v),
                    query({"Category": [pc(PLAN, "PlanName", "Plan")],
                           "Y": [pm("Churn Rate by Group", "Ever churned")]}),
                    objects=one_colour("Churn Rate by Group", CRIMSON) | DATA_LABELS,
                    title="Churn by price point - the one real driver",
                    why="Starter churns at more than three times Enterprise, and the gradient holds inside every "
                        "segment, so it is the price point and not the kind of company"))
    v.append(visual(f"{k}.cut", "clusteredColumnChart",
                    (RIGHT_X + half + GAP, ROW3_Y, RIGHT_W - half - GAP, ROW3_H), len(v),
                    query({"Category": [pc(CUT, "Customer Cut", "Cut by")],
                           "Y": [pm("Churn Rate by Group", "Ever churned")]}),
                    objects=one_colour("Churn Rate by Group", PLUM) | DATA_LABELS,
                    title="Ever-churn rate - pick a cut above to re-group",
                    why="driven by the field parameter. With nothing picked it shows the base rate against each cut "
                        "on offer, which is true and obviously waiting for input; pick one and it re-groups. Every "
                        "cut except plan lands within a couple of points of the base rate"))
    note(k, "What was tested, and what was found.",
         "Adoption, logins, seats, utilisation and errors are all independent of churn here - every correlation "
         "inside 0.02, and identical averages for customers who left and stayed. A model on those features would fit "
         "noise, so none is built. Two things carry signal: price point, and support contacts per month of tenure.", v)
    return {"name": page_id(k), "displayName": "Churn Drivers"}, v, []


def page_customers():
    """From the aggregate to the account: who, and on what terms."""
    k = "customers"
    v = shell(k, "Customer Base")
    slicers(k, [(CUST, "Country", "Country"), (CUST, "Industry", "Industry")], v)
    # A button slicer, not a dropdown: two short values read better as buttons, and it
    # is the one place on this report where they fit the band without wrapping.
    v.append(visual(f"{k}.status", "advancedSlicerVisual", (CX + 424, SLICER_Y, 260, SLICER_H), len(v),
                    query({"Values": [pc(CUST, "SubscriptionStatus")]}), title="",
                    why="Active or Churned, as buttons"))
    kpis(k, [("Customers", "Paying customers", "count"),
             ("Customers Ever Acquired", "Ever acquired", "count"),
             ("Churned Customers", "Left, all months", "count"),
             ("Median Tenure (Months)", "Median tenure, months", None),
             ("Realised Price vs List %", "Realised price against list", None)], v)
    b = split([46, 60], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.tree", "decompositionTreeVisual", b[0], len(v),
                    query({"Analyze": [pm("MRR", "MRR")],
                           "ExplainBy": [pc(CUST, "Country", "Country"), pc(CUST, "Segment", "Segment"),
                                         pc(PLAN, "PlanName", "Plan"), pc(CUST, "Industry", "Industry"),
                                         pc(CUST, "BillingCycle", "Billing cycle")]}),
                    objects={"tree": [{"properties": {"effectiveBarsPerLevel": lit_l(4)}}]},
                    title="Where the MRR sits - choose the path",
                    why="decomposition tree: five attributes in any order the reader wants"))
    v.append(visual(f"{k}.scatter", "scatterChart", b[1], len(v),
                    query({"Category": [pc(PLAN, "PlanName", "Plan")],
                           "Series": [pc(CUST, "Segment", "Segment")],
                           "X": [pm("Median Tenure (Months)", "Median tenure")],
                           "Y": [pm("ARPA", "ARPA")],
                           "Size": [pm("Customers", "Customers")]}),
                    objects=LEGEND_BOTTOM,
                    title="Price against tenure, by plan and segment",
                    why="the higher the price point the longer they stay - the same finding as the drivers page, "
                        "drawn rather than tabulated"))
    v.append(visual(f"{k}.table", "tableEx", (CX, ROW3_Y, CW, ROW3_H), len(v),
                    query({"Values": [pc(CUST, "CustomerName", "Customer"), pc(CUST, "Country", "Country"),
                                      pc(CUST, "Segment", "Segment"), pc(PLAN, "PlanName", "Plan"),
                                      pm("MRR", "MRR"), pm("Median Tenure (Months)", "Tenure (months)"),
                                      pm("Tickets", "Tickets"), pm("Failed Invoices", "Failed invoices")]},
                          sort="MRR"),
                    filters=[top_n(f"{k}.table", CUST, "CustomerName", 15)],
                    title="Top 15 customers by MRR",
                    why="the account detail behind every aggregate on the report"))
    note(k, "One subscription each.",
         "Every customer in this source has exactly one subscription, for life, at one price - which is why the "
         "customer base and the subscription base are the same list, and why nobody in it has ever upgraded, "
         "downgraded or come back. Tenure is completed months to the end date, or to 31 Aug 2026 for a customer "
         "still running.", v)
    return {"name": page_id(k), "displayName": "Customer Base"}, v, []


def page_economics():
    """What a customer costs and what they are worth - and which half of that is modelled."""
    k = "economics"
    v = shell(k, "Unit Economics")
    slicers(k, [(CUST, "Country", "Country"), (CUST, "AcquisitionSource", "Channel")], v)
    kpis(k, [("CAC (Blended)", "Blended CAC", None),
             ("CAC (Median)", "Median CAC", None),
             ("ARPA", "ARPA", None),
             ("Gross Profit per Account", "Gross profit per account", None),
             ("CAC Payback (Months)", "CAC payback, months", None),
             ("LTV to CAC", "LTV to CAC", None)], v)
    b = split([40, 34, 32], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.channel", "clusteredBarChart", b[0], len(v),
                    query({"Category": [pc(CUST, "AcquisitionSource", "Channel")],
                           "Y": [pm("CAC (Blended)", "Blended CAC")]}, sort="CAC (Blended)"),
                    objects=one_colour("CAC (Blended)", CRIMSON) | DATA_LABELS | WIDE_LABELS,
                    title="Acquisition cost by channel",
                    why="flat: about $120 between the dearest and cheapest channel on a $2,017 base, so channel "
                        "choice is not a cost lever here"))
    v.append(visual(f"{k}.payback", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(PLAN, "PlanName", "Plan")],
                           "Y": [pm("CAC Payback (Months)", "Months to repay")]}),
                    objects=one_colour("CAC Payback (Months)", TERRACOTTA) | DATA_LABELS,
                    title="Months to repay acquisition, by plan",
                    why="the same cost against very different revenue: a Starter customer takes far longer to "
                        "repay than an Enterprise one"))
    v.append(visual(f"{k}.gauge", "gauge", b[2], len(v),
                    query({"Y": [pm("LTV to CAC", "LTV to CAC")]}),
                    title="LTV to CAC", title_size=9,
                    why="a gauge against the conventional 3x benchmark - and the number depends entirely on the "
                        "two assumptions stated below it"))
    b = split([46, 60], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.spend", "treemap", b[0], len(v),
                    query({"Group": [pc(CUST, "AcquisitionSource", "Channel")],
                           "Details": [pc(CUST, "Segment", "Segment")],
                           "Values": [pm("Acquisition Spend", "Spend")]}),
                    title="Where the acquisition money went",
                    why="treemap: seven channels and three segments in one view"))
    v.append(textbox(f"{k}.assume", [
        [("Two of these numbers are modelled, not measured", True, CRIMSON)],
        [("Gross margin is an assumption. ", True),
         ("The source carries no cost of service at all, so gross profit per account, CAC payback and lifetime "
          "value cannot be derived from it. The 75% held in ModelConfig is a stated placeholder; change it there and "
          "every figure here moves.", False)],
        [("Lifetime value assumes a constant churn rate. ", True),
         ("LTV is gross profit per account divided by the trailing-twelve-month monthly churn rate. That treats "
          "churn as if it never changed with tenure - and the cohort curve on the Retention page shows it does. "
          "Read LTV as a planning number, not a measurement.", False)],
        [("What IS measured: ", True),
         ("acquisition cost per customer, ARPA, and the churn rate itself. Blended CAC leads because it is what the "
          "money actually was; the median sits beside it because the distribution is skewed about 1.7 to 1.", False)],
    ], b[1], len(v), size=9))
    note(k, "Cost has no campaign and no date.",
         "Acquisition cost is attached to the customer, not to a campaign or a month, so it can be cut by anything "
         "about the customer and by their signup month - but a marketing-efficiency trend would be invention. "
         "384 customers were acquired for under $100 and the cheapest for 33 cents, which is why the median is "
         "published beside the blended figure.", v)
    return {"name": page_id(k), "displayName": "Unit Economics"}, v, []


def page_product():
    """Adoption and support - the two things everyone assumes drive churn, measured."""
    k = "product"
    v = shell(k, "Product & Support")
    slicers(k, [(CUST, "Segment", "Segment"), (SEV, "SeverityName", "Severity")], v)
    kpis(k, [("Usage Coverage %", "Customers we can see", None),
             ("Seat Utilisation %", "Active users per licensed seat", None),
             ("Feature Adoption %", "Feature adoption", None),
             ("Tickets per Customer per Month", "Tickets per customer month", None),
             ("Mean Time To Resolve (Hours)", "Hours to resolve", None),
             ("Unresolved Share", "Still open or escalated", None)], v)
    b = split([56, 50], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.usage", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Seat Utilisation %", "Seat utilisation"),
                                 pm("Feature Adoption %", "Feature adoption")]}),
                    objects=colours([("Seat Utilisation %", CRIMSON), ("Feature Adoption %", TEAL)]) | ZERO_BASED,
                    title="Adoption and utilisation over time, for the customers we can see",
                    why="both flat for four years - and neither has any relationship with churn"))
    v.append(visual(f"{k}.small", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Usage Coverage %", "Coverage")],
                           "Rows": [pc(CUST, "Segment", "Segment")]}),
                    objects={"smallMultiplesLayout": [{"properties": {"rowCount": lit_l(1), "columnCount": lit_l(3)}}]}
                            | one_colour("Usage Coverage %", PLUM),
                    title="Usage coverage by segment",
                    why="small multiples: the sample is about the same size in every segment, so the gap is not a "
                        "segment effect"))
    b = split([38, 34, 34], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.sev", "hundredPercentStackedColumnChart", b[0], len(v),
                    query({"Category": [pc(DATE, "Year", "Year")],
                           "Series": [pc(SEV, "SeverityName", "Severity")],
                           "Y": [pm("Tickets", "Tickets")]}),
                    title="Ticket severity mix by year",
                    why="composition, not volume: the mix is the same every year"))
    v.append(visual(f"{k}.cat", "pieChart", b[1], len(v),
                    query({"Category": [pc(TICK, "Category", "Category")], "Y": [pm("Tickets", "Tickets")]}),
                    objects=DONUT_PERCENT | LEGEND_BOTTOM,
                    title="What tickets are about",
                    why="pie: six near-equal slices, which is the point - nothing dominates"))
    v.append(visual(f"{k}.rate", "clusteredColumnChart", b[2], len(v),
                    query({"Category": [pc(PLAN, "PlanName", "Plan")],
                           "Y": [pm("Tickets per Customer per Month", "Per customer month")]}),
                    objects=one_colour("Tickets per Customer per Month", TERRACOTTA) | DATA_LABELS,
                    title="Support contact rate by plan",
                    why="a rate, not a count: a raw ticket count would just rank plans by how long their customers "
                        "have been around"))
    note(k, "A sample, not a census.",
         "Usage covers about 40% of paying customers in any month: a customer appears in a median of nine months "
         "against a median tenure of twenty-nine. Adoption figures are 'of the customers we can see', never a "
         "denominator for revenue. Mean time to resolve counts resolved tickets only.", v)
    return {"name": page_id(k), "displayName": "Product & Support"}, v, []


def page_method():
    k = "method"
    v = shell(k, "Data & Method")
    kpis(k, [("Customers Ever Acquired", "Customers in the file", "count"),
             ("Invoices", "Invoices", "count"),
             ("Tickets", "Support tickets", "count"),
             ("Failed Invoices", "Failed invoices", "count"),
             ("Usage Coverage %", "Usage coverage", None)], v, y=SLICER_Y + 8)
    b = split([52, 54], 190, 250)
    v.append(visual(f"{k}.dq", "pivotTable", b[0], len(v),
                    query({"Rows": [pc(DQ, "Metric", "Measured property")],
                           "Values": [pm("DQ Metric Value", "Value"), pm("DQ Metric Unit", "Unit")]}),
                    objects=NO_SUBTOTALS,
                    title="Data quality, computed live in SQL",
                    why="fifteen properties measured from the database on every refresh, so this page cannot drift "
                        "from the data. A matrix, not a table: a table renders the text column blank"))
    v.append(textbox(f"{k}.rules", [
        [("The rules every figure obeys", True, CRIMSON)],
        [("As of 31 Aug 2026. ", True),
         ("MRR, ARR, customers and seats are STOCKS: read at a month end, never summed across months. Selecting a "
          "range gives the figure at the end of it.", False)],
        [("Retention is quoted with its basis. ", True),
         ("Revenue retention and logo retention answer different questions, so both are published and neither "
          "stands in for the other.", False)],
        [("Rates, not counts, for behaviour. ", True),
         ("Support contact and payment failure are per month of tenure and per invoice. A raw count measures how "
          "long somebody has been a customer.", False)],
        [("Nothing beyond the data. ", True),
         ("A month the file does not reach reads blank, not zero - so a chart stops where the data stops.", False)],
    ], b[1], len(v), size=9))
    b = split([52, 54], 452, 206)
    v.append(textbox(f"{k}.limits", [
        [("What this data will not support", True, TERRACOTTA)],
        [("No expansion, contraction or reactivation. ", True),
         ("MRR is one static value per subscription, every subscription bills a single invoice amount for life, and "
          "every customer has exactly one subscription. Three of the five waterfall components are structurally nil, "
          "and net revenue retention can therefore never exceed gross.", False)],
        [("No churn model. ", True),
         ("Product usage is statistically independent of churn here - every correlation inside 0.02. A model trained "
          "on it would fit noise, so a tested driver view is published instead.", False)],
        [("No lifetime value from the data. ", True),
         ("There is no cost of service anywhere in the source, so LTV and CAC payback are modelled on a stated "
          "gross-margin assumption held in ModelConfig.", False)],
        [("No marketing efficiency over time. ", True),
         ("Acquisition cost is attached to a customer, not to a campaign or a month.", False)],
    ], b[0], len(v), size=9))
    v.append(textbox(f"{k}.traps", [
        [("Traps in this source, and what was done", True, PLUM)],
        [("Acquisition stops before churn does. ", True),
         ("The newest subscription starts 30 Jun 2026 while churn runs to 30 Aug 2026, so the last two months show "
          "losses and no wins. Reported as measured, and flagged wherever it shows.", False)],
        [("Usage is a 40% sample. ", True),
         ("A customer appears in a median of nine months against a median tenure of twenty-nine. Adoption figures "
          "say 'of the customers we can see' and are never a denominator for revenue.", False)],
        [("Unresolved tickets carry a resolution time. ", True),
         ("All 18,142 of them, drawn from the same distribution as resolved ones. Mean time to resolve uses "
          "resolved tickets only, and no claim is made that escalation takes longer.", False)],
        [("Invoices are dated before subscriptions start. ", True),
         ("11,599 of them, every one inside the start month: invoices are dated the 1st while a subscription starts "
          "on any day. A convention, not a fault - but an invoice date never dates a subscription.", False)],
        [("Synthetic data. ", True),
         ("A portfolio dataset for a fictional SaaS business - never a real customer base.", False)],
    ], b[1], len(v), size=9))
    return {"name": page_id(k), "displayName": "Data & Method"}, v, []


PAGES = [page_exec, page_movement, page_retention, page_drivers, page_customers, page_economics,
         page_product, page_method]
# A movement page is a PERIOD view by nature - "what moved" needs a window - so this
# one carries the trailing twelve months as a page filter and its labels say so. A
# slicer could not do this: a slicer cannot hold a default selection.
PAGE_FILTERS = {"movement": 12}


# -------------------------------------------------------------------- theme ---
def solid(colour):
    return {"solid": {"color": colour}}


PAGE_OBJECTS = {"background": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}],
                "outspace": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}]}

THEME = {
    "name": "Northstar Crimson",
    "dataColors": DATA_COLOURS,
    "foreground": INK, "foregroundNeutralSecondary": MUTED, "foregroundNeutralTertiary": NEUTRAL,
    "background": PANEL, "backgroundLight": PANEL_ALT, "backgroundNeutral": BORDER,
    # good / bad / neutral drive the waterfall: what was WON is the light tone, what
    # was LOST is the dark one, and the total is the one neutral in the palette.
    "tableAccent": CRIMSON, "good": ROSE, "neutral": SLATE, "bad": CRIMSON,
    "maximum": CRIMSON, "center": PINK, "minimum": PINK_WASH, "null": NEUTRAL,
    "hyperlink": CRIMSON, "visitedHyperlink": PLUM,
    "textClasses": {
        # Every card names its own colour; this is only what an unstyled one falls back to.
        "callout": {"fontSize": 26, "fontFace": "Consolas", "color": CRIMSON},
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
            page["filterConfig"] = {"filters": [recent_months(f"page.{key}", PAGE_FILTERS[key])]}
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
            if a["name"] in BACKDROPS or b["name"] in BACKDROPS:
                continue            # the rail backdrop is meant to be underneath
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
