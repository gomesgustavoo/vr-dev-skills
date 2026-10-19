"""run_stages.py - run a headless Blender pipeline: one process per stage, blocking on each exit.

    python run_stages.py [pipeline.json] [--blender PATH] [--python PATH] [--out DIR]
                         [--from STAGE] [--to STAGE] [--only a,b] [--quick] [--list] [--dry-run]

pipeline.json (paths relative to its own folder):
    {
      "name": "hello-room",
      "out": "out",                                      # default output folder (env OUT / --out override)
      "blender": {"min_version": "4.2", "pin": "5.2.2", "policy": "warn"},
      "stages": [
        {"name": "build", "script": "01_build.py", "args": ["--seed", "1"]},
        {"name": "bake", "script": "02_bake.py", "quick_args": ["--quick"]},
        {"name": "fidelity", "python": true, "script": "../../scripts/fidelity.py",
         "args": ["--ref", "{out}/previews", "--test", "{out}/previews_unlit"]}
      ]
    }

A Blender stage runs as
    <blender> -b --factory-startup --python-exit-code 2 -P <script> -- --out <OUT> <args> [<quick_args>]
  * -b: no UI; --factory-startup: no user preferences, add-ons or startup file (the same scene on every host);
  * --python-exit-code 2: an uncaught exception exits 2 (without it Blender exits 0 and the pipeline marches on);
  * a "python": true stage runs in CPython (--python / env PIPELINE_PY / this interpreter) - for tools that need
    packages Blender's Python lacks (scikit-image for fidelity.py).
Placeholders in args: {out} (the absolute output folder), {here} (the pipeline.json folder).
--quick appends each stage's quick_args (default ["--quick"] for Blender stages, nothing for CPython stages).
Every stage gets env OUT, BLENDER_MIN_VERSION, BLENDER_PIN, BLENDER_VERSION_POLICY; its output is echoed and teed to
<OUT>/logs/<stage>.log. The runner stops at the first non-zero exit and exits with that code - the exit code is the
result; nothing here waits for or greps a log line.

Blender: --blender, else env BLENDER, else `blender` on PATH, else the default macOS app location.
Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAC_DEFAULT = "/Applications/Blender.app/Contents/MacOS/Blender"


def find_blender(cli: str | None) -> str:
    for cand in (cli, os.environ.get("BLENDER"), shutil.which("blender")):
        if cand and Path(cand).is_file():
            return str(Path(cand).resolve())
        if cand and shutil.which(cand):
            return shutil.which(cand)
    if sys.platform == "darwin" and Path(MAC_DEFAULT).is_file():
        return MAC_DEFAULT
    sys.exit("run_stages: no Blender found - pass --blender PATH or set env BLENDER (a portable Blender is best: "
             "the exact build is part of the pipeline's inputs)")


def blender_version(blender: str) -> tuple:
    """`blender --version` -> (major, minor, patch); about a second, and it catches a wrong binary before any stage."""
    try:
        out = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.exit(f"run_stages: cannot run {blender} --version: {e}")
    m = re.search(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        sys.exit(f"run_stages: could not read a version from `{blender} --version`:\n{out[:400]}")
    return tuple(int(x) for x in m.groups(default="0"))


def vtuple(s) -> tuple:
    return tuple(int(x) for x in str(s).split(".")) if s else ()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a headless Blender stage pipeline (see the module docstring).")
    ap.add_argument("pipeline", nargs="?", default="pipeline.json")
    ap.add_argument("--blender", default=None, help="Blender executable (default: env BLENDER, then PATH)")
    ap.add_argument("--python", default=None, help="CPython for python stages (default: env PIPELINE_PY, then this one)")
    ap.add_argument("--out", default=None, help="output folder (default: env OUT, then the pipeline's \"out\")")
    ap.add_argument("--from", dest="start", default=None, help="first stage to run")
    ap.add_argument("--to", dest="stop", default=None, help="last stage to run")
    ap.add_argument("--only", default=None, help="comma-separated stages to run (in pipeline order)")
    ap.add_argument("--quick", action="store_true", help="append every stage's quick_args (iteration builds)")
    ap.add_argument("--list", action="store_true", help="list the stages and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    a = ap.parse_args()
    # a console code page that cannot print a character from Blender's log must not kill the run
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    pj = Path(a.pipeline).expanduser().resolve()
    if not pj.is_file():
        sys.exit(f"run_stages: {pj} not found")
    spec = json.loads(pj.read_text(encoding="utf-8"))
    here = pj.parent
    stages = spec.get("stages", [])
    names = [s["name"] for s in stages]
    if len(set(names)) != len(names):
        sys.exit(f"run_stages: duplicate stage names in {pj.name}: {names}")
    if a.list:
        for s in stages:
            print(f"{s['name']:12s} {'python' if s.get('python') else 'blender'}  {s['script']}")
        return 0

    for flag, val in (("--from", a.start), ("--to", a.stop)):
        if val is not None and val not in names:
            sys.exit(f"run_stages: {flag} {val!r} is not a stage ({', '.join(names)})")
    i0 = names.index(a.start) if a.start else 0
    i1 = names.index(a.stop) if a.stop else len(names) - 1
    run = stages[i0:i1 + 1]
    if a.only:
        want = [x.strip() for x in a.only.split(",") if x.strip()]
        unknown = [x for x in want if x not in names]
        if unknown:
            sys.exit(f"run_stages: --only names unknown stages {unknown}")
        run = [s for s in stages if s["name"] in want]
    if not run:
        sys.exit("run_stages: nothing to run (check --from / --to)")

    # the output folder: absolute, so every stage (and every Blender path API) sees the same place
    out_raw = a.out or os.environ.get("OUT")
    out = Path(out_raw).expanduser().resolve() if out_raw else (here / spec.get("out", "out")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(exist_ok=True)

    bl_spec = spec.get("blender", {})
    need_blender = any(not s.get("python") for s in run)
    blender = find_blender(a.blender) if need_blender else None
    py = a.python or os.environ.get("PIPELINE_PY") or sys.executable
    env = dict(os.environ, OUT=str(out))
    env["BLENDER_MIN_VERSION"] = str(bl_spec.get("min_version") or "")
    env["BLENDER_PIN"] = str(bl_spec.get("pin") or "")
    env["BLENDER_VERSION_POLICY"] = str(bl_spec.get("policy") or "warn")
    if blender:
        v = blender_version(blender)
        lo, pin = vtuple(bl_spec.get("min_version")), vtuple(bl_spec.get("pin"))
        print(f"=== blender {'.'.join(map(str, v))}: {blender}", flush=True)
        if lo and v[:len(lo)] < lo:
            sys.exit(f"run_stages: Blender {'.'.join(map(str, v))} < required {bl_spec['min_version']}")
        if pin and v[:len(pin)] != pin:
            msg = f"Blender {'.'.join(map(str, v))} is not the pinned {bl_spec['pin']}"
            if env["BLENDER_VERSION_POLICY"] == "refuse":
                sys.exit(f"run_stages: {msg} (policy refuse)")
            print(f"=== WARNING: {msg}; outputs may differ byte for byte", flush=True)
    print(f"=== out: {out}", flush=True)

    def subst(x: str) -> str:
        return x.replace("{out}", str(out)).replace("{here}", str(here))

    t_all = time.time()
    for s in run:
        script = (here / subst(s["script"])).resolve()
        if not script.is_file():
            print(f"=== {s['name']}: script {script} not found", flush=True)
            return 1
        args = [subst(x) for x in s.get("args", [])]
        if a.quick:
            args += [subst(x) for x in s.get("quick_args", [] if s.get("python") else ["--quick"])]
        if s.get("python"):
            cmd = [py, str(script)] + args
        else:
            cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "2", "-P", str(script), "--"]
            cmd += (["--out", str(out)] if s.get("pass_out", True) else []) + args
        print(f"=== {s['name']}: {subprocess.list2cmdline(cmd) if os.name == 'nt' else ' '.join(cmd)}", flush=True)
        if a.dry_run:
            continue
        t0 = time.time()
        rc = run_tee(cmd, env, out / "logs" / f"{s['name']}.log", cwd=here)
        print(f"=== {s['name']}: exit {rc} in {time.time() - t0:.1f} s", flush=True)
        if rc != 0:
            print(f"=== pipeline FAILED at {s['name']} (exit {rc}; log {out / 'logs' / (s['name'] + '.log')})",
                  flush=True)
            return rc
    if a.dry_run:
        print(f"=== dry run: {len(run)} stage(s), nothing executed", flush=True)
        return 0
    print(f"=== pipeline OK: {len(run)} stage(s) in {time.time() - t_all:.1f} s", flush=True)
    return 0


def run_tee(cmd, env, log_path: Path, cwd: Path) -> int:
    """Run cmd to completion, echoing its merged stdout/stderr and writing it to log_path. Returns the exit code."""
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=str(cwd),
                                 text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            print(f"=== cannot start {cmd[0]}: {e}", flush=True)
            return 127
        try:
            for line in p.stdout:
                sys.stdout.write(line)
                log.write(line)
            sys.stdout.flush()
            return p.wait()
        except KeyboardInterrupt:
            p.terminate()
            p.wait()
            return 130


if __name__ == "__main__":
    sys.exit(main())
