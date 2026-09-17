# -*- coding: utf-8 -*-
"""
Core measure layer, consumed by 02_generate_semantic_model.py.

Conventions (from project 1's lessons, Documentation/semantic_model.md):
  * Every measure lives in _Measures, with a folder, a format and a description.
  * Two lenses, never mixed silently:
        LEAD-SOURCE  FactLeadFunnel through the lead's own campaign  (CPL, funnel)
        ATTRIBUTED   FactAttributionCredit through touch campaigns    (credit, ROAS)
  * Attribution never sums across models - that would multiply revenue.
  * Role-playing dates use USERELATIONSHIP, and date-role COUNTS add
    NOT ISBLANK on the role column (project 1 D25).
  * Population shares use ALLSELECTED(<table>), never ALLSELECTED(<key column>).
  * No variable is named This, Visible or another reserved word.
  * Money is USD at planning FX rates (dbo.FxRate) - not market rates.

Phase 4 domain rules (PROJECT_STATE D33-D38):
  * ONE AS-OF DATE FOR EVERYTHING (D33). A milestone counts only if it happened on
    or before the as-of date: an opportunity once opened, a customer once revenue
    is booked. The source records outcomes seven weeks past the as-of date; they
    appear only in the explicitly named Post-Period measures.
  * ATTRIBUTED REVENUE IS DATED BY BOOKING DATE (D34), so any period's attributed
    revenue - under any model - equals the revenue booked in that period and ties
    to finance. Touch dating would place credit in Nov-Dec 2023, before any spend.
  * Statistical signal before ranking (D37): a difference is called out only when
    it is large relative to its own sampling noise.
"""

F_CTRL, F_MEDIA, F_FUNNEL = "01 Model Controls", "02 Media & Spend", "03 Funnel (Lead Cohort)"
F_REV, F_ATTR, F_COST = "04 Revenue & Pipeline", "05 Attribution", "06 Cost Efficiency"
F_JOURNEY, F_DQ, F_FMT = "07 Journey", "08 Data Quality", "09 Report Formatting"

# Signal colours: a DEAD ZONE, not a gradient. A gradient tints a cell at |z| = 1.5
# halfway to full colour and so implies a difference that chance explains; these
# leave everything inside |z| < 2 unshaded - the report's dark panel colour
# (#0A120A, the client's reference theme). Green above, red below; stronger at 3.
SIGNAL_COLOURS = """SWITCH (
        TRUE (),
        ISBLANK ( ZScore ), BLANK (),
        ZScore >= 3, "#4E9A1E",
        ZScore >= 2, "#2A5518",
        ZScore <= -3, "#8A2E24",
        ZScore <= -2, "#4A1F1A",
        "#0A120A"
    )\""""

USD0, USD2 = r"\$#,0", r"\$#,0.00"
N0, N2, PCT, RATIO = "#,0", "#,0.00", "0.0%", "0.00"
GROWTH = "+0.0%;-0.0%;0.0%"          # a change always shows its sign


def m(name, folder, fmt, desc, dax):
    return {"name": name, "folder": folder, "fmt": fmt, "desc": desc, "dax": dax}


CONFIG = lambda key: f"""CALCULATE (
        SELECTEDVALUE ( ModelConfig[ConfigValue] ),
        REMOVEFILTERS ( ModelConfig ),
        ModelConfig[ConfigKey] = "{key}"
    )"""

# Attributed revenue: the model in use, revenue booked by the as-of date, dated by
# booking date. One definition, reused wherever a model's credit is summed.
# NOT ISBLANK matters: credit rows of leads that never converted carry no booking
# date and a stored 0. Through the booking-date relationship they would land on
# the blank date member and draw a "(Blank)" category with value 0 on every
# date axis.
ATTRIBUTED_FILTERS = """NOT ISBLANK ( FactAttributionCredit[RevenueDate] ),
        FactAttributionCredit[IsRevenueAfterAsOf] = FALSE (),
        USERELATIONSHIP ( FactAttributionCredit[RevenueDate], DimDate[Date] )"""

