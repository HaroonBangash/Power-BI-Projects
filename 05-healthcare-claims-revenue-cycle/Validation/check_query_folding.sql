/*=============================================================================
  check_query_folding.sql

  Proves from the SERVER side that Power Query folded: every view the model
  imports must appear in Query Store as a native SELECT against that view with
  its columns listed - not a "select *" with the work done in the mashup engine
  afterwards.

  Query Store is switched on in 01_create_database.sql, so the statements Power
  BI sent during each refresh are recorded without any tracing.

  TWO THINGS THIS SCRIPT LEARNED THE HARD WAY:

  1. QUERY STORE BUFFERS IN MEMORY and flushes on its own schedule (15 minutes by
     default). Read too soon and the small dimension queries are simply not there
     yet, while the slower fact queries are - which looks exactly like partial
     folding and is not. sp_query_store_flush_db is called first.

  2. COUNT(*) OVER A LEFT JOIN COUNTS THE NULL-EXTENDED ROW, so a view with no
     statement at all reported one - and "not seen" was being printed as "seen,
     but not a column list". It counts the joined column now.

  vw_DimAgeBand is deliberately NOT imported: the age band is carried on
  vw_DimBeneficiary instead, so there is no separate dimension table in the
  model. It is excluded rather than allowed to fail.

  Run AFTER at least one refresh (Validation\open_powerbi.ps1 -Restart):
      sqlcmd -S localhost\SQLEXPRESS -C -b -d HealthcareRCMBI -i Validation\check_query_folding.sql
=============================================================================*/
USE HealthcareRCMBI;
GO
SET NOCOUNT ON;
GO

-- Force what is still in memory out to disk before reading it.
EXEC sys.sp_query_store_flush_db;
GO

DECLARE @Views TABLE (ViewName SYSNAME);
INSERT @Views (ViewName)
SELECT name FROM sys.views
WHERE SCHEMA_NAME(schema_id) = N'analytics'
  AND name <> N'vw_DimAgeBand';          -- not imported: the band lives on the patient

;WITH folded AS (
    SELECT v.ViewName,
           COUNT(qt.query_sql_text) AS Statements,
           MAX(CASE WHEN qt.query_sql_text LIKE N'%select [[]$Table].[[]%' THEN 1 ELSE 0 END) AS SelectsColumns,
           MAX(CASE WHEN qt.query_sql_text LIKE N'%select * from%' THEN 1 ELSE 0 END) AS SelectsStar
    FROM @Views v
    LEFT JOIN sys.query_store_query_text qt
           ON qt.query_sql_text LIKE N'%[[]' + v.ViewName + N']%'
    GROUP BY v.ViewName)
SELECT ViewName,
       Statements,
       CASE WHEN SelectsColumns = 1 THEN N'folded (columns listed)'
            WHEN Statements = 0 THEN N'NOT SEEN - refresh first'
            ELSE N'seen, but not a column list' END AS Verdict
FROM folded
ORDER BY ViewName;

DECLARE @total INT = (SELECT COUNT(*) FROM @Views);
DECLARE @foldedCount INT = (
    SELECT COUNT(*) FROM @Views v
    WHERE EXISTS (SELECT 1 FROM sys.query_store_query_text qt
                  WHERE qt.query_sql_text LIKE N'%[[]' + v.ViewName + N']%'
                    AND qt.query_sql_text LIKE N'%select [[]$Table].[[]%'));
-- This script's own text lands in Query Store too, so self-referential statements
-- (anything that reads query_store) are excluded from the unfolded count.
DECLARE @star INT = (
    SELECT COUNT(*) FROM sys.query_store_query_text
    WHERE query_sql_text LIKE N'%analytics%' AND query_sql_text LIKE N'%select * from%'
      AND query_sql_text NOT LIKE N'%query_store%');

PRINT CONCAT(N'Query folding: ', @foldedCount, N' of ', @total,
             N' analytics views were read with a folded column-list SELECT; unfolded "select *" statements: ', @star, N'.');
IF @foldedCount <> @total OR @star <> 0
    THROW 50120, N'Query folding check failed - see the verdict column above.', 1;
GO
