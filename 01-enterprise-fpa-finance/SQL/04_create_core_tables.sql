/*=============================================================================
  04_create_core_tables.sql

  Typed, constrained star schema. Every foreign key is declared here and loaded
  WITH CHECK, so the engine trusts it (is_not_trusted = 0) - verified in 09.

  Sign convention: every amount keeps the LEDGER sign (debit +, credit -).
  Revenue is therefore negative, costs positive; the semantic model presents
  revenue and costs as positive numbers and profit as revenue less costs.

  Grain of every fact:
    FactGL           one general-ledger line (GLTxnID), in local currency and
                     translated to AUD
    FactBudget       month x entity x department x account
    FactForecast     month x entity x department x account (one version)
    FactFinancials   version (Actual/Budget/Forecast) x month x entity x
                     department x account - the plan-and-actual fact every P&L
                     visual reads. Actual rows are FactGL summed to the month.
    FactARInvoice    one customer invoice
    FactAPBill       one supplier bill
    FactCashBalance  one entity's closing cash on one day
=============================================================================*/
USE FinancePlanningBI;
GO

-------------------------------------------------------------------- config ---
CREATE TABLE dbo.ModelConfig (
    ConfigKey    NVARCHAR(60)  NOT NULL CONSTRAINT PK_ModelConfig PRIMARY KEY,
    ConfigValue  NVARCHAR(100) NOT NULL,
    Description  NVARCHAR(600) NOT NULL);

---------------------------------------------------------------- dimensions ---
CREATE TABLE dbo.DimDate (
    [Date]                  DATE         NOT NULL CONSTRAINT PK_DimDate PRIMARY KEY,
    [Year]                  SMALLINT     NOT NULL,
    MonthNo                 TINYINT      NOT NULL,
    MonthName               NVARCHAR(10) NOT NULL,
    MonthShort              NCHAR(3)     NOT NULL,
    [Quarter]               TINYINT      NOT NULL,
    QuarterLabel            NCHAR(7)     NOT NULL,   -- 2025 Q3
    YearMonth               INT          NOT NULL,   -- 202507, sort key
    YearMonthLabel          NCHAR(8)     NOT NULL,   -- Jul 2025
    MonthStart              DATE         NOT NULL,
    MonthEnd                DATE         NOT NULL,
    ISOWeek                 TINYINT      NOT NULL,
    DayName                 NVARCHAR(10) NOT NULL,
    DayOfWeekNo             TINYINT      NOT NULL,   -- 1 = Monday
    FinancialYearStart      SMALLINT     NOT NULL,
    FinancialYear           NCHAR(4)     NOT NULL,   -- FY26 = Jul 2025 - Jun 2026
    FinancialMonthNo        TINYINT      NOT NULL,   -- 1 = July
    FinancialQuarter        TINYINT      NOT NULL,   -- 1 = Jul-Sep
    FinancialQuarterLabel   NCHAR(7)     NOT NULL,   -- FY26 Q1
    FinancialQuarterSort    INT          NOT NULL,
    MonthOffset             INT          NOT NULL,   -- months from the as-of month (0 = Aug 2026)
    FinancialYearOffset     INT          NOT NULL,   -- financial years from the as-of year (0 = FY27)
    IsSourceCalendar        BIT          NOT NULL,   -- 1 where the supplied dim_date covers the day
    IsAfterAsOf             BIT          NOT NULL,   -- 1 for days after the as-of date: no actuals yet
    IsMonthComplete         BIT          NOT NULL,   -- 1 when the whole month lies on or before the as-of date
    IsFinancialYearComplete BIT          NOT NULL);

CREATE TABLE dbo.DimCurrency (
    CurrencyCode         NCHAR(3) NOT NULL CONSTRAINT PK_DimCurrency PRIMARY KEY,
    IsReportingCurrency  BIT      NOT NULL);

CREATE TABLE dbo.DimEntity (
    EntityID       NVARCHAR(10) NOT NULL CONSTRAINT PK_DimEntity PRIMARY KEY,
    EntityName     NVARCHAR(60) NOT NULL CONSTRAINT UQ_DimEntity_Name UNIQUE,
    Region         NVARCHAR(20) NOT NULL,
    LocalCurrency  NCHAR(3)     NOT NULL CONSTRAINT FK_DimEntity_Currency REFERENCES dbo.DimCurrency (CurrencyCode));

