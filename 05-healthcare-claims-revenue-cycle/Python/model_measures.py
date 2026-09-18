# -*- coding: utf-8 -*-
"""
Every measure in the model, both calculation groups, and the field-parameter table.

Read by Python/02_generate_semantic_model.py. Kept apart from the table spec because
this is the business logic and that is the plumbing.

The rules this file obeys, each one earned in Phase 1:

  THE ALLOWED AMOUNT IS THE SPINE.  Billed is a sticker price nobody pays - 26.5% of
  it is a contractual adjustment agreed in advance. Allowed is the contracted
  expectation, and it splits into exactly four buckets that sum back to it:
  collected, patient responsibility, open AR, denied. Every money measure here is
  built so that identity survives any slice.

  AR IS A STOCK, not a flow.  It is read from the snapshot at the last month end in
  context, capped at the as-of month, and never summed across months. Adding January's
  AR to February's counts the same unpaid claim twice.

  A window that starts after the as-of date returns BLANK, not the as-of figure.
  Otherwise every future month inherits today's number and the chart runs flat into
  2027 looking like a forecast.

  NET COLLECTION RATE IS QUOTED ON RESOLVED CLAIMS, and the all-claims version is
  published beside it. A revenue-cycle team is not accountable for claims the payer
  has not answered yet, so dividing cash by ALL allowed understates them; but the
  all-claims figure is what the organisation actually has, so both are shown.

  NOTHING CLAIMS A RECOVERY.  No denied claim in this file was ever paid, whatever
  its denial status says, so there is no appeal yield, overturn rate or recovery
  measure - only the workload profile of what is sitting in the queue.

  A PROVIDER IS NEVER RANKED WITHOUT ITS ERROR BAR.  The provider denial rates run
  3% to 14% and every bit of that is chance. The measures publish the standard error
  and the chance band next to the rate, so the distribution can be drawn against its
  own baseline instead of as a league table.

  Assumptions live in ModelConfig and are shown, never buried.
"""

# --------------------------------------------------------------- formatting ---
F_MONEY = "\\$#,0.00"
F_MONEY0 = "\\$#,0"
F_MONEY1 = "\\$#,0,\"K\""
F_INT = "#,0"
F_PCT = "0.0%"
F_PCT2 = "0.00%"
F_NUM1 = "#,0.0"
F_NUM2 = "#,0.00"
F_DAYS = "#,0.0"
F_DATE = "yyyy-mm-dd"
F_PP = "+0.0;-0.0;0.0"
F_TXT = None                      # a text measure: a format string would mean nothing

# ------------------------------------------------------------------ colours ---
# Conditional formatting, matched to the report theme in Python/04_generate_report.py.
# The report is a dark operations console, so a cell that carries NO signal must read
# as the PANEL and disappear; the ageing ramp runs cool (fresh) to hot (stale), which
# is the one place in this report where colour carries an ordered meaning.
C_PANEL = "#10292F"                        # the card: "nothing to see here"
C_AGE_1, C_AGE_2 = "#37C9A8", "#4FB3C4"    # 0-30, 31-60  - fresh
C_AGE_3, C_AGE_4 = "#6AA9E0", "#F2B441"    # 61-90, 91-180 - slipping
C_AGE_5, C_AGE_6 = "#E8944B", "#E8657A"    # 181-365, 365+ - past saving
C_IN, C_OUT = "#37C9A8", "#E8657A"         # into AR, out of AR
C_PATIENT = "#F2B441"                      # the patient's share
C_MUTED = "#5B767C"                        # measured, and inside chance
C_SIGNAL = "#37C9A8"                       # measured, and real


def m(name, fmt, folder, desc, dax, hidden=False):
    # .strip(), not .strip("\n"). A DAX expression that begins or ends with a quote needs a
    # space between it and Python's triple-quote delimiter, or the delimiter eats the
    # quote - but Power BI TRIMS the expression when it saves, so leaving that space
    # in the file makes a genuine Ctrl+S rewrite the measure. Trailing whitespace on
    # any line goes the same way.
    body = "\n".join(line.rstrip() for line in dax.strip().split("\n"))
    return {"name": name, "fmt": fmt, "folder": folder, "desc": desc, "dax": body, "hidden": hidden}


# The month end every stock measure is read at: the last month end in the current
# filter, capped at the as-of month, and BLANK when the whole selection sits in the
# future - so an AR chart stops where the data stops instead of drawing a flat line
# into next year.
SNAP = """VAR AsOfEnd = EOMONTH ( [As-Of Date], 0 )
VAR LastInContext = MAX ( DimDate[MonthEnd] )
VAR FirstInContext = MIN ( DimDate[MonthEnd] )
RETURN
    IF ( FirstInContext <= AsOfEnd, MIN ( LastInContext, AsOfEnd ) )"""

MEASURES = [
    # ==================================================== 00 model context ====
    m("As-Of Date", F_DATE, "00 Model Context",
      "The last day anything happens in the file - the latest payment date - read from ModelConfig. Every "
      "point-in-time figure is stated on it and nothing in this model hard-codes it.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "AsOfDate", REMOVEFILTERS () )
RETURN
    DATEVALUE ( Raw )"""),

    m("Snapshot Month End", F_DATE, "00 Model Context",
      "The month end every AR figure is read at: the last month end in the current filter, capped at the as-of "
      "month, and BLANK when the whole selection is in the future.",
      SNAP, hidden=True),

    m("Data Start Date", F_DATE, "00 Model Context",
      "First service date in the file.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "DataStartDate", REMOVEFILTERS () )
RETURN
    DATEVALUE ( Raw )"""),

    m("Service Data End", F_DATE, "00 Model Context",
      "The last SERVICE date. Claims go on being adjudicated and paid after this, which is why the cash tail runs "
      "two months further than the clinical activity.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "ServiceDataEnd", REMOVEFILTERS () )
RETURN
    DATEVALUE ( Raw )"""),

    m("Currency", F_TXT, "00 Model Context",
      "AUD. Every facility state is Australian and the payers are Medicare, Bupa, Medibank, HCF and NIB.",
      """CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "Currency", REMOVEFILTERS () )"""),

    m("Timely Filing Days", F_INT, "00 Model Context",
      "An ASSUMPTION, not data: the outer limit of a payer timely-filing window, used to mark receivables that "
      "could not be collected in practice. Held in ModelConfig so it is visible and changeable in one place.",
      """VAR Raw =
    CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "TimelyFilingDays", REMOVEFILTERS () )
