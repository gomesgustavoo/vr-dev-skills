"""bpy_stage - the plumbing every headless Blender stage script imports.

    blender -b --factory-startup --python-exit-code 2 -P 02_bake.py -- --out /abs/out [--quick]

One process per stage: a stage opens the previous stage's .blend (open_stage), does one job, saves its own
(save_stage) and exits non-zero on any failure, so the runner (run_stages.py) learns the result from the exit code,
never from a log line.

Use it from a stage script (put this folder on sys.path first - Blender ignores PYTHONPATH):

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "path/to/scripts"))
    import bpy_stage as S

    args = S.parse_args()              # argv after "--"; --out and --quick always exist
    S.check_version()                  # BLENDER_MIN_VERSION / BLENDER_PIN from the runner (or arguments)
    S.open_stage("01_build")           # <OUT>/work/01_build.blend
    ...
    S.save_stage("02_bake")            # <OUT>/work/02_bake.blend

sha256 / write_json / log / resolve / fail also work in plain CPython (no bpy), so CPython stages share them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

try:  # inside Blender
    import bpy
except ImportError:  # plain CPython: only the file helpers are usable
    bpy = None

_ARGS: argparse.Namespace | None = None


# ----------------------------------------------------------------------------- logging + failing


def script_path() -> Path | None:
    """The stage script: the argument after -P / --python in Blender, argv[0] in CPython."""
    argv = sys.argv
    for i, a in enumerate(argv[:-1]):
        if a in ("-P", "--python"):
            return Path(argv[i + 1]).resolve()
    if argv and argv[0].endswith(".py"):
        return Path(argv[0]).resolve()
    return None


def _tag() -> str:
    sp = script_path()
    return sp.stem if sp else "stage"


def log(msg: str) -> None:
    # flush: Blender's stdout is block-buffered when piped, and a log that arrives after the exit is useless
    print(f"[{_tag()}] {msg}", flush=True)


def fail(msg: str, code: int = 1):
    """Stop the stage with a non-zero exit. SystemExit(code) keeps the code; an uncaught exception would exit 2 under
    --python-exit-code 2 - and 0 without it, which is why the runner always passes that flag."""
    print(f"[{_tag()}] FAILED: {msg}", flush=True)
    raise SystemExit(code)


# ----------------------------------------------------------------------------- arguments + folders


def stage_argv() -> list[str]:
    """Arguments meant for the script: everything after "--" in Blender (Blender parses the rest itself)."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return [] if bpy is not None else sys.argv[1:]


