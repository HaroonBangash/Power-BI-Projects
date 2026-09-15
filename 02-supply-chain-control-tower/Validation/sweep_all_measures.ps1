# Evaluate every measure in the model in isolation and report which ones error.
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
if (-not $conn) { throw "no model" }

function Q($dax) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $dax
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return ,$dt
}

$tmdl = Join-Path $PSScriptRoot "..\PowerBI\SupplyChainControlTower.SemanticModel\definition\tables\_Measures.tmdl"
$names = @()
foreach ($ln in (Get-Content -LiteralPath $tmdl)) {
    if ($ln -match "^\tmeasure\s+'([^']+)'\s*=") { $names += $Matches[1] }
    elseif ($ln -match "^\tmeasure\s+([^\s=]+)\s*=") { $names += $Matches[1] }
}
Write-Host "Measures found: $($names.Count)"

$bad = @(); $blank = @(); $good = 0
foreach ($n in $names) {
    $esc = $n.Replace("]", "]]")
    try {
        $d = Q ("EVALUATE ROW ( ""v"", [" + $esc + "] )")
        $v = $d.Rows[0][0]
        if ($v -is [System.DBNull]) { $blank += $n } else { $good++ }
    } catch {
        $msg = $_.Exception.Message
        if ($msg -match "MdxScript\(Model\) \((\d+), (\d+)\)") { $msg = "script error at " + $Matches[0] }
        $bad += [pscustomobject]@{ Measure = $n; Error = $msg }
    }
}
Write-Host ""
Write-Host ("Evaluated OK (non-blank): {0}" -f $good) -ForegroundColor Green
Write-Host ("Evaluated OK (blank at grand total, may be legitimate): {0}" -f $blank.Count) -ForegroundColor Yellow
if ($blank.Count) { $blank | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow } }
Write-Host ("ERRORED: {0}" -f $bad.Count) -ForegroundColor Red
if ($bad.Count) { $bad | ForEach-Object { Write-Host ("    {0}  ::  {1}" -f $_.Measure, $_.Error) -ForegroundColor Red } }
$conn.Close()
