"""Aim the simulated head at a UI panel and snapshot it framed tightly - the way to READ a
panel's text in the simulator.

    python panelshot.py --prefix myapp Panel:Settings settings --click TabAdvanced
    python panelshot.py --prefix myapp Panel:Tools tools

It needs two app tools (add them to your project's AgentTools file):
  <prefix>_list_panels  -> {"panels": [{"name", "open", "worldPosition": {x,y,z},
                                        "worldWidthM", "worldHeightM", ...}]}
  <prefix>_snapshot     {width, height, fov, name} -> {"path": ...}
and, for --click, <prefix>_click_widget {panel, widget}.

What it does, and why:
  - reads the head position (openxr_get_head_pose) and turns the head to face the panel's
    centre: a yaw about +Y and a pitch about +X in the OpenXR frame (-Z forward, so looking
    RIGHT is a NEGATIVE rotation about +Y), composed yaw * pitch, normalised - an unnormalised
    quaternion floods the log with ISDK "Quaternion To Matrix conversion failed";
  - sets the vertical fov from the panel's world height at its distance (+8%), and the image
    aspect from its width, so the panel fills the frame at a resolution text can be read at;
  - re-queries the panel list on every call: turning the head can trigger the app's own
    "workspace strayed out of view" re-layout, which moves the panels.
  Moving the head re-seeds the controllers (operator.md): restore their poses afterwards if a
  later step needs them. And a snapshot renders the EYE BUFFER - a panel drawn as a compositor
  layer (OVROverlayCanvas) is a hole in it; switch the app's compositor path off first, or use
  openxr_capture_composited_image.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time

OP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "op.py")


def call(tool, args=None):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(args or {}, f)
    try:
        r = subprocess.run([sys.executable, OP, "call", tool, "@" + path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    finally:
        os.remove(path)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return r.stdout


def look_at(eye, target):
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    yaw = math.atan2(dx, dz)                        # Unity: +x right, +z forward
    pitch = math.atan2(dy, math.hypot(dx, dz))
    th, ph = -yaw, pitch
    qy = (0.0, math.sin(th / 2), 0.0, math.cos(th / 2))
    qx = (math.sin(ph / 2), 0.0, 0.0, math.cos(ph / 2))
    x1, y1, z1, w1 = qy
    x2, y2, z2, w2 = qx
    q = [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
         w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
         w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
         w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q], math.sqrt(dx * dx + dy * dy + dz * dz)


def shoot(prefix, panel, name, px=1800, margin=0.08):
    panels = call(prefix + "_list_panels")["panels"]
    p = next((x for x in panels if x["name"] == panel), None)
    if p is None:
        raise SystemExit("no panel %r (have: %s)" % (panel, ", ".join(x["name"] for x in panels)))
    if not p.get("open", True):
        raise SystemExit("panel %r is closed" % panel)
    head = call("openxr_get_head_pose")
    eye_xr = head["pose"]["position"]
    eye = (eye_xr[0], eye_xr[1], -eye_xr[2])        # OpenXR local_floor -> Unity: negate z
    c = p["worldPosition"]
    q, dist = look_at(eye, (c["x"], c["y"], c["z"]))
    call("openxr_set_head_pose", {"position": list(eye_xr), "orientation": q})
    time.sleep(1.2)
    h = p["worldHeightM"] * (1 + margin)
    w = p["worldWidthM"] * (1 + margin)
    fov = math.degrees(2 * math.atan(h / 2 / dist))
    return call(prefix + "_snapshot", {"width": int(px * w / h), "height": px, "fov": fov, "name": name})


def main(argv):
    prefix = os.environ.get("QUEST_PREFIX", "")
    args = argv[1:]
    if args[:1] == ["--prefix"]:
        prefix, args = args[1], args[2:]
    if len(args) < 2 or not prefix:
        print(__doc__)
        return 2
    panel, name = args[0], args[1]
    if "--click" in args:
        for widget in args[args.index("--click") + 1:]:
            print("click", widget, str(call(prefix + "_click_widget", {"panel": panel, "widget": widget}))[:120])
            time.sleep(0.4)
    print(shoot(prefix, panel, name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
