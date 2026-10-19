"""04_validate.py - fail loudly (exit 1) unless the final stage meets the contract; record WHICH file passed.

    blender -b --factory-startup --python-exit-code 2 -P 04_validate.py -- --out <OUT> [--stage 02_bake]

Checks (Blender frame, metres):
  * the contract hierarchy: every name present with its parent and kind, nothing else under the root, no stray
    exportable object outside it
  * rest pose: identity rotation, unit scale, identity parent-inverse, zero delta transforms, det > 0 (no mirror)
  * every node at its contract rest position (0.1 mm); each joint turns about its contract axis through its pivot
    (posed +30 deg, the child marker lands where the analytic rotation puts it), and the Unity sign rule
    AngleAxis(-t, M a) reproduces that pose in Unity coordinates
  * closed meshes have outward normals (signed volume > 0); the room's faces all face the interior
  * tris <= TRIS_MAX
  * UVs: one map named UVAtlas per mesh, inside [0, 1], non-overlapping, undistorted (stretch p95)
  * the atlas: 8-bit RGBA PNG at the contract size (<= ATLAS_MAX, power of two), straight alpha (matte texels keep
    their colour), its alpha values are the materials' gloss values
  * cameras.json + the three preview sets + a PASSING fidelity.json, all bound to THIS stage file's sha256
Writes <OUT>/validate.json with the validated stage's sha256 - export refuses any other file. Never saves the stage.
"""

import argparse
import math
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True       # no __pycache__ inside the skill folder
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "scripts")]

import bpy_stage as S  # noqa: E402
import contract as K  # noqa: E402
import lookdev as L  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[validate] {'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def world_verts(o):
    # float64 from the start: mathutils is float32, which costs ~0.1 mm at room scale
    a = np.empty(len(o.data.vertices) * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", a)
    m = np.array(o.matrix_world, dtype=np.float64)
    return a.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def tris_of(o):
    o.data.calc_loop_triangles()
    t = np.empty(len(o.data.loop_triangles) * 3, dtype=np.int64)
    o.data.loop_triangles.foreach_get("vertices", t)
    return t.reshape(-1, 3)


def signed_volume(o):
    v, t = world_verts(o), tris_of(o)
    return float(np.einsum("ij,ij->i", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])).sum() / 6.0)


def rodrigues(axis, deg, v):
    """Rotate v about the unit axis by deg - the plain formula, the same one Unity's Quaternion.AngleAxis applies to
    raw coordinates (its left-handedness is in how the axes are drawn, not in the arithmetic)."""
    k = np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis)
    v = np.asarray(v, dtype=np.float64)
    t = math.radians(deg)
    return v * math.cos(t) + np.cross(k, v) * math.sin(t) + k * np.dot(k, v) * (1 - math.cos(t))


def uv_arrays(o):
    me = o.data
    me.calc_loop_triangles()
    uvl = me.uv_layers.get(K.UV_LAYER)
    uv = np.empty(len(me.loops) * 2, dtype=np.float64)
    uvl.data.foreach_get("uv", uv)
    lt = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", lt)
    vt = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", vt)
    return uv.reshape(-1, 2), lt.reshape(-1, 3), vt.reshape(-1, 3)


def uv_raster(meshes, res):
    """Per texel centre, how many UV triangles cover it, over every mesh together (one atlas). Rows bottom-up, like
    Blender's image pixels."""
    count = np.zeros((res, res), dtype=np.int16)
    for o in meshes:
        uv, lt, _ = uv_arrays(o)
        for p in uv[lt] * res - 0.5:
            x0, y0 = max(int(math.floor(p[:, 0].min())), 0), max(int(math.floor(p[:, 1].min())), 0)
            x1, y1 = min(int(math.ceil(p[:, 0].max())), res - 1), min(int(math.ceil(p[:, 1].max())), res - 1)
            if x1 < x0 or y1 < y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
            (ax, ay), (bx, by), (cx, cy) = p
            d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(d) < 1e-12:
                continue
            l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
            l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
            inside = (l1 > 1e-6) & (l2 > 1e-6) & (1 - l1 - l2 > 1e-6)
            count[ys[inside], xs[inside]] += 1
    return count


