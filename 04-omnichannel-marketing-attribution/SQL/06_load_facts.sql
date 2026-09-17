/*=============================================================================
  06_load_facts.sql

  Types the five source facts into dbo and derives the columns every later
  layer relies on. Each derivation below answers a measured data finding
  (Documentation/data_quality_report.md):

  JOURNEY ORDER. The supplied TouchSequence contradicts TouchDate for 71% of
    leads, and touch types sit at ~20% in every position, so the sequence
    number carries no behavioural signal. JourneyPosition orders touches by
    TouchDate, breaking same-day ties by TouchSequence. Time-decay attribution
    is defined in days, so it needs a real timeline; a counter that disagrees
    with the calendar cannot be what "first" means. The source value is kept
    as SourceTouchSequence for audit.

  FUNNEL STAGE. 2,428 leads with booked revenue are still labelled
    "Opportunity". DerivedStage takes the evidence: revenue -> Customer,
    an opportunity -> Opportunity, otherwise the CRM label (Lead / MQL / SQL,
    which only the CRM can know). The label is kept as LatestStageLabel.

  CURRENCY. Spend is converted at the planning rate in force on the spend date.

  AS-OF. Opportunity and revenue rows dated after the as-of date are loaded
    and flagged IsAfterAsOf, never dropped, so they stay auditable.
=============================================================================*/
USE MarketingAttributionBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');

---------------------------------------------------- conversion pre-check ---
-- Fail loudly on any value that will not type, rather than letting a NULL or
-- a truncation slip into dbo.
DECLARE @Bad INT =
      (SELECT COUNT(*) FROM stg.fact_ad_spend WHERE TRY_CONVERT(DATE, [Date], 23) IS NULL
            OR TRY_CONVERT(INT, Impressions) IS NULL OR TRY_CONVERT(INT, Clicks) IS NULL
            OR TRY_CONVERT(DECIMAL(18,2), SpendLocal) IS NULL)
    + (SELECT COUNT(*) FROM stg.fact_leads WHERE TRY_CONVERT(DATE, CreatedDate, 23) IS NULL
            OR TRY_CONVERT(DECIMAL(18,2), EstimatedValue) IS NULL)
    + (SELECT COUNT(*) FROM stg.fact_touchpoints WHERE TRY_CONVERT(DATE, TouchDate, 23) IS NULL
            OR TRY_CONVERT(TINYINT, TouchSequence) IS NULL)
    + (SELECT COUNT(*) FROM stg.fact_opportunities WHERE TRY_CONVERT(DATE, CreatedDate, 23) IS NULL
            OR TRY_CONVERT(DECIMAL(18,2), OpportunityValue) IS NULL)
    + (SELECT COUNT(*) FROM stg.fact_revenue WHERE TRY_CONVERT(DATE, RevenueDate, 23) IS NULL
            OR TRY_CONVERT(DECIMAL(18,2), RevenueAmount) IS NULL);
IF @Bad > 0 THROW 50010, N'Fact values failed type conversion - inspect stg before loading.', 1;

--------------------------------------------------------------- FactAdSpend ---
INSERT dbo.FactAdSpend (AdRowID, [Date], CampaignID, ChannelID, Impressions, Clicks,
                        SpendLocal, CurrencyCode, FxRateToUSD, SpendUSD, IsBeforeCampaignStart)
SELECT a.AdRowID, x.d, a.CampaignID, a.ChannelID,
       CONVERT(INT, a.Impressions), CONVERT(INT, a.Clicks),
       x.spend, a.Currency, fx.RateToUSD,
       ROUND(x.spend * fx.RateToUSD, 2),
       CASE WHEN x.d < c.StartDate THEN 1 ELSE 0 END
FROM stg.fact_ad_spend a
CROSS APPLY (SELECT CONVERT(DATE, a.[Date], 23) AS d, CONVERT(DECIMAL(18,2), a.SpendLocal) AS spend) x
JOIN dbo.DimCampaign c ON c.CampaignID = a.CampaignID
JOIN dbo.FxRate fx ON fx.CurrencyCode = a.Currency
                  AND fx.RateType = N'Planning'
                  AND x.d BETWEEN fx.EffectiveFrom AND fx.EffectiveTo;

IF (SELECT COUNT(*) FROM dbo.FactAdSpend) <> (SELECT COUNT(*) FROM stg.fact_ad_spend)
    THROW 50011, N'Ad spend rows lost in load - a currency or date had no FX rate.', 1;

------------------------------------------ journey positions (staged first) ---
-- Leads must exist before touchpoints (foreign key), yet lead flags depend on
-- the touch journey, so positions are computed once into a temp table.
DROP TABLE IF EXISTS #tp;
SELECT t.TouchpointID, t.LeadID, CONVERT(DATE, t.TouchDate, 23) AS TouchDate,
       t.CampaignID, t.ChannelID, t.TouchType,
       CONVERT(TINYINT, t.TouchSequence) AS SourceTouchSequence,
       CONVERT(TINYINT, ROW_NUMBER() OVER (PARTITION BY t.LeadID
                        ORDER BY CONVERT(DATE, t.TouchDate, 23), CONVERT(TINYINT, t.TouchSequence))) AS JourneyPosition,
       CONVERT(TINYINT, COUNT(*) OVER (PARTITION BY t.LeadID)) AS JourneyLength
