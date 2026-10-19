# Copy this repo's skills into a Claude Code skills folder (for use without the plugin).
#
#   powershell -File tools\install.ps1                      # -> %USERPROFILE%\.claude\skills
#   powershell -File tools\install.ps1 -Project C:\MyApp    # -> C:\MyApp\.claude\skills (commit with that project)
#   powershell -File tools\install.ps1 -Only unity-quest-sim-loop,horizon-os-mcp
#
# An existing skill folder of the same name is replaced (its old copy is renamed <name>.bak-<time>).
param([string]$Project = "", [string[]]$Only = @())
$ErrorActionPreference = "Stop"
$here = Split-Path $PSScriptRoot -Parent
$dest = if ($Project) { Join-Path $Project ".claude\skills" } else { Join-Path $env:USERPROFILE ".claude\skills" }
$Only = @($Only | ForEach-Object { $_ -split "," } | Where-Object { $_ })
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($dir in Get-ChildItem (Join-Path $here "skills") -Directory) {
    if ($Only.Count -gt 0 -and $Only -notcontains $dir.Name) { continue }
    $target = Join-Path $dest $dir.Name
    if (Test-Path $target) { Rename-Item $target ($dir.Name + ".bak-" + $stamp) }
    Copy-Item $dir.FullName $target -Recurse
    Get-ChildItem $target -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem $target -Recurse -Directory -Filter "out" | Where-Object { $_.FullName -match '\\examples\\' } | Remove-Item -Recurse -Force
    Write-Output "installed $($dir.Name) -> $target"
}
Write-Output "done. Start a new Claude Code session to load them."
