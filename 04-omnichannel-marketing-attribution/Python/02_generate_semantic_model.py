# -*- coding: utf-8 -*-
"""
Phase 2 - Semantic model as code.

Writes the Power BI project (PBIP) semantic model in TMDL, plus the minimal
report shell it needs, from the declarative specification below:

    PowerBI/OmnichannelAttribution.pbip
    PowerBI/OmnichannelAttribution.SemanticModel/definition/
        model.tmdl  expressions.tmdl  relationships.tmdl  roles/  tables/
    PowerBI/OmnichannelAttribution.Report/  (definition.pbir, one page)

Files Power BI itself authored in project 1 (database.tmdl, cultures, report.json,
version.json, the base theme) are copied in once and never rewritten here.

Output matches what Power BI writes: tab indentation, CRLF, no BOM, triple-slash
descriptions directly above the object, dates as dateTime with
UnderlyingDateTimeDataType = Date. Lineage tags are uuid5 of the object path, so
a re-run produces byte-identical files and a clean Git diff.

Usage:  python Python/02_generate_semantic_model.py
"""
import json
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Python"))

NAME = "OmnichannelAttribution"
PBI = ROOT / "PowerBI"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"
DEF = SM / "definition"
NS = uuid.UUID("6f0c2a4e-8d2b-4f3e-9a51-2c7e0d4b1a90")   # fixed: deterministic tags

BOOL_FMT = '"""TRUE"";""TRUE"";""FALSE"""'


def tag(*parts):
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name):
    """TMDL-quote a name containing whitespace or . = : '"""
    return "'" + name.replace("'", "''") + "'" if any(c in name for c in " .=:'") else name


# --------------------------------------------------------------------- spec ---
@dataclass
class Col:
    name: str
    dtype: str                      # string | int64 | double | dateTime | boolean
    fmt: str = None
    hidden: bool = False
    summarize: str = "none"
    sort_by: str = None
    desc: str = None
    category: str = None
    key: bool = False


@dataclass
class Table:
    name: str
    source: str                     # analytics view name, or full M text
    desc: str
    cols: list
    hidden: bool = False
    category: str = None
    hierarchies: list = field(default_factory=list)   # (name, [level columns])


def S(n, **k): return Col(n, "string", **k)
def I(n, **k): return Col(n, "int64", **k)
def D(n, **k): return Col(n, "double", **k)
def T(n, **k): return Col(n, "dateTime", **k)
def B(n, **k): return Col(n, "boolean", **k)


ALIAS_M = """let
    Source = Sql.Database(SqlServer, SqlDatabase),
    Aliases = Source{[Schema="analytics",Item="vw_CampaignAlias"]}[Data],
    Campaigns = Source{[Schema="analytics",Item="vw_DimCampaign"]}[Data],
    // Documented cleansing rules (Documentation/data_quality_report.md):
    //   R1 case-insensitive                 R2 space, hyphen, underscore are one separator
    //   R3 separator runs collapse, trimmed R4 region synonym: AU-NZ is ANZ
    RegionSynonyms = {{"au nz", "anz"}},
    Normalise = (name as text) as text =>
        let
            Lowered = Text.Lower(Text.Trim(name)),
            Unified = Text.Replace(Text.Replace(Lowered, "-", " "), "_", " "),
            Joined = Text.Combine(List.Select(Text.Split(Unified, " "), each _ <> ""), " "),
            Synonymised = List.Accumulate(RegionSynonyms, Joined,
                (state, pair) => if Text.StartsWith(state, pair{0} & " ")
                                 then pair{1} & Text.Middle(state, Text.Length(pair{0}))
                                 else state)
        in
            Synonymised,
    CanonicalKeys = Table.AddColumn(Table.SelectColumns(Campaigns, {"CampaignID", "CampaignName"}),
                                    "MatchKey", each Normalise([CampaignName]), type text),
    AliasKeys = Table.AddColumn(Aliases, "MatchKey", each Normalise([RawCampaignName]), type text),
    Matched = Table.NestedJoin(AliasKeys, {"MatchKey"}, CanonicalKeys, {"MatchKey"}, "Canonical", JoinKind.LeftOuter),
    Expanded = Table.ExpandTableColumn(Matched, "Canonical", {"CampaignID", "CampaignName"},
                                       {"ResolvedCampaignID", "ResolvedCampaignName"}),
    WithStyle = Table.AddColumn(Expanded, "AliasStyle",
                                each Text.AfterDelimiter([RawCampaignKey], "_", {0, RelativePosition.FromEnd}), type text),
    WithStatus = Table.AddColumn(WithStyle, "ResolutionStatus",
                                 each if [ResolvedCampaignID] = null then "Unresolved"
                                      else if [ResolvedCampaignID] = [CampaignID] then "Resolved"
                                      else "Mismatch", type text),
    Typed = Table.TransformColumnTypes(WithStatus, {{"ResolvedCampaignID", type text}, {"ResolvedCampaignName", type text}})
in
    Typed"""