INTO #tp
FROM stg.fact_touchpoints t;

DROP TABLE IF EXISTS #journey;
SELECT LeadID,
       COUNT(*)                   AS TouchCount,
       COUNT(DISTINCT ChannelID)  AS DistinctChannels,
       MAX(CASE WHEN JourneyPosition <> SourceTouchSequence THEN 1 ELSE 0 END) AS SequenceContradictsDate
INTO #journey
FROM #tp GROUP BY LeadID;

------------------------------------------------------------------ FactLead ---
INSERT dbo.FactLead (LeadID, CreatedDate, CampaignID, ChannelID, Segment, Country, EstimatedValue,
                     LatestStageLabel, DerivedStage, StageRank, ReachedMQL, ReachedSQL,
                     HasOpportunity, IsWon, IsStageLabelStale, TouchCount, DistinctChannels,
                     SequenceContradictsDate)
SELECT l.LeadID, CONVERT(DATE, l.CreatedDate, 23), l.CampaignID, l.ChannelID, l.Segment, l.Country,
       CONVERT(DECIMAL(18,2), l.EstimatedValue),
       l.LatestStage,
       CASE s.DerivedRank WHEN 1 THEN N'Lead' WHEN 2 THEN N'MQL' WHEN 3 THEN N'SQL'
                          WHEN 4 THEN N'Opportunity' ELSE N'Customer' END,
       s.DerivedRank,
       CASE WHEN s.DerivedRank >= 2 THEN 1 ELSE 0 END,
       CASE WHEN s.DerivedRank >= 3 THEN 1 ELSE 0 END,
       e.HasOpp, e.IsWon,
       CASE WHEN s.DerivedRank <> s.LabelRank THEN 1 ELSE 0 END,
       ISNULL(j.TouchCount, 0), ISNULL(j.DistinctChannels, 0), ISNULL(j.SequenceContradictsDate, 0)
FROM stg.fact_leads l
CROSS APPLY (SELECT
        CASE WHEN EXISTS (SELECT 1 FROM stg.fact_opportunities o WHERE o.LeadID = l.LeadID) THEN 1 ELSE 0 END AS HasOpp,
        CASE WHEN EXISTS (SELECT 1 FROM stg.fact_revenue r WHERE r.LeadID = l.LeadID) THEN 1 ELSE 0 END AS IsWon) e
CROSS APPLY (SELECT CASE l.LatestStage WHEN N'Lead' THEN 1 WHEN N'MQL' THEN 2 WHEN N'SQL' THEN 3
                                       WHEN N'Opportunity' THEN 4 WHEN N'Customer' THEN 5 END AS LabelRank) lr
CROSS APPLY (SELECT lr.LabelRank,
                    CASE WHEN e.IsWon = 1 THEN 5 WHEN e.HasOpp = 1 THEN 4 ELSE lr.LabelRank END AS DerivedRank) s
LEFT JOIN #journey j ON j.LeadID = l.LeadID;

------------------------------------------------------------ FactTouchpoint ---
INSERT dbo.FactTouchpoint (TouchpointID, LeadID, TouchDate, CampaignID, ChannelID, TouchType,
                           SourceTouchSequence, JourneyPosition, JourneyLength, DaysBeforeLead)
SELECT t.TouchpointID, t.LeadID, t.TouchDate, t.CampaignID, t.ChannelID, t.TouchType,
       t.SourceTouchSequence, t.JourneyPosition, t.JourneyLength,
       DATEDIFF(DAY, t.TouchDate, l.CreatedDate)
FROM #tp t
JOIN dbo.FactLead l ON l.LeadID = t.LeadID;

----------------------------------------------------------- FactOpportunity ---
INSERT dbo.FactOpportunity (OpportunityID, LeadID, CreatedDate, OpportunityValue, [Status], IsAfterAsOf)
SELECT o.OpportunityID, o.LeadID, x.d, CONVERT(DECIMAL(18,2), o.OpportunityValue), o.[Status],
       CASE WHEN x.d > @AsOf THEN 1 ELSE 0 END
FROM stg.fact_opportunities o
CROSS APPLY (SELECT CONVERT(DATE, o.CreatedDate, 23) AS d) x;

--------------------------------------------------------------- FactRevenue ---
INSERT dbo.FactRevenue (RevenueID, OpportunityID, LeadID, RevenueDate, RevenueUSD, IsAfterAsOf)
SELECT r.RevenueID, r.OpportunityID, r.LeadID, x.d, CONVERT(DECIMAL(18,2), r.RevenueAmount),
       CASE WHEN x.d > @AsOf THEN 1 ELSE 0 END
FROM stg.fact_revenue r
CROSS APPLY (SELECT CONVERT(DATE, r.RevenueDate, 23) AS d) x;

SELECT (SELECT COUNT(*) FROM dbo.FactAdSpend)     AS FactAdSpend,
       (SELECT COUNT(*) FROM dbo.FactLead)        AS FactLead,
       (SELECT COUNT(*) FROM dbo.FactTouchpoint)  AS FactTouchpoint,
       (SELECT COUNT(*) FROM dbo.FactOpportunity) AS FactOpportunity,
       (SELECT COUNT(*) FROM dbo.FactRevenue)     AS FactRevenue;
PRINT 'Facts loaded.';
GO
