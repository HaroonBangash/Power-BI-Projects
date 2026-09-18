/*=============================================================================
  06_build_ar_snapshot.sql

  Two derived tables that do not exist in the source, and the identity that ties
  them together.

  fact.FactARSnapshot   one row per claim per month end that the claim was still
                        outstanding. A STOCK: what was owed, and how old it was,
                        at each month end.

  fact.FactARMovement   one row per event that moved the receivable. A FLOW:
                        a claim entering AR on submission, and leaving it as
                        cash, as patient responsibility, or as a denial.

  They check each other, in every month:

      AR(m) = AR(m-1) + submitted(m) - collected(m)
                      - patient responsibility(m) - denied(m)

  A snapshot alone can drift without anyone noticing; a ledger alone cannot be
  aged. Built together, each proves the other, and 08_validation.sql re-runs the
  identity for all 47 months on every build.

  AR IS CARRIED AT THE ALLOWED AMOUNT, not at billed - the contracted expectation
  rather than the sticker price. Carrying it at billed would overstate the
  receivable by the 26.5% contractual adjustment, which is agreed in advance and
  was never collectable.

  ONE ASSUMPTION IS STATED HERE. When a claim is paid, the whole allowed amount
  leaves AR: the payer's share as cash, and the patient's share as patient
  responsibility. The source records no patient payment events, so patient
  responsibility is treated as resolved on the payer's payment date. In a real
  revenue cycle it would begin a second, slower AR of its own.

  Idempotent.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DROP TABLE IF EXISTS fact.FactARSnapshot;
DROP TABLE IF EXISTS fact.FactARMovement;
DROP TABLE IF EXISTS dim.DimARMovementType;
GO

CREATE TABLE dim.DimARMovementType (
    ARMovementTypeKey  TINYINT        NOT NULL PRIMARY KEY,
    MovementType       NVARCHAR(40)   NOT NULL UNIQUE,
    Direction          SMALLINT       NOT NULL,       -- +1 into AR, -1 out of AR
    MovementOrder      TINYINT        NOT NULL,
    Definition         NVARCHAR(250)  NOT NULL
);
INSERT dim.DimARMovementType VALUES
 (1, N'Submitted',             1, 1, N'A claim enters AR at its allowed amount on the day it is submitted.'),
 (2, N'Collected',            -1, 2, N'Payer cash received. Leaves AR on the payment date.'),
 (3, N'Patient responsibility',-1, 3, N'The allowed amount the payer did not settle - copay, coinsurance, deductible. Treated as leaving AR on the payer payment date, because the source records no patient payment events.'),
 (4, N'Denied',               -1, 4, N'Adjudicated to zero. Leaves AR on the denial date.');
GO

/*=========================================================== FactARMovement ==
  The flow. One row per event, so every dollar that enters AR leaves it exactly
  once - or is still there, which is what the snapshot measures.
=============================================================================*/
CREATE TABLE fact.FactARMovement (
    ARMovementKey      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    ClaimID            NVARCHAR(20)  NOT NULL,
    ARMovementTypeKey  TINYINT       NOT NULL,
    MovementDateKey    INT           NOT NULL,
    BeneficiaryKey     INT           NOT NULL,
    ProviderKey        INT           NOT NULL,
    FacilityKey        INT           NOT NULL,
    PayerKey           INT           NOT NULL,
    Amount             DECIMAL(18,2) NOT NULL,       -- signed: + into AR, - out of AR
    AbsAmount          DECIMAL(18,2) NOT NULL
);
GO

-- 1. Submission: every claim enters AR at its allowed amount.
INSERT fact.FactARMovement (ClaimID, ARMovementTypeKey, MovementDateKey, BeneficiaryKey,
                            ProviderKey, FacilityKey, PayerKey, Amount, AbsAmount)
SELECT c.ClaimID, 1, c.SubmittedDateKey, c.BeneficiaryKey, c.ProviderKey, c.FacilityKey,
       c.PayerKey, c.AllowedAmount, c.AllowedAmount
FROM fact.FactClaim c;

-- 2. Collected: payer cash, on the payment date.
INSERT fact.FactARMovement (ClaimID, ARMovementTypeKey, MovementDateKey, BeneficiaryKey,
                            ProviderKey, FacilityKey, PayerKey, Amount, AbsAmount)
SELECT c.ClaimID, 2, c.ResolvedDateKey, c.BeneficiaryKey, c.ProviderKey, c.FacilityKey,
       c.PayerKey, -c.PaidAmount, c.PaidAmount
FROM fact.FactClaim c
WHERE c.IsPaid = 1 AND c.PaidAmount > 0;

-- 3. Patient responsibility: the rest of the allowed amount on a paid claim.
INSERT fact.FactARMovement (ClaimID, ARMovementTypeKey, MovementDateKey, BeneficiaryKey,
                            ProviderKey, FacilityKey, PayerKey, Amount, AbsAmount)
SELECT c.ClaimID, 3, c.ResolvedDateKey, c.BeneficiaryKey, c.ProviderKey, c.FacilityKey,
       c.PayerKey, -c.PatientResponsibility, c.PatientResponsibility
FROM fact.FactClaim c
WHERE c.IsPaid = 1 AND c.PatientResponsibility > 0;

-- 4. Denied: the whole allowed amount leaves on the denial date.
INSERT fact.FactARMovement (ClaimID, ARMovementTypeKey, MovementDateKey, BeneficiaryKey,
                            ProviderKey, FacilityKey, PayerKey, Amount, AbsAmount)
