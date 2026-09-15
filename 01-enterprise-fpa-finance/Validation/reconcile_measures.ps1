<#
    Live validation of the semantic model, run with Power BI Desktop open and refreshed.

    Step 1  SWEEP      every measure is evaluated alone. One broken measure poisons the
                       whole model script, so nothing else is trusted until this passes.
                       Grand-total values are written to Validation/measure_values.csv
                       for the measure dictionary.
    Step 2  RECONCILE  every measure is compared with an independently written SQL query
                       against FinancePlanningBI - the income statement by year, entity,
                       department and account, both calculation groups, FX and constant
                       currency, working capital as of any date, cash, and the scenario
                       outlook.
    Step 3  SECURITY   the role is tested for its secure default (an unmapped user sees
                       nothing) and its mapping logic is evaluated for each scoped user.

    AS OF: every expected value states the world on the as-of date (2026-08-31). A
    receipt banked after it leaves the invoice OPEN, exactly as the model does.

    SQL expected values that divide are computed in FLOAT: SQL Server rounds a
    DECIMAL / DECIMAL quotient to as few as 6 decimal places, which would fail a
    correct DAX result.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\reconcile_measures.ps1
#>
param([string]$SqlServer = "localhost\SQLEXPRESS")
$ErrorActionPreference = "Stop"
$script:pass = 0; $script:fail = 0; $script:rows = @()

# ------------------------------------------------------------------ connect ---
$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$script:port = $null; $script:cat = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    try {
        $p = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$p")
        $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $k = $null; if ($rd.Read()) { $k = $rd.GetValue(0) }; $rd.Close(); $c.Close()
        if ($k) { $script:port = $p; $script:cat = $k; break }
    } catch {}
}
if (-not $script:cat) { throw "No live Power BI model. Open EnterpriseFPA.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($script:port);Initial Catalog=$($script:cat)")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=FinancePlanningBI;Integrated Security=True;TrustServerCertificate=True")
$sql.Open()
Write-Host "Power BI model on localhost:$($script:port); SQL on $SqlServer" -ForegroundColor Cyan

function Dax([string]$q, $c = $conn) {
    $cmd = $c.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Sql([string]$q) {
    $cmd = $sql.CreateCommand(); $cmd.CommandText = $q; $cmd.CommandTimeout = 300
    $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Check($area, $name, $actual, $expected, $tol) {
    $ok = $false
    if ($expected -is [string]) { $ok = ("$actual" -eq "$expected") }
    elseif ($null -ne $actual -and "$actual" -ne "" -and -not ($actual -is [System.DBNull])) {
        $ok = ([Math]::Abs([double]$actual - [double]$expected) -le [double]$tol)
    }
    if ($ok) { $script:pass++; $tag = "PASS" } else { $script:fail++; $tag = "FAIL" }
    $script:rows += [pscustomobject]@{ Result = $tag; Area = $area; Check = $name; Expected = $expected; Actual = $actual }
    if (-not $ok) { Write-Host ("  [FAIL] {0,-10} {1,-64} expected {2} got {3}" -f $area, $name, $expected, $actual) -ForegroundColor Red }
}
function Scalar($area, $name, $daxExpr, $sqlExpr, $tol) {
    $a = (Dax "EVALUATE ROW ( ""v"", $daxExpr )").Rows[0][0]
    $e = (Sql "SELECT $sqlExpr").Rows[0][0]
    if ($e -is [string]) { Check $area $name "$a" $e 0 } else { Check $area $name $a ([double]$e) $tol }
}
# A row's key is every column but the last, joined; the last column is the value.
function RowKey($r) {
    $n = $r.Table.Columns.Count
    return ((0..($n - 2) | ForEach-Object { "$($r[$_])".Trim() }) -join " | ")
}
function Grouped($area, $name, $daxQuery, $sqlQuery, $tol) {
    $d = Dax $daxQuery; $s = Sql $sqlQuery
    $map = @{}; foreach ($r in $d.Rows) { $map[(RowKey $r)] = $r[$r.Table.Columns.Count - 1] }
    if ($s.Rows.Count -eq 0) { Check $area "$name (SQL returned rows)" 0 1 0 }
    foreach ($r in $s.Rows) {
        $v = $r[$r.Table.Columns.Count - 1]
        if ($v -is [string]) { Check $area "$name | $(RowKey $r)" "$($map[(RowKey $r)])" $v 0 }
        else { Check $area "$name | $(RowKey $r)" $map[(RowKey $r)] ([double]$v) $tol }
    }
    Check $area "$name | group count" $d.Rows.Count $s.Rows.Count 0
}

$ASOF = "(SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate')"
# The income statement in SQL, at any grain: presented signs, ledger source.
$PLJOIN = "FROM dbo.FactFinancials f JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode JOIN dbo.DimDate d ON d.[Date] = f.MonthStart JOIN dbo.DimEntity e ON e.EntityID = f.EntityID JOIN dbo.DimDepartment dp ON dp.DepartmentID = f.DepartmentID"
$REV = "-SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN f.AmountAUD END)"
$COGS = "SUM(CASE WHEN a.AccountGroup = 'COGS' THEN f.AmountAUD END)"
$OPEX = "SUM(CASE WHEN a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)"
$OP = "-SUM(CASE WHEN a.IsOperating = 1 THEN f.AmountAUD END)"

# ---------------------------------------------------------------- 1. sweep ---
Write-Host "`n== 1. SWEEP: every measure evaluated alone ==" -ForegroundColor Yellow
$tmdl = Join-Path $PSScriptRoot "..\PowerBI\EnterpriseFPA.SemanticModel\definition\tables\_Measures.tmdl"
$names = @()
foreach ($ln in (Get-Content -LiteralPath $tmdl)) {
    if ($ln -match "^\tmeasure '([^']+)'") { $names += $Matches[1] }
    elseif ($ln -match "^\tmeasure (\S+) =") { $names += $Matches[1] }
}
$values = @()
foreach ($n in $names) {
    $esc = $n.Replace("]", "]]")
    try {
        $dt = Dax "EVALUATE ROW ( ""v"", [$esc] )"
        $v = $dt.Rows[0][0]
        $values += [pscustomobject]@{ Measure = $n; Value = "$v" }
        $script:pass++
    } catch {
        $script:fail++
        $script:rows += [pscustomobject]@{ Result = "FAIL"; Area = "Sweep"; Check = $n; Expected = "evaluates"; Actual = $_.Exception.Message }
        Write-Host ("  [FAIL] sweep {0}: {1}" -f $n, ($_.Exception.Message -replace "`r?`n", " ")) -ForegroundColor Red
    }
}
$values | Export-Csv -NoTypeInformation -Path (Join-Path $PSScriptRoot "measure_values.csv")
Write-Host ("  {0} measures evaluated" -f $names.Count)

# ------------------------------------------------------------ 2. reconcile ---
Write-Host "`n== 2. RECONCILE: model vs independent SQL ==" -ForegroundColor Yellow

# -- 2a. income statement by financial year and version -----------------------
$versions = @{ "Actual" = "ACT"; "Budget" = "BUD"; "Forecast" = "FC" }
foreach ($vname in $versions.Keys) {
    $vid = $versions[$vname]
    foreach ($pair in @(@("Revenue", $REV), @("COGS", $COGS), @("Operating Expense", $OPEX), @("Operating Profit", $OP))) {
        $mname = $pair[0]; $expr = $pair[1]
        Grouped "P&L" "$mname ($vname) by FY" @"
EVALUATE
SUMMARIZECOLUMNS (
    DimDate[FinancialYear],
    "v", CALCULATE ( [$mname], 'Plan Version'[Version] = "$vname" )
)
"@ @"
SELECT d.FinancialYear, $expr AS v $PLJOIN
WHERE f.VersionID = '$vid' GROUP BY d.FinancialYear HAVING $expr IS NOT NULL
"@ 0.02
    }
}

# -- 2b. below the line, actual only ------------------------------------------
Grouped "P&L" "Net Profit (Actual) by FY" @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", [Net Profit] )
"@ @"
SELECT d.FinancialYear, -SUM(f.AmountAUD) AS v $PLJOIN WHERE f.VersionID = 'ACT' GROUP BY d.FinancialYear
"@ 0.02
Scalar "P&L" "Net Profit is blank under Budget" `
    "IF ( ISBLANK ( CALCULATE ( [Net Profit], 'Plan Version'[Version] = ""Budget"" ) ), ""blank"", ""value"" )" "'blank'" 0
Scalar "P&L" "Tax Expense is blank under Forecast" `
    "IF ( ISBLANK ( CALCULATE ( [Tax Expense], 'Plan Version'[Version] = ""Forecast"" ) ), ""blank"", ""value"" )" "'blank'" 0

# -- 2c. variance, favourable-signed ------------------------------------------
Grouped "Variance" "Revenue vs Budget by FY" @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", [Revenue vs Budget] )
"@ @"
SELECT d.FinancialYear,
       SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.02
Grouped "Variance" "Operating Expense vs Budget (underspend positive) by FY" @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", [Operating Expense vs Budget] )
"@ @"
SELECT d.FinancialYear,
       SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END) AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.02
Grouped "Variance" "Operating Profit vs Budget by FY" @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", [Operating Profit vs Budget] )
"@ @"
SELECT d.FinancialYear,
       SUM(CASE WHEN f.VersionID = 'ACT' AND a.IsOperating = 1 THEN -f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'BUD' AND a.IsOperating = 1 THEN -f.AmountAUD END) AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.02

# the calculation group's own variance items, at the grain a matrix shows them
Grouped "CalcGroup" "Var vs Budget item (Revenue) by FY" @"
EVALUATE
SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", CALCULATE ( [Revenue], 'Plan Version'[Version] = "Var vs Budget" ) )
"@ @"
SELECT d.FinancialYear,
       SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.02
Grouped "CalcGroup" "Var vs Budget item (Operating Expense, favourable) by FY" @"
EVALUATE
SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", CALCULATE ( [Operating Expense], 'Plan Version'[Version] = "Var vs Budget" ) )
"@ @"
SELECT d.FinancialYear,
       SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END) AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.02