RETURN
    VALUE ( Raw )"""),

    m("AR Carried At", F_TXT, "00 Model Context",
      "Allowed. Open AR is carried at the contracted expectation, not at billed - billed AR would overstate the "
      "receivable by the whole contractual adjustment.",
      """CALCULATE ( MAX ( ModelConfig[ConfigValue] ), ModelConfig[ConfigKey] = "ARCarriedAt", REMOVEFILTERS () )"""),

    m("Last Submission Date", F_DATE, "00 Model Context",
      "The last day a claim was SUBMITTED - 7 September 2026, two months before the last payment. It matters "
      "because any rate expressed as days of business has to divide by a window in which business was actually "
      "being submitted; a window running to the end of the data would divide by seven days of submissions and "
      "report a receivable of twenty-four years.",
      """VAR LastKey = CALCULATE ( MAX ( FactClaim[SubmittedDateKey] ), REMOVEFILTERS () )
RETURN
    CALCULATE ( MAX ( DimDate[Date] ), REMOVEFILTERS (), DimDate[DateKey] = LastKey )"""),

    m("As-Of Label", F_TXT, "00 Model Context",
      "The footer line every page carries: what date the figures stand on, in what currency.",
      """ "As at " & FORMAT ( [As-Of Date], "d mmm yyyy" ) & "  |  " & [Currency] & "  |  Synthetic data" """),

    # ========================================================== 01 volume ====
    m("Claims", F_INT, "01 Volume",
      "Claims in context. The claim header is the grain: one row, one adjudication decision.",
      """COUNTROWS ( FactClaim )"""),

    m("Claim Lines", F_INT, "01 Volume",
      "Procedure lines. About 2.5 per claim. Counted from the line table, which carries its own dimension keys "
      "rather than reaching through the header.",
      """COUNTROWS ( FactClaimLine )"""),

    m("Lines per Claim", F_NUM2, "01 Volume",
      "Average procedure lines per claim.",
      """DIVIDE ( [Claim Lines], [Claims] )"""),

    m("Patients Treated", F_INT, "01 Volume",
      "Distinct patients on the claims in context. Taken from the CLAIMS, never from the patient dimension: "
      "1,034 of the 30,000 beneficiaries never appear on a claim, and counting the dimension would overstate "
      "the treated population by that much.",
      """DISTINCTCOUNT ( FactClaim[BeneficiaryKey] )"""),

    m("Providers Billing", F_INT, "01 Volume",
      "Distinct providers who billed in context.",
      """DISTINCTCOUNT ( FactClaim[ProviderKey] )"""),

    m("Facilities Billing", F_INT, "01 Volume",
      "Distinct facilities that billed in context.",
      """DISTINCTCOUNT ( FactClaim[FacilityKey] )"""),

    m("Claims per Patient", F_NUM2, "01 Volume",
      "Average claims per treated patient.",
      """DIVIDE ( [Claims], [Patients Treated] )"""),

    m("Claims per Provider", F_NUM1, "01 Volume",
      "Average claims per billing provider. It matters for the denial analysis: at roughly 200 claims each, a "
      "provider's denial rate carries a standard error of about 1.9 points.",
      """DIVIDE ( [Claims], [Providers Billing] )"""),

    m("Paid Claims", F_INT, "01 Volume",
      "Claims that settled. Each has exactly one remittance.",
      """CALCULATE ( COUNTROWS ( FactClaim ), FactClaim[IsPaid] = TRUE () )"""),

    m("Pending Claims", F_INT, "01 Volume",
      "Claims with no payment and no denial - the open receivable. Note that in this source a pending claim "
      "NEVER resolves: the pending share is the same in every month of the file.",
      """CALCULATE ( COUNTROWS ( FactClaim ), FactClaim[IsPending] = TRUE () )"""),

    m("Denied Claims", F_INT, "01 Volume",
      "Claims adjudicated to zero. Each has exactly one denial row.",
      """CALCULATE ( COUNTROWS ( FactClaim ), FactClaim[IsDenied] = TRUE () )"""),

    # =========================================================== 02 money ====
    m("Billed", F_MONEY0, "02 Money",
      "What was charged, at the chargemaster price. Nobody ever pays this - it is the top of the funnel and "
      "nothing else.",
      """SUM ( FactClaim[BilledAmount] )"""),

    m("Allowed", F_MONEY0, "02 Money",
      "What the payer agreed to under contract. THE spine of this model: every dollar here ends up collected, "
      "owed by a patient, denied, or still in AR, and those four sum back to it on every row.",
      """SUM ( FactClaim[AllowedAmount] )"""),

    m("Collected", F_MONEY0, "02 Money",
      "Cash received from the payer.",
      """SUM ( FactClaim[PaidAmount] )"""),

    m("Contractual Adjustment", F_MONEY0, "02 Money",
      "Billed less allowed: the discount agreed in advance. It is not a loss and it is never presented as one.",
      """SUM ( FactClaim[ContractualAdjustment] )"""),

    m("Patient Responsibility", F_MONEY0, "02 Money",
      "The allowed amount the payer did not settle - copay, coinsurance and deductible. In a real revenue cycle "
      "this begins a second, slower receivable; this source records no patient payment events, so it is treated "
      "as resolved on the payer's payment date and that assumption is stated on the page.",
      """SUM ( FactClaim[PatientResponsibility] )"""),

    m("Denied Amount", F_MONEY0, "02 Money",
      "Allowed value on denied claims. Carried at allowed rather than billed, for the same reason AR is.",
      """SUM ( FactClaim[DeniedAmount] )"""),

    m("Open AR (Claim Basis)", F_MONEY0, "02 Money",
      "Allowed value sitting on pending claims, read from the claim header rather than the snapshot. Used for "
      "the four-bucket identity; the AR pages use the snapshot, which can also be aged.",
      """SUM ( FactClaim[OpenARAmount] )"""),

    m("Allowed Buckets Total", F_MONEY0, "02 Money",
      "Collected + patient responsibility + open AR + denied. It must equal Allowed exactly, and the difference "
      "is published next to it so the identity is visible rather than merely asserted.",
      """[Collected] + [Patient Responsibility] + [Open AR (Claim Basis)] + [Denied Amount]"""),

    m("Allowed Identity Gap", F_MONEY, "02 Money",
      "Allowed less the four buckets. Zero, always - on every row and therefore at every level of every "
      "aggregation. Shown on the method page as evidence, not as a metric.",
      """[Allowed] - [Allowed Buckets Total]"""),

    m("Average Billed per Claim", F_MONEY, "02 Money",
      "Mean charge per claim.",
      """DIVIDE ( [Billed], [Claims] )"""),

    m("Average Allowed per Claim", F_MONEY, "02 Money",
      "Mean contracted value per claim.",
      """DIVIDE ( [Allowed], [Claims] )"""),

    m("Average Collected per Paid Claim", F_MONEY, "02 Money",
      "Mean cash per claim that actually settled.",
      """VAR PaidCount = [Paid Claims]