MEASURES = [
    # ------------------------------------------------------------ controls ---
    m("As Of Date", F_CTRL, "yyyy-mm-dd",
      "Last day of recorded marketing activity, read from ModelConfig. Anchors every figure in the report: nothing "
      "dated later is counted, except in the Post-Period measures. Never TODAY().",
      f"""VAR ConfigText =
    {CONFIG("AsOfDate")}
RETURN
    IF (
        NOT ISBLANK ( ConfigText ),
        DATE ( VALUE ( LEFT ( ConfigText, 4 ) ), VALUE ( MID ( ConfigText, 6, 2 ) ), VALUE ( RIGHT ( ConfigText, 2 ) ) )
    )"""),
    m("Reporting Currency", F_CTRL, None,
      "Currency of every money measure. Spend is converted at planning rates, not market rates.",
      CONFIG("ReportingCurrency").replace("\n    ", "\n")),
    m("Attribution Model Key", F_CTRL, "0",
      "Model in effect: the one selected, else the configured default. Deliberately NOT a sum when several models "
      "are in scope - credit from different models describes the same revenue and must never be added.",
      f"""VAR DefaultName =
    {CONFIG("DefaultAttributionModel")}
VAR DefaultKey =
    CALCULATE (
        SELECTEDVALUE ( DimAttributionModel[ModelKey] ),
        REMOVEFILTERS ( DimAttributionModel ),
        DimAttributionModel[ModelName] = DefaultName
    )
RETURN
    IF ( HASONEVALUE ( DimAttributionModel[ModelKey] ), VALUES ( DimAttributionModel[ModelKey] ), DefaultKey )"""),
    m("Attribution Model In Use", F_CTRL, None,
      "Name of the attribution model the attributed measures are using - shown on the report so a reader always knows.",
      """VAR KeyInUse = [Attribution Model Key]
RETURN
    CALCULATE (
        SELECTEDVALUE ( DimAttributionModel[ModelName] ),
        REMOVEFILTERS ( DimAttributionModel ),
        DimAttributionModel[ModelKey] = KeyInUse
    )"""),
    m("Report Context", F_CTRL, None,
      "One line stating the basis of every figure on the page: as-of date, attribution model, currency basis.",
      """"Data as of " & FORMAT ( [As Of Date], "d mmm yyyy" ) & "  |  Attribution: " & [Attribution Model In Use]
    & "  |  USD at planning FX\""""),
    m("Conversion Window Days", F_CTRL, "0",
      "Longest observed time from lead creation to booked revenue (58 days). A lead cohort younger than this has not "
      "finished converting, so conversion trends leave it out.",
      """CALCULATE (
    MAXX (
        FILTER ( FactLeadFunnel, NOT ISBLANK ( FactLeadFunnel[RevenueDate] ) ),
        FactLeadFunnel[DaysLeadToOpportunity] + FactLeadFunnel[DaysOpportunityToRevenue]
    ),
    REMOVEFILTERS ()
)"""),

    # ------------------------------------------------------- media & spend ---
    m("Spend USD", F_MEDIA, USD0,
      "Channel cost in USD at planning FX rates, by spend date. Includes the cost recorded against owned, organic "
      "and referral channels, so it is labelled channel cost rather than ad spend.",
      "SUM ( FactAdSpend[SpendUSD] )"),
    m("Paid Media Spend USD", F_MEDIA, USD0, "Spend on Paid Search, Paid Social and Paid Display only.",
      "CALCULATE ( [Spend USD], DimCampaign[IsPaidMedia] = TRUE () )"),
    m("Impressions", F_MEDIA, N0, "Ad impressions.", "SUM ( FactAdSpend[Impressions] )"),
    m("Clicks", F_MEDIA, N0, "Ad clicks.", "SUM ( FactAdSpend[Clicks] )"),
    m("CTR", F_MEDIA, "0.00%", "Click-through rate: clicks per impression.", "DIVIDE ( [Clicks], [Impressions] )"),
    m("CPC USD", F_MEDIA, USD2, "Cost per click.", "DIVIDE ( [Spend USD], [Clicks] )"),
    m("CPM USD", F_MEDIA, USD2, "Cost per thousand impressions.", "DIVIDE ( [Spend USD], [Impressions] ) * 1000"),
    m("Paid CTR", F_MEDIA, "0.00%",
      "Click-through rate on paid media only. Impressions and clicks have no media meaning for owned, organic and "
      "referral channels. Near-identical on every channel in this synthetic data (4.21-4.25%), so it is shown as a "
      "total and never ranked by channel.",
      "CALCULATE ( [CTR], DimCampaign[IsPaidMedia] = TRUE () )"),
    m("Paid CPC USD", F_MEDIA, USD2, "Cost per click on paid media only (see Paid CTR).",
      "CALCULATE ( [CPC USD], DimCampaign[IsPaidMedia] = TRUE () )"),
    m("Paid CPM USD", F_MEDIA, USD2, "Cost per thousand impressions on paid media only (see Paid CTR).",
      "CALCULATE ( [CPM USD], DimCampaign[IsPaidMedia] = TRUE () )"),
    m("Spend Share %", F_MEDIA, PCT,
      "Share of the selected spend. Denominator lifts every campaign filter set by the visual but keeps slicers.",
      "DIVIDE ( [Spend USD], CALCULATE ( [Spend USD], ALLSELECTED ( DimCampaign ) ) )"),
    m("Click-to-Lead %", F_MEDIA, "0.000%",
      "Leads per ad click. 0.02% here against the 2-5% typical of B2B landing pages: the ad data and the CRM "
      "extract are on different scales, so absolute ROAS and CAC are not meaningful. Media efficiency (CTR, CPC, "
      "CPM) and funnel conversion are unaffected.",
      "DIVIDE ( [Leads], [Clicks] )"),

    # ---------------------------------------------------- funnel (cohort) ---
    m("Leads", F_FUNNEL, N0, "Leads created, by creation date and lead-source campaign.",
      "COUNTROWS ( FactLeadFunnel )"),
    m("MQLs", F_FUNNEL, N0, "Leads that reached MQL or beyond (derived stage).",
      "CALCULATE ( [Leads], FactLeadFunnel[ReachedMQL] = TRUE () )"),
    m("SQLs", F_FUNNEL, N0, "Leads that reached SQL or beyond (derived stage).",
      "CALCULATE ( [Leads], FactLeadFunnel[ReachedSQL] = TRUE () )"),
    m("Opportunities", F_FUNNEL, N0, "Leads whose opportunity was opened by the as-of date.",
      "CALCULATE ( [Leads], FactLeadFunnel[IsOpportunityByAsOf] = TRUE () )"),
    m("Customers", F_FUNNEL, N0,
      "Leads that became customers by the as-of date - evidenced by revenue booked by then, not by the stale CRM label.",
      "CALCULATE ( [Leads], FactLeadFunnel[IsWonByAsOf] = TRUE () )"),
    m("Lead to MQL %", F_FUNNEL, PCT, "Share of leads reaching MQL.", "DIVIDE ( [MQLs], [Leads] )"),
    m("MQL to SQL %", F_FUNNEL, PCT, "Share of MQLs reaching SQL.", "DIVIDE ( [SQLs], [MQLs] )"),
    m("SQL to Opportunity %", F_FUNNEL, PCT, "Share of SQLs with an opportunity by the as-of date.",
      "DIVIDE ( [Opportunities], [SQLs] )"),
    m("Opportunity to Customer %", F_FUNNEL, PCT,
      "Share of opportunities won by the as-of date. Still-open opportunities stay in the denominator - see Win Rate "
      "for closed deals only.",
      "DIVIDE ( [Customers], [Opportunities] )"),
    m("Lead to Customer %", F_FUNNEL, PCT, "End-to-end conversion by the as-of date.", "DIVIDE ( [Customers], [Leads] )"),
    m("Win Rate %", F_FUNNEL, PCT,
      "Won share of opportunities CLOSED by the as-of date. Open ones - including deals won later - are excluded, "
      "not counted as lost.",
      """DIVIDE (
    CALCULATE ( [Leads], FactLeadFunnel[OpportunityStatusAsOf] = "Closed Won" ),
    CALCULATE ( [Leads], FactLeadFunnel[OpportunityStatusAsOf] IN { "Closed Won", "Closed Lost" } )
)"""),
    m("Cohort Revenue USD", F_FUNNEL, USD0,
      "Revenue booked by the as-of date by the leads created in the period - the lead-cohort view used for payback.",
      "CALCULATE ( SUM ( FactLeadFunnel[RevenueUSD] ), FactLeadFunnel[IsWonByAsOf] = TRUE () )"),
    m("Funnel Stage Leads", F_FUNNEL, N0,
      "Leads that reached AT LEAST the funnel stage in context by the as-of date. Blank without a single stage - a "
      "funnel total has no meaning, so it is deliberately not a sum of stages.",
      """VAR StageRankInScope = SELECTEDVALUE ( DimFunnelStage[StageRank] )
RETURN
    IF (
        NOT ISBLANK ( StageRankInScope ),
        CALCULATE ( [Leads], FactLeadFunnel[StageRankAsOf] >= StageRankInScope )
    )"""),
    m("Conversion From Previous Stage %", F_FUNNEL, PCT,
      "Share of the previous funnel stage that reached this one by the as-of date. Blank for the first stage.",
      """VAR StageRankInScope = SELECTEDVALUE ( DimFunnelStage[StageRank] )
VAR StageLeads = CALCULATE ( [Leads], FactLeadFunnel[StageRankAsOf] >= StageRankInScope )
VAR PriorStageLeads = CALCULATE ( [Leads], FactLeadFunnel[StageRankAsOf] >= StageRankInScope - 1 )
RETURN
    IF ( StageRankInScope > 1, DIVIDE ( StageLeads, PriorStageLeads ) )"""),
    m("Leads PY", F_FUNNEL, N0,
      "Leads in the same period one year earlier. Blank for periods after the as-of date: they have no actuals to "
      "compare against.",
      """VAR PeriodStart = MIN ( DimDate[Date] )
RETURN
    IF ( PeriodStart <= [As Of Date], CALCULATE ( [Leads], SAMEPERIODLASTYEAR ( DimDate[Date] ) ) )"""),
    m("Lead to Customer % (Mature Cohorts)", F_FUNNEL, PCT,
      "Lead-to-customer conversion for cohorts old enough to have finished converting (created at least the "
      "Conversion Window before the as-of date). Blank for younger cohorts and for any period reaching past that "
      "point: the August 2026 cohort shows 2.1% by the as-of date against 13.5% eventually, which a trend would "
      "misread as a collapse.",
      """VAR LastCohortDay = MAX ( DimDate[Date] )
VAR MatureUntil = [As Of Date] - [Conversion Window Days]
RETURN
    IF ( LastCohortDay <= MatureUntil, [Lead to Customer %] )"""),
    m("Lead to Customer z vs Portfolio", F_FUNNEL, "0.0",
      "How many standard errors this cell's lead-to-customer rate sits from the rate of everything selected "
      "(binomial). Beyond +/-2 is unlikely to be chance; inside it, the difference is noise. Drives the heatmap colour.",
      """VAR Rate = [Lead to Customer %]
VAR LeadCount = [Leads]
VAR PortfolioRate =
    CALCULATE ( [Lead to Customer %], ALLSELECTED ( FactLeadFunnel ), ALLSELECTED ( DimCampaign ) )
RETURN
    IF (
        LeadCount > 0,
        DIVIDE ( Rate - PortfolioRate, SQRT ( DIVIDE ( PortfolioRate * ( 1 - PortfolioRate ), LeadCount ) ) )
    )"""),

    # --------------------------------------------------- revenue & pipeline ---
    m("Revenue USD", F_REV, USD0,
      "Revenue booked on or before the as-of date, by booking date. The headline revenue figure.",
      """CALCULATE (
    SUM ( FactLeadFunnel[RevenueUSD] ),
    USERELATIONSHIP ( FactLeadFunnel[RevenueDate], DimDate[Date] ),
    FactLeadFunnel[IsRevenueAfterAsOf] = FALSE ()
)"""),
    m("Post-Period Revenue USD", F_REV, USD0,
      "Revenue dated after the as-of date (209 bookings in the source). Shown only as a data-quality figure, never in "
      "headline numbers.",
      """CALCULATE (
    SUM ( FactLeadFunnel[RevenueUSD] ),
    USERELATIONSHIP ( FactLeadFunnel[RevenueDate], DimDate[Date] ),
    FactLeadFunnel[IsRevenueAfterAsOf] = TRUE ()
)"""),
    m("Deals Won", F_REV, N0, "Revenue bookings by booking date, up to the as-of date.",
      """CALCULATE (
    COUNTROWS ( FactLeadFunnel ),
    USERELATIONSHIP ( FactLeadFunnel[RevenueDate], DimDate[Date] ),
    NOT ISBLANK ( FactLeadFunnel[RevenueDate] ),
    FactLeadFunnel[IsRevenueAfterAsOf] = FALSE ()
)"""),
    m("Average Deal Size USD", F_REV, USD0, "Revenue per deal won.", "DIVIDE ( [Revenue USD], [Deals Won] )"),
    m("Opportunities Created", F_REV, N0, "Opportunities by their own creation date, up to the as-of date.",
      """CALCULATE (
    COUNTROWS ( FactLeadFunnel ),
    USERELATIONSHIP ( FactLeadFunnel[OpportunityCreatedDate], DimDate[Date] ),
    NOT ISBLANK ( FactLeadFunnel[OpportunityCreatedDate] ),
    FactLeadFunnel[IsOpportunityAfterAsOf] = FALSE ()
)"""),
    m("Open Pipeline USD", F_REV, USD0,
      "Value of opportunities open on the as-of date, including those won later.",
      """CALCULATE ( SUM ( FactLeadFunnel[OpportunityValue] ), FactLeadFunnel[OpportunityStatusAsOf] = "Open" )"""),
    m("Avg Days Lead to Opportunity", F_REV, "0.0", "Mean days from lead creation to an opportunity opened by the as-of date.",
      "CALCULATE ( AVERAGE ( FactLeadFunnel[DaysLeadToOpportunity] ), FactLeadFunnel[IsOpportunityByAsOf] = TRUE () )"),
    m("Avg Days Opportunity to Revenue", F_REV, "0.0", "Mean days from opportunity to revenue booked by the as-of date.",
      "CALCULATE ( AVERAGE ( FactLeadFunnel[DaysOpportunityToRevenue] ), FactLeadFunnel[IsWonByAsOf] = TRUE () )"),
    m("Revenue PY USD", F_REV, USD0,
      "Revenue booked in the same period one year earlier. Blank for periods after the as-of date, so a trend ends at "
      "the last actual month instead of comparing an empty future month with last year.",
      """VAR PeriodStart = MIN ( DimDate[Date] )
RETURN
    IF ( PeriodStart <= [As Of Date], CALCULATE ( [Revenue USD], SAMEPERIODLASTYEAR ( DimDate[Date] ) ) )"""),
    m("Revenue YoY %", F_REV, GROWTH,
      "Change in booked revenue against the same period last year. Month-level values swing widely (after the "
      "January 2024 ramp-up month, monthly revenue ranges $0.77M-$1.26M), so the headline comparison is "
      "year-to-date - see Revenue YTD vs PY %.",
      "DIVIDE ( [Revenue USD] - [Revenue PY USD], [Revenue PY USD] )"),
    m("Revenue YTD USD", F_REV, USD0,
      "Revenue booked from 1 January of the as-of year to the as-of date. Fixed to the as-of date: it ignores date "
      "slicers by design.",
      """VAR AsOf = [As Of Date]
RETURN
    CALCULATE (
        [Revenue USD],
        REMOVEFILTERS ( DimDate ),
        DATESBETWEEN ( DimDate[Date], DATE ( YEAR ( AsOf ), 1, 1 ), AsOf )
    )"""),
    m("Revenue PYTD USD", F_REV, USD0,
      "Revenue booked over the same days one year earlier (1 January to the as-of date minus one year).",
      """VAR AsOf = [As Of Date]
RETURN
    CALCULATE (
        [Revenue USD],
        REMOVEFILTERS ( DimDate ),
        DATESBETWEEN ( DimDate[Date], DATE ( YEAR ( AsOf ) - 1, 1, 1 ), EDATE ( AsOf, -12 ) )
    )"""),
    m("Revenue YTD vs PY %", F_REV, GROWTH,
      "Like-for-like year-to-date growth: the same calendar days this year and last year.",
      "DIVIDE ( [Revenue YTD USD] - [Revenue PYTD USD], [Revenue PYTD USD] )"),
    m("Revenue Cumulative YTD USD", F_REV, USD0,
      "Running year-to-date revenue for each period of the as-of year, up to the as-of date; blank for other years. "
      "The KPI visual's indicator.",
      """VAR AsOf = [As Of Date]
VAR PeriodStart = MIN ( DimDate[Date] )
VAR PeriodEnd = MIN ( MAX ( DimDate[Date] ), AsOf )
RETURN
    IF (
        YEAR ( PeriodStart ) = YEAR ( AsOf ) && PeriodStart <= AsOf,
        CALCULATE (
            [Revenue USD],
            REMOVEFILTERS ( DimDate ),
            DATESBETWEEN ( DimDate[Date], DATE ( YEAR ( AsOf ), 1, 1 ), PeriodEnd )
        )
    )"""),
    m("Revenue Cumulative PYTD USD", F_REV, USD0,
      "Running year-to-date revenue one year earlier, over the same days as Revenue Cumulative YTD USD. The KPI "
      "visual's goal.",
      """VAR AsOf = [As Of Date]
VAR PeriodStart = MIN ( DimDate[Date] )
VAR PeriodEnd = MIN ( MAX ( DimDate[Date] ), AsOf )
RETURN
    IF (
        YEAR ( PeriodStart ) = YEAR ( AsOf ) && PeriodStart <= AsOf,
        CALCULATE (
            [Revenue USD],
            REMOVEFILTERS ( DimDate ),
            DATESBETWEEN ( DimDate[Date], DATE ( YEAR ( AsOf ) - 1, 1, 1 ), EDATE ( PeriodEnd, -12 ) )
        )
    )"""),

    # ----------------------------------------------------------- attribution ---
    m("Attributed Revenue USD", F_ATTR, USD0,
      "Revenue credited to touches under the model in use, for revenue booked by the as-of date, dated by BOOKING "
      "date - so any period's attributed revenue equals the revenue booked in it, under every model.",
      f"""VAR KeyInUse = [Attribution Model Key]
RETURN
    CALCULATE (
        SUM ( FactAttributionCredit[AttributedRevenueUSD] ),
        FactAttributionCredit[ModelKey] = KeyInUse,
        {ATTRIBUTED_FILTERS}
    )"""),
    m("Attributed Leads", F_ATTR, N2,
      "Fractional lead credit under the model in use, dated by TOUCH date: a lead with four touches spreads its one "
      "lead across them. Not used for revenue.",
      """VAR KeyInUse = [Attribution Model Key]
RETURN
    CALCULATE ( SUM ( FactAttributionCredit[CreditWeight] ), FactAttributionCredit[ModelKey] = KeyInUse )"""),
    m("Attributed Customers", F_ATTR, N2,
      "Fractional customer credit under the model in use, for customers won by the as-of date, by booking date.",
      f"""VAR KeyInUse = [Attribution Model Key]
RETURN
    CALCULATE (
        SUM ( FactAttributionCredit[CreditWeight] ),
        FactAttributionCredit[ModelKey] = KeyInUse,
        {ATTRIBUTED_FILTERS}
    )"""),
    m("Last Touch Revenue USD", F_ATTR, USD0, "Attributed revenue under Last Touch - the baseline for credit shift.",
      f"""CALCULATE (
    SUM ( FactAttributionCredit[AttributedRevenueUSD] ),
    FactAttributionCredit[ModelKey] = 2,
    {ATTRIBUTED_FILTERS.replace(chr(10) + "        ", chr(10) + "    ")}
)"""),
    m("Credit Shift vs Last Touch USD", F_ATTR, USD0,
      "Revenue the model in use moves onto (+) or away from (-) this channel or campaign compared with Last Touch.",
      "[Attributed Revenue USD] - [Last Touch Revenue USD]"),
    m("Attributed Revenue Share %", F_ATTR, PCT, "Share of selected attributed revenue.",
      "DIVIDE ( [Attributed Revenue USD], CALCULATE ( [Attributed Revenue USD], ALLSELECTED ( DimCampaign ) ) )"),
    m("ROAS", F_ATTR, RATIO,
      "Attributed revenue per USD of channel cost. Around 0.03 on this synthetic data because the ad and CRM "
      "extracts are on different scales (Click-to-Lead %): compare channels relatively, never against benchmarks.",
      "DIVIDE ( [Attributed Revenue USD], [Spend USD] )"),
    m("Revenue-to-Spend Index", F_ATTR, RATIO,
      "Attributed revenue share divided by spend share. Above 1: earns more than its share of the budget. "
      "Scale-free, so it stays meaningful however spend and revenue compare in absolute terms.",
      "DIVIDE ( [Attributed Revenue Share %], [Spend Share %] )"),
    m("Attribution Sensitivity %", F_ATTR, PCT,
      "How much the attribution model matters here: the spread of attributed revenue across the five models, as a "
      "share of their average. Zero at the grand total (every model conserves revenue); large for many campaigns - "
      "that is where the model choice changes budget decisions.",
      """VAR ByModel =
    ADDCOLUMNS (
        ALL ( DimAttributionModel[ModelKey] ),
        "@Rev",
            VAR ModelKeyRow = DimAttributionModel[ModelKey]
            RETURN
                CALCULATE (
                    SUM ( FactAttributionCredit[AttributedRevenueUSD] ),
                    FactAttributionCredit[ModelKey] = ModelKeyRow,
                    NOT ISBLANK ( FactAttributionCredit[RevenueDate] ),
                    FactAttributionCredit[IsRevenueAfterAsOf] = FALSE (),
                    USERELATIONSHIP ( FactAttributionCredit[RevenueDate], DimDate[Date] )
                )
    )
VAR Spread = MAXX ( ByModel, [@Rev] ) - MINX ( ByModel, [@Rev] )
RETURN
    DIVIDE ( Spread, AVERAGEX ( ByModel, [@Rev] ) )"""),
    m("Campaign Index z", F_ATTR, "0.0",
      "Signal test for one campaign's Revenue-to-Spend Index: how many standard errors its attributed revenue sits "
      "from what its spend share would earn. Variance is taken under that fair-share hypothesis (compound Poisson "
      "with the model's campaign dispersion, SQL 07), which stays honest with heavily skewed deal sizes. Blank unless "
      "exactly one campaign is in scope.",
      """VAR KeyInUse = [Attribution Model Key]
VAR CampaignRevenue = [Attributed Revenue USD]
VAR ExpectedRevenue =
    [Spend Share %] * CALCULATE ( [Attributed Revenue USD], ALLSELECTED ( DimCampaign ) )
VAR Dispersion =
    CALCULATE (
        SELECTEDVALUE ( DimAttributionModel[CampaignDispersionUSD] ),
        REMOVEFILTERS ( DimAttributionModel ),
        DimAttributionModel[ModelKey] = KeyInUse
    )
RETURN
    IF (
        HASONEVALUE ( DimCampaign[CampaignID] ) && ExpectedRevenue > 0,
        DIVIDE ( CampaignRevenue - ExpectedRevenue, SQRT ( ExpectedRevenue * Dispersion ) )
    )"""),
    m("Campaign Index Signal", F_ATTR, None,
      "Reading of Campaign Index z. |z| >= 3 is a clear signal (about 1 of 300 campaigns would cross it by chance); "
      "2-3 is possible (about 14 of 300 would by chance); anything smaller is noise, however high or low the index.",
      """VAR ZScore = [Campaign Index z]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( ZScore ), BLANK (),
        ZScore >= 3, "Clearly above",
        ZScore >= 2, "Possibly above",
        ZScore <= -3, "Clearly below",
        ZScore <= -2, "Possibly below",
        "Within noise"
    )"""),

    # ------------------------------------------------------- cost efficiency ---
    m("CPL USD", F_COST, USD2,
      "Cost per lead: spend over leads created (lead-source lens). About $21.8K on this data - read relatively "
      "(Click-to-Lead %).",
      "DIVIDE ( [Spend USD], [Leads] )"),
    m("Cost per MQL USD", F_COST, USD2, "Spend per MQL.", "DIVIDE ( [Spend USD], [MQLs] )"),
    m("Cost per SQL USD", F_COST, USD2, "Spend per SQL.", "DIVIDE ( [Spend USD], [SQLs] )"),
    m("Cost per Opportunity USD", F_COST, USD2, "Spend per opportunity opened by the as-of date.",
      "DIVIDE ( [Spend USD], [Opportunities] )"),
    m("CPA USD", F_COST, USD0,
      "Cost per acquisition: spend per ATTRIBUTED customer, so a channel is charged only for the customers credited "
      "to it. Changes with the attribution model.",
      "DIVIDE ( [Spend USD], [Attributed Customers] )"),
    m("CAC USD", F_COST, USD0,
      "Blended customer acquisition cost: all channel cost per customer won by the as-of date. Independent of "
      "attribution.",
      "DIVIDE ( [Spend USD], [Customers] )"),

    # --------------------------------------------------------------- journey ---
    m("Touchpoints", F_JOURNEY, N0, "Marketing touches.", "COUNTROWS ( FactTouchpoint )"),
    m("Avg Touches per Journey", F_JOURNEY, "0.00", "Mean touches before a lead is created.",
      "AVERAGE ( FactLeadFunnel[TouchCount] )"),
    m("Multi-Channel Journey %", F_JOURNEY, PCT, "Share of leads whose journey spans two or more channels.",
      "DIVIDE ( CALCULATE ( [Leads], FactLeadFunnel[DistinctChannels] > 1 ), [Leads] )"),
    m("Avg Days First Touch to Lead", F_JOURNEY, "0.0", "Mean days from a lead's first touch to its creation.",
      """AVERAGEX (
    VALUES ( FactTouchpoint[LeadID] ),
    CALCULATE ( MAX ( FactTouchpoint[DaysBeforeLead] ) )
)"""),

    # ---------------------------------------------------------- data quality ---
    m("Campaign Aliases", F_DQ, N0, "Raw campaign aliases supplied.", "COUNTROWS ( CampaignAliasResolution )"),
    m("Aliases Resolved", F_DQ, N0, "Aliases the Power Query rules resolved to the correct campaign.",
      """CALCULATE ( COUNTROWS ( CampaignAliasResolution ), CampaignAliasResolution[ResolutionStatus] = "Resolved" )"""),
    m("Alias Resolution %", F_DQ, PCT, "Share of aliases resolved correctly.",
      "DIVIDE ( [Aliases Resolved], [Campaign Aliases] )"),
    m("Alias Mismatches", F_DQ, N0, "Aliases resolved to the WRONG campaign. Must be zero.",
      """CALCULATE ( COUNTROWS ( CampaignAliasResolution ), CampaignAliasResolution[ResolutionStatus] = "Mismatch" ) + 0"""),
    m("Stale Stage Labels", F_DQ, N0, "Leads whose CRM stage label disagrees with the evidence.",
      "CALCULATE ( [Leads], FactLeadFunnel[IsStageLabelStale] = TRUE () )"),
    m("Journeys With Contradicting Sequence", F_DQ, N0,
      "Leads whose supplied touch sequence contradicts touch dates.",
      "CALCULATE ( [Leads], FactLeadFunnel[SequenceContradictsDate] = TRUE () )"),
    m("Spend Lines Before Campaign Start", F_DQ, N0, "Spend lines dated before their campaign's StartDate.",
      "CALCULATE ( COUNTROWS ( FactAdSpend ), FactAdSpend[IsBeforeCampaignStart] = TRUE () )"),
    m("Alias Resolution Target %", F_DQ, PCT,
      "Service level for campaign-name cleansing: every alias must resolve. The gauge target.", "1"),
    m("Post-Period Opportunities", F_DQ, N0,
      "Opportunities the source dates after the as-of date. Excluded from every funnel figure.",
      "CALCULATE ( COUNTROWS ( FactLeadFunnel ), FactLeadFunnel[IsOpportunityAfterAsOf] = TRUE () )"),
    m("Post-Period Bookings", F_DQ, N0,
      "Revenue bookings the source dates after the as-of date. Excluded from every revenue and customer figure.",
      "CALCULATE ( COUNTROWS ( FactLeadFunnel ), FactLeadFunnel[IsRevenueAfterAsOf] = TRUE () )"),
    m("Clicks per Lead", F_DQ, N0,
      "Ad clicks recorded per CRM lead. Typical B2B landing pages convert 2-5% of clicks (20-50 clicks per lead); "
      "about 5,100 here shows the ad and CRM extracts are on different scales.",
      "DIVIDE ( [Clicks], [Leads] )"),
    m("Spend to Revenue Ratio", F_DQ, "0.0",
      "Channel cost per dollar of revenue booked. Far above 1 on this data for the same scale reason - the figure "
      "that makes absolute ROAS, CPL and CAC unusable against benchmarks.",
      "DIVIDE ( [Spend USD], [Revenue USD] )"),

    # ------------------------------------------------------ report formatting ---
    m("Heatmap Signal Colour", F_FMT, None,
      "Background colour of a funnel-heatmap cell: unshaded (the panel colour) unless its lead-to-customer rate "
      "differs from the portfolio by more than chance (|z| >= 2 muted, >= 3 strong; green above, red below).",
      "VAR ZScore = [Lead to Customer z vs Portfolio]\nRETURN\n    " + SIGNAL_COLOURS.rstrip('"')),
    m("Campaign Signal Colour", F_FMT, None,
      "Background colour of a campaign's Revenue-to-Spend Index: unshaded (the panel colour) unless Campaign Index z "
      "says the campaign differs from fair share by more than chance (|z| >= 2 muted, >= 3 strong; green above, red "
      "below).",
      "VAR ZScore = [Campaign Index z]\nRETURN\n    " + SIGNAL_COLOURS.rstrip('"')),
]
