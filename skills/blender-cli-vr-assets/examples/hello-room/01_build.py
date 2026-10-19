"""01_build.py - build the hello-room scene from the contract: a 4 x 4 x 2.8 m room and a jointed machine.

    blender -b --factory-startup --python-exit-code 2 -P 01_build.py -- --out <OUT>

Geometry is written in WORLD coordinates (bmesh) and shifted so each mesh's origin sits on its joint; every object is
parented with an identity parent-inverse and a pure translation, so the rest pose is identity everywhere. Colour
regions are separate primitives that are never welded: each stays its own UV island, so a colour edge is an island
edge and stays crisp in the bake. The room faces INWARD (it is seen from inside; Unity culls back faces).
Output: <OUT>/work/01_build.blend
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True       # no __pycache__ inside the skill folder
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "scripts")]     # contract/lookdev + the skill's bpy_stage

import bpy_stage as S  # noqa: E402
import contract as K  # noqa: E402
import lookdev as L  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402


# ----------------------------------------------------------------------------- bmesh primitives (world coordinates)


def quad(bm, centre, normal, u, half_u, half_v, mat):
    """A rectangle facing `normal`: half extents along u and v = normal x u (so u x v points along the normal)."""
    c, n, u = Vector(centre), Vector(normal).normalized(), Vector(u).normalized()
    v = n.cross(u).normalized()
    U, V = u * half_u, v * half_v
    f = bm.faces.new([bm.verts.new(c + p) for p in (-U - V, U - V, U + V, -U + V)])
    f.material_index = mat
    return f


def box(bm, mn, mx, mat):
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0)
    mn, mx = Vector(mn), Vector(mx)
    bmesh.ops.scale(tmp, vec=mx - mn, verts=tmp.verts)
    bmesh.ops.translate(tmp, vec=(mn + mx) * 0.5, verts=tmp.verts)
    for f in tmp.faces:
        f.material_index = mat
    _merge(bm, tmp)


def cylinder(bm, centre, axis, radius, depth, mat, segments=24):
    tmp = bmesh.new()
    bmesh.ops.create_cone(tmp, cap_ends=True, cap_tris=False, segments=segments, radius1=radius, radius2=radius,
                          depth=depth)
    rot = Vector((0, 0, 1)).rotation_difference(Vector(axis).normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(tmp, matrix=Matrix.Translation(Vector(centre)) @ rot, verts=tmp.verts)
    for f in tmp.faces:
        f.material_index = mat
        f.smooth = len(f.verts) == 4            # smooth sides, flat caps
    _merge(bm, tmp)


def _merge(bm, other):
    me = bpy.data.meshes.new("_merge")
    other.to_mesh(me)
    other.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


# ----------------------------------------------------------------------------- objects


def rest_world(name):
    return Vector(K.node(name)[3])


def place(o, name):
    """Parent o per the contract with identity rotation / scale / parent-inverse and a pure translation."""
    parent = K.node(name)[1]
    o.parent = bpy.data.objects[parent] if parent else None
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.rotation_mode = "XYZ"
    o.rotation_euler = (0.0, 0.0, 0.0)
    o.scale = (1.0, 1.0, 1.0)
    o.location = rest_world(name) - (rest_world(parent) if parent else Vector())


def empty(name, kind):
    o = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(o)
    o.empty_display_type = {"joint": "ARROWS", "marker": "SPHERE"}.get(kind, "PLAIN_AXES")
    o.empty_display_size = 0.15 if kind == "joint" else 0.05
    place(o, name)
    return o


def mesh(name, build, mats):
    bm = bmesh.new()
    build(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.transform(Matrix.Translation(-rest_world(name)))      # origin on the contract node, geometry unchanged
    for m in mats:
        me.materials.append(bpy.data.materials[m])
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    place(o, name)
    return o


def build_room(bm):
    w, d, h = K.ROOM_SIZE
    x, y = w / 2, d / 2
    floor, wall, ceil, panel, door, mat = range(6)
    quad(bm, (0, 0, 0), (0, 0, 1), (1, 0, 0), x, y, floor)
    quad(bm, (0, 0, h), (0, 0, -1), (1, 0, 0), x, y, ceil)
    quad(bm, (0, y, h / 2), (0, -1, 0), (1, 0, 0), x, h / 2, wall)
    quad(bm, (0, -y, h / 2), (0, 1, 0), (1, 0, 0), x, h / 2, wall)
    quad(bm, (x, 0, h / 2), (-1, 0, 0), (0, 1, 0), y, h / 2, wall)
    quad(bm, (-x, 0, h / 2), (1, 0, 0), (0, 1, 0), y, h / 2, wall)
    for spec in L.LIGHTS:                                     # the diffusers the camera sees, 5 mm under the ceiling
        lx, ly, _ = spec["location"]
        quad(bm, (lx, ly, h - 0.005), (0, 0, -1), (1, 0, 0), spec["size"][0] / 2, spec["size"][1] / 2, panel)
    quad(bm, (x - 0.005, -0.95, 1.05), (-1, 0, 0), (0, 1, 0), 0.45, 1.05, door)
    quad(bm, (0, 0.75, 0.003), (0, 0, 1), (1, 0, 0), 0.6, 0.65, mat)


def build_base(bm):
    box(bm, (-0.25, 0.65, 0.0), (0.25, 1.15, 1.0), 0)
    box(bm, (-0.06, 0.84, 1.0), (0.06, 0.96, 1.055), 0)     # neck up to the arm's hub (5 mm gap: they move)


def build_arm(bm):
    p = rest_world("ArmPivot")
    cylinder(bm, p, (1, 0, 0), 0.09, 0.20, 0)                # the hub on the pivot axis
    box(bm, (-0.08, -0.12, 1.08), (0.08, 0.86, 1.22), 0)   # the beam toward the room centre


def build_head(bm):
    head, accent, neck = range(3)
    p = rest_world("HeadPivot")
    cylinder(bm, (p.x, p.y, 1.05), (0, 0, 1), 0.05, 0.06, neck)
    box(bm, (-0.17, p.y - 0.17, 0.74), (0.17, p.y + 0.17, 1.02), head)
    cylinder(bm, (p.x, p.y, 0.715), (0, 0, 1), 0.07, 0.05, accent)


def main():
    S.parse_args()
    v = S.check_version()
    S.reset_scene()
    for name in L.MATERIALS:
        L.authoring_material(name)
    for name, _parent, kind, _pos in K.HIERARCHY:             # contract order = parents before children
        if kind == "mesh":
            build, mats = {"Room": (build_room, ["M_Floor", "M_Wall", "M_Ceiling", "M_Panel", "M_Door", "M_FloorMat"]),
                           "Base": (build_base, ["M_Base"]),
                           "Arm": (build_arm, ["M_Arm"]),
                           "Head": (build_head, ["M_Head", "M_Accent", "M_Arm"])}[name]
            o = mesh(name, build, mats)
        else:
            o = empty(name, kind)
        if o.name != name:
            S.fail(f"{name} was created as {o.name!r} (a name clash) - Unity finds joints by exact name")
    L.add_lights()
    sc = bpy.context.scene
    L.apply_view(sc)
    sc["pipeline"] = "hello-room"
    S.log(f"built {len(K.HIERARCHY)} contract nodes + {len(L.LIGHTS)} lights on Blender {'.'.join(map(str, v))}; "
          f"tris {sum(len(p.vertices) - 2 for o in bpy.data.objects if o.type == 'MESH' for p in o.data.polygons)}")
    S.save_stage("01_build")


if __name__ == "__main__":
    main()
