/*=============================================================================
  08_create_views.sql

  The analytics contract: the only objects Power BI reads. Each view selects
  explicit columns (never *), so a change to a dbo table cannot silently change
  what the model imports.

  Two views here are more than a projection, and both exist so that a claim on
  a report page is computed from the data on every refresh instead of typed
  into a text box:

    vw_DataQualityMetric    the coverage and consistency figures the Data &
                            Method page shows.
    vw_ChurnDriverStrength  the correlation between each candidate churn driver
                            and whether the customer actually churned, computed
                            in SQL. This is what justifies building a driver
                            view rather than the churn model the brief asked
                            for - and if the data ever changed, the page would
                            change with it rather than keep asserting.
=============================================================================*/
USE SaaSRevenueBI;
GO

CREATE OR ALTER VIEW analytics.vw_DimDate AS
SELECT [Date], [Year], MonthNo, MonthName, MonthShort, [Quarter], QuarterLabel, YearMonth, YearMonthLabel,
       MonthStart, MonthEnd, ISOWeek, DayName, DayOfWeekNo, FinancialYearStart, FinancialYear,
       FinancialMonthNo, FinancialQuarter, FinancialQuarterLabel, FinancialQuarterSort, MonthOffset,
       IsSourceCalendar, IsAfterAsOf, IsMonthComplete
FROM dbo.DimDate;
GO

CREATE OR ALTER VIEW analytics.vw_DimCustomer AS
SELECT CustomerID, CustomerName, SignupDate, CohortMonth, CohortLabel, Industry, Country,
       Segment, SegmentOrder, PlanID, BillingCycle, SubscriptionStatus, IsChurned,
       AcquisitionSource, AttributionType
FROM dbo.DimCustomer;
GO

CREATE OR ALTER VIEW analytics.vw_DimPlan AS
SELECT PlanID, PlanName, MonthlyListPrice, PlanOrder, PlanLabel FROM dbo.DimPlan;
GO

CREATE OR ALTER VIEW analytics.vw_DimSeverity AS
SELECT SeverityName, SeverityOrder, IsUrgent FROM dbo.DimSeverity;
GO

CREATE OR ALTER VIEW analytics.vw_DimMovementType AS
SELECT MovementType, MovementOrder, MovementSign, IsSupported,
       COALESCE(WhyNot, N'') AS WhyNot,
       CASE WHEN IsSupported = 1 THEN N'Occurs in this data' ELSE N'Cannot occur in this data' END AS SupportLabel
FROM dbo.DimMovementType;
GO

CREATE OR ALTER VIEW analytics.vw_DimTenureBand AS
SELECT TenureBand, TenureBandOrder, MinMonths, MaxMonths FROM dbo.DimTenureBand;
GO

CREATE OR ALTER VIEW analytics.vw_DimCohort AS
SELECT CohortMonth, CohortLabel, CohortSort, CohortSize, CohortMRR FROM dbo.DimCohort;
GO

CREATE OR ALTER VIEW analytics.vw_DimTenureMonth AS
SELECT TenureMonth, TenureLabel, TenureYear FROM dbo.DimTenureMonth;
GO

CREATE OR ALTER VIEW analytics.vw_FactSubscription AS
SELECT SubscriptionID, CustomerID, PlanID, StartDate, EndDate, StartMonth, EndMonth, [Status], IsChurned,
       MRR, ARR, BillingCycle, TenureMonths, TenureBand
FROM dbo.FactSubscription;
GO

CREATE OR ALTER VIEW analytics.vw_FactSubscriptionMonth AS
SELECT MonthStart, SubscriptionID, CustomerID, PlanID, MRR, CohortMonth, TenureMonth, IsFirstMonth, IsLastMonth
FROM dbo.FactSubscriptionMonth;
GO

CREATE OR ALTER VIEW analytics.vw_FactMRRMovement AS
SELECT MonthStart, CustomerID, PlanID, MovementType, MRRDelta, PriorMRR, CurrentMRR
FROM dbo.FactMRRMovement;
GO