CREATE TABLE dbo.DimDepartment (
    DepartmentID    NVARCHAR(10) NOT NULL CONSTRAINT PK_DimDepartment PRIMARY KEY,
    DepartmentName  NVARCHAR(60) NOT NULL CONSTRAINT UQ_DimDepartment_Name UNIQUE);

CREATE TABLE dbo.DimAccount (
    AccountCode   NVARCHAR(10) NOT NULL CONSTRAINT PK_DimAccount PRIMARY KEY,
    AccountName   NVARCHAR(60) NOT NULL CONSTRAINT UQ_DimAccount_Name UNIQUE,
    AccountGroup  NVARCHAR(30) NOT NULL,
    [Statement]   NVARCHAR(20) NOT NULL CONSTRAINT CK_DimAccount_Statement CHECK ([Statement] IN (N'Income Statement', N'Balance Sheet')),
    GroupOrder    TINYINT      NOT NULL,
    NaturalSign   SMALLINT     NOT NULL CONSTRAINT CK_DimAccount_Sign CHECK (NaturalSign IN (-1, 1)),
    IsIncome      BIT          NOT NULL,
    IsOperating   BIT          NOT NULL,   -- revenue, COGS, operating expense: the budgeted scope
    IsBudgeted    BIT          NOT NULL,
    AccountLabel  NVARCHAR(80) NOT NULL);

CREATE TABLE dbo.DimCustomer (
    CustomerID    NVARCHAR(10) NOT NULL CONSTRAINT PK_DimCustomer PRIMARY KEY,
    CustomerName  NVARCHAR(60) NOT NULL,
    Industry      NVARCHAR(40) NOT NULL,
    Country       NVARCHAR(40) NOT NULL,
    Segment       NVARCHAR(20) NOT NULL);

CREATE TABLE dbo.DimVendor (
    VendorID        NVARCHAR(10) NOT NULL CONSTRAINT PK_DimVendor PRIMARY KEY,
    VendorName      NVARCHAR(60) NOT NULL,
    VendorCategory  NVARCHAR(40) NOT NULL,
    Country         NVARCHAR(40) NOT NULL);

CREATE TABLE dbo.DimVersion (
    VersionID    NVARCHAR(3)   NOT NULL CONSTRAINT PK_DimVersion PRIMARY KEY,
    VersionName  NVARCHAR(20)  NOT NULL,
    SortOrder    TINYINT       NOT NULL,
    Description  NVARCHAR(300) NOT NULL);

CREATE TABLE dbo.DimAgeingBucket (
    BucketOrder     TINYINT      NOT NULL CONSTRAINT PK_DimAgeingBucket PRIMARY KEY,
    BucketName      NVARCHAR(20) NOT NULL CONSTRAINT UQ_DimAgeingBucket_Name UNIQUE,
    MinDaysPastDue  INT          NOT NULL,
    MaxDaysPastDue  INT          NOT NULL,
    IsPastDue       BIT          NOT NULL,
    CONSTRAINT CK_DimAgeingBucket_Range CHECK (MaxDaysPastDue >= MinDaysPastDue));

CREATE TABLE dbo.DimScenario (
    ScenarioKey       TINYINT       NOT NULL CONSTRAINT PK_DimScenario PRIMARY KEY,
    ScenarioName      NVARCHAR(20)  NOT NULL CONSTRAINT UQ_DimScenario_Name UNIQUE,
    RevenueChangePct  DECIMAL(9,4)  NOT NULL,
    OpexChangePct     DECIMAL(9,4)  NOT NULL,
    AUDChangePct      DECIMAL(9,4)  NOT NULL,
    Description       NVARCHAR(400) NOT NULL);

-- The income-statement layout: account groups, subtotals and ratios in reporting
-- order. FavourableSign turns (actual - plan) into a favourable-positive variance.
CREATE TABLE dbo.DimPLLine (
    LineKey         TINYINT      NOT NULL CONSTRAINT PK_DimPLLine PRIMARY KEY,
    LineName        NVARCHAR(40) NOT NULL CONSTRAINT UQ_DimPLLine_Name UNIQUE,
    LineType        NVARCHAR(10) NOT NULL CONSTRAINT CK_DimPLLine_Type CHECK (LineType IN (N'Group', N'Subtotal', N'Ratio')),
    FavourableSign  SMALLINT     NOT NULL CONSTRAINT CK_DimPLLine_Sign CHECK (FavourableSign IN (-1, 1)),
    IsBudgeted      BIT          NOT NULL);

