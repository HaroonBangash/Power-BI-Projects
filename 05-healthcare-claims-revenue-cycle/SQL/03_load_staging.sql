/*=============================================================================
  03_load_staging.sql

  Native BULK INSERT of the ten source CSVs into stg.

  File format, measured in Phase 1 before this script was written:
    ASCII, CRLF row terminator (CR count = LF count in every file), comma
    separated, NO quoted fields anywhere, no BOM, header on line 1.
    FORMAT='CSV' is kept so a future file with quoted fields still parses.

  PATH IS NOT HARD-CODED. The data folder arrives as the sqlcmd variable
  $(DataRoot), supplied by SQL/run_all.ps1 from the repository location, so no
  machine-specific path is committed. BULK INSERT resolves paths on the SERVER:
  the SQL Server service account must be able to read that folder.

  Every load is checked against the row count measured in the audit and fails
  loudly on any mismatch, so a truncated or doubled file can never reach dim/fact.
  Idempotent.
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

DECLARE @SourceRoot NVARCHAR(400) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

DECLARE @Files TABLE (Ord INT, SourceFile NVARCHAR(200), TargetTable NVARCHAR(200), ExpectedRows INT);
INSERT @Files VALUES
 ( 1, N'dim_beneficiary.csv',      N'stg.dim_beneficiary',       30000),
 ( 2, N'dim_date.csv',             N'stg.dim_date',               1704),
 ( 3, N'dim_facility.csv',         N'stg.dim_facility',             30),
 ( 4, N'dim_payer.csv',            N'stg.dim_payer',                 6),
 ( 5, N'dim_provider.csv',         N'stg.dim_provider',            500),
 ( 6, N'fact_claims.csv',          N'stg.fact_claims',          100000),
 ( 7, N'fact_claim_lines.csv',     N'stg.fact_claim_lines',     249905),
 ( 8, N'fact_payments.csv',        N'stg.fact_payments',         69111),
 ( 9, N'fact_denials.csv',         N'stg.fact_denials',           7824),
 (10, N'security_user_access.csv', N'stg.security_user_access',     82);

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
                       ROWTERMINATOR = ''0x0d0a'', CODEPAGE = ''raw'', TABLOCK);';
    EXEC sp_executesql @Sql;

    SET @Sql = N'SELECT @n = COUNT(*) FROM ' + @Table + N';';
    EXEC sp_executesql @Sql, N'@n INT OUTPUT', @n = @Actual OUTPUT;

    IF @Actual <> @Expected
    BEGIN
        DECLARE @msg NVARCHAR(400) = CONCAT(
            N'ROW COUNT MISMATCH loading ', @File, N' into ', @Table,
            N': expected ', @Expected, N', loaded ', @Actual,
            N'. The source file is not the one this build was written against.');
        THROW 51000, @msg, 1;
    END

    PRINT CONCAT(N'  ', @Table, N' <- ', @File, N'  ', @Actual, N' rows');
    SET @Ord += 1;
END
GO

PRINT '10 files loaded, every row count as measured in Phase 1';
GO
