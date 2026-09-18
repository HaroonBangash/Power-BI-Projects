/*=============================================================================
  04_create_dimensions.sql

  Conformed dimensions. Two things here are not a straight copy of the source.

  1. dim.DimDate is GENERATED, not loaded. The supplied dim_date.csv stops on
     2026-08-31 because it was built to the SERVICE date range, but a claim is
     submitted after it is performed, adjudicated after that and paid after that:
     4,807 adjudication, payment and denial dates fall past the end of the
     supplied calendar (Phase 1, section 10). Joined to it they would land on a
     blank date and vanish from anything sliced by adjudication or payment month,
     while the totals still looked plausible. The generated calendar covers every
     date in every fact plus a margin, keeps the supplied Australian financial
     year convention, and carries InSuppliedCalendar so the gap stays visible.

  2. The small dimensions carry attributes the source does not: a payer type
     (the Self Pay split is the only real denial signal in the data), a denial
     reason category, an AR ageing bucket, a procedure service line and a
     diagnosis chapter. The code descriptions are the published meanings of real
     CPT and ICD-10 codes - reference metadata about the code, not invented facts
     about a patient.

  Currency is AUD: every facility state is Australian and the payers are
  Medicare, Bupa, Medibank, HCF and NIB.

  Idempotent.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

-- Facts are dropped first: they hold the foreign keys.
DROP TABLE IF EXISTS fact.FactARSnapshot;
DROP TABLE IF EXISTS fact.FactDenial;
DROP TABLE IF EXISTS fact.FactPayment;
DROP TABLE IF EXISTS fact.FactClaimLine;
DROP TABLE IF EXISTS fact.FactClaim;

DROP TABLE IF EXISTS dim.DimDate;
DROP TABLE IF EXISTS dim.DimBeneficiary;
DROP TABLE IF EXISTS dim.DimProvider;
DROP TABLE IF EXISTS dim.DimFacility;
DROP TABLE IF EXISTS dim.DimPayer;
DROP TABLE IF EXISTS dim.DimClaimStatus;
DROP TABLE IF EXISTS dim.DimDenialReason;
DROP TABLE IF EXISTS dim.DimDenialStatus;
DROP TABLE IF EXISTS dim.DimProcedure;
DROP TABLE IF EXISTS dim.DimDiagnosis;
DROP TABLE IF EXISTS dim.DimPaymentMethod;
DROP TABLE IF EXISTS dim.DimARBucket;
DROP TABLE IF EXISTS dim.DimAgeBand;
DROP TABLE IF EXISTS dim.SecurityUserAccess;
DROP TABLE IF EXISTS dim.ModelConfig;
GO

/*---------------------------------------------------------------- ModelConfig --
  One row per stated assumption. Every one of these is read by the semantic model
  rather than typed into a measure, so an assumption can be found and changed in
  one place - and so the report can print the assumption it is standing on.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.ModelConfig (
    ConfigKey    NVARCHAR(60)   NOT NULL PRIMARY KEY,
    ConfigValue  NVARCHAR(100)  NOT NULL,
    Notes        NVARCHAR(400)  NOT NULL
);

INSERT dim.ModelConfig (ConfigKey, ConfigValue, Notes) VALUES
 (N'AsOfDate',          N'2026-11-03', N'The last day any event happens in the file: the latest payment date. Every point-in-time figure is measured here, and nothing is projected beyond it.'),
 (N'DataStartDate',     N'2023-01-01', N'First service date in the file.'),
 (N'ServiceDataEnd',    N'2026-08-31', N'Last service date. Claims are still being adjudicated and paid after this, which is why the adjudication tail runs into November.'),
 (N'Currency',          N'AUD',        N'Australian dollars: every facility state is Australian and the payers are Medicare, Bupa, Medibank, HCF and NIB.'),
 (N'TimelyFilingDays',  N'365',        N'The outer limit of a payer timely-filing window, used to mark AR that could not be collected in practice. An assumption, not a fact in the data.'),
 (N'ARCarriedAt',       N'Allowed',    N'Open AR is carried at the ALLOWED amount - the contracted expectation - not at billed. Billed AR would overstate the receivable by the contractual adjustment.');
GO

/*------------------------------------------------------------------- DimDate --
  Generated from a tally. Australian financial year: 1 July to 30 June, labelled
  by the year it ends in, so 2022-07-01 falls in FY23 - the convention the
  supplied calendar uses, preserved here.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimDate (
    DateKey             INT           NOT NULL PRIMARY KEY,
    [Date]              DATE          NOT NULL,
    [Year]              SMALLINT      NOT NULL,
    MonthNo             TINYINT       NOT NULL,
    MonthName           NVARCHAR(20)  NOT NULL,
    MonthShort          NVARCHAR(10)  NOT NULL,
    MonthKey            INT           NOT NULL,
    MonthStart          DATE          NOT NULL,
    MonthEnd            DATE          NOT NULL,
    MonthLabel          NVARCHAR(20)  NOT NULL,
    [Quarter]           TINYINT       NOT NULL,
    QuarterLabel        NVARCHAR(20)  NOT NULL,
    ISOWeek             TINYINT       NOT NULL,
    DayName             NVARCHAR(20)  NOT NULL,
    DayNumberOfWeek     TINYINT       NOT NULL,
    IsWeekend           BIT           NOT NULL,
    FinancialYearStart  SMALLINT      NOT NULL,
    FinancialYear       NVARCHAR(10)  NOT NULL,
    FinancialQuarter    NVARCHAR(10)  NOT NULL,
    FinancialMonthNo    TINYINT       NOT NULL,
    IsMonthEnd          BIT           NOT NULL,
    MonthOffset         SMALLINT      NOT NULL,
    InSuppliedCalendar  BIT           NOT NULL
);
GO

DECLARE @Start DATE = '2022-01-01';      -- the supplied calendar's first day, kept
DECLARE @End   DATE = '2026-12-31';      -- past the last payment (2026-11-03), to month end
-- MonthOffset is counted from the AS-OF month, so 0 is November 2026 and -11..0 is
-- the trailing twelve months. A measure then filters a small integer instead of
-- rebuilding a date range every time.
DECLARE @AsOfMonth DATE = (SELECT DATEFROMPARTS(YEAR(CONVERT(DATE, ConfigValue)),
                                                MONTH(CONVERT(DATE, ConfigValue)), 1)
                           FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');

;WITH N AS (SELECT 0 AS n UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0
            UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0
            UNION ALL SELECT 0 UNION ALL SELECT 0),
      Tally AS (SELECT TOP (DATEDIFF(DAY, @Start, @End) + 1)
                       ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS i
                FROM N a CROSS JOIN N b CROSS JOIN N c CROSS JOIN N d CROSS JOIN N e),
      D AS (SELECT DATEADD(DAY, i, @Start) AS d FROM Tally)
INSERT dim.DimDate
SELECT
    CONVERT(INT, FORMAT(d, 'yyyyMMdd')),
    d,
    YEAR(d),
    MONTH(d),
    DATENAME(MONTH, d),
    LEFT(DATENAME(MONTH, d), 3),
    YEAR(d) * 100 + MONTH(d),
    DATEFROMPARTS(YEAR(d), MONTH(d), 1),
    EOMONTH(d),
    LEFT(DATENAME(MONTH, d), 3) + ' ' + CONVERT(NVARCHAR(4), YEAR(d)),
    DATEPART(QUARTER, d),
    CONVERT(NVARCHAR(4), YEAR(d)) + ' Q' + CONVERT(NVARCHAR(1), DATEPART(QUARTER, d)),
    DATEPART(ISO_WEEK, d),
    DATENAME(WEEKDAY, d),
    ((DATEPART(WEEKDAY, d) + @@DATEFIRST - 2) % 7) + 1,          -- 1 = Monday, independent of @@DATEFIRST
    CASE WHEN ((DATEPART(WEEKDAY, d) + @@DATEFIRST - 2) % 7) + 1 >= 6 THEN 1 ELSE 0 END,
    CASE WHEN MONTH(d) >= 7 THEN YEAR(d) ELSE YEAR(d) - 1 END,
    'FY' + RIGHT(CONVERT(NVARCHAR(4), CASE WHEN MONTH(d) >= 7 THEN YEAR(d) + 1 ELSE YEAR(d) END), 2),
    'FY' + RIGHT(CONVERT(NVARCHAR(4), CASE WHEN MONTH(d) >= 7 THEN YEAR(d) + 1 ELSE YEAR(d) END), 2)
          + ' Q' + CONVERT(NVARCHAR(1), ((MONTH(d) + 5) % 12) / 3 + 1),
    ((MONTH(d) + 5) % 12) + 1,
    CASE WHEN d = EOMONTH(d) THEN 1 ELSE 0 END,
    DATEDIFF(MONTH, @AsOfMonth, d),
    CASE WHEN EXISTS (SELECT 1 FROM stg.dim_date s WHERE CONVERT(DATE, s.[Date]) = d) THEN 1 ELSE 0 END
FROM D
ORDER BY d;
GO

/*-- The generated calendar must agree with the supplied one wherever they overlap,
     or the financial-year convention has been misread. --*/
