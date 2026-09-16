# -*- coding: utf-8 -*-
"""
Phase 2 - Semantic model as code.

Writes the Power BI project (PBIP) semantic model in TMDL, plus the minimal
report shell it needs, from the declarative specification below:

    PowerBI/SaaSRevenue.pbip
    PowerBI/SaaSRevenue.SemanticModel/definition/
        model.tmdl  expressions.tmdl  relationships.tmdl  roles/  tables/
    PowerBI/SaaSRevenue.Report/  (definition.pbir, one page)

Files Power BI itself authored (database.tmdl, report.json, version.json, the
base theme) are copied once from PowerBI/scaffold and never rewritten here.

Output matches what Power BI writes: tab indentation, CRLF, no BOM, triple-slash
descriptions directly above the object, dates as dateTime with
UnderlyingDateTimeDataType = Date. Lineage tags are uuid5 of the object path, so
a re-run produces byte-identical files and a clean Git diff.

The model's shape, and why:

  Two fact tables carry the story and they are deliberately different grains.
  FactSubscriptionMonth is a monthly SNAPSHOT - what was on the books at each
  month end - so MRR is read at a moment and a cohort matrix is a pivot. Its
  companion FactMRRMovement is a LEDGER of changes, so the waterfall is derived
  rather than inferred. `09_validation.sql` checks the two agree every month.

  DimCohort and DimTenureMonth are real dimensions, not fact columns, because a
  retention matrix needs both axes in time order rather than alphabetical.

  One calculation group (Time Comparison) and one field parameter (Customer Cut)
  carry the interaction: the reader changes the question instead of the page.

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

NAME = "SaaSRevenue"
PBI = ROOT / "PowerBI"
SCAFFOLD = PBI / "scaffold"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"
DEF = SM / "definition"
NS = uuid.UUID("4f7a1c62-5d0e-4b83-9a17-3e6c8d2f5b41")   # fixed: deterministic tags

BOOL_FMT = '"""TRUE"";""TRUE"";""FALSE"""'

# The money formats the columns use are the same ones the measures use, so they
# are defined once, next to the measures, and imported here.
from model_measures import F_MONEY, F_MONEY0        # noqa: E402


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
    source: str                     # analytics view name
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


MEASURES_TABLE_M = """let
    Source = #table(type table [Placeholder = text], {})
