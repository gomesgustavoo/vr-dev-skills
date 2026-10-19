"""Tiny SVG kit for README diagrams: HarfBuzz-shaped text as outlines (identical on every OS) and icon placement.

Text becomes <path> so a GitHub <img> renders the same glyphs on Windows, macOS and Linux; each SVG
still carries <title>/<desc> for screen readers.
"""
import io
import os
import re

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, ".cache", "fonts")   # fetch.py fills .cache/ (git-ignored)
ICONS = os.path.join(HERE, ".cache", "icons")


class Font:
    def __init__(self, path):
        tt = TTFont(path)
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        self.tt = TTFont(io.BytesIO(buf.getvalue()))
        self.upem = self.tt["head"].unitsPerEm
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.hbfont = hb.Font(hb.Face(buf.getvalue()))
        self.ascender = self.tt["OS/2"].sTypoAscender
        self.cap = getattr(self.tt["OS/2"], "sCapHeight", 0) or int(self.upem * 0.7)

    def shape(self, text, size, tracking=0.0):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": True, "liga": True})
        s = size / self.upem
        out, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset * s, pos.y_offset * s))
            x += pos.x_advance * s + tracking
        return out, x - (tracking if out else 0)

    def width(self, text, size, tracking=0.0):
        return self.shape(text, size, tracking)[1]


_FONTS = {}


def font(name):
    if name not in _FONTS:
        _FONTS[name] = Font(os.path.join(FONTS, name + ".woff"))
    return _FONTS[name]


def _r(m):
    return "%g" % round(float(m.group(0)), 1)


_DEFS = {}   # (font, size, glyph) -> (id, path d): each glyph outline is written once per document


def reset_defs():
    _DEFS.clear()


def defs():
    """<path id=...> for every glyph used since reset_defs(); put it inside the document's <defs>."""
    return "".join('<path id="%s" d="%s"/>' % (gid, d) for gid, d in _DEFS.values())


def _glyph(f, fname, size, gname):
    key = (fname, size, gname)
    if key not in _DEFS:
        sc = size / f.upem
        pen = SVGPathPen(f.glyphs)
        f.glyphs[gname].draw(TransformPen(pen, (sc, 0, 0, -sc, 0, 0)))
        d = re.sub(r"-?\d+\.\d+|-?\d+", _r, pen.getCommands())
        _DEFS[key] = ("g%d" % len(_DEFS), d) if d else (None, "")
    return _DEFS[key][0]


def text(s, fname, size, x, y, fill, anchor="start", tracking=0.0, opacity=None, cls=None):
    """Text run as reused glyph outlines. y is the BASELINE. Returns (svg, width)."""
    f = font(fname)
    glyphs, w = f.shape(s, size, tracking)
    if any(g[0] == ".notdef" for g in glyphs):
        raise ValueError("glyph missing from %s: %r" % (fname, s))
    x0 = x - (w / 2 if anchor == "middle" else w if anchor == "end" else 0)
    parts = []
    for gname, gx, gy in glyphs:
        gid = _glyph(f, fname, size, gname)
        if gid:
            parts.append('<use href="#%s" x="%g" y="%g"/>' % (gid, round(x0 + gx, 1), round(y - gy, 1)))
    attrs = ' fill="%s"' % fill
    if opacity is not None:
        attrs += ' fill-opacity="%s"' % opacity
    if cls:
        attrs += ' class="%s"' % cls
    return '<g%s>%s</g>' % (attrs, "".join(parts)), w


def icon_inner(name):
    """The drawable children of an icon SVG (paths, circles, lines...), without the outer <svg>."""
    raw = open(os.path.join(ICONS, name + ".svg"), encoding="utf-8").read()
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    raw = re.sub(r"<title>.*?</title>", "", raw, flags=re.S)
    inner = re.search(r"<svg[^>]*>(.*)</svg>", raw, flags=re.S).group(1)
    inner = re.sub(r'<path stroke="none" d="M0 0h24v24H0z" fill="none"/>', "", inner)   # tabler's bounding box
    return re.sub(r"\s+", " ", inner).strip()


def icon(name, x, y, size, color, stroke=1.75):
    """Place a 24x24 icon with its top-left at (x, y). Brand icons (si-*) are filled; line icons are stroked
    at a constant `stroke` px whatever the size."""
    s = size / 24.0
    inner = icon_inner(name)
    if name.startswith("si-"):
        return '<g transform="translate(%g %g) scale(%g)" fill="%s">%s</g>' % (x, y, s, color, inner)
    return ('<g transform="translate(%g %g) scale(%g)" fill="none" stroke="%s" stroke-width="%g" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g>' % (x, y, s, color, stroke / s, inner))
