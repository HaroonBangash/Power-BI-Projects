<#
    Captures the Power BI Desktop window as an image so rendered visuals can be
    inspected - the check no query-level test can make: a visual can return data
    yet still draw "Select or drag fields" or "(Blank)".

    Uses PrintWindow with PW_RENDERFULLCONTENT, which renders the Power BI window
    itself into the bitmap. It works even when another window covers Power BI,
    and it never captures any other window on the screen.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\capture_powerbi.ps1 -Out C:\path\shot.png
#>
param([Parameter(Mandatory = $true)][string]$Out, [int]$SettleSeconds = 20)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PbiWin {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
Add-Type -AssemblyName System.Drawing
[void][PbiWin]::SetProcessDPIAware()

$p = $null
for ($i = 0; $i -lt 20 -and -not $p; $i++) {
    $p = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
    if (-not $p) { Start-Sleep -Seconds 3 }
}
if (-not $p) { throw "No Power BI Desktop window." }
[void][PbiWin]::ShowWindow($p.MainWindowHandle, 3)      # SW_MAXIMIZE: a full-size canvas renders every visual
Start-Sleep -Seconds $SettleSeconds                       # let visuals finish rendering

$r = New-Object PbiWin+RECT
[void][PbiWin]::GetWindowRect($p.MainWindowHandle, [ref]$r)
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [PbiWin]::PrintWindow($p.MainWindowHandle, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT (WebView2 / DirectX content)
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "captured ${w}x${h} (PrintWindow ok=$ok) -> $Out ($($p.MainWindowTitle))"
