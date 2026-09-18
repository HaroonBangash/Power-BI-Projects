<#
    Runs one DAX query (inline or from a file) against the live Power BI model.
    Usage:  powershell -File Validation\run_dax.ps1 -Query "EVALUATE ROW(""v"", [Revenue])"
            powershell -File Validation\run_dax.ps1 -File q.dax
#>
param([string]$Query, [string]$File)
$ErrorActionPreference = "Stop"
if ($File) { $Query = Get-Content -Raw $File }
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
$cmd = $conn.CreateCommand(); $cmd.CommandText = $Query
$da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
[void]$da.Fill($dt)
$dt | Format-Table -AutoSize | Out-String -Width 250
$conn.Close()
