"""Call a Quest app's agent tools on a headset over adb - the device side of the dev loop.

A DEVELOPMENT build carries the app's tools (assets/AgentTools.cs) and the file command channel
(assets/DevCommandChannel.cs). Use it when there is no Meta XR Operator to attach to on the
device: a Meta XR SDK older than 205, or a dev build made without the Operator layer
(assets/OperatorLayerExclusion.cs, references/device.md).

    python adbtools.py --pkg com.Company.App --prefix myapp call myapp_get_state
    python adbtools.py call myapp_load_sample "{\"id\": \"demo\"}"      # with QUEST_PKG / QUEST_PREFIX set
    python adbtools.py call myapp_do_thing @args.json                 # arguments from a file: no quoting fights
    python adbtools.py batch steps.json      # [[tool, args], ["sleep", {"s": 1}], ...]
    python adbtools.py worn                  # is the headset on a head? (sys.hmt.mounted)
    python adbtools.py time                  # the headset's clock, to cut logcat windows

Or from Python:  from adbtools import Device;  d = Device("com.Company.App", "myapp");  d.call("myapp_get_state")
Defaults come from QUEST_PKG / QUEST_PREFIX; adb from $ADB, PATH, or $ANDROID_HOME/platform-tools.

Things this handles that each cost time once:
  - the command is pushed under a temporary name and renamed with `mv`, so the app never
    reads a half-written file;
  - answers are read with `adb shell cat` and matched by id HERE: `adb shell` re-parses its
    arguments in the device shell, so a quoted grep pattern arrives without its quotes and
    matches nothing;
  - the call object is written id-first, so an app that parses loosely never takes an
    argument named "id" for the call id;
  - adb output is decoded as UTF-8 (UI text carries ellipses and curly quotes; cp1252 throws);
  - device paths go to adb.exe directly, never through Git Bash, which rewrites /sdcard/...
    into a Windows path (if you must call adb from bash, set MSYS_NO_PATHCONV=1);
  - an unworn headset suspends the app and every call then times out: `worn` says so first.

Perf runs: LogcatCapture / perf_window / vrapi_summary cut the VrApi lines at the app's
'[<prefix>-perf] BEGIN scenario=<name> ' / 'RESULT' markers (run_scenario.py --device uses them).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def _find_adb():
    """$ADB, else adb on PATH, else the platform-tools of $ANDROID_HOME / $ANDROID_SDK_ROOT."""
    if os.environ.get("ADB"):
        return os.environ["ADB"]
    found = shutil.which("adb")
    if found:
        return found
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(var)
        if root:
            exe = os.path.join(root, "platform-tools", "adb.exe" if os.name == "nt" else "adb")
            if os.path.isfile(exe):
                return exe
    return "adb"   # the first call then fails with a clear "not found"


ADB = _find_adb()

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def adb(*args, timeout=60):
    r = subprocess.run([ADB, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode


def worn():
    return adb("shell", "getprop", "sys.hmt.mounted")[0].strip() == "1"


class Device:
    def __init__(self, pkg=None, prefix=None):
        self.pkg = pkg or os.environ.get("QUEST_PKG")
        self.prefix = prefix or os.environ.get("QUEST_PREFIX")
        if not self.pkg or not self.prefix:
            raise SystemExit("adbtools: pass --pkg <android package> --prefix <tool prefix> "
                             "(or set QUEST_PKG / QUEST_PREFIX)")
        self.dir = "/sdcard/Android/data/%s/files" % self.pkg

    def device_time(self):
        """The headset's clock, HH:MM:SS - to cut logcat into windows around scripted steps."""
        return adb("shell", "date", "+%H:%M:%S")[0]

    def call(self, tool, args=None, timeout=15.0):
        cid = uuid.uuid4().hex[:12]
        payload = json.dumps({"id": cid, "tool": tool, "args": args or {}})   # id first for older dev builds (module doc)
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        cmd = "%s/%s-cmd.json" % (self.dir, self.prefix)
        try:
            out, err, code = adb("push", path, cmd + ".tmp")
            if code != 0:
                raise RuntimeError("adb push failed: " + err)
            adb("shell", "mv", cmd + ".tmp", cmd)
        finally:
            os.remove(path)

        deadline = time.time() + timeout
        key = '"id":"%s"' % cid
        while time.time() < deadline:
            out, _, _ = adb("shell", "cat", "%s/%s-out.jsonl" % (self.dir, self.prefix))
            for line in reversed(out.splitlines()):
                if key in line:
                    try:
                        return json.loads(line).get("result")
                    except ValueError:
                        return line
            time.sleep(0.25)
        raise TimeoutError("%s: no answer in %.0f s - is the DEV build running and in front, and is the headset worn "
                           "(sys.hmt.mounted=%s)?" % (tool, timeout, adb("shell", "getprop", "sys.hmt.mounted")[0]))


