/*=============================================================================
  03_load_staging.sql

  Native BULK INSERT of the nine source CSVs into stg.

  File format, measured in Phase 1 before this script was written:
    ASCII, CRLF row terminator (CR count = LF count in every file), comma
    separated, NO quoted fields anywhere, no BOM, header on line 1.
    FORMAT='CSV' is kept so a future file with quoted fields still parses.

  PATH IS NOT HARD-CODED. The data folder arrives as the sqlcmd variable
  $(DataRoot), supplied by SQL/run_all.ps1 from the repository location, so no
  machine-specific path is committed. BULK INSERT resolves paths on the SERVER:
  the SQL Server service account must be able to read that folder.

  Every load is checked against the row count measured in the audit and fails
  loudly on any mismatch, so a truncated or doubled file can never reach dbo.
  Idempotent.
=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @SourceRoot NVARCHAR(400) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

DECLARE @Files TABLE (Ord INT, SourceFile NVARCHAR(200), TargetTable NVARCHAR(200), ExpectedRows INT);
INSERT @Files VALUES
 (1, N'dim_customer.csv',               N'stg.dim_customer',                 12000),
 (2, N'dim_plan.csv',                   N'stg.dim_plan',                         4),
 (3, N'dim_date.csv',                   N'stg.dim_date',                      1704),
 (4, N'fact_subscriptions.csv',         N'stg.fact_subscriptions',           12000),
 (5, N'fact_invoices.csv',              N'stg.fact_invoices',               177236),
 (6, N'fact_product_usage_monthly.csv', N'stg.fact_product_usage_monthly',  113038),
 (7, N'fact_support_tickets.csv',       N'stg.fact_support_tickets',         45000),
 (8, N'fact_customer_acquisition.csv',  N'stg.fact_customer_acquisition',    12000),
 (9, N'security_user_access.csv',       N'stg.security_user_access',             8);

DECLARE @Ord INT = 1, @Max INT = (SELECT MAX(Ord) FROM @Files);
DECLARE @File NVARCHAR(200), @Table NVARCHAR(200), @Expected INT, @Actual INT, @Sql NVARCHAR(MAX);

WHILE @Ord <= @Max
BEGIN
    SELECT @File = SourceFile, @Table = TargetTable, @Expected = ExpectedRows
    FROM @Files WHERE Ord = @Ord;

    SET @Sql = N'TRUNCATE TABLE ' + @Table + N';
        BULK INSERT ' + @Table + N'
        FROM ''' + @SourceRoot + @File + N'''
        WITH (FORMAT = ''CSV'', FIRSTROW = 2, FIELDTERMINATOR = '','',
              ROWTERMINATOR = ''0x0d0a'', TABLOCK, CODEPAGE = ''raw'');';
    EXEC sp_executesql @Sql;

    SET @Sql = N'SELECT @n = COUNT(*) FROM ' + @Table + N';';
    EXEC sp_executesql @Sql, N'@n INT OUTPUT', @n = @Actual OUTPUT;

    IF @Actual <> @Expected
        THROW 51001, N'Row count mismatch after BULK INSERT - the source file is not the audited file.', 1;

    PRINT CONCAT(N'  ', @Table, N' <- ', @File, N'  ', FORMAT(@Actual, N'N0'), N' rows');
    SET @Ord += 1;
END
GO
PRINT 'Staging loaded (9 files, row counts verified).';
GO
