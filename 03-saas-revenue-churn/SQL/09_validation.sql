/*=============================================================================
  09_validation.sql

  Every claim the build makes, checked against the data.

  A check is a name, an expected value and an actual value computed from the
  tables. The script prints them all and raises if any fails, so the build
  cannot "succeed" with a broken star, a lost row, or a waterfall that does not
  add up.

  The two that matter most are the identities in section 7: the whole project
  rests on the movement ledger explaining the change in MRR exactly, and on the
  customer count doing the same. If either drifts by a cent, the waterfall is
  decoration and the script says so.
=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @Checks TABLE (Seq INT IDENTITY(1, 1), Area NVARCHAR(30), CheckName NVARCHAR(160),
                       Expected NVARCHAR(60), Actual NVARCHAR(60));

DECLARE @AsOf DATE = (SELECT TRY_CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = N'AsOfDate');
DECLARE @AsOfMonth DATE = DATEFROMPARTS(YEAR(@AsOf), MONTH(@AsOf), 1);

/* ------------------------------------------------------ 1. row counts ---- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Rows', N'DimCustomer', N'12000', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.DimCustomer
UNION ALL SELECT N'Rows', N'DimPlan', N'4', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.DimPlan
UNION ALL SELECT N'Rows', N'FactSubscription', N'12000', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactSubscription
UNION ALL SELECT N'Rows', N'FactInvoice', N'177236', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactInvoice
UNION ALL SELECT N'Rows', N'FactUsageMonthly', N'113038', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactUsageMonthly
UNION ALL SELECT N'Rows', N'FactSupportTicket', N'45000', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactSupportTicket
UNION ALL SELECT N'Rows', N'FactAcquisition', N'12000', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactAcquisition
UNION ALL SELECT N'Rows', N'SecurityUserAccess', N'8', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.SecurityUserAccess
UNION ALL SELECT N'Rows', N'DimSeverity', N'4', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.DimSeverity
UNION ALL SELECT N'Rows', N'DimMovementType', N'5', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.DimMovementType
UNION ALL SELECT N'Rows', N'DimTenureBand', N'5', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.DimTenureBand
UNION ALL SELECT N'Rows', N'ModelConfig', N'6', CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.ModelConfig
UNION ALL SELECT N'Rows', N'Every staging row reached dbo (subscriptions)',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_subscriptions)), CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactSubscription
UNION ALL SELECT N'Rows', N'Every staging row reached dbo (invoices)',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_invoices)), CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactInvoice
UNION ALL SELECT N'Rows', N'Every staging row reached dbo (usage)',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_product_usage_monthly)), CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactUsageMonthly
UNION ALL SELECT N'Rows', N'Every staging row reached dbo (tickets)',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_support_tickets)), CONVERT(NVARCHAR(60), COUNT(*)) FROM dbo.FactSupportTicket;

/* ---------------------------------------------------- 2. typing worked ---- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Typing', N'Subscription start dates all parsed', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_subscriptions WHERE TRY_CONVERT(DATE, StartDate, 23) IS NULL))
UNION ALL SELECT N'Typing', N'Subscription MRR all parsed', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_subscriptions WHERE TRY_CONVERT(DECIMAL(19, 2), MRR) IS NULL))
UNION ALL SELECT N'Typing', N'Invoice amounts all parsed', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM stg.fact_invoices WHERE TRY_CONVERT(DECIMAL(19, 2), InvoiceAmount) IS NULL))
UNION ALL SELECT N'Typing', N'Only failed invoices lack a payment date', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice WHERE CASE WHEN PaymentDate IS NULL THEN 1 ELSE 0 END <> IsFailed))
UNION ALL SELECT N'Typing', N'Adoption rate within 0 and 1', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactUsageMonthly WHERE FeatureAdoptionRate < 0 OR FeatureAdoptionRate > 1))
UNION ALL SELECT N'Typing', N'Resolution hours never negative', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSupportTicket WHERE ResolutionHours < 0));

/* ------------------------------------------------ 3. referential integrity  */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Integrity', N'Subscriptions with an unknown customer', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription s WHERE NOT EXISTS (SELECT 1 FROM dbo.DimCustomer c WHERE c.CustomerID = s.CustomerID)))
UNION ALL SELECT N'Integrity', N'Invoices with an unknown subscription', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i WHERE NOT EXISTS (SELECT 1 FROM dbo.FactSubscription s WHERE s.SubscriptionID = i.SubscriptionID)))
UNION ALL SELECT N'Integrity', N'Usage rows with an unknown customer', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactUsageMonthly u WHERE NOT EXISTS (SELECT 1 FROM dbo.DimCustomer c WHERE c.CustomerID = u.CustomerID)))
UNION ALL SELECT N'Integrity', N'Tickets with an unknown customer', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSupportTicket t WHERE NOT EXISTS (SELECT 1 FROM dbo.DimCustomer c WHERE c.CustomerID = t.CustomerID)))
UNION ALL SELECT N'Integrity', N'Every customer has exactly one subscription', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM (SELECT CustomerID FROM dbo.FactSubscription GROUP BY CustomerID HAVING COUNT(*) = 1) q))
UNION ALL SELECT N'Integrity', N'Every customer has exactly one acquisition row', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactAcquisition))
-- Plan is carried on the customer so that a plan filter reaches tickets, usage and
-- invoices. That is only sound while a customer has exactly one plan, so check it.
UNION ALL SELECT N'Integrity', N'Every customer has exactly one plan', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM (SELECT CustomerID FROM dbo.FactSubscription
                              GROUP BY CustomerID HAVING COUNT(DISTINCT PlanID) > 1) q))
