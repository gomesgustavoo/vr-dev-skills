"""02_bake.py - one non-overlapping atlas for every mesh, with the full Cycles light baked in DISPLAY-REFERRED.

    blender -b --factory-startup --python-exit-code 2 -P 02_bake.py -- --out <OUT> [--quick]

Atlas texel = encode(view)(albedo x (direct + indirect diffuse light) + emission), 8-bit sRGB: what the Cycles
reference shows, so Unity samples it UNLIT and pays no lighting cost. Alpha = the gloss mask (from roughness /
metallic; Unity's cheap reflection term reads it), written STRAIGHT from a byte image.
Bake sets (contract GROUPS / CASTERS): the room + the static base bake with the moving parts hidden (no arm shadow is
frozen onto the floor), each moving part bakes at REST seeing the static scene and itself only (its neighbours move).
Per-set bakes use margin 0 (a bake's margin overwrites the other sets' islands, which it treats as empty) and the
gutters are filled afterwards by dilation.
--quick: 512 atlas, 32 samples (iteration; export refuses it without --allow-quick).
Output: <OUT>/work/02_bake.blend (+ UVs, the atlas datablock, bake record) and <OUT>/work/HelloRoom_atlas.png
"""

import json
import math
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True       # no __pycache__ inside the skill folder
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "scripts")]

import bpy_stage as S  # noqa: E402
import contract as K  # noqa: E402
import lookdev as L  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

BAKE_NODE = "__bake__"


