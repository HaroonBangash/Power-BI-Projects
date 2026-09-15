/*=============================================================================
  01_create_database.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Create the SupplyChainBI database, its three layer schemas, the
            central configuration table and the load audit table.

  Layers
  ------
    stg        Raw landing. Every column nvarchar; nothing is rejected here, so
               a malformed value can never block ingestion.
    dbo        Typed, keyed, constrained core. The trusted relational truth.
    analytics  Views. The ONLY objects Power BI is permitted to consume, so a
               source change can be absorbed by editing a view rather than
               rebuilding the semantic model.

  Idempotent: safe to re-run.
=============================================================================*/

SET NOCOUNT ON;
GO

/*-----------------------------------------------------------------------------
  1. Database
  ---------------------------------------------------------------------------
  Recovery model SIMPLE: this is a rebuildable analytical store fed by bulk
  loads. Point-in-time recovery has no value here, and SIMPLE stops the
  transaction log growing during the 315,000-row loads.
-----------------------------------------------------------------------------*/
IF DB_ID('SupplyChainBI') IS NULL
BEGIN
    CREATE DATABASE SupplyChainBI;
    PRINT 'Database SupplyChainBI created.';
END
ELSE
    PRINT 'Database SupplyChainBI already exists - skipped.';
GO

ALTER DATABASE SupplyChainBI SET RECOVERY SIMPLE;
GO

USE SupplyChainBI;
GO

/*-----------------------------------------------------------------------------
  2. Schemas
-----------------------------------------------------------------------------*/
IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg;');
IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics;');
GO

PRINT 'Schemas ready: stg, dbo, analytics.';
GO

/*-----------------------------------------------------------------------------
  3. dbo.ModelConfig
  ---------------------------------------------------------------------------
  Single source of truth for the constants that would otherwise be scattered
  across scripts, views and measures.

  The as-of date matters most. The dataset was extracted on 2026-08-31: it is
  the latest date on which any transaction was raised, and every 'Open' record
  in the source - and only those records - is scheduled beyond it. All
  'current' logic must anchor to this date.

  Using GETDATE() here would silently corrupt the solution. Today is already
  past the extract, so every in-flight order would be misread as overdue and
  OTIF would drift a little further from the truth every day the report is
  opened. A fixed anchor keeps results reproducible.
-----------------------------------------------------------------------------*/
IF OBJECT_ID('dbo.ModelConfig', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ModelConfig
    (
        ConfigKey    varchar(50)   NOT NULL,
        ConfigValue  nvarchar(100) NOT NULL,
        Description  nvarchar(400) NOT NULL,
        UpdatedAtUtc datetime2(0)  NOT NULL
            CONSTRAINT DF_ModelConfig_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_ModelConfig PRIMARY KEY CLUSTERED (ConfigKey)
    );
    PRINT 'Table dbo.ModelConfig created.';
END
GO

MERGE dbo.ModelConfig AS tgt
USING
(
    VALUES
        ('AsOfDate', '2026-08-31',
         N'Dataset extract date. Latest transaction date across all facts. Every Open record - and only Open records - is scheduled beyond it. Anchor for all current/overdue logic. Never substitute GETDATE().'),

        ('CalendarStartDate', '2022-01-01',
         N'First date in DimDate. Matches the earliest date in the supplied source calendar.'),

        ('CalendarEndDate', '2027-06-30',
         N'Last date in DimDate. Covers the furthest fact date (2026-10-07), the 13-week forecast horizon, and completes FY27 on a July-June financial year.'),

        ('ForecastHorizonWeeks', '13',
         N'Planned forward forecast horizon in weeks, used in Phase 14. One quarter of weekly buckets.'),

        ('FinancialYearStartMonth', '7',
         N'Financial year begins in July. July 2026 to June 2027 is FY27. Derived from the FinancialYear column in the supplied source calendar.'),

        ('DatasetProvenance', 'Synthetic',
         N'The dataset is synthetic and portfolio-safe. It must never be presented as real client data.')
) AS src (ConfigKey, ConfigValue, Description)
    ON tgt.ConfigKey = src.ConfigKey
WHEN MATCHED AND (tgt.ConfigValue <> src.ConfigValue OR tgt.Description <> src.Description)
    THEN UPDATE SET
        tgt.ConfigValue  = src.ConfigValue,
        tgt.Description  = src.Description,
        tgt.UpdatedAtUtc = SYSUTCDATETIME()
WHEN NOT MATCHED BY TARGET
    THEN INSERT (ConfigKey, ConfigValue, Description)
         VALUES (src.ConfigKey, src.ConfigValue, src.Description);
GO

/*-----------------------------------------------------------------------------
  4. stg.LoadLog
  ---------------------------------------------------------------------------
  Load-level lineage.

  Per-row lineage columns were considered and rejected: BULK INSERT cannot
  populate them without a format file per table (verified - it raises Msg 7301),
  and stamping the same file name onto 315,000 identical rows carries no
  information. Recording one row per load captures what actually matters -
  which file, how many rows, when, how long - and provides the evidence for the
  reconciliation report in 08_validation.sql.
-----------------------------------------------------------------------------*/
IF OBJECT_ID('stg.LoadLog', 'U') IS NULL
BEGIN
    CREATE TABLE stg.LoadLog
    (
        LoadID           int IDENTITY(1,1) NOT NULL,
        TargetTable      sysname       NOT NULL,
        SourceFile       nvarchar(260) NOT NULL,
        RowsLoaded       int           NULL,
        LoadStartedUtc   datetime2(3)  NOT NULL,
        LoadCompletedUtc datetime2(3)  NULL,
        DurationMs       AS DATEDIFF(millisecond, LoadStartedUtc, LoadCompletedUtc),
        LoadStatus       varchar(20)   NOT NULL,
        ErrorMessage     nvarchar(2000) NULL,
        CONSTRAINT PK_LoadLog PRIMARY KEY CLUSTERED (LoadID),
        CONSTRAINT CK_LoadLog_Status CHECK (LoadStatus IN ('RUNNING', 'SUCCESS', 'FAILED'))
    );
    PRINT 'Table stg.LoadLog created.';
END
GO

/*-----------------------------------------------------------------------------
  5. Confirmation
-----------------------------------------------------------------------------*/
SELECT
    DatabaseName  = DB_NAME(),
    RecoveryModel = CAST(DATABASEPROPERTYEX(DB_NAME(), 'Recovery') AS varchar(20)),
    Collation     = CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS varchar(50));

SELECT SchemaName = name
FROM   sys.schemas
WHERE  name IN ('stg', 'dbo', 'analytics')
ORDER BY name;

SELECT ConfigKey, ConfigValue
FROM   dbo.ModelConfig
ORDER BY ConfigKey;
GO
