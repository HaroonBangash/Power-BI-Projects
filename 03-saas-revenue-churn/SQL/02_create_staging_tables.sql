/*=============================================================================
  02_create_staging_tables.sql

  One landing table per source file, every column NVARCHAR.

  Text landing is deliberate. A date that does not parse, or a number with a
  stray character, must not abort the load - it must arrive, be counted, and
  fail a named check in 09 where the row can be seen. Typing happens once, in
  dbo, against columns that are declared NOT NULL where the audit proved the
  source never holds a null.

  Column order matches the CSV header exactly; BULK INSERT is positional.
=============================================================================*/
USE SaaSRevenueBI;
GO

DROP TABLE IF EXISTS stg.dim_customer;
CREATE TABLE stg.dim_customer (
    CustomerID      NVARCHAR(50),
    CustomerName    NVARCHAR(200),
    SignupDate      NVARCHAR(50),
    Industry        NVARCHAR(100),
    Country         NVARCHAR(100),
    Segment         NVARCHAR(100)
);

DROP TABLE IF EXISTS stg.dim_plan;
CREATE TABLE stg.dim_plan (
    PlanID              NVARCHAR(50),
    PlanName            NVARCHAR(100),
    MonthlyListPrice    NVARCHAR(50)
);

DROP TABLE IF EXISTS stg.dim_date;
CREATE TABLE stg.dim_date (
    [Date]              NVARCHAR(50),
    [Year]              NVARCHAR(50),
    MonthNo             NVARCHAR(50),
    MonthName           NVARCHAR(50),
    [Quarter]           NVARCHAR(50),
    ISOWeek             NVARCHAR(50),
    DayName             NVARCHAR(50),
    FinancialYearStart  NVARCHAR(50),
    FinancialYear       NVARCHAR(50)
);

DROP TABLE IF EXISTS stg.fact_subscriptions;
CREATE TABLE stg.fact_subscriptions (
    SubscriptionID  NVARCHAR(50),
    CustomerID      NVARCHAR(50),
    PlanID          NVARCHAR(50),
    StartDate       NVARCHAR(50),
    EndDate         NVARCHAR(50),
    [Status]        NVARCHAR(50),
    MRR             NVARCHAR(50),
    BillingCycle    NVARCHAR(50)
);

DROP TABLE IF EXISTS stg.fact_invoices;
CREATE TABLE stg.fact_invoices (
    InvoiceID       NVARCHAR(50),
    SubscriptionID  NVARCHAR(50),
    CustomerID      NVARCHAR(50),
    InvoiceDate     NVARCHAR(50),
    InvoiceAmount   NVARCHAR(50),
    PaymentDate     NVARCHAR(50),
    PaymentStatus   NVARCHAR(50)
);

DROP TABLE IF EXISTS stg.fact_product_usage_monthly;
CREATE TABLE stg.fact_product_usage_monthly (
    [Month]             NVARCHAR(50),
    CustomerID          NVARCHAR(50),
    LicensedSeats       NVARCHAR(50),
    ActiveUsers         NVARCHAR(50),
    Logins              NVARCHAR(50),
    FeatureAdoptionRate NVARCHAR(50),
    CriticalErrors      NVARCHAR(50)
);

DROP TABLE IF EXISTS stg.fact_support_tickets;
CREATE TABLE stg.fact_support_tickets (
    TicketID        NVARCHAR(50),
    CustomerID      NVARCHAR(50),
    OpenedDate      NVARCHAR(50),
    Severity        NVARCHAR(50),
    ResolutionHours NVARCHAR(50),
    [Status]        NVARCHAR(50),
    Category        NVARCHAR(100)
);

DROP TABLE IF EXISTS stg.fact_customer_acquisition;
CREATE TABLE stg.fact_customer_acquisition (
    CustomerID          NVARCHAR(50),
    AcquisitionSource   NVARCHAR(100),
    AcquisitionCost     NVARCHAR(50),
    AttributionType     NVARCHAR(100)
);

DROP TABLE IF EXISTS stg.security_user_access;
CREATE TABLE stg.security_user_access (
    UserEmail   NVARCHAR(200),
    [Role]      NVARCHAR(100),
    Country     NVARCHAR(100)
);
GO
PRINT 'Staging tables created (9).';
GO
