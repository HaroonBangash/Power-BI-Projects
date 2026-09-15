/*=============================================================================
  03_load_data.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Bulk-load all ten source CSVs into the stg schema and record one
            audit row per load in stg.LoadLog.

  Load method
  -----------
  Native BULK INSERT. Chosen over an external Python loader because it is
  server-side, needs no runtime outside SQL Server, and keeps ingestion inside
  the SQL scripts where a reviewer expects to find it. Verified working against
  this repository path under the service account NT Service\MSSQL$SQLEXPRESS.

  File format (verified in Phase 3 inspection)
  --------------------------------------------
    Encoding        ASCII
    Row terminator  CRLF (0x0d0a)
    Field separator comma
    Quoted fields   none present in any file
    Ragged rows     none; every file is perfectly rectangular
  FORMAT='CSV' is still specified so that a future file containing quoted
  fields is parsed correctly rather than silently split.

  PREREQUISITE
  ------------
  BULK INSERT resolves paths on the SERVER, not the client. The SQL Server
  service account must be able to read @SourceRoot. If this database is ever
  rebuilt on another machine, @SourceRoot below is the only line to change.

  Idempotent: every target is truncated before loading, so re-running produces
  the same result rather than duplicating rows.
=============================================================================*/

USE SupplyChainBI;
GO
SET NOCOUNT ON;
GO

/*-----------------------------------------------------------------------------
  Configuration - the single machine-specific value in the whole SQL layer
-----------------------------------------------------------------------------*/
-- Passed in by sqlcmd:  sqlcmd ... -v DataRoot="<clone>\Data\Raw"
-- BULK INSERT resolves paths on the SERVER, so this must be a directory the SQL
-- Server service account can read. No machine-specific path is committed.
DECLARE @SourceRoot nvarchar(260) = N'$(DataRoot)';
IF RIGHT(@SourceRoot, 1) <> N'\' SET @SourceRoot += N'\';

/*-----------------------------------------------------------------------------
  Load manifest: target table <- source file
-----------------------------------------------------------------------------*/
DECLARE @Manifest TABLE
(
    Seq         int IDENTITY(1,1) PRIMARY KEY,
    TargetTable sysname       NOT NULL,
    SourceFile  nvarchar(260) NOT NULL
);

INSERT INTO @Manifest (TargetTable, SourceFile)
VALUES
    -- Dimensions first. Order is not required by staging (no constraints exist
    -- here), but it mirrors the dependency order used later in dbo.
    ('stg.DimDate',               'dim_date.csv'),
    ('stg.DimProduct',            'dim_product.csv'),
    ('stg.DimSupplier',           'dim_supplier.csv'),
    ('stg.DimWarehouse',          'dim_warehouse.csv'),
    ('stg.FactSalesOrders',       'fact_sales_orders.csv'),
    ('stg.FactPurchaseOrders',    'fact_purchase_orders.csv'),
    ('stg.FactShipments',         'fact_shipments.csv'),
    ('stg.FactWeeklyDemand',      'fact_weekly_demand.csv'),
    ('stg.FactInventorySnapshot', 'fact_inventory_snapshot.csv'),
    ('stg.SecurityUserAccess',    'security_user_access.csv');

/*-----------------------------------------------------------------------------
  Load loop
-----------------------------------------------------------------------------*/
DECLARE @Seq         int = 1,
        @MaxSeq      int,
        @TargetTable sysname,
        @SourceFile  nvarchar(260),
        @FullPath    nvarchar(520),
        @Sql         nvarchar(max),
        @LoadID      int,
        @Rows        int,
        @StartedUtc  datetime2(3);

SELECT @MaxSeq = MAX(Seq) FROM @Manifest;

WHILE @Seq <= @MaxSeq
BEGIN
    SELECT @TargetTable = TargetTable,
           @SourceFile  = SourceFile
    FROM   @Manifest
    WHERE  Seq = @Seq;

    SET @FullPath   = @SourceRoot + @SourceFile;
    SET @StartedUtc = SYSUTCDATETIME();

    INSERT INTO stg.LoadLog (TargetTable, SourceFile, LoadStartedUtc, LoadStatus)
    VALUES (@TargetTable, @SourceFile, @StartedUtc, 'RUNNING');

    SET @LoadID = SCOPE_IDENTITY();

    BEGIN TRY
        -- Truncate for idempotency. The table name comes from the fixed
        -- manifest above, never from user input, so dynamic SQL is safe here.
        SET @Sql = N'TRUNCATE TABLE ' + @TargetTable + N';';
        EXEC sys.sp_executesql @Sql;

        -- BULK INSERT will not accept a variable for the file path, so the
        -- statement is composed. QUOTENAME with a single-quote delimiter
        -- escapes any apostrophe in the path.
        SET @Sql =
            N'BULK INSERT ' + @TargetTable + N'
              FROM ' + QUOTENAME(@FullPath, '''') + N'
              WITH (
                  FORMAT          = ''CSV'',
                  FIRSTROW        = 2,
                  FIELDTERMINATOR = '','',
                  ROWTERMINATOR   = ''0x0d0a'',
                  TABLOCK,
                  MAXERRORS       = 0
              );';
        EXEC sys.sp_executesql @Sql;

        -- Count what actually landed, rather than trusting @@ROWCOUNT through
        -- a nested dynamic batch.
        SET @Sql = N'SELECT @cnt = COUNT(*) FROM ' + @TargetTable + N';';
        EXEC sys.sp_executesql @Sql, N'@cnt int OUTPUT', @cnt = @Rows OUTPUT;

        UPDATE stg.LoadLog
        SET    RowsLoaded       = @Rows,
               LoadCompletedUtc = SYSUTCDATETIME(),
               LoadStatus       = 'SUCCESS'
        WHERE  LoadID = @LoadID;

        PRINT CONCAT('Loaded ', @TargetTable, ' <- ', @SourceFile,
                     '  (', @Rows, ' rows)');
    END TRY
    BEGIN CATCH
        UPDATE stg.LoadLog
        SET    LoadCompletedUtc = SYSUTCDATETIME(),
               LoadStatus       = 'FAILED',
               ErrorMessage     = ERROR_MESSAGE()
        WHERE  LoadID = @LoadID;

        PRINT CONCAT('FAILED  ', @TargetTable, ' <- ', @SourceFile,
                     '  : ', ERROR_MESSAGE());
    END CATCH

    SET @Seq += 1;
END
GO

/*-----------------------------------------------------------------------------
  Load report - this run only
-----------------------------------------------------------------------------*/
SELECT
    TargetTable,
    SourceFile,
    RowsLoaded,
    DurationMs,
    LoadStatus,
    ErrorMessage
FROM   stg.LoadLog
WHERE  LoadID > COALESCE(
           (SELECT MAX(LoadID) - 10 FROM stg.LoadLog), 0)
ORDER BY LoadID;

SELECT
    TablesLoaded = COUNT(*),
    Succeeded    = SUM(CASE WHEN LoadStatus = 'SUCCESS' THEN 1 ELSE 0 END),
    Failed       = SUM(CASE WHEN LoadStatus = 'FAILED'  THEN 1 ELSE 0 END),
    TotalRows    = SUM(RowsLoaded),
    TotalMs      = SUM(DurationMs)
FROM   stg.LoadLog
WHERE  LoadID > COALESCE((SELECT MAX(LoadID) - 10 FROM stg.LoadLog), 0);
GO
