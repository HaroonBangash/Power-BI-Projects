/*=============================================================================
  09_validation.sql

  Every check prints Expected vs Actual and PASS/FAIL; the script THROWs if any
  check fails, so run_all.ps1 stops rather than reporting success.

  Where an expected value is a literal, it was measured independently by the
  pandas audit (Python/01_data_audit.py) straight from the raw CSVs - not read
  back from these tables. Structural expectations (a weight sum of 1, zero
  untrusted keys) are properties the build must satisfy by construction.
=============================================================================*/
USE MarketingAttributionBI;
GO
SET NOCOUNT ON;
GO

DROP TABLE IF EXISTS #c;
CREATE TABLE #c (Id INT IDENTITY(1,1), Area NVARCHAR(20), CheckName NVARCHAR(160),
                 Expected DECIMAL(38,6), Actual DECIMAL(38,6), Tolerance DECIMAL(38,6) NOT NULL DEFAULT 0);

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @Revenue DECIMAL(38,6) = 31756120.64;   -- pandas: sum of fact_revenue.RevenueAmount

----------------------------------------------------------------- 1. loads ---
INSERT #c (Area, CheckName, Expected, Actual)
SELECT N'Load', N'staging files matching published row counts', 10,
       (SELECT COUNT(*) FROM stg.LoadLog WHERE RowsLoaded = ExpectedRows);

INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Load', N'FactAdSpend rows',     80000,  (SELECT COUNT(*) FROM dbo.FactAdSpend)),
 (N'Load', N'FactLead rows',        50000,  (SELECT COUNT(*) FROM dbo.FactLead)),
 (N'Load', N'FactTouchpoint rows', 174938,  (SELECT COUNT(*) FROM dbo.FactTouchpoint)),
 (N'Load', N'FactOpportunity rows', 11152,  (SELECT COUNT(*) FROM dbo.FactOpportunity)),
 (N'Load', N'FactRevenue rows',      6559,  (SELECT COUNT(*) FROM dbo.FactRevenue)),
 (N'Load', N'DimCampaign rows',       300,  (SELECT COUNT(*) FROM dbo.DimCampaign)),
 (N'Load', N'CampaignAlias rows',     900,  (SELECT COUNT(*) FROM dbo.CampaignAlias)),
 (N'Load', N'DimChannel rows',          7,  (SELECT COUNT(*) FROM dbo.DimChannel)),
 (N'Load', N'DimRegion rows',           5,  (SELECT COUNT(*) FROM dbo.DimRegion)),
 (N'Load', N'SecurityUserAccess rows',  7,  (SELECT COUNT(*) FROM dbo.SecurityUserAccess));

--------------------------------------------------------------- 2. calendar ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Calendar', N'DimDate covers 2022-01-01..2027-06-30 with no gaps',
      DATEDIFF(DAY, '2022-01-01', '2027-06-30') + 1, (SELECT COUNT(*) FROM dbo.DimDate)),
 (N'Calendar', N'days also present in the supplied calendar', 1704,
      (SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 1)),
 (N'Calendar', N'regenerated days disagreeing with supplied calendar (8 columns)', 0,
      (SELECT COUNT(*) FROM stg.dim_date s
       JOIN dbo.DimDate d ON d.[Date] = CONVERT(DATE, s.[Date], 23)
       WHERE CONVERT(INT, s.[Year]) <> d.[Year] OR CONVERT(INT, s.MonthNo) <> d.MonthNo
          OR s.MonthName <> d.MonthName OR CONVERT(INT, s.[Quarter]) <> d.[Quarter]
          OR CONVERT(INT, s.ISOWeek) <> d.ISOWeek OR s.DayName <> d.DayName
          OR CONVERT(INT, s.FinancialYearStart) <> d.FinancialYearStart
          OR s.FinancialYear <> d.FinancialYear)),
 (N'Calendar', N'AsOfDate = 2026-08-31 (pandas: last spend/lead/touch date)', 20260831,
      CONVERT(INT, CONVERT(NCHAR(8), @AsOf, 112)));

