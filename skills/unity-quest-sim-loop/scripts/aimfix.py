"""Point a simulated controller's RAY (as the app sees it) at a Unity-world target.

Why this exists: the Interaction SDK builds the controller ray from the GRIP pose plus
Meta's fixed per-controller offset, so setting the OpenXR `aim` pose does not aim it. This
sets a grip pose, asks the APP where its ray points, and rotates the grip by exactly the
rotation that takes the measured ray onto the wanted one. The offset is a constant local
rotation, so one correction is nearly exact; a second pass settles the origin shift.

    python aimfix.py HAND FROM_X FROM_Y FROM_Z TO_X TO_Y TO_Z [--tool NAME] [--backend URL]

HAND is left|right. FROM is where the controller is held and TO is the point to hit, both
in UNITY world coordinates (metres). The app must expose a tool (--tool, else $AIM_RAY_TOOL,
else <prefix>_get_input_state from AppAgentTools) whose JSON answer has, per hand:
    {"left": {"rayOrigin": {"x":..,"y":..,"z":..}, "rayDirection": {...},
              "hovered": "...", "onUi": true}, "right": {...}}
(`hovered` / `onUi` are optional and only printed). After it converges, press with
    op.py call openxr_set_controller_input '{"hand":"right","component":"Trigger","value":1,"auto_release":true}'
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from op import Client, pop_opt, text_of  # noqa: E402


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def from_to(a, b):
    a, b = norm(a), norm(b)
    d = sum(a[i] * b[i] for i in range(3))
    c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    if d < -0.999999:
        return [0, 1, 0, 0]
    return norm([c[0], c[1], c[2], 1 + d])


def unity_to_openxr_quat(q):
    # Unity is left-handed (+z forward), OpenXR right-handed (-z forward): z flips, so a
    # rotation's x and y components flip. The same map is its own inverse.
    return [-q[0], -q[1], q[2], q[3]]


def read_ray(c, tool, hand):
    state = json.loads(text_of(c.call(tool, {})))[hand]
    o, d = state["rayOrigin"], state["rayDirection"]
    return [o["x"], o["y"], o["z"]], [d["x"], d["y"], d["z"]], state


def main():
    argv = sys.argv[1:]
    tool = pop_opt(argv, "--tool") or os.environ.get("AIM_RAY_TOOL")
    if not tool:
        print("aimfix: pass --tool <prefix>_get_input_state (or set AIM_RAY_TOOL)")
        return 2
    backend = pop_opt(argv, "--backend")
    if len(argv) < 7:
        print(__doc__)
        return 2
    hand = argv[0]
    frm = [float(v) for v in argv[1:4]]
    to = [float(v) for v in argv[4:7]]
    c = Client(backend)
    try:
        q_unity = [0, 0, 0, 1]
        pose, state, err = None, {}, 180.0
        for it in range(4):
            pose = {"hand": hand, "pose_type": "grip", "position": [frm[0], frm[1], -frm[2]],
                    "orientation": [round(v, 6) for v in unity_to_openxr_quat(q_unity)],
                    "base_space": "local_floor"}
            c.call("openxr_set_controller_pose", pose)
            time.sleep(0.4)  # a few frames for the rig to read the new pose
            o, d, state = read_ray(c, tool, hand)
            want = [to[i] - o[i] for i in range(3)]
            cos = sum(x * y for x, y in zip(norm(d), norm(want)))
            err = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            print("pass %d: ray %s -> error %.2f deg, hovered '%s', onUi %s" % (
                it, [round(v, 3) for v in d], err, state.get("hovered"), state.get("onUi")))
            if err < 0.3:
                break
            q_unity = norm(qmul(from_to(d, want), q_unity))
        print(json.dumps({"grip_openxr": pose, "error_deg": round(err, 3),
                          "hovered": state.get("hovered"), "onUi": state.get("onUi")}))
        return 0 if err < 1.0 else 1
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
