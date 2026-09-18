/*=============================================================================
  05_create_facts.sql

  Four facts, each at its own stated grain, each carrying its OWN foreign keys.

  WHY THE KEYS ARE REPEATED ON EVERY FACT
  A filter never travels from one fact table to another. If the payer, facility
  and provider keys lived only on the claim header, then "line volume by payer"
  or "denials by specialty" would filter the claim table and leave the line or
  denial table whole - a shrinking denominator against a full numerator, which is
  exactly the defect that took longest to find in the previous project in this
  series. Every fact therefore hangs off the shared dimensions directly. The cost
  is four integers per row; the alternative is a number that is quietly wrong.

  For the same reason there is NO relationship between FactClaim and
  FactClaimLine: with the dimensions conformed, a header-to-line relationship
  would give the engine two paths from DimPayer to the line table. ClaimID is
  carried on every fact as a degenerate key for drill-through.

  MONEY IS DEFINED IN ONE PLACE. The claim header owns billed, allowed and paid.
  The line table owns ChargeAmount, which sums to the header billed amount
  (Phase 1, section 12), and is used for mix and volume only. No measure ever
  adds the two together.

  Idempotent - the tables are dropped in 04 before the dimensions are rebuilt.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');
PRINT CONCAT('as-of date: ', CONVERT(NVARCHAR(10), @AsOf));
GO

/*================================================================= FactClaim ==
  Grain: one claim. 100,000 rows.

  The four money columns below are the whole point of the model. Every dollar the
  payer allowed sits in exactly one of them, so that

      AllowedAmount = PaidAmount + PatientResponsibility + OpenARAmount + DeniedAmount

  holds on every single row, and therefore at every level of every aggregation.
  08_validation.sql re-checks it row by row and in total.
=============================================================================*/
CREATE TABLE fact.FactClaim (
    ClaimKey               INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    ClaimID                NVARCHAR(20)  NOT NULL UNIQUE,

    BeneficiaryKey         INT           NOT NULL,
    ProviderKey            INT           NOT NULL,
    FacilityKey            INT           NOT NULL,
    PayerKey               INT           NOT NULL,
    ClaimStatusKey         TINYINT       NOT NULL,

    ServiceDateKey         INT           NOT NULL,
    SubmittedDateKey       INT           NOT NULL,
    ProcessedDateKey       INT           NOT NULL,
    ResolvedDateKey        INT           NULL,       -- payment or denial; NULL while pending

    BilledAmount           DECIMAL(18,2) NOT NULL,
    AllowedAmount          DECIMAL(18,2) NOT NULL,
    PaidAmount             DECIMAL(18,2) NOT NULL,
    ContractualAdjustment  DECIMAL(18,2) NOT NULL,
    PatientResponsibility  DECIMAL(18,2) NOT NULL,
    OpenARAmount           DECIMAL(18,2) NOT NULL,
    DeniedAmount           DECIMAL(18,2) NOT NULL,

    DaysToSubmit           SMALLINT      NOT NULL,
    DaysToProcess          SMALLINT      NOT NULL,
    DaysToResolve          SMALLINT      NULL,       -- submission to cash or denial
    DaysOutstanding        SMALLINT      NULL,       -- pending only, measured at the as-of date
    ARBucketKey            TINYINT       NULL,       -- pending only

    PatientAgeAtService    TINYINT       NOT NULL,
    LineCount              TINYINT       NOT NULL,

    IsPaid                 BIT           NOT NULL,
    IsPending              BIT           NOT NULL,
    IsDenied               BIT           NOT NULL,
    IsFirstPassAccepted    BIT           NOT NULL
);
GO

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');

