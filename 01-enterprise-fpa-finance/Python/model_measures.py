# -*- coding: utf-8 -*-
"""
Core measure layer, consumed by 02_generate_semantic_model.py.

Conventions (carried from projects 1 and 2, see Documentation/semantic_model.md):
  * Every measure lives in _Measures, with a folder, a format and a description.
  * LEDGER SIGN IN, PRESENTATION SIGN OUT. The data keeps debit + / credit -;
    measures show revenue, costs and profit as positive numbers, and a variance
    is positive when it is FAVOURABLE.
  * The version (Actual / Budget / Forecast) is chosen by the 'Plan Version'
    calculation group, never by summing versions. A measure with no version
    filter means ACTUAL.
  * Plan comparisons stop at operating profit: interest, FX and tax have no
    budget, so their variance is BLANK, never 100% (PROJECT_STATE D10).
  * Balances are as of a date: [Balance Date] = the last day in context, capped
    at the as-of date. An invoice paid after that date was open on it (D4).
  * No variable is named after a DAX function or reserved word.
  * Calculation items never reference another measure - only SELECTEDMEASURE and
    columns - so nothing can be applied twice.
"""

F_CTRL = "01 Model Controls"
F_PL = "02 Income Statement"
F_PLAN = "03 Plan vs Actual"
F_TIME = "04 Time Comparison"
F_FX = "05 FX & Constant Currency"
F_GL = "06 Ledger Detail"
F_WC = "07 Working Capital"
F_CASH = "08 Cash"
F_SCEN = "09 Scenario Planning"
F_DQ = "10 Data Quality"
F_FMT = "11 Report Formatting"

AUD0 = r"\$#,0"
AUD2 = r"\$#,0.00"
AUDVAR = r"+\$#,0;-\$#,0;\$0"
N0, N1, N2 = "#,0", "#,0.0", "#,0.00"
PCT, PCT2 = "0.0%", "0.00%"
PCTVAR = "+0.0%;-0.0%;0.0%"
PP = "+0.0 pp;-0.0 pp;0.0 pp"
RATE = "0.0000"
DATEF = "yyyy-mm-dd"

# Cell colours for the variance heatmap. The panel colour must match the report's
# untinted panel (only cards are tinted toward their own hue), so a cell inside the dead
# zone disappears into the matrix. See the theme rules in the visual catalogue.
# Signal shading uses a DEAD ZONE, not a gradient: inside |z| < 2 a cell keeps the
# panel colour, so noise is never tinted as if it were news.
C_PANEL = "#151A23"
C_FAV_STRONG, C_FAV = "#1F9D55", "#14532D"
C_UNFAV_STRONG, C_UNFAV = "#DC2626", "#4C1D1D"
# A bar is not a cell background: it carries the report's own signal green and red.
C_BAR_FAV, C_BAR_UNFAV = "#22C55E", "#EF4444"


def m(name, folder, fmt, desc, dax, hidden=False):
    return {"name": name, "folder": folder, "fmt": fmt, "desc": desc, "dax": dax, "hidden": hidden}


def CONFIG(key):
    return (f'CALCULATE (\n        SELECTEDVALUE ( ModelConfig[ConfigValue] ),\n'
            f'        REMOVEFILTERS ( ModelConfig ),\n        ModelConfig[ConfigKey] = "{key}"\n    )')


# Inlined as-of date: calculation items must not reference measures.
ASOF_INLINE = """VAR AsOfText =
    CALCULATE ( SELECTEDVALUE ( ModelConfig[ConfigValue] ), REMOVEFILTERS ( ModelConfig ), ModelConfig[ConfigKey] = "AsOfDate" )
VAR AsOf =
    DATE ( VALUE ( LEFT ( AsOfText, 4 ) ), VALUE ( MID ( AsOfText, 6, 2 ) ), VALUE ( RIGHT ( AsOfText, 2 ) ) )
VAR EndDate =
    MIN ( MAX ( DimDate[Date] ), AsOf )"""


def ZSCORE(measure):
    """A month's variance against its own previous twelve months. The plan is
    noisy at line level (audit: a budget line moves a median 57% between months),
    so a variance is called out only when it departs from that line's usual range."""
    return f"""VAR CurrentMonth = MAX ( DimDate[MonthStart] )
VAR MonthsInContext = DISTINCTCOUNT ( DimDate[MonthStart] )
VAR CurrentValue = {measure}
VAR History =
    ADDCOLUMNS (
        CALCULATETABLE (
            VALUES ( DimDate[MonthStart] ),
            REMOVEFILTERS ( DimDate ),
            DimDate[MonthStart] < CurrentMonth,
            DimDate[MonthStart] >= EDATE ( CurrentMonth, -12 )
        ),
        "@Variance",
            VAR PriorMonth = DimDate[MonthStart]
            RETURN CALCULATE ( {measure}, REMOVEFILTERS ( DimDate ), DimDate[MonthStart] = PriorMonth )
    )
VAR Usable = FILTER ( History, NOT ISBLANK ( [@Variance] ) )
VAR Centre = AVERAGEX ( Usable, [@Variance] )
VAR Spread = STDEVX.S ( Usable, [@Variance] )
RETURN
    IF (
        MonthsInContext = 1 && COUNTROWS ( Usable ) >= 6 && NOT ISBLANK ( CurrentValue ) && Spread > 0,
        DIVIDE ( CurrentValue - Centre, Spread )
    )"""


def SIGNAL_COLOUR(zmeasure):
    return f"""VAR Z = {zmeasure}
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Z ), BLANK (),
        Z >= 3, "{C_FAV_STRONG}",
        Z >= 2, "{C_FAV}",
        Z <= -3, "{C_UNFAV_STRONG}",
        Z <= -2, "{C_UNFAV}",
        "{C_PANEL}"
    )"""


# Open on a date: issued by it and not paid by it. Status is never read - the
# extract records 769 receipts and 395 payments dated after the as-of date (D4).
def OPEN_AS_OF(table, amount, docdate):
    return f"""VAR EndDate = [Balance Date]
RETURN
    CALCULATE (
        {amount},
        REMOVEFILTERS ( DimDate ),
        {table}[{docdate}] <= EndDate,
        FILTER ( ALL ( {table}[PaidDate] ), ISBLANK ( {table}[PaidDate] ) || {table}[PaidDate] > EndDate )
    )"""


