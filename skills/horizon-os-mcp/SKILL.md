---
name: horizon-os-mcp
description: Connect and use Meta's Horizon OS developer MCP server (metavr via npx, or hzos-dev-mcp bundled with Meta Quest Developer Hub) for Quest work - authoritative Meta docs and exact Unity/Unreal API signatures, device control (list, apps, files, logcat, screenshots, UI automation), and Perfetto performance traces with baseline comparison. Use it before relying on memory about any Meta XR SDK name, setting, manifest entry or Store/VRC rule; when a Quest app crashes, stutters or runs hot; when the user asks to install, launch, inspect or capture something on the headset; or when setting up, checking or repairing the MCP connection itself.
---

# Horizon OS dev MCP: docs first, device second, traces for performance

Meta ships one MCP server for Quest development, in two packagings. It answers three kinds of
question better than memory or guesswork:
- **What does Meta say?** Docs search + full pages, and exact API signatures for Unity and
  Unreal. Meta SDK names change between versions (the legacy OVR rig names were replaced by
  `OVRComprehensiveInteractionRig` in SDK 205), so memory goes stale quietly.
- **What is the headset doing?** Devices, apps, files, logcat, screenshots, system UI.
- **Where did the frame time go?** Perfetto capture, automatic analysis, GPU counters,
  before/after comparison.

`<skill>` below is this skill's folder (the base directory shown when the skill loads).

## 1. Connect (once per machine)

| packaging | command | notes |
|---|---|---|
| **npx `metavr`** (recommended) | `npx -y metavr mcp server` | cross-platform, newest (v1.8: 38 tools incl. `perf_session`, `perf_memory_snapshot`) |
| Meta's Claude Code plugin | `/plugin marketplace add meta-quest/agentic-tools` then `/plugin install meta-vr@meta-quest` | the same npx server + Meta's own skills (`hz-*`) |
| Meta Quest Developer Hub | `C:\Program Files\Meta Quest Developer Hub\resources\bin\hzos-dev-mcp.exe` | Windows, ships with MQDH, lags behind (v1.6: 36 tools) |

Register **one** of them. Two copies give every tool twice, under two prefixes, and nothing
else.

```bash
claude mcp add --scope user metavr -- npx -y metavr mcp server
# native Windows, if npx does not start from Claude Code:
claude mcp add --scope user metavr -- cmd /c npx -y metavr mcp server
```
Or commit it to the project's `.mcp.json` (see the repo's `mcp/project.mcp.json`) so every
session in that project has it.

**Check the connection, don't assume it:**
```bash
claude mcp list                                     # each server: Connected / failed
python <skill>/scripts/mcp_probe.py                 # starts the server itself, lists tools, times a docs query
python <skill>/scripts/mcp_probe.py --server hzos   # the MQDH packaging instead
```
`mcp_probe.py` speaks MCP over stdio directly, so it tells "the server is broken" apart from
"Claude Code didn't load it". It prints the server version, the tool count, the tools missing
from the other packaging, and how long one `vr_docs_search` took.

Inside a session the tools appear as `mcp__metavr__*`, `mcp__plugin_meta-vr_metavr__*` or
`mcp__hzos-dev-mcp__*`. If they are deferred, load them with ToolSearch
(`select:<full tool name>,...`, or a keyword search such as `vr_docs_search`) before calling.
Use whichever prefix is present; the tool names after the prefix are identical.

Known noise: `claude mcp list` prints many `unknown format "uint" ignored in schema` lines for
this server's perf tools. They are JSON-schema warnings about output types, not failures.

## 2. Docs and APIs: verify before you write

Rule: **before writing code or config against a Meta SDK API, a manifest entry, a build
setting or a Store/VRC rule, look it up.** It costs seconds; a stale name costs a build.

| question | tool |
|---|---|
| how / why / which feature, concepts, setup guides | `vr_docs_search {query}` → then `vr_docs_get_page {url}` with the `doc_path` / `canonical_url` it returned (never a guessed URL) |
| exact signature, property type, event, enum | `vr_api_search {query, engine: "unity"}` → `vr_api_details {name, engine}` |
| is there a ready 3D model | `vr_assets_search {prompt}` (FBX / GLB links with previews) |
| which metavr subcommand exists now | `metavr_cli_help {topic}` - the CLI grows every release |

- Quote the doc (page title + the sentence) in your answer when it decides something, so the
  user can check it.
