# The headset (L2) and performance

Go to the device when the simulator can't answer:
- real tracking, hands, Capsense hands on controllers;
- the Adreno/Vulkan shader paths (clip distance, multiview);
- compositor layers;
- eye-buffer size and dynamic resolution;
- thermals and frame timing.

## Build and install

- **Development build.** Meta's build processor bundles `XrApiLayer_METAX_operator_*.aar`
  into development builds only.
  - Grep the build log for `Including XrApiLayer_METAX_operator`. A dev build that lost the
    layer looks exactly like a device that won't connect.
  - The `quest-build-deploy` skill's `unity_build.ps1 -Dev` does this.
  - The editor must be closed: batchmode needs the project lock.
  - **Wait on the build script's own exit**, not on a grep of its log. Run it in the
    foreground, or with `run_in_background` and wait for the notification. Its last lines
    are `NO APK` and/or `exit <code>`, and it refuses to build when a gate FAILs (the
    `[BuildGates] FAIL` lines say why). See pitfalls → "Never wait on a guessed log marker".
- **Gradle can fail to start on Windows** when Java NIO's AF_UNIX pipe cannot be created
  under the default TEMP, and the TCP fallback never triggers. Point `TEMP`/`TMP` at a short
  local folder for the build process (`unity_build.ps1 -BuildTemp C:\unity-build-temp`).
- **adb** comes from Android platform-tools: `$ADB`, PATH, or `metavr_software_paths` from
  the Horizon OS MCP. Install with
  `adb install -r -g Build\<App>-dev.apk`.
- **A first-time USB debugging prompt** appears *inside* the headset, and only the wearer
  can accept it. If `adb devices` shows `unauthorized`, ask the user to put it on and allow
  it.