UNION ALL SELECT N'Integrity', N'The customer''s plan matches the subscription''s', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimCustomer c
                              JOIN dbo.FactSubscription s ON s.CustomerID = c.CustomerID
                              WHERE s.PlanID <> c.PlanID))
-- Billing cycle and status live on the customer for the same reason as plan: a slicer
-- on them has to reach the snapshot, and a filter never travels from fact to fact.
UNION ALL SELECT N'Integrity', N'The customer''s billing cycle matches the subscription''s', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimCustomer c
                              JOIN dbo.FactSubscription s ON s.CustomerID = c.CustomerID
                              WHERE s.BillingCycle <> c.BillingCycle))
UNION ALL SELECT N'Integrity', N'The customer''s status matches the subscription''s', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimCustomer c
                              JOIN dbo.FactSubscription s ON s.CustomerID = c.CustomerID
                              WHERE s.[Status] <> c.SubscriptionStatus OR s.IsChurned <> c.IsChurned))
UNION ALL SELECT N'Integrity', N'Snapshot rows with a cohort not in DimCohort', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth m WHERE NOT EXISTS (SELECT 1 FROM dbo.DimCohort c WHERE c.CohortMonth = m.CohortMonth)))
UNION ALL SELECT N'Integrity', N'Snapshot rows with a tenure not in DimTenureMonth', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth m WHERE NOT EXISTS (SELECT 1 FROM dbo.DimTenureMonth t WHERE t.TenureMonth = m.TenureMonth)))
UNION ALL SELECT N'Integrity', N'Security countries that exist in DimCustomer', N'6',
       CONVERT(NVARCHAR(60), (SELECT COUNT(DISTINCT s.Country) FROM dbo.SecurityUserAccess s
                              WHERE s.Country <> N'ALL' AND EXISTS (SELECT 1 FROM dbo.DimCustomer c WHERE c.Country = s.Country)));

