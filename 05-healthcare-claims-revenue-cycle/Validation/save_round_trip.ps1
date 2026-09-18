<#
    Proves that a genuine Power BI Desktop SAVE does not rewrite the generated files:
    the generator already writes Power BI's own format, so a save must be a no-op in Git.

      1. snapshot the PBIP folders
      2. activate Power BI Desktop and send Ctrl+S
      3. wait for the save to settle, then compare every file

    Files Power BI owns per machine (.pbi\localSettings.json, cache.abf, editor state)
    are excluded: they are per-machine state, not project definition, and .gitignore
    already excludes them.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\save_round_trip.ps1
#>
param([int]$SettleSeconds = 30)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic

$root = Split-Path $PSScriptRoot -Parent
$pbi = Join-Path $root "PowerBI"
$snap = Join-Path ([System.IO.Path]::GetFullPath($env:TEMP)) ("rcm_snapshot_" + (Get-Date -Format "HHmmss"))
$exclude = @("\.pbi\\", "cache\.abf", "localSettings\.json", "editorSettings\.json", "unappliedChanges\.json")

# Windows PowerShell 5.1 has no [System.IO.Path]::GetRelativePath, and $env:TEMP can
# be the 8.3 short form, so both sides are resolved before the prefix is removed.
function RelPath($base, $full) {
    $b = (Resolve-Path $base).Path.TrimEnd('') + ''
    return $full.Substring($b.Length)
}

function Snapshot($dest) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem $pbi -Recurse -File | Where-Object {
        $rel = RelPath $pbi $_.FullName
        -not ($exclude | Where-Object { $rel -match $_ })
    } | ForEach-Object {
        $rel = RelPath $pbi $_.FullName
        $target = Join-Path $dest $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item $_.FullName $target
    }
}

Snapshot $snap
$before = Get-ChildItem $snap -Recurse -File
Write-Host ("snapshot: {0} files" -f $before.Count)

$p = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { throw "Power BI Desktop is not open. Run Validation\open_powerbi.ps1 -Restart first." }
[Microsoft.VisualBasic.Interaction]::AppActivate($p.Id)
Start-Sleep -Seconds 2
[System.Windows.Forms.SendKeys]::SendWait("^s")
Write-Host "Ctrl+S sent to '$($p.MainWindowTitle)'; waiting $SettleSeconds s"
Start-Sleep -Seconds $SettleSeconds

$changed = @(); $added = @(); $removed = @()
foreach ($f in $before) {
    $rel = RelPath $snap $f.FullName
    $now = Join-Path $pbi $rel
    if (-not (Test-Path $now)) { $removed += $rel; continue }
    $a = [System.IO.File]::ReadAllBytes($f.FullName)
    $b = [System.IO.File]::ReadAllBytes($now)
    if ($a.Length -ne $b.Length -or [System.Convert]::ToBase64String($a) -ne [System.Convert]::ToBase64String($b)) {
        $changed += $rel
    }
}
Get-ChildItem $pbi -Recurse -File | ForEach-Object {
    $rel = RelPath $pbi $_.FullName
    if ($exclude | Where-Object { $rel -match $_ }) { return }
    if (-not (Test-Path (Join-Path $snap $rel))) { $added += $rel }
}

Write-Host ""
Write-Host ("files compared : {0}" -f $before.Count)
Write-Host ("changed        : {0}" -f $changed.Count) -ForegroundColor $(if ($changed.Count) { "Yellow" } else { "Green" })
Write-Host ("added by save  : {0}" -f $added.Count) -ForegroundColor $(if ($added.Count) { "Yellow" } else { "Green" })
Write-Host ("removed by save: {0}" -f $removed.Count) -ForegroundColor $(if ($removed.Count) { "Yellow" } else { "Green" })
foreach ($c in $changed) { Write-Host "  CHANGED $c" }
foreach ($a in $added) { Write-Host "  ADDED   $a" }
foreach ($r in $removed) { Write-Host "  REMOVED $r" }
Remove-Item $snap -Recurse -Force