def uv_stretch(meshes):
    """Area-weighted p95 of sigma_max / sigma_min of each triangle's 3D -> UV map (1 = conformal)."""
    vals, wts = [], []
    for o in meshes:
        uv, lt, vt = uv_arrays(o)
        co = world_verts(o)
        e1, e2 = co[vt[:, 1]] - co[vt[:, 0]], co[vt[:, 2]] - co[vt[:, 0]]
        u1, u2 = uv[lt[:, 1]] - uv[lt[:, 0]], uv[lt[:, 2]] - uv[lt[:, 0]]
        n = np.cross(e1, e2)
        area = 0.5 * np.linalg.norm(n, axis=1)
        l1 = np.linalg.norm(e1, axis=1)
        ok = (area > 1e-10) & (l1 > 1e-9)
        ax = e1[ok] / l1[ok, None]
        by = np.cross(n[ok] / np.linalg.norm(n[ok], axis=1)[:, None], ax)
        P = np.stack([np.stack([l1[ok], np.zeros(ok.sum())], 1), np.stack([(e2[ok] * ax).sum(1), (e2[ok] * by).sum(1)], 1)], 2)
        J = np.stack([u1[ok], u2[ok]], 2) @ np.linalg.inv(P)
        sv = np.linalg.svd(J, compute_uv=False)
        good = sv[:, 1] > 1e-12
        vals.append(sv[good, 0] / sv[good, 1])
        wts.append(area[ok][good])
    v, w = np.concatenate(vals), np.concatenate(wts)
    order = np.argsort(v)
    return float(v[order][np.searchsorted(np.cumsum(w[order]) / w.sum(), 0.95)])


