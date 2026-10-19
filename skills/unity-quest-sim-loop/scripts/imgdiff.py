"""Prove what colour ONE object is drawn in, by difference: capture the same frame with the
object shown and hidden (toggle only that), then measure the pixels that changed.

    python imgdiff.py ON.png OFF.png [--expect "#ff3b30"] [--roi x0,y0,x1,y1]
                      [--control ON_AGAIN.png] [--threshold 24] [--mask OUT.png]

Prints: how many pixels changed, their median colour and hue, a hue histogram, and (with
--expect) how far the median is from the intended colour. Writes a mask image (changed
pixels in their real colour over a washed-out frame) - that picture plus these numbers is
evidence; a single screenshot of a crowded scene is an argument.

--control re-captures the ON state a second time: the pixels that differ between the two ON
frames are the noise floor (dithering, animated UI). --roi limits the count to a region when
something else in frame repaints too (a UI toggle row changes when you click it). PIL only.
"""
import colorsys
import statistics
import sys

from PIL import Image

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def pop(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return default


def pixels(path):
    im = Image.open(path).convert("RGB")
    b = im.tobytes()
    return im, [(b[i], b[i + 1], b[i + 2]) for i in range(0, len(b), 3)]


def hsv(p):
    h, s, v = colorsys.rgb_to_hsv(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0)
    return h * 360.0, s, v


def hue_name(h, s):
    if s < 0.2:
        return "grey/white (s<0.2)"
    names = [(15, "red"), (40, "orange"), (65, "yellow"), (160, "green"), (200, "cyan"),
             (250, "blue"), (290, "purple"), (345, "pink/magenta"), (361, "red")]
    for limit, name in names:
        if h < limit:
            return name
    return "red"


def main():
    argv = sys.argv[1:]
    expect = pop(argv, "--expect")
    roi = pop(argv, "--roi")
    control = pop(argv, "--control")
    thr = int(pop(argv, "--threshold", "24"))
    mask_path = pop(argv, "--mask", "imgdiff-mask.png")
    if len(argv) < 2:
        print(__doc__)
        return 2
    on_im, on = pixels(argv[0])
    off_im, off = pixels(argv[1])
    if on_im.size != off_im.size:
        print("sizes differ: %s vs %s - capture both with the same width/height/fov" % (on_im.size, off_im.size))
        return 2
    w, h = on_im.size
    box = tuple(int(v) for v in roi.split(",")) if roi else (0, 0, w, h)

    def changed(a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])) > thr

    idx_all = [i for i in range(w * h) if changed(on[i], off[i])]
    idx = [i for i in idx_all if box[0] <= i % w < box[2] and box[1] <= i // w < box[3]]
    print("%dx%d  changed pixels (>%d/255): %d in region, %d outside it" % (w, h, thr, len(idx), len(idx_all) - len(idx)))
    if control:
        _, again = pixels(control)
        noise = sum(1 for i in range(w * h) if changed(on[i], again[i]))
        print("control (ON vs ON again): %d pixels differ = noise floor (%.1f%% of the signal)"
              % (noise, 100.0 * noise / max(1, len(idx))))
    if not idx:
        print("NOTHING CHANGED: the object is not drawn in this view (hidden, culled, occluded or off-screen)")
        return 1

    reds = [on[i][0] for i in idx]; greens = [on[i][1] for i in idx]; blues = [on[i][2] for i in idx]
    med = (int(statistics.median(reds)), int(statistics.median(greens)), int(statistics.median(blues)))
    mh, ms, mv = hsv(med)
    print("median colour of the object's pixels: RGB%s  #%02x%02x%02x  hue %.1f  sat %.2f  val %.2f"
          % (med, med[0], med[1], med[2], mh, ms, mv))
    hist = {}
    for i in idx:
        hh, ss, _ = hsv(on[i])
        name = hue_name(hh, ss)
        hist[name] = hist.get(name, 0) + 1
    for name, n in sorted(hist.items(), key=lambda kv: -kv[1]):
        print("  %-20s %6d  %5.1f%%" % (name, n, 100.0 * n / len(idx)))
    off_same = sum(1 for i in idx if hue_name(*hsv(off[i])[:2]) == hue_name(mh, ms))
    print("same hue family in the OFF frame at those pixels: %.1f%% (low = the colour comes from the object)"
          % (100.0 * off_same / len(idx)))
    if expect:
        e = expect.lstrip("#")
        ec = (int(e[0:2], 16), int(e[2:4], 16), int(e[4:6], 16))
        eh, es, _ = hsv(ec)
        dh = min(abs(mh - eh), 360 - abs(mh - eh))
        print("expected #%s (hue %.1f): median is %.1f deg of hue away%s" % (
            e, eh, dh, " - translucent layers in front shift it; compare where it is seen directly" if dh > 5 else ""))

    out = Image.new("RGB", (w, h))
    sel = set(idx)
    out.putdata([on[i] if i in sel else tuple(int(c * 0.35 + 255 * 0.65) for c in on[i]) for i in range(w * h)])
    out.save(mask_path)
    print("mask: " + mask_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
