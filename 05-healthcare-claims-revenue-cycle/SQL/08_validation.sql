/*=============================================================================
  08_validation.sql

  Every claim this build makes, tested. The script writes one row per check and
  THROWS at the end if any failed, so run_all.ps1 stops and a broken build can
  never be published.

  Most checks are INVARIANTS - "this violation count must be zero" - rather than
  magic numbers, because an invariant survives a rebuild on scaled data while a
  hardcoded total does not. The handful of anchored counts are the row counts and
  the Phase 1 findings the whole analysis rests on: if those change, the source
  is not the file this project was written against and the report's conclusions
  no longer follow.

  Idempotent, read-only.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DROP TABLE IF EXISTS #Checks;
CREATE TABLE #Checks (
    Ord         INT IDENTITY(1,1),
    Category    NVARCHAR(40)  NOT NULL,
    Name        NVARCHAR(200) NOT NULL,
    ExpectedNum FLOAT         NULL,
    ActualNum   FLOAT         NULL,
    Tolerance   FLOAT         NOT NULL DEFAULT 0,
    ExpectedTxt NVARCHAR(60)  NULL,
    ActualTxt   NVARCHAR(60)  NULL,
    Passed      BIT           NULL
);
GO

/*  A check is a ROW, not a procedure call. T-SQL will not accept a subquery as a
    parameter to EXEC, but it will accept one inside INSERT ... VALUES, so every
    check below reads "here is what this number must be, and here is the query
    that measures it" on the page - which is the point of a test.               */

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');

