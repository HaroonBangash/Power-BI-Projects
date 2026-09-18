/*=============================================================================
  07_create_views.sql

  The analytics schema is the ONLY surface Power BI is allowed to touch. Nothing
  in the model reads dim, fact or stg directly, so a column can be renamed or a
  key reshaped underneath without touching the semantic model.

  Every view is a straight projection over one table - no scalar UDFs, no
  correlated subqueries in the SELECT list - so Power Query folds the whole
  import to a single SELECT. Validation/check_query_folding.sql proves it.

  Two views are not projections, and they are the analytical heart of the
  project:

    vw_DenialSignalStrength   for every candidate dimension, the observed spread
                              in denial rate AND a chi-square test of whether
                              that spread is more than chance. Computed in SQL on
                              every refresh, so it cannot go stale against a
                              hand-typed number in a text box.

    vw_ProviderDenialChance   every provider's denial rate next to the binomial
                              standard error for that provider's claim count.
                              This is what turns a tempting league table into an
                              honest one.

  Idempotent.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DROP VIEW IF EXISTS analytics.vw_DimDate;
DROP VIEW IF EXISTS analytics.vw_DimBeneficiary;
DROP VIEW IF EXISTS analytics.vw_DimProvider;
DROP VIEW IF EXISTS analytics.vw_DimFacility;
DROP VIEW IF EXISTS analytics.vw_DimPayer;
DROP VIEW IF EXISTS analytics.vw_DimClaimStatus;
DROP VIEW IF EXISTS analytics.vw_DimDenialReason;
DROP VIEW IF EXISTS analytics.vw_DimDenialStatus;
DROP VIEW IF EXISTS analytics.vw_DimProcedure;
DROP VIEW IF EXISTS analytics.vw_DimDiagnosis;
DROP VIEW IF EXISTS analytics.vw_DimPaymentMethod;
DROP VIEW IF EXISTS analytics.vw_DimARBucket;
DROP VIEW IF EXISTS analytics.vw_DimAgeBand;
DROP VIEW IF EXISTS analytics.vw_DimARMovementType;
DROP VIEW IF EXISTS analytics.vw_SecurityUserAccess;
DROP VIEW IF EXISTS analytics.vw_ModelConfig;
DROP VIEW IF EXISTS analytics.vw_FactClaim;
DROP VIEW IF EXISTS analytics.vw_FactClaimLine;
DROP VIEW IF EXISTS analytics.vw_FactPayment;
DROP VIEW IF EXISTS analytics.vw_FactDenial;
DROP VIEW IF EXISTS analytics.vw_FactARSnapshot;
DROP VIEW IF EXISTS analytics.vw_FactARMovement;
DROP VIEW IF EXISTS analytics.vw_DenialSignalStrength;
DROP VIEW IF EXISTS analytics.vw_ProviderDenialChance;
DROP VIEW IF EXISTS analytics.vw_DataQualityMetric;
GO

/*----------------------------------------------------------------- dimensions --*/
CREATE VIEW analytics.vw_DimDate AS
SELECT DateKey, [Date], [Year], MonthNo, MonthName, MonthShort, MonthKey, MonthStart,
       MonthEnd, MonthLabel, [Quarter], QuarterLabel, ISOWeek, DayName, DayNumberOfWeek,
       IsWeekend, FinancialYearStart, FinancialYear, FinancialQuarter, FinancialMonthNo,
       IsMonthEnd, MonthOffset, InSuppliedCalendar
FROM dim.DimDate;
GO

CREATE VIEW analytics.vw_DimBeneficiary AS
SELECT b.BeneficiaryKey, b.BeneficiaryID, b.DateOfBirth, b.AgeAtAsOf, b.Gender, b.[State],
       b.ChronicRiskBand, b.RiskBandOrder, a.AgeBand, a.AgeBandKey
FROM dim.DimBeneficiary b
JOIN dim.DimAgeBand a ON a.AgeBandKey = b.AgeBandKey;
GO

CREATE VIEW analytics.vw_DimProvider AS
SELECT ProviderKey, ProviderID, ProviderName, Specialty, FacilityID, FacilityName,
       FacilityType, [State]
FROM dim.DimProvider;
GO

CREATE VIEW analytics.vw_DimFacility AS
SELECT FacilityKey, FacilityID, FacilityName, FacilityType, [State]
FROM dim.DimFacility;
GO

