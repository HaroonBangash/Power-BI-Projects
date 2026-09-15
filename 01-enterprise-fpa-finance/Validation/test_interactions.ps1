<#
    Interaction tests, run with Power BI Desktop open and refreshed.

    A rendered page proves a visual draws; this proves the page still tells the truth
    once a reader USES it. Every interactive state a page offers is reproduced as the
    query that state produces, and checked against an independent SQL query:

      slicers          entity and department, on the pages that carry them
      calculation grp  Plan Version (Actual / Budget / variance) and Period View
      scenario buttons Downside / Base / Upside drive the outlook
      cross-filtering  selecting a department in one visual filters the next
      drill            the chart of accounts hierarchy, group then account
      as-of guard      a balance stays blank after the as-of date, whatever is selected

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\test_interactions.ps1
#>
param([string]$SqlServer = "localhost\SQLEXPRESS")
$ErrorActionPreference = "Stop"
$pass = 0; $fail = 0

$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$port = $null; $cat = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    try {
        $p = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$p")
        $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $k = $null; if ($rd.Read()) { $k = $rd.GetValue(0) }; $rd.Close(); $c.Close()
        if ($k) { $port = $p; $cat = $k; break }
    } catch {}
}
if (-not $cat) { throw "No live Power BI model. Open EnterpriseFPA.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=FinancePlanningBI;Integrated Security=True;TrustServerCertificate=True")
$sql.Open()

function DaxScalar($q) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = "EVALUATE ROW ( ""v"", $q )"
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return $dt.Rows[0][0]
}
function SqlScalar($q) {
    # an expression gets a SELECT; a full statement (a CTE) is run as written
    $text = if ($q.TrimStart().StartsWith("WITH", "CurrentCultureIgnoreCase")) { $q } else { "SELECT $q" }
    $cmd = $sql.CreateCommand(); $cmd.CommandText = $text
    $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return $dt.Rows[0][0]
}
function Check($area, $name, $dax, $sqlExpr, $tol = 0.02) {
    $a = DaxScalar $dax
    if ($sqlExpr -is [string] -and $sqlExpr.StartsWith("literal:")) {
        $e = $sqlExpr.Substring(8)
        $ok = ("$a" -eq "$e")
    } else {
        $e = SqlScalar $sqlExpr
        $ok = ($null -ne $a -and -not ($a -is [System.DBNull]) -and [Math]::Abs([double]$a - [double]$e) -le $tol)
    }
    if ($ok) { $script:pass++ } else { $script:fail++; Write-Host ("  [FAIL] {0,-12} {1,-52} expected {2}, got {3}" -f $area, $name, $e, $a) -ForegroundColor Red }
}

$PLJOIN = "FROM dbo.FactFinancials f JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode JOIN dbo.DimDate d ON d.[Date] = f.MonthStart JOIN dbo.DimEntity e ON e.EntityID = f.EntityID JOIN dbo.DimDepartment dp ON dp.DepartmentID = f.DepartmentID"
$REV = "-SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN f.AmountAUD END)"
$OPEX = "SUM(CASE WHEN a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)"

Write-Host "== slicers ==" -ForegroundColor Yellow
Check "Slicer" "entity slicer: Northstar UK, revenue FY26" `
    'CALCULATE ( [Revenue], DimEntity[EntityName] = "Northstar UK", DimDate[FinancialYear] = "FY26" )' `
    "$REV $PLJOIN WHERE f.VersionID = 'ACT' AND e.EntityName = 'Northstar UK' AND d.FinancialYear = 'FY26'"
Check "Slicer" "entity slicer: Northstar UK, receivables on the as-of date" `
    'CALCULATE ( [AR Balance], DimEntity[EntityName] = "Northstar UK" )' `
    "SUM(i.InvoiceAmountAUD) FROM dbo.FactARInvoice i JOIN dbo.DimEntity e ON e.EntityID = i.EntityID
     CROSS JOIN (SELECT CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate') k
     WHERE e.EntityName = 'Northstar UK' AND i.InvoiceDate <= k.AsOf AND (i.PaidDate IS NULL OR i.PaidDate > k.AsOf)"
Check "Slicer" "department slicer: Sales, operating expense FY26" `
    'CALCULATE ( [Operating Expense], DimDepartment[DepartmentName] = "Sales", DimDate[FinancialYear] = "FY26" )' `
    "$OPEX $PLJOIN WHERE f.VersionID = 'ACT' AND dp.DepartmentName = 'Sales' AND d.FinancialYear = 'FY26'"
Check "Slicer" "both slicers: Northstar UK and Sales, operating expense FY26" `
    'CALCULATE ( [Operating Expense], DimEntity[EntityName] = "Northstar UK", DimDepartment[DepartmentName] = "Sales", DimDate[FinancialYear] = "FY26" )' `
    "$OPEX $PLJOIN WHERE f.VersionID = 'ACT' AND e.EntityName = 'Northstar UK' AND dp.DepartmentName = 'Sales' AND d.FinancialYear = 'FY26'"

Write-Host "== calculation groups ==" -ForegroundColor Yellow
Check "CalcGroup" "Plan Version = Budget on the statement" `
    'CALCULATE ( [P&L Line Value], ''Plan Version''[Version] = "Budget", DimPLLine[LineName] = "Operating expenses", DimDate[FinancialYear] = "FY26" )' `
    "$OPEX $PLJOIN WHERE f.VersionID = 'BUD' AND d.FinancialYear = 'FY26'"
Check "CalcGroup" "Plan Version = Var vs Budget, with the entity slicer set" `
    'CALCULATE ( [Operating Expense], ''Plan Version''[Version] = "Var vs Budget", DimEntity[EntityName] = "Northstar UK", DimDate[FinancialYear] = "FY26" )' `
    "SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
   - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
     $PLJOIN WHERE e.EntityName = 'Northstar UK' AND d.FinancialYear = 'FY26'"
Check "CalcGroup" "Period View = Year to date inside FY27" `
    'CALCULATE ( [Revenue], ''Period View''[Period] = "Year to date", DimDate[FinancialYear] = "FY27" )' `
    "$REV $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY27'"
Check "CalcGroup" "both groups at once: Var % vs Budget of the year to date" `
    'CALCULATE ( [Revenue], ''Plan Version''[Version] = "Var % vs Budget", ''Period View''[Period] = "Year to date", DimDate[FinancialYear] = "FY26" )' `
    "(CAST(SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS FLOAT)
    - SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END))
    / ABS(SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END))
     $PLJOIN WHERE d.FinancialYear = 'FY26'" 0.0000001