CREATE TABLE dbo.DimSensitivityStep (
    StepPct    DECIMAL(9,4) NOT NULL CONSTRAINT PK_DimSensitivityStep PRIMARY KEY,
    StepLabel  NVARCHAR(10) NOT NULL);

------------------------------------------------------------------------ FX ---
CREATE TABLE dbo.FxRateDaily (
    [Date]              DATE         NOT NULL CONSTRAINT FK_FxRateDaily_Date REFERENCES dbo.DimDate ([Date]),
    CurrencyCode        NCHAR(3)     NOT NULL CONSTRAINT FK_FxRateDaily_Currency REFERENCES dbo.DimCurrency (CurrencyCode),
    AUDPerUnitSupplied  DECIMAL(9,4) NOT NULL,
    AUDPerUnit          DECIMAL(9,4) NOT NULL CONSTRAINT CK_FxRateDaily_Positive CHECK (AUDPerUnit > 0),
    IsOverridden        BIT          NOT NULL,   -- 1 where AUD's supplied rate was not 1
    CONSTRAINT PK_FxRateDaily PRIMARY KEY ([Date], CurrencyCode));

CREATE TABLE dbo.FxRateMonthly (
    MonthStart           DATE          NOT NULL CONSTRAINT FK_FxRateMonthly_Date REFERENCES dbo.DimDate ([Date]),
    CurrencyCode         NCHAR(3)      NOT NULL CONSTRAINT FK_FxRateMonthly_Currency REFERENCES dbo.DimCurrency (CurrencyCode),
    AvgAUDPerUnit        DECIMAL(18,6) NOT NULL,   -- mean of the month's daily rates: the P&L translation rate
    ClosingAUDPerUnit    DECIMAL(9,4)  NOT NULL,   -- last day of the month
    MinAUDPerUnit        DECIMAL(9,4)  NOT NULL,
    MaxAUDPerUnit        DECIMAL(9,4)  NOT NULL,
    DaysInMonth          TINYINT       NOT NULL,
    MeanAbsDailyMovePct  DECIMAL(9,4)  NULL,
    CONSTRAINT PK_FxRateMonthly PRIMARY KEY (MonthStart, CurrencyCode),
    CONSTRAINT CK_FxRateMonthly_Day CHECK (DAY(MonthStart) = 1));

--------------------------------------------------------------------- facts ---
CREATE TABLE dbo.FactGL (
    GLTxnID            NVARCHAR(12)  NOT NULL CONSTRAINT PK_FactGL PRIMARY KEY,
    [Date]             DATE          NOT NULL CONSTRAINT FK_FactGL_Date REFERENCES dbo.DimDate ([Date]),
    MonthStart         DATE          NOT NULL,
    EntityID           NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactGL_Entity REFERENCES dbo.DimEntity (EntityID),
    DepartmentID       NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactGL_Department REFERENCES dbo.DimDepartment (DepartmentID),
    AccountCode        NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactGL_Account REFERENCES dbo.DimAccount (AccountCode),
    CurrencyCode       NCHAR(3)      NOT NULL CONSTRAINT FK_FactGL_Currency REFERENCES dbo.DimCurrency (CurrencyCode),
    AmountLocal        DECIMAL(19,2) NOT NULL,
    CustomerID         NVARCHAR(10)  NULL CONSTRAINT FK_FactGL_Customer REFERENCES dbo.DimCustomer (CustomerID),
    VendorID           NVARCHAR(10)  NULL CONSTRAINT FK_FactGL_Vendor REFERENCES dbo.DimVendor (VendorID),
    PostingStatus      NVARCHAR(10)  NOT NULL CONSTRAINT CK_FactGL_Status CHECK (PostingStatus IN (N'Posted', N'Accrued')),
    FxRateAvg          DECIMAL(18,6) NOT NULL,   -- monthly average: the translation rate
    AmountAUD          DECIMAL(19,2) NOT NULL,   -- ROUND(AmountLocal x FxRateAvg, 2)
    FxRateSpot         DECIMAL(9,4)  NOT NULL,   -- the day's rate, kept for audit
    AmountAUDSpot      DECIMAL(19,2) NOT NULL,
    FxRatePY           DECIMAL(18,6) NULL,       -- same month one year earlier: constant-currency basis
    AmountAUDAtPYRate  DECIMAL(19,2) NULL,
    CONSTRAINT CK_FactGL_Month CHECK (MonthStart = DATEFROMPARTS(YEAR([Date]), MONTH([Date]), 1)));

