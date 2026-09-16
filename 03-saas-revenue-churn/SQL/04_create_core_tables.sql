/*=============================================================================
  04_create_core_tables.sql

  The typed star schema, plus the two derived tables this project turns on.

  Grains, stated once so nothing downstream has to guess:
    DimDate                 one row per day
    DimCustomer             one row per customer (how we got them is an attribute
                            of the customer; what they cost is a fact)
    DimPlan                 one row per plan
    DimSeverity             one row per ticket severity, with its order
    DimMovementType         one row per MRR movement type, with its order and sign
    DimTenureBand           one row per tenure band, with its order
    DimCohort               one row per signup month, with its size and opening MRR
    DimTenureMonth          one row per months-since-start (M0, M1, ...)
    FactSubscription        one row per subscription (= one per customer here)
    FactSubscriptionMonth   one row per subscription per month it is LIVE at month end
    FactMRRMovement         one row per customer per month in which its MRR CHANGED
    FactInvoice             one row per invoice
    FactUsageMonthly        one row per customer per month observed
    FactSupportTicket       one row per ticket
    FactAcquisition         one row per customer
    SecurityUserAccess      one row per user

  Keys and foreign keys are declared and engine-trusted, so a broken join fails
  at build time rather than showing up as a missing bar on a page.
=============================================================================*/
USE SaaSRevenueBI;
GO

-- Facts first: they hold the foreign keys.
DROP TABLE IF EXISTS dbo.FactMRRMovement;
DROP TABLE IF EXISTS dbo.FactSubscriptionMonth;
DROP TABLE IF EXISTS dbo.FactInvoice;
DROP TABLE IF EXISTS dbo.FactUsageMonthly;
DROP TABLE IF EXISTS dbo.FactSupportTicket;
DROP TABLE IF EXISTS dbo.FactAcquisition;
DROP TABLE IF EXISTS dbo.FactSubscription;
DROP TABLE IF EXISTS dbo.SecurityUserAccess;
DROP TABLE IF EXISTS dbo.DimTenureMonth;
DROP TABLE IF EXISTS dbo.DimCohort;
DROP TABLE IF EXISTS dbo.DimTenureBand;
DROP TABLE IF EXISTS dbo.DimMovementType;
DROP TABLE IF EXISTS dbo.DimSeverity;
DROP TABLE IF EXISTS dbo.DimCustomer;
DROP TABLE IF EXISTS dbo.DimPlan;
DROP TABLE IF EXISTS dbo.DimDate;
DROP TABLE IF EXISTS dbo.ModelConfig;
GO

/*  Every assumption this project makes, held as data so the report can show it
    and a check can read it. Nothing here is hard-coded in a measure.          */
CREATE TABLE dbo.ModelConfig (
    ConfigKey   NVARCHAR(60)  NOT NULL CONSTRAINT PK_ModelConfig PRIMARY KEY,
    ConfigValue NVARCHAR(100) NOT NULL,
    Description NVARCHAR(400) NOT NULL
);
GO

CREATE TABLE dbo.DimDate (
    [Date]                DATE         NOT NULL CONSTRAINT PK_DimDate PRIMARY KEY,
    [Year]                INT          NOT NULL,
    MonthNo               TINYINT      NOT NULL,
    MonthName             NVARCHAR(20) NOT NULL,
    MonthShort            NVARCHAR(6)  NOT NULL,
    [Quarter]             TINYINT      NOT NULL,
    QuarterLabel          NVARCHAR(10) NOT NULL,
    YearMonth             INT          NOT NULL,     -- 202608, for sorting
    YearMonthLabel        NVARCHAR(10) NOT NULL,     -- Aug 2026
    MonthStart            DATE         NOT NULL,
    MonthEnd              DATE         NOT NULL,
    ISOWeek               TINYINT      NOT NULL,
    DayName               NVARCHAR(20) NOT NULL,
    DayOfWeekNo           TINYINT      NOT NULL,
    FinancialYearStart    INT          NOT NULL,
    FinancialYear         NVARCHAR(10) NOT NULL,
    FinancialMonthNo      TINYINT      NOT NULL,
    FinancialQuarter      TINYINT      NOT NULL,
    FinancialQuarterLabel NVARCHAR(12) NOT NULL,
    FinancialQuarterSort  INT          NOT NULL,
    -- Months from the as-of month: 0 is the as-of month, -11 is eleven months back.
    -- A trailing window is then a range on an integer, which folds to SQL.
    MonthOffset           INT          NOT NULL,
    IsSourceCalendar      BIT          NOT NULL,     -- present in the supplied dim_date
    IsAfterAsOf           BIT          NOT NULL,
    IsMonthComplete       BIT          NOT NULL
);
GO

