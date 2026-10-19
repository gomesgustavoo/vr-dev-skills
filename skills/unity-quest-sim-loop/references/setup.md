# Setting the loop up

Do this once per machine, then once per project. Copying from `assets/` is faster than
rebuilding from Meta's docs; the templates are proven on both common layouts:

| layout | SDK | shape |
|---|---|---|
| asmdefs (`MyApp.Runtime` / `MyApp.Editor`) | Meta XR Core 205 | controllers + hands |
| Assembly-CSharp, no asmdefs (DicomSegVR) | Meta XR all-in-one 203 | controllers + fingertip UI, passthrough |

## Machine (once)

1. **Meta XR Simulator:** `npx -y metavr tools install xrsim`. Check it with
   `npx -y metavr tools info xrsim --format plain` (look for `Installed: Yes`).
   - It updates itself. On 2026-09-24 a per-user v205 install became a system-wide
     `C:\Program Files\MetaXRSimulator\v207.0`. The DevXr template copes with the stale
     registry entry that update leaves behind.
   - Unity finds the simulator through the `xrsim://` protocol handler (HKCU, else HKLM).
2. **The Operator, copied out of a Core SDK 205+ package.** Copy both to stable paths,
   because the PackageCache folder name carries a hash that changes:
   ```powershell
   $op = Get-ChildItem <a 205+ project>\Library\PackageCache -Directory -Filter "com.meta.xr.sdk.core@*" | Select-Object -First 1
   $dst = "$env:USERPROFILE\meta-xr-operator"
   New-Item -ItemType Directory -Force "$dst\layer\x64" | Out-Null
   Copy-Item "$($op.FullName)\Editor\MetaXROperator\Tools~\Windows\meta-xr-operator-mcp-proxy.exe" $dst -Force
   Copy-Item "$($op.FullName)\Editor\MetaXROperator\x64\XrApiLayer_METAX_operator.*" "$dst\layer\x64" -Exclude *.meta -Force
   ```
   - **The proxy** (`meta-xr-operator-mcp-proxy.exe`) is what `op.py` and `.mcp.json` talk
     to.
   - **The layer** (`XrApiLayer_METAX_operator.dll` + `.json`) is a plain OpenXR API layer.
     It lets a project on an **older SDK** have the Operator's `openxr_*` tools. DevXr loads
     it with `XR_API_LAYER_PATH` / `XR_ENABLE_API_LAYERS` for each Play session, exactly as
     Meta's own enabler does for OpenXR plugins before 1.17.
3. **Optional native MCP:** a project `.mcp.json` makes the Operator's tools first-class
   (`mcp__meta-xr-operator__*`) for a Claude Code session started in that folder:
   ```json
   { "mcpServers": { "meta-xr-operator": { "type": "stdio",
       "command": "C:\\Users\\<you>\\meta-xr-operator\\meta-xr-operator-mcp-proxy.exe", "args": [] } } }
   ```
   `scripts/op.py` does the same job from any directory, and it also merges in the app's
   DevRemote tools, which native MCP does not.
4. **If DevRemote can't bind** (`HttpListenerException 5`), add a one-time URL reservation
   per port: `netsh http add urlacl url=http://127.0.0.1:8731/ user=%USERNAME%`.

## Project (once)

**Which SDK?** Run
`grep -rl "class MetaXROperatorExternalTool" Library/PackageCache/com.meta.xr.sdk.core@*`.

