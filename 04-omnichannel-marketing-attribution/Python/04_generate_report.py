# -*- coding: utf-8 -*-
"""
Phase 4 - Report pages (PBIR as code).

Seven pages, each answering one business question, behind a left navigation rail
(project 1's proven design). Every visual type was first proven in the Phase 3
visual lab (git commit 197f398; Documentation/visual_catalogue.md); the lab pages
are replaced by these.

  Executive       Is marketing producing revenue, and is the spend defensible?
  Channels        Where does the budget go, and does attributed credit follow it?
  Funnel          How do leads become revenue, and how fast?
  Attribution     Which model, and where does the choice matter?
  Journeys        How do buyers reach us before they become leads?
  Campaigns       Which campaigns earn more than their share - beyond chance?
  Data & Method   What was fixed, assumed and flagged in the data.

DOMAIN RULES THE PAGES OBEY (PROJECT_STATE D33-D38)
  * One as-of date: nothing after 31 Aug 2026 is counted anywhere except on the
    Data & Method page, where post-period records are shown as such.
  * Attributed revenue is dated by booking date, so it ties to revenue booked.
  * Quarterly charts keep to complete quarters (DimDate[IsQuarterComplete]):
    2026 Q3 holds two of its three months and would read as a collapse.
  * Conversion trends keep to mature cohorts (Lead to Customer % (Mature Cohorts)).
  * CTR, CPC and CPM are identical on every channel in this data, so they are
    shown for paid media in total and never ranked.
  * Colour marks only differences larger than chance, through colour MEASURES with
    a dead zone (|z| < 2 stays white) - a gradient would tint noise.
  * Absolute ROAS, CPL and CAC sit beside a data note: the ad and CRM extracts are
    on different scales (D25).

PRESENTATION RULES LEARNED FROM THE FIRST RENDER (Validation/evidence/phase4)
  * Money cards show two decimals of their display unit ($1.09bn, not $1bn);
    count cards show every digit (10,908, not 11K).
  * Monthly series use a date column: a text month over 32 months truncates.
  * Integer categories (journey length 1-6) are forced onto a categorical axis.
  * An area chart's value axis starts at zero; bars and columns always do.
  * Fields carry display names, so no raw column name reaches a legend or axis.

Usage:  python Python/04_generate_report.py [--only KEY] [--check]
        --only   write ONE page (KEY from NAV_ITEMS) for a rendering check: Power BI
                 Desktop does not reliably open a requested page (Phase 3 finding)
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
RP = PBI / "OmnichannelAttribution.Report"
PAGES_DIR = RP / "definition" / "pages"
DEF = PBI / "OmnichannelAttribution.SemanticModel" / "definition"
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
CX = NAV_W + MARGIN                  # content starts at 184
CW = W - CX - MARGIN                 # content width 1080
HEADER_Y, HEADER_H = 8, 40
SLICER_Y, SLICER_H = 52, 62          # 44 px clipped the dropdown box; the themed outline needs 62
KPI_Y, KPI_H = 122, 70
ROW2_Y, ROW2_H = 204, 246
ROW3_Y, ROW3_H = 462, 196
NOTE_Y, NOTE_H = 668, 44

# Colour theme - the client's reference design ("command centre"): a near-black
# canvas, dark panels outlined in green with a faint neon glow, lime-neon accents,
# light text. Applied twice on purpose: a registered custom theme (THEME below) sets
# the defaults every visual inherits, and the explicit colours here win wherever a
# visual carries its own formatting.
PAGE_BG, PANEL, PANEL_ALT = "#050805", "#0A120A", "#0D160D"
BORDER, GRID = "#2A4F18", "#1A2C14"
NEON, NEON_MID, NEON_DARK, NEON_PALE = "#9AE62E", "#5DB523", "#3F7F1A", "#D7F58C"
INK, MUTED = "#E3EEDB", "#8FA387"               # text on dark panels
ACCENT, ACCENT_LIGHT, NEUTRAL = NEON, NEON_DARK, "#61735A"
NEGATIVE = "#E5484D"
# Series palette: greens of clearly different lightness, plus a teal-green and a
# yellow-green, so seven channels stay distinguishable inside a green scheme.
DATA_COLOURS = ["#9AE62E", "#3FA535", "#D7F58C", "#1E7A46", "#B8E04A", "#5CCB8A", "#6B8F2A",
                "#E9F9C0", "#2F5A1A", "#8FD19E"]
THEME_FILE = "OmnichannelNeon.json"

# Navigation rail - project 1's geometry, validated there; colours from the theme.
SB_PAD, SB_BTN_H, SB_GAP, SB_TOP, SB_FONT = 10, 38, 5, 64, 10
SB_BTN_W = NAV_W - 2 * SB_PAD        # 148
SB_BG_DEFAULT, SB_BG_SELECTED = "#0C150C", NEON
SB_FG_DEFAULT, SB_FG_SELECTED = INK, "#071007"
NAV_ITEMS = [("Executive", "exec"), ("Channels", "channels"), ("Funnel", "funnel"),
             ("Attribution", "attribution"), ("Journeys", "journeys"), ("Campaigns", "campaigns"),
             ("Data & Method", "method")]

CAMP, DATE, FUN, TP, LF, AM = "DimCampaign", "DimDate", "DimFunnelStage", "FactTouchpoint", "FactLeadFunnel", "DimAttributionModel"
MANIFEST_ROWS = []


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
    """sort: a measure name, or (table, column) to sort by a category."""
    q = {"queryState": {r: {"projections": p} for r, p in roles.items()}}
    if sort:
        field = measure_ref(sort) if isinstance(sort, str) else column_ref(*sort)
        q["sortDefinition"] = {"sort": [{"field": field, "direction": "Descending" if desc else "Ascending"}],
                               "isDefaultSort": False}
    return q


def colours(pairs):
    """Series colour per measure - the dataPoint shape project 1 rendered."""
    return {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit_s(c)}}},
                           "selector": {"metadata": f"_Measures.{m}"}} for m, c in pairs]}


DATA_LABELS = {"labels": [{"properties": {"show": lit_b(True)}}]}
CATEGORICAL_AXIS = {"categoryAxis": [{"properties": {"axisType": lit_s("Categorical")}}]}
ZERO_BASED = {"valueAxis": [{"properties": {"start": lit_n(0)}}]}
DONUT_PERCENT = {"labels": [{"properties": {"labelStyle": lit_s("Percent of total")}}]}


CHROMELESS = {"textbox", "actionButton"}


def container(panel):
    """Visual container: a dark panel with a green outline and a faint neon glow,
    or nothing at all for text and navigation."""
    if not panel:
        return {"background": [{"properties": {"show": lit_b(False)}}],
                "border": [{"properties": {"show": lit_b(False)}}]}
    return {"background": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(PANEL)}},
                                           "transparency": lit_n(0)}}],
            "border": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(BORDER)}},
                                       "radius": lit_n(6)}}],
            "dropShadow": [{"properties": {"show": lit_b(True), "color": {"solid": {"color": lit_s(NEON)}},
                                           "position": lit_s("Outer"), "preset": lit_s("Custom"),
                                           "shadowBlur": lit_n(8), "shadowDistance": lit_n(0),
                                           "shadowSpread": lit_n(0), "transparency": lit_n(85)}}]}


def visual(seed, vtype, box, tab, q=None, objects=None, title=None, filters=None, why="", title_size=10,
           panel=None):
    # Mirrors how Power BI itself saves a visual (Phase 3 save-diff), so a save of
    # an unchanged report is a no-op in Git.
    x, y, w, h = box
    position = {"x": x, "y": y, "z": 0, "width": w, "height": h}
    if tab:                                    # Power BI omits tabOrder 0
        position["tabOrder"] = tab
    v = {"$schema": VISUAL_SCHEMA, "name": sid(seed), "position": position, "visual": {"visualType": vtype}}
    if q:
        q = json.loads(json.dumps(q))
        q.get("sortDefinition", {}).pop("isDefaultSort", None)      # dropped when false
        qs = q["queryState"]
        if vtype == "scatterChart":                                  # X measure is marked active
            for p in qs.get("X", {}).get("projections", []):
                p["active"] = True
        if vtype == "tableEx":
            # A table must carry NO 'active' flags: with them it renders BLANK although
            # its query returns data (Phase 3, decision D32).
            for p in qs.get("Values", {}).get("projections", []):
                p.pop("active", None)
        v["visual"]["query"] = q
    if vtype == "decompositionTreeVisual" and not objects:          # default bars per level
        objects = {"tree": [{"properties": {"effectiveBarsPerLevel": lit_l(3)}}]}
    if objects:
        v["visual"]["objects"] = objects
    vco = container(vtype not in CHROMELESS if panel is None else panel)
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
    """Background colour of `shown_measure` cells taken from a measure that returns a
    hex colour ('format by field value'). The colour measures leave |z| < 2 white:
    a gradient would tint differences that chance explains."""
    return [{"properties": {"backColor": {"solid": {"color": {"expr": measure_ref(colour_measure)}}}},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                          "metadata": f"_Measures.{shown_measure}"}}]


def top_n(seed, table, column, n):
    return {"name": sid(seed + ".topn"), "field": column_ref(table, column), "type": "VisualTopN",
            "filter": {"Version": 2, "From": [{"Name": table[0].lower(), "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"VisualTopN": {"ItemCount": n}}}]}}


def is_true(seed, table, column):
    """Visual-level basic filter: column = true. Inside a filter's Where clause the
    column refers to the alias declared in From (Source), unlike a projection.
    Proven by render: the ribbon stops at the last complete quarter."""
    alias = table[0].lower()
    return {"name": sid(seed + "." + column), "field": column_ref(table, column), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": alias, "Entity": table, "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": column}}],
                           "Values": [[{"Literal": {"Value": "true"}}]]}}}]}}


def split(weights, y, h, x0=CX, total=CW):
    """Boxes across the content width. weights: a count, or relative widths."""
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
    """paragraphs: strings, or lists of (text, bold) or (text, bold, colour) runs."""
    paras = []
    for p in paragraphs:
        runs = [(p, False)] if isinstance(p, str) else p
        paras.append({"textRuns": [{"value": r[0], "textStyle": {"fontSize": f"{size}pt",
                                                                 "color": r[2] if len(r) > 2 else colour,
                                                                 **({"fontWeight": "bold"} if r[1] else {})}}
                                   for r in runs]})
    return visual(seed, "textbox", box, tab, objects={"general": [{"properties": {"paragraphs": paras}}]})


def card(seed, measure, label, box, tab, size=20, colour=NEON, kind=None, font="Consolas", panel=None):
    """Classic card - project 1's proven shape; the label is the container title.
    kind 'money': auto display unit with two decimals ($1.09bn); 'count': every digit.
    Headline numbers are neon in a monospaced face, as in the reference design."""
    labels = {"fontSize": lit_n(size), "color": {"solid": {"color": lit_s(colour)}}}
    if font:
        labels["fontFamily"] = lit_s(font)
    if kind == "money":
        labels |= {"labelDisplayUnits": lit_n(0), "labelPrecision": lit_l(2)}
    elif kind == "count":
        labels |= {"labelDisplayUnits": lit_n(1)}
    objects = {"labels": [{"properties": labels}], "categoryLabels": [{"properties": {"show": lit_b(False)}}]}
    return visual(seed, "card", box, tab, query({"Values": [pm(measure)]}), objects, title=label, title_size=9,
                  why=f"Headline figure: {measure}", panel=panel)


def slicer(seed, table, column, label, box, tab):
    objects = {"data": [{"properties": {"mode": lit_s("Dropdown")}}],
               "header": [{"properties": {"show": lit_b(True), "text": lit_s(label), "fontSize": lit_n(9),
                                          "fontColor": {"solid": {"color": lit_s(MUTED)}}}}]}
    return visual(seed, "slicer", box, tab, query({"Values": [pc(table, column)]}), objects, title="",
                  why=f"Filter by {label}")


def nav_button(seed, label, target, selected, y, tab):
    objects = {
        "icon": [{"properties": {"show": lit_b(False)}}],
        "outline": [{"properties": {"show": lit_b(not selected)}},
                    {"properties": {"lineColor": {"solid": {"color": lit_s(BORDER)}}}, "selector": {"id": "default"}}],
        "fill": [{"properties": {"show": lit_b(True)}},
                 {"properties": {"fillColor": {"solid": {"color": lit_s(SB_BG_SELECTED if selected else SB_BG_DEFAULT)}},
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
    """Rail, page title and the context line every page carries."""
    v = [textbox(f"{key}.rail.hdr", [[("OMNICHANNEL", True, INK)], [("ATTRIBUTION", True, NEON)]],
                 (SB_PAD, 12, SB_BTN_W, 44), 0, size=10)]
    for i, (label, target) in enumerate(NAV_ITEMS):
        v.append(nav_button(f"{key}.nav.{target}", label, page_id(target), target == key,
                            SB_TOP + i * (SB_BTN_H + SB_GAP), len(v)))
    v.append(textbox(f"{key}.rail.ftr", ["Synthetic portfolio dataset", "- not client data"],
                     (SB_PAD, 664, SB_BTN_W, 44), len(v), size=8, colour=MUTED))
    v.append(textbox(f"{key}.title", [[(title, True)]], (CX, HEADER_Y, 560, HEADER_H), len(v), size=16))
    v.append(card(f"{key}.context", "Report Context", "", (W - MARGIN - 500, HEADER_Y, 500, HEADER_H), len(v),
                  size=10, colour=MUTED, font="Segoe UI", panel=False))   # not the monospaced number face: it truncated
    return v


def kpis(key, items, v, y=KPI_Y):
    """items: (measure, label, kind)."""
    for (measure, label, kind), box in zip(items, split(len(items), y, KPI_H)):
        v.append(card(f"{key}.kpi.{measure}", measure, label, box, len(v), kind=kind))


def note(key, lead, text, v):
    v.append(textbox(f"{key}.note", [[(lead + "  ", True), (text, False)]], (CX, NOTE_Y, CW, NOTE_H), len(v),
                     size=9, colour=MUTED))


def slicers(key, specs, v):
    for i, (table, column, label) in enumerate(specs):
        v.append(slicer(f"{key}.sl.{column}", table, column, label, (CX + i * 212, SLICER_Y, 200, SLICER_H), len(v)))


# ------------------------------------------------------------------- pages ---
def page_exec():
    k = "exec"
    v = shell(k, "Executive Summary")
    slicers(k, [(CAMP, "Region", "Region"), (CAMP, "ChannelGroup", "Channel group")], v)
    kpis(k, [("Spend USD", "Channel cost", "money"), ("Revenue USD", "Revenue booked", "money"),
             ("Leads", "Leads", "count"), ("Customers", "Customers", "count"),
             ("Lead to Customer %", "Lead to customer", None), ("Revenue YTD vs PY %", "Revenue YTD vs last year", None)], v)
    b = split([34, 72], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.kpi", "kpi", b[0], len(v),
                    query({"Indicator": [pm("Revenue Cumulative YTD USD")], "Goal": [pm("Revenue Cumulative PYTD USD")],
                           "TrendLine": [pc(DATE, "MonthStart")]}),
                    title="Revenue year to date vs the same days last year",
                    why="Like-for-like YTD growth with the running total behind it; a single month's YoY swings "
                        "with deal timing, so it is not the headline."))
    v.append(visual(f"{k}.combo", "lineStackedColumnComboChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("Leads")],
                           "Y2": [pm("Lead to Customer % (Mature Cohorts)", "Lead to customer (mature cohorts)")]}),
                    # The combo ignores a column colour override, so its columns take the neon
                    # series colour; the line is near-white to stay readable over them.
                    objects=colours([("Leads", NEON_DARK), ("Lead to Customer % (Mature Cohorts)", "#F4FAEE")]),
                    title="Leads created (columns) and lead-to-customer conversion of mature cohorts (line)",
                    why="Volume and quality on two scales; the line stops where cohorts are still converting."))
    b = split([34, 72], ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.donut", "donutChart", b[0], len(v),
                    query({"Category": [pc(CAMP, "ChannelGroup", "Channel group")], "Y": [pm("Spend USD", "Channel cost")]}),
                    objects=DONUT_PERCENT,
                    title="Channel cost by channel group", why="Budget split: part-to-whole with six parts."))
    v.append(visual(f"{k}.rev", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")],
                           "Y": [pm("Revenue USD", "Revenue booked"), pm("Revenue PY USD", "Same month last year")]}),
                    objects=colours([("Revenue USD", ACCENT), ("Revenue PY USD", NEUTRAL)]),
                    title="Revenue booked by month vs the same month last year",
                    why="Monthly revenue against last year - shows how noisy single months are."))
    note(k, "Data note.",
         "Synthetic dataset. Ad and CRM extracts are on different scales (about 5,100 clicks per lead vs 20-50 typical "
         "in B2B), so channel cost is about 35x revenue: compare ROAS, CPL and CAC between channels, not with "
         "benchmarks. Figures count activity by the as-of date; January 2024 revenue is low: the data starts then "
         "and deals take about a month to close.", v)
    return {"name": page_id(k), "displayName": "Executive Summary"}, v, []


def page_channels():
    k = "channels"
    v = shell(k, "Channels & Budget")
    slicers(k, [(CAMP, "Region", "Region")], v)
    kpis(k, [("Paid Media Spend USD", "Paid media spend", "money"), ("Paid CTR", "Paid CTR", None),
             ("Paid CPC USD", "Paid CPC", None), ("Paid CPM USD", "Paid CPM", None),
             ("Click-to-Lead %", "Click to lead", None)], v)
    b = split(2, ROW2_Y, ROW2_H)
    # Columns, not bars: seven channels x two bars scrolled Organic Search out of a
    # 246 px bar chart (second render); side by side they all fit.
    v.append(visual(f"{k}.shares", "clusteredColumnChart", b[0], len(v),
                    query({"Category": [pc(CAMP, "ChannelName", "Channel")],
                           "Y": [pm("Spend Share %", "Share of channel cost"),
                                 pm("Attributed Revenue Share %", "Share of attributed revenue")]},
                          sort="Spend Share %"),
                    objects=colours([("Spend Share %", NEUTRAL), ("Attributed Revenue Share %", ACCENT)]),
                    title="Share of channel cost vs share of attributed revenue",
                    why="Does credit follow budget? Scale-free, so valid despite the ad/CRM scale gap."))
    # A date axis, not quarter labels: in a small panel ten rotated quarter labels
    # scrolled, showing only the first five quarters (second render).
    v.append(visual(f"{k}.cpl", "lineChart", b[1], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Month")], "Y": [pm("CPL USD", "Cost per lead")],
                           "Rows": [pc(CAMP, "Region", "Region")]}),
                    objects={**colours([("CPL USD", ACCENT)]),
                             "smallMultiplesLayout": [{"properties": {"rowCount": lit_l(2), "columnCount": lit_l(3)}}]},
                    title="Cost per lead by month, one panel per region",
                    why="Same trend, five regions, no overplotting; the whole period visible in every panel."))
    b = split(2, ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.treemap", "treemap", b[0], len(v),
                    query({"Group": [pc(CAMP, "Region", "Region")], "Details": [pc(CAMP, "ChannelName", "Channel")],
                           "Values": [pm("Spend USD", "Channel cost")]}),
                    # Dark tile labels: white read at ~1.2:1 on the pale-lime and neon tiles.
                    objects={"labels": [{"properties": {"color": {"solid": {"color": lit_s("#071007")}}}}],
                             "categoryLabels": [{"properties": {"color": {"solid": {"color": lit_s("#071007")}}}}]},
                    title="Channel cost by region, then channel", why="Hierarchical budget allocation."))
    v.append(visual(f"{k}.ribbon", "ribbonChart", b[1], len(v),
                    query({"Category": [pc(DATE, "QuarterLabel", "Quarter")], "Series": [pc(CAMP, "ChannelName", "Channel")],
                           "Y": [pm("Attributed Revenue USD", "Attributed revenue")]}),
                    filters=[is_true(f"{k}.ribbon", DATE, "IsQuarterComplete")],
                    title="Channel rank by attributed revenue, complete quarters",
                    why="Rank changes over time (booking-date quarters): Meta Ads leads 9 of 10 complete quarters "
                        "while Display ranges from 1st to 6th."))
    note(k, "Reading this page.",
         "CTR, CPC and CPM are near-identical on every channel in this data (CTR 4.21-4.25%), so they are reported for "
         "paid media in total and not ranked by channel. Revenue shares use the attribution model shown top right. "
         "Quarterly charts show complete quarters only.", v)
    return {"name": page_id(k), "displayName": "Channels & Budget"}, v, []


def page_funnel():
    k = "funnel"
    v = shell(k, "Funnel & Pipeline")
    slicers(k, [(CAMP, "Region", "Region"), (LF, "Segment", "Segment")], v)
    kpis(k, [("Opportunities", "Opportunities", "count"), ("Customers", "Customers", "count"),
             ("Win Rate %", "Win rate (closed deals)", None), ("Open Pipeline USD", "Open pipeline", "money"),
             ("Avg Days Lead to Opportunity", "Days lead to opportunity", None),
             ("Avg Days Opportunity to Revenue", "Days opportunity to close", None)], v)
    b = split([24, 24, 52], ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.funnel", "funnel", b[0], len(v),
                    query({"Category": [pc(FUN, "StageName", "Stage")], "Y": [pm("Funnel Stage Leads", "Leads")]}),
                    objects={"labels": [{"properties": {"labelDisplayUnits": lit_n(1)}}]},
                    title="Lead funnel by the as-of date", why="Stage-by-stage attrition; stages nest by construction."))
    v.append(visual(f"{k}.stageconv", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(FUN, "StageName", "Stage")],
                           "Y": [pm("Conversion From Previous Stage %", "Conversion from previous stage")]},
                          sort=(FUN, "StageName"), desc=False),
                    objects={**colours([("Conversion From Previous Stage %", ACCENT)]), **DATA_LABELS},
                    title="Conversion from the previous stage", why="Where the funnel leaks, stage by stage."))
    v.append(visual(f"{k}.heatmap", "pivotTable", b[2], len(v),
                    query({"Rows": [pc(LF, "Segment", "Segment")], "Columns": [pc(CAMP, "ChannelGroup", "Channel group")],
                           "Values": [pm("Lead to Customer %", "Lead to customer")]}),
                    objects={"values": field_colour("Heatmap Signal Colour", "Lead to Customer %")},
                    title="Lead to customer by segment and channel group (shaded only when beyond chance)",
                    why="Two-way comparison coloured by statistical distance, not by size."))
    b = split(2, ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.cohort", "lineChart", b[0], len(v),
                    query({"Category": [pc(DATE, "MonthStart", "Lead cohort month")],
                           "Y": [pm("Lead to Customer % (Mature Cohorts)", "Lead to customer (mature cohorts)")]}),
                    objects=colours([("Lead to Customer % (Mature Cohorts)", ACCENT)]),
                    title="Lead-to-customer conversion by lead cohort month (mature cohorts)",
                    why="Is lead quality changing? Young cohorts are excluded so the line does not fake a collapse."))
    v.append(visual(f"{k}.velocity", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(LF, "DaysOpportunityToRevenue", "Days from opportunity to close")],
                           "Y": [pm("Customers", "Deals")]},
                          sort=(LF, "DaysOpportunityToRevenue"), desc=False),
                    objects=colours([("Customers", ACCENT)]),
                    title="Deals by days from opportunity to close", why="Sales-cycle distribution as a histogram."))
    note(k, "Reading this page.",
         "Stages count leads that had reached at least that stage by the as-of date. A heatmap cell is shaded only when "
         "its rate differs from the portfolio by more than chance (|z| >= 2); unshaded cells are within noise. The cohort "
         "line omits cohorts younger than the 58-day conversion window.", v)
    return {"name": page_id(k), "displayName": "Funnel & Pipeline"}, v, []


def page_attribution():
    k = "attribution"
    v = shell(k, "Attribution Models")
    # A label beside an untitled selector: with a container title the themed panel
    # clipped the button text, and the page's lower row lost the height its Top 10
    # needs (themed render).
    v.append(textbox(f"{k}.model.label", [[("ATTRIBUTION MODEL", True, NEON)],
                                          [("drives every attributed figure", False, MUTED)]],
                     (CX, SLICER_Y + 6, 170, 50), len(v), size=9))
    # 68 px: at 56 px inside the themed panel the button text was cut at its baseline.
    sl = visual(f"{k}.model", "advancedSlicerVisual", (CX + 182, SLICER_Y, CW - 182, 68), len(v),
                query({"Values": [pc(AM, "ModelName")]}),
                objects={"layout": [{"properties": {"rowCount": lit_l(1), "columnCount": lit_l(5)}}]},
                title="", why="Button selector for the model in use (untitled; labelled beside it).")
    v.append(sl)
    top = SLICER_Y + 68 + GAP
    # The matrix needs ~610 px for five dollar columns; at half the row its fifth
    # column (Time-Decay) was cut off in the second render.
    b = split([42, 58], top, 250)
    compare = visual(f"{k}.compare", "clusteredColumnChart", b[0], len(v),
                     query({"Category": [pc(CAMP, "ChannelName", "Channel")], "Series": [pc(AM, "ModelName", "Model")],
                            "Y": [pm("Attributed Revenue Share %", "Share of attributed revenue")]}),
                     title="Attributed revenue share by channel under each of the five models",
                     why="All five models side by side - unaffected by the selector.")
    v.append(compare)
    matrix = visual(f"{k}.matrix", "pivotTable", b[1], len(v),
                    query({"Rows": [pc(CAMP, "ChannelName", "Channel")], "Columns": [pc(AM, "ModelName", "Model")],
                           "Values": [pm("Attributed Revenue USD", "Attributed revenue")]}),
                    # No total ACROSS models: the measure never sums models (D18), so a Total
                    # column would show the default model's figure under a "Total" heading
                    # (third render). The Total ROW stays - it is the conservation proof.
                    objects={"subTotals": [{"properties": {"columnSubtotals": lit_b(False)}}]},
                    title="Attributed revenue by channel and model (USD) - every model totals the same",
                    why="Exact figures behind the comparison - unaffected by the selector.")
    v.append(matrix)
    y2 = top + 250 + GAP
    b = split([40, 30, 30], y2, NOTE_Y - GAP - y2)
    v.append(visual(f"{k}.sensitivity", "clusteredBarChart", b[0], len(v),
                    query({"Category": [pc(CAMP, "CampaignName", "Campaign")],
                           "Y": [pm("Attribution Sensitivity %", "Model sensitivity")]},
                          sort="Attribution Sensitivity %"),
                    objects={**colours([("Attribution Sensitivity %", ACCENT)]), **DATA_LABELS,
                             # campaign names are long: let the label area take up to 45% of the width;
                             # no axis titles and no value axis (the data labels carry the values), so
                             # all ten bars fit without a scrollbar
                             "categoryAxis": [{"properties": {"maxMarginFactor": lit_l(45),
                                                              "showAxisTitle": lit_b(False)}}],
                             "valueAxis": [{"properties": {"show": lit_b(False), "showAxisTitle": lit_b(False)}}]},
                    filters=[top_n(f"{k}.sensitivity", CAMP, "CampaignName", 10)],
                    title="Top 10 campaigns where the model choice matters most",
                    why="Spread across the five models as a share of their average."))
    v.append(visual(f"{k}.shift", "waterfallChart", b[1], len(v),
                    query({"Category": [pc(CAMP, "ChannelName", "Channel")],
                           "Y": [pm("Credit Shift vs Last Touch USD", "Credit shift vs Last Touch")]}),
                    objects={"sentimentColors": [{"properties": {
                        "increaseFill": {"solid": {"color": lit_s(NEON)}},
                        "decreaseFill": {"solid": {"color": lit_s(NEGATIVE)}},
                        "totalFill": {"solid": {"color": lit_s(NEUTRAL)}}}}]},
                    title="Credit the selected model moves vs Last Touch",
                    why="Signed shifts that net to zero: every model conserves revenue."))
    v.append(visual(f"{k}.position", "hundredPercentStackedBarChart", b[2], len(v),
                    query({"Category": [pc(CAMP, "ChannelName", "Channel")],
                           "Series": [pc(TP, "PositionBand", "Journey position")], "Y": [pm("Touchpoints")]}),
                    title="Where each channel's touches sit in the journey",
                    why="Every channel sits at similar positions, which is why models agree at channel level."))
    note(k, "Reading this page.",
         "Every model re-divides the same revenue booked. Channel shares barely move between models because every "
         "channel's touches sit at similar journey positions (right); campaign credit moves far more (left).", v)
    # The comparison visuals show all five models side by side, so the selector must not filter them.
    interactions = [{"source": sl["name"], "target": t["name"], "type": "NoFilter"} for t in (compare, matrix)]
    return {"name": page_id(k), "displayName": "Attribution Models"}, v, interactions


def page_journeys():
    k = "journeys"
    v = shell(k, "Customer Journeys")
    slicers(k, [(CAMP, "Region", "Region"), (CAMP, "ChannelGroup", "Channel group")], v)
    kpis(k, [("Touchpoints", "Touchpoints", "count"), ("Avg Touches per Journey", "Touches per journey", None),
             ("Multi-Channel Journey %", "Multi-channel journeys", None),
             ("Avg Days First Touch to Lead", "Days first touch to lead", None)], v)
    b = split(2, ROW2_Y, ROW2_H)
    v.append(visual(f"{k}.length", "columnChart", b[0], len(v),
                    query({"Category": [pc(LF, "TouchCount", "Touches in journey")],
                           "Series": [pc(LF, "DistinctChannels", "Channels in journey")], "Y": [pm("Leads")]},
                          sort=(LF, "TouchCount"), desc=False),
                    objects=CATEGORICAL_AXIS,
                    title="Leads by journey length, split by channels in the journey",
                    why="Journey length and channel mix in one stacked view."))
    v.append(visual(f"{k}.timing", "areaChart", b[1], len(v),
                    query({"Category": [pc(TP, "DaysBeforeLead", "Days before lead creation")], "Y": [pm("Touchpoints")]},
                          sort=(TP, "DaysBeforeLead"), desc=False),
                    objects={**colours([("Touchpoints", ACCENT)]), **ZERO_BASED},
                    title="Touches by days before the lead was created",
                    why="When in the month-long journey touches happen - on a zero-based axis."))
    b = split(2, ROW3_Y, ROW3_H)
    v.append(visual(f"{k}.channels", "donutChart", b[0], len(v),
                    query({"Category": [pc(LF, "DistinctChannels", "Channels in journey")], "Y": [pm("Leads")]}),
                    objects=DONUT_PERCENT,
                    title="Leads by number of channels in the journey", why="How omnichannel the buyer is."))
    v.append(visual(f"{k}.lengthconv", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc(LF, "TouchCount", "Touches in journey")],
                           "Y": [pm("Lead to Customer %", "Lead to customer")]},
                          sort=(LF, "TouchCount"), desc=False),
                    objects={**colours([("Lead to Customer %", ACCENT)]), **DATA_LABELS, **CATEGORICAL_AXIS},
                    title="Lead-to-customer conversion by journey length",
                    why="Do longer journeys convert better? The question behind every multi-touch model."))
    note(k, "Reading this page.",
         "A journey is the lead's touches before it was created, ordered by date. Channel group and region filter the "
         "lead's own campaign for lead-level figures and the touched campaign for touch-level figures.", v)
    return {"name": page_id(k), "displayName": "Customer Journeys"}, v, []


def page_campaigns():
    k = "campaigns"
    v = shell(k, "Campaign Scorecard")
    slicers(k, [(CAMP, "Region", "Region"), (CAMP, "ChannelGroup", "Channel group")], v)
    b = split(2, KPI_Y, 270)
    v.append(visual(f"{k}.scatter", "scatterChart", b[0], len(v),
                    query({"Category": [pc(CAMP, "CampaignName", "Campaign")],
                           "Series": [pc(CAMP, "ChannelGroup", "Channel group")],
                           "X": [pm("Spend USD", "Channel cost")], "Y": [pm("Attributed Revenue USD", "Attributed revenue")],
                           "Size": [pm("Attributed Customers", "Customers credited")]}),
                    title="Campaigns: channel cost vs attributed revenue (bubble = customers credited)",
                    why="Efficiency across 300 campaigns with volume."))
    v.append(visual(f"{k}.decomp", "decompositionTreeVisual", b[1], len(v),
                    query({"Analyze": [pm("Attributed Revenue USD", "Attributed revenue")],
                           "ExplainBy": [pc(CAMP, "Region"), pc(CAMP, "ChannelGroup"), pc(CAMP, "ChannelName"),
                                         pc(CAMP, "CampaignName")]}),
                    title="Attributed revenue: region, channel group, channel, campaign",
                    why="Guided drill into where attributed revenue comes from."))
    y2 = KPI_Y + 270 + GAP
    v.append(visual(f"{k}.scorecard", "tableEx", (CX, y2, CW, NOTE_Y - GAP - y2), len(v),
                    query({"Values": [pc(CAMP, "CampaignName", "Campaign"), pc(CAMP, "ChannelName", "Channel"),
                                      pm("Spend USD", "Channel cost"), pm("Leads"),
                                      pm("Attributed Customers", "Customers credited"),
                                      pm("Attributed Revenue USD", "Attributed revenue"),
                                      pm("Revenue-to-Spend Index", "Index"), pm("Campaign Index Signal", "Signal"),
                                      pm("Attribution Sensitivity %", "Model sensitivity")]},
                          sort="Revenue-to-Spend Index"),
                    objects={"values": field_colour("Campaign Signal Colour", "Revenue-to-Spend Index")},
                    title="Campaign scorecard - index shaded only where it is beyond chance",
                    why="Detail per campaign with a statistical signal beside the ranking."))
    note(k, "Reading this page.",
         "Index = share of attributed revenue / share of channel cost (1.0 = fair share). Signal compares a campaign's "
         "revenue with what its cost share would earn, in standard errors: |z| >= 3 clear, 2-3 possible. With 300 "
         "campaigns about 14 reach |z| >= 2 by chance alone, so most index differences are noise.", v)
    return {"name": page_id(k), "displayName": "Campaign Scorecard"}, v, []


def page_method():
    k = "method"
    v = shell(k, "Data & Method")
    kpis(k, [("Aliases Resolved", "Campaign aliases resolved", "count"), ("Alias Mismatches", "Alias mismatches", "count"),
             ("Stale Stage Labels", "Stale CRM stage labels", "count"),
             ("Journeys With Contradicting Sequence", "Sequence contradicts dates", "count"),
             ("Spend Lines Before Campaign Start", "Spend lines pre-start", "count"),
             ("Post-Period Bookings", "Bookings after as-of", "count")], v, y=SLICER_Y)
    y = SLICER_Y + KPI_H + GAP
    b = split(3, y, 240)
    v.append(visual(f"{k}.gauge", "gauge", b[0], len(v),
                    query({"Y": [pm("Alias Resolution %", "Aliases resolved")], "MaxValue": [pm("Alias Resolution Target %")],
                           "TargetValue": [pm("Alias Resolution Target %", "Target")]}),
                    title="Campaign aliases resolved by the Power Query rules", why="A rate against its 100% service level."))
    v.append(visual(f"{k}.styles", "clusteredColumnChart", b[1], len(v),
                    query({"Category": [pc("CampaignAliasResolution", "AliasStyle", "Naming style")],
                           "Y": [pm("Aliases Resolved", "Aliases resolved")]}),
                    objects={**colours([("Aliases Resolved", ACCENT)]), **DATA_LABELS},
                    title="Aliases resolved by naming style", why="Every naming style is handled by rules R1-R4."))
    v.append(visual(f"{k}.fx", "tableEx", b[2], len(v),
                    query({"Values": [pc("FxRate", "CurrencyCode", "Currency"), pc("FxRate", "RateToUSD", "Rate to USD"),
                                      pc("FxRate", "EffectiveFrom", "From"), pc("FxRate", "EffectiveTo", "To")]}),
                    title="Planning exchange rates to USD (not market data)", why="The one currency assumption, in full."))
    y3 = y + 240 + GAP
    h3 = H - MARGIN - y3
    left, right = split([30, 70], y3, h3)
    lx, ly, lw, lh = left
    cw, ch = (lw - GAP) // 2, (lh - GAP) // 2
    for i, (m, lbl, kind) in enumerate([("Clicks per Lead", "Ad clicks per lead", "count"),
                                        ("Spend to Revenue Ratio", "Cost per $ of revenue", None),
                                        ("Post-Period Revenue USD", "Revenue after as-of", "money"),
                                        ("Conversion Window Days", "Conversion window (days)", "count")]):
        r, c = divmod(i, 2)
        v.append(card(f"{k}.scale.{m}", m, lbl, (lx + c * (cw + GAP), ly + r * (ch + GAP), cw, ch), len(v),
                      size=16, kind=kind))
    v.append(textbox(f"{k}.method", [
        [("As of 31 Aug 2026. ", True), ("Every figure counts only what happened by then: an opportunity once opened, a "
                                         "customer once revenue is booked. Records dated later appear only on this page.", False)],
        [("Attribution. ", True), ("Five models precomputed in SQL and checked against an independent Python "
                                   "implementation. Attributed revenue is dated by booking date, so every model's monthly "
                                   "total equals the revenue booked that month.", False)],
        [("Scale. ", True), ("The ad and CRM extracts are on different scales (cards at left). Figures are reported as "
                             "measured, never rescaled - compare them relatively.", False)],
        [("Media rates. ", True), ("CTR, CPC and CPM are near-identical on every channel, so they are not ranked.", False)],
        [("Signal. ", True), ("Heatmap and scorecard shading marks only differences larger than chance.", False)],
        [("Currency. ", True), ("Spend in AUD, EUR, GBP and USD is converted at the planning rates above.", False)],
        [("Synthetic data. ", True), ("A portfolio dataset - never client data.", False)],
    ], right, len(v), size=9))
    return {"name": page_id(k), "displayName": "Data & Method"}, v, []


PAGES = [page_exec, page_channels, page_funnel, page_attribution, page_journeys, page_campaigns, page_method]


# -------------------------------------------------------------------- theme ---
def solid(colour):
    return {"solid": {"color": colour}}


PAGE_OBJECTS = {"background": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}],
                "outspace": [{"properties": {"color": {"solid": {"color": lit_s(PAGE_BG)}}, "transparency": lit_n(0)}}]}

# The registered custom theme: defaults every visual inherits - canvas, panels,
# text, axes, gridlines, tables, slicers - so nothing falls back to the light base theme.
THEME = {
    "name": "Omnichannel Neon",
    "dataColors": DATA_COLOURS,
    "foreground": INK, "foregroundNeutralSecondary": MUTED, "foregroundNeutralTertiary": NEUTRAL,
    "background": PANEL, "backgroundLight": PANEL_ALT, "backgroundNeutral": BORDER,
    "tableAccent": NEON, "good": NEON, "neutral": "#C9B94A", "bad": NEGATIVE,
    "maximum": NEON, "center": NEON_DARK, "minimum": PANEL, "null": NEUTRAL,
    "hyperlink": NEON, "visitedHyperlink": NEON_MID,
    "textClasses": {
        "callout": {"fontSize": 28, "fontFace": "Consolas", "color": NEON},
        "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
        "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": MUTED}},
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": solid(PANEL), "transparency": 0}],
            "border": [{"show": True, "color": solid(BORDER), "radius": 6, "width": 1}],
            "title": [{"fontColor": solid(INK), "titleWrap": True}],
            "categoryAxis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED), "gridlineColor": solid(GRID),
                              "gridlineStyle": "dotted", "showAxisTitle": True, "concatenateLabels": False}],
            "valueAxis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED), "gridlineColor": solid(GRID),
                           "gridlineStyle": "dotted", "showAxisTitle": True}],
            "y2Axis": [{"labelColor": solid(MUTED), "titleColor": solid(MUTED)}],
            "legend": [{"labelColor": solid(MUTED), "titleColor": solid(INK)}],
            # No theme-wide data-label colour: forcing one (white) overrode Power BI's
            # automatic contrast and put white labels on neon funnel bars. Labels outside
            # a shape still take the light foreground.
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
            "columnHeaders": [{"fontColor": solid(NEON), "backColor": solid(PANEL_ALT), "columnAdjustment": "growToFit"}],
            "values": [{"fontColorPrimary": solid(INK), "backColorPrimary": solid(PANEL),
                        "fontColorSecondary": solid(INK), "backColorSecondary": solid(PANEL_ALT)}],
            "total": [{"fontColor": solid(NEON), "backColor": solid(PANEL_ALT)}],
            "grid": [{"gridHorizontalColor": solid(GRID), "gridVerticalColor": solid(GRID), "outlineColor": solid(BORDER)}]}},
        "pivotTable": {"*": {
            "columnHeaders": [{"fontColor": solid(NEON), "backColor": solid(PANEL_ALT)}],
            "rowHeaders": [{"fontColor": solid(INK), "backColor": solid(PANEL), "showExpandCollapseButtons": True,
                            "legacyStyleDisabled": True}],
            "values": [{"fontColorPrimary": solid(INK), "backColorPrimary": solid(PANEL),
                        "fontColorSecondary": solid(INK), "backColorSecondary": solid(PANEL_ALT)}],
            "subTotals": [{"fontColor": solid(NEON), "backColor": solid(PANEL_ALT)}],
            "total": [{"fontColor": solid(NEON), "backColor": solid(PANEL_ALT)}],
            "grid": [{"gridHorizontalColor": solid(GRID), "gridVerticalColor": solid(GRID), "outlineColor": solid(BORDER)}]}},
        "slicer": {"*": {"items": [{"fontColor": solid(INK), "background": solid(PANEL_ALT), "padding": 4}],
                         "header": [{"fontColor": solid(MUTED)}]}},
        "advancedSlicerVisual": {"*": {"value": [{"$id": "default", "fontColor": solid(INK)}],
                                       "shapeCustomRectangle": [{"$id": "default", "tileShape": "rectangleRoundedByPixel",
                                                                 "rectangleRoundedCurve": 4}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
        "actionButton": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
    },
}


def themed_report_json(validator):
    """report.json with the custom theme registered on top of the base theme."""
    path = RP / "definition" / "report.json"
    rj = json.loads(path.read_text(encoding="utf-8-sig"))
    tc = rj["themeCollection"]
    tc["customTheme"] = {"name": THEME_FILE, "reportVersionAtImport": tc["baseTheme"]["reportVersionAtImport"],
                         "type": "RegisteredResources"}
    rj["resourcePackages"] = [p for p in rj["resourcePackages"] if p["name"] != "RegisteredResources"] + [
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
    """Power BI's save format: two-space indent, CRLF, no final newline."""
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
        page = {"$schema": PAGE_SCHEMA, **meta, "displayOption": "FitToPage", "height": H, "width": W,
                "objects": PAGE_OBJECTS}
        if inter:
            page["visualInteractions"] = inter
        pages.append((page, vis))
        for e in pval.iter_errors(page):
            print(f"  PAGE {meta['displayName']}: {e.message}"); errors += 1
        names = {v["name"] for v in vis}
        for i in inter:
            if i["source"] not in names or i["target"] not in names:
                print(f"  INTERACTION on {meta['displayName']} names a visual not on the page"); errors += 1
        if len(names) != len(vis):
            print(f"  DUPLICATE visual names on {meta['displayName']}"); errors += 1
        for v in vis:
            for e in vval.iter_errors(v):
                print(f"  VISUAL {v['visual']['visualType']}: {list(e.path)}: {e.message}"); errors += 1
            p = v["position"]
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > W or p["y"] + p["height"] > H:
                print(f"  OFF-CANVAS {v['visual']['visualType']} {p}"); errors += 1
            rr = []
            refs({k: v[k] for k in v if k != "filterConfig"}, rr)
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
        # nothing may overlap anything else on the page
        for a, b in itertools.combinations(vis, 2):
            pa, pb = a["position"], b["position"]
            ix = min(pa["x"] + pa["width"], pb["x"] + pb["width"]) - max(pa["x"], pb["x"])
            iy = min(pa["y"] + pa["height"], pb["y"] + pb["height"]) - max(pa["y"], pb["y"])
            if ix > 0 and iy > 0:
                print(f"  OVERLAP on {meta['displayName']}: {a['visual']['visualType']} / {b['visual']['visualType']}"); errors += 1
        tabs = [v["position"].get("tabOrder", 0) for v in vis]
        if len(tabs) != len(set(tabs)):
            print(f"  DUPLICATE tabOrder on {meta['displayName']}"); errors += 1
        # A page note has a 44 px band: two lines of 9 pt text. About 5.7 px per
        # character across 1,080 px gives ~185 characters a line.
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

    write_json(RP / "StaticResources" / "RegisteredResources" / THEME_FILE, THEME)
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
