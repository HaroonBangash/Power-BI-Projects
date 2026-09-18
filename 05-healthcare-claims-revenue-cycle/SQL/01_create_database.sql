/*=============================================================================
  01_create_database.sql

  Creates HealthcareRCMBI and the four schemas the build uses.

    stg        the CSVs exactly as they arrive - every column NVARCHAR, so a
               malformed value fails a CAST in 04/05 where it can be reported,
               not silently in BULK INSERT where it cannot.
    dim        conformed dimensions
    fact       facts, at their stated grain
    analytics  the only surface Power BI is allowed to touch

  Idempotent: safe to run against an existing database.
=============================================================================*/
SET NOCOUNT ON;
GO

IF DB_ID(N'HealthcareRCMBI') IS NULL
BEGIN
    PRINT 'creating database HealthcareRCMBI';
    EXEC (N'CREATE DATABASE HealthcareRCMBI');
END
ELSE
    PRINT 'database HealthcareRCMBI already exists';
GO

USE HealthcareRCMBI;
GO

-- Simple recovery: this is a rebuildable analytics database, not a system of
-- record. Full recovery would grow a log no one will ever back up.
IF (SELECT recovery_model_desc FROM sys.databases WHERE name = N'HealthcareRCMBI') <> N'SIMPLE'
    EXEC (N'ALTER DATABASE HealthcareRCMBI SET RECOVERY SIMPLE');
GO

-- Query Store on, so the statements Power Query sends during a refresh are recorded
-- without any tracing. Validation/check_query_folding.sql reads them to prove from the
-- SERVER side that the import folded to a native SELECT rather than being done in the
-- mashup engine afterwards.
--
-- QUERY_CAPTURE_MODE = ALL is the point of this, and it is set UNCONDITIONALLY. SQL
-- Server turns Query Store on by default in AUTO mode, which discards cheap and
-- infrequent queries - so the six-row dimension reads never appeared and only the nine
-- expensive fact queries did. That looks exactly like partial folding and is not.
-- Guarding this on actual_state_desc <> 'READ_WRITE' skipped it, because the store was
-- already on.
ALTER DATABASE HealthcareRCMBI SET QUERY_STORE = ON
    (OPERATION_MODE = READ_WRITE, QUERY_CAPTURE_MODE = ALL, MAX_STORAGE_SIZE_MB = 256,
     DATA_FLUSH_INTERVAL_SECONDS = 60);
GO

-- A fresh proof needs a fresh record: the previous refresh's statements are cleared so
-- the check can never pass on a stale capture.
ALTER DATABASE HealthcareRCMBI SET QUERY_STORE CLEAR;
GO

USE HealthcareRCMBI;
GO

IF SCHEMA_ID(N'stg')       IS NULL EXEC (N'CREATE SCHEMA stg');
IF SCHEMA_ID(N'dim')       IS NULL EXEC (N'CREATE SCHEMA dim');
IF SCHEMA_ID(N'fact')      IS NULL EXEC (N'CREATE SCHEMA fact');
IF SCHEMA_ID(N'analytics') IS NULL EXEC (N'CREATE SCHEMA analytics');
GO

PRINT 'schemas ready: stg, dim, fact, analytics';
GO