RETURN
    DIVIDE ( [Collected], PaidCount )"""),

    m("Line Charges", F_MONEY0, "02 Money",
      "Charges summed from the LINE table. It reconciles to Billed on every claim, which is why the line table "
      "can carry procedure and diagnosis mix without becoming a second source of truth. No measure ever adds "
      "this to a header amount.",
      """SUM ( FactClaimLine[ChargeAmount] )"""),

    m("Cash Received", F_MONEY0, "02 Money",
      "The same cash as Collected, but seen on the PAYMENT date rather than the service date. This is the "
      "measure a cash-flow question wants; Collected is the one a revenue question wants.",
      """SUM ( FactPayment[PaymentAmount] )"""),

    # =========================================================== 03 rates ====
    m("Allowed Rate %", F_PCT, "03 Rates",
      "Allowed as a share of billed. It runs 73.4% to 73.6% for every payer including Self Pay, so it is "
      "reported group-wide and payers are never ranked by it - there is nothing there to rank.",
      """DIVIDE ( [Allowed], [Billed] )"""),

    m("Contractual Adjustment %", F_PCT, "03 Rates",
      "The share of billed given away by contract. The complement of the allowed rate.",
      """DIVIDE ( [Contractual Adjustment], [Billed] )"""),

    m("Gross Collection Rate %", F_PCT, "03 Rates",
      "Cash as a share of BILLED. Always a low number and largely meaningless on its own, because most of the "
      "gap is a contractual adjustment agreed before the claim was sent. Published because the brief asks for "
      "it, next to the net rate that actually means something.",
      """DIVIDE ( [Collected], [Billed] )"""),

    m("Net Collection Rate %", F_PCT, "03 Rates",
      "Cash as a share of allowed on RESOLVED claims only. This is the figure a revenue-cycle team is measured "
      "on: they are not accountable for claims the payer has not answered yet, so pending claims are excluded "
      "from the denominator. The gap to 100% is denials plus patient responsibility.",
      """VAR ResolvedAllowed =
    CALCULATE ( SUM ( FactClaim[AllowedAmount] ), FactClaim[IsPending] = FALSE () )
RETURN
    DIVIDE ( [Collected], ResolvedAllowed )"""),

    m("Net Collection Rate (All Claims) %", F_PCT, "03 Rates",
      "Cash as a share of ALL allowed, pending included. Lower than the resolved figure and shown beside it, "
      "because this is what the organisation has actually banked against what it was promised - and in this "
      "source, where a pending claim never resolves, the difference between the two is the whole story.",
      """DIVIDE ( [Collected], [Allowed] )"""),

    m("Patient Responsibility %", F_PCT, "03 Rates",
      "The patient's share of the allowed amount on paid claims - copay, coinsurance and deductible.",
      """VAR PaidAllowed =
    CALCULATE ( SUM ( FactClaim[AllowedAmount] ), FactClaim[IsPaid] = TRUE () )
RETURN
    DIVIDE ( [Patient Responsibility], PaidAllowed )"""),

    m("Paid Claim Rate %", F_PCT, "03 Rates",
      "Share of claims that settled.",
      """DIVIDE ( [Paid Claims], [Claims] )"""),

    m("Pending Rate %", F_PCT, "03 Rates",
      "Share of claims still unanswered. It is 20.6% to 25.0% in every submission month of the file, including "
      "the first - which is why the ageing that follows from it is arithmetic and not a collections story.",
      """DIVIDE ( [Pending Claims], [Claims] )"""),

    # ========================================================= 04 denials ====
    m("Denial Rate %", F_PCT2, "04 Denials",
      "Denied claims as a share of claims. The headline acceptance figure, upside down.",
      """DIVIDE ( [Denied Claims], [Claims] )"""),

    m("Denial Rate (Value) %", F_PCT2, "04 Denials",
      "Denied ALLOWED value as a share of allowed. It tracks the count rate closely here, because claim size "
      "has no relationship to denial (r = -0.0001).",
      """DIVIDE ( [Denied Amount], [Allowed] )"""),

    m("First-Pass Acceptance %", F_PCT2, "04 Denials",
      "Claims accepted on first submission. IMPORTANT: with no resubmission chain anywhere in this source - no "
      "original-claim link, no claim with two denials, no denied claim ever paid - this is exactly 1 minus the "
      "denial rate, not an independent measurement. It is published with that caveat on the page.",
      """DIVIDE ( CALCULATE ( COUNTROWS ( FactClaim ), FactClaim[IsFirstPassAccepted] = TRUE () ), [Claims] )"""),

    m("Clean Claim Rate %", F_PCT2, "04 Denials",
      "A claim that needed no rework. In this source it is the SAME NUMBER as first-pass acceptance, for the "
      "same reason: nothing records a rework. Both are shown on one card so no one reads three measurements "
      "where there is one.",
      """[First-Pass Acceptance %]"""),

    m("Denials", F_INT, "04 Denials",
      "Denial records in context, from the denial fact. Equal to Denied Claims - there is exactly one denial "
      "per denied claim - but sliceable by reason and status, which the claim header is not.",
      """COUNTROWS ( FactDenial )"""),

    m("Denied Value", F_MONEY0, "04 Denials",
      "Allowed value on the denials in context. Read from the denial fact so it can be split by reason.",
      """SUM ( FactDenial[DeniedAllowed] )"""),

    m("Denied Value at Billed", F_MONEY0, "04 Denials",
      "The same denials at chargemaster price. Always the larger, more alarming number; shown once next to the "
      "allowed figure to make the point that the allowed one is the real exposure.",
      """SUM ( FactDenial[DeniedBilled] )"""),

    m("Denial Share of Reason %", F_PCT, "04 Denials",
      "A reason's share of all denials in context. The mix is close to uniform across payers and facilities, so "
      "this is a WORKLOAD profile - what the denials team has to work - and never a root cause.",
      """DIVIDE ( [Denials], CALCULATE ( [Denials], REMOVEFILTERS ( DimDenialReason ) ) )"""),

    m("Preventable at Registration %", F_PCT, "04 Denials",
      "The share of denials whose reason is a front-end failure - eligibility, prior authorisation or missing "
      "information. These are the ones a registration desk can stop before the claim is ever sent.",
      """VAR FrontEnd =
    CALCULATE ( [Denials], DimDenialReason[ReasonCategory] = "Front-end" )