IF EXISTS (
    SELECT 1
    FROM stg.dim_date s
    JOIN dim.DimDate d ON d.[Date] = CONVERT(DATE, s.[Date])
    WHERE d.FinancialYear <> s.FinancialYear
       OR d.FinancialYearStart <> CONVERT(SMALLINT, s.FinancialYearStart)
       OR d.ISOWeek <> CONVERT(TINYINT, s.ISOWeek)
       OR d.MonthName <> s.MonthName
       OR d.DayName <> s.DayName)
    THROW 51001, N'The generated calendar disagrees with the supplied dim_date where they overlap.', 1;
GO

/*-------------------------------------------------------------- DimBeneficiary --
  Age is stated AT THE AS-OF DATE and labelled that way. A patient's age band
  changes over a four-year file; pinning it to one date makes the band a stable
  attribute, and the claim-level age at service is carried on the fact for
  anything that needs age as at treatment.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimAgeBand (
    AgeBandKey   TINYINT       NOT NULL PRIMARY KEY,
    AgeBand      NVARCHAR(20)  NOT NULL,
    MinAge       TINYINT       NOT NULL,
    MaxAge       TINYINT       NOT NULL
);
INSERT dim.DimAgeBand VALUES
 (1, N'Under 30', 0, 29), (2, N'30-44', 30, 44), (3, N'45-59', 45, 59),
 (4, N'60-74', 60, 74), (5, N'75 and over', 75, 255);
GO

CREATE TABLE dim.DimBeneficiary (
    BeneficiaryKey   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    BeneficiaryID    NVARCHAR(20)  NOT NULL UNIQUE,
    DateOfBirth      DATE          NOT NULL,
    AgeAtAsOf        TINYINT       NOT NULL,
    AgeBandKey       TINYINT       NOT NULL,
    Gender           NVARCHAR(10)  NOT NULL,
    [State]          NVARCHAR(10)  NOT NULL,
    ChronicRiskBand  NVARCHAR(20)  NOT NULL,
    RiskBandOrder    TINYINT       NOT NULL
);

DECLARE @AsOf DATE = (SELECT CONVERT(DATE, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate');

INSERT dim.DimBeneficiary (BeneficiaryID, DateOfBirth, AgeAtAsOf, AgeBandKey, Gender, [State], ChronicRiskBand, RiskBandOrder)
SELECT
    s.BeneficiaryID,
    CONVERT(DATE, s.DateOfBirth),
    a.Age,
    b.AgeBandKey,
    s.Gender,
    s.[State],
    s.ChronicRiskBand,
    CASE s.ChronicRiskBand WHEN N'Low' THEN 1 WHEN N'Medium' THEN 2 WHEN N'High' THEN 3 END
FROM stg.dim_beneficiary s
CROSS APPLY (SELECT CONVERT(TINYINT,
        DATEDIFF(YEAR, CONVERT(DATE, s.DateOfBirth), @AsOf)
        - CASE WHEN DATEADD(YEAR, DATEDIFF(YEAR, CONVERT(DATE, s.DateOfBirth), @AsOf),
                            CONVERT(DATE, s.DateOfBirth)) > @AsOf THEN 1 ELSE 0 END) AS Age) a
JOIN dim.DimAgeBand b ON a.Age BETWEEN b.MinAge AND b.MaxAge;
GO

/*---------------------------------------------------------------- DimFacility --*/
CREATE TABLE dim.DimFacility (
    FacilityKey   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    FacilityID    NVARCHAR(20)   NOT NULL UNIQUE,
    FacilityName  NVARCHAR(100)  NOT NULL,
    FacilityType  NVARCHAR(50)   NOT NULL,
    [State]       NVARCHAR(10)   NOT NULL
);
INSERT dim.DimFacility (FacilityID, FacilityName, FacilityType, [State])
SELECT FacilityID, FacilityName, FacilityType, [State] FROM stg.dim_facility;
GO