/* ------------------------------------------------------- 4. the calendar --- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Calendar', N'No gap in the date table', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimDate d WHERE d.[Date] < (SELECT MAX([Date]) FROM dbo.DimDate)
                              AND NOT EXISTS (SELECT 1 FROM dbo.DimDate n WHERE n.[Date] = DATEADD(DAY, 1, d.[Date]))))
UNION ALL SELECT N'Calendar', N'As-of date is the last source day', CONVERT(NVARCHAR(60), @AsOf),
       CONVERT(NVARCHAR(60), (SELECT MAX([Date]) FROM dbo.DimDate WHERE IsSourceCalendar = 1))
UNION ALL SELECT N'Calendar', N'Days flagged after the as-of date', N'303',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimDate WHERE IsAfterAsOf = 1))
UNION ALL SELECT N'Calendar', N'Added days are all after the as-of date', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimDate WHERE IsSourceCalendar = 0 AND IsAfterAsOf = 0))
UNION ALL SELECT N'Calendar', N'The financial year starts in July', N'1',
       CONVERT(NVARCHAR(60), (SELECT FinancialMonthNo FROM dbo.DimDate WHERE [Date] = N'2026-07-01'))
UNION ALL SELECT N'Calendar', N'MonthOffset is zero in the as-of month', N'0',
       CONVERT(NVARCHAR(60), (SELECT DISTINCT MonthOffset FROM dbo.DimDate WHERE MonthStart = @AsOfMonth))
UNION ALL SELECT N'Calendar', N'Every fact date exists in the calendar', N'0',
       CONVERT(NVARCHAR(60),
           (SELECT COUNT(*) FROM dbo.FactInvoice i WHERE NOT EXISTS (SELECT 1 FROM dbo.DimDate d WHERE d.[Date] = i.InvoiceDate))
         + (SELECT COUNT(*) FROM dbo.FactSupportTicket t WHERE NOT EXISTS (SELECT 1 FROM dbo.DimDate d WHERE d.[Date] = t.OpenedDate))
         + (SELECT COUNT(*) FROM dbo.FactSubscription s WHERE NOT EXISTS (SELECT 1 FROM dbo.DimDate d WHERE d.[Date] = s.StartDate))
         + (SELECT COUNT(*) FROM dbo.FactSubscription s WHERE s.EndDate IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.DimDate d WHERE d.[Date] = s.EndDate)));

/* ----------------------------------------------- 5. the subscription facts - */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Lifecycle', N'Active subscriptions', N'9708',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE IsChurned = 0))
UNION ALL SELECT N'Lifecycle', N'Churned subscriptions', N'2292',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE IsChurned = 1))
UNION ALL SELECT N'Lifecycle', N'Status and end date never disagree', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE CASE WHEN EndDate IS NULL THEN 1 ELSE 0 END <> CASE WHEN [Status] = N'Active' THEN 1 ELSE 0 END))
UNION ALL SELECT N'Lifecycle', N'No subscription ends on or before it starts', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE EndDate <= StartDate))
UNION ALL SELECT N'Lifecycle', N'Subscription start equals customer signup', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription s JOIN dbo.DimCustomer c ON c.CustomerID = s.CustomerID
                              WHERE s.StartDate <> c.SignupDate))
UNION ALL SELECT N'Lifecycle', N'Tenure is never negative', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE TenureMonths < 0))
UNION ALL SELECT N'Lifecycle', N'No subscription starts and ends in one month', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscription WHERE EndMonth = StartMonth))
UNION ALL SELECT N'Lifecycle', N'Newest subscription start', N'2026-06-30',
       CONVERT(NVARCHAR(60), (SELECT MAX(StartDate) FROM dbo.FactSubscription))
UNION ALL SELECT N'Lifecycle', N'Latest churn date', N'2026-08-30',
       CONVERT(NVARCHAR(60), (SELECT MAX(EndDate) FROM dbo.FactSubscription));

