---
name: unity-quest-sim-loop
description: Test and debug a Unity Meta Quest app without the headset. Runs it in editor Play Mode on the Meta XR Simulator and drives it through the Meta XR Operator (port 8720) plus the app's own agent tools - inject controller and head poses and buttons, press UI for hand-tracking apps, query app state, capture the eye view, pixel-diff one object's colour, run JSON scenario suites that assert on app state, then stop, refresh and replay after each edit and pin findings with a headless gate. Works on Meta XR SDK 205 and on older SDKs such as 203, and covers passthrough apps. Also the headset follow-up (dev APK, adb, logcat, VrApi numbers). Use it whenever the user wants to verify, test, reproduce or look at a Quest/Unity XR feature; mentions the XR Simulator, XR Operator, xrsim or openxr_* tools; reports something wrong in the headset (invisible or untextured objects, dead buttons, overlapping UI); or wants this loop in a new project.
---

# Unity Quest simulator loop

A picture of a VR scene can't tell "the button did nothing" from "the ray wasn't on it".
A headset round trip costs about 4 minutes and needs someone wearing it. So this loop swaps
*looking* for *asking*:
- The app runs in the Unity editor against the **Meta XR Simulator**.
- The **Meta XR Operator**, an OpenXR API layer inside the app's own process, serves MCP on
  `127.0.0.1:8720`.
- Through it you read the app's state, inject input, and read the state again.
- The headset is kept for what only real hardware can answer.

`<skill>` below means this skill's folder (the base directory shown when the skill loads).
Scripts are in `<skill>/scripts/`, C# templates and example scenarios in `<skill>/assets/`,
longer material in `<skill>/references/`. The scripts are plain Python 3.10+ (stdlib; Pillow
only for image diffs) and Windows PowerShell 5.1.

**Meta XR Core SDK 205 is not required.** On older SDKs the Operator layer is loaded by
environment variable, and the app's tools come through DevRemote (`references/setup.md`). The
loop runs in production on an SDK 203 passthrough app (DicomSegVR: controllers + fingertip UI,
AR ↔ a VR treatment room) and on an SDK 205 controller-first app.

## The pieces

| piece | where | for |
|---|---|---|
| Meta XR Simulator | desktop OpenXR runtime | a simulated Quest 3 with a head and Touch controllers |
| Meta XR Operator | API layer in the app, MCP on :8720 | 25 bundled tools (`openxr_*`, `unity_*`, `math_*`, `convert_*`) plus the app's own |
| MCP proxy | `%USERPROFILE%\meta-xr-operator\meta-xr-operator-mcp-proxy.exe` | stdio ↔ :8720; the backend URL is its first argument |
| app tools `<prefix>_*` | the project's AgentTools (editor + dev builds) | the app reporting on itself and acting for the hand: state, open a screen, press a named button, snapshot, renderers |
| DevRemote | editor, loopback HTTP :8731 (up to :8739 if taken) | status / play / stop / refresh / compile, plus `/tool/NAME` for the app's tools on any SDK |
| layer copy | `%USERPROFILE%\meta-xr-operator\layer\x64` | the Operator for projects whose SDK doesn't ship it (pre-205) |
| Horizon OS dev MCP (`metavr` / `hzos-dev-mcp`) | MCP | Meta docs + API search, device logcat and screenshots, Perfetto (the `horizon-os-mcp` skill) |
| adb command channel | `assets/DevCommandChannel.cs` + `assets/OperatorLayerExclusion.cs`, host side `scripts/adbtools.py` | the app's tools on a headset whose dev build must go without the Operator layer (device.md) |
| `scripts/run_scenario.py` | host | JSON scenario suites: call, wait, assert, aim, capture - the regression suite of L1 and L2 |
| `scripts/quickcheck.ps1` | host | L0: Roslyn compile of the project's assemblies in ~10 s without the project lock |
| `scripts/panelshot.py` | host | aims the simulated head at a named panel and snapshots it framed tightly, to read its text |

