---
name: blender-cli-vr-assets
description: Build VR-ready 3D assets with headless Blender driven from the command line (blender -b, bpy stage scripts) and hand them to Unity for Meta Quest - rooms, props and jointed machines built by scripted stages, Cycles light baked display-referred into atlases drawn unlit, gated by validation, exported as byte-deterministic FBX with the axis conversion and joint contract Unity needs, and checked against Cycles reference renders with SSIM and CIEDE2000. Use it whenever the user runs or writes Blender in background / CLI mode or bpy scripts; generates or fixes 3D assets, rooms or props for Unity or Quest; exports FBX for Unity (wrong axes, scale, joints in the wrong place); bakes lighting or AO into atlases; wants Unity to match a Blender render; or wants a scripted, deterministic asset pipeline. Includes a stage runner, bpy helpers, a deterministic-FBX patch, a fidelity gate and an example.
---

# Headless Blender -> VR assets for Quest

An agent cannot click through Blender, and a Quest cannot afford real-time lighting of a detailed room. Both problems
have the same answer: **a pipeline of headless Blender stages** that builds the asset from code, bakes the full Cycles
light into atlases that Unity draws unlit, proves the result with gates and numbers, and exports bytes that only change
when the asset changes.

The method was proven on a radiotherapy treatment room for a Quest app (a TrueBeam-class linear accelerator in a
6.2 m vault: a jointed gantry, imaging arms and a couch), built entirely by headless stages: 61 validate checks,
73,744 machine triangles at LOD0, 4096^2 atlases at ASTC 4x4, a deterministic FBX, and Unity frames matching the
Cycles previews at machine-region mean SSIM 0.898 and mean CIEDE2000 3.72 (all 6 shots inside the >= 0.85 / <= 6
target).

## When to use / not

Use for: generating rooms, props, jointed machines or environments from scripts; fixing an FBX that lands rotated,
scaled or with joints in the wrong place; baking light / AO into atlases; making Unity match a Blender render;
making an asset pipeline reproducible and reviewable; any `blender -b ... -P script.py` work.
Not for: interactive sculpting / artist workflows (no gates to automate), skinned characters and animation clips
(the joint contract here is rigid-body joints driven by code), or Unity-side runtime work after import (see the
Quest simulator / build skills).

## What is in here

| Path | What |
|---|---|
| `scripts/run_stages.py` | CPython runner: `pipeline.json` -> one Blender process per stage, `--from/--to/--only/--quick`, stops at the first non-zero exit |
| `scripts/bpy_stage.py` | imported by stage scripts: args after `--`, absolute OUT, `open_stage` / `save_stage`, `sha256`, `check_version`, `write_json` |
| `scripts/fbx_deterministic.py` | `deterministic_fbx()` patch, `UNITY_EXPORT_KW`, `read_fbx()` read-back, `assert_no_host_paths()` |
| `scripts/fidelity.py` (+ `requirements.txt`) | CPython SSIM + CIEDE2000 gate over masks, JSON + montages |
| `examples/hello-room/` | a runnable 6-stage pipeline using all of the above (~12 s with `--quick` on a GPU, ~26 s on CPU) |
| `references/unity-handoff.md` | axes, the rotation-sign rule, units, joint contract template, Unity import checklist |
| `references/baking-and-fidelity.md` | view transform, display-referred bake, bake sets, gloss, env map, contact shadows, metrics, expected gaps |
| `references/determinism.md` | inputs vs non-inputs, the FBX patch points, bake device noise, the validate binding |
| `references/pitfalls.md` | every headless trap hit so far, symptom -> cause -> fix |