CREATE VIEW analytics.vw_DimPayer AS
SELECT PayerKey, PayerID, PayerName, PayerType, IsSelfPay
FROM dim.DimPayer;
GO

CREATE VIEW analytics.vw_DimClaimStatus AS
SELECT ClaimStatusKey, ClaimStatus, IsResolved, IsOpenAR, StatusOrder, Definition
FROM dim.DimClaimStatus;
GO

CREATE VIEW analytics.vw_DimDenialReason AS
SELECT DenialReasonKey, DenialReason, ReasonCategory, PreventableAt, CategoryOrder
FROM dim.DimDenialReason;
GO

CREATE VIEW analytics.vw_DimDenialStatus AS
SELECT DenialStatusKey, DenialStatus, IsTerminal, StatusOrder, Definition
FROM dim.DimDenialStatus;
GO

CREATE VIEW analytics.vw_DimProcedure AS
SELECT ProcedureKey, ProcedureCode, ProcedureName, ServiceLine, SettingHint,
       ProcedureCode + N' · ' + ProcedureName AS ProcedureLabel
FROM dim.DimProcedure;
GO

CREATE VIEW analytics.vw_DimDiagnosis AS
SELECT DiagnosisKey, DiagnosisCode, DiagnosisName, ICD10Chapter, IsChronicCondition,
       DiagnosisCode + N' · ' + DiagnosisName AS DiagnosisLabel
FROM dim.DimDiagnosis;
GO

CREATE VIEW analytics.vw_DimPaymentMethod AS
SELECT PaymentMethodKey, PaymentMethod, IsElectronic, MethodOrder FROM dim.DimPaymentMethod;
GO

CREATE VIEW analytics.vw_DimARBucket AS
SELECT ARBucketKey, ARBucket, MinDays, MaxDays, IsPastFiling FROM dim.DimARBucket;
GO

CREATE VIEW analytics.vw_DimAgeBand AS
SELECT AgeBandKey, AgeBand, MinAge, MaxAge FROM dim.DimAgeBand;
GO

CREATE VIEW analytics.vw_DimARMovementType AS
SELECT ARMovementTypeKey, MovementType, Direction, MovementOrder, Definition
FROM dim.DimARMovementType;
GO

CREATE VIEW analytics.vw_SecurityUserAccess AS
SELECT UserEmail, [Role], FacilityID, ProviderID, ScopeLabel FROM dim.SecurityUserAccess;
GO

CREATE VIEW analytics.vw_ModelConfig AS
SELECT ConfigKey, ConfigValue, Notes FROM dim.ModelConfig;
GO

/*---------------------------------------------------------------------- facts --*/
CREATE VIEW analytics.vw_FactClaim AS
SELECT ClaimKey, ClaimID, BeneficiaryKey, ProviderKey, FacilityKey, PayerKey, ClaimStatusKey,
       ServiceDateKey, SubmittedDateKey, ProcessedDateKey, ResolvedDateKey,
       BilledAmount, AllowedAmount, PaidAmount, ContractualAdjustment,
       PatientResponsibility, OpenARAmount, DeniedAmount,
       DaysToSubmit, DaysToProcess, DaysToResolve, DaysOutstanding, ARBucketKey,
       PatientAgeAtService, LineCount, IsPaid, IsPending, IsDenied, IsFirstPassAccepted
FROM fact.FactClaim;
GO

CREATE VIEW analytics.vw_FactClaimLine AS
SELECT ClaimLineKey, ClaimLineID, ClaimID, ProcedureKey, DiagnosisKey, BeneficiaryKey,
       ProviderKey, FacilityKey, PayerKey, ClaimStatusKey, ServiceDateKey, ChargeAmount
FROM fact.FactClaimLine;
GO

CREATE VIEW analytics.vw_FactPayment AS
SELECT PaymentKey, PaymentID, ClaimID, PaymentDateKey, SubmittedDateKey, PaymentMethodKey,
       BeneficiaryKey, ProviderKey, FacilityKey, PayerKey, PaymentAmount, AllowedAmount, DaysToPay
FROM fact.FactPayment;
GO