## Loops, cheapest first

| loop | cost | proves |
|---|---|---|
| **L0** `quickcheck.ps1` + headless gates / EditMode tests | 10 s – 90 s | it compiles (editor AND device defines), and the scene is wired as the gates expect |
| **L1** editor Play Mode + simulator + Operator (+ `run_scenario.py` suites) | seconds per check | the app runs, and simulated input changes state as intended |
| **L2** development APK on the headset + Operator over `adb forward` (or the adb channel) | ~4 min, needs a worn headset | real tracking, hands, GPU, performance |
| **L3** release APK + a smoke checklist | ~4 min | the build that ships (it has no Operator layer) |

Climb only as far as the question needs. Most bugs are found and fixed in L1. Building and
sideloading is the `quest-build-deploy` skill.

## 1. Find out where things stand

```bash
python <skill>/scripts/reload.py status            # editor: isPlaying, isCompiling, last 40 errors (finds the port)
python <skill>/scripts/op.py list                  # Operator tools + the app's [remote] tools, merged
```
- **"no Unity editor is running"** (at once, no probing): start one, step 2.
- **No DevRemote on 8731–8739:** the editor is still starting, or DevRemote is off in it. A killed
  editor can linger and keep 8731 for minutes, so DevRemote moves up and the scripts follow.
- **Every tool description starts with `[OFFLINE]`:** the proxy runs but no app is attached
  to :8720. Start Play Mode (step 2) or launch the dev APK on the headset.
- **The app's own tools are listed** (e.g. `myapp_*`): it's live. Go to step 3.
- **The project has no `DevXr` / `DevRemote` / `AgentTools`:** set it up first, see
  `references/setup.md`. The templates compile as-is on SDK 205 with asmdefs and on SDK 203
  in Assembly-CSharp; most of the work is the app's own tools file.

## 2. Bring the editor up in Play Mode on the simulator

```powershell
powershell -File <skill>\scripts\editor-play.ps1 -Project C:\path\to\MyQuestApp [-Restart]
```
The script:
- launches the GUI editor with `-executeMethod <Ns>.DevXr.CliPlay`, which opens the scene,
  activates the Operator and the simulator, and arms an auto-play that survives cold-start
  domain reloads;
- answers the modal "Recovering Scene Backups" dialog a killed editor leaves behind;
- waits until DevRemote reports `isPlaying:true`.

A cold start takes 2–4 minutes. Then wait until the app has registered its tools. This
happens after the OpenXR instance exists, not at Play:
`python op.py wait myapp_get_state 180`.

Headless Unity runs (gates, tests, builds) take the project lock, so the editor must be
closed for them. Only the Roslyn quickcheck runs beside an open editor. `-Restart` kills
every Unity editor, so if the user may be looking at it, say so before you do.

## 3. Drive it: ask → act → ask

Use the `mcp__meta-xr-operator__*` tools if this session loaded them (a project
`.mcp.json` registers them). Otherwise use the bundled client, which works from any
directory:
```bash
python op.py call myapp_get_state
python op.py call openxr_set_controller_input @press.json   # args from a file: no quoting fights in PowerShell/bash
python op.py batch scenario.json --out <scratchpad>/shots   # [[tool, args], ["sleep", {"s": 0.4}], ...] in one session
```
Shape every check the same way:
1. Read the state with an app tool.
2. Inject the input.
3. Read the state again and compare.

A check that ends in "the screenshot looks right" asserted nothing.

The things that cost hours to learn (details and more recipes in `references/operator.md`):
- **Coordinates:** OpenXR `local_floor` is Unity world with **z negated**. Quaternions
  negate **x and y**.
- **Buttons:** `openxr_set_controller_input {hand, component, value, auto_release: true}`.
  - Components are Trigger, Grip, A, B, X, Y, Menu, Thumbstick and ThumbstickClick.
  - Thumbstick also takes `sub_component` X or Y.
  - Leave ~0.3 s between a pose change and a press, so the rig has read the new pose.
