"""05_export.py - the validated stage -> a deterministic FBX + the atlas + manifest.json for Unity.

    blender -b --factory-startup --python-exit-code 2 -P 05_export.py -- --out <OUT> [--allow-quick]

REFUSES (exit 1) unless <OUT>/validate.json passed (fail 0, pass > 0) on exactly the 02_bake.blend it is about to
export (stage name + sha256), and refuses a --quick stage unless --allow-quick (only run_stages --quick passes it):
a `--from export` after an edit, or after a quick bake, cannot ship an unvalidated or low-quality asset.

The ONE axis conversion of the pipeline happens here, in memory (the stage file is never saved): every joint offset
and every vertex is rewritten as FBX = P . Blender with P = (-X, Z, Y) (a proper rotation, det +1), the root gets the
inverse of the exporter's own axis matrix so it is written as identity, and the file is written in the plain Y-up
axis system. Unity negates FBX x for its left-handed space, giving Unity (x, y, z) = (X, Z, Y) = contract M. Blender's
"Apply Transform" (bake_space_transform) is NOT used: it converts meshes and the root but leaves child joint offsets
in Blender axes. Units: data in metres, UnitScaleFactor 100 -> Unity useFileScale = 1 unit per metre.
The FBX is parsed back and the contract re-checked in UNITY coordinates; any miss is exit 1.
Output: <OUT>/HelloRoom.fbx, <OUT>/HelloRoom_atlas.png (byte copy), <OUT>/manifest.json
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True       # no __pycache__ inside the skill folder
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "scripts")]

import bpy_stage as S  # noqa: E402
import contract as K  # noqa: E402
import fbx_deterministic as F  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix  # noqa: E402

P_BLENDER_TO_FBX = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
NATIVE_FILE = f"hello-room:work/{K.FINAL_STAGE}.blend"     # written instead of the absolute .blend path


def require_validated(stage_file, allow_quick):
    out = S.out_dir()
    val = S.read_json(out / "validate.json")
    if val is None:
        S.fail(f"REFUSED: {out / 'validate.json'} missing - run the validate stage on {stage_file.name} first")
    have = S.sha256(stage_file)
    why = []
    if val.get("stage") != K.FINAL_STAGE:
        why.append(f"validated stage {val.get('stage')!r} != {K.FINAL_STAGE!r}")
    if val.get("stage_sha256") != have:
        why.append(f"validate.json is for stage sha256 {str(val.get('stage_sha256'))[:12]}, the file being exported is "
                   f"{have[:12]} (stale: re-run validate)")
    if not (val.get("fail") == 0 and (val.get("pass") or 0) > 0):
        why.append(f"validate pass {val.get('pass')} / fail {val.get('fail')}")
    quick = bool(bpy.context.scene.get("quick", False))
    if quick and not allow_quick:
        why.append("the stage was baked with --quick; pass --allow-quick for an iteration export (never ship it)")
    if why:
        S.fail("REFUSED:\n  " + "\n  ".join(why))
    S.log(f"validate.json: {val['pass']} pass / 0 fail on {K.FINAL_STAGE} (sha256 {have[:12]})")
    return {"stage": K.FINAL_STAGE, "stage_sha256": have, "pass": val["pass"], "fail": 0, "quick": quick}


def prepare_fbx_space(root):
    """Joint offsets + vertices in FBX axes, the root written as identity (see the module docstring)."""
    from bpy_extras.io_utils import axis_conversion
    done = set()
    for o in root.children_recursive:
        o.location = (P_BLENDER_TO_FBX @ o.location.to_4d()).to_3d()
        if o.type == "MESH" and o.data.name not in done:
            o.data.transform(P_BLENDER_TO_FBX)
            o.data.update()
            done.add(o.data.name)
    root.matrix_world = axis_conversion(to_forward="-Z", to_up="Y").to_4x4().inverted()


def rnd(v, n=6):
    return [round(float(x), n) for x in v]


def verify(fbx_path):
    """Parse the FBX and check the contract where Unity will see it."""
    fbx = F.read_fbx(fbx_path)
    to_unity, world_fbx, names = F.unity_frame(fbx)
    checks, errors = {}, []

    def chk(label, ok, detail):
        checks[label] = {"ok": bool(ok), "detail": detail}
        print(f"[export] {'PASS' if ok else 'FAIL'}  {label}  {detail}", flush=True)
        if not ok:
            errors.append(label)

    ax = F.axis_system(fbx)
    chk("FBX axis system is plain Y-up (Up +Y, Front +Z, Coord +X)", ax == ((1, 1), (2, 1), (0, 1)), ax)
    usf = float(fbx["global"].get("UnitScaleFactor", [0])[0])
    chk("UnitScaleFactor 100 (metre data; Unity useFileScale -> 1 unit per metre)", abs(usf - 100.0) < 1e-9, usf)
    terr = F.transform_errors(fbx)
    chk("every node: identity rotation, unit scale, no pre/post/geometric offsets", not terr, terr[:6])
    want = {h[0] for h in K.HIERARCHY}
    chk("exactly the contract nodes, by exact name", set(names) == want,
        f"missing {sorted(want - set(names))} extra {sorted(set(names) - want)}")
    off = {}
    for name, _p, _k, pos in K.HIERARCHY:
        if name in names:
            got = np.array(to_unity(world_fbx(names[name])))
            d = float(np.linalg.norm(got - np.array(K.to_unity(pos))))
            if d > 1e-4:
                off[name] = round(d * 1000, 3)
    chk("every node at M . (contract rest position) in Unity (0.1 mm)", not off, f"off by mm: {off}")
    room = np.array([to_unity(np.array(p) + world_fbx(names["Room"])) for p in fbx["vertices"][names["Room"]]])
    lo, hi = room.min(axis=0), room.max(axis=0)
    w, d, h = K.ROOM_SIZE
    chk("room in Unity: floor y = 0, ceiling y = height, x / z extents = width / depth",
        np.allclose(lo, [-w / 2, 0, -d / 2], atol=1e-4) and np.allclose(hi, [w / 2, h, d / 2], atol=1e-4),
        f"min {rnd(lo, 4)} max {rnd(hi, 4)}")
    base = np.array([to_unity(np.array(p) + world_fbx(names["Base"])) for p in fbx["vertices"][names["Base"]]])
    chk("machine toward Unity +z (Blender +Y), standing on y = 0", base[:, 2].min() > 0.5 and abs(base[:, 1].min()) < 1e-6,
        f"z >= {base[:, 2].min():.3f}, y min {base[:, 1].min():.6f}")
    return checks, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-quick", action="store_true", help="export a --quick stage (iteration only)")
    a = S.parse_args(ap)
    v = S.check_version()
    stage_file = S.open_stage(K.FINAL_STAGE)
    validated = require_validated(stage_file, a.allow_quick)
    out = S.out_dir()
    ob = bpy.data.objects
    root = ob[K.ROOT]
    rig = [root] + list(root.children_recursive)

    # the manifest, from the Blender frame (before the export turn)
    M = np.array(K.M_BLENDER_TO_UNITY, dtype=np.float64)
    joints, meshes = [], []
    for name, parent, kind, pos in K.HIERARCHY:
        o = ob[name]
        e = {"name": name, "parent": parent, "kind": kind, "unity_local_position": rnd(M @ np.array(o.location)),
             "unity_rest_world": rnd(K.to_unity(pos))}
        if name in K.JOINTS:
            e["axis_unity"] = rnd(M @ np.array(K.JOINTS[name]["axis"]))
            e["range_deg"] = list(K.JOINTS[name]["range_deg"])
            e["rotation"] = "localRotation = Quaternion.AngleAxis(-t, axis_unity) for a Blender +t; rest = identity"
        if kind == "mesh":
            o.data.calc_loop_triangles()
            e["tris"] = len(o.data.loop_triangles)
            meshes.append(e)
        else:
            joints.append(e)

    # the export turn, in memory only: one material on the atlas, no lights / cameras, FBX axes
    for o in list(ob):
        if o not in rig:
            bpy.data.objects.remove(o, do_unlink=True)
    m_atlas = bpy.data.materials["M_Atlas"]
    for o in rig:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(m_atlas)
            for p in o.data.polygons:
                p.material_index = 0
    prepare_fbx_space(root)
    bpy.context.view_layer.update()
    fbx_path = out / K.FBX_FILE
    with F.deterministic_fbx(native_file=NATIVE_FILE):
        bpy.ops.export_scene.fbx(filepath=S.resolve(fbx_path), **F.UNITY_EXPORT_KW)
    F.assert_no_host_paths(fbx_path, [out, Path(bpy.data.filepath).parent, Path.home()])
    S.log(f"wrote {fbx_path.name} (sha256 {S.sha256(fbx_path)[:12]})")
    checks, errors = verify(fbx_path)

    atlas_src = S.work_dir() / K.ATLAS_FILE
    atlas_dst = out / K.ATLAS_FILE
    shutil.copyfile(atlas_src, atlas_dst)            # byte copy: the atlas the gates saw is the atlas that ships
    bake = json.loads(bpy.context.scene.get("bake", "{}"))     # 02_bake's record (device, samples, casters)
    fid = S.read_json(out / "fidelity.json", {})
    files = {p.name: S.sha256(p) for p in (fbx_path, atlas_dst, out / "cameras.json", out / "fidelity.json",
                                           out / "validate.json") if p.is_file()}
    S.write_json(out / "manifest.json", {
        "format": "hello-room-manifest/1",
        "generator": {"blender": S.blender_record(), "pipeline": "hello-room", "quick": validated["quick"],
                      "bake": {k: bake.get(k) for k in ("device", "samples", "atlas_size", "casters")},
                      "fbx_determinism": {"creation_time": F.CREATION_TIME.isoformat(sep=" "),
                                          "application_native_file": NATIVE_FILE,
                                          "video_filename": "relative (file name only, path_mode STRIP)",
                                          "uids": "sha256(key) instead of Python's per-process hash()"}},
        "frame": {"unity": "x = Blender X, y = Blender Z, z = Blender Y (metres); root on the floor at the room centre",
                  "rotation_rule": "Blender right-handed +t about axis a == Unity Quaternion.AngleAxis(-t, M a)"},
        "fbx": {"file": K.FBX_FILE, "unit_scale_factor": 100.0,
                "unity_import": {"globalScale": 1.0, "useFileScale": True, "bakeAxisConversion": False,
                                 "importNormals": "Import", "importTangents": "None", "materialImportMode": "None",
                                 "importCameras": False, "importLights": False, "animationType": "None",
                                 "isReadable": False, "preserveHierarchy": True},
                "verify": {"checks": checks, "errors": errors}},
        "textures": [{"file": K.ATLAS_FILE, "size": bake.get("atlas_size"), "srgb": True, "alpha": "gloss (straight)",
                      "role": "display-referred baked light: sample UNLIT in a linear project",
                      "unity_import": {"sRGBTexture": True, "alphaSource": "FromInput", "alphaIsTransparency": False,
                                       "mipmapEnabled": True, "anisoLevel": 8, "android": "ASTC 4x4 (6x6 to save memory)"}}],
        "joints": joints, "meshes": meshes, "tris": sum(m["tris"] for m in meshes),
        "validate": validated,
        "fidelity": {"pass": fid.get("pass"), "gate": fid.get("gate"), "summary": fid.get("summary")},
        "files": files})
    S.log(f"manifest.json: {len(joints)} joints/empties, {len(meshes)} meshes, {sum(m['tris'] for m in meshes)} tris")
    if errors:
        S.fail(f"FBX read-back failed: {errors}")
    S.log("FBX read-back OK in Unity coordinates")


if __name__ == "__main__":
    main()
