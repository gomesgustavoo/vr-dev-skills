"""03_preview.py - per shot: the Cycles REFERENCE, the UNLIT render of the atlases, a coverage MASK; cameras.json.

    blender -b --factory-startup --python-exit-code 2 -P 03_preview.py -- --out <OUT> [--quick]

  previews/<shot>.png        reference: the authoring materials path-traced under lookdev's lights and view (denoised).
                             This is what "looks right" means; the fidelity gate measures everything else against it.
  previews_unlit/<shot>.png  what the Quest draws: every surface the emission of its atlas texel (no light, no
                             reflection), not denoised (OIDN has no albedo guide on an emission closure and would blur).
  previews_mask/<shot>.png   linear coverage (Raw view): R room, G static machine, B moving parts - fidelity regions.
  cameras.json               every shot in the UNITY frame (position, target, up, vertical FOV, aspect, resolution,
                             near clip, the pose) so a Unity capture script renders the same frames; bound to the
                             stage's sha256.
Reads <OUT>/work/02_bake.blend and never saves it (the stage file stays byte-identical for validate / export).
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
from mathutils import Vector  # noqa: E402

SENSOR_MM = 36.0
CLIP_NEAR = 0.05


def render(sc, path, samples, denoise, view="Standard"):
    sc.cycles.samples = samples
    sc.cycles.use_denoising = denoise
    sc.view_settings.view_transform = view
    ims = sc.render.image_settings
    ims.file_format, ims.color_mode, ims.color_depth = "PNG", "RGB", "8"
    sc.render.filepath = S.resolve(path)          # absolute: a relative render path lands at the drive root
    bpy.ops.render.render(write_still=True)


def fov_deg(lens, res):
    h = 2.0 * math.atan(SENSOR_MM / 2.0 / lens)                     # sensor_fit AUTO + landscape = horizontal fit
    v = 2.0 * math.atan(math.tan(h / 2.0) * res[1] / res[0])
    return math.degrees(h), math.degrees(v)


def main():
    a = S.parse_args()
    S.check_version()
    stage = S.open_stage(K.FINAL_STAGE)
    stage_sha = S.sha256(stage)
    sc = bpy.context.scene
    res = K.RESOLUTION_QUICK if a.quick else K.RESOLUTION
    s_ref, s_unlit, s_mask = (64, 8, 4) if a.quick else (256, 16, 8)
    dev = L.use_device(sc)
    L.set_bounces(sc)
    L.black_world(sc)
    L.apply_view(sc)
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    out = S.out_dir()
    dirs = {k: out / k for k in ("previews", "previews_unlit", "previews_mask")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    meshes = [bpy.data.objects[n] for n, _p, kind, _l in K.HIERARCHY if kind == "mesh"]
    authoring = {o.name: [s.material for s in o.material_slots] for o in meshes}
    atlas = L.load_atlas(S.work_dir() / K.ATLAS_FILE)
    unlit = L.unlit_material("PV_unlit", atlas, K.UV_LAYER)
    masks = {g: L.flat_material(f"PV_mask_{g}", rgb) for g, rgb in K.MASK_RGB.items()}

    cam_data = bpy.data.cameras.new("PV_cam")
    cam_data.sensor_width, cam_data.sensor_fit, cam_data.clip_start = SENSOR_MM, "AUTO", CLIP_NEAR
    cam = bpy.data.objects.new("PV_cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    shots = []
    for name, loc, tgt, lens in K.SHOTS:
        t0 = time.time()
        cam_data.lens = lens
        cam.location = Vector(loc)
        # -Z looks at the target, +Y toward world up: the same frame as Unity's Quaternion.LookRotation(dir, up)
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        for o in meshes:
            for s, m in zip(o.material_slots, authoring[o.name]):
                s.material = m
        render(sc, dirs["previews"] / f"{name}.png", s_ref, True)
        for o in meshes:
            L.assign_all_slots(o, unlit)
        render(sc, dirs["previews_unlit"] / f"{name}.png", s_unlit, False)
        for o in meshes:
            L.assign_all_slots(o, masks[K.GROUPS[o.name]])
        render(sc, dirs["previews_mask"] / f"{name}.png", s_mask, False, view="Raw")
        L.apply_view(sc)
        hf, vf = fov_deg(lens, res)
        shots.append({"name": name, "positionUnity": [round(x, 6) for x in K.to_unity(loc)],
                      "targetUnity": [round(x, 6) for x in K.to_unity(tgt)], "upUnity": [0.0, 1.0, 0.0],
                      "verticalFovDeg": round(vf, 6), "horizontalFovDeg": round(hf, 6),
                      "aspect": round(res[0] / res[1], 6), "resolution": list(res), "nearClipM": CLIP_NEAR,
                      "lensMm": lens, "sensorWidthMm": SENSOR_MM, "pose": {j: 0.0 for j in K.JOINTS}})
        S.log(f"{name}: reference + unlit + mask ({time.time() - t0:.1f} s)")

    S.write_json(out / "cameras.json", {
        "format": "cameras/1", "stage": K.FINAL_STAGE, "stage_sha256": stage_sha, "device": dev, "view": L.VIEW,
        "samples": {"reference": s_ref, "unlit": s_unlit, "mask": s_mask}, "quick": bool(a.quick),
        "frame": "Unity: x = Blender X, y = Blender Z, z = Blender Y (m); camera = LookRotation(target - position, up), "
                 "Camera.fieldOfView = verticalFovDeg, no roll",
        "denoise": {"reference": True, "unlit": False, "mask": False},
        "shots": shots})
    S.log(f"cameras.json: {len(shots)} shots, stage sha256 {stage_sha[:12]}")


if __name__ == "__main__":
    main()
