<#
    Captures every report page. Power BI Desktop must already be open on the project.

    Page navigation is Ctrl+PageDown, which only moves between pages - it never edits
    a visual. Nothing is saved: the files on disk stay authoritative.

    Usage: powershell -ExecutionPolicy Bypass -File Validation\capture_all_pages.ps1 -OutDir _review
#>
param([string]$OutDir = "_review", [int]$Pages = 10, [int]$SettleSeconds = 11)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$OutDir = Join-Path $root $OutDir
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$p = Get-Process PBIDesktop -ErrorAction SilentlyContinue |
     Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
if (-not $p) { throw "No Power BI Desktop window." }

$ws = New-Object -ComObject WScript.Shell
function Focus-Pbi { for ($i = 0; $i -lt 10; $i++) { if ($ws.AppActivate($p.Id)) { return } ; Start-Sleep -Milliseconds 400 } }

# Rewind to page 1 from wherever Desktop happens to be sitting.
Focus-Pbi; Start-Sleep -Seconds 1
for ($i = 0; $i -lt ($Pages + 2); $i++) { $ws.SendKeys("^{PGUP}"); Start-Sleep -Milliseconds 350 }
Start-Sleep -Seconds $SettleSeconds

for ($n = 1; $n -le $Pages; $n++) {
    $out = Join-Path $OutDir ("page{0:00}.png" -f $n)
    & (Join-Path $PSScriptRoot "capture_powerbi.ps1") -Out $out -SettleSeconds 2
    if ($n -lt $Pages) {
        Focus-Pbi; Start-Sleep -Milliseconds 400
        $ws.SendKeys("^{PGDN}")
        Start-Sleep -Seconds $SettleSeconds
    }
}
Write-Host "captured $Pages pages into $OutDir"