in
    Source"""

TABLES = [
    Table("DimDate", "vw_DimDate",
          "Conformed calendar 2022-01-01 to 2027-06-30, generated in SQL. The supplied calendar stops on the as-of "
          "date, two months into FY27, so it was extended to complete the financial year; added days are flagged and "
          "never counted as data. Marked as the date table. The financial year runs July to June.",
          [T("Date", key=True, desc="Model date key: unique, contiguous, no gaps."),
           I("Year", fmt="0"), I("MonthNo", fmt="0", hidden=True),
           S("MonthName", sort_by="MonthNo"),
           S("MonthShort", sort_by="MonthNo", desc="Month abbreviation, for a narrow axis."),
           I("Quarter", fmt="0", hidden=True), S("QuarterLabel"),
           I("YearMonth", fmt="0", hidden=True, desc="Sort key for YearMonthLabel."),
           S("YearMonthLabel", sort_by="YearMonth"),
           T("MonthStart", desc="First day of the month: the grain every monthly fact joins on."),
           T("MonthEnd", hidden=True),
           I("ISOWeek", fmt="0", hidden=True),
           S("DayName", sort_by="DayOfWeekNo"), I("DayOfWeekNo", fmt="0", hidden=True),
           I("FinancialYearStart", fmt="0", hidden=True), S("FinancialYear"),
           I("FinancialMonthNo", fmt="0", hidden=True, desc="1 = July."),
           I("FinancialQuarter", fmt="0", hidden=True),
           S("FinancialQuarterLabel", sort_by="FinancialQuarterSort"),
           I("FinancialQuarterSort", fmt="0", hidden=True),
           I("MonthOffset", fmt="0",
             desc="Months from the as-of month: 0 = Aug 2026, -11 to 0 is the trailing twelve months. A trailing "
                  "window is then a range on an integer, which folds to SQL."),
           B("IsSourceCalendar", hidden=True, desc="True where the supplied dim_date also covers the day."),
           B("IsAfterAsOf", desc="True for days after the as-of date: no data exists there."),
           B("IsMonthComplete", desc="True when the whole month falls on or before the as-of date.")],
          category="Time",
          hierarchies=[("Calendar", ["Year", "QuarterLabel", "YearMonthLabel", "Date"]),
                       ("Financial", ["FinancialYear", "FinancialQuarterLabel", "YearMonthLabel", "Date"])]),

    Table("DimCustomer", "vw_DimCustomer",
          "The 12,000 accounts. How a customer was acquired is an attribute of the customer and lives here; what they "
          "cost is a number that sums and lives in FactAcquisition. Row-level security filters this table by country, "
          "so a country scope reaches every fact through it.",
          [S("CustomerID", hidden=True), S("CustomerName"),
           T("SignupDate", desc="Also the subscription start date, for every customer without exception."),
           T("CohortMonth", hidden=True),
           S("CohortLabel", desc="The signup month as a label. For cohort analysis use DimCohort, which sorts."),
           S("Industry"), S("Country", desc="Drives row-level security."),
           S("Segment", sort_by="SegmentOrder", desc="SMB, Mid-Market or Enterprise - the company's own size band, "
                                                     "which turns out to say almost nothing about churn."),
           I("SegmentOrder", fmt="0", hidden=True),
           S("PlanID", hidden=True,
             desc="The customer's plan. It lives here, not only on the subscription, because a plan filter has to "
                  "reach tickets, usage, invoices and acquisition - and all of those hang off the customer. Sound "
                  "only because this source gives every customer exactly one subscription for life, on one plan; "
                  "checked in 09_validation.sql."),
           S("BillingCycle", desc="Monthly or Annual - one per customer, for life. Annual customers churn "
                                    "slightly less (18.3% against 19.9%)."),
           S("SubscriptionStatus", desc="Active or Churned. On the customer, not only on the subscription, so that a "
                                        "status slicer reaches the monthly snapshot."),
           B("IsChurned", desc="Has this customer's subscription ended?"),
           S("AcquisitionSource", desc="The channel that brought them in. Flat against churn and against cost."),
           S("AttributionType", desc="First touch, last touch or multi-touch - how the source attributed them.")]),

    Table("DimPlan", "vw_DimPlan",
          "The four subscription plans. Plan is the ONE strong churn driver in this data: Starter churns at 26% and "
          "Enterprise at 8%, and the gradient holds inside every segment.",
          [S("PlanID", hidden=True), S("PlanName", sort_by="PlanOrder"),
           D("MonthlyListPrice", fmt=F_MONEY0, summarize="none",
             desc="The price book. Realised MRR sits between 85% and 125% of it, so the two are reported apart."),
           I("PlanOrder", fmt="0", hidden=True),
           S("PlanLabel", sort_by="PlanOrder", desc="Plan with its list price, for a chart axis.")]),

    Table("DimSeverity", "vw_DimSeverity",
          "Ticket severity, with an order so a chart reads Low to Critical rather than alphabetically.",
          [S("SeverityName", sort_by="SeverityOrder"), I("SeverityOrder", fmt="0", hidden=True),
           B("IsUrgent", desc="High or Critical.")]),

    Table("DimMovementType", "vw_DimMovementType",
          "The five movements a SaaS book can make. Three of them cannot occur in this source; the dimension carries "
          "that fact and the reason, so the waterfall can show an empty bar and say why.",
          [S("MovementType", sort_by="MovementOrder"), I("MovementOrder", fmt="0", hidden=True),
           I("MovementSign", fmt="0", hidden=True, desc="+1 adds to MRR, -1 removes."),
           B("IsSupported", desc="Whether this movement can occur in this data at all."),
           S("SupportLabel"),
           S("WhyNot", desc="Why a movement cannot occur here. Empty for the two that can.")]),

    Table("DimTenureBand", "vw_DimTenureBand",
          "Tenure grouped into bands, ordered.",
          [S("TenureBand", sort_by="TenureBandOrder"), I("TenureBandOrder", fmt="0", hidden=True),
           I("MinMonths", fmt="0", hidden=True), I("MaxMonths", fmt="0", hidden=True)]),

    Table("DimCohort", "vw_DimCohort",
          "One row per signup month: the cohort, its size, and the MRR it started with. A real dimension rather than a "
          "fact column, so a retention matrix sorts by time instead of alphabetically.",
          [T("CohortMonth", hidden=True), S("CohortLabel", sort_by="CohortSort"),
           I("CohortSort", fmt="0", hidden=True),
           I("CohortSize", fmt="#,0", summarize="sum", desc="Customers that started in the month. Fixed: it never "
                                                            "moves as customers leave."),
           D("CohortMRR", fmt=F_MONEY0, summarize="sum", desc="The MRR the cohort started with.")]),

    Table("DimTenureMonth", "vw_DimTenureMonth",
          "Months since a customer signed up: M0 is the signup month. The other axis of the retention matrix, again a "
          "dimension so that M2 sorts before M10.",
          [I("TenureMonth", fmt="0", hidden=True), S("TenureLabel", sort_by="TenureMonth"),
           I("TenureYear", fmt="0", hidden=True, desc="Year of life: 0 for the first twelve months.")]),

    Table("FactSubscription", "vw_FactSubscription",
          "One subscription, which in this source is also one customer. Its date relationship is to the START date, so "
          "filtering the calendar gives the customers that ARRIVED in the period; the end date is an inactive "
          "relationship, used through USERELATIONSHIP where churn timing is the question.",
          [S("SubscriptionID", hidden=True), S("CustomerID", hidden=True), S("PlanID", hidden=True,
             desc="Carried by the view. NOT the filter path: plan filters through DimCustomer, so that it reaches tickets, usage, invoices and acquisition too."),
           T("StartDate", desc="Active date relationship: the month the customer arrived."),
           T("EndDate", desc="Inactive date relationship: the month the customer left."),
           T("StartMonth", hidden=True), T("EndMonth", hidden=True),
           S("Status", desc="Carried by the view. NOT the filter path - slice DimCustomer[SubscriptionStatus], "
                            "which reaches the snapshot as well."),
           B("IsChurned", desc="Never disagrees with the status."),
           D("MRR", fmt=F_MONEY, hidden=True, summarize="sum",
             desc="One static value for the whole life of the subscription - which is why this data has no expansion "
                  "or contraction."),
           D("ARR", fmt=F_MONEY0, hidden=True, summarize="sum"),
           S("BillingCycle", desc="Carried by the view. NOT the filter path - slice "
                                   "DimCustomer[BillingCycle] instead."),
           I("TenureMonths", fmt="#,0", summarize="none",
             desc="Completed months to the end date, or to the as-of date while still running."),
           S("TenureBand", hidden=True)]),

    Table("FactSubscriptionMonth", "vw_FactSubscriptionMonth",
          "The monthly SNAPSHOT: one row per subscription per month it is live at month end. MRR is a stock, so it is "
          "read at a moment and never summed across months - every measure here goes through [Snapshot Month]. "
          "320,294 rows over 56 months.",
          [T("MonthStart", hidden=True), S("SubscriptionID", hidden=True), S("CustomerID", hidden=True),
           S("PlanID", hidden=True,
             desc="Carried by the view. NOT the filter path: plan filters through DimCustomer, so that it reaches tickets, usage, invoices and acquisition too."),
           D("MRR", fmt=F_MONEY, hidden=True, summarize="sum"),
           T("CohortMonth", hidden=True), I("TenureMonth", fmt="0", hidden=True),
           B("IsFirstMonth", desc="The month the subscription started."),
           B("IsLastMonth", desc="The last month it was live.")]),

    Table("FactMRRMovement", "vw_FactMRRMovement",
          "The movement LEDGER: one row per customer per month its MRR changed, classified by comparing the month "
          "against the one before. The waterfall is derived from this, not inferred from dates - and the change it "
          "reports reconciles to the snapshot every month.",
          [T("MonthStart", hidden=True), S("CustomerID", hidden=True), S("PlanID", hidden=True,
             desc="Carried by the view. NOT the filter path: plan filters through DimCustomer, so that it reaches tickets, usage, invoices and acquisition too."),
           S("MovementType", hidden=True),
           D("MRRDelta", fmt=F_MONEY, hidden=True, summarize="sum", desc="Signed: churn is negative."),
           D("PriorMRR", fmt=F_MONEY, hidden=True, summarize="sum"),
           D("CurrentMRR", fmt=F_MONEY, hidden=True, summarize="sum")]),

    Table("FactInvoice", "vw_FactInvoice",
          "One invoice. Billed value is a FLOW and does sum over time, unlike MRR - and it is lumpy, because an annual "
          "customer bills twelve months at once. Invoices are all dated the 1st of the month while a subscription "
          "starts on any day, so an invoice date never decides when a subscription began.",
          [S("InvoiceID", hidden=True), S("SubscriptionID", hidden=True), S("CustomerID", hidden=True),
           T("InvoiceDate", desc="Always the 1st of a month: a billing convention in the source."),
           T("InvoiceMonth", hidden=True),
           D("InvoiceAmount", fmt=F_MONEY, hidden=True, summarize="sum"),
           T("PaymentDate", desc="Inactive date relationship. Blank where the invoice failed."),
           S("PaymentStatus"),
           B("IsFailed", desc="The invoice did not collect. Unrelated to churn in this source."),
           I("DaysToPay", fmt="#,0", summarize="none")]),

    Table("FactUsageMonthly", "vw_FactUsageMonthly",
          "One customer's product usage in one month - for the customers it covers. Usage reaches about 40% of paying "
          "customers in any month, so everything here is a SAMPLE and is labelled as one. None of it predicts churn.",
          [T("MonthStart", hidden=True), S("CustomerID", hidden=True),
           I("LicensedSeats", fmt="#,0", hidden=True, summarize="sum"),
           I("ActiveUsers", fmt="#,0", hidden=True, summarize="sum"),
           I("Logins", fmt="#,0", hidden=True, summarize="sum"),
           D("FeatureAdoptionRate", fmt="0.0%", hidden=True, summarize="average"),
           I("CriticalErrors", fmt="#,0", hidden=True, summarize="sum")]),

    Table("FactSupportTicket", "vw_FactSupportTicket",
          "One support ticket. Resolution hours are populated for tickets that are still open, drawn from the same "
          "distribution as resolved ones, so mean time to resolve uses resolved tickets only.",
          [S("TicketID", hidden=True), S("CustomerID", hidden=True),
           T("OpenedDate"), T("OpenedMonth", hidden=True),
           S("Severity", hidden=True),
           D("ResolutionHours", fmt="#,0.0", hidden=True, summarize="average"),
           S("Status"), B("IsResolved"),
           S("Category", desc="What the ticket was about. Flat against churn, like everything else here.")]),

    Table("FactAcquisition", "vw_FactAcquisition",
          "What each customer cost to acquire, landed in their signup month. No campaign and no spend over time exist "
          "in the source, so a blended CAC is honest and a marketing-efficiency trend is not.",
          [S("CustomerID", hidden=True), T("AcquisitionMonth", hidden=True),
           D("AcquisitionCost", fmt=F_MONEY, hidden=True, summarize="sum")]),

    Table("ChurnDriverStrength", "vw_ChurnDriverStrength",
          "The measured relationship between each candidate churn driver and whether a customer actually churned, "
          "computed in SQL on every refresh. Disconnected on purpose: it describes the customer base as a whole, so it "
          "must not be filtered by a slicer that would change the population it was computed over.",
          [S("Driver", sort_by="DriverOrder"), I("DriverOrder", fmt="0", hidden=True),
           S("DriverGroup", desc="Commercial, Behaviour, Product or Billing."),
           B("IsRawCount", desc="True for the two raw counts kept deliberately alongside their rate, to show that a "
                                "count measures tenure rather than behaviour."),
           I("Customers", fmt="#,0", hidden=True, summarize="sum"),
           D("Correlation", fmt="+0.000;-0.000;0.000", hidden=True, summarize="average")]),

    Table("DataQualityMetric", "vw_DataQualityMetric",
          "Data-quality figures computed live in SQL from dbo, so the Data & Method page can never drift from the data.",
          [I("SortOrder", fmt="0", hidden=True), S("Metric", sort_by="SortOrder"),
           D("MetricValue", fmt="#,0.00", hidden=True, summarize="sum"),
           S("Unit", desc="How to read the value: a share, a count, a correlation.")]),

    Table("ModelConfig", "vw_ModelConfig",
          "Disconnected configuration: the as-of date, the gross-margin assumption, the currency. Read by measures so "
          "nothing is hard-coded, and shown on the page so no assumption is invisible.",
          [S("ConfigKey"), S("ConfigValue"), S("Description")], hidden=True),

    Table("SecurityUserAccess", "vw_SecurityUserAccess",
          "Row-level security mapping: user email to country, or ALL. Disconnected; read by the role.",
          [S("UserEmail"), S("Role"), S("Country")], hidden=True),

    Table("_Measures", MEASURES_TABLE_M,
          "Holds every business measure. The single hidden column exists only because a table needs one.",
          [S("Placeholder", hidden=True)]),
]

# (from table.column, to table.column, active)
# Single direction throughout, fact to dimension. DimDate reaches five facts and
# DimCustomer reaches six, but filters never travel back up through a fact, so
# there is no ambiguous path between any two dimensions.
RELATIONSHIPS = [
    ("FactSubscriptionMonth.MonthStart", "DimDate.Date", True),
    ("FactSubscriptionMonth.CustomerID", "DimCustomer.CustomerID", True),
    # Plan filters through the CUSTOMER, not through each fact. One path then reaches
    # every table - including tickets, usage, invoices and acquisition, which a
    # fact-level plan relationship could never reach. Found by rendering: "support
    # contact rate by plan" was dividing ALL 45,000 tickets by one plan's exposure.
    ("DimCustomer.PlanID", "DimPlan.PlanID", True),
    ("FactSubscriptionMonth.CohortMonth", "DimCohort.CohortMonth", True),
    ("FactSubscriptionMonth.TenureMonth", "DimTenureMonth.TenureMonth", True),
    ("FactMRRMovement.MonthStart", "DimDate.Date", True),
    ("FactMRRMovement.CustomerID", "DimCustomer.CustomerID", True),
    ("FactMRRMovement.MovementType", "DimMovementType.MovementType", True),
    # The ACTIVE date relationship is the start date: the calendar selects arrivals.
    # The end date is inactive and reached with USERELATIONSHIP when churn timing
    # is the question, so one fact answers both without a second copy of it.
    ("FactSubscription.StartDate", "DimDate.Date", True),
    ("FactSubscription.EndDate", "DimDate.Date", False),
    ("FactSubscription.CustomerID", "DimCustomer.CustomerID", True),
    ("FactSubscription.TenureBand", "DimTenureBand.TenureBand", True),
    ("FactInvoice.InvoiceDate", "DimDate.Date", True),
    ("FactInvoice.PaymentDate", "DimDate.Date", False),
    ("FactInvoice.CustomerID", "DimCustomer.CustomerID", True),
    ("FactUsageMonthly.MonthStart", "DimDate.Date", True),
    ("FactUsageMonthly.CustomerID", "DimCustomer.CustomerID", True),
    ("FactSupportTicket.OpenedDate", "DimDate.Date", True),
    ("FactSupportTicket.CustomerID", "DimCustomer.CustomerID", True),
    ("FactSupportTicket.Severity", "DimSeverity.SeverityName", True),
    ("FactAcquisition.AcquisitionMonth", "DimDate.Date", True),
    ("FactAcquisition.CustomerID", "DimCustomer.CustomerID", True),
]

RLS_ROLE = "Country Access"
# A customer success manager sees their country; Revenue Operations and the CFO
# are mapped to ALL. An unmapped user sees nothing, which is the secure default.
COUNTRY_SCOPE = """VAR UserScope =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[Country] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    "ALL" IN UserScope || DimCustomer[Country] IN UserScope"""

RLS_FILTERS = {
    "DimCustomer": COUNTRY_SCOPE,
    # A user may see only their own mapping row.
    "SecurityUserAccess": "SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()",
}

PARAMETERS = [
    ("SqlServer", "localhost\\SQLEXPRESS",
     "SQL Server instance hosting SaaSRevenueBI. The only place the server is named."),
    ("SqlDatabase", "SaaSRevenueBI", "Database holding the analytics views."),
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
    if m.get("fmt"):                       # Power BI's order: format string, then hidden
        L.append(f"\t\tformatString: {m['fmt']}")
    if m.get("hidden"):
        L.append("\t\tisHidden")
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



def render_field_parameter(fp):
    """A field parameter table. Three columns by convention - the label, the field
    reference, and the sort order - and the middle one carries the extended
    property that tells Power BI it holds fields rather than text. Written as a
    CALCULATED partition, because the rows are NAMEOF() references resolved by the
    engine, not data read from SQL."""
    name = fp["name"]
    L = desc_lines(fp["desc"], "") + [f"table {q(name)}", f"\tlineageTag: {tag(name)}", ""]
    L += [f"\tcolumn {q(name)}", "\t\tdataType: string",
          f"\t\tlineageTag: {tag(name, 'column', name)}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: [Value1]",
          f"\t\tsortByColumn: {q(name + ' Order')}", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    L += [f"\tcolumn {q(name + ' Fields')}", "\t\tdataType: string", "\t\tisHidden",
          f"\t\tlineageTag: {tag(name, 'column', name + ' Fields')}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: [Value2]", "",
          # A blank line before extendedProperty, exactly as before a calculation
          # item's formatStringDefinition: Power BI inserts one on save.
          "\t\textendedProperty ParameterMetadata =",
          "\t\t\t\t{",
          '\t\t\t\t  "version": 3,',
          '\t\t\t\t  "kind": 2',
          "\t\t\t\t}", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    L += [f"\tcolumn {q(name + ' Order')}", "\t\tdataType: int64", "\t\tisHidden",
          "\t\tformatString: 0",
          f"\t\tlineageTag: {tag(name, 'column', name + ' Order')}",
          "\t\tsummarizeBy: sum", "\t\tsourceColumn: [Value3]", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    rows = [f'\t\t\t\t    ("{label}", NAMEOF(\'{tbl}\'[{col}]), {i}),'
            for i, (label, tbl, col) in enumerate(fp["fields"])]
    rows[-1] = rows[-1].rstrip(",")
    L += [f"\tpartition {q(name)} = calculated", "\t\tmode: import", "\t\tsource =",
          "\t\t\t\t{"] + rows + ["\t\t\t\t}", ""]
    L += [f"\tannotation PBI_Id = {uuid.uuid5(NS, 'fieldparam/' + name).hex}", ""]
    return L


def render_calc_group(g):
    """A calculation group table: the group, its items, and the Name / Ordinal
    columns Power BI expects. Item expressions sit one level below the item, and
    the order the items are written IS the reporting order: an explicit `ordinal:`
    only repeats it, and Power BI strips it out again on the next save."""
    L = desc_lines(g["desc"], "") + [f"table {q(g['name'])}", f"\tlineageTag: {tag(g['name'])}", "",
                                     "\tcalculationGroup", f"\t\tprecedence: {g['precedence']}", ""]
    for item, desc, dax, fmt in g["items"]:
        L += desc_lines(desc, "\t\t")
        body = dax.strip("\n").split("\n")
        if len(body) == 1:
            # A one-line expression stays on the item's own line: Power BI only
            # breaks to a continuation when the expression needs more than one.
            L += [f"\t\tcalculationItem {q(item)} = {body[0].strip()}"]
        else:
            L += [f"\t\tcalculationItem {q(item)} ="]
            L += ["\t\t\t\t" + b if b else "" for b in body]
        if fmt:
            # A format-string definition must be ONE line: TMDL expects any
            # continuation indented a level deeper, and a multi-line value here
            # fails the parser with "Unexpected line type: Other".
            L += ["", f"\t\t\tformatStringDefinition = {' '.join(fmt.split())}"]   # after a blank line, as Power BI writes it
        L.append("")
    L += [f"\tcolumn {q(g['column'])}", "\t\tdataType: string", f"\t\tlineageTag: {tag(g['name'], 'column', g['column'])}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: Name", "\t\tsortByColumn: Ordinal", "",
          "\t\tannotation SummarizationSetBy = Automatic", "",
          "\tcolumn Ordinal", "\t\tdataType: int64", "\t\tisHidden", "\t\tformatString: 0",
          f"\t\tlineageTag: {tag(g['name'], 'column', 'Ordinal')}", "\t\tsummarizeBy: sum", "\t\tsourceColumn: Ordinal",
          "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    return L


def write(path, lines):
    """TMDL exactly as Power BI saves it: CRLF, and the file ends with one blank
    line, so a Power BI save of an unchanged model is a no-op in Git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def write_json(path, obj):
    """JSON as Power BI saves it: two-space indent, CRLF, no final newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=2).replace("\n", "\r\n").encode("utf-8"))


def main():
    from model_measures import CALC_GROUPS, FIELD_PARAMETERS, MEASURES

    names = [t.name for t in TABLES]
    # Calculation groups and field parameters are tables too: they must appear in
    # model.tmdl's ref list and its query order, or Power BI loads the folder
    # without them and the report silently loses a slicer.
    group_names = [g["name"] for g in CALC_GROUPS] + [f["name"] for f in FIELD_PARAMETERS]

    tdir = DEF / "tables"
    if tdir.exists():
        shutil.rmtree(tdir)
    for t in TABLES:
        write(tdir / f"{t.name}.tmdl", render_table(t, MEASURES if t.name == "_Measures" else []))
    for g in CALC_GROUPS:
        write(tdir / f"{g['name']}.tmdl", render_calc_group(g))
    for fp in FIELD_PARAMETERS:
        write(tdir / f"{fp['name']}.tmdl", render_field_parameter(fp))

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
    ro = ["/// Dynamic security by entity AND department, from the user's email. ALL means no restriction. A "
          "department-scoped user sees that department's income statement across entities and no receivables, payables "
          "or cash - those facts have no department. An unmapped user sees nothing.",
          f"role {q(RLS_ROLE)}", "\tmodelPermission: read", ""]
    for tbl, dax in RLS_FILTERS.items():
        body = dax.split("\n")
        if len(body) == 1:
            ro += [f"\ttablePermission {q(tbl)} = {body[0]}", ""]
        else:
            ro += [f"\ttablePermission {q(tbl)} ="] + ["\t\t\t" + b if b else "" for b in body] + [""]
    # Power BI stamps every role with a PBI_Id on save; a stable one keeps Git clean.
    ro += [f"\tannotation PBI_Id = {uuid.uuid5(NS, 'role/' + RLS_ROLE).hex}", ""]
    write(rdir / f"{RLS_ROLE}.tmdl", ro)

    # Cultures come from Power BI itself: it generates the Q&A linguistic schema from
    # the model and rewrites this file whenever the model changes. Seed it once, then
    # leave it alone - rewriting the stub each run threw away what Power BI had written.
    culture = DEF / "cultures" / "en-US.tmdl"
    if not culture.exists():
        write(culture,
              ["cultureInfo en-US", "", "\tlinguisticMetadata =", "\t\t\t{", '\t\t\t  "Version": "1.0.0",',
               '\t\t\t  "Language": "en-US"', "\t\t\t}", "\t\tcontentType: json"])
    shutil.copyfile(SCAFFOLD / "database.tmdl", DEF / "database.tmdl")
    shutil.copyfile(SCAFFOLD / "definition.pbism", SM / "definition.pbism")

    order = json.dumps([p[0] for p in PARAMETERS] + names + group_names, separators=(",", ":"))
    mdl = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
           # required by calculation groups: implicit measures would bypass them
           "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "\tdataAccessOptions",
           "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
           "annotation __PBI_TimeIntelligenceEnabled = 0", "",
           'annotation PBI_ProTooling = ["DevMode"]', "",
           f"annotation PBI_QueryOrder = {order}", ""]
    mdl += [f"ref table {q(n)}" for n in names + group_names]
    mdl += ["", f"ref role {q(RLS_ROLE)}", "", "ref cultureInfo en-US", ""]
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

    theme_dir = RP / "StaticResources" / "SharedResources" / "BaseThemes"
    theme_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCAFFOLD / "StaticResources/SharedResources/BaseThemes/CY25SU10.json", theme_dir / "CY25SU10.json")
    (RP / "definition").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCAFFOLD / "version.json", RP / "definition" / "version.json")
    if not (RP / "definition" / "report.json").exists():
        # the base shell; the report generator adds the client theme in Phase 3
        report = json.loads((SCAFFOLD / "report.json").read_text(encoding="utf-8-sig"))
        report["themeCollection"].pop("customTheme", None)
        report["resourcePackages"] = [p for p in report["resourcePackages"] if p["type"] != "RegisteredResources"]
        write_json(RP / "definition" / "report.json", report)

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
    nitems = sum(len(g["items"]) for g in CALC_GROUPS)
    print(f"{len(TABLES)} tables + {len(CALC_GROUPS)} calculation groups ({nitems} items), {ncols} columns, "
          f"{len(RELATIONSHIPS)} relationships ({sum(1 for r in RELATIONSHIPS if r[2])} active), "
          f"1 role ({len(RLS_FILTERS)} table filters), {len(MEASURES)} measures")


if __name__ == "__main__":
    main()
