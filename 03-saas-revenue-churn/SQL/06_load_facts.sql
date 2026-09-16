/*=============================================================================
  06_load_facts.sql

  Types and loads the source-grain facts. Nothing is derived here beyond what a
  single row can answer about itself - month keys, flags and simple date
  arithmetic. The two derived tables that need to look across months are built
  in 07, where the logic can be read on its own.

  Conventions applied here, each one from a Phase 1 finding:

  * A month key is the FIRST day of the month, everywhere, so every fact joins
    to the same date table on the same grain.
  * Tenure is COMPLETED months, not a day difference divided by 30: a customer
    who joins on the 30th has not completed a month until the 30th comes round.
  * Resolution hours are loaded as given but IsResolved is set from the status,
    because the source populates resolution time for tickets that are still
    open (audit section 7) and every mean must be able to exclude them.
  * An invoice's date can fall before its subscription starts: invoices are all
    dated to the 1st while a subscription starts on any day. The invoice month
    is therefore never used to decide when a subscription began.
=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');

/* ------------------------------------------------------------ subscriptions */
;WITH s AS (
    SELECT SubscriptionID, CustomerID, PlanID,
           TRY_CONVERT(DATE, StartDate, 23) AS StartDate,
           TRY_CONVERT(DATE, NULLIF(EndDate, N''), 23) AS EndDate,
           [Status],
           TRY_CONVERT(DECIMAL(19, 2), MRR) AS MRR,
           BillingCycle
    FROM stg.fact_subscriptions
)
INSERT dbo.FactSubscription (SubscriptionID, CustomerID, PlanID, StartDate, EndDate, StartMonth, EndMonth,
                             [Status], IsChurned, MRR, ARR, BillingCycle, TenureMonths, TenureBand)
SELECT s.SubscriptionID, s.CustomerID, s.PlanID, s.StartDate, s.EndDate,
       DATEFROMPARTS(YEAR(s.StartDate), MONTH(s.StartDate), 1),
       CASE WHEN s.EndDate IS NULL THEN NULL ELSE DATEFROMPARTS(YEAR(s.EndDate), MONTH(s.EndDate), 1) END,
       s.[Status],
       CASE WHEN s.EndDate IS NULL THEN 0 ELSE 1 END,
       s.MRR, s.MRR * 12, s.BillingCycle,
       t.TenureMonths,
       b.TenureBand
FROM s
CROSS APPLY (SELECT COALESCE(s.EndDate, @AsOf) AS CutDate) c
CROSS APPLY (SELECT DATEDIFF(MONTH, s.StartDate, c.CutDate)
                    - CASE WHEN DAY(c.CutDate) < DAY(s.StartDate) THEN 1 ELSE 0 END AS TenureMonths) t
CROSS APPLY (SELECT TOP (1) TenureBand FROM dbo.DimTenureBand
             WHERE t.TenureMonths BETWEEN MinMonths AND MaxMonths) b;
GO

/* ----------------------------------------------------------------- invoices */
;WITH i AS (
    SELECT InvoiceID, SubscriptionID, CustomerID,
           TRY_CONVERT(DATE, InvoiceDate, 23) AS InvoiceDate,
           TRY_CONVERT(DECIMAL(19, 2), InvoiceAmount) AS InvoiceAmount,
           TRY_CONVERT(DATE, NULLIF(PaymentDate, N''), 23) AS PaymentDate,
           PaymentStatus
    FROM stg.fact_invoices
)
INSERT dbo.FactInvoice (InvoiceID, SubscriptionID, CustomerID, InvoiceDate, InvoiceMonth, InvoiceAmount,
                        PaymentDate, PaymentStatus, IsFailed, DaysToPay)
SELECT i.InvoiceID, i.SubscriptionID, i.CustomerID, i.InvoiceDate,
       DATEFROMPARTS(YEAR(i.InvoiceDate), MONTH(i.InvoiceDate), 1),
       i.InvoiceAmount, i.PaymentDate, i.PaymentStatus,
       CASE WHEN i.PaymentStatus = N'Failed' THEN 1 ELSE 0 END,
       CASE WHEN i.PaymentDate IS NULL THEN NULL ELSE DATEDIFF(DAY, i.InvoiceDate, i.PaymentDate) END
FROM i;
GO

/* -------------------------------------------------------------------- usage */
INSERT dbo.FactUsageMonthly (MonthStart, CustomerID, LicensedSeats, ActiveUsers, Logins,
                             FeatureAdoptionRate, CriticalErrors)
SELECT TRY_CONVERT(DATE, [Month], 23), CustomerID,
       TRY_CONVERT(INT, LicensedSeats), TRY_CONVERT(INT, ActiveUsers), TRY_CONVERT(INT, Logins),
       TRY_CONVERT(DECIMAL(9, 4), FeatureAdoptionRate), TRY_CONVERT(INT, CriticalErrors)
FROM stg.fact_product_usage_monthly;
GO

/* ------------------------------------------------------------------ tickets */
INSERT dbo.FactSupportTicket (TicketID, CustomerID, OpenedDate, OpenedMonth, Severity, ResolutionHours,
                              [Status], IsResolved, Category)
SELECT TicketID, CustomerID,
       TRY_CONVERT(DATE, OpenedDate, 23),
       DATEFROMPARTS(YEAR(TRY_CONVERT(DATE, OpenedDate, 23)), MONTH(TRY_CONVERT(DATE, OpenedDate, 23)), 1),
       Severity,
       TRY_CONVERT(DECIMAL(9, 2), ResolutionHours),
       [Status],
       CASE WHEN [Status] = N'Resolved' THEN 1 ELSE 0 END,
       Category
FROM stg.fact_support_tickets;
GO

/* -------------------------------------------------------------- acquisition */
INSERT dbo.FactAcquisition (CustomerID, AcquisitionMonth, AcquisitionCost)
SELECT a.CustomerID, c.CohortMonth, TRY_CONVERT(DECIMAL(19, 2), a.AcquisitionCost)
FROM stg.fact_customer_acquisition a
JOIN dbo.DimCustomer c ON c.CustomerID = a.CustomerID;
GO

CREATE INDEX IX_FactInvoice_Month     ON dbo.FactInvoice (InvoiceMonth) INCLUDE (InvoiceAmount, IsFailed);
CREATE INDEX IX_FactInvoice_Customer  ON dbo.FactInvoice (CustomerID)   INCLUDE (InvoiceAmount, IsFailed);
CREATE INDEX IX_FactTicket_Month      ON dbo.FactSupportTicket (OpenedMonth) INCLUDE (IsResolved, ResolutionHours);
CREATE INDEX IX_FactTicket_Customer   ON dbo.FactSupportTicket (CustomerID);
CREATE INDEX IX_FactUsage_Customer    ON dbo.FactUsageMonthly (CustomerID);
CREATE INDEX IX_FactSub_Customer      ON dbo.FactSubscription (CustomerID) INCLUDE (MRR, StartDate, EndDate);
GO

DECLARE @msg NVARCHAR(400) = CONCAT(
    N'Facts loaded: subscriptions ', (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactSubscription),
    N', invoices ',  (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactInvoice),
    N', usage ',     (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactUsageMonthly),
    N', tickets ',   (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactSupportTicket),
    N', acquisition ', (SELECT FORMAT(COUNT(*), N'N0') FROM dbo.FactAcquisition), N'.');
PRINT @msg;
GO
