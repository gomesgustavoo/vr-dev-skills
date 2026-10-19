# Quest dev loop (paste into your Unity project's CLAUDE.md and fill in the <...>)

## Workflow: four loops, cheapest first

**Assert through tools, not screenshots.** A picture of a VR scene cannot tell "the button did
nothing" from "the ray was not on it". Read the app's state, inject the input, read the state
again.

| loop | command | cost | proves |
|---|---|---|---|
| **L0** | `quickcheck.ps1 -Project . -Editor -Dev`, then `unity_build.ps1 -Project . -GatesOnly` (editor closed) | 10 s / 90 s | it compiles with editor AND player defines; every build gate passes |
| **L1** | `editor-play.ps1 -Project .`, then `run_scenario.py tools/sim-scenarios/*.json --prefix <prefix>` | seconds per check | the app runs in the Meta XR Simulator and simulated input changes state as intended |
| **L2** | `unity_build.ps1 -Project . -Dev`, `quest_deploy.py deploy Build/<App>-dev.apk --project .` | ~4 min + a worn headset | real tracking, hands, Adreno GPU, performance |
| **L3** | `unity_build.ps1 -Project .` + the smoke checklist in `docs/SMOKE.md` | ~4 min | the release APK (no Operator layer, no dev tools) |

Skills: `vr-dev:unity-quest-sim-loop` (L0-L2), `vr-dev:quest-build-deploy` (builds,
sideload, device readout), `vr-dev:horizon-os-mcp` (Meta docs, device, Perfetto),
`vr-dev:blender-cli-vr-assets` (generated 3D assets).

## Project facts the agent needs

- Unity `<version>`, Meta XR SDK `<203 | 205 | ...>`, `<URP version>`, OpenXR `<version>`.
- Scene: `<Assets/Scenes/Main.unity>`. Assemblies: `<Assembly-CSharp | MyApp.Runtime + MyApp.Editor>`.
- Android package: `<com.Company.App>`. Agent tool prefix: `<prefix>`.
- Build entry point: `<Ns>.EditorTools.QuestBuild.Cli / CliDev / CliGates`.
- Scenario suites: `tools/sim-scenarios/`. Device readout questions: `tools/device_questions.json`.

## Rules

- **Never save C# during Play Mode** (a mid-play domain reload kills the Interaction SDK); use
  `reload.py` (stop → refresh → compile → play).
- **Verify Meta SDK names in the docs** (`vr_docs_search`, `vr_api_search`) before relying on
  memory: they change between SDK versions.
- **A finding is done when a gate would catch it again:** write the gate, watch it fail once with
  the bug restored, write the failure message as the bug looks in the headset.
- Headless Unity runs take the project lock: close the editor first, and say so if the user may
  be looking at it.
- Say where each claim was verified (simulator, device, gate) and what was not. Simulator-only
  rendering and performance results stay "unverified on the headset".
