# Headless Quest build (or a gates-only run) that waits on the Unity process it started.
# The editor must be CLOSED on this project: batchmode takes the project lock.
#
#   powershell -File unity_build.ps1 -Project C:\path\to\MyQuestApp                   # release APK
#   powershell -File unity_build.ps1 -Project ... -Dev                                 # development APK (agent tools, Operator layer)
#   powershell -File unity_build.ps1 -Project ... -Dev -NoOperator                     # dev APK WITHOUT the Operator layer
#   powershell -File unity_build.ps1 -Project ... -GatesOnly                           # every [QuestBuildGate], no APK
#   -Method Ns.EditorTools.QuestBuild.Cli   the entry point (default: the class in Assets that defines
#                                           `static void Cli(` next to `CliDev(` - assets/QuestBuild.cs)
#   -Apk Build\App.apk                      passed as -apkPath; default <project>\Build\<productName>[-dev].apk
#   -Unity C:\...\Unity.exe                 default: $env:UNITY_EDITOR, else the Hub install for ProjectVersion.txt
#   -BuildTemp C:\unity-build-temp          TEMP/TMP for Unity's child processes (Gradle's AF_UNIX pipe can
#                                           fail under the default TEMP on Windows; the TCP fallback never runs)
#   -TimeoutMinutes 45
#
# Run it in the foreground, or in the background and act on its exit. Its LAST line is always
# "exit <code>" and it exits with that code (non-zero also when the APK is missing). Before that it
# prints the [QuestBuild] / [QuestBuildGates] result lines, any "error CS" lines and the log tail.
# Never poll its log for a marker you have not copied from this script or from QuestBuild.cs.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [switch]$Dev,
    [switch]$GatesOnly,
    [switch]$NoOperator,
    [string]$Method = "",
    [string]$Apk = "",
    [string]$Unity = "",
    [string]$BuildTemp = "",
    [int]$TimeoutMinutes = 45
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path $Project).Path
$verFile = Join-Path $root "ProjectSettings\ProjectVersion.txt"
if (-not (Test-Path $verFile)) { Write-Output "not a Unity project: $root"; Write-Output "exit 2"; exit 2 }

# ---- the Unity editor
if (-not $Unity) { $Unity = $env:UNITY_EDITOR }
if ($Unity -and (Test-Path (Join-Path $Unity "Unity.exe"))) { $Unity = Join-Path $Unity "Unity.exe" }
if (-not $Unity -or -not (Test-Path $Unity)) {
    $ver = (Select-String -Path $verFile -Pattern "m_EditorVersion:\s*(\S+)").Matches[0].Groups[1].Value
    foreach ($c in @("C:\Program Files\Unity\Hub\Editor\$ver-x86_64\Editor\Unity.exe", "C:\Program Files\Unity\Hub\Editor\$ver\Editor\Unity.exe")) {
        if (Test-Path $c) { $Unity = $c; break }
    }
}
if (-not $Unity -or -not (Test-Path $Unity)) { Write-Output "no Unity.exe found - pass -Unity or set UNITY_EDITOR"; Write-Output "exit 2"; exit 2 }

# ---- the entry point: the class that defines Cli() and CliDev() (QuestBuild.cs), unless given
if (-not $Method) {
    $hit = Get-ChildItem (Join-Path $root "Assets") -Recurse -Filter *.cs -ErrorAction SilentlyContinue |
        Select-String -Pattern "static void CliDev\(" -List | Select-Object -First 1
    if (-not $hit) { Write-Output "no build entry point (static void Cli/CliDev) in Assets - copy assets/QuestBuild.cs or pass -Method"; Write-Output "exit 2"; exit 2 }
    $text = Get-Content $hit.Path -Raw
    $ns = [regex]::Match($text, "namespace\s+([\w\.]+)").Groups[1].Value
    $cls = [regex]::Match($text, "static\s+class\s+(\w+)").Groups[1].Value
    $base = if ($ns) { "$ns.$cls" } else { $cls }
    $Method = if ($GatesOnly) { "$base.CliGates" } elseif ($Dev) { "$base.CliDev" } else { "$base.Cli" }
}

