"""Unity Editor.log (or a batchmode -logFile) -> distinct warnings / errors / exceptions.

    python logscan.py                         # %LOCALAPPDATA%\\Unity\\Editor\\Editor.log
    python logscan.py PATH                    # any Unity log
    python logscan.py PATH "MARKER"           # only what follows the LAST occurrence of MARKER
                                              # (e.g. "entering Play Mode" or your own log tag)
    python logscan.py PATH "MARKER" --info    # also Info lines: "console spam" is usually Info
                                              # (a per-frame or per-second Debug.Log), not an error

Each line: kind (ERR / WARN / EXC), how many times, the message, and <File.cs:line> of the
first frame that is probably yours. Thousands of repeats of one NullReferenceException read
as one line here, which is the point.
"""
import collections
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

with_info = "--info" in sys.argv
argv = [a for a in sys.argv[1:] if a != "--info"]
path = argv[0] if argv and argv[0] != "-" else os.path.expandvars(r"%LOCALAPPDATA%\Unity\Editor\Editor.log")
start = argv[1] if len(argv) > 1 else None
text = open(path, encoding="utf-8", errors="replace").read()
if start and start in text:
    text = text[text.rindex(start):]

entries = re.split(r"\n\(Filename: [^\n]*\)\n", text)
seen = collections.OrderedDict()
for e in entries:
    lines = [l for l in e.strip("\n").split("\n") if l.strip()]
    if not lines:
        continue
    # The message is the line just before the stack trace begins.
    idx = None
    for i, l in enumerate(lines):
        if l.startswith("UnityEngine.Debug:ExtractStackTraceNoAlloc") or l.startswith("UnityEngine.StackTraceUtility"):
            idx = i
            break
    if idx is None:
        # Exceptions and compiler errors print without the Debug trace.
        for l in lines:
            if re.search(r"(error CS\d+|Exception: |Exception\b.*: |Assertion failed)", l) and not l.startswith(" "):
                key = ("EXC", l[:220])
                seen[key] = seen.get(key, 0) + 1
        continue
    msg = lines[max(0, idx - 1)]
    trace = "\n".join(lines[idx:])
    if "Debug:LogError" in trace or "Debug:LogException" in trace or "LogErrorFormat" in trace:
        kind = "ERR"
    elif "Debug:LogWarning" in trace or "LogWarningFormat" in trace:
        kind = "WARN"
    elif with_info:
        kind = "INFO"
    else:
        continue
    origin = ""
    frames = re.findall(r"\(at ([^)]+)\)", trace)
    if frames:
        origin = frames[min(len(frames) - 1, 2)].split("/")[-1]
    key = (kind, msg[:220] + ("   <" + origin + ">" if origin else ""))
    seen[key] = seen.get(key, 0) + 1

items = list(seen.items())
if with_info:  # loudest first within each kind - that is what "spam" means
    rank = {"EXC": 0, "ERR": 1, "WARN": 2, "INFO": 3}
    items.sort(key=lambda kv: (rank[kv[0][0]], -kv[1]))
for (kind, msg), n in items:
    print("%-4s x%-5d %s" % (kind, n, msg))
print("--- %d distinct" % len(seen))
