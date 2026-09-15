/*=============================================================================
  03_load_staging.sql

  Native BULK INSERT of the fourteen source CSVs into stg.

  File format, measured in Phase 1 before writing this script:
    ASCII, CRLF row terminator (CR count = LF count in every file), comma
    separated, no quoted fields, no BOM, header on line 1. FORMAT='CSV' is kept
    so a future file with quoted fields still parses correctly.

  PATH IS NOT HARD-CODED. The data folder arrives as the sqlcmd variable
  $(DataRoot), supplied by SQL/run_all.ps1 from the repository location, so no
  machine-specific path is committed. BULK INSERT resolves paths on the SERVER:
  the SQL Server service account must be able to read that folder.

  Every load is checked against the row count published with the dataset
  (row_counts.json) and fails loudly on any mismatch. Idempotent.
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

DECLARE @SourceRoot NVARCHAR(400) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

DECLARE @Files TABLE (Ord INT, SourceFile NVARCHAR(200), TargetTable NVARCHAR(200), ExpectedRows INT);
INSERT @Files VALUES
 ( 1, N'dim_account.csv',            N'stg.dim_account',              26),
 ( 2, N'dim_customer.csv',           N'stg.dim_customer',           1500),
 ( 3, N'dim_date.csv',               N'stg.dim_date',               1704),
 ( 4, N'dim_department.csv',         N'stg.dim_department',           10),
 ( 5, N'dim_entity.csv',             N'stg.dim_entity',                6),
 ( 6, N'dim_vendor.csv',             N'stg.dim_vendor',              500),
 ( 7, N'fact_ap.csv',                N'stg.fact_ap',               12000),
 ( 8, N'fact_ar.csv',                N'stg.fact_ar',               18000),
 ( 9, N'fact_budget.csv',            N'stg.fact_budget',           60480),
 (10, N'fact_cash_balance.csv',      N'stg.fact_cash_balance',     10224),
 (11, N'fact_forecast.csv',          N'stg.fact_forecast',         60480),
 (12, N'fact_fx_rates.csv',          N'stg.fact_fx_rates',         10224),
 (13, N'fact_gl.csv',                N'stg.fact_gl',               80000),
 (14, N'security_user_access.csv',   N'stg.security_user_access',     18);

TRUNCATE TABLE stg.LoadLog;

DECLARE @Ord INT = 1, @File NVARCHAR(200), @Target NVARCHAR(200), @Expected INT,
        @Sql NVARCHAR(MAX), @Rows INT, @T0 DATETIME2(3);

WHILE @Ord <= 14
BEGIN
    SELECT @File = SourceFile, @Target = TargetTable, @Expected = ExpectedRows
    FROM @Files WHERE Ord = @Ord;

    SET @T0 = SYSDATETIME();
    SET @Sql = N'TRUNCATE TABLE ' + @Target + N';';
    EXEC sys.sp_executesql @Sql;

    -- BULK INSERT will not take a variable for the path, so the statement is
    -- composed. QUOTENAME with a single-quote delimiter escapes apostrophes.
    SET @Sql = N'BULK INSERT ' + @Target + N'
        FROM ' + QUOTENAME(@SourceRoot + @File, '''') + N'
        WITH (FORMAT = ''CSV'', FIRSTROW = 2, FIELDTERMINATOR = '','',
              ROWTERMINATOR = ''0x0d0a'', TABLOCK, MAXERRORS = 0);';
    EXEC sys.sp_executesql @Sql;

    -- Count what actually landed rather than trusting @@ROWCOUNT through dynamic SQL.
    SET @Sql = N'SELECT @n = COUNT(*) FROM ' + @Target + N';';
    EXEC sys.sp_executesql @Sql, N'@n INT OUTPUT', @n = @Rows OUTPUT;

    INSERT stg.LoadLog (SourceFile, TargetTable, RowsLoaded, ExpectedRows, DurationMs)
    VALUES (@File, @Target, @Rows, @Expected, DATEDIFF(MILLISECOND, @T0, SYSDATETIME()));

    IF @Rows <> @Expected
        THROW 50001, N'Row count mismatch on staging load - see stg.LoadLog.', 1;

    SET @Ord += 1;
END

SELECT SourceFile, TargetTable, RowsLoaded, ExpectedRows, DurationMs
FROM stg.LoadLog ORDER BY LoadLogID;
PRINT 'Staging load complete: all 14 files match published row counts.';
GO