# ---- outputs
$kind = if ($GatesOnly) { "gates" } elseif ($Dev) { "build-dev" } else { "build" }
$log = Join-Path $root "Temp\$kind.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }
if (-not $GatesOnly) {
    if (-not $Apk) {
        $product = (Select-String -Path (Join-Path $root "ProjectSettings\ProjectSettings.asset") -Pattern "^\s*productName:\s*(.+)$").Matches[0].Groups[1].Value.Trim()
        $product = ($product -replace '[\\/:*?"<>|]', '_')
        $Apk = Join-Path $root ("Build\" + $product + ($(if ($Dev) { "-dev" } else { "" })) + ".apk")
    } elseif (-not [IO.Path]::IsPathRooted($Apk)) { $Apk = Join-Path $root $Apk }
    if (Test-Path $Apk) { Remove-Item $Apk -Force }   # a stale APK must never pass for a new one
}

# ---- the project lock: say so instead of failing without a log
$running = Get-CimInstance Win32_Process -Filter "Name = 'Unity.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match [regex]::Escape($root) }
if ($running) {
    Write-Output ("a Unity editor already has this project open (pid " + (($running | ForEach-Object { $_.ProcessId }) -join ", ") + "). Close it first.")
    Write-Output "exit 3"; exit 3
}
$lock = Join-Path $root "Temp\UnityLockfile"
if (Test-Path $lock) { Remove-Item $lock -Force -ErrorAction SilentlyContinue }   # left by a killed editor: batchmode would exit WITHOUT a log

$unityArgs = @("-batchmode", "-quit", "-projectPath", "`"$root`"", "-executeMethod", $Method,
               "-logFile", "`"$log`"", "-buildTarget", "Android")
if ($GatesOnly) { $unityArgs += "-nographics" }   # gates that read pixels need a device: drop this for them
if (-not $GatesOnly) { $unityArgs += @("-apkPath", "`"$Apk`"") }
if ($NoOperator) { $env:QUEST_NO_OPERATOR = "1" } else { Remove-Item Env:QUEST_NO_OPERATOR -ErrorAction SilentlyContinue }
if ($BuildTemp) {
    New-Item -ItemType Directory -Force -Path $BuildTemp | Out-Null
    $env:TEMP = $BuildTemp; $env:TMP = $BuildTemp
}

Write-Output "unity -executeMethod $Method  (log: $log)"
$started = Get-Date
$proc = Start-Process -FilePath $Unity -ArgumentList $unityArgs -PassThru -NoNewWindow
$null = $proc.Handle   # cache the handle now, or ExitCode reads back empty after the process exits
if (-not $proc.WaitForExit($TimeoutMinutes * 60 * 1000)) {
    Write-Output "TIMEOUT after $TimeoutMinutes min - Unity pid $($proc.Id) is still running; not killed. See $log"
    Write-Output "exit 124"; exit 124
}
$code = $proc.ExitCode
$mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)

Write-Output "---- result ($mins min) ----"
if (Test-Path $log) {
    Select-String -Path $log -Pattern "\[QuestBuild\] (result=|refusing|FAILED|building)|\[QuestBuildGates\] (FAIL|ALL PASS|\d+ FAILURE)|OperatorLayerExclusion|Including XrApiLayer_METAX_operator|error CS|Build Finished, Result|Aborting batchmode|Smart App Control|blocked by" |
        ForEach-Object { $_.Line } | Select-Object -Unique | Select-Object -Last 40
    Write-Output "---- log tail ----"
    Get-Content $log -Tail 20
} else {
    Write-Output "NO LOG at $log (Unity exited before logging: a licence prompt, a stale lock, or it never started)"
}
if (-not $GatesOnly) {
    if (Test-Path $Apk) {
        $f = Get-Item $Apk
        Write-Output ("APK " + [math]::Round($f.Length / 1MB, 1) + " MB  " + $Apk)
        # Only an SDK that ships the Operator (Meta XR Core 205+) can put it in a dev build.
        $sdkShipsOperator = @(Get-ChildItem (Join-Path $root "Library\PackageCache") -Directory -Filter "com.meta.xr.sdk.core@*" -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName "Editor\MetaXROperator") }).Count -gt 0
        if ($Dev -and $sdkShipsOperator -and -not $NoOperator -and (Test-Path $log) -and -not (Select-String -Path $log -Pattern "Including XrApiLayer_METAX_operator" -Quiet)) {
            Write-Output "WARNING: a development build, but the log never says it included the Meta XR Operator layer (no agent can attach on :8720)."
        }
    } else {
        Write-Output "NO APK"
        if ($code -eq 0) { $code = 1 }
    }
}
Write-Output ("exit " + $code)
exit $code
