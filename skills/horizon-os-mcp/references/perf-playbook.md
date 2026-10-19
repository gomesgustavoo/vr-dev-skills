# Quest performance playbook (Horizon OS MCP + VrApi)

The order matters more than the tools: make the run repeatable, capture a baseline, change one
thing, capture again, compare with the same numbers.

## 0. Know the budget

| refresh | frame budget | what "fits" means |
|---|---|---|
| 72 Hz | 13.9 ms | App GPU time + compositor under 13.9 ms with headroom (aim ≤ 11 ms App GPU) |
| 90 Hz | 11.1 ms | |
| 120 Hz | 8.3 ms | |

Quest GPUs are tile-based (Adreno). Fill rate and bandwidth dominate: full-screen passes,
overdraw, MSAA resolves, raymarching and post-processing cost far more than triangles. On a
fill-bound app the lever is pixels (eye-buffer scale, foveation, shader cost), not draw calls.

## 1. Make the run repeatable

- A dev-only app tool that places the content at a fixed pose relative to the head and sets the
  feature switches under test (e.g. `myapp_perf_scene {preset}`), plus a marker line in logcat
  at the start and end of each scripted window (`[myapp-perf] BEGIN scenario=<name> ` ...
  `RESULT`). `run_scenario.py --device` cuts VrApi at those markers.
- Pin or disable dynamic resolution. OVRManager's dynamic resolution rewrites
  `XRSettings.renderViewportScale` every frame, so a "pinned" scale does nothing unless DR is
  off, and a scripted scene that pins it at the maximum measures the best case, not what the
  user sees under load.
- Same device model (Quest 3 vs 3S differ), same OS build, headset worn, thermals settled for a
  minute, nothing else immersive running (VrApi lines from a second pid mean the shell shared
  the GPU).

## 2. Capture

```text
perf_trace_capture {app: "com.Company.App", duration_ms: 10000, mode: "standard"}
```
Modes: `standard` (CPU scheduling + GPU counters + XR runtime), `gpu` (deep GPU), `cpu`
(extended scheduling, no GPU overhead), `memory`, `lightweight` (markers only). Use
`perf_trace_capture_start` / `perf_trace_capture_stop {pid, output_name}` around one
interaction. Keep the session id it returns; `perf_trace_list` finds old ones.

## 3. Analyse

1. `perf_trace_analyze {focus: "overview", target_app: "com.Company.App"}` - CPU- or GPU-bound,
   frame timing distribution, stale frames, top slices.
2. GPU detail: frame ranges first, then counters:
   ```sql
   SELECT ts, dur FROM slice WHERE name LIKE 'GPU%' ORDER BY ts LIMIT 40
   ```
   then `perf_trace_gpu_counters {start_ts: [...], end_ts: [...]}` (20+ pairs).
3. CPU detail: `SELECT utid, name FROM thread` then `perf_trace_thread_state {utid}` for the
   render thread / main thread: runnable-but-not-running time is contention, not work.
4. Anything specific: `perf_trace_query_sql {query}` against the loaded trace.
5. `perf_trace_get_context` explains which analyses the captured data supports.

## 4. Compare

`perf_trace_compare {baseline_id, comparison_id}` gives frame-timing deltas, the top expensive
slices of both and thread utilisation. Report the same metric for both, e.g. "App GPU p50
11.2 → 8.9 ms, stale frames 41 → 3 over 10 s".

## 5. Cross-check with VrApi

`device_logcat {tag: "VrApi", lines: 400}` (or `adb logcat -s VrApi`), one line per second:

| field | meaning |
|---|---|
| `FPS=72/72` | frames shown / target |
| `App=9.1ms` | app GPU time |
| `GPU%=0.93` | GPU utilisation (≥ 0.9 = GPU-bound) |
| `CPU4/GPU=3/3,1651/640MHz` | CPU / GPU level and clocks |
| `SF=0.80` | the eye-buffer scale dynamic resolution chose this second |
| `Stale=4` | frames the compositor re-showed (the user feels these) |
| `TW=0.56ms` | compositor (TimeWarp) time |
| `LCnt=3` | compositor layers (passthrough + panels + eye buffer) |

Cut logcat into windows with the headset's own clock (`adb shell date +%H:%M:%S`) or with the
app's marker lines, and summarise each window (p50 / max) instead of quoting one line.
`unity-quest-sim-loop/scripts/adbtools.py` has `vrapi_summary()` for exactly that.

Lessons from production:
- **Levels are not clocks.** Under GPU saturation the firmware raised the GPU clock to the same
  MHz at different level numbers, so a higher "GPU level" bought nothing measurable. Measure
  MHz and App time, not the level you asked for.
- **Passthrough caps clocks at runtime.** The cap was re-evaluated live when passthrough was
  turned off (the FEATURE, not just the layer), and came back when it was turned on.
- **Find per-pass costs with runtime switches,** not rebuilds: a dev tool that flips one render
  feature and logs a marker measured six levers in ten minutes (an always-on clip-distance write
  cost ~40% of the frame on Adreno multiview; discard was cheap).
- **Allocation per frame** is a perf bug too: calling `OVRInput.Update()` again from app code
  allocated ~4 KB a frame (OVRManager already calls it).

## 6. Memory

`perf_memory_snapshot {app, label: "baseline"}` before, `"incident"` at the problem, `"final"`
after: /proc, dumpsys meminfo, dmabuf, PSI and swap side by side. Textures and render targets
show up under dmabuf / graphics, not the managed heap.