RETURN
    DIVIDE ( FrontEnd, CALCULATE ( [Denials], REMOVEFILTERS ( DimDenialReason ) ) )"""),

    m("Self Pay Denial Rate %", F_PCT2, "04 Denials",
      "The denial rate on self-funded patients: 2.95%, and the only genuinely different number in the data.",
      """CALCULATE ( [Denial Rate %], DimPayer[IsSelfPay] = TRUE (), REMOVEFILTERS ( DimPayer ) )"""),

    m("Insured Denial Rate %", F_PCT2, "04 Denials",
      "The denial rate across the five insurers: 8.79%. Among themselves they sit within 0.66 points of one "
      "another, which at these volumes is noise.",
      """CALCULATE ( [Denial Rate %], DimPayer[IsSelfPay] = FALSE (), REMOVEFILTERS ( DimPayer ) )"""),

    m("Self Pay Gap (pp)", F_PP, "04 Denials",
      "Insured denial rate less self-pay denial rate, in percentage points. The largest effect anywhere in this "
      "dataset, and the only one the report treats as a finding.",
      """( [Insured Denial Rate %] - [Self Pay Denial Rate %] ) * 100"""),

    m("Denials Written Off", F_INT, "04 Denials",
      "Denials in the terminal workflow state. The source records no write-off AMOUNT, so the value of these is "
      "read as their allowed amount and labelled as such.",
      """CALCULATE ( [Denials], DimDenialStatus[IsTerminal] = TRUE () )"""),

    m("Denials Still Open %", F_PCT, "04 Denials",
      "The share of denials sitting in a non-terminal workflow state. This is queue depth, NOT a recovery "
      "prospect: no denied claim in this file was ever paid, including every one marked Corrected or Appealed.",
      """VAR TerminalCount = CALCULATE ( [Denials], DimDenialStatus[IsTerminal] = TRUE () )
VAR AllDenials = CALCULATE ( [Denials], REMOVEFILTERS ( DimDenialStatus ) )
RETURN
    DIVIDE ( AllDenials - COALESCE ( TerminalCount, 0 ), AllDenials )"""),

    m("Denial Recovery Rate %", F_PCT2, "04 Denials",
      "Cash recovered on denied claims as a share of denied value. It is ZERO by construction in this source - "
      "not small, zero - and it is published precisely so the page can say that appeal yield is unmeasurable "
      "here rather than leaving a reader to assume it was overlooked.",
      """VAR RecoveredCash =
    CALCULATE ( SUM ( FactClaim[PaidAmount] ), FactClaim[IsDenied] = TRUE () )
RETURN
    DIVIDE ( COALESCE ( RecoveredCash, 0 ), [Denied Amount] )"""),

    # ==================================================== 05 receivables =====
    m("Open AR", F_MONEY0, "05 Accounts Receivable",
      "The receivable at the snapshot month end: what was submitted and not yet resolved, at allowed. A STOCK - "
      "read at one month end, never summed across months, and BLANK when the whole selection is beyond the data.",
      """VAR SnapEnd = [Snapshot Month End]
RETURN
    IF (
        NOT ISBLANK ( SnapEnd ),
        CALCULATE (
            SUM ( FactARSnapshot[ARAmount] ),
            REMOVEFILTERS ( DimDate ),
            DimDate[Date] = SnapEnd
        )
    )"""),

    m("AR Claims", F_INT, "05 Accounts Receivable",
      "Claims sitting in AR at the snapshot month end.",
      """VAR SnapEnd = [Snapshot Month End]
RETURN
    IF (
        NOT ISBLANK ( SnapEnd ),
        CALCULATE (
            COUNTROWS ( FactARSnapshot ),
            REMOVEFILTERS ( DimDate ),
            DimDate[Date] = SnapEnd
        )
    )"""),

    m("Average AR per Claim", F_MONEY, "05 Accounts Receivable",
      "Mean receivable per open claim.",
      """DIVIDE ( [Open AR], [AR Claims] )"""),

    m("AR Weighted Age (Days)", F_DAYS, "05 Accounts Receivable",
      "The average age of the receivable WEIGHTED BY DOLLARS, not by claim. A big old claim should move this "
      "number more than a small fresh one, and an unweighted average lets a pile of small recent claims hide a "
      "large stale one.",
      """VAR SnapEnd = [Snapshot Month End]
VAR SnapRows =
    CALCULATETABLE (
        FactARSnapshot,
        REMOVEFILTERS ( DimDate ),
        DimDate[Date] = SnapEnd
    )
VAR WeightedDays = SUMX ( SnapRows, FactARSnapshot[ARAmount] * FactARSnapshot[AgeDays] )
VAR TotalAmount = SUMX ( SnapRows, FactARSnapshot[ARAmount] )
RETURN
    IF ( NOT ISBLANK ( SnapEnd ), DIVIDE ( WeightedDays, TotalAmount ) )"""),

    m("AR Median Age (Days)", F_DAYS, "05 Accounts Receivable",
      "The middle claim's age at the snapshot month end. Published next to the weighted age because a gap between "
      "the two would mean the oldest receivables are also the largest. Here they agree to within a week, "
      "which says claim size and claim age are unrelated - consistent with everything else measured about "
      "this source.",
      """VAR SnapEnd = [Snapshot Month End]
RETURN
    IF (
        NOT ISBLANK ( SnapEnd ),
        CALCULATE (
            MEDIANX ( FactARSnapshot, FactARSnapshot[AgeDays] ),
            REMOVEFILTERS ( DimDate ),
            DimDate[Date] = SnapEnd
        )
    )"""),

    m("AR Past Filing Limit", F_MONEY0, "05 Accounts Receivable",
      "Receivable older than the timely-filing window. In a real revenue cycle this is not a receivable at all - "
      "it is a write-off that has not been recognised yet.",
      """CALCULATE ( [Open AR], DimARBucket[IsPastFiling] = TRUE () )"""),

    m("AR Past Filing %", F_PCT, "05 Accounts Receivable",
      "The share of the receivable beyond any payer's filing window. It is 77% here, which is the clearest "
      "single sign that 'Pending' in this source is a permanent label rather than a claim in flight.",
      """VAR PastFiling = CALCULATE ( [Open AR], DimARBucket[IsPastFiling] = TRUE () )
