<#
    Live validation of report Page 10 - Demand Forecasting.

    Every expected value is derived independently in Validation/expected_forecast.sql
    and pasted here as a target. The model must reproduce them on its own.

    Requires Power BI Desktop open with the .pbip loaded.
    Usage: powershell -ExecutionPolicy Bypass -File validate_page_10.ps1
#>
$ErrorActionPreference = "Stop"
$script:pass = 0; $script:fail = 0; $script:results = @()

$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dll) { throw "ADOMD.NET client not found." }
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$conn = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    try {
        $port = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
        $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $cat = $null; if ($rd.Read()) { $cat = $rd.GetValue(0) }; $rd.Close(); $c.Close()
        if ($cat) { $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat"); $conn.Open(); Write-Host "Connected: localhost:$port" -ForegroundColor Cyan; break }
    } catch {}
}
if (-not $conn) { throw "Could not connect to a Power BI Desktop model." }

function Invoke-Dax([string]$dax) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $dax
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Check($name, $actual, $expected, $tol) {
    if ($null -eq $tol) { $tol = 0 }
    $ok = $false
    if ($expected -is [string]) { $ok = ("$actual" -eq "$expected") }
    elseif ($null -ne $actual -and "$actual" -ne "") { $ok = ([Math]::Abs([double]$actual - [double]$expected) -le [double]$tol) }
    if ($ok) { $script:pass++; $tag = "PASS" } else { $script:fail++; $tag = "FAIL" }
    $script:results += [pscustomobject]@{ Result = $tag; Check = $name; Expected = $expected; Actual = $actual }
    $col = "Green"; if (-not $ok) { $col = "Red" }
    Write-Host ("  [{0}] {1,-46} expected {2,-14} got {3}" -f $tag, $name, $expected, $actual) -ForegroundColor $col
}
function Cell($dt, $keyCol, $keyVal, $valCol) {
    foreach ($r in $dt.Rows) { if ("$($r[$keyCol])" -eq "$keyVal") { return $r[$valCol] } }
    return $null
}

Write-Host "`n=== PAGE 10 - DEMAND FORECASTING ===" -ForegroundColor Yellow

Write-Host "`n-- Headline KPI cards"
$dt = Invoke-Dax 'EVALUATE ROW ( "Actual", [Actual Demand Units], "Forecast", [Baseline Forecast Units], "WAPE", [Forecast WAPE], "Acc", [Forecast Accuracy %], "BiasU", [Forecast Bias Units], "BiasP", [Forecast Bias %], "MAE", [Forecast MAE], "Over", [Over-Forecast Weeks], "Under", [Under-Forecast Weeks], "Weeks", [Demand Weeks Covered] )'
$r = $dt.Rows[0]
Check "Actual Demand Units"      $r["[Actual]"]   6219403   0
Check "Baseline Forecast Units"  $r["[Forecast]"] 6062796   0
Check "Forecast WAPE"            ([Math]::Round([double]$r["[WAPE]"], 6))  0.130408 0.000002
Check "Forecast Accuracy %"      ([Math]::Round([double]$r["[Acc]"], 6))   0.869592 0.000002
Check "Forecast Bias Units"      $r["[BiasU]"]   (-156607)  0
Check "Forecast Bias %"          ([Math]::Round([double]$r["[BiasP]"], 6)) (-0.025180) 0.000002
Check "Forecast MAE"             ([Math]::Round([double]$r["[MAE]"], 6))   2.574784 0.000002
Check "Over-Forecast Weeks"      $r["[Over]"]     112853    0
Check "Under-Forecast Weeks"     $r["[Under]"]    157393    0
Check "Demand Weeks Covered"     $r["[Weeks]"]    105       0

Write-Host "`n-- Growth windows and product movement"
$dt = Invoke-Dax 'EVALUATE ROW ( "Recent", [Recent 13W Demand], "Prior", [Prior 13W Demand], "Growth", [Demand Growth %], "Grow", [Growing Products], "Decl", [Declining Products], "Stable", [Stable Demand Products], "Vol", [Volatile Products] )'
$r = $dt.Rows[0]
Check "Recent 13W Demand"        $r["[Recent]"]   723181    0
Check "Prior 13W Demand"         $r["[Prior]"]    631767    0
Check "Demand Growth %"          ([Math]::Round([double]$r["[Growth]"], 6)) 0.144696 0.000002
Check "Growing Products"         $r["[Grow]"]     432       0
Check "Declining Products"       $r["[Decl]"]     2         0
Check "Stable Demand Products"   $r["[Stable]"]   66        0
Check "Volatile Products (Z)"    $r["[Vol]"]      167       0
$sum = [int]$r["[Grow]"] + [int]$r["[Decl]"] + [int]$r["[Stable]"]
Check "growing+declining+stable reconciles" $sum 500 0

Write-Host "`n-- Forecast accuracy by category (the category column chart)"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( DimProduct[Category], "Acc", [Forecast Accuracy %], "Units", [Actual Demand Units] )'
$cats = @(@("Outdoor", 0.872837), @("Electronics", 0.870453), @("Industrial", 0.870398),
          @("Personal Care", 0.870121), @("Office", 0.868522), @("Home", 0.867239), @("Automotive", 0.867072))
foreach ($c in $cats) {
    Check "accuracy - $($c[0])" ([Math]::Round([double](Cell $dt "DimProduct[Category]" $c[0] "[Acc]"), 6)) $c[1] 0.000002
}
Check "category rows returned" $dt.Rows.Count 7 0

Write-Host "`n-- Trend line must return a month series with both measures"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonthLabel], "A", [Actual Demand Units], "F", [Baseline Forecast Units] )'
$nonBlank = 0
foreach ($row in $dt.Rows) { if (-not ($row["[A]"] -is [System.DBNull]) -and -not ($row["[F]"] -is [System.DBNull])) { $nonBlank++ } }
# 2024-09-02 .. 2026-08-31 spans Sep-2024 through Aug-2026 inclusive = 24 months.
Check "trend months with actual AND forecast" $nonBlank 24 0

Write-Host "`n-- No forecast exists beyond the as-of date (honesty check)"
$dt = Invoke-Dax 'EVALUATE ROW ( "MaxWeek", MAX ( FactWeeklyDemand[WeekStart] ), "AsOf", [As Of Date] )'
$mx = ([datetime]$dt.Rows[0]["[MaxWeek]"]).ToString("yyyy-MM-dd")
$ao = ([datetime]$dt.Rows[0]["[AsOf]"]).ToString("yyyy-MM-dd")
Check "latest demand week"  $mx "2026-08-31"
Check "as-of date"          $ao "2026-08-31"

Write-Host "`n-- Growth measure responds to the Category slicer"
$dt = Invoke-Dax 'EVALUATE CALCULATETABLE ( ROW ( "G", [Demand Growth %], "Grow", [Growing Products] ), TREATAS ( { "Electronics" }, DimProduct[Category] ) )'
$g = [double]$dt.Rows[0]["[G]"]
Check "Electronics growth differs from portfolio" ([int]([Math]::Abs($g - 0.144696) -gt 0.000001)) 1 0

$conn.Close()
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host ("RESULT: {0} passed, {1} failed, {2} total" -f $script:pass, $script:fail, ($script:pass + $script:fail)) -ForegroundColor Cyan
$script:results | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $PSScriptRoot "validation_results_page_10.csv")
if ($script:fail -gt 0) {
    Write-Host "`nFAILURES:" -ForegroundColor Red
    $script:results | Where-Object { $_.Result -eq "FAIL" } | Format-Table -AutoSize
    exit 1
}
exit 0