/* --------------------------------------------------------- 6. the billing -- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Billing', N'Annual invoices that are not 12x MRR', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                              WHERE s.BillingCycle = N'Annual' AND ABS(i.InvoiceAmount - s.MRR * 12) > 0.02))
UNION ALL SELECT N'Billing', N'Monthly invoices that are not the MRR', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                              WHERE s.BillingCycle = N'Monthly' AND ABS(i.InvoiceAmount - s.MRR) > 0.02))
UNION ALL SELECT N'Billing', N'Invoices dated after the subscription ended', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                              WHERE s.EndDate IS NOT NULL AND i.InvoiceDate > s.EndDate))
UNION ALL SELECT N'Billing', N'Invoices dated before the subscription started', N'11599',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                              WHERE i.InvoiceDate < s.StartDate))
UNION ALL SELECT N'Billing', N'...and every one of them inside the start month', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice i JOIN dbo.FactSubscription s ON s.SubscriptionID = i.SubscriptionID
                              WHERE i.InvoiceDate < s.StartDate AND i.InvoiceMonth <> s.StartMonth))
UNION ALL SELECT N'Billing', N'Every invoice is dated the 1st of a month', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice WHERE DAY(InvoiceDate) <> 1))
UNION ALL SELECT N'Billing', N'Failed invoices', N'6041',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice WHERE IsFailed = 1))
UNION ALL SELECT N'Billing', N'Days to pay is never negative', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactInvoice WHERE DaysToPay < 0));

/* ---------------------------------- 7. the snapshot and the two identities - */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Snapshot', N'Snapshot rows equal the sum of live months',
       CONVERT(NVARCHAR(60), (SELECT SUM(CONVERT(BIGINT, 1)) FROM dbo.FactSubscription s
                              JOIN dbo.DimDate d ON d.[Date] = d.MonthStart AND d.MonthStart <= @AsOfMonth
                               AND s.StartDate <= d.MonthEnd AND (s.EndDate IS NULL OR s.EndDate > d.MonthEnd))),
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth))
UNION ALL SELECT N'Snapshot', N'Every subscription appears at least once', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(DISTINCT SubscriptionID) FROM dbo.FactSubscriptionMonth))
UNION ALL SELECT N'Snapshot', N'One first month per subscription', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth WHERE IsFirstMonth = 1))
UNION ALL SELECT N'Snapshot', N'One last month per subscription', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth WHERE IsLastMonth = 1))
UNION ALL SELECT N'Snapshot', N'Tenure month is never negative', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth WHERE TenureMonth < 0))
UNION ALL SELECT N'Snapshot', N'Active customers in the as-of month', N'9708',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth WHERE MonthStart = @AsOfMonth))
UNION ALL SELECT N'Snapshot', N'Snapshot never runs past the as-of month', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactSubscriptionMonth WHERE MonthStart > @AsOfMonth));

-- Identity 1: the movement ledger explains the change in MRR, every month.
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Identity', N'Months where MRR does not equal prior MRR + movements', N'0',
       CONVERT(NVARCHAR(60), (
           SELECT COUNT(*) FROM (
               SELECT m.MonthStart,
                      SUM(m.MRR) AS ThisMRR,
                      LAG(SUM(m.MRR)) OVER (ORDER BY m.MonthStart) AS PriorMRR,
                      (SELECT COALESCE(SUM(v.MRRDelta), 0) FROM dbo.FactMRRMovement v WHERE v.MonthStart = m.MonthStart) AS Delta
               FROM dbo.FactSubscriptionMonth m GROUP BY m.MonthStart) q
           WHERE PriorMRR IS NOT NULL AND ABS(ThisMRR - (PriorMRR + Delta)) > 0.01));

-- Identity 2: the customer count does the same.
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Identity', N'Months where customers do not equal prior + new - churn', N'0',
       CONVERT(NVARCHAR(60), (
           SELECT COUNT(*) FROM (
               SELECT m.MonthStart,
                      COUNT(DISTINCT m.CustomerID) AS ThisN,
                      LAG(COUNT(DISTINCT m.CustomerID)) OVER (ORDER BY m.MonthStart) AS PriorN,
                      (SELECT COUNT(*) FROM dbo.FactMRRMovement v WHERE v.MonthStart = m.MonthStart AND v.MovementType IN (N'New', N'Reactivation')) AS Won,
                      (SELECT COUNT(*) FROM dbo.FactMRRMovement v WHERE v.MonthStart = m.MonthStart AND v.MovementType = N'Churn') AS Lost
               FROM dbo.FactSubscriptionMonth m GROUP BY m.MonthStart) q
           WHERE PriorN IS NOT NULL AND ThisN <> PriorN + Won - Lost));