Grouped "CalcGroup" "Var vs Budget item (Gross Margin %, percentage points) by FY" @"
EVALUATE
SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", CALCULATE ( [Gross Margin %], 'Plan Version'[Version] = "Var vs Budget" ) )
"@ @"
SELECT d.FinancialYear,
       ( (CAST(SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS FLOAT)
          - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'COGS' THEN f.AmountAUD END))
         / NULLIF(SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END), 0)
       - (CAST(SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS FLOAT)
          - SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'COGS' THEN f.AmountAUD END))
         / NULLIF(SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END), 0) ) * 100 AS v
$PLJOIN GROUP BY d.FinancialYear
"@ 0.0001

# -- 2d. entity, department, account ------------------------------------------
Grouped "Entity" "Revenue by entity (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [Revenue] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT e.EntityName, $REV AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' GROUP BY e.EntityName
"@ 0.02
Grouped "Entity" "Gross Margin % by entity (FY26, currency-neutral)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [Gross Margin %] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT e.EntityName,
       (CAST($REV AS FLOAT) - $COGS) / NULLIF($REV, 0) AS v
$PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' GROUP BY e.EntityName
"@ 0.0000001
Grouped "Department" "Operating Expense by department (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], "v", [Operating Expense] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT dp.DepartmentName, $OPEX AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' GROUP BY dp.DepartmentName
"@ 0.02
Grouped "Department" "Operating Expense vs Budget by department (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], "v", [Operating Expense vs Budget] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT dp.DepartmentName,
       SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END)
     - SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END) AS v
$PLJOIN WHERE d.FinancialYear = 'FY26' GROUP BY dp.DepartmentName
"@ 0.02
Grouped "Account" "Account Amount, natural sign, by account (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimAccount[AccountLabel], "v", [Account Amount] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT a.AccountLabel, SUM(f.AmountAUD * a.NaturalSign) AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' GROUP BY a.AccountLabel
"@ 0.02

