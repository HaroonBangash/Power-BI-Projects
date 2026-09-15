<#
    Live validation of report Pages 7, 8 and 9 against the running Power BI model.

    Every expected value below was derived INDEPENDENTLY from SQL Server
    (Validation/expected_*.sql) before the DAX was queried. Nothing is copied
    from a report screenshot, and nothing is hard-coded into the model itself -
    the model must reproduce these numbers on its own.

    Requires: Power BI Desktop open with SupplyChainControlTower.pbip loaded
              and the model refreshed (so calculated tables are processed).

    Usage:    powershell -ExecutionPolicy Bypass -File validate_pages_7_8_9.ps1
#>

$ErrorActionPreference = "Stop"
$script:pass = 0; $script:fail = 0; $script:results = @()

# ---------------------------------------------------------------- connect ---
$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dll) { throw "ADOMD.NET client not found." }
Add-Type -Path $dll.FullName

$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
if (-not (Test-Path $wsRoot)) { throw "No Power BI Desktop workspace folder. Is Power BI Desktop open?" }

$conn = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    $port = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
    try {
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
        $c.Open()
        $cmd = $c.CreateCommand()
        $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $cat = $null
        if ($rd.Read()) { $cat = $rd.GetValue(0) }
        $rd.Close(); $c.Close()
        if ($cat) {
            $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
            $conn.Open()
            Write-Host "Connected: localhost:$port  catalog=$cat" -ForegroundColor Cyan
            break
        }
    } catch { }
}
if (-not $conn) { throw "Could not connect to a Power BI Desktop model. Open the .pbip and refresh first." }

function Invoke-Dax([string]$dax) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $dax
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable
    [void]$da.Fill($dt)
    return ,$dt
}

function Check($name, $actual, $expected, $tol) {
    if ($null -eq $tol) { $tol = 0 }
    $ok = $false
    if ($expected -is [string]) {
        $ok = ("$actual" -eq "$expected")
    } else {
        if ($null -ne $actual -and "$actual" -ne "") {
            $ok = ([Math]::Abs([double]$actual - [double]$expected) -le [double]$tol)
        }
    }
    if ($ok) { $script:pass++; $tag = "PASS" } else { $script:fail++; $tag = "FAIL" }
    $script:results += [pscustomobject]@{ Result = $tag; Check = $name; Expected = $expected; Actual = $actual }
    $col = "Green"; if (-not $ok) { $col = "Red" }
    Write-Host ("  [{0}] {1,-50} expected {2,-12} got {3}" -f $tag, $name, $expected, $actual) -ForegroundColor $col
}

function Cell($dt, $keyCol, $keyVal, $valCol) {
    foreach ($r in $dt.Rows) {
        if ("$($r[$keyCol])" -eq "$keyVal") { return $r[$valCol] }
    }
    return $null
}

function Cell2($dt, $k1, $v1, $k2, $v2, $valCol) {
    foreach ($r in $dt.Rows) {
        if ("$($r[$k1])" -eq "$v1" -and "$($r[$k2])" -eq "$v2") { return $r[$valCol] }
    }
    return $null
}

# ============================================================ PAGE 8 : ABC ===
Write-Host "`n=== PAGE 8 - ABC / XYZ INVENTORY STRATEGY ===" -ForegroundColor Yellow

Write-Host "`n-- ABC distribution (expect 512 / 279 / 209 at 79.99 / 14.98 / 5.04 %)"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( ABCClass[Class], "Products", [Products at ABC Class], "Revenue", [Revenue at ABC Class] )'
$totRev = 0.0
foreach ($r in $dt.Rows) { $totRev += [double]$r["[Revenue]"] }
foreach ($e in @(@("A", 512, 79.99), @("B", 279, 14.98), @("C", 209, 5.04))) {
    $cls = $e[0]
    Check "ABC $cls product count" (Cell $dt "ABCClass[Class]" $cls "[Products]") $e[1] 0
    $rv = [double](Cell $dt "ABCClass[Class]" $cls "[Revenue]")
    Check "ABC $cls revenue share %" ([Math]::Round(100 * $rv / $totRev, 2)) $e[2] 0.02
}

