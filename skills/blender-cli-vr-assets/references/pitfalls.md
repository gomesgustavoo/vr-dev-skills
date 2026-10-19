# Headless Blender pitfalls

Each one cost real time in a production pipeline (a radiotherapy treatment room for Quest, a 3D-print model
pipeline) or was reproduced while writing this skill on Blender 5.2.2. Symptom -> cause -> fix.

## Process and paths

* **A stage crashes and the pipeline carries on.** Without `--python-exit-code N`, an uncaught exception in a `-P`
  script exits Blender with **0** (verified). Always run `blender -b --factory-startup --python-exit-code 2 -P s.py --`.
  `sys.exit(1)` and `raise SystemExit("message")` exit 1 - use them for gate failures, so 1 = "a gate said no" and
  2 = "the script broke".
* **Output lands at `C:\`.** A relative `render.filepath` (or image path) in an unsaved file resolves against the
  DRIVE ROOT, not the working directory (verified: `render.filepath = "x.png"` -> `C:\x.png`, failed to write). `//`
  paths resolve against the open .blend's folder. Pass `Path(p).resolve()` strings to every bpy path API.
* **PYTHONPATH / PYTHONHASHSEED are ignored.** Blender runs Python with `ignore_environment` (verified:
  `sys.flags.ignore_environment == 1`; `hash("abc")` differs per run even with PYTHONHASHSEED=0). Put
  `sys.path.insert(0, <scripts dir>)` at the top of each stage; read your own settings from `os.environ` (that works).
* **Argument order matters.** Blender processes arguments left to right: the `.blend` to open and the flags go before
  `-P`, and everything after `--` belongs to the script (`sys.argv[sys.argv.index("--") + 1:]`).
* **Logs arrive late or interleaved.** Blender's stdout is block-buffered on a pipe: `print(..., flush=True)`.
  On Windows, a console code page that cannot print a character from the log can kill a Python runner that echoes it
  (`sys.stdout.reconfigure(errors="replace")`).
* **Waiting on a log line.** A runner (or an agent) that waits for "Saved" or "Finished" hangs when the message
  changes or the process dies first. Block on the process exit; for long runs start it in the background and wait for
  the completion notification; check that it is progressing (CPU, growing output), never poll a guessed marker.
* **Python references die after `open_mainfile`.** Opening a file replaces `bpy.data`; held objects raise
  `ReferenceError`. Re-fetch by name after every open.
* **Stage files pin host paths.** Image paths saved absolute point into the old output folder when it moves. Call
  `bpy.ops.file.make_paths_relative()` before `save_as_mainfile(..., relative_remap=True)` (stages after the first).
* **`.blend1` files pile up.** Overwriting a .blend keeps a backup (factory "Save Versions" = 1): set
  `bpy.context.preferences.filepaths.save_version = 0` before saving stage files.
* **Third-party add-ons or user prefs change results.** `--factory-startup` on every stage; enable the add-ons a stage
  needs in code.

## Scene and transforms

* **The rig has hidden rotations.** Interactive parenting writes `matrix_parent_inverse`; delta transforms
  (`delta_location`, `delta_rotation_euler`, `delta_scale`) hide in another panel. Parent in code with an identity
  parent-inverse and gate all of them.
* **`matrix_world` is stale** right after setting `location` / `rotation` / `parent`: call
  `bpy.context.view_layer.update()` before reading world matrices (or sum the local translations of an
  identity-rotation chain).
* **A joint silently renamed.** A name clash gives `Name.001`; Unity's `transform.Find("Name")` then returns null. Check
  `obj.name == wanted` right after creating it.
* **mathutils is float32.** `Vector` / `Matrix` lose ~0.1 mm at room scale; IK / FK, clearance and measurement go
  through numpy float64 (`foreach_get` into float64 arrays).
* **`bake_space_transform=True` ("Apply Transform") breaks child joints.** It converts mesh data and roots but leaves
  child joint offsets in Blender axes. Convert in the data in the export stage (unity-handoff.md).
* **Auto smooth is gone (4.1+).** Use `mesh.shade_smooth()` + `mesh.set_sharp_from_angle(angle=...)` or a
  `WEIGHTED_NORMAL` modifier (keep sharp, applied) and export with `mesh_smooth_type="OFF"` (normals only); import
  them in Unity (`importNormals = Import`).