------------------------------------------------------------ 3. integrity ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Integrity', N'foreign keys declared', 25, (SELECT COUNT(*) FROM sys.foreign_keys)),
 (N'Integrity', N'foreign keys untrusted or disabled', 0,
      (SELECT COUNT(*) FROM sys.foreign_keys WHERE is_not_trusted = 1 OR is_disabled = 1)),
 (N'Integrity', N'check constraints untrusted or disabled', 0,
      (SELECT COUNT(*) FROM sys.check_constraints WHERE is_not_trusted = 1 OR is_disabled = 1)),
 (N'Integrity', N'fact rows whose channel differs from the campaign home channel', 0,
      (SELECT COUNT(*) FROM dbo.FactAdSpend f JOIN dbo.DimCampaign c ON c.CampaignID = f.CampaignID WHERE f.ChannelID <> c.ChannelID)
    + (SELECT COUNT(*) FROM dbo.FactLead f JOIN dbo.DimCampaign c ON c.CampaignID = f.CampaignID WHERE f.ChannelID <> c.ChannelID)
    + (SELECT COUNT(*) FROM dbo.FactTouchpoint f JOIN dbo.DimCampaign c ON c.CampaignID = f.CampaignID WHERE f.ChannelID <> c.ChannelID)),
 (N'Integrity', N'campaigns with exactly 3 aliases', 300,
      (SELECT COUNT(*) FROM (SELECT CampaignID FROM dbo.CampaignAlias GROUP BY CampaignID HAVING COUNT(*) = 3) x)),
 (N'Integrity', N'raw campaign names mapping to more than one campaign', 0,
      (SELECT COUNT(*) FROM (SELECT RawCampaignName FROM dbo.CampaignAlias GROUP BY RawCampaignName HAVING COUNT(DISTINCT CampaignID) > 1) x));

------------------------------------------------------------ 4. currency ---
INSERT #c (Area, CheckName, Expected, Actual, Tolerance) VALUES
 (N'Currency', N'total local spend = source (pandas 1,085,259,568.68)', 1085259568.68,
      (SELECT SUM(SpendLocal) FROM dbo.FactAdSpend), 0),
 (N'Currency', N'local spend = staging, to the cent', (SELECT SUM(CONVERT(DECIMAL(18,2), SpendLocal)) FROM stg.fact_ad_spend),
      (SELECT SUM(SpendLocal) FROM dbo.FactAdSpend), 0),
 (N'Currency', N'SpendUSD = SpendLocal x planning rate (rounding only)',
      (SELECT SUM(SpendLocal * FxRateToUSD) FROM dbo.FactAdSpend),
      (SELECT SUM(SpendUSD) FROM dbo.FactAdSpend), 400),
 (N'Currency', N'ad rows whose FX rate does not match the rate table', 0,
      (SELECT COUNT(*) FROM dbo.FactAdSpend a
       WHERE NOT EXISTS (SELECT 1 FROM dbo.FxRate r WHERE r.CurrencyCode = a.CurrencyCode AND r.RateType = N'Planning'
                         AND a.[Date] BETWEEN r.EffectiveFrom AND r.EffectiveTo AND r.RateToUSD = a.FxRateToUSD)), 0),
 (N'Currency', N'spend rows before campaign StartDate (pandas 33,739)', 33739,
      (SELECT COUNT(*) FROM dbo.FactAdSpend WHERE IsBeforeCampaignStart = 1), 0);