- **Aiming:** the Interaction SDK builds the controller ray from the **grip** pose plus
  Meta's fixed offset, so setting the `aim` pose moves nothing. Use
  `scripts/aimfix.py HAND fx fy fz tx ty tz --tool <prefix>_get_input_state` (Unity world
  coordinates), or an `aim` step in a scenario. It reads the ray the app reports and corrects
  the grip until the ray hits the target to within 0.3°.
- **Control vs aim:** when a button "doesn't work", compare two presses:
  - an app tool that invokes the widget directly (`myapp_click_widget`);
  - a simulated trigger through the ray.

  Fails both ways → the handler logic. Fails only through the ray → aim, the raycast, or
  the event path.
- **Fingertip-touch UI** ignores controller rays: the ray can converge on a button to 0.1°
  and hover nothing, because those canvases are built for fingertip touch. The Operator
  can't move hand joints, so the app needs two tools:
  - one that presses through the same call the fingertip makes (`myapp_press` → the
    button's own `TryPress`);
  - one that pushes a stand-in fingertip collider through the button (`myapp_poke`). That
    tests the physics link `press` skips: collider placement, size and layers.

  Press works but poke fails → a collider or layer bug. Only real hand tracking and gesture
  detection (a palm menu) are left for the headset.
- **Head:** `openxr_set_head_pose` works in the simulator. It also re-seeds both
  controllers, which lose their pose and switch to `simulated: true`, so read the grip poses
  first and restore them afterwards. On a device the head follows the real headset.
- **Quaternions at full precision:** `[0.5, 0, 0, 0.8660254]`, never `0.866`. A slightly
  non-unit quaternion makes the Interaction SDK log "Quaternion To Matrix conversion failed"
  every frame (5,000 lines in two minutes).
- **Put things back.** Restore every pose and toggle you changed, then compare a final
  capture with your first one. The user, or the next check, inherits the session.
- `unity_find_interactables` only sees uGUI `Selectable`s. Custom widgets need an app tool
  that lists them.

## 4. Make it a suite: JSON scenarios that assert

Every check worth doing twice becomes a scenario file, run by `scripts/run_scenario.py`
against the editor (L1) or a dev build on the headset (L2, `--device`). The app's answers are
asserted, not eyeballed, and a failing step prints the **symptom as the user would see it**.

```bash
python <skill>/scripts/run_scenario.py <project>/tools/sim-scenarios/*.json --prefix myapp --project <project>
python <skill>/scripts/run_scenario.py smoke.json --prefix myapp --device --pkg com.Company.App
```
```json
{"name": "load_sample", "steps": [
  ["myapp_load_sample", {"id": "demo"}],
  ["wait",   {"tool": "myapp_get_state", "path": "dataset.ready", "equals": true, "timeout": 90,
              "symptom": "the sample never finishes loading"}],
  ["assert", {"tool": "myapp_get_state", "path": "windows[*].title", "none_contains": "Downloading",
              "symptom": "the window title is stuck on 'Downloading 100%'"}],
  ["aim",    {"hand": "right", "target": {"tool": "myapp_ui_point", "args": {"name": "Close"}},
              "expect_hovered": "Panel_Viewer"}],
  ["openxr_set_controller_input", {"hand": "right", "component": "Trigger", "value": 1, "auto_release": true}],
  ["assert", {"tool": "myapp_get_state", "path": "windows[id=viewer].open", "equals": false}]]}
```
- Steps: any tool call, `sleep`, `wait`, `assert`, `capture` (remember a value, compare later
  with `greater_than: {"var": ...}`), `aim`, `composite` (save the composited eye image),
  `layers_match` (compositor layers sit exactly on their canvases). The full grammar is the
  script's docstring; `assets/scenarios/` has starting points.
- **No vacuous passes:** nothing at the path, an `{"error": ...}` answer or a non-JSON answer
  fails every check. A tool that threw must never turn "no title contains Downloading" green.
- **Set up deterministically, then restore.** Close every window, reset tuning, put the head
  at a known pose, and undo it all at the end, so the suite runs in any order.
- Keep suites in the project (`tools/sim-scenarios/`), named after what they protect, and
  re-run the touched ones after every fix. On the DicomSegVR app, 55 L1 scenarios cover
  input, panels, the RT tools, the AR ↔ VR room switch and teleport.

## 5. Look at it, when a picture really is the question

Capture from the pose you found. A narrow snapshot fov zooms without moving anything.
Move the head only if the object isn't in view: that re-seeds the controllers, and you
then have to restore them.

**Passthrough apps:** the composited image shows the simulator's synthetic room (a bedroom)
where passthrough would be, which is the honest "what the user sees". The app snapshot has a
transparent background.

Three ways to capture, best first:
- **`openxr_capture_composited_image {eye: "left"|"right"}`** returns what the runtime
  actually composited for that eye (840×880 in the simulator), compositor layers included.
  It works on simulator v207 (v205 answered "not instrumented"); if it fails, fall through.
- **The app's snapshot tool** (`myapp_snapshot {width, height, fov, name}`) renders the
  centre eye offscreen with the real camera and skybox, at any size and field of view. A
  narrow fov (18–30°) makes a close-up without moving anything. In the editor the PNG lands
  in `<project>/Temp/<prefix>-snapshots/`. Unity wipes `Temp` on every launch, so copy
  keepers to the scratchpad.
- **`scripts/grab-window.ps1 -Title "Meta XR Simulator" -Out <path>`** captures a window
  with PrintWindow.

**To read a panel's text,** `python scripts/panelshot.py --prefix myapp Panel:Settings settings [--click TabAdvanced]`
turns the head to the panel, sizes the fov to it and snapshots at a resolution text can be
read at. It re-reads the panel list after the head turn (the app may re-lay the workspace
out) and leaves the controllers re-seeded. A panel drawn as a compositor layer is a HOLE in
the app snapshot: capture composited, or switch the compositor path off.

Open the PNG with Read and look critically. Is every structure the colour it should be? Are
panels overlapping? Are controllers textured? Is the floor there? Send it with
SendUserFile when the user needs to see it.

**To prove one object's colour or visibility, diff instead of eyeballing.**
1. Capture the frame with the object shown.
2. Toggle only that object off (through an app tool) and capture the same frame.
3. Toggle it back on and capture again as a control.
4. Run `python scripts/imgdiff.py ON.png OFF.png --control ON2.png --expect "#ff3b30"`. It
   prints the object's own pixel count, median colour, hue histogram and noise floor, and
   writes a mask image.

Those numbers plus the mask are evidence; a crowded screenshot is an argument.

When something is "invisible, flat or untextured", query before you theorise.
`myapp_debug_renderers {contains}` gives active, visible, material, shader, texture, colour,
queue, layer and bounds for each match. That tells a missing texture from a hidden object
from something drawn *over* it. The last one was a reversed-Z skybox painting over every
opaque object; see `references/pitfalls.md`.

## 6. Edit → reload

1. **Never let C# recompile during Play Mode.** A mid-play domain reload kills the
   Interaction SDK and MRUK: one save produced 32k NullReferenceExceptions. `CliPlay` sets
   `EditorPrefs ScriptCompilationDuringPlay = 1` (recompile after playing).
2. **Compile first** with `scripts/quickcheck.ps1 -Project <project> [-Editor] [-Dev]` (~10 s,
   no project lock). It compiles against Unity's own response files, so the editor defines
   AND (`-Dev`) the player's defines are checked: dev-only code that leaks into a release
   build fails here, not after a 20-minute APK build.
3. **Reload:** `python scripts/reload.py --wait-tool myapp_get_state`. It stops Play Mode,
   POSTs `/refresh`, waits for the compile, refuses to play on compile errors, plays, and
   waits for the app's tools. `/refresh` matters because an editor without window focus never
   imports files changed on disk. If stopping Play hangs (no `isPlaying:false`, DevRemote
   silent), don't wait: `editor-play.ps1 -Restart`.
4. **Shaders, materials and textures:** `python scripts/reload.py --refresh-only`. They
   hot-reload in Play Mode.
5. **Errors:** DevRemote's `/status` holds the last 40. For Editor.log
   (`%LOCALAPPDATA%\Unity\Editor\Editor.log`) or a batchmode log, run
   `python scripts/logscan.py [LOG] [MARKER] [--info]`. It prints distinct warnings and errors
   with counts and origins, so 30,000 identical NREs read as one line. Use
   `"entering Play Mode"` or your app's own startup line as the MARKER to scope it to this
   Play session. Add `--info` when the complaint is "console spam": that is usually a
   per-frame or per-second `Debug.Log`, not an error.
6. **Re-run the same scenarios** and compare with the previous answers.

## 7. Pin it with a gate

A simulator finding isn't done until a headless check would catch it again:
- Write the gate or EditMode test and run it green. Then **revert the fix once and watch it
  go red**, and restore it. A gate never seen failing proves nothing.
- Write failure messages that say how the bug *looks in the headset*, for example "the sky
  is drawn over every opaque object: controllers, floor, highlights". Recognising a bug has
  always cost more than fixing it.
- **Build the fixture the way the app builds it.** UI gates that built panels with their
  final data and the default font passed while the headset showed overlapping text; built
  EMPTY, then fed through the app's own events with the production font, the same gate
  found 20 failures. The same goes for any state the app reaches in steps.
- **Porting maths or geometry from another codebase** (a web viewer, a server): run the
  original under Node or Python on fixed inputs, save the results as a JSON fixture with the
  script that made it, and gate the port against it. "Looks the same" is not a check.
- Pixel gates need a graphics device: batchmode **without** `-nographics`. Under
  `-nographics`, ReadPixels returns uniform grey, which gives a confident, fabricated
  verdict. The gate must also render the app's *real* frame, including its skybox. A check
  that clears to a solid colour isn't checking the app.

## 8. The headset (L2)

When the simulator can't answer, go to the headset. That covers real tracking,
hands/Capsense, the device GPU and shader paths, compositor layers, and performance. See
`references/device.md` for:
- the development build (the Operator AAR ships only in dev builds);
- `adb install -r -g`;
- the `debug.*` sysprops and `adb forward tcp:8720 tcp:8720`;
- **the headset must be worn** (`sys.hmt.mounted = 1`), or every Operator call times out
  "waiting for main thread";
- a scripted first readout from logcat;
- **when the Operator layer crashes the dev build at launch** (SDK 205 on the Horizon OS of
  2026-09-24): build without it and drive the same tools over adb (`DevCommandChannel` +
  `adbtools.py`, or `run_scenario.py --device`);
- **reading VrApi honestly:** `SF=` is the eye-buffer scale dynamic resolution chose, and a
  scripted run that pins it measures the best case, not what the user sees;
- runtime A/B switches over the channel instead of rebuilds, and GPU read-back self-tests
  for anything the editor's D3D can't vouch for;
- **waiting on a build:** block on the build script's own exit, or run it in the
  background and act on the notification. Never loop on `grep` for a log line you haven't
  copied from the script, and always pair a poll with a "producer process is gone" exit
  (`references/pitfalls.md` → "Never wait on a guessed log marker").

For Meta docs, API lookups, device logcat/screenshots and Perfetto traces, use the
`horizon-os-mcp` skill: check a Meta SDK name against the docs before relying on memory,
because names change between SDK versions.

## Reporting back

- Say where each claim was verified (simulator, device, or gate) and what was **not**.
- Attach the snapshots that show it.
- Rendering and performance behaviour seen only in the simulator stays "unverified on the
  headset" until a worn device confirms it. The simulator runs D3D on a desktop GPU, not
  Vulkan on Adreno.
- Before committing, check `git status` for assets the editor rewrote during play (TMP
  font assets, scenes, `Assets/_Recovery`) and revert the ones you didn't mean to change.
