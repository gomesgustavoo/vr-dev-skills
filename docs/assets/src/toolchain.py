"""docs/assets/toolchain.svg - one agent, four skills, three stages, one MCP under all of them."""
import sys

from common import (BLENDER, BLUE, CARD2, CLAUDE, GREEN, LINE, LINE2, M, META, MUTED, ORANGE, T1, T2, T3, UNITY,
                    VIOLET, Doc, write)
from svgkit import font

W, H = 1280, 656
d = Doc(W, H)
d.heading("One agent, four skills", "Every stage hands the next one something it can check: an FBX, a passing suite, an APK with a readout.")

# ---- the agent and its skills
TY, TH = 124, 72
d.card(M, TY, W - 2 * M, TH)
d.icon("si-claude", M + 22, TY + 24, 24, CLAUDE)
d.t("Claude Code", "inter-600", 17, M + 58, TY + 33, T1)
d.t("vr-dev plugin", "inter-400", 13, M + 58, TY + 53, T3)
skills = [("tb-cardboards", T2, "unity-quest-sim-loop"), ("lu-rocket", T2, "quest-build-deploy"),
          ("si-meta", META, "horizon-os-mcp"), ("si-blender", BLENDER, "blender-cli-vr-assets")]
widths = [font("jbm-400").width(n, 12.5) + 52 for _, _, n in skills]
x = W - M - 18 - sum(widths) - 10 * (len(skills) - 1)
for (ic, col, name), w in zip(skills, widths):
    d.card(x, TY + 18, w, 36, r=10, fill=CARD2, stroke=LINE)
    d.icon(ic, x + 14, TY + 27, 18, col, stroke=1.7)
    d.t(name, "jbm-400", 12.5, x + 40, TY + 41, T2)
    x += w + 10

# ---- three stages
LY, LH, GAPX = 244, 268, 48
LW = (W - 2 * M - 2 * GAPX) / 3
lanes = [
    ("si-blender", BLENDER, "ASSETS", "Headless Blender", ["build  ›  bake  ›  preview", "validate  ›  export"],
     ["One process per stage, pinned version,", "deterministic FBX and baked atlases."],
     ("SSIM 0.90  ·  CIEDE2000 3.7", ORANGE), "Unity frame vs the Cycles render"),
    ("si-unity", UNITY, "APP  ·  L0 + L1", "Unity + XR Simulator", ["XR Operator   MCP :8720", "DevRemote     HTTP :8731"],
     ["Inject poses and buttons, read app state,", "capture the eye view, diff pixels."],
     ("run_scenario.py *.json", BLUE), "suites that never pass vacuously"),
    ("tb-cardboards", T2, "DEVICE  ·  L2 + L3", "Quest 3 / Quest 3S", ["unity_build.ps1 -Dev", "quest_deploy.py readout"],
     ["Real hands, the Adreno GPU, VrApi fps,", "App GPU time and stale frames."],
     ("perf_trace_compare", VIOLET), "baseline vs change, one lever at a time"),
]
for i, (ic, col, eyebrow, title, mono, desc, (metric, mcol), msub) in enumerate(lanes):
    x = M + i * (LW + GAPX)
    d.card(x, LY, LW, LH)
    d.icon(ic, x + 22, LY + 22, 20, col, stroke=1.7)
    d.t(eyebrow, "inter-600", 11, x + 52, LY + 37, MUTED, tracking=1.2)
    d.t(title, "inter-600", 17, x + 22, LY + 72, T1)
    for j, line in enumerate(mono):
        d.t(line, "jbm-400", 12.5, x + 22, LY + 98 + j * 19, T2)
    for j, line in enumerate(desc):
        d.t(line, "inter-400", 13, x + 22, LY + 148 + j * 19, T3)
    d.card(x + 16, LY + LH - 78, LW - 32, 62, r=10, fill=CARD2, stroke=LINE2)
    d.t(metric, "jbm-600", 13, x + 32, LY + LH - 50, mcol)
    d.t(msub, "inter-400", 12.5, x + 32, LY + LH - 29, T3)
    if i < 2:
        d.arrow(x + LW + 2, LY + LH / 2, x + LW + GAPX - 4, LY + LH / 2, T3, ["FBX", "APK"][i])
    cxl = x + LW / 2                                  # the agent drives every stage
    d.add('<path d="M %g %g V %g" stroke="%s" stroke-width="1.4"/>' % (cxl, TY + TH, LY, LINE), layer="base")
    d.add('<circle cx="%g" cy="%g" r="3" fill="%s"/>' % (cxl, LY, LINE))

# ---- Horizon OS MCP under all of them
BY, BH = LY + LH + 28, 64
d.card(M, BY, W - 2 * M, BH, stroke="#3B2F63")
d.icon("si-meta", M + 22, BY + 21, 22, META)
d.t("HORIZON OS MCP  ·  metavr", "inter-600", 11, M + 56, BY + 28, VIOLET, tracking=1.2)
d.t("Check Meta SDK names in the docs before writing code against them.", "inter-400", 13, M + 56, BY + 48, T3)
d.t("vr_docs_search  ·  vr_api_search  ·  metavr_device  ·  device_logcat  ·  perf_trace_*", "jbm-400", 12.5,
    W - M - 22, BY + 38, T2, anchor="end")
for i in range(3):
    cxl = M + i * (LW + GAPX) + LW / 2
    d.add('<path d="M %g %g V %g" stroke="#3B2F63" stroke-width="1.4"/>' % (cxl, LY + LH, BY), layer="base")
    d.add('<circle cx="%g" cy="%g" r="3" fill="#3B2F63"/>' % (cxl, BY))

write(d.svg("One agent, four skills",
            "Claude Code with the vr-dev plugin uses four skills. Headless Blender builds validated assets for Unity; Unity runs "
            "the app on the Meta XR Simulator, driven through the XR Operator and DevRemote; development builds go to a Quest 3 or "
            "3S over adb with a scripted readout. The Horizon OS MCP serves Meta docs, device control and Perfetto traces to every stage."),
      sys.argv[1] if len(sys.argv) > 1 else "toolchain.svg")