def parse_args(parser: argparse.ArgumentParser | None = None, argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the stage arguments. --out and --quick are added when the parser does not define them, so every stage
    accepts the runner's common flags."""
    global _ARGS
    p = parser or argparse.ArgumentParser(prog=_tag())
    dests = {a.dest for a in p._actions}
    if "out" not in dests:
        p.add_argument("--out", default=None, help="output folder (default: env OUT, else <script dir>/out)")
    if "quick" not in dests:
        p.add_argument("--quick", action="store_true", help="iteration quality (low samples, small atlases)")
    _ARGS = p.parse_args(stage_argv() if argv is None else argv)
    return _ARGS


def resolve(p) -> str:
    """An absolute, normalised path string for every path handed to Blender. Blender resolves a relative output path
    against the .blend's folder ("//") or, in an unsaved file, the DRIVE ROOT (a render to "x.png" lands at C:\\x.png on
    Windows, whatever the working directory) - so a relative path never reaches the bpy API."""
    return str(Path(p).expanduser().resolve())


def out_dir() -> Path:
    """<OUT>: --out, else env OUT, else <script dir>/out - always absolute and created."""
    raw = (getattr(_ARGS, "out", None) if _ARGS is not None else None) or os.environ.get("OUT")
    if raw:
        p = Path(raw)
    else:
        sp = script_path()
        p = (sp.parent if sp else Path.cwd()) / "out"
    p = Path(resolve(p))
    p.mkdir(parents=True, exist_ok=True)
    return p


def work_dir() -> Path:
    """<OUT>/work: stage .blend files and intermediate images (never shipped)."""
    p = out_dir() / "work"
    p.mkdir(parents=True, exist_ok=True)
    return p


def stage_path(name: str) -> Path:
    return work_dir() / f"{name}.blend"


# ----------------------------------------------------------------------------- stage files (Blender only)


def _need_bpy():
    if bpy is None:
        raise RuntimeError("this helper needs Blender's bpy (run the stage with blender -b -P)")


def reset_scene() -> None:
    """An empty factory scene in metres (the first stage starts here, so no user startup file leaks in)."""
    _need_bpy()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    us = bpy.context.scene.unit_settings
    us.system, us.scale_length, us.length_unit = "METRIC", 1.0, "METERS"


def open_stage(name: str) -> Path:
    """Open <OUT>/work/<name>.blend; a missing file is a clear failure, not a fresh empty scene."""
    _need_bpy()
    p = stage_path(name)
    if not p.is_file():
        fail(f"missing stage file {p} - run the stage that writes it first")
    bpy.ops.wm.open_mainfile(filepath=resolve(p), load_ui=False)
    log(f"opened {p.name} (sha256 {sha256(p)[:12]})")
    return p


def save_stage(name: str) -> Path:
    """Save <OUT>/work/<name>.blend with paths relative to it, so the stage folder can move (copied OUT folders still
    find their images) and no host path is baked into it."""
    _need_bpy()
    p = stage_path(name)
    if bpy.data.filepath:
        # relative to the CURRENT file's folder, which is work/ for every stage after the first
        bpy.ops.file.make_paths_relative()
    bpy.context.preferences.filepaths.save_version = 0      # no <name>.blend1 backups beside the stage files
    bpy.ops.wm.save_as_mainfile(filepath=resolve(p), compress=True, relative_remap=True)
    log(f"saved {p.name} (sha256 {sha256(p)[:12]})")
    return p


# ----------------------------------------------------------------------------- version


def _vt(v) -> tuple:
    if v in (None, ""):
        return ()
    if isinstance(v, (tuple, list)):
        return tuple(int(x) for x in v)
    return tuple(int(x) for x in str(v).split("."))


def blender_version() -> tuple:
    _need_bpy()
    return tuple(bpy.app.version)


def check_version(min_version=None, pin=None, policy: str | None = None) -> tuple:
    """Refuse a Blender older than min_version; on a pin mismatch warn or refuse (policy "warn" / "refuse").
    Defaults come from the runner's environment (BLENDER_MIN_VERSION, BLENDER_PIN, BLENDER_VERSION_POLICY), so a stage
    run by hand applies the same rule. Returns the running version - record it in every output that a version could
    change (bake noise, FBX writer, UV packer)."""
    v = blender_version()
    lo = _vt(min_version if min_version is not None else os.environ.get("BLENDER_MIN_VERSION"))
    pn = _vt(pin if pin is not None else os.environ.get("BLENDER_PIN"))
    pol = (policy or os.environ.get("BLENDER_VERSION_POLICY") or "warn").lower()
    if lo and v[:len(lo)] < lo:
        fail(f"Blender {'.'.join(map(str, v))} is older than the required {'.'.join(map(str, lo))}")
    if pn and v[:len(pn)] != pn:
        msg = f"Blender {'.'.join(map(str, v))} is not the pinned {'.'.join(map(str, pn))}"
        if pol == "refuse":
            fail(msg + " (policy refuse)")
        log(f"WARNING: {msg} - outputs may differ byte for byte from the pinned build")
    return v


def blender_record() -> dict:
    """What to write into a manifest about the Blender that produced it."""
    _need_bpy()
    bh = bpy.app.build_hash
    return {"version": list(bpy.app.version), "version_string": bpy.app.version_string,
            "build_hash": bh.decode() if isinstance(bh, bytes) else str(bh)}


# ----------------------------------------------------------------------------- files


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data) -> Path:
    """Sorted keys, 2-space indent, LF newlines on every OS: the same data gives the same bytes, so a JSON can be
    hashed into a manifest and diffed between runs."""
    p = Path(resolve(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return p


def read_json(path, missing=None):
    p = Path(path)
    if not p.is_file():
        return missing
    with open(p, encoding="utf-8") as f:
        return json.load(f)
