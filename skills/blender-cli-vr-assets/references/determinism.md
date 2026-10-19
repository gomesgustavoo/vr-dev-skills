# Determinism: same inputs, same bytes

A shipped asset is pinned by sha256 (a manifest, `SHA256SUMS`, Git LFS). That only means something if re-running the
pipeline on unchanged inputs gives the same bytes - then a changed hash is a real change, a re-export is safe, and a
reviewer can diff two runs.

## Inputs vs non-inputs

Write the list down (the README of the pipeline) and make the code match it.

**Inputs** (they may change output bytes; record each one in the manifest):
* the stage scripts and the shared contract / look modules;
* the exact Blender build (`bpy.app.version`, `build_hash`) - FBX writer, UV packer, Cycles all change between
  versions; pin a portable build and refuse or warn on another;
* every source file (meshes, textures, fonts) - vendored or sha256-pinned; a missing or changed file is a hard error,
  never a fallback to "whatever font the host has";
* the Cycles device / backend (OptiX, CUDA, CPU...): sampling differs per backend - record it (measured below);
* `--quick` vs full quality.

**Not inputs** (must not change a byte; normalise them):
* the wall clock;
* the output folder and every other absolute path (`OUT`, the .blend location, the home directory);
* the host's fonts, locale, preferences and add-ons (`--factory-startup` removes the last two);
* Python's per-process hash seed - Blender runs its interpreter with `ignore_environment`, so `PYTHONHASHSEED`
  does nothing (verified on 5.2.2: two runs print two different `hash("abc")` with PYTHONHASHSEED=0);
* the order objects were created in an earlier session (sort by name wherever you iterate collections into output).

## The FBX patch points

Blender's `io_scene_fbx` takes four values from the environment. `scripts/fbx_deterministic.py` patches them for one
export and refuses to run if they moved:

| What | Where (io_scene_fbx) | Stock value | Pinned to |
|---|---|---|---|
| creation time | `export_fbx_bin.fbx_header_elements(root, scene_data, time=None)` | `datetime.now()` | 2000-01-01 00:00:00 |
| native file | the `Original\|ApplicationNativeFile` property it writes | `bpy.data.filepath` (absolute) | a constant like `pipeline:work/02_bake.blend` |
| texture paths | `export_fbx_bin._gen_vid_path(img, scene_data)` | `<OUT>\<image>` absolute + relative | the relative name, forward slashes |
| object UIDs | `fbx_utils._key_to_uuid(uuids, key)` | `hash(key)` (salted per process) | sha256 of `repr(key)`, then the original function |

```python
def key_to_uuid(uuids, key):
    if isinstance(key, int) and 0 <= key < 2 ** 63:
        return orig_uuid(uuids, key)                       # integer keys are used as-is by the stock code
    h = int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:8], "little") & (2 ** 63 - 1)
    return orig_uuid(uuids, h)                             # stock code still shortens + resolves collisions, same order

def header(root, scene_data, time=None):
    orig_header(root, scene_data, CREATION_TIME)           # constant time
    hits = [e for e in walk(root) if e.id == b"P" and e.props and e.props[0] in (RAW, pstr(RAW))]
    if len(hits) != 1:
        raise FbxInternalsChanged(...)                     # never guess
    hits[0].props[-1] = pstr(NATIVE_FILE.encode())         # strings are stored as <uint32 len> + bytes

E.fbx_header_elements, E._gen_vid_path, U._key_to_uuid = header, vid_path, key_to_uuid   # restored in finally
```

Also: clear `fbx_utils._keys_to_uuids` / `_uuids_to_keys` on entry and exit - the module caches UIDs across exports in
one process, so a second export would otherwise reuse UIDs from the first. And fail loudly when a patched function is
missing, has another signature, or did not run (`calls["header"] != 1`): a Blender upgrade that renames them must stop
the pipeline, not ship non-deterministic files. Finish with `assert_no_host_paths(fbx, [out_dir, blend_dir, home])` -
the proof that no absolute path leaked into the bytes.

Measured on the hello-room example (Blender 5.2.2): the same stage exported in two processes WITHOUT the patch gives
two different files (342 differing bytes); WITH it, identical files - also from a copy of the output folder on another
drive, and from a full rebuild whose `.blend` files had different hashes.

## Other byte sources

* **JSON**: `json.dump(..., sort_keys=True, indent=2)` + a final `\n`, opened with `newline="\n"` (CRLF on Windows
  otherwise). Keep timings out of hashed JSON - write them to the log or a `.timing` sidecar (the treatment-room
  clearance sweep does). Record relative paths, never host paths.
* **PNG**: Blender's PNG writer is deterministic for the same pixels; the pixels depend on the bake device (below).
  Copy shipped images byte for byte from the stage that made them; never re-save them on the way out.
* **`.blend` files are NOT byte-reproducible**: re-saving an unchanged file changes its hash (hello-room: re-save ->
  new sha256). That is fine - gates bind to "this exact file" (`validate.json: stage_sha256`), not to "a file this
  pipeline would make". The deterministic artefacts are the exports.
* **Floating point**: do geometry math in numpy float64 (mathutils is float32: ~0.1 mm at room scale); round numbers
  written to manifests (6 decimals); avoid summing in set / dict-iteration order of keys that may differ.
* **Bake device noise** (measured, hello-room `--quick` bake, Blender 5.2.2): two CPU bakes of the same stage are
  byte-identical; two OptiX bakes differ by 1/255 in ~0.001 % of texels (GPU scheduling); CPU vs OptiX differ in 0.2 %
  of texels by up to 3/255. So: bake on CPU when the atlas itself must be byte-reproducible (CI, a hash in a review),
  on the GPU when speed matters and "visually identical" is enough. Record `generator.bake = {backend, devices,
  samples, quick}` either way, and compare atlases only like with like.

## The validate binding

`validate.json` records `stage` + `stage_sha256` of the file it checked; preview writes `cameras.json` with the
stage hash it rendered from and fidelity copies it into `fidelity.json`; validate requires both to match; export
refuses unless `validate.json` passed (`fail == 0`, `pass > 0`) on exactly the file it is about to export, and refuses a
`--quick` stage unless explicitly allowed. So `--from export` after any edit (even a no-op re-save) stops with
"stale: re-run validate", and validate then demands fresh previews - the whole chain re-derives from the new file.
