/*=============================================================================
  01_create_database.sql
  Omnichannel Marketing Attribution - SQL data platform

  Creates MarketingAttributionBI with three schemas:
    stg        text landing. Every column NVARCHAR so a malformed value can
               never abort a load; typing happens in dbo, where failures are
               counted and reported instead of silently truncated.
    dbo        typed, constrained star schema. Primary and foreign keys are
               declared and engine-trusted.
    analytics  views. The ONLY objects Power BI reads. Renaming or reshaping
               a dbo table never breaks the report while the views hold.

  Idempotent: safe to re-run. Drops and recreates the database.
  The dataset is synthetic and must never be presented as real client data.
=============================================================================*/
USE master;
GO
IF DB_ID(N'MarketingAttributionBI') IS NOT NULL
BEGIN
    ALTER DATABASE MarketingAttributionBI SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE MarketingAttributionBI;
END
GO
CREATE DATABASE MarketingAttributionBI;
GO
ALTER DATABASE MarketingAttributionBI SET RECOVERY SIMPLE;
GO
USE MarketingAttributionBI;
GO
EXEC (N'CREATE SCHEMA stg AUTHORIZATION dbo;');
EXEC (N'CREATE SCHEMA analytics AUTHORIZATION dbo;');
GO
PRINT 'MarketingAttributionBI created with schemas stg, dbo, analytics.';
GO
