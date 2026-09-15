/*=============================================================================
  06_load_facts.sql

  Types and loads the facts. NOT NULL targets make any unparseable value fail
  the insert loudly; the one nullable parsed column (PaidDate) is checked
  explicitly. Each fact's row count is asserted after the insert, so an inner
  join that lost rows (a missing exchange rate, say) cannot pass silently.
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');

IF EXISTS (SELECT 1 FROM stg.fact_ar WHERE NULLIF(PaidDate, N'') IS NOT NULL AND TRY_CONVERT(DATE, PaidDate, 23) IS NULL)
   OR EXISTS (SELECT 1 FROM stg.fact_ap WHERE NULLIF(PaidDate, N'') IS NOT NULL AND TRY_CONVERT(DATE, PaidDate, 23) IS NULL)
    THROW 50010, N'Unparseable PaidDate in AR or AP staging.', 1;

------------------------------------------------------------------- ledger ---
-- Translation at the monthly average rate; the day's spot rate and the prior
-- year's monthly rate are kept alongside for audit and constant-currency work.
INSERT dbo.FactGL (GLTxnID, [Date], MonthStart, EntityID, DepartmentID, AccountCode, CurrencyCode, AmountLocal,
                   CustomerID, VendorID, PostingStatus, FxRateAvg, AmountAUD, FxRateSpot, AmountAUDSpot,
                   FxRatePY, AmountAUDAtPYRate)
SELECT s.GLTxnID, v.d, v.ms, s.EntityID, s.DepartmentID, s.AccountCode, s.Currency, v.a,
       NULLIF(s.CustomerID, N''), NULLIF(s.VendorID, N''), s.PostingStatus,
       m.AvgAUDPerUnit, ROUND(v.a * m.AvgAUDPerUnit, 2),
       x.AUDPerUnit, ROUND(v.a * x.AUDPerUnit, 2),
       p.AvgAUDPerUnit, ROUND(v.a * p.AvgAUDPerUnit, 2)
FROM stg.fact_gl s
CROSS APPLY (SELECT CONVERT(DATE, s.[Date], 23) AS d,
                    DATEFROMPARTS(YEAR(CONVERT(DATE, s.[Date], 23)), MONTH(CONVERT(DATE, s.[Date], 23)), 1) AS ms,
                    CONVERT(DECIMAL(19,2), s.AmountLocal) AS a) v
JOIN dbo.FxRateMonthly m ON m.MonthStart = v.ms AND m.CurrencyCode = s.Currency
JOIN dbo.FxRateDaily x ON x.[Date] = v.d AND x.CurrencyCode = s.Currency
LEFT JOIN dbo.FxRateMonthly p ON p.MonthStart = DATEADD(YEAR, -1, v.ms) AND p.CurrencyCode = s.Currency;
IF (SELECT COUNT(*) FROM dbo.FactGL) <> 80000 THROW 50011, N'FactGL lost rows: a line has no exchange rate.', 1;

----------------------------------------------------------- budget / forecast ---
INSERT dbo.FactBudget (MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD)
SELECT CONVERT(DATE, [Month], 23), EntityID, DepartmentID, AccountCode, CONVERT(DECIMAL(19,2), BudgetAmountAUD)
FROM stg.fact_budget;

INSERT dbo.FactForecast (MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD, ScenarioLabel)
SELECT CONVERT(DATE, [Month], 23), EntityID, DepartmentID, AccountCode, CONVERT(DECIMAL(19,2), ForecastAmountAUD), Scenario
FROM stg.fact_forecast;

--------------------------------------------------------------- receivables ---
-- Open on the as-of date = issued by it and not paid by it. The source Status
-- describes the extract, which includes payments made after the as-of date.
INSERT dbo.FactARInvoice (InvoiceID, InvoiceDate, DueDate, PaidDate, CustomerID, EntityID, InvoiceAmountAUD, PaidAmountAUD,
                          SourceStatus, TermsDays, DaysToPay, DaysLate, IsPaidAfterAsOf, IsOpenAsOf, DaysPastDueAsOf,
                          AgeingBucketAsOf)
SELECT s.InvoiceID, v.doc, v.due, v.paid, s.CustomerID, s.EntityID, CONVERT(DECIMAL(19,2), s.InvoiceAmountAUD),
       CONVERT(DECIMAL(19,2), s.PaidAmountAUD), s.[Status], DATEDIFF(DAY, v.doc, v.due),
       DATEDIFF(DAY, v.doc, v.paid), DATEDIFF(DAY, v.due, v.paid),
       CASE WHEN v.paid > @AsOf THEN 1 ELSE 0 END, o.IsOpen,
       CASE WHEN o.IsOpen = 1 THEN DATEDIFF(DAY, v.due, @AsOf) END,
       CASE WHEN o.IsOpen = 1 THEN (SELECT b.BucketOrder FROM dbo.DimAgeingBucket b
                                    WHERE DATEDIFF(DAY, v.due, @AsOf) BETWEEN b.MinDaysPastDue AND b.MaxDaysPastDue) END
FROM stg.fact_ar s
CROSS APPLY (SELECT CONVERT(DATE, s.InvoiceDate, 23) AS doc, CONVERT(DATE, s.DueDate, 23) AS due,
                    TRY_CONVERT(DATE, NULLIF(s.PaidDate, N''), 23) AS paid) v
CROSS APPLY (SELECT CASE WHEN v.doc <= @AsOf AND (v.paid IS NULL OR v.paid > @AsOf) THEN 1 ELSE 0 END AS IsOpen) o;

------------------------------------------------------------------ payables ---
INSERT dbo.FactAPBill (BillID, BillDate, DueDate, PaidDate, VendorID, EntityID, BillAmountAUD, PaidAmountAUD,
                       SourceStatus, TermsDays, DaysToPay, DaysLate, IsPaidAfterAsOf, IsOpenAsOf, DaysPastDueAsOf,
                       AgeingBucketAsOf)
SELECT s.BillID, v.doc, v.due, v.paid, s.VendorID, s.EntityID, CONVERT(DECIMAL(19,2), s.BillAmountAUD),
       CONVERT(DECIMAL(19,2), s.PaidAmountAUD), s.[Status], DATEDIFF(DAY, v.doc, v.due),
       DATEDIFF(DAY, v.doc, v.paid), DATEDIFF(DAY, v.due, v.paid),
       CASE WHEN v.paid > @AsOf THEN 1 ELSE 0 END, o.IsOpen,
       CASE WHEN o.IsOpen = 1 THEN DATEDIFF(DAY, v.due, @AsOf) END,
       CASE WHEN o.IsOpen = 1 THEN (SELECT b.BucketOrder FROM dbo.DimAgeingBucket b
                                    WHERE DATEDIFF(DAY, v.due, @AsOf) BETWEEN b.MinDaysPastDue AND b.MaxDaysPastDue) END
FROM stg.fact_ap s
CROSS APPLY (SELECT CONVERT(DATE, s.BillDate, 23) AS doc, CONVERT(DATE, s.DueDate, 23) AS due,
                    TRY_CONVERT(DATE, NULLIF(s.PaidDate, N''), 23) AS paid) v
CROSS APPLY (SELECT CASE WHEN v.doc <= @AsOf AND (v.paid IS NULL OR v.paid > @AsOf) THEN 1 ELSE 0 END AS IsOpen) o;

---------------------------------------------------------------------- cash ---
INSERT dbo.FactCashBalance ([Date], EntityID, ClosingCashAUD, IsFloorValue)
SELECT CONVERT(DATE, [Date], 23), EntityID, CONVERT(DECIMAL(19,2), ClosingCashAUD),
       CASE WHEN CONVERT(DECIMAL(19,2), ClosingCashAUD) = 50000.00 THEN 1 ELSE 0 END
FROM stg.fact_cash_balance;

IF (SELECT COUNT(*) FROM dbo.FactBudget) <> 60480 OR (SELECT COUNT(*) FROM dbo.FactForecast) <> 60480
   OR (SELECT COUNT(*) FROM dbo.FactARInvoice) <> 18000 OR (SELECT COUNT(*) FROM dbo.FactAPBill) <> 12000
   OR (SELECT COUNT(*) FROM dbo.FactCashBalance) <> 10224
    THROW 50012, N'A fact table does not match its staging row count.', 1;
GO
PRINT 'Facts loaded: GL translated, budget, forecast, AR, AP, cash.';
GO