RETURN
    DIVIDE ( COALESCE ( PastFiling, 0 ), CALCULATE ( [Open AR], REMOVEFILTERS ( DimARBucket ) ) )"""),

    m("Open AR (All Buckets)", F_MONEY0, "05 Accounts Receivable",
      "The receivable, plus zero, so that an EMPTY ageing bucket still draws. The two freshest buckets are empty "
      "at the as-of month end - nothing has been submitted for 84 days - and a blank bar silently vanishing from "
      "the ladder would hide precisely the thing worth seeing.",
      """VAR Amount = [Open AR]
RETURN
    IF ( NOT ISBLANK ( [Snapshot Month End] ), COALESCE ( Amount, 0 ) )"""),

    m("AR Bucket Share %", F_PCT, "05 Accounts Receivable",
      "An ageing bucket's share of the whole receivable.",
      """DIVIDE ( [Open AR], CALCULATE ( [Open AR], REMOVEFILTERS ( DimARBucket ) ) )"""),

    m("Days in AR", F_DAYS, "05 Accounts Receivable",
      "The receivable expressed as days of submitted business - the revenue cycle's DSO. Open AR divided by the "
      "average daily allowed value SUBMITTED over the preceding 91 days, because a receivable is created on "
      "submission and that is the relationship this measure switches on explicitly. "
      "THE WINDOW IS CAPPED AT THE LAST SUBMISSION DATE. Claims stop being submitted on 7 September 2026 but "
      "cash goes on arriving until 3 November, so a window running to the end of the data would divide a full "
      "receivable by seven days of business and report a DSO of about 8,700 days. Capping it divides by a "
      "quarter in which claims were actually being sent.",
      """VAR SnapEnd = [Snapshot Month End]
VAR WindowEnd = MIN ( SnapEnd, [Last Submission Date] )
VAR Recent =
    CALCULATE (
        SUM ( FactClaim[AllowedAmount] ),
        REMOVEFILTERS ( DimDate ),
        DATESINPERIOD ( DimDate[Date], WindowEnd, -91, DAY ),
        USERELATIONSHIP ( FactClaim[SubmittedDateKey], DimDate[DateKey] )
    )
RETURN
    IF ( NOT ISBLANK ( SnapEnd ), DIVIDE ( [Open AR], DIVIDE ( Recent, 91 ) ) )"""),

    m("AR Opening", F_MONEY0, "05 Accounts Receivable",
      "The receivable at the END of the previous month - the opening balance for the period in context. The "
      "other half of the roll-forward.",
      """VAR SnapEnd = [Snapshot Month End]
VAR PriorEnd = EOMONTH ( SnapEnd, -1 )
RETURN
    IF (
        NOT ISBLANK ( SnapEnd ),
        CALCULATE (
            SUM ( FactARSnapshot[ARAmount] ),
            REMOVEFILTERS ( DimDate ),
            DimDate[Date] = PriorEnd
        )
    )"""),

    # =================================================== 06 AR movement =====
    m("AR Movement", F_MONEY0, "06 AR Movement",
      "Signed movement in the receivable: positive on submission, negative as cash, patient responsibility or "
      "denial. A FLOW, so unlike Open AR it sums across months correctly.",
      """SUM ( FactARMovement[Amount] )"""),

    m("AR Movement (All Components)", F_MONEY0, "06 AR Movement",
      "The same figure plus zero, so a waterfall draws every component including any that happens to be empty. "
      "A blank component silently vanishes from a waterfall, which defeats the point of showing the bridge.",
      """SUM ( FactARMovement[Amount] ) + 0"""),

    m("AR In (Submitted)", F_MONEY0, "06 AR Movement",
      "Allowed value entering the receivable as claims are submitted.",
      """CALCULATE ( [AR Movement], DimARMovementType[MovementType] = "Submitted" )"""),

    m("AR Out (Collected)", F_MONEY0, "06 AR Movement",
      "Allowed value leaving as payer cash. Shown positive on the page; negative here so the bridge adds up.",
      """CALCULATE ( [AR Movement], DimARMovementType[MovementType] = "Collected" )"""),

    m("AR Out (Patient)", F_MONEY0, "06 AR Movement",
      "Allowed value leaving as patient responsibility. It leaves the payer receivable on the payment date - a "
      "stated assumption, because this source records no patient payment events.",
      """CALCULATE ( [AR Movement], DimARMovementType[MovementType] = "Patient responsibility" )"""),

    m("AR Out (Denied)", F_MONEY0, "06 AR Movement",
      "Allowed value leaving as a denial.",
      """CALCULATE ( [AR Movement], DimARMovementType[MovementType] = "Denied" )"""),

    m("AR Movement in Snapshot Month", F_MONEY0, "06 AR Movement",
      "Net movement during the SNAPSHOT MONTH specifically, whatever period the visual is showing. The plain "
      "movement measure follows the visual's own date filter, which is right for a flow but wrong for checking "
      "a balance: with no date filter it spans four years while the opening balance is one month back. This one "
      "is anchored to the same month the balances are.",
      """VAR SnapEnd = [Snapshot Month End]
VAR SnapStart = DATE ( YEAR ( SnapEnd ), MONTH ( SnapEnd ), 1 )
RETURN
    IF (
        NOT ISBLANK ( SnapEnd ),
        CALCULATE (
            SUM ( FactARMovement[Amount] ),
            REMOVEFILTERS ( DimDate ),
            DimDate[Date] >= SnapStart && DimDate[Date] <= SnapEnd
        )
    )"""),

    m("AR Roll-Forward Check", F_MONEY, "06 AR Movement",
      "Closing AR less opening AR less the month's net movement. Zero in all 47 months AND at every grain, "
      "because all three terms are anchored to the same month - which is what makes the snapshot and the ledger "
      "evidence for each other rather than two numbers that happen to sit on the same page.",
      """VAR SnapEnd = [Snapshot Month End]
VAR OpeningAR = COALESCE ( [AR Opening], 0 )
VAR NetMove = COALESCE ( [AR Movement in Snapshot Month], 0 )
RETURN
    IF ( NOT ISBLANK ( SnapEnd ), [Open AR] - OpeningAR - NetMove )"""),

    m("Resolution Rate %", F_PCT, "06 AR Movement",
      "Allowed value leaving the receivable in the period as a share of what entered it. Above 100% means the "
      "backlog shrank; below, it grew.",
      """VAR CameIn = [AR In (Submitted)]
VAR WentOut =
    - ( COALESCE ( [AR Out (Collected)], 0 ) + COALESCE ( [AR Out (Patient)], 0 )
        + COALESCE ( [AR Out (Denied)], 0 ) )
