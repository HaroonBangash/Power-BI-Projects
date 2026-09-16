/*=============================================================================
  05_load_dimensions.sql

  Types and loads the dimensions.

  Two things are done here rather than later:

  * The calendar is EXTENDED past the data. The supplied dim_date stops on the
    as-of date, 31 Aug 2026, which is two months into financial year 2027 - so
    a year-to-date or a full-year comparison would silently run off the end of
    the date table. Days are added to 30 Jun 2027 to complete FY27, flagged
    IsSourceCalendar = 0 and IsAfterAsOf = 1 so nothing counts them as data.

  * Acquisition SOURCE and ATTRIBUTION move onto the customer, where they
    belong: they describe the customer, not an event. The COST stays a fact,
    because it is a number that sums.

  The financial year starts in July (the source's own FinancialYearStart is
  2021 for January 2022), so FY27 runs Jul 2026 - Jun 2027.
=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT MAX(TRY_CONVERT(DATE, [Date], 23)) FROM stg.dim_date);
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);
-- The financial year containing the as-of date ends on the following 30 June.
DECLARE @CalendarEnd DATE = DATEFROMPARTS(CASE WHEN MONTH(@AsOf) >= 7 THEN YEAR(@AsOf) + 1 ELSE YEAR(@AsOf) END, 6, 30);

INSERT dbo.ModelConfig (ConfigKey, ConfigValue, Description) VALUES
 (N'AsOfDate',            CONVERT(NVARCHAR(10), @AsOf, 23),
  N'The last day the data describes. Every point-in-time figure - MRR, customer count, open tickets - is stated ON this date.'),
 (N'CalendarEnd',         CONVERT(NVARCHAR(10), @CalendarEnd, 23),
  N'The calendar is extended to the end of the financial year containing the as-of date, so year-to-date logic has a complete year to work in.'),
 (N'LastNewBusinessDate', N'2026-06-30',
  N'The newest subscription start in the source. Churn runs two months beyond it, so the final two months show losses and no wins - an artefact of the extract, not a trend.'),
 (N'GrossMarginAssumption', N'0.75',
  N'ASSUMPTION, not data. There is no cost of service anywhere in the source, so lifetime value and CAC payback cannot be derived - only modelled. 75% is a stated placeholder and is shown beside every figure that uses it.'),
 (N'ReportingCurrency',   N'USD',
  N'All amounts are in one currency; the source carries no currency column and no exchange rates.'),
 (N'ChurnDefinition',     N'Subscription end date',
  N'A customer is churned in the month its subscription end date falls. The status column and the end dates never disagree in this source, so either gives the same answer.');
GO

/* ------------------------------------------------------------------ DimDate */
DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @CalendarEnd DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'CalendarEnd');
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);
DECLARE @Start DATE = (SELECT MIN(TRY_CONVERT(DATE, [Date], 23)) FROM stg.dim_date);

;WITH Days AS (
    SELECT @Start AS d
    UNION ALL
    SELECT DATEADD(DAY, 1, d) FROM Days WHERE d < @CalendarEnd
),
Source AS (SELECT DISTINCT TRY_CONVERT(DATE, [Date], 23) AS d FROM stg.dim_date)
INSERT dbo.DimDate ([Date], [Year], MonthNo, MonthName, MonthShort, [Quarter], QuarterLabel, YearMonth,
                    YearMonthLabel, MonthStart, MonthEnd, ISOWeek, DayName, DayOfWeekNo, FinancialYearStart,
                    FinancialYear, FinancialMonthNo, FinancialQuarter, FinancialQuarterLabel,
                    FinancialQuarterSort, MonthOffset, IsSourceCalendar, IsAfterAsOf, IsMonthComplete)
SELECT
    d.d,
    YEAR(d.d),
    MONTH(d.d),
    DATENAME(MONTH, d.d),
    LEFT(DATENAME(MONTH, d.d), 3),
    DATEPART(QUARTER, d.d),
    CONCAT(N'Q', DATEPART(QUARTER, d.d), N' ', YEAR(d.d)),
    YEAR(d.d) * 100 + MONTH(d.d),
    CONCAT(LEFT(DATENAME(MONTH, d.d), 3), N' ', YEAR(d.d)),
    DATEFROMPARTS(YEAR(d.d), MONTH(d.d), 1),
    EOMONTH(d.d),
    DATEPART(ISO_WEEK, d.d),
    DATENAME(WEEKDAY, d.d),
    ((DATEPART(WEEKDAY, d.d) + @@DATEFIRST - 2) % 7) + 1,
    fy.FyStart,
    CONCAT(N'FY', RIGHT(CONVERT(NVARCHAR(4), fy.FyStart + 1), 2)),
    fy.FyMonth,
    ((fy.FyMonth - 1) / 3) + 1,
    CONCAT(N'FY', RIGHT(CONVERT(NVARCHAR(4), fy.FyStart + 1), 2), N' Q', ((fy.FyMonth - 1) / 3) + 1),
    (fy.FyStart + 1) * 10 + (((fy.FyMonth - 1) / 3) + 1),
    DATEDIFF(MONTH, @AsOfMonth, DATEFROMPARTS(YEAR(d.d), MONTH(d.d), 1)),
    CASE WHEN s.d IS NULL THEN 0 ELSE 1 END,
    CASE WHEN d.d > @AsOf THEN 1 ELSE 0 END,
    CASE WHEN EOMONTH(d.d) <= @AsOf THEN 1 ELSE 0 END
