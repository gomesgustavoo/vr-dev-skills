"""docs/assets/hero.svg - the README banner."""
import math
import sys

from svgkit import icon, text, font, defs

OUT = sys.argv[1] if len(sys.argv) > 1 else "hero.svg"
W, H = 1280, 472

# palette (GitHub dark + one accent)
T1, T2, T3, MUTED = "#F0F6FC", "#C9D1D9", "#8B949E", "#6E7681"
CARD, LINE, LINE2 = "#161B22", "#30363D", "#21262D"
ACCENT = "#4493F8"
CLAUDE, META, BLENDER, UNITY = "#D97757", "#0A84FF", "#E87D0D", "#FFFFFF"

el = []
X0 = 72

# ---- eyebrow
el.append(icon("si-claude", X0, 62, 18, CLAUDE))
s, w = text("Claude Code plugin", "inter-600", 14, X0 + 28, 76, T3, tracking=0.2); el.append(s)
s, w2 = text("·", "inter-600", 14, X0 + 28 + w + 9, 76, MUTED); el.append(s)
s, _ = text("MIT licensed", "inter-500", 14, X0 + 28 + w + 9 + w2 + 9, 76, T3, tracking=0.2); el.append(s)

# ---- title, subtitle, proof line
s, _ = text("vr-dev-skills", "inter-700", 64, X0 - 3, 150, T1, tracking=-1.8); el.append(s)
s, sw1 = text("Develop, simulate, test and ship Meta Quest apps", "inter-500", 23, X0, 198, T2, tracking=-0.2); el.append(s)
s, sw2 = text("with Claude Code. Simulator first, headset last.", "inter-500", 23, X0, 229, T2, tracking=-0.2); el.append(s)
s, _ = text("Skills, scripts and C# templates proven on a production Quest app.", "inter-400", 16, X0, 268, T3); el.append(s)

# ---- works with: real logos, one baseline
s, _ = text("WORKS WITH", "inter-600", 11, X0, 318, MUTED, tracking=1.4); el.append(s)
items = [("si-unity", UNITY, "Unity"), ("tb-cardboards", T2, "Meta XR Simulator"),
         ("si-meta", META, "Horizon OS MCP"), ("si-blender", BLENDER, "Blender")]
x, base = X0, 350
for ic, col, label in items:
    el.append(icon(ic, x, base - 15.5, 20, col, stroke=1.6))
    s, lw = text(label, "inter-500", 15, x + 28, base, T2); el.append(s)
    x += 28 + lw + 30

# ---- install command
cmd = "/plugin install vr-dev@vr-dev-skills"
cw = font("jbm-400").width("$ " + cmd, 15)
py, ph = 384, 42
el.append('<rect x="%g" y="%g" width="%g" height="%g" rx="10" fill="%s" stroke="%s"/>' % (X0, py, cw + 56, ph, CARD, LINE))
s, dw = text("$ ", "jbm-400", 15, X0 + 18, py + 26, MUTED); el.append(s)
s, _ = text(cmd, "jbm-400", 15, X0 + 18 + dw, py + 26, T1); el.append(s)
el.append('<rect class="caret" x="%g" y="%g" width="8" height="17" rx="1" fill="%s"/>' % (X0 + 18 + cw + 6, py + 12.5, ACCENT))

# ---- the loop: Develop -> Simulate -> Test -> Ship, Claude Code in the middle
cx, cy, rx, ry = 970, 236, 150, 126
track = "M %g %g A %g %g 0 0 1 %g %g A %g %g 0 0 1 %g %g" % (cx, cy - ry, rx, ry, cx, cy + ry, rx, ry, cx, cy - ry)
el.append('<rect x="700" y="0" width="580" height="%d" fill="url(#dots)" mask="url(#fade)"/>' % H)
el.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.5"/>' % (track, LINE))
for deg in (-45, 45, 135, 225):                       # direction chevrons between the steps (clockwise)
    t = math.radians(deg)
    px, py_ = cx + rx * math.cos(t), cy + ry * math.sin(t)
    ang = math.degrees(math.atan2(ry * math.cos(t), -rx * math.sin(t)))
    el.append('<path d="M -4 -4.5 L 2 0 L -4 4.5" fill="none" stroke="%s" stroke-width="1.6" stroke-linecap="round" '
              'stroke-linejoin="round" transform="translate(%.1f %.1f) rotate(%.1f)"/>' % (MUTED, px, py_, ang))