;WITH src AS (
    SELECT
        c.ClaimID,
        c.BeneficiaryID, c.ProviderID, c.FacilityID, c.PayerID, c.ClaimStatus,
        CONVERT(DATE, c.ServiceDate)   AS ServiceDate,
        CONVERT(DATE, c.SubmittedDate) AS SubmittedDate,
        CONVERT(DATE, c.ProcessedDate) AS ProcessedDate,
        CONVERT(DECIMAL(18,2), c.BilledAmount)  AS BilledAmount,
        CONVERT(DECIMAL(18,2), c.AllowedAmount) AS AllowedAmount,
        CONVERT(DECIMAL(18,2), c.PaidAmount)    AS PaidAmount
    FROM stg.fact_claims c
),
res AS (
    SELECT s.*,
           -- A claim leaves AR when cash arrives or when it is denied. A pending
           -- claim never leaves: that is the finding in Phase 1, section 4.
           COALESCE(CONVERT(DATE, p.PaymentDate), CONVERT(DATE, d.DenialDate)) AS ResolvedDate
    FROM src s
    LEFT JOIN stg.fact_payments p ON p.ClaimID = s.ClaimID
    LEFT JOIN stg.fact_denials  d ON d.ClaimID = s.ClaimID
),
lines AS (
    SELECT ClaimID, COUNT(*) AS LineCount FROM stg.fact_claim_lines GROUP BY ClaimID
)
INSERT fact.FactClaim (
    ClaimID, BeneficiaryKey, ProviderKey, FacilityKey, PayerKey, ClaimStatusKey,
    ServiceDateKey, SubmittedDateKey, ProcessedDateKey, ResolvedDateKey,
    BilledAmount, AllowedAmount, PaidAmount, ContractualAdjustment,
    PatientResponsibility, OpenARAmount, DeniedAmount,
    DaysToSubmit, DaysToProcess, DaysToResolve, DaysOutstanding, ARBucketKey,
    PatientAgeAtService, LineCount, IsPaid, IsPending, IsDenied, IsFirstPassAccepted)
SELECT
    r.ClaimID,
    b.BeneficiaryKey, pv.ProviderKey, f.FacilityKey, py.PayerKey, cs.ClaimStatusKey,
    CONVERT(INT, FORMAT(r.ServiceDate,   'yyyyMMdd')),
    CONVERT(INT, FORMAT(r.SubmittedDate, 'yyyyMMdd')),
    CONVERT(INT, FORMAT(r.ProcessedDate, 'yyyyMMdd')),
    CASE WHEN r.ResolvedDate IS NULL THEN NULL ELSE CONVERT(INT, FORMAT(r.ResolvedDate, 'yyyyMMdd')) END,

    r.BilledAmount,
    r.AllowedAmount,
    r.PaidAmount,
    r.BilledAmount - r.AllowedAmount,
    CASE WHEN r.ClaimStatus = N'Paid'    THEN r.AllowedAmount - r.PaidAmount ELSE 0 END,
    CASE WHEN r.ClaimStatus = N'Pending' THEN r.AllowedAmount ELSE 0 END,
    CASE WHEN r.ClaimStatus = N'Denied'  THEN r.AllowedAmount ELSE 0 END,

    DATEDIFF(DAY, r.ServiceDate,   r.SubmittedDate),
    DATEDIFF(DAY, r.SubmittedDate, r.ProcessedDate),
    CASE WHEN r.ResolvedDate IS NULL THEN NULL ELSE DATEDIFF(DAY, r.SubmittedDate, r.ResolvedDate) END,
    CASE WHEN r.ResolvedDate IS NULL THEN DATEDIFF(DAY, r.SubmittedDate, @AsOf) ELSE NULL END,
    CASE WHEN r.ResolvedDate IS NULL THEN
        (SELECT TOP 1 ARBucketKey FROM dim.DimARBucket
          WHERE DATEDIFF(DAY, r.SubmittedDate, @AsOf) BETWEEN MinDays AND MaxDays)
    END,

    CONVERT(TINYINT, DATEDIFF(YEAR, b.DateOfBirth, r.ServiceDate)
        - CASE WHEN DATEADD(YEAR, DATEDIFF(YEAR, b.DateOfBirth, r.ServiceDate), b.DateOfBirth) > r.ServiceDate
               THEN 1 ELSE 0 END),
    l.LineCount,

    CASE WHEN r.ClaimStatus = N'Paid'    THEN 1 ELSE 0 END,
    CASE WHEN r.ClaimStatus = N'Pending' THEN 1 ELSE 0 END,
    CASE WHEN r.ClaimStatus = N'Denied'  THEN 1 ELSE 0 END,
    -- First pass acceptance = not denied. Phase 1, section 6: with no resubmission
    -- chain in the source this is the denial rate written the other way up, and the
    -- report says so rather than presenting it as an independent measurement.
    CASE WHEN r.ClaimStatus = N'Denied'  THEN 0 ELSE 1 END