RETURN
    DIVIDE ( WentOut, CameIn )"""),

    # ====================================================== 07 timeliness ====
    m("Days to Submit", F_DAYS, "07 Timeliness",
      "Service to submission, in days. This is the PROVIDER'S own lag - the one part of the clock a billing "
      "office controls outright.",
      """AVERAGE ( FactClaim[DaysToSubmit] )"""),

    m("Days to Adjudicate", F_DAYS, "07 Timeliness",
      "Submission to the payer's decision, in days.",
      """AVERAGE ( FactClaim[DaysToProcess] )"""),

    m("Days to Resolve", F_DAYS, "07 Timeliness",
      "Submission to cash or denial, in days. Pending claims are excluded - they have no resolution date, and "
      "including them as zero would flatter the figure enormously.",
      """AVERAGE ( FactClaim[DaysToResolve] )"""),

    m("Days to Cash", F_DAYS, "07 Timeliness",
      "Submission to payment, measured on the payment fact. The end-to-end number a revenue-cycle team quotes.",
      """AVERAGE ( FactPayment[DaysToPay] )"""),

    m("Days Adjudication to Cash", F_DAYS, "07 Timeliness",
      "How long the payer takes to release money after deciding to. A median of five days here, which is fast "
      "and consistent.",
      """VAR PaidRows = CALCULATETABLE ( FactClaim, FactClaim[IsPaid] = TRUE () )
RETURN
    AVERAGEX ( PaidRows, FactClaim[DaysToResolve] - FactClaim[DaysToProcess] )"""),

    m("Days to Cash (Claim Basis)", F_DAYS, "07 Timeliness",
      "Submission to cash, measured on the CLAIM rather than on the payment. Identical to [Days to Cash] at the "
      "grand total - both average the same 69,111 lags - but it hangs off the claim's own date relationship, so "
      "it can share a time axis with the other two intervals.  "
      "WHY THIS EXISTS: [Days to Cash] reads FactPayment, whose active date is the PAYMENT date, while days to "
      "submit and days to adjudicate read FactClaim, whose active date is the SERVICE date. Plotted together "
      "they put service months and payment months on one axis, and the line ran off the end of the chart in the "
      "two months when cash was still arriving for care delivered earlier.",
      """CALCULATE ( AVERAGE ( FactClaim[DaysToResolve] ), FactClaim[IsPaid] = TRUE () )"""),

    m("Median Days to Cash", F_DAYS, "07 Timeliness",
      "The middle claim's submission-to-cash time. Published beside the mean because a mean hides a tail and a "
      "median does not.",
      """MEDIANX ( FactPayment, FactPayment[DaysToPay] )"""),

    m("Submitted within 3 Days %", F_PCT, "07 Timeliness",
      "Share of claims sent within three days of service. The provider's own discipline, isolated from anything "
      "a payer does.",
      """VAR Quick = CALCULATE ( [Claims], FactClaim[DaysToSubmit] <= 3 )
RETURN
    DIVIDE ( COALESCE ( Quick, 0 ), [Claims] )"""),

    m("Adjudicated within 30 Days %", F_PCT, "07 Timeliness",
      "Share of claims the payer answered inside 30 days.",
      """VAR Quick = CALCULATE ( [Claims], FactClaim[DaysToProcess] <= 30 )
RETURN
    DIVIDE ( COALESCE ( Quick, 0 ), [Claims] )"""),

    m("Paid within 45 Days %", F_PCT, "07 Timeliness",
      "Share of PAID claims where cash arrived inside 45 days of submission. Measured on paid claims only, and "
      "labelled that way: a pending claim has not failed this test, it simply has not taken it.",
      """VAR Quick = CALCULATE ( COUNTROWS ( FactPayment ), FactPayment[DaysToPay] <= 45 )
RETURN
    DIVIDE ( COALESCE ( Quick, 0 ), COUNTROWS ( FactPayment ) )"""),

    m("Longest Days to Cash", F_INT, "07 Timeliness",
      "The slowest claim to settle, in days.",
      """MAX ( FactPayment[DaysToPay] )"""),

    # ================================================ 08 method & evidence ====
    m("Signal Strength", "0.0000", "08 Method & Evidence",
      "Cramer's V between a dimension and the denied flag, computed in SQL on every refresh. Comparable across "
      "dimensions with different numbers of values, which a raw chi-square is not.",
      """AVERAGE ( DenialSignal[CramersV] )"""),

    m("Strongest Signal", "0.0000", "08 Method & Evidence",
      "The largest association with denial anywhere in the data: payer, at 0.081. The next is facility at 0.015.",
      """CALCULATE ( MAX ( DenialSignal[CramersV] ), REMOVEFILTERS ( DenialSignal ) )"""),

    m("Strongest Signal Dimension", F_TXT, "08 Method & Evidence",
      "Which dimension that is. Computed rather than typed, so it cannot disagree with the chart beside it.",
      """VAR Best = CALCULATE ( MAX ( DenialSignal[CramersV] ), REMOVEFILTERS ( DenialSignal ) )
RETURN
    CALCULATE (
        MAX ( DenialSignal[Dimension] ),
        REMOVEFILTERS ( DenialSignal ),
        DenialSignal[CramersV] = Best
    )"""),

    m("Dimensions Tested", F_INT, "08 Method & Evidence",
      "How many candidate dimensions were put through the test. All of them, not just the ones that worked.",
      """CALCULATE ( COUNTROWS ( DenialSignal ), REMOVEFILTERS ( DenialSignal ) )"""),

    m("Dimensions with Signal", F_INT, "08 Method & Evidence",
      "How many passed the stated rule of Cramer's V at or above 0.02. One.",
      """CALCULATE (
    COUNTROWS ( DenialSignal ),
    REMOVEFILTERS ( DenialSignal ),
    DenialSignal[SignalVerdict] = "Signal"
)"""),

    m("Denial Rate Spread (pp)", F_NUM2, "08 Method & Evidence",
      "Percentage points between the highest and lowest denial rate inside a dimension. Useful, and on its own "
      "misleading - a dimension with 30 values will always spread further than one with three, which is exactly "
      "why the chi-square sits next to it.",
      """AVERAGE ( DenialSignal[SpreadPP] )"""),

    m("Providers Measured", F_INT, "08 Method & Evidence",
      "Providers in the chance table.",
      """COUNTROWS ( ProviderChance )"""),

    m("Providers Beyond 2 SE", F_INT, "08 Method & Evidence",
      "Providers whose denial rate is more than two standard errors from the group rate - the ones a league "
      "table would name.",
      """CALCULATE ( COUNTROWS ( ProviderChance ), ProviderChance[ChanceBand] <> "Within chance" )"""),

    m("Providers Beyond 2 SE %", F_PCT, "08 Method & Evidence",
      "Their share of all providers: 4.6%. A normal distribution puts 4.55% beyond two standard deviations, so "
      "the number of apparent outliers is exactly what chance produces.",
      """VAR Outliers =
    CALCULATE ( COUNTROWS ( ProviderChance ), ProviderChance[ChanceBand] <> "Within chance" )