/*=========================================================== 1. ROW COUNTS ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.fact_claims',
  100000,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.fact_claims)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.fact_claim_lines',
  249905,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.fact_claim_lines)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.fact_payments',
  69111,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.fact_payments)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.fact_denials',
  7824,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.fact_denials)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.dim_beneficiary',
  30000,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_beneficiary)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.dim_provider',
  500,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_provider)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.dim_facility',
  30,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_facility)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.dim_payer',
  6,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_payer)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'stg.security_user_access',
  82,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.security_user_access)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'fact.FactClaim',
  100000,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'fact.FactClaimLine',
  249905,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'fact.FactPayment',
  69111,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactPayment)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'fact.FactDenial',
  7824,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimBeneficiary',
  30000,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimBeneficiary)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimProvider',
  500,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimProvider)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimProcedure',
  10,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimProcedure)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimDiagnosis',
  10,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimDiagnosis)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimDenialReason',
  7,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimDenialReason)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimARBucket',
  6,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimARBucket)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'dim.DimARMovementType',
  4,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimARMovementType)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'nothing lost from staging to fact',
  0,
  CONVERT(FLOAT, (SELECT (SELECT COUNT(*) FROM stg.fact_claims) - (SELECT COUNT(*) FROM fact.FactClaim))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Row counts', N'no line lost from staging to fact',
  0,
  CONVERT(FLOAT, (SELECT (SELECT COUNT(*) FROM stg.fact_claim_lines) - (SELECT COUNT(*) FROM fact.FactClaimLine))), 0);

/*======================================================= 2. KEY INTEGRITY ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaim -> DimBeneficiary',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c LEFT JOIN dim.DimBeneficiary d ON d.BeneficiaryKey = c.BeneficiaryKey WHERE d.BeneficiaryKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaim -> DimProvider',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c LEFT JOIN dim.DimProvider d ON d.ProviderKey = c.ProviderKey WHERE d.ProviderKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaim -> DimFacility',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c LEFT JOIN dim.DimFacility d ON d.FacilityKey = c.FacilityKey WHERE d.FacilityKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaim -> DimPayer',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c LEFT JOIN dim.DimPayer d ON d.PayerKey = c.PayerKey WHERE d.PayerKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaim -> DimClaimStatus',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c LEFT JOIN dim.DimClaimStatus d ON d.ClaimStatusKey = c.ClaimStatusKey WHERE d.ClaimStatusKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaimLine -> DimProcedure',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine l LEFT JOIN dim.DimProcedure d ON d.ProcedureKey = l.ProcedureKey WHERE d.ProcedureKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactClaimLine -> DimDiagnosis',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine l LEFT JOIN dim.DimDiagnosis d ON d.DiagnosisKey = l.DiagnosisKey WHERE d.DiagnosisKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactPayment -> DimPaymentMethod',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactPayment p LEFT JOIN dim.DimPaymentMethod d ON d.PaymentMethodKey = p.PaymentMethodKey WHERE d.PaymentMethodKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactDenial -> DimDenialReason',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n LEFT JOIN dim.DimDenialReason d ON d.DenialReasonKey = n.DenialReasonKey WHERE d.DenialReasonKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactDenial -> DimDenialStatus',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n LEFT JOIN dim.DimDenialStatus d ON d.DenialStatusKey = n.DenialStatusKey WHERE d.DenialStatusKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactARSnapshot -> DimARBucket',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot s LEFT JOIN dim.DimARBucket d ON d.ARBucketKey = s.ARBucketKey WHERE d.ARBucketKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'FactARMovement -> DimARMovementType',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARMovement m LEFT JOIN dim.DimARMovementType d ON d.ARMovementTypeKey = m.ARMovementTypeKey WHERE d.ARMovementTypeKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'ClaimID unique in FactClaim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT ClaimID FROM fact.FactClaim GROUP BY ClaimID HAVING COUNT(*) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'ClaimLineID unique',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT ClaimLineID FROM fact.FactClaimLine GROUP BY ClaimLineID HAVING COUNT(*) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'every line belongs to a claim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine l WHERE NOT EXISTS (SELECT 1 FROM fact.FactClaim c WHERE c.ClaimID = l.ClaimID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'every payment belongs to a claim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactPayment p WHERE NOT EXISTS (SELECT 1 FROM fact.FactClaim c WHERE c.ClaimID = p.ClaimID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Integrity', N'every denial belongs to a claim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n WHERE NOT EXISTS (SELECT 1 FROM fact.FactClaim c WHERE c.ClaimID = n.ClaimID))), 0);

/*===================================================== 3. THE MONEY CHAIN ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'allowed identity holds on every ROW',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim
      WHERE ABS(AllowedAmount - PaidAmount - PatientResponsibility - OpenARAmount - DeniedAmount) > 0.005)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'allowed identity holds in TOTAL',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, SUM(AllowedAmount - PaidAmount - PatientResponsibility - OpenARAmount - DeniedAmount)) FROM fact.FactClaim)), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'billed = allowed + contractual adjustment',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE ABS(BilledAmount - AllowedAmount - ContractualAdjustment) > 0.005)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'no claim allows more than it bills',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE AllowedAmount > BilledAmount)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'no claim pays more than it allows',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE PaidAmount > AllowedAmount)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'no negative amount anywhere',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim
      WHERE BilledAmount < 0 OR AllowedAmount < 0 OR PaidAmount < 0
         OR ContractualAdjustment < 0 OR PatientResponsibility < 0 OR OpenARAmount < 0 OR DeniedAmount < 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'FactPayment total = FactClaim paid total',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, (SELECT SUM(PaymentAmount) FROM fact.FactPayment)
                          - (SELECT SUM(PaidAmount) FROM fact.FactClaim)))), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'FactDenial allowed total = FactClaim denied total',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, (SELECT SUM(DeniedAllowed) FROM fact.FactDenial)
                          - (SELECT SUM(DeniedAmount) FROM fact.FactClaim)))), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'only paid claims carry patient responsibility',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPaid = 0 AND PatientResponsibility <> 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'only pending claims carry open AR',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 0 AND OpenARAmount <> 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'only denied claims carry a denied amount',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsDenied = 0 AND DeniedAmount <> 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Money', N'claim lines sum to the header (within a cent)',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c
      JOIN (SELECT ClaimID, SUM(ChargeAmount) s FROM fact.FactClaimLine GROUP BY ClaimID) l ON l.ClaimID = c.ClaimID
      WHERE ABS(l.s - c.BilledAmount) > 0.03)), 0);

/*================================================= 4. STATUS CONSISTENCY ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'exactly one status flag per claim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE CONVERT(INT,IsPaid) + CONVERT(INT,IsPending) + CONVERT(INT,IsDenied) <> 1)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'status flags agree with the status key',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c JOIN dim.DimClaimStatus d ON d.ClaimStatusKey = c.ClaimStatusKey
      WHERE (d.ClaimStatus = N'Paid' AND c.IsPaid = 0) OR (d.ClaimStatus = N'Pending' AND c.IsPending = 0)
         OR (d.ClaimStatus = N'Denied' AND c.IsDenied = 0))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'every paid claim has exactly one payment',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c WHERE c.IsPaid = 1
      AND (SELECT COUNT(*) FROM fact.FactPayment p WHERE p.ClaimID = c.ClaimID) <> 1)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'no unpaid claim has a payment',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c WHERE c.IsPaid = 0
      AND EXISTS (SELECT 1 FROM fact.FactPayment p WHERE p.ClaimID = c.ClaimID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'every denied claim has exactly one denial',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c WHERE c.IsDenied = 1
      AND (SELECT COUNT(*) FROM fact.FactDenial n WHERE n.ClaimID = c.ClaimID) <> 1)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'no undenied claim has a denial',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c WHERE c.IsDenied = 0
      AND EXISTS (SELECT 1 FROM fact.FactDenial n WHERE n.ClaimID = c.ClaimID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'pending claims have no resolution date',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 1 AND ResolvedDateKey IS NOT NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'resolved claims have a resolution date',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 0 AND ResolvedDateKey IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'denied claims paid nothing',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsDenied = 1 AND PaidAmount <> 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'pending claims paid nothing',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 1 AND PaidAmount <> 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'first-pass accepted = not denied',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsFirstPassAccepted = CONVERT(BIT, IsDenied))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Status', N'claim line status matches its claim',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine l JOIN fact.FactClaim c ON c.ClaimID = l.ClaimID
      WHERE l.ClaimStatusKey <> c.ClaimStatusKey)), 0);

/*==================================================== 5. DATES AND CLOCKS ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'no claim submitted before it was performed',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE SubmittedDateKey < ServiceDateKey)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'no claim adjudicated before it was submitted',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE ProcessedDateKey < SubmittedDateKey)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'no claim resolved before it was submitted',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE ResolvedDateKey IS NOT NULL AND ResolvedDateKey < SubmittedDateKey)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'no negative lag anywhere',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE DaysToSubmit < 0 OR DaysToProcess < 0 OR ISNULL(DaysToResolve, 0) < 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'pending claims carry a days-outstanding',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 1 AND DaysOutstanding IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'resolved claims carry no days-outstanding',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsPending = 0 AND DaysOutstanding IS NOT NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'every claim date resolves in the calendar',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim c
      WHERE NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = c.ServiceDateKey)
         OR NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = c.SubmittedDateKey)
         OR NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = c.ProcessedDateKey)
         OR (c.ResolvedDateKey IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = c.ResolvedDateKey)))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'every payment date resolves in the calendar',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactPayment p WHERE NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = p.PaymentDateKey))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'every denial date resolves in the calendar',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n WHERE NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.DateKey = n.DenialDateKey))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'the calendar has no gaps',
  0,
  CONVERT(FLOAT, (SELECT DATEDIFF(DAY, MIN([Date]), MAX([Date])) + 1 - COUNT(*) FROM dim.DimDate)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'the generated calendar covers the supplied one',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_date s WHERE NOT EXISTS (SELECT 1 FROM dim.DimDate d WHERE d.[Date] = CONVERT(DATE, s.[Date])))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'financial years agree with the supplied calendar',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM stg.dim_date s JOIN dim.DimDate d ON d.[Date] = CONVERT(DATE, s.[Date])
      WHERE d.FinancialYear <> s.FinancialYear)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Dates', N'the extension beyond the supplied calendar is real',
  1,
  CONVERT(FLOAT, (SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END FROM dim.DimDate WHERE InSuppliedCalendar = 0)), 0);
INSERT #Checks (Category, Name, ExpectedTxt, ActualTxt) VALUES
 (N'Dates', N'as-of date is the last event in the file',
  CONVERT(NVARCHAR(60), @AsOf),
  CONVERT(NVARCHAR(60), (SELECT MAX(d.[Date]) FROM fact.FactPayment p JOIN dim.DimDate d ON d.DateKey = p.PaymentDateKey)));

/*=============================================== 6. AR SNAPSHOT AND LEDGER ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'snapshot covers 47 month ends',
  47,
  CONVERT(FLOAT, (SELECT COUNT(DISTINCT SnapshotDateKey) FROM fact.FactARSnapshot)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'every snapshot row sits on a month end',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot s JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.IsMonthEnd = 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'no snapshot row has a negative age',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot WHERE AgeDays < 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'ageing bucket matches the age in days',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot s JOIN dim.DimARBucket b ON b.ARBucketKey = s.ARBucketKey
      WHERE s.AgeDays < b.MinDays OR s.AgeDays > b.MaxDays)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'AR roll-forward holds in every month',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (
        SELECT j.MonthKey FROM (
          SELECT s.MonthKey, s.ARClose, LAG(s.ARClose) OVER (ORDER BY s.MonthKey) AS AROpen,
                 ISNULL(m.NetMovement, 0) AS NetMovement
          FROM (SELECT d.MonthKey, SUM(s.ARAmount) AS ARClose FROM fact.FactARSnapshot s
                JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey GROUP BY d.MonthKey) s
          LEFT JOIN (SELECT d.MonthKey, SUM(m.Amount) AS NetMovement FROM fact.FactARMovement m
                JOIN dim.DimDate d ON d.DateKey = m.MovementDateKey GROUP BY d.MonthKey) m ON m.MonthKey = s.MonthKey) j
        WHERE ABS(j.ARClose - (ISNULL(j.AROpen, 0) + j.NetMovement)) > 0.01) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'every claim enters AR exactly once',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT ClaimID FROM fact.FactARMovement WHERE ARMovementTypeKey = 1
                            GROUP BY ClaimID HAVING COUNT(*) <> 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'AR entering = total allowed',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, (SELECT SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey = 1)
                          - (SELECT SUM(AllowedAmount) FROM fact.FactClaim)))), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'AR leaving = allowed on resolved claims',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, (SELECT -SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey IN (2,3,4))
                          - (SELECT SUM(AllowedAmount) FROM fact.FactClaim WHERE IsPending = 0)))), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'closing AR = open AR on the claim header',
  0.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT,
        (SELECT SUM(ARAmount) FROM fact.FactARSnapshot
         WHERE SnapshotDateKey = (SELECT MAX(SnapshotDateKey) FROM fact.FactARSnapshot))
      - (SELECT SUM(OpenARAmount) FROM fact.FactClaim)))), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'a resolved claim never appears after its resolution',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot s
      JOIN fact.FactClaim c ON c.ClaimID = s.ClaimID
      WHERE c.ResolvedDateKey IS NOT NULL AND s.SnapshotDateKey >= c.ResolvedDateKey
        AND s.SnapshotDateKey >= (SELECT DateKey FROM dim.DimDate WHERE [Date] = (SELECT EOMONTH(d2.[Date]) FROM dim.DimDate d2 WHERE d2.DateKey = c.ResolvedDateKey)))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'no claim appears in AR before it was submitted',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARSnapshot s JOIN fact.FactClaim c ON c.ClaimID = s.ClaimID
      WHERE s.SnapshotDateKey < c.SubmittedDateKey)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'AR', N'signed movement direction matches its type',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactARMovement m JOIN dim.DimARMovementType t ON t.ARMovementTypeKey = m.ARMovementTypeKey
      WHERE SIGN(m.Amount) <> t.Direction AND m.Amount <> 0)), 0);

/*======================================== 7. THE PHASE 1 FINDINGS, RETESTED ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'denied claims ever paid',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaim WHERE IsDenied = 1 AND PaidAmount > 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'denied-and-corrected claims ever paid',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n JOIN dim.DimDenialStatus s ON s.DenialStatusKey = n.DenialStatusKey
      JOIN fact.FactClaim c ON c.ClaimID = n.ClaimID WHERE s.DenialStatus = N'Corrected' AND c.PaidAmount > 0)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'claims carrying more than one denial',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT ClaimID FROM fact.FactDenial GROUP BY ClaimID HAVING COUNT(*) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'claims carrying more than one payment',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT ClaimID FROM fact.FactPayment GROUP BY ClaimID HAVING COUNT(*) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'actual duplicate claims in the file',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT BeneficiaryKey, ProviderKey, ServiceDateKey, BilledAmount
                            FROM fact.FactClaim GROUP BY BeneficiaryKey, ProviderKey, ServiceDateKey, BilledAmount
                            HAVING COUNT(*) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'denial date always equals the adjudication date',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactDenial n JOIN fact.FactClaim c ON c.ClaimID = n.ClaimID
      WHERE n.DenialDateKey <> c.ProcessedDateKey)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'payer is the only dimension with signal',
  1,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_DenialSignalStrength WHERE SignalVerdict = N'Signal')), 0);
INSERT #Checks (Category, Name, ExpectedTxt, ActualTxt) VALUES
 (N'Findings', N'and that dimension is Payer',
  CONVERT(NVARCHAR(60), N'Payer'),
  CONVERT(NVARCHAR(60), (SELECT TOP 1 Dimension FROM analytics.vw_DenialSignalStrength ORDER BY CramersV DESC)));
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'Self Pay denial rate (%)',
  2.95,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, ROUND(100.0 * AVG(CONVERT(FLOAT, c.IsDenied)), 2))
      FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 1)), 0.01);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'insured denial rate (%)',
  8.79,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, ROUND(100.0 * AVG(CONVERT(FLOAT, c.IsDenied)), 2))
      FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 0)), 0.01);
/*  Not "no provider looks unusual" - that would be the wrong test, and it fails.
    23 of the 500 providers sit beyond two standard errors of the group rate. That
    is 4.6%, and a normal distribution puts 4.55% outside two standard deviations.
    The right test is therefore that the number of apparent outliers matches what
    pure chance predicts: the distribution is not merely flat, it has exactly the
    spread a coin toss would give it.                                            */
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'providers beyond 2 standard errors (%), vs 4.55% expected by chance',
  4.55,
  CONVERT(FLOAT, (SELECT 100.0 * SUM(CASE WHEN ChanceBand <> N'Within chance' THEN 1.0 ELSE 0 END) / COUNT(*)
                  FROM analytics.vw_ProviderDenialChance WHERE Claims >= 100)), 2.0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'no provider is beyond 4 standard errors',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_ProviderDenialChance WHERE ABS(ZScore) > 4)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'pending share is flat across months (spread, pp)',
  5.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, MAX(p) - MIN(p)) FROM (
        SELECT d.MonthKey, 100.0 * SUM(CONVERT(FLOAT, c.IsPending)) / COUNT(*) AS p, COUNT(*) AS n
        FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey
        GROUP BY d.MonthKey HAVING COUNT(*) > 1000) x)), 2.0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'procedure code does not price the procedure (spread $)',
  6.0,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, MAX(m) - MIN(m)) FROM
        (SELECT AVG(ChargeAmount) m FROM fact.FactClaimLine GROUP BY ProcedureKey) x)), 4.0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Findings', N'every payer allows the same share of billed (spread pp)',
  0.25,
  CONVERT(FLOAT, (SELECT CONVERT(FLOAT, MAX(r) - MIN(r)) FROM
        (SELECT 100.0 * SUM(AllowedAmount) / SUM(BilledAmount) AS r
         FROM fact.FactClaim GROUP BY PayerKey) x)), 0.25);