Start a new pipeline by copying `examples/hello-room/` and replacing `contract.py`, `lookdev.py` and the geometry;
copy `scripts/bpy_stage.py` and `scripts/fbx_deterministic.py` beside the stages (or fix their `sys.path` line, which
expects the skill's `scripts/` two folders up).

```
export BLENDER=/path/to/blender            # Windows PowerShell: $env:BLENDER = "C:\path\to\blender.exe"
export PIPELINE_PY=/path/to/venv/python    # CPython with numpy, scikit-image, Pillow (only for fidelity.py)
python scripts/run_stages.py examples/hello-room/pipeline.json --quick
```

## 1. Pin a portable Blender

* Use a portable (zip / tar) Blender build, point env `BLENDER` at it, and record `bpy.app.version` and `build_hash` in
  every manifest - the FBX writer, the UV packer and Cycles change between versions, so the build is an input.
* Declare the floor and the pin in `pipeline.json` (`"blender": {"min_version": "4.2", "pin": "5.2.2", "policy":
  "warn"}`); the runner checks `blender --version` before any stage and passes the rule to `bpy_stage.check_version()`
  as env `BLENDER_MIN_VERSION` / `BLENDER_PIN` / `BLENDER_VERSION_POLICY` (set them when running a stage by hand).
  Use `"refuse"` for release builds.
* Never rely on the user's Blender preferences or add-ons: `--factory-startup` on every stage.

## 2. One process per stage

```
blender -b --factory-startup --python-exit-code 2 -P 02_bake.py -- --out /abs/out [--quick]
```

* **One stage = one process = one job**, handing over through a `.blend` in `<OUT>/work/` (`open_stage("01_build")`
  ... `save_stage("02_bake")`): a crash cannot leave half-modified state for the next step, a stage can be re-run
  alone, and memory never accumulates across a long pipeline.
* **`--python-exit-code 2`**: without it an uncaught exception exits 0 and the next stage runs on garbage. Gate
  failures `raise SystemExit(1)`; so 1 = "a gate refused", 2 = "the script broke".
* **The runner stops at the first non-zero exit and exits with that code** (`run_stages.py` prints
  `=== bake: exit 0 in 5.6 s`). The exit code IS the result: block on the process, never on a log line.
* **Long runs**: start the runner in the background and wait for its completion notification; check it is progressing
  (log growing, CPU busy) rather than polling for a guessed message.
* **Absolute paths only** (`bpy_stage.resolve`): a relative output path in an unsaved file lands at the drive root.
* **`--quick`** (small atlases, low samples) for iteration; the export refuses a quick stage unless `--allow-quick`, so
  an iteration build cannot ship by accident.
* CPython stages (`"python": true`) run tools that need packages Blender lacks (fidelity.py: scikit-image).
* Stages never modify the previous stage file and read-only stages (preview, validate, export) never save it.

## 3. The contract first

Write `contract.py` before any geometry; every stage imports it and nothing else defines these numbers.

* **Frames and units**: the authoring frame (Blender, right-handed, Z up, metres; pick axes that make the domain easy),
  the Unity frame (left-handed, Y up), and the ONE mapping, e.g. `unity (x, y, z) = (X, Z, Y)`, det -1. The
  conversion happens in the export stage only, so bake, preview, validate and clearance all work in one frame.
* **Rotation rule**: Blender right-handed `+t` about `a` == Unity `Quaternion.AngleAxis(-t, M a)`. Write it next to
  every joint in the manifest and gate it numerically.
* **Joint hierarchy by NAME**: joints are empties, meshes hang under joints (never joints under meshes, or re-modelling
  a mesh moves a joint), markers for the points the runtime needs. Unity finds them by exact name, so a `.001` suffix
  is a build failure.
* **Identity rest**: every node rests at identity rotation, unit scale, identity parent-inverse and zero delta
  transforms, with a pure-translation offset - "rest" then means the same thing in Blender, the FBX and Unity, and the
  runtime animates with one `localRotation` assignment.
* **Budgets, atlas sizes, shots, file names** live here too. Template: `references/unity-handoff.md`.

## 4. Build stage rules

* Build geometry in WORLD coordinates (bmesh), then shift the mesh data so its origin sits on its contract node, and
  parent with an identity parent-inverse (`o.location = world - parent_world`): positions are readable in the source
  and exact in the file.
* Keep colour regions as separate primitives and **never weld them**: each stays its own UV island, so a colour edge
  is an island edge and stays crisp in the bake.
* A room seen from inside faces INWARD (Unity culls back faces); closed parts face outward (gate the signed volume).
* Put materials, lights and the view transform in one `lookdev.py` that build, bake and preview share, so the bake sees
  exactly what the reference renders.
* Vendor and sha256-pin every input file (textures, fonts, source meshes); a missing file is an error, never a fallback.

## 5. Bake for Quest

Atlas RGB = `encode(view)(albedo x (direct + indirect diffuse) + emission)`, 8-bit sRGB; A = gloss. Drawn with an
unlit shader in a linear project it reproduces the reference pixel at no lighting cost. Details in
`references/baking-and-fidelity.md`; the rules:

* **View**: Standard, look None, exposure 0, gamma 1 in every stage that renders or encodes - the factory default is
  AgX, so an unset stage bakes one tone curve and previews another. Encode with Blender's own transform
  (`image.save_render`), not a hand-written curve.
* **Bake** `DIFFUSE {DIRECT, INDIRECT, COLOR}` + `EMIT`, not `COMBINED` (its glossy term is seen from the wrong
  direction). Glossy goes to a cheap runtime reflection scaled by the gloss alpha.
* **Bake sets**: the static scene with every moving part hidden (no shadow of a moving arm frozen onto the floor); each
  moving part at rest with only the parts that never move relative to it. Record these casters.
* **Margins**: per-set bakes use `margin=0` (a bake's margin overwrites other islands it thinks are empty), then dilate
  the gutters in numpy and fill unused texels with the mean colour.
* **UVs**: one named UV map per mesh, all islands of an atlas packed together, no overlaps, `correct_aspect=False` and
  `rotate=False` headless (otherwise islands stretch 4-16x), texel-density weights for what users look at.
* **Straight alpha**: write atlases from BYTE images with `alpha_mode = "CHANNEL_PACKED"`; a float image is
  premultiplied and saving it wipes the colour of every matte (alpha 0) texel.
* **Device**: OptiX -> CUDA -> HIP / Metal / oneAPI -> CPU, recorded. CPU bakes repeat byte for byte; GPU bakes differ
  by 1/255 in a few texels run to run.
* Moving parts' shadows on the room: contact-shadow quads (an irradiance ratio, multiply-blended) or runtime blobs.

## 6. Previews are the reference; fidelity is a gate

Per shot, from the final stage file (never saved): `previews/` = the Cycles REFERENCE (authoring materials, the look
definition, denoised except emission closures), `previews_unlit/` = every surface the emission of its atlas (what the
Quest draws), `previews_mask/` = flat group colours rendered with the Raw view (R room, G static, B moving; overlays
black), and `cameras.json` = every shot in UNITY coordinates (position, target, up, vertical FOV, aspect, resolution,
near clip, pose) plus the stage sha256, so Unity can render the same frames.

```
python scripts/fidelity.py --ref out/previews --test out/previews_unlit --mask out/previews_mask \
    --cameras out/cameras.json --regions machine=gb,scene=rgb --gate machine --min-ssim 0.85 --max-de 6 \
    --json out/fidelity.json --montage out/previews_compare
```

SSIM (Gaussian sigma 1.5, data range 255) catches noise, blur and misalignment; mean CIEDE2000 catches colour,
exposure and view-transform errors. Gate the region the bake is responsible for, report the rest, and name the
expected gaps (glossy coat, moving-part shadows, poses away from rest, noise, edge AA) instead of chasing them. Run the
same script on Unity captures (`--resize-test` if sizes differ): one metric for both hops.

## 7. Validate, and bind the result to the file

`04_validate.py` fails loudly (exit 1) and writes `validate.json` with the sha256 of the exact stage it checked. Gate
at least: contract names / parents / kinds and nothing extra; identity rest everywhere and det > 0; every node at its
contract position; each joint turning about its contract axis through its pivot (and the Unity sign rule reproducing
it); outward / inward normals; tris and atlas budgets; one UV map, inside [0, 1], no overlaps, stretch p95; the atlas
format (8-bit RGBA, size, straight alpha, gloss values); `cameras.json`, the previews and a PASSING `fidelity.json`
all bound to this stage's sha256. Domain checks (a part on the correct side, a clearance, a floor height) are worth more
than generic ones - they catch the sign error a self-consistent pipeline reproduces.

The export **refuses** unless `validate.json` passed (`fail == 0`, `pass > 0`) on exactly the file it is about to
export:

```
[05_export] FAILED: REFUSED:
  validate.json is for stage sha256 ebe8ce8d5384, the file being exported is c3fe5f9336cd (stale: re-run validate)
```

(that was a no-op re-save of the stage: `.blend` files are not byte-reproducible, so any touch re-derives the chain).

## 8. Deterministic export, then read it back

* Convert axes in memory: every joint offset and vertex to FBX = `(-X, Z, Y)` (det +1), the root set to the inverse of
  the exporter's axis matrix, `axis_forward="-Z", axis_up="Y"`, **`bake_space_transform=False`** - "Apply Transform"
  converts meshes and roots but leaves child joint offsets in Blender axes. Units: `apply_scale_options="FBX_SCALE_ALL"`
  -> metres with UnitScaleFactor 100 -> Unity `useFileScale` = 1 unit per metre. All in `F.UNITY_EXPORT_KW`.
* Wrap the export in `fbx_deterministic.deterministic_fbx()`: it pins the creation time, `ApplicationNativeFile`, the
  texture paths and the UIDs (Python's salted `hash()`; Blender ignores PYTHONHASHSEED), and raises if io_scene_fbx
  changed instead of silently writing non-deterministic files. Then `assert_no_host_paths()`.
* Copy atlases byte for byte from the stage that made them; write `manifest.json` with joints in Unity coordinates
  (local + world rest position, axis, range, sign rule), tris, texture import settings, the validate block, the
  fidelity summary, the bake device and the sha256 of every file.
* **Parse the FBX back** (`read_fbx`) and re-check in Unity coordinates: axis system Y-up, UnitScaleFactor 100, no
  rotation / scale / pre / post / geometric transforms, exact names, every node at `M . contract position`, a few
  domain facts. Exit 1 on any miss.
* Prove it: `run_stages.py --from export --to export` twice -> same sha256, also into another `--out`. In the example,
  unpatched exports of the same stage differ in 342 bytes; patched ones are identical across runs, folders and drives.

Details and the code: `references/determinism.md`, `references/unity-handoff.md`.

## 9. Quest budgets

Set budgets from measured GPU time on the device, then gate them. Reference point from the treatment room (Quest 3S,
72 Hz = 13.9 ms frame): an earlier build drew 1.5 - 3.6 ms App GPU, so the detail pass spent that headroom on geometry
and texels - machine 73,744 tris (LOD0 only) + room 5,430, five 4096^2 atlases at ASTC 4x4.

| Item | Rule | Why |
|---|---|---|
| Triangles | gate a per-group budget (`TRIS_MAX`), LOD0 counts | the budget is GPU ms; tris are the knob you control |
| Atlases | <= 4096^2, power of two, <= 2 per group | memory, import max size, mip chain; more texels rarely show at VR pixel density |
| ASTC 4x4 | 8 bpp: a 4096^2 atlas = 16 MiB, ~21 MiB with mips | hero surfaces: text, sharp colour edges, the machine |
| ASTC 6x6 | 3.56 bpp: ~7 MiB, ~9.5 MiB with mips | large smooth walls / floors |
| RGBA8 | 32 bpp: 64 MiB, ~85 MiB with mips | never ship uncompressed atlases |
| Anisotropy | 8x on floors, walls, long surfaces | grazing angles blur in a room without it |
| Materials | one per atlas group | each extra material is another draw call per mesh |
| LOD | only when measured to help | decimate AFTER the unwrap so LODs share the atlas; LOD siblings add mesh memory and pop; the room dropped them once GPU headroom was measured |

## 10. Optional: mesh-accurate clearance sweep for moving parts

When parts move (gantries, arms, doors, couches), still renders cannot show collisions. Pose the rig exactly like the
runtime kinematics (same signs and interpolation as the Unity code), and measure every moving pair on the triangles:

```python
from mathutils.bvhtree import BVHTree
bvh_b = BVHTree.FromPolygons(verts_b_local, tris_b)            # once per part, in its local frame
M_ab = np.linalg.inv(world(B)) @ world(A)                        # float64, per pose
for q in samples_a @ M_ab[:3, :3].T + M_ab[:3, 3]:               # A's vertices + edge samples every ~4 mm
    loc, nrm, idx, dist = bvh_b.find_nearest(Vector(q), cut)     # min distance (both ways)
hit = bool(bvh_a.overlap(BVHTree.FromPolygons(verts_b_in_a, tris_b)))   # surfaces intersect
# containment: ray parity against B's closed components; depth = deepest sample inside
```

Skip pairs whose transformed boxes are farther apart than the cut; classify each contact (A = modelling error, B = a
limit the real device has too, U = a runtime pose / kinematics number) and gate "no A in the working poses". Keep the
JSON deterministic (timings to a sidecar) and bind it to the stage sha256 like the previews. The treatment-room sweep
found an imaging panel whose deploy path crossed the machine's own shell 149 mm deep - invisible in every still.

## 11. The Unity side

* Model import (from an `AssetPostprocessor` or the scene builder, never by hand): `globalScale` 1, `useFileScale`
  on, `bakeAxisConversion` off, normals Import, tangents None for unlit, `materialImportMode` None (assign the unlit
  atlas material in code), no cameras / lights / animation, Read/Write off (copy triangles at edit time if CPU code
  needs them), `preserveHierarchy` on.
* Atlas import: sRGB on, alpha from input, **Alpha Is Transparency off** (it rewrites the RGB of alpha-0 texels -
  every matte texel), mipmaps on, aniso 8 on large surfaces, clamp, max size = the atlas size, Android ASTC 4x4 / 6x6.
* Draw unlit with no tone mapping on the camera; add the gloss-scaled reflection and dynamic shadows only where the
  bake leaves them out.
* Gate the import in Unity against `manifest.json` (names, local positions, identity rotations, tris), render the
  `cameras.json` shots and run `fidelity.py` on them.
Full checklist: `references/unity-handoff.md`.

## 12. Report what was verified, and how

End every pipeline run with a short report that separates the three kinds of evidence:
* **By gates (exit codes)**: `validate.json` n / n pass on stage sha256 `...`; FBX read-back OK in Unity coordinates;
  fidelity per shot (gate region SSIM / mean dE vs target); determinism (two export sha256s equal); the bake device.
* **By eye**: which montages / previews you looked at and what the remaining gap is (name it from the expected-gap
  list).
* **Not verified**: Unity import (unless a Unity gate ran), the headset look, device GPU time, poses away from rest,
  anything run only with `--quick`.
Never present an iteration (`--quick`) build or a GPU-baked atlas hash as the reproducible release artefact.

## Pitfalls at a glance

Full list with fixes: `references/pitfalls.md`. The ones that bite first:
1. No `--python-exit-code` -> crashes exit 0.  2. Relative output paths -> written to the drive root.
3. AgX default view -> bake and preview disagree.  4. `correct_aspect` / `rotate` headless -> stretched islands.
5. Per-object bake margins overwrite other islands -> margin 0 + dilate.  6. Float RGBA atlas -> premultiplied colour.
7. `bake_space_transform` -> child joints in the wrong place.  8. `hash()`-based FBX UIDs -> new bytes every run.
9. Camera-invisible bake target -> all zeros.  10. mathutils float32 -> do measurements in numpy float64.
