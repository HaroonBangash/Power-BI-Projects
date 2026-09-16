# -*- coding: utf-8 -*-
"""
Every measure in the model, the calculation group, and the field-parameter table.

Read by Python/02_generate_semantic_model.py. Kept apart from the table spec
because this is the business logic and that is the plumbing.

The rules this file obeys, each one earned in Phase 1:

  MRR is a STOCK.  It is read at the last month in context, capped at the as-of
  date, and never summed across months. A measure that adds January's MRR to
  February's is counting the same subscription twice, and that is the single
  easiest way to be confidently wrong about a SaaS business.

  A window that starts after the as-of date returns BLANK, not the as-of figure.
  Otherwise every future month inherits today's number and a chart runs flat
  into 2027 looking like a forecast.

  Retention is quoted with its BASIS.  Revenue retention and logo retention
  answer different questions and this model never lets one stand in for the
  other. Because this data has no expansion or contraction (Phase 1), NRR and
  GRR are equal by construction - so both are published, side by side, rather
  than quoting the flattering one.

  Rates, not counts, for behaviour.  Support contact and payment failure are
  always per month of tenure or per invoice. A raw count measures how long
  somebody has been a customer.

  Assumptions live in ModelConfig and are shown, never buried.  Gross margin is
  the only one, and every measure that depends on it says so in its description.
"""

# --------------------------------------------------------------- formatting ---
F_MONEY = "\\$#,0.00"
F_MONEY0 = "\\$#,0"
F_INT = "#,0"
F_PCT = "0.0%"
F_PCT2 = "0.00%"
F_NUM1 = "#,0.0"
F_NUM2 = "#,0.00"
F_R = "+0.000;-0.000;0.000"
F_FMT = None                      # a text measure: a format string would mean nothing

# Colour constants for the report's conditional formatting. The panel colour must
# match the report's untinted panel so a cell inside the dead zone disappears.
# The report is ink on paper, so a cell that carries no signal must read as the CARD,
# not as a dark block - and every step of the retention ramp stays light enough for dark
# text to sit on it. Nothing here is a traffic light: the palette is one crimson family.
C_PANEL = "#FFFFFF"                      # the card: "nothing to see here"
C_RAMP_4, C_RAMP_3 = "#E8899B", "#F0AFBB"    # strongest and strong retention
C_RAMP_2, C_RAMP_1 = "#F6CED5", "#FBE7EA"    # middling and weak
C_MUTED = "#DCD5D7"                      # a measured driver that is not a driver
C_SIGNAL = "#9E1B32"                     # a measured driver that is
C_BAR_WON, C_BAR_LOST = "#E0788C", "#9E1B32"


def m(name, fmt, folder, desc, dax, hidden=False):
    return {"name": name, "fmt": fmt, "folder": folder, "desc": desc, "dax": dax.strip("\n"), "hidden": hidden}


# The snapshot month: the last month in the current filter, capped at the as-of
# month, and blank when the whole selection is in the future. Used by every
# point-in-time measure so they all agree about "now".
SNAP = """VAR AsOfMonth = [As-Of Month]
VAR LastInContext = MAX ( DimDate[MonthStart] )
VAR FirstInContext = MIN ( DimDate[MonthStart] )
RETURN
    IF ( FirstInContext <= AsOfMonth, MIN ( LastInContext, AsOfMonth ) )"""


