"""docs/assets/sim-loop.svg - how the agent drives the app in the simulator."""
import sys

from svgkit import icon, text, font, defs

OUT = sys.argv[1] if len(sys.argv) > 1 else "sim-loop.svg"
W, H = 1280, 668

T1, T2, T3, MUTED = "#F0F6FC", "#C9D1D9", "#8B949E", "#6E7681"
CARD, CARD2, LINE, LINE2 = "#161B22", "#11161D", "#30363D", "#21262D"
BLUE, GREEN = "#4493F8", "#3FB950"
CLAUDE, UNITY = "#D97757", "#FFFFFF"

el, under, base = [], [], []
M = 56                       # outer margin
# columns
AX, AW = M, 268              # agent
CX, CWD = 428, 312           # channels
UX, UW = 852, W - M - 852    # unity container (372)
IX, IW = UX + 20, UW - 40    # unity inner blocks
# rows
RA, RB, RH = 156, 316, 112   # row tops, row height
ya, yb = RA + RH / 2, RB + RH / 2


def card(x, y, w, h, stroke=LINE, fill=CARD, r=14):
    return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" stroke="%s" stroke-width="1.2"/>' % (x, y, w, h, r, fill, stroke)


def t(s, f, size, x, y, fill, **kw):
    svg, w = text(s, f, size, x, y, fill, **kw)
    el.append(svg)
    return w


