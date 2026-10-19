"""fbx_deterministic - byte-identical FBX files from Blender's io_scene_fbx, and a read-back parser to check them.

    import fbx_deterministic as F

    with F.deterministic_fbx(native_file="my-pipeline:work/04_final.blend"):
        bpy.ops.export_scene.fbx(filepath=fbx_path, **F.UNITY_EXPORT_KW)
    F.assert_no_host_paths(fbx_path, [out_dir])      # the patches really took
    fbx = F.read_fbx(fbx_path)                         # GlobalSettings, models, parents, Lcl transforms, vertices

Why: the stock writer takes four things from the environment, so the same .blend gives different bytes on every run
and every host, and a sha256 in a manifest or an LFS diff means nothing:
  * the creation time stamps (FBXHeaderExtension/CreationTimeStamp and the root CreationTime) - the wall clock;
  * Original|ApplicationNativeFile - the absolute path of the .blend being exported (a host path, too);
  * the texture Video Path / Filename - the absolute path of each image under the output folder;
  * object UIDs - fbx_utils._key_to_uuid() uses Python's hash(), which is salted per process. Blender runs its Python
    with ignore_environment, so PYTHONHASHSEED cannot fix it; the UID function has to be replaced.
deterministic_fbx() replaces those, for the duration of the export only, with a constant time, a constant native-file
string, the image paths as given relative (forward slashes), and a sha256-based UID that still goes through the
original function (which shortens it and resolves collisions in the same call order). It also clears the module's UID
caches, which otherwise keep UIDs from an earlier export in the same process.

It fails LOUDLY (FbxInternalsChanged) when the patched functions are missing, have another signature, or did not run:
a Blender update that renames them must stop the pipeline, not silently ship non-deterministic files. Verified on
Blender 5.2.2 (io_scene_fbx 5.15.0); on another version the guards either pass or say exactly what moved.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import inspect
import struct

CREATION_TIME = datetime.datetime(2000, 1, 1, 0, 0, 0)

# Settings for an FBX meant for Unity (see references/unity-handoff.md): Y-up "Maya" axis system written as data (no
# importer-side correction), metres with UnitScaleFactor 100 (Unity's useFileScale gives 1 unit per metre), no
# bake_space_transform (it converts meshes and roots but leaves child joint offsets in Blender axes), loop normals
# only, triangles, no animation, no leaf bones, no embedded media, image paths stripped to file names.
UNITY_EXPORT_KW = dict(
    check_existing=False, use_selection=False, use_visible=False, object_types={"EMPTY", "MESH"},
    use_mesh_modifiers=True, mesh_smooth_type="OFF", use_triangles=True, use_custom_props=False,
    add_leaf_bones=False, bake_anim=False, use_tspace=False,
    apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL", global_scale=1.0,
    axis_forward="-Z", axis_up="Y", bake_space_transform=False,
    path_mode="STRIP", embed_textures=False, colors_type="NONE",
)


class FbxInternalsChanged(RuntimeError):
    """io_scene_fbx no longer looks like the version these patches were written against."""


def _require(mod, name: str, params: tuple):
    fn = getattr(mod, name, None)
    if fn is None or not callable(fn):
        raise FbxInternalsChanged(f"{mod.__name__}.{name} is missing - update fbx_deterministic.py for this Blender")
    got = tuple(inspect.signature(fn).parameters)
    if got != params:
        raise FbxInternalsChanged(f"{mod.__name__}.{name}{got} no longer has the signature {params} - update "
                                  f"fbx_deterministic.py for this Blender")
    return fn


def _walk(e):
    yield e
    for c in e.elems:
        yield from _walk(c)


def _pstr(b: bytes) -> bytes:
    # encode_bin.FBXElem.add_string stores strings as <uint32 length> + bytes
    return struct.pack("<I", len(b)) + b


def _replace_native_file(root, value: str) -> None:
    raw = b"Original|ApplicationNativeFile"
    hits = [e for e in _walk(root) if e.id == b"P" and e.props and e.props[0] in (raw, _pstr(raw))]
    if len(hits) != 1:
        raise FbxInternalsChanged(f"expected one Original|ApplicationNativeFile property in the FBX header, found "
                                  f"{len(hits)}")
    e = hits[0]
    v = value.encode("utf-8")
    e.props[-1] = _pstr(v) if e.props[0] == _pstr(raw) else v


@contextlib.contextmanager
def deterministic_fbx(native_file: str = "pipeline.blend", creation_time: datetime.datetime = CREATION_TIME):
    """Patch io_scene_fbx for one export (see the module docstring). native_file is written instead of the absolute
    .blend path - use something that names the stage, e.g. "my-pipeline:work/04_final.blend"."""
    import io_scene_fbx.export_fbx_bin as E
    import io_scene_fbx.fbx_utils as U

    orig_header = _require(E, "fbx_header_elements", ("root", "scene_data", "time"))
    orig_vid = _require(E, "_gen_vid_path", ("img", "scene_data"))
    orig_uuid = _require(U, "_key_to_uuid", ("uuids", "key"))
    for cache in ("_keys_to_uuids", "_uuids_to_keys"):
        if not isinstance(getattr(U, cache, None), dict):
            raise FbxInternalsChanged(f"io_scene_fbx.fbx_utils.{cache} is missing - update fbx_deterministic.py")
    calls = {"header": 0, "uuid": 0, "video": 0}

    def header(root, scene_data, time=None):
        calls["header"] += 1
        orig_header(root, scene_data, creation_time)
        _replace_native_file(root, native_file)

    def key_to_uuid(uuids, key):
        calls["uuid"] += 1
        if isinstance(key, int) and 0 <= key < 2 ** 63:
            return orig_uuid(uuids, key)
        rk = repr(key)
        if " at 0x" in rk:   # a key that embeds a memory address is not stable either - refuse rather than guess
            raise FbxInternalsChanged(f"FBX UID key {rk[:80]} embeds a memory address")
        h = int.from_bytes(hashlib.sha256(rk.encode("utf-8")).digest()[:8], "little") & (2 ** 63 - 1)
        return orig_uuid(uuids, h)

    def vid_path(img, scene_data):
        calls["video"] += 1
        _abs, rel = orig_vid(img, scene_data)
        rel = rel.replace("\\", "/")      # os.path separators differ per host; the file must not
        return rel, rel                   # Video Path / Filename = the relative name, never <OUT>/<image>

    U._keys_to_uuids.clear()
    U._uuids_to_keys.clear()
    E.fbx_header_elements, E._gen_vid_path, U._key_to_uuid = header, vid_path, key_to_uuid
    ok = False
    try:
        yield calls
        ok = True
    finally:
        E.fbx_header_elements, E._gen_vid_path, U._key_to_uuid = orig_header, orig_vid, orig_uuid
        U._keys_to_uuids.clear()
        U._uuids_to_keys.clear()
    if ok and (calls["header"] != 1 or calls["uuid"] == 0):
        raise FbxInternalsChanged(f"the patched FBX writer did not run as expected ({calls}) - did the export go "
                                  f"through bpy.ops.export_scene.fbx inside the with block?")


def assert_no_host_paths(fbx_path, paths) -> None:
    """Raise if any of `paths` (folders: the output dir, the .blend dir, the home dir ...) appears in the FBX bytes in
    either slash style - the proof that no host path leaked in (and that the patches were active)."""
    data = open(fbx_path, "rb").read()
    for p in paths:
        s = str(p).rstrip("\\/")
        if not s:
            continue
        for form in {s, s.replace("\\", "/"), s.replace("/", "\\")}:
            if form.encode("utf-8") in data:
                raise FbxInternalsChanged(f"{fbx_path} contains the host path {form!r}")


# ----------------------------------------------------------------------------- read-back


def read_fbx(path) -> dict:
    """Parse an FBX with Blender's own parser (io_scene_fbx.parse_fbx; run inside Blender). Returns
        {"global": {prop: values}, "models": {uid: {"name", "kind", "props"}}, "parent": {uid: parent uid (0 = root)},
         "vertices": {model uid: [[x, y, z], ...]}}  (FBX file axes and units)."""
    from io_scene_fbx import parse_fbx
    root, _version = parse_fbx.parse(str(path))

    def child(e, name):
        return next((c for c in e.elems if c.id == name), None)

    def props70(e):
        out = {}
        p70 = child(e, b"Properties70") if e is not None else None
        for p in (p70.elems if p70 is not None else ()):
            out[p.props[0].decode()] = list(p.props[4:])
        return out

    models, geoms = {}, {}
    for e in child(root, b"Objects").elems:
        if e.id == b"Model":
            models[e.props[0]] = {"name": e.props[1].split(b"\x00\x01")[0].decode(), "kind": e.props[2].decode(),
                                  "props": props70(e)}
        elif e.id == b"Geometry":
            vv = child(e, b"Vertices")
            if vv is not None:
                flat = list(vv.props[0])
                geoms[e.props[0]] = [flat[i:i + 3] for i in range(0, len(flat), 3)]
    parent, vertices = {}, {}
    for c in child(root, b"Connections").elems:
        if c.props[0] != b"OO":
            continue
        a, b = c.props[1], c.props[2]
        if a in models and (b in models or b == 0):
            parent[a] = b
        if a in geoms and b in models:
            vertices[b] = geoms[a]
    return {"global": props70(child(root, b"GlobalSettings")), "models": models, "parent": parent,
            "vertices": vertices}


def transform_errors(fbx: dict, rot_tol: float = 1e-4, scale_tol: float = 1e-5) -> list[str]:
    """Every model must carry identity rotation and unit scale (the joint contract) and no pre/post/geometric
    offsets - otherwise the plain-translation world positions below are wrong and Unity's joints are not at rest."""
    errs = []
    for m in fbx["models"].values():
        p = m["props"]
        if any(abs(float(x)) > rot_tol for x in p.get("Lcl Rotation", ())):
            errs.append(f"{m['name']} has Lcl Rotation {p['Lcl Rotation']}")
        if any(abs(float(x) - 1.0) > scale_tol for x in p.get("Lcl Scaling", ())):
            errs.append(f"{m['name']} has Lcl Scaling {p['Lcl Scaling']}")
        for bad in ("PreRotation", "PostRotation", "GeometricRotation", "GeometricTranslation", "GeometricScaling"):
            vals = p.get(bad)
            if vals and any(abs(float(x) - (1.0 if bad == "GeometricScaling" else 0.0)) > rot_tol for x in vals):
                errs.append(f"{m['name']} has {bad} {vals}")
    return errs


