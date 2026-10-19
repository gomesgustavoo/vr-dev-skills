"""Get edited files into the running editor and back into simulator Play Mode, via DevRemote.

    python reload.py                          # C# edits: stop -> refresh -> compile -> play
    python reload.py --wait-tool myapp_get_state     # ...and wait until the app's tools answer
    python reload.py --refresh-only           # shaders / materials / textures: import only
    python reload.py status                   # print the editor's state and recent errors
    python reload.py play | stop              # just that

Options: --port N (DevRemote; default: the first of 8731-8739 that answers), --timeout 420 (seconds).

Why stop first: a C# change recompiles and reloads the domain, and the Interaction SDK and
MRUK do not survive a reload in Play Mode (tens of thousands of NullReferenceExceptions from
one save). Why /refresh: an editor without window focus does not import files changed on
disk, so an edit made from outside simply is not there until something asks.
"""
import json
import os
import sys
import time
import subprocess
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_PINNED = None   # --port given: never move


def remote(port, route, method="GET", timeout=30):
    """The editor's answer as a dict, or None when it is busy (compiling, reloading, closed).

    `port` is ignored unless pinned with --port: DevRemote can come back on a different port after a
    domain reload (8731 held by a dying editor -> 8732, and back), so a failed call re-probes 8731-8739."""
    from op import find_remote_port
    live = _PINNED or find_remote_port()
    req = urllib.request.Request("http://127.0.0.1:%d/%s" % (live, route), method=method,
                                 data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        if not _PINNED:
            find_remote_port(refresh=True)
        return None
    if "isPlaying" not in data:  # {"error": "the editor did not answer in time (compiling?)"}
        return None
    return data


def wait_for(port, pred, what, deadline, settle=2):
    """Poll /status until pred holds `settle` times in a row (a compile can start late)."""
    hits = 0
    while time.time() < deadline:
        s = remote(port, "status", timeout=15)
        if s is not None and pred(s):
            hits += 1
            if hits >= settle:
                return s
        else:
            hits = 0
        time.sleep(2)
    raise SystemExit("TIMEOUT waiting for: " + what)


EDITOR_LOG = os.path.expandvars(r"%LOCALAPPDATA%\Unity\Editor\Editor.log")


def editor_log_size():
    try:
        return os.path.getsize(EDITOR_LOG)
    except OSError:
        return 0


def editor_log_since(offset):
    try:
        with open(EDITOR_LOG, "rb") as f:
            f.seek(offset if offset <= os.path.getsize(EDITOR_LOG) else 0)
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def editor_running():
    """False only when no Unity.exe exists at all - then waiting for DevRemote is pointless."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Unity.exe", "/NH"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return True  # can't tell: keep the normal wait
    return "Unity.exe" in out


def pop_opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def main():
    argv = sys.argv[1:]
    global _PINNED
    # Before any port probe: on Windows each closed localhost port takes ~1.5 s to refuse, and
    # the 8731-8739 scan would run several times before giving up.
    if not editor_running():
        raise SystemExit("no Unity editor is running - start one with editor-play.ps1 -Project <path>")
    from op import find_remote_port
    pinned = pop_opt(argv, "--port")
    _PINNED = int(pinned) if pinned else None
    port = find_remote_port(pinned)
    timeout = float(pop_opt(argv, "--timeout", "420"))
    wait_tool = pop_opt(argv, "--wait-tool")
    refresh_only = "--refresh-only" in argv
    argv = [a for a in argv if a != "--refresh-only"]
    cmd = argv[0] if argv else "cycle"
    deadline = time.time() + timeout

    s = remote(port, "status")
    if s is None:
        s = wait_for(port, lambda _: True, "DevRemote to answer (is the editor open, Remote Control on?)",
                     time.time() + 30, settle=1)

    if cmd == "status":
        print(json.dumps(s, indent=1))
        return 0
    if cmd in ("play", "stop"):
        remote(port, cmd, "POST")
        want = cmd == "play"
        s = wait_for(port, lambda x: x["isPlaying"] == want, cmd, deadline)
        print(("PLAYING" if want else "STOPPED"))
        return 0

    before = set(s.get("errors", []))
    if not refresh_only and s["isPlaying"]:
        remote(port, "stop", "POST")
        wait_for(port, lambda x: not x["isPlaying"], "Play Mode to stop", deadline)
        print("stopped")

    log_start = editor_log_size()
    remote(port, "refresh", "POST", timeout=60)
    s = wait_for(port, lambda x: not x["isCompiling"], "import + compile to finish", deadline, settle=3)
    print("refreshed" + ("" if refresh_only else ", compiled"))

    # Compiler errors are certain to be in Editor.log; DevRemote's error list is best-effort.
    compile_errors = sorted(set(l for l in editor_log_since(log_start) if "error CS" in l))
    if compile_errors:
        print("COMPILE ERRORS - not entering Play Mode:")
        for e in compile_errors[:20]:
            print("  " + e.splitlines()[0])
        return 1

    if not refresh_only:
        remote(port, "play", "POST")
        s = wait_for(port, lambda x: x["isPlaying"], "Play Mode to start", deadline)
        print("PLAYING")

    if wait_tool:
        from op import Client
        while time.time() < deadline:
            c = None
            try:
                c = Client(remote_port=_PINNED)
                if wait_tool in {t["name"] for t in c.all_tools() if "[OFFLINE]" not in (t.get("description") or "")}:
                    print("ready: " + wait_tool)
                    break
            except Exception:
                pass
            finally:
                if c:
                    c.close()
            time.sleep(3)
        else:
            print("TIMEOUT: %s never registered" % wait_tool)
            return 1

    s = remote(port, "status") or s
    new_errors = [e for e in s.get("errors", []) if e not in before]
    if new_errors:
        print("new errors since the reload (%d):" % len(new_errors))
        for e in new_errors[:15]:
            print("  " + e.splitlines()[0][:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
