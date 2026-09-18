<#
    Builds HealthcareRCMBI end to end: 01 -> 08, in order, stopping at the
    first failure.

    The data folder is passed to 03_load_staging.sql as the sqlcmd variable
    DataRoot, resolved from this repository's location, so no machine-specific
    path is ever committed. BULK INSERT reads the files on the server side:
    the SQL Server service account needs read access to Data\raw.

    Usage:  powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1
            powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1 -Server "localhost\SQLEXPRESS"
#>
param([string]$Server = "")

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

# The server name lives in config.local.json (git-ignored) or is passed in, so
# no machine-specific instance name is committed either.
if (-not $Server) {
    $cfgPath = Join-Path $root "config.local.json"
    if (Test-Path $cfgPath) {
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        if ($cfg.sqlServer) { $Server = $cfg.sqlServer }
    }
}
if (-not $Server) { $Server = "localhost\SQLEXPRESS" }

$dataRoot = (Resolve-Path (Join-Path $root "Data\raw")).Path
Write-Host "Server   : $Server"
Write-Host "DataRoot : (repository)\Data\raw"
Write-Host ""

# Passed as an ENVIRONMENT variable, which sqlcmd resolves as $(DataRoot).
# `-v DataRoot=...` is rejected when the path contains spaces, and Windows
# PowerShell 5.1 strips the embedded quotes that would fix it.
$env:DataRoot = $dataRoot

$scripts = Get-ChildItem $PSScriptRoot -Filter "0*.sql" | Sort-Object Name
$total = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($s in $scripts) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host ("--- {0}" -f $s.Name) -ForegroundColor Cyan
    # -C trusts the local instance certificate; -b stops on the first error.
    sqlcmd -S $Server -C -b -I -i $s.FullName
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $($s.Name) (exit $LASTEXITCODE)" }
    Write-Host ("    ok in {0:N1} s" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
}
Write-Host ""
Write-Host ("All {0} scripts succeeded in {1:N1} s." -f $scripts.Count, $total.Elapsed.TotalSeconds) -ForegroundColor Green
