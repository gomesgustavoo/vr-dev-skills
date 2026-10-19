"""Shared tokens and helpers for the README diagrams (one visual system)."""
from svgkit import defs, font, icon, reset_defs, text

T1, T2, T3, MUTED = "#F0F6FC", "#C9D1D9", "#8B949E", "#6E7681"
CARD, CARD2, LINE, LINE2 = "#161B22", "#11161D", "#30363D", "#21262D"
BLUE, GREEN, ORANGE, VIOLET = "#4493F8", "#3FB950", "#DB8B44", "#A371F7"
CLAUDE, META, BLENDER, UNITY = "#D97757", "#0A84FF", "#E87D0D", "#FFFFFF"
M = 56


class Doc:
    def __init__(self, w, h):
        reset_defs()
        self.w, self.h = w, h
        self.base, self.under, self.el = [], [], []

    def add(self, s, layer="el"):
        getattr(self, layer).append(s)

    def t(self, s, f, size, x, y, fill, layer="el", **kw):
        svg, w = text(s, f, size, x, y, fill, **kw)
        getattr(self, layer).append(svg)
        return w

    def card(self, x, y, w, h, stroke=LINE, fill=CARD, r=14, layer="el", cls=None):
        c = ' class="%s"' % cls if cls else ""
        getattr(self, layer).append('<rect%s x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" stroke="%s" stroke-width="1.2"/>'
                                    % (c, x, y, w, h, r, fill, stroke))

    def chip(self, x, y, ic, color=T2, size=32, isz=18):
        self.el.append('<rect x="%g" y="%g" width="%g" height="%g" rx="8" fill="#FFFFFF" fill-opacity="0.04" stroke="%s"/>'
                       % (x, y, size, size, LINE2))
        self.el.append(icon(ic, x + (size - isz) / 2, y + (size - isz) / 2, isz, color, stroke=1.7))

    def icon(self, *a, **kw):
        self.el.append(icon(*a, **kw))

    def chevron(self, x, y, color=MUTED, h=5, layer="el"):
        getattr(self, layer).append('<path d="M %g %g L %g %g L %g %g" fill="none" stroke="%s" stroke-width="1.6" '
                                    'stroke-linecap="round" stroke-linejoin="round"/>' % (x - h / 2, y - h, x + h / 2, y, x - h / 2, y + h, color))

    def arrow(self, x1, y1, x2, y2, color, label=None, below=False):
        self.el.append('<path d="M %g %g L %g %g" stroke="%s" stroke-opacity="0.75" stroke-width="1.6" fill="none"/>' % (x1, y1, x2, y2, color))
        if x1 == x2:
            d = 1 if y2 > y1 else -1
            head = "M %g %g L %g %g L %g %g Z" % (x2, y2, x2 - 5, y2 - 9 * d, x2 + 5, y2 - 9 * d)
        else:
            d = 1 if x2 > x1 else -1
            head = "M %g %g L %g %g L %g %g Z" % (x2, y2, x2 - 9 * d, y2 - 5, x2 - 9 * d, y2 + 5)
        self.el.append('<path d="%s" fill="%s"/>' % (head, color))
        if label:
            if x1 == x2:
                self.t(label, "inter-500", 12, x1 + 12, (y1 + y2) / 2 + 4, T3)
            else:
                self.t(label, "inter-500", 12, (x1 + x2) / 2, y1 + (21 if below else -10), T3, anchor="middle")

    def heading(self, title, sub):
        self.t(title, "inter-700", 26, M, 66, T1, tracking=-0.4)
        if sub:
            self.t(sub, "inter-400", 15.5, M, 94, T3)

    def svg(self, title, desc, style=""):
        return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">
<title id="t">{TITLE}</title>
<desc id="d">{DESC}</desc>
<defs>{GLYPHS}
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#11161D"/><stop offset="1" stop-color="#0B0E13"/></linearGradient>
<style>{STYLE}
@media (prefers-reduced-motion: reduce) {{ .runner {{ display: none; }} .anim {{ animation: none !important; }} }}</style>
</defs>
<rect width="{W}" height="{H}" rx="20" fill="url(#bg)"/>
<rect x="0.5" y="0.5" width="{W1}" height="{H1}" rx="19.5" fill="none" stroke="#262C36"/>
{BASE}
{UNDER}
{BODY}
</svg>
""".format(W=self.w, H=self.h, W1=self.w - 1, H1=self.h - 1, TITLE=title, DESC=desc, STYLE=style, GLYPHS=defs(),
           BASE="\n".join(self.base), UNDER="\n".join(self.under), BODY="\n".join(self.el))


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


def write(doc_svg, out):
    open(out, "w", encoding="utf-8", newline="\n").write(doc_svg)
    print("wrote", out, len(doc_svg) // 1024, "KB")