MEASURES_TABLE_M = """let
    Source = #table(type table [Placeholder = text], {})
in
    Source"""

TABLES = [
    Table("DimDate", "vw_DimDate",
          "Conformed calendar 2022-01-01 to 2027-06-30, generated in SQL because the supplied calendar ended "
          "before the last opportunity and revenue dates. Marked as the date table. Financial year runs July to June.",
          [T("Date", key=True, desc="Model date key: unique, contiguous, no gaps."),
           I("Year", fmt="0"), I("MonthNo", fmt="0", hidden=True),
           S("MonthName", sort_by="MonthNo"), S("MonthShort", sort_by="MonthNo"),
           I("Quarter", fmt="0", hidden=True), S("QuarterLabel"),
           I("YearMonth", fmt="0", hidden=True, desc="Sort key for YearMonthLabel."),
           S("YearMonthLabel", sort_by="YearMonth"), T("MonthStart"),
           I("ISOWeek", fmt="0"), T("WeekStart", desc="Monday of the ISO week."),
           S("DayName", sort_by="DayOfWeekNo"), I("DayOfWeekNo", fmt="0", hidden=True),
           I("FinancialYearStart", fmt="0", hidden=True), S("FinancialYear"),
           I("FinancialMonthNo", fmt="0", hidden=True),
           B("IsSourceCalendar", hidden=True, desc="True where the supplied dim_date also covers the day."),
           B("IsAfterAsOf", desc="True for days after the as-of date: no actuals exist yet."),
           B("IsQuarterComplete", desc="True when the whole quarter lies on or before the as-of date. Filter quarterly "
             "counts on it: 2026 Q3 holds two of its three months and would read as a collapse.")],
          category="Time",
          hierarchies=[("Calendar", ["Year", "QuarterLabel", "YearMonthLabel", "Date"]),
                       ("Financial", ["FinancialYear", "YearMonthLabel", "Date"])]),

    Table("DimCampaign", "vw_DimCampaign",
          "The single marketing dimension: campaign with its region, objective and channel. Channel is a level of "
          "the campaign hierarchy because every fact row's channel equals its campaign's channel (SQL check: 0 "
          "mismatches). Row-level security filters this table by Region.",
          [S("CampaignID"), S("CampaignName"), S("Region"), S("Objective"),
           T("StartDate", desc="As supplied. Unreliable: 42% of spend predates it, so it is never used as a filter."),
           S("ChannelID", hidden=True), S("ChannelName"), S("ChannelGroup"),
           B("IsPaidMedia", desc="True for Paid Search, Paid Social and Paid Display.")],
          hierarchies=[("Channel", ["ChannelGroup", "ChannelName", "CampaignName"]),
                       ("Region Campaign", ["Region", "CampaignName"])]),

    Table("DimAttributionModel", "vw_DimAttributionModel",
          "Disconnected attribution-model selector. Deliberately has no relationship: measures read the selection "
          "and filter FactAttributionCredit[ModelKey] to it, falling back to the default model when none or "
          "several are selected - credit from different models must never be summed.",
          [I("ModelKey", fmt="0", hidden=True), S("ModelName", sort_by="SortOrder"),
           I("SortOrder", fmt="0", hidden=True), S("Description"),
           D("CampaignDispersionUSD", fmt="#,0.00", hidden=True,
             desc="sum(v^2)/sum(v) of each lead's credited revenue per campaign, by model: the variance term of the "
                  "campaign signal test (SQL 07).")]),

    Table("FactAdSpend", "vw_FactAdSpend",
          "Paid-media billing lines, one per AdRowID. Several lines can share Date x Campaign; they differ in "
          "metrics and usually currency, so they are separate lines, not duplicates. Spend converted to USD at "
          "planning rates.",
          [S("AdRowID", hidden=True), T("Date", hidden=True), S("CampaignID", hidden=True),
           S("ChannelID", hidden=True),
           I("Impressions", fmt="#,0", hidden=True, summarize="sum"),
           I("Clicks", fmt="#,0", hidden=True, summarize="sum"),
           D("SpendLocal", fmt="#,0.00", hidden=True, summarize="sum",
             desc="Spend in the billing currency. Not additive across currencies - use SpendUSD."),
           S("CurrencyCode"), D("FxRateToUSD", fmt="0.0000", hidden=True),
           D("SpendUSD", fmt="#,0.00", hidden=True, summarize="sum"),
           B("IsBeforeCampaignStart", desc="Spend dated before the campaign's recorded StartDate.")]),

    Table("FactLeadFunnel", "vw_FactLeadFunnel",
          "Accumulating snapshot: one row per lead with its opportunity and revenue milestones. Stage is derived "
          "from evidence, not the stale CRM label. CreatedDate is the active date; opportunity and revenue dates "
          "are inactive role-playing relationships.",
          [S("LeadID", hidden=True), T("CreatedDate", hidden=True), S("CampaignID", hidden=True),
           S("Segment"), S("Country", category="Country"),
           D("EstimatedValue", fmt="#,0.00", hidden=True, summarize="sum"),
           S("LatestStageLabel", desc="Stage as supplied by the CRM. Stale for 2,428 won leads - see DerivedStage."),
           S("DerivedStage", sort_by="StageRank", desc="Stage from evidence: revenue > opportunity > CRM label."),
           I("StageRank", fmt="0", hidden=True),
           B("ReachedMQL", hidden=True), B("ReachedSQL", hidden=True),
           B("HasOpportunity", hidden=True), B("IsWon", hidden=True), B("IsStageLabelStale"),
           I("TouchCount", fmt="0", desc="Touches in the lead's journey (1-6)."),
           I("DistinctChannels", fmt="0", desc="Distinct channels in the lead's journey."),
           B("SequenceContradictsDate", hidden=True),
           S("OpportunityID", hidden=True), T("OpportunityCreatedDate", hidden=True),
           D("OpportunityValue", fmt="#,0.00", hidden=True, summarize="sum"),
           S("OpportunityStatus", hidden=True,
             desc="Status at extract time, seven weeks after the as-of date. Use OpportunityStatusAsOf."),
           B("IsOpportunityAfterAsOf", hidden=True),
           S("RevenueID", hidden=True), T("RevenueDate", hidden=True),
           D("RevenueUSD", fmt="#,0.00", hidden=True, summarize="sum"),
           B("IsRevenueAfterAsOf", hidden=True),
           I("DaysLeadToOpportunity", fmt="0", desc="Days from lead creation to its opportunity (2-39)."),
           I("DaysOpportunityToRevenue", fmt="0", desc="Days from opportunity to booked revenue (1-19)."),
           B("IsOpportunityByAsOf", hidden=True, desc="The opportunity existed by the as-of date."),
           B("IsWonByAsOf", hidden=True, desc="Revenue was booked by the as-of date."),
           S("OpportunityStatusAsOf",
             desc="Status on the as-of date: Closed Won if booked by then, Open if won later or still open, Closed Lost "
                  "(the source has no loss date, so a lost deal opened by the as-of date is taken as lost by then)."),
           I("StageRankAsOf", fmt="0", hidden=True,
             desc="Furthest funnel stage reached by the as-of date: 5 won, 4 opportunity, else the CRM stage capped at SQL.")]),

    Table("FactTouchpoint", "vw_FactTouchpoint",
          "One marketing touch on a lead's pre-conversion journey. JourneyPosition orders touches by date; the "
          "supplied sequence number contradicted the calendar for 71% of leads.",
          [S("TouchpointID", hidden=True), S("LeadID", hidden=True), T("TouchDate", hidden=True),
           S("CampaignID", hidden=True), S("ChannelID", hidden=True), S("TouchType"),
           I("SourceTouchSequence", fmt="0", hidden=True),
           I("JourneyPosition", fmt="0", desc="1 = earliest touch, by date."),
           I("JourneyLength", fmt="0"), I("DaysBeforeLead", fmt="0"),
           S("PositionBand", sort_by="PositionBandOrder",
             desc="First, Middle, Last or Only touch. First Touch credits only First; Last Touch only Last."),
           I("PositionBandOrder", fmt="0", hidden=True)]),

    Table("DimFunnelStage", "vw_DimFunnelStage",
          "Disconnected funnel axis: Lead, MQL, SQL, Opportunity, Customer. Each stage counts leads that reached AT "
          "LEAST that stage, so the funnel's bars nest by construction.",
          [I("StageRank", fmt="0", hidden=True), S("StageName", sort_by="StageRank"), S("Definition")]),

    Table("FactAttributionCredit", "vw_FactAttributionCredit",
          "One row per touchpoint per attribution model: the share of the lead's conversion credited to the touch. "
          "Weights sum to 1 per lead per model. Always filter to ONE model - summing across models multiplies revenue.",
          [S("TouchpointID", hidden=True), I("ModelKey", fmt="0", hidden=True), S("LeadID", hidden=True),
           S("CampaignID", hidden=True), S("ChannelID", hidden=True), T("TouchDate", hidden=True),
           T("RevenueDate", hidden=True),
           D("CreditWeight", fmt="0.0000", hidden=True, summarize="sum"),
           D("AttributedRevenueUSD", fmt="#,0.00", hidden=True, summarize="sum"),
           B("IsRevenueAfterAsOf", hidden=True)]),

    Table("CampaignAliasResolution", ALIAS_M,
          "Power Query cleansing showcase: the 900 messy campaign aliases resolved to canonical campaigns by "
          "documented rules R1-R4, and checked against the supplied mapping (CampaignID). ResolutionStatus reports "
          "Resolved, Unresolved or Mismatch per alias.",
          [S("RawCampaignKey"), S("RawCampaignName"), S("CampaignID", hidden=True, desc="Supplied mapping - the answer key."),
           S("MatchKey", desc="Normalised name after rules R1-R4."),
           S("ResolvedCampaignID"), S("ResolvedCampaignName"), S("AliasStyle"), S("ResolutionStatus")]),

    Table("FxRate", "vw_FxRate",
          "Planning exchange rates to USD. Illustrative assumptions, NOT market data. Disconnected - shown for transparency.",
          [S("CurrencyCode"), S("RateType"), T("EffectiveFrom"), T("EffectiveTo"),
           D("RateToUSD", fmt="0.0000"), S("Source")]),

    Table("ModelConfig", "vw_ModelConfig",
          "Disconnected configuration: as-of date, reporting currency, attribution parameters. Read by measures so "
          "nothing is hard-coded.",
          [S("ConfigKey"), S("ConfigValue"), S("Description")], hidden=True),

    Table("SecurityUserAccess", "vw_SecurityUserAccess",
          "Row-level security mapping: user email to region, or ALL. Disconnected; read by the Regional Marketing role.",
          [S("UserEmail"), S("Role"), S("Region")], hidden=True),

    Table("_Measures", MEASURES_TABLE_M,
          "Holds every business measure. The single hidden column exists only because a table needs one.",
          [S("Placeholder", hidden=True)]),
]