FROM res r
JOIN dim.DimBeneficiary  b  ON b.BeneficiaryID = r.BeneficiaryID
JOIN dim.DimProvider     pv ON pv.ProviderID   = r.ProviderID
JOIN dim.DimFacility     f  ON f.FacilityID    = r.FacilityID
JOIN dim.DimPayer        py ON py.PayerID      = r.PayerID
JOIN dim.DimClaimStatus  cs ON cs.ClaimStatus  = r.ClaimStatus
JOIN lines               l  ON l.ClaimID       = r.ClaimID;
GO

CREATE INDEX IX_FactClaim_Submitted ON fact.FactClaim (SubmittedDateKey) INCLUDE (AllowedAmount, PaidAmount);
CREATE INDEX IX_FactClaim_Status    ON fact.FactClaim (ClaimStatusKey)   INCLUDE (AllowedAmount, PaidAmount, BilledAmount);
CREATE INDEX IX_FactClaim_Payer     ON fact.FactClaim (PayerKey)         INCLUDE (IsDenied);
GO

/*============================================================= FactClaimLine ==
  Grain: one procedure line. 249,905 rows. ChargeAmount only - the header owns
  billed, allowed and paid. Carries the claim's dimension keys so that a payer or
  facility filter reaches it directly, and the claim status so that denial mix by
  procedure or diagnosis is answerable without a second hop.
=============================================================================*/
CREATE TABLE fact.FactClaimLine (
    ClaimLineKey    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    ClaimLineID     NVARCHAR(20)  NOT NULL UNIQUE,
    ClaimID         NVARCHAR(20)  NOT NULL,
    ProcedureKey    TINYINT       NOT NULL,
    DiagnosisKey    TINYINT       NOT NULL,
    BeneficiaryKey  INT           NOT NULL,
    ProviderKey     INT           NOT NULL,
    FacilityKey     INT           NOT NULL,
    PayerKey        INT           NOT NULL,
    ClaimStatusKey  TINYINT       NOT NULL,
    ServiceDateKey  INT           NOT NULL,
    ChargeAmount    DECIMAL(18,2) NOT NULL
);
GO

INSERT fact.FactClaimLine (ClaimLineID, ClaimID, ProcedureKey, DiagnosisKey, BeneficiaryKey,
                           ProviderKey, FacilityKey, PayerKey, ClaimStatusKey, ServiceDateKey, ChargeAmount)
SELECT
    l.ClaimLineID, l.ClaimID, pr.ProcedureKey, dg.DiagnosisKey,
    c.BeneficiaryKey, c.ProviderKey, c.FacilityKey, c.PayerKey, c.ClaimStatusKey, c.ServiceDateKey,
    CONVERT(DECIMAL(18,2), l.ChargeAmount)
FROM stg.fact_claim_lines l
JOIN fact.FactClaim   c  ON c.ClaimID = l.ClaimID
JOIN dim.DimProcedure pr ON pr.ProcedureCode = l.ProcedureCode
JOIN dim.DimDiagnosis dg ON dg.DiagnosisCode = l.DiagnosisCode;
GO

CREATE INDEX IX_FactClaimLine_Procedure ON fact.FactClaimLine (ProcedureKey) INCLUDE (ChargeAmount);
CREATE INDEX IX_FactClaimLine_Diagnosis ON fact.FactClaimLine (DiagnosisKey) INCLUDE (ChargeAmount);
GO

/*=============================================================== FactPayment ==
  Grain: one remittance. 69,111 rows - exactly one per paid claim, because this
  source has no partial payments, no takebacks and no secondary payer.
  PaymentAmount is the SAME money as FactClaim.PaidAmount seen on the cash date
  rather than the submission date; the two are never added together, and
  08_validation.sql proves they agree in total.
=============================================================================*/
CREATE TABLE fact.FactPayment (
    PaymentKey        INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    PaymentID         NVARCHAR(20)  NOT NULL UNIQUE,
    ClaimID           NVARCHAR(20)  NOT NULL,
    PaymentDateKey    INT           NOT NULL,
    SubmittedDateKey  INT           NOT NULL,
    PaymentMethodKey  TINYINT       NOT NULL,
    BeneficiaryKey    INT           NOT NULL,
    ProviderKey       INT           NOT NULL,
    FacilityKey       INT           NOT NULL,
    PayerKey          INT           NOT NULL,
    PaymentAmount     DECIMAL(18,2) NOT NULL,
    AllowedAmount     DECIMAL(18,2) NOT NULL,
    DaysToPay         SMALLINT      NOT NULL
);
GO

