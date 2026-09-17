/*=============================================================================
  07_build_attribution.sql

  Materialises dbo.FactAttributionCredit: one row per touchpoint per model,
  carrying the share of that lead's conversion credited to the touch.

  WHY PRECOMPUTE IN SQL, NOT DAX. Five models over 174,938 touches is 874,690
  weights. Computing position and decay weights per touch at query time would
  re-sort every journey on every visual refresh. Stored weights are computed
  once, can be audited row by row, are checked against an independent Python
  implementation (Validation/validate_attribution.py), and leave the report's
  model selector with a simple filter instead of a five-way SWITCH.

  THE CONVERSION EVENT is lead creation. Every touch in the source falls on or
  before its lead's CreatedDate (0 after, measured), so the journey is exactly
  the pre-lead touch history. Revenue is booked later and is attributed back
  through that journey: AttributedRevenueUSD = CreditWeight x the lead's revenue.

  THE FIVE MODELS, with n = journey length and k = JourneyPosition (06):
    1 First Touch     k = 1 -> 1, otherwise 0
    2 Last Touch      k = n -> 1, otherwise 0
    3 Linear          1 / n
    4 Position-Based  n = 1 -> 1; n = 2 -> 0.5 each;
                      n >= 3 -> first 0.40, last 0.40, middle 0.20 / (n - 2)
    5 Time-Decay      raw = 0.5 ^ (DaysBeforeLead / half-life), then divided by
                      the lead's total raw so the lead's credit sums to exactly 1

  Every lead's weights sum to 1 under every model, so each model re-divides
  the same revenue total rather than creating or losing any. Verified in 09.
=============================================================================*/
USE MarketingAttributionBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf     DATE  = (SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @HalfLife FLOAT = (SELECT CONVERT(FLOAT, ConfigValue) FROM dbo.ModelConfig WHERE ConfigKey = N'TimeDecayHalfLifeDays');
DECLARE @PbFirst  FLOAT = (SELECT CONVERT(FLOAT, ConfigValue) FROM dbo.ModelConfig WHERE ConfigKey = N'PositionBasedFirstWeight');
DECLARE @PbLast   FLOAT = (SELECT CONVERT(FLOAT, ConfigValue) FROM dbo.ModelConfig WHERE ConfigKey = N'PositionBasedLastWeight');

TRUNCATE TABLE dbo.FactAttributionCredit;

WITH j AS (
    SELECT t.TouchpointID, t.LeadID, t.CampaignID, t.ChannelID, t.TouchDate,
           CONVERT(FLOAT, t.JourneyPosition) AS k,
           CONVERT(FLOAT, t.JourneyLength)   AS n,
           POWER(CONVERT(FLOAT, 0.5), t.DaysBeforeLead / @HalfLife) AS DecayRaw
    FROM dbo.FactTouchpoint t
),
w AS (
    SELECT j.*,
           DecayRaw / SUM(DecayRaw) OVER (PARTITION BY LeadID) AS wDecay,
           CASE WHEN n = 1 THEN 1.0
                WHEN n = 2 THEN 0.5
                WHEN k = 1 THEN @PbFirst
                WHEN k = n THEN @PbLast
                ELSE (1.0 - @PbFirst - @PbLast) / (n - 2) END AS wPosition
    FROM j
)
INSERT dbo.FactAttributionCredit (TouchpointID, ModelKey, LeadID, CampaignID, ChannelID, TouchDate,
                                  RevenueDate, CreditWeight, AttributedRevenueUSD, IsRevenueAfterAsOf)
SELECT w.TouchpointID, m.ModelKey, w.LeadID, w.CampaignID, w.ChannelID, w.TouchDate,
       r.RevenueDate,
       CONVERT(DECIMAL(19,15), m.Weight),
       CONVERT(DECIMAL(19,6), m.Weight * ISNULL(CONVERT(FLOAT, r.RevenueUSD), 0.0)),
       ISNULL(r.IsAfterAsOf, 0)
FROM w
LEFT JOIN dbo.FactRevenue r ON r.LeadID = w.LeadID
CROSS APPLY (VALUES
    (CONVERT(TINYINT, 1), CASE WHEN w.k = 1   THEN 1.0 ELSE 0.0 END),
    (CONVERT(TINYINT, 2), CASE WHEN w.k = w.n THEN 1.0 ELSE 0.0 END),
    (CONVERT(TINYINT, 3), 1.0 / w.n),
    (CONVERT(TINYINT, 4), w.wPosition),
    (CONVERT(TINYINT, 5), w.wDecay)
) m (ModelKey, Weight);

-- CAMPAIGN SIGNAL TEST (report measure Campaign Index z). A campaign's
-- attributed revenue is a sum of per-lead contributions v. If the campaign
-- earned exactly its spend share, that sum would have mean E and - treating
-- converting leads as arriving independently (compound Poisson) - variance
-- E x sum(v^2) / sum(v). The dispersion term depends on the portfolio's deal
-- sizes and on how each model splits credit, so it is computed once per model
-- from revenue booked by the as-of date. Deal sizes are heavily skewed (standard
-- deviation 1.26x the mean), which is why a plain count-based test would
-- overstate how many campaigns genuinely differ.
UPDATE m SET CampaignDispersionUSD = d.Dispersion
FROM dbo.DimAttributionModel m
JOIN (SELECT ModelKey, SUM(v * v) / SUM(v) AS Dispersion
      FROM (SELECT ModelKey, CampaignID, LeadID, SUM(CONVERT(FLOAT, AttributedRevenueUSD)) AS v
            FROM dbo.FactAttributionCredit
            WHERE RevenueDate IS NOT NULL AND IsRevenueAfterAsOf = 0
            GROUP BY ModelKey, CampaignID, LeadID) c
      WHERE v > 0
      GROUP BY ModelKey) d ON d.ModelKey = m.ModelKey;

SELECT m.ModelName,
       COUNT(*)                                 AS CreditRows,
       CONVERT(DECIMAL(18,6), SUM(c.CreditWeight)) AS TotalLeadCredit,
       SUM(c.AttributedRevenueUSD)              AS AttributedRevenueUSD
FROM dbo.FactAttributionCredit c
JOIN dbo.DimAttributionModel m ON m.ModelKey = c.ModelKey
GROUP BY m.ModelName, m.SortOrder
ORDER BY m.SortOrder;
PRINT 'Attribution credit built.';
GO
