/*=============================================================================
  08_create_views.sql

  The analytics contract: the only objects Power BI reads. Each view selects
  explicit columns (never *), so a change to a dbo table cannot silently change
  what the model imports.

  Kimball unknown members: a ledger line with no customer or vendor maps to
  C-NONE / V-NONE ("Not specified") here, so the model never shows a blank
  member. dbo keeps the NULL, which is the true state of the source.
=============================================================================*/
USE FinancePlanningBI;
GO

CREATE OR ALTER VIEW analytics.vw_DimDate AS
SELECT [Date], [Year], MonthNo, MonthName, MonthShort, [Quarter], QuarterLabel, YearMonth, YearMonthLabel,
       MonthStart, MonthEnd, ISOWeek, DayName, DayOfWeekNo, FinancialYearStart, FinancialYear, FinancialMonthNo,
       FinancialQuarter, FinancialQuarterLabel, FinancialQuarterSort, MonthOffset, FinancialYearOffset,
       IsSourceCalendar, IsAfterAsOf, IsMonthComplete, IsFinancialYearComplete
FROM dbo.DimDate;
GO

CREATE OR ALTER VIEW analytics.vw_DimEntity AS
SELECT e.EntityID, e.EntityName, e.Region, e.LocalCurrency,
       -- Chart axes are narrow: "Northstar UK" truncates to "Northstar..." on every
       -- entity, which tells the reader nothing. The short name is what a chart shows.
       REPLACE(e.EntityName, N'Northstar ', N'') AS EntityShort,
       CONCAT(e.EntityName, N' (', e.LocalCurrency, N')') AS EntityLabel,
       CASE WHEN c.IsReportingCurrency = 1 THEN N'Reporting currency' ELSE N'Foreign currency' END AS CurrencyRole
FROM dbo.DimEntity e
JOIN dbo.DimCurrency c ON c.CurrencyCode = e.LocalCurrency;
GO

CREATE OR ALTER VIEW analytics.vw_DimDepartment AS
SELECT DepartmentID, DepartmentName FROM dbo.DimDepartment;
GO

CREATE OR ALTER VIEW analytics.vw_DimAccount AS
SELECT AccountCode, AccountName, AccountGroup, [Statement], GroupOrder, NaturalSign, IsIncome, IsOperating,
       IsBudgeted, AccountLabel, CONVERT(INT, AccountCode) AS AccountOrder
FROM dbo.DimAccount;
GO

CREATE OR ALTER VIEW analytics.vw_DimCustomer AS
SELECT CustomerID, CustomerName, Industry, Country, Segment FROM dbo.DimCustomer
UNION ALL
SELECT N'C-NONE', N'Not specified', N'Not specified', N'Not specified', N'Not specified';
GO

CREATE OR ALTER VIEW analytics.vw_DimVendor AS
SELECT VendorID, VendorName, VendorCategory, Country FROM dbo.DimVendor
UNION ALL
SELECT N'V-NONE', N'Not specified', N'Not specified', N'Not specified';
GO

CREATE OR ALTER VIEW analytics.vw_DimAgeingBucket AS
SELECT BucketOrder, BucketName, MinDaysPastDue, MaxDaysPastDue, IsPastDue FROM dbo.DimAgeingBucket;
GO

CREATE OR ALTER VIEW analytics.vw_DimScenario AS
SELECT ScenarioKey, ScenarioName, RevenueChangePct, OpexChangePct, AUDChangePct, Description FROM dbo.DimScenario;
GO

CREATE OR ALTER VIEW analytics.vw_DimSensitivityStep AS
SELECT StepPct, StepLabel FROM dbo.DimSensitivityStep;
GO

CREATE OR ALTER VIEW analytics.vw_FxRateMonthly AS
SELECT MonthStart, CurrencyCode, AvgAUDPerUnit, ClosingAUDPerUnit, MinAUDPerUnit, MaxAUDPerUnit, DaysInMonth,
       MeanAbsDailyMovePct
FROM dbo.FxRateMonthly;
GO

CREATE OR ALTER VIEW analytics.vw_FactGL AS
SELECT GLTxnID, [Date], EntityID, DepartmentID, AccountCode, CurrencyCode, AmountLocal,
       COALESCE(CustomerID, N'C-NONE') AS CustomerID, COALESCE(VendorID, N'V-NONE') AS VendorID,
       PostingStatus, FxRateAvg, AmountAUD, AmountAUDSpot
FROM dbo.FactGL;
GO

CREATE OR ALTER VIEW analytics.vw_FactFinancials AS
SELECT VersionID, MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD, AmountLocal, AmountAUDAtPYRate,
       PostingLines, ScenarioLabel
FROM dbo.FactFinancials;
GO

CREATE OR ALTER VIEW analytics.vw_FactARInvoice AS
SELECT InvoiceID, InvoiceDate, DueDate, PaidDate, CustomerID, EntityID, InvoiceAmountAUD, SourceStatus, TermsDays,
       DaysToPay, DaysLate, IsPaidAfterAsOf, IsOpenAsOf, DaysPastDueAsOf, AgeingBucketAsOf
FROM dbo.FactARInvoice;
GO

