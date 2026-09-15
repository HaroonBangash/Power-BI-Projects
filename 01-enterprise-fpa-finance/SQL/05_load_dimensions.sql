/*=============================================================================
  05_load_dimensions.sql

  Configuration, calendar, dimensions, exchange rates and security.

  The as-of date is DERIVED from the data - the last general-ledger day - never
  GETDATE(), so the report means the same thing whenever it is refreshed.
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

-------------------------------------------------------------------- config ---
DECLARE @AsOf DATE = (SELECT MAX(CONVERT(DATE, [Date], 23)) FROM stg.fact_gl);
DECLARE @FYStart SMALLINT = CASE WHEN MONTH(@AsOf) >= 7 THEN YEAR(@AsOf) ELSE YEAR(@AsOf) - 1 END;

INSERT dbo.ModelConfig (ConfigKey, ConfigValue, Description) VALUES
 (N'AsOfDate', CONVERT(NVARCHAR(10), @AsOf, 23),
  N'Last general-ledger day. Every figure, balance and ageing is stated as of this date; later-dated payments are open on it.'),
 (N'ReportingCurrency', N'AUD', N'Group reporting currency. Budget, forecast, AR, AP and cash are supplied in AUD; the ledger is translated.'),
 (N'FxTranslation', N'Monthly average',
  N'P&L actuals are translated at the mean of the month''s daily rates (IAS 21 average-rate practice). AUD is fixed at 1.'),
 (N'FinancialYearStartMonth', N'7', N'Financial year runs July to June: FY26 = 1 Jul 2025 - 30 Jun 2026.'),
 (N'CurrentFinancialYear', CONCAT(N'FY', RIGHT(CONVERT(NCHAR(4), @FYStart + 1), 2)), N'Financial year containing the as-of date.'),
 (N'LastCompleteFinancialYear', CONCAT(N'FY', RIGHT(CONVERT(NCHAR(4), @FYStart), 2)), N'Most recent financial year ended on or before the as-of date.'),
 (N'DsoWindowDays', N'90', N'Days of invoicing (or billing) in the DSO / DPO denominator: balance / last-90-day flow x 90.'),
 (N'ProjectionBasisMonths', N'12',
  N'Scenario outlook: months after the as-of date are projected at the average of the trailing 12 months of actuals, then flexed by the scenario drivers.');

-------------------------------------------------------------------- calendar ---
-- 2022-01-01 to 2027-06-30 (end of FY27): the supplied calendar ends on the
-- as-of date, but AR and AP due and payment dates run to January 2027.
DECLARE @Start DATE = '2022-01-01', @End DATE = '2027-06-30';
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);

WITH n AS (
    SELECT TOP (DATEDIFF(DAY, @Start, @End) + 1) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS i
    FROM sys.all_objects a CROSS JOIN sys.all_objects b),
c AS (
    SELECT d.[Date], YEAR(d.[Date]) AS y, MONTH(d.[Date]) AS mo,
           CASE WHEN MONTH(d.[Date]) >= 7 THEN YEAR(d.[Date]) ELSE YEAR(d.[Date]) - 1 END AS fys,
           (MONTH(d.[Date]) + 5) % 12 + 1 AS fmo
    FROM (SELECT DATEADD(DAY, i, @Start) AS [Date] FROM n) d)
INSERT dbo.DimDate ([Date], [Year], MonthNo, MonthName, MonthShort, [Quarter], QuarterLabel, YearMonth, YearMonthLabel,
                    MonthStart, MonthEnd, ISOWeek, DayName, DayOfWeekNo, FinancialYearStart, FinancialYear,
                    FinancialMonthNo, FinancialQuarter, FinancialQuarterLabel, FinancialQuarterSort, MonthOffset,
                    FinancialYearOffset, IsSourceCalendar, IsAfterAsOf, IsMonthComplete, IsFinancialYearComplete)
SELECT c.[Date], c.y, c.mo, DATENAME(MONTH, c.[Date]), LEFT(DATENAME(MONTH, c.[Date]), 3), DATEPART(QUARTER, c.[Date]),
       CONCAT(c.y, N' Q', DATEPART(QUARTER, c.[Date])), c.y * 100 + c.mo,
       CONCAT(LEFT(DATENAME(MONTH, c.[Date]), 3), N' ', c.y),
       DATEFROMPARTS(c.y, c.mo, 1), EOMONTH(c.[Date]), DATEPART(ISO_WEEK, c.[Date]), DATENAME(WEEKDAY, c.[Date]),
       (DATEPART(WEEKDAY, c.[Date]) + @@DATEFIRST - 2) % 7 + 1,
       c.fys, CONCAT(N'FY', RIGHT(CONVERT(NCHAR(4), c.fys + 1), 2)), c.fmo, (c.fmo - 1) / 3 + 1,
       CONCAT(N'FY', RIGHT(CONVERT(NCHAR(4), c.fys + 1), 2), N' Q', (c.fmo - 1) / 3 + 1),
       (c.fys + 1) * 10 + (c.fmo - 1) / 3 + 1,
       DATEDIFF(MONTH, @AsOfMonth, c.[Date]), c.fys - @FYStart,
       CASE WHEN s.[Date] IS NULL THEN 0 ELSE 1 END,
       CASE WHEN c.[Date] > @AsOf THEN 1 ELSE 0 END,
       CASE WHEN EOMONTH(c.[Date]) <= @AsOf THEN 1 ELSE 0 END,
       CASE WHEN DATEFROMPARTS(c.fys + 1, 6, 30) <= @AsOf THEN 1 ELSE 0 END
FROM c
LEFT JOIN (SELECT CONVERT(DATE, [Date], 23) AS [Date] FROM stg.dim_date) s ON s.[Date] = c.[Date];

---------------------------------------------------------------- dimensions ---
INSERT dbo.DimCurrency (CurrencyCode, IsReportingCurrency)
SELECT DISTINCT CONVERT(NCHAR(3), LocalCurrency), CASE WHEN LocalCurrency = N'AUD' THEN 1 ELSE 0 END
FROM stg.dim_entity;

INSERT dbo.DimEntity (EntityID, EntityName, Region, LocalCurrency)
SELECT EntityID, EntityName, Region, LocalCurrency FROM stg.dim_entity;

INSERT dbo.DimDepartment (DepartmentID, DepartmentName)
SELECT DepartmentID, DepartmentName FROM stg.dim_department;

-- Revenue carries NaturalSign -1: a credit balance presented as a positive number.
INSERT dbo.DimAccount (AccountCode, AccountName, AccountGroup, [Statement], GroupOrder, NaturalSign, IsIncome,
                       IsOperating, IsBudgeted, AccountLabel)
SELECT a.AccountCode, a.AccountName, a.AccountGroup,
       CASE WHEN a.AccountGroup IN (N'Asset', N'Liability') THEN N'Balance Sheet' ELSE N'Income Statement' END,
       CASE a.AccountGroup WHEN N'Revenue' THEN 1 WHEN N'COGS' THEN 2 WHEN N'Operating Expense' THEN 3
                           WHEN N'Other Expense' THEN 4 WHEN N'Tax' THEN 5 WHEN N'Asset' THEN 6 WHEN N'Liability' THEN 7 END,
       CASE WHEN a.AccountGroup IN (N'Revenue', N'Liability') THEN -1 ELSE 1 END,
       CASE WHEN a.AccountGroup = N'Revenue' THEN 1 ELSE 0 END,
       CASE WHEN a.AccountGroup IN (N'Revenue', N'COGS', N'Operating Expense') THEN 1 ELSE 0 END,
       CASE WHEN EXISTS (SELECT 1 FROM stg.fact_budget b WHERE b.AccountCode = a.AccountCode) THEN 1 ELSE 0 END,
       CONCAT(a.AccountCode, N' ', a.AccountName)
FROM stg.dim_account a;

INSERT dbo.DimCustomer (CustomerID, CustomerName, Industry, Country, Segment)
SELECT CustomerID, CustomerName, Industry, Country, Segment FROM stg.dim_customer;

INSERT dbo.DimVendor (VendorID, VendorName, VendorCategory, Country)
SELECT VendorID, VendorName, VendorCategory, Country FROM stg.dim_vendor;

INSERT dbo.DimVersion (VersionID, VersionName, SortOrder, Description) VALUES
 (N'ACT', N'Actual', 1, N'General ledger, translated to AUD at monthly average rates.'),
 (N'BUD', N'Budget', 2, N'Annual budget, supplied in AUD. Covers revenue, COGS and operating expense only.'),
 (N'FC',  N'Forecast', 3, N'One forecast version, all lines. The source Scenario label is a random label per line, not a scenario.');

INSERT dbo.DimAgeingBucket (BucketOrder, BucketName, MinDaysPastDue, MaxDaysPastDue, IsPastDue) VALUES
 (1, N'Current',   -100000,      0, 0),
 (2, N'1-30',            1,     30, 1),
 (3, N'31-60',          31,     60, 1),
 (4, N'61-90',          61,     90, 1),
 (5, N'91-180',         91,    180, 1),
 (6, N'181-365',       181,    365, 1),
 (7, N'Over 365',      366, 100000, 1);

-- ILLUSTRATIVE planning assumptions, entered here so they are visible and
-- versioned - NOT supplied data. AUDChangePct > 0 = the AUD strengthens, which
-- lowers the AUD value of every foreign-currency entity's result.
INSERT dbo.DimScenario (ScenarioKey, ScenarioName, RevenueChangePct, OpexChangePct, AUDChangePct, Description) VALUES
 (1, N'Downside', -0.1000,  0.0300,  0.0500, N'Revenue 10% below run-rate, operating expense 3% above, AUD 5% stronger. Illustrative assumption.'),
 (2, N'Base',      0.0000,  0.0000,  0.0000, N'Trailing-12-month run-rate, unchanged. Illustrative assumption.'),
 (3, N'Upside',    0.0500, -0.0200, -0.0500, N'Revenue 5% above run-rate, operating expense 2% below, AUD 5% weaker. Illustrative assumption.');

-- Plan comparisons stop at operating profit (lines 1-7): the budget has no
-- interest, FX or tax lines, so lines 8-11 are actual-only.
INSERT dbo.DimPLLine (LineKey, LineName, LineType, FavourableSign, IsBudgeted) VALUES
 ( 1, N'Revenue',              N'Group',     1, 1),
 ( 2, N'Cost of goods sold',   N'Group',    -1, 1),
 ( 3, N'Gross profit',         N'Subtotal',  1, 1),
 ( 4, N'Gross margin %',       N'Ratio',     1, 1),
 ( 5, N'Operating expenses',   N'Group',    -1, 1),
 ( 6, N'Operating profit',     N'Subtotal',  1, 1),
 ( 7, N'Operating margin %',   N'Ratio',     1, 1),
 ( 8, N'Other expense (net)',  N'Group',    -1, 0),
 ( 9, N'Tax expense',          N'Group',    -1, 0),
 (10, N'Net profit',           N'Subtotal',  1, 0),
 (11, N'Net margin %',         N'Ratio',     1, 0);

INSERT dbo.DimSensitivityStep (StepPct, StepLabel)
SELECT v / 100.0, CASE WHEN v > 0 THEN CONCAT(N'+', v, N'%') ELSE CONCAT(v, N'%') END
FROM (VALUES (-20), (-15), (-10), (-5), (0), (5), (10), (15), (20)) t(v);

------------------------------------------------------------------------ FX ---
-- AUD is the reporting currency: its rate is 1 by definition. The file's AUD
-- values (0.9504 - 1.0475) are kept in AUDPerUnitSupplied for audit.
INSERT dbo.FxRateDaily ([Date], CurrencyCode, AUDPerUnitSupplied, AUDPerUnit, IsOverridden)
SELECT CONVERT(DATE, s.[Date], 23), s.Currency, CONVERT(DECIMAL(9,4), s.AUDPerUnit),
       CASE WHEN s.Currency = N'AUD' THEN 1.0000 ELSE CONVERT(DECIMAL(9,4), s.AUDPerUnit) END,
       CASE WHEN s.Currency = N'AUD' AND CONVERT(DECIMAL(9,4), s.AUDPerUnit) <> 1 THEN 1 ELSE 0 END
FROM stg.fact_fx_rates s;

-- Monthly average, rounded half away from zero to 6 dp. The sum is cast to
-- DECIMAL(18,4) first so the division carries 15 decimals before rounding
-- (the pandas audit applies the identical rule).
WITH d AS (
    SELECT r.CurrencyCode, r.AUDPerUnit, DATEFROMPARTS(YEAR(r.[Date]), MONTH(r.[Date]), 1) AS MonthStart,
           ABS(CAST(r.AUDPerUnit AS FLOAT) / LAG(CAST(r.AUDPerUnit AS FLOAT)) OVER (PARTITION BY r.CurrencyCode ORDER BY r.[Date]) - 1) AS AbsMove,
           ROW_NUMBER() OVER (PARTITION BY r.CurrencyCode, YEAR(r.[Date]), MONTH(r.[Date]) ORDER BY r.[Date] DESC) AS rn
    FROM dbo.FxRateDaily r)
INSERT dbo.FxRateMonthly (MonthStart, CurrencyCode, AvgAUDPerUnit, ClosingAUDPerUnit, MinAUDPerUnit, MaxAUDPerUnit,
                          DaysInMonth, MeanAbsDailyMovePct)
SELECT MonthStart, CurrencyCode,
       CAST(ROUND(CAST(SUM(AUDPerUnit) AS DECIMAL(18,4)) / COUNT(*), 6) AS DECIMAL(18,6)),
       MAX(CASE WHEN rn = 1 THEN AUDPerUnit END), MIN(AUDPerUnit), MAX(AUDPerUnit), COUNT(*),
       CAST(AVG(AbsMove) * 100 AS DECIMAL(9,4))
FROM d
GROUP BY MonthStart, CurrencyCode;

------------------------------------------------------------------ security ---
INSERT dbo.SecurityUserAccess (UserEmail, [Role], EntityID, DepartmentID)
SELECT UserEmail, [Role], EntityID, DepartmentID FROM stg.security_user_access;
GO
PRINT 'Dimensions, calendar, FX and security loaded.';
GO