MEASURES = [
    # ------------------------------------------------------------ controls ---
    m("As Of Date", F_CTRL, DATEF,
      "Last day of the general ledger, read from ModelConfig. Every figure, balance and ageing is stated as of this "
      "date. Never TODAY().",
      f"""VAR AsOfText =
    {CONFIG("AsOfDate")}
RETURN
    IF (
        NOT ISBLANK ( AsOfText ),
        DATE ( VALUE ( LEFT ( AsOfText, 4 ) ), VALUE ( MID ( AsOfText, 6, 2 ) ), VALUE ( RIGHT ( AsOfText, 2 ) ) )
    )"""),
    m("Reporting Currency", F_CTRL, None,
      "Group reporting currency (AUD). The ledger is translated at monthly average rates; everything else is supplied in it.",
      CONFIG("ReportingCurrency").replace("\n    ", "\n")),
    m("Balance Date", F_CTRL, DATEF,
      "The date every balance is stated on: the last day in the current filter context, capped at the as-of date. With "
      "FY26 selected it is 30 Jun 2026; with no date filter, the as-of date. BLANK for a period that starts after "
      "the as-of date, so a balance never runs flat into months that have no data.",
      """VAR LastInContext = MAX ( DimDate[Date] )
VAR FirstInContext = MIN ( DimDate[Date] )
VAR AsOf = [As Of Date]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( LastInContext ), AsOf,
        FirstInContext > AsOf, BLANK (),
        MIN ( LastInContext, AsOf )
    )"""),
    m("Months Remaining in FY", F_CTRL, N0,
      "Whole months between the as-of date and the end of the financial year it falls in: the months the outlook has to project.",
      """VAR AsOf = [As Of Date]
VAR FinancialYearEnd = DATE ( YEAR ( AsOf ) + IF ( MONTH ( AsOf ) >= 7, 1, 0 ), 6, 30 )
RETURN
    DATEDIFF ( AsOf, FinancialYearEnd, MONTH )"""),
    m("Report Context", F_CTRL, None,
      "The one-line context every page carries: as-of date, period in view, currency and basis.",
      """VAR AsOf = [As Of Date]
VAR PeriodLabel =
    IF (
        ISFILTERED ( DimDate[FinancialYear] ),
        CONCATENATEX ( VALUES ( DimDate[FinancialYear] ), DimDate[FinancialYear], ", ", DimDate[FinancialYear] ),
        "FY22 to FY27"
    )
RETURN
    "As of " & FORMAT ( AsOf, "d mmm yyyy" ) & "   |   " & PeriodLabel & "   |   " & [Reporting Currency]
        & " at monthly average rates   |   Synthetic data\""""),
    m("Selected Financial Year", F_CTRL, None,
      "Financial year or years in the current filter context, for page titles.",
      """IF (
    ISFILTERED ( DimDate[FinancialYear] ),
    CONCATENATEX ( VALUES ( DimDate[FinancialYear] ), DimDate[FinancialYear], ", ", DimDate[FinancialYear] ),
    "All financial years"
)"""),

    # ------------------------------------------------------ income statement ---
    m("PL Ledger Amount", F_PL, AUD2,
      "Ledger-sign amount (debit +, credit -) for the version in context. With no version filter it is the ACTUAL: "
      "versions are never summed. Every income-statement measure builds on this one.",
      """IF (
    ISFILTERED ( FactFinancials[VersionID] ),
    SUM ( FactFinancials[AmountAUD] ),
    CALCULATE ( SUM ( FactFinancials[AmountAUD] ), FactFinancials[VersionID] = "ACT" )
)""", hidden=True),
    m("Is Actual Version", F_PL, None,
      "TRUE when the context is the actuals - no version filter, or exactly ACT. Below-the-line measures use it to stay "
      "blank under Budget and Forecast, which do not carry those accounts.",
      """VAR VersionsInFilter = FILTERS ( FactFinancials[VersionID] )
RETURN
    NOT ISFILTERED ( FactFinancials[VersionID] )
        || ( COUNTROWS ( VersionsInFilter ) = 1 && "ACT" IN VersionsInFilter )""", hidden=True),
    m("Revenue", F_PL, AUD0,
      "Revenue accounts (4000-4020), presented positive. Credits in the ledger, so the ledger sum is negated.",
      """- CALCULATE ( [PL Ledger Amount], KEEPFILTERS ( DimAccount[AccountGroup] = "Revenue" ) )"""),
    m("COGS", F_PL, AUD0,
      "Cost of goods sold (5000-5100), presented positive.",
      """CALCULATE ( [PL Ledger Amount], KEEPFILTERS ( DimAccount[AccountGroup] = "COGS" ) )"""),
    m("Gross Profit", F_PL, AUD0, "Revenue less cost of goods sold.", "[Revenue] - [COGS]"),
    m("Gross Margin %", F_PL, PCT,
      "Gross profit as a share of revenue. Currency-neutral: translation moves revenue and COGS by the same rate, so "
      "entities can be compared on it (PROJECT_STATE D12).",
      "DIVIDE ( [Gross Profit], [Revenue] )"),
    m("Operating Expense", F_PL, AUD0, "Operating expense accounts (6000-6110), presented positive.",
      """CALCULATE ( [PL Ledger Amount], KEEPFILTERS ( DimAccount[AccountGroup] = "Operating Expense" ) )"""),
    m("Operating Profit", F_PL, AUD0,
      "Gross profit less operating expense: the last line the budget covers, and so the last line with a variance.",
      "[Gross Profit] - [Operating Expense]"),
    m("Operating Margin %", F_PL, PCT, "Operating profit as a share of revenue.",
      "DIVIDE ( [Operating Profit], [Revenue] )"),
    m("Other Expense (Net)", F_PL, AUD0,
      "Interest and FX gain or loss, net (7000, 7100). Actuals only - unbudgeted, so never shown as a variance.",
      """IF (
    [Is Actual Version],
    CALCULATE ( [PL Ledger Amount], KEEPFILTERS ( DimAccount[AccountGroup] = "Other Expense" ) )
)"""),
    m("Tax Expense", F_PL, AUD0, "Tax expense (7200). Actuals only - unbudgeted.",
      """IF (
    [Is Actual Version],
    CALCULATE ( [PL Ledger Amount], KEEPFILTERS ( DimAccount[AccountGroup] = "Tax" ) )
)"""),
    m("Net Profit", F_PL, AUD0,
      "Operating profit less other expense and tax. Actuals only: a budget net profit would silently equal the budget "
      "operating profit, because the plan has no below-the-line lines.",
      "IF ( [Is Actual Version], [Operating Profit] - [Other Expense (Net)] - [Tax Expense] )"),
    m("Net Margin %", F_PL, PCT, "Net profit as a share of revenue.", "DIVIDE ( [Net Profit], [Revenue] )"),
    m("COGS % of Revenue", F_PL, PCT, "Cost of goods sold as a share of revenue; currency-neutral.",
      "DIVIDE ( [COGS], [Revenue] )"),
    m("Opex % of Revenue", F_PL, PCT,
      "Operating expense as a share of revenue; currency-neutral, so it compares entities without the exchange-rate "
      "level distorting them.",
      "DIVIDE ( [Operating Expense], [Revenue] )"),
    m("P&L Line Value", F_PL, AUD0,
      "The value of the income-statement line in context (DimPLLine): groups, subtotals and margins in one measure, so "
      "the statement reads as a statement. Ratio lines are formatted as percentages by the calculation group.",
      """SWITCH (
    SELECTEDVALUE ( DimPLLine[LineKey] ),
    1, [Revenue],
    2, [COGS],
    3, [Gross Profit],
    4, [Gross Margin %],
    5, [Operating Expense],
    6, [Operating Profit],
    7, [Operating Margin %],
    8, [Other Expense (Net)],
    9, [Tax Expense],
    10, [Net Profit],
    11, [Net Margin %]
)"""),
    m("P&L Bridge Amount", F_PL, AUDVAR,
      "The statement line as a CONTRIBUTION to profit: revenue positive, every cost negative, so a waterfall of the "
      "group lines nets exactly to net profit. Use it only with DimPLLine filtered to the group lines.",
      """VAR ContributionSign = SELECTEDVALUE ( DimPLLine[FavourableSign] )
RETURN
    IF ( NOT ISBLANK ( ContributionSign ), [P&L Line Value] * ContributionSign )"""),
    m("Account Amount", F_PL, AUD0,
      "Account-level amount in its natural sign: revenue positive because it is income, costs positive because they are "
      "costs. Use it for account detail; a grand total that mixes both is meaningless by construction.",
      """SUMX (
    VALUES ( DimAccount[NaturalSign] ),
    CALCULATE ( [PL Ledger Amount] ) * DimAccount[NaturalSign]
)"""),

    # -------------------------------------------------------- plan vs actual ---
    m("Revenue Actual", F_PLAN, AUD0, "Revenue, actuals explicitly - for charts that show versions side by side.",
      """CALCULATE ( [Revenue], FactFinancials[VersionID] = "ACT" )"""),
    m("Revenue Budget", F_PLAN, AUD0, "Revenue, budget version.",
      """CALCULATE ( [Revenue], FactFinancials[VersionID] = "BUD" )"""),
    m("Revenue Forecast", F_PLAN, AUD0,
      "Revenue, forecast version (one version: the source Scenario label is not a scenario).",
      """CALCULATE ( [Revenue], FactFinancials[VersionID] = "FC" )"""),
    m("Revenue vs Budget", F_PLAN, AUDVAR,
      "Actual less budget revenue. Positive is favourable. Blank where there is no budget line.",
      """VAR Plan = [Revenue Budget]
RETURN
    IF ( NOT ISBLANK ( Plan ), [Revenue Actual] - Plan )"""),
    m("Revenue vs Budget %", F_PLAN, PCTVAR, "Revenue variance as a share of budget.",
      "DIVIDE ( [Revenue vs Budget], [Revenue Budget] )"),
    m("Revenue Achievement %", F_PLAN, PCT,
      "Actual revenue as a share of budget. Structurally about 69% in every month of the data - a plan-calibration "
      "finding, not monthly news (PROJECT_STATE D11).",
      "DIVIDE ( [Revenue Actual], [Revenue Budget] )"),
    m("COGS Budget", F_PLAN, AUD0, "Cost of goods sold, budget version.",
      """CALCULATE ( [COGS], FactFinancials[VersionID] = "BUD" )"""),
    m("Gross Profit Budget", F_PLAN, AUD0, "Gross profit, budget version.",
      """CALCULATE ( [Gross Profit], FactFinancials[VersionID] = "BUD" )"""),
    m("Gross Margin % Budget", F_PLAN, PCT, "Gross margin, budget version.",
      """CALCULATE ( [Gross Margin %], FactFinancials[VersionID] = "BUD" )"""),
    m("Operating Expense Actual", F_PLAN, AUD0, "Operating expense, actuals explicitly.",
      """CALCULATE ( [Operating Expense], FactFinancials[VersionID] = "ACT" )"""),
    m("Operating Expense Budget", F_PLAN, AUD0, "Operating expense, budget version.",
      """CALCULATE ( [Operating Expense], FactFinancials[VersionID] = "BUD" )"""),
    m("Operating Expense Forecast", F_PLAN, AUD0, "Operating expense, forecast version.",
      """CALCULATE ( [Operating Expense], FactFinancials[VersionID] = "FC" )"""),
    m("Operating Expense vs Budget", F_PLAN, AUDVAR,
      "Budget less actual operating expense: an UNDERSPEND is positive, because for a cost that is the favourable direction.",
      """VAR Plan = [Operating Expense Budget]
RETURN
    IF ( NOT ISBLANK ( Plan ), Plan - [Operating Expense Actual] )"""),
    m("Operating Expense vs Budget %", F_PLAN, PCTVAR,
      "Operating-expense underspend as a share of budget. Positive is favourable.",
      "DIVIDE ( [Operating Expense vs Budget], [Operating Expense Budget] )"),
    m("Operating Profit Actual", F_PLAN, AUD0, "Operating profit, actuals explicitly.",
      """CALCULATE ( [Operating Profit], FactFinancials[VersionID] = "ACT" )"""),
    m("Operating Profit Budget", F_PLAN, AUD0, "Operating profit, budget version.",
      """CALCULATE ( [Operating Profit], FactFinancials[VersionID] = "BUD" )"""),
    m("Operating Profit Forecast", F_PLAN, AUD0, "Operating profit, forecast version.",
      """CALCULATE ( [Operating Profit], FactFinancials[VersionID] = "FC" )"""),
    m("Operating Profit vs Budget", F_PLAN, AUDVAR,
      "Actual less budget operating profit. Positive is favourable - a smaller loss counts as favourable.",
      """VAR Plan = [Operating Profit Budget]
RETURN
    IF ( NOT ISBLANK ( Plan ), [Operating Profit Actual] - Plan )"""),
    m("Forecast vs Budget % (Revenue)", F_PLAN, PCTVAR,
      "How far the forecast departs from the budget. It barely does: the forecast tracks the plan, not the actuals "
      "(audit finding 8).",
      "DIVIDE ( [Revenue Forecast] - [Revenue Budget], [Revenue Budget] )"),
    m("Revenue Forecast Error %", F_PLAN, PCTVAR,
      "Actual less forecast revenue, as a share of forecast: how wrong the forecast was.",
      "DIVIDE ( [Revenue Actual] - [Revenue Forecast], [Revenue Forecast] )"),
    m("Revenue vs Budget Z-Score", F_PLAN, N2,
      "This month's revenue variance against the previous twelve months of the same variance, in standard deviations. "
      "The gap to plan is structural, so only a SHIFT in it is news; needs at least six comparable months.",
      ZSCORE("[Revenue vs Budget %]")),
    m("Opex vs Budget Z-Score", F_PLAN, N2,
      "This month's operating-expense variance against its own previous twelve months, in standard deviations. "
      "Positive means a larger underspend than usual.",
      ZSCORE("[Operating Expense vs Budget %]")),

    # ------------------------------------------------------ time comparison ---
    m("Revenue Prior Year", F_TIME, AUD0,
      "Revenue in the same window one year earlier, like for like: the window ends at the balance date, so a part-year "
      "is never compared with a full one.",
      """VAR FirstActualMonth =
    CALCULATE ( MIN ( FactFinancials[MonthStart] ), REMOVEFILTERS (), FactFinancials[VersionID] = "ACT" )
VAR StartDate = MIN ( DimDate[Date] )
VAR EndDate = [Balance Date]
RETURN
    IF (
        EDATE ( StartDate, -12 ) >= FirstActualMonth,
        CALCULATE ( [Revenue], DATESBETWEEN ( DimDate[Date], EDATE ( StartDate, -12 ), EDATE ( EndDate, -12 ) ) )
    )"""),
    m("Revenue YoY %", F_TIME, PCTVAR, "Revenue growth against the same window last year.",
      "DIVIDE ( [Revenue] - [Revenue Prior Year], [Revenue Prior Year] )"),
    m("Operating Expense Prior Year", F_TIME, AUD0, "Operating expense in the same window one year earlier.",
      """VAR FirstActualMonth =
    CALCULATE ( MIN ( FactFinancials[MonthStart] ), REMOVEFILTERS (), FactFinancials[VersionID] = "ACT" )
VAR StartDate = MIN ( DimDate[Date] )
VAR EndDate = [Balance Date]
RETURN
    IF (
        EDATE ( StartDate, -12 ) >= FirstActualMonth,
        CALCULATE ( [Operating Expense], DATESBETWEEN ( DimDate[Date], EDATE ( StartDate, -12 ), EDATE ( EndDate, -12 ) ) )
    )"""),
    m("Operating Expense YoY %", F_TIME, PCTVAR, "Operating-expense change against the same window last year.",
      "DIVIDE ( [Operating Expense] - [Operating Expense Prior Year], [Operating Expense Prior Year] )"),
    m("Operating Profit Prior Year", F_TIME, AUD0, "Operating profit in the same window one year earlier.",
      """VAR FirstActualMonth =
    CALCULATE ( MIN ( FactFinancials[MonthStart] ), REMOVEFILTERS (), FactFinancials[VersionID] = "ACT" )
VAR StartDate = MIN ( DimDate[Date] )
VAR EndDate = [Balance Date]
RETURN
    IF (
        EDATE ( StartDate, -12 ) >= FirstActualMonth,
        CALCULATE ( [Operating Profit], DATESBETWEEN ( DimDate[Date], EDATE ( StartDate, -12 ), EDATE ( EndDate, -12 ) ) )
    )"""),
    m("Revenue FYTD", F_TIME, AUD0,
      "Revenue from 1 July to the balance date, through the Period View calculation group.",
      """CALCULATE ( [Revenue], 'Period View'[Period] = "Year to date" )"""),
    m("Revenue Prior FYTD", F_TIME, AUD0, "The same financial-year-to-date window, one year earlier.",
      """CALCULATE ( [Revenue], 'Period View'[Period] = "Prior year to date" )"""),
    m("Revenue FYTD YoY %", F_TIME, PCTVAR, "Year-to-date revenue growth, like for like.",
      "DIVIDE ( [Revenue FYTD] - [Revenue Prior FYTD], [Revenue Prior FYTD] )"),
    m("Revenue TTM", F_TIME, AUD0,
      "Revenue over the twelve complete months ending on the as-of date. A FIXED window, so it reads the same whatever "
      "period is selected: use it on a card, never on a date axis.",
      """CALCULATE ( [Revenue], REMOVEFILTERS ( DimDate ), DimDate[MonthOffset] >= -11, DimDate[MonthOffset] <= 0 )"""),
    m("Operating Expense TTM", F_TIME, AUD0,
      "Operating expense over the twelve complete months ending on the as-of date. Card-only, like Revenue TTM.",
      """CALCULATE ( [Operating Expense], REMOVEFILTERS ( DimDate ), DimDate[MonthOffset] >= -11, DimDate[MonthOffset] <= 0 )"""),
    m("Operating Profit TTM", F_TIME, AUD0,
      "Operating profit over the twelve complete months ending on the as-of date. Card-only, like Revenue TTM.",
      """CALCULATE ( [Operating Profit], REMOVEFILTERS ( DimDate ), DimDate[MonthOffset] >= -11, DimDate[MonthOffset] <= 0 )"""),
    m("Operating Profit FYTD", F_TIME, AUD0, "Operating profit from 1 July to the balance date.",
      """CALCULATE ( [Operating Profit], 'Period View'[Period] = "Year to date" )"""),

    # --------------------------------------------------- FX / constant currency ---
    m("Revenue at Prior-Year Rates", F_FX, AUD0,
      "Actual revenue retranslated at last year's monthly average rates. The difference from Revenue is exchange rate, "
      "not trading. BLANK unless every actual row in context has a prior-year rate: FY22 has none and FY23 "
      "only half, so a constant-currency growth rate there would be arithmetic on a partial year.",
      """VAR MissingPriorYearRate =
    CALCULATE (
        COUNTROWS ( FactFinancials ),
        FactFinancials[VersionID] = "ACT",
        KEEPFILTERS ( DimAccount[AccountGroup] = "Revenue" ),
        ISBLANK ( FactFinancials[AmountAUDAtPYRate] )
    )
RETURN
    IF (
        ISBLANK ( MissingPriorYearRate ),
        - CALCULATE (
            SUM ( FactFinancials[AmountAUDAtPYRate] ),
            FactFinancials[VersionID] = "ACT",
            KEEPFILTERS ( DimAccount[AccountGroup] = "Revenue" )
        )
    )"""),
    m("Revenue YoY % (Constant Currency)", F_FX, PCTVAR,
      "Revenue growth with the exchange rate held at last year's: the organic part of the move.",
      """VAR ConstantCurrency = [Revenue at Prior-Year Rates]
VAR PriorYear = [Revenue Prior Year]
RETURN
    IF ( NOT ISBLANK ( ConstantCurrency ) && NOT ISBLANK ( PriorYear ), DIVIDE ( ConstantCurrency - PriorYear, PriorYear ) )"""),
    m("FX Translation Effect (Revenue)", F_FX, AUDVAR,
      "Revenue less revenue at prior-year rates: how much of the reported figure is the exchange rate.",
      """VAR ConstantCurrency = [Revenue at Prior-Year Rates]
RETURN
    IF ( NOT ISBLANK ( ConstantCurrency ), [Revenue] - ConstantCurrency )"""),
    m("FX Effect on Revenue Growth (pp)", F_FX, PP,
      "Percentage points of revenue growth explained by the exchange rate: reported growth less constant-currency growth.",
      """VAR Reported = [Revenue YoY %]
VAR ConstantCurrency = [Revenue YoY % (Constant Currency)]
RETURN
    IF ( NOT ISBLANK ( Reported ) && NOT ISBLANK ( ConstantCurrency ), ( Reported - ConstantCurrency ) * 100 )"""),
    m("Operating Profit at Prior-Year Rates", F_FX, AUD0,
      "Actual operating profit retranslated at last year's monthly average rates.",
      """VAR MissingPriorYearRate =
    CALCULATE (
        COUNTROWS ( FactFinancials ),
        FactFinancials[VersionID] = "ACT",
        KEEPFILTERS ( DimAccount[IsOperating] = TRUE () ),
        ISBLANK ( FactFinancials[AmountAUDAtPYRate] )
    )
RETURN
    IF (
        ISBLANK ( MissingPriorYearRate ),
        - CALCULATE (
            SUM ( FactFinancials[AmountAUDAtPYRate] ),
            FactFinancials[VersionID] = "ACT",
            KEEPFILTERS ( DimAccount[IsOperating] = TRUE () )
        )
    )"""),
    m("FX Translation Effect (Operating Profit)", F_FX, AUDVAR,
      "Operating profit less operating profit at prior-year rates.",
      """VAR ConstantCurrency = [Operating Profit at Prior-Year Rates]
RETURN
    IF ( NOT ISBLANK ( ConstantCurrency ), [Operating Profit] - ConstantCurrency )"""),
    m("Average FX Rate", F_FX, RATE,
      "AUD per unit of the currency in context, averaged over the months in view - the rate the ledger was translated at.",
      "AVERAGE ( FxRateMonthly[AvgAUDPerUnit] )"),
    m("FX Rate YoY %", F_FX, PCTVAR, "Change in the average rate against twelve months earlier.",
      """VAR PriorRate = CALCULATE ( [Average FX Rate], DATEADD ( DimDate[Date], -12, MONTH ) )
RETURN
    DIVIDE ( [Average FX Rate] - PriorRate, PriorRate )"""),
    m("FX Mean Daily Move %", F_FX, PCT2,
      "Average absolute day-on-day move in the supplied rates: about 1.7%, several times a real G10 currency, which is "
      "why the ledger is translated at monthly averages (audit finding 6).",
      "DIVIDE ( AVERAGE ( FxRateMonthly[MeanAbsDailyMovePct] ), 100 )"),
    m("Foreign-Currency Revenue Share", F_FX, PCT,
      "Share of revenue booked by entities that do not report in AUD - the group's translation exposure.",
      """DIVIDE (
    CALCULATE ( [Revenue], KEEPFILTERS ( DimEntity[CurrencyRole] = "Foreign currency" ) ),
    [Revenue]
)"""),
    m("Spot vs Average Translation Difference", F_FX, AUD0,
      "What the ledger would total if every line were translated at its own day's rate instead of the month average. "
      "The gap is under 0.01% of the total - the reason the choice is safe as well as standard.",
      "SUM ( FactGL[AmountAUDSpot] ) - SUM ( FactGL[AmountAUD] )"),

    # ------------------------------------------------------- ledger detail ---
    m("GL Amount (AUD)", F_GL, AUD2,
      "Ledger-sign sum of the translated general-ledger lines: revenue negative, costs positive.",
      "SUM ( FactGL[AmountAUD] )"),
    m("GL Lines", F_GL, N0, "Number of general-ledger lines.", "COUNTROWS ( FactGL )"),
    m("Accrued Share of Lines", F_GL, PCT,
      "Share of ledger lines still marked Accrued. About a quarter in every year, including 2022: accruals are never "
      "reversed in this source (audit finding 12).",
      """DIVIDE ( CALCULATE ( COUNTROWS ( FactGL ), FactGL[PostingStatus] = "Accrued" ), COUNTROWS ( FactGL ) )"""),
    m("Vendor Spend (AUD)", F_GL, AUD0, "Cost lines that name a vendor, presented positive.",
      """CALCULATE ( SUM ( FactGL[AmountAUD] ), FactGL[VendorID] <> "V-NONE" )"""),
    m("Customer Revenue (AUD)", F_GL, AUD0, "Revenue lines that name a customer, presented positive.",
      """- CALCULATE ( SUM ( FactGL[AmountAUD] ), KEEPFILTERS ( DimAccount[IsIncome] = TRUE () ) )"""),
    m("Active Vendors", F_GL, N0, "Vendors with at least one ledger line in context.",
      """CALCULATE ( DISTINCTCOUNT ( FactGL[VendorID] ), FactGL[VendorID] <> "V-NONE" )"""),
    m("Active Customers", F_GL, N0, "Customers with at least one ledger line in context.",
      """CALCULATE ( DISTINCTCOUNT ( FactGL[CustomerID] ), FactGL[CustomerID] <> "C-NONE" )"""),

    # ----------------------------------------------------- working capital ---
    m("AR Balance", F_WC, AUD0,
      "Receivables outstanding on the balance date: invoices issued by it and not paid by it. Computed from dates, so a "
      "receipt banked afterwards does not retrospectively close the balance.",
      OPEN_AS_OF("FactARInvoice", "SUM ( FactARInvoice[InvoiceAmountAUD] )", "InvoiceDate")),
    m("AR Open Invoices", F_WC, N0, "Number of invoices outstanding on the balance date.",
      OPEN_AS_OF("FactARInvoice", "COUNTROWS ( FactARInvoice )", "InvoiceDate")),
    m("AR Past Due", F_WC, AUD0, "Outstanding receivables whose due date has passed on the balance date.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE ( [AR Balance], FILTER ( ALL ( FactARInvoice[DueDate] ), FactARInvoice[DueDate] < EndDate ) )"""),
    m("AR Past Due %", F_WC, PCT, "Share of the receivables balance that is past due.",
      "DIVIDE ( [AR Past Due], [AR Balance] )"),
    m("AR Over 90 Days %", F_WC, PCT, "Share of the receivables balance more than 90 days past due.",
      """VAR EndDate = [Balance Date]
VAR Aged =
    CALCULATE ( [AR Balance], FILTER ( ALL ( FactARInvoice[DueDate] ), FactARInvoice[DueDate] < EndDate - 90 ) )
RETURN
    DIVIDE ( Aged, [AR Balance] )"""),
    m("AR Over 365 Days", F_WC, AUD0,
      "Receivables more than a year past due. Nothing is ever written off in this source, so this stock only grows "
      "(audit finding 13).",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE ( [AR Balance], FILTER ( ALL ( FactARInvoice[DueDate] ), FactARInvoice[DueDate] < EndDate - 365 ) )"""),
    m("AR Ageing Amount", F_WC, AUD0,
      "Receivables balance in the ageing bucket in context, aged AS OF the balance date - not a stored bucket, so the "
      "ageing is correct for any period the user picks.",
      """VAR EndDate = [Balance Date]
RETURN
    SUMX (
        VALUES ( DimAgeingBucket[BucketOrder] ),
        VAR LowerDays = CALCULATE ( MIN ( DimAgeingBucket[MinDaysPastDue] ) )
        VAR UpperDays = CALCULATE ( MAX ( DimAgeingBucket[MaxDaysPastDue] ) )
        RETURN
            CALCULATE (
                [AR Balance],
                FILTER (
                    ALL ( FactARInvoice[DueDate] ),
                    FactARInvoice[DueDate] >= EndDate - UpperDays && FactARInvoice[DueDate] <= EndDate - LowerDays
                )
            )
    )"""),
    m("AR Invoiced", F_WC, AUD0, "Value invoiced to customers in the period (by invoice date).",
      "SUM ( FactARInvoice[InvoiceAmountAUD] )"),
    m("AR Invoiced (Last 90 Days)", F_WC, AUD0,
      "Value invoiced in the 90 days ending on the balance date: the DSO denominator.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE (
        SUM ( FactARInvoice[InvoiceAmountAUD] ),
        REMOVEFILTERS ( DimDate ),
        FactARInvoice[InvoiceDate] > EndDate - 90,
        FactARInvoice[InvoiceDate] <= EndDate
    )"""),
    m("DSO (Days)", F_WC, N0,
      "Days sales outstanding: balance divided by the last 90 days of invoicing, times 90. It sits far above the time a "
      "PAID invoice takes to collect, because the balance carries invoices that are never collected - read the two together.",
      "DIVIDE ( [AR Balance], [AR Invoiced (Last 90 Days)] ) * 90"),
    m("AR Collections", F_WC, AUD0, "Cash collected in the period, by receipt date, capped at the as-of date.",
      """VAR AsOf = [As Of Date]
RETURN
    CALCULATE (
        SUM ( FactARInvoice[InvoiceAmountAUD] ),
        USERELATIONSHIP ( FactARInvoice[PaidDate], DimDate[Date] ),
        FILTER (
            ALL ( FactARInvoice[PaidDate] ),
            NOT ISBLANK ( FactARInvoice[PaidDate] ) && FactARInvoice[PaidDate] <= AsOf
        )
    )"""),
    m("Days to Collect", F_WC, N1,
      "Value-weighted days from invoice to receipt, over invoices collected in the period. The behavioural collection "
      "speed, as opposed to DSO, which also carries the uncollected stock.",
      """VAR AsOf = [As Of Date]
VAR Weighted =
    CALCULATE (
        SUMX ( FactARInvoice, FactARInvoice[DaysToPay] * FactARInvoice[InvoiceAmountAUD] ),
        USERELATIONSHIP ( FactARInvoice[PaidDate], DimDate[Date] ),
        FILTER (
            ALL ( FactARInvoice[PaidDate] ),
            NOT ISBLANK ( FactARInvoice[PaidDate] ) && FactARInvoice[PaidDate] <= AsOf
        )
    )
RETURN
    DIVIDE ( Weighted, [AR Collections] )"""),
    m("Days Paid Late (AR)", F_WC, N1,
      "Value-weighted days between due date and receipt, over invoices collected in the period.",
      """VAR AsOf = [As Of Date]
VAR Weighted =
    CALCULATE (
        SUMX ( FactARInvoice, FactARInvoice[DaysLate] * FactARInvoice[InvoiceAmountAUD] ),
        USERELATIONSHIP ( FactARInvoice[PaidDate], DimDate[Date] ),
        FILTER (
            ALL ( FactARInvoice[PaidDate] ),
            NOT ISBLANK ( FactARInvoice[PaidDate] ) && FactARInvoice[PaidDate] <= AsOf
        )
    )
RETURN
    DIVIDE ( Weighted, [AR Collections] )"""),
    m("Invoiced Value Collected %", F_WC, PCT,
      "Of the value invoiced in the period, the share collected by the balance date.",
      """VAR EndDate = [Balance Date]
VAR Collected =
    CALCULATE (
        SUM ( FactARInvoice[InvoiceAmountAUD] ),
        FILTER (
            ALL ( FactARInvoice[PaidDate] ),
            NOT ISBLANK ( FactARInvoice[PaidDate] ) && FactARInvoice[PaidDate] <= EndDate
        )
    )
RETURN
    DIVIDE ( Collected, [AR Invoiced] )"""),
    m("AP Balance", F_WC, AUD0, "Payables outstanding on the balance date: bills received by it and not paid by it.",
      OPEN_AS_OF("FactAPBill", "SUM ( FactAPBill[BillAmountAUD] )", "BillDate")),
    m("AP Open Bills", F_WC, N0, "Number of bills outstanding on the balance date.",
      OPEN_AS_OF("FactAPBill", "COUNTROWS ( FactAPBill )", "BillDate")),
    m("AP Past Due", F_WC, AUD0, "Outstanding payables whose due date has passed on the balance date.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE ( [AP Balance], FILTER ( ALL ( FactAPBill[DueDate] ), FactAPBill[DueDate] < EndDate ) )"""),
    m("AP Over 365 Days", F_WC, AUD0, "Payables more than a year past due.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE ( [AP Balance], FILTER ( ALL ( FactAPBill[DueDate] ), FactAPBill[DueDate] < EndDate - 365 ) )"""),
    m("AP Ageing Amount", F_WC, AUD0, "Payables balance in the ageing bucket in context, aged as of the balance date.",
      """VAR EndDate = [Balance Date]
RETURN
    SUMX (
        VALUES ( DimAgeingBucket[BucketOrder] ),
        VAR LowerDays = CALCULATE ( MIN ( DimAgeingBucket[MinDaysPastDue] ) )
        VAR UpperDays = CALCULATE ( MAX ( DimAgeingBucket[MaxDaysPastDue] ) )
        RETURN
            CALCULATE (
                [AP Balance],
                FILTER (
                    ALL ( FactAPBill[DueDate] ),
                    FactAPBill[DueDate] >= EndDate - UpperDays && FactAPBill[DueDate] <= EndDate - LowerDays
                )
            )
    )"""),
    m("AP Billed", F_WC, AUD0, "Value billed by suppliers in the period (by bill date).",
      "SUM ( FactAPBill[BillAmountAUD] )"),
    m("AP Billed (Last 90 Days)", F_WC, AUD0,
      "Value billed in the 90 days ending on the balance date: the DPO denominator.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE (
        SUM ( FactAPBill[BillAmountAUD] ),
        REMOVEFILTERS ( DimDate ),
        FactAPBill[BillDate] > EndDate - 90,
        FactAPBill[BillDate] <= EndDate
    )"""),
    m("DPO (Days)", F_WC, N0, "Days payable outstanding: balance divided by the last 90 days of billing, times 90.",
      "DIVIDE ( [AP Balance], [AP Billed (Last 90 Days)] ) * 90"),
    m("AP Payments", F_WC, AUD0, "Cash paid to suppliers in the period, by payment date, capped at the as-of date.",
      """VAR AsOf = [As Of Date]
RETURN
    CALCULATE (
        SUM ( FactAPBill[BillAmountAUD] ),
        USERELATIONSHIP ( FactAPBill[PaidDate], DimDate[Date] ),
        FILTER (
            ALL ( FactAPBill[PaidDate] ),
            NOT ISBLANK ( FactAPBill[PaidDate] ) && FactAPBill[PaidDate] <= AsOf
        )
    )"""),
    m("Days to Pay", F_WC, N1, "Value-weighted days from bill to payment, over bills paid in the period.",
      """VAR AsOf = [As Of Date]
VAR Weighted =
    CALCULATE (
        SUMX ( FactAPBill, FactAPBill[DaysToPay] * FactAPBill[BillAmountAUD] ),
        USERELATIONSHIP ( FactAPBill[PaidDate], DimDate[Date] ),
        FILTER (
            ALL ( FactAPBill[PaidDate] ),
            NOT ISBLANK ( FactAPBill[PaidDate] ) && FactAPBill[PaidDate] <= AsOf
        )
    )
RETURN
    DIVIDE ( Weighted, [AP Payments] )"""),
    m("Trade Working Capital", F_WC, AUD0,
      "Receivables less payables on the balance date. Inventory has no source in this dataset, so it is not included and "
      "days inventory outstanding is not reported.",
      "[AR Balance] - [AP Balance]"),
    m("DSO minus DPO (Days)", F_WC, N0,
      "Days sales outstanding less days payable outstanding: how long the group funds the gap between collecting and paying.",
      "[DSO (Days)] - [DPO (Days)]"),

    # ------------------------------------------------------------------ cash ---
    m("Cash Balance", F_CASH, AUD0,
      "Closing cash on the balance date, summed across entities in context. A balance is never summed over time.",
      """VAR EndDate = [Balance Date]
RETURN
    CALCULATE (
        SUM ( FactCashBalance[ClosingCashAUD] ),
        REMOVEFILTERS ( DimDate ),
        FactCashBalance[Date] = EndDate
    )"""),
    m("Average Daily Cash", F_CASH, AUD0, "Mean of the daily closing balances in the period, up to the as-of date.",
      """VAR AsOf = [As Of Date]
RETURN
    AVERAGEX (
        FILTER ( VALUES ( DimDate[Date] ), DimDate[Date] <= AsOf ),
        CALCULATE ( SUM ( FactCashBalance[ClosingCashAUD] ) )
    )"""),
    m("Minimum Daily Cash", F_CASH, AUD0, "Lowest daily closing balance in the period - the liquidity low point.",
      """VAR AsOf = [As Of Date]
RETURN
    MINX (
        FILTER ( VALUES ( DimDate[Date] ), DimDate[Date] <= AsOf ),
        CALCULATE ( SUM ( FactCashBalance[ClosingCashAUD] ) )
    )"""),
    m("Cash Change in Period", F_CASH, AUDVAR, "Closing cash less the balance on the day before the period started.",
      """VAR StartDate = MIN ( DimDate[Date] )
VAR Opening =
    CALCULATE (
        SUM ( FactCashBalance[ClosingCashAUD] ),
        REMOVEFILTERS ( DimDate ),
        FactCashBalance[Date] = StartDate - 1
    )
RETURN
    IF ( NOT ISBLANK ( Opening ), [Cash Balance] - Opening )"""),
    m("Cash Floor Days", F_CASH, N0,
      "Days where an entity's balance is exactly 50,000.00 - a generator floor in the source, not a treasury decision "
      "(audit finding 15).",
      "CALCULATE ( COUNTROWS ( FactCashBalance ), FactCashBalance[IsFloorValue] = TRUE () )"),

    # ------------------------------------------------------ scenario planning ---
    m("Scenario Revenue Change %", F_SCEN, PCTVAR,
      "Revenue driver of the selected scenario. Illustrative planning assumption, not supplied data.",
      "SELECTEDVALUE ( DimScenario[RevenueChangePct], 0 )"),
    m("Scenario Opex Change %", F_SCEN, PCTVAR, "Operating-expense driver of the selected scenario.",
      "SELECTEDVALUE ( DimScenario[OpexChangePct], 0 )"),
    m("Scenario AUD Change %", F_SCEN, PCTVAR,
      "Exchange-rate driver: a positive value strengthens the AUD, which lowers the translated result of every "
      "foreign-currency entity.",
      "SELECTEDVALUE ( DimScenario[AUDChangePct], 0 )"),
    m("Revenue Current FY to Date", F_SCEN, AUD0,
      "Actual revenue booked so far in the financial year containing the as-of date.",
      "CALCULATE ( [Revenue], REMOVEFILTERS ( DimDate ), DimDate[FinancialYearOffset] = 0 )"),
    m("COGS Current FY to Date", F_SCEN, AUD0, "Actual COGS booked so far in the current financial year.",
      "CALCULATE ( [COGS], REMOVEFILTERS ( DimDate ), DimDate[FinancialYearOffset] = 0 )"),
    m("Operating Expense Current FY to Date", F_SCEN, AUD0,
      "Actual operating expense booked so far in the current financial year.",
      "CALCULATE ( [Operating Expense], REMOVEFILTERS ( DimDate ), DimDate[FinancialYearOffset] = 0 )"),
    m("Run-Rate Revenue (Monthly)", F_SCEN, AUD0,
      "Average monthly revenue over the twelve complete months ending on the as-of date: the basis for projecting the "
      "rest of the year. A projection, not a supplied forecast.",
      """DIVIDE (
    CALCULATE (
        [Revenue],
        REMOVEFILTERS ( DimDate ),
        DimDate[MonthOffset] >= -11,
        DimDate[MonthOffset] <= 0
    ),
    12
)"""),
    m("Run-Rate COGS (Monthly)", F_SCEN, AUD0, "Average monthly COGS over the twelve months ending on the as-of date.",
      """DIVIDE (
    CALCULATE ( [COGS], REMOVEFILTERS ( DimDate ), DimDate[MonthOffset] >= -11, DimDate[MonthOffset] <= 0 ),
    12
)"""),
    m("Run-Rate Operating Expense (Monthly)", F_SCEN, AUD0,
      "Average monthly operating expense over the twelve months ending on the as-of date.",
      """DIVIDE (
    CALCULATE ( [Operating Expense], REMOVEFILTERS ( DimDate ), DimDate[MonthOffset] >= -11, DimDate[MonthOffset] <= 0 ),
    12
)"""),
    m("Outlook Revenue", F_SCEN, AUD0,
      "Full financial year: actual revenue to date plus the remaining months at the trailing-twelve-month run rate, "
      "flexed by the scenario's revenue driver and, for foreign-currency entities, by its exchange-rate driver.",
      """VAR RevenueDriver = [Scenario Revenue Change %]
VAR CurrencyDriver = [Scenario AUD Change %]
VAR RemainingMonths = [Months Remaining in FY]
RETURN
    SUMX (
        SUMMARIZE ( DimEntity, DimEntity[EntityID], DimEntity[CurrencyRole] ),
        VAR TranslationFactor =
            IF ( DimEntity[CurrencyRole] = "Foreign currency", DIVIDE ( 1, 1 + CurrencyDriver ), 1 )
        RETURN
            [Revenue Current FY to Date]
                + RemainingMonths * [Run-Rate Revenue (Monthly)] * ( 1 + RevenueDriver ) * TranslationFactor
    )"""),
    m("Outlook COGS", F_SCEN, AUD0,
      "Cost of goods sold on the same basis. COGS moves with revenue volume, so the revenue driver applies to it too - "
      "gross margin is held at the run-rate level.",
      """VAR RevenueDriver = [Scenario Revenue Change %]
VAR CurrencyDriver = [Scenario AUD Change %]
VAR RemainingMonths = [Months Remaining in FY]
RETURN
    SUMX (
        SUMMARIZE ( DimEntity, DimEntity[EntityID], DimEntity[CurrencyRole] ),
        VAR TranslationFactor =
            IF ( DimEntity[CurrencyRole] = "Foreign currency", DIVIDE ( 1, 1 + CurrencyDriver ), 1 )
        RETURN
            [COGS Current FY to Date]
                + RemainingMonths * [Run-Rate COGS (Monthly)] * ( 1 + RevenueDriver ) * TranslationFactor
    )"""),
    m("Outlook Operating Expense", F_SCEN, AUD0,
      "Operating expense on the same basis, flexed by the scenario's cost driver. Treated as a fixed base: it does not "
      "move with revenue.",
      """VAR CostDriver = [Scenario Opex Change %]
VAR CurrencyDriver = [Scenario AUD Change %]
VAR RemainingMonths = [Months Remaining in FY]
RETURN
    SUMX (
        SUMMARIZE ( DimEntity, DimEntity[EntityID], DimEntity[CurrencyRole] ),
        VAR TranslationFactor =
            IF ( DimEntity[CurrencyRole] = "Foreign currency", DIVIDE ( 1, 1 + CurrencyDriver ), 1 )
        RETURN
            [Operating Expense Current FY to Date]
                + RemainingMonths * [Run-Rate Operating Expense (Monthly)] * ( 1 + CostDriver ) * TranslationFactor
    )"""),
    m("Outlook Operating Profit", F_SCEN, AUD0,
      "Full-year operating profit under the selected scenario: outlook revenue less outlook COGS and operating expense.",
      "[Outlook Revenue] - [Outlook COGS] - [Outlook Operating Expense]"),
    m("Outlook Operating Margin %", F_SCEN, PCT, "Outlook operating profit as a share of outlook revenue.",
      "DIVIDE ( [Outlook Operating Profit], [Outlook Revenue] )"),
    m("Last Complete FY Operating Profit", F_SCEN, AUD0,
      "Operating profit of the last complete financial year - what the outlook is compared with.",
      "CALCULATE ( [Operating Profit], REMOVEFILTERS ( DimDate ), DimDate[FinancialYearOffset] = -1 )"),
    m("Outlook vs Last FY Operating Profit", F_SCEN, AUDVAR,
      "Outlook operating profit less the last complete year's. Positive is an improvement.",
      "[Outlook Operating Profit] - [Last Complete FY Operating Profit]"),
    m("Sensitivity Operating Profit", F_SCEN, AUD0,
      "Outlook operating profit when revenue moves by the step in context, on top of the selected scenario: the profit "
      "sensitivity curve.",
      """VAR RevenueStep = SELECTEDVALUE ( DimSensitivityStep[StepPct], 0 )
VAR RevenueDriver = [Scenario Revenue Change %] + RevenueStep
VAR CostDriver = [Scenario Opex Change %]
VAR CurrencyDriver = [Scenario AUD Change %]
VAR RemainingMonths = [Months Remaining in FY]
RETURN
    SUMX (
        SUMMARIZE ( DimEntity, DimEntity[EntityID], DimEntity[CurrencyRole] ),
        VAR TranslationFactor =
            IF ( DimEntity[CurrencyRole] = "Foreign currency", DIVIDE ( 1, 1 + CurrencyDriver ), 1 )
        VAR OutlookRevenue =
            [Revenue Current FY to Date]
                + RemainingMonths * [Run-Rate Revenue (Monthly)] * ( 1 + RevenueDriver ) * TranslationFactor
        VAR OutlookCogs =
            [COGS Current FY to Date]
                + RemainingMonths * [Run-Rate COGS (Monthly)] * ( 1 + RevenueDriver ) * TranslationFactor
        VAR OutlookOpex =
            [Operating Expense Current FY to Date]
                + RemainingMonths * [Run-Rate Operating Expense (Monthly)] * ( 1 + CostDriver ) * TranslationFactor
        RETURN
            OutlookRevenue - OutlookCogs - OutlookOpex
    )"""),

    # ------------------------------------------------------- data quality ---
    m("DQ Metric Value", F_DQ, N2, "Value of the data-quality metric in context, computed live in SQL from dbo.",
      "SUM ( DataQualityMetric[MetricValue] )"),
    m("DQ Metric Unit", F_DQ, None,
      "How to read the metric in context: days, lines, share or AUD. A measure rather than a row level, so the "
      "matrix keeps one row per metric.",
      "SELECTEDVALUE ( DataQualityMetric[Unit] )"),
    m("Receipts After As-Of", F_DQ, N0,
      "Invoices whose receipt is dated after the as-of date. They are shown as OPEN on it, which is what they were.",
      "CALCULATE ( COUNTROWS ( FactARInvoice ), FactARInvoice[IsPaidAfterAsOf] = TRUE () )"),
    m("Payments After As-Of", F_DQ, N0, "Bills whose payment is dated after the as-of date.",
      "CALCULATE ( COUNTROWS ( FactAPBill ), FactAPBill[IsPaidAfterAsOf] = TRUE () )"),
    m("Budget Lines Without Posting", F_DQ, N0,
      "Budget lines (month x entity x department x account) with no ledger posting at all: the clearest measure of the "
      "extract's partial coverage.",
      """VAR PlanKeys =
    CALCULATETABLE (
        SUMMARIZE (
            FactFinancials,
            FactFinancials[MonthStart], FactFinancials[EntityID],
            FactFinancials[DepartmentID], FactFinancials[AccountCode]
        ),
        FactFinancials[VersionID] = "BUD"
    )
VAR PostedKeys =
    CALCULATETABLE (
        SUMMARIZE (
            FactFinancials,
            FactFinancials[MonthStart], FactFinancials[EntityID],
            FactFinancials[DepartmentID], FactFinancials[AccountCode]
        ),
        FactFinancials[VersionID] = "ACT"
    )
RETURN
    COUNTROWS ( EXCEPT ( PlanKeys, PostedKeys ) )"""),

    # --------------------------------------------------- report formatting ---
    m("Opex Variance Colour", F_FMT, None,
      "Cell colour for the operating-expense variance heatmap: the panel colour inside two standard deviations of the "
      "line's usual variance, green above, red below. A dead zone, not a gradient, so noise is never shaded.",
      SIGNAL_COLOUR("[Opex vs Budget Z-Score]")),
    m("Revenue Variance Colour", F_FMT, None,
      "The same dead-zone shading for the revenue variance.",
      SIGNAL_COLOUR("[Revenue vs Budget Z-Score]")),
    m("Variance Bar Colour", F_FMT, None,
      "Bar colour for an operating-profit variance: green when favourable, red when not.",
      f"""VAR FavourableAmount = [Operating Profit vs Budget]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( FavourableAmount ), BLANK (),
        FavourableAmount >= 0, "{C_FAV_STRONG}",
        "{C_UNFAV_STRONG}"
    )"""),
    m("Outlook Variance Colour", F_FMT, None,
      "Bar colour for the outlook against last year: the report's green where the outlook improves on FY26, red where "
      "it does not. Favourable is positive here as everywhere, drawn rather than written.",
      f"""VAR FavourableAmount = [Outlook vs Last FY Operating Profit]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( FavourableAmount ), BLANK (),
        FavourableAmount >= 0, "{C_BAR_FAV}",
        "{C_BAR_UNFAV}"
    )"""),
]

# ---------------------------------------------------------- calculation groups ---
# Measures the Plan Version group may act on, and how a variance should be signed.
INCOME_MEASURES = ["Revenue", "Gross Profit", "Operating Profit", "Net Profit"]
COST_MEASURES = ["COGS", "Operating Expense", "Other Expense (Net)", "Tax Expense"]
RATIO_MEASURES = ["Gross Margin %", "Operating Margin %", "Net Margin %", "COGS % of Revenue", "Opex % of Revenue"]
CONTEXT_MEASURES = ["P&L Line Value", "Account Amount"]
VERSION_AWARE = INCOME_MEASURES + COST_MEASURES + RATIO_MEASURES + CONTEXT_MEASURES


def _sel(names):
    return "ISSELECTEDMEASURE ( " + ", ".join(f"[{n}]" for n in names) + " )"


GUARD = _sel(VERSION_AWARE)
IS_RATIO = (f"{_sel(RATIO_MEASURES)}\n        || ( ISSELECTEDMEASURE ( [P&L Line Value] ) "
            f'&& SELECTEDVALUE ( DimPLLine[LineType] ) = "Ratio" )')
FAV_SIGN = f"""SWITCH (
        TRUE (),
        {_sel(COST_MEASURES)}, -1,
        {_sel(INCOME_MEASURES + RATIO_MEASURES)}, 1,
        ISSELECTEDMEASURE ( [P&L Line Value] ), SELECTEDVALUE ( DimPLLine[FavourableSign] ),
        ISSELECTEDMEASURE ( [Account Amount] ),
            IF ( HASONEVALUE ( DimAccount[IsIncome] ), IF ( SELECTEDVALUE ( DimAccount[IsIncome] ), 1, -1 ) ),
        1
    )"""


def _version_item(version):
    return f"""IF (
    {GUARD},
    CALCULATE ( SELECTEDMEASURE (), FactFinancials[VersionID] = "{version}" )
)"""


def _variance_item(version, as_percent):
    body = ("IF ( IsRatioLine, BLANK (), DIVIDE ( ( ActualValue - PlanValue ) * FavourableSign, ABS ( PlanValue ) ) )"
            if as_percent else
            "IF ( IsRatioLine, ( ActualValue - PlanValue ) * 100, ( ActualValue - PlanValue ) * FavourableSign )")
    return f"""VAR ActualValue = CALCULATE ( SELECTEDMEASURE (), FactFinancials[VersionID] = "ACT" )