-------------------------------------------------------- 5. funnel/journey ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Funnel', N'leads reaching MQL or beyond (pandas 32,589)', 32589, (SELECT SUM(CONVERT(INT, ReachedMQL)) FROM dbo.FactLead)),
 (N'Funnel', N'leads reaching SQL or beyond (pandas 20,148)', 20148, (SELECT SUM(CONVERT(INT, ReachedSQL)) FROM dbo.FactLead)),
 (N'Funnel', N'leads with an opportunity (pandas 11,152)',    11152, (SELECT SUM(CONVERT(INT, HasOpportunity)) FROM dbo.FactLead)),
 (N'Funnel', N'won leads = revenue rows (pandas 6,559)',        6559, (SELECT SUM(CONVERT(INT, IsWon)) FROM dbo.FactLead)),
 (N'Funnel', N'stale stage labels corrected (pandas 2,428)',    2428, (SELECT SUM(CONVERT(INT, IsStageLabelStale)) FROM dbo.FactLead)),
 (N'Funnel', N'labels Opportunity/Customer with no opportunity', 0,
      (SELECT COUNT(*) FROM dbo.FactLead WHERE LatestStageLabel IN (N'Opportunity', N'Customer') AND HasOpportunity = 0)),
 (N'Funnel', N'revenue rows on an opportunity that is not Closed Won', 0,
      (SELECT COUNT(*) FROM dbo.FactRevenue r JOIN dbo.FactOpportunity o ON o.OpportunityID = r.OpportunityID WHERE o.[Status] <> N'Closed Won')),
 (N'Funnel', N'revenue differing from its opportunity value', 0,
      (SELECT COUNT(*) FROM dbo.FactRevenue r JOIN dbo.FactOpportunity o ON o.OpportunityID = r.OpportunityID WHERE r.RevenueUSD <> o.OpportunityValue)),
 (N'Journey', N'leads whose sequence contradicts dates (pandas 35,409)', 35409,
      (SELECT SUM(CONVERT(INT, SequenceContradictsDate)) FROM dbo.FactLead)),
 (N'Journey', N'leads whose JourneyPosition is not exactly 1..n', 0,
      (SELECT COUNT(*) FROM (SELECT LeadID FROM dbo.FactTouchpoint GROUP BY LeadID
                             HAVING MIN(JourneyPosition) <> 1 OR MAX(JourneyPosition) <> COUNT(*)
                                 OR MAX(JourneyLength) <> COUNT(*)) x)),
 (N'Journey', N'touches dated after their lead was created', 0,
      (SELECT COUNT(*) FROM dbo.FactTouchpoint WHERE DaysBeforeLead < 0)),
 (N'AsOf', N'opportunities dated after as-of (pandas 244)', 244, (SELECT SUM(CONVERT(INT, IsAfterAsOf)) FROM dbo.FactOpportunity)),
 (N'AsOf', N'revenue rows dated after as-of (pandas 209)',  209, (SELECT SUM(CONVERT(INT, IsAfterAsOf)) FROM dbo.FactRevenue));

INSERT #c (Area, CheckName, Expected, Actual, Tolerance) VALUES
 (N'AsOf', N'revenue amount dated after as-of (pandas 888,614.96)', 888614.96,
      (SELECT SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 1), 0),
 (N'Funnel', N'total revenue (pandas 31,756,120.64)', @Revenue, (SELECT SUM(RevenueUSD) FROM dbo.FactRevenue), 0);

----------------------------------------------------------- 6. attribution ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Attribution', N'credit rows = 5 models x 174,938 touches', 874690, (SELECT COUNT(*) FROM dbo.FactAttributionCredit)),
 (N'Attribution', N'lead x model pairs whose weights do not sum to 1 (1e-12)', 0,
      (SELECT COUNT(*) FROM (SELECT LeadID, ModelKey FROM dbo.FactAttributionCredit GROUP BY LeadID, ModelKey
                             HAVING ABS(SUM(CreditWeight) - 1) > 0.000000000001) x)),
 (N'Attribution', N'first-touch credit on a touch other than position 1', 0,
      (SELECT COUNT(*) FROM dbo.FactAttributionCredit c JOIN dbo.FactTouchpoint t ON t.TouchpointID = c.TouchpointID
       WHERE c.ModelKey = 1 AND c.CreditWeight > 0 AND t.JourneyPosition <> 1)),
 (N'Attribution', N'last-touch credit on a touch other than position n', 0,
      (SELECT COUNT(*) FROM dbo.FactAttributionCredit c JOIN dbo.FactTouchpoint t ON t.TouchpointID = c.TouchpointID
       WHERE c.ModelKey = 2 AND c.CreditWeight > 0 AND t.JourneyPosition <> t.JourneyLength)),
 -- Tested as weight x n = 1, not weight = 1.0 / n: SQL Server rounds the
 -- DECIMAL quotient 1.0 / 3 to 0.333333 (scale 6), which would flag every
 -- correct weight in a 3- or 6-touch journey as wrong.
 (N'Attribution', N'linear weights where weight x n differs from 1', 0,
      (SELECT COUNT(*) FROM dbo.FactAttributionCredit c JOIN dbo.FactTouchpoint t ON t.TouchpointID = c.TouchpointID
       WHERE c.ModelKey = 3 AND ABS(c.CreditWeight * t.JourneyLength - 1) > 0.000000000001)),
 (N'Attribution', N'position-based endpoints differing from 40/40 (n>=3), 50/50 (n=2), 100 (n=1)', 0,
      (SELECT COUNT(*) FROM dbo.FactAttributionCredit c JOIN dbo.FactTouchpoint t ON t.TouchpointID = c.TouchpointID
       WHERE c.ModelKey = 4 AND (
             (t.JourneyLength = 1 AND c.CreditWeight <> 1)
          OR (t.JourneyLength = 2 AND c.CreditWeight <> 0.5)
          OR (t.JourneyLength >= 3 AND t.JourneyPosition IN (1, t.JourneyLength) AND ABS(c.CreditWeight - 0.4) > 0.000000000001)))),
 (N'Attribution', N'time-decay: a later touch earning less than an earlier one', 0,
      (SELECT COUNT(*) FROM dbo.FactAttributionCredit a
       JOIN dbo.FactTouchpoint ta ON ta.TouchpointID = a.TouchpointID
       JOIN dbo.FactTouchpoint tb ON tb.LeadID = ta.LeadID AND tb.DaysBeforeLead < ta.DaysBeforeLead
       JOIN dbo.FactAttributionCredit b ON b.TouchpointID = tb.TouchpointID AND b.ModelKey = 5
       WHERE a.ModelKey = 5 AND b.CreditWeight < a.CreditWeight));