def png_ihdr(path):
    """(width, height, bit depth, colour type) - colour type 6 = RGBA."""
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h, head[24], head[25]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=K.FINAL_STAGE)
    a = S.parse_args(ap)
    v = S.check_version()
    stage_file = S.open_stage(a.stage)
    stage_sha = S.sha256(stage_file)
    sc = bpy.context.scene
    quick = bool(sc.get("quick", False))
    ob = bpy.data.objects
    check("blender version recorded", True, ".".join(map(str, v)))

    # --- hierarchy
    missing, wrong = [], []
    for name, parent, kind, _pos in K.HIERARCHY:
        o = ob.get(name)
        if o is None:
            missing.append(name)
            continue
        want_type = "MESH" if kind == "mesh" else "EMPTY"
        if (o.parent.name if o.parent else None) != parent or o.type != want_type:
            wrong.append(f"{name}: parent {o.parent.name if o.parent else None} type {o.type}")
    check("contract hierarchy: names, parents, kinds", not missing and not wrong, f"missing={missing} wrong={wrong}")
    root = ob.get(K.ROOT)
    rig = [root] + list(root.children_recursive) if root else []
    names = {h[0] for h in K.HIERARCHY}
    extra = sorted(o.name for o in rig if o.name not in names)
    stray = sorted(o.name for o in ob if o.type in ("MESH", "EMPTY") and o not in rig)
    check("nothing but the contract under the root, no exportable object outside it", not extra and not stray,
          f"extra={extra} stray={stray}")

    # --- rest pose
    bad = []
    for o in rig:
        if (o.rotation_mode != "XYZ" or any(abs(x) > 1e-9 for x in o.rotation_euler) or
                any(abs(s - 1) > 1e-9 for s in o.scale) or
                any(abs(x) > 1e-9 for x in o.delta_location) or any(abs(x) > 1e-9 for x in o.delta_rotation_euler) or
                any(abs(s - 1) > 1e-9 for s in o.delta_scale) or
                not np.allclose(np.array(o.matrix_parent_inverse), np.eye(4), atol=1e-9)):
            bad.append(o.name)
    check("rest: identity rotation / unit scale / identity parent-inverse / no delta transforms", not bad, f"{bad}")
    mirrored = [o.name for o in rig if o.matrix_world.determinant() <= 0]
    check("det > 0 everywhere (no mirrored node)", not mirrored, f"{mirrored}")
    bpy.context.view_layer.update()
    off = {}
    for name, _p, _k, pos in K.HIERARCHY:
        if name in ob:
            d = np.linalg.norm(np.array(ob[name].matrix_world.translation, dtype=np.float64) - np.array(pos))
            if d > 1e-4:
                off[name] = round(float(d) * 1000, 3)
    check("every node at its contract rest position (0.1 mm)", not off, f"off by mm: {off}")

    # --- joints: axis + pivot, and the Unity sign rule
    jerr = {}
    for j, spec in K.JOINTS.items():
        tip = "HeadTip"
        p_j = np.array(K.node(j)[3])
        p_tip = np.array(K.node(tip)[3])
        o = ob[j]
        ax = np.array(spec["axis"], dtype=np.float64)
        o.rotation_mode = "AXIS_ANGLE"
        o.rotation_axis_angle = (math.radians(30.0), *ax)
        bpy.context.view_layer.update()
        got = np.array(ob[tip].matrix_world.translation, dtype=np.float64)
        want = p_j + rodrigues(ax, 30.0, p_tip - p_j)
        # Unity: localRotation = AngleAxis(-30, M a) on the M-mapped offset must land on M(got)
        M = np.array(K.M_BLENDER_TO_UNITY, dtype=np.float64)
        unity_pred = M @ p_j + rodrigues(M @ ax, -30.0, M @ (p_tip - p_j))
        e_b, e_u = np.linalg.norm(got - want), np.linalg.norm(M @ got - unity_pred)
        o.rotation_mode = "XYZ"
        o.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()
        if e_b > 1e-4 or e_u > 1e-4:
            jerr[j] = (round(float(e_b) * 1000, 3), round(float(e_u) * 1000, 3))
    check("joints turn about their contract axis through their pivot; Unity AngleAxis(-t, M a) agrees", not jerr,
          f"errors mm (blender, unity): {jerr}")

    # --- geometry
    meshes = [ob[n] for n, _p, kind, _l in K.HIERARCHY if kind == "mesh" and n in ob]
    inside_out = [o.name for o in meshes if o.name != "Room" and signed_volume(o) <= 0]
    check("closed machine meshes have outward normals (signed volume > 0)", not inside_out, f"{inside_out}")
    room = ob["Room"]
    mw = np.array(room.matrix_world, dtype=np.float64)
    centre = np.array([0.0, 0.0, K.ROOM_SIZE[2] / 2])
    outward = 0
    for p in room.data.polygons:
        c = mw[:3, :3] @ np.array(p.center) + mw[:3, 3]
        n = mw[:3, :3] @ np.array(p.normal)
        outward += int(np.dot(n, centre - c) <= 0)
    check("every room face faces the interior (Unity culls back faces)", outward == 0, f"{outward} outward faces")
    tris = {o.name: len(tris_of(o)) for o in meshes}
    check(f"tris <= {K.TRIS_MAX}", sum(tris.values()) <= K.TRIS_MAX, f"{sum(tris.values())} {tris}")

    # --- UVs
    layers = {o.name: [u.name for u in o.data.uv_layers] for o in meshes}
    check(f"one UV map named {K.UV_LAYER} per mesh", all(v_ == [K.UV_LAYER] for v_ in layers.values()), f"{layers}")
    if all(v_ == [K.UV_LAYER] for v_ in layers.values()):
        lo = min(float(uv_arrays(o)[0].min()) for o in meshes)
        hi = max(float(uv_arrays(o)[0].max()) for o in meshes)
        check("UVs inside [0, 1]", lo >= -1e-6 and hi <= 1 + 1e-6, f"[{lo:.4f}, {hi:.4f}]")
        count = uv_raster(meshes, 512)
        ov = float((count > 1).sum() / max((count > 0).sum(), 1))
        check("UV islands do not overlap (one atlas)", ov <= 1e-4, f"{ov * 100:.4f} % of covered texels")
        st = uv_stretch(meshes)
        check(f"UVs undistorted (stretch p95 <= {K.UV_STRETCH_MAX})", st <= K.UV_STRETCH_MAX, f"{st:.3f}")

    # --- atlas
    atlas = S.work_dir() / K.ATLAS_FILE
    size = K.ATLAS_SIZE_QUICK if quick else K.ATLAS_SIZE
    info = png_ihdr(atlas) if atlas.is_file() else None
    check("atlas: 8-bit RGBA PNG at the contract size (power of two, <= ATLAS_MAX)",
          info == (size, size, 8, 6) and size <= K.ATLAS_MAX and size & (size - 1) == 0, f"{info} want {size}")
    if info:
        img = bpy.data.images.load(S.resolve(atlas), check_existing=False)
        img.colorspace_settings.name = "Non-Color"
        img.alpha_mode = "CHANNEL_PACKED"
        px = L.pixels(img)
        bpy.data.images.remove(img)
        matte = px[..., 3] == 0
        rgb_matte = float(px[matte][:, :3].mean()) if matte.any() else 0.0
        check("straight alpha: matte (alpha 0) texels keep their colour", matte.any() and rgb_matte > 0.05,
              f"{matte.mean() * 100:.1f} % matte texels, their mean RGB {rgb_matte:.3f} (premultiplied would be 0)")
        # inside the islands only: the gutters and the unused texels hold dilated / mean fill by design
        inside = uv_raster(meshes, info[0]) > 0
        gl = sorted({round(float(m["gloss"]) * 255) for m in bpy.data.materials if "gloss" in m})
        vals, cnt = np.unique(np.round(px[..., 3][inside] * 255).astype(int), return_counts=True)
        dominant = [int(x) for x, c in zip(vals, cnt) if c >= 0.01 * inside.sum()]
        stray_a = [x for x in dominant if min(abs(x - g) for g in gl) > 2]
        check("atlas alpha inside the islands = the materials' gloss values", dominant and not stray_a,
              f"dominant x255 {dominant}, gloss table x255 {gl}")

    # --- previews + fidelity bound to this stage
    out = S.out_dir()
    cams = S.read_json(out / "cameras.json", {})
    shot_names = [s[0] for s in K.SHOTS]
    have = [n for n in shot_names if all((out / d / f"{n}.png").is_file()
                                         for d in ("previews", "previews_unlit", "previews_mask"))]
    check("cameras.json + reference / unlit / mask for every shot, from THIS stage",
          cams.get("stage_sha256") == stage_sha and [s["name"] for s in cams.get("shots", [])] == shot_names and
          have == shot_names, f"stage match {cams.get('stage_sha256') == stage_sha}, shots {have}")
    fid = S.read_json(out / "fidelity.json", {})
    summ = fid.get("summary", {}).get(fid.get("gate", {}).get("region"), {})
    check("fidelity.json passed, on THIS stage's previews", fid.get("pass") is True and fid.get("stage_sha256") == stage_sha,
          f"pass {fid.get('pass')}, stage match {fid.get('stage_sha256') == stage_sha}, gate {fid.get('gate', {}).get('region')} "
          f"SSIM {summ.get('ssim_mean')} dE {summ.get('deltaE_mean')}")

    n_fail = sum(1 for r in RESULTS if not r["ok"])
    S.write_json(out / "validate.json", {
        "format": "validate/1", "stage": a.stage, "stage_sha256": stage_sha, "quick": quick, "blender": list(v),
        "pass": len(RESULTS) - n_fail, "fail": n_fail, "tris": tris, "results": RESULTS})
    print(f"[validate] {len(RESULTS) - n_fail}/{len(RESULTS)} passed on {a.stage} (sha256 {stage_sha[:12]})", flush=True)
    if n_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
