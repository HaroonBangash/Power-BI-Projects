/*=============================================================================
  07_build_financials.sql

  FactFinancials: actual, budget and forecast in ONE fact at one grain -
  version x month x entity x department x account.

  Why one fact: every P&L comparison (actual vs budget vs forecast) is the same
  measure evaluated under a different version, which is exactly what the
  semantic model's calculation group does. Actual rows are the ledger summed to
  the month, so a P&L visual scans ~48k actual rows instead of 80k lines - and
  far fewer than a scaled multi-million-line ledger (Phase 5 performance test).

  Actual AUD is the SUM of the per-line translated amounts, so the fact equals
  FactGL to the cent at every grain (checked in 09).
=============================================================================*/
USE FinancePlanningBI;
GO
SET NOCOUNT ON;
GO

TRUNCATE TABLE dbo.FactFinancials;

INSERT dbo.FactFinancials (VersionID, MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD, AmountLocal,
                           AmountAUDAtPYRate, PostingLines, ScenarioLabel)
SELECT N'ACT', MonthStart, EntityID, DepartmentID, AccountCode, SUM(AmountAUD), SUM(AmountLocal),
       SUM(AmountAUDAtPYRate), COUNT(*), NULL
FROM dbo.FactGL
GROUP BY MonthStart, EntityID, DepartmentID, AccountCode
UNION ALL
SELECT N'BUD', MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD, NULL, NULL, NULL, NULL
FROM dbo.FactBudget
UNION ALL
SELECT N'FC', MonthStart, EntityID, DepartmentID, AccountCode, AmountAUD, NULL, NULL, NULL, ScenarioLabel
FROM dbo.FactForecast;

SELECT VersionID, COUNT(*) AS [Rows], SUM(AmountAUD) AS AmountAUD
FROM dbo.FactFinancials GROUP BY VersionID ORDER BY VersionID;
GO
PRINT 'FactFinancials built.';
GO