class LogcatCapture:
    """`adb logcat -v time -s Unity:V VrApi:V` into a file, from a cleared buffer, for the life of the
    object. The perf numbers the app cannot read itself come from here: OVRPlugin's CPU/GPU level and
    MHz metrics are deprecated (OVRP 1.68) and unsupported under the OpenXR loader, while VrApi still
    prints FPS / Stale / CPU+GPU level and MHz / App ms once a second."""

    def __init__(self, path):
        self.path = path
        adb("logcat", "-c")
        self._file = open(path, "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen([ADB, "logcat", "-v", "time", "-s", "Unity:V", "VrApi:V"],
                                      stdout=self._file, stderr=subprocess.DEVNULL)

    def lines(self):
        self._file.flush()
        with open(self.path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()

    def stop(self):
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._file.close()


def perf_window(lines, scenario, prefix=None):
    """The logcat lines between the LAST '[<prefix>-perf] BEGIN scenario=<scenario> ' and the RESULT that
    follows it, or None while that RESULT has not arrived."""
    tag = "[%s-perf]" % (prefix or os.environ.get("QUEST_PREFIX") or "app")
    begin_key = "%s BEGIN scenario=%s " % (tag, scenario)
    begin = None
    for i, line in enumerate(lines):
        if begin_key in line:
            begin = i
    if begin is None:
        return None
    for j in range(begin + 1, len(lines)):
        if tag + " RESULT" in lines[j] or tag + " FAILED" in lines[j]:
            return lines[begin + 1:j]
    return None


_VRAPI = {
    "fps": re.compile(r"FPS=(\d+)/(\d+)"),
    "stale": re.compile(r"Stale=(\d+)"),
    "levels": re.compile(r"CPU\d*/GPU=(\d+)/(\d+),(\d+)/(\d+)MHz"),
    "app": re.compile(r"App=([\d.]+)ms"),
    "gpuPct": re.compile(r"GPU%=([\d.]+)"),
    "sf": re.compile(r"(?:^|[,\s])SF=([\d.]+)"),   # not DSF=
    "tw": re.compile(r"(?:^|[,\s])TW=([\d.]+)ms"),   # the compositor's TimeWarp time
    "lcnt": re.compile(r"LCnt=(\d+)"),                # the compositor layer count (passthrough + panels + eye buffer)
}


def vrapi_summary(lines):
    """Per-second VrApi lines -> {lines, fps min/p50, staleSum, cpu/gpu level (most common), MHz p50, App p50/max ms}."""
    fps, stale, cpu_l, gpu_l, cpu_mhz, gpu_mhz, app, gpu_pct, sf, tw, lcnt = [], [], [], [], [], [], [], [], [], [], []
    for line in lines:
        if "VrApi" not in line or "FPS=" not in line:
            continue
        m = _VRAPI["fps"].search(line)
        if m:
            fps.append(int(m.group(1)))
        m = _VRAPI["stale"].search(line)
        if m:
            stale.append(int(m.group(1)))
        m = _VRAPI["levels"].search(line)
        if m:
            cpu_l.append(int(m.group(1))); gpu_l.append(int(m.group(2)))
            cpu_mhz.append(int(m.group(3))); gpu_mhz.append(int(m.group(4)))
        m = _VRAPI["app"].search(line)
        if m:
            app.append(float(m.group(1)))
        m = _VRAPI["gpuPct"].search(line)
        if m:
            gpu_pct.append(float(m.group(1)))
        m = _VRAPI["sf"].search(line)
        if m:
            sf.append(float(m.group(1)))
        m = _VRAPI["tw"].search(line)
        if m:
            tw.append(float(m.group(1)))
        m = _VRAPI["lcnt"].search(line)
        if m:
            lcnt.append(int(m.group(1)))

    def p50(a):
        return sorted(a)[len(a) // 2] if a else None

    def mode(a):
        return max(set(a), key=a.count) if a else None

    return {"lines": len(fps), "fpsMin": min(fps) if fps else None, "fpsP50": p50(fps),
            "staleSum": sum(stale) if stale else None, "cpuLevel": mode(cpu_l), "gpuLevel": mode(gpu_l),
            "cpuMHzP50": p50(cpu_mhz), "gpuMHzP50": p50(gpu_mhz), "appMsP50": p50(app),
            "appMsMax": max(app) if app else None, "gpuUtilP50": p50(gpu_pct), "sfP50": p50(sf),
            "twMsP50": p50(tw), "layersMode": mode(lcnt), "layersMax": max(lcnt) if lcnt else None}


def run_batch(dev, steps):
    """op.py's batch format over adb: [[tool, args], ["sleep", {"s": 0.5}], ...]."""
    for step in steps:
        tool, args = step[0], (step[1] if len(step) > 1 else {})
        if tool == "sleep":
            time.sleep(float(args.get("s", 0.5)))
            continue
        print("=== %s %s" % (tool, json.dumps(args)))
        try:
            print(json.dumps(dev.call(tool, args), indent=2, ensure_ascii=False))
        except Exception as e:
            print("[error] " + str(e))


def load_args(raw):
    if raw.startswith("@"):
        with open(raw[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(raw)


def main(argv):
    pkg = prefix = None
    rest = []
    it = iter(argv[1:])
    for a in it:
        if a == "--pkg":
            pkg = next(it)
        elif a == "--prefix":
            prefix = next(it)
        else:
            rest.append(a)
    if rest[:1] == ["worn"]:
        print("worn" if worn() else "NOT worn (sys.hmt.mounted != 1): the app is suspended")
        return 0
    if rest[:1] == ["time"]:
        print(Device(pkg, prefix).device_time())
        return 0
    if len(rest) >= 2 and rest[0] == "batch":
        run_batch(Device(pkg, prefix), load_args("@" + rest[1] if not rest[1].startswith("@") else rest[1]))
        return 0
    if len(rest) < 2 or rest[0] != "call":
        print(__doc__)
        return 2
    args = load_args(rest[2]) if len(rest) > 2 else {}
    print(json.dumps(Device(pkg, prefix).call(rest[1], args), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