def unity_frame(fbx: dict):
    """-> (to_unity(p_fbx) -> [x, y, z] metres, world_fbx(uid) -> [x, y, z], names {name: uid}).
    Unity's importer negates FBX X for its left-handed space and, with useFileScale, scales by UnitScaleFactor / 100.
    world_fbx sums Lcl Translation up the parent chain - valid because transform_errors() is empty."""
    usf = float(fbx["global"].get("UnitScaleFactor", [1.0])[0])
    to_m = usf / 100.0

    def world_fbx(uid):
        t = [0.0, 0.0, 0.0]
        while uid in fbx["models"]:
            lt = fbx["models"][uid]["props"].get("Lcl Translation")
            if lt:
                t = [t[i] + float(lt[i]) for i in range(3)]
            uid = fbx["parent"].get(uid, 0)
        return t

    def to_unity(p):
        return [-float(p[0]) * to_m, float(p[1]) * to_m, float(p[2]) * to_m]

    names = {m["name"]: uid for uid, m in fbx["models"].items()}
    return to_unity, world_fbx, names


def axis_system(fbx: dict) -> tuple:
    """((UpAxis, sign), (FrontAxis, sign), (CoordAxis, sign)); Unity-ready Y-up is ((1, 1), (2, 1), (0, 1))."""
    g = fbx["global"]
    return tuple((int(g[f"{k}Axis"][0]), int(g[f"{k}AxisSign"][0])) for k in ("Up", "Front", "Coord"))
