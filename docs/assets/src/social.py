"""docs/assets/social-preview.png source: a 1280x640 card (rendered to PNG by a browser screenshot)."""
import base64
import sys

from common import BLENDER, CARD, CLAUDE, LINE, META, MUTED, T1, T2, T3, UNITY, Doc
from svgkit import icon

OUT, IMG = sys.argv[1], sys.argv[2]
W, H = 1280, 640
d = Doc(W, H)
X0 = 72

d.icon("si-claude", X0, 92, 20, CLAUDE)
w = d.t("Claude Code plugin", "inter-600", 15, X0 + 30, 107, T3, tracking=0.2)
d.t("·  open source", "inter-500", 15, X0 + 30 + w + 9, 107, T3, tracking=0.2)
d.t("vr-dev-skills", "inter-700", 76, X0 - 4, 196, T1, tracking=-2.2)
d.t("Develop, simulate, test and ship", "inter-500", 27, X0, 252, T2, tracking=-0.3)
d.t("Meta Quest apps with Claude Code.", "inter-500", 27, X0, 288, T2, tracking=-0.3)
d.t("Simulator first, headset last.", "inter-400", 19, X0, 334, T3)

d.t("WORKS WITH", "inter-600", 12, X0, 470, MUTED, tracking=1.4)
items = [("si-unity", UNITY, "Unity"), ("tb-cardboards", T2, "XR Simulator"), ("si-meta", META, "Horizon OS"), ("si-blender", BLENDER, "Blender")]
x, base = X0, 508
for ic, col, label in items:
    d.icon(ic, x, base - 17, 22, col, stroke=1.6)
    lw = d.t(label, "inter-500", 17, x + 31, base, T2)
    x += 31 + lw + 30

# the showcase capture, framed
fx, fy, fw, fh = 700, 96, 508, 381
b64 = base64.b64encode(open(IMG, "rb").read()).decode("ascii")
d.add('<clipPath id="shot"><rect x="%g" y="%g" width="%g" height="%g" rx="16"/></clipPath>' % (fx, fy, fw, fh))
d.add('<image href="data:image/jpeg;base64,%s" x="%g" y="%g" width="%g" height="%g" preserveAspectRatio="xMidYMid slice" clip-path="url(#shot)"/>'
      % (b64, fx, fy, fw, fh))
d.add('<rect x="%g" y="%g" width="%g" height="%g" rx="16" fill="none" stroke="%s" stroke-width="1.5"/>' % (fx, fy, fw, fh, LINE))
d.t("DicomSegVR's TrueBeam room, tested in the Meta XR Simulator", "inter-400", 14, fx + fw / 2, fy + fh + 30, T3, anchor="middle")

d.el.insert(0, '<g transform="translate(0 22)">')   # centre the content block vertically
d.el.append("</g>")
open(OUT, "w", encoding="utf-8").write(d.svg("vr-dev-skills", "Social preview card."))
print("wrote", OUT)