CREATE TABLE dbo.DimPlan (
    PlanID           NVARCHAR(10)   NOT NULL CONSTRAINT PK_DimPlan PRIMARY KEY,
    PlanName         NVARCHAR(50)   NOT NULL,
    MonthlyListPrice DECIMAL(19, 2) NOT NULL,
    PlanOrder        TINYINT        NOT NULL,        -- Starter -> Enterprise, by price
    PlanLabel        NVARCHAR(80)   NOT NULL         -- Business ($399/mo)
);
GO

CREATE TABLE dbo.DimCustomer (
    CustomerID        NVARCHAR(20)  NOT NULL CONSTRAINT PK_DimCustomer PRIMARY KEY,
    CustomerName      NVARCHAR(200) NOT NULL,
    SignupDate        DATE          NOT NULL,
    CohortMonth       DATE          NOT NULL,        -- first day of the signup month
    CohortLabel       NVARCHAR(10)  NOT NULL,
    Industry          NVARCHAR(100) NOT NULL,
    Country           NVARCHAR(100) NOT NULL,
    Segment           NVARCHAR(50)  NOT NULL,
    SegmentOrder      TINYINT       NOT NULL,        -- SMB -> Enterprise
    -- Plan lives on the CUSTOMER, not only on the subscription: this source gives every
    -- customer exactly one subscription for life on one plan, so plan is an attribute of
    -- the customer. It matters because filtering by plan must reach tickets, usage and
    -- invoices too, and those hang off the customer.
    PlanID            NVARCHAR(10)  NOT NULL,
    BillingCycle      NVARCHAR(20)  NOT NULL,       -- one per customer, for life
    SubscriptionStatus NVARCHAR(20) NOT NULL,       -- Active or Churned
    IsChurned         BIT           NOT NULL,
    AcquisitionSource NVARCHAR(100) NOT NULL,
    AttributionType   NVARCHAR(100) NOT NULL
);
GO

CREATE TABLE dbo.DimSeverity (
    SeverityName  NVARCHAR(20) NOT NULL CONSTRAINT PK_DimSeverity PRIMARY KEY,
    SeverityOrder TINYINT      NOT NULL,
    IsUrgent      BIT          NOT NULL              -- High or Critical
);
GO

/*  The five movements a SaaS book can make. All five are modelled; the audit
    showed three of them cannot occur in this data, and the report says so
    rather than quietly dropping them from the waterfall.                      */
CREATE TABLE dbo.DimMovementType (
    MovementType  NVARCHAR(20) NOT NULL CONSTRAINT PK_DimMovementType PRIMARY KEY,
    MovementOrder TINYINT      NOT NULL,
    MovementSign  SMALLINT     NOT NULL,             -- +1 adds to MRR, -1 removes
    IsSupported   BIT          NOT NULL,             -- can it occur in THIS data?
    WhyNot        NVARCHAR(200) NULL
);
GO

CREATE TABLE dbo.DimTenureBand (
    TenureBand      NVARCHAR(20) NOT NULL CONSTRAINT PK_DimTenureBand PRIMARY KEY,
    TenureBandOrder TINYINT      NOT NULL,
    MinMonths       INT          NOT NULL,
    MaxMonths       INT          NOT NULL
);
GO

/*  The two axes of a retention matrix. Both are derived from the subscriptions,
    and both exist as dimensions rather than fact columns so that the matrix sorts
    by time and by tenure instead of alphabetically - "Apr 2022" before "Aug 2022",
    and "M10" before "M2", is how a fact column would order them.               */
CREATE TABLE dbo.DimCohort (
    CohortMonth DATE           NOT NULL CONSTRAINT PK_DimCohort PRIMARY KEY,
    CohortLabel NVARCHAR(10)   NOT NULL,
    CohortSort  INT            NOT NULL,
    CohortSize  INT            NOT NULL,       -- customers that started in the month
    CohortMRR   DECIMAL(19, 2) NOT NULL        -- the MRR they started with
);
GO

CREATE TABLE dbo.DimTenureMonth (
    TenureMonth INT          NOT NULL CONSTRAINT PK_DimTenureMonth PRIMARY KEY,
    TenureLabel NVARCHAR(10) NOT NULL,         -- M0 is the month they signed up
    TenureYear  INT          NOT NULL
);
GO