/*---------------------------------------------------------------- DimProvider --
  Every provider belongs to exactly one facility and 100% of claims are billed at
  the provider's own facility (Phase 1, section 11), so facility is carried here
  as well. Provider and facility are ONE hierarchy, which is what lets row-level
  security filter a single table rather than two.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimProvider (
    ProviderKey   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    ProviderID    NVARCHAR(20)   NOT NULL UNIQUE,
    ProviderName  NVARCHAR(100)  NOT NULL,
    Specialty     NVARCHAR(50)   NOT NULL,
    FacilityID    NVARCHAR(20)   NOT NULL,
    FacilityName  NVARCHAR(100)  NOT NULL,
    FacilityType  NVARCHAR(50)   NOT NULL,
    [State]       NVARCHAR(10)   NOT NULL
);
INSERT dim.DimProvider (ProviderID, ProviderName, Specialty, FacilityID, FacilityName, FacilityType, [State])
SELECT p.ProviderID, p.ProviderName, p.Specialty, p.FacilityID, f.FacilityName, f.FacilityType, f.[State]
FROM stg.dim_provider p
JOIN stg.dim_facility f ON f.FacilityID = p.FacilityID;
GO

/*------------------------------------------------------------------- DimPayer --
  PayerType is the one attribute in this model that carries a real, measured
  effect: Self Pay denies at 2.95% against 8.79% for the five insurers, and that
  gap is larger than every other effect in the data put together.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimPayer (
    PayerKey    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    PayerID     NVARCHAR(20)   NOT NULL UNIQUE,
    PayerName   NVARCHAR(100)  NOT NULL,
    PayerType   NVARCHAR(30)   NOT NULL,
    IsSelfPay   BIT            NOT NULL
);
INSERT dim.DimPayer (PayerID, PayerName, PayerType, IsSelfPay)
SELECT
    PayerID,
    PayerName,
    CASE WHEN PayerName = N'Self Pay' THEN N'Self-funded patient'
         WHEN PayerName = N'Medicare' THEN N'Government'
         ELSE N'Private health insurer' END,
    CASE WHEN PayerName = N'Self Pay' THEN 1 ELSE 0 END
FROM stg.dim_payer;
GO

/*------------------------------------------------------------- DimClaimStatus --*/
CREATE TABLE dim.DimClaimStatus (
    ClaimStatusKey  TINYINT       NOT NULL PRIMARY KEY,
    ClaimStatus     NVARCHAR(20)  NOT NULL UNIQUE,
    IsResolved      BIT           NOT NULL,
    IsOpenAR        BIT           NOT NULL,
    StatusOrder     TINYINT       NOT NULL,
    Definition      NVARCHAR(200) NOT NULL
);
INSERT dim.DimClaimStatus VALUES
 (1, N'Paid',    1, 0, 1, N'Adjudicated and settled in a single remittance. The allowed amount splits into payer cash and patient responsibility.'),
 (2, N'Pending', 0, 1, 2, N'No payment and no denial. Carried as open AR at the allowed amount.'),
 (3, N'Denied',  1, 0, 3, N'Adjudicated to zero. No payment exists on any denied claim in this file, whatever the denial status says.');
