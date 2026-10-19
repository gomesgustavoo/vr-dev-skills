# Pitfalls that cost real time

Each one here was hit on a production Quest app. Each entry gives the symptom as it presented, then
the cause and the fix.

## Rendering

- **"Controllers have no texture", "the floor is missing", "the red highlight meshes
  are invisible", while translucent things look fine.**
  - Cause: a custom skybox shader pushed itself to the far plane with `clip.xyww`
    (depth 1). That is the far plane only under OpenGL. Under reversed-Z (D3D11/12 in the
    editor, Vulkan on Quest) depth 1 is the **near** plane, so the sky passed the depth
    test everywhere. It painted over every opaque draw that came before it, and only
    transparents (drawn after the sky) survived.
  - Fix: `positionCS = float4(clip.xy, clip.w * UNITY_RAW_FAR_CLIP_VALUE, clip.w)`.
  - How it was found: `debug_renderers` showed textured materials on objects that rendered
    flat, and a snapshot showed sky colour inside opaque silhouettes.
- **Every render gate was green through that bug** because all of them cleared to a solid
  colour and never drew the sky. A pixel gate must render the app's real frame (real
  skybox, real materials from the app's own factory), and must be seen failing once with
  the bug restored.
- **Pixel gates under `-nographics`** get a uniform grey back from `ReadPixels`, which
  gives a confident, fabricated verdict. Render in batchmode *without* `-nographics`.
- **The simulator isn't the device GPU.** It runs D3D on a desktop GPU. Clip distances,
  multiview, foveation and compositor layers still need the headset.

- **"The whole screen flashes when I turn the cut on."** Flipping a GLOBAL shader keyword
  (`Shader.EnableKeyword`) moved every draw of that shader to a new variant in one frame, and on
  Vulkan each variant x render state is a pipeline built on the render thread the first time
  it is drawn - with a cold pipeline cache after every install. Swapping materials the same
  frame (a never-drawn two-sided variant, a first transparent draw) adds more.
  - Fix: choose keywords once at boot and switch features with uniforms (a plane at infinity
    `(0,0,0,1)` clips nothing); warm every material x pass the scene can need in the real eye
    pass during a load screen (a one-frame strip behind the loading panel). A probe rendered
    mono at 32x8 does not match the multiview + MSAA eye pass and warms nothing.
- **A state test in WORLD space for something parented to a moving object** re-ran the whole
  "changed" path every frame the parent moved (keywords, culling, material swaps): pops
  mid-grab. Compare in the parent's local space. And a world `Renderer.bounds` of a rotated
  U-shaped mesh is far bigger than the mesh - test real extents (min/max of dot(n, v)).
- **Cyan objects, or lines missing, in the first editor frames** are Unity's async shader
  compilation placeholder, not the app. A vertex-expanded line shader draws zero-width under
  it. Wait a few frames (or disable async compilation for the check) before calling a
  shader broken.
- **Composited panels are holes in the app's snapshot.** A panel drawn as a compositor layer
  (`OVROverlayCanvas`) is not in the eye buffer the snapshot renders; use
  `openxr_capture_composited_image`, or switch the compositor path off for the shot.
- **A compositor watchdog that falls back at boot.** `OVROverlay.isOverlayVisible` is false
  while the app has no input focus (boot, the system menu, headset off), so a watchdog that
  counts invisible frames there drops panels to the eye buffer for nothing. Count only while
  `OVRManager.hasVrFocus`, and log why it fell back.
- **"Text too sharp / aliased with less resolution" on the device only** was the eye buffer
  at dynamic resolution's floor (VrApi `SF=0.80`) while every scripted measurement had pinned
  it at the maximum. Panels as compositor layers keep text at display resolution whatever
  the eye buffer does. See device.md, "Performance numbers you can trust".

## Editor and domain reloads

