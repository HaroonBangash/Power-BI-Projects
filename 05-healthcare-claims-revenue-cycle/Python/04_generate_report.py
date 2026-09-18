# -*- coding: utf-8 -*-
"""
Phase 4 - Report pages (PBIR as code).

Eight pages behind a TOP NAVIGATION BAR. Every previous project in this series put a
column of buttons down the left; this one runs a row of tabs across the top, with the
current page marked by a mint underline. It is a different device in a different place,
and it buys back 168 px of width that a 47-month receivable chart uses.

  Executive              What did we bill, what did we agree to, what came in, what is owed
  Revenue Cycle          The money chain, and the two collection rates nobody should quote alone
  Accounts Receivable    How much is outstanding, how old it is, and what moved it
  Denials                What is denied, for what reason, by whom - and what never recovers
  What Predicts a Denial The brief asked for root-cause analysis. Nine of ten dimensions failed the test
  Timeliness             The clock: service, submission, adjudication, cash
  Service & Patient Mix  What was done and to whom. Volume only - the code does not price the procedure
  Data & Method          What was assumed, what was tested, what this data will not support

DOMAIN RULES THE PAGES OBEY (PROJECT_STATE D1-D27)
  * ALLOWED is the spine, not billed. Billed is a sticker price nobody pays; 26.5% of
    it is a discount agreed before the claim was sent, and it is never shown as a loss.
  * Every allowed dollar is in exactly one of four buckets - collected, patient
    responsibility, open AR, denied - and they sum back to it on every row.
  * AR is a STOCK. It is read at one month end from a snapshot, capped at the as-of
    month, and never summed across months.
  * Net collection rate is quoted on RESOLVED claims, with the all-claims figure beside
    it. Neither appears alone anywhere in this report.
  * Nothing claims a recovery. No denied claim in this file was ever paid, so appeal
    yield is not offered - and the recovery rate is shown reading 0.00% so that this is
    stated rather than quietly omitted.
  * A provider is never ranked without its error bar. The distribution is drawn against
    its own chance baseline instead of as a league table.
  * The reason mix is a WORKLOAD profile, never a root cause.
  * Colour is not decoration: mint means "this is the thing", and the ageing ramp is the
    only ordered scale in the report because age is the only ordered quantity.

PRESENTATION RULES CARRIED FORWARD FROM THE EARLIER PROJECTS
  * Gauge >= 110 px or the arc is clipped; multi-row card >= 110 px for three rows;
    decomposition tree >= 260 px and about four bars a level; a table >= 180 px.
  * Money axes start at zero.
  * A single-measure bar or column chart ignores a measure-keyed dataPoint fill and
    falls back to the palette; defaultColor is what it actually reads.
  * A slicer cannot hold a default selection, and a filter ON a slicer restricts its
    items rather than selecting one.

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
RP = PBI / "HealthcareRCM.Report"
PAGES_DIR = RP / "definition" / "pages"
DEF = PBI / "HealthcareRCM.SemanticModel" / "definition"
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
# THE NAVIGATION IS A TOP BAR, not a left rail. Every previous project in this series
# put a column of buttons down the left-hand side; this one runs a row of tabs across
# the top, so the five reports do not read as one report re-skinned five times. It also
# buys 168 px of width back, which a 47-month AR chart uses.
W, H = 1280, 720
MARGIN, GAP = 16, 12
CX = MARGIN
CW = W - 2 * MARGIN
TOPBAR_H = 56
HEADER_Y, HEADER_H = 60, 38
SLICER_Y, SLICER_H = 100, 56
KPI_Y, KPI_H = 164, 72
ROW2_Y, ROW2_H = 244, 228
ROW3_Y, ROW3_H = 480, 180
NOTE_Y, NOTE_H = 668, 44

# A DARK OPERATIONS CONSOLE. A revenue cycle is an operational discipline - a denials
# queue, an ageing ladder, a clock - so the report is built like a console rather than a
# board pack: a deep teal ground, lifted panels, and ONE accent.
#
# The discipline here is that colour is not decoration. Mint is the accent and it means
# "this is the thing". The AGEING RAMP is the only ordered colour scale in the report,
# because age is the only quantity here that genuinely has an order. Everything else is
# either the accent or a muted tone.
PAGE_BG, BAR = "#0A1D22", "#071619"          # the ground, and the bar across the top
PANEL, PANEL_ALT = "#10292F", "#0E242A"      # a card, and its alternating row
PANEL_HI = "#143840"                         # the hero card: lifted, not recoloured
BORDER, GRID = "#1C3D45", "#17343B"
INK, MUTED, NEUTRAL = "#E6F1F2", "#8FA9AD", "#5B767C"
HEADER_INK = "#9FC3C6"                       # table and matrix headers

ACCENT = "#37C9A8"                           # mint: the one accent in the report
ACCENT_DIM = "#1F6F63"
AMBER, CORAL, SKY = "#F2B441", "#E8657A", "#6AA9E0"
TEAL2, ORANGE = "#4FB3C4", "#E8944B"
VIOLET, LIME, ROSE = "#B78BE8", "#8FD14F", "#C98A7A"

# The ageing ladder, cool to hot. These six are the same constants the model's
# [AR Bucket Colour] measure returns, so a bar and its own conditional colour cannot
# drift apart.
AGE_RAMP = [ACCENT, TEAL2, SKY, AMBER, ORANGE, CORAL]

# Supporting hues, used ONLY where a chart has more categories than the accent and one
# muted tone can separate - a seven-slice denial-reason chart, a ten-code treemap.
DATA_COLOURS = [ACCENT, SKY, AMBER, CORAL, VIOLET, TEAL2, LIME, ORANGE, ROSE, MUTED]
THEME_FILE = "NorthstarConsole.json"

# ------------------------------------------------------------ the top bar ---
# The tab a reader is on is a filled block with a mint underline beneath it; every other
# tab is bare text on the bar. That underline is the classic tab affordance and it is
# what makes this unmistakably not the left-rail pill of the previous projects.
TAB_Y, TAB_H, TAB_GAP = 11, 32, 4
BRAND_W = 236
TAB_W = (W - BRAND_W - MARGIN - TAB_GAP * 7) // 8
UNDERLINE_Y, UNDERLINE_H = 44, 5
TAB_FONT = 9
TAB_FG, TAB_FG_SELECTED = MUTED, ACCENT
TAB_FILL_SELECTED = "#0E2F35"

NAV_ITEMS = [("Executive", "exec"), ("Revenue Cycle", "cycle"),
             ("Receivables", "ar"), ("Denials", "denials"),
             ("What Predicts", "evidence"), ("Timeliness", "timeliness"),
             ("Service Mix", "mix"), ("Data & Method", "method")]

# --------------------------------------------------------------- model names ---
DATE, PAYER, FAC, PROV, PAT = "DimDate", "DimPayer", "DimFacility", "DimProvider", "DimPatient"
STATUS, REASON, DSTATUS = "DimClaimStatus", "DimDenialReason", "DimDenialStatus"
PROC, DIAG, METHOD = "DimProcedure", "DimDiagnosis", "DimPaymentMethod"
BUCKET, MOVETYPE = "DimARBucket", "DimARMovementType"
CLAIM, LINE, PAY, DEN = "FactClaim", "FactClaimLine", "FactPayment", "FactDenial"
SNAP, MOVE = "FactARSnapshot", "FactARMovement"
SIGNAL, CHANCE, DQ = "DenialSignal", "ProviderChance", "DataQualityMetric"
# The calculation groups and the field parameter are tables too, and a slicer over any
# of them is how a reader changes the question instead of the page.
BASIS, TIMEGRP, CUT = "Date Basis", "Time Comparison", "Breakdown"

ASOF_MONTH = (2026, 11)          # the month the data ends: used to build a trailing window
MANIFEST_ROWS = []
# The bar behind the tabs is the one visual that is SUPPOSED to sit under others, so the
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
    return categorical_filter(seed + ".recent", DATE, "MonthLabel", list(reversed(labels)))


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

def nav_tab(seed, label, target, selected, x, tab):
    """A tab on the top bar. The page you are on is a filled block with mint text and a
    mint underline beneath it; every other page is bare text on the bar. The other
    projects in this series all used a column of filled rectangles down the left, so
    this is a different device in a different place."""
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(False)}}],
        "fill": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"fillColor": {"solid": {"color": lit_s(TAB_FILL_SELECTED)}},
                                 "transparency": lit_n(0 if selected else 100)},
                  "selector": {"id": "default"}}],
        "text": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"text": lit_s(label),
                                 "fontColor": {"solid": {"color": lit_s(TAB_FG_SELECTED if selected else TAB_FG)}},
                                 "fontSize": lit_n(TAB_FONT), "bold": lit_b(selected)},
                  "selector": {"id": "default"}}],
    }
    v = visual(seed, "actionButton", (x, TAB_Y, TAB_W, TAB_H), tab, objects=objects, title="",
               why=f"Navigate to {label}")
    v["visual"]["visualContainerObjects"]["visualLink"] = [{"properties": {
        "show": lit_b(True), "type": lit_s("PageNavigation"), "navigationSection": lit_s(target)}}]
    return v


def bar_block(seed, box, colour, tab, why):
    """A rectangle. PBIR has no shape primitive, so this is an action button with its
    text off and its fill on. NOT a textbox: an empty textbox is forced to a minimum
    height of about 24 px, which turned a 3 px tab indicator into a mint blob, and
    Desktop draws a text caret inside it that shows up in every capture. z = 0 keeps it
    underneath whatever stands on it."""
    BACKDROPS.add(sid(seed))
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(False)}}],
        "text": [{"properties": {"show": lit_b(False)}}],
        "fill": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"fillColor": {"solid": {"color": lit_s(colour)}},
                                 "transparency": lit_n(0)},
                  "selector": {"id": "default"}}],
    }
    return visual(seed, "actionButton", box, tab, objects=objects, title=None, z=0, why=why)


def shell(key, title):
    v = [bar_block(f"{key}.bar.bg", (0, 0, W, TOPBAR_H), BAR, 0, "The navigation bar")]
    # Not a textbox: Desktop draws a text caret at the end of a textbox's content and it
    # lands in every capture. A button with its text on and everything else off does not.
    v.append(visual(f"{key}.brand", "actionButton", (MARGIN, TAB_Y + 3, BRAND_W - MARGIN - 10, 28), len(v),
                    objects={"icon": [{"properties": {"show": lit_b(False)}}],
                             "outline": [{"properties": {"show": lit_b(False)}}],
                             "fill": [{"properties": {"show": lit_b(False)}}],
                             "text": [{"properties": {"show": lit_b(True)}},
                                      {"properties": {"text": lit_s("MERIDIAN HEALTH  RCM"),
                                                      "fontColor": {"solid": {"color": lit_s(INK)}},
                                                      "fontSize": lit_n(10), "bold": lit_b(True)},
                                       "selector": {"id": "default"}}]},
                    title="", why="Report identity"))
    for i, (label, target) in enumerate(NAV_ITEMS):
        x = BRAND_W + i * (TAB_W + TAB_GAP)
        v.append(nav_tab(f"{key}.nav.{target}", label, page_id(target), target == key, x, len(v)))
        if target == key:
            # The underline sits BELOW the tab, not behind it, so the two never overlap
            # and the z-order never has to arbitrate between them.
            v.append(bar_block(f"{key}.nav.{target}.underline",
                               (x + 8, UNDERLINE_Y, TAB_W - 16, UNDERLINE_H), ACCENT, len(v),
                               "Marks the current page"))
    v.append(textbox(f"{key}.title", [[(title, True, INK)]], (CX, HEADER_Y, 560, HEADER_H), len(v), size=14))
    v.append(card(f"{key}.context", "As-Of Label", "", (W - MARGIN - 480, HEADER_Y + 4, 480, HEADER_H - 4), len(v),
                  size=9, colour=MUTED, font="Segoe UI", panel=False))
    return v


def kpis(key, items, v, y=KPI_Y, height=KPI_H, filters=None):
    """items: (measure, label, kind). On a dark ground hierarchy is carried by ELEVATION
    rather than hue: the first card is lifted a shade and writes its figure in the
    accent, the rest sit on the panel colour in ink. Filling a card with a colour on a
    dark theme buries its own number, which is the first thing a render shows."""
    for i, ((measure, label, kind), box) in enumerate(zip(items, split(len(items), y, height))):
        v.append(card(f"{key}.kpi.{measure}", measure, label, box, len(v), kind=kind, filters=filters,
                      colour=ACCENT if i == 0 else INK, hero=PANEL_HI if i == 0 else None))


def note(key, lead, text, v):
    v.append(textbox(f"{key}.note", [[(lead + "  ", True), (text, False)]], (CX, NOTE_Y, CW, NOTE_H), len(v),
                     size=9, colour=MUTED))


def slicers(key, specs, v, y=SLICER_Y):
    for i, (table, column, label) in enumerate(specs):
        v.append(slicer(f"{key}.sl.{column}", table, column, label, (CX + i * 212, y, 200, SLICER_H), len(v)))
# ------------------------------------------------------------------- pages ---
def page_exec():
    """What a health system's executive asks first: what did we bill, what did we agree
    to, what came in, and what is still owed. Every figure is anchored to the as-of date
    and names its own window, so the page means the same thing however it is opened."""
    k = "exec"
    v = shell(k, "Executive Summary")
    slicers(k, [(PAYER, "PayerName", "Payer"), (FAC, "FacilityType", "Facility type"),
                (BASIS, "Basis", "Date basis")], v)
    kpis(k, [("Allowed", "Allowed, all claims", "money"),
             ("Collected", "Cash collected", "money"),
             ("Net Collection Rate %", "Net collection, resolved claims", None),
             ("Open AR", "Open AR at 30 Nov 2026", "money"),
             ("Denial Rate %", "Denial rate", None),
             ("Days in AR", "Days in AR", None)], v)
    b = split([58, 42], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.chain", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Billed"), pm("Allowed"), pm("Collected")]}),
                    objects=colours([("Billed", MUTED), ("Allowed", SKY), ("Collected", ACCENT)])
                            | LEGEND_BOTTOM | ZERO_BASED,
                    title="Billed, allowed and collected, by service month",
                    why="the whole funnel in one line chart: the gap between the top line and the bottom one is "
                        "what the revenue cycle is for"))
    v.append(visual(f"{k}.buckets", "donutChart", b[1], len(v),
                    query({"Y": [pm("Collected", "Collected"),
                                 pm("Patient Responsibility", "Patient responsibility"),
                                 pm("Open AR (Claim Basis)", "Still in AR"),
                                 pm("Denied Amount", "Denied")]}),
                    objects=colours([("Collected", ACCENT), ("Patient Responsibility", AMBER),
                                     ("Open AR (Claim Basis)", SKY), ("Denied Amount", CORAL)])
                            | LEGEND_BOTTOM | DONUT_PERCENT,
                    title="Where every allowed dollar went",
                    why="the four buckets the allowed amount splits into. They sum back to it exactly, which is "
                        "the identity the whole model is built to protect"))
    b = split([38, 32, 30], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.volume", "columnChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Claims")]}),
                    objects=one_colour("Claims", SKY) | ZERO_BASED,
                    title="Claims by service month",
                    why="volume is flat: 2,067 to 2,383 a month across 44 months, so no month-on-month movement "
                        "on this page should be read as a trend"))
    v.append(visual(f"{k}.status", "barChart", b[1], len(v),
                    query({"Category": [pc(STATUS, "ClaimStatus", "Status")], "Y": [pm("Claims")]},
                          sort=(STATUS, "StatusOrder"), desc=False),
                    objects=one_colour("Claims", ACCENT) | DATA_LABELS,
                    title="Claims by adjudication status",
                    why="paid, pending, denied - and the pending share is identical in every month of the file"))
    v.append(visual(f"{k}.rates", "multiRowCard", b[2], len(v),
                    query({"Values": [pm("Gross Collection Rate %", "Gross collection"),
                                      pm("Net Collection Rate (All Claims) %", "Net, all claims"),
                                      pm("First-Pass Acceptance %", "First-pass acceptance")]}),
                    accent=PANEL_HI, title="",
                    why="multiRowCard: the three rates that only mean anything next to each other"))
    note(k, "How to read this.",
         "Amounts are AUD and the as-of date is 3 Nov 2026. NET COLLECTION RATE is quoted on RESOLVED claims - a "
         "billing office is not accountable for claims the payer has not answered - and the all-claims figure sits "
         "beside it, lower, because that is what has actually been banked. Open AR is read at the 30 Nov month end "
         "from a monthly snapshot, never summed across months.", v)
    return {"name": page_id(k), "displayName": "Executive Summary"}, v, []


def page_cycle():
    """The money chain, and the two collection rates that are usually quoted without
    each other."""
    k = "cycle"
    v = shell(k, "Revenue Cycle")
    slicers(k, [(PAYER, "PayerName", "Payer"), (FAC, "FacilityName", "Facility"),
                (DATE, "FinancialYear", "Financial year")], v)
    kpis(k, [("Billed", "Billed at chargemaster", "money"),
             ("Contractual Adjustment", "Contractual adjustment", "money"),
             ("Allowed", "Allowed under contract", "money"),
             ("Collected", "Collected", "money"),
             ("Contractual Adjustment %", "Given away by contract", None),
             ("Patient Responsibility %", "Patient share of allowed", None)], v)
    b = split([34, 66], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.funnel", "funnel", b[0], len(v),
                    query({"Y": [pm("Billed", "Billed"), pm("Allowed", "Allowed"), pm("Collected", "Collected")]}),
                    objects=colours([("Billed", MUTED), ("Allowed", SKY), ("Collected", ACCENT)]),
                    title="Billed to allowed to collected",
                    why="funnel: nobody ever pays the chargemaster price. 26.5% of billed is a discount agreed "
                        "before the claim was sent, and it is not a loss"))
    v.append(visual(f"{k}.mix", "hundredPercentStackedColumnChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Collected", "Collected"),
                                 pm("Patient Responsibility", "Patient"),
                                 pm("Open AR (Claim Basis)", "Still in AR"),
                                 pm("Denied Amount", "Denied")]}),
                    objects=colours([("Collected", ACCENT), ("Patient Responsibility", AMBER),
                                     ("Open AR (Claim Basis)", SKY), ("Denied Amount", CORAL)]) | LEGEND_BOTTOM,
                    title="What happened to each month's allowed amount",
                    why="the composition is stable month after month, which is itself the finding: the share that "
                        "never resolves does not improve with age"))
    b = split([44, 30, 26], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.bypayer", "clusteredColumnChart", b[0], len(v),
                    query({"Category": [pc(PAYER, "PayerName", "Payer")],
                           "Y": [pm("Allowed"), pm("Collected")]},
                          sort="Allowed"),
                    objects=colours([("Allowed", SKY), ("Collected", ACCENT)]) | LEGEND_BOTTOM,
                    title="Allowed and collected by payer",
                    why="six payers, near-identical shares. The allowed RATE is 73.4% to 73.6% for every one of "
                        "them, so no payer is ranked by contract performance anywhere in this report"))
    v.append(visual(f"{k}.bytype", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(FAC, "FacilityType", "Facility type")],
                           "Y": [pm("Net Collection Rate %")]}),
                    objects=one_colour("Net Collection Rate %", ACCENT) | DATA_LABELS,
                    title="Net collection rate by facility type",
                    why="flat across all four types, to within half a point"))
    v.append(visual(f"{k}.gauge", "gauge", b[2], len(v),
                    query({"Y": [pm("Net Collection Rate %", "Net collection")],
                           "MaxValue": [pm("Rate Scale Max", "Scale")],
                           "TargetValue": [pm("Net Collection Benchmark", "Benchmark")]}),
                    title="Net collection rate against a 95% benchmark", title_size=9,
                    why="gauge, scaled 0 to 100% with the benchmark as its target. Without an explicit maximum a "
                        "gauge scales to twice its own value, which puts any number in the middle of the dial"))
    note(k, "The two rates, and why both are here.",
         "GROSS collection rate divides cash by BILLED and is always a low, largely meaningless number, because "
         "most of the gap was agreed in advance. NET divides by ALLOWED on resolved claims and is the figure a "
         "revenue-cycle team is measured on. Quoting either alone would mislead, so neither appears without the "
         "other anywhere in this report.", v)
    return {"name": page_id(k), "displayName": "Revenue Cycle"}, v, []


def page_ar():
    """The receivable: how much, how old, and what moved it. The one page where colour
    carries an order, because age is the one quantity here that has one."""
    k = "ar"
    v = shell(k, "Accounts Receivable")
    slicers(k, [(PAYER, "PayerName", "Payer"), (FAC, "FacilityType", "Facility type"),
                (BUCKET, "ARBucket", "Ageing bucket")], v)
    kpis(k, [("Open AR", "Open AR at 30 Nov 2026", "money"),
             ("AR Claims", "Claims outstanding", "count"),
             ("Days in AR", "Days in AR", None),
             ("AR Weighted Age (Days)", "Weighted average age", None),
             ("AR Past Filing %", "Past any filing limit", None),
             ("Average AR per Claim", "Average per claim", "money")], v)
    b = split([58, 42], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.trend", "areaChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Open AR")]}),
                    objects=one_colour("Open AR", SKY) | ZERO_BASED,
                    title="Open AR at each month end, since January 2023",
                    why="it never turns. A receivable that only ever climbs is what happens when a fixed share of "
                        "claims is never answered - see the note below"))
    v.append(visual(f"{k}.bridge", "waterfallChart", b[1], len(v),
                    query({"Category": [pc(MOVETYPE, "MovementType", "Movement")],
                           "Y": [pm("AR Movement (All Components)", "Change in AR")]}),
                    title="What moved the receivable",
                    why="waterfall: claims enter AR at allowed on submission and leave as cash, as patient "
                        "responsibility, or as a denial. The four reconcile to the balance in every month"))
    b = split([40, 60], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.ageing", "columnChart", b[0], len(v),
                    query({"Category": [pc(BUCKET, "ARBucket", "Days outstanding")],
                           "Y": [pm("Open AR (All Buckets)", "Open AR")]},
                          sort=(BUCKET, "ARBucketKey"), desc=False),
                    objects=one_colour("Open AR (All Buckets)", SKY, by="AR Bucket Colour")
                            | DATA_LABELS,
                    title="The ageing ladder",
                    why="cool to hot, fresh to past saving - the only ordered colour scale in the report, because "
                        "age is the only quantity here with an order. Columns, because six buckets scroll in a "
                        "180 px bar chart and the ones hidden below the fold were the large ones. The three "
                        "freshest draw at zero rather than vanishing: nothing has been submitted for 84 days"))
    v.append(visual(f"{k}.matrix", "pivotTable", b[1], len(v),
                    query({"Rows": [pc(PAYER, "PayerName", "Payer")],
                           "Columns": [pc(BUCKET, "ARBucket", "Bucket")],
                           "Values": [pm("Open AR (All Buckets)", "Open AR")]}),
                    objects=NO_SUBTOTALS,
                    title="Receivable by payer and age",
                    why="matrix: the same shape in every payer, which says the ageing is a property of the file "
                        "rather than of anybody's collections performance"))
    note(k, "This ageing is arithmetic, not a collections story.",
         "23.1% of claims are Pending, and that share is 20.6-25.0% in EVERY submission month - a 2023 claim is as "
         "likely to be pending as last month's. 77% of the receivable is over a year old, past any filing limit. "
         "In a real revenue cycle those would have been written off; here they are a status assigned and never "
         "revisited. AR is carried at ALLOWED, not billed.", v)
    return {"name": page_id(k), "displayName": "Accounts Receivable"}, v, []


def page_denials():
    """What is being denied, for what reason, and by whom. The reason mix is a workload
    profile - it is not a root cause, and the page says so."""
    k = "denials"
    v = shell(k, "Denials")
    slicers(k, [(PAYER, "PayerName", "Payer"), (REASON, "ReasonCategory", "Reason category"),
                (DSTATUS, "DenialStatus", "Workflow state")], v)
    kpis(k, [("Denied Claims", "Claims denied", "count"),
             ("Denial Rate %", "Denial rate", None),
             ("Denied Value", "Denied, at allowed", "money"),
             ("First-Pass Acceptance %", "First-pass acceptance", None),
             ("Preventable at Registration %", "Preventable at registration", None),
             ("Denial Recovery Rate %", "Recovered after denial", None)], v)
    b = split([46, 54], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.reasons", "columnChart", b[0], len(v),
                    query({"Category": [pc(REASON, "DenialReason", "Reason")], "Y": [pm("Denials")]},
                          sort="Denials"),
                    objects=one_colour("Denials", SKY) | DATA_LABELS,
                    title="Denials by reason",
                    why="seven reasons, 1,079 to 1,175 each. A near-uniform mix is a WORKLOAD profile, not a root "
                        "cause - there is no dominant failure to go and fix. Columns rather than bars because "
                        "seven categories scroll in a 228 px bar chart and the seventh would be hidden"))
    v.append(visual(f"{k}.tree", "treemap", b[1], len(v),
                    query({"Group": [pc(REASON, "ReasonCategory", "Category")],
                           "Details": [pc(REASON, "DenialReason", "Reason")],
                           "Values": [pm("Denied Value")]}),
                    objects=LEGEND_BOTTOM,
                    title="Denied value by category and reason",
                    why="treemap: grouped the way a denials team is organised - front-end, coding, clinical, "
                        "process - so the categories name who would own the fix"))
    b = split([34, 34, 32], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.bypayer", "columnChart", b[0], len(v),
                    query({"Category": [pc(PAYER, "PayerName", "Payer")], "Y": [pm("Denial Rate %")]},
                          sort="Denial Rate %"),
                    objects=one_colour("Denial Rate %", MUTED, by="Payer Colour") | DATA_LABELS,
                    title="Denial rate by payer",
                    why="the one real split in the data, and the bar colour says which: Self Pay in the accent, "
                        "the five insurers in one muted tone because they do not differ from each other"))
    v.append(visual(f"{k}.status", "pieChart", b[1], len(v),
                    query({"Category": [pc(DSTATUS, "DenialStatus", "State")], "Y": [pm("Denials")]}),
                    objects=LEGEND_BOTTOM,
                    title="The denials queue, by workflow state",
                    why="pie: Open, Appealed, Corrected, Written Off. These are WORKFLOW STATES, not outcomes - "
                        "see the note"))
    v.append(visual(f"{k}.bymonth", "lineChart", b[2], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Denial Rate %")]}),
                    objects=one_colour("Denial Rate %", CORAL) | ZERO_BASED,
                    title="Denial rate by adjudication month",
                    why="flat at 7-8% for 44 months. There is no deterioration and no improvement to explain"),)
    note(k, "No denial in this file ever recovers.",
         "0 of 7,824 denied claims were subsequently paid - including all 1,913 marked CORRECTED and 1,946 marked "
         "APPEALED - and the denial date equals the adjudication date on every one, so there is no appeal timeline "
         "either. Appeal yield and overturn rate cannot be computed here. The recovery card reads 0.00% by "
         "construction, and it is on the page so this is stated rather than quietly omitted.", v)
    return {"name": page_id(k), "displayName": "Denials"}, v, []


def page_evidence():
    """The page the brief asked for, answered honestly. 'Analyse denial root causes by
    payer, facility, provider, diagnosis and procedure' - so every one of them was
    tested, and nine of the ten failed."""
    k = "evidence"
    v = shell(k, "What Predicts a Denial")
    slicers(k, [(SIGNAL, "SignalVerdict", "Verdict"), (CHANCE, "ChanceBand", "Chance band"),
                (PROV, "Specialty", "Specialty")], v)
    kpis(k, [("Strongest Signal", "Strongest association (Cramer's V)", None),
             ("Dimensions with Signal", "Dimensions with any signal", "count"),
             ("Dimensions Tested", "Dimensions tested", "count"),
             ("Self Pay Gap (pp)", "Self Pay vs insured, points", None),
             ("Providers Beyond 2 SE %", "Providers beyond 2 SE", None),
             ("Expected Beyond 2 SE %", "Expected by chance", None)], v)
    b = split([46, 54], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.signal", "columnChart", b[0], len(v),
                    query({"Category": [pc(SIGNAL, "Dimension", "Dimension")], "Y": [pm("Signal Strength")]},
                          sort="Signal Strength"),
                    objects=one_colour("Signal Strength", MUTED, by="Signal Colour") | DATA_LABELS,
                    title="How strongly each dimension predicts a denial",
                    why="Cramer's V from a chi-square test, computed in SQL on every refresh. Columns rather than "
                        "bars because ten categories scroll in a 228 px bar chart - and the four that would hide "
                        "behind the scrollbar are the ones that FAILED, which is the point of the page. Payer "
                        "scores 0.081; the next is facility at 0.015. Anything under the stated 0.02 rule is drawn "
                        "flat grey, so the page says 'nothing here' with its ink as well as its words"))
    v.append(visual(f"{k}.dist", "columnChart", b[1], len(v),
                    query({"Category": [pc(CHANCE, "RateBand", "Provider denial rate")],
                           "Y": [pm("Providers Measured", "Providers")]}),
                    objects=one_colour("Providers Measured", SKY) | DATA_LABELS,
                    title="How 500 providers' denial rates are distributed",
                    why="a bell curve centred on the group rate: 6, 83, 189, 156, 56, 9, 1. That is what a "
                        "binomial distribution looks like, and it is what a league table would have ranked"))
    b = split([56, 44], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.scatter", "scatterChart", b[0], len(v),
                    query({"Category": [pc(CHANCE, "ProviderName", "Provider")],
                           "Series": [pc(CHANCE, "ChanceBand", "Chance band")],
                           "X": [pm("Claims", "Claims")],
                           "Y": [pm("Provider Denial Rate", "Denial rate")],
                           "Size": [pm("Provider Standard Error", "Standard error")]}),
                    objects=LEGEND_BOTTOM,
                    title="Every provider: claim count against denial rate",
                    why="a funnel plot, and a flat one. Every provider carries about 200 claims, so every error "
                        "bar is nearly the same width - which means the vertical spread you can see IS the spread "
                        "chance produces at that sample size, not a range of performance"))
    v.append(visual(f"{k}.table", "pivotTable", b[1], len(v),
                    query({"Rows": [pc(SIGNAL, "Dimension", "Dimension")],
                           "Values": [pm("Denial Rate Spread (pp)", "Spread (pp)"),
                                      pm("Signal Strength", "Cramer's V"),
                                      pm("Signal Verdict", "Verdict")]},
                          sort="Signal Strength"),
                    objects=NO_SUBTOTALS,
                    title="The test, for every dimension the brief named",
                    why="a matrix, not a table, because a table cannot drop its total row and an AVERAGE Cramer's "
                        "V across ten dimensions is not a number that means anything. The spread alone is "
                        "misleading too - a 30-value dimension always spreads further than a 3-value one - which "
                        "is exactly why the chi-square sits beside it"))
    note(k, "Why there is no denial-risk model here.",
         "Patient age, claim size, line count and days-to-submit all correlate with denial at |r| < 0.01. A model "
         "on them would fit noise, then hold up claims that were never at risk. 23 of 500 providers sit beyond two "
         "standard errors - 4.6%, against the 4.55% chance predicts - and the worst is z = 3.3, about the maximum "
         "500 draws give. The only real effect is Self Pay, 2.95% against 8.79%.", v)
    return {"name": page_id(k), "displayName": "What Predicts a Denial"}, v, []


def page_timeliness():
    """The clock. The strongest thing this data has, and the part of the cycle a billing
    office actually controls."""
    k = "timeliness"
    v = shell(k, "Timeliness")
    slicers(k, [(PAYER, "PayerName", "Payer"), (METHOD, "PaymentMethod", "Payment method"),
                (FAC, "FacilityType", "Facility type")], v)
    kpis(k, [("Days to Cash", "Submission to cash", None),
             ("Days to Submit", "Service to submission", None),
             ("Days to Adjudicate", "Submission to decision", None),
             ("Days Adjudication to Cash", "Decision to cash", None),
             ("Median Days to Cash", "Median to cash", None),
             ("Paid within 45 Days %", "Paid inside 45 days", None)], v)
    b = split([58, 42], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.clock", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Days to Submit"), pm("Days to Adjudicate"),
                                 pm("Days to Cash (Claim Basis)", "Days to Cash")]}),
                    objects=colours([("Days to Submit", ACCENT), ("Days to Adjudicate", AMBER),
                                     ("Days to Cash (Claim Basis)", SKY)]) | LEGEND_BOTTOM | ZERO_BASED,
                    title="Every interval in the cycle, by service month",
                    why="three clocks on ONE axis, and that is the point: all three are measured on the claim, so "
                        "all three are read on the service month. The payment-date version of days-to-cash ran off "
                        "the end of this chart, because in the last two months cash was still arriving for care "
                        "delivered earlier - two different months on one axis"))
    v.append(visual(f"{k}.combo", "lineClusteredColumnComboChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Paid Claims", "Claims paid")],
                           "Y2": [pm("Days to Cash (Claim Basis)", "Days to cash")]}),
                    objects=colours([("Paid Claims", ACCENT_DIM),
                                     ("Days to Cash (Claim Basis)", AMBER)]) | LEGEND_BOTTOM,
                    title="Volume paid against speed of payment",
                    why="combo chart: if the payer slowed down when volume rose, these two would move together. "
                        "They do not"))
    b = split([34, 34, 32], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.bypayer", "clusteredColumnChart", b[0], len(v),
                    query({"Category": [pc(PAYER, "PayerName", "Payer")], "Y": [pm("Days to Cash")]},
                          sort="Days to Cash"),
                    objects=one_colour("Days to Cash", SKY) | DATA_LABELS,
                    title="Days to cash by payer",
                    why="within two days of each other across all six - the payers behave identically here"))
    v.append(visual(f"{k}.bymethod", "barChart", b[1], len(v),
                    query({"Category": [pc(METHOD, "PaymentMethod", "Method")], "Y": [pm("Days to Cash")]},
                          sort=(METHOD, "MethodOrder"), desc=False),
                    objects=one_colour("Days to Cash", TEAL2) | DATA_LABELS,
                    title="Days to cash by remittance method",
                    why="a cheque should be slower than an EFT. Here it is not, which is one more sign the "
                        "payment method in this source carries no information"))
    v.append(visual(f"{k}.gauge", "gauge", b[2], len(v),
                    query({"Y": [pm("Submitted within 3 Days %", "Within 3 days")],
                           "MaxValue": [pm("Rate Scale Max", "Scale")]}),
                    title="Claims submitted within 3 days", title_size=9,
                    why="the provider's own discipline, isolated from anything a payer does"))
    note(k, "This is the part of the cycle that works.",
         "A median of 33 days from submission to cash, 29 of them waiting on the payer's decision and 5 on the "
         "money moving afterwards. No claim is submitted before it is performed, adjudicated before it is "
         "submitted, or paid before it is adjudicated. Days to cash is measured on PAID claims: a pending claim "
         "has not failed this test, it simply has not taken it.", v)
    return {"name": page_id(k), "displayName": "Timeliness"}, v, []


def page_mix():
    """What was actually done, and to whom. Volume and mix only - the charge in this
    source is drawn independently of the procedure code, so nothing here is ranked by
    money."""
    k = "mix"
    v = shell(k, "Service & Patient Mix")
    slicers(k, [(PROC, "ServiceLine", "Service line"), (DIAG, "ICD10Chapter", "ICD-10 chapter"),
                (PAT, "AgeBand", "Patient age")], v)
    kpis(k, [("Claims", "Claims", "count"),
             ("Claim Lines", "Procedure lines", "count"),
             ("Patients Treated", "Patients treated", "count"),
             ("Lines per Claim", "Lines per claim", None),
             ("Providers Billing", "Providers billing", "count"),
             ("Claims per Patient", "Claims per patient", None)], v)
    b = split([56, 44], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.tree", "decompositionTreeVisual", b[0], len(v),
                    query({"Analyze": [pm("Claims", "Claims")],
                           "ExplainBy": [pc(FAC, "State", "State"), pc(FAC, "FacilityType", "Facility type"),
                                         pc(PROV, "Specialty", "Specialty"), pc(PAYER, "PayerName", "Payer"),
                                         pc(PAT, "AgeBand", "Patient age")]}),
                    objects={"tree": [{"properties": {"effectiveBarsPerLevel": lit_l(4)}}]},
                    title="Where the claims sit - choose the path",
                    why="decomposition tree: five attributes in whatever order the reader wants to ask them in. "
                        "It sits in the taller row because at 180 px the tree drew one level and nothing else"))
    v.append(visual(f"{k}.proc", "treemap", b[1], len(v),
                    query({"Group": [pc(PROC, "ServiceLine", "Service line")],
                           "Details": [pc(PROC, "ProcedureName", "Procedure")],
                           "Values": [pm("Claim Lines")]}),
                    objects=LEGEND_BOTTOM,
                    title="Procedure volume by service line",
                    why="treemap: ten real CPT codes grouped into the five departments that would own them. "
                        "VOLUME only - the charge is unrelated to the code, so no revenue ranking exists"))
    b = split([56, 44], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.diag", "columnChart", b[0], len(v),
                    query({"Category": [pc(DIAG, "DiagnosisCode", "ICD-10")], "Y": [pm("Claim Lines")]},
                          sort=(DIAG, "DiagnosisKey"), desc=False),
                    objects=one_colour("Claim Lines", SKY) | DATA_LABELS,
                    title="Lines by ICD-10 category - ten codes, 25,000 lines each",
                    why="columns on the CODE rather than bars on the name: ten long diagnosis names scroll in a "
                        "bar chart, and the whole point of this chart is that all ten bars are the same height. "
                        "A synthetic case mix, labelled as one"))
    v.append(visual(f"{k}.risk", "hundredPercentStackedColumnChart", b[1], len(v),
                    query({"Category": [pc(PAT, "AgeBand", "Patient age")],
                           "Series": [pc(PAT, "ChronicRiskBand", "Risk band")],
                           "Y": [pm("Claims")]}),
                    objects=LEGEND_BOTTOM,
                    title="Chronic risk band within each age band",
                    why="the source's own risk stratification is independent of age, which in a real population "
                        "it would not be. It is noted here and used nowhere as a driver"))
    note(k, "Volume and mix only.",
         "Every one of the ten procedure codes averages between $391.76 and $397.46 per line, across codes that in "
         "practice run from a venipuncture to an MRI of the brain with contrast. The charge is drawn independently "
         "of the code, so case-mix analysis, cost per procedure and service-line profitability are not available "
         "from this source and no page attempts them.", v)
    return {"name": page_id(k), "displayName": "Service & Patient Mix"}, v, []


def page_method():
    """What was assumed, what was tested, and what this data will not support. Every
    number on this page is recomputed from the source on every refresh."""
    k = "method"
    v = shell(k, "Data & Method")
    slicers(k, [(DQ, "Category", "Finding type")], v)
    kpis(k, [("Findings Recorded", "Findings recomputed each refresh", "count"),
             ("Allowed Identity Gap", "Allowed identity gap", "money"),
             ("AR Roll-Forward Check", "AR roll-forward gap", "money"),
             ("Calendar Days Added", "Calendar days generated", "count"),
             ("Claims Outside Supplied Calendar", "Claims outside the supplied calendar", "count"),
             ("Denial Recovery Rate %", "Denial recovery rate", None)], v)
    b = split([62, 38], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.dq", "pivotTable", b[0], len(v),
                    query({"Rows": [pc(DQ, "Category", "Type"), pc(DQ, "Metric", "What was measured")],
                           "Values": [pm("Data Quality Value", "Value")]}),
                    objects=NO_SUBTOTALS,
                    title="The audit findings, recomputed on every refresh",
                    why="a finding typed into a text box goes stale the moment the source changes; one computed "
                        "from the source cannot. A MATRIX rather than a table, because a table cannot drop its "
                        "total row - and this column holds counts, dollar amounts and percentages, so their sum "
                        "was reading 128,912.5482. The value formats itself per row for the same reason"))
    v.append(textbox(f"{k}.assume", [
        [("What this report assumes", True, ACCENT)],
        [("As-of date. ", True), ("3 Nov 2026, the last payment in the file. Nothing is projected past it.", False)],
        [("AR is carried at ALLOWED. ", True),
         ("Billed would overstate the receivable by the 26.5% contractual adjustment.", False)],
        [("Patient responsibility leaves AR on the payer's payment date. ", True),
         ("The source records no patient payment events. In reality this would begin a second, slower AR.", False)],
        [("Timely filing = 365 days. ", True),
         ("Used to mark receivables that could not be collected in practice. An assumption, not a fact in the "
          "data.", False)],
        [("Currency is AUD. ", True),
         ("Every facility state is Australian and the payers are Medicare, Bupa, Medibank, HCF and NIB.", False)],
    ], b[1], len(v), size=9))
    b = split([50, 50], ROW3_Y, ROW3_H)
    v.append(textbox(f"{k}.limits", [
        [("What this data will not support", True, CORAL)],
        [("No denial-risk model. ", True),
         ("Every candidate feature sits inside |r| < 0.01. It would fit noise.", False)],
        [("No appeal yield or recovery rate. ", True),
         ("0 of 7,824 denied claims were ever paid, whatever their workflow state says.", False)],
        [("No provider league table. ", True),
         ("23 of 500 providers sit beyond 2 SE; chance predicts 22.75.", False)],
        [("No payer contract ranking. ", True),
         ("Every payer allows 73.4-73.6% of billed, including Self Pay, where no contract exists.", False)],
        [("No procedure revenue or case mix. ", True),
         ("The charge is drawn independently of the CPT code.", False)],
        [("No growth narrative. ", True), ("Volume varies 3.3% month to month across 44 months.", False)],
    ], b[0], len(v), size=9))
    v.append(textbox(f"{k}.traps", [
        [("Traps in this source, and what was done", True, AMBER)],
        [("The calendar stopped short. ", True),
         ("The supplied dim_date ends at the last SERVICE date, leaving 4,807 adjudication, payment and denial "
          "dates outside it - which would have joined to a blank date and vanished from any measure sliced by "
          "those months, while the totals still looked right. The build generates its own calendar.", False)],
        [("'Pending' is permanent. ", True),
         ("23.1% of claims in every month of the file, median age 737 days. The ageing is built in full and "
          "labelled for what it is.", False)],
        [("Days in AR nearly read 8,700. ", True),
         ("Claims stop being submitted two months before the last payment, so the 91-day denominator window is "
          "capped at the last submission date.", False)],
        [("The dataset is SYNTHETIC. ", True),
         ("A portfolio dataset for a fictional Australian provider group - never real patient data.", False)],
    ], b[1], len(v), size=9))
    note(k, "Two identities hold on every refresh.",
         "ALLOWED = collected + patient responsibility + open AR + denied, on every row and therefore at every "
         "level of every aggregation. AR(m) = AR(m-1) + submitted - collected - patient responsibility - denied, "
         "in all 47 months. Both gaps are on the cards above, and both read zero.", v)
    return {"name": page_id(k), "displayName": "Data & Method"}, v, []


PAGES = [page_exec, page_cycle, page_ar, page_denials, page_evidence, page_timeliness,
         page_mix, page_method]
PAGE_FILTERS = {}


# -------------------------------------------------------------------- theme ---
def solid(colour):
    return {"solid": {"color": colour}}


PAGE_OBJECTS = {"background": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}],
                "outspace": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}]}

THEME = {
    "name": "Northstar Console",
    "dataColors": DATA_COLOURS,
    "foreground": INK, "foregroundNeutralSecondary": MUTED, "foregroundNeutralTertiary": NEUTRAL,
    "background": PANEL, "backgroundLight": PANEL_ALT, "backgroundNeutral": BORDER,
    # good / bad / neutral drive the waterfall: money ENTERING the receivable is the
    # accent, money leaving as a denial is the alarm colour, and the total is neutral.
    "tableAccent": ACCENT, "good": ACCENT, "neutral": SKY, "bad": CORAL,
    "maximum": CORAL, "center": AMBER, "minimum": ACCENT, "null": NEUTRAL,
    "hyperlink": ACCENT, "visitedHyperlink": TEAL2,
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
            # contrast and puts dark labels on dark bars.
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