/* -------------------------------------------------- 8. the movement ledger - */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Movement', N'New movements equal the customer count', N'12000',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'New'))
UNION ALL SELECT N'Movement', N'Churn movements equal churned subscriptions', N'2292',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Churn'))
UNION ALL SELECT N'Movement', N'Expansion movements (structurally impossible here)', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Expansion'))
UNION ALL SELECT N'Movement', N'Contraction movements (structurally impossible here)', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Contraction'))
UNION ALL SELECT N'Movement', N'Reactivation movements (structurally impossible here)', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Reactivation'))
UNION ALL SELECT N'Movement', N'New MRR is always positive', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'New' AND MRRDelta <= 0))
UNION ALL SELECT N'Movement', N'Churn MRR is always negative', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MovementType = N'Churn' AND MRRDelta >= 0))
UNION ALL SELECT N'Movement', N'New MRR total equals the sum of opening MRR',
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), SUM(MRR)) FROM dbo.FactSubscription)),
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), SUM(MRRDelta)) FROM dbo.FactMRRMovement WHERE MovementType = N'New'))
UNION ALL SELECT N'Movement', N'Churned MRR total equals the churned subscriptions'' MRR',
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), -SUM(MRR)) FROM dbo.FactSubscription WHERE IsChurned = 1)),
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), SUM(MRRDelta)) FROM dbo.FactMRRMovement WHERE MovementType = N'Churn'))
UNION ALL SELECT N'Movement', N'Movements never run past the as-of month', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.FactMRRMovement WHERE MonthStart > @AsOfMonth));

/* ------------------------------------------------------------ 9. cohorts --- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Cohort', N'Cohort sizes sum to the customer count', N'12000',
       CONVERT(NVARCHAR(60), (SELECT SUM(CohortSize) FROM dbo.DimCohort))
UNION ALL SELECT N'Cohort', N'Cohorts', N'54', CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimCohort))
UNION ALL SELECT N'Cohort', N'Cohort MRR equals total opening MRR',
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), SUM(MRR)) FROM dbo.FactSubscription)),
       CONVERT(NVARCHAR(60), (SELECT CONVERT(DECIMAL(19, 2), SUM(CohortMRR)) FROM dbo.DimCohort))
UNION ALL SELECT N'Cohort', N'Every cohort has a month-zero row in the snapshot', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM dbo.DimCohort c
                              WHERE NOT EXISTS (SELECT 1 FROM dbo.FactSubscriptionMonth m
                                                WHERE m.CohortMonth = c.CohortMonth AND m.TenureMonth = 0)))
UNION ALL SELECT N'Cohort', N'Month-zero customers equal the cohort size', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM (
           SELECT c.CohortMonth FROM dbo.DimCohort c
           JOIN (SELECT CohortMonth, COUNT(*) AS n FROM dbo.FactSubscriptionMonth WHERE TenureMonth = 0 GROUP BY CohortMonth) m
             ON m.CohortMonth = c.CohortMonth
           WHERE m.n <> c.CohortSize) q));

/* ------------------------------------------- 10. the churn-driver evidence - */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Drivers', N'Drivers measured', N'11',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM analytics.vw_ChurnDriverStrength))
UNION ALL SELECT N'Drivers', N'Every driver has a correlation', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM analytics.vw_ChurnDriverStrength WHERE Correlation IS NULL))
UNION ALL SELECT N'Drivers', N'No product-usage driver reaches |r| = 0.05', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM analytics.vw_ChurnDriverStrength WHERE DriverGroup = N'Product' AND ABS(Correlation) >= 0.05))
UNION ALL SELECT N'Drivers', N'Plan price point is negatively related to churn', N'1',
       CONVERT(NVARCHAR(60), (SELECT CASE WHEN Correlation < -0.10 THEN 1 ELSE 0 END FROM analytics.vw_ChurnDriverStrength WHERE Driver = N'Plan price point (MRR)'))