Write-Host "`n-- XYZ distribution (expect 167 / 166 / 167, plus 500 unclassified)"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( XYZClass[Class], "Products", [Products at XYZ Class] )'
Check "XYZ X count" (Cell $dt "XYZClass[Class]" "X" "[Products]") 167 0
Check "XYZ Y count" (Cell $dt "XYZClass[Class]" "Y" "[Products]") 166 0
Check "XYZ Z count" (Cell $dt "XYZClass[Class]" "Z" "[Products]") 167 0
$dt = Invoke-Dax 'EVALUATE ROW ( "U", [Unclassified Products] )'
Check "Unclassified products" $dt.Rows[0]["[U]"] 500 0

Write-Host "`n-- XYZ thresholds must NOT collapse under a per-product filter"
$dt = Invoke-Dax 'EVALUATE TOPN ( 3, SUMMARIZECOLUMNS ( DimProduct[ProductName], "P33", [XYZ P33 Threshold], "P66", [XYZ P66 Threshold] ), DimProduct[ProductName], ASC )'
foreach ($r in $dt.Rows) {
    Check ("P33 stable at '" + $r[0] + "'") ([Math]::Round([double]$r["[P33]"], 6)) 0.129674 0.000001
    Check ("P66 stable at '" + $r[0] + "'") ([Math]::Round([double]$r["[P66]"], 6)) 0.170917 0.000001
}

Write-Host "`n-- DEFECT 1: matrix cells (nine cells, must sum to 500)"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( ABCXYZClass[ABC], ABCXYZClass[XYZ], "Products", [Products at ABCXYZ Class] )'
$expCells = @{ "A|X" = 87; "A|Y" = 80; "A|Z" = 93; "B|X" = 47; "B|Y" = 51; "B|Z" = 43; "C|X" = 33; "C|Y" = 35; "C|Z" = 31 }
$cellSum = 0
foreach ($k in ($expCells.Keys | Sort-Object)) {
    $p = $k.Split("|")
    $v = Cell2 $dt "ABCXYZClass[ABC]" $p[0] "ABCXYZClass[XYZ]" $p[1] "[Products]"
    Check "matrix cell $($p[0])$($p[1])" $v $expCells[$k] 0
    if ($null -ne $v) { $cellSum += [int]$v }
}
Check "nine cells sum (no double-counting)" $cellSum 500 0

Write-Host "`n-- DEFECT 1: subtotals (these previously all read 500)"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( ABCXYZClass[ABC], "Products", [Products at ABCXYZ Class] )'
Check "ROW subtotal A" (Cell $dt "ABCXYZClass[ABC]" "A" "[Products]") 260 0
Check "ROW subtotal B" (Cell $dt "ABCXYZClass[ABC]" "B" "[Products]") 141 0
Check "ROW subtotal C" (Cell $dt "ABCXYZClass[ABC]" "C" "[Products]") 99 0
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( ABCXYZClass[XYZ], "Products", [Products at ABCXYZ Class] )'
Check "COLUMN subtotal X" (Cell $dt "ABCXYZClass[XYZ]" "X" "[Products]") 167 0
Check "COLUMN subtotal Y" (Cell $dt "ABCXYZClass[XYZ]" "Y" "[Products]") 166 0
Check "COLUMN subtotal Z" (Cell $dt "ABCXYZClass[XYZ]" "Z" "[Products]") 167 0
$dt = Invoke-Dax 'EVALUATE ROW ( "G", [Products at ABCXYZ Class] )'
Check "GRAND total" $dt.Rows[0]["[G]"] 500 0

