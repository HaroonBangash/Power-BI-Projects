<#
    Renders report pages one at a time and captures each.

    Power BI Desktop does not reliably open a REQUESTED page, so each page is
    written alone (04_generate_report.py --only KEY), the project is opened and
    refreshed, the window is captured, and Desktop is force-closed without saving.

    Usage: powershell -Command "& '.\Validation\render_pages.ps1' -Keys lab1,lab2,lab3 -Phase phase3"
           (-File passes 'a,b' as ONE string; -Command does not)
#>
param([Parameter(Mandatory = $true)][string[]]$Keys, [string]$Phase = "phase3", [int]$Settle = 25)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $PSScriptRoot "evidence\$Phase"
New-Item -ItemType Directory -Force -Path $out | Out-Null

foreach ($k in $Keys) {
    Write-Host "--- $k" -ForegroundColor Cyan
    Push-Location $root
    python Python\04_generate_report.py --only $k
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "generator failed for $k" }
    Pop-Location
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "open_powerbi.ps1") -Restart | Select-Object -Last 2
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "capture_powerbi.ps1") -Out (Join-Path $out "$k.png") -SettleSeconds $Settle
}
Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
Push-Location $root; python Python\04_generate_report.py | Select-Object -Last 1; Pop-Location
Write-Host "captured: $out" -ForegroundColor Green