RETURN
    DIVIDE ( COALESCE ( Outliers, 0 ), COUNTROWS ( ProviderChance ) )"""),

    m("Expected Beyond 2 SE %", F_PCT, "08 Method & Evidence",
      "4.55%: the share of a normal distribution beyond two standard deviations. The baseline the observed "
      "share is compared against, stated as a constant because it is one.",
      """0.0455"""),

    m("Largest Provider Z-Score", F_NUM2, "08 Method & Evidence",
      "The most extreme provider, in standard errors. About 3.3 - which is roughly the maximum 500 draws from a "
      "normal distribution produce, so even the worst-looking provider is unremarkable.",
      """MAXX ( ProviderChance, ABS ( ProviderChance[ZScore] ) )"""),

    m("Provider Denial Rate", F_PCT2, "08 Method & Evidence",
      "A provider's own denial rate, from the chance table.",
      """AVERAGE ( ProviderChance[DenialRate] )"""),

    m("Provider Standard Error", "0.0000", "08 Method & Evidence",
      "The binomial standard error at that provider's claim count. The width of the band the rate is allowed to "
      "wander in before it means anything.",
      """AVERAGE ( ProviderChance[StandardError] )"""),

    m("Group Denial Rate", F_PCT2, "08 Method & Evidence",
      "The denial rate across all claims, as the chance table computed it. The line every provider is compared "
      "against.",
      """AVERAGE ( ProviderChance[GroupRate] )"""),

    m("Rate Scale Max", F_PCT, "08 Method & Evidence",
      "A constant 100%, so a gauge showing a rate is scaled 0 to 1 instead of to twice its own value - which is "
      "what Power BI does when no maximum is given, and which makes 83% look like the middle of the dial.",
      """1""", hidden=True),

    m("Net Collection Benchmark", F_PCT, "08 Method & Evidence",
      "95%. A BENCHMARK, not data: the net collection rate a healthy revenue cycle is normally held to. It is "
      "here so the gauge has something to be measured against, and it is labelled as an outside reference.",
      """0.95"""),

    m("Signal Verdict", F_TXT, "08 Method & Evidence",
      "The verdict for the dimension in context, as a text MEASURE. A matrix will render this where a text COLUMN "
      "may not, and a matrix is what lets the verdict table lose its total row - an average of Cramer's V across "
      "ten dimensions is not a number that means anything.",
      """SELECTEDVALUE ( DenialSignal[SignalVerdict] )"""),

    m("Data Quality Value", F_TXT, "08 Method & Evidence",
      "A Phase 1 finding, formatted in the units it belongs in - a count, a dollar amount or a percentage - "
      "because one column holds all three and a single format string would be wrong for two of them.",
      """VAR Amount = SUM ( DataQualityMetric[MetricValue] )
VAR Fmt = SELECTEDVALUE ( DataQualityMetric[ValueFormat] )
RETURN
    IF ( NOT ISBLANK ( Amount ), FORMAT ( Amount, Fmt ) )"""),

    m("Findings Recorded", F_INT, "08 Method & Evidence",
      "How many audit findings are recomputed from the source on every refresh rather than typed into a text box.",
      """COUNTROWS ( DataQualityMetric )"""),

    m("Calendar Days Added", F_INT, "08 Method & Evidence",
      "Days this build had to add because the supplied calendar stopped at the last service date.",
      """CALCULATE (
    COUNTROWS ( DimDate ),
    REMOVEFILTERS ( DimDate ),
    DimDate[InSuppliedCalendar] = FALSE ()
)"""),

    m("Claims Outside Supplied Calendar", F_INT, "08 Method & Evidence",
      "Claims whose ADJUDICATION date falls past the end of the supplied calendar. Every one of them would have "
      "joined to a blank date and disappeared from any measure sliced by adjudication month.",
      """CALCULATE (
    COUNTROWS ( FactClaim ),
    REMOVEFILTERS ( DimDate ),
    DimDate[InSuppliedCalendar] = FALSE (),
    USERELATIONSHIP ( FactClaim[ProcessedDateKey], DimDate[DateKey] )
)"""),

    # ======================================================= 09 formatting ====
    m("AR Bucket Colour", F_TXT, "09 Formatting",
      "Colour for the ageing chart: a cool-to-hot ramp from fresh to past saving. This is the one place in the "
      "report where colour carries an ORDER, because age is the one thing here that genuinely has one.",
      f"""VAR Bucket = SELECTEDVALUE ( DimARBucket[ARBucket] )
RETURN
    SWITCH (
        Bucket,
        "0-30", "{C_AGE_1}",
        "31-60", "{C_AGE_2}",
        "61-90", "{C_AGE_3}",
        "91-180", "{C_AGE_4}",
        "181-365", "{C_AGE_5}",
        "365+", "{C_AGE_6}",
        "{C_MUTED}"
    )"""),

    m("Movement Colour", F_TXT, "09 Formatting",
      "Colour for the AR bridge: money entering the receivable, money leaving as cash, and money leaving as "
      "anything else. Not a traffic light - the patient's share is neither good nor bad, it is simply somebody "
      "else's to pay.",
      f"""VAR MoveType = SELECTEDVALUE ( DimARMovementType[MovementType] )
RETURN
    SWITCH (
        MoveType,
        "Submitted", "{C_IN}",
        "Collected", "{C_IN}",
        "Patient responsibility", "{C_PATIENT}",
        "Denied", "{C_OUT}",
        "{C_MUTED}"
    )"""),

    m("Signal Colour", F_TXT, "09 Formatting",
      "Colour for the signal chart: a dimension that passed the stated test is drawn in the accent, and one "
      "that did not is drawn flat grey. The page should say 'there is nothing here' with its ink as well as "
      "its words.",
      f"""VAR Verdict = SELECTEDVALUE ( DenialSignal[SignalVerdict] )
RETURN
    IF ( Verdict = "Signal", "{C_SIGNAL}", "{C_MUTED}" )"""),

    m("Chance Band Colour", F_TXT, "09 Formatting",
      "Colour for the provider distribution: everything inside two standard errors is one muted tone, because "
      "the point of the chart is that almost all of it is inside.",
      f"""VAR Band = SELECTEDVALUE ( ProviderChance[ChanceBand] )
