/*=============================================================================
  07_build_movement.sql

  The two derived tables the whole project rests on.

  ---------------------------------------------------------------------------
  1. FactSubscriptionMonth - the monthly snapshot
  ---------------------------------------------------------------------------
  One row per subscription per month in which it is live AT MONTH END:

      StartDate <= month end  AND  (EndDate IS NULL OR EndDate > month end)

  MRR is a STOCK, not a flow: it is what is on the books at a moment, so it is
  measured at a moment - the last day of the month - and never summed over
  time. Holding it as a snapshot means a cohort retention matrix is a pivot of
  a stored column instead of a window function evaluated in DAX at query time.

  A subscription ending on the 30th is NOT live at the 31st, so it counts as
  churned in that month. Phase 1 checked that no subscription starts and ends
  inside one month (the shortest lives 90 days), so every subscription appears
  in the snapshot at least once and nothing is lost by this rule.

  ---------------------------------------------------------------------------
  2. FactMRRMovement - the movement ledger
  ---------------------------------------------------------------------------
  One row per customer per month in which its MRR CHANGED, classified by
  comparing the month against the one before it:

      prior = 0, current > 0, first ever month  -> New
      prior = 0, current > 0, has been live before -> Reactivation
      prior > 0, current = 0                    -> Churn
      current > prior > 0                       -> Expansion
      0 < current < prior                       -> Contraction

  All five are DERIVED, not asserted. That matters because the Phase 1 audit
  found that three of them cannot occur in this source: MRR is a single static
  value per subscription and every customer has exactly one subscription ever.
  The classification still runs, and the report shows the three empty
  components rather than quietly leaving them out of the waterfall - a reader
  can see that the logic exists and that the data has nothing to put in it.

  The identity this must satisfy, checked in 09:

      MRR(month) = MRR(month - 1) + SUM(MRRDelta in month)

=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);

-- Re-runnable on its own, not only as part of a fresh build.
DELETE dbo.FactMRRMovement;
DELETE dbo.FactSubscriptionMonth;
DELETE dbo.DimTenureMonth;
DELETE dbo.DimCohort;

/* --------------------------------- 0. the two axes of the retention matrix */
INSERT dbo.DimCohort (CohortMonth, CohortLabel, CohortSort, CohortSize, CohortMRR)
SELECT s.StartMonth,
       CONCAT(LEFT(DATENAME(MONTH, s.StartMonth), 3), N' ', YEAR(s.StartMonth)),
       YEAR(s.StartMonth) * 100 + MONTH(s.StartMonth),
       COUNT(*), SUM(s.MRR)
FROM dbo.FactSubscription s
GROUP BY s.StartMonth;

-- One row for every tenure month that can occur: month 0 (the signup month) to
-- the longest life in the data. The bound is computed FIRST: a recursive CTE may
-- not carry an aggregate in its recursive half.
DECLARE @MaxTenure INT = (
    SELECT MAX(DATEDIFF(MONTH, StartMonth,
                        CASE WHEN EndDate IS NULL THEN @AsOfMonth ELSE DATEADD(MONTH, -1, EndMonth) END))
    FROM dbo.FactSubscription);

;WITH n AS (
    SELECT 0 AS TenureMonth
    UNION ALL
    SELECT TenureMonth + 1 FROM n WHERE TenureMonth < @MaxTenure
)
INSERT dbo.DimTenureMonth (TenureMonth, TenureLabel, TenureYear)
SELECT TenureMonth, CONCAT(N'M', TenureMonth), TenureMonth / 12
FROM n
OPTION (MAXRECURSION 0);
GO

/* ------------------------------------------------- 1. the monthly snapshot */
DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);

;WITH Months AS (
    SELECT DISTINCT MonthStart, MonthEnd
    FROM dbo.DimDate
    WHERE MonthStart <= @AsOfMonth
)
INSERT dbo.FactSubscriptionMonth (MonthStart, SubscriptionID, CustomerID, PlanID, MRR, CohortMonth,
                                  TenureMonth, IsFirstMonth, IsLastMonth)
SELECT m.MonthStart, s.SubscriptionID, s.CustomerID, s.PlanID, s.MRR,
       s.StartMonth,
       DATEDIFF(MONTH, s.StartMonth, m.MonthStart),
       CASE WHEN m.MonthStart = s.StartMonth THEN 1 ELSE 0 END,
       -- the last month this subscription is live: the month before it ends, or
       -- the as-of month while it is still running
       CASE WHEN m.MonthStart = CASE WHEN s.EndDate IS NULL THEN @AsOfMonth
                                     ELSE DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(s.EndDate), MONTH(s.EndDate), 1))
                                END
            THEN 1 ELSE 0 END
