"""Run an L1 (editor Play Mode on the XR Simulator) or L2 (dev APK on the headset) scenario and
ASSERT on the app's own answers - a scenario that ends in "the screenshot looks right" asserted nothing.

    python run_scenario.py scenarios/smoke.json --prefix myapp                 # editor, DevRemote + Operator
    python run_scenario.py scenarios/smoke.json --prefix myapp --device --pkg com.Company.App
    python run_scenario.py scenarios/*.json --prefix myapp --project C:/path/to/MyQuestApp
    python run_scenario.py scenario.json --port 8732                           # DevRemote not on 8731

--prefix (or $QUEST_PREFIX) is the app's tool prefix: tools named <prefix>_* go to the app (DevRemote
in the editor, the adb command channel on a device); everything else (openxr_*, unity_*) goes through
the Meta XR Operator via op.py. --project (default: the current directory) is the Unity project, for
Temp/DevRemote.port and for where captures are written (<project>/Temp/...; copy keepers out, Unity
wipes Temp at every launch).

Exit code 0 = every wait and assert passed in every file, 1 = one failed (the step's "symptom" is
printed), 2 = usage.

Scenario file: {"name": ..., "description": ..., "steps": [...]}. Steps (op.py's batch format, plus):
    ["myapp_load_sample", {"id": "demo"}]                 call a tool, print its answer
    ["sleep", {"s": 1.0}]
    ["wait",   {"tool": "myapp_get_state", "path": "volume.ready", "equals": true, "timeout": 90}]
    ["assert", {"tool": "myapp_get_state", "path": "windows[*].title", "none_contains": "Downloading",
                "symptom": "what the user would see in the headset if this fails"}]
    ["aim",    {"hand": "right", "target": {"tool": "myapp_ui_point", "args": {"name": "OkButton"}},
                "standoff": 0.4, "offset": [0.1, -0.15, 0], "expect_hovered": "Panel_Settings"}]
               point a simulated controller's RAY (as the app reports it through <prefix>_get_input_state)
               at a Unity-world point: the target tool's answer gives "position" (+ "normal", the panel's
               viewer-facing side); the controller is held `standoff` metres out along that normal plus
               `offset` (world metres), or at an explicit "from"; the grip is corrected until the ray is
               within 0.3 degrees (the Interaction SDK builds the ray from the GRIP pose, so the aim pose
               moves nothing). expect_hovered / expect_on_ui assert what the ray then hovers.
    ["capture", {"tool": "myapp_get_input_state", "path": "right.lastPulse", "as": "pulse0"}]
               remember the first value at a path (fails when there is none), for a later comparison:
               "greater_than": {"var": "pulse0"} - "the pulse time INCREASED", not "some pulse ever happened".
    ["composite", {"eye": "left", "save": "panels_over_room"}]
               editor only: save the COLOUR composited eye image (what the runtime shows: compositor layers
               over the eye buffer) to <project>/Temp/composite-<scenario>/<save>.png
    ["layers_match", {"eye": "left", "max_fraction": 0.02, "save": "yaw60",
                      "switch": ["myapp_render_switch", {"name": "compositor"}], "symptom": "..."}]
               editor only: the composited eye image with the compositor ON vs OFF at the same pose (OFF =
               every panel in the eye buffer, on its canvas): a layer on its canvas differs only in
               sharpness. "switch" names the app tool that flips the compositor; it is called with the
               given args plus {"on": false} / {"on": true}. Needs Pillow.

Paths are dot-separated keys; "[*]" fans out over a list (or an object's values); "[key=value]" keeps
the list items whose key equals value (as text); a numeric key indexes one. Checks: equals, not_equals,
contains, none_contains (every value is a string without it), all_equal (every value equals it),
min_count, greater_than / less_than (a number, {"path": ...} into the same answer - every value beyond
every value there - or {"var": name} from a capture step, optionally {"var": name, "plus": 0.5}).

An assert or wait never passes vacuously: nothing at the path fails every check, and so does an answer
that is an {"error": ...} (AgentTools turns every exception into one) or not JSON at all - otherwise a
tool that threw would turn "no title contains Downloading" green.

Device perf (--device): the runner streams `adb logcat -s Unity VrApi` for the whole scenario and, for
every <prefix>_perf_result answer with state "done", attaches the VrApi lines between that run's
'[<prefix>-perf] BEGIN scenario=<name> ' and 'RESULT' markers (FPS, Stale, CPU/GPU level + MHz, App ms,
SF, TW, layer count). OVRPlugin's level/MHz metrics are deprecated under OpenXR, so VrApi is the source
for them. --no-logcat turns it off. All runs are written to <project>/Temp/perf-<time>.json.
"""
import base64
import glob
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # op.py, adbtools.py live next to this file

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OPT = {"prefix": None, "project": os.getcwd()}