# -- 2e. the statement layout --------------------------------------------------
Grouped "Statement" "P&L Line Value (FY26 actual)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimPLLine[LineName], "v", [P&L Line Value] ), DimDate[FinancialYear] = "FY26" )
"@ @"
WITH p AS (
    SELECT $REV AS Revenue, $COGS AS Cogs, $OPEX AS Opex,
           SUM(CASE WHEN a.AccountGroup = 'Other Expense' THEN f.AmountAUD END) AS Other,
           SUM(CASE WHEN a.AccountGroup = 'Tax' THEN f.AmountAUD END) AS Tax,
           -SUM(f.AmountAUD) AS NetProfit, $OP AS OperatingProfit
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26')
SELECT 'Revenue' AS LineName, CAST(Revenue AS FLOAT) AS v FROM p
UNION ALL SELECT 'Cost of goods sold', Cogs FROM p
UNION ALL SELECT 'Gross profit', Revenue - Cogs FROM p
UNION ALL SELECT 'Gross margin %', (Revenue - Cogs) / Revenue FROM p
UNION ALL SELECT 'Operating expenses', Opex FROM p
UNION ALL SELECT 'Operating profit', OperatingProfit FROM p
UNION ALL SELECT 'Operating margin %', OperatingProfit / Revenue FROM p
UNION ALL SELECT 'Other expense (net)', Other FROM p
UNION ALL SELECT 'Tax expense', Tax FROM p
UNION ALL SELECT 'Net profit', NetProfit FROM p
UNION ALL SELECT 'Net margin %', NetProfit / Revenue FROM p
"@ 0.02

# -- 2f. period view -----------------------------------------------------------
Grouped "Period" "Revenue, year to date, by financial year" @"
EVALUATE
SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", CALCULATE ( [Revenue], 'Period View'[Period] = "Year to date" ) )
"@ @"
SELECT d.FinancialYear, $REV AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND f.MonthStart <= $ASOF GROUP BY d.FinancialYear
"@ 0.02
Scalar "Period" "Revenue over the trailing twelve months (fixed window measure)" "[Revenue TTM]" @"
$REV $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0
"@ 0.02
Scalar "Period" "Operating profit over the trailing twelve months" "[Operating Profit TTM]" @"
$OP $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0
"@ 0.02
Grouped "Period" "Revenue, prior year (like-for-like), by financial year" @"
EVALUATE
SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", CALCULATE ( [Revenue], 'Period View'[Period] = "Prior year" ) )
"@ @"
SELECT d.FinancialYear, p.v FROM dbo.DimDate d
CROSS APPLY (
    SELECT -SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN f.AmountAUD END) AS v
    FROM dbo.FactFinancials f
    JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
    JOIN dbo.DimDate pd ON pd.[Date] = f.MonthStart
    WHERE f.VersionID = 'ACT' AND pd.FinancialYearStart = d.FinancialYearStart - 1
      AND pd.MonthStart <= DATEADD(YEAR, -1, (SELECT MIN(x.MonthStart) FROM dbo.DimDate x
            WHERE x.FinancialYear = d.FinancialYear AND x.[Date] <= $ASOF
              AND x.MonthStart = (SELECT MAX(y.MonthStart) FROM dbo.DimDate y WHERE y.FinancialYear = d.FinancialYear AND y.[Date] <= $ASOF)))
) p
WHERE d.[Date] = (SELECT MIN([Date]) FROM dbo.DimDate z WHERE z.FinancialYear = d.FinancialYear)
  AND p.v IS NOT NULL
  -- like-for-like only: the ledger must cover the earlier window as well
  AND DATEADD(MONTH, -12, DATEFROMPARTS(d.FinancialYearStart, 7, 1))
      >= (SELECT MIN(MonthStart) FROM dbo.FactFinancials WHERE VersionID = 'ACT')
"@ 0.02
Scalar "Period" "Revenue prior year to date (FY27 context)" `
    "CALCULATE ( [Revenue], 'Period View'[Period] = ""Prior year to date"", DimDate[FinancialYear] = ""FY27"" )" @"
$REV $PLJOIN WHERE f.VersionID = 'ACT' AND f.MonthStart >= '2025-07-01' AND f.MonthStart <= '2025-08-01'
"@ 0.02
Scalar "Period" "Revenue FYTD measure (FY27)" `
    "CALCULATE ( [Revenue FYTD], DimDate[FinancialYear] = ""FY27"" )" @"
$REV $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY27'
"@ 0.02

# -- 2g. FX and constant currency ---------------------------------------------
Grouped "FX" "Revenue at prior-year rates by FY" @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[FinancialYear], "v", [Revenue at Prior-Year Rates] )
"@ @"
SELECT d.FinancialYear, -SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN f.AmountAUDAtPYRate END) AS v
$PLJOIN WHERE f.VersionID = 'ACT' GROUP BY d.FinancialYear
HAVING SUM(CASE WHEN a.AccountGroup = 'Revenue' AND f.AmountAUDAtPYRate IS NULL THEN 1 ELSE 0 END) = 0
"@ 0.02
Grouped "FX" "Average FX rate by currency (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( FxRateMonthly[CurrencyCode], "v", [Average FX Rate] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT m.CurrencyCode, AVG(CAST(m.AvgAUDPerUnit AS FLOAT)) AS v
FROM dbo.FxRateMonthly m JOIN dbo.DimDate d ON d.[Date] = m.MonthStart
WHERE d.FinancialYear = 'FY26' GROUP BY m.CurrencyCode
"@ 0.0000001
Scalar "FX" "Foreign-currency revenue share (FY26)" `
    "CALCULATE ( [Foreign-Currency Revenue Share], DimDate[FinancialYear] = ""FY26"" )" @"
CAST(SUM(CASE WHEN e.LocalCurrency <> 'AUD' AND a.AccountGroup = 'Revenue' THEN -f.AmountAUD END) AS FLOAT)
    / NULLIF(SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN -f.AmountAUD END), 0)
$PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26'
"@ 0.0000001
Scalar "FX" "Spot vs average translation difference (whole ledger)" `
    "[Spot vs Average Translation Difference]" `
    "SUM(AmountAUDSpot) - SUM(AmountAUD) FROM dbo.FactGL" 0.02

# -- 2h. ledger detail ---------------------------------------------------------
Scalar "Ledger" "GL amount (ledger sign)" "[GL Amount (AUD)]" "SUM(AmountAUD) FROM dbo.FactGL" 0.02
Scalar "Ledger" "GL lines" "[GL Lines]" "COUNT(*) FROM dbo.FactGL" 0
Scalar "Ledger" "Accrued share of lines" "[Accrued Share of Lines]" `
    "CAST(SUM(CASE WHEN PostingStatus = 'Accrued' THEN 1.0 ELSE 0 END) AS FLOAT) / COUNT(*) FROM dbo.FactGL" 0.0000001