Write-Host "`n-- DEFECT 2: contribution must not read 100% on every row"
$dt = Invoke-Dax 'EVALUATE TOPN ( 5, SUMMARIZECOLUMNS ( DimProduct[ProductName], "Rev", [Total Revenue], "Contrib", [Product Revenue Contribution %], "Cum", [Cumulative Revenue %], "Rank", [Product Revenue Rank] ), [Rev], DESC ) ORDER BY [Rev] DESC'
$i = 0; $prevCum = 0.0
foreach ($r in $dt.Rows) {
    $i++
    Check "row $i contribution below 100%" ([int]([double]$r["[Contrib]"] -lt 0.99)) 1 0
    Check "row $i revenue rank" $r["[Rank]"] $i 0
    $cum = [double]$r["[Cum]"]
    Check "row $i cumulative increasing" ([int]($cum -gt $prevCum)) 1 0
    $prevCum = $cum
}
$dt = Invoke-Dax 'EVALUATE ROW ( "S", SUMX ( VALUES ( DimProduct[ProductName] ), [Product Revenue Contribution %] ) )'
Check "contributions sum to 100%" ([Math]::Round([double]$dt.Rows[0]["[S]"], 4)) 1.0 0.0005

# ======================================================= PAGE 9 : SUPPLIER ===
Write-Host "`n=== PAGE 9 - SUPPLIER PERFORMANCE ===" -ForegroundColor Yellow

Write-Host "`n-- Class distribution (expect 9 / 32 / 63 / 16) and spend share"
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( SupplierClass[Class], "Suppliers", [Suppliers at Class], "Spend", [PO Value at Supplier Class] )'
$totSpend = 0.0
foreach ($r in $dt.Rows) { $totSpend += [double]$r["[Spend]"] }
foreach ($e in @(@("Excellent", 9, 6.65), @("Good", 32, 25.48), @("Needs Improvement", 63, 55.57), @("High Risk", 16, 12.30))) {
    Check "$($e[0]) supplier count" (Cell $dt "SupplierClass[Class]" $e[0] "[Suppliers]") $e[1] 0
    $sp = [double](Cell $dt "SupplierClass[Class]" $e[0] "[Spend]")
    Check "$($e[0]) spend share %" ([Math]::Round(100 * $sp / $totSpend, 2)) $e[2] 0.02
}

Write-Host "`n-- Four line-by-line supplier tests, one per class"
$dt = Invoke-Dax 'EVALUATE FILTER ( SUMMARIZECOLUMNS ( DimSupplier[SupplierID], "OnTimePct", [On-Time Receipt %], "LeadSd", [Supplier Lead Time Variability], "Defect", [Average Defect Rate], "OnTimeScore", [On-Time Receipt Score], "RelScore", [Lead-Time Reliability Score], "QualScore", [Quality Score], "Score", [Supplier Performance Score], "Rank", [Supplier Rank], "Class", [Supplier Performance Class] ), DimSupplier[SupplierID] IN { "S0014", "S0024", "S0117", "S0043" } )'
$cases = @(
    @{ id = "S0014"; ot = 0.4694; sd = 3.49; df = 0.02954; ots = 0.7829; rls = 1.0000; qls = 0.9761; sc = 89.75; rk = 1;   cl = "Excellent" },
    @{ id = "S0024"; ot = 0.4130; sd = 4.67; df = 0.03064; ots = 0.5427; rls = 0.8294; qls = 0.8206; sc = 69.87; rk = 10;  cl = "Good" },
    @{ id = "S0117"; ot = 0.4035; sd = 6.63; df = 0.03179; ots = 0.5021; rls = 0.5459; qls = 0.6575; sc = 54.85; rk = 42;  cl = "Needs Improvement" },
    @{ id = "S0043"; ot = 0.3653; sd = 9.21; df = 0.03644; ots = 0.3393; rls = 0.1721; qls = 0.0000; sc = 21.29; rk = 120; cl = "High Risk" }
)
foreach ($c in $cases) {
    $f = $c.id
    Check "$($c.id) on-time %"         ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[OnTimePct]"), 4))   $c.ot  0.0002
    Check "$($c.id) lead-time SD"      ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[LeadSd]"), 2))      $c.sd  0.01
    Check "$($c.id) defect rate"       ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[Defect]"), 5))      $c.df  0.00002
    Check "$($c.id) on-time score"     ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[OnTimeScore]"), 4)) $c.ots 0.0002
    Check "$($c.id) reliability score" ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[RelScore]"), 4))    $c.rls 0.0002
    Check "$($c.id) quality score"     ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[QualScore]"), 4))   $c.qls 0.0002
    Check "$($c.id) composite score"   ([Math]::Round([double](Cell $dt "DimSupplier[SupplierID]" $f "[Score]"), 2))       $c.sc  0.02
    Check "$($c.id) rank"              (Cell $dt "DimSupplier[SupplierID]" $f "[Rank]")                                    $c.rk  0
    Check "$($c.id) class"             (Cell $dt "DimSupplier[SupplierID]" $f "[Class]")                                   $c.cl
    # the composite must genuinely be the documented 45/35/20 blend, recomputed from its parts
    $w = 100 * (0.45 * [double](Cell $dt "DimSupplier[SupplierID]" $f "[OnTimeScore]") + 0.35 * [double](Cell $dt "DimSupplier[SupplierID]" $f "[RelScore]") + 0.20 * [double](Cell $dt "DimSupplier[SupplierID]" $f "[QualScore]"))
    Check "$($c.id) composite = 45/35/20 blend" ([Math]::Round($w, 2)) $c.sc 0.02
}