# (from table.column, to table.column, active)
RELATIONSHIPS = [
    ("FactAdSpend.Date", "DimDate.Date", True),
    ("FactLeadFunnel.CreatedDate", "DimDate.Date", True),
    ("FactLeadFunnel.OpportunityCreatedDate", "DimDate.Date", False),
    ("FactLeadFunnel.RevenueDate", "DimDate.Date", False),
    ("FactTouchpoint.TouchDate", "DimDate.Date", True),
    ("FactAttributionCredit.TouchDate", "DimDate.Date", True),
    ("FactAttributionCredit.RevenueDate", "DimDate.Date", False),
    ("FactAdSpend.CampaignID", "DimCampaign.CampaignID", True),
    ("FactLeadFunnel.CampaignID", "DimCampaign.CampaignID", True),
    ("FactTouchpoint.CampaignID", "DimCampaign.CampaignID", True),
    ("FactAttributionCredit.CampaignID", "DimCampaign.CampaignID", True),
    ("CampaignAliasResolution.CampaignID", "DimCampaign.CampaignID", True),
]

RLS_ROLE = "Regional Marketing"
RLS_FILTERS = {
    "DimCampaign": """VAR UserRegions =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[Region] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    "ALL" IN UserRegions || DimCampaign[Region] IN UserRegions""",
    # a user may see only their own mapping row
    "SecurityUserAccess": "SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()",
}

