/*=============================================================================
  02_create_staging.sql

  Staging tables shaped exactly like the CSV headers, in CSV column order.

  EVERY column is NVARCHAR. That is deliberate. BULK INSERT into a typed column
  fails with a row number and nothing else; a CAST in 04/05 fails with the value,
  the column and the claim it belongs to. Types are applied once, on the way into
  dim and fact, where a bad value can be named.

  Idempotent: each table is dropped and recreated.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DROP TABLE IF EXISTS stg.dim_beneficiary;
DROP TABLE IF EXISTS stg.dim_date;
DROP TABLE IF EXISTS stg.dim_facility;
DROP TABLE IF EXISTS stg.dim_payer;
DROP TABLE IF EXISTS stg.dim_provider;
DROP TABLE IF EXISTS stg.fact_claim_lines;
DROP TABLE IF EXISTS stg.fact_claims;
DROP TABLE IF EXISTS stg.fact_denials;
DROP TABLE IF EXISTS stg.fact_payments;
DROP TABLE IF EXISTS stg.security_user_access;
GO

CREATE TABLE stg.dim_beneficiary (
    BeneficiaryID    NVARCHAR(50),
    DateOfBirth      NVARCHAR(50),
    Gender           NVARCHAR(50),
    State            NVARCHAR(50),
    ChronicRiskBand  NVARCHAR(50)
);

CREATE TABLE stg.dim_date (
    [Date]              NVARCHAR(50),
    [Year]              NVARCHAR(50),
    MonthNo             NVARCHAR(50),
    MonthName           NVARCHAR(50),
    Quarter             NVARCHAR(50),
    ISOWeek             NVARCHAR(50),
    DayName             NVARCHAR(50),
    FinancialYearStart  NVARCHAR(50),
    FinancialYear       NVARCHAR(50)
);

CREATE TABLE stg.dim_facility (
    FacilityID    NVARCHAR(50),
    FacilityName  NVARCHAR(200),
    FacilityType  NVARCHAR(100),
    State         NVARCHAR(50)
);

CREATE TABLE stg.dim_payer (
    PayerID    NVARCHAR(50),
    PayerName  NVARCHAR(200)
);

CREATE TABLE stg.dim_provider (
    ProviderID    NVARCHAR(50),
    ProviderName  NVARCHAR(200),
    Specialty     NVARCHAR(100),
    FacilityID    NVARCHAR(50)
);

CREATE TABLE stg.fact_claim_lines (
    ClaimLineID    NVARCHAR(50),
    ClaimID        NVARCHAR(50),
    ProcedureCode  NVARCHAR(50),
    DiagnosisCode  NVARCHAR(50),
    ChargeAmount   NVARCHAR(50)
);

CREATE TABLE stg.fact_claims (
    ClaimID        NVARCHAR(50),
    BeneficiaryID  NVARCHAR(50),
    ProviderID     NVARCHAR(50),
    FacilityID     NVARCHAR(50),
    PayerID        NVARCHAR(50),
    ServiceDate    NVARCHAR(50),
    SubmittedDate  NVARCHAR(50),
    ProcessedDate  NVARCHAR(50),
    ClaimStatus    NVARCHAR(50),
    BilledAmount   NVARCHAR(50),
    AllowedAmount  NVARCHAR(50),
    PaidAmount     NVARCHAR(50)
);

CREATE TABLE stg.fact_denials (
    DenialID      NVARCHAR(50),
    ClaimID       NVARCHAR(50),
    DenialReason  NVARCHAR(100),
    DenialDate    NVARCHAR(50),
    DenialStatus  NVARCHAR(50)
);

CREATE TABLE stg.fact_payments (
    PaymentID      NVARCHAR(50),
    ClaimID        NVARCHAR(50),
    PaymentDate    NVARCHAR(50),
    PaymentAmount  NVARCHAR(50),
    PaymentMethod  NVARCHAR(50)
);

CREATE TABLE stg.security_user_access (
    UserEmail   NVARCHAR(200),
    Role        NVARCHAR(100),
    FacilityID  NVARCHAR(50),
    ProviderID  NVARCHAR(50)
);
GO

PRINT '10 staging tables created';
GO
