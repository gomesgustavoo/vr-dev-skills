# Lock-free compile check for a Unity project: Roslyn from Unity's own install, against Unity's own
# response files. ~10 s, and it does NOT take the project lock, so it runs with the editor open, during
# Play Mode, and while another tool builds. This is L0: run it after every C# edit, before reload.py.
#
#   powershell -File quickcheck.ps1 -Project C:\path\to\MyQuestApp                 # runtime assembly
#   powershell -File quickcheck.ps1 -Project ... -Editor                           # + the editor assembly
#   powershell -File quickcheck.ps1 -Project ... -Dev                              # + two DEVICE passes
#   powershell -File quickcheck.ps1 -Project ... -Assembly MyApp.Runtime -EditorAssembly MyApp.Editor
#   -Unity "C:\Program Files\Unity\Hub\Editor\6000.x\Editor"   # else $env:UNITY_EDITOR, else the Hub
#                                                              # install matching ProjectVersion.txt
#
# exit 0 and no "error CS" = clean; non-zero if any pass failed.
#
# Source of truth: Unity's Bee response files (Library\Bee\artifacts\<dag>E.dag\<Assembly>.rsp), so defines,
# references, analyzers and langversion match exactly what Unity compiles. A check that passes NO -define
# compiles every `#if UNITY_EDITOR || DEVELOPMENT_BUILD` file (all the dev tools) to nothing, and "clean"
# then means nothing for them.
#   - -out: / -refout: lines are DROPPED and replaced with Temp\qc_*.dll. Leaving -refout in overwrote
#     Unity's own reference assembly once; Unity then built an editor assembly against the impostor and
#     refused to load it. Unity's artifacts are never written here.
#   - Sources deleted since the last Unity compile are dropped; sources added since (any .cs under the
#     assembly's folder that the .rsp does not list) are added, so a new file does not fail with a
#     "type could not be found" that reads like a namespace problem.
#   - Device passes (-Dev) start from the PLAYER response file (<dag>P.dag, written by the last APK build):
#     its references and its define set. device-dev adds DEVELOPMENT_BUILD (the dev APK: agent tools,
#     command channel); device-release proves nothing outside a dev guard depends on dev-only code.
#     With no player .rsp yet it approximates the player from the editor .rsp and says so.
#   - Adding a PACKAGE or an asmdef reference needs one real Unity compile to refresh the .rsp.
param(
    [string]$Project = (Get-Location).Path,
    [string]$Assembly = "Assembly-CSharp",
    [string]$EditorAssembly = "",
    [string]$SourceDir = "",          # where the runtime assembly's sources live (default: Assets, minus Editor folders)
    [string]$Unity = "",
    [switch]$Editor,
    [switch]$Dev
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path $Project).Path
if (-not (Test-Path (Join-Path $root "ProjectSettings\ProjectVersion.txt"))) {
    Write-Host "not a Unity project: $root" -ForegroundColor Red; exit 2
}
if (-not $EditorAssembly) { $EditorAssembly = if ($Assembly -eq "Assembly-CSharp") { "Assembly-CSharp-Editor" } else { ($Assembly -replace '\.Runtime$', '') + ".Editor" } }

# ---- Unity install: -Unity, $env:UNITY_EDITOR, else the Hub folder for ProjectVersion.txt (prefer -x86_64,
# which is the Android-capable install on machines that have both).
function Find-UnityData {
    $cands = @()
    if ($Unity) { $cands += $Unity }
    if ($env:UNITY_EDITOR) { $cands += $env:UNITY_EDITOR }
    $ver = (Select-String -Path (Join-Path $root "ProjectSettings\ProjectVersion.txt") -Pattern "m_EditorVersion:\s*(\S+)").Matches[0].Groups[1].Value
    foreach ($hub in @("C:\Program Files\Unity\Hub\Editor", "$env:ProgramFiles\Unity\Hub\Editor")) {
        $cands += "$hub\$ver-x86_64\Editor"; $cands += "$hub\$ver\Editor"
    }
    foreach ($c in $cands) {
        $c = $c -replace '\\Unity\.exe$', ''
        foreach ($d in @("$c\Data", $c)) {
            if (Test-Path "$d\DotNetSdkRoslyn\csc.dll") { return $d }
        }
    }
    Write-Host "no Unity install found for $ver - pass -Unity <...\Editor> or set UNITY_EDITOR" -ForegroundColor Red
    exit 2
}
$unityData = Find-UnityData
$dotnet = "$unityData\NetCoreRuntime\dotnet.exe"
$csc = "$unityData\DotNetSdkRoslyn\csc.dll"
New-Item -ItemType Directory -Force -Path (Join-Path $root "Temp") | Out-Null

