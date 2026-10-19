---
name: quest-build-deploy
description: Build a Unity Meta Quest app into an APK headlessly (release, development, or development without the XR Operator layer), refuse the build when a build gate fails, sideload it with adb, launch it, confirm it stays up with no crash in logcat, and turn a worn-headset session into a scripted readout (self-report lines, distinct problems, VrApi fps/GPU/stale summary). Use it when the user says build, build the apk, deploy, sideload, install or push to the Quest/headset, test on the device, or asks why a build or install failed - and when a change needs real hardware after the simulator loop.
---

# Build, sideload and verify on the Quest

Three stages: **build the APK → install with adb → launch and verify**. The one real branch is
how you build, because an open Unity editor holds the project lock.

`<skill>` below is this skill's folder (the base directory shown when the skill loads). The
scripts are Windows PowerShell 5.1 and Python 3.10+ (stdlib).

## 0. Pre-flight

1. **Compile first, without the lock** (the `unity-quest-sim-loop` skill's L0):
   `powershell -File <unity-quest-sim-loop>\scripts\quickcheck.ps1 -Project <project> -Editor -Dev`.
   `-Dev` compiles with the PLAYER's defines too, so dev-only code leaking into the release build
   fails in 10 seconds, not after a 20-minute build.
2. **Find the device:** `python <skill>/scripts/quest_deploy.py devices` (serial, model, OS
   build, worn or not). `unauthorized` = the USB debugging prompt is waiting INSIDE the headset;
   only the wearer can accept it. No device and the user only asked for a build: build anyway
   and say the install is pending.
3. **Is an editor open on this project?** The build script refuses (exit 3) with the pid if so.

## 1. Build

**The project needs a CLI entry point.** Copy `assets/QuestBuild.cs` into an Editor folder
(replace `__NS__` and `__MENU__`). It gives `Cli` (release), `CliDev` (development) and
`CliGates`, menu items for the same, and a gate hook: every static
`[QuestBuild.QuestBuildGate]` method returning `IEnumerable<string>` runs before every build,
and any message it yields refuses the build. The project may already have its own entry point;
pass it with `-Method`.

**Editor closed → headless (preferred):**
```powershell
powershell -File <skill>\scripts\unity_build.ps1 -Project <project>              # release
powershell -File <skill>\scripts\unity_build.ps1 -Project <project> -Dev         # development (agent tools + Operator)
powershell -File <skill>\scripts\unity_build.ps1 -Project <project> -GatesOnly   # gates, no APK (~1-2 min)
```
- Run it in the background and act on its exit; a clean build takes 5–30 minutes. Its last
  line is `exit <code>` and the process exits with that code. **Never poll its log for a
  marker you have not copied from the script**: one agent waited 10 minutes for `exit=` on a
  build that had failed in 40 seconds and printed `exit 1`.
- It prints the `[QuestBuild] result=...` line, every `[QuestBuildGates] FAIL ...`, any
  `error CS...` and the log tail. `NO APK` with exit 0 from Unity still exits 1.
- `-NoOperator` sets `QUEST_NO_OPERATOR=1` for `OperatorLayerExclusion.cs` (in
  `unity-quest-sim-loop/assets`): a development build WITHOUT the Meta XR Operator layer, for an
  OS build where the layer crashes the app at launch. The app's tools then answer over adb.
- A development build on an SDK that ships the Operator (Meta XR Core 205+) must say
  `Including XrApiLayer_METAX_operator` in its log; the script warns when it does not, because
  such an APK looks exactly like a device that will not connect.
- `-BuildTemp C:\unity-build-temp` when Gradle fails to start on Windows (Java NIO cannot
  create its AF_UNIX pipe under the default TEMP and never falls back to TCP).
- A stale `Temp/UnityLockfile` left by a killed editor makes batchmode exit **without writing a
  log**; the script removes it when no Unity process has the project open.

**Editor open → ask before closing it.** The user may be looking at it. If they want it kept
open, build from the editor's own menu (`__MENU__/Build/Build Quest APK`) - through the Unity
MCP's menu-item tool if that server works in this session, or by asking the user to click it -
then wait for the APK to exist with a stable size across two checks AND for
`[QuestBuild] result=` in `%LOCALAPPDATA%\Unity\Editor\Editor.log`. A Unity MCP "run command"
that calls `BuildPipeline.BuildPlayer` is rejected as interactive; use the menu item.

## 2. Install, launch, check

```bash
python <skill>/scripts/quest_deploy.py deploy <project>/Build/MyApp-dev.apk --project <project>
```
`deploy` runs `adb install -r -g` (replace, keep data, grant runtime permissions), clears
logcat, force-stops and launches through the LAUNCHER intent, waits ~12 s, then reports
whether the process is alive and every crash line (FATAL EXCEPTION, Fatal signal, SIGABRT,
ANR). The package id comes from `ProjectSettings` with `--project`, or `--pkg`.

- Direct adb installs a ~300 MB APK over USB in seconds; MCP installers have hung on large
  APKs. Use the Horizon OS MCP (`horizon-os-mcp` skill) for list / launch / inspect instead.
- `INSTALL_FAILED_UPDATE_INCOMPATIBLE` = the installed copy is signed with another key.
  Uninstalling deletes the app's data on the headset: **ask first**.
- Off a head, Horizon OS suspends an immersive app within seconds ("Finding position in
  room"). "Not running" on an unworn headset is not a crash; `quest_deploy.py worn` tells you.

## 3. Verify: a readout, not a screenshot session

Install and launch prove it boots. The behaviour needs either the agent driving the dev build
(the `unity-quest-sim-loop` skill: Operator over `adb forward tcp:8720 tcp:8720`, or
`run_scenario.py --device` over the adb channel) or a worn headset with a readout:

```bash
python <skill>/scripts/quest_deploy.py readout --project <project> --minutes 3 --relaunch \
       --questions <project>/tools/device_questions.json --out <tmp>/readout.txt
```
It waits until the headset is worn, grows and clears the log buffer, relaunches, streams
`Unity`, `VrApi`, `AgenticXR` and crash tags for the window (stop early by creating
`<out>.stop`), then prints:
- for each **question** (label + regex, `assets/device_questions.example.json`), the last line
  that answers it: render path, eye-buffer size, which data tier loaded, whether the agent tools
  registered...
- every distinct problem line with its count (30,000 identical exceptions read as one line);
- a **VrApi summary**: fps min/p50, App GPU ms p50/max, GPU utilisation, stale frames, CPU/GPU
  level and MHz, `SF` (the eye-buffer scale dynamic resolution chose), TW, layer count.

Make the app log one self-report line per question at startup and on key events. Then a device
session needs nobody to describe what they see, and the same file answers follow-up questions
later (`quest_deploy.py summary readout.txt`).

Tell the user exactly what to look at in the headset for the change you made, and report
install / launch / no-crash as verified and the visual outcome as theirs to confirm.

## 4. Before calling it shipped (L3)

- Build the **release** APK too (`unity_build.ps1` without `-Dev`): it has no Operator layer
  and no dev tools, so it is the build that ships, and a dev-only dependency breaks only here.
- Store requirements: ARM64 + IL2CPP, target API level, the manifest's Quest entries and VRC
  rules change - check them in the Meta docs (`horizon-os-mcp`: `vr_docs_search`) rather than
  from memory.
- Keep the last good dev APK (`Build/baseline-<date>-dev.apk`) for performance comparisons.
