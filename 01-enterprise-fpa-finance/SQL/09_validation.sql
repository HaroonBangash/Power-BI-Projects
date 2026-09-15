/*=============================================================================
  09_validation.sql

  Every check prints Expected vs Actual and PASS/FAIL; the script THROWs if any
  check fails, so run_all.ps1 stops rather than reporting success.

  Where an expected value is a literal, it was measured independently by the
  pandas audit (Python/01_data_audit.py -> Validation/audit_metrics.json)
  straight from the raw CSVs, with the same rounding rule - not read back from
  these tables. Structural expectations (zero untrusted keys, FactFinancials
  equal to FactGL) are properties the build must satisfy by construction.
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

DROP TABLE IF EXISTS #c;
CREATE TABLE #c (Id INT IDENTITY(1,1), Area NVARCHAR(20), CheckName NVARCHAR(160),
                 Expected DECIMAL(38,6), Actual DECIMAL(38,6), Tolerance DECIMAL(38,6) NOT NULL DEFAULT 0);

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');

----------------------------------------------------------------- 1. loads ---
INSERT #c (Area, CheckName, Expected, Actual)
SELECT N'Load', N'staging files matching published row counts', 14,
       (SELECT COUNT(*) FROM stg.LoadLog WHERE RowsLoaded = ExpectedRows);

INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Load', N'FactGL rows',             80000, (SELECT COUNT(*) FROM dbo.FactGL)),
 (N'Load', N'FactBudget rows',         60480, (SELECT COUNT(*) FROM dbo.FactBudget)),
 (N'Load', N'FactForecast rows',       60480, (SELECT COUNT(*) FROM dbo.FactForecast)),
 (N'Load', N'FactARInvoice rows',      18000, (SELECT COUNT(*) FROM dbo.FactARInvoice)),
 (N'Load', N'FactAPBill rows',         12000, (SELECT COUNT(*) FROM dbo.FactAPBill)),
 (N'Load', N'FactCashBalance rows',    10224, (SELECT COUNT(*) FROM dbo.FactCashBalance)),
 (N'Load', N'FxRateDaily rows',        10224, (SELECT COUNT(*) FROM dbo.FxRateDaily)),
 (N'Load', N'DimAccount rows',            26, (SELECT COUNT(*) FROM dbo.DimAccount)),
 (N'Load', N'DimCustomer rows',         1500, (SELECT COUNT(*) FROM dbo.DimCustomer)),
 (N'Load', N'DimVendor rows',            500, (SELECT COUNT(*) FROM dbo.DimVendor)),
 (N'Load', N'DimEntity rows',              6, (SELECT COUNT(*) FROM dbo.DimEntity)),
 (N'Load', N'DimDepartment rows',         10, (SELECT COUNT(*) FROM dbo.DimDepartment)),
 (N'Load', N'SecurityUserAccess rows',    18, (SELECT COUNT(*) FROM dbo.SecurityUserAccess));

--------------------------------------------------------------- 2. calendar ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Calendar', N'DimDate covers 2022-01-01..2027-06-30 with no gaps',
      DATEDIFF(DAY, '2022-01-01', '2027-06-30') + 1, (SELECT COUNT(*) FROM dbo.DimDate)),
 (N'Calendar', N'days also present in the supplied calendar', 1704,
      (SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 1)),
 (N'Calendar', N'regenerated days disagreeing with the supplied calendar (8 columns)', 0,
      (SELECT COUNT(*) FROM stg.dim_date s
       JOIN dbo.DimDate d ON d.[Date] = CONVERT(DATE, s.[Date], 23)
       WHERE CONVERT(INT, s.[Year]) <> d.[Year] OR CONVERT(INT, s.MonthNo) <> d.MonthNo
          OR s.MonthName <> d.MonthName OR CONVERT(INT, s.[Quarter]) <> d.[Quarter]
          OR CONVERT(INT, s.ISOWeek) <> d.ISOWeek OR s.DayName <> d.DayName
          OR CONVERT(INT, s.FinancialYearStart) <> d.FinancialYearStart
          OR s.FinancialYear <> d.FinancialYear)),
 (N'Calendar', N'AsOfDate = 2026-08-31 (pandas: last GL day)', 20260831,
      CONVERT(INT, CONVERT(NCHAR(8), @AsOf, 112))),
 (N'Calendar', N'FY27 months complete on the as-of date (Jul, Aug)', 2,
      (SELECT COUNT(DISTINCT MonthStart) FROM dbo.DimDate WHERE FinancialYear = N'FY27' AND IsMonthComplete = 1)),
 (N'Calendar', N'days in complete financial years FY22-FY26', 181 + 365 + 366 + 365 + 365,
      (SELECT COUNT(*) FROM dbo.DimDate WHERE IsFinancialYearComplete = 1)),
 (N'Calendar', N'July is financial month 1 and FY26 Q1 starts 2025-07-01', 1,
      (SELECT COUNT(*) FROM dbo.DimDate WHERE [Date] = '2025-07-01' AND FinancialMonthNo = 1
                                          AND FinancialQuarterLabel = N'FY26 Q1' AND MonthOffset = -13));

------------------------------------------------------------ 3. integrity ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Integrity', N'foreign keys declared', 39, (SELECT COUNT(*) FROM sys.foreign_keys)),
 (N'Integrity', N'foreign keys untrusted or disabled', 0,
      (SELECT COUNT(*) FROM sys.foreign_keys WHERE is_not_trusted = 1 OR is_disabled = 1)),
 (N'Integrity', N'check constraints untrusted or disabled', 0,
      (SELECT COUNT(*) FROM sys.check_constraints WHERE is_not_trusted = 1 OR is_disabled = 1)),
 (N'Integrity', N'GL lines whose currency is not the entity currency', 0,
      (SELECT COUNT(*) FROM dbo.FactGL g JOIN dbo.DimEntity e ON e.EntityID = g.EntityID WHERE g.CurrencyCode <> e.LocalCurrency)),
 (N'Integrity', N'GL lines with a customer (pandas)', 10605, (SELECT COUNT(*) FROM dbo.FactGL WHERE CustomerID IS NOT NULL)),
 (N'Integrity', N'GL lines with a vendor (pandas)', 37856, (SELECT COUNT(*) FROM dbo.FactGL WHERE VendorID IS NOT NULL)),
 (N'Integrity', N'customers on non-revenue lines or vendors on revenue lines', 0,
      (SELECT COUNT(*) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode
       WHERE (g.CustomerID IS NOT NULL AND a.IsIncome = 0) OR (g.VendorID IS NOT NULL AND a.IsIncome = 1))),
 (N'Integrity', N'security rows whose entity or department is neither ALL nor a known key', 0,
      (SELECT COUNT(*) FROM dbo.SecurityUserAccess s
       WHERE (s.EntityID <> N'ALL' AND s.EntityID NOT IN (SELECT EntityID FROM dbo.DimEntity))
          OR (s.DepartmentID <> N'ALL' AND s.DepartmentID NOT IN (SELECT DepartmentID FROM dbo.DimDepartment)))),
 (N'Integrity', N'budgeted accounts = revenue, COGS and operating expense (18)', 18,
      (SELECT COUNT(*) FROM dbo.DimAccount WHERE IsBudgeted = 1 AND IsOperating = 1)),
 (N'Integrity', N'accounts budgeted outside the operating scope', 0,
      (SELECT COUNT(*) FROM dbo.DimAccount WHERE IsBudgeted <> IsOperating));

--------------------------------------------------------------------- 4. FX ---
INSERT #c (Area, CheckName, Expected, Actual, Tolerance) VALUES
 (N'FX', N'AUD daily rates overridden to 1 (pandas: supplied value <> 1)', 1697,
      (SELECT COUNT(*) FROM dbo.FxRateDaily WHERE IsOverridden = 1), 0),
 (N'FX', N'AUD rates not exactly 1 after override (daily + monthly)', 0,
      (SELECT COUNT(*) FROM dbo.FxRateDaily WHERE CurrencyCode = N'AUD' AND AUDPerUnit <> 1)
    + (SELECT COUNT(*) FROM dbo.FxRateMonthly WHERE CurrencyCode = N'AUD' AND AvgAUDPerUnit <> 1), 0),
 (N'FX', N'monthly average rates (56 months x 6 currencies)', 336, (SELECT COUNT(*) FROM dbo.FxRateMonthly), 0),
 (N'FX', N'sum of all monthly average rates (pandas, 6 dp half-up)', 465.869694,
      (SELECT SUM(AvgAUDPerUnit) FROM dbo.FxRateMonthly), 0),
 (N'FX', N'GL lines translated at a rate other than their month average', 0,
      (SELECT COUNT(*) FROM dbo.FactGL g JOIN dbo.FxRateMonthly m ON m.MonthStart = g.MonthStart AND m.CurrencyCode = g.CurrencyCode
       WHERE g.FxRateAvg <> m.AvgAUDPerUnit OR g.AmountAUD <> ROUND(g.AmountLocal * m.AvgAUDPerUnit, 2)), 0),
 (N'FX', N'spot vs monthly-average translation, % of total (pandas 0.005; must stay < 0.01)', 0,
      (SELECT ABS(SUM(AmountAUDSpot) - SUM(AmountAUD)) / ABS(SUM(AmountAUD)) * 100 FROM dbo.FactGL), 0.01);

------------------------------------------------------------------ 5. ledger ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Ledger', N'GL local-currency total (pandas)', 62448433.44, (SELECT SUM(AmountLocal) FROM dbo.FactGL)),
 (N'Ledger', N'GL AUD total (pandas)', 86847392.76, (SELECT SUM(AmountAUD) FROM dbo.FactGL)),
 (N'Ledger', N'GL AUD Revenue (pandas)', -80234572.05,
      (SELECT SUM(g.AmountAUD) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode WHERE a.AccountGroup = N'Revenue')),
 (N'Ledger', N'GL AUD COGS (pandas)', 44794574.58,
      (SELECT SUM(g.AmountAUD) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode WHERE a.AccountGroup = N'COGS')),
 (N'Ledger', N'GL AUD Operating Expense (pandas)', 103819545.61,
      (SELECT SUM(g.AmountAUD) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode WHERE a.AccountGroup = N'Operating Expense')),
 (N'Ledger', N'GL AUD Other Expense (pandas)', 9991807.89,
      (SELECT SUM(g.AmountAUD) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode WHERE a.AccountGroup = N'Other Expense')),
 (N'Ledger', N'GL AUD Tax (pandas)', 8476036.73,
      (SELECT SUM(g.AmountAUD) FROM dbo.FactGL g JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode WHERE a.AccountGroup = N'Tax')),
 (N'Ledger', N'GL lines Accrued (pandas)', 19788, (SELECT COUNT(*) FROM dbo.FactGL WHERE PostingStatus = N'Accrued')),
 (N'Ledger', N'GL lines without a prior-year rate = calendar 2022 lines',
      (SELECT COUNT(*) FROM dbo.FactGL WHERE [Date] < '2023-01-01'),
      (SELECT COUNT(*) FROM dbo.FactGL WHERE FxRatePY IS NULL));

-------------------------------------------------------- 6. budget / forecast ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Plan', N'budget total (pandas)', 77092186.61, (SELECT SUM(AmountAUD) FROM dbo.FactBudget)),
 (N'Plan', N'budget Revenue (pandas)', -116051346.77,
      (SELECT SUM(b.AmountAUD) FROM dbo.FactBudget b JOIN dbo.DimAccount a ON a.AccountCode = b.AccountCode WHERE a.AccountGroup = N'Revenue')),
 (N'Plan', N'budget Operating Expense (pandas)', 154702663.74,
      (SELECT SUM(b.AmountAUD) FROM dbo.FactBudget b JOIN dbo.DimAccount a ON a.AccountCode = b.AccountCode WHERE a.AccountGroup = N'Operating Expense')),
 (N'Plan', N'forecast total (pandas)', 77194465.13, (SELECT SUM(AmountAUD) FROM dbo.FactForecast)),
 (N'Plan', N'forecast Revenue (pandas)', -116012034.06,
      (SELECT SUM(f.AmountAUD) FROM dbo.FactForecast f JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode WHERE a.AccountGroup = N'Revenue')),
 (N'Plan', N'forecast lines labelled Base (pandas)', 36315, (SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Base')),
 (N'Plan', N'forecast lines labelled Best (pandas)', 12006, (SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Best')),
 (N'Plan', N'forecast lines labelled Worst (pandas)', 12159, (SELECT COUNT(*) FROM dbo.FactForecast WHERE ScenarioLabel = N'Worst')),
 (N'Plan', N'budget lines with a forecast line (one-to-one keys)', 60480,
      (SELECT COUNT(*) FROM dbo.FactBudget b JOIN dbo.FactForecast f ON f.MonthStart = b.MonthStart AND f.EntityID = b.EntityID
                                             AND f.DepartmentID = b.DepartmentID AND f.AccountCode = b.AccountCode)),
 (N'Plan', N'budget lines with no ledger posting (pandas)', 19468,
      (SELECT COUNT(*) FROM dbo.FactBudget b WHERE NOT EXISTS (
           SELECT 1 FROM dbo.FactGL g WHERE g.MonthStart = b.MonthStart AND g.EntityID = b.EntityID
                                        AND g.DepartmentID = b.DepartmentID AND g.AccountCode = b.AccountCode)));

------------------------------------------------------------ 7. financials ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Financials', N'actual rows = month x entity x department x account keys in the GL (pandas)', 47822,
      (SELECT COUNT(*) FROM dbo.FactFinancials WHERE VersionID = N'ACT')),
 (N'Financials', N'budget rows', 60480, (SELECT COUNT(*) FROM dbo.FactFinancials WHERE VersionID = N'BUD')),
 (N'Financials', N'forecast rows', 60480, (SELECT COUNT(*) FROM dbo.FactFinancials WHERE VersionID = N'FC')),
 (N'Financials', N'actual AUD = GL AUD', (SELECT SUM(AmountAUD) FROM dbo.FactGL),
      (SELECT SUM(AmountAUD) FROM dbo.FactFinancials WHERE VersionID = N'ACT')),
 (N'Financials', N'actual lines = GL lines', 80000, (SELECT SUM(PostingLines) FROM dbo.FactFinancials WHERE VersionID = N'ACT')),
 (N'Financials', N'actual AUD at PY rate = GL AUD at PY rate', (SELECT SUM(AmountAUDAtPYRate) FROM dbo.FactGL),
      (SELECT SUM(AmountAUDAtPYRate) FROM dbo.FactFinancials WHERE VersionID = N'ACT')),
 (N'Financials', N'month x entity x account cells where actual <> GL', 0,
      (SELECT COUNT(*) FROM (
           SELECT MonthStart, EntityID, AccountCode, SUM(AmountAUD) AS a FROM dbo.FactFinancials WHERE VersionID = N'ACT'
           GROUP BY MonthStart, EntityID, AccountCode) f
       FULL JOIN (
           SELECT MonthStart, EntityID, AccountCode, SUM(AmountAUD) AS a FROM dbo.FactGL
           GROUP BY MonthStart, EntityID, AccountCode) g
         ON g.MonthStart = f.MonthStart AND g.EntityID = f.EntityID AND g.AccountCode = f.AccountCode
       WHERE f.a IS NULL OR g.a IS NULL OR f.a <> g.a)),
 (N'Financials', N'budget AUD = FactBudget', 77092186.61, (SELECT SUM(AmountAUD) FROM dbo.FactFinancials WHERE VersionID = N'BUD')),
 (N'Financials', N'forecast AUD = FactForecast', 77194465.13, (SELECT SUM(AmountAUD) FROM dbo.FactFinancials WHERE VersionID = N'FC'));

-- FY26 P&L, the headline year (pandas: Validation/audit_metrics.json pl.*_FY26).
-- Presented sign: revenue = -ledger; costs = +ledger; operating profit = -ledger over the operating accounts.
DECLARE @pl TABLE (VersionID NVARCHAR(3), Revenue DECIMAL(19,2), COGS DECIMAL(19,2), Opex DECIMAL(19,2),
                   OperatingProfit DECIMAL(19,2), Other DECIMAL(19,2), Tax DECIMAL(19,2), NetProfit DECIMAL(19,2));
INSERT @pl
SELECT f.VersionID,
       -SUM(CASE WHEN a.AccountGroup = N'Revenue' THEN f.AmountAUD END),
       SUM(CASE WHEN a.AccountGroup = N'COGS' THEN f.AmountAUD END),
       SUM(CASE WHEN a.AccountGroup = N'Operating Expense' THEN f.AmountAUD END),
       -SUM(CASE WHEN a.IsOperating = 1 THEN f.AmountAUD END),
       COALESCE(SUM(CASE WHEN a.AccountGroup = N'Other Expense' THEN f.AmountAUD END), 0),
       COALESCE(SUM(CASE WHEN a.AccountGroup = N'Tax' THEN f.AmountAUD END), 0),
       -SUM(f.AmountAUD)
FROM dbo.FactFinancials f
JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
JOIN dbo.DimDate d ON d.[Date] = f.MonthStart
WHERE d.FinancialYear = N'FY26'
GROUP BY f.VersionID;

INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'P&L', N'FY26 actual revenue (pandas)', 17323588.14, (SELECT Revenue FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual COGS (pandas)', 9845919.29, (SELECT COGS FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual operating expense (pandas)', 22398339.88, (SELECT Opex FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual operating profit (pandas)', -14920671.03, (SELECT OperatingProfit FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual other expense (pandas)', 2089523.77, (SELECT Other FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual tax (pandas)', 1831762.38, (SELECT Tax FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 actual net profit (pandas)', -18841957.18, (SELECT NetProfit FROM @pl WHERE VersionID = N'ACT')),
 (N'P&L', N'FY26 budget revenue (pandas)', 24762895.94, (SELECT Revenue FROM @pl WHERE VersionID = N'BUD')),
 (N'P&L', N'FY26 budget COGS (pandas)', 8282274.80, (SELECT COGS FROM @pl WHERE VersionID = N'BUD')),
 (N'P&L', N'FY26 budget operating expense (pandas)', 33000382.37, (SELECT Opex FROM @pl WHERE VersionID = N'BUD')),
 (N'P&L', N'FY26 budget operating profit (pandas)', -16519761.23, (SELECT OperatingProfit FROM @pl WHERE VersionID = N'BUD')),
 (N'P&L', N'FY26 budget has no below-the-line lines', 0,
      (SELECT Other + Tax FROM @pl WHERE VersionID = N'BUD'));

-------------------------------------------------------- 8. working capital ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'AR', N'invoices open on the as-of date (pandas)', 3943, (SELECT COUNT(*) FROM dbo.FactARInvoice WHERE IsOpenAsOf = 1)),
 (N'AR', N'AR balance on the as-of date (pandas)', 40197880.32,
      (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE IsOpenAsOf = 1)),
 (N'AR', N'receipts dated after the as-of date (pandas)', 769, (SELECT COUNT(*) FROM dbo.FactARInvoice WHERE IsPaidAfterAsOf = 1)),
 (N'AR', N'value of receipts after the as-of date (pandas)', 7382038.79,
      (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE IsPaidAfterAsOf = 1)),
 (N'AR', N'Current (pandas)',  4765705.74, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 1)),
 (N'AR', N'1-30 (pandas)',     2959683.30, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 2)),
 (N'AR', N'31-60 (pandas)',    1691316.93, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 3)),
 (N'AR', N'61-90 (pandas)',     933098.79, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 4)),
 (N'AR', N'91-180 (pandas)',   2376607.35, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 5)),
 (N'AR', N'181-365 (pandas)',  4472559.46, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 6)),
 (N'AR', N'Over 365 (pandas)',22998908.75, (SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE AgeingBucketAsOf = 7)),
 (N'AR', N'status Paid exactly when a paid date exists', 18000,
      (SELECT COUNT(*) FROM dbo.FactARInvoice WHERE CASE WHEN SourceStatus = N'Paid' THEN 1 ELSE 0 END = CASE WHEN PaidDate IS NOT NULL THEN 1 ELSE 0 END
       AND (SourceStatus <> N'Paid' OR PaidAmountAUD = InvoiceAmountAUD) AND (SourceStatus = N'Paid' OR PaidAmountAUD = 0))),
 (N'AP', N'bills open on the as-of date (pandas)', 1842, (SELECT COUNT(*) FROM dbo.FactAPBill WHERE IsOpenAsOf = 1)),
 (N'AP', N'AP balance on the as-of date (pandas)', 10489853.64,
      (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE IsOpenAsOf = 1)),
 (N'AP', N'payments dated after the as-of date (pandas)', 395, (SELECT COUNT(*) FROM dbo.FactAPBill WHERE IsPaidAfterAsOf = 1)),
 (N'AP', N'value of payments after the as-of date (pandas)', 2328737.98,
      (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE IsPaidAfterAsOf = 1)),
 (N'AP', N'Current (pandas)',  1614971.13, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 1)),
 (N'AP', N'1-30 (pandas)',      985584.97, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 2)),
 (N'AP', N'31-60 (pandas)',     196760.78, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 3)),
 (N'AP', N'61-90 (pandas)',     162424.09, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 4)),
 (N'AP', N'91-180 (pandas)',    574653.06, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 5)),
 (N'AP', N'181-365 (pandas)',  1256630.21, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 6)),
 (N'AP', N'Over 365 (pandas)', 5698829.40, (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE AgeingBucketAsOf = 7)),
 (N'AP', N'status Paid exactly when a paid date exists', 12000,
      (SELECT COUNT(*) FROM dbo.FactAPBill WHERE CASE WHEN SourceStatus = N'Paid' THEN 1 ELSE 0 END = CASE WHEN PaidDate IS NOT NULL THEN 1 ELSE 0 END
       AND (SourceStatus <> N'Paid' OR PaidAmountAUD = BillAmountAUD) AND (SourceStatus = N'Paid' OR PaidAmountAUD = 0)));

--------------------------------------------------------------------- 9. cash ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Cash', N'group closing cash on the as-of date (pandas)', 25494728.71,
      (SELECT SUM(ClosingCashAUD) FROM dbo.FactCashBalance WHERE [Date] = @AsOf)),
 (N'Cash', N'days at the 50,000.00 floor (pandas)', 33, (SELECT COUNT(*) FROM dbo.FactCashBalance WHERE IsFloorValue = 1)),
 (N'Cash', N'entity-days with no balance between 2022-01-01 and the as-of date', 0,
      (SELECT COUNT(*) FROM dbo.DimDate d CROSS JOIN dbo.DimEntity e
       WHERE d.[Date] <= @AsOf AND NOT EXISTS (SELECT 1 FROM dbo.FactCashBalance c WHERE c.[Date] = d.[Date] AND c.EntityID = e.EntityID)));

--------------------------------------------------------------------- 10. views ---
INSERT #c (Area, CheckName, Expected, Actual) VALUES
 (N'Views', N'analytics views', 19, (SELECT COUNT(*) FROM sys.views WHERE SCHEMA_NAME(schema_id) = N'analytics')),
 (N'Views', N'P&L statement lines (7 budgeted, 4 actual-only)', 11, (SELECT COUNT(*) FROM analytics.vw_DimPLLine)),
 (N'Views', N'budgeted P&L lines stop at operating margin (keys 1-7)', 7,
      (SELECT COUNT(*) FROM analytics.vw_DimPLLine WHERE IsBudgeted = 1 AND LineKey <= 7)),
 (N'Views', N'DQ metric: AUD rates overridden (pandas)', 1697,
      (SELECT MetricValue FROM analytics.vw_DataQualityMetric WHERE SortOrder = 1)),
 (N'Views', N'DQ metric: budget lines with no posting (pandas)', 19468,
      (SELECT MetricValue FROM analytics.vw_DataQualityMetric WHERE SortOrder = 3)),
 (N'Views', N'DQ metric: payroll department-months posted x 3360 (pandas 2292)', 2292,
      (SELECT ROUND(MetricValue * 3360, 0) FROM analytics.vw_DataQualityMetric WHERE SortOrder = 4)),
 (N'Views', N'DQ metric: receipts after the as-of date (pandas)', 769,
      (SELECT MetricValue FROM analytics.vw_DataQualityMetric WHERE SortOrder = 8)),
 (N'Views', N'DQ metric: AR over 365 days (pandas)', 22998908.75,
      (SELECT MetricValue FROM analytics.vw_DataQualityMetric WHERE SortOrder = 15)),
 (N'Views', N'DQ metrics defined', 15, (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric)),
 (N'Views', N'vw_DimCustomer = customers + 1 unknown member', 1501, (SELECT COUNT(*) FROM analytics.vw_DimCustomer)),
 (N'Views', N'vw_FactGL customer keys with no dimension row', 0,
      (SELECT COUNT(*) FROM analytics.vw_FactGL g WHERE NOT EXISTS (SELECT 1 FROM analytics.vw_DimCustomer c WHERE c.CustomerID = g.CustomerID))),
 (N'Views', N'vw_FactGL vendor keys with no dimension row', 0,
      (SELECT COUNT(*) FROM analytics.vw_FactGL g WHERE NOT EXISTS (SELECT 1 FROM analytics.vw_DimVendor v WHERE v.VendorID = g.VendorID)));

---------------------------------------------------------------------- report ---
SELECT Id, Area, CheckName, Expected, Actual,
       CASE WHEN ABS(COALESCE(Actual, -999999999) - Expected) <= Tolerance THEN N'PASS' ELSE N'FAIL' END AS Result
FROM #c ORDER BY Id;

DECLARE @fail INT = (SELECT COUNT(*) FROM #c WHERE Actual IS NULL OR ABS(Actual - Expected) > Tolerance);
DECLARE @total INT = (SELECT COUNT(*) FROM #c);
PRINT CONCAT(N'Validation: ', @total - @fail, N' of ', @total, N' checks passed.');
IF @fail > 0 THROW 50099, N'Validation failed - see the FAIL rows above.', 1;
GO
