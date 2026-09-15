/*=============================================================================
  10_scale_test.sql   (OPTIONAL - not part of run_all.ps1, which runs 0*.sql)

  The volume test the dataset invites: what happens to this design when the
  ledger is an enterprise-sized one rather than an 80,000-line starter.

  It loads a generated million-line ledger (Python/scale_ledger.py) into
  dbo.FactGL_Scaled and then times the SAME question - operating expense by
  department and month - against:

      the line-level ledger at 1,000,000 lines   (what a transaction model scans)
      dbo.FactFinancials at 168,782 rows         (what this model's P&L reads)

  The point is not that one query is faster today; at 80,000 lines they are the
  same. The point is what each one does NEXT year: FactFinancials grows by one
  row per month per entity, department and account, whatever the ledger does.

  Run:  python Python\scale_ledger.py --rows 1000000
        powershell -Command "$env:DataRoot='<repo>\Data\Scaled'; sqlcmd -S localhost\SQLEXPRESS -C -b -i SQL\10_scale_test.sql"
  (SQL\run_all.ps1 sets DataRoot for the real load; this script reads the scaled folder.)
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

DECLARE @SourceRoot NVARCHAR(400) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

DROP TABLE IF EXISTS stg.fact_gl_scaled;
CREATE TABLE stg.fact_gl_scaled (GLTxnID NVARCHAR(20), [Date] NVARCHAR(20), EntityID NVARCHAR(20),
                                 DepartmentID NVARCHAR(20), AccountCode NVARCHAR(20), Currency NVARCHAR(10),
                                 AmountLocal NVARCHAR(40), CustomerID NVARCHAR(20), VendorID NVARCHAR(20),
                                 PostingStatus NVARCHAR(20));

DECLARE @Sql NVARCHAR(MAX) = N'BULK INSERT stg.fact_gl_scaled
    FROM ' + QUOTENAME(@SourceRoot + N'fact_gl_1000k.csv', '''') + N'
    WITH (FORMAT = ''CSV'', FIRSTROW = 2, FIELDTERMINATOR = '','',
          ROWTERMINATOR = ''0x0d0a'', TABLOCK, MAXERRORS = 0);';
EXEC sys.sp_executesql @Sql;

DROP TABLE IF EXISTS dbo.FactGL_Scaled;
CREATE TABLE dbo.FactGL_Scaled (
    GLTxnID       NVARCHAR(12)  NOT NULL,
    [Date]        DATE          NOT NULL,
    MonthStart    DATE          NOT NULL,
    EntityID      NVARCHAR(10)  NOT NULL,
    DepartmentID  NVARCHAR(10)  NOT NULL,
    AccountCode   NVARCHAR(10)  NOT NULL,
    CurrencyCode  NCHAR(3)      NOT NULL,
    AmountLocal   DECIMAL(19,2) NOT NULL,
    AmountAUD     DECIMAL(19,2) NOT NULL);

INSERT dbo.FactGL_Scaled (GLTxnID, [Date], MonthStart, EntityID, DepartmentID, AccountCode, CurrencyCode,
                          AmountLocal, AmountAUD)
SELECT s.GLTxnID, v.d, v.ms, s.EntityID, s.DepartmentID, s.AccountCode, s.Currency, v.a,
       ROUND(v.a * m.AvgAUDPerUnit, 2)
FROM stg.fact_gl_scaled s
CROSS APPLY (SELECT CONVERT(DATE, s.[Date], 23) AS d,
                    DATEFROMPARTS(YEAR(CONVERT(DATE, s.[Date], 23)), MONTH(CONVERT(DATE, s.[Date], 23)), 1) AS ms,
                    CONVERT(DECIMAL(19,2), s.AmountLocal) AS a) v
JOIN dbo.FxRateMonthly m ON m.MonthStart = v.ms AND m.CurrencyCode = s.Currency;

CREATE CLUSTERED INDEX IX_FactGL_Scaled ON dbo.FactGL_Scaled (MonthStart, DepartmentID, AccountCode);

DECLARE @scaled INT = (SELECT COUNT(*) FROM dbo.FactGL_Scaled);
DECLARE @monthly INT = (SELECT COUNT(*) FROM dbo.FactFinancials);
DECLARE @t0 DATETIME2(3), @lineMs INT, @monthlyMs INT;
DECLARE @sink DECIMAL(38,2);

-- the same question, both ways (twice each: the first run warms the cache)
SELECT @sink = SUM(g.AmountAUD) FROM dbo.FactGL_Scaled g
JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode
WHERE a.AccountGroup = N'Operating Expense' GROUP BY g.DepartmentID, g.MonthStart;
SET @t0 = SYSDATETIME();
SELECT @sink = SUM(g.AmountAUD) FROM dbo.FactGL_Scaled g
JOIN dbo.DimAccount a ON a.AccountCode = g.AccountCode
WHERE a.AccountGroup = N'Operating Expense' GROUP BY g.DepartmentID, g.MonthStart;
SET @lineMs = DATEDIFF(MILLISECOND, @t0, SYSDATETIME());

SELECT @sink = SUM(f.AmountAUD) FROM dbo.FactFinancials f
JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
WHERE f.VersionID = N'ACT' AND a.AccountGroup = N'Operating Expense' GROUP BY f.DepartmentID, f.MonthStart;
SET @t0 = SYSDATETIME();
SELECT @sink = SUM(f.AmountAUD) FROM dbo.FactFinancials f
JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
WHERE f.VersionID = N'ACT' AND a.AccountGroup = N'Operating Expense' GROUP BY f.DepartmentID, f.MonthStart;
SET @monthlyMs = DATEDIFF(MILLISECOND, @t0, SYSDATETIME());

SELECT ScaledLedgerLines = @scaled,
       MonthlyFactRows = @monthly,
       LineLevelQueryMs = @lineMs,
       MonthlyFactQueryMs = @monthlyMs,
       RowsScannedRatio = CAST(@scaled AS DECIMAL(18,2)) / NULLIF(@monthly, 0);

PRINT CONCAT(N'Scale test: the ledger grew to ', FORMAT(@scaled, N'N0'), N' lines; the monthly fact is still ',
             FORMAT(@monthly, N'N0'), N' rows. Same question: ', @lineMs, N' ms line-level vs ', @monthlyMs,
             N' ms on the monthly fact.');
GO
