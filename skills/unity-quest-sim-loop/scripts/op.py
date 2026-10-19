"""One client for everything an agent can call on a running Quest app.

    python op.py list                        # tool names + one-line descriptions
    python op.py schema TOOL                 # a tool's input schema
    python op.py call TOOL '{"k": "v"}'      # call a tool, print its text, save its images
    python op.py call TOOL @args.json        # ...arguments from a file (no shell-quoting fights)
    python op.py batch steps.json            # [[tool, args], ["sleep", {"s": 0.4}], ...] in ONE session
    python op.py wait TOOL [SECONDS]         # block until TOOL is registered (app is live)

Two sources, merged:
  - Meta XR Operator (MCP over the proxy -> :8720): openxr_*, unity_*, math_*, convert_*, and the
    app's tools where it registers them with the Operator (Meta XR Core SDK 205+).
  - The app's AgentTools served by the editor's DevRemote (GET :8731/tools, POST /tool/NAME). This is
    how an app on an OLDER SDK (no MetaXROperatorExternalTool) still has its own tools. Listed with
    a "[remote]" prefix; `call` routes to whichever source has the tool (the Operator wins a tie).

Options:
    --backend URL   Operator endpoint; the proxy's default is http://127.0.0.1:8720
                    (editor Play Mode, or a headset after `adb forward tcp:8720 tcp:8720`).
    --remote-port N DevRemote port (default $DEVREMOTE_PORT, else the first of 8731-8739 that answers).
                    Remote tools are editor-only.
    --out DIR       where images returned by tools are written (default: current directory).
    --proxy PATH    the proxy exe; else $META_XR_OPERATOR_PROXY, else
                    %USERPROFILE%\\meta-xr-operator\\meta-xr-operator-mcp-proxy.exe.

Every description starting with "[OFFLINE]" means the proxy is up but no app is attached to
the backend: start editor Play Mode, or launch the dev APK on a worn headset.

Also importable: `from op import Client, text_of, pop_opt` (see aimfix.py, reload.py).
Client.call routes remote tools too, so scripts need not care where a tool lives.
"""
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# Tool descriptions carry emoji; the Windows console code page cannot print them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_PROXY = os.path.join(os.path.expanduser("~"), "meta-xr-operator", "meta-xr-operator-mcp-proxy.exe")
_ENV_PORT = os.environ.get("DEVREMOTE_PORT")
_found_port = None


def find_remote_port(preferred=None, refresh=False):
    """The DevRemote port: explicit/env first, else the first of 8731-8739 answering /status.

    DevRemote moves up from 8731 when a socket leaked by an earlier domain in the same editor still
    holds it (it also writes <project>/Temp/DevRemote.port). A leaked socket accepts and never
    answers, so each probe has a short timeout."""
    global _found_port
    if refresh:
        _found_port = None
    if preferred:
        return int(preferred)
    if _ENV_PORT:
        return int(_ENV_PORT)
    if _found_port:
        return _found_port
    for port in range(8731, 8740):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/status" % port, timeout=1.5) as r:
                if b"isPlaying" in r.read(4096):
                    _found_port = port
                    return port
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return 8731


def find_proxy(explicit=None):
    for candidate in (explicit, os.environ.get("META_XR_OPERATOR_PROXY"), DEFAULT_PROXY):
        if candidate and os.path.isfile(candidate):
            return candidate
    raise SystemExit(
        "Meta XR Operator MCP proxy not found. Copy it from "
        "<project>/Library/PackageCache/com.meta.xr.sdk.core@*/Editor/MetaXROperator/Tools~/Windows/ "
        "to " + DEFAULT_PROXY + " (see references/setup.md), or pass --proxy.")


# ---- DevRemote-served AgentTools ------------------------------------------------------------

