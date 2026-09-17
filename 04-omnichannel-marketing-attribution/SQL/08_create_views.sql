/*=============================================================================
  08_create_views.sql

  analytics.vw_* - the ONLY contract Power BI reads. Each view is a plain,
  foldable SELECT with no business logic of its own: logic lives in dbo where
  it is typed, constrained and validated. A dbo change never reaches the report
  while these views keep their shape.

  Two views are shaped for the semantic model rather than mirroring one table:

  vw_DimCampaign carries the channel columns. Every fact row's channel equals
    its campaign's home channel (09 checks 0 mismatches), so channel is a level
    of the campaign hierarchy, not a second dimension. One marketing dimension
    means no ambiguous filter paths and slicers that cross-filter naturally.

  vw_FactLeadFunnel is an accumulating snapshot: one row per lead carrying its
    opportunity and revenue milestones. Each lead has at most one opportunity
    and each opportunity at most one revenue booking (09 enforces both through
    unique keys), so the join cannot fan out. The model can then follow a lead
    from creation to revenue without any fact-to-fact relationship.

    It also restates each lead AS IT STOOD ON THE AS-OF DATE, from dbo's
    IsAfterAsOf flags. The source records outcomes up to 2026-10-21, seven
    weeks past the as-of date; counting them would put September's wins into a
    report dated 31 August, and customers would stop reconciling to revenue.
      IsOpportunityByAsOf    the opportunity existed by the as-of date
      IsWonByAsOf            revenue was booked by the as-of date
      OpportunityStatusAsOf  Closed Won if booked by then; an opportunity won
                             later was still Open; Closed Lost is taken as lost
                             by then (the source records no loss date - the
                             one assumption, documented in PROJECT_STATE)
      StageRankAsOf          5 won, 4 opportunity, else the CRM stage capped at
                             SQL (an opportunity opened later implies SQL)
=============================================================================*/
USE MarketingAttributionBI;
GO

CREATE OR ALTER VIEW analytics.vw_ModelConfig AS
SELECT ConfigKey, ConfigValue, Description FROM dbo.ModelConfig;
GO
CREATE OR ALTER VIEW analytics.vw_DimDate AS
SELECT [Date], [Year], MonthNo, MonthName, MonthShort, [Quarter], QuarterLabel,
       YearMonth, YearMonthLabel, MonthStart, ISOWeek, WeekStart, DayName, DayOfWeekNo,
       FinancialYearStart, FinancialYear, FinancialMonthNo, IsSourceCalendar,
       IsAfterAsOf, IsQuarterComplete
FROM dbo.DimDate;
GO
CREATE OR ALTER VIEW analytics.vw_DimRegion AS
SELECT Region FROM dbo.DimRegion;
GO
CREATE OR ALTER VIEW analytics.vw_DimChannel AS
SELECT ChannelID, ChannelName, ChannelGroup, IsPaidMedia FROM dbo.DimChannel;
GO
CREATE OR ALTER VIEW analytics.vw_DimCampaign AS
SELECT c.CampaignID, c.CampaignName, c.Region, c.Objective, c.StartDate,
       c.ChannelID, ch.ChannelName, ch.ChannelGroup, ch.IsPaidMedia
FROM dbo.DimCampaign c
JOIN dbo.DimChannel ch ON ch.ChannelID = c.ChannelID;
GO
CREATE OR ALTER VIEW analytics.vw_CampaignAlias AS
SELECT RawCampaignKey, RawCampaignName, CampaignID FROM dbo.CampaignAlias;
GO
CREATE OR ALTER VIEW analytics.vw_FxRate AS
SELECT CurrencyCode, RateType, EffectiveFrom, EffectiveTo, RateToUSD, Source FROM dbo.FxRate;
GO
CREATE OR ALTER VIEW analytics.vw_DimAttributionModel AS
SELECT ModelKey, ModelName, SortOrder, Description, CampaignDispersionUSD FROM dbo.DimAttributionModel;
GO
CREATE OR ALTER VIEW analytics.vw_DimFunnelStage AS
SELECT StageRank, StageName, Definition FROM dbo.DimFunnelStage;
GO
CREATE OR ALTER VIEW analytics.vw_SecurityUserAccess AS
SELECT UserEmail, [Role], Region FROM dbo.SecurityUserAccess;
GO
CREATE OR ALTER VIEW analytics.vw_FactAdSpend AS
SELECT AdRowID, [Date], CampaignID, ChannelID, Impressions, Clicks,
       SpendLocal, CurrencyCode, FxRateToUSD, SpendUSD, IsBeforeCampaignStart