VAR PlanValue = CALCULATE ( SELECTEDMEASURE (), FactFinancials[VersionID] = "{version}" )
VAR IsRatioLine =
    {IS_RATIO}
VAR FavourableSign =
    {FAV_SIGN}
RETURN
    IF (
        {GUARD} && NOT ISBLANK ( ActualValue ) && NOT ISBLANK ( PlanValue ),
        {body}
    )"""


def _period_item(expression):
    return f"""{ASOF_INLINE}
RETURN
    IF (
        {GUARD},
        {expression}
    )"""


FMT_MONEY_OR_RATIO = f'IF (\n            {IS_RATIO},\n            "0.0%",\n            SELECTEDMEASUREFORMATSTRING ()\n        )'
FMT_VAR = f'IF (\n            {IS_RATIO},\n            "+0.0 pp;-0.0 pp;0.0 pp",\n            "{AUDVAR}"\n        )'

CALC_GROUPS = [
    {
        "name": "Plan Version",
        "column": "Version",
        "precedence": 20,
        "desc": "Actual, Budget and Forecast, and the variance between them, as one selection applied to every "
                "income-statement measure. Variance is favourable-positive: for a cost, an underspend is positive. "
                "Where the plan has no line - interest, FX, tax - the variance is blank, never 100%.",
        "items": [
            ("Actual", "General ledger, translated to AUD at monthly average rates.",
             _version_item("ACT"), FMT_MONEY_OR_RATIO),
            ("Budget", "The annual budget. Covers revenue, COGS and operating expense only.",
             _version_item("BUD"), FMT_MONEY_OR_RATIO),
            ("Forecast", "The forecast, as one version of all its lines.",
             _version_item("FC"), FMT_MONEY_OR_RATIO),
            ("Var vs Budget",
             "Actual less budget, signed so that positive is favourable. Margin lines are shown in percentage points.",
             _variance_item("BUD", False), FMT_VAR),
            ("Var % vs Budget",
             "Favourable variance as a share of the budget. Blank on margin lines, where a percentage of a percentage "
             "would mislead.",
             _variance_item("BUD", True), '"+0.0%;-0.0%;0.0%"'),
            ("Var vs Forecast", "Actual less forecast, signed so that positive is favourable.",
             _variance_item("FC", False), FMT_VAR),
            ("Var % vs Forecast", "Favourable variance as a share of the forecast.",
             _variance_item("FC", True), '"+0.0%;-0.0%;0.0%"'),
        ],
    },
    {
        "name": "Period View",
        "column": "Period",
        "precedence": 10,
        "desc": "How much of time a figure covers: the period in view, the financial year to date, the trailing twelve "
                "months, or the same window a year earlier. Every window ends at the balance date - the last day in "
                "context capped at the as-of date - so a part year is never compared with a full one.",
        "items": [
            ("Selected period", "The period the page's filters select.", _period_item("SELECTEDMEASURE ()"), None),
            ("Year to date", "From 1 July to the end of the period in view, never past the as-of date.",
             _period_item("""CALCULATE (
            SELECTEDMEASURE (),
            DATESYTD ( DimDate[Date], "6/30" ),
            DimDate[IsAfterAsOf] = FALSE ()
        )"""), None),
            ("Prior year", "The same window one year earlier. The window is capped at the as-of date BEFORE it is "
                           "shifted, so a part year is compared with the same part year; blank where the ledger does "
                           "not cover that earlier window.",
             _period_item("""IF (
            EDATE ( MIN ( DimDate[Date] ), -12 )
                >= CALCULATE ( MIN ( FactFinancials[MonthStart] ), REMOVEFILTERS (), FactFinancials[VersionID] = "ACT" ),
            CALCULATE (
                SELECTEDMEASURE (),
                SAMEPERIODLASTYEAR ( CALCULATETABLE ( VALUES ( DimDate[Date] ), DimDate[IsAfterAsOf] = FALSE () ) )
            )
        )"""), None),
            ("Prior year to date", "1 July to the same point of last year - the like-for-like comparison.",
             _period_item("""IF (
            EDATE ( MIN ( DimDate[Date] ), -12 )
                >= CALCULATE ( MIN ( FactFinancials[MonthStart] ), REMOVEFILTERS (), FactFinancials[VersionID] = "ACT" ),
            CALCULATE (
                SELECTEDMEASURE (),
                SAMEPERIODLASTYEAR ( CALCULATETABLE ( DATESYTD ( DimDate[Date], "6/30" ), DimDate[IsAfterAsOf] = FALSE () ) )
            )
        )"""), None),
        ],
    },
]