PARAMETERS = [
    ("SqlServer", "localhost\\SQLEXPRESS", "SQL Server instance hosting MarketingAttributionBI. The only place the server is named."),
    ("SqlDatabase", "MarketingAttributionBI", "Database holding the analytics views."),
]


# ----------------------------------------------------------------- rendering ---
def desc_lines(text, indent):
    return [f"{indent}/// {text}"] if text else []


def render_column(t, c):
    L = desc_lines(c.desc, "\t") + [f"\tcolumn {q(c.name)}", f"\t\tdataType: {c.dtype}"]
    if c.hidden:
        L.append("\t\tisHidden")
    if c.key:
        L.append("\t\tisKey")
    fmt = c.fmt or {"dateTime": "yyyy-mm-dd", "boolean": BOOL_FMT}.get(c.dtype)
    if fmt:
        L.append(f"\t\tformatString: {fmt}")
    L.append(f"\t\tlineageTag: {tag(t.name, 'column', c.name)}")
    if c.category:
        L.append(f"\t\tdataCategory: {c.category}")
    L += [f"\t\tsummarizeBy: {c.summarize}", f"\t\tsourceColumn: {c.name}"]
    if c.sort_by:
        L.append(f"\t\tsortByColumn: {q(c.sort_by)}")
    L += ["", "\t\tannotation SummarizationSetBy = Automatic"]
    if c.dtype == "dateTime":
        L += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    return L + [""]