UNION ALL SELECT N'Drivers', N'Contact RATE is positively related to churn', N'1',
       CONVERT(NVARCHAR(60), (SELECT CASE WHEN Correlation > 0.10 THEN 1 ELSE 0 END FROM analytics.vw_ChurnDriverStrength WHERE Driver = N'Support contact rate (per month)'))
UNION ALL SELECT N'Drivers', N'Raw ticket COUNT is not', N'1',
       CONVERT(NVARCHAR(60), (SELECT CASE WHEN ABS(Correlation) < 0.05 THEN 1 ELSE 0 END FROM analytics.vw_ChurnDriverStrength WHERE Driver = N'Raw ticket count'))
UNION ALL SELECT N'Drivers', N'Payment failure RATE is not', N'1',
       CONVERT(NVARCHAR(60), (SELECT CASE WHEN ABS(Correlation) < 0.05 THEN 1 ELSE 0 END FROM analytics.vw_ChurnDriverStrength WHERE Driver = N'Payment failure rate'))
UNION ALL SELECT N'Drivers', N'Churn falls as the plan gets larger', N'1',
       CONVERT(NVARCHAR(60), (SELECT CASE WHEN MIN(ok) = 1 THEN 1 ELSE 0 END FROM (
           SELECT CASE WHEN LAG(r) OVER (ORDER BY p.PlanOrder) IS NULL OR r < LAG(r) OVER (ORDER BY p.PlanOrder) THEN 1 ELSE 0 END AS ok
           FROM (SELECT s.PlanID, AVG(CONVERT(FLOAT, s.IsChurned)) AS r FROM dbo.FactSubscription s GROUP BY s.PlanID) x
           JOIN dbo.DimPlan p ON p.PlanID = x.PlanID) y));

/* ---------------------------------------------------- 11. the views work --- */
INSERT @Checks (Area, CheckName, Expected, Actual)
SELECT N'Views', N'Data-quality metrics published', N'15',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric))
UNION ALL SELECT N'Views', N'No data-quality metric is null', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric WHERE MetricValue IS NULL))
UNION ALL SELECT N'Views', N'Analytics views defined', N'19',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM sys.views v JOIN sys.schemas s ON s.schema_id = v.schema_id WHERE s.name = N'analytics'))
UNION ALL SELECT N'Views', N'No analytics view selects *', N'0',
       CONVERT(NVARCHAR(60), (SELECT COUNT(*) FROM sys.sql_modules m JOIN sys.views v ON v.object_id = m.object_id
                              JOIN sys.schemas s ON s.schema_id = v.schema_id
                              WHERE s.name = N'analytics' AND m.definition LIKE N'%SELECT *%'));

/* -------------------------------------------------------------- results ---- */
SELECT Seq, Area, CheckName, Expected, Actual,
       CASE WHEN Expected = Actual THEN N'PASS' ELSE N'** FAIL **' END AS Result
FROM @Checks ORDER BY Seq;

DECLARE @Total INT = (SELECT COUNT(*) FROM @Checks);
DECLARE @Failed INT = (SELECT COUNT(*) FROM @Checks WHERE Expected <> Actual);
PRINT N'';
PRINT CONCAT(N'VALIDATION: ', @Total - @Failed, N' of ', @Total, N' checks passed.');
IF @Failed > 0
BEGIN
    SELECT Area, CheckName, Expected, Actual FROM @Checks WHERE Expected <> Actual ORDER BY Seq;
    THROW 51009, N'Validation failed - see the rows above.', 1;
END
GO