CREATE VIEW analytics.vw_FactDenial AS
SELECT DenialKey, DenialID, ClaimID, DenialDateKey, SubmittedDateKey, DenialReasonKey,
       DenialStatusKey, BeneficiaryKey, ProviderKey, FacilityKey, PayerKey,
       DeniedAllowed, DeniedBilled, DaysToDeny
FROM fact.FactDenial;
GO

CREATE VIEW analytics.vw_FactARSnapshot AS
SELECT ARSnapshotKey, SnapshotDateKey, ClaimID, BeneficiaryKey, ProviderKey, FacilityKey,
       PayerKey, ARBucketKey, AgeDays, ARAmount
FROM fact.FactARSnapshot;
GO

CREATE VIEW analytics.vw_FactARMovement AS
SELECT ARMovementKey, ClaimID, ARMovementTypeKey, MovementDateKey, BeneficiaryKey,
       ProviderKey, FacilityKey, PayerKey, Amount, AbsAmount
FROM fact.FactARMovement;
GO

/*================================================== vw_DenialSignalStrength ==
  For every candidate dimension: the denial rate in its lowest and highest value,
  the spread between them, and a chi-square test of independence against the
  claim's denied flag.

  With two outcome columns the association measure reduces to Cramer's V =
  sqrt(chi-square / n), which sits on 0 to 1 and is directly comparable across
  dimensions with different numbers of values - which a raw chi-square is not,
  since chi-square grows with the degrees of freedom.

  The verdict column is a stated rule, not a judgement: V below 0.02 is reported
  as no usable signal. It is applied to every dimension the same way, including
  the one that passes.
=============================================================================*/
CREATE VIEW analytics.vw_DenialSignalStrength AS
WITH Cells AS (
    -- Every (dimension, value) pair with its denied and not-denied counts.
    SELECT N'Payer' AS Dimension, p.PayerName AS DimValue, CONVERT(INT, c.IsDenied) AS IsDenied
    FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey
    UNION ALL SELECT N'Facility type', f.FacilityType, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimFacility f ON f.FacilityKey = c.FacilityKey
    UNION ALL SELECT N'Facility', f.FacilityName, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimFacility f ON f.FacilityKey = c.FacilityKey
    UNION ALL SELECT N'Specialty', pr.Specialty, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimProvider pr ON pr.ProviderKey = c.ProviderKey
    UNION ALL SELECT N'Chronic risk band', b.ChronicRiskBand, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimBeneficiary b ON b.BeneficiaryKey = c.BeneficiaryKey
    UNION ALL SELECT N'Patient age band', a.AgeBand, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimBeneficiary b ON b.BeneficiaryKey = c.BeneficiaryKey
                          JOIN dim.DimAgeBand a ON a.AgeBandKey = b.AgeBandKey
    UNION ALL SELECT N'Gender', b.Gender, CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimBeneficiary b ON b.BeneficiaryKey = c.BeneficiaryKey
    UNION ALL SELECT N'Patient state', b.[State], CONVERT(INT, c.IsDenied)
    FROM fact.FactClaim c JOIN dim.DimBeneficiary b ON b.BeneficiaryKey = c.BeneficiaryKey
    UNION ALL SELECT N'Procedure', pc.ProcedureCode, CASE WHEN l.ClaimStatusKey = 3 THEN 1 ELSE 0 END
    FROM fact.FactClaimLine l JOIN dim.DimProcedure pc ON pc.ProcedureKey = l.ProcedureKey
    UNION ALL SELECT N'Diagnosis', dg.DiagnosisCode, CASE WHEN l.ClaimStatusKey = 3 THEN 1 ELSE 0 END
    FROM fact.FactClaimLine l JOIN dim.DimDiagnosis dg ON dg.DiagnosisKey = l.DiagnosisKey
),
ByValue AS (
    SELECT Dimension, DimValue,
           COUNT_BIG(*) AS n,
           SUM(CONVERT(BIGINT, IsDenied)) AS denied
    FROM Cells GROUP BY Dimension, DimValue
),
Totals AS (
    SELECT Dimension, SUM(n) AS N_total, SUM(denied) AS D_total
    FROM ByValue GROUP BY Dimension
),
Chi AS (
    -- chi-square over a 2-column contingency table, summed cell by cell.
    SELECT v.Dimension,
           SUM( SQUARE(v.denied       - t.D_total * 1.0 * v.n / t.N_total)
                / NULLIF(t.D_total * 1.0 * v.n / t.N_total, 0)
              + SQUARE((v.n - v.denied) - (t.N_total - t.D_total) * 1.0 * v.n / t.N_total)
                / NULLIF((t.N_total - t.D_total) * 1.0 * v.n / t.N_total, 0) ) AS ChiSquare,
           COUNT(*) - 1 AS DegreesOfFreedom
    FROM ByValue v JOIN Totals t ON t.Dimension = v.Dimension
    GROUP BY v.Dimension
),
Extremes AS (
    SELECT Dimension,
           MIN(denied * 100.0 / n) AS LowestRatePct,
           MAX(denied * 100.0 / n) AS HighestRatePct,
           COUNT(*) AS DistinctValues
    FROM ByValue GROUP BY Dimension
)
SELECT
    e.Dimension,
    e.DistinctValues,
    CONVERT(DECIMAL(9,3), e.LowestRatePct)                     AS LowestRatePct,
    CONVERT(DECIMAL(9,3), e.HighestRatePct)                    AS HighestRatePct,
    CONVERT(DECIMAL(9,3), e.HighestRatePct - e.LowestRatePct)  AS SpreadPP,
    CONVERT(DECIMAL(12,2), c.ChiSquare)                        AS ChiSquare,
    c.DegreesOfFreedom,
    CONVERT(DECIMAL(9,4), SQRT(c.ChiSquare / t.N_total))       AS CramersV,
    CASE WHEN SQRT(c.ChiSquare / t.N_total) >= 0.02
         THEN N'Signal' ELSE N'No usable signal' END           AS SignalVerdict