GO

/*------------------------------------------------------------ DimDenialReason --
  ReasonCategory is the standard revenue-cycle split: a front-end failure is
  preventable at registration, a coding failure at submission, a clinical failure
  needs the record, and timeliness is a process failure. It is the grouping a
  denials team is actually organised around.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimDenialReason (
    DenialReasonKey  TINYINT        NOT NULL PRIMARY KEY,
    DenialReason     NVARCHAR(50)   NOT NULL UNIQUE,
    ReasonCategory   NVARCHAR(40)   NOT NULL,
    PreventableAt    NVARCHAR(40)   NOT NULL,
    CategoryOrder    TINYINT        NOT NULL
);
INSERT dim.DimDenialReason VALUES
 (1, N'Eligibility',         N'Front-end',   N'Registration',      1),
 (2, N'Prior Authorisation', N'Front-end',   N'Registration',      1),
 (3, N'Missing Information', N'Front-end',   N'Registration',      1),
 (4, N'Coding Error',        N'Coding',      N'Charge capture',    2),
 (5, N'Duplicate Claim',     N'Coding',      N'Charge capture',    2),
 (6, N'Medical Necessity',   N'Clinical',    N'Clinical review',   3),
 (7, N'Timely Filing',       N'Process',     N'Billing office',    4);
GO

/*------------------------------------------------------------ DimDenialStatus --
  Labelled as WORKFLOW STATE, not outcome. Phase 1, section 5: no denied claim in
  this file was ever paid, including every one marked Corrected or Appealed, so
  none of these values may be read as a recovery.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimDenialStatus (
    DenialStatusKey  TINYINT        NOT NULL PRIMARY KEY,
    DenialStatus     NVARCHAR(30)   NOT NULL UNIQUE,
    IsTerminal       BIT            NOT NULL,
    StatusOrder      TINYINT        NOT NULL,
    Definition       NVARCHAR(200)  NOT NULL
);
INSERT dim.DimDenialStatus VALUES
 (1, N'Open',        0, 1, N'Workflow state only: sitting in the denials queue. No recovery is observable in this data.'),
 (2, N'Appealed',    0, 2, N'Workflow state only: an appeal was raised. No appealed claim was subsequently paid.'),
 (3, N'Corrected',   0, 3, N'Workflow state only: the claim was corrected. No corrected claim was subsequently paid.'),
 (4, N'Written Off', 1, 4, N'Workflow state only: abandoned. The written-off amount is not recorded separately in the source.');
GO

/*--------------------------------------------------------------- DimProcedure --
  Descriptions are the published meanings of these CPT codes; ServiceLine is the
  usual departmental grouping. Phase 1, section 8, found the charge is drawn
  independently of the code, so this dimension is for VOLUME and MIX only - no
  page ranks a procedure by revenue.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimProcedure (
    ProcedureKey    TINYINT        NOT NULL PRIMARY KEY,
    ProcedureCode   NVARCHAR(20)   NOT NULL UNIQUE,
    ProcedureName   NVARCHAR(120)  NOT NULL,
    ServiceLine     NVARCHAR(40)   NOT NULL,
    SettingHint     NVARCHAR(40)   NOT NULL
);
INSERT dim.DimProcedure VALUES
 (1,  N'99213', N'Office visit, established patient, low complexity',      N'Office visits',  N'Clinic'),
 (2,  N'99214', N'Office visit, established patient, moderate complexity', N'Office visits',  N'Clinic'),
 (3,  N'36415', N'Collection of venous blood by venipuncture',             N'Pathology',      N'Clinic'),
 (4,  N'85025', N'Full blood count with differential',                     N'Pathology',      N'Clinic'),
 (5,  N'80053', N'Comprehensive metabolic panel',                          N'Pathology',      N'Clinic'),
 (6,  N'71046', N'Chest X-ray, two views',                                 N'Imaging',        N'Imaging Centre'),
 (7,  N'70553', N'MRI brain, with and without contrast',                   N'Imaging',        N'Imaging Centre'),
 (8,  N'72148', N'MRI lumbar spine, without contrast',                     N'Imaging',        N'Imaging Centre'),
 (9,  N'93000', N'Electrocardiogram with interpretation and report',       N'Cardiac',        N'Clinic'),
 (10, N'45378', N'Diagnostic colonoscopy',                                 N'Procedural',     N'Day Surgery');
GO

/*--------------------------------------------------------------- DimDiagnosis --
  ICD-10 three-character categories with their chapter. IsChronicCondition marks
  the five that appear on a standard chronic disease register - it exists so the
  diagnosis mix can be checked against the beneficiary's ChronicRiskBand, which
  is a claim the source makes and the model can test.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimDiagnosis (
    DiagnosisKey         TINYINT        NOT NULL PRIMARY KEY,
    DiagnosisCode        NVARCHAR(20)   NOT NULL UNIQUE,
    DiagnosisName        NVARCHAR(120)  NOT NULL,
    ICD10Chapter         NVARCHAR(60)   NOT NULL,
    IsChronicCondition   BIT            NOT NULL
);
INSERT dim.DimDiagnosis VALUES
 (1,  N'I10', N'Essential (primary) hypertension',        N'Circulatory system',      1),
 (2,  N'I25', N'Chronic ischaemic heart disease',         N'Circulatory system',      1),
 (3,  N'E11', N'Type 2 diabetes mellitus',                N'Endocrine and metabolic', 1),
 (4,  N'N18', N'Chronic kidney disease',                  N'Genitourinary system',    1),
 (5,  N'J45', N'Asthma',                                  N'Respiratory system',      1),
 (6,  N'C50', N'Malignant neoplasm of breast',            N'Neoplasms',               0),
 (7,  N'M54', N'Dorsalgia (back pain)',                   N'Musculoskeletal system',  0),
 (8,  N'K21', N'Gastro-oesophageal reflux disease',       N'Digestive system',        0),
 (9,  N'G43', N'Migraine',                                N'Nervous system',          0),
 (10, N'F32', N'Depressive episode',                      N'Mental and behavioural',  0);
GO

/*----------------------------------------------------------- DimPaymentMethod --*/
CREATE TABLE dim.DimPaymentMethod (
    PaymentMethodKey  TINYINT       NOT NULL PRIMARY KEY,
    PaymentMethod     NVARCHAR(30)  NOT NULL UNIQUE,
    IsElectronic      BIT           NOT NULL,
    MethodOrder       TINYINT       NOT NULL
);
INSERT dim.DimPaymentMethod VALUES
 (1, N'EFT',    1, 1),
 (2, N'Card',   1, 2),
 (3, N'Cheque', 0, 3);