RETURN
    SWITCH (
        Band,
        "Within chance", "{C_MUTED}",
        "Above chance", "{C_AGE_6}",
        "Below chance", "{C_AGE_3}",
        "{C_MUTED}"
    )"""),

    m("Payer Colour", F_TXT, "09 Formatting",
      "Self Pay is drawn in the accent and the five insurers in one muted tone, because the finding is the "
      "split between them and not the differences among the five.",
      f"""VAR SelfPay = SELECTEDVALUE ( DimPayer[IsSelfPay] )
RETURN
    IF ( SelfPay = TRUE (), "{C_SIGNAL}", "{C_MUTED}" )"""),

    # ======================================================== 10 narrative ====
    m("AR Headline", F_TXT, "10 Narrative",
      "The one-line summary of the receivable, computed so it can never disagree with the chart beside it.",
      """VAR Amount = [Open AR]
VAR PastFilingShare = [AR Past Filing %]
RETURN
    IF (
        NOT ISBLANK ( Amount ),
        FORMAT ( Amount, "$#,0" ) & " outstanding, "
            & FORMAT ( PastFilingShare, "0%" ) & " of it past any filing limit"
    )"""),

    m("Denial Headline", F_TXT, "10 Narrative",
      "The denial rate with the one comparison that means anything attached to it.",
      """FORMAT ( [Denial Rate %], "0.0%" ) & " denied  |  Self Pay "
    & FORMAT ( [Self Pay Denial Rate %], "0.0%" ) & " vs insured "
    & FORMAT ( [Insured Denial Rate %], "0.0%" )"""),

    m("Collection Headline", F_TXT, "10 Narrative",
      "Net collection rate on resolved claims, with the all-claims figure beside it so neither can be quoted "
      "alone.",
      """VAR Resolved = FORMAT ( [Net Collection Rate %], "0.0%" )
VAR AllClaims = FORMAT ( [Net Collection Rate (All Claims) %], "0.0%" )
RETURN
    Resolved & " of resolved allowed collected  |  " & AllClaims & " of all allowed" """),

    m("Method Headline", F_TXT, "10 Narrative",
      "What the signal test found, stated from the data rather than typed.",
      """[Dimensions with Signal] & " of " & [Dimensions Tested]
    & " dimensions carry any signal at all - the strongest is "
    & [Strongest Signal Dimension] & " at V = " & FORMAT ( [Strongest Signal], "0.000" )"""),
]

CALC_GROUPS = [
    {
        "name": "Date Basis",
        "column": "Basis",
        "precedence": 10,
        "desc": "Which clock the calendar is measuring. A claim has four dates - when the care happened, when the "
                "claim was submitted, when the payer adjudicated it, and when it resolved into cash or a denial - "
                "and they answer different questions. Service date is the active relationship; the other three are "
                "switched on here with USERELATIONSHIP, so one fact table answers all four questions instead of "
                "four copies of it. Lower precedence than Time Comparison, so a comparison is applied to whichever "
                "basis is selected rather than the other way round.",
        "items": [
            ("Service date", "When the care was delivered. The default, and the right basis for clinical volume.",
             "SELECTEDMEASURE ()", None),
            ("Submission date", "When the claim reached the payer. The right basis for anything about the "
                                "receivable, because this is when the payer's clock starts.",
             """CALCULATE (
    SELECTEDMEASURE (),
    USERELATIONSHIP ( FactClaim[SubmittedDateKey], DimDate[DateKey] ),
    USERELATIONSHIP ( FactPayment[SubmittedDateKey], DimDate[DateKey] ),
    USERELATIONSHIP ( FactDenial[SubmittedDateKey], DimDate[DateKey] )
)""", None),
            ("Adjudication date", "When the payer decided. The right basis for denial workload, because that is "
                                  "the day the work lands on somebody's desk.",
             """CALCULATE (
    SELECTEDMEASURE (),
    USERELATIONSHIP ( FactClaim[ProcessedDateKey], DimDate[DateKey] )
)""", None),
            ("Resolution date", "When the claim turned into cash or a denial. The right basis for a cash "
                                "question. Pending claims have no resolution date and correctly fall out.",
             """CALCULATE (
    SELECTEDMEASURE (),
    USERELATIONSHIP ( FactClaim[ResolvedDateKey], DimDate[DateKey] )
)""", None),
        ],
    },
    {
        "name": "Time Comparison",
        "column": "Comparison",
        "precedence": 20,
        "desc": "Applies a time comparison to whatever measure a visual shows. Higher precedence than Date Basis, "
                "so the comparison wraps the basis: 'prior month on submission date' means the month before, "
                "measured on submission. A comparison is BLANK where there is nothing to compare against, rather "
                "than reporting the whole of a figure as growth.",
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
            ("Prior year", "The same measure twelve months earlier. Blank where the data does not reach back "
                           "that far, rather than comparing against nothing.",
             """VAR Target = EDATE ( MIN ( DimDate[Date] ), -12 )
VAR FirstDay = CALCULATE ( MIN ( DimDate[Date] ), REMOVEFILTERS ( DimDate ) )
RETURN
    IF (
        Target >= FirstDay,
        CALCULATE ( SELECTEDMEASURE (), DATEADD ( DimDate[Date], -12, MONTH ) )
    )""", None),
            ("Trailing 12 months", "The measure summed over the twelve months ending in the current one. A stock "
                                   "measure is unaffected by this, which is correct: a receivable has no "
                                   "twelve-month total.",
             """CALCULATE (
    SELECTEDMEASURE (),
    DATESINPERIOD ( DimDate[Date], MAX ( DimDate[Date] ), -12, MONTH )
)""", None),
        ],
    },
]

FIELD_PARAMETERS = [
    {
        "name": "Breakdown",
        "desc": "A field parameter: pick the attribute every 'by' chart on the page should group by. One slicer, "
                "ten questions, and no duplicated visuals sitting on top of one another.",
        "fields": [
            ("Payer", "DimPayer", "PayerName"),
            ("Payer type", "DimPayer", "PayerType"),
            ("Facility", "DimFacility", "FacilityName"),
            ("Facility type", "DimFacility", "FacilityType"),
            ("Specialty", "DimProvider", "Specialty"),
            ("State", "DimFacility", "State"),
            ("Denial reason", "DimDenialReason", "DenialReason"),
            ("Reason category", "DimDenialReason", "ReasonCategory"),
            ("Patient age band", "DimPatient", "AgeBand"),
            ("Chronic risk band", "DimPatient", "ChronicRiskBand"),
        ],
    },
]