el.append('<g class="runner"><circle r="9" fill="%s" fill-opacity="0.18"/><circle r="4" fill="%s"/>'
          '<animateMotion dur="8s" repeatCount="indefinite" path="%s"/></g>' % (ACCENT, ACCENT, track))

steps = [  # name, sublabel, icon, centre
    ("Develop", "Unity · C# · Blender", "lu-code-xml", (cx, cy - ry)),
    ("Simulate", "Meta XR Simulator", "tb-cardboards", (cx + rx, cy)),
    ("Test", "scenarios · gates", "lu-list-checks", (cx, cy + ry)),
    ("Ship", "Quest 3 · Quest 3S", "lu-rocket", (cx - rx, cy)),
]
CW_, CH_ = 176, 60
for i, (name, sub, ic, (mx, my)) in enumerate(steps):
    x0, y0 = mx - CW_ / 2, my - CH_ / 2
    el.append('<g class="step s%d">' % i)
    el.append('<rect class="card" x="%g" y="%g" width="%g" height="%g" rx="14" fill="%s" stroke="%s" stroke-width="1.2"/>'
              % (x0, y0, CW_, CH_, CARD, LINE))
    el.append('<rect class="chip" x="%g" y="%g" width="34" height="34" rx="9" fill="#FFFFFF" fill-opacity="0.04" stroke="%s"/>'
              % (x0 + 13, y0 + 13, LINE2))
    el.append(icon(ic, x0 + 13 + 7, y0 + 13 + 7, 20, T2, stroke=1.7))
    s, _ = text(name, "inter-600", 15.5, x0 + 59, y0 + 27, T1); el.append(s)
    s, _ = text(sub, "inter-400", 12.5, x0 + 59, y0 + 45, T3); el.append(s)
    el.append("</g>")

el.append('<circle cx="%g" cy="%g" r="51" fill="%s" stroke="%s" stroke-width="1.2"/>' % (cx, cy, CARD, LINE))
el.append(icon("si-claude", cx - 15, cy - 27, 30, CLAUDE))
s, _ = text("Claude Code", "inter-600", 12.5, cx, cy + 25, T2, anchor="middle"); el.append(s)

svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">
<title id="t">vr-dev-skills</title>
<desc id="d">Claude Code plugin for Meta Quest development: develop in Unity, simulate in the Meta XR Simulator, test with scenarios and gates, ship to Quest 3 and 3S. Works with Unity, the Meta XR Simulator, the Horizon OS MCP and Blender. Install: /plugin install vr-dev@vr-dev-skills</desc>
<defs>{GLYPHS}
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#11161D"/><stop offset="1" stop-color="#0B0E13"/></linearGradient>
<radialGradient id="fadeg" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/></radialGradient>
<pattern id="dots" x="2" y="8" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="12" cy="12" r="1" fill="#FFFFFF" fill-opacity="0.07"/></pattern>
<mask id="fade"><rect x="700" y="0" width="580" height="{H}" fill="url(#fadeg)"/></mask>
<clipPath id="card"><rect width="{W}" height="{H}" rx="20"/></clipPath>
<style>
.caret {{ animation: blink 1.1s steps(1) infinite; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
.step .card {{ animation: lit 8s linear infinite; }}
.s1 .card {{ animation-delay: 2s; }} .s2 .card {{ animation-delay: 4s; }} .s3 .card {{ animation-delay: 6s; }}
@keyframes lit {{ 0% {{ stroke: {A}; }} 14% {{ stroke: {A}; }} 22% {{ stroke: {L}; }} 92% {{ stroke: {L}; }} 100% {{ stroke: {A}; }} }}
@media (prefers-reduced-motion: reduce) {{ .caret, .step .card {{ animation: none; }} .runner {{ display: none; }} }}
</style>
</defs>
<g clip-path="url(#card)"><rect width="{W}" height="{H}" fill="url(#bg)"/></g>
<rect x="0.5" y="0.5" width="{W1}" height="{H1}" rx="19.5" fill="none" stroke="#262C36"/>
{BODY}
</svg>
""".format(GLYPHS=defs(), W=W, H=H, W1=W - 1, H1=H - 1, A=ACCENT, L=LINE, BODY="\n".join(el))
open(OUT, "w", encoding="utf-8", newline="\n").write(svg)
print("wrote", OUT, len(svg) // 1024, "KB; subtitle widths", round(sw1), round(sw2))