Scalar "Ledger" "Active vendors" "[Active Vendors]" "COUNT(DISTINCT VendorID) FROM dbo.FactGL WHERE VendorID IS NOT NULL" 0
Scalar "Ledger" "Active customers" "[Active Customers]" "COUNT(DISTINCT CustomerID) FROM dbo.FactGL WHERE CustomerID IS NOT NULL" 0
Grouped "Ledger" "Vendor spend by vendor category (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimVendor[VendorCategory], "v", [Vendor Spend (AUD)] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT v.VendorCategory, SUM(g.AmountAUD) AS v
FROM dbo.FactGL g JOIN dbo.DimVendor v ON v.VendorID = g.VendorID JOIN dbo.DimDate d ON d.[Date] = g.[Date]
WHERE d.FinancialYear = 'FY26' GROUP BY v.VendorCategory
"@ 0.02

# -- 2i. working capital, as of two different dates ---------------------------
foreach ($ctx in @(@{ Name = "as-of date"; Dax = ""; Sql = "2026-08-31" },
                   @{ Name = "FY26 year end"; Dax = ", DimDate[FinancialYear] = ""FY26"""; Sql = "2026-06-30" })) {
    $n = $ctx.Name; $dfilter = $ctx.Dax; $D = $ctx.Sql
    Scalar "AR" "AR balance ($n)" "CALCULATE ( [AR Balance]$dfilter )" @"
SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D')
"@ 0.02
    Scalar "AR" "AR open invoices ($n)" "CALCULATE ( [AR Open Invoices]$dfilter )" @"
COUNT(*) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D')
"@ 0
    Scalar "AR" "AR past due ($n)" "CALCULATE ( [AR Past Due]$dfilter )" @"
SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D') AND DueDate < '$D'
"@ 0.02
    Scalar "AR" "AR over 365 days ($n)" "CALCULATE ( [AR Over 365 Days]$dfilter )" @"
SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D') AND DueDate < DATEADD(DAY, -365, '$D')
"@ 0.02
    Scalar "AR" "DSO ($n)" "CALCULATE ( [DSO (Days)]$dfilter )" @"
CAST((SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D')) AS FLOAT)
  / NULLIF((SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate > DATEADD(DAY, -90, '$D') AND InvoiceDate <= '$D'), 0) * 90
"@ 0.0001
    Scalar "AP" "AP balance ($n)" "CALCULATE ( [AP Balance]$dfilter )" @"
SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE BillDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D')
"@ 0.02
    Scalar "AP" "DPO ($n)" "CALCULATE ( [DPO (Days)]$dfilter )" @"
CAST((SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE BillDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D')) AS FLOAT)
  / NULLIF((SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE BillDate > DATEADD(DAY, -90, '$D') AND BillDate <= '$D'), 0) * 90
"@ 0.0001
    Scalar "WC" "Trade working capital ($n)" "CALCULATE ( [Trade Working Capital]$dfilter )" @"
(SELECT SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE InvoiceDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D'))
- (SELECT SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE BillDate <= '$D' AND (PaidDate IS NULL OR PaidDate > '$D'))
"@ 0.02
    Grouped "AR" "AR ageing buckets ($n)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimAgeingBucket[BucketName], "v", [AR Ageing Amount] )$dfilter )
"@ @"
SELECT b.BucketName, SUM(i.InvoiceAmountAUD) AS v
FROM dbo.FactARInvoice i JOIN dbo.DimAgeingBucket b ON DATEDIFF(DAY, i.DueDate, '$D') BETWEEN b.MinDaysPastDue AND b.MaxDaysPastDue
WHERE i.InvoiceDate <= '$D' AND (i.PaidDate IS NULL OR i.PaidDate > '$D') GROUP BY b.BucketName
"@ 0.02
    Grouped "AP" "AP ageing buckets ($n)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimAgeingBucket[BucketName], "v", [AP Ageing Amount] )$dfilter )
"@ @"
SELECT b.BucketName, SUM(p.BillAmountAUD) AS v
FROM dbo.FactAPBill p JOIN dbo.DimAgeingBucket b ON DATEDIFF(DAY, p.DueDate, '$D') BETWEEN b.MinDaysPastDue AND b.MaxDaysPastDue
WHERE p.BillDate <= '$D' AND (p.PaidDate IS NULL OR p.PaidDate > '$D') GROUP BY b.BucketName
"@ 0.02
}
Grouped "AR" "AR balance by entity (as-of date)" @"
EVALUATE SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [AR Balance] )
"@ @"
SELECT e.EntityName, SUM(i.InvoiceAmountAUD) AS v
FROM dbo.FactARInvoice i JOIN dbo.DimEntity e ON e.EntityID = i.EntityID
WHERE i.InvoiceDate <= $ASOF AND (i.PaidDate IS NULL OR i.PaidDate > $ASOF) GROUP BY e.EntityName
"@ 0.02
Scalar "AR" "AR collections (FY26, by receipt date)" `
    "CALCULATE ( [AR Collections], DimDate[FinancialYear] = ""FY26"" )" @"
SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE PaidDate >= '2025-07-01' AND PaidDate <= '2026-06-30'
"@ 0.02
Scalar "AR" "Days to collect (FY26, value-weighted)" `
    "CALCULATE ( [Days to Collect], DimDate[FinancialYear] = ""FY26"" )" @"
SUM(CAST(DaysToPay AS FLOAT) * InvoiceAmountAUD) / NULLIF(SUM(InvoiceAmountAUD), 0)
FROM dbo.FactARInvoice WHERE PaidDate >= '2025-07-01' AND PaidDate <= '2026-06-30'
"@ 0.0001
Scalar "AP" "Days to pay (FY26, value-weighted)" `
    "CALCULATE ( [Days to Pay], DimDate[FinancialYear] = ""FY26"" )" @"
SUM(CAST(DaysToPay AS FLOAT) * BillAmountAUD) / NULLIF(SUM(BillAmountAUD), 0)
FROM dbo.FactAPBill WHERE PaidDate >= '2025-07-01' AND PaidDate <= '2026-06-30'
"@ 0.0001
Scalar "AR" "Invoices whose receipt is dated after the as-of date" "[Receipts After As-Of]" `
    "COUNT(*) FROM dbo.FactARInvoice WHERE IsPaidAfterAsOf = 1" 0

# The UNFILTERED grain: a BLANK date passes a "<= as-of" filter in DAX, so an unpaid
# document would be counted as collected. With a date filter the blank simply does not
# join, which is why only this grain exposes it.
Scalar "AR" "AR collections, no period selected (paid by the as-of date)" "[AR Collections]" @"
SUM(InvoiceAmountAUD) FROM dbo.FactARInvoice WHERE PaidDate IS NOT NULL AND PaidDate <= $ASOF
"@ 0.02
Scalar "AR" "Days to collect, no period selected" "[Days to Collect]" @"
SUM(CAST(DaysToPay AS FLOAT) * InvoiceAmountAUD) / NULLIF(SUM(InvoiceAmountAUD), 0)
FROM dbo.FactARInvoice WHERE PaidDate IS NOT NULL AND PaidDate <= $ASOF
"@ 0.0001
Scalar "AR" "Days paid late, no period selected" "[Days Paid Late (AR)]" @"
SUM(CAST(DaysLate AS FLOAT) * InvoiceAmountAUD) / NULLIF(SUM(InvoiceAmountAUD), 0)
FROM dbo.FactARInvoice WHERE PaidDate IS NOT NULL AND PaidDate <= $ASOF
"@ 0.0001
Scalar "AP" "AP payments, no period selected" "[AP Payments]" @"
SUM(BillAmountAUD) FROM dbo.FactAPBill WHERE PaidDate IS NOT NULL AND PaidDate <= $ASOF
"@ 0.02
Scalar "AP" "Days to pay, no period selected" "[Days to Pay]" @"
SUM(CAST(DaysToPay AS FLOAT) * BillAmountAUD) / NULLIF(SUM(BillAmountAUD), 0)
FROM dbo.FactAPBill WHERE PaidDate IS NOT NULL AND PaidDate <= $ASOF
"@ 0.0001

# Constant currency must be BLANK where a prior-year rate does not exist for every row.
Scalar "FX" "constant currency is blank for FY23 (half the year has no prior-year rate)" `
    "IF ( ISBLANK ( CALCULATE ( [Revenue at Prior-Year Rates], DimDate[FinancialYear] = ""FY23"" ) ), ""blank"", ""value"" )" "'blank'" 0
Scalar "FX" "constant currency is blank for FY22 (no prior-year rate at all)" `
    "IF ( ISBLANK ( CALCULATE ( [Revenue at Prior-Year Rates], DimDate[FinancialYear] = ""FY22"" ) ), ""blank"", ""value"" )" "'blank'" 0
Scalar "FX" "constant currency is present for FY24" `
    "IF ( ISBLANK ( CALCULATE ( [Revenue at Prior-Year Rates], DimDate[FinancialYear] = ""FY24"" ) ), ""blank"", ""value"" )" "'value'" 0

# -- 2j. cash ------------------------------------------------------------------
Scalar "Cash" "Group closing cash (as-of date)" "[Cash Balance]" `
    "SUM(ClosingCashAUD) FROM dbo.FactCashBalance WHERE [Date] = $ASOF" 0.02
Scalar "Cash" "Group closing cash (FY26 year end)" `
    "CALCULATE ( [Cash Balance], DimDate[FinancialYear] = ""FY26"" )" `
    "SUM(ClosingCashAUD) FROM dbo.FactCashBalance WHERE [Date] = '2026-06-30'" 0.02
Grouped "Cash" "Closing cash by entity (as-of date)" @"
EVALUATE SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [Cash Balance] )
"@ @"
SELECT e.EntityName, SUM(c.ClosingCashAUD) AS v
FROM dbo.FactCashBalance c JOIN dbo.DimEntity e ON e.EntityID = c.EntityID
WHERE c.[Date] = $ASOF GROUP BY e.EntityName
"@ 0.02
Scalar "Cash" "Minimum daily group cash (FY26)" `
    "CALCULATE ( [Minimum Daily Cash], DimDate[FinancialYear] = ""FY26"" )" @"
MIN(t.v) FROM (SELECT [Date], SUM(ClosingCashAUD) AS v FROM dbo.FactCashBalance
               WHERE [Date] >= '2025-07-01' AND [Date] <= '2026-06-30' GROUP BY [Date]) t
"@ 0.02
Scalar "Cash" "Average daily group cash (FY26)" `
    "CALCULATE ( [Average Daily Cash], DimDate[FinancialYear] = ""FY26"" )" @"
AVG(CAST(t.v AS FLOAT)) FROM (SELECT [Date], SUM(ClosingCashAUD) AS v FROM dbo.FactCashBalance
               WHERE [Date] >= '2025-07-01' AND [Date] <= '2026-06-30' GROUP BY [Date]) t
"@ 0.02
Scalar "Cash" "Days at the 50,000 floor" "[Cash Floor Days]" `
    "COUNT(*) FROM dbo.FactCashBalance WHERE IsFloorValue = 1" 0

# -- 2k. scenario outlook ------------------------------------------------------
# SQL repeats the projection independently: FY27 to date + remaining months at the
# trailing-twelve-month run rate, flexed by each scenario's drivers, with the
# exchange-rate driver applied only to foreign-currency entities.
$OUTLOOK = @"
WITH k AS (SELECT $ASOF AS AsOf),
ytd AS (
    SELECT f.EntityID,
           $REV AS Revenue, $COGS AS Cogs, $OPEX AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = 0 GROUP BY f.EntityID),
run AS (
    SELECT f.EntityID,
           $REV / 12.0 AS Revenue, $COGS / 12.0 AS Cogs, $OPEX / 12.0 AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0 GROUP BY f.EntityID)
SELECT s.ScenarioName, {0} AS v
FROM dbo.DimScenario s
CROSS JOIN (SELECT 10 AS RemainingMonths) rm
JOIN dbo.DimEntity e ON 1 = 1
LEFT JOIN ytd ON ytd.EntityID = e.EntityID
LEFT JOIN run ON run.EntityID = e.EntityID
GROUP BY s.ScenarioName
"@
$fx = "CASE WHEN e.LocalCurrency <> 'AUD' THEN 1.0 / (1 + s.AUDChangePct) ELSE 1 END"
Grouped "Scenario" "Outlook revenue by scenario" @"
EVALUATE SUMMARIZECOLUMNS ( DimScenario[ScenarioName], "v", [Outlook Revenue] )
"@ ($OUTLOOK -f "SUM(COALESCE(ytd.Revenue, 0) + rm.RemainingMonths * COALESCE(run.Revenue, 0) * (1 + s.RevenueChangePct) * $fx)") 0.5
Grouped "Scenario" "Outlook operating expense by scenario" @"
EVALUATE SUMMARIZECOLUMNS ( DimScenario[ScenarioName], "v", [Outlook Operating Expense] )
"@ ($OUTLOOK -f "SUM(COALESCE(ytd.Opex, 0) + rm.RemainingMonths * COALESCE(run.Opex, 0) * (1 + s.OpexChangePct) * $fx)") 0.5
Grouped "Scenario" "Outlook operating profit by scenario" @"
EVALUATE SUMMARIZECOLUMNS ( DimScenario[ScenarioName], "v", [Outlook Operating Profit] )
"@ ($OUTLOOK -f @"
SUM(COALESCE(ytd.Revenue, 0) + rm.RemainingMonths * COALESCE(run.Revenue, 0) * (1 + s.RevenueChangePct) * $fx)
- SUM(COALESCE(ytd.Cogs, 0) + rm.RemainingMonths * COALESCE(run.Cogs, 0) * (1 + s.RevenueChangePct) * $fx)
- SUM(COALESCE(ytd.Opex, 0) + rm.RemainingMonths * COALESCE(run.Opex, 0) * (1 + s.OpexChangePct) * $fx)
"@) 0.5
Scalar "Scenario" "Run-rate monthly revenue (trailing 12 months)" "[Run-Rate Revenue (Monthly)]" @"
$REV / 12.0 $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0
"@ 0.02
Scalar "Scenario" "Revenue booked so far this financial year" "[Revenue Current FY to Date]" @"
$REV $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = 0
"@ 0.02
Scalar "Scenario" "Months remaining in the financial year" "[Months Remaining in FY]" "10" 0
Scalar "Scenario" "Last complete FY operating profit" "[Last Complete FY Operating Profit]" @"
$OP $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = -1
"@ 0.02

# Budget lines with no posting: every PLAN row has a blank posting count, so a test
# on that column alone counted all 60,480. The measure compares the keys instead.
Scalar "DQ" "Budget lines with no ledger posting" "[Budget Lines Without Posting]" @"
COUNT(*) FROM dbo.FactBudget b WHERE NOT EXISTS (
    SELECT 1 FROM dbo.FactGL g WHERE g.MonthStart = b.MonthStart AND g.EntityID = b.EntityID
                                 AND g.DepartmentID = b.DepartmentID AND g.AccountCode = b.AccountCode)
"@ 0

# A balance must be BLANK for a period that starts after the as-of date, or a chart
# runs flat into months that have no data at all.
Scalar "DQ" "cash balance is blank for the month after the as-of date" `
    "IF ( ISBLANK ( CALCULATE ( [Cash Balance], DimDate[YearMonthLabel] = ""Sep 2026"" ) ), ""blank"", ""value"" )" "'blank'" 0
Scalar "DQ" "receivables balance is blank for the month after the as-of date" `
    "IF ( ISBLANK ( CALCULATE ( [AR Balance], DimDate[YearMonthLabel] = ""Sep 2026"" ) ), ""blank"", ""value"" )" "'blank'" 0
Scalar "DQ" "cash balance still reads on the as-of month" `
    "CALCULATE ( [Cash Balance], DimDate[YearMonthLabel] = ""Aug 2026"" )" @"
SUM(ClosingCashAUD) FROM dbo.FactCashBalance WHERE [Date] = $ASOF
"@ 0.02

# -- 2l. data quality metrics --------------------------------------------------
Grouped "DQ" "Data-quality metrics" @"
EVALUATE SUMMARIZECOLUMNS ( DataQualityMetric[Metric], "v", [DQ Metric Value] )
"@ "SELECT Metric, CAST(MetricValue AS FLOAT) AS v FROM analytics.vw_DataQualityMetric" 0.000001

# -- 2m. every figure a report page shows, at the grain the visual shows it ----
Write-Host "`n-- report figures --" -ForegroundColor DarkGray

# Executive: the P&L bridge (waterfall), FY26, group lines only
Grouped "Report" "P&L bridge by statement line (FY26)" @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimPLLine[LineName], "v", [P&L Bridge Amount] ),
    DimDate[FinancialYear] = "FY26",
    DimPLLine[LineType] = "Group"
)
"@ @"
WITH p AS (
    SELECT $REV AS Revenue, $COGS AS Cogs, $OPEX AS Opex,
           SUM(CASE WHEN a.AccountGroup = 'Other Expense' THEN f.AmountAUD END) AS Other,
           SUM(CASE WHEN a.AccountGroup = 'Tax' THEN f.AmountAUD END) AS Tax
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26')
SELECT 'Revenue' AS LineName, CAST(Revenue AS FLOAT) AS v FROM p
UNION ALL SELECT 'Cost of goods sold', -Cogs FROM p
UNION ALL SELECT 'Operating expenses', -Opex FROM p
UNION ALL SELECT 'Other expense (net)', -Other FROM p
UNION ALL SELECT 'Tax expense', -Tax FROM p
"@ 0.02

# Budget variance: the z-score heatmap, department x month. The plan is noisy at line
# level, so the page shades a month only when it leaves that department's own range.
Grouped "Report" "Variance z-score by department and month (FY26)" @"
EVALUATE
CALCULATETABLE (
    FILTER (
        SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimDate[YearMonthLabel], "v", [Opex vs Budget Z-Score] ),
        NOT ISBLANK ( [v] )
    ),
    DimDate[FinancialYear] = "FY26"
)
"@ @"
WITH m AS (
    SELECT dp.DepartmentName, f.MonthStart,
           SUM(CASE WHEN f.VersionID = 'BUD' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END) AS bud,
           SUM(CASE WHEN f.VersionID = 'ACT' AND a.AccountGroup = 'Operating Expense' THEN f.AmountAUD END) AS act
    FROM dbo.FactFinancials f
    JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
    JOIN dbo.DimDepartment dp ON dp.DepartmentID = f.DepartmentID
    GROUP BY dp.DepartmentName, f.MonthStart),
v AS (SELECT DepartmentName, MonthStart, (CAST(bud AS FLOAT) - act) / NULLIF(bud, 0) AS varpct FROM m),
z AS (
    SELECT c.DepartmentName, c.MonthStart, c.varpct,
           AVG(h.varpct) AS mu, STDEV(h.varpct) AS sd, COUNT(h.varpct) AS n
    FROM v c JOIN v h ON h.DepartmentName = c.DepartmentName
         AND h.MonthStart < c.MonthStart AND h.MonthStart >= DATEADD(MONTH, -12, c.MonthStart)
    GROUP BY c.DepartmentName, c.MonthStart, c.varpct)
SELECT z.DepartmentName, d.YearMonthLabel, (z.varpct - z.mu) / NULLIF(z.sd, 0) AS v
FROM z JOIN dbo.DimDate d ON d.[Date] = z.MonthStart
WHERE d.FinancialYear = 'FY26' AND z.n >= 6 AND z.sd > 0 AND z.varpct IS NOT NULL
"@ 0.000001

# Cost centres: the treemap's grain
Grouped "Report" "Operating expense by department and account (FY26)" @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimAccount[AccountName], "v", [Operating Expense] ),
    DimDate[FinancialYear] = "FY26"
)
"@ @"
SELECT dp.DepartmentName, a.AccountName, $OPEX AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26' AND a.AccountGroup = 'Operating Expense'
GROUP BY dp.DepartmentName, a.AccountName
"@ 0.02