GO

/*---------------------------------------------------------------- DimARBucket --
  The standard revenue-cycle ageing ladder. 365+ exists as its own bucket because
  that is the outer edge of a payer timely-filing window: past it, a claim is not
  a receivable, it is a write-off waiting to be recognised.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.DimARBucket (
    ARBucketKey   TINYINT       NOT NULL PRIMARY KEY,
    ARBucket      NVARCHAR(20)  NOT NULL UNIQUE,
    MinDays       SMALLINT      NOT NULL,
    MaxDays       SMALLINT      NOT NULL,
    IsPastFiling  BIT           NOT NULL
);
INSERT dim.DimARBucket VALUES
 (1, N'0-30',    0,    30, 0),
 (2, N'31-60',  31,    60, 0),
 (3, N'61-90',  61,    90, 0),
 (4, N'91-180', 91,   180, 0),
 (5, N'181-365',181,  365, 0),
 (6, N'365+',   366, 9999, 1);
GO

/*--------------------------------------------------------- SecurityUserAccess --
  Left at its source grain, one row per grant. 'ALL' is kept as a literal rather
  than expanded to every facility: the RLS expression tests for it, which is one
  comparison instead of a 30-row table scan per user.
-------------------------------------------------------------------------------*/
CREATE TABLE dim.SecurityUserAccess (
    UserEmail   NVARCHAR(200)  NOT NULL,
    [Role]      NVARCHAR(100)  NOT NULL,
    FacilityID  NVARCHAR(20)   NOT NULL,
    ProviderID  NVARCHAR(20)   NOT NULL,
    ScopeLabel  NVARCHAR(60)   NOT NULL,
    CONSTRAINT PK_SecurityUserAccess PRIMARY KEY (UserEmail, FacilityID, ProviderID)
);
INSERT dim.SecurityUserAccess (UserEmail, [Role], FacilityID, ProviderID, ScopeLabel)
SELECT UserEmail, [Role], FacilityID, ProviderID,
       CASE WHEN FacilityID = N'ALL' AND ProviderID = N'ALL' THEN N'Whole organisation'
            WHEN ProviderID = N'ALL' THEN N'One facility'
            ELSE N'One provider' END