- **Windows Firewall prompts** (e.g. for the simulator's `local_sharing_server`) are the
  user's decision. Don't click them.

## When the Operator layer crashes the app (SDK 205, Horizon OS 2026-09)

**Symptom:** after a Horizon OS update (build of 2026-09-24) every development APK aborted at
launch - SIGABRT, `FORTIFY: pthread_mutex_lock called on a destroyed mutex` inside
`libXrApiLayer_METAX_operator`, right after `AgenticLayerXrDestroyInstance`. The release APK
(no layer) ran. Unity's OpenXR plugin creates and destroys a throwaway instance first; the
layer tears its MCP server down on that destroy, and the server thread it starts for the
real instance locks the freed mutex. Nothing app-side fixes it, and the dev build has no
switch to leave the layer out.

**Workaround, and it keeps the whole tool surface:**
1. `assets/OperatorLayerExclusion.cs` (Editor): an `IPreprocessBuildWithReport` at
   callbackOrder 100 - after Meta's processor - that calls
   `SetIncludeInBuildDelegate(_ => false)` on the operator AAR's `PluginImporter` when
   `QUEST_NO_OPERATOR=1`. Give the dev-build script a `-NoOperator` switch and grep its log
   for "excluding XrApiLayer_METAX_operator".
2. `assets/DevCommandChannel.cs` (runtime, dev builds): polls
   `persistentDataPath/<prefix>-cmd.json` five times a second, runs each call through the same
   `AgentTools` handlers, appends `{id, tool, t, result}` lines to `<prefix>-out.jsonl`.
3. `scripts/adbtools.py`: the host side - push under a temp name then `mv`, read back with
   `adb shell cat` and match the id in Python (`adb shell` strips the quotes off a grep
   pattern), decode UTF-8, and `adbtools.py worn` before blaming a timeout on the app.
Register app tools in a layer-independent registry first and hand them to the layer only
if it is present, so the Operator path and this one share every handler. Re-test the layer
after each OS or SDK update; drop the switch once a dev build with the layer launches again.

## Operator on the device, per session

Reboots clear all of this:
```powershell
adb shell setprop debug.oculus.experimentalEnabled 1                    # agentic path is behind this flag
adb shell setprop debug.meta_xr_operator.request_capture_permission 1   # front-load the capture consent
adb shell setprop debug.meta_xr_operator.verbose 1                      # optional: [inputdiag] lines in `logcat -s AgenticXR`
adb forward tcp:8720 tcp:8720
```
Then `op.py` and the MCP proxy talk to the headset exactly as they do to the editor.

- The app must be **running and focused**, because the MCP server lives in its process.
- The headset must be **worn**: `adb shell getprop sys.hmt.mounted` must print `1`.
  - Off a head, Horizon OS suspends the app within seconds and shows "Finding position in
    room".
  - Every tool then times out "waiting for main thread". That reads like a broken tool; it
    is an unworn headset.
  - Scripts should poll the prop and wait rather than fail.
- `openxr_set_head_pose` does nothing on a device (the head is the real head). Controller
  injection works but fights the real controllers, so ask the wearer to put them down.
- `openxr_capture_composited_image` works here (unlike the simulator), and so does
  hzos-dev-mcp `device_screenshot`.

## A readout, not a screenshot session

Make the app log one self-report line per question at startup and on key events: the
render path chosen, the eye-buffer size, the resolved font, whether the Operator tools
registered, what loaded and from which tier, and every exception. Then one script answers
a device session without anyone describing what they see. The `quest-build-deploy`
skill's `quest_deploy.py readout` is the pattern:
1. Wait for `sys.hmt.mounted == 1`, and optionally install.
2. Grow and clear the log buffer: `logcat -G 32M; logcat -c`. The default ring buffer has
   dropped captures.
3. `am force-stop`, then launch with
   `monkey -p <pkg> -c android.intent.category.LAUNCHER 1`.
4. Stream `logcat -v time -s Unity:V AgenticXR:V` for N minutes. Stream it, don't `-d`.
5. Print the last matching line for each question, then every `Exception` / `FAIL` /
   `NullReference`.

## Performance numbers you can trust

- **VrApi logcat is the ground truth, one line a second per rendering process:** `FPS=61/72`,
  `App=13.9ms` (app GPU time), `GPU%=0.99`, `Stale` (frames the compositor re-showed), and
  **`SF=` - the eye-buffer scale dynamic resolution is using right now** (1.23 = the
  maximum on one app, 0.80 = its floor). Cut logcat into windows with the headset's own
  clock (`adb shell date +%H:%M:%S` before and after each scripted step) and summarise each.
- **A scripted perf scene that pins dynamic resolution reports the MAXIMUM resolution**, and
  a whole round of "SF=1.23" logs came from exactly that. What the user sees under load can
  be SF 0.80 - which the user then reported as "text too sharp, with less resolution". Look
  at SF in an unscripted session before concluding anything about resolution.
- **OVRManager's dynamic resolution rewrites `XRSettings.renderViewportScale` every frame.**
  To pin a scale for an A/B, turn `enableDynamicResolution` off first, or the pin does nothing
  and the lever looks "ineffective".
- **Lines from a second pid** mean another immersive process (the system shell) rendered at
  the same time and shared the GPU; don't count its frames against the app.
- **A/B levers at runtime, not by rebuilding.** A dev tool that flips one thing
  (`myapp_render_switch {name, value}`: clip method, a render pass, MSAA, a renderer group, a
  scenario) and logs a marker line, driven over the channel while VrApi windows are summarised,
  measured six levers in one ten-minute session. Found that way on a production app: an always-on
  `SV_ClipDistance` write cost ~40% of the frame on Adreno 740 multiview (discard was cheap);
  translucent meshes drawn in two passes cost about half the frame.
- **Allocation per frame**: `OVRManager` already calls `OVRInput.Update()`; app code calling it
  again allocated ~4 KB a frame. An allocation probe per system (GC.GetAllocatedBytesForCurrentThread
  deltas around each Update section) found it.
- **Check the device model** in the Unity startup lines (`Device Model 'Oculus Quest 3S'`) before
  quoting Quest 3 numbers.
- **USB drops silently.** A background logcat recorder then exits 255 and its file ends; check
  `adb devices` before reading a log as the user's session.

## Things only the device's GPU can answer - make the app ask

A texture format, a sampler state or a render feature can work in the editor (D3D) and come
back as zeros on the Adreno, and "nothing appears" is all anyone sees. After uploading
anything the device must render, have the app **read a few known values back from the GPU**:
a tiny probe shader samples them into an N x 1 float target, `AsyncGPUReadback` returns them,
and the app compares with what it uploaded - falling back to another format, or refusing with
a message, on a mismatch (a `CtGpuProbe`: 16 voxels of a 3D R16 texture). And log
one line per change of "shown / not shown - because ...", so a logcat answers why a feature
is invisible without anyone describing the view.

## Performance with hzos-dev-mcp

Load the tools with ToolSearch; they're prefixed `mcp__hzos-dev-mcp__` or
`mcp__plugin_meta-vr_metavr__`.
- **Capture:** `perf_trace_capture {mode: "vr", duration_ms: 10000, app: "<package>"}`,
  headset worn and app in the state under test. Or use `perf_trace_capture_start` /
  `_stop` around a scripted scenario.
- **Analyse:** `perf_trace_analyze` (frame timing, CPU- or GPU-bound, stale frames),
  `perf_trace_gpu_counters`, `perf_trace_thread_state`, and `perf_trace_query_sql` for
  anything specific.
- **Compare:** capture a **baseline on the unchanged build first**, e.g. keep
  `Build/baseline-<date>-dev.apk`. Then run `perf_trace_compare` after each change, one
  change at a time.
- Make the states repeatable: a dev-only app tool that fixes the scene pose relative to the
  head and toggles the knobs under test. Keep dynamic resolution off while profiling, or
  numbers from different runs aren't comparable.
- For deeper analysis, load the `meta-vr:hz-perfetto-debug` skill.
