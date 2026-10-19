"""docs/assets/loops.svg - the four verification loops on a log time axis."""
import math
import sys

from common import BLUE, CARD, GREEN, LINE, LINE2, M, MUTED, T1, T2, T3, Doc, wrap, write

W, H = 1280, 480
d = Doc(W, H)
d.heading("Four loops, cheapest first", "Climb only as far as the question needs. Most bugs are found, fixed and gated in L1.")

X_NAME, X_BAR, X_PROVES = M + 64, 560, 920
def tx(sec):                                   # log time axis: 1 s at X_BAR, one decade per 100 px
    return X_BAR + 100 * math.log10(sec)

for label, x in (("LOOP", M), ("TIME TO AN ANSWER", X_BAR), ("WHAT IT PROVES", X_PROVES)):
    d.t(label, "inter-600", 11, x, 136, MUTED, tracking=1.3)

rows = [
    ("L0", "Compile check + headless gates", "quickcheck.ps1 (Roslyn, no project lock) · build gates", 90, "10 – 90 s",
     ["Compiles with editor and player defines;", "the scene is wired as the gates expect."], BLUE),
    ("L1", "Editor + XR Simulator + Operator", "ask, act, ask again · scenario suites · pixel diffs", 5, "seconds per check",
     ["Simulated input changes the app's state", "exactly as intended."], GREEN),
    ("L2", "Dev APK on a worn headset", "Operator over adb · VrApi · Perfetto traces", 240, "~4 min",
     ["Real hands, the Adreno GPU, the", "compositor and performance."], MUTED),
    ("L3", "Release APK + smoke checklist", "no Operator layer, no dev tools", 240, "~4 min",
     ["The build that ships: store rules", "and a human look."], MUTED),
]
RY, RH, GAP = 152, 56, 16
for i, (lv, name, detail, sec, tlabel, proves, col) in enumerate(rows):
    y = RY + i * (RH + GAP)
    d.card(M, y + 6, 44, 44, r=10, stroke=col if lv == "L1" else LINE)
    d.t(lv, "jbm-600", 15, M + 22, y + 33, T1, anchor="middle")
    nw = d.t(name, "inter-600", 16, X_NAME, y + 24, T1)
    d.t(detail, "inter-400", 13, X_NAME, y + 45, T3)
    if lv == "L1":                              # where the work happens
        d.add('<rect x="%g" y="%g" width="132" height="20" rx="10" fill="%s" fill-opacity="0.12" stroke="%s" stroke-opacity="0.5"/>'
              % (X_NAME + nw + 12, y + 10, GREEN, GREEN))
        d.t("most bugs fixed here", "inter-600", 11, X_NAME + nw + 12 + 66, y + 24, GREEN, anchor="middle")
    x1 = tx(sec)
    d.add('<rect class="anim bar" style="animation-delay:%.2fs" x="%g" y="%g" width="%g" height="10" rx="5" fill="%s"/>'
          % (0.12 * i, X_BAR, y + 23, x1 - X_BAR, col))
    d.t(tlabel, "jbm-400", 13, x1 + 12, y + 32, T2)
    for j, line in enumerate(proves):
        d.t(line, "inter-400", 13.5, X_PROVES, y + 24 + j * 19, T2)

# axis
ay = RY + 4 * (RH + GAP) - GAP + 14
d.add('<path d="M %g %g H %g" stroke="%s" stroke-width="1"/>' % (X_BAR, ay, tx(1000), LINE))
for sec, lab in ((1, "1 s"), (10, "10 s"), (60, "1 min"), (300, "5 min")):
    x = tx(sec)
    d.add('<path d="M %g %g V %g" stroke="%s" stroke-width="1"/>' % (x, ay, ay + 5, LINE))
    d.add('<path d="M %g %g V %g" stroke="%s" stroke-width="1" stroke-dasharray="2 4"/>' % (x, RY, ay, LINE2))
    d.t(lab, "inter-500", 11.5, x, ay + 20, MUTED, anchor="middle")

style = """.bar { transform-box: fill-box; transform-origin: left center; animation: grow 1.2s cubic-bezier(.2,.8,.2,1) both; }
@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }"""
# the dashed grid lines must sit under the bars: move them first
d.el.sort(key=lambda s: 0 if 'stroke-dasharray="2 4"' in s else 1)
write(d.svg("Four loops, cheapest first",
            "L0 compile check and headless gates: 10 to 90 seconds. L1 editor with the Meta XR Simulator and Operator: seconds per "
            "check, where most bugs are fixed. L2 development APK on a worn headset: about 4 minutes. L3 release APK and a smoke "
            "checklist: about 4 minutes.", style), sys.argv[1] if len(sys.argv) > 1 else "loops.svg")