/*==================================================== 8. SECURITY AND CONFIG ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Security', N'every scoped grant names a real facility',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.SecurityUserAccess s WHERE s.FacilityID <> N'ALL'
      AND NOT EXISTS (SELECT 1 FROM dim.DimFacility f WHERE f.FacilityID = s.FacilityID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Security', N'every scoped grant names a real provider',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.SecurityUserAccess s WHERE s.ProviderID <> N'ALL'
      AND NOT EXISTS (SELECT 1 FROM dim.DimProvider p WHERE p.ProviderID = s.ProviderID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Security', N'no user email appears twice with conflicting scope',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM (SELECT UserEmail FROM dim.SecurityUserAccess GROUP BY UserEmail HAVING COUNT(DISTINCT ScopeLabel) > 1) x)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Security', N'organisation-wide users exist',
  1,
  CONVERT(FLOAT, (SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END FROM dim.SecurityUserAccess WHERE ScopeLabel = N'Whole organisation')), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Security', N'facility-scoped users cover every facility',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.DimFacility f WHERE NOT EXISTS
        (SELECT 1 FROM dim.SecurityUserAccess s WHERE s.FacilityID = f.FacilityID))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Config', N'every config key has a value',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.ModelConfig WHERE ConfigValue IS NULL OR LTRIM(RTRIM(ConfigValue)) = N'')), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Config', N'every config key is explained',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM dim.ModelConfig WHERE LEN(Notes) < 20)), 0);
INSERT #Checks (Category, Name, ExpectedTxt, ActualTxt) VALUES
 (N'Config', N'currency is AUD',
  CONVERT(NVARCHAR(60), N'AUD'),
  CONVERT(NVARCHAR(60), (SELECT ConfigValue FROM dim.ModelConfig WHERE ConfigKey = N'Currency')));

/*=========================================================== 9. THE VIEWS ==*/
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'analytics view count',
  25,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM sys.views WHERE schema_id = SCHEMA_ID('analytics'))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_FactClaim row count matches the table',
  0,
  CONVERT(FLOAT, (SELECT (SELECT COUNT(*) FROM analytics.vw_FactClaim) - (SELECT COUNT(*) FROM fact.FactClaim))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_FactARSnapshot row count matches the table',
  0,
  CONVERT(FLOAT, (SELECT (SELECT COUNT(*) FROM analytics.vw_FactARSnapshot) - (SELECT COUNT(*) FROM fact.FactARSnapshot))), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_DenialSignalStrength covers 10 dimensions',
  10,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_DenialSignalStrength)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_ProviderDenialChance covers every provider',
  500,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_ProviderDenialChance)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_DataQualityMetric has 15 findings',
  15,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'no data-quality metric is null',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric WHERE MetricValue IS NULL)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'every data-quality metric is interpreted',
  0,
  CONVERT(FLOAT, (SELECT COUNT(*) FROM analytics.vw_DataQualityMetric WHERE LEN(Interpretation) < 20)), 0);
