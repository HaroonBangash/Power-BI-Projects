/*=============================================================================
  03_load_staging.sql

  Native BULK INSERT of the ten source CSVs into stg.

  File format, measured in Phase 1 before writing this script:
    ASCII, CRLF row terminator, comma separated, no quoted fields, no BOM,
    no ragged rows, header on line 1. FORMAT='CSV' is kept anyway so a future
    file with quoted fields still parses correctly.

  PATH IS NOT HARD-CODED. The data folder arrives as the sqlcmd variable
  $(DataRoot), supplied by SQL/run_all.ps1 from the repository location, so no
  machine-specific path is committed. BULK INSERT resolves paths on the SERVER:
  the SQL Server service account must be able to read that folder.

  Every load is checked against the row count published with the dataset
  (row_counts.json) and fails loudly on any mismatch. Idempotent: targets are
  truncated first, so re-running never duplicates rows.
=============================================================================*/
USE MarketingAttributionBI;
GO
SET NOCOUNT ON;
GO

DECLARE @SourceRoot NVARCHAR(400) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

DECLARE @Files TABLE (Ord INT, SourceFile NVARCHAR(200), TargetTable NVARCHAR(200), ExpectedRows INT);
INSERT @Files VALUES
 ( 1, N'dim_channel.csv',            N'stg.dim_channel',               7),
 ( 2, N'dim_campaign.csv',           N'stg.dim_campaign',            300),
 ( 3, N'campaign_name_mapping.csv',  N'stg.campaign_name_mapping',   900),
 ( 4, N'dim_date.csv',               N'stg.dim_date',               1704),
 ( 5, N'fact_ad_spend.csv',          N'stg.fact_ad_spend',         80000),
 ( 6, N'fact_leads.csv',             N'stg.fact_leads',            50000),
 ( 7, N'fact_touchpoints.csv',       N'stg.fact_touchpoints',     174938),
 ( 8, N'fact_opportunities.csv',     N'stg.fact_opportunities',    11152),
 ( 9, N'fact_revenue.csv',           N'stg.fact_revenue',           6559),
 (10, N'security_user_access.csv',   N'stg.security_user_access',      7);

TRUNCATE TABLE stg.LoadLog;

DECLARE @Ord INT = 1, @File NVARCHAR(200), @Target NVARCHAR(200), @Expected INT,
        @Sql NVARCHAR(MAX), @Rows INT, @T0 DATETIME2(3);

WHILE @Ord <= 10
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
PRINT 'Staging load complete: all 10 files match published row counts.';
GO