# Income statement: the cost-mix column, which must exclude revenue
Grouped "Report" "Cost mix by entity and group (FY26)" @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimEntity[EntityName], DimAccount[AccountGroup], "v", [Account Amount] ),
    DimDate[FinancialYear] = "FY26",
    DimAccount[AccountGroup] IN { "COGS", "Operating Expense", "Other Expense", "Tax" }
)
"@ @"
SELECT e.EntityName, a.AccountGroup, SUM(f.AmountAUD * a.NaturalSign) AS v $PLJOIN
WHERE f.VersionID = 'ACT' AND d.FinancialYear = 'FY26'
  AND a.AccountGroup IN ('COGS', 'Operating Expense', 'Other Expense', 'Tax')
GROUP BY e.EntityName, a.AccountGroup
"@ 0.02

# Scenario: the sensitivity curve and the outlook by entity
Grouped "Report" "Profit sensitivity by revenue step (base scenario)" @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimSensitivityStep[StepLabel], "v", [Sensitivity Operating Profit] ),
    DimScenario[ScenarioName] = "Base"
)
"@ @"
WITH ytd AS (
    SELECT f.EntityID, $REV AS Revenue, $COGS AS Cogs, $OPEX AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = 0 GROUP BY f.EntityID),
run AS (
    SELECT f.EntityID, $REV / 12.0 AS Revenue, $COGS / 12.0 AS Cogs, $OPEX / 12.0 AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0 GROUP BY f.EntityID)
