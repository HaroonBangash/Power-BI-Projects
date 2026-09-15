<#
    Executes every visual's reconstructed query against the live Power BI model and
    reports PASS (returns data) or FAIL (empty, all-blank, or query error).

    Usage:  python Validation\generate_visual_queries.py > $env:TEMP\q.dax
            powershell -ExecutionPolicy Bypass -File Validation\validate_visuals.ps1 -QueryFile $env:TEMP\q.dax
#>
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
if (-not $conn) { throw "No live Power BI model." }

$STATIC = @("textbox", "pageNavigator", "image", "shape", "actionButton")
$rows = @()
foreach ($b in ((Get-Content -Raw $QueryFile) -split "(?m)^---\s*$")) {
    $b = $b.Trim(); if (-not $b) { continue }
    $lines = $b -split "`n"; $meta = $lines[0].TrimStart("/", " ")
    $nofields = $meta.StartsWith("NOFIELDS "); if ($nofields) { $meta = $meta.Substring(9) }
    $parts = $meta -split "\|\|"
    $page = $parts[0].Trim(); $vid = $parts[1].Trim(); $vtype = $parts[2].Trim(); $title = $parts[3].Trim()
    $n = 0
    if ($nofields) {
        if ($STATIC -contains $vtype) { $verdict = "PASS"; $note = "static visual" } else { $verdict = "FAIL"; $note = "NO FIELD BINDINGS" }
    } else {
        try {
            $cmd = $conn.CreateCommand(); $cmd.CommandText = (($lines | Select-Object -Skip 1) -join "`n")
            $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
            $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt)
            $n = $dt.Rows.Count
            $mcols = @($dt.Columns | Where-Object { $_.ColumnName -match "^\[M\d+\]$" } | ForEach-Object { $_.ColumnName })
            $nonNull = 0; foreach ($r in $dt.Rows) { foreach ($mc in $mcols) { if (-not ($r[$mc] -is [System.DBNull])) { $nonNull++ } } }
            if ($n -eq 0) { $verdict = "FAIL"; $note = "0 rows" }
            elseif ($mcols.Count -gt 0 -and $nonNull -eq 0) { $verdict = "FAIL"; $note = "all measures blank" }
            else { $verdict = "PASS"; $note = "$n row(s), $nonNull non-blank value(s)" }
        } catch { $verdict = "FAIL"; $note = "QUERY ERROR: " + ($_.Exception.Message -replace "`r?`n", " ") }
    }
    $rows += [pscustomobject]@{ Page = $page; Type = $vtype; Title = $title; Verdict = $verdict; Note = $note }
}
$conn.Close()
foreach ($r in $rows) {
    $col = "Green"; if ($r.Verdict -eq "FAIL") { $col = "Red" }
    Write-Host ("  [{0}] {1,-30} {2,-30} {3}" -f $r.Verdict, $r.Page.Substring(0, [Math]::Min(30, $r.Page.Length)), $r.Type, $r.Note) -ForegroundColor $col
}
$f = @($rows | Where-Object Verdict -eq "FAIL").Count
Write-Host ("VISUALS: {0} total, {1} PASS, {2} FAIL" -f $rows.Count, ($rows.Count - $f), $f) -ForegroundColor Cyan
if ($f) { exit 1 }
exit 0
