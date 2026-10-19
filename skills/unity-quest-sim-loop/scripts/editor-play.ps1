# (Re)start a Unity Quest project's editor straight into Play Mode on the Meta XR Simulator,
# ready for the Meta XR Operator (:8720) and DevRemote (:8731).
#
#   powershell -File editor-play.ps1 -Project C:\path\to\MyQuestApp [-Restart] [-D3D11]
#                                    [-PlayMethod Ns.DevXr.CliPlay] [-Unity C:\...\Unity.exe]
#
# -Restart     kills running Unity editors first. Say so to the user if they might be using it.
# -PlayMethod  defaults to the class in Assets/Editor that defines `static void CliPlay(`
#              (see assets/DevXr.cs); it opens the scene, activates Operator + simulator and
#              arms an auto-play that survives the domain reloads of a cold start.
# -Unity       defaults to the Hub editor matching ProjectSettings/ProjectVersion.txt,
#              preferring the "<version>-x86_64" folder (on machines with both, the plain one can be an
#              orphaned duplicate without Android support).
#
# A killed editor leaves scene backups and the next launch stops on a modal "Recovering Scene
# Backups" dialog until someone answers; this answers YES (the copies go to Assets/_Recovery,
# nothing is discarded - add /Assets/_Recovery/ to .gitignore). It then waits for DevRemote
# and presses Play itself if the auto-play has not. Prints PLAYING, or TIMEOUT and exits 1.
param(
    [string]$Project = (Get-Location).Path,
    [switch]$Restart,
    [switch]$D3D11,
    [string]$PlayMethod = "",
    [string]$Unity = "",
    [int]$RemotePort = 8731,
    [int]$TimeoutMinutes = 8
)
$ErrorActionPreference = "Continue"
$Project = (Resolve-Path $Project).Path

if (-not $Unity) {
    $ver = (Get-Content (Join-Path $Project "ProjectSettings\ProjectVersion.txt") |
            Select-String "^m_EditorVersion:\s*(\S+)").Matches[0].Groups[1].Value
    foreach ($dir in @("$ver-x86_64", $ver)) {
        $candidate = "C:\Program Files\Unity\Hub\Editor\$dir\Editor\Unity.exe"
        if (Test-Path $candidate) { $Unity = $candidate; break }
    }
    if (-not $Unity) { Write-Host "no Unity $ver under C:\Program Files\Unity\Hub\Editor; pass -Unity"; exit 1 }
}

if (-not $PlayMethod) {
    $file = Get-ChildItem -Path (Join-Path $Project "Assets") -Recurse -Filter *.cs -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\Editor\\" } |
            Where-Object { Select-String -Path $_.FullName -Pattern "static void CliPlay\(" -Quiet } |
            Select-Object -First 1
    if (-not $file) { Write-Host "no CliPlay() in Assets/**/Editor - set the project up first (references/setup.md)"; exit 1 }
    $src = Get-Content $file.FullName -Raw
    $ns = [regex]::Match($src, "namespace\s+([\w\.]+)").Groups[1].Value
    $cls = [regex]::Match($src, "static\s+class\s+(\w+)").Groups[1].Value
    $PlayMethod = (@($ns, $cls, "CliPlay") | Where-Object { $_ }) -join "."
}

if ($Restart) {
    Get-Process -Name Unity -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 8   # lets the DevRemote port and the project lock go
}

$launchArgs = @("-projectPath", $Project, "-executeMethod", $PlayMethod)   # not $args: that is automatic
if ($D3D11) { $launchArgs = @("-force-d3d11") + $launchArgs }
Start-Process -FilePath $Unity -ArgumentList $launchArgs | Out-Null
Write-Host "editor launching: $Unity -executeMethod $PlayMethod"

if (-not ("EditorPlayDlg" -as [type])) {
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public static class EditorPlayDlg {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static bool ClickYes(IntPtr dlg) { IntPtr yes = IntPtr.Zero;
    EnumChildWindows(dlg, (h, l) => { var t = new StringBuilder(64); GetWindowText(h, t, 64); var c = new StringBuilder(32); GetClassName(h, c, 32);
      if (c.ToString() == "Button" && t.ToString().Replace("&", "") == "Yes") { yes = h; return false; } return true; }, IntPtr.Zero);
    if (yes == IntPtr.Zero) return false; SendMessage(yes, 0x00F5, IntPtr.Zero, IntPtr.Zero); return true; }
}
"@
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$pressed = $false
while ((Get-Date) -lt $deadline) {
    $dlg = Get-Process -Name Unity -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -eq "Recovering Scene Backups" } | Select-Object -First 1
    if ($dlg -and [EditorPlayDlg]::ClickYes($dlg.MainWindowHandle)) { Write-Host "answered 'Recovering Scene Backups': Yes (kept in Assets/_Recovery/)" }

    # DevRemote moves off 8731 when a socket leaked inside the editor still holds it, and says where.
    $portFile = Join-Path $Project "Temp\DevRemote.port"
    $port = if (Test-Path $portFile) { (Get-Content $portFile -Raw).Trim() } else { $RemotePort }
    try { $s = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$port/status").Content } catch { $s = $null }
    if ($s -match '"isPlaying":true') { Write-Host ("PLAYING" + $(if ("$port" -ne "$RemotePort") { " (DevRemote on port $port)" } else { "" })); exit 0 }
    if ($s -match '"isPlaying":false' -and -not $pressed -and $s -match '"isCompiling":false') {
        Start-Sleep -Seconds 20   # give the armed auto-play its chance first
        try { Invoke-WebRequest -UseBasicParsing -Method Post -TimeoutSec 15 "http://127.0.0.1:$port/play" | Out-Null; $pressed = $true } catch { }
    }
    Start-Sleep -Seconds 4
}
Write-Host "TIMEOUT: the editor did not reach Play Mode (DevRemote off? a modal dialog? see Editor.log)"
exit 1