FROM Extremes e
JOIN Chi c    ON c.Dimension = e.Dimension
JOIN Totals t ON t.Dimension = e.Dimension;
GO

/*================================================== vw_ProviderDenialChance ==
  A provider league table is the first thing anyone asks for and the easiest
  thing to get wrong. With around 200 claims each, a provider's denial rate
  carries a standard error of roughly 1.9 points, so a spread from 3% to 14%
  across 500 providers is what pure chance looks like.

  This view puts each provider's rate next to that standard error, so the report
  can draw the distribution against its own chance band instead of ranking names.
=============================================================================*/
CREATE VIEW analytics.vw_ProviderDenialChance AS
WITH Grp AS (
    SELECT CONVERT(FLOAT, SUM(CONVERT(BIGINT, IsDenied))) / COUNT_BIG(*) AS GroupRate
    FROM fact.FactClaim
),
P AS (
    SELECT c.ProviderKey, pr.ProviderID, pr.ProviderName, pr.Specialty, pr.FacilityName,
           COUNT_BIG(*) AS Claims,
           SUM(CONVERT(BIGINT, c.IsDenied)) AS Denials
    FROM fact.FactClaim c
    JOIN dim.DimProvider pr ON pr.ProviderKey = c.ProviderKey
    GROUP BY c.ProviderKey, pr.ProviderID, pr.ProviderName, pr.Specialty, pr.FacilityName
)
SELECT
    p.ProviderKey, p.ProviderID, p.ProviderName, p.Specialty, p.FacilityName,
    p.Claims,
    p.Denials,
    CONVERT(DECIMAL(9,4), p.Denials * 1.0 / p.Claims)            AS DenialRate,
    CONVERT(DECIMAL(9,4), g.GroupRate)                           AS GroupRate,
    CONVERT(DECIMAL(9,5), SQRT(g.GroupRate * (1 - g.GroupRate) / p.Claims)) AS StandardError,
    CONVERT(DECIMAL(9,3),
        (p.Denials * 1.0 / p.Claims - g.GroupRate)
        / NULLIF(SQRT(g.GroupRate * (1 - g.GroupRate) / p.Claims), 0))      AS ZScore,
    CASE
        WHEN ABS((p.Denials * 1.0 / p.Claims - g.GroupRate)
                 / NULLIF(SQRT(g.GroupRate * (1 - g.GroupRate) / p.Claims), 0)) <= 2
             THEN N'Within chance'
        WHEN p.Denials * 1.0 / p.Claims > g.GroupRate THEN N'Above chance'
        ELSE N'Below chance'
    END AS ChanceBand,
    -- Two-point bands, so the 500 providers can be drawn as a distribution rather
    -- than a league table. RateBandSort keeps them in numeric order on an axis.
    CONVERT(INT, FLOOR(p.Denials * 100.0 / p.Claims / 2) * 2) AS RateBandSort,
    CONVERT(NVARCHAR(20), CONVERT(INT, FLOOR(p.Denials * 100.0 / p.Claims / 2) * 2))
        + N'-' + CONVERT(NVARCHAR(20), CONVERT(INT, FLOOR(p.Denials * 100.0 / p.Claims / 2) * 2 + 2))
        + N'%' AS RateBand
