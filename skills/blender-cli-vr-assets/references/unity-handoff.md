# Unity handoff: axes, units, the joint contract, import settings

The goal: the FBX imports into Unity with **identity rotation and unit scale on every node**, joints exactly where
the contract says, 1 unit = 1 m, and the runtime animates a joint with one line
(`joint.localRotation = Quaternion.AngleAxis(-t, axisUnity)`). Everything below serves that.

## Frames

| Space | Handedness | Up | Notes |
|---|---|---|---|
| Blender (authoring) | right | +Z | metres; author in the frame that makes the domain easy (a room frame, an IEC frame...) |
| FBX as written | right | +Y | the plain "Y-up / Maya" axis system: `UpAxis 1 +1`, `FrontAxis 2 +1`, `CoordAxis 0 +1` |
| Unity | left | +Y | the importer negates FBX x to change handedness |

With Blender (X right, Y forward, Z up) the contract is usually **Unity (x, y, z) = (X, Z, Y)**: the matrix
`M = [[1,0,0],[0,0,1],[0,1,0]]`, det -1 - the handedness flip, stated once.

### Do the conversion in the data, in the export stage only

```python
P = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))   # FBX = (-X, Z, Y), det +1 (no mirror in Blender)
for o in root.children_recursive:
    o.location = (P @ o.location.to_4d()).to_3d()                 # every joint offset in FBX axes
    if o.type == "MESH" and o.data.name not in done:
        o.data.transform(P); done.add(o.data.name)                # every vertex (shared meshes once)
root.matrix_world = axis_conversion(to_forward="-Z", to_up="Y").to_4x4().inverted()   # written as identity
bpy.ops.export_scene.fbx(..., axis_forward="-Z", axis_up="Y", bake_space_transform=False)
```

Unity then negates x: `(-(-X), Z, Y) = (X, Z, Y)`. The exporter applies its axis matrix only to root-level objects;
children are written as their parent-relative locals, which is why the offsets must already be in FBX axes.
Do this in memory in the export stage and never save the result: every other stage (bake, preview, validate,
clearance) keeps working in the authoring frame, and the conversion exists in exactly one place.