SELECT st.StepLabel,
       SUM(COALESCE(ytd.Revenue, 0) + 10 * COALESCE(run.Revenue, 0) * (1 + st.StepPct))
     - SUM(COALESCE(ytd.Cogs, 0) + 10 * COALESCE(run.Cogs, 0) * (1 + st.StepPct))
     - SUM(COALESCE(ytd.Opex, 0) + 10 * COALESCE(run.Opex, 0)) AS v
FROM dbo.DimSensitivityStep st
JOIN dbo.DimEntity e ON 1 = 1
LEFT JOIN ytd ON ytd.EntityID = e.EntityID
LEFT JOIN run ON run.EntityID = e.EntityID
GROUP BY st.StepLabel
"@ 0.5

Grouped "Report" "Outlook operating profit by entity (base scenario)" @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [Outlook Operating Profit] ),
    DimScenario[ScenarioName] = "Base"
)
"@ @"
WITH ytd AS (
    SELECT f.EntityID, $REV AS Revenue, $COGS AS Cogs, $OPEX AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.FinancialYearOffset = 0 GROUP BY f.EntityID),
run AS (
    SELECT f.EntityID, $REV / 12.0 AS Revenue, $COGS / 12.0 AS Cogs, $OPEX / 12.0 AS Opex
    $PLJOIN WHERE f.VersionID = 'ACT' AND d.MonthOffset BETWEEN -11 AND 0 GROUP BY f.EntityID)
