param([Parameter(Mandatory = $true)][string]$QueryFile)
$ErrorActionPreference = "Stop"
$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
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
        if ($cat) { $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat"); $conn.Open(); break }
    } catch {}
}
if (-not $conn) { throw "no live model" }

$blocks = (Get-Content -Raw $QueryFile) -split "(?m)^---\s*$"
$rows = @()
foreach ($b in $blocks) {
    $b = $b.Trim(); if (-not $b) { continue }
    $lines = $b -split "`n"
    $meta = $lines[0].TrimStart("/", " ")
    $nofields = $meta.StartsWith("NOFIELDS ")
    if ($nofields) { $meta = $meta.Substring(9) }
    $body = ($lines | Select-Object -Skip 1) -join "`n"
    $parts = $meta -split "\|\|"
    $page = $parts[0].Trim(); $vid = $parts[1].Trim(); $vtype = $parts[2].Trim()
    $title = ""; if ($parts.Count -gt 3) { $title = $parts[3].Trim() }

    if ($nofields) {
        # textboxes and page navigators legitimately carry no fields
        $verdict = "PASS"; $note = "static visual (no data bindings required)"
        if ($vtype -notin @("textbox", "pageNavigator", "image", "shape", "actionButton")) {
            $verdict = "FAIL"; $note = "NO FIELD BINDINGS - would show 'Select or drag fields'"
        }
        $rows += [pscustomobject]@{ Page = $page; Visual = $vid; Type = $vtype; Title = $title; Rows = 0; Verdict = $verdict; Note = $note }
        continue
    }
    try {
        $cmd = $conn.CreateCommand(); $cmd.CommandText = $body
        $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
        $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt)
        $n = $dt.Rows.Count
        $mcols = @(); foreach ($c in $dt.Columns) { if ($c.ColumnName -match "^\[M\d+\]$") { $mcols += $c.ColumnName } }
        $nonNull = 0
        foreach ($r in $dt.Rows) { foreach ($mc in $mcols) { if (-not ($r[$mc] -is [System.DBNull])) { $nonNull++ } } }
        if ($n -eq 0) {
            $verdict = "FAIL"; $note = "query returned 0 rows - visual renders empty"
        } elseif ($mcols.Count -gt 0 -and $nonNull -eq 0) {
            $verdict = "FAIL"; $note = "all $($mcols.Count) measure value(s) blank across $n row(s)"
        } elseif ($mcols.Count -eq 0) {
            $verdict = "PASS"; $note = "$n category value(s) (slicer)"
        } else {
            $verdict = "PASS"; $note = "$n row(s), $nonNull non-blank measure value(s)"
        }
    } catch {
        $verdict = "FAIL"; $note = "QUERY ERROR: " + ($_.Exception.Message -replace "`n", " ")
    }
    $rows += [pscustomobject]@{ Page = $page; Visual = $vid; Type = $vtype; Title = $title; Rows = $n; Verdict = $verdict; Note = $note }
}
$conn.Close()

foreach ($pg in ($rows | Select-Object -ExpandProperty Page -Unique)) {
    Write-Host ""
    Write-Host "==== $pg ====" -ForegroundColor Yellow
    foreach ($r in ($rows | Where-Object { $_.Page -eq $pg })) {
        $col = "Green"; if ($r.Verdict -eq "FAIL") { $col = "Red" }
        $t = $r.Title; if (-not $t) { $t = "(untitled)" }
        Write-Host ("  [{0}] {1,-22} {2,-42} {3}" -f $r.Verdict, $r.Type, $t, $r.Note) -ForegroundColor $col
    }
}
$f = ($rows | Where-Object { $_.Verdict -eq "FAIL" }).Count
Write-Host ""
Write-Host ("VISUALS: {0} total, {1} PASS, {2} FAIL" -f $rows.Count, ($rows.Count - $f), $f) -ForegroundColor Cyan
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path (Split-Path $QueryFile) "visual_check_results.csv")
