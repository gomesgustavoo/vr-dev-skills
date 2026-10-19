"""docs/assets/blender-pipeline.svg - headless Blender stages into Unity, gated at every step."""
import sys

from common import (BLENDER, BLUE, CARD2, GREEN, LINE, LINE2, M, MUTED, ORANGE, T1, T2, T3, UNITY, Doc, wrap, write)
from svgkit import font

W, H = 1280, 452
d = Doc(W, H)
d.heading("Headless Blender to Unity, gated at every step", None)
d.t("blender -b --factory-startup --python-exit-code 2 -P stage.py   ·   one process per stage   ·   stops at the first non-zero exit",
    "jbm-400", 12.5, M, 94, T3)

SY, SH, G = 124, 152, 24
SW = (W - 2 * M - 5 * G) / 6
stages = [
    ("lu-box", T2, "build", ["Named joints, identity", "rest pose, metres: the", "contract comes first."]),
    ("lu-sun", T2, "bake", ["Cycles light baked into", "atlases, gloss in alpha."]),
    ("lu-camera", T2, "preview", ["Cycles reference, plus", "unlit and mask renders."]),
    ("lu-shield-check", T2, "validate", ["Contract, budgets and", "UVs; records the hash."]),
    ("lu-lock-keyhole", T2, "export", ["Refuses unless that", "hash passed; the FBX", "is byte-identical."]),
    ("si-unity", UNITY, "Unity", ["Same cameras, scored", "against Cycles."]),
]
for i, (ic, col, name, body) in enumerate(stages):
    x = M + i * (SW + G)
    d.card(x, SY, SW, SH, cls="anim stage st%d" % i)
    d.chip(x + 16, SY + 16, ic, col)
    d.t("%02d" % (i + 1), "jbm-600", 11.5, x + SW - 16, SY + 36, BLUE if i == 5 else MUTED, anchor="end")
    d.t(name, "inter-600", 15.5, x + 16, SY + 74, T1)
    for j, line in enumerate(body):
        assert font("inter-400").width(line, 12.5) <= SW - 36, "too wide for the card: %r" % line
        d.t(line, "inter-400", 12.5, x + 16, SY + 98 + j * 18, T3)
    if i < 5:
        d.chevron(x + SW + G / 2, SY + SH / 2, ORANGE if i < 4 else BLUE)

# proven-on strip, on the same 6-column grid
PY, PH = SY + SH + 28, 128
d.card(M, PY, W - 2 * M, PH, fill=CARD2, stroke=LINE2)
d.icon("si-blender", M + 18, PY + 16, 16, BLENDER)
d.t("PROVEN ON THE DICOMSEGVR TREATMENT ROOM", "inter-600", 11, M + 42, PY + 29, MUTED, tracking=1.3)
metrics = [("73.7k tris", ORANGE, ["machine, LOD0 only"]), ("4096² · ASTC 4x4", ORANGE, ["baked atlases"]),
           ("61 / 61", GREEN, ["validate checks, bound", "to the stage hash"]), ("SSIM 0.90", BLUE, ["machine vs Cycles,", "target 0.85"]),
           ("CIEDE2000 3.7", BLUE, ["mean colour error,", "target 6"]), ("6 / 6 shots", GREEN, ["inside the target"])]
for i, (big, col, sub) in enumerate(metrics):
    x = M + i * (SW + G) + 16
    d.t(big, "inter-600", 17, x, PY + 68, col)
    for j, line in enumerate(sub):
        d.t(line, "inter-400", 12.5, x, PY + 90 + j * 18, T3)

style = """.stage { animation: run 6s linear infinite; }
""" + "".join(".st%d { animation-delay: %.1fs; }\n" % (i, i * 0.8) for i in range(6)) + """@keyframes run { 0% { stroke: #30363D; } 4% { stroke: #DB8B44; } 14% { stroke: #DB8B44; } 22% { stroke: #30363D; } 100% { stroke: #30363D; } }"""
write(d.svg("Headless Blender to Unity, gated at every step",
            "Each stage is its own headless Blender process: build the contract, bake light into atlases, render Cycles reference "
            "previews and cameras, validate and record the stage sha256, then export a byte-identical FBX that refuses to run "
            "without a matching validation. Unity renders the same cameras and is scored against the Cycles reference.", style),
      sys.argv[1] if len(sys.argv) > 1 else "blender-pipeline.svg")
