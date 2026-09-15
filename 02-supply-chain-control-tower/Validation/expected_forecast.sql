-- Independent expected values for Page 10 - Demand Forecasting.
-- Written against SQL Server directly so the DAX has something external to be
-- checked against. WAPE is used rather than MAPE because 1,096 product-weeks
-- carry zero actual demand, where MAPE is undefined.
SET NOCOUNT ON;
DECLARE @AsOf date = (SELECT CONVERT(date, ConfigValue) FROM analytics.vw_ModelConfig WHERE ConfigKey = 'AsOfDate');

-- 1. Headline forecast quality across all history
SELECT '1_HEADLINE' AS Section,
       SUM(CAST(ActualDemandUnits AS bigint))                                       AS ActualUnits,
       SUM(CAST(BaselineForecastUnits AS bigint))                                   AS ForecastUnits,
       CAST(SUM(ABS(CAST(ActualDemandUnits AS float) - BaselineForecastUnits))
            / NULLIF(SUM(CAST(ActualDemandUnits AS float)), 0) AS decimal(9,6))     AS WAPE,
       CAST(1 - SUM(ABS(CAST(ActualDemandUnits AS float) - BaselineForecastUnits))
            / NULLIF(SUM(CAST(ActualDemandUnits AS float)), 0) AS decimal(9,6))     AS Accuracy,
       CAST((SUM(CAST(BaselineForecastUnits AS float)) - SUM(CAST(ActualDemandUnits AS float)))
            / NULLIF(SUM(CAST(ActualDemandUnits AS float)), 0) AS decimal(9,6))     AS BiasPct,
       SUM(CAST(BaselineForecastUnits AS bigint)) - SUM(CAST(ActualDemandUnits AS bigint)) AS BiasUnits,
       CAST(AVG(ABS(CAST(ActualDemandUnits AS float) - BaselineForecastUnits)) AS decimal(12,6)) AS MAE,
       SUM(CASE WHEN BaselineForecastUnits > ActualDemandUnits THEN 1 ELSE 0 END)   AS OverWeeks,
       SUM(CASE WHEN BaselineForecastUnits < ActualDemandUnits THEN 1 ELSE 0 END)   AS UnderWeeks,
       COUNT(DISTINCT WeekStart)                                                    AS WeeksCovered
FROM analytics.vw_WeeklyDemand;

-- 2. Growth windows: 13 weeks to the as-of date vs the 13 before that
WITH w AS (
    SELECT ProductID,
           SUM(CASE WHEN WeekStart >  DATEADD(day,-91,@AsOf)  AND WeekStart <= @AsOf                  THEN CAST(ActualDemandUnits AS float) END) AS Recent,
           SUM(CASE WHEN WeekStart >  DATEADD(day,-182,@AsOf) AND WeekStart <= DATEADD(day,-91,@AsOf) THEN CAST(ActualDemandUnits AS float) END) AS Prior
    FROM analytics.vw_WeeklyDemand
    GROUP BY ProductID
),
g AS (
    SELECT ProductID, Recent, Prior,
           CASE WHEN Prior IS NULL OR Prior = 0 THEN NULL ELSE (Recent - Prior) / Prior END AS Growth
    FROM w
)
SELECT '2_GROWTH' AS Section,
       (SELECT SUM(Recent) FROM g)                                              AS Recent13W,
       (SELECT SUM(Prior)  FROM g)                                              AS Prior13W,
       CAST(((SELECT SUM(Recent) FROM g) - (SELECT SUM(Prior) FROM g))
            / NULLIF((SELECT SUM(Prior) FROM g), 0) AS decimal(9,6))            AS PortfolioGrowth,
       SUM(CASE WHEN Growth >  0.05 THEN 1 ELSE 0 END)                          AS GrowingProducts,
       SUM(CASE WHEN Growth < -0.05 THEN 1 ELSE 0 END)                          AS DecliningProducts,
       SUM(CASE WHEN Growth IS NOT NULL AND Growth >= -0.05 AND Growth <= 0.05 THEN 1 ELSE 0 END) AS StableProducts,
       COUNT(*)                                                                 AS ProductsWithHistory
FROM g;

-- 3. Forecast accuracy by product category (drives the category column chart)
SELECT '3_BY_CATEGORY' AS Section, p.Category,
       CAST(1 - SUM(ABS(CAST(d.ActualDemandUnits AS float) - d.BaselineForecastUnits))
            / NULLIF(SUM(CAST(d.ActualDemandUnits AS float)), 0) AS decimal(9,6)) AS Accuracy,
       SUM(CAST(d.ActualDemandUnits AS bigint)) AS ActualUnits
FROM analytics.vw_WeeklyDemand d
JOIN analytics.vw_DimProduct p ON p.ProductID = d.ProductID
GROUP BY p.Category
ORDER BY Accuracy DESC;
