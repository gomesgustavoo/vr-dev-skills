# Copy this repo's skills to where your coding agent looks for them (no Node needed).
# The one-line alternative for any agent is:  npx skills add gomesgustavoo/vr-dev-skills
#
#   powershell -File tools\install.ps1                                   # universal + Claude Code if ~\.claude exists
#   powershell -File tools\install.ps1 -Agent codex                      # one agent
#   powershell -File tools\install.ps1 -Agent codex,claude-code,cursor   # several
#   powershell -File tools\install.ps1 -Project C:\src\MyQuestApp        # into that project instead of your home folder
#   powershell -File tools\install.ps1 -Only unity-quest-sim-loop,horizon-os-mcp
#
# Agents (global path / project path):
#   universal       ~\.agents\skills           .agents\skills   (Codex, Cline, Warp, Zed and others)
#   codex           ~\.agents\skills           .agents\skills
#   claude-code     ~\.claude\skills           .claude\skills
#   cursor          ~\.cursor\skills           .agents\skills
#   gemini-cli      ~\.gemini\skills           .agents\skills
#   github-copilot  ~\.copilot\skills          .agents\skills
#   opencode        ~\.config\opencode\skills  .agents\skills
# An existing skill folder of the same name is replaced (the old copy is renamed <name>.bak-<time>).
param([string[]]$Agent = @(), [string]$Project = "", [string[]]$Only = @())
$ErrorActionPreference = "Stop"
$here = Split-Path $PSScriptRoot -Parent
$Agent = @($Agent | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$Only = @($Only | ForEach-Object { $_ -split "," } | Where-Object { $_ })
if ($Agent.Count -eq 0) {
    $Agent = @("universal")
    if (Test-Path (Join-Path $env:USERPROFILE ".claude")) { $Agent += "claude-code" }
}

function Get-Dest([string]$a) {
    if ($Project) {
        switch ($a) {
            "claude-code" { return Join-Path $Project ".claude\skills" }
            { $_ -in "universal", "codex", "cursor", "gemini-cli", "github-copilot", "opencode" } { return Join-Path $Project ".agents\skills" }
        }
    } else {
        switch ($a) {
            { $_ -in "universal", "codex" } { return Join-Path $env:USERPROFILE ".agents\skills" }
            "claude-code" { return Join-Path $env:USERPROFILE ".claude\skills" }
            "cursor" { return Join-Path $env:USERPROFILE ".cursor\skills" }
            "gemini-cli" { return Join-Path $env:USERPROFILE ".gemini\skills" }
            "github-copilot" { return Join-Path $env:USERPROFILE ".copilot\skills" }
            "opencode" { return Join-Path $env:USERPROFILE ".config\opencode\skills" }
        }
    }
    throw "unknown agent: $a (see the header of this script)"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$done = @{}
foreach ($a in $Agent) {
    $dest = Get-Dest $a
    if ($done.ContainsKey($dest.ToLowerInvariant())) { continue }   # agents that share a folder get one copy
    $done[$dest.ToLowerInvariant()] = $true
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($dir in Get-ChildItem (Join-Path $here "skills") -Directory) {
        if ($Only.Count -gt 0 -and $Only -notcontains $dir.Name) { continue }
        $target = Join-Path $dest $dir.Name
        if (Test-Path $target) { Rename-Item $target ($dir.Name + ".bak-" + $stamp) }
        Copy-Item $dir.FullName $target -Recurse
        Get-ChildItem $target -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
        Get-ChildItem $target -Recurse -Directory -Filter "out" | Where-Object { $_.FullName -match '\\examples\\' } | Remove-Item -Recurse -Force
    }
    Write-Output "installed -> $dest  ($a)"
}
Write-Output "done. Start a new agent session to load them."