def select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def unwrap(meshes, size):
    """One UV map per mesh, every island packed together into one 0..1 square, never overlapping."""
    for o in meshes:
        me = o.data
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])
        me.uv_layers.new(name=K.UV_LAYER)
    select_only(meshes)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # correct_aspect OFF: headless there is no image editor and the operator uses a bogus aspect (islands 4-16x stretched)
    bpy.ops.uv.smart_project(angle_limit=math.radians(45.0), island_margin=0.0, area_weight=0.0,
                             correct_aspect=False, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for o in meshes:                                   # texel-density weights: more texels where users look closely
        w = K.TEXEL_WEIGHT.get(o.name, 1.0)
        if w != 1.0:
            uvl = o.data.uv_layers[K.UV_LAYER]
            uv = np.empty(len(uvl.data) * 2, dtype=np.float32)
            uvl.data.foreach_get("uv", uv)
            uvl.data.foreach_set("uv", uv * w)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    # rotate OFF for the same headless-aspect reason (a 90 degree turn applies the bogus aspect)
    bpy.ops.uv.pack_islands(rotate=False, scale=True, margin_method="FRACTION", margin=K.UV_MARGIN_PX / size,
                            shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


def new_float_image(name, size):
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"         # raw linear numbers: no transform on write
    img.generated_color = (0.0, 0.0, 0.0, 0.0)
    return img


def point_bake_nodes(meshes, img):
    for m in {s.material for o in meshes for s in o.material_slots if s.material}:
        nt = m.node_tree
        n = nt.nodes.get(BAKE_NODE) or nt.nodes.new("ShaderNodeTexImage")
        n.name = BAKE_NODE
        n.image = img
        nt.nodes.active = n                             # the bake writes into the ACTIVE image node


def bake(targets, visible, img, kind, samples, clear, pass_filter=None):
    sc = bpy.context.scene
    sc.cycles.samples = samples
    point_bake_nodes(targets, img)
    vis = {o.name for o in visible}
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o.name not in vis
    select_only(targets)
    kw = dict(type=kind, margin=0, margin_type="EXTEND", use_clear=clear, uv_layer=K.UV_LAYER,
              target="IMAGE_TEXTURES", use_selected_to_active=False)
    if pass_filter:
        kw["pass_filter"] = pass_filter
    bpy.ops.object.bake(**kw)


def dilate(val, valid, iters):
    """Fill invalid texels from their valid 4-neighbours, `iters` rings out (the gutters mip-mapping and bilinear
    filtering will read), then the rest with the mean colour (no dark halo in the far mips)."""
    v, ok = val.copy(), valid.copy()
    for _ in range(iters):
        acc = np.zeros_like(v)
        cnt = np.zeros(ok.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            so = np.roll(np.roll(ok, dy, 0), dx, 1)
            acc += np.roll(np.roll(v, dy, 0), dx, 1) * so[..., None]
            cnt += so
        fill = ~ok & (cnt > 0)
        v[fill] = acc[fill] / cnt[fill][:, None]
        ok |= fill
    v[~ok] = val[valid].mean(axis=0)
    return v


def gloss_pass(meshes, img):
    """EMIT bake of each material's constant gloss: its Surface temporarily routed to Emission(gloss)."""
    saved = []
    for m in {s.material for o in meshes for s in o.material_slots if s.material}:
        nt = m.node_tree
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        src = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
        em = nt.nodes.new("ShaderNodeEmission")
        g = float(m.get("gloss", 0.0))
        em.inputs["Color"].default_value = (g, g, g, 1.0)
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        saved.append((nt, out, src, em))
    bake(meshes, meshes, img, "EMIT", 1, clear=True)
    for nt, out, src, em in saved:
        nt.nodes.remove(em)
        if src is not None:
            nt.links.new(src, out.inputs["Surface"])
    return L.pixels(img)[..., 0].copy()


def main():
    a = S.parse_args()
    v = S.check_version()
    S.open_stage("01_build")
    sc = bpy.context.scene
    size = K.ATLAS_SIZE_QUICK if a.quick else K.ATLAS_SIZE
    samples = 32 if a.quick else 256
    ob = bpy.data.objects
    meshes = [ob[n] for n, _p, kind, _l in K.HIERARCHY if kind == "mesh"]
    static = [o for o in meshes if K.GROUPS[o.name] in ("room", "static")]
    moving = [o for o in meshes if K.GROUPS[o.name] == "moving"]

    t0 = time.time()
    unwrap(meshes, size)
    S.log(f"unwrapped {len(meshes)} meshes into one {size}^2 atlas ({time.time() - t0:.1f} s)")

    dev = L.use_device(sc)
    L.set_bounces(sc)
    L.black_world(sc)
    L.apply_view(sc)
    sc.cycles.use_denoising = False
    sc.render.bake.use_selected_to_active = False
    S.log(f"cycles device {dev['backend']} {dev['devices']}, {samples} samples")

    # diffuse light: the static set with the moving parts hidden, then each moving part at rest with its casters
    t0 = time.time()
    img = new_float_image("__bake_diffuse__", size)
    bake(static, static, img, "DIFFUSE", samples, clear=True, pass_filter={"DIRECT", "INDIRECT", "COLOR"})
    casters = {}
    for o in moving:
        vis = static + [ob[n] for n in K.CASTERS.get(o.name, (o.name,))]
        bake([o], vis, img, "DIFFUSE", samples, clear=False, pass_filter={"DIRECT", "INDIRECT", "COLOR"})
        casters[o.name] = sorted(x.name for x in vis)
    px = L.pixels(img)
    diffuse, cover = px[..., :3].copy(), px[..., 3] > 0.5
    S.log(f"diffuse bakes: {time.time() - t0:.1f} s, coverage {cover.mean() * 100:.1f} % of the atlas")

    emit_img = new_float_image("__bake_emit__", size)
    bake(meshes, meshes, emit_img, "EMIT", 1, clear=True)
    emit = L.pixels(emit_img)[..., :3]
    gloss = gloss_pass(meshes, new_float_image("__bake_gloss__", size))

    rings = 2 * K.UV_MARGIN_PX + 2
    rgb = dilate(diffuse + emit, cover, rings)
    alpha = dilate(gloss[..., None], cover, rings)[..., 0]
    display = L.encode_display(sc, rgb, S.work_dir() / "__encode.png")
    atlas_path = S.work_dir() / K.ATLAS_FILE
    atlas = L.save_rgba_png(atlas_path, "HelloRoom_atlas", display, alpha)
    clip = float((rgb[cover] >= 1.0).any(axis=1).mean())
    S.log(f"atlas {atlas_path.name}: {size}x{size} RGBA, {clip * 100:.2f} % of covered texels clip at 1.0, gloss "
          f"{float(alpha[cover].min()):.2f}..{float(alpha[cover].max()):.2f}")

    # the shipping material (the FBX names the atlas; Unity's importer/builder assigns the real unlit shader)
    m = bpy.data.materials.get("M_Atlas") or bpy.data.materials.new("M_Atlas")
    nt = L.node_tree(m)
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = K.UV_LAYER
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = atlas
    nt.links.new(uv.outputs["UV"], tx.inputs["Vector"])
    nt.links.new(tx.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    m.use_fake_user = True          # unused until export swaps it in; keep it in the stage file

    # leave the stage clean: no bake nodes, no scratch images, every mesh renderable again
    for mat in bpy.data.materials:
        if mat.node_tree and BAKE_NODE in mat.node_tree.nodes:
            mat.node_tree.nodes.remove(mat.node_tree.nodes[BAKE_NODE])
    for im in (img, emit_img, bpy.data.images.get("__bake_gloss__")):
        if im is not None:
            bpy.data.images.remove(im)
    for o in ob:
        if o.type == "MESH":
            o.hide_render = False
    sc["quick"] = bool(a.quick)
    sc["bake"] = json.dumps({
        "blender": list(v), "device": dev, "samples": samples, "atlas_size": size, "quick": bool(a.quick),
        "view": L.VIEW, "bounces": L.BOUNCES, "lights": L.LIGHTS, "casters": casters,
        "gloss": {mm.name: round(float(mm["gloss"]), 4) for mm in bpy.data.materials if "gloss" in mm},
        "encoding": "RGB = encode(view)(albedo x (direct + indirect diffuse) + emission), 8-bit sRGB; A = gloss, "
                    "straight"}, sort_keys=True)
    S.save_stage(K.FINAL_STAGE)


if __name__ == "__main__":
    main()