FROM P p CROSS JOIN Grp g;
GO

/*===================================================== vw_DataQualityMetric ==
  The Phase 1 findings as DATA, recomputed on every refresh. A finding written
  into a text box goes stale the moment the source changes; a finding computed
  from the source cannot.
=============================================================================*/
CREATE VIEW analytics.vw_DataQualityMetric AS
WITH C AS (SELECT * FROM fact.FactClaim)
SELECT  1 AS MetricOrder, N'Coverage' AS Category,
        N'Claims loaded' AS Metric,
        CONVERT(DECIMAL(18,4), COUNT_BIG(*)) AS MetricValue,
        N'#,0' AS ValueFormat,
        N'Every row in the source file, no filtering.' AS Interpretation
FROM C
UNION ALL SELECT 2, N'Coverage', N'Claims with no payment and no denial',
        CONVERT(DECIMAL(18,4), SUM(CONVERT(BIGINT, IsPending))), N'#,0',
        N'Carried as open AR. The share is the same in every month of the file.' FROM C
UNION ALL SELECT 3, N'Integrity', N'Allowed amount left unexplained',
        CONVERT(DECIMAL(18,4), SUM(AllowedAmount - PaidAmount - PatientResponsibility - OpenARAmount - DeniedAmount)),
        N'$#,0.00', N'Collected + patient responsibility + open AR + denied must equal allowed, on every row.' FROM C
UNION ALL SELECT 4, N'Integrity', N'Claims allowing more than they bill',
        CONVERT(DECIMAL(18,4), SUM(CASE WHEN AllowedAmount > BilledAmount THEN 1 ELSE 0 END)), N'#,0',
        N'An allowed amount above billed would mean the payer paid more than was asked.' FROM C
UNION ALL SELECT 5, N'Integrity', N'Claims paying more than allowed',
        CONVERT(DECIMAL(18,4), SUM(CASE WHEN PaidAmount > AllowedAmount THEN 1 ELSE 0 END)), N'#,0',
        N'Would mean a payment above the contracted rate.' FROM C
UNION ALL SELECT 6, N'Limits', N'Denied claims ever paid',
        CONVERT(DECIMAL(18,4), SUM(CASE WHEN IsDenied = 1 AND PaidAmount > 0 THEN 1 ELSE 0 END)), N'#,0',
        N'Zero. No denial in this file recovers, whatever its status says, so appeal yield is not measurable.' FROM C
UNION ALL SELECT 7, N'Limits', N'Claims with more than one payment',
        CONVERT(DECIMAL(18,4), (SELECT COUNT_BIG(*) FROM (SELECT ClaimID FROM fact.FactPayment
                                GROUP BY ClaimID HAVING COUNT(*) > 1) x)), N'#,0',
        N'Zero. No partial payment, takeback or secondary payer exists, so days-to-pay is a single event.'
UNION ALL SELECT 8, N'Limits', N'Actual duplicate claims in the file',
        CONVERT(DECIMAL(18,4), (SELECT COUNT_BIG(*) FROM (
            SELECT BeneficiaryKey, ProviderKey, ServiceDateKey, BilledAmount
            FROM fact.FactClaim GROUP BY BeneficiaryKey, ProviderKey, ServiceDateKey, BilledAmount
            HAVING COUNT(*) > 1) x)), N'#,0',
        N'Zero, against 1,117 claims denied for Duplicate Claim. The reason is a label, not a finding.'
UNION ALL SELECT 9, N'Limits', N'Spread in average charge across all procedure codes',
        CONVERT(DECIMAL(18,4), (SELECT MAX(m) - MIN(m) FROM
            (SELECT AVG(ChargeAmount) m FROM fact.FactClaimLine GROUP BY ProcedureKey) x)), N'$#,0.00',
        N'The charge is drawn independently of the code, so no page ranks a procedure by revenue.'