def remote_tools(port=None):
    """{name: {"name","description","params"}} from DevRemote, or {} (editor closed, not playing, no AgentTools)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/tools" % find_remote_port(port), timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return {t["name"]: t for t in data} if isinstance(data, list) else {}


def remote_call(name, args, port=None, timeout=60):
    body = json.dumps(args or {}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d/tool/%s" % (find_remote_port(port), name),
                                 data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    return {"content": [{"type": "text", "text": text}], "isError": text.lstrip().startswith('{"error"')}


def remote_schema(tool):
    props, required = {}, []
    for p in tool.get("params", []):
        props[p["name"]] = {"type": p.get("type", "string"), "description": p.get("description", "")}
        if p.get("required"):
            required.append(p["name"])
    return {"type": "object", "properties": props, "required": required}


# ---- the Operator (MCP stdio proxy) ---------------------------------------------------------

class Client:
    def __init__(self, backend=None, proxy=None, remote_port=None):
        args = [find_proxy(proxy)] + ([backend] if backend else [])
        self.remote_port = remote_port
        self._remote = None
        self._operator_names = None
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, bufsize=0)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()
        self.id = 0
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "op.py", "version": "3"}})
        self.notify("notifications/initialized", {})

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if line:
                try:
                    self.q.put(json.loads(line))
                except ValueError:
                    pass

    def _err(self):
        for line in self.p.stderr:
            if os.environ.get("OP_DEBUG"):
                sys.stderr.write("[proxy] " + line.decode("utf-8", "replace"))

    def notify(self, method, params):
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode())

    def request(self, method, params, timeout=120):
        self.id += 1
        rid = self.id
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
        while True:
            msg = self.q.get(timeout=timeout)
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(json.dumps(msg["error"]))
                return msg["result"]

    def tools(self):
        """The Operator's tools only."""
        tools = self.request("tools/list", {})["tools"]
        self._operator_names = {t["name"] for t in tools}
        return tools

    def remote(self, refresh=False):
        if self._remote is None or refresh:
            self._remote = remote_tools(self.remote_port)
        return self._remote

    def all_tools(self):
        """Operator tools plus DevRemote tools the Operator does not have, MCP-shaped."""
        tools = self.tools()
        for name, t in self.remote(refresh=True).items():
            if name not in self._operator_names:
                tools.append({"name": name, "description": "[remote] " + t.get("description", ""),
                              "inputSchema": remote_schema(t)})
        return tools

    def call(self, tool, args=None, timeout=180):
        if tool in self.remote():
            if self._operator_names is None:
                self.tools()
            if tool not in self._operator_names:
                return remote_call(tool, args, self.remote_port, timeout=min(timeout, 60))
        return self.request("tools/call", {"name": tool, "arguments": args or {}}, timeout)

    def call_json(self, tool, args=None, timeout=180):
        """Call a tool whose text answer is JSON and parse it."""
        return json.loads(text_of(self.call(tool, args, timeout)))

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
        except Exception:
            pass


def text_of(result):
    return "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def show(result, tag, out_dir):
    for i, c in enumerate(result.get("content", [])):
        if c.get("type") == "text":
            print(c["text"])
        elif c.get("type") == "image":
            ext = ".png" if "png" in c.get("mimeType", "") else ".jpg"
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "op-%s-%d%s" % (tag, i, ext))
            with open(path, "wb") as f:
                f.write(base64.b64decode(c["data"]))
            print("[image saved] " + os.path.abspath(path))
    if result.get("isError"):
        print("[isError]")


def load_args(raw):
    if raw is None:
        return {}
    if raw.startswith("@"):
        with open(raw[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(raw)


def pop_opt(argv, name):
    if name in argv:
        i = argv.index(name)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return None


def main():
    argv = sys.argv[1:]
    backend = pop_opt(argv, "--backend")
    out_dir = pop_opt(argv, "--out") or os.environ.get("OP_OUT") or os.getcwd()
    proxy = pop_opt(argv, "--proxy")
    rp = pop_opt(argv, "--remote-port")
    remote_port = int(rp) if rp else None
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]

    if cmd == "wait":
        tool, limit = argv[1], float(argv[2]) if len(argv) > 2 else 180.0
        deadline = time.time() + limit
        while time.time() < deadline:
            if tool in remote_tools(remote_port):
                print("ready: " + tool + " (remote)")
                return 0
            c = None
            try:
                c = Client(backend, proxy, remote_port)
                live = [t for t in c.tools() if t["name"] == tool and "[OFFLINE]" not in (t.get("description") or "")]
                if live:
                    print("ready: " + tool)
                    return 0
            except Exception:
                pass
            finally:
                if c:
                    c.close()
            time.sleep(3)
        print("TIMEOUT: %s never registered - is the app playing (and the Operator layer / DevRemote up)?" % tool)
        return 1

    c = Client(backend, proxy, remote_port)
    try:
        if cmd == "list":
            tools = c.all_tools()
            for t in tools:
                print(t["name"], "-", (t.get("description") or "").replace("\n", " ")[:150])
            live = [t for t in tools if "[OFFLINE]" not in (t.get("description") or "")]
            if tools and not live:
                print("--- every tool is OFFLINE: no app is attached to the Operator backend, and DevRemote serves no tools.")
        elif cmd == "schema":
            for t in c.all_tools():
                if t["name"] == argv[1]:
                    print(json.dumps(t.get("inputSchema"), indent=1))
        elif cmd == "call":
            args = load_args(argv[2] if len(argv) > 2 else None)
            show(c.call(argv[1], args), argv[1], out_dir)
        elif cmd == "batch":
            with open(argv[1], encoding="utf-8") as f:
                steps = json.load(f)
            for n, step in enumerate(steps):
                tool, args = step[0], (step[1] if len(step) > 1 else {})
                if tool == "sleep":  # ["sleep", {"s": 0.5}] - give the app frames to react
                    time.sleep(float(args.get("s", 0.5)))
                    continue
                print("=== %s %s" % (tool, json.dumps(args)))
                try:
                    show(c.call(tool, args), "%02d-%s" % (n, tool), out_dir)
                except Exception as e:
                    print("[error] " + str(e))
        else:
            print(__doc__)
            return 2
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
