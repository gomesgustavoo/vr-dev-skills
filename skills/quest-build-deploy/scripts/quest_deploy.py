"""Sideload, launch and verify a Quest app over adb, and turn one headset session into a readout.

    python quest_deploy.py devices                                   # serials, model, OS build, worn?
    python quest_deploy.py deploy Build/App.apk --pkg com.Company.App     # install -r -g, launch, check it stays up
    python quest_deploy.py deploy Build/App.apk --project C:/path/to/MyQuestApp   # package id from ProjectSettings
    python quest_deploy.py launch --pkg com.Company.App
    python quest_deploy.py check  --pkg com.Company.App              # running? any crash in logcat?
    python quest_deploy.py worn                                      # sys.hmt.mounted (1 = on a head)
    python quest_deploy.py readout --pkg com.Company.App --minutes 3 --relaunch --questions questions.json
    python quest_deploy.py summary readout.txt --questions questions.json

Options: --serial S (when several devices are connected; default: the only one), --out FILE (readout).

readout: waits until the headset is WORN (off a head Horizon OS suspends the app and nothing would
print), grows and clears the log buffer, optionally force-stops and relaunches the app, streams
`logcat -v time -s Unity:V VrApi:V AgenticXR:V AndroidRuntime:E DEBUG:V` for --minutes (or until the
file <out>.stop appears), then prints a summary: for each QUESTION the last line that answers it, every
distinct problem line (exceptions, FATAL, SIGABRT, FAIL) with a count, and a VrApi summary (fps, App
GPU ms, stale frames, CPU/GPU level and MHz, SF, TW, layer count). Make the app log one self-report line
per question at startup and on key events; then no one has to describe what they see.

questions.json: [["render path", "\\\\[Render\\\\] path"], ["eye buffer", "eye buffer \\\\d+x\\\\d+"], ...]
(a label and a Python regex per row). Without it, generic startup questions are used.

adb: $ADB, else PATH, else $ANDROID_HOME/platform-tools. Python 3.10+, stdlib only.
Why direct adb and not an MCP install: a ~300 MB APK installs over USB in seconds this way; MCP
installers have hung on large APKs.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_adb():
    if os.environ.get("ADB"):
        return os.environ["ADB"]
    found = shutil.which("adb")
    if found:
        return found
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(var)
        exe = os.path.join(root or "", "platform-tools", "adb.exe" if os.name == "nt" else "adb")
        if root and os.path.isfile(exe):
            return exe
    raise SystemExit("adb not found: set ADB, put platform-tools on PATH, or set ANDROID_HOME "
                     "(the Horizon OS MCP's metavr_software_paths lists where it is)")


ADB = None
SERIAL = None


def adb(*args, timeout=120):
    cmd = [ADB] + (["-s", SERIAL] if SERIAL else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode


def device_rows():
    out = subprocess.run([ADB, "devices", "-l"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1], " ".join(parts[2:])))
    return rows


def pick_serial(explicit):
    if explicit:
        return explicit
    ready = [r for r in device_rows() if r[1] == "device"]
    if len(ready) == 1:
        return ready[0][0]
    if not ready:
        states = ", ".join("%s=%s" % (r[0], r[1]) for r in device_rows()) or "none"
        raise SystemExit("no device in state 'device' (%s). 'unauthorized' = accept the USB debugging prompt "
                         "INSIDE the headset (only the wearer can)." % states)
    raise SystemExit("several devices: pass --serial (%s)" % ", ".join(r[0] for r in ready))


def worn():
    return adb("shell", "getprop", "sys.hmt.mounted")[0].strip() == "1"


def package_from_project(project):
    """applicationIdentifier for Android from ProjectSettings/ProjectSettings.asset."""
    path = os.path.join(project, "ProjectSettings", "ProjectSettings.asset")
    text = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"applicationIdentifier:\s*\n((?:\s+\S+:.*\n)+)", text)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.strip().partition(":")
            if k == "Android" and v.strip():
                return v.strip()
    raise SystemExit("no Android applicationIdentifier in %s - pass --pkg" % path)


def pidof(pkg):
    return adb("shell", "pidof", pkg)[0].strip()


def launch(pkg):
    adb("shell", "am", "force-stop", pkg)
    out, err, code = adb("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    if "Events injected: 1" not in out:
        raise SystemExit("launch failed (is %s installed? does it have a LAUNCHER activity?): %s %s" % (pkg, out, err))
    print("launched %s" % pkg)


CRASH = re.compile(r"FATAL EXCEPTION|AndroidRuntime.*(?:FATAL|Process: )|Fatal signal|SIGABRT|SIGSEGV|"
                   r"\bF DEBUG\b|backtrace:|Abort message|ANR in ", re.I)


def check(pkg, wait_s=12.0):
    """(running, crash_lines): the app has a pid after wait_s, and what logcat says about crashes."""
    # Wait the whole window, then look: a crash in the first seconds after launch is the common case,
    # and a pid seen once at 1 s proves nothing about 10 s.
    time.sleep(wait_s)
    pid = pidof(pkg)
    log, _, _ = adb("logcat", "-d", "-t", "2000", timeout=60)
    crash = [l for l in log.splitlines() if CRASH.search(l) and (pkg in l or "DEBUG" in l or "AndroidRuntime" in l)]
    return bool(pid), pid, crash[-25:]


def cmd_devices(_a):
    rows = device_rows()
    if not rows:
        print("no devices (USB cable / developer mode / `adb kill-server`?)")
        return 1
    global SERIAL
    for serial, state, extra in rows:
        SERIAL = serial
        line = "%-20s %-12s %s" % (serial, state, extra)
        if state == "device":
            model = adb("shell", "getprop", "ro.product.model")[0]
            build = adb("shell", "getprop", "ro.build.display.id")[0]
            line += " | %s | %s | %s" % (model, build, "WORN" if worn() else "not worn")
        print(line)
    return 0


def cmd_deploy(a):
    apk = os.path.abspath(a.apk)
    if not os.path.isfile(apk):
        raise SystemExit("no APK at %s" % apk)
    mb = os.path.getsize(apk) / (1024 * 1024)
    print("installing %s (%.1f MB) on %s" % (apk, mb, SERIAL))
    t0 = time.time()
    out, err, code = adb("install", "-r", "-g", apk, timeout=900)
    print("  %s (%.1f s)" % ((out.splitlines() or [err])[-1], time.time() - t0))
    if code != 0 or "Success" not in out:
        print(err or out)
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in (out + err):
            print("  the installed copy is signed with another key: uninstalling it DELETES its data - ask the user first")
        return 1
    if a.no_launch:
        return 0
    adb("logcat", "-c")
    launch(a.pkg)
    return report_check(a.pkg)


def report_check(pkg):
    running, pid, crash = check(pkg)
    print("running: %s%s" % ("yes, pid " + pid if running else "NO", "" if worn() else
                            "  (headset NOT worn: Horizon OS may suspend or stop an immersive app off-head)"))
    for l in crash:
        print("  crash: " + l[:240])
    return 0 if running and not crash else 1


def cmd_launch(a):
    launch(a.pkg)
    return report_check(a.pkg)


def cmd_check(a):
    return report_check(a.pkg)


def cmd_worn(_a):
    w = worn()
    print("worn" if w else "NOT worn (sys.hmt.mounted != 1): the app is suspended, captures are empty")
    return 0 if w else 1


# ---------------------------------------------------------------- readout

DEFAULT_QUESTIONS = [
    ("device", r"Device Model|SystemInfo"),
    ("unity version", r"Built from|Unity Engine Version|Initialize engine version"),
    ("openxr runtime", r"OpenXR Runtime|XR_KHR|OpenXR (?:Loader|Instance)"),
    ("operator", r"AgenticXR|METAX_operator|operator tools"),
    ("first scene", r"Loaded scene|SceneManager|scene loaded"),
]
PROBLEMS = re.compile(r"Exception|NullReference|\bFAIL\b|Assertion failed|SIGABRT|SIGSEGV|FATAL|ANR in", re.I)
_VRAPI = {
    "fps": re.compile(r"FPS=(\d+)/(\d+)"), "stale": re.compile(r"Stale=(\d+)"),
    "levels": re.compile(r"CPU\d*/GPU=(\d+)/(\d+),(\d+)/(\d+)MHz"), "app": re.compile(r"App=([\d.]+)ms"),
    "gpu": re.compile(r"GPU%=([\d.]+)"), "sf": re.compile(r"(?:^|[,\s])SF=([\d.]+)"),
    "tw": re.compile(r"(?:^|[,\s])TW=([\d.]+)ms"), "lcnt": re.compile(r"LCnt=(\d+)"),
}


def vrapi(lines):
    acc = {k: [] for k in ("fps", "stale", "cpuL", "gpuL", "cpuMHz", "gpuMHz", "app", "gpu", "sf", "tw", "lcnt")}
    for line in lines:
        if "VrApi" not in line or "FPS=" not in line:
            continue
        for key, rx in _VRAPI.items():
            m = rx.search(line)
            if not m:
                continue
            if key == "levels":
                acc["cpuL"].append(int(m.group(1))); acc["gpuL"].append(int(m.group(2)))
                acc["cpuMHz"].append(int(m.group(3))); acc["gpuMHz"].append(int(m.group(4)))
            elif key in ("fps", "stale", "lcnt"):
                acc[key].append(int(m.group(1)))
            else:
                acc[key].append(float(m.group(1)))

    def p50(v):
        return sorted(v)[len(v) // 2] if v else None

    def mode(v):
        return max(set(v), key=v.count) if v else None

    return {"seconds": len(acc["fps"]), "fpsMin": min(acc["fps"]) if acc["fps"] else None, "fpsP50": p50(acc["fps"]),
            "staleSum": sum(acc["stale"]) if acc["stale"] else None, "appMsP50": p50(acc["app"]),
            "appMsMax": max(acc["app"]) if acc["app"] else None, "gpuUtilP50": p50(acc["gpu"]),
            "cpuLevel": mode(acc["cpuL"]), "gpuLevel": mode(acc["gpuL"]), "cpuMHzP50": p50(acc["cpuMHz"]),
            "gpuMHzP50": p50(acc["gpuMHz"]), "sfP50": p50(acc["sf"]), "twMsP50": p50(acc["tw"]),
            "layersMax": max(acc["lcnt"]) if acc["lcnt"] else None}


def load_questions(path):
    if not path:
        return DEFAULT_QUESTIONS
    with open(path, encoding="utf-8") as f:
        return [tuple(row) for row in json.load(f)]


def summarise(lines, questions):
    print("== questions (last answer each)")
    for name, pat in questions:
        rx = re.compile(pat)
        hits = [l for l in lines if rx.search(l)]
        print("  %-20s %s" % (name, hits[-1].strip()[:220] if hits else "-- no line"))
    counts = {}
    for l in lines:
        if PROBLEMS.search(l):
            key = re.sub(r"^\S+ \S+\s+", "", l.strip())[:200]   # drop the timestamp so repeats collapse
            counts[key] = counts.get(key, 0) + 1
    print("== problems (%d distinct, %d lines)" % (len(counts), sum(counts.values())))
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1])[:30]:
        print("  %5dx %s" % (n, key))
    print("== VrApi (whole session)")
    print("  " + json.dumps(vrapi(lines)))


def cmd_readout(a):
    out = os.path.abspath(a.out)
    print("waiting for the headset to be worn (sys.hmt.mounted = 1)...")
    while not worn():
        time.sleep(3)
    print("worn.")
    adb("logcat", "-G", "32M")   # the default ring buffer has dropped whole captures
    adb("logcat", "-c")
    if a.relaunch:
        launch(a.pkg)
    stop_file = out + ".stop"
    if os.path.exists(stop_file):
        os.remove(stop_file)
    print("streaming logcat for %.1f min -> %s (create %s to stop early)" % (a.minutes, out, stop_file))
    with open(out, "w", encoding="utf-8", errors="replace") as f:
        cmd = [ADB] + (["-s", SERIAL] if SERIAL else []) + [
            "logcat", "-v", "time", "-s", "Unity:V", "VrApi:V", "AgenticXR:V", "AndroidRuntime:E", "DEBUG:V"]
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.DEVNULL)
        deadline = time.time() + a.minutes * 60
        try:
            while time.time() < deadline and not os.path.exists(stop_file):
                if proc.poll() is not None:
                    print("logcat exited (%s): USB dropped? `adb devices` before trusting this file" % proc.returncode)
                    break
                time.sleep(1)
        finally:
            if proc.poll() is None:
                proc.terminate()
    with open(out, encoding="utf-8", errors="replace") as f:
        summarise(f.read().splitlines(), load_questions(a.questions))
    return 0


def cmd_summary(a):
    with open(a.file, encoding="utf-8", errors="replace") as f:
        summarise(f.read().splitlines(), load_questions(a.questions))
    return 0


def main():
    global ADB, SERIAL
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serial")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_pkg(p):
        p.add_argument("--pkg", default=os.environ.get("QUEST_PKG"))
        p.add_argument("--project", help="Unity project: read the package id from ProjectSettings")
        return p

    sub.add_parser("devices")
    sub.add_parser("worn")
    p = with_pkg(sub.add_parser("deploy"))
    p.add_argument("apk")
    p.add_argument("--no-launch", action="store_true")
    with_pkg(sub.add_parser("launch"))
    with_pkg(sub.add_parser("check"))
    p = with_pkg(sub.add_parser("readout"))
    p.add_argument("--minutes", type=float, default=3.0)
    p.add_argument("--relaunch", action="store_true")
    p.add_argument("--questions")
    p.add_argument("--out", default="readout.txt")
    p = sub.add_parser("summary")
    p.add_argument("file")
    p.add_argument("--questions")
    a = ap.parse_args()

    ADB = find_adb()
    if a.cmd == "devices":
        return cmd_devices(a)
    if a.cmd != "summary":
        SERIAL = pick_serial(a.serial)
    if hasattr(a, "pkg") and not a.pkg:
        if a.project:
            a.pkg = package_from_project(a.project)
        elif a.cmd != "worn":
            raise SystemExit("pass --pkg <android package id> or --project <unity project> (or set QUEST_PKG)")
    return {"worn": cmd_worn, "deploy": cmd_deploy, "launch": cmd_launch, "check": cmd_check,
            "readout": cmd_readout, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
