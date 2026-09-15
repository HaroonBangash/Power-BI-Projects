/*=============================================================================
  01_create_database.sql
  Enterprise FP&A Finance - SQL data platform

  Creates FinancePlanningBI with three schemas:
    stg        text landing. Every column NVARCHAR so a malformed value can
               never abort a load; typing happens in dbo, where a bad value
               fails loudly instead of being silently truncated.
    dbo        typed, constrained star schema. Primary and foreign keys are
               declared and engine-trusted.
    analytics  views. The ONLY objects Power BI reads. Reshaping a dbo table
               never breaks the report while the views hold.

  Idempotent: drops and recreates the database.
  The dataset is synthetic and must never be presented as real company data.
=============================================================================*/
USE master;
GO
IF DB_ID(N'FinancePlanningBI') IS NOT NULL
BEGIN
    ALTER DATABASE FinancePlanningBI SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE FinancePlanningBI;
END
GO
CREATE DATABASE FinancePlanningBI;
GO
ALTER DATABASE FinancePlanningBI SET RECOVERY SIMPLE;
GO
-- Query Store records every statement Power BI sends during a refresh, which is
-- how Phase 5 proves query folding from the server side.
ALTER DATABASE FinancePlanningBI SET QUERY_STORE = ON (OPERATION_MODE = READ_WRITE, QUERY_CAPTURE_MODE = ALL);
GO
USE FinancePlanningBI;
GO
EXEC (N'CREATE SCHEMA stg AUTHORIZATION dbo;');
EXEC (N'CREATE SCHEMA analytics AUTHORIZATION dbo;');
GO
PRINT 'FinancePlanningBI created with schemas stg, dbo, analytics.';
GO