FROM stg.security_user_access;
GO

PRINT 'dimensions built';
SELECT 'DimDate' t, COUNT(*) rows FROM dim.DimDate
UNION ALL SELECT 'DimBeneficiary', COUNT(*) FROM dim.DimBeneficiary
UNION ALL SELECT 'DimProvider', COUNT(*) FROM dim.DimProvider
UNION ALL SELECT 'DimFacility', COUNT(*) FROM dim.DimFacility
UNION ALL SELECT 'DimPayer', COUNT(*) FROM dim.DimPayer
UNION ALL SELECT 'DimClaimStatus', COUNT(*) FROM dim.DimClaimStatus
UNION ALL SELECT 'DimDenialReason', COUNT(*) FROM dim.DimDenialReason
UNION ALL SELECT 'DimDenialStatus', COUNT(*) FROM dim.DimDenialStatus
UNION ALL SELECT 'DimProcedure', COUNT(*) FROM dim.DimProcedure
UNION ALL SELECT 'DimDiagnosis', COUNT(*) FROM dim.DimDiagnosis
UNION ALL SELECT 'DimPaymentMethod', COUNT(*) FROM dim.DimPaymentMethod
UNION ALL SELECT 'DimARBucket', COUNT(*) FROM dim.DimARBucket
UNION ALL SELECT 'DimAgeBand', COUNT(*) FROM dim.DimAgeBand
UNION ALL SELECT 'SecurityUserAccess', COUNT(*) FROM dim.SecurityUserAccess
UNION ALL SELECT 'ModelConfig', COUNT(*) FROM dim.ModelConfig;
GO