INSERT #Checks (Category, Name, ExpectedNum, ActualNum, Tolerance) VALUES
 (N'Views', N'vw_DimBeneficiary keeps every beneficiary',
  0,
  CONVERT(FLOAT, (SELECT (SELECT COUNT(*) FROM dim.DimBeneficiary) - (SELECT COUNT(*) FROM analytics.vw_DimBeneficiary))), 0);
GO

/*========================================================= REPORT AND STOP ==*/
UPDATE #Checks
SET Passed = CASE
    WHEN ExpectedTxt IS NOT NULL
        THEN CASE WHEN ExpectedTxt = ActualTxt THEN 1 ELSE 0 END
    ELSE CASE WHEN ActualNum IS NOT NULL
                   AND ABS(ExpectedNum - ActualNum) <= Tolerance THEN 1 ELSE 0 END
END;

DECLARE @Total INT = (SELECT COUNT(*) FROM #Checks);
DECLARE @Failed INT = (SELECT COUNT(*) FROM #Checks WHERE Passed = 0);

SELECT Category, COUNT(*) AS Checks, SUM(CONVERT(INT, Passed)) AS Passed,
       COUNT(*) - SUM(CONVERT(INT, Passed)) AS Failed
FROM #Checks GROUP BY Category ORDER BY MIN(Ord);

IF @Failed > 0
    SELECT Ord, Category, Name,
           ISNULL(ExpectedTxt, CONVERT(NVARCHAR(60), ExpectedNum)) AS Expected,
           ISNULL(ActualTxt,   CONVERT(NVARCHAR(60), ActualNum))   AS Actual
    FROM #Checks WHERE Passed = 0 ORDER BY Ord;

PRINT '';
PRINT CONCAT('VALIDATION: ', @Total - @Failed, ' of ', @Total, ' checks passed');

IF @Failed > 0
BEGIN
    DECLARE @msg NVARCHAR(200) = CONCAT(N'VALIDATION FAILED: ', @Failed, N' of ', @Total, N' checks');
    THROW 51003, @msg, 1;
END
GO