- `vr_api_search` is for names you already know; conceptual questions go to `vr_docs_search`.
- When the docs and the installed SDK disagree, the installed SDK wins for what compiles:
  read `Library/PackageCache/com.meta.xr.sdk.*/` and say that the docs differ.
- If a call hangs (it ran ~20 minutes per call on one machine for a while, then recovered),
  don't stall the task: read the SDK source in `Library/PackageCache`, use direct `adb`, and
  batch the doc questions for later.

## 3. The headset

Start with `metavr_device {action: "list"}`: it gives the serials. Never guess device state.

| want | tool |
|---|---|
| devices, OS build, battery, controllers, proximity, Guardian | `metavr_device {action: list / info / battery / controllers / proximity_get / boundary_get / os}` |
| installed apps, install, launch, stop | `metavr_app {action: list / info / install / launch / stop}` |
| files on the headset | `metavr_files {action: ls / push / pull}` |
| logs | `device_logcat {package?, tag?, level?, regex?, lines?, clear?}` |
| what the wearer sees | `device_screenshot {method?, width?, height?}` |
| 2D system UI (permission dialogs, settings) | `ui_dump`, `ui_actions`, `ui_tap`, `ui_type`, `ui_wait` |
| where adb / Unity / Java / Meta tools are | `metavr_software_paths` |
| anything else metavr does | `metavr_run {subcommand, args}` after `metavr_cli_help` |

Things that cost time:
- **The headset must be worn** for screenshots and for a running immersive app: off the head
  it sleeps, the app is suspended, a capture comes back empty and every in-app call times
  out. Check `adb shell getprop sys.hmt.mounted` (1 = worn) before blaming a tool.
- **Big APK installs:** direct `adb install -r -g` is much faster and more predictable than
  an MCP install call; use the MCP for list / launch / inspect (the `quest-build-deploy`
  skill does the install).
- **Mutating actions** (uninstall, rm, settings changes, `metavr_device` setters) change the
  user's device. Ask first, unless the user already asked for exactly that.
- `ui_*` tools drive Android 2D UI (uiautomator). They do not reach inside an immersive
  Unity app; that is the Meta XR Operator's job (`unity-quest-sim-loop`).
- A first-time USB debugging prompt appears **inside** the headset; only the wearer can
  accept it. `unauthorized` in the device list means exactly that.

## 4. Performance: measure, compare, change one thing

`references/perf-playbook.md` has the full recipe. The short form:
1. **Fix the scene.** A dev-only app tool puts the content at a known pose and state, and
   dynamic resolution is pinned or off, or runs are not comparable.
2. **Baseline first,** on the unchanged build:
   `perf_trace_capture {app: "<package>", duration_ms: 10000, mode: "standard"}` with the
   headset worn and the app in the state under test. Keep the APK (`Build/baseline-<date>-dev.apk`).
3. **Read it:** `perf_trace_analyze {focus: "overview"}` (CPU- or GPU-bound, frame timing,
   stale frames), then `perf_trace_gpu_counters` / `perf_trace_thread_state` /
   `perf_trace_query_sql` for the specific question.
4. **One change, one capture, then** `perf_trace_compare {baseline_id, comparison_id}`.
5. **Cross-check with VrApi logcat** (`FPS=`, `App=`, `GPU%=`, `SF=`, `Stale=`, `TW=`, `LCnt=`):
   one line a second, the ground truth for what the compositor saw. A trace that disagrees
   with VrApi is the trace's problem until proven otherwise.

- Memory: `perf_memory_snapshot {app, label: "baseline" | "incident" | "final"}` (npx v1.8+).
- Repro capture of a whole OpenXR session: `perf_session` (Tapedeck record/replay; bundles a
  layer into the APK - ask before re-signing the user's build).
- Use `perf_trace_capture_start` / `_stop` around a scripted scenario instead of a fixed
  duration when the interesting part is one interaction.
- For a deep trace investigation, Meta's `hz-perfetto-debug` skill (from the `meta-vr`
  plugin) goes further.

## 5. Reporting back

- Name the source of every Meta fact: the doc page, the API entry, or the SDK source file.
- For device findings, say which device (model + OS build from `metavr_device info`) and
  whether it was worn.
- For performance, give baseline vs change with the same metric, the same scene state and the
  same device, and say what was NOT measured (thermals over 30+ minutes, other content).