CREATE TABLE dbo.FactSubscription (
    SubscriptionID NVARCHAR(20)   NOT NULL CONSTRAINT PK_FactSubscription PRIMARY KEY,
    CustomerID     NVARCHAR(20)   NOT NULL,
    PlanID         NVARCHAR(10)   NOT NULL,
    StartDate      DATE           NOT NULL,
    EndDate        DATE           NULL,
    StartMonth     DATE           NOT NULL,
    EndMonth       DATE           NULL,
    [Status]       NVARCHAR(20)   NOT NULL,
    IsChurned      BIT            NOT NULL,
    MRR            DECIMAL(19, 2) NOT NULL,
    ARR            DECIMAL(19, 2) NOT NULL,
    BillingCycle   NVARCHAR(20)   NOT NULL,
    -- Whole months from start to the end date, or to the as-of date if still running.
    TenureMonths   INT            NOT NULL,
    TenureBand     NVARCHAR(20)   NOT NULL,
    CONSTRAINT FK_Sub_Customer FOREIGN KEY (CustomerID) REFERENCES dbo.DimCustomer (CustomerID),
    CONSTRAINT FK_Sub_Plan     FOREIGN KEY (PlanID)     REFERENCES dbo.DimPlan (PlanID),
    CONSTRAINT FK_Sub_Band     FOREIGN KEY (TenureBand) REFERENCES dbo.DimTenureBand (TenureBand),
    CONSTRAINT FK_Sub_Start    FOREIGN KEY (StartDate)  REFERENCES dbo.DimDate ([Date])
);
GO

/*  The monthly snapshot. One row per subscription per month in which it is live
    AT MONTH END - which is what makes MRR a stock that can be read on any month
    without a window function in DAX, and what a cohort matrix pivots.          */
CREATE TABLE dbo.FactSubscriptionMonth (
    MonthStart     DATE           NOT NULL,
    SubscriptionID NVARCHAR(20)   NOT NULL,
    CustomerID     NVARCHAR(20)   NOT NULL,
    PlanID         NVARCHAR(10)   NOT NULL,
    MRR            DECIMAL(19, 2) NOT NULL,
    CohortMonth    DATE           NOT NULL,
    TenureMonth    INT            NOT NULL,          -- 0 in the month it started
    IsFirstMonth   BIT            NOT NULL,
    IsLastMonth    BIT            NOT NULL,
    CONSTRAINT PK_FactSubscriptionMonth PRIMARY KEY (MonthStart, SubscriptionID),
    CONSTRAINT FK_SubMonth_Date  FOREIGN KEY (MonthStart)     REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_SubMonth_Coh   FOREIGN KEY (CohortMonth)    REFERENCES dbo.DimCohort (CohortMonth),
    CONSTRAINT FK_SubMonth_Ten   FOREIGN KEY (TenureMonth)    REFERENCES dbo.DimTenureMonth (TenureMonth),
    CONSTRAINT FK_SubMonth_Sub   FOREIGN KEY (SubscriptionID) REFERENCES dbo.FactSubscription (SubscriptionID),
    CONSTRAINT FK_SubMonth_Cust  FOREIGN KEY (CustomerID)     REFERENCES dbo.DimCustomer (CustomerID),
    CONSTRAINT FK_SubMonth_Plan  FOREIGN KEY (PlanID)         REFERENCES dbo.DimPlan (PlanID)
);
GO

/*  The movement ledger: one row per customer per month in which its MRR changed,
    with the change classified. Built by comparing each month against the one
    before it, so the classification is DERIVED and can be checked, not asserted. */
CREATE TABLE dbo.FactMRRMovement (
    MonthStart   DATE           NOT NULL,
    CustomerID   NVARCHAR(20)   NOT NULL,
    PlanID       NVARCHAR(10)   NOT NULL,
    MovementType NVARCHAR(20)   NOT NULL,
    MRRDelta     DECIMAL(19, 2) NOT NULL,            -- signed: churn is negative
    PriorMRR     DECIMAL(19, 2) NOT NULL,
    CurrentMRR   DECIMAL(19, 2) NOT NULL,
    CONSTRAINT PK_FactMRRMovement PRIMARY KEY (MonthStart, CustomerID, MovementType),
    CONSTRAINT FK_Mov_Date FOREIGN KEY (MonthStart)   REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_Mov_Cust FOREIGN KEY (CustomerID)   REFERENCES dbo.DimCustomer (CustomerID),
    CONSTRAINT FK_Mov_Plan FOREIGN KEY (PlanID)       REFERENCES dbo.DimPlan (PlanID),
    CONSTRAINT FK_Mov_Type FOREIGN KEY (MovementType) REFERENCES dbo.DimMovementType (MovementType)
);
GO

