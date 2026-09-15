<#
    Opens SupplyChainControlTower.pbip in Power BI Desktop and refreshes the model through
    the engine, so nobody has to click Refresh.

      1. refuses to start while Power BI is already running, unless -Restart
         (Restart force-closes it WITHOUT saving - the files on disk stay authoritative)
      2. opens the project and waits for the new engine's port file
      3. waits 20 s: a refresh fired as soon as the port opens can hit the OLD schema
         while Desktop is still applying the TMDL (project 2, Phase 3 finding)
      4. TMSL full refresh over ADOMD, then prints every table's row count

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\open_powerbi.ps1 [-Restart]
#>
param([switch]$Restart, [int]$TimeoutSec = 420)
$ErrorActionPreference = "Stop"
$pbip = Join-Path $PSScriptRoot "..\PowerBI\SupplyChainControlTower.pbip" | Resolve-Path

if (Get-Process PBIDesktop -ErrorAction SilentlyContinue) {
    if (-not $Restart) { throw "Power BI Desktop is running. Close it, or pass -Restart to force-close it without saving." }
    Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 5
}

$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$started = Get-Date
Start-Process -FilePath $pbip
Write-Host "opened $pbip"

$port = $null; $cat = $null
while (-not $cat -and ((Get-Date) - $started).TotalSeconds -lt $TimeoutSec) {
    Start-Sleep -Seconds 3
    foreach ($ws in (Get-ChildItem $wsRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $started.AddSeconds(-5) })) {
        $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
        if (-not (Test-Path $pf)) { continue }
        try {
            $p = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
            $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$p")
            $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
            $rd = $cmd.ExecuteReader(); if ($rd.Read()) { $cat = $rd.GetValue(0); $port = $p }; $rd.Close(); $c.Close()
        } catch {}
    }
}
if (-not $cat) { throw "No Power BI engine came up within $TimeoutSec s." }
# A malformed TMDL makes Desktop open a blank "Untitled" document instead, whose
# engine has no tables at all. Fail loudly rather than "refresh" nothing.
$probe = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$probe.Open()
$pc = $probe.CreateCommand(); $pc.CommandText = 'SELECT [TABLE_NAME] FROM $SYSTEM.DBSCHEMA_TABLES'
$pr = $pc.ExecuteReader(); $n = 0; while ($pr.Read()) { $n++ }; $pr.Close(); $probe.Close()
if ($n -eq 0) { throw "The model loaded with NO tables - Power BI opened a blank document. Run Validation\parse_tmdl.ps1 for the TMDL error." }

Write-Host "engine on localhost:$port ($cat); settling 20 s before refresh"
Start-Sleep -Seconds 20

$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$conn.Open()
$cmd = $conn.CreateCommand()
$cmd.CommandText = '{"refresh":{"type":"full","objects":[{"database":"' + $cat + '"}]}}'
$t0 = Get-Date
[void]$cmd.ExecuteNonQuery()
Write-Host ("refreshed in {0:n1} s" -f ((Get-Date) - $t0).TotalSeconds)

# The table list is read FROM THE MODEL, not hard-coded: a table added to the
# generator then shows up here automatically instead of being silently unchecked.
# INFO.TABLES() is used rather than the DBSCHEMA DMV because it returns the tabular
# metadata directly, calculation groups included.
$tables = @()
$q = $conn.CreateCommand()
$q.CommandText = 'EVALUATE SELECTCOLUMNS ( INFO.TABLES (), "TableName", [Name] ) ORDER BY [TableName]'
$r = $q.ExecuteReader()
while ($r.Read()) {
    $n = $r.GetValue(0)
    if ($n -notlike 'LocalDateTable*' -and $n -notlike 'DateTableTemplate*') { $tables += $n }
}
$r.Close()

$unqueryable = @()
foreach ($t in $tables) {
    $q = $conn.CreateCommand(); $q.CommandText = "EVALUATE ROW ( ""n"", COUNTROWS ( '$t' ) )"
    try {
        $r = $q.ExecuteReader(); [void]$r.Read()
        $v = $r.GetValue(0); $r.Close()
        Write-Host ("  {0,-24} {1,10:n0}" -f $t, $v)
    } catch {
        Write-Host ("  {0,-24} {1,10}" -f $t, "no rows") -ForegroundColor Yellow
        $unqueryable += $t
    }
}
Write-Host ("{0} tables in the live model" -f $tables.Count)

$conn.Close()