def wrap(s, f, size, maxw):
    lines, cur = [], ""
    for word in s.split():
        trial = (cur + " " + word).strip()
        if font(f).width(trial, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def arrow(x1, y1, x2, y2, color, label=None, label_side=-1):
    """Straight connector with a drawn arrowhead at (x2, y2); label centred above (-1) or below (+1)."""
    el.append('<path d="M %g %g L %g %g" stroke="%s" stroke-opacity="0.75" stroke-width="1.6" fill="none"/>' % (x1, y1, x2, y2, color))
    if x1 == x2:   # vertical
        d = 1 if y2 > y1 else -1
        head = "M %g %g L %g %g L %g %g Z" % (x2, y2, x2 - 5, y2 - 9 * d, x2 + 5, y2 - 9 * d)
    else:
        d = 1 if x2 > x1 else -1
        head = "M %g %g L %g %g L %g %g Z" % (x2, y2, x2 - 9 * d, y2 - 5, x2 - 9 * d, y2 + 5)
    el.append('<path d="%s" fill="%s"/>' % (head, color))
    if label:
        if x1 == x2:
            t(label, "inter-500", 12, x1 + 12, (y1 + y2) / 2 + 4, T3)
        else:
            t(label, "inter-500", 12, (x1 + x2) / 2, y1 + (-10 if label_side < 0 else 21), T3, anchor="middle")


# ---- heading
t("The simulator loop", "inter-700", 28, M, 70, T1, tracking=-0.4)
t("Your app runs in Unity Play Mode on the Meta XR Simulator. Your agent reads its state, drives its input, and reads it again.",
  "inter-400", 15.5, M, 100, T3)

# ---- the moving dot runs under the cards: visible on the connectors, hidden while it passes through a component
loop = "M %g %g H %g V %g H %g Z" % (AX + AW, ya, IX + IW / 2, yb, AX + AW)
under.append('<g class="runner"><circle r="8" fill="%s" fill-opacity="0.2"/><circle r="3.5" fill="%s"/>'
             '<animateMotion dur="6s" repeatCount="indefinite" path="%s"/></g>' % (BLUE, BLUE, loop))

# ---- agent (spans both rows)
el.append(card(AX, RA, AW, RB + RH - RA))
el.append(icon("lu-square-terminal", AX + 22, RA + 22, 24, T1, stroke=1.8))
t("Your agent", "inter-600", 17, AX + 56, RA + 41, T1)
t("Claude Code, Codex, Gemini CLI...", "inter-400", 13, AX + 22, RA + 74, T3)
scripts = [("op.py", "run_scenario.py"), ("aimfix.py", "panelshot.py"), ("imgdiff.py", "logscan.py"), ("reload.py", "quickcheck.ps1")]
for i, (a, b) in enumerate(scripts):
    y = RA + 98 + i * 40
    el.append(card(AX + 16, y, AW - 32, 28, stroke=LINE2, fill=CARD2, r=7))
    t(a + "  ·  " + b, "jbm-400", 12.5, AX + 30, y + 18.5, T2)

# ---- channels
el.append(card(CX, RA, CWD, RH))
t("ACT  ·  MCP :8720", "inter-600", 11, CX + 20, RA + 28, BLUE, tracking=1.2)
t("Meta XR Operator", "inter-600", 17, CX + 20, RA + 54, T1)
t("openxr_set_controller_input", "jbm-400", 12.5, CX + 20, RA + 78, T2)
t("openxr_capture_composited_image", "jbm-400", 12.5, CX + 20, RA + 97, T2)

el.append(card(CX, RB, CWD, RH))
t("ASK  ·  HTTP :8731", "inter-600", 11, CX + 20, RB + 28, GREEN, tracking=1.2)
t("DevRemote", "inter-600", 17, CX + 20, RB + 54, T1)
t("/tool/myapp_get_state", "jbm-400", 12.5, CX + 20, RB + 78, T2)
t("/status  /play  /stop  /refresh", "jbm-400", 12.5, CX + 20, RB + 97, T2)

# ---- unity editor
UY, UH = RA - 44, RB + RH + 22 - (RA - 44)
base.append(card(UX, UY, UW, UH, fill="#0F1419", r=18))
el.append(icon("si-unity", UX + 20, UY + 14, 16, UNITY))
t("UNITY EDITOR  ·  PLAY MODE", "inter-600", 11, UX + 44, UY + 27, T3, tracking=1.2)

el.append(card(IX, RA, IW, RH))
el.append(icon("tb-cardboards", IX + 18, RA + 18, 22, T2, stroke=1.7))
t("Meta XR Simulator", "inter-600", 16, IX + 50, RA + 36, T1)
for i, line in enumerate(["OpenXR runtime: a simulated Quest 3", "head, Touch controllers, Operator layer"]):
    t(line, "inter-400", 13, IX + 18, RA + 66 + i * 19, T3)

el.append(card(IX, RB, IW, RH))
el.append(icon("lu-box", IX + 18, RB + 18, 22, T2, stroke=1.7))
t("Your Quest app", "inter-600", 16, IX + 50, RB + 36, T1)
t("AgentTools: the app reports its own state", "inter-400", 13, IX + 18, RB + 66, T3)
t("myapp_get_state  ·  myapp_press", "jbm-400", 12.5, IX + 18, RB + 88, T2)

# ---- connectors (input: blue, state: green)
arrow(AX + AW, ya, CX - 2, ya, BLUE, "input")
arrow(CX + CWD, ya, IX - 2, ya, BLUE, "poses · buttons")
arrow(IX + IW / 2, RA + RH, IX + IW / 2, RB - 2, T3, "OpenXR")
arrow(IX, yb, CX + CWD + 2, yb, GREEN, "JSON", label_side=1)
arrow(CX, yb, AX + AW + 2, yb, GREEN, "state", label_side=1)

# ---- the four moves of every check
SY, SH, gap = 476, 128, 20
sw = (W - 2 * M - 3 * gap) / 4
steps = [("lu-search", "Ask", "Read the state with an app tool, not from a picture."),
         ("lu-mouse-pointer-click", "Act", "Inject head, controller and button input through the real path."),
         ("lu-refresh-cw", "Ask again", "Compare the answers. A screenshot on its own asserts nothing."),
         ("lu-shield-check", "Gate it", "Pin it with a headless check, seen failing once with the bug back.")]
for i, (ic, title, body) in enumerate(steps):
    x = M + i * (sw + gap)
    el.append(card(x, SY, sw, SH))
    el.append('<rect x="%g" y="%g" width="32" height="32" rx="8" fill="#FFFFFF" fill-opacity="0.04" stroke="%s"/>' % (x + 18, SY + 18, LINE2))
    el.append(icon(ic, x + 25, SY + 25, 18, T2, stroke=1.7))
    t("%02d" % (i + 1), "jbm-600", 12, x + sw - 18, SY + 38, MUTED, anchor="end")
    t(title, "inter-600", 15.5, x + 62, SY + 39, T1)
    for j, line in enumerate(wrap(body, "inter-400", 13.5, sw - 36)):
        t(line, "inter-400", 13.5, x + 18, SY + 78 + j * 20, T3)
    if i < 3:   # small chevron in the gutter
        gx = x + sw + gap / 2
        el.append('<path d="M %g %g L %g %g L %g %g" fill="none" stroke="%s" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
                  % (gx - 2.5, SY + SH / 2 - 5, gx + 2.5, SY + SH / 2, gx - 2.5, SY + SH / 2 + 5, MUTED))

# ---- the edit loop, as a footer
parts = ["edit", "quickcheck.ps1 (10 s, no lock)", "reload.py", "run_scenario.py", "repeat"]
x, fy = M, 638
for i, p in enumerate(parts):
    w = t(p, "jbm-400", 12.5, x, fy, T3 if i % 4 else MUTED)
    x += w
    if i < len(parts) - 1:
        el.append('<path d="M %g %g L %g %g L %g %g" fill="none" stroke="%s" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
                  % (x + 12, fy - 8.5, x + 16, fy - 4.5, x + 12, fy - 0.5, MUTED))
        x += 28

svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">
<title id="t">The simulator loop</title>
<desc id="d">A coding agent drives a Unity Quest app running in editor Play Mode on the Meta XR Simulator. It injects head, controller and button input through the Meta XR Operator (MCP on port 8720), and reads the app's own state through DevRemote (HTTP on port 8731). Every check is ask, act, ask again, and each finding is pinned with a headless gate.</desc>
<defs>{GLYPHS}
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#11161D"/><stop offset="1" stop-color="#0B0E13"/></linearGradient>
<style>@media (prefers-reduced-motion: reduce) {{ .runner {{ display: none; }} }}</style>
</defs>
<rect width="{W}" height="{H}" rx="20" fill="url(#bg)"/>
<rect x="0.5" y="0.5" width="{W1}" height="{H1}" rx="19.5" fill="none" stroke="#262C36"/>
{BASE}
{UNDER}
{BODY}
</svg>
""".format(GLYPHS=defs(), W=W, H=H, W1=W - 1, H1=H - 1, BASE="\n".join(base), UNDER="\n".join(under), BODY="\n".join(el))
open(OUT, "w", encoding="utf-8", newline="\n").write(svg)
print("wrote", OUT, len(svg) // 1024, "KB")
