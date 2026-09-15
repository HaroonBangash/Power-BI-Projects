/*=============================================================================
  02_create_staging_tables.sql

  One text landing table per source CSV, columns in file order and named as in
  the file header. Nothing is typed here: dbo does that.
=============================================================================*/
USE FinancePlanningBI;
GO

CREATE TABLE stg.LoadLog (
    LoadLogID     INT IDENTITY(1,1) PRIMARY KEY,
    SourceFile    NVARCHAR(200) NOT NULL,
    TargetTable   NVARCHAR(200) NOT NULL,
    RowsLoaded    INT           NOT NULL,
    ExpectedRows  INT           NOT NULL,
    DurationMs    INT           NOT NULL,
    LoadedAt      DATETIME2(0)  NOT NULL DEFAULT SYSDATETIME());

CREATE TABLE stg.dim_account (AccountCode NVARCHAR(20), AccountName NVARCHAR(100), AccountGroup NVARCHAR(50));
CREATE TABLE stg.dim_customer (CustomerID NVARCHAR(20), CustomerName NVARCHAR(100), Industry NVARCHAR(60),
                               Country NVARCHAR(60), Segment NVARCHAR(40));
CREATE TABLE stg.dim_date ([Date] NVARCHAR(20), [Year] NVARCHAR(10), MonthNo NVARCHAR(10), MonthName NVARCHAR(20),
                           [Quarter] NVARCHAR(10), ISOWeek NVARCHAR(10), DayName NVARCHAR(20),
                           FinancialYearStart NVARCHAR(10), FinancialYear NVARCHAR(10));
CREATE TABLE stg.dim_department (DepartmentID NVARCHAR(20), DepartmentName NVARCHAR(100));
CREATE TABLE stg.dim_entity (EntityID NVARCHAR(20), EntityName NVARCHAR(100), Region NVARCHAR(40), LocalCurrency NVARCHAR(10));
CREATE TABLE stg.dim_vendor (VendorID NVARCHAR(20), VendorName NVARCHAR(100), VendorCategory NVARCHAR(60), Country NVARCHAR(60));
CREATE TABLE stg.fact_ap (BillID NVARCHAR(20), BillDate NVARCHAR(20), DueDate NVARCHAR(20), PaidDate NVARCHAR(20),
                          VendorID NVARCHAR(20), EntityID NVARCHAR(20), BillAmountAUD NVARCHAR(40),
                          PaidAmountAUD NVARCHAR(40), [Status] NVARCHAR(20));
CREATE TABLE stg.fact_ar (InvoiceID NVARCHAR(20), InvoiceDate NVARCHAR(20), DueDate NVARCHAR(20), PaidDate NVARCHAR(20),
                          CustomerID NVARCHAR(20), EntityID NVARCHAR(20), InvoiceAmountAUD NVARCHAR(40),
                          PaidAmountAUD NVARCHAR(40), [Status] NVARCHAR(20));
CREATE TABLE stg.fact_budget ([Month] NVARCHAR(20), EntityID NVARCHAR(20), DepartmentID NVARCHAR(20),
                              AccountCode NVARCHAR(20), BudgetAmountAUD NVARCHAR(40));
CREATE TABLE stg.fact_cash_balance ([Date] NVARCHAR(20), EntityID NVARCHAR(20), ClosingCashAUD NVARCHAR(40));
CREATE TABLE stg.fact_forecast ([Month] NVARCHAR(20), EntityID NVARCHAR(20), DepartmentID NVARCHAR(20),
                                AccountCode NVARCHAR(20), ForecastAmountAUD NVARCHAR(40), Scenario NVARCHAR(20));
CREATE TABLE stg.fact_fx_rates ([Date] NVARCHAR(20), Currency NVARCHAR(10), AUDPerUnit NVARCHAR(40));
CREATE TABLE stg.fact_gl (GLTxnID NVARCHAR(20), [Date] NVARCHAR(20), EntityID NVARCHAR(20), DepartmentID NVARCHAR(20),
                          AccountCode NVARCHAR(20), Currency NVARCHAR(10), AmountLocal NVARCHAR(40),
                          CustomerID NVARCHAR(20), VendorID NVARCHAR(20), PostingStatus NVARCHAR(20));
CREATE TABLE stg.security_user_access (UserEmail NVARCHAR(200), [Role] NVARCHAR(60), EntityID NVARCHAR(20),
                                       DepartmentID NVARCHAR(20));
GO
PRINT 'Staging tables created (14 files + load log).';
GO