FROM dbo.FactSubscription s
JOIN Months m
  ON  s.StartDate <= m.MonthEnd
  AND (s.EndDate IS NULL OR s.EndDate > m.MonthEnd);
GO

DROP INDEX IF EXISTS IX_SubMonth_Cohort ON dbo.FactSubscriptionMonth;
DROP INDEX IF EXISTS IX_SubMonth_Customer ON dbo.FactSubscriptionMonth;
CREATE INDEX IX_SubMonth_Cohort   ON dbo.FactSubscriptionMonth (CohortMonth, TenureMonth) INCLUDE (MRR, CustomerID);
CREATE INDEX IX_SubMonth_Customer ON dbo.FactSubscriptionMonth (CustomerID, MonthStart)   INCLUDE (MRR);
GO

/* ------------------------------------------------- 2. the movement ledger */
DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);

;WITH Snap AS (
    SELECT MonthStart, CustomerID, MIN(PlanID) AS PlanID, SUM(MRR) AS MRR
    FROM dbo.FactSubscriptionMonth
    GROUP BY MonthStart, CustomerID
),
FirstMonth AS (
    SELECT CustomerID, MIN(MonthStart) AS FirstLiveMonth FROM Snap GROUP BY CustomerID
),
-- Every month a customer is live, PLUS the month after each - so the month a
-- customer disappears is still considered, which is where churn is found.
Candidates AS (
    SELECT MonthStart, CustomerID FROM Snap
    UNION
    SELECT DATEADD(MONTH, 1, MonthStart), CustomerID FROM Snap
),
Compared AS (
    SELECT c.MonthStart, c.CustomerID,
           COALESCE(cur.MRR, 0)  AS CurrentMRR,
           COALESCE(prv.MRR, 0)  AS PriorMRR,
           COALESCE(cur.PlanID, prv.PlanID) AS PlanID,
           f.FirstLiveMonth
    FROM Candidates c
    JOIN FirstMonth f ON f.CustomerID = c.CustomerID
    LEFT JOIN Snap cur ON cur.CustomerID = c.CustomerID AND cur.MonthStart = c.MonthStart
    LEFT JOIN Snap prv ON prv.CustomerID = c.CustomerID AND prv.MonthStart = DATEADD(MONTH, -1, c.MonthStart)
    WHERE c.MonthStart <= @AsOfMonth
)
INSERT dbo.FactMRRMovement (MonthStart, CustomerID, PlanID, MovementType, MRRDelta, PriorMRR, CurrentMRR)
SELECT MonthStart, CustomerID, PlanID,
       CASE WHEN PriorMRR = 0 AND CurrentMRR > 0 AND MonthStart = FirstLiveMonth THEN N'New'
            WHEN PriorMRR = 0 AND CurrentMRR > 0                                 THEN N'Reactivation'
            WHEN PriorMRR > 0 AND CurrentMRR = 0                                 THEN N'Churn'
            WHEN CurrentMRR > PriorMRR                                           THEN N'Expansion'
            ELSE N'Contraction'
       END,
       CurrentMRR - PriorMRR, PriorMRR, CurrentMRR
FROM Compared
WHERE CurrentMRR <> PriorMRR;
GO

DROP INDEX IF EXISTS IX_Movement_Month ON dbo.FactMRRMovement;
CREATE INDEX IX_Movement_Month ON dbo.FactMRRMovement (MonthStart, MovementType) INCLUDE (MRRDelta, CustomerID);
GO

DECLARE @msg NVARCHAR(600) = CONCAT(
    N'Derived: DimCohort ', (SELECT COUNT(*) FROM dbo.DimCohort),
    N' cohorts, DimTenureMonth ', (SELECT COUNT(*) FROM dbo.DimTenureMonth),
    N'; FactSubscriptionMonth ', (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactSubscriptionMonth),
    N' rows over ', (SELECT COUNT(DISTINCT MonthStart) FROM dbo.FactSubscriptionMonth), N' months; FactMRRMovement ',
    (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactMRRMovement), N' rows (',
    (SELECT STRING_AGG(CONCAT(MovementType, N' ', FORMAT(n, N'N0')), N', ') WITHIN GROUP (ORDER BY MovementType)
     FROM (SELECT MovementType, COUNT(*) AS n FROM dbo.FactMRRMovement GROUP BY MovementType) x), N').');
PRINT @msg;
GO