function Find-Rsp($name, $dagSuffix) {
    Get-ChildItem -Path (Join-Path $root "Library\Bee\artifacts") -Recurse -Filter "$name.rsp" -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -like "*$dagSuffix.dag" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Get-Sources([bool]$editorAsm) {
    if ($SourceDir -and -not $editorAsm) {
        return Get-ChildItem (Join-Path $root $SourceDir) -Recurse -Filter *.cs | ForEach-Object { $_.FullName }
    }
    if ($Assembly -ne "Assembly-CSharp") { return @() }   # asmdef projects: only refresh what the .rsp lists
    Get-ChildItem (Join-Path $root "Assets") -Recurse -Filter *.cs | Where-Object {
        $isEditor = $_.FullName -match '\\Editor\\'
        if ($editorAsm) { $isEditor } else { -not $isEditor }
    } | ForEach-Object { $_.FullName }
}

# The .rsp minus its outputs and stale sources, plus sources it does not know yet.
function Get-RspLines($rspFile, [bool]$editorAsm, [bool]$quiet = $false) {
    Push-Location $root
    $lines = Get-Content $rspFile.FullName | Where-Object {
        if ($_ -match '^"(.+\.cs)"$') { Test-Path $matches[1] } else { $_ -notmatch '^\s*[-/](out|refout):' }
    }
    $listed = @{}
    foreach ($l in $lines) {
        if ($l -match '^"(.+\.cs)"$') {
            $full = (Resolve-Path $matches[1] -ErrorAction SilentlyContinue).Path
            if ($full) { $listed[$full.ToLowerInvariant()] = $true }
        }
    }
    Pop-Location
    $added = @()
    foreach ($src in (Get-Sources $editorAsm)) {
        if (-not $listed.ContainsKey($src.ToLowerInvariant())) { $added += $src; $lines += "`"$src`"" }
    }
    if ($added.Count -gt 0 -and $quiet) {
        Write-Host "  $($added.Count) source(s) newer than $($rspFile.Directory.Name) added to this check" -ForegroundColor DarkYellow
    } elseif ($added.Count -gt 0) {
        Write-Host "  new since the last Unity compile (added to this check):" -ForegroundColor DarkYellow
        $added | ForEach-Object { Write-Host "    $($_.Substring($root.Length + 1))" -ForegroundColor DarkYellow }
    }
    return ,$lines
}

$script:worst = 0
function Invoke-Csc($name, $lines) {
    $out = "$root\Temp\qc_$name.dll"
    $lines = @($lines) + "-out:`"$out`""
    $rsp = "$root\Temp\qc_$name.rsp"
    Set-Content -Path $rsp -Value $lines -Encoding UTF8
    $nSrc = @($lines | Where-Object { $_ -match '\.cs"$' }).Count
    $nRef = @($lines | Where-Object { $_ -match '^-r:' }).Count
    $nDef = @($lines | Where-Object { $_ -match '^-define:' }).Count
    Write-Host "[$name] $nSrc sources, $nRef refs, $nDef defines"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # csc output through 2>&1 must not turn into a terminating error
    Push-Location $root                   # the .rsp's relative source paths are project-relative
    & $dotnet $csc "@$rsp" 2>&1 | ForEach-Object {
        if ("$_" -match "error CS") { Write-Host $_ -ForegroundColor Red }
    }
    $code = $LASTEXITCODE
    Pop-Location
    $ErrorActionPreference = $prev
    Write-Host "[$name] exit=$code" -ForegroundColor ($(if ($code -eq 0) { "Green" } else { "Red" }))
    if ($code -ne 0 -and $script:worst -eq 0) { $script:worst = $code }
    return $out
}

$runtimeRsp = Find-Rsp $Assembly "E"
if (-not $runtimeRsp) {
    Write-Host "no Library\Bee .rsp for $Assembly - open the project in Unity once (or check -Assembly)." -ForegroundColor Red
    exit 1
}
Write-Host "source of truth: $($runtimeRsp.FullName.Substring($root.Length + 1)) ($($runtimeRsp.LastWriteTime))"
$runtimeLines = Get-RspLines $runtimeRsp $false
$runtimeDll = Invoke-Csc "runtime" $runtimeLines

if ($Editor) {
    $editorRsp = Find-Rsp $EditorAssembly "E"
    if (-not $editorRsp) { Write-Host "no $EditorAssembly.rsp; open the project in Unity once." -ForegroundColor Red; exit 1 }
    # The editor assembly must see the runtime assembly just compiled, not the one from the last Unity compile.
    $editorRaw = Get-RspLines $editorRsp $true
    $asmRe = [regex]::Escape($Assembly)
    $editorLines = $editorRaw | ForEach-Object {
        if ($_ -match "^-r:.*[\\/]$asmRe(\.ref)?\.dll`"?$") { "-r:`"$runtimeDll`"" } else { $_ }
    }
    Invoke-Csc "editor" $editorLines | Out-Null
}

if ($Dev) {
    # Device passes: what the Android player compiles. Editor defines out, IL2CPP in, editor-only references
    # out, so an unguarded UnityEditor call in runtime code fails here as it would in the APK build.
    $devOnly = '^-define:(DEVELOPMENT_BUILD|UNITY_ASSERTIONS|ENABLE_PROFILER)$'
    $playerRsp = Find-Rsp $Assembly "P"
    if ($playerRsp) {
        $playerLines = Get-RspLines $playerRsp $false $true   # assign first: it returns the array as ONE object
        $deviceBase = @($playerLines | Where-Object { $_ -notmatch $devOnly })
        $baseDesc = "player .rsp $($playerRsp.Directory.Name) ($($playerRsp.LastWriteTime))"
    } else {
        $dropDefines = '^-define:(UNITY_EDITOR|UNITY_EDITOR_64|UNITY_EDITOR_WIN|UNITY_EDITOR_OSX|UNITY_EDITOR_LINUX|UNITY_INCLUDE_TESTS|ENABLE_MONO|DEBUG|TRACE|ENABLE_PROFILER|ENABLE_PROFILER_ASSISTANT_INTEGRATION|UNITY_ASSERTIONS|ENABLE_UNITY_COLLECTIONS_CHECKS|ENABLE_BURST_AOT|UNITY_TEAM_LICENSE|DEVELOPMENT_BUILD)$'
        $deviceBase = @($runtimeLines | Where-Object {
            if ($_ -match $dropDefines) { return $false }
            if ($_ -match '^-r:"?(.+?)"?$') {
                $leaf = ([IO.Path]::GetFileName($matches[1]) -replace '\.ref\.dll$', '.dll').ToLowerInvariant()
                return -not ($leaf -match '^unityeditor|\.editor(\.|$)|editor\.dll$|^meta\.xr\.editor|\.editor\.|mono\.cecil|^unity\.android\.(gradle|types)')
            }
            return $true
        })
        $deviceBase += "-define:ENABLE_IL2CPP"
        if (-not ($deviceBase -contains "-define:UNITY_ANDROID")) { $deviceBase += "-define:UNITY_ANDROID" }
        $baseDesc = "editor .rsp minus editor defines/assemblies (APPROXIMATE: build an APK once for the player .rsp)"
    }
    Write-Host "device base: $baseDesc"
    $devDefines = @("-define:DEVELOPMENT_BUILD", "-define:UNITY_ASSERTIONS", "-define:ENABLE_PROFILER")
    Invoke-Csc "device-dev" (@($deviceBase) + $devDefines) | Out-Null
    Invoke-Csc "device-release" $deviceBase | Out-Null
}
exit $script:worst