FROM dbo.FactAdSpend;
GO
CREATE OR ALTER VIEW analytics.vw_FactLead AS
SELECT LeadID, CreatedDate, CampaignID, ChannelID, Segment, Country, EstimatedValue,
       LatestStageLabel, DerivedStage, StageRank, ReachedMQL, ReachedSQL, HasOpportunity,
       IsWon, IsStageLabelStale, TouchCount, DistinctChannels, SequenceContradictsDate
FROM dbo.FactLead;
GO
CREATE OR ALTER VIEW analytics.vw_FactLeadFunnel AS
SELECT l.LeadID, l.CreatedDate, l.CampaignID, l.Segment, l.Country, l.EstimatedValue,
       l.LatestStageLabel, l.DerivedStage, l.StageRank,
       l.ReachedMQL, l.ReachedSQL, l.HasOpportunity, l.IsWon, l.IsStageLabelStale,
       l.TouchCount, l.DistinctChannels, l.SequenceContradictsDate,
       o.OpportunityID,
       o.CreatedDate                          AS OpportunityCreatedDate,
       o.OpportunityValue,
       o.[Status]                             AS OpportunityStatus,
       o.IsAfterAsOf                          AS IsOpportunityAfterAsOf,
       r.RevenueID, r.RevenueDate, r.RevenueUSD,
       r.IsAfterAsOf                          AS IsRevenueAfterAsOf,
       DATEDIFF(DAY, l.CreatedDate, o.CreatedDate) AS DaysLeadToOpportunity,
       DATEDIFF(DAY, o.CreatedDate, r.RevenueDate) AS DaysOpportunityToRevenue,
       -- The lead AS IT STOOD on the as-of date (see header).
       CAST(CASE WHEN o.OpportunityID IS NOT NULL AND o.IsAfterAsOf = 0 THEN 1 ELSE 0 END AS BIT) AS IsOpportunityByAsOf,
       CAST(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 1 ELSE 0 END AS BIT) AS IsWonByAsOf,
       CASE WHEN o.OpportunityID IS NULL OR o.IsAfterAsOf = 1 THEN NULL
            WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN N'Closed Won'
            WHEN o.[Status] = N'Closed Lost' THEN N'Closed Lost'
            ELSE N'Open' END                  AS OpportunityStatusAsOf,
       CAST(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 5
                 WHEN o.OpportunityID IS NOT NULL AND o.IsAfterAsOf = 0 THEN 4
                 WHEN l.StageRank >= 4 THEN 3
                 ELSE l.StageRank END AS TINYINT) AS StageRankAsOf
FROM dbo.FactLead l
LEFT JOIN dbo.FactOpportunity o ON o.LeadID = l.LeadID
LEFT JOIN dbo.FactRevenue r     ON r.OpportunityID = o.OpportunityID;
GO
CREATE OR ALTER VIEW analytics.vw_FactTouchpoint AS
SELECT TouchpointID, LeadID, TouchDate, CampaignID, ChannelID, TouchType,
       SourceTouchSequence, JourneyPosition, JourneyLength, DaysBeforeLead,
       PositionBand, PositionBandOrder
FROM dbo.FactTouchpoint;
GO
CREATE OR ALTER VIEW analytics.vw_FactOpportunity AS
SELECT OpportunityID, LeadID, CreatedDate, OpportunityValue, [Status], IsAfterAsOf
FROM dbo.FactOpportunity;
GO
CREATE OR ALTER VIEW analytics.vw_FactRevenue AS
SELECT RevenueID, OpportunityID, LeadID, RevenueDate, RevenueUSD, IsAfterAsOf
FROM dbo.FactRevenue;
GO
CREATE OR ALTER VIEW analytics.vw_FactAttributionCredit AS
SELECT TouchpointID, ModelKey, LeadID, CampaignID, ChannelID, TouchDate, RevenueDate,
       CreditWeight, AttributedRevenueUSD, IsRevenueAfterAsOf
FROM dbo.FactAttributionCredit;
GO
PRINT '17 analytics views created.';
GO
