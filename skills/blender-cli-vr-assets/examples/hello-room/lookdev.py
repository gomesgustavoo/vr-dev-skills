"""lookdev.py - the ONE definition of the look: materials, lights, bounces, view transform, Cycles device, shaders.

01_build.py creates the materials and lights from here, 02_bake.py bakes with them and 03_preview.py renders the
reference with them - so the bake sees exactly what the reference renders, and a light or view change cannot reach
one stage and miss the other.
"""

from __future__ import annotations

import os
from pathlib import Path

import bpy
import numpy as np

import bpy_stage as S

# The previews' view: Standard, no look. A --factory-startup scene defaults to AgX, which would bake one tone curve
# and preview another; every stage that renders or encodes calls apply_view() explicitly.
VIEW = {"display_device": "sRGB", "view_transform": "Standard", "look": "None", "exposure": 0.0, "gamma": 1.0}

# Authoring materials (Principled BSDF; base colours are LINEAR). The atlas bakes their diffuse light; roughness and
# metallic become the gloss mask in the atlas alpha. "emit": an emission-only surface (the ceiling light diffusers).
MATERIALS = {
    "M_Floor": {"base": (0.18, 0.17, 0.16), "roughness": 0.65},
    "M_Wall": {"base": (0.62, 0.62, 0.60), "roughness": 0.90},
    "M_Ceiling": {"base": (0.75, 0.75, 0.75), "roughness": 0.95},
    "M_Panel": {"emit": (1.0, 1.0, 1.0)},
    "M_Door": {"base": (0.25, 0.12, 0.05), "roughness": 0.50},
    "M_FloorMat": {"base": (0.55, 0.42, 0.05), "roughness": 0.80},
    "M_Base": {"base": (0.06, 0.06, 0.07), "roughness": 0.45},
    "M_Arm": {"base": (0.70, 0.71, 0.73), "roughness": 0.25},
    "M_Head": {"base": (0.04, 0.12, 0.40), "roughness": 0.35},
    "M_Accent": {"base": (0.80, 0.22, 0.02), "roughness": 0.55, "metallic": 0.0},
}

# Area lights just under the emissive ceiling panels (the panels are what the camera sees; the lights are invisible
# to camera rays). They live in the stage .blend but outside the export root, so they never reach the FBX.
LIGHTS = [
    {"name": "Light_A", "location": (-0.9, -0.2, 2.78), "size": (0.6, 1.2), "power_w": 35.0},
    {"name": "Light_B", "location": (0.9, -0.2, 2.78), "size": (0.6, 1.2), "power_w": 35.0},
]
BOUNCES = {"max": 6, "diffuse": 4, "glossy": 2, "transmission": 0, "transparent": 4}

# gloss (atlas alpha) from the authoring BSDF: 0 for matte, ~0.6 for a glossy cover; Unity scales its reflection term by it
GLOSS_R0, GLOSS_SPAN, GLOSS_METAL = 0.61, 0.65, 0.25


def gloss_of(roughness: float, metallic: float = 0.0) -> float:
    return float(min(1.0, max(0.0, (GLOSS_R0 - roughness) / GLOSS_SPAN + GLOSS_METAL * metallic)))


# ----------------------------------------------------------------------------- scene set-up


def apply_view(sc) -> None:
    sc.display_settings.display_device = VIEW["display_device"]
    sc.view_settings.view_transform = VIEW["view_transform"]
    sc.view_settings.look = VIEW["look"]
    sc.view_settings.exposure = VIEW["exposure"]
    sc.view_settings.gamma = VIEW["gamma"]
    sc.view_settings.use_curve_mapping = False
    sc.render.dither_intensity = 0.0          # dither would add noise to every 8-bit atlas and preview


def use_device(sc) -> dict:
    """Cycles on the first GPU backend that has a device (OptiX, CUDA, HIP, Metal, oneAPI), else CPU; env CYCLES_DEVICE
    = CPU / OPTIX / ... forces one. Sampling noise differs per backend, so the one that ran is a byte-affecting input:
    the returned record goes into every output it shaped."""
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    cpu = {"device": "CPU", "backend": "CPU", "devices": []}
    want = os.environ.get("CYCLES_DEVICE", "AUTO").upper()
    if want == "CPU":
        return cpu
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ([want] if want != "AUTO" else ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"]):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
        except (TypeError, AttributeError, RuntimeError):
            continue                                   # backend not compiled into this build / OS
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == backend
            sc.cycles.device = "GPU"
            return {"device": "GPU", "backend": backend, "devices": sorted(d.name for d in gpus)}
    return cpu


def set_bounces(sc) -> None:
    c = sc.cycles
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces = BOUNCES["max"], BOUNCES["diffuse"], BOUNCES["glossy"]
    c.transmission_bounces, c.transparent_max_bounces = BOUNCES["transmission"], BOUNCES["transparent"]


def node_tree(idb):
    """The node tree of a material / world. Blender 5 always uses nodes (setting use_nodes is deprecated there);
    4.x needs use_nodes switched on first."""
    if bpy.app.version < (5, 0, 0) and not idb.use_nodes:
        idb.use_nodes = True
    return idb.node_tree


def black_world(sc) -> None:
    """A black world: the room is closed, and no stray sky light may reach the bake or the reference."""
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    nt = node_tree(sc.world)
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        nt.nodes.clear()
        bg = nt.nodes.new("ShaderNodeBackground")
        nt.links.new(bg.outputs[0], nt.nodes.new("ShaderNodeOutputWorld").inputs["Surface"])
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)


