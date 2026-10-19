"""fidelity.py - does the cheap render (baked atlases drawn unlit, or a Unity capture) match the Cycles reference?

    python fidelity.py --ref out/previews --test out/previews_unlit [--mask out/previews_mask]
                       [--cameras out/cameras.json] [--regions scene=rgb,machine=gb] [--gate machine]
                       [--min-ssim 0.85] [--max-de 6.0] [--gate-mode each|mean]
                       [--json out/fidelity.json] [--montage out/previews_compare] [--resize-test]

Per shot (<name>.png in every folder; the names come from --cameras shots[].name, else the reference folder):
  SSIM    skimage.metrics.structural_similarity on 8-bit sRGB RGB: gaussian weights, sigma 1.5,
          use_sample_covariance False, data_range 255 (Wang et al. 2004); the full SSIM map, mean of the 3 channels,
          averaged over each region.
  deltaE  skimage.color.rgb2lab (sRGB, D65) -> deltaE_ciede2000 per pixel; mean and p95 over each region.
Regions come from a coverage mask PNG per shot: "machine=gb" = pixels where mask G + B >= 0.5. Without --mask the
only region is "frame" (every pixel). Masks exclude overlays (captions, axes), so a Unity frame without them still
compares cleanly.
Gate: the --gate region must reach SSIM >= --min-ssim and mean deltaE <= --max-de in every shot (--gate-mode each)
or on the mean over shots (--gate-mode mean). Exit 0 pass, 1 miss / missing shot / size mismatch, 2 bad usage.
--montage writes ref | test | deltaE heat (black 0 .. white >= 12) per shot at half size, for eyes.
--resize-test resamples a test frame to the reference size (a Unity capture at another resolution); without it a
size mismatch is a failure, because a silent resample changes the numbers.

Plain CPython 3.10+ with numpy, scikit-image and Pillow (requirements.txt) - not Blender's Python, which lacks them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image
import skimage
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

SSIM_KW = dict(channel_axis=2, gaussian_weights=True, sigma=1.5, use_sample_covariance=False, data_range=255)
CHANNELS = {"r": 0, "g": 1, "b": 2}


def load_rgb(path, size=None):
    img = Image.open(path).convert("RGB")      # alpha dropped, not composited: render references opaque
    if size is not None and img.size != size:
        img = img.resize(size, Image.BILINEAR)
    return np.asarray(img, dtype=np.uint8)


def parse_regions(spec: str) -> dict:
    out = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        name, _, ch = part.partition("=")
        ch = ch.strip().lower()
        if not name or not ch or any(c not in CHANNELS for c in ch):
            raise SystemExit(f"fidelity: bad region {part!r} (want name=channels, channels from r, g, b)")
        out[name.strip()] = [CHANNELS[c] for c in ch]
    return out


def stats(ssim_map, de, m):
    n = int(m.sum())
    if n == 0:
        return {"pixels": 0}
    return {"pixels": n, "ssim": round(float(ssim_map[m].mean()), 4),
            "deltaE_mean": round(float(de[m].mean()), 3), "deltaE_p95": round(float(np.percentile(de[m], 95)), 3)}


def montage(ref, test, de, path):
    h = ref.shape[0]
    heat = (np.clip(de / 12.0, 0, 1) * 255).astype(np.uint8)
    row = np.concatenate([ref, test, np.repeat(heat[..., None], 3, axis=2)], axis=1)
    Image.fromarray(row).resize((row.shape[1] // 2, h // 2), Image.BILINEAR).save(path)


def rel(p, base):
    try:
        return os.path.relpath(p, base).replace("\\", "/")
    except ValueError:      # another drive on Windows: keep the name only, never a host path
        return os.path.basename(os.path.normpath(p))


def main():
    ap = argparse.ArgumentParser(description="SSIM + CIEDE2000 of test renders against reference renders.")
    ap.add_argument("--ref", required=True, help="folder of reference PNGs (the Cycles previews)")
    ap.add_argument("--test", required=True, help="folder of test PNGs (unlit previews or Unity captures)")
    ap.add_argument("--mask", default=None, help="folder of coverage-mask PNGs (one per shot)")
    ap.add_argument("--cameras", default=None, help="cameras.json: shot names + stage_sha256 to carry over")
    ap.add_argument("--names", default=None, help="comma-separated shot names (overrides --cameras)")
    ap.add_argument("--regions", default=None, help="name=channels list, e.g. scene=rgb,machine=gb (needs --mask)")
    ap.add_argument("--gate", default=None, help="region the thresholds apply to (default: the first region)")
    ap.add_argument("--gate-mode", choices=("each", "mean"), default="each")
    ap.add_argument("--min-ssim", type=float, default=0.85)
    ap.add_argument("--max-de", type=float, default=6.0, help="maximum mean CIEDE2000")
    ap.add_argument("--no-gate", action="store_true", help="report only, always exit 0 unless inputs are missing")
    ap.add_argument("--json", default=None, help="write the result here")
    ap.add_argument("--montage", default=None, help="folder for ref | test | deltaE montages")
    ap.add_argument("--resize-test", action="store_true", help="resample test frames to the reference size")
    a = ap.parse_args()

    regions = parse_regions(a.regions) if a.regions else ({"scene": [0, 1, 2]} if a.mask else {"frame": []})
    if not a.mask and any(regions.values()):
        raise SystemExit("fidelity: --regions with channels needs --mask")
    gate = a.gate or next(iter(regions))
    if gate not in regions:
        raise SystemExit(f"fidelity: --gate {gate!r} is not a region ({', '.join(regions)})")
    cams = {}
    if a.cameras and os.path.isfile(a.cameras):
        with open(a.cameras, encoding="utf-8") as f:
            cams = json.load(f)
    if a.names:
        names = [n.strip() for n in a.names.split(",") if n.strip()]
    elif cams.get("shots"):
        names = [s["name"] for s in cams["shots"]]
    else:
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(a.ref) if f.lower().endswith(".png"))
    if a.montage:
        os.makedirs(a.montage, exist_ok=True)

    shots, missing, problems = {}, [], []
    for n in names:
        rp, tp = os.path.join(a.ref, f"{n}.png"), os.path.join(a.test, f"{n}.png")
        mp = os.path.join(a.mask, f"{n}.png") if a.mask else None
        if not all(os.path.isfile(p) for p in (rp, tp) + ((mp,) if mp else ())):
            missing.append(n)
            continue
        ref = load_rgb(rp)
        size = (ref.shape[1], ref.shape[0])
        test = load_rgb(tp, size if a.resize_test else None)
        if test.shape != ref.shape:
            problems.append(f"{n}: test {test.shape[1]}x{test.shape[0]} != reference {size[0]}x{size[1]} "
                            f"(pass --resize-test to resample)")
            continue
        _, smap = structural_similarity(ref, test, full=True, **SSIM_KW)
        smap = smap.mean(axis=2)
        de = deltaE_ciede2000(rgb2lab(ref / 255.0), rgb2lab(test / 255.0))
        if mp:
            msk = load_rgb(mp, size).astype(np.float32) / 255.0
            masks = {r: msk[..., ch].sum(axis=2) >= 0.5 for r, ch in regions.items()}
        else:
            masks = {r: np.ones(ref.shape[:2], dtype=bool) for r in regions}
        shots[n] = {r: stats(smap, de, m) for r, m in masks.items()}
        g = shots[n][gate]
        line = " | ".join(f"{r} SSIM {s.get('ssim', float('nan')):.3f} dE {s.get('deltaE_mean', float('nan')):5.2f}"
                          for r, s in shots[n].items())
        print(f"[fidelity] {n:24s} {line}", flush=True)
        if g.get("pixels", 0) == 0:
            problems.append(f"{n}: the gate region {gate!r} is empty in its mask")
        if a.montage:
            montage(ref, test, de, os.path.join(a.montage, f"{n}.png"))

    summary = {}
    for r in regions:
        vals = [s[r] for s in shots.values() if s[r].get("pixels")]
        if vals:
            summary[r] = {"ssim_mean": round(float(np.mean([v["ssim"] for v in vals])), 4),
                          "ssim_min": round(float(np.min([v["ssim"] for v in vals])), 4),
                          "deltaE_mean": round(float(np.mean([v["deltaE_mean"] for v in vals])), 3),
                          "deltaE_max": round(float(np.max([v["deltaE_mean"] for v in vals])), 3)}
    fails = []
    if not a.no_gate and gate in summary:
        if a.gate_mode == "mean":
            s = summary[gate]
            if s["ssim_mean"] < a.min_ssim or s["deltaE_mean"] > a.max_de:
                fails.append(f"mean over shots: SSIM {s['ssim_mean']} (min {a.min_ssim}), dE {s['deltaE_mean']} "
                             f"(max {a.max_de})")
        else:
            for n, s in shots.items():
                g = s[gate]
                if g.get("pixels") and (g["ssim"] < a.min_ssim or g["deltaE_mean"] > a.max_de):
                    fails.append(f"{n}: SSIM {g['ssim']} (min {a.min_ssim}), dE {g['deltaE_mean']} (max {a.max_de})")
    ok = bool(shots) and not missing and not problems and not fails
    base = os.path.dirname(os.path.abspath(a.json)) if a.json else os.getcwd()
    out = {"format": "fidelity/1", "reference": rel(a.ref, base), "test": rel(a.test, base),
           "mask": rel(a.mask, base) if a.mask else None, "stage_sha256": cams.get("stage_sha256"),
           "metric": {"ssim": "skimage structural_similarity " + json.dumps(SSIM_KW, sort_keys=True) +
                              ", full map, mean of the 3 channels, averaged over the region",
                      "deltaE": "skimage rgb2lab (sRGB, D65) + deltaE_ciede2000 per pixel; mean and p95 over the region",
                      "regions": {r: "".join("rgb"[c] for c in ch) or "all pixels" for r, ch in regions.items()}},
           "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "scikit_image": skimage.__version__},
           "gate": {"region": gate, "mode": a.gate_mode, "min_ssim": a.min_ssim, "max_deltaE_mean": a.max_de,
                    "enabled": not a.no_gate},
           "shots": shots, "summary": summary, "missing": missing, "problems": problems, "failures": fails,
           "pass": ok}
    if a.json:
        os.makedirs(base, exist_ok=True)
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
    for r, s in summary.items():
        print(f"[fidelity] mean {r:10s} SSIM {s['ssim_mean']:.3f} (min {s['ssim_min']:.3f})  dE {s['deltaE_mean']:.2f} "
              f"(max {s['deltaE_max']:.2f})", flush=True)
    if missing:
        print(f"[fidelity] FAIL missing shot(s) in ref / test / mask: {missing}", flush=True)
    for msg in problems + fails:
        print(f"[fidelity] FAIL {msg}", flush=True)
    print(f"[fidelity] {'PASS' if ok else 'FAIL'}: gate {gate} ({a.gate_mode}) SSIM >= {a.min_ssim}, "
          f"mean dE <= {a.max_de}; {len(shots)} shot(s)" + (f" -> {a.json}" if a.json else ""), flush=True)
    if a.no_gate:
        return 0 if shots and not missing and not problems else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
