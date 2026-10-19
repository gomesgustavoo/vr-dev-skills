"""Probe Meta's Horizon OS dev MCP server directly over stdio: does it start, which version, which
tools, and how fast does a docs query answer. Independent of Claude Code, so it separates "the server
is broken" from "the session didn't load it".

    python mcp_probe.py                         # npx -y metavr mcp server (the recommended packaging)
    python mcp_probe.py --server hzos           # Meta Quest Developer Hub's bundled hzos-dev-mcp.exe
    python mcp_probe.py --server both           # both, plus the tools only one of them has
    python mcp_probe.py --cmd path/to/server.exe --arg x   # any other stdio MCP server
    python mcp_probe.py --query "passthrough camera access"   # the docs query to time (default below)
    python mcp_probe.py --no-query              # tools only, no docs call
    python mcp_probe.py --markdown              # print the tool catalog as a Markdown table
    python mcp_probe.py --json out.json         # save server info + full tool schemas

Exit 0 = every probed server started and listed tools (and answered the query, when asked), 1 = not.
Python 3.10+, stdlib only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MQDH_EXE = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                        "Meta Quest Developer Hub", "resources", "bin", "hzos-dev-mcp.exe")


def server_cmd(name):
    if name == "metavr":
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx:
            raise SystemExit("npx not found: install Node.js 18+ (https://nodejs.org)")
        return [npx, "-y", "metavr", "mcp", "server"]
    if name == "hzos":
        if not os.path.isfile(MQDH_EXE):
            raise SystemExit("hzos-dev-mcp.exe not found at %s (install Meta Quest Developer Hub)" % MQDH_EXE)
        return [MQDH_EXE]
    raise SystemExit("unknown server %r" % name)


class Stdio:
    """Newline-delimited JSON-RPC over a child's stdin/stdout (the MCP stdio transport)."""

    def __init__(self, cmd):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.msgs = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.p.stdout:
            try:
                m = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue   # a server may print banners; only JSON-RPC lines matter
            if isinstance(m, dict) and "id" in m:
                with self.lock:
                    self.msgs[m["id"]] = m

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def request(self, i, method, params, timeout):
        self.send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if i in self.msgs:
                    return self.msgs.pop(i), time.time() - t0
            if self.p.poll() is not None:
                raise RuntimeError("the server exited (code %s)" % self.p.returncode)
            time.sleep(0.05)
        raise TimeoutError("%s: no answer in %.0f s" % (method, timeout))

    def close(self):
        try:
            self.p.kill()
        except OSError:
            pass


def probe(label, cmd, query, timeout):
    print("== %s: %s" % (label, " ".join(cmd)))
    rpc = Stdio(cmd)
    out = {"label": label, "cmd": cmd, "ok": False}
    try:
        init, t_init = rpc.request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                     "clientInfo": {"name": "mcp_probe", "version": "1"}}, timeout)
        rpc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        info = (init.get("result") or {}).get("serverInfo") or {}
        print("   server %s %s (initialize %.1f s)" % (info.get("name"), info.get("version"), t_init))
        listed, _ = rpc.request(2, "tools/list", {}, timeout)
        tools = (listed.get("result") or {}).get("tools") or []
        print("   %d tools" % len(tools))
        out.update(server=info, tools=tools, ok=bool(tools))
        if query and any(t["name"] == "vr_docs_search" for t in tools):
            res, t_q = rpc.request(3, "tools/call", {"name": "vr_docs_search",
                                                     "arguments": {"query": query, "max_results": 3}}, timeout)
            text = " ".join(c.get("text", "") for c in (res.get("result") or {}).get("content", []) if isinstance(c, dict))
            err = res.get("error") or (res.get("result") or {}).get("isError")
            print("   vr_docs_search %r: %s in %.1f s (%d chars)" % (query, "ERROR" if err else "ok", t_q, len(text)))
            out["query"] = {"seconds": round(t_q, 2), "ok": not err, "chars": len(text)}
            out["ok"] = out["ok"] and not err
    except Exception as e:   # report, don't trace: this is a diagnostic
        print("   FAILED: %s" % e)
        out["error"] = str(e)
    finally:
        rpc.close()
    return out


def markdown(tools):
    print("| tool | required args | summary |\n|---|---|---|")
    for t in sorted(tools, key=lambda t: t["name"]):
        req = ", ".join((t.get("inputSchema") or {}).get("required") or []) or "-"
        first = " ".join((t.get("description") or "").split()).split(". ")[0][:140]
        print("| `%s` | %s | %s |" % (t["name"], req, first.replace("|", "/")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--server", choices=["metavr", "hzos", "both"], default="metavr")
    ap.add_argument("--cmd", help="probe this stdio server instead")
    ap.add_argument("--arg", action="append", default=[], help="argument for --cmd (repeatable)")
    ap.add_argument("--query", default="passthrough camera access permissions")
    ap.add_argument("--no-query", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0, help="per request; the first npx run downloads the package")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    query = None if a.no_query else a.query
    if a.cmd:
        targets = [("custom", [a.cmd] + a.arg)]
    else:
        names = ["metavr", "hzos"] if a.server == "both" else [a.server]
        targets = [(n, server_cmd(n)) for n in names]
    results = [probe(label, cmd, query, a.timeout) for label, cmd in targets]
    if len(results) == 2 and all(r.get("tools") for r in results):
        s0 = {t["name"] for t in results[0]["tools"]}
        s1 = {t["name"] for t in results[1]["tools"]}
        print("== only in %s: %s" % (results[0]["label"], ", ".join(sorted(s0 - s1)) or "-"))
        print("== only in %s: %s" % (results[1]["label"], ", ".join(sorted(s1 - s0)) or "-"))
    if a.markdown and results and results[0].get("tools"):
        markdown(results[0]["tools"])
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1, ensure_ascii=False)
        print("== wrote %s" % a.json)
    ok = all(r["ok"] for r in results)
    print("== %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
