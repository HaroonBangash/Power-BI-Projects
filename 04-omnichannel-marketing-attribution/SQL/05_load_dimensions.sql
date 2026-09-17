/*=============================================================================
  05_load_dimensions.sql

  Configuration, FX planning rates, the regenerated calendar, and the dimension
  tables. Facts load in 06, attribution in 07.
=============================================================================*/
USE MarketingAttributionBI;
GO
SET NOCOUNT ON;
SET LANGUAGE us_english;   -- DATENAME must return English month/day names
SET DATEFIRST 1;           -- Monday = 1, matching ISO weeks
GO

-------------------------------------------------------------- ModelConfig ---
-- The as-of date is DERIVED from the data, never GETDATE(): it is the last day
-- on which marketing activity (spend, leads, touches) was recorded. Opportunity
-- and revenue rows run past it and are flagged rather than silently counted.
DECLARE @AsOf DATE = (
    SELECT MAX(d) FROM (
        SELECT MAX(CONVERT(DATE, [Date], 23))      FROM stg.fact_ad_spend    UNION ALL
        SELECT MAX(CONVERT(DATE, CreatedDate, 23)) FROM stg.fact_leads       UNION ALL
        SELECT MAX(CONVERT(DATE, TouchDate, 23))   FROM stg.fact_touchpoints) x(d));

INSERT dbo.ModelConfig (ConfigKey, ConfigValue, Description) VALUES
 (N'AsOfDate', CONVERT(NCHAR(10), @AsOf, 23),
  N'Last date with recorded marketing activity (spend, leads, touchpoints). Anchor for every "to date" figure. Derived from the data; never GETDATE().'),
 (N'CalendarStartDate', N'2022-01-01', N'First date in DimDate. Matches the supplied source calendar.'),
 (N'CalendarEndDate', N'2027-06-30',
  N'Last date in DimDate. The supplied calendar ends 2026-08-31, but opportunities run to 2026-10-09 and revenue to 2026-10-21. Extended to the end of FY27 so every fact date resolves.'),
 (N'FinancialYearStartMonth', N'7', N'Financial year starts in July: Jul 2025 - Jun 2026 is FY26. Derived from the supplied calendar.'),
 (N'ReportingCurrency', N'USD', N'Every money measure is reported in USD. Revenue carries no currency column and is treated as USD.'),
 (N'FxRateType', N'Planning', N'Rate set applied to ad spend. Static planning rates - see dbo.FxRate.Source. Not market data.'),
 (N'TimeDecayHalfLifeDays', N'7', N'Time-decay attribution: a touch 7 days before the lead was created earns half the credit of a touch on the day. 7 days is the common industry default.'),
 (N'PositionBasedFirstWeight', N'0.40', N'Position-based (U-shaped) model: share of credit to the first touch.'),
 (N'PositionBasedLastWeight', N'0.40', N'Position-based model: share of credit to the last touch. The remaining 20% is split evenly across middle touches.'),
 (N'DefaultAttributionModel', N'Position-Based', N'Model shown when the report selector has no selection.'),
 (N'DatasetProvenance', N'Synthetic', N'The dataset is synthetic and portfolio-safe. It must never be presented as real client data.');

-------------------------------------------------------------------- FxRate ---
-- The source ships spend in AUD, EUR, GBP and USD but no exchange rates, so a
-- rate table has to be introduced. These are round, clearly labelled PLANNING
-- rates, not market rates. One rate per currency across the whole period keeps
-- cross-period comparison free of currency noise. The table is dated so a real
-- monthly rate feed can replace it with no change to anything downstream.
DECLARE @FxSource NVARCHAR(300) =
    N'Illustrative planning rate chosen for this synthetic portfolio dataset. NOT market data. Replace with a dated rate feed for real use.';
INSERT dbo.FxRate (CurrencyCode, RateType, EffectiveFrom, EffectiveTo, RateToUSD, Source) VALUES
 (N'USD', N'Planning', '2022-01-01', '2027-06-30', 1.000000, N'Reporting currency.'),
 (N'EUR', N'Planning', '2022-01-01', '2027-06-30', 1.080000, @FxSource),
 (N'GBP', N'Planning', '2022-01-01', '2027-06-30', 1.270000, @FxSource),
 (N'AUD', N'Planning', '2022-01-01', '2027-06-30', 0.660000, @FxSource);

------------------------------------------------------------------- DimDate ---
-- Regenerated rather than loaded, because the supplied calendar stops before
-- the last fact date. Columns are checked against the supplied calendar for
-- every overlapping day in 09_validation.sql.
DECLARE @Start DATE = '2022-01-01', @End DATE = '2027-06-30';