Write-Host "== scenario buttons ==" -ForegroundColor Yellow
foreach ($s in @("Downside", "Base", "Upside")) {
    Check "Scenario" "$s drives the outlook" `
        "CALCULATE ( [Outlook Operating Profit], DimScenario[ScenarioName] = ""$s"" )" `
        "WITH ytd AS (
            SELECT f.EntityID, $REV AS Revenue,
                   SUM(CASE WHEN a.AccountGroup = 'COGS' THEN f.AmountAUD END) AS Cogs, $OPEX AS Opex
            $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = 0 GROUP BY f.EntityID),
        run AS (
            SELECT f.EntityID, $REV / 12.0 AS Revenue,
                   SUM(CASE WHEN a.AccountGroup = 'COGS' THEN f.AmountAUD END) / 12.0 AS Cogs, $OPEX / 12.0 AS Opex
            $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0 GROUP BY f.EntityID)
        SELECT SUM(COALESCE(ytd.Revenue,0) + 10 * COALESCE(run.Revenue,0) * (1 + sc.RevenueChangePct) * fx.f)
             - SUM(COALESCE(ytd.Cogs,0) + 10 * COALESCE(run.Cogs,0) * (1 + sc.RevenueChangePct) * fx.f)
             - SUM(COALESCE(ytd.Opex,0) + 10 * COALESCE(run.Opex,0) * (1 + sc.OpexChangePct) * fx.f)
        FROM dbo.DimEntity e2
        CROSS JOIN (SELECT * FROM dbo.DimScenario WHERE ScenarioName = '$s') sc
        CROSS APPLY (SELECT CASE WHEN e2.LocalCurrency <> 'AUD' THEN 1.0 / (1 + sc.AUDChangePct) ELSE 1 END AS f) fx
        LEFT JOIN ytd ON ytd.EntityID = e2.EntityID
        LEFT JOIN run ON run.EntityID = e2.EntityID" 0.5
}

Write-Host "== cross-filtering and drill ==" -ForegroundColor Yellow
Check "CrossFilter" "selecting Marketing filters the scorecard's underspend" `
    'CALCULATE ( [Operating Expense vs Budget], DimDepartment[DepartmentName] = "Marketing", DimDate[FinancialYear] = "FY26" )' `
    "SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
   - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
     $PLJOIN WHERE dp.DepartmentName = 'Marketing' AND d.FinancialYear = 'FY26'"
Check "CrossFilter" "selecting an ageing bucket filters the receivable" `
    'CALCULATE ( [AR Ageing Amount], DimAgeingBucket[BucketName] = "Over 365" )' `
    "SUM(i.InvoiceAmountAUD) FROM dbo.FactARInvoice i
     CROSS JOIN (SELECT CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate') k
     WHERE i.InvoiceDate <= k.AsOf AND (i.PaidDate IS NULL OR i.PaidDate > k.AsOf) AND i.DueDate < DATEADD(DAY, -365, k.AsOf)"
Check "Drill" "chart of accounts, group level: Operating Expense FY26" `
    'CALCULATE ( [Account Amount], DimAccount[AccountGroup] = "Operating Expense", DimDate[FinancialYear] = "FY26" )' `
    "$OPEX $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26'"
Check "Drill" "chart of accounts, account level: 6000 Salaries FY26" `
    'CALCULATE ( [Account Amount], DimAccount[AccountLabel] = "6000 Salaries", DimDate[FinancialYear] = "FY26" )' `
    "SUM(f.AmountAUD * a.NaturalSign) $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' AND a.AccountCode = '6000'"

Write-Host "== the as-of guard holds under interaction ==" -ForegroundColor Yellow
Check "AsOf" "cash stays blank for a month after the as-of date, with an entity selected" `
    'IF ( ISBLANK ( CALCULATE ( [Cash Balance], DimDate[YearMonthLabel] = "Sep 2026", DimEntity[EntityName] = "Northstar UK" ) ), "blank", "value" )' `
    "literal:blank"
Check "AsOf" "receivables stay blank for FY27 Q3 (after the as-of date)" `
    'IF ( ISBLANK ( CALCULATE ( [AR Balance], DimDate[FinancialQuarterLabel] = "FY27 Q3" ) ), "blank", "value" )' `
    "literal:blank"
Check "AsOf" "the balance date follows the selection: FY26 ends 30 Jun 2026" `
    'FORMAT ( CALCULATE ( [Balance Date], DimDate[FinancialYear] = "FY26" ), "yyyy-mm-dd" )' `
    "literal:2026-06-30"

$conn.Close(); $sql.Close()
Write-Host ""
Write-Host ("INTERACTIONS: {0} of {1} checks passed" -f $pass, ($pass + $fail)) -ForegroundColor Cyan
if ($fail) { exit 1 }
exit 0