**Why not `bake_space_transform=True` ("Apply Transform")**: it converts mesh data and root objects but leaves child
joint offsets in Blender axes - every joint below the root lands in the wrong place. The treatment-room export caught this
only because the FBX was parsed back and re-checked in Unity coordinates. **Why not leave the conversion to Unity**
(no data conversion, Unity's root -90 deg X rotation or `bakeAxisConversion`): the joints then rotate in a rotated
frame, the rest rotations are not identity, and every runtime angle needs a correction.

### The rotation-sign rule

A right-handed Blender rotation by `+t` about axis `a` is, in Unity, `Quaternion.AngleAxis(-t, M a)`.
Why: Unity's `AngleAxis` applies the ordinary rotation formula to the raw coordinates; conjugating a rotation by a
reflection (`M`, det -1) reverses its angle. Check with one case: Blender +90 deg about +Z turns forward (+Y) to
left (-X); Unity +90 deg about +y turns forward (+z) to right (+x) - so Blender +90 about Z is Unity -90 about y.
Put the rule in the manifest next to every joint axis, and gate it numerically (the example's validate poses each
joint +30 deg and checks `M (posed child) == M pivot + R(-30, M a) M (child - pivot)`).

## Units

`apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL", global_scale=1` writes the data in metres with
`UnitScaleFactor 100` (FBX's reference unit is the centimetre). Unity with **`useFileScale` on and `globalScale` 1**
turns that into 1 unit per metre and unit scale on every transform. Other combinations put 100 or 0.01 into the
transforms (or into a hidden file scale), and a joint offset read from the manifest no longer matches the imported
`localPosition`. Read `UnitScaleFactor` back from the file and gate it.

## The joint contract (template)

```python
# contract.py - imported by every stage; nothing else defines these
M_BLENDER_TO_UNITY = ((1, 0, 0), (0, 0, 1), (0, 1, 0))
HIERARCHY = [   # name, parent, kind (group / joint / mesh / marker), rest position (Blender world, m)
    ("Asset", None, "group", (0, 0, 0)),             # root on the floor, where Unity places the prefab
    ("Static", "Asset", "mesh", (0, 0, 0)),
    ("Pivot1", "Asset", "joint", (0, 0.9, 1.15)),    # joints are empties
    ("Part1", "Pivot1", "mesh", (0, 0.9, 1.15)),     # meshes hang under joints, origin on the joint
    ("Pivot2", "Pivot1", "joint", (0, -0.05, 1.15)), # joints chain to joints, never under a mesh
    ("Part2", "Pivot2", "mesh", (0, -0.05, 1.15)),
    ("Tip", "Pivot2", "marker", (0, -0.05, 0.69)),   # points the runtime needs (a tool tip, a sensor)
]
JOINTS = {"Pivot1": {"axis": (1, 0, 0), "range_deg": (-45, 45)}, "Pivot2": {"axis": (0, 1, 0), "range_deg": (-180, 180)}}
```

Rules, each with the failure it prevents:
* **Identity rest rotation, unit scale, identity parent-inverse, zero delta transforms on every node** - otherwise
  "rest" differs between Blender, the FBX and Unity, and a joint angle from the manifest is off by the hidden rotation.
  Parent in scripts with `o.parent = p; o.matrix_parent_inverse = Identity; o.location = world - parent_world`
  (interactive Ctrl-P writes a parent-inverse matrix).
* **Joints by exact name** - Unity code finds them with `transform.Find`; Blender silently renames a clash to
  `Name.001`. Fail the build stage when `obj.name != wanted`, and gate exact names in the FBX read-back.
* **Meshes under joints, never joints under meshes** - re-modelling or re-origining a mesh must not move a joint.
* **One axis conversion, in export** - see above.
* **Manifest per joint**: parent, `unity_local_position`, `unity_rest_world`, `axis_unity`, range, the sign rule;
  per mesh: tris, its atlas. Unity-side builders read this instead of re-deriving numbers.

## Read the FBX back (in the export stage)

Parse the written file (`io_scene_fbx.parse_fbx`, wrapped by `scripts/fbx_deterministic.py: read_fbx`) and check in
Unity coordinates (`unity = (-x, y, z) * UnitScaleFactor / 100`):
* axis system `((1, 1), (2, 1), (0, 1))`, `UnitScaleFactor` 100;
* every model: `Lcl Rotation` 0, `Lcl Scaling` 1, no `PreRotation` / `PostRotation` / `Geometric*`;
* exactly the contract names; each node's world position == `M . contract position` (0.1 mm);
* a few domain facts (floor at y = 0, the machine on +z, a part on the correct side) - cheap, and they catch a sign
  error that a pure round-trip check would reproduce consistently.
Exit non-zero on any miss. This is where the treatment room's child-offset bug was found.

## Unity import checklist

Model (`ModelImporter`, set it from an `AssetPostprocessor` or the scene builder so it is code, not clicks):

| Setting | Value | Why |
|---|---|---|
| `globalScale` / `useFileScale` | 1 / true | 1 unit per metre with unit scale transforms (UnitScaleFactor 100) |
| `bakeAxisConversion` | false | the FBX is already Y-up as data |
| `importNormals` | Import | keep Blender's normals (weighted / custom normals, flat faces flat); Calculate re-smooths |
| `importTangents` | None (unlit) / CalculateMikk (normal maps) | tangents cost memory an unlit atlas never reads |
| `materialImportMode` | None | assign your own unlit / atlas material in code; imported materials drift |
| `importCameras` / `importLights` / `importBlendShapes` | false | not part of the asset |
| `animationType` | None | joints are driven by code, not clips |
| `isReadable` (Read/Write) | false | halves mesh memory; if CPU code needs triangles (collision probes), copy them in the builder at edit time |
| `meshCompression` | Off unless measured | compression quantises vertex positions; check it against your clearance tolerances |
| `preserveHierarchy` | true for a stable root | with false, a single FBX root becomes the prefab root itself |
| `weldVertices` | default | welding cannot merge across UV seams, so separate colour islands stay separate |

Atlas texture (`TextureImporter`):

| Setting | Value | Why |
|---|---|---|
| `sRGBTexture` | true | the atlas holds display values; the GPU decodes to linear and the framebuffer re-encodes - an unlit shader reproduces the preview pixel |
| `alphaSource` | FromInput | alpha is data (gloss), not coverage |
| `alphaIsTransparency` | **false** | true rewrites the RGB of alpha-0 texels (colour dilation) - with gloss in alpha that is every matte texel |
| `mipmapEnabled` | true | VR minification shimmer otherwise |
| `anisoLevel` | 8 for floors / walls / long surfaces | grazing angles in a room blur without it |
| `wrapMode` | Clamp | atlases never tile |
| `maxTextureSize` | the atlas size (<= 4096) | a smaller max silently downsamples the bake |
| Android override | ASTC 4x4 (8 bpp) for hero atlases, 6x6 (3.56 bpp) to save memory | see the budget table in SKILL.md |

Unlit drawing must not be tone-mapped: with post-processing / HDR tonemapping on the camera the screen value is no
longer the atlas value (that is why the reference renders with Blender's Standard view, not AgX / Filmic).

## Matching the Blender shots in Unity

`cameras.json` gives, per shot, `positionUnity`, `targetUnity`, `upUnity`, `verticalFovDeg`, `aspect`, `resolution`,
`nearClipM` and the pose. In Unity: `cam.transform.SetPositionAndRotation(pos, Quaternion.LookRotation(target - pos, up))`,
`cam.fieldOfView = verticalFovDeg` (Unity's FOV is vertical; Blender's lens with a horizontal sensor fit is not), render
into a RenderTexture of `resolution`, read it back, save PNGs named like the shots, then run
`scripts/fidelity.py --ref <out>/previews --test <unity-frames> --mask <out>/previews_mask --resize-test ...`.
The treatment room (the worked example in SKILL.md) did exactly this: Unity frames vs the Cycles previews, machine
region mean SSIM 0.898 and mean CIEDE2000 3.72, all 6 shots inside the >= 0.85 / <= 6 target.
