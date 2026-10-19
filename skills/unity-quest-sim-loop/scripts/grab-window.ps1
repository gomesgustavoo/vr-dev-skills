# Capture a desktop window to PNG by title prefix, even when it is behind other windows.
#
#   powershell -File grab-window.ps1 [-Title "Meta XR Simulator"] [-Out C:\path\sim.png]
#
# Uses PrintWindow with PW_RENDERFULLCONTENT, so GPU-drawn windows (the simulator, the Unity
# Game view) come out instead of black. Prefer the app's own snapshot tool when it has one:
# it renders the real eye camera at a chosen size and field of view, independent of whatever
# the window happens to show.
param([string]$Title = "Meta XR Simulator", [string]$Out = "")
Add-Type -AssemblyName System.Drawing
if (-not ("GrabWin" -as [type])) {
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public static class GrabWin {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L, T, R, B; }
  public static IntPtr Find(string title) { IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
      if (IsWindowVisible(h) && sb.ToString().StartsWith(title)) { found = h; return false; } return true; }, IntPtr.Zero); return found; }
}
"@
}
if (-not $Out) { $Out = Join-Path (Get-Location) "window.png" }
$h = [GrabWin]::Find($Title)
if ($h -eq [IntPtr]::Zero) { "no visible window whose title starts with '$Title'"; exit 1 }
$r = New-Object GrabWin+RECT; [void][GrabWin]::GetWindowRect($h, [ref]$r)
$w = $r.R - $r.L; $hh = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $hh; $g = [System.Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
[void][GrabWin]::PrintWindow($h, $hdc, 2); $g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
"$Out ${w}x${hh}"