def add_lights():
    out = []
    for spec in LIGHTS:
        ld = bpy.data.lights.new(spec["name"], "AREA")
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = spec["size"]
        ld.energy = spec["power_w"]
        lo = bpy.data.objects.new(spec["name"], ld)
        bpy.context.scene.collection.objects.link(lo)
        lo.location = spec["location"]
        lo.visible_camera = False          # the camera sees the emissive panel mesh, as the atlas does
        out.append(lo)
    return out


# ----------------------------------------------------------------------------- materials


def _fresh(name):
    old = bpy.data.materials.get(name)
    if old is not None:
        bpy.data.materials.remove(old)
    m = bpy.data.materials.new(name)
    nt = node_tree(m)
    nt.nodes.clear()
    return m, nt, nt.nodes.new("ShaderNodeOutputMaterial")


def authoring_material(name):
    spec = MATERIALS[name]
    m, nt, out = _fresh(name)
    if "emit" in spec:
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*spec["emit"], 1.0)
        em.inputs["Strength"].default_value = 1.0
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    else:
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        b.inputs["Base Color"].default_value = (*spec["base"], 1.0)
        b.inputs["Roughness"].default_value = spec["roughness"]
        b.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
        nt.links.new(b.outputs[0], out.inputs["Surface"])
    m["gloss"] = 0.0 if "emit" in spec else gloss_of(spec["roughness"], spec.get("metallic", 0.0))
    return m


def load_atlas(path):
    """The atlas for shading: sRGB colour, alpha CHANNEL_PACKED - the gloss alpha must never premultiply the colour
    (a matte texel has alpha 0)."""
    if not Path(path).is_file():
        S.fail(f"missing atlas {path} - run the bake stage")
    img = bpy.data.images.load(S.resolve(path), check_existing=True)
    img.colorspace_settings.name = "sRGB"
    img.alpha_mode = "CHANNEL_PACKED"
    return img


def unlit_material(name, img, uv_layer):
    """What the Quest draws: emission = the atlas colour (an unlit shader), no light, no reflection."""
    m, nt, out = _fresh(name)
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = uv_layer
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = img
    tx.interpolation = "Linear"
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(uv.outputs["UV"], tx.inputs["Vector"])
    nt.links.new(tx.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def flat_material(name, rgb):
    m, nt, out = _fresh(name)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*rgb, 1.0)
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def assign_all_slots(o, m) -> None:
    """Every slot of o shows m (slot count and face indices untouched - the stage file is not modified on disk)."""
    if not o.material_slots:
        o.data.materials.append(m)
    for s in o.material_slots:
        s.material = m


# ----------------------------------------------------------------------------- images


def pixels(img) -> np.ndarray:
    a = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def encode_display(sc, rgb_lin: np.ndarray, tmp_path) -> np.ndarray:
    """Linear scene values -> the 8-bit display values the previews show, through BLENDER'S OWN view transform
    (Image.save_render with the scene's colour management), not a hand-written sRGB curve. Returns k / 255 floats."""
    apply_view(sc)
    h, w = rgb_lin.shape[:2]
    img = bpy.data.images.new("__encode__", w, h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Linear Rec.709"
    px = np.ones((h, w, 4), dtype=np.float32)
    px[..., :3] = rgb_lin
    img.pixels.foreach_set(px.ravel())
    ims = sc.render.image_settings
    keep = (ims.file_format, ims.color_mode, ims.color_depth)
    ims.file_format, ims.color_mode, ims.color_depth = "PNG", "RGB", "8"
    img.save_render(S.resolve(tmp_path), scene=sc)
    ims.file_format, ims.color_mode, ims.color_depth = keep
    bpy.data.images.remove(img)
    rd = bpy.data.images.load(S.resolve(tmp_path), check_existing=False)
    rd.colorspace_settings.name = "Non-Color"            # read the stored bytes, no decode
    out = pixels(rd)[..., :3].copy()
    bpy.data.images.remove(rd)
    os.remove(tmp_path)
    return out


def save_rgba_png(path, name, rgb_display: np.ndarray, alpha: np.ndarray):
    """Write display RGB + straight alpha as an 8-bit RGBA PNG from a BYTE image. A float image would be
    premultiplied, and saving it would divide RGB by the gloss alpha (black where gloss is 0)."""
    h, w = rgb_display.shape[:2]
    px = np.empty((h, w, 4), dtype=np.float32)
    px[..., :3] = np.round(np.clip(rgb_display, 0.0, 1.0) * 255.0) / 255.0
    px[..., 3] = np.round(np.clip(alpha, 0.0, 1.0) * 255.0) / 255.0
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "sRGB"
    img.alpha_mode = "CHANNEL_PACKED"
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = S.resolve(path)
    img.file_format = "PNG"
    img.save()
    return img
