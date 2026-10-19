# hello-room

A small, complete headless-Blender pipeline: a 4 x 4 x 2.8 m room and a jointed machine, built, baked into one
display-referred atlas, previewed, measured, validated and exported to a byte-deterministic FBX for Unity. Every
stage is its own Blender process. It uses the skill's `scripts/` unchanged.

```
export BLENDER=/path/to/blender          # Windows: set BLENDER=C:\path\to\blender.exe  (or PowerShell $env:BLENDER)
export PIPELINE_PY=/path/to/python       # a CPython with numpy + scikit-image + Pillow (scripts/requirements.txt)
python ../../scripts/run_stages.py --quick      # iteration build: 512 atlas, low samples
python ../../scripts/run_stages.py              # full quality: 1024 atlas, 256 samples
python ../../scripts/run_stages.py --from export --to export --quick   # re-export only
```

Output goes to `out/` (git-ignored; `--out DIR` or env `OUT` to move it). `CYCLES_DEVICE=CPU` forces the CPU.

| Stage | Script | Does |
|---|---|---|
| build | `01_build.py` | the contract hierarchy (`contract.py`), geometry, authoring materials, lights -> `work/01_build.blend` |
| bake | `02_bake.py` | one UV atlas for every mesh; Cycles bake of the full diffuse light + emission, display-referred, gloss in alpha -> `work/02_bake.blend`, `work/HelloRoom_atlas.png` |
| preview | `03_preview.py` | per shot: Cycles reference, unlit (atlas only), coverage mask; `cameras.json` in Unity coordinates |
| fidelity | `../../scripts/fidelity.py` | SSIM + CIEDE2000 unlit vs reference over the machine mask; gate SSIM >= 0.85, mean dE <= 6 |
| validate | `04_validate.py` | the contract gates; `validate.json` with the sha256 of the stage it checked |
| export | `05_export.py` | refuses unless validate passed on that exact file; FBX in Unity axes, read back and re-checked; atlas copy; `manifest.json` |

The machine: `Machine > Base`, `Machine > ArmPivot (joint, about X) > Arm`, `ArmPivot > HeadPivot (joint, about the
arm's axis) > Head + HeadTip`. Joints are empties and meshes hang under them, so re-modelling a mesh can never move a
joint; every node rests at identity rotation. `contract.py` is the single place that defines names, frames, budgets
and shots; `lookdev.py` the single place that defines materials, lights and the view transform.

Measured on Blender 5.2.2 (Windows, RTX 5070 OptiX unless noted):

| Run | Time | Machine SSIM / mean dE | Scene SSIM / mean dE |
|---|---|---|---|
| `--quick`, OptiX | 12 s | 0.905 / 3.87 | 0.931 / 1.97 |
| `--quick`, `CYCLES_DEVICE=CPU` | 26 s | 0.905 / 3.87 | 0.931 / 1.97 |
| full, OptiX | 22 s | 0.940 / 3.75 | 0.979 / 1.75 |

What the remaining gap is (look at `out/previews_compare/`): the glossy term of the authoring materials (not baked,
by design), the moving parts' shadows on each other and on the floor (baked without them, by design: they would be
wrong once the arm moves - Unity adds them dynamically if needed), and bake noise.

Checks you can repeat:
* `run_stages.py --from export --to export --quick` twice gives the same `HelloRoom.fbx` sha256, also with another
  `--out` (copy `out/` first) - and without `fbx_deterministic` two exports differ.
* Re-save `out/work/02_bake.blend` without changing anything: export refuses ("validate.json is for stage sha256 ...
  stale"), validate then fails on the previews bound to the old file, `--from preview` passes again.
* Export of a `--quick` stage without `--quick` on the runner refuses (no `--allow-quick`).