-- Each model re-divides the same revenue: none may create or lose any.
INSERT #c (Area, CheckName, Expected, Actual, Tolerance)
SELECT N'Attribution', CONCAT(m.ModelName, N' attributed revenue = total revenue'), @Revenue,
       (SELECT SUM(AttributedRevenueUSD) FROM dbo.FactAttributionCredit c WHERE c.ModelKey = m.ModelKey), 0.05
FROM dbo.DimAttributionModel m;

INSERT #c (Area, CheckName, Expected, Actual, Tolerance)
SELECT N'Attribution', CONCAT(m.ModelName, N' total lead credit = 50,000 leads'), 50000,
       (SELECT SUM(CreditWeight) FROM dbo.FactAttributionCredit c WHERE c.ModelKey = m.ModelKey), 0.000001
FROM dbo.DimAttributionModel m;

------------------------------------------------------------------ 7. views ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Views', N'analytics views present', 17,
      (SELECT COUNT(*) FROM sys.views WHERE SCHEMA_NAME(schema_id) = N'analytics')),
 (N'Views', N'vw_DimFunnelStage: five ordered stages', 5,
      (SELECT COUNT(*) FROM analytics.vw_DimFunnelStage)),
 (N'Journey', N'PositionBand Only touch = one-touch journeys (pandas 8,361)', 8361,
      (SELECT COUNT(*) FROM dbo.FactTouchpoint WHERE PositionBand = N'Only touch')),
 (N'Journey', N'PositionBand First = multi-touch journeys (50,000 - 8,361)', 41639,
      (SELECT COUNT(*) FROM dbo.FactTouchpoint WHERE PositionBand = N'First')),
 (N'Journey', N'PositionBand Last = multi-touch journeys (50,000 - 8,361)', 41639,
      (SELECT COUNT(*) FROM dbo.FactTouchpoint WHERE PositionBand = N'Last')),
 (N'Journey', N'PositionBand Middle = the remaining touches', 83299,
      (SELECT COUNT(*) FROM dbo.FactTouchpoint WHERE PositionBand = N'Middle')),
 (N'Views', N'vw_FactLeadFunnel: one row per lead (joins do not fan out)', 50000,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel)),
 (N'Views', N'vw_FactLeadFunnel: rows carrying an opportunity', 11152,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE OpportunityID IS NOT NULL)),
 (N'Views', N'vw_FactLeadFunnel: rows carrying revenue', 6559,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE RevenueID IS NOT NULL)),
 (N'Views', N'vw_FactLeadFunnel: revenue = total revenue', @Revenue,
      (SELECT SUM(RevenueUSD) FROM analytics.vw_FactLeadFunnel)),
 (N'Views', N'vw_DimCampaign: channel join keeps all 300 campaigns', 300,
      (SELECT COUNT(*) FROM analytics.vw_DimCampaign)),
 (N'Views', N'view row counts differing from their dbo table', 0,
        CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactAdSpend)           = (SELECT COUNT(*) FROM dbo.FactAdSpend) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactLead)              = (SELECT COUNT(*) FROM dbo.FactLead) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactTouchpoint)        = (SELECT COUNT(*) FROM dbo.FactTouchpoint) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactOpportunity)       = (SELECT COUNT(*) FROM dbo.FactOpportunity) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactRevenue)           = (SELECT COUNT(*) FROM dbo.FactRevenue) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_FactAttributionCredit) = (SELECT COUNT(*) FROM dbo.FactAttributionCredit) THEN 0 ELSE 1 END
      + CASE WHEN (SELECT COUNT(*) FROM analytics.vw_DimDate)               = (SELECT COUNT(*) FROM dbo.DimDate) THEN 0 ELSE 1 END);