CREATE TABLE dbo.FactInvoice (
    InvoiceID      NVARCHAR(20)   NOT NULL CONSTRAINT PK_FactInvoice PRIMARY KEY,
    SubscriptionID NVARCHAR(20)   NOT NULL,
    CustomerID     NVARCHAR(20)   NOT NULL,
    InvoiceDate    DATE           NOT NULL,
    InvoiceMonth   DATE           NOT NULL,
    InvoiceAmount  DECIMAL(19, 2) NOT NULL,
    PaymentDate    DATE           NULL,
    PaymentStatus  NVARCHAR(20)   NOT NULL,
    IsFailed       BIT            NOT NULL,
    DaysToPay      INT            NULL,
    CONSTRAINT FK_Inv_Date FOREIGN KEY (InvoiceDate)    REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_Inv_Sub  FOREIGN KEY (SubscriptionID) REFERENCES dbo.FactSubscription (SubscriptionID),
    CONSTRAINT FK_Inv_Cust FOREIGN KEY (CustomerID)     REFERENCES dbo.DimCustomer (CustomerID)
);
GO

CREATE TABLE dbo.FactUsageMonthly (
    MonthStart          DATE           NOT NULL,
    CustomerID          NVARCHAR(20)   NOT NULL,
    LicensedSeats       INT            NOT NULL,
    ActiveUsers         INT            NOT NULL,
    Logins              INT            NOT NULL,
    FeatureAdoptionRate DECIMAL(9, 4)  NOT NULL,
    CriticalErrors      INT            NOT NULL,
    CONSTRAINT PK_FactUsageMonthly PRIMARY KEY (MonthStart, CustomerID),
    CONSTRAINT FK_Use_Date FOREIGN KEY (MonthStart) REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_Use_Cust FOREIGN KEY (CustomerID) REFERENCES dbo.DimCustomer (CustomerID)
);
GO

CREATE TABLE dbo.FactSupportTicket (
    TicketID        NVARCHAR(20)   NOT NULL CONSTRAINT PK_FactSupportTicket PRIMARY KEY,
    CustomerID      NVARCHAR(20)   NOT NULL,
    OpenedDate      DATE           NOT NULL,
    OpenedMonth     DATE           NOT NULL,
    Severity        NVARCHAR(20)   NOT NULL,
    ResolutionHours DECIMAL(9, 2)  NOT NULL,
    [Status]        NVARCHAR(20)   NOT NULL,
    IsResolved      BIT            NOT NULL,
    Category        NVARCHAR(50)   NOT NULL,
    CONSTRAINT FK_Tick_Date FOREIGN KEY (OpenedDate) REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_Tick_Cust FOREIGN KEY (CustomerID) REFERENCES dbo.DimCustomer (CustomerID),
    CONSTRAINT FK_Tick_Sev  FOREIGN KEY (Severity)   REFERENCES dbo.DimSeverity (SeverityName)
);
GO

CREATE TABLE dbo.FactAcquisition (
    CustomerID       NVARCHAR(20)   NOT NULL CONSTRAINT PK_FactAcquisition PRIMARY KEY,
    AcquisitionMonth DATE           NOT NULL,        -- the signup month: when the cost lands
    AcquisitionCost  DECIMAL(19, 2) NOT NULL,
    CONSTRAINT FK_Acq_Date FOREIGN KEY (AcquisitionMonth) REFERENCES dbo.DimDate ([Date]),
    CONSTRAINT FK_Acq_Cust FOREIGN KEY (CustomerID)       REFERENCES dbo.DimCustomer (CustomerID)
);
GO

CREATE TABLE dbo.SecurityUserAccess (
    UserEmail NVARCHAR(200) NOT NULL,
    [Role]    NVARCHAR(100) NOT NULL,
    Country   NVARCHAR(100) NOT NULL,               -- 'ALL' means every country
    CONSTRAINT PK_SecurityUserAccess PRIMARY KEY (UserEmail, Country)
);
GO
PRINT 'Core tables created (9 dimensions incl. config, 7 facts, 1 security).';
GO
