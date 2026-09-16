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
if (-not $cat) { throw "No live Power BI model. Open SaaSRevenue.pbip first." }
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
    "Executive: MRR at every month end" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [MRR] )
"@
    "Movement: the waterfall, five components" = @"
EVALUATE SUMMARIZECOLUMNS ( DimMovementType[MovementType], "v", [MRR Movement (All Components)] )
"@
    "Movement: won and lost every month" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "a", [New MRR], "b", [Churned MRR], "c", [MRR] )
"@
    "Retention: the cohort matrix, 54 cohorts x 56 months" = @"
EVALUATE SUMMARIZECOLUMNS ( DimCohort[CohortLabel], DimTenureMonth[TenureLabel], "v", [Cohort Retention %] )
"@
    "Retention: churn on both bases, every month" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "a", [Logo Churn %], "b", [Revenue Churn %] )
"@
    "Drivers: eleven correlations" = @"
EVALUATE SUMMARIZECOLUMNS ( ChurnDriverStrength[Driver], "r", [Driver Correlation], "n", [Driver Customers] )
"@
    "Customers: top 15 by MRR with tickets and failures" = @"
EVALUATE
TOPN ( 15, SUMMARIZECOLUMNS ( DimCustomer[CustomerName], "v", [MRR], "t", [Tickets], "f", [Failed Invoices] ), [v] )
"@
    "Economics: payback by plan" = @"
EVALUATE SUMMARIZECOLUMNS ( DimPlan[PlanName], "v", [CAC Payback (Months)], "l", [LTV to CAC] )
"@
    "Product: adoption and utilisation every month" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "a", [Seat Utilisation %], "b", [Feature Adoption %] )
"@
    "The calculation group over every month" = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], 'Time Comparison'[Comparison], "v", [MRR] )
"@
}
foreach ($name in $queries.Keys) {
    $times = @()
    $rows = 0
    for ($i = 0; $i -lt 3; $i++) { $r = RunDax $queries[$name]; $times += $r.Ms; $rows = $r.Rows }
    Write-Host ("  {0,-46} {1,7:n0} ms (median of 3), {2,4} rows" -f $name, (Median $times), $rows)
}

Write-Host "`n== 3. why the monthly snapshot exists ==" -ForegroundColor Yellow
# The snapshot is 320,294 rows built from 12,000 subscriptions, which looks like a poor
# trade until you ask for MRR at every month end. Without it, every month has to scan
# every subscription and test its start and end dates - the query below is what the
# model would have to do, and the difference is why FactSubscriptionMonth exists.
$snapshot = @"
EVALUATE SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [MRR] )
"@
$onthefly = @"
EVALUATE
SUMMARIZECOLUMNS (
    DimDate[MonthStart],
    "v",
        VAR MonthEndDate = MAX ( DimDate[MonthEnd] )
        RETURN
            CALCULATE (
                SUM ( FactSubscription[MRR] ),
                FILTER (
                    ALL ( FactSubscription ),
                    FactSubscription[StartDate] <= MonthEndDate
                        && ( ISBLANK ( FactSubscription[EndDate] ) || FactSubscription[EndDate] > MonthEndDate )
                )
            )
)
"@
$snapTimes = @(); $flyTimes = @()
for ($i = 0; $i -lt 3; $i++) { $snapTimes += (RunDax $snapshot).Ms; $flyTimes += (RunDax $onthefly).Ms }
Write-Host ("  MRR at every month end, from the snapshot   (320,294 rows): {0,6:n0} ms" -f (Median $snapTimes))
Write-Host ("  the same, computed from dates at query time ( 12,000 subs): {0,6:n0} ms" -f (Median $flyTimes))

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