CREATE OR ALTER VIEW analytics.vw_FactInvoice AS
SELECT InvoiceID, SubscriptionID, CustomerID, InvoiceDate, InvoiceMonth, InvoiceAmount, PaymentDate,
       PaymentStatus, IsFailed, DaysToPay
FROM dbo.FactInvoice;
GO

CREATE OR ALTER VIEW analytics.vw_FactUsageMonthly AS
SELECT MonthStart, CustomerID, LicensedSeats, ActiveUsers, Logins, FeatureAdoptionRate, CriticalErrors
FROM dbo.FactUsageMonthly;
GO

CREATE OR ALTER VIEW analytics.vw_FactSupportTicket AS
SELECT TicketID, CustomerID, OpenedDate, OpenedMonth, Severity, ResolutionHours, [Status], IsResolved, Category
FROM dbo.FactSupportTicket;
GO

CREATE OR ALTER VIEW analytics.vw_FactAcquisition AS
SELECT CustomerID, AcquisitionMonth, AcquisitionCost FROM dbo.FactAcquisition;
GO

CREATE OR ALTER VIEW analytics.vw_ModelConfig AS
SELECT ConfigKey, ConfigValue, Description FROM dbo.ModelConfig;
GO

CREATE OR ALTER VIEW analytics.vw_SecurityUserAccess AS
SELECT UserEmail, [Role], Country FROM dbo.SecurityUserAccess;
GO