def app_tool(name):
    return bool(OPT["prefix"]) and name.startswith(OPT["prefix"] + "_")


class EditorBackend:
    def __init__(self, port=None):
        self.port = port or self._find_port()
        self._op = None

    @staticmethod
    def _find_port():
        candidates = []
        try:
            with open(os.path.join(OPT["project"], "Temp", "DevRemote.port")) as f:
                candidates.append(int(f.read().strip()))
        except (OSError, ValueError):
            pass
        candidates += [p for p in range(8731, 8740) if p not in candidates]
        for port in candidates:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/status" % port, timeout=1.5) as r:
                    if b"isPlaying" in r.read(4096):
                        return port
            except (urllib.error.URLError, OSError, ValueError):
                continue
        raise SystemExit("no DevRemote on 8731-8739: start the editor in Play Mode (scripts/editor-play.ps1)")

    def operator(self):
        if self._op is None:
            from op import Client  # noqa: E402  (the MCP client for the Meta XR Operator)
            self._op = Client(remote_port=self.port)
        return self._op

    def call(self, tool, args):
        if app_tool(tool):
            req = urllib.request.Request("http://127.0.0.1:%d/tool/%s" % (self.port, tool),
                                         data=json.dumps(args or {}).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return parse(r.read().decode("utf-8", "replace"))
        from op import text_of  # noqa: E402
        return parse(text_of(self.operator().call(tool, args or {})))

    def raw_operator(self, tool, args):
        return self.operator().call(tool, args or {})

    def perf_attach(self, answer):
        return None

    def close(self):
        if self._op is not None:
            self._op.close()


class DeviceBackend:
    def __init__(self, pkg=None, logcat=True):
        import adbtools  # noqa: E402
        self._adb = adbtools
        if not adbtools.worn():
            print("warning: the headset is NOT worn (sys.hmt.mounted != 1) - the app is suspended and calls will time out")
        self.dev = adbtools.Device(pkg, OPT["prefix"])
        self.log = None
        if logcat:
            path = os.path.join(OPT["project"], "Temp", "scenario-logcat.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.log = adbtools.LogcatCapture(path)
            print("logcat (Unity + VrApi) -> %s" % path)

    def call(self, tool, args):
        if not app_tool(tool):
            # The file channel serves the app's own tools only; openxr_* needs the Operator layer + adb forward.
            return {"error": "%s is not an app tool (<prefix>_*); on a device without the Operator layer only "
                             "the app's tools answer" % tool}
        return self.dev.call(tool, args or {}, timeout=30.0)

    def perf_attach(self, answer):
        """VrApi numbers for the finished run in a <prefix>_perf_result answer, cut at its BEGIN/RESULT markers."""
        if self.log is None or not isinstance(answer, dict) or answer.get("state") != "done":
            return None
        scenario = answer.get("scenario") or ""
        # RESULT is logged right after the state turns "done"; give logcat a moment to flush it.
        for _ in range(10):
            window = self._adb.perf_window(self.log.lines(), scenario, OPT["prefix"])
            if window is not None:
                return self._adb.vrapi_summary(window)
            time.sleep(0.5)
        return {"error": "no '[%s-perf] BEGIN scenario=%s' ... 'RESULT' pair in logcat" % (OPT["prefix"], scenario)}

    def close(self):
        if self.log is not None:
            self.log.stop()


def parse(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def answer_error(answer):
    """Why an answer cannot be asserted on (a tool error, or not JSON), or None."""
    if isinstance(answer, dict) and "error" in answer and len(answer) <= 2:
        return "the tool answered with an error: %s" % answer.get("error")
    if not isinstance(answer, (dict, list)):
        return "the answer is not JSON: %s" % short(answer, 300)
    return None


_TOKEN = re.compile(r"\[([^\]]*)\]|([^.\[\]]+)")


def select(obj, path):
    """Values at a dot path. "[*]" (or ".*") fans out over a list's items or an object's values;
    "[key=value]" keeps the list items - or, chained, the already-selected objects - whose key equals
    value; "[n]" / ".n" indexes a list."""
    values = [obj]
    for m in _TOKEN.finditer(path):
        bracket, key = m.group(1), m.group(2)
        if key == "*":
            bracket, key = "*", None
        nxt = []
        for v in values:
            if bracket is not None:
                if bracket == "*":
                    if isinstance(v, list):
                        nxt.extend(v)
                    elif isinstance(v, dict):
                        nxt.extend(v.values())
                elif "=" in bracket:
                    k, want = bracket.split("=", 1)
                    items = v if isinstance(v, list) else [v]
                    nxt.extend(x for x in items if isinstance(x, dict) and k in x and _text(x[k]) == want)
                elif isinstance(v, list) and bracket.isdigit() and int(bracket) < len(v):
                    nxt.append(v[int(bracket)])
            elif isinstance(v, dict) and key in v:
                nxt.append(v[key])
            elif isinstance(v, list) and key.isdigit() and int(key) < len(v):
                nxt.append(v[int(key)])
        values = nxt
    return values


def _text(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return v if isinstance(v, str) else json.dumps(v)


VARS = {}


def _numbers(values):
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def check(values, spec, answer=None):
    """(ok, why) for one wait/assert spec against the selected values. Nothing selected never passes."""
    if not values:
        return False, "nothing at the path %r (renamed key? wrong filter? the tool's answer changed?)" % spec.get("path")
    if "equals" in spec:
        return all(v == spec["equals"] for v in values), "expected %r, got %r" % (spec["equals"], values)
    if "not_equals" in spec:
        return all(v != spec["not_equals"] for v in values), "expected not %r, got %r" % (spec["not_equals"], values)
    if "contains" in spec:
        return any(isinstance(v, str) and spec["contains"] in v for v in values), "no value contains %r: %r" % (spec["contains"], values)
    if "none_contains" in spec:
        bad = [v for v in values if isinstance(v, str) and spec["none_contains"] in v]
        return (len(bad) == 0), "values containing %r: %r" % (spec["none_contains"], bad)
    if "all_equal" in spec:
        # Every value equals the GIVEN one. Comparing the values only with each other passed a scene where
        # every texture was the wrong kind, as long as they were all the same wrong kind.
        return all(v == spec["all_equal"] for v in values), "expected every value %r, got %r" % (spec["all_equal"], values)
    if "min_count" in spec:
        return len(values) >= spec["min_count"], "only %d value(s) at the path" % len(values)
    for op in ("greater_than", "less_than"):
        if op in spec:
            ref = spec[op]
            if isinstance(ref, dict) and "var" in ref:
                if ref["var"] not in VARS:
                    return False, "no captured value %r (a capture step must come first)" % ref["var"]
                others = [VARS[ref["var"]] + float(ref.get("plus", 0))]
            elif isinstance(ref, dict):
                others = _numbers(select(answer, ref.get("path", "")))
                if not others:
                    return False, "nothing numeric at the comparison path %r" % ref.get("path")
            else:
                others = [ref]
            mine = _numbers(values)
            if len(mine) != len(values):
                return False, "non-numeric values at the path: %r" % values
            ok = all((a > b) if op == "greater_than" else (a < b) for a in mine for b in others)
            return ok, "%r is not %s %r" % (mine, op.replace("_", " "), others)
    return True, ""


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def _norm(v):
    n = sum(c * c for c in v) ** 0.5
    return [c / n for c in v]


def _from_to(a, b):
    a, b = _norm(a), _norm(b)
    d = sum(a[i] * b[i] for i in range(3))
    c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    if d < -0.999999:
        return [0, 1, 0, 0]
    return _norm([c[0], c[1], c[2], 1 + d])


def _xyz(v):
    return [v["x"], v["y"], v["z"]] if isinstance(v, dict) else list(v)


def aim(backend, spec):
    """(ok, why, info). Point the app's controller ray for spec["hand"] at a target (see the module doc)."""
    hand = spec.get("hand", "right")
    input_tool = spec.get("input_tool") or "%s_get_input_state" % OPT["prefix"]
    if "target" in spec:
        t = spec["target"]
        answer = backend.call(t["tool"], t.get("args"))
        err = answer_error(answer)
        if err:
            return False, "aim target: " + err, answer
        to = _xyz(answer["position"])
        normal = _xyz(answer.get("normal", {"x": 0, "y": 0, "z": -1}))
    else:
        to, normal = list(spec["at"]), [0.0, 0.0, -1.0]
    if "from" in spec:
        frm = list(spec["from"])
    else:
        side = 1.0 if hand == "right" else -1.0
        off = spec.get("offset", [0.1 * side, -0.15, 0.0])
        so = float(spec.get("standoff", 0.4))
        frm = [to[i] + normal[i] * so + off[i] for i in range(3)]
    q, err_deg, state = [0.0, 0.0, 0.0, 1.0], 180.0, {}
    for _ in range(5):
        # Unity world -> OpenXR local_floor: z negated; quaternion x and y negated. 7 decimals: a slightly
        # non-unit quaternion makes the Interaction SDK log a conversion failure every frame.
        backend.call("openxr_set_controller_pose", {
            "hand": hand, "pose_type": "grip", "base_space": "local_floor",
            "position": [frm[0], frm[1], -frm[2]],
            "orientation": [round(v, 7) for v in [-q[0], -q[1], q[2], q[3]]]})
        time.sleep(0.35)   # let the rig read the new pose before asking where the ray is
        full = backend.call(input_tool, {})
        state = full.get(hand, {}) if isinstance(full, dict) else {}
        if "rayOrigin" not in state:
            return False, "no %s ray in %s (controller not connected?)" % (hand, input_tool), full
        o, d = _xyz(state["rayOrigin"]), _xyz(state["rayDirection"])
        want = [to[i] - o[i] for i in range(3)]
        cos = sum(x * y for x, y in zip(_norm(d), _norm(want)))
        err_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
        if err_deg < 0.3:
            break
        q = _norm(_qmul(_from_to(d, want), q))
    info = {"from": [round(v, 4) for v in frm], "to": [round(v, 4) for v in to], "error_deg": round(err_deg, 3),
            "hovered": state.get("hovered"), "onUi": state.get("onUi"), "hitPoint": state.get("hitPoint")}
    if err_deg >= 1.0:
        return False, "the ray did not converge on the target (%.2f deg off)" % err_deg, info
    if "expect_hovered" in spec and spec["expect_hovered"] not in (state.get("hovered") or ""):
        return False, "the ray hovers %r, expected %r" % (state.get("hovered"), spec["expect_hovered"]), info
    if "expect_on_ui" in spec and bool(state.get("onUi")) != bool(spec["expect_on_ui"]):
        return False, "onUi is %r, expected %r" % (state.get("onUi"), spec["expect_on_ui"]), info
    return True, "", info


def short(v, limit=1500):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= limit else s[:limit] + " ...(%d chars)" % len(s)


def _composited_png(backend, eye):
    """The PNG bytes of openxr_capture_composited_image for one eye, or None."""
    raw = backend.raw_operator("openxr_capture_composited_image", {"eye": eye})
    for part in raw.get("content", []) if isinstance(raw, dict) else []:
        if part.get("type") == "image":
            return base64.b64decode(part["data"])
    return None


def _out_dir(kind, scenario_path):
    out = os.path.join(OPT["project"], "Temp", "%s-%s" % (kind, os.path.splitext(os.path.basename(scenario_path))[0]))
    os.makedirs(out, exist_ok=True)
    return out


def layers_match(backend, spec, scenario_path):
    """Is every compositor layer exactly where its canvas is? See the module doc. Editor only."""
    if not isinstance(backend, EditorBackend):
        return True, "skipped (editor only)"
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return False, "needs Pillow (pip install pillow)"
    eye = spec.get("eye", "left")
    switch_tool, switch_args = (spec.get("switch") or ["%s_render_switch" % OPT["prefix"], {"name": "compositor"}])

    def shot():
        png = _composited_png(backend, eye)
        return Image.open(io.BytesIO(png)).convert("L") if png else None

    time.sleep(float(spec.get("settle", 1.0)))
    on = shot()
    backend.call(switch_tool, dict(switch_args, on=False))
    time.sleep(0.8)
    off = shot()
    backend.call(switch_tool, dict(switch_args, on=True))
    time.sleep(1.2)
    if on is None or off is None:
        return False, "no composited image (openxr_capture_composited_image needs simulator v207+)"
    name = spec.get("save")
    if name:
        out = _out_dir("layers", scenario_path)
        on.save(os.path.join(out, name + "_on.png"))
        off.save(os.path.join(out, name + "_off.png"))
    hist = ImageChops.difference(on, off).histogram()
    total = on.size[0] * on.size[1]
    threshold = int(spec.get("threshold", 48))
    frac = sum(hist[threshold:]) / float(total)
    limit = float(spec.get("max_fraction", 0.02))
    return frac <= limit, "%s: %.3f%% of the pixels differ by > %d grey levels (limit %.2f%%)" % (
        name or eye, 100 * frac, threshold, 100 * limit)


def composite(backend, spec, scenario_path):
    """Save the colour composited eye image (editor only)."""
    if not isinstance(backend, EditorBackend):
        return True, "skipped (editor only)"
    time.sleep(float(spec.get("settle", 0.8)))
    png = _composited_png(backend, spec.get("eye", "left"))
    if not png:
        return False, "no composited image (openxr_capture_composited_image needs simulator v207+)"
    path = os.path.join(_out_dir("composite", scenario_path), spec.get("save", "composite") + ".png")
    with open(path, "wb") as f:
        f.write(png)
    return True, path


def evaluate(backend, spec):
    answer = backend.call(spec["tool"], spec.get("args"))
    err = answer_error(answer)
    if err:
        return False, err, answer
    ok, why = check(select(answer, spec["path"]), spec, answer)
    return ok, why, answer


def _symptom(spec):
    if spec.get("symptom"):
        print("     symptom: " + spec["symptom"])


def run_file(backend, path, device):
    """Run one scenario file; returns (failed, perf_runs)."""
    with open(path, encoding="utf-8") as f:
        scenario = json.load(f)
    steps = scenario["steps"] if isinstance(scenario, dict) else scenario
    name = scenario.get("name", path) if isinstance(scenario, dict) else path
    print("### %s (%s)" % (name, "device" if device else "editor"))
    failed, perf_runs = 0, []
    for n, step in enumerate(steps):
        kind, spec = step[0], (step[1] if len(step) > 1 else {})
        if kind == "sleep":
            time.sleep(float(spec.get("s", 0.5)))
            continue
        if kind == "wait":
            deadline = time.time() + float(spec.get("timeout", 60))
            ok, why, answer = False, "", None
            while time.time() < deadline:
                ok, why, answer = evaluate(backend, spec)
                if ok:
                    break
                time.sleep(float(spec.get("every", 0.5)))
            print("[%02d] WAIT %s %s -> %s" % (n, spec["tool"], spec["path"], "ok" if ok else "TIMEOUT: " + why))
            if not ok:
                failed += 1
                _symptom(spec)
                print("     answer: " + short(answer))
                break   # later steps depend on the state this wait was for
            continue
        if kind == "capture":
            answer = backend.call(spec["tool"], spec.get("args"))
            err = answer_error(answer)
            values = select(answer, spec["path"]) if not err else []
            ok = bool(values)
            if ok:
                VARS[spec["as"]] = values[0]
            print("[%02d] CAPTURE %s %s -> %s" % (n, spec["tool"], spec["path"],
                                                  ("%s = %r" % (spec["as"], values[0])) if ok else "FAIL: " + (err or "nothing at the path")))
            if not ok:
                failed += 1
                print("     answer: " + short(answer))
                break
            continue
        if kind == "aim":
            ok, why, info = aim(backend, spec)
            print("[%02d] AIM %s -> %s %s" % (n, spec.get("hand", "right"), "ok" if ok else "FAIL: " + why, short(info, 400)))
            if not ok:
                failed += 1
                _symptom(spec)
                break
            continue
        if kind == "composite":
            ok, why = composite(backend, spec, path)
            print("[%02d] %s COMPOSITE %s" % (n, "PASS" if ok else "FAIL", why))
            failed += 0 if ok else 1
            continue
        if kind == "layers_match":
            ok, why = layers_match(backend, spec, path)
            print("[%02d] %s LAYERS %s" % (n, "PASS" if ok else "FAIL", why))
            if not ok:
                failed += 1
                _symptom(spec)
            continue
        if kind == "assert":
            ok, why, answer = evaluate(backend, spec)
            print("[%02d] %s %s %s" % (n, "PASS" if ok else "FAIL", spec["tool"], spec["path"]) + ("" if ok else " - " + why))
            if not ok:
                failed += 1
                _symptom(spec)
                print("     answer: " + short(answer))
            continue
        print("[%02d] %s %s" % (n, kind, json.dumps(spec)))
        answer = backend.call(kind, spec)
        print("     " + short(answer))
        if kind == "%s_perf_result" % OPT["prefix"]:
            vrapi = backend.perf_attach(answer)
            if vrapi is not None:
                print("     vrapi: " + short(vrapi, 800))
            if isinstance(answer, dict) and answer.get("state") == "done":
                perf_runs.append({"scenario": answer.get("scenario"), "result": answer.get("result"), "vrapi": vrapi})
    print("### %s: %s" % (name, "PASS" if failed == 0 else "FAIL (%d)" % failed))
    return failed, perf_runs


def pop(argv, flag, default=None):
    if flag in argv:
        i = argv.index(flag)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def main(argv):
    argv = list(argv[1:])
    device = "--device" in argv
    no_logcat = "--no-logcat" in argv
    argv = [a for a in argv if a not in ("--device", "--no-logcat")]
    port = pop(argv, "--port")
    pkg = pop(argv, "--pkg")
    OPT["prefix"] = pop(argv, "--prefix", os.environ.get("QUEST_PREFIX"))
    OPT["project"] = os.path.abspath(pop(argv, "--project", os.getcwd()))
    files = [f for a in argv for f in (sorted(glob.glob(a)) or [a]) if f.endswith(".json")]
    if not files or not OPT["prefix"]:
        print(__doc__)
        return 2
    backend = DeviceBackend(pkg, logcat=not no_logcat) if device else EditorBackend(int(port) if port else None)
    total_failed, perf_runs = 0, []
    try:
        for path in files:
            failed, runs = run_file(backend, path, device)
            total_failed += failed
            perf_runs += runs
    finally:
        backend.close()
    if perf_runs:
        out = os.path.join(OPT["project"], "Temp", "perf-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"files": files, "device": device, "runs": perf_runs}, f, indent=2, ensure_ascii=False)
        print("### perf runs -> %s" % out)
    if len(files) > 1:
        print("### %d file(s): %s" % (len(files), "PASS" if total_failed == 0 else "FAIL (%d)" % total_failed))
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
