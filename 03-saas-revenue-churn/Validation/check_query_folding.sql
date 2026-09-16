/*=============================================================================
  check_query_folding.sql

  Proves from the SERVER side that Power Query folded: every table the model
  imports must appear in Query Store as a native SELECT against its analytics
  view, with its columns listed - not a "select *" with the work done in the
  mashup engine afterwards.

  Query Store is switched on in 01_create_database.sql, so the statements Power
  BI sent during each refresh are recorded without any tracing.

  Run AFTER at least one refresh (Validation\open_powerbi.ps1 -Restart):
      sqlcmd -S localhost\SQLEXPRESS -C -b -d SaaSRevenueBI -i Validation\check_query_folding.sql
=============================================================================*/
USE SaaSRevenueBI;
GO
SET NOCOUNT ON;
GO

DECLARE @Views TABLE (ViewName SYSNAME);
INSERT @Views (ViewName)
SELECT name FROM sys.views WHERE SCHEMA_NAME(schema_id) = N'analytics';

;WITH folded AS (
    SELECT v.ViewName,
           COUNT(*) AS Statements,
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