/*===========================================================================
  The churn-driver evidence, computed rather than claimed.

  One row per candidate driver, with the Pearson correlation between the driver
  and "did this customer ever churn" (1/0). Features that describe behaviour
  over time are measured over the LAST 90 DAYS a customer was observed - the 90
  days before it churned, or the 90 days before the as-of date if it is still
  running - so a churned customer is judged on how it behaved before leaving.

  Two pairs are deliberately included side by side:

    raw ticket COUNT     vs  tickets per month of tenure
    raw failed-invoice COUNT vs failed invoices / invoices

  because the raw counts are exposure: a customer that stays longer accumulates
  more of everything, so a raw count measures tenure wearing the costume of
  behaviour. Showing both is the point.
===========================================================================*/
CREATE OR ALTER VIEW analytics.vw_ChurnDriverStrength AS
WITH cfg AS (
    SELECT TRY_CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate'
),
base AS (
    SELECT s.CustomerID,
           CONVERT(FLOAT, s.IsChurned) AS Churned,
           COALESCE(NULLIF(s.TenureMonths, 0), 1) AS TenureMonths,
           CONVERT(FLOAT, s.MRR) AS MRR,
           COALESCE(s.EndDate, c.AsOf) AS CutDate
    FROM dbo.FactSubscription s CROSS JOIN cfg c
),
usage90 AS (
    SELECT b.CustomerID,
           AVG(CONVERT(FLOAT, u.FeatureAdoptionRate)) AS Adoption,
           AVG(CONVERT(FLOAT, u.Logins))              AS Logins,
           AVG(CONVERT(FLOAT, u.LicensedSeats))       AS Seats,
           AVG(CONVERT(FLOAT, u.CriticalErrors))      AS Errors,
           CASE WHEN SUM(CONVERT(FLOAT, u.LicensedSeats)) > 0
                THEN SUM(CONVERT(FLOAT, u.ActiveUsers)) / SUM(CONVERT(FLOAT, u.LicensedSeats)) END AS Utilisation
    FROM base b
    JOIN dbo.FactUsageMonthly u
      ON u.CustomerID = b.CustomerID
     AND u.MonthStart <= b.CutDate
     AND u.MonthStart >  DATEADD(DAY, -92, b.CutDate)
    GROUP BY b.CustomerID
),
tickets AS (
    SELECT CustomerID, COUNT(*) AS TicketCount FROM dbo.FactSupportTicket GROUP BY CustomerID
),
invoices AS (
    SELECT CustomerID, COUNT(*) AS InvoiceCount, SUM(CONVERT(FLOAT, IsFailed)) AS FailedCount
    FROM dbo.FactInvoice GROUP BY CustomerID
),
f AS (
    SELECT b.CustomerID, b.Churned, b.MRR,
           CONVERT(FLOAT, b.TenureMonths)                                   AS TenureMonths,
           COALESCE(CONVERT(FLOAT, t.TicketCount), 0)                       AS TicketCount,
           COALESCE(CONVERT(FLOAT, t.TicketCount), 0) / b.TenureMonths      AS TicketRate,
           COALESCE(i.FailedCount, 0)                                       AS FailedCount,
           CASE WHEN i.InvoiceCount > 0 THEN i.FailedCount / i.InvoiceCount END AS FailureRate,
           CONVERT(FLOAT, a.AcquisitionCost)                                AS CAC,
           u.Adoption, u.Logins, u.Seats, u.Errors, u.Utilisation
    FROM base b
    LEFT JOIN tickets  t ON t.CustomerID = b.CustomerID
    LEFT JOIN invoices i ON i.CustomerID = b.CustomerID
    LEFT JOIN usage90  u ON u.CustomerID = b.CustomerID
    JOIN dbo.FactAcquisition a ON a.CustomerID = b.CustomerID
),
d AS (
    SELECT N'Plan price point (MRR)'          AS Driver, 1 AS DriverOrder, N'Commercial'  AS DriverGroup, 0 AS IsExposure, MRR         AS x, Churned AS y FROM f
    UNION ALL SELECT N'Support contact rate (per month)', 2, N'Behaviour', 0, TicketRate,  Churned FROM f
    UNION ALL SELECT N'Feature adoption (last 90 days)',          3, N'Product',   0, Adoption,    Churned FROM f
    UNION ALL SELECT N'Seat utilisation (active / licensed)',     4, N'Product',   0, Utilisation, Churned FROM f
    UNION ALL SELECT N'Logins (last 90 days)',                    5, N'Product',   0, Logins,      Churned FROM f
    UNION ALL SELECT N'Licensed seats',                           6, N'Product',   0, Seats,       Churned FROM f
    UNION ALL SELECT N'Critical errors (last 90 days)',           7, N'Product',   0, Errors,      Churned FROM f
    UNION ALL SELECT N'Payment failure rate',                     8, N'Billing',   0, FailureRate, Churned FROM f
    UNION ALL SELECT N'Acquisition cost',                         9, N'Commercial',0, CAC,         Churned FROM f
    UNION ALL SELECT N'Raw ticket count',                        10, N'Behaviour', 1, TicketCount, Churned FROM f
    UNION ALL SELECT N'Raw failed-invoice count',                11, N'Billing',   1, FailedCount, Churned FROM f
),
agg AS (
    SELECT Driver, DriverOrder, DriverGroup, IsExposure,
           COUNT(*)      AS n,
           SUM(x)        AS Sx,  SUM(y)      AS Sy,
           SUM(x * x)    AS Sxx, SUM(y * y)  AS Syy, SUM(x * y) AS Sxy
    FROM d
    WHERE x IS NOT NULL
    GROUP BY Driver, DriverOrder, DriverGroup, IsExposure
)
SELECT Driver, DriverOrder, DriverGroup,
       CONVERT(BIT, IsExposure) AS IsRawCount,
       n AS Customers,
       CONVERT(DECIMAL(9, 4),
           CASE WHEN (n * Sxx - Sx * Sx) > 0 AND (n * Syy - Sy * Sy) > 0
                THEN (n * Sxy - Sx * Sy) / (SQRT(n * Sxx - Sx * Sx) * SQRT(n * Syy - Sy * Sy)) END
       ) AS Correlation
FROM agg;
GO