SELECT c.ClaimID, 4, c.ResolvedDateKey, c.BeneficiaryKey, c.ProviderKey, c.FacilityKey,
       c.PayerKey, -c.DeniedAmount, c.DeniedAmount
FROM fact.FactClaim c
WHERE c.IsDenied = 1 AND c.DeniedAmount > 0;
GO

CREATE INDEX IX_FactARMovement_Date ON fact.FactARMovement (MovementDateKey) INCLUDE (Amount);
CREATE INDEX IX_FactARMovement_Type ON fact.FactARMovement (ARMovementTypeKey) INCLUDE (Amount);
GO

/*=========================================================== FactARSnapshot ==
  The stock. A claim is in AR at month end M when it was submitted on or before M
  and had not yet been resolved.

  Age is measured from the SUBMISSION date, not the service date. That is the
  revenue-cycle convention: the clock a payer is held to starts when the claim
  reaches them. Days from service to submission is the provider's own lag and is
  measured separately.
=============================================================================*/
CREATE TABLE fact.FactARSnapshot (
    ARSnapshotKey    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    SnapshotDateKey  INT           NOT NULL,
    ClaimID          NVARCHAR(20)  NOT NULL,
    BeneficiaryKey   INT           NOT NULL,
    ProviderKey      INT           NOT NULL,
    FacilityKey      INT           NOT NULL,
    PayerKey         INT           NOT NULL,
    ARBucketKey      TINYINT       NOT NULL,
    AgeDays          SMALLINT      NOT NULL,
    ARAmount         DECIMAL(18,2) NOT NULL
);
GO

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');
DECLARE @LastSnap DATE = EOMONTH(@AsOf);
DECLARE @FirstSnap DATE = (SELECT EOMONTH(MIN(d.[Date]))
                           FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey);

;WITH MonthEnds AS (
    SELECT DateKey, [Date]
    FROM dim.DimDate
    WHERE IsMonthEnd = 1 AND [Date] BETWEEN @FirstSnap AND @LastSnap
),
OpenAR AS (
    SELECT m.DateKey AS SnapshotDateKey,
           c.ClaimID, c.BeneficiaryKey, c.ProviderKey, c.FacilityKey, c.PayerKey,
           DATEDIFF(DAY, s.[Date], m.[Date]) AS AgeDays,
           c.AllowedAmount AS ARAmount
    FROM fact.FactClaim c
    JOIN dim.DimDate s ON s.DateKey = c.SubmittedDateKey
    JOIN MonthEnds m   ON s.[Date] <= m.[Date]
    LEFT JOIN dim.DimDate r ON r.DateKey = c.ResolvedDateKey
    WHERE r.[Date] IS NULL OR r.[Date] > m.[Date]
)
INSERT fact.FactARSnapshot (SnapshotDateKey, ClaimID, BeneficiaryKey, ProviderKey,
                            FacilityKey, PayerKey, ARBucketKey, AgeDays, ARAmount)
SELECT o.SnapshotDateKey, o.ClaimID, o.BeneficiaryKey, o.ProviderKey, o.FacilityKey,
       o.PayerKey, b.ARBucketKey, o.AgeDays, o.ARAmount
FROM OpenAR o
JOIN dim.DimARBucket b ON o.AgeDays BETWEEN b.MinDays AND b.MaxDays;
GO

CREATE INDEX IX_FactARSnapshot_Snap   ON fact.FactARSnapshot (SnapshotDateKey) INCLUDE (ARAmount);
CREATE INDEX IX_FactARSnapshot_Bucket ON fact.FactARSnapshot (ARBucketKey)     INCLUDE (ARAmount);
GO

/*----------------------------------------------------------------------------
  The identity, checked here as well as in 08 so a bad build fails at the point
  it was created rather than three scripts later.
----------------------------------------------------------------------------*/
DECLARE @Breaks INT;

;WITH Snap AS (
    SELECT d.MonthKey, SUM(s.ARAmount) AS ARClose
    FROM fact.FactARSnapshot s
    JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
    GROUP BY d.MonthKey
),
Move AS (
    SELECT d.MonthKey, SUM(m.Amount) AS NetMovement
    FROM fact.FactARMovement m
    JOIN dim.DimDate d ON d.DateKey = m.MovementDateKey
    GROUP BY d.MonthKey
),
Joined AS (
    SELECT s.MonthKey, s.ARClose,
           LAG(s.ARClose) OVER (ORDER BY s.MonthKey) AS AROpen,
           ISNULL(m.NetMovement, 0) AS NetMovement
    FROM Snap s LEFT JOIN Move m ON m.MonthKey = s.MonthKey
)
SELECT @Breaks = COUNT(*)
FROM Joined
WHERE ABS(ARClose - (ISNULL(AROpen, 0) + NetMovement)) > 0.01;

IF @Breaks > 0
BEGIN
    DECLARE @msg NVARCHAR(300) = CONCAT(
        N'AR roll-forward identity broken in ', @Breaks,
        N' month(s): the snapshot and the movement ledger disagree.');
    THROW 51002, @msg, 1;
END
PRINT '  AR roll-forward identity holds in every month';
GO

PRINT 'AR snapshot and movement ledger built';
SELECT 'FactARSnapshot' t, COUNT(*) rows, COUNT(DISTINCT SnapshotDateKey) months FROM fact.FactARSnapshot
UNION ALL SELECT 'FactARMovement', COUNT(*), COUNT(DISTINCT MovementDateKey) FROM fact.FactARMovement;
GO
