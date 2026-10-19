# MCP servers for Quest development

Two MCP servers make the loop work. Neither is part of this repo; both come from Meta.

| server | what it gives the agent | where it comes from |
|---|---|---|
| **`metavr`** (Horizon OS dev MCP) | Meta docs search + full pages, exact Unity/Unreal API signatures, device list/apps/files, logcat, screenshots, Android UI automation, Perfetto capture/analyse/compare | `npx -y metavr mcp server` (Node 18+), or bundled with Meta Quest Developer Hub as `hzos-dev-mcp.exe` |
| **`meta-xr-operator`** | inside the running app: head/controller poses, buttons, composited eye capture, Unity scene queries, and the app's own registered tools | the MCP proxy copied out of a Meta XR Core SDK 205+ package (`skills/unity-quest-sim-loop/references/setup.md`) |

## Add them

**User scope** (every project on this machine):
```bash
claude mcp add --scope user metavr -- npx -y metavr mcp server
```
On native Windows, if `npx` does not start from Claude Code, wrap it:
`claude mcp add --scope user metavr -- cmd /c npx -y metavr mcp server`.

**Project scope** (committed, so every session in the Unity project has them): copy
[`project.mcp.json`](project.mcp.json) to the project root as `.mcp.json`. `${USERPROFILE}` is
expanded by Claude Code at launch, so the file carries no personal path.

If you install Meta's own plugin (`/plugin install meta-vr@meta-quest`), it already registers
`metavr`; don't add it a second time - duplicate servers only give every tool twice.

## Check them

```bash
claude mcp list                                                     # Connected / failed per server
python skills/horizon-os-mcp/scripts/mcp_probe.py --server both     # version, tool count, a timed docs query
python skills/unity-quest-sim-loop/scripts/op.py list               # Operator tools ([OFFLINE] = no app attached)
```

Measured on Windows 11, 2026-10: `metavr` 1.8 (npx) lists 38 tools and answers a docs search in
about 2 s; the MQDH-bundled 1.6 lists 36 (no `perf_session`, `perf_memory_snapshot`).
`claude mcp list` prints `unknown format "uint" ignored in schema` warnings for the perf tools'
output schemas; they are harmless.

## Not recommended

The Unity editor MCP bridge (`unity-mcp` relay) answered "Unity not detected", "Connection
revoked" or "tools fetch failed" across several projects. The loop here does not depend on it:
DevRemote (a loopback HTTP endpoint inside the editor) and the Operator cover Play Mode control
and the app's tools.