* **`Material.use_nodes` is deprecated in 5.x** (DeprecationWarning, to be removed in 6.0; 5.x always uses nodes). Only
  set it on 4.x (`if bpy.app.version < (5, 0, 0)`).

## UVs

* **Islands stretched 4-16x along one axis.** `uv.smart_project(correct_aspect=True)` and
  `uv.pack_islands(rotate=True)` use a bogus image-editor aspect in background mode (there is no image editor). Use
  `correct_aspect=False`, `rotate=False`, and gate the stretch (area-weighted p95 of sigma_max / sigma_min <= 1.25).
* **`angle_limit=66` means 66 radians.** Operator angle properties are radians in Python:
  `angle_limit=math.radians(66)`.
* **Colour edges stair-step in the bake.** Welding separate primitives merges their UV charts, so a colour edge falls
  inside an island and aliases at bake resolution. Never weld across colour regions; keep each primitive its own island.
* **UV ops do nothing.** They need edit mode with an active object: set `view_layer.objects.active`, `mode_set("EDIT")`,
  select all (mesh and UV), then call them; multi-object edit mode packs every selected object into one atlas.

## Baking

* **Black blotches over other objects' islands.** A per-object (or per-set) `object.bake` treats the other objects'
  islands as empty and writes its margin over them. Bake with `margin=0` and `use_clear` only on the first call, then
  dilate the gutters in numpy.
* **A bake target bakes all zeros.** Its camera ray visibility is off (`visible_camera = False`). Keep camera
  visibility on every bake target; drop the other ray types if it must not shade anything.
* **Bake writes into the wrong image.** It writes into the ACTIVE image texture node of each material of each target:
  add the node to every material and set `node_tree.nodes.active`. Shared materials share the target image.
* **Excluding objects from a bake.** Use `hide_render` (render visibility); viewport-hidden objects cannot be selected
  as targets.
* **Moving parts' shadows frozen onto the floor.** The static bake ran with the moving parts visible; hide them and
  bake each moving part at rest with its "casters" only (baking-and-fidelity.md).
* **The bake and the preview disagree in tone.** A `--factory-startup` scene defaults to the AgX view; set Standard
  (look None, exposure 0, gamma 1) explicitly in every stage that renders or encodes, and `dither_intensity = 0`.
* **`COMBINED` bakes look shiny from one direction.** They include the glossy term from the bake's view. Bake
  `DIFFUSE` (direct + indirect + colour) + `EMIT`; leave reflections to the runtime.
* **The denoiser blurs emissive textures.** OIDN has no albedo guide on an emission closure. Do not denoise unlit /
  emissive renders; composite them from an undenoised pass by mask.
* **GPU bakes are not byte-reproducible.** OptiX bakes of the same stage differ by 1/255 in a few texels run to run;
  CPU bakes repeat byte for byte (measured on 5.2.2). Bake on CPU when the atlas hash must repeat.

## Images

* **Matte texels lose their colour (RGB / alpha).** Blender premultiplies float buffers; saving an RGBA float image
  divides RGB by alpha, and a gloss mask in alpha is 0 on matte texels. Write atlases from a BYTE image
  (`float_buffer=False`), `alpha_mode = "CHANNEL_PACKED"`; load them for shading with `CHANNEL_PACKED` too.
* **`save()` vs `save_render()`.** `image.save()` writes the buffer as stored; `image.save_render(path, scene=...)`
  applies the scene's colour management (view transform) - the tool for display-referred encoding.
* **Mask edges are gamma-encoded.** A coverage mask rendered with the Standard view stores sRGB-encoded partial
  coverage at edges; render masks with the `Raw` view.
* **Reading pixels back.** Load an 8-bit PNG with `colorspace_settings.name = "Non-Color"` to get the stored values;
  `pixels` rows are bottom-up (UV v = 0 is row 0).
* **`images.load(check_existing=True)` returns a stale datablock** after the file changed on disk: `reload()` it or
  load with `check_existing=False`.

## FBX

* **Different bytes every run.** Wall-clock time stamps, the absolute .blend path, absolute texture paths and UIDs
  from Python's salted `hash()` (determinism.md; `scripts/fbx_deterministic.py`).
* **UIDs leak between exports in one process.** `fbx_utils` caches key -> UID across exports; clear its caches around
  each export.
* **Lights and cameras in the FBX.** `object_types={"EMPTY", "MESH"}` and delete everything outside the export root
  before exporting.