INSERT dbo.DimDate
SELECT d,
       YEAR(d),
       MONTH(d),
       DATENAME(MONTH, d),
       LEFT(DATENAME(MONTH, d), 3),
       DATEPART(QUARTER, d),
       CONCAT(YEAR(d), N' Q', DATEPART(QUARTER, d)),
       YEAR(d) * 100 + MONTH(d),
       CONCAT(LEFT(DATENAME(MONTH, d), 3), N' ', YEAR(d)),
       DATEFROMPARTS(YEAR(d), MONTH(d), 1),
       DATEPART(ISO_WEEK, d),
       DATEADD(DAY, 1 - DATEPART(WEEKDAY, d), d),
       DATENAME(WEEKDAY, d),
       DATEPART(WEEKDAY, d),
       fys,
       CONCAT(N'FY', RIGHT(CONVERT(NCHAR(4), fys + 1), 2)),
       (MONTH(d) + 5) % 12 + 1,
       CASE WHEN EXISTS (SELECT 1 FROM stg.dim_date s WHERE CONVERT(DATE, s.[Date], 23) = d) THEN 1 ELSE 0 END,
       -- Relative to the as-of date, so a chart can keep to complete periods: a
       -- count by quarter would otherwise end in a partial quarter that reads as a
       -- collapse (2026 Q3 holds two of its three months).
       CASE WHEN d > @AsOf THEN 1 ELSE 0 END,
       CASE WHEN EOMONTH(DATEFROMPARTS(YEAR(d), DATEPART(QUARTER, d) * 3, 1)) <= @AsOf THEN 1 ELSE 0 END
FROM (SELECT DATEADD(DAY, value, @Start) AS d
      FROM GENERATE_SERIES(0, DATEDIFF(DAY, @Start, @End))) g
CROSS APPLY (SELECT CASE WHEN MONTH(d) >= 7 THEN YEAR(d) ELSE YEAR(d) - 1 END AS fys) f;

---------------------------------------------------------------- dimensions ---
INSERT dbo.DimRegion (Region)
SELECT DISTINCT Region FROM stg.dim_campaign;

INSERT dbo.DimChannel (ChannelID, ChannelName, ChannelGroup, IsPaidMedia)
SELECT ChannelID, ChannelName, ChannelGroup,
       CASE WHEN ChannelGroup LIKE N'Paid %' THEN 1 ELSE 0 END
FROM stg.dim_channel;

INSERT dbo.DimCampaign (CampaignID, CampaignName, ChannelID, Region, Objective, StartDate)
SELECT CampaignID, CanonicalCampaignName, ChannelID, Region, Objective, CONVERT(DATE, StartDate, 23)
FROM stg.dim_campaign;

INSERT dbo.CampaignAlias (RawCampaignKey, RawCampaignName, CampaignID)
SELECT RawCampaignKey, RawCampaignName, CampaignID
FROM stg.campaign_name_mapping;

INSERT dbo.DimAttributionModel (ModelKey, ModelName, SortOrder, Description) VALUES
 (1, N'First Touch',    1, N'All credit to the earliest touch in the journey.'),
 (2, N'Last Touch',     2, N'All credit to the final touch before the lead was created.'),
 (3, N'Linear',         3, N'Credit split equally across every touch.'),
 (4, N'Position-Based', 4, N'U-shaped: 40% first, 40% last, 20% shared by the middle touches. One touch takes 100%; two touches take 50% each.'),
 (5, N'Time-Decay',     5, N'Credit halves for every 7 days a touch sits before lead creation, then normalised to 100% per lead.');

INSERT dbo.SecurityUserAccess (UserEmail, [Role], Region)
SELECT UserEmail, [Role], Region FROM stg.security_user_access;

IF EXISTS (SELECT 1 FROM dbo.SecurityUserAccess s
           WHERE s.Region <> N'ALL' AND NOT EXISTS (SELECT 1 FROM dbo.DimRegion r WHERE r.Region = s.Region))
    THROW 50002, N'SecurityUserAccess references a region that no campaign belongs to.', 1;

-- Each stage counts leads that reached AT LEAST that stage, so the five bars
-- of a funnel nest inside one another by construction.
INSERT dbo.DimFunnelStage (StageRank, StageName, Definition) VALUES
 (1, N'Lead',        N'Every lead created.'),
 (2, N'MQL',         N'Marketing-qualified: CRM stage MQL or later.'),
 (3, N'SQL',         N'Sales-qualified: CRM stage SQL or later.'),
 (4, N'Opportunity', N'An opportunity exists for the lead (evidence, not the CRM label).'),
 (5, N'Customer',    N'Revenue is booked for the lead (evidence, not the CRM label).');

SELECT (SELECT COUNT(*) FROM dbo.ModelConfig)         AS ModelConfig,
       (SELECT COUNT(*) FROM dbo.DimFunnelStage)      AS DimFunnelStage,
       (SELECT COUNT(*) FROM dbo.FxRate)              AS FxRate,
       (SELECT COUNT(*) FROM dbo.DimDate)             AS DimDate,
       (SELECT COUNT(*) FROM dbo.DimRegion)           AS DimRegion,
       (SELECT COUNT(*) FROM dbo.DimChannel)          AS DimChannel,
       (SELECT COUNT(*) FROM dbo.DimCampaign)         AS DimCampaign,
       (SELECT COUNT(*) FROM dbo.CampaignAlias)       AS CampaignAlias,
       (SELECT COUNT(*) FROM dbo.DimAttributionModel) AS DimAttributionModel,
       (SELECT COUNT(*) FROM dbo.SecurityUserAccess)  AS SecurityUserAccess;
PRINT 'Dimensions loaded.';
GO