------------------------------------------------------------------ 8. as of ---
-- The funnel restated as it stood on the as-of date (08 header). Literal
-- expected values are measured by the pandas audit from the raw CSVs.
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'AsOf', N'opportunities opened by the as-of date (pandas 10,908)', 10908,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE IsOpportunityByAsOf = 1)),
 (N'AsOf', N'customers: revenue booked by the as-of date (pandas 6,350)', 6350,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE IsWonByAsOf = 1)),
 (N'AsOf', N'status as of: Closed Won = customers by the as-of date (pandas 6,350)', 6350,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE OpportunityStatusAsOf = N'Closed Won')),
 (N'AsOf', N'status as of: Closed Lost (pandas 2,258)', 2258,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE OpportunityStatusAsOf = N'Closed Lost')),
 (N'AsOf', N'status as of: Open, incl. deals won after the as-of date (pandas 2,300)', 2300,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE OpportunityStatusAsOf = N'Open')),
 (N'AsOf', N'stage as of reaching SQL or beyond = SQLs (pandas 20,148)', 20148,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE StageRankAsOf >= 3)),
 (N'AsOf', N'stage as of above the evidence stage', 0,
      (SELECT COUNT(*) FROM analytics.vw_FactLeadFunnel WHERE StageRankAsOf > StageRank)),
 (N'Calendar', N'days flagged after the as-of date', DATEDIFF(DAY, @AsOf, '2027-06-30'),
      (SELECT COUNT(*) FROM dbo.DimDate WHERE IsAfterAsOf = 1)),
 (N'Calendar', N'days in complete quarters, 2022 Q1 - 2026 Q2 (as of 2026-08-31)', DATEDIFF(DAY, '2022-01-01', '2026-06-30') + 1,
      (SELECT COUNT(*) FROM dbo.DimDate WHERE IsQuarterComplete = 1)),
 (N'Attribution', N'models carrying a campaign dispersion for the signal test', 5,
      (SELECT COUNT(*) FROM dbo.DimAttributionModel WHERE CampaignDispersionUSD > 0));

INSERT #c (Area, CheckName, Expected, Actual, Tolerance) VALUES
 (N'AsOf', N'revenue booked by the as-of date (pandas 30,867,505.68)', 30867505.68,
      (SELECT SUM(RevenueUSD) FROM analytics.vw_FactLeadFunnel WHERE IsWonByAsOf = 1), 0),
 (N'AsOf', N'open pipeline at the as-of date (pandas 11,053,204.40)', 11053204.40,
      (SELECT SUM(OpportunityValue) FROM analytics.vw_FactLeadFunnel WHERE OpportunityStatusAsOf = N'Open'), 0);

----------------------------------------------------------------- report ---
SELECT Id, Area, CheckName, Expected, Actual,
       CASE WHEN ABS(Expected - Actual) <= Tolerance THEN N'PASS' ELSE N'FAIL' END AS Result
FROM #c ORDER BY Id;

DECLARE @Fail INT = (SELECT COUNT(*) FROM #c WHERE ABS(Expected - Actual) > Tolerance);
DECLARE @Total INT = (SELECT COUNT(*) FROM #c);
PRINT CONCAT(@Total - @Fail, N' of ', @Total, N' checks passed.');
IF @Fail > 0 THROW 50090, N'Validation failed - see FAIL rows above.', 1;
GO