- **Saving a script during Play Mode** reloaded the domain mid-play: the Interaction SDK
  and MRUK threw ~32,000 NullReferenceExceptions. Keep `EditorPrefs.ScriptCompilationDuringPlay = 1`
  (DevXr's `CliPlay` sets it), and use stop → refresh → play (`reload.py`).
- **Asset-import worker processes run `[InitializeOnLoad]` code too.** One of them bound
  DevRemote's port before the editor did, and another consumed the auto-play pref. Return
  early when `AssetDatabase.IsAssetImportWorkerProcess()`.
- **A killed editor leaves three things behind:**
  1. its HTTP port, held for a few seconds (DevRemote retries its bind);
  2. the modal "Recovering Scene Backups" on the next launch (`editor-play.ps1` answers
     Yes);
  3. a stale `Temp/UnityLockfile` that makes batchmode exit **without writing a log**.
     Delete it if no Unity process runs.
- **An editor that hangs on the way out.** Stopping Play Mode against the simulator, or
  closing the editor while playing, can leave `Unity.exe` alive with frozen memory use after
  Editor.log already ends in the final `##utp:{"type":"MemoryLeaks"...}` line.
  - The shutdown is complete, but the process still holds the project lock.
  - Kill it (`taskkill /F /PID <pid>`) and relaunch with `editor-play.ps1`. That's faster
    than waiting.
  - If the log does *not* end with that line, it's still working. Wait.
- **Stopping Play Mode hangs** (`reload.py` waits forever for `isPlaying:false`, DevRemote
  stops answering) after a long session on the simulator. Don't wait it out:
  `editor-play.ps1 -Restart` kills and relaunches, a cold start of 2-4 minutes.
- **The editor closing on its own mid-session** (the log shows a clean
  `[LAYOUT] About to save layout` shutdown).
  - It can be a person closing the window.
  - It can also be the **Meta XR Simulator's auto-updater**. On 2026-09-24 it swapped the
    per-user v205 install for a system-wide v207 (`C:\Program Files\MetaXRSimulator\v207.0`)
    while the editor was playing on it. The installer closed the editor, left an unkillable
    `Unity.exe`, and left the per-user `xrsim://` key pointing at the deleted exe.
  - With that stale key, Meta's detector reports "not installed" and the Activate item stays
    grey. Play then runs on the default runtime (`[MetaXRFeature] Feature is unavailable`,
    every Operator tool `[OFFLINE]`).
  - The DevXr template's `EnsureSimulatorRuntime` works around it by pointing
    `XR_RUNTIME_JSON` at whichever install still exists. A Play session that already failed
    to start OpenXR needs an editor restart.
  - Check `C:\Program Files\MetaXRSimulator\` and `%APPDATA%\metavr\tools\xrsim` before
    blaming the project.
- **Unity wipes `<project>/Temp` at every launch.** Snapshots written there vanish, so
  copy them somewhere outside the project right away.
- **A background editor doesn't import changed files.** Anything edited from outside
  (shaders included) sits unimported until it gets focus. POST `/refresh`.
- **`delayCall` doesn't survive a domain reload.** Opening a scene can trigger one, which
  is why auto-play is armed with an EditorPref, not a delayCall.

- **A cold start that never reaches Play, with no error.**
  - `CliPlay` armed auto-play and enabled DevRemote only through EditorPrefs, which are read
    at the next domain reload. When the scene was already open, nothing reloaded: no Play,
    and no remote to press it through.
  - The template now starts both immediately. Look for `dev XR: armed auto-play.` in the log.
- **Killed editors linger.** A force-killed `Unity.exe` can stay in the process list for
  minutes, or until reboot, still holding its ports.
  - DevRemote steps from 8731 up to 8739 and the scripts follow.
  - If a lingering editor holds **8720**, the new editor's Operator cannot listen and every
    tool reads `[OFFLINE]`. Check `netstat -ano | findstr :8720` before blaming the layer.
- **A socket leaked across a domain reload** kept 8731 bound inside the same editor. DevRemote
  now stops on `ExitingEditMode` / `ExitingPlayMode` and uses `Abort()`. `reload.py` re-probes
  the port whenever a call fails, because DevRemote may come back on another one.
- **DevRemote dark after a clean Play Mode stop** (`reload.py stop` → "TIMEOUT waiting for:
  DevRemote to answer", nothing listening on the port in `DevRemote.port`, no domain reload in
  Editor.log). The stop-on-`ExitingPlayMode` above only comes back through the static
  constructor, i.e. a domain reload, and Unity reloads on leaving Play Mode only when a script
  changed meanwhile. The template now also calls `Start()` on `EnteredEditMode` /
  `EnteredPlayMode` when enabled (a no-op when a reload already started it). A copy that never
  stops on play-mode changes doesn't have this bug. Found in DicomSegVR.

## UI text and panels

- **Labels overlapping, or chips on top of the text they follow, only after data arrives.**
  A TMP label created under an INACTIVE parent never runs Awake, so `GetPreferredValues` /
  `preferredHeight` answer with default metrics and any layout built from them is wrong.
  Measure with a stand-in label on an active object (same font, size, width), or lay out
  after the panel is shown.
- **`TextAlignmentOptions.Left` is vertically CENTRED.** Stacked multi-line blocks drift into
  each other when their heights are estimates. Use `TopLeft` for anything laid out by
  measured height.
- **UI gates that passed while the panel was broken.** The gate built each panel with its
  final data and the default font; the app builds panels EMPTY at boot and feeds data later
  through events, with the production font. Build a gate's fixture the way the app does -
  empty, then populate through the same events, with the real font asset - and it
  reproduces what the headset shows (it went from 0 to 20 failures).
- **Bullet lists in TMP:** `\u2022<indent=1.1em>text</indent>` wraps under the text, not
  under the bullet.
- **A fade band on a scroll view** must cover the `RectMask2D` padding too, or a thin strip of
  unfaded text shows at the edge.

## Operator and simulator

- **Pre-205 SDKs have no Operator.** Load the layer copy by environment variable (DevXr does
  it) and serve app tools through DevRemote. Don't upgrade the SDK just for the loop.
- **Hands-only apps ignore controller rays.** Converging the ray to 0.1° on a DicomSegVR
  button hovered nothing: its canvases take fingertip touch only. Press through the
  fingertip's own entry point and poke with a stand-in collider (setup.md, DicomSegVR tools).
- **Unity's MCP bridge (`unity-mcp` relay → `com.unity.ai.assistant`)** answered
  "Unity not detected" in one project and "Connection revoked" in another. Don't build
  on it.

- **App tools never registered in the editor** while Meta's `unity_*` tools answered.
  - Cause: the availability check only asked `OpenXRRuntime.IsExtensionEnabled("XR_METAX1_agentic_external_tool")`.
    The editor gets the layer through the OpenXR **API Layers** feature instead.
  - Fix: check both, as the template does, and retry registration for a minute.
- **Aiming the `aim` pose moves nothing.** The ISDK ray comes from the grip pose plus a
  fixed offset. Use `aimfix.py`.
- **`openxr_capture_composited_image`** answered "not instrumented" on simulator v205 and
  works on v207. Try it first; the app snapshot tool is the fallback.
- **A debug tool that reads `sharedMaterial` colours lies about per-object colour.** When
  colours are set through a `MaterialPropertyBlock`, every renderer reported the base
  material's base colour, including the red highlight. Read the property block first (the
  template does).
- **`openxr_set_head_pose` moves the controllers too**, and a non-unit quaternion floods
  the log with ISDK "Quaternion To Matrix conversion failed". See `operator.md`.
- **Turning the simulated head can move the panels.** An app that re-centres its workspace
  when it strays out of view does it for a scripted head turn too. Re-read panel positions
  after every head move (`scripts/panelshot.py` does), and don't place a panel relative to
  the head's CURRENT yaw at boot if the user may have turned - use the workspace's frame.
- **`unity_find_interactables` sees no custom widgets.** It enumerates uGUI `Selectable`
  only.
- **"The button works" gates that prove nothing:**
  - invoking a widget's handler directly bypasses the EventSystem, the pointable canvas
    module and the raycaster;
  - asserting that components exist isn't a click.

  Test through the ray too, and keep both results.
- **Emoji in tool descriptions** crash Python's print on a cp1252 console. `op.py`
  reconfigures stdout to UTF-8.

## Shell and Windows

- **Never wait on a guessed log marker.** A build agent ran
  `until grep -q "^exit=" build.log; do sleep 15; done` with a 10-minute timeout. The build
  had failed in 0.7 min, and `build_and_wait.ps1` prints `exit 1` (no `=`). The loop could
  never match, so the agent sat idle for the full timeout while the user watched nothing
  happen. Rules for any wait on a build, gate run, editor start or recorder:
  1. **Prefer the process to the log.** Run the blocking script itself in the foreground,
     since `build_and_wait.ps1` already blocks and returns Unity's exit code. Or start it
     with `run_in_background: true` and act on the completion notification. Don't poll a
     file for a line the script happens to print.
  2. **If you must poll, copy the marker from the script's source.** Grep the script for
     its final `Write-Output` or `echo` line first; don't type it from memory. Match every
     terminal outcome: success, failure, `NO APK`, timeout (`exit 124`) and the refusal
     lines (`refusing to build`).
  3. **Always add a liveness exit.** Break when the producing process is gone
     (`tasklist | grep -i Unity.exe`, or `kill -0 <pid>`) or the log stopped growing for
     N minutes. A dead producer means you are done waiting; read the log tail.
  4. **Keep sleep and timeout short.** Check every 10–20 s under a deadline you actually
     expect (a gates-only run is ~1 min, a dev APK is 3–6 min). Don't use a 600 s timeout
     on a loop that has no other exit.

- **PowerShell's `$args` is automatic.** A script that builds a variable named `$args`
  silently launches with the wrong arguments; name it `$launchArgs`.
- **JSON arguments through PowerShell or bash quoting** break constantly. Put the arguments
  in a file (`op.py call TOOL @file.json`) or a batch file.
- **Writing C# or HLSL through bash heredocs** mangled backslashes and left stray carriage
  returns. Write source files with the Write tool, or with a small Python script written by
  the Write tool.
- **Git Bash rewrites `/sdcard/...` arguments into Windows paths** before adb sees them
  (`adb push x /sdcard/...` lands in `C:/Program Files/Git/sdcard/...`). Call adb.exe from
  Python (`scripts/adbtools.py`) or PowerShell, or set `MSYS_NO_PATHCONV=1` for that command.
- **The same heredoc problem hits Python edit scripts:** a `\u2022` or `\n` inside a Python
  string in a bash heredoc arrived changed and wrote a wrong character into C#. Write the
  edit script to a file with the Write tool and run it.
- **Background recorders (logcat to a file) die with exit 255** when USB drops; the file just
  ends. `adb devices` before trusting it covers the session.
- **pt-BR locale:** `float.ToString()` gives `1,41`. That breaks JSON built by hand, parsed
  numbers, and UI labels. Set `CultureInfo.DefaultThreadCurrentCulture = InvariantCulture`
  at startup, and format numbers with InvariantCulture.

## Bugs the loop has caught (patterns worth grepping for)

- **`Progress<T>` overwrites the final state.** DicomSegVR's Viewer title stayed "Downloading…
  100%" after the volume loaded.
  - `Progress<T>.Report` posts to the sync context, so the last report runs after the await's
    continuation had already set the real title.
  - Fix: ignore progress once the result is bound (a loading flag or generation counter).
- **`GetComponent<T>() ?? AddComponent<T>()` on Unity objects.** In the editor `GetComponent`
  returns Unity's fake-null placeholder, which C#'s `??` treats as non-null. The next member
  access throws `MissingComponentException` (DicomSegVR `PointingRayVisual.EnsureLine`).
  - It is editor-only: builds return true null. But it breaks the feature in every simulator
    session.
  - Fix: `x = GetComponent<T>(); if (x == null) x = AddComponent<T>();`.
- **Porting geometry from another codebase by eye.** A web viewer's procedural screw (thread
  profile, apex, collar) was ported to C# against GOLDEN FIXTURES: run the original JS under
  Node for a spread of sizes, save vertex and triangle counts, the axial extent and every
  97th vertex in full as JSON (`tools/screw_golden.py`), and have an editor gate
  compare the C# mesh with them. A port that only looks right - another thread pitch, a
  missing collar - cannot pass it, and no one has to judge it by eye.
- **A GPU format that works in the editor and returns zeros on the Adreno** (a 3D R16 texture
  looked "not loading"): the app now reads known voxels back through a probe shader +
  `AsyncGPUReadback` and falls back to half floats on a mismatch (device.md, "Things only
  the device's GPU can answer").
- **The scripted perf scene pinned dynamic resolution**, so every device number came from the
  maximum resolution while the user saw the minimum (device.md).
- **The reversed-Z sky** (Rendering above) and **material-colour debug tools** (Operator
  section) were found the same way: query and measure, don't eyeball.

## Git

- **The editor rewrites assets during play:** TMP fallback font atlases, scenes, and
  `Assets/_Recovery`. Check `git status` and revert the unintended ones before committing.
  Git-ignore `/Assets/_Recovery/`.
