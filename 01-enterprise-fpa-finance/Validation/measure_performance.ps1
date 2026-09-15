<#
    Performance evidence, run with Power BI Desktop open and refreshed.

    1 REFRESH    a full refresh through the engine, timed
    2 QUERIES    the heaviest query behind each page, run three times; the median is
                 reported, because the first run pays for cold caches
    3 AGGREGATION the same figure from the monthly fact and from the line-level ledger,
                 which is the reason FactFinancials exists
    4 STORAGE    what the model actually costs in memory, column by column (VertiPaq),
                 so the expensive columns are a fact rather than a guess

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\measure_performance.ps1
#>
$ErrorActionPreference = "Stop"
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

function RunDax($q) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    [void]$da.Fill($dt)
    $sw.Stop()
    return @{ Ms = $sw.Elapsed.TotalMilliseconds; Rows = $dt.Rows.Count }
}
function Median($values) {
    $s = $values | Sort-Object
    return $s[[int]([Math]::Floor($s.Count / 2))]
}

Write-Host "== 1. full refresh through the engine ==" -ForegroundColor Yellow
$cmd = $conn.CreateCommand()
$cmd.CommandText = '{"refresh":{"type":"full","objects":[{"database":"' + $cat + '"}]}}'
$sw = [System.Diagnostics.Stopwatch]::StartNew()
[void]$cmd.ExecuteNonQuery()
$sw.Stop()
Write-Host ("  full refresh of every table: {0:n1} s" -f $sw.Elapsed.TotalSeconds)

Write-Host "`n== 2. the heaviest query behind each page ==" -ForegroundColor Yellow
$queries = [ordered]@{
    "Executive: revenue vs budget by month" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "a", [Revenue Actual], "b", [Revenue Budget] )
"@
    "Statement: the statement x four versions" = @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimPLLine[LineName], 'Plan Version'[Version], "v", [P&L Line Value] ),
    DimDate[FinancialYear] = "FY26",
    'Plan Version'[Version] IN { "Actual", "Budget", "Var vs Budget", "Var % vs Budget" }
)
"@
    "Variance: z-score heatmap, department x month" = @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimDate[MonthShort], "z", [Opex vs Budget Z-Score] ),
    DimDate[FinancialYear] = "FY26"
)
"@
    "Cost centres: treemap, department x account" = @"
EVALUATE
CALCULATETABLE (
    SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimAccount[AccountName], "v", [Operating Expense] ),
    DimDate[FinancialYear] = "FY26"
)
"@
    "Scenario: outlook by scenario" = @"
EVALUATE SUMMARIZECOLUMNS ( DimScenario[ScenarioName], "v", [Outlook Operating Profit] )
"@
    "Working capital: ageing buckets" = @"
EVALUATE SUMMARIZECOLUMNS ( DimAgeingBucket[BucketName], "ar", [AR Ageing Amount], "ap", [AP Ageing Amount] )
"@
    "Working capital: balance at every month end" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonthLabel], "ar", [AR Balance], "ap", [AP Balance] )
"@
    "Cash & FX: rates by month and currency" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], FxRateMonthly[CurrencyCode], "v", [Average FX Rate] )
"@
}
foreach ($name in $queries.Keys) {
    $times = @()
    $rows = 0
    for ($i = 0; $i -lt 3; $i++) { $r = RunDax $queries[$name]; $times += $r.Ms; $rows = $r.Rows }
    Write-Host ("  {0,-46} {1,7:n0} ms (median of 3), {2,4} rows" -f $name, (Median $times), $rows)
}

Write-Host "`n== 3. why the monthly fact exists ==" -ForegroundColor Yellow
$agg = @"
EVALUATE
SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimDate[YearMonthLabel], "v", [Operating Expense] )
"@
$detail = @"
EVALUATE
SUMMARIZECOLUMNS ( DimDepartment[DepartmentName], DimDate[YearMonthLabel], "v", [GL Amount (AUD)] )
"@
$aggTimes = @(); $detTimes = @()
for ($i = 0; $i -lt 3; $i++) { $aggTimes += (RunDax $agg).Ms; $detTimes += (RunDax $detail).Ms }
Write-Host ("  department x month from FactFinancials (168,782 rows): {0,6:n0} ms" -f (Median $aggTimes))
Write-Host ("  department x month from FactGL         ( 80,000 lines): {0,6:n0} ms" -f (Median $detTimes))

Write-Host "`n== 4. what the model costs in memory ==" -ForegroundColor Yellow
$cmd = $conn.CreateCommand()
# The segment DMV names the column COLUMN_ID (ATTRIBUTE_NAME belongs to a different
# DMV), and it does not take a WHERE clause, so the filtering happens here.
$cmd.CommandText = 'SELECT DIMENSION_NAME, COLUMN_ID, USED_SIZE FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS' 
$da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable; [void]$da.Fill($dt)
$rows = $dt.Rows | Where-Object { $_.USED_SIZE -gt 0 }
$total = ($rows | Measure-Object -Property USED_SIZE -Sum).Sum
Write-Host ("  column data in memory: {0:n1} MB across {1} segments" -f ($total / 1MB), $rows.Count)
$rows | Group-Object DIMENSION_NAME | ForEach-Object {
    [pscustomobject]@{ Table = $_.Name; MB = (($_.Group | Measure-Object -Property USED_SIZE -Sum).Sum / 1MB) }
} | Sort-Object MB -Descending | Select-Object -First 6 | ForEach-Object {
    Write-Host ("    {0,-22} {1,6:n2} MB" -f $_.Table, $_.MB)
}
Write-Host "  largest columns:"
$rows | Group-Object DIMENSION_NAME, COLUMN_ID | ForEach-Object {
    [pscustomobject]@{ Column = $_.Name; MB = (($_.Group | Measure-Object -Property USED_SIZE -Sum).Sum / 1MB) }
} | Sort-Object MB -Descending | Select-Object -First 6 | ForEach-Object {
    Write-Host ("    {0,-46} {1,6:n2} MB" -f $_.Column, $_.MB)
}
$conn.Close()