INSERT fact.FactPayment (PaymentID, ClaimID, PaymentDateKey, SubmittedDateKey, PaymentMethodKey,
                         BeneficiaryKey, ProviderKey, FacilityKey, PayerKey,
                         PaymentAmount, AllowedAmount, DaysToPay)
SELECT
    p.PaymentID, p.ClaimID,
    CONVERT(INT, FORMAT(CONVERT(DATE, p.PaymentDate), 'yyyyMMdd')),
    c.SubmittedDateKey,
    pm.PaymentMethodKey,
    c.BeneficiaryKey, c.ProviderKey, c.FacilityKey, c.PayerKey,
    CONVERT(DECIMAL(18,2), p.PaymentAmount),
    c.AllowedAmount,
    DATEDIFF(DAY, d.[Date], CONVERT(DATE, p.PaymentDate))
FROM stg.fact_payments p
JOIN fact.FactClaim       c  ON c.ClaimID = p.ClaimID
JOIN dim.DimDate          d  ON d.DateKey = c.SubmittedDateKey
JOIN dim.DimPaymentMethod pm ON pm.PaymentMethod = p.PaymentMethod;
GO

CREATE INDEX IX_FactPayment_Date ON fact.FactPayment (PaymentDateKey) INCLUDE (PaymentAmount);
GO

/*================================================================ FactDenial ==
  Grain: one denial. 7,824 rows - exactly one per denied claim. Carries the
  allowed amount so the denied value can be sliced by reason without reaching
  back to the claim header.
=============================================================================*/
CREATE TABLE fact.FactDenial (
    DenialKey        INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    DenialID         NVARCHAR(20)  NOT NULL UNIQUE,
    ClaimID          NVARCHAR(20)  NOT NULL,
    DenialDateKey    INT           NOT NULL,
    SubmittedDateKey INT           NOT NULL,
    DenialReasonKey  TINYINT       NOT NULL,
    DenialStatusKey  TINYINT       NOT NULL,
    BeneficiaryKey   INT           NOT NULL,
    ProviderKey      INT           NOT NULL,
    FacilityKey      INT           NOT NULL,
    PayerKey         INT           NOT NULL,
    DeniedAllowed    DECIMAL(18,2) NOT NULL,
    DeniedBilled     DECIMAL(18,2) NOT NULL,
    DaysToDeny       SMALLINT      NOT NULL
);
GO

INSERT fact.FactDenial (DenialID, ClaimID, DenialDateKey, SubmittedDateKey, DenialReasonKey,
                        DenialStatusKey, BeneficiaryKey, ProviderKey, FacilityKey, PayerKey,
                        DeniedAllowed, DeniedBilled, DaysToDeny)
SELECT
    n.DenialID, n.ClaimID,
    CONVERT(INT, FORMAT(CONVERT(DATE, n.DenialDate), 'yyyyMMdd')),
    c.SubmittedDateKey,
    dr.DenialReasonKey, ds.DenialStatusKey,
    c.BeneficiaryKey, c.ProviderKey, c.FacilityKey, c.PayerKey,
    c.AllowedAmount, c.BilledAmount,
    DATEDIFF(DAY, d.[Date], CONVERT(DATE, n.DenialDate))
FROM stg.fact_denials n
JOIN fact.FactClaim      c  ON c.ClaimID = n.ClaimID
JOIN dim.DimDate         d  ON d.DateKey = c.SubmittedDateKey
JOIN dim.DimDenialReason dr ON dr.DenialReason = n.DenialReason
JOIN dim.DimDenialStatus ds ON ds.DenialStatus = n.DenialStatus;
GO

CREATE INDEX IX_FactDenial_Reason ON fact.FactDenial (DenialReasonKey) INCLUDE (DeniedAllowed);
GO

PRINT 'facts built';
SELECT 'FactClaim' t, COUNT(*) rows FROM fact.FactClaim
UNION ALL SELECT 'FactClaimLine', COUNT(*) FROM fact.FactClaimLine
UNION ALL SELECT 'FactPayment', COUNT(*) FROM fact.FactPayment
UNION ALL SELECT 'FactDenial', COUNT(*) FROM fact.FactDenial;
GO
