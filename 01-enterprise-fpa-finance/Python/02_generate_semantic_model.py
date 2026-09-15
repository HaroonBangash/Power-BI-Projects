# -*- coding: utf-8 -*-
"""
Phase 2 - Semantic model as code.

Writes the Power BI project (PBIP) semantic model in TMDL, plus the minimal
report shell it needs, from the declarative specification below:

    PowerBI/EnterpriseFPA.pbip
    PowerBI/EnterpriseFPA.SemanticModel/definition/
        model.tmdl  expressions.tmdl  relationships.tmdl  roles/  tables/
    PowerBI/EnterpriseFPA.Report/  (definition.pbir, one page)

Files Power BI itself authored (database.tmdl, report.json, version.json, the
base theme) are copied once from PowerBI/scaffold and never rewritten here.

Output matches what Power BI writes: tab indentation, CRLF, no BOM, triple-slash
descriptions directly above the object, dates as dateTime with
UnderlyingDateTimeDataType = Date. Lineage tags are uuid5 of the object path, so
a re-run produces byte-identical files and a clean Git diff.

Two calculation groups carry the FP&A logic (see Python/model_measures.py):
    Plan Version (precedence 20)  Actual / Budget / Forecast and the variances
    Period View  (precedence 10)  the period, year to date, trailing 12 months,
                                  prior year - every window ending at the
                                  balance date
Precedence puts Plan Version outermost, so "Var % vs Budget" of a year-to-date
figure divides two year-to-date figures.

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

NAME = "EnterpriseFPA"
PBI = ROOT / "PowerBI"
SCAFFOLD = PBI / "scaffold"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"
DEF = SM / "definition"
NS = uuid.UUID("4f7a1c62-5d0e-4b83-9a17-3e6c8d2f5b41")   # fixed: deterministic tags

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
          "Conformed calendar 2022-01-01 to 2027-06-30, generated in SQL because the supplied calendar ends on the "
          "as-of date while receivables run to January 2027. Marked as the date table. The financial year runs July to "
          "June: FY26 = Jul 2025 - Jun 2026.",
          [T("Date", key=True, desc="Model date key: unique, contiguous, no gaps."),
           I("Year", fmt="0"), I("MonthNo", fmt="0", hidden=True),
           S("MonthName", sort_by="MonthNo"),
           S("MonthShort", sort_by="FinancialMonthNo",
             desc="Month abbreviation ordered July first, so a financial-year axis reads Jul to Jun."),
           I("Quarter", fmt="0", hidden=True), S("QuarterLabel"),
           I("YearMonth", fmt="0", hidden=True, desc="Sort key for YearMonthLabel."),
           S("YearMonthLabel", sort_by="YearMonth"), T("MonthStart"), T("MonthEnd", hidden=True),
           I("ISOWeek", fmt="0", hidden=True),
           S("DayName", sort_by="DayOfWeekNo"), I("DayOfWeekNo", fmt="0", hidden=True),
           I("FinancialYearStart", fmt="0", hidden=True), S("FinancialYear"),
           I("FinancialMonthNo", fmt="0", hidden=True, desc="1 = July."),
           I("FinancialQuarter", fmt="0", hidden=True),
           S("FinancialQuarterLabel", sort_by="FinancialQuarterSort"),
           I("FinancialQuarterSort", fmt="0", hidden=True),
           I("MonthOffset", fmt="0",
             desc="Months from the as-of month: 0 = Aug 2026, -11 to 0 is the trailing twelve months."),
           I("FinancialYearOffset", fmt="0", desc="Financial years from the as-of year: 0 = FY27, -1 = FY26."),
           B("IsSourceCalendar", hidden=True, desc="True where the supplied dim_date also covers the day."),
           B("IsAfterAsOf", desc="True for days after the as-of date: no actuals exist yet."),
           B("IsMonthComplete", desc="True when the whole month falls on or before the as-of date."),
           B("IsFinancialYearComplete", desc="True when the whole financial year falls on or before the as-of date.")],
          category="Time",
          hierarchies=[("Financial", ["FinancialYear", "FinancialQuarterLabel", "YearMonthLabel", "Date"]),
                       ("Calendar", ["Year", "QuarterLabel", "YearMonthLabel", "Date"])]),

    Table("DimEntity", "vw_DimEntity",
          "The six reporting entities, each booking in its own currency. Row-level security filters this table, so an "
          "entity scope reaches every fact through it.",
          [S("EntityID", hidden=True), S("EntityName"), S("Region"),
           S("LocalCurrency", desc="Currency the entity's ledger is kept in; the group reports in AUD."),
           S("EntityLabel", desc="Entity with its currency, for axes: Northstar UK (GBP)."),
           S("CurrencyRole", desc="Reporting currency (AUD) or foreign currency - the group's translation exposure."),
           # Last, because that is where Power BI holds it: the column was added to the
           # view after the model was first built, and a save rewrites the file to match.
           S("EntityShort", sort_by="EntityName",
             desc="Entity without the group prefix, for chart axes: UK, US, SG, DE, CA, Holdings.")],
          hierarchies=[("Region Entity", ["Region", "EntityName"])]),

    Table("DimDepartment", "vw_DimDepartment",
          "The ten cost centres. Row-level security filters this table for department-scoped users.",
          [S("DepartmentID", hidden=True), S("DepartmentName")]),

    Table("DimAccount", "vw_DimAccount",
          "Chart of accounts. NaturalSign turns the ledger's credit balances into positive revenue; IsOperating marks "
          "the scope the budget covers (revenue, COGS, operating expense).",
          [S("AccountCode", hidden=True), S("AccountName", sort_by="AccountOrder"),
           S("AccountGroup", sort_by="GroupOrder"),
           S("Statement", desc="Income statement or balance sheet. The ledger extract is income statement only."),
           I("GroupOrder", fmt="0", hidden=True),
           I("NaturalSign", fmt="0", hidden=True, desc="-1 for revenue: a credit presented as a positive number."),
           B("IsIncome", hidden=True), B("IsOperating", desc="Revenue, COGS and operating expense: the budgeted scope."),
           B("IsBudgeted", desc="False for interest, FX gain/loss and tax, which have actuals but no plan."),
           S("AccountLabel", sort_by="AccountOrder"), I("AccountOrder", fmt="0", hidden=True)],
          hierarchies=[("Chart of Accounts", ["AccountGroup", "AccountLabel"])]),

    Table("DimCustomer", "vw_DimCustomer",
          "Customers, with a 'Not specified' member for ledger lines that name none.",
          [S("CustomerID", hidden=True), S("CustomerName"), S("Industry"),
           S("Country", category="Country"), S("Segment")]),

    Table("DimVendor", "vw_DimVendor",
          "Suppliers, with a 'Not specified' member for ledger lines that name none.",
          [S("VendorID", hidden=True), S("VendorName"), S("VendorCategory"), S("Country", category="Country")]),

    Table("DimPLLine", "vw_DimPLLine",
          "The income statement as a layout: account groups, subtotals and margins in reporting order. Disconnected - "
          "[P&L Line Value] resolves each line, so the statement reads as a statement instead of a list of accounts.",
          [I("LineKey", fmt="0", hidden=True), S("LineName", sort_by="LineKey"),
           S("LineType", desc="Group, Subtotal or Ratio. Ratio lines are formatted as percentages."),
           I("FavourableSign", fmt="0", hidden=True,
             desc="+1 where more is better, -1 for cost lines: turns actual less plan into a favourable-positive variance."),
           B("IsBudgeted", desc="False below operating profit, where the plan has no lines.")]),

    Table("DimAgeingBucket", "vw_DimAgeingBucket",
          "Ageing buckets for receivables and payables. Disconnected: the measures age each document AS OF the balance "
          "date, so the ageing is correct for any period selected, not only the as-of date.",
          [I("BucketOrder", fmt="0", hidden=True), S("BucketName", sort_by="BucketOrder"),
           I("MinDaysPastDue", fmt="0", hidden=True), I("MaxDaysPastDue", fmt="0", hidden=True),
           B("IsPastDue", desc="False only for the Current bucket (not yet due).")]),

    Table("DimScenario", "vw_DimScenario",
          "Scenario drivers for the full-year outlook: revenue, operating expense and exchange-rate assumptions. "
          "ILLUSTRATIVE PLANNING ASSUMPTIONS, not supplied data - the source's forecast 'Scenario' label carries no "
          "information (data quality report, finding 5). Disconnected.",
          [I("ScenarioKey", fmt="0", hidden=True), S("ScenarioName", sort_by="ScenarioKey"),
           D("RevenueChangePct", fmt="+0.0%;-0.0%;0.0%"), D("OpexChangePct", fmt="+0.0%;-0.0%;0.0%"),
           D("AUDChangePct", fmt="+0.0%;-0.0%;0.0%",
             desc="Positive strengthens the AUD, lowering the translated result of foreign-currency entities."),
           S("Description")]),

    Table("DimSensitivityStep", "vw_DimSensitivityStep",
          "Revenue steps from -20% to +20% for the profit sensitivity curve. Disconnected.",
          [D("StepPct", fmt="+0%;-0%;0%", hidden=True), S("StepLabel", sort_by="StepPct")]),

    Table("FxRateMonthly", "vw_FxRateMonthly",
          "Monthly average and closing AUD rates per currency, derived from the daily file. The average rate is what "
          "the ledger is translated at (IAS 21 practice); MeanAbsDailyMovePct records how noisy the daily source is.",
          [T("MonthStart", hidden=True), S("CurrencyCode"),
           D("AvgAUDPerUnit", fmt="0.0000", desc="Mean of the month's daily rates: the translation rate."),
           D("ClosingAUDPerUnit", fmt="0.0000", hidden=True), D("MinAUDPerUnit", fmt="0.0000", hidden=True),
           D("MaxAUDPerUnit", fmt="0.0000", hidden=True), I("DaysInMonth", fmt="0", hidden=True),
           D("MeanAbsDailyMovePct", fmt="0.00", hidden=True,
             desc="Average absolute day-on-day move, in per cent, of the supplied daily rates.")]),

    Table("FactGL", "vw_FactGL",
          "One general-ledger line, in its local currency and translated to AUD at its month's average rate. Ledger "
          "sign: revenue negative, costs positive. Used for detail and drill-through; the income statement reads "
          "FactFinancials.",
          [S("GLTxnID", hidden=True), T("Date", hidden=True), S("EntityID", hidden=True),
           S("DepartmentID", hidden=True), S("AccountCode", hidden=True),
           S("CurrencyCode", desc="Currency the line was booked in."),
           D("AmountLocal", fmt="#,0.00", hidden=True, summarize="sum",
             desc="Amount in the booking currency. Not additive across currencies - use AmountAUD."),
           S("CustomerID", hidden=True), S("VendorID", hidden=True),
           S("PostingStatus", desc="Posted or Accrued. Both are actuals; accruals are never reversed in this source."),
           D("FxRateAvg", fmt="0.0000", hidden=True), D("AmountAUD", fmt="#,0.00", hidden=True, summarize="sum"),
           D("AmountAUDSpot", fmt="#,0.00", hidden=True, summarize="sum",
             desc="The same line translated at its own day's rate, kept to show the choice of rate is immaterial.")]),

    Table("FactFinancials", "vw_FactFinancials",
          "Actual, budget and forecast at one grain - version x month x entity x department x account - so every plan "
          "comparison is one measure under a different version. Actual rows are the ledger summed to the month and "
          "equal FactGL to the cent.",
          [S("VersionID", hidden=True, desc="ACT, BUD or FC. Filtered by the Plan Version calculation group; never summed."),
           T("MonthStart", hidden=True), S("EntityID", hidden=True), S("DepartmentID", hidden=True),
           S("AccountCode", hidden=True),
           D("AmountAUD", fmt="#,0.00", hidden=True, summarize="sum"),
           D("AmountLocal", fmt="#,0.00", hidden=True, summarize="sum", desc="Actual rows only."),
           D("AmountAUDAtPYRate", fmt="#,0.00", hidden=True, summarize="sum",
             desc="Actual rows retranslated at last year's monthly average rate: the constant-currency basis."),
           I("PostingLines", fmt="#,0", hidden=True, summarize="sum",
             desc="Ledger lines behind an actual row; blank on plan rows, which is how unposted budget lines are counted."),
           S("ScenarioLabel",
             desc="The forecast file's label. Kept as an attribute and reported as a data-quality finding: it is one "
                  "random label per line, not a scenario.")]),

    Table("FactARInvoice", "vw_FactARInvoice",
          "One customer invoice. InvoiceDate is the active date; due date and receipt date are inactive role-playing "
          "relationships. Whether an invoice is open is computed from dates against the balance date, not read from "
          "SourceStatus, which reflects an extract taken after the as-of date.",
          [S("InvoiceID", hidden=True), T("InvoiceDate", hidden=True), T("DueDate", hidden=True),
           T("PaidDate", hidden=True), S("CustomerID", hidden=True), S("EntityID", hidden=True),
           D("InvoiceAmountAUD", fmt="#,0.00", hidden=True, summarize="sum"),
           S("SourceStatus", desc="Status in the extract. Balances never use it - see IsOpenAsOf."),
           I("TermsDays", fmt="0", desc="Payment terms: 14, 30, 45 or 60 days."),
           I("DaysToPay", fmt="0", hidden=True), I("DaysLate", fmt="0", hidden=True),
           B("IsPaidAfterAsOf", desc="Receipt dated after the as-of date: the invoice was open on it."),
           B("IsOpenAsOf", desc="Open on the as-of date. The measures recompute this for any balance date."),
           I("DaysPastDueAsOf", fmt="0", hidden=True), I("AgeingBucketAsOf", fmt="0", hidden=True)]),

    Table("FactAPBill", "vw_FactAPBill",
          "One supplier bill, on the same pattern as receivables: bill date active, due and payment dates inactive, "
          "open computed from dates.",
          [S("BillID", hidden=True), T("BillDate", hidden=True), T("DueDate", hidden=True), T("PaidDate", hidden=True),
           S("VendorID", hidden=True), S("EntityID", hidden=True),
           D("BillAmountAUD", fmt="#,0.00", hidden=True, summarize="sum"),
           S("SourceStatus", desc="Status in the extract. Balances never use it - see IsOpenAsOf."),
           I("TermsDays", fmt="0", desc="Payment terms: 14, 30 or 45 days."),
           I("DaysToPay", fmt="0", hidden=True), I("DaysLate", fmt="0", hidden=True),
           B("IsPaidAfterAsOf"), B("IsOpenAsOf"), I("DaysPastDueAsOf", fmt="0", hidden=True),
           I("AgeingBucketAsOf", fmt="0", hidden=True)]),

    Table("FactCashBalance", "vw_FactCashBalance",
          "One entity's closing cash on one day. A stock, not a flow: measures read the balance ON the balance date and "
          "never sum it over time.",
          [T("Date", hidden=True), S("EntityID", hidden=True),
           D("ClosingCashAUD", fmt="#,0.00", hidden=True, summarize="sum"),
           B("IsFloorValue", desc="Exactly 50,000.00 - a floor in the generated source, not a treasury decision.")]),

    Table("DataQualityMetric", "vw_DataQualityMetric",
          "Data-quality figures computed live in SQL from dbo, so the Data & Method page can never drift from the data.",
          [I("SortOrder", fmt="0", hidden=True), S("Metric", sort_by="SortOrder"),
           D("MetricValue", fmt="#,0.00", hidden=True, summarize="sum"),
           S("Unit", desc="How to read the value: days, lines, share, AUD.")]),

    Table("ModelConfig", "vw_ModelConfig",
          "Disconnected configuration: as-of date, reporting currency, translation method, financial-year start. Read "
          "by measures so nothing is hard-coded.",
          [S("ConfigKey"), S("ConfigValue"), S("Description")], hidden=True),

    Table("SecurityUserAccess", "vw_SecurityUserAccess",
          "Row-level security mapping: user email to entity and department, or ALL. Disconnected; read by the role.",
          [S("UserEmail"), S("Role"), S("EntityID"), S("DepartmentID")], hidden=True),

    Table("_Measures", MEASURES_TABLE_M,
          "Holds every business measure. The single hidden column exists only because a table needs one.",
          [S("Placeholder", hidden=True)]),
]

# (from table.column, to table.column, active)
RELATIONSHIPS = [
    ("FactGL.Date", "DimDate.Date", True),
    ("FactGL.EntityID", "DimEntity.EntityID", True),
    ("FactGL.DepartmentID", "DimDepartment.DepartmentID", True),
    ("FactGL.AccountCode", "DimAccount.AccountCode", True),
    ("FactGL.CustomerID", "DimCustomer.CustomerID", True),
    ("FactGL.VendorID", "DimVendor.VendorID", True),
    ("FactFinancials.MonthStart", "DimDate.Date", True),
    ("FactFinancials.EntityID", "DimEntity.EntityID", True),
    ("FactFinancials.DepartmentID", "DimDepartment.DepartmentID", True),
    ("FactFinancials.AccountCode", "DimAccount.AccountCode", True),
    ("FactARInvoice.InvoiceDate", "DimDate.Date", True),
    ("FactARInvoice.DueDate", "DimDate.Date", False),
    ("FactARInvoice.PaidDate", "DimDate.Date", False),
    ("FactARInvoice.CustomerID", "DimCustomer.CustomerID", True),
    ("FactARInvoice.EntityID", "DimEntity.EntityID", True),
    ("FactAPBill.BillDate", "DimDate.Date", True),
    ("FactAPBill.DueDate", "DimDate.Date", False),
    ("FactAPBill.PaidDate", "DimDate.Date", False),
    ("FactAPBill.VendorID", "DimVendor.VendorID", True),
    ("FactAPBill.EntityID", "DimEntity.EntityID", True),
    ("FactCashBalance.Date", "DimDate.Date", True),
    ("FactCashBalance.EntityID", "DimEntity.EntityID", True),
    ("FxRateMonthly.MonthStart", "DimDate.Date", True),
]

RLS_ROLE = "Entity and Department Access"
USER_SCOPE = """VAR UserScope =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[{col}] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    "ALL" IN UserScope || {table}[{key}] IN UserScope"""

# A department-scoped user sees their department's income statement across
# entities, and no receivables, payables or cash: those facts carry an entity but
# no department, so company-wide treasury data is not part of a cost-centre view.
DEPARTMENT_ALL = """VAR UserScope =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[DepartmentID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    "ALL" IN UserScope"""

RLS_FILTERS = {
    "DimEntity": USER_SCOPE.format(col="EntityID", table="DimEntity", key="EntityID"),
    "DimDepartment": USER_SCOPE.format(col="DepartmentID", table="DimDepartment", key="DepartmentID"),
    "FactARInvoice": DEPARTMENT_ALL,
    "FactAPBill": DEPARTMENT_ALL,
    "FactCashBalance": DEPARTMENT_ALL,
    # a user may see only their own mapping row
    "SecurityUserAccess": "SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()",
}

PARAMETERS = [
    ("SqlServer", "localhost\\SQLEXPRESS", "SQL Server instance hosting FinancePlanningBI. The only place the server is named."),
    ("SqlDatabase", "FinancePlanningBI", "Database holding the analytics views."),
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


def render_calc_group(g):
    """A calculation group table: the group, its items, and the Name / Ordinal
    columns Power BI expects. Item expressions sit one level below the item, and
    the order the items are written IS the reporting order: an explicit `ordinal:`
    only repeats it, and Power BI strips it out again on the next save."""
    L = desc_lines(g["desc"], "") + [f"table {q(g['name'])}", f"\tlineageTag: {tag(g['name'])}", "",
                                     "\tcalculationGroup", f"\t\tprecedence: {g['precedence']}", ""]
    for item, desc, dax, fmt in g["items"]:
        L += desc_lines(desc, "\t\t")
        L += [f"\t\tcalculationItem {q(item)} ="]
        L += ["\t\t\t\t" + b if b else "" for b in dax.strip("\n").split("\n")]
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
    from model_measures import CALC_GROUPS, MEASURES

    names = [t.name for t in TABLES]
    group_names = [g["name"] for g in CALC_GROUPS]

    tdir = DEF / "tables"
    if tdir.exists():
        shutil.rmtree(tdir)
    for t in TABLES:
        write(tdir / f"{t.name}.tmdl", render_table(t, MEASURES if t.name == "_Measures" else []))
    for g in CALC_GROUPS:
        write(tdir / f"{g['name']}.tmdl", render_calc_group(g))

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