def at_snapshot(expr):
    """Evaluate `expr` in the snapshot month only - the semi-additive pattern."""
    return f"""VAR SnapshotMonth = [Snapshot Month]
RETURN
    IF (
        NOT ISBLANK ( SnapshotMonth ),
        CALCULATE (
            {expr},
            FactSubscriptionMonth[MonthStart] = SnapshotMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""


def movement(kind):
    """One component of the MRR waterfall. Positive for what was won, negative for
    what was lost - the sign is carried in the data, not applied here."""
    return f"""CALCULATE (
    SUM ( FactMRRMovement[MRRDelta] ),
    FactMRRMovement[MovementType] = "{kind}"
)"""


MEASURES = [
    # ------------------------------------------------------- 00 model context ---
    m("As-Of Date", "yyyy-mm-dd", "00 Model Context",
      "The last day the data describes, read from ModelConfig. Every point-in-time figure is stated on it, and nothing "
      "in this model hard-codes it.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "AsOfDate", REMOVEFILTERS () )
RETURN
    DATEVALUE ( Raw )"""),

    m("As-Of Month", "yyyy-mm-dd", "00 Model Context",
      "The first day of the as-of month. The snapshot never runs past it.",
      """VAR D = [As-Of Date]
RETURN
    DATE ( YEAR ( D ), MONTH ( D ), 1 )""", hidden=True),

    m("Snapshot Month", "yyyy-mm-dd", "00 Model Context",
      "The month every stock measure is read at: the last month in the current filter, capped at the as-of month, and "
      "BLANK when the whole selection is in the future - so a chart stops at the data instead of running flat into it.",
      SNAP, hidden=True),

    m("Gross Margin Assumption", F_PCT, "00 Model Context",
      "An ASSUMPTION, not data: the source carries no cost of service. Held in ModelConfig so it is visible and can be "
      "changed in one place. Lifetime value and CAC payback both depend on it and both say so.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "GrossMarginAssumption", REMOVEFILTERS () )
RETURN
    VALUE ( Raw )"""),

    m("Last New Business Date", "yyyy-mm-dd", "00 Model Context",
      "The newest subscription start in the source. Churn runs two months past it, so anything after this date shows "
      "losses and no wins.",
      """CALCULATE ( MAX ( FactSubscription[StartDate] ), REMOVEFILTERS () )"""),

    m("Report Context", F_FMT, "00 Model Context",
      "The one-line header every page carries, so a screenshot can never be read out of context.",
      """VAR AsOf = FORMAT ( [As-Of Date], "d MMM yyyy" )
VAR Margin = FORMAT ( [Gross Margin Assumption], "0%" )
RETURN
    "As of " & AsOf & "  |  USD  |  Gross margin assumed " & Margin & "  |  Synthetic data\""""),

    m("Months In Context", F_INT, "00 Model Context",
      "How many months the current filter covers. Guards the measures that only mean something over one month.",
      """CALCULATE ( DISTINCTCOUNT ( DimDate[MonthStart] ), FactSubscriptionMonth )""", hidden=True),

    # ------------------------------------------------------------ 01 revenue ---
    m("MRR", F_MONEY0, "01 Revenue",
      "Monthly recurring revenue on the books at the snapshot month. A stock: read at a moment, never summed over "
      "months. Selecting a range gives the figure at the END of the range, which is what 'MRR' means.",
      at_snapshot("SUM ( FactSubscriptionMonth[MRR] )")),

    m("ARR", F_MONEY0, "01 Revenue",
      "Annual recurring revenue: MRR at the snapshot month times twelve. No annualisation of a partial period is "
      "involved - it is a restatement of the same stock.",
      """[MRR] * 12"""),

    m("Opening MRR", F_MONEY0, "01 Revenue",
      "MRR at the end of the month BEFORE the period in context - what the period started with. The denominator of "
      "every retention figure.",
      """VAR FirstMonth = MIN ( DimDate[MonthStart] )
VAR PriorMonth = EDATE ( FirstMonth, -1 )
RETURN
    IF (
        PriorMonth >= CALCULATE ( MIN ( FactSubscriptionMonth[MonthStart] ), REMOVEFILTERS () ),
        CALCULATE (
            SUM ( FactSubscriptionMonth[MRR] ),
            FactSubscriptionMonth[MonthStart] = PriorMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""),

    m("ARPA", F_MONEY, "01 Revenue",
      "Average revenue per account: MRR divided by the customers it comes from, both read at the snapshot month.",
      """DIVIDE ( [MRR], [Customers] )"""),

    m("ARPA (New Customers)", F_MONEY, "01 Revenue",
      "The average MRR a new customer arrives on, in the period in context. Compared with ARPA it says whether new "
      "business is landing above or below the installed base.",
      """DIVIDE ( [New MRR], [New Customers] )"""),

    m("Realised Price vs List %", F_PCT, "01 Revenue",
      "MRR as a share of the plan's list price, at the snapshot month. Every subscription in this source is discounted "
      "or uplifted off its plan, so realised price is worth watching separately from the price book.",
      """VAR SnapshotMonth = [Snapshot Month]
RETURN
    IF (
        NOT ISBLANK ( SnapshotMonth ),
        CALCULATE (
            DIVIDE (
                SUM ( FactSubscriptionMonth[MRR] ),
                SUMX ( FactSubscriptionMonth, RELATED ( DimPlan[MonthlyListPrice] ) )
            ),
            FactSubscriptionMonth[MonthStart] = SnapshotMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""),

    m("Invoiced Amount", F_MONEY0, "01 Revenue",
      "Billed value in the period. This is a FLOW and does sum over time - unlike MRR. Annual subscriptions bill twelve "
      "months at once, so invoiced value is lumpy where MRR is smooth; the two are never mixed.",
      """SUM ( FactInvoice[InvoiceAmount] )"""),

    m("Collected Amount", F_MONEY0, "01 Revenue",
      "Billed value that was actually paid.",
      """CALCULATE ( SUM ( FactInvoice[InvoiceAmount] ), FactInvoice[IsFailed] = FALSE () )"""),

    # ----------------------------------------------------------- 02 movement ---
    m("New MRR", F_MONEY0, "02 MRR Movement",
      "MRR added by customers arriving in the period.",
      movement("New")),

    m("Churned MRR", F_MONEY0, "02 MRR Movement",
      "MRR lost to customers leaving in the period. Negative, because that is the direction it moves the book.",
      movement("Churn")),

    m("Expansion MRR", F_MONEY0, "02 MRR Movement",
      "MRR added by existing customers growing. STRUCTURALLY NIL in this source: MRR is one static value per "
      "subscription and every subscription bills a single invoice amount for life. The measure is real and the logic "
      "is tested; the data has nothing to put in it.",
      movement("Expansion")),

    m("Contraction MRR", F_MONEY0, "02 MRR Movement",
      "MRR lost by existing customers shrinking. Structurally nil here, for the same reason as expansion.",
      movement("Contraction")),

    m("Reactivation MRR", F_MONEY0, "02 MRR Movement",
      "MRR from customers returning after leaving. Structurally nil here: every customer has exactly one subscription, "
      "ever, so no customer can come back.",
      movement("Reactivation")),

    m("Net MRR Movement", F_MONEY0, "02 MRR Movement",
      "Everything that moved the book in the period. Closing MRR minus opening MRR, by another route - and "
      "`09_validation.sql` checks the two agree every month.",
      """SUM ( FactMRRMovement[MRRDelta] )"""),

    m("MRR Movement", F_MONEY0, "02 MRR Movement",
      "The movement amount under whatever movement types are in context. This is what the waterfall plots, so the "
      "chart is driven by the dimension rather than by five separate measures.",
      """SUM ( FactMRRMovement[MRRDelta] )"""),

    m("MRR Movement (All Components)", F_MONEY0, "02 MRR Movement",
      "The movement amount, forced to ZERO rather than blank where a movement type has no rows. The waterfall uses "
      "this so all five components appear on the axis: a blank one would simply vanish, and the reader would never "
      "learn that expansion, contraction and reactivation cannot happen in this source.",
      """SUM ( FactMRRMovement[MRRDelta] ) + 0"""),

    m("Movement Supported", F_FMT, "02 MRR Movement",
      "Whether the movement type in context can occur in THIS data, and why not where it cannot. Shown beside the "
      "waterfall so an empty bar reads as a property of the source rather than a missing number.",
      """VAR Unsupported =
    CALCULATETABLE (
        VALUES ( DimMovementType[WhyNot] ),
        DimMovementType[IsSupported] = FALSE ()
    )
RETURN
    IF ( COUNTROWS ( Unsupported ) = 1, CONCATENATEX ( Unsupported, DimMovementType[WhyNot] ) )"""),

    # ---------------------------------------------------------- 03 customers ---
    m("Customers", F_INT, "03 Customers",
      "Paying customers at the snapshot month. Like MRR this is a stock, read at a moment.",
      at_snapshot("DISTINCTCOUNT ( FactSubscriptionMonth[CustomerID] )")),

    m("New Customers", F_INT, "03 Customers",
      "Customers that arrived in the period.",
      """CALCULATE (
    COUNTROWS ( FactMRRMovement ),
    FactMRRMovement[MovementType] IN { "New", "Reactivation" }
)"""),

    m("Churned Customers", F_INT, "03 Customers",
      "Customers that left in the period.",
      """CALCULATE ( COUNTROWS ( FactMRRMovement ), FactMRRMovement[MovementType] = "Churn" )"""),

    m("Net Customer Change", F_INT, "03 Customers",
      "Arrivals less departures in the period.",
      """[New Customers] - [Churned Customers]"""),

    m("Customers Ever Acquired", F_INT, "03 Customers",
      "Every customer that has ever started, whether or not they are still here.",
      """DISTINCTCOUNT ( FactSubscription[CustomerID] )"""),

    m("Customers Ever Churned", F_INT, "03 Customers",
      "Customers whose subscription has ended.",
      """CALCULATE ( DISTINCTCOUNT ( FactSubscription[CustomerID] ), FactSubscription[IsChurned] = TRUE () )"""),

    m("Ever-Churn Rate", F_PCT, "03 Customers",
      "The share of all customers ever acquired that have left. A lifetime figure, not a rate per period - it is not "
      "comparable with monthly churn and is never plotted beside it.",
      """DIVIDE ( [Customers Ever Churned], [Customers Ever Acquired] )"""),

    m("Median Tenure (Months)", F_NUM1, "03 Customers",
      "Median completed months from start to the end date, or to the as-of date for a customer still running.",
      """MEDIANX ( FactSubscription, FactSubscription[TenureMonths] )"""),

    # ----------------------------------------------- 04 retention and churn ---
    m("Logo Churn %", F_PCT2, "04 Retention & Churn",
      "Customers lost in the period as a share of the customers it opened with. The logo view: every customer counts "
      "the same whatever they pay. A month in which nobody left reads 0%, not blank - DIVIDE ( BLANK, n ) is BLANK, "
      "which would leave a GAP in the line where the best month should be. A month the data does not reach is BLANK, not 0% - otherwise a chart ends on a perfect month that is only an absence of data.",
      """VAR Opening = [Opening Customers]
VAR InData = NOT ISBLANK ( [Snapshot Month] )
RETURN
    IF ( InData && NOT ISBLANK ( Opening ), DIVIDE ( COALESCE ( [Churned Customers], 0 ), Opening ) )"""),

    m("Opening Customers", F_INT, "04 Retention & Churn",
      "Customers on the books at the end of the month BEFORE the period in context.",
      """VAR FirstMonth = MIN ( DimDate[MonthStart] )
VAR PriorMonth = EDATE ( FirstMonth, -1 )
RETURN
    IF (
        PriorMonth >= CALCULATE ( MIN ( FactSubscriptionMonth[MonthStart] ), REMOVEFILTERS () ),
        CALCULATE (
            DISTINCTCOUNT ( FactSubscriptionMonth[CustomerID] ),
            FactSubscriptionMonth[MonthStart] = PriorMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""),

    m("Revenue Churn %", F_PCT2, "04 Retention & Churn",
      "MRR lost in the period as a share of opening MRR. The revenue view: a departing Enterprise customer weighs "
      "twenty times a departing Starter, which is why this sits beside logo churn and never replaces it. A month the data does not reach is BLANK, not 0% - otherwise a chart ends on a perfect month that is only an absence of data.",
      """VAR Opening = [Opening MRR]
VAR InData = NOT ISBLANK ( [Snapshot Month] )
RETURN
    IF ( InData && NOT ISBLANK ( Opening ), DIVIDE ( -COALESCE ( [Churned MRR], 0 ), Opening ) )"""),

    m("Logo Retention %", F_PCT, "04 Retention & Churn",
      "The complement of logo churn: the share of opening customers still here at the end of the period.",
      """IF ( NOT ISBLANK ( [Opening Customers] ), 1 - [Logo Churn %] )"""),

    m("Gross Revenue Retention %", F_PCT, "04 Retention & Churn",
      "Opening MRR less churn and contraction, over opening MRR. Expansion is deliberately excluded: GRR asks what the "
      "book keeps without selling anything more, so it can never exceed 100%.",
      """VAR Opening = [Opening MRR]
VAR Lost = COALESCE ( [Churned MRR], 0 ) + COALESCE ( [Contraction MRR], 0 )
VAR InData = NOT ISBLANK ( [Snapshot Month] )
RETURN
    IF ( InData && NOT ISBLANK ( Opening ), DIVIDE ( Opening + Lost, Opening ) )"""),

    m("Net Revenue Retention %", F_PCT, "04 Retention & Churn",
      "Gross revenue retention plus expansion and reactivation. In THIS source there is neither, so NRR and GRR are "
      "identical by construction - both are published so the reader can see that, rather than being shown the "
      "flattering one alone. Any NRR above 100% on this data would be an arithmetic error.",
      """VAR Opening = [Opening MRR]
VAR Lost = COALESCE ( [Churned MRR], 0 ) + COALESCE ( [Contraction MRR], 0 )
VAR Won = COALESCE ( [Expansion MRR], 0 ) + COALESCE ( [Reactivation MRR], 0 )
VAR InData = NOT ISBLANK ( [Snapshot Month] )
RETURN
    IF ( InData && NOT ISBLANK ( Opening ), DIVIDE ( Opening + Lost + Won, Opening ) )"""),

    m("NRR less GRR (pp)", F_NUM2, "04 Retention & Churn",
      "The gap between net and gross revenue retention, in percentage points - the contribution of expansion. It is "
      "zero here, and that zero is a finding about the data rather than a blank cell.",
      """VAR N = [Net Revenue Retention %]
VAR G = [Gross Revenue Retention %]
RETURN
    IF ( NOT ISBLANK ( N ) && NOT ISBLANK ( G ), ( N - G ) * 100 )"""),

    m("Annualised Logo Churn %", F_PCT, "04 Retention & Churn",
      "The trailing-twelve-month logo churn rate, so a monthly figure can be read against an annual retention target. "
      "Blank until twelve complete months exist.",
      """VAR AsOfMonth = [As-Of Month]
VAR Window =
    CALCULATETABLE (
        VALUES ( DimDate[MonthStart] ),
        DimDate[MonthOffset] > -12,
        DimDate[MonthOffset] <= 0,
        REMOVEFILTERS ( DimDate )
    )
VAR Lost = CALCULATE ( [Churned Customers], Window, REMOVEFILTERS ( DimDate ) )
VAR OpeningN =
    CALCULATE (
        DISTINCTCOUNT ( FactSubscriptionMonth[CustomerID] ),
        FactSubscriptionMonth[MonthStart] = EDATE ( AsOfMonth, -12 ),
        REMOVEFILTERS ( DimDate )
    )
RETURN
    DIVIDE ( Lost, OpeningN )"""),

    m("Trailing 12m Revenue Retention %", F_PCT, "04 Retention & Churn",
      "Gross revenue retention measured over the twelve months ending at the as-of month. A fixed window, so it means "
      "the same thing whatever is selected on the page - which is why it is a card measure and not a chart one.",
      """VAR AsOfMonth = [As-Of Month]
VAR OpeningMRR =
    CALCULATE (
        SUM ( FactSubscriptionMonth[MRR] ),
        FactSubscriptionMonth[MonthStart] = EDATE ( AsOfMonth, -12 ),
        REMOVEFILTERS ( DimDate )
    )
VAR LostMRR =
    CALCULATE (
        SUM ( FactMRRMovement[MRRDelta] ),
        FactMRRMovement[MovementType] IN { "Churn", "Contraction" },
        DimDate[MonthOffset] > -12,
        DimDate[MonthOffset] <= 0,
        REMOVEFILTERS ( DimDate )
    )
RETURN
    DIVIDE ( OpeningMRR + LostMRR, OpeningMRR )"""),

    m("Logo Retention % (Latest Month)", F_PCT, "04 Retention & Churn",
      "Logo retention in the newest complete month, whatever period is selected elsewhere. A card measure: a "
      "retention rate needs a window, and over all time there is no month before the first one to open with.",
      """VAR LatestMonth = [As-Of Month]
RETURN
    CALCULATE ( [Logo Retention %], DimDate[MonthStart] = LatestMonth, REMOVEFILTERS ( DimDate ) )"""),

    m("Gross Revenue Retention % (Latest Month)", F_PCT, "04 Retention & Churn",
      "Gross revenue retention in the newest complete month, on the same fixed window as its logo counterpart.",
      """VAR LatestMonth = [As-Of Month]
RETURN
    CALCULATE ( [Gross Revenue Retention %], DimDate[MonthStart] = LatestMonth, REMOVEFILTERS ( DimDate ) )"""),

    m("Net Revenue Retention % (Latest Month)", F_PCT, "04 Retention & Churn",
      "Net revenue retention in the newest complete month. Equal to the gross figure beside it, because this source "
      "has no expansion - which is the point of showing both.",
      """VAR LatestMonth = [As-Of Month]
RETURN
    CALCULATE ( [Net Revenue Retention %], DimDate[MonthStart] = LatestMonth, REMOVEFILTERS ( DimDate ) )"""),

    m("NRR less GRR (Latest Month, pp)", F_NUM2, "04 Retention & Churn",
      "The gap between net and gross revenue retention in the newest complete month, in percentage points. It reads "
      "0.00, and that zero is a finding about the data rather than an empty card.",
      """VAR LatestMonth = [As-Of Month]
RETURN
    CALCULATE ( [NRR less GRR (pp)], DimDate[MonthStart] = LatestMonth, REMOVEFILTERS ( DimDate ) )"""),

    # ------------------------------------------------------------ 05 cohorts ---
    m("Cohort Size", F_INT, "05 Cohorts",
      "How many customers started in the cohort month. The denominator of cohort retention, and fixed - it never moves "
      "as customers leave.",
      """SUM ( DimCohort[CohortSize] )"""),

    m("Cohort Customers Retained", F_INT, "05 Cohorts",
      "Customers from the cohort still paying at the tenure month in context.",
      """DISTINCTCOUNT ( FactSubscriptionMonth[CustomerID] )"""),

    m("Cohort Retention %", F_PCT, "05 Cohorts",
      "Retained customers over cohort size. BLANK where the cohort has not lived that long yet, so the matrix reads as "
      "the triangle it really is instead of showing 0% for a future that has not happened.",
      """VAR AsOfMonth = [As-Of Month]
VAR Cohort = MIN ( DimCohort[CohortMonth] )
VAR Tenure = MIN ( DimTenureMonth[TenureMonth] )
VAR Reached = EDATE ( Cohort, Tenure ) <= AsOfMonth
RETURN
    IF ( Reached, DIVIDE ( [Cohort Customers Retained], [Cohort Size] ) )"""),

    m("Cohort MRR Retained", F_MONEY0, "05 Cohorts",
      "MRR still coming from the cohort at the tenure month in context.",
      """SUM ( FactSubscriptionMonth[MRR] )"""),

    m("Cohort MRR Retention %", F_PCT, "05 Cohorts",
      "Retained MRR over the MRR the cohort started with. Because MRR never changes per subscription in this source, "
      "this tracks logo retention exactly - which is itself the finding.",
      """VAR AsOfMonth = [As-Of Month]
VAR Cohort = MIN ( DimCohort[CohortMonth] )
VAR Tenure = MIN ( DimTenureMonth[TenureMonth] )
VAR Reached = EDATE ( Cohort, Tenure ) <= AsOfMonth
RETURN
    IF ( Reached, DIVIDE ( [Cohort MRR Retained], SUM ( DimCohort[CohortMRR] ) ) )"""),

    m("Months To Half Retained", F_NUM1, "05 Cohorts",
      "The first tenure month at which the cohort has lost half the customers it started with - a median lifetime read "
      "off the curve rather than assumed from a churn rate. Blank for cohorts that have not yet halved.",
      """VAR Cohort = MIN ( DimCohort[CohortMonth] )
VAR Size = [Cohort Size]
VAR Curve =
    ADDCOLUMNS (
        CALCULATETABLE ( VALUES ( DimTenureMonth[TenureMonth] ), ALL ( DimTenureMonth ) ),
        "@Retained",
            CALCULATE ( DISTINCTCOUNT ( FactSubscriptionMonth[CustomerID] ) )
    )
RETURN
    MINX ( FILTER ( Curve, [@Retained] > 0 && [@Retained] <= Size / 2 ), DimTenureMonth[TenureMonth] )"""),

    # ---------------------------------------------------- 06 unit economics ---
    m("Acquisition Spend", F_MONEY0, "06 Unit Economics",
      "What was spent acquiring the customers in context. Cost is attached to the customer, not to a campaign or a "
      "month, so this can be cut by anything about the customer and by their signup month - but not by channel spend "
      "over time, which the source does not carry.",
      """SUM ( FactAcquisition[AcquisitionCost] )"""),

    m("CAC (Blended)", F_MONEY, "06 Unit Economics",
      "Acquisition spend divided by the customers it bought. Blended, because the source gives no campaign detail.",
      """DIVIDE ( [Acquisition Spend], DISTINCTCOUNT ( FactAcquisition[CustomerID] ) )"""),

    m("CAC (Median)", F_MONEY, "06 Unit Economics",
      "The median customer's acquisition cost. Shown beside the blended figure because the distribution is skewed "
      "about 1.7 to 1 - the mean is not the typical customer.",
      """MEDIANX ( FactAcquisition, FactAcquisition[AcquisitionCost] )"""),

    m("Gross Profit per Account", F_MONEY, "06 Unit Economics",
      "ARPA times the gross-margin ASSUMPTION held in ModelConfig. There is no cost of service in this data, so this is "
      "modelled, not measured.",
      """[ARPA] * [Gross Margin Assumption]"""),

    m("CAC Payback (Months)", F_NUM1, "06 Unit Economics",
      "How many months of gross profit it takes to repay the cost of acquiring one customer. Depends on the gross-"
      "margin assumption, which is shown on the page beside it.",
      """DIVIDE ( [CAC (Blended)], [Gross Profit per Account] )"""),

    m("Monthly Churn Rate (TTM)", F_PCT2, "06 Unit Economics",
      "The average monthly logo churn rate over the trailing twelve months. The denominator of the lifetime-value "
      "calculation, isolated so the assumption behind LTV is visible.",
      """[Annualised Logo Churn %] / 12"""),

    m("LTV", F_MONEY, "06 Unit Economics",
      "Gross profit per account divided by the monthly churn rate: the value of an average customer over an average "
      "life. Two modelled inputs, both stated - the gross-margin assumption and a churn rate that is assumed constant. "
      "It is a planning number, not a measurement.",
      """VAR Churn = [Monthly Churn Rate (TTM)]
RETURN
    IF ( Churn > 0, DIVIDE ( [Gross Profit per Account], Churn ) )"""),

    m("LTV to CAC", F_NUM2, "06 Unit Economics",
      "Lifetime value over acquisition cost. Inherits every assumption LTV carries.",
      """DIVIDE ( [LTV], [CAC (Blended)] )"""),

    # ------------------------------------------------------- 07 product usage ---
    m("Usage Customers", F_INT, "07 Product Usage",
      "Customers with a usage record in the period. NOT the customer base: usage covers about 40% of paying customers "
      "in any month, so this is the sample every adoption figure is measured on.",
      """DISTINCTCOUNT ( FactUsageMonthly[CustomerID] )"""),

    m("Usage Coverage %", F_PCT, "07 Product Usage",
      "Customers with usage as a share of customers paying, at the snapshot month. Published on the page beside the "
      "adoption figures so nobody reads a sample as a census.",
      """VAR SnapshotMonth = [Snapshot Month]
VAR Seen =
    CALCULATE (
        DISTINCTCOUNT ( FactUsageMonthly[CustomerID] ),
        FactUsageMonthly[MonthStart] = SnapshotMonth,
        REMOVEFILTERS ( DimDate )
    )
RETURN
    IF ( NOT ISBLANK ( SnapshotMonth ), DIVIDE ( Seen, [Customers] ) )"""),

    m("Licensed Seats", F_INT, "07 Product Usage",
      "Seats licensed across the customers we can see, at the snapshot month.",
      """VAR SnapshotMonth = [Snapshot Month]
RETURN
    IF (
        NOT ISBLANK ( SnapshotMonth ),
        CALCULATE (
            SUM ( FactUsageMonthly[LicensedSeats] ),
            FactUsageMonthly[MonthStart] = SnapshotMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""),

    m("Active Users", F_INT, "07 Product Usage",
      "Users actually active across the customers we can see, at the snapshot month.",
      """VAR SnapshotMonth = [Snapshot Month]
RETURN
    IF (
        NOT ISBLANK ( SnapshotMonth ),
        CALCULATE (
            SUM ( FactUsageMonthly[ActiveUsers] ),
            FactUsageMonthly[MonthStart] = SnapshotMonth,
            REMOVEFILTERS ( DimDate )
        )
    )"""),

    m("Seat Utilisation %", F_PCT, "07 Product Usage",
      "Active users over licensed seats. The classic expansion signal in seat-based SaaS - and in this source it has "
      "no relationship with churn at all (r = -0.001), which the Churn Drivers page shows rather than asserts.",
      """DIVIDE ( [Active Users], [Licensed Seats] )"""),

    m("Feature Adoption %", F_PCT, "07 Product Usage",
      "Average feature adoption across the customers we can see. Averaged over customers, not weighted by their size, "
      "because it describes the product experience rather than the revenue.",
      """AVERAGE ( FactUsageMonthly[FeatureAdoptionRate] )"""),

    m("Logins per Customer", F_NUM1, "07 Product Usage",
      "Average logins per observed customer-month.",
      """AVERAGE ( FactUsageMonthly[Logins] )"""),

    m("Critical Errors per Customer", F_NUM2, "07 Product Usage",
      "Average critical errors per observed customer-month.",
      """AVERAGE ( FactUsageMonthly[CriticalErrors] )"""),

    m("Seats Changed %", F_PCT, "07 Product Usage",
      "The share of observed customers whose licensed seats move over time. Seats move in this data; MRR does not, "
      "which is exactly why seat growth is an adoption signal here and never billed expansion.",
      """VAR Observed = DISTINCTCOUNT ( FactUsageMonthly[CustomerID] )
VAR Movers =
    COUNTROWS (
        FILTER (
            VALUES ( FactUsageMonthly[CustomerID] ),
            CALCULATE ( DISTINCTCOUNT ( FactUsageMonthly[LicensedSeats] ) ) > 1
        )
    )
RETURN
    DIVIDE ( Movers, Observed )"""),

    # ----------------------------------------------------------- 08 support ---
    m("Tickets", F_INT, "08 Support",
      "Support tickets opened in the period.",
      """COUNTROWS ( FactSupportTicket )"""),

    m("Tickets per Customer per Month", F_NUM2, "08 Support",
      "Tickets divided by the months of customer life they could have come from. THE rate that matters: a raw ticket "
      "count correlates with churn at -0.00 because it mostly measures how long somebody has been a customer, while "
      "this rate correlates at +0.15.",
      """VAR Exposure = SUMX ( FactSubscription, FactSubscription[TenureMonths] )
RETURN
    DIVIDE ( [Tickets], Exposure )"""),

    m("Urgent Ticket Share", F_PCT, "08 Support",
      "High and Critical tickets as a share of all tickets opened.",
      """DIVIDE (
    CALCULATE ( COUNTROWS ( FactSupportTicket ), DimSeverity[IsUrgent] = TRUE () ),
    [Tickets]
)"""),

    m("Mean Time To Resolve (Hours)", F_NUM1, "08 Support",
      "Average resolution time across RESOLVED tickets only. The source populates a resolution time for tickets that "
      "are still open, drawn from the same distribution - so including them would be meaningless even though it barely "
      "moves the number here.",
      """CALCULATE (
    AVERAGE ( FactSupportTicket[ResolutionHours] ),
    FactSupportTicket[IsResolved] = TRUE ()
)"""),

    m("Open Tickets", F_INT, "08 Support",
      "Tickets not yet resolved, of those opened in the period.",
      """CALCULATE ( COUNTROWS ( FactSupportTicket ), FactSupportTicket[IsResolved] = FALSE () )"""),

    m("Unresolved Share", F_PCT, "08 Support",
      "Tickets still open or escalated as a share of those opened.",
      """DIVIDE ( [Open Tickets], [Tickets] )"""),

    m("Customers Raising Tickets", F_INT, "08 Support",
      "Distinct customers that opened at least one ticket in the period.",
      """DISTINCTCOUNT ( FactSupportTicket[CustomerID] )"""),

    # ----------------------------------------------------------- 09 billing ---
    m("Invoices", F_INT, "09 Billing",
      "Invoices issued in the period.",
      """COUNTROWS ( FactInvoice )"""),

    m("Failed Invoices", F_INT, "09 Billing",
      "Invoices that did not collect.",
      """CALCULATE ( COUNTROWS ( FactInvoice ), FactInvoice[IsFailed] = TRUE () )"""),

    m("Payment Failure Rate", F_PCT2, "09 Billing",
      "Failed invoices over invoices issued. The exposure-adjusted view of payment trouble - and it has no relationship "
      "with churn in this source (r = +0.000), so involuntary churn does not exist here.",
      """DIVIDE ( [Failed Invoices], [Invoices] )"""),

    m("Failed Invoice Value", F_MONEY0, "09 Billing",
      "The value behind the failed invoices.",
      """CALCULATE ( SUM ( FactInvoice[InvoiceAmount] ), FactInvoice[IsFailed] = TRUE () )"""),

    m("Median Days To Pay", F_NUM1, "09 Billing",
      "Median days from invoice to payment, across invoices that were paid.",
      """MEDIANX (
    CALCULATETABLE ( FactInvoice, FactInvoice[IsFailed] = FALSE () ),
    FactInvoice[DaysToPay]
)"""),

    m("Customers With a Failure", F_INT, "09 Billing",
      "Distinct customers with at least one failed invoice in the period.",
      """CALCULATE ( DISTINCTCOUNT ( FactInvoice[CustomerID] ), FactInvoice[IsFailed] = TRUE () )"""),

    # ---------------------------------------------------- 10 churn drivers ---
    m("Driver Correlation", F_R, "10 Churn Drivers",
      "The correlation between the driver in context and whether a customer ever churned, computed in SQL on every "
      "refresh (analytics.vw_ChurnDriverStrength) rather than typed onto a page. Positive means more of it goes with "
      "leaving.",
      """AVERAGE ( ChurnDriverStrength[Correlation] )"""),

    m("Driver Strength", F_FMT, "10 Churn Drivers",
      "The correlation read in words, so the page states a conclusion rather than leaving the reader to judge a "
      "decimal: anything inside 0.05 is no relationship at all.",
      """VAR R = ABS ( [Driver Correlation] )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( R ), BLANK (),
        R < 0.05, "No relationship",
        R < 0.10, "Very weak",
        R < 0.20, "Weak but real",
        R < 0.40, "Moderate",
        "Strong"
    )"""),

    m("Driver Group", F_FMT, "10 Churn Drivers",
      "Which family a candidate driver belongs to - Commercial, Behaviour, Product or Billing. A text measure rather "
      "than a column, so the evidence can be shown in a matrix (which suppresses its own total, where a table will "
      "not) without the group becoming a nested row level.",
      """SELECTEDVALUE ( ChurnDriverStrength[DriverGroup] )"""),

    m("Driver Customers", F_INT, "10 Churn Drivers",
      "How many customers the correlation was measured over. The usage drivers are measured on fewer, because usage "
      "does not cover everyone.",
      """SUM ( ChurnDriverStrength[Customers] )"""),

    m("Churn Rate by Group", F_PCT, "10 Churn Drivers",
      "The share of customers in context that have ever churned. Used to cut ever-churn by plan, segment, industry, "
      "country and channel - the cut that matters and the four that do not.",
      """DIVIDE ( [Customers Ever Churned], [Customers Ever Acquired] )"""),

    m("Churn Rate vs Average (pp)", F_NUM1, "10 Churn Drivers",
      "How far the group's ever-churn rate sits from the rate across every customer, in percentage points. The honest "
      "way to show that segment, industry and country say almost nothing here.",
      """VAR OverallRate = CALCULATE ( [Churn Rate by Group], REMOVEFILTERS () )
VAR GroupRate = [Churn Rate by Group]
RETURN
    IF ( NOT ISBLANK ( GroupRate ), ( GroupRate - OverallRate ) * 100 )"""),

    m("Churn Rate Spread (pp)", F_NUM1, "10 Churn Drivers",
      "The distance between the highest and lowest ever-churn rate across the values in context, in percentage points. "
      "One number for 'does this cut tell me anything'.",
      """VAR Rates =
    ADDCOLUMNS ( VALUES ( DimCustomer[Segment] ), "@r", [Churn Rate by Group] )
RETURN
    ( MAXX ( Rates, [@r] ) - MINX ( Rates, [@r] ) ) * 100""", hidden=True),

    # ---------------------------------------------------- 11 data quality ---
    m("DQ Metric Value", F_NUM2, "11 Data Quality",
      "A data-quality figure computed live in SQL from dbo, so the Data & Method page cannot drift from the data.",
      """SUM ( DataQualityMetric[MetricValue] )"""),

    m("DQ Metric Unit", F_FMT, "11 Data Quality",
      "How to read the value beside it: a share, a count, a correlation.",
      """SELECTEDVALUE ( DataQualityMetric[Unit] )"""),

    # ------------------------------------------------ 12 report formatting ---
    m("Retention Colour", F_FMT, "12 Report Formatting",
      "Cell colour for the cohort retention matrix: a three-step scale from the panel colour, so a matrix reads as a "
      "shape rather than as 600 numbers.",
      f"""VAR R = [Cohort Retention %]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( R ), BLANK (),
        R >= 0.90, "{C_RAMP_4}",
        R >= 0.75, "{C_RAMP_3}",
        R >= 0.50, "{C_RAMP_2}",
        R >= 0.25, "{C_RAMP_1}",
        "{C_PANEL}"
    )"""),

    m("Movement Bar Colour", F_FMT, "12 Report Formatting",
      "Waterfall bar colour from the sign of the movement it draws: what was won in green, what was lost in red, and "
      "a component that cannot occur in this data left grey so an empty bar reads as a property of the source.",
      f"""VAR Amount = [MRR Movement]
VAR Supported = SELECTEDVALUE ( DimMovementType[IsSupported] )
RETURN
    SWITCH (
        TRUE (),
        Supported = FALSE (), "{C_MUTED}",
        ISBLANK ( Amount ), BLANK (),
        Amount >= 0, "{C_BAR_WON}",
        "{C_BAR_LOST}"
    )"""),

    m("Driver Bar Colour", F_FMT, "12 Report Formatting",
      "Colour for the churn-driver chart: a driver inside |r| < 0.05 is drawn in a flat grey because it is not a "
      "driver, and the page should say so with its ink as well as its words. Direction is read off the axis, so the "
      "colour carries one thing only - whether this is a driver at all.",
      f"""VAR R = [Driver Correlation]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( R ), BLANK (),
        ABS ( R ) < 0.05, "{C_MUTED}",
        "{C_SIGNAL}"
    )"""),
]

# --------------------------------------------------------- calculation group ---
# One group, applied to whatever measure the visual is showing. Month over month
# on a stock (MRR, customers) and on a flow (new business, churn) both mean
# something, so this is deliberately not restricted to one family of measures.
CALC_GROUPS = [
    {
        "name": "Time Comparison",
        "column": "Comparison",
        "precedence": 10,
        "desc": "Applies a time comparison to whatever measure a visual shows: the period itself, the month before, "
                "the change, or the same month a year earlier. A comparison is BLANK where the model has no data to "
                "compare against, rather than showing the whole of a figure as growth.",
        "items": [
            ("Selected period", "The measure as it stands, with no comparison applied.",
             "SELECTEDMEASURE ()", None),
            ("Prior month", "The same measure one month earlier. Blank in the first month the data covers.",
             """CALCULATE (
    SELECTEDMEASURE (),
    DATEADD ( DimDate[Date], -1, MONTH )
)""", None),
            ("Month over month", "This month less last month.",
             """VAR CurrentValue = SELECTEDMEASURE ()
VAR PriorValue = CALCULATE ( SELECTEDMEASURE (), DATEADD ( DimDate[Date], -1, MONTH ) )
RETURN
    IF ( NOT ISBLANK ( PriorValue ), CurrentValue - PriorValue )""", None),
            ("Month over month %", "The change as a share of last month. Blank when last month is blank or zero, "
                                   "because a percentage of nothing is not infinity - it is unanswerable.",
             """VAR CurrentValue = SELECTEDMEASURE ()
VAR PriorValue = CALCULATE ( SELECTEDMEASURE (), DATEADD ( DimDate[Date], -1, MONTH ) )
RETURN
    IF ( PriorValue <> 0, DIVIDE ( CurrentValue - PriorValue, PriorValue ) )""",
             '"+0.0%;-0.0%;0.0%"'),
            ("Prior year", "The same measure twelve months earlier. Blank where the data does not reach back that far.",
             """VAR Target = EDATE ( MIN ( DimDate[Date] ), -12 )
VAR FirstMonth = CALCULATE ( MIN ( FactSubscriptionMonth[MonthStart] ), REMOVEFILTERS () )
RETURN
    IF (
        Target >= FirstMonth,
        CALCULATE ( SELECTEDMEASURE (), DATEADD ( DimDate[Date], -12, MONTH ) )
    )""", None),
            ("Year over year %", "Growth on the same month a year earlier, with the same guard: a year the ledger does "
                                 "not cover is blank, not infinite growth.",
             """VAR Target = EDATE ( MIN ( DimDate[Date] ), -12 )
VAR FirstMonth = CALCULATE ( MIN ( FactSubscriptionMonth[MonthStart] ), REMOVEFILTERS () )
VAR CurrentValue = SELECTEDMEASURE ()
VAR PriorValue = CALCULATE ( SELECTEDMEASURE (), DATEADD ( DimDate[Date], -12, MONTH ) )
RETURN
    IF ( Target >= FirstMonth && PriorValue <> 0, DIVIDE ( CurrentValue - PriorValue, PriorValue ) )""",
             '"+0.0%;-0.0%;0.0%"'),
        ],
    },
]

# ------------------------------------------------------------ field parameter ---
# The brief asks for field parameters for segment / industry / country analysis.
# One parameter drives every "cut by" visual on the report, so a reader changes
# the question rather than the page - and the generator does not have to build
# six near-identical charts.
FIELD_PARAMETERS = [
    {
        "name": "Customer Cut",
        "desc": "A field parameter: pick the attribute every 'by' chart on the page should group by. One slicer, six "
                "questions, and no duplicated visuals.",
        "fields": [
            ("Segment", "DimCustomer", "Segment"),
            ("Industry", "DimCustomer", "Industry"),
            ("Country", "DimCustomer", "Country"),
            ("Plan", "DimPlan", "PlanName"),
            ("Acquisition channel", "DimCustomer", "AcquisitionSource"),
            ("Billing cycle", "DimCustomer", "BillingCycle"),
        ],
    },
]