CREATE TABLE dbo.FactBudget (
    MonthStart    DATE          NOT NULL CONSTRAINT FK_FactBudget_Date REFERENCES dbo.DimDate ([Date]),
    EntityID      NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactBudget_Entity REFERENCES dbo.DimEntity (EntityID),
    DepartmentID  NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactBudget_Department REFERENCES dbo.DimDepartment (DepartmentID),
    AccountCode   NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactBudget_Account REFERENCES dbo.DimAccount (AccountCode),
    AmountAUD     DECIMAL(19,2) NOT NULL,
    CONSTRAINT PK_FactBudget PRIMARY KEY (MonthStart, EntityID, DepartmentID, AccountCode),
    CONSTRAINT CK_FactBudget_Day CHECK (DAY(MonthStart) = 1));

CREATE TABLE dbo.FactForecast (
    MonthStart     DATE          NOT NULL CONSTRAINT FK_FactForecast_Date REFERENCES dbo.DimDate ([Date]),
    EntityID       NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactForecast_Entity REFERENCES dbo.DimEntity (EntityID),
    DepartmentID   NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactForecast_Department REFERENCES dbo.DimDepartment (DepartmentID),
    AccountCode    NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactForecast_Account REFERENCES dbo.DimAccount (AccountCode),
    AmountAUD      DECIMAL(19,2) NOT NULL,
    ScenarioLabel  NVARCHAR(10)  NOT NULL CONSTRAINT CK_FactForecast_Label CHECK (ScenarioLabel IN (N'Base', N'Best', N'Worst')),
    CONSTRAINT PK_FactForecast PRIMARY KEY (MonthStart, EntityID, DepartmentID, AccountCode),
    CONSTRAINT CK_FactForecast_Day CHECK (DAY(MonthStart) = 1));

CREATE TABLE dbo.FactFinancials (
    VersionID          NVARCHAR(3)   NOT NULL CONSTRAINT FK_FactFinancials_Version REFERENCES dbo.DimVersion (VersionID),
    MonthStart         DATE          NOT NULL CONSTRAINT FK_FactFinancials_Date REFERENCES dbo.DimDate ([Date]),
    EntityID           NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactFinancials_Entity REFERENCES dbo.DimEntity (EntityID),
    DepartmentID       NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactFinancials_Department REFERENCES dbo.DimDepartment (DepartmentID),
    AccountCode        NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactFinancials_Account REFERENCES dbo.DimAccount (AccountCode),
    AmountAUD          DECIMAL(19,2) NOT NULL,
    AmountLocal        DECIMAL(19,2) NULL,       -- actuals only
    AmountAUDAtPYRate  DECIMAL(19,2) NULL,       -- actuals only, from FY23 onwards
    PostingLines       INT           NULL,       -- actuals only: GL lines summed into the row
    ScenarioLabel      NVARCHAR(10)  NULL,       -- forecast only: the source label, not a scenario
    CONSTRAINT PK_FactFinancials PRIMARY KEY (VersionID, MonthStart, EntityID, DepartmentID, AccountCode));