/*===========================================================================
  Data-quality figures for the Data & Method page, computed live from dbo so
  they cannot drift from the data. Each one is also checked in 09.
===========================================================================*/
CREATE OR ALTER VIEW analytics.vw_DataQualityMetric AS
WITH cfg AS (SELECT TRY_CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate'),
lastmonth AS (SELECT MAX(MonthStart) AS m FROM dbo.FactSubscriptionMonth)
SELECT 1 AS SortOrder, N'Subscriptions per customer (maximum)' AS Metric,
       CONVERT(DECIMAL(19, 4), (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM dbo.FactSubscription GROUP BY CustomerID) q)) AS MetricValue,
       N'subscriptions' AS Unit
UNION ALL SELECT 2, N'Distinct invoice amounts per subscription (maximum)',
       CONVERT(DECIMAL(19, 4), (SELECT MAX(n) FROM (SELECT COUNT(DISTINCT InvoiceAmount) AS n FROM dbo.FactInvoice GROUP BY SubscriptionID) q)), N'amounts'
UNION ALL SELECT 3, N'Expansion movements recorded',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Expansion')), N'movements'
UNION ALL SELECT 4, N'Contraction movements recorded',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Contraction')), N'movements'
UNION ALL SELECT 5, N'Reactivation movements recorded',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Reactivation')), N'movements'
UNION ALL SELECT 6, N'Months at the end of the file with no new business',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.DimDate d
            WHERE d.[Date] = d.MonthStart AND d.MonthStart > (SELECT MAX(StartMonth) FROM dbo.FactSubscription)
              AND d.MonthStart <= (SELECT m FROM lastmonth))), N'months'
UNION ALL SELECT 7, N'Usage coverage of paying customers, latest month',
       CONVERT(DECIMAL(19, 6),
           (SELECT COUNT(DISTINCT u.CustomerID) * 1.0 FROM dbo.FactUsageMonthly u WHERE u.MonthStart = (SELECT m FROM lastmonth))
         / (SELECT COUNT(DISTINCT sm.CustomerID) * 1.0 FROM dbo.FactSubscriptionMonth sm WHERE sm.MonthStart = (SELECT m FROM lastmonth))), N'share'
UNION ALL SELECT 8, N'Unresolved tickets carrying a resolution time',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactSupportTicket WHERE IsResolved = 0)), N'tickets'
UNION ALL SELECT 9, N'Invoices dated before their subscription started',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                                WHERE i.InvoiceDate < s.StartDate)), N'invoices'
UNION ALL SELECT 10, N'Failed invoices as a share of all invoices',
       CONVERT(DECIMAL(19, 6), (SELECT SUM(CONVERT(DECIMAL(19, 6), IsFailed)) / COUNT(*) FROM dbo.FactInvoice)), N'share'
UNION ALL SELECT 11, N'Customers acquired for under $100',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.FactAcquisition WHERE AcquisitionCost < 100)), N'customers'
UNION ALL SELECT 12, N'Customers that have ever churned',
       CONVERT(DECIMAL(19, 6), (SELECT SUM(CONVERT(DECIMAL(19, 6), IsChurned)) / COUNT(*) FROM dbo.FactSubscription)), N'share'
UNION ALL SELECT 13, N'Calendar days added beyond the supplied calendar',
       CONVERT(DECIMAL(19, 4), (SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 0)), N'days'
UNION ALL SELECT 14, N'Customers whose licensed seats change over time',
       CONVERT(DECIMAL(19, 6), (SELECT COUNT(*) * 1.0 FROM (SELECT CustomerID FROM dbo.FactUsageMonthly GROUP BY CustomerID HAVING COUNT(DISTINCT LicensedSeats) > 1) q)
                             / (SELECT COUNT(DISTINCT CustomerID) * 1.0 FROM dbo.FactUsageMonthly)), N'share'
UNION ALL SELECT 15, N'Strongest usage correlation with churn (absolute)',
       CONVERT(DECIMAL(19, 6), (SELECT MAX(ABS(Correlation)) FROM analytics.vw_ChurnDriverStrength WHERE DriverGroup = N'Product')), N'r';
GO
PRINT 'Analytics views created (19).';
GO