Write-Host "`n-- Scores must not blank out when grouped by SupplierName"
$dt = Invoke-Dax 'EVALUATE TOPN ( 5, SUMMARIZECOLUMNS ( DimSupplier[SupplierName], "Score", [Supplier Performance Score] ), [Score], DESC )'
$nonBlank = 0
foreach ($r in $dt.Rows) { if ("$($r['[Score]'])" -ne "") { $nonBlank++ } }
Check "top-5 by SupplierName return a score" $nonBlank 5 0

Write-Host "`n-- Performance Class slicer must genuinely filter"
$dt = Invoke-Dax 'EVALUATE CALCULATETABLE ( ROW ( "N", [Suppliers at Class] ), TREATAS ( { "Excellent" }, SupplierClass[Class] ) )'
Check "slicer Excellent -> Suppliers at Class" $dt.Rows[0]["[N]"] 9 0
$dt = Invoke-Dax 'EVALUATE CALCULATETABLE ( ROW ( "N", [Suppliers at Class] ), TREATAS ( { "High Risk" }, SupplierClass[Class] ) )'
Check "slicer High Risk -> Suppliers at Class" $dt.Rows[0]["[N]"] 16 0
$dt = Invoke-Dax 'EVALUATE CALCULATETABLE ( ROW ( "N", [Suppliers at Class] ), TREATAS ( { "Excellent", "Good" }, SupplierClass[Class] ) )'
Check "slicer multi-select Excellent+Good" $dt.Rows[0]["[N]"] 41 0

# ==================================================== PAGE 7 : REGRESSION ====
Write-Host "`n=== PAGE 7 - STOCKOUT & REPLENISHMENT (regression only) ===" -ForegroundColor Yellow
$dt = Invoke-Dax 'EVALUATE SUMMARIZECOLUMNS ( ReplenishmentStatus[Status], "Lines", [Lines at Status] )'
$sum = 0
foreach ($r in $dt.Rows) { $sum += [int]$r["[Lines]"] }
Check "status lines sum to product-warehouse grain" $sum 3000 0
$dt = Invoke-Dax 'EVALUATE ROW ( "R", [Products Requiring Reorder], "C", [Critical Products] )'
Check "Products Requiring Reorder unchanged" $dt.Rows[0]["[R]"] 178 0

# ------------------------------------------------------------------ report ---
$conn.Close()
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host ("RESULT: {0} passed, {1} failed, {2} total" -f $script:pass, $script:fail, ($script:pass + $script:fail)) -ForegroundColor Cyan
$out = Join-Path $PSScriptRoot "validation_results_pages_7_8_9.csv"
$script:results | Export-Csv -NoTypeInformation -Encoding UTF8 $out
Write-Host "Detail written to $out"
if ($script:fail -gt 0) {
    Write-Host "`nFAILURES:" -ForegroundColor Red
    $script:results | Where-Object { $_.Result -eq "FAIL" } | Format-Table -AutoSize
    exit 1
}
exit 0