def render_measure(t, m):
    L = desc_lines(m["desc"], "\t")
    body = m["dax"].strip("\n").split("\n")
    if len(body) == 1:
        L.append(f"\tmeasure {q(m['name'])} = {body[0]}")
    else:
        L.append(f"\tmeasure {q(m['name'])} =")
        L += ["\t\t\t" + b if b else "" for b in body]
    if m.get("fmt"):
        L.append(f"\t\tformatString: {m['fmt']}")
    if m.get("folder"):
        L.append(f"\t\tdisplayFolder: {m['folder']}")
    L.append(f"\t\tlineageTag: {tag(t.name, 'measure', m['name'])}")
    return L + [""]


def partition_m(t):
    if t.source.startswith("vw_"):
        step = f"analytics_{t.source}"
        m = ("let\n"
             "    Source = Sql.Database(SqlServer, SqlDatabase),\n"
             f"    {step} = Source{{[Schema=\"analytics\",Item=\"{t.source}\"]}}[Data]\n"
             "in\n"
             f"    {step}")
    else:
        m = t.source
    return m.split("\n")


def render_table(t, measures):
    L = desc_lines(t.desc, "") + [f"table {q(t.name)}"]
    if t.hidden:
        L.append("\tisHidden")
    L.append(f"\tlineageTag: {tag(t.name)}")
    if t.category:
        L.append(f"\tdataCategory: {t.category}")
    L.append("")
    for m in measures:
        L += render_measure(t, m)
    for c in t.cols:
        L += render_column(t, c)
    for hname, levels in t.hierarchies:
        L += [f"\thierarchy {q(hname)}", f"\t\tlineageTag: {tag(t.name, 'hierarchy', hname)}", ""]
        for lv in levels:
            L += [f"\t\tlevel {q(lv)}", f"\t\t\tlineageTag: {tag(t.name, 'hierarchy', hname, lv)}",
                  f"\t\t\tcolumn: {q(lv)}", ""]
    L += [f"\tpartition {q(t.name)} = m", "\t\tmode: import", "\t\tsource ="]
    L += ["\t\t\t\t" + x if x else "" for x in partition_m(t)]
    L += ["", "\tannotation PBI_NavigationStepName = Navigation", "", "\tannotation PBI_ResultType = Table", ""]
    return L


def write(path, lines):
    """TMDL exactly as Power BI saves it: CRLF, and the file ends with one blank
    line. Matching this means a Power BI save of an unchanged model is a no-op
    in Git (verified by diffing a Power BI-saved copy against this output)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def write_json(path, obj):
    """JSON as Power BI saves it: two-space indent, CRLF, no final newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=2).replace("\n", "\r\n").encode("utf-8"))


def load_measures():
    try:
        from model_measures import MEASURES     # Python/model_measures.py
    except ImportError:
        return []
    return MEASURES