UNION ALL SELECT 10, N'Limits', N'Strongest association with denial (Cramers V)',
        CONVERT(DECIMAL(18,4), (SELECT MAX(CramersV) FROM analytics.vw_DenialSignalStrength)), N'0.0000',
        N'Payer, and within payer it is the Self Pay split alone. Everything else is inside chance.'
UNION ALL SELECT 11, N'Calendar', N'Fact dates outside the supplied dim_date',
        CONVERT(DECIMAL(18,4),
          (SELECT COUNT_BIG(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ProcessedDateKey WHERE d.InSuppliedCalendar = 0)
        + (SELECT COUNT_BIG(*) FROM fact.FactPayment p JOIN dim.DimDate d ON d.DateKey = p.PaymentDateKey WHERE d.InSuppliedCalendar = 0)
        + (SELECT COUNT_BIG(*) FROM fact.FactDenial n JOIN dim.DimDate d ON d.DateKey = n.DenialDateKey WHERE d.InSuppliedCalendar = 0)
        + (SELECT COUNT_BIG(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey WHERE d.InSuppliedCalendar = 0)),
        N'#,0',
        N'The supplied calendar stops at the last service date. This build generates its own, or these rows would join to a blank date.'
UNION ALL SELECT 12, N'Coverage', N'Beneficiaries never appearing on a claim',
        CONVERT(DECIMAL(18,4), (SELECT COUNT_BIG(*) FROM dim.DimBeneficiary b
            WHERE NOT EXISTS (SELECT 1 FROM fact.FactClaim c WHERE c.BeneficiaryKey = b.BeneficiaryKey))), N'#,0',
        N'Patient counts are taken from claims, never from the dimension, or the treated population is overstated.'
UNION ALL SELECT 13, N'Integrity', N'Claim lines not summing to the header',
        CONVERT(DECIMAL(18,4), (SELECT COUNT_BIG(*) FROM (
            SELECT c.ClaimID FROM fact.FactClaim c
            JOIN (SELECT ClaimID, SUM(ChargeAmount) s FROM fact.FactClaimLine GROUP BY ClaimID) l
              ON l.ClaimID = c.ClaimID
            WHERE ABS(l.s - c.BilledAmount) > 0.03) x)), N'#,0',
        N'Lines reconcile to the header, which is why the line table can carry mix without becoming a second source of truth for money.'
UNION ALL SELECT 14, N'Integrity', N'Months where the AR roll-forward breaks',
        CONVERT(DECIMAL(18,4), (SELECT COUNT_BIG(*) FROM (
            SELECT j.MonthKey
            FROM (SELECT s.MonthKey, s.ARClose,
                         LAG(s.ARClose) OVER (ORDER BY s.MonthKey) AS AROpen,
                         ISNULL(m.NetMovement, 0) AS NetMovement
                  FROM (SELECT d.MonthKey, SUM(s.ARAmount) AS ARClose
                        FROM fact.FactARSnapshot s
                        JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
                        GROUP BY d.MonthKey) s
                  LEFT JOIN (SELECT d.MonthKey, SUM(m.Amount) AS NetMovement
                             FROM fact.FactARMovement m
                             JOIN dim.DimDate d ON d.DateKey = m.MovementDateKey
                             GROUP BY d.MonthKey) m ON m.MonthKey = s.MonthKey) j
            WHERE ABS(j.ARClose - (ISNULL(j.AROpen, 0) + j.NetMovement)) > 0.01) x)), N'#,0',
        N'The snapshot and the movement ledger must agree in every month, or one of them is wrong.'
UNION ALL SELECT 15, N'Limits', N'Share of open AR more than a year old',
        CONVERT(DECIMAL(18,4), (SELECT SUM(CASE WHEN DaysOutstanding > 365 THEN 1.0 ELSE 0 END) / COUNT_BIG(*)
                                FROM fact.FactClaim WHERE IsPending = 1)), N'0.0%',
        N'A claim outstanding this long does not exist in a real revenue cycle. The ageing is arithmetic, not a collections story.';
GO

PRINT 'analytics views created';
SELECT COUNT(*) AS views_in_analytics FROM sys.views WHERE schema_id = SCHEMA_ID('analytics');
GO