SELECT e.EntityName,
       (COALESCE(ytd.Revenue, 0) + 10 * COALESCE(run.Revenue, 0))
     - (COALESCE(ytd.Cogs, 0) + 10 * COALESCE(run.Cogs, 0))
     - (COALESCE(ytd.Opex, 0) + 10 * COALESCE(run.Opex, 0)) AS v
FROM dbo.DimEntity e
LEFT JOIN ytd ON ytd.EntityID = e.EntityID
LEFT JOIN run ON run.EntityID = e.EntityID
"@ 0.5

# Working capital: the month-end balance line, the entity bars and the customer table
Grouped "Report" "Receivables balance at each month end (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDate[YearMonthLabel], "v", [AR Balance] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT d.YearMonthLabel, SUM(i.InvoiceAmountAUD) AS v
FROM dbo.DimDate d
JOIN dbo.FactARInvoice i ON i.InvoiceDate <= d.MonthEnd AND (i.PaidDate IS NULL OR i.PaidDate > d.MonthEnd)
WHERE d.FinancialYear = 'FY26' AND d.[Date] = d.MonthEnd
GROUP BY d.YearMonthLabel
"@ 0.02

Grouped "Report" "DSO by entity (as-of date)" @"
EVALUATE SUMMARIZECOLUMNS ( DimEntity[EntityName], "v", [DSO (Days)] )
"@ @"
SELECT e.EntityName,
       CAST(SUM(CASE WHEN i.InvoiceDate <= k.AsOf AND (i.PaidDate IS NULL OR i.PaidDate > k.AsOf)
                     THEN i.InvoiceAmountAUD END) AS FLOAT)
     / NULLIF(SUM(CASE WHEN i.InvoiceDate > DATEADD(DAY, -90, k.AsOf) AND i.InvoiceDate <= k.AsOf
                       THEN i.InvoiceAmountAUD END), 0) * 90 AS v