| | Core SDK 205+ | older (203, 201, ...) |
|---|---|---|
| Operator `openxr_*` tools | Meta's own activator | layer copy loaded by DevXr (machine step 2) |
| app tools over MCP | `OperatorBridge.cs` forwards AgentTools | not possible (no C# binding) |
| app tools over HTTP | DevRemote `/tool/*` | DevRemote `/tool/*` (the only way) |
| on the headset | dev APK carries the Operator | nothing to attach to; use logcat |

Either way, `op.py` shows one merged list. Don't upgrade the SDK just for this loop: that
change touches every Meta API the project uses, and it's the user's call.

Copy the templates from `assets/` and replace their placeholders:

| placeholder | meaning | example |
|---|---|---|
| `__NS__` | root namespace | `DicomSegVR` |
| `__MENU__` | editor menu root | `DicomSegVR` |
| `__SCENE__` | scene to play | `Assets/Scenes/SampleScene.unity` |
| `__PREFIX__` | tool prefix | `dsvr` |

1. **`DevXr.cs` → `Assets/Editor/`.**
   - Standalone OpenXR setup: the loader with Initialize-on-Startup, the Meta feature set,
     API Layers, and the Touch/Touch Plus profiles. Standalone only; the Android settings
     are untouched.
   - Simulator activation, with a registry fallback for the auto-updater's stale key.
   - The Operator layer on older SDKs.
   - `CliPlay`: opens the scene, activates everything, starts DevRemote, and arms auto-play
     both now and after any reload. It also sets `ScriptCompilationDuringPlay = 1`.
   - With an editor asmdef, add `Unity.XR.Management(.Editor)` and `Unity.XR.OpenXR(.Editor)`.
2. **`DevRemote.cs` → `Assets/Editor/`.** Loopback HTTP with routes `/status`, `/play`,
   `/stop`, `/refresh`, `/compile`, `/tools` and `/tool/NAME`.
   - It skips import workers.
   - It stops before Play-Mode reloads and uses `Abort()`.
   - If 8731 stays taken, it moves up to 8739 and writes `Temp/DevRemote.port`. The
     scripts find it either way.
3. **`AgentTools.cs` + `AppAgentTools.cs` → the runtime assembly** (e.g. `Assets/Scripts/Dev/`).
   - **`AgentTools`** is the SDK-independent registry, reached by DevRemote through
     reflection.
   - **`AppAgentTools`** holds the generic tools: `get_scene`, `get_input_state`,
     `snapshot`, and `debug_renderers` (which reports the property-block colour).
   - Both register themselves via `RuntimeInitializeOnLoadMethod`.
   - With a runtime asmdef, reference `Oculus.VR` (and `Oculus.Interaction` for the input
     tool). Assembly-CSharp needs nothing.
   - They're guarded by `#if UNITY_EDITOR || DEVELOPMENT_BUILD` only. Never use an asmdef
     versionDefine: in Assembly-CSharp it is never defined, and the file silently compiles
     to nothing.
4. **SDK 205+ only: `OperatorBridge.cs`**, which forwards every AgentTools tool to the
   Operator. It boots itself and retries for a minute, because the OpenXR instance can come
   up after `Start`.
   **Optional, for the headset: the adb command channel.** `DevCommandChannel.cs` (runtime,
   dev builds; create one in the bootstrap and call `Tick(Time.unscaledTime)` from Update)
   and `OperatorLayerExclusion.cs` (Editor; builds without the layer when
   `QUEST_NO_OPERATOR=1`) serve the same AgentTools over a file in `persistentDataPath`, and
   `scripts/adbtools.py` is the host side. Add them when a dev build carrying the Operator
   layer will not launch on the device (device.md), or when you want the headset scriptable
   without `adb forward`. Both were compiled against an SDK 205 project's generated references.
5. **The app's own tools file.** This is where the value is (see below).
6. **Git hygiene:** add `/Assets/_Recovery/` to `.gitignore` (`editor-play.ps1` answers
   "Recovering Scene Backups" with Yes). Leave all of this uncommitted until the user
   decides; it's dev-only code in their app.

**Compile before opening Unity.** Compile the new files against the project's own
generated response file, with editor defines, and swap in the new versions of any files
already listed. This is how every template here was checked, including against the 203
project.

**Verify:**
1. `editor-play.ps1 -Project <path>` prints PLAYING, and names the port if it isn't 8731.
2. `op.py list` shows `openxr_*` online, not `[OFFLINE]`, plus the `<prefix>_*` tools.
3. `op.py call <prefix>_snapshot`, then open the PNG.

## The app's own tools: act for the hand, report the state

Every time you catch yourself guessing app state from a picture, add a tool that returns it.
Every time the agent can't do something because it has no hand, add a tool that does it
through the **same entry point** the hand uses.

**DicomSegVR** (`Assets/Scripts/Dev/DicomSegVRAgentTools.cs`, SDK 203, hands-only,
passthrough) is the worked example:

| tool | why |
|---|---|
| `dsvr_get_state` | paired, open windows and titles, series, volume dims/RT/dose, viewer preset and slice, 3D bound, structures active, result of the last async action |
| `dsvr_load_demo {id}` | the offline demo, selected as "Try demo samples" does, minus the Account window's network call; async, poll the state |
| `dsvr_open_tab {id}` / `dsvr_close_tab` | the palm menu opens only on a tracked palm-up pose, so this goes straight to `WorldWindowSpawner.Spawn` |
| `dsvr_list_controls {window}` | every Button/Slider/Toggle with name, label, interactable and world position |
| `dsvr_press {name}` | `WorldSpaceTouchButton.TryPress`, the call a fingertip makes (active + interactable + cooldown); `force` falls back to `onClick` |
| `dsvr_poke {name}` | a stand-in 9 mm fingertip (kinematic trigger sphere, default layer) pushed through the button's collider: tests the physics link `press` skips |
| `dsvr_set_slider` / `dsvr_toggle_structure` | slice/density scrub; segmentation toggles through the controller's own API |

**A controller-first SDK 205 app** (`Assets/Scripts/App/OperatorTools.cs`) is the second example.
It has `get_app_state`, `list_panels` (custom widgets), `click_widget` (control vs aim),
`get_object_pose` / `object_action`, `get_plan_state` / `place_item`, `get_render_state`,
`snapshot` and `debug_renderers`.

A few rules for writing them:
- Every tool body runs on the main thread.
- Wrap every body in try/catch (AgentTools does it). An exception crossing into native
  code kills the app under test.
- Return JSON (the AgentTools helpers: `Q`, `V3`, `F`, `Str`/`Num`/`Bool`).
- For anything async (loading, network), start it, return `{"started":true}`, and expose
  progress in the state tool.
- Controllers that only exist while a window is open can be stale. Compare with Unity
  `!= null`, not `TryGet`'s bool.
