SET NOCOUNT ON;
DECLARE @AsOf date = (SELECT CONVERT(date, ConfigValue) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate');
DECLARE @WinStart date = DATEADD(day,-91,@AsOf);

-- ABC : cumulative revenue share, ties inclusive (matches DAX [@Rev] >= ThisRev)
WITH rev AS (
    SELECT p.ProductID, SUM(s.Revenue) AS Rev
    FROM analytics.vw_DimProduct p
    JOIN analytics.vw_SalesOrders s ON s.ProductID = p.ProductID
    GROUP BY p.ProductID
),
abc AS (
    SELECT ProductID, Rev,
           SUM(Rev) OVER (ORDER BY Rev DESC RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(Rev) OVER () AS CumPct
    FROM rev
),
abc2 AS (
    SELECT ProductID, Rev,
           CASE WHEN CumPct <= 0.80 THEN 'A' WHEN CumPct <= 0.95 THEN 'B' ELSE 'C' END AS ABCClass
    FROM abc
),
-- XYZ : product-level weekly totals in the 13-week window
wk AS (
    SELECT ProductID, WeekStart, SUM(ActualDemandUnits) AS Units
    FROM analytics.vw_WeeklyDemand
    WHERE WeekStart > @WinStart AND WeekStart <= @AsOf
    GROUP BY ProductID, WeekStart
),
cv AS (
    SELECT ProductID,
           AVG(CAST(Units AS float)) AS MeanU,
           STDEV(CAST(Units AS float)) AS SdU,
           CASE WHEN AVG(CAST(Units AS float)) = 0 THEN NULL
                ELSE STDEV(CAST(Units AS float)) / AVG(CAST(Units AS float)) END AS CV
    FROM wk GROUP BY ProductID
),
thr AS (
    SELECT DISTINCT
        PERCENTILE_CONT(1.0/3) WITHIN GROUP (ORDER BY CV) OVER () AS P33,
        PERCENTILE_CONT(2.0/3) WITHIN GROUP (ORDER BY CV) OVER () AS P66
    FROM cv WHERE CV IS NOT NULL
),
xyz AS (
    SELECT c.ProductID, c.CV,
           CASE WHEN c.CV <= t.P33 THEN 'X' WHEN c.CV <= t.P66 THEN 'Y' ELSE 'Z' END AS XYZClass
    FROM cv c CROSS JOIN thr t WHERE c.CV IS NOT NULL
),
full_ AS (
    SELECT a.ProductID, a.Rev, a.ABCClass, x.XYZClass
    FROM abc2 a LEFT JOIN xyz x ON x.ProductID = a.ProductID
)
SELECT '1_ABC_DIST' AS Section, ABCClass AS K1, '' AS K2,
       COUNT(*) AS Products, CAST(100.0*SUM(Rev)/SUM(SUM(Rev)) OVER () AS decimal(6,2)) AS RevPct
FROM full_ GROUP BY ABCClass
UNION ALL
SELECT '2_XYZ_DIST', ISNULL(XYZClass,'(Unclassified)'), '', COUNT(*), NULL FROM full_ GROUP BY XYZClass
UNION ALL
SELECT '3_MATRIX_CELL', ABCClass, XYZClass, COUNT(*), NULL FROM full_ WHERE XYZClass IS NOT NULL GROUP BY ABCClass, XYZClass
UNION ALL
SELECT '4_MATRIX_ROWTOT', ABCClass, 'Total', COUNT(*), NULL FROM full_ WHERE XYZClass IS NOT NULL GROUP BY ABCClass
UNION ALL
SELECT '5_MATRIX_COLTOT', 'Total', XYZClass, COUNT(*), NULL FROM full_ WHERE XYZClass IS NOT NULL GROUP BY XYZClass
UNION ALL
SELECT '6_MATRIX_GRAND', 'Total', 'Total', COUNT(*), NULL FROM full_ WHERE XYZClass IS NOT NULL
UNION ALL
SELECT '7_THRESHOLDS', 'P33', 'P66', NULL, NULL
ORDER BY Section, K1, K2;

SELECT 'THRESHOLDS' AS T, CAST(P33 AS decimal(10,6)) AS P33, CAST(P66 AS decimal(10,6)) AS P66
FROM (SELECT DISTINCT
        PERCENTILE_CONT(1.0/3) WITHIN GROUP (ORDER BY CV) OVER () AS P33,
        PERCENTILE_CONT(2.0/3) WITHIN GROUP (ORDER BY CV) OVER () AS P66
      FROM (SELECT ProductID,
                   CASE WHEN AVG(CAST(ActualDemandUnits AS float))=0 THEN NULL
                        ELSE STDEV(CAST(ActualDemandUnits AS float))/AVG(CAST(ActualDemandUnits AS float)) END AS CV
            FROM (SELECT ProductID, WeekStart, SUM(ActualDemandUnits) AS ActualDemandUnits
                  FROM analytics.vw_WeeklyDemand
                  WHERE WeekStart > DATEADD(day,-91,(SELECT CONVERT(date,ConfigValue) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate'))
                    AND WeekStart <= (SELECT CONVERT(date,ConfigValue) FROM analytics.vw_ModelConfig WHERE ConfigKey='AsOfDate')
                  GROUP BY ProductID, WeekStart) w
            GROUP BY ProductID) c
      WHERE CV IS NOT NULL) z;
