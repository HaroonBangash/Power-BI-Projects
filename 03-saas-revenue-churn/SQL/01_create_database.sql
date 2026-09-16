/*=============================================================================
  01_create_database.sql
  SaaS Revenue, Retention & Churn - SQL data platform

  Creates SaaSRevenueBI with three schemas:
    stg        text landing. Every column NVARCHAR so a malformed value can
               never abort a load; typing happens in dbo, where a bad value
               fails loudly instead of being silently truncated.
    dbo        typed, constrained star schema, plus the two derived tables the
               whole project turns on (the monthly subscription snapshot and
               the MRR movement ledger).
    analytics  views. The ONLY objects Power BI reads. Reshaping a dbo table
               never breaks the report while the views hold.

  Idempotent: drops and recreates the database.
  The dataset is synthetic and must never be presented as real customer data.
=============================================================================*/
USE master;
GO
IF DB_ID(N'SaaSRevenueBI') IS NOT NULL
BEGIN
    ALTER DATABASE SaaSRevenueBI SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE SaaSRevenueBI;
END
GO
CREATE DATABASE SaaSRevenueBI;
GO
ALTER DATABASE SaaSRevenueBI SET RECOVERY SIMPLE;
GO
-- Query Store records every statement Power BI sends during a refresh, which is
-- how Phase 5 proves query folding from the server side rather than by assertion.
ALTER DATABASE SaaSRevenueBI SET QUERY_STORE = ON (OPERATION_MODE = READ_WRITE, QUERY_CAPTURE_MODE = ALL);
GO
USE SaaSRevenueBI;
GO
EXEC (N'CREATE SCHEMA stg AUTHORIZATION dbo;');
EXEC (N'CREATE SCHEMA analytics AUTHORIZATION dbo;');
GO
PRINT 'SaaSRevenueBI created with schemas stg, dbo, analytics.';
GO