def main():
    measures = load_measures()
    names = [t.name for t in TABLES]

    # tables: rewrite the folder so a removed table cannot linger
    tdir = DEF / "tables"
    if tdir.exists():
        shutil.rmtree(tdir)
    for t in TABLES:
        write(tdir / f"{t.name}.tmdl", render_table(t, measures if t.name == "_Measures" else []))

    rel = []
    for f, to, active in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', f, to)}"]
        if not active:
            rel.append("\tisActive: false")
        rel += [f"\tfromColumn: {f}", f"\ttoColumn: {to}", ""]
    write(DEF / "relationships.tmdl", rel)

    ex = []
    for n, v, d in PARAMETERS:
        ex += [f"/// {d}",
               f'expression {n} = "{v}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
               f"\tlineageTag: {tag('expression', n)}", "", "\tannotation PBI_ResultType = Text", ""]
    write(DEF / "expressions.tmdl", ex)

    rdir = DEF / "roles"
    if rdir.exists():
        shutil.rmtree(rdir)
    ro = ["/// Dynamic regional security: a user sees the campaigns - and through them all spend, leads, touches "
          "and attributed credit - of the regions mapped to their email in SecurityUserAccess. ALL sees everything; "
          "an unmapped user sees nothing.",
          f"role {q(RLS_ROLE)}", "\tmodelPermission: read", ""]
    for tbl, dax in RLS_FILTERS.items():
        body = dax.split("\n")
        if len(body) == 1:
            ro += [f"\ttablePermission {q(tbl)} = {body[0]}", ""]
        else:
            ro += [f"\ttablePermission {q(tbl)} ="] + ["\t\t\t" + b if b else "" for b in body] + [""]
    # Power BI stamps every role with a PBI_Id on save. Supplying a stable one
    # stops it inventing a new random id on each save, which would churn Git.
    ro += [f"\tannotation PBI_Id = {uuid.uuid5(NS, 'role/' + RLS_ROLE).hex}", ""]
    write(rdir / f"{RLS_ROLE}.tmdl", ro)

    order = json.dumps([p[0] for p in PARAMETERS] + names, separators=(",", ":"))
    mdl = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
           "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects",
           "\t\treturnErrorValuesAsNull", "",
           "annotation __PBI_TimeIntelligenceEnabled = 0", "",
           'annotation PBI_ProTooling = ["DevMode"]', "",
           f"annotation PBI_QueryOrder = {order}", ""]
    # Power BI appends a table created after the model's first save to the END of
    # its collection and writes the refs in that order (observed on the save that
    # followed DimFunnelStage's addition). Mirroring it keeps saves a no-op.
    # PBI_QueryOrder is left as generated - Power BI did not reorder it.
    appended_later = ["DimFunnelStage"]
    ref_names = [n for n in names if n not in appended_later] + [n for n in appended_later if n in names]
    mdl += [f"ref table {q(n)}" for n in ref_names] + ["", f"ref role {q(RLS_ROLE)}", "", "ref cultureInfo en-US", ""]
    write(DEF / "model.tmdl", mdl)

    # ------------------------------------------------ PBIP / report shell ---
    write_json(PBI / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    plat = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
    write_json(SM / ".platform", {"$schema": plat, "metadata": {"type": "SemanticModel", "displayName": NAME},
                                  "config": {"version": "2.0", "logicalId": tag("logical", "semanticmodel")}})
    write_json(RP / ".platform", {"$schema": plat, "metadata": {"type": "Report", "displayName": NAME},
                                  "config": {"version": "2.0", "logicalId": tag("logical", "report")}})
    write_json(RP / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    pages = RP / "definition" / "pages"
    pid = uuid.uuid5(NS, "page.overview").hex[:20]
    if not (pages / "pages.json").exists():     # never overwrite report pages built later
        write_json(pages / "pages.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [pid], "activePageName": pid})
        write_json(pages / pid / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
            "name": pid, "displayName": "Overview", "displayOption": "FitToPage", "height": 720, "width": 1280})

    ncols = sum(len(t.cols) for t in TABLES)
    print(f"{len(TABLES)} tables, {ncols} columns, {len(RELATIONSHIPS)} relationships "
          f"({sum(1 for r in RELATIONSHIPS if r[2])} active), 1 role, {len(measures)} measures")


if __name__ == "__main__":
    main()