CREATE TABLE dbo.FactARInvoice (
    InvoiceID         NVARCHAR(12)  NOT NULL CONSTRAINT PK_FactARInvoice PRIMARY KEY,
    InvoiceDate       DATE          NOT NULL CONSTRAINT FK_FactAR_InvoiceDate REFERENCES dbo.DimDate ([Date]),
    DueDate           DATE          NOT NULL CONSTRAINT FK_FactAR_DueDate REFERENCES dbo.DimDate ([Date]),
    PaidDate          DATE          NULL     CONSTRAINT FK_FactAR_PaidDate REFERENCES dbo.DimDate ([Date]),
    CustomerID        NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAR_Customer REFERENCES dbo.DimCustomer (CustomerID),
    EntityID          NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAR_Entity REFERENCES dbo.DimEntity (EntityID),
    InvoiceAmountAUD  DECIMAL(19,2) NOT NULL CONSTRAINT CK_FactAR_Amount CHECK (InvoiceAmountAUD > 0),
    PaidAmountAUD     DECIMAL(19,2) NOT NULL,
    SourceStatus      NVARCHAR(10)  NOT NULL CONSTRAINT CK_FactAR_Status CHECK (SourceStatus IN (N'Open', N'Paid')),
    TermsDays         SMALLINT      NOT NULL,
    DaysToPay         INT           NULL,
    DaysLate          INT           NULL,
    IsPaidAfterAsOf   BIT           NOT NULL,
    IsOpenAsOf        BIT           NOT NULL,
    DaysPastDueAsOf   INT           NULL,
    AgeingBucketAsOf  TINYINT       NULL     CONSTRAINT FK_FactAR_Bucket REFERENCES dbo.DimAgeingBucket (BucketOrder),
    CONSTRAINT CK_FactAR_Due CHECK (DueDate >= InvoiceDate));

CREATE TABLE dbo.FactAPBill (
    BillID            NVARCHAR(12)  NOT NULL CONSTRAINT PK_FactAPBill PRIMARY KEY,
    BillDate          DATE          NOT NULL CONSTRAINT FK_FactAP_BillDate REFERENCES dbo.DimDate ([Date]),
    DueDate           DATE          NOT NULL CONSTRAINT FK_FactAP_DueDate REFERENCES dbo.DimDate ([Date]),
    PaidDate          DATE          NULL     CONSTRAINT FK_FactAP_PaidDate REFERENCES dbo.DimDate ([Date]),
    VendorID          NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAP_Vendor REFERENCES dbo.DimVendor (VendorID),
    EntityID          NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAP_Entity REFERENCES dbo.DimEntity (EntityID),
    BillAmountAUD     DECIMAL(19,2) NOT NULL CONSTRAINT CK_FactAP_Amount CHECK (BillAmountAUD > 0),
    PaidAmountAUD     DECIMAL(19,2) NOT NULL,
    SourceStatus      NVARCHAR(10)  NOT NULL CONSTRAINT CK_FactAP_Status CHECK (SourceStatus IN (N'Open', N'Paid')),
    TermsDays         SMALLINT      NOT NULL,
    DaysToPay         INT           NULL,
    DaysLate          INT           NULL,
    IsPaidAfterAsOf   BIT           NOT NULL,
    IsOpenAsOf        BIT           NOT NULL,
    DaysPastDueAsOf   INT           NULL,
    AgeingBucketAsOf  TINYINT       NULL     CONSTRAINT FK_FactAP_Bucket REFERENCES dbo.DimAgeingBucket (BucketOrder),
    CONSTRAINT CK_FactAP_Due CHECK (DueDate >= BillDate));

CREATE TABLE dbo.FactCashBalance (
    [Date]          DATE          NOT NULL CONSTRAINT FK_FactCash_Date REFERENCES dbo.DimDate ([Date]),
    EntityID        NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactCash_Entity REFERENCES dbo.DimEntity (EntityID),
    ClosingCashAUD  DECIMAL(19,2) NOT NULL,
    IsFloorValue    BIT           NOT NULL,   -- exactly 50,000.00: a generator floor, not a balance
    CONSTRAINT PK_FactCashBalance PRIMARY KEY ([Date], EntityID));

------------------------------------------------------------------ security ---
-- EntityID / DepartmentID hold a key or 'ALL' (no restriction), so they are
-- validated in 09 rather than by a foreign key.
CREATE TABLE dbo.SecurityUserAccess (
    UserEmail     NVARCHAR(120) NOT NULL CONSTRAINT PK_SecurityUserAccess PRIMARY KEY,
    [Role]        NVARCHAR(40)  NOT NULL,
    EntityID      NVARCHAR(10)  NOT NULL,
    DepartmentID  NVARCHAR(10)  NOT NULL);
GO
PRINT 'Core tables created.';
GO