FROM Days d
CROSS APPLY (SELECT CASE WHEN MONTH(d.d) >= 7 THEN YEAR(d.d) ELSE YEAR(d.d) - 1 END AS FyStart,
                    CASE WHEN MONTH(d.d) >= 7 THEN MONTH(d.d) - 6 ELSE MONTH(d.d) + 6 END AS FyMonth) fy
LEFT JOIN Source s ON s.d = d.d
OPTION (MAXRECURSION 0);
GO

/* ------------------------------------------------------------------ DimPlan */
INSERT dbo.DimPlan (PlanID, PlanName, MonthlyListPrice, PlanOrder, PlanLabel)
SELECT p.PlanID, p.PlanName, p.MonthlyListPrice,
       CONVERT(TINYINT, ROW_NUMBER() OVER (ORDER BY p.MonthlyListPrice)),
       CONCAT(p.PlanName, N' ($', FORMAT(p.MonthlyListPrice, N'N0'), N'/mo)')
FROM (SELECT PlanID, PlanName, TRY_CONVERT(DECIMAL(19, 2), MonthlyListPrice) AS MonthlyListPrice
      FROM stg.dim_plan) p;
GO

/* -------------------------------------------------------------- DimCustomer */
INSERT dbo.DimCustomer (CustomerID, CustomerName, SignupDate, CohortMonth, CohortLabel, Industry, Country,
                        Segment, SegmentOrder, PlanID, BillingCycle, SubscriptionStatus, IsChurned,
                        AcquisitionSource, AttributionType)
SELECT c.CustomerID, c.CustomerName,
       TRY_CONVERT(DATE, c.SignupDate, 23),
       DATEFROMPARTS(YEAR(TRY_CONVERT(DATE, c.SignupDate, 23)), MONTH(TRY_CONVERT(DATE, c.SignupDate, 23)), 1),
       CONCAT(LEFT(DATENAME(MONTH, TRY_CONVERT(DATE, c.SignupDate, 23)), 3), N' ',
              YEAR(TRY_CONVERT(DATE, c.SignupDate, 23))),
       c.Industry, c.Country, c.Segment,
       CASE c.Segment WHEN N'SMB' THEN 1 WHEN N'Mid-Market' THEN 2 WHEN N'Enterprise' THEN 3 ELSE 9 END,
       s.PlanID, s.BillingCycle, s.[Status],
       CASE WHEN NULLIF(s.EndDate, N'') IS NULL THEN 0 ELSE 1 END,
       a.AcquisitionSource, a.AttributionType
FROM stg.dim_customer c
JOIN stg.fact_customer_acquisition a ON a.CustomerID = c.CustomerID
JOIN stg.fact_subscriptions s ON s.CustomerID = c.CustomerID;
GO

/* ------------------------------------------------- small ordered dimensions */
INSERT dbo.DimSeverity (SeverityName, SeverityOrder, IsUrgent) VALUES
 (N'Low', 1, 0), (N'Medium', 2, 0), (N'High', 3, 1), (N'Critical', 4, 1);

-- Order is the order a waterfall reads: what was added, then what was lost.
INSERT dbo.DimMovementType (MovementType, MovementOrder, MovementSign, IsSupported, WhyNot) VALUES
 (N'New',          1,  1, 1, NULL),
 (N'Expansion',    2,  1, 0, N'MRR is one static value per subscription, so there is no larger MRR to move up to.'),
 (N'Reactivation', 3,  1, 0, N'One subscription per customer, ever - so nobody can leave and come back.'),
 (N'Contraction',  4, -1, 0, N'Same as expansion: there is no second MRR value to fall to.'),
 (N'Churn',        5, -1, 1, NULL);

INSERT dbo.DimTenureBand (TenureBand, TenureBandOrder, MinMonths, MaxMonths) VALUES
 (N'0-6 months',   1,  0,  5),
 (N'6-12 months',  2,  6, 11),
 (N'1-2 years',    3, 12, 23),
 (N'2-3 years',    4, 24, 35),
 (N'3 years+',     5, 36, 999);
GO

/* --------------------------------------------------------------- security */
INSERT dbo.SecurityUserAccess (UserEmail, [Role], Country)
SELECT LOWER(LTRIM(RTRIM(UserEmail))), [Role], LTRIM(RTRIM(Country)) FROM stg.security_user_access;
GO

DECLARE @msg NVARCHAR(400) = CONCAT(
    N'Dimensions loaded: DimDate ', (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.DimDate),
    N' days (', (SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 0), N' added beyond the source calendar), DimCustomer ',
    (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.DimCustomer), N', DimPlan ',
    (SELECT COUNT(*) FROM dbo.DimPlan), N', security users ',
    (SELECT COUNT(*) FROM dbo.SecurityUserAccess), N'.');
PRINT @msg;
GO
