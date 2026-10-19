"""contract.py - the hello-room contract: frames, units, names, hierarchy, joints, budgets, shots.

Every stage imports this module and nothing else defines these numbers, so the build, the bake, the gates, the export
and the Unity side cannot drift apart. Plain Python (no bpy): the Unity-side tooling may read it too.

Frames
------
Blender (authoring, every stage but the export): right-handed, Z up, metres.
    X = right (seen from the door wall), Y = toward the machine, Z = up; the root on the floor at the room centre.
Unity (what export.py writes, the ONE axis conversion in the pipeline): left-handed, Y up, metres.
    unity (x, y, z) = (X, Z, Y)  - the matrix M below (det -1: the handedness flip lives in this one place).
Rotations: a right-handed Blender rotation by +t about axis a is, in Unity, Quaternion.AngleAxis(-t, M a).
Units: 1 Blender unit = 1 m = 1 Unity unit (FBX UnitScaleFactor 100 + Unity useFileScale).

Joint contract
--------------
Joints are empties; meshes hang under joints, never joints under meshes (re-modelling a mesh must not move a joint).
Every node rests at identity rotation and unit scale with a pure-translation offset, so "rest" means the same thing in
Blender, in the FBX and in Unity, and the runtime animates a joint by setting localRotation = AngleAxis(-t, axis_unity).
Unity finds the joints by NAME - names are part of the contract (Blender's ".001" suffixes break it).
"""

# Blender (X, Y, Z) -> Unity (x, y, z)
M_BLENDER_TO_UNITY = ((1, 0, 0), (0, 0, 1), (0, 1, 0))

ROOT = "HelloRoom"
ROOM_SIZE = (4.0, 4.0, 2.8)          # X width, Y depth, Z height (m)

# name, parent, kind, rest position (Blender world, m). kind: group / joint (empties), mesh, marker (an empty Unity
# reads, e.g. a tool tip).
HIERARCHY = [
    ("HelloRoom", None, "group", (0.0, 0.0, 0.0)),
    ("Room", "HelloRoom", "mesh", (0.0, 0.0, 0.0)),
    ("Machine", "HelloRoom", "group", (0.0, 0.9, 0.0)),
    ("Base", "Machine", "mesh", (0.0, 0.9, 0.0)),
    ("ArmPivot", "Machine", "joint", (0.0, 0.9, 1.15)),
    ("Arm", "ArmPivot", "mesh", (0.0, 0.9, 1.15)),
    ("HeadPivot", "ArmPivot", "joint", (0.0, -0.05, 1.15)),
    ("Head", "HeadPivot", "mesh", (0.0, -0.05, 1.15)),
    ("HeadTip", "HeadPivot", "marker", (0.0, -0.05, 0.69)),
]

# joint -> rotation axis (Blender, unit vector) and travel (deg). ArmPivot tilts the arm, HeadPivot spins the head
# about the arm's long axis.
JOINTS = {
    "ArmPivot": {"axis": (1.0, 0.0, 0.0), "range_deg": (-45.0, 45.0)},
    "HeadPivot": {"axis": (0.0, 1.0, 0.0), "range_deg": (-180.0, 180.0)},
}

# atlas / mask groups. "room" and "static" never move; "moving" parts bake at rest, each seeing only the static scene
# and itself (02_bake.py "casters").
GROUPS = {"Room": "room", "Base": "static", "Arm": "moving", "Head": "moving"}
CASTERS = {"Arm": ("Arm",), "Head": ("Head",)}      # moving part -> the moving parts visible in its bake
MASK_RGB = {"room": (1.0, 0.0, 0.0), "static": (0.0, 1.0, 0.0), "moving": (0.0, 0.0, 1.0)}

# relative linear texel density (1 = the room's): the machine is what users look at closely
TEXEL_WEIGHT = {"Base": 1.6, "Arm": 2.0, "Head": 2.5}

# budgets (the gates): the example is tiny; a real Quest room sets these from measured GPU time
TRIS_MAX = 2000
ATLAS_SIZE = 1024
ATLAS_SIZE_QUICK = 512
ATLAS_MAX = 4096
UV_STRETCH_MAX = 1.25        # area-weighted p95 sigma_max / sigma_min; the headless aspect bug shows 4 - 16
UV_MARGIN_PX = 4

# files
FINAL_STAGE = "02_bake"      # the stage validate checks and export ships
ATLAS_FILE = "HelloRoom_atlas.png"
FBX_FILE = "HelloRoom.fbx"
UV_LAYER = "UVAtlas"

# preview shots: name, camera location, target (Blender world, m), lens (mm, 36 mm sensor, horizontal fit)
SHOTS = [
    ("01_room", (-1.62, -1.78, 1.68), (0.25, 0.55, 0.85), 14.0),
    ("02_machine", (1.05, -0.95, 1.55), (0.0, 0.45, 0.95), 22.0),
]
RESOLUTION = (960, 600)
RESOLUTION_QUICK = (640, 400)


def to_unity(v):
    """Blender vector -> Unity vector (positions and axes alike)."""
    return [float(sum(M_BLENDER_TO_UNITY[r][c] * v[c] for c in range(3))) for r in range(3)]


def node(name):
    return next(h for h in HIERARCHY if h[0] == name)