FROM dbo.FactARInvoice i
JOIN dbo.DimEntity e ON e.EntityID = i.EntityID
CROSS JOIN (SELECT CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate') k
GROUP BY e.EntityName
"@ 0.0001

Grouped "Report" "Ten largest outstanding customer balances" @"
EVALUATE
TOPN ( 10, SUMMARIZECOLUMNS ( DimCustomer[CustomerName], "v", [AR Balance] ), [v], DESC )
"@ @"
SELECT TOP 10 c.CustomerName, SUM(i.InvoiceAmountAUD) AS v
FROM dbo.FactARInvoice i
JOIN dbo.DimCustomer c ON c.CustomerID = i.CustomerID
CROSS JOIN (SELECT CONVERT(DATE, ConfigValue, 23) AS AsOf FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate') k
WHERE i.InvoiceDate <= k.AsOf AND (i.PaidDate IS NULL OR i.PaidDate > k.AsOf)
GROUP BY c.CustomerName ORDER BY SUM(i.InvoiceAmountAUD) DESC
"@ 0.02

# Cash & FX: the cash line and the growth columns
Grouped "Report" "Group cash at each month end (FY26)" @"
EVALUATE
CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDate[YearMonthLabel], "v", [Cash Balance] ), DimDate[FinancialYear] = "FY26" )
"@ @"
SELECT d.YearMonthLabel, SUM(c.ClosingCashAUD) AS v
FROM dbo.DimDate d JOIN dbo.FactCashBalance c ON c.[Date] = d.MonthEnd
WHERE d.FinancialYear = 'FY26' AND d.[Date] = d.MonthEnd
GROUP BY d.YearMonthLabel
"@ 0.02

# ------------------------------------------------------------- 3. security ---
Write-Host "`n== 3. SECURITY: the role's default and its mapping logic ==" -ForegroundColor Yellow
# Secure default: the Windows user running this is not in the mapping table, so the
# role's own filter expression must yield nothing.
$roleConn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection(
    "Data Source=localhost:$($script:port);Initial Catalog=$($script:cat);Roles=Entity and Department Access")
$roleConn.Open()
$r = Dax "EVALUATE ROW ( ""n"", COALESCE ( COUNTROWS ( DimEntity ), 0 ) )" $roleConn
Check "Security" "an unmapped user sees no entities" $r.Rows[0][0] 0 0
$r = Dax "EVALUATE ROW ( ""v"", COALESCE ( [Revenue], 0 ) )" $roleConn
Check "Security" "an unmapped user sees no revenue" $r.Rows[0][0] 0 0
$roleConn.Close()

# The mapping logic itself, evaluated per user exactly as the role expression does.
$users = Sql "SELECT UserEmail, [Role], EntityID, DepartmentID FROM dbo.SecurityUserAccess ORDER BY UserEmail"
foreach ($u in $users.Rows) {
    $email = $u["UserEmail"]; $ent = $u["EntityID"]; $dep = $u["DepartmentID"]
    $expectedEntities = if ($ent -eq "ALL") { 6 } else { 1 }
    $expectedDepts = if ($dep -eq "ALL") { 10 } else { 1 }
    $d = Dax @"
EVALUATE
ROW (
    "entities",
        COUNTROWS (
            FILTER (
                DimEntity,
                VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[EntityID] ), SecurityUserAccess[UserEmail] = "$email" )
                RETURN "ALL" IN UserScope || DimEntity[EntityID] IN UserScope
            )
        ),
    "departments",
        COUNTROWS (
            FILTER (
                DimDepartment,
                VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[DepartmentID] ), SecurityUserAccess[UserEmail] = "$email" )
                RETURN "ALL" IN UserScope || DimDepartment[DepartmentID] IN UserScope
            )
        )
)
"@
    Check "Security" "$email sees entities" $d.Rows[0][0] $expectedEntities 0
    Check "Security" "$email sees departments" $d.Rows[0][1] $expectedDepts 0
}
# A department-scoped user must see no receivables, payables or cash.
$d = Dax @"
EVALUATE
ROW (
    "treasuryVisible",
        VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[DepartmentID] ), SecurityUserAccess[UserEmail] = "sales@northstar.demo" )
        RETURN IF ( "ALL" IN UserScope, 1, 0 )
)
"@
Check "Security" "a department manager sees no receivables, payables or cash" $d.Rows[0][0] 0 0

# ---------------------------------------------------------------- report ---
$conn.Close(); $sql.Close()
$script:rows | Export-Csv -NoTypeInformation -Path (Join-Path $PSScriptRoot "reconcile_results.csv")
$byArea = $script:rows | Group-Object Area | Sort-Object Name
foreach ($g in $byArea) {
    $f = @($g.Group | Where-Object Result -eq "FAIL").Count
    $colour = if ($f) { "Red" } else { "Green" }
    Write-Host ("  {0,-12} {1,5} passed  {2,3} failed" -f $g.Name, ($g.Count - $f), $f) -ForegroundColor $colour
}
Write-Host ("`nRECONCILIATION: {0} of {1} checks passed" -f $script:pass, ($script:pass + $script:fail)) -ForegroundColor Cyan
if ($script:fail) { exit 1 }
exit 0