CREATE OR ALTER VIEW analytics.vw_FactAPBill AS
SELECT BillID, BillDate, DueDate, PaidDate, VendorID, EntityID, BillAmountAUD, SourceStatus, TermsDays,
       DaysToPay, DaysLate, IsPaidAfterAsOf, IsOpenAsOf, DaysPastDueAsOf, AgeingBucketAsOf
FROM dbo.FactAPBill;
GO

CREATE OR ALTER VIEW analytics.vw_FactCashBalance AS
SELECT [Date], EntityID, ClosingCashAUD, IsFloorValue FROM dbo.FactCashBalance;
GO

CREATE OR ALTER VIEW analytics.vw_DimPLLine AS
SELECT LineKey, LineName, LineType, FavourableSign, IsBudgeted FROM dbo.DimPLLine;
GO

-- Data-quality figures for the report's Data & Method page, computed live from
-- dbo so they can never drift from the data (each is also checked in 09).
CREATE OR ALTER VIEW analytics.vw_DataQualityMetric AS
WITH k AS (SELECT CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate')
SELECT 1 AS SortOrder, N'AUD rates overridden to 1' AS Metric,
       CAST((SELECT COUNT(*) FROM dbo.FxRateDaily WHERE IsOverridden = 1) AS DECIMAL(19,4)) AS MetricValue, N'days' AS Unit
UNION ALL SELECT 2, N'Spot vs average translation difference',
       CAST((SELECT ABS(SUM(AmountAUDSpot) - SUM(AmountAUD)) / ABS(SUM(AmountAUD)) FROM dbo.FactGL) AS DECIMAL(19,6)), N'share'
UNION ALL SELECT 3, N'Budget lines with no ledger posting',
       CAST((SELECT COUNT(*) FROM dbo.FactBudget b WHERE NOT EXISTS (
            SELECT 1 FROM dbo.FactGL g WHERE g.MonthStart = b.MonthStart AND g.EntityID = b.EntityID
                                         AND g.DepartmentID = b.DepartmentID AND g.AccountCode = b.AccountCode)) AS DECIMAL(19,4)), N'lines'
UNION ALL SELECT 4, N'Payroll department-months posted',
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT EntityID, DepartmentID, MonthStart FROM dbo.FactGL WHERE AccountCode = N'6000') p) * 1.0
            / (SELECT COUNT(*) FROM (SELECT DISTINCT EntityID, DepartmentID, MonthStart FROM dbo.FactBudget WHERE AccountCode = N'6000') b)
            AS DECIMAL(19,6)), N'share'
UNION ALL SELECT 5, N'Forecast lines labelled Base', CAST((SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Base') AS DECIMAL(19,4)), N'lines'
UNION ALL SELECT 6, N'Forecast lines labelled Best', CAST((SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Best') AS DECIMAL(19,4)), N'lines'
UNION ALL SELECT 7, N'Forecast lines labelled Worst', CAST((SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Worst') AS DECIMAL(19,4)), N'lines'
UNION ALL SELECT 8, N'Receipts dated after the as-of date', CAST((SELECT COUNT(*) FROM dbo.FactARInvoice WHERE IsPaidAfterAsOf = 1) AS DECIMAL(19,4)), N'invoices'
UNION ALL SELECT 9, N'Payments dated after the as-of date', CAST((SELECT COUNT(*) FROM dbo.FactAPBill WHERE IsPaidAfterAsOf = 1) AS DECIMAL(19,4)), N'bills'
UNION ALL SELECT 10, N'Invoiced value never collected',
       CAST((SELECT SUM(CASE WHEN SourceStatus = N'Open' THEN InvoiceAmountAUD END) / SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice) AS DECIMAL(19,6)), N'share'
UNION ALL SELECT 11, N'Cash days at the 50,000 floor', CAST((SELECT COUNT(*) FROM dbo.FactCashBalance WHERE IsFloorValue = 1) AS DECIMAL(19,4)), N'days'
UNION ALL SELECT 12, N'Ledger lines still accrued',
       CAST((SELECT SUM(CASE WHEN PostingStatus = N'Accrued' THEN 1.0 ELSE 0 END) / COUNT(*) FROM dbo.FactGL) AS DECIMAL(19,6)), N'share'
UNION ALL SELECT 13, N'Calendar days added beyond the supplied calendar',
       CAST((SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 0) AS DECIMAL(19,4)), N'days'
UNION ALL SELECT 14, N'Actual revenue as a share of budget (all months)',
       CAST((SELECT SUM(CASE WHEN f.VersionID = N'ACT' THEN f.AmountAUD END) / SUM(CASE WHEN f.VersionID = N'BUD' THEN f.AmountAUD END)
             FROM dbo.FactFinancials f JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode WHERE a.AccountGroup = N'Revenue') AS DECIMAL(19,6)), N'share'
UNION ALL SELECT 15, N'AR more than 365 days past due on the as-of date',
       CAST((SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 7) AS DECIMAL(19,4)), N'AUD';
GO

CREATE OR ALTER VIEW analytics.vw_ModelConfig AS
SELECT ConfigKey, ConfigValue, Description FROM dbo.ModelConfig;
GO

CREATE OR ALTER VIEW analytics.vw_SecurityUserAccess AS
SELECT UserEmail, [Role], EntityID, DepartmentID FROM dbo.SecurityUserAccess;
GO
PRINT 'Analytics views created.';
GO
