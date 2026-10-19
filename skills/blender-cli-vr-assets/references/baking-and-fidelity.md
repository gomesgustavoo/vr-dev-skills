# Baking for Quest and measuring fidelity

The contract that makes a Cycles-quality room cost almost nothing on a Quest: **bake the full light, display-referred,
into atlases and draw them unlit.** An unlit sample then reproduces the reference pixel, so the person who judges the
asset by the Cycles renders sees the same thing in the headset, and the GPU spends no time on lighting. Then
**measure** that claim per shot instead of eyeballing it.

## 1. One look definition

Put materials, lights, bounce counts, the view transform and the Cycles device choice in one module (`lookdev.py`)
that the build, bake and preview stages all import. A light that reaches the bake and not the reference (or the other
way round) is the most common source of a fidelity gap that nobody can explain.

Lights that only exist for baking live in the stage file but outside the export root (they never reach the FBX).
Make area lights invisible to camera rays (`obj.visible_camera = False`) and model the visible fixture as an emissive
mesh - then the reference and the atlas both show the fixture, not the light primitive.

## 2. The view transform

Render the reference with **Standard, look None, exposure 0, gamma 1, sRGB display**, and encode the atlas through the
same view. A `--factory-startup` scene defaults to **AgX**, so every stage that renders or encodes sets the view
explicitly - otherwise the bake gets one tone curve and the preview another. Standard is per-channel and needs no
tone mapping in Unity; AgX / Filmic would have to be reproduced by Unity's post stack, which an unlit Quest
shader does not run.

Encode with **Blender's own transform**, not a hand-written sRGB curve:
* simplest (the example's `lookdev.encode_display`): put the linear bake in a float image (colorspace
  `Linear Rec.709`), `image.save_render(path, scene=scene)` as an 8-bit PNG, load it back as `Non-Color`;
* or measure a 1-D LUT once per process by saving a 4096-sample linear ramp the same way (valid for per-channel views;
  for Standard the treatment-room pipeline measured ~1e-5 from the piecewise sRGB curve) and apply it with `np.interp`.
Set `scene.render.dither_intensity = 0`: dither adds noise to every 8-bit output.

## 3. What to bake

Atlas RGB = `encode(view)(albedo x (direct + indirect diffuse) + emission)`:
* `bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT", "COLOR"})` + a separate `EMIT` bake, summed in float.
  Not `COMBINED`: it adds the glossy term seen from the bake's arbitrary direction, which is wrong from every other
  view. The glossy part belongs to a cheap runtime reflection term (gloss in alpha, section 6).
* Optional exposure normalisation (the treatment room scaled the room bake so the 75th-percentile wall irradiance hit a
  target): whatever factor you apply to the atlas must also apply to the reference, or the gate measures the factor.

**Bake sets for moving parts.** A shadow baked onto a surface is only right while its caster stays put.
* Static scene (room + static machine parts): bake with every moving part hidden (`hide_render = True`) - otherwise
  the arm's shadow is frozen onto the floor and stays there when the arm moves.
* Each moving part: bake in the REST pose, seeing the static scene, itself, and only the parts that never move
  relative to it, or whose shadow on it is invariant under the relative motion (two lathes about the same axis).
  Record these "casters" in the manifest.
* What the bake leaves out (moving-part shadows on the room and on each other) is a runtime job: contact-shadow quads
  (section 7), blob shadows, or per-vertex relighting relative to the rest pose.

**Margins.** A per-object or per-set bake treats the other objects' islands as empty and writes its margin over them
(black blotches). Bake every set with `margin=0` into one image (`use_clear` only on the first), then dilate in numpy:
fill the gutters from the valid neighbours for `2 x island margin + 2` rings and give the unused texels the mean
colour (no dark halo in the far mips). Dilate the gloss alpha the same way.

**UVs.** One UV map per mesh (one name, e.g. `UVAtlas`), all islands of an atlas packed together, never overlapping,
never rotated or aspect-corrected headless (see pitfalls.md). Weight the texel density by what users look at (scale an
object's UVs before `pack_islands(scale=True)`; the treatment room's head cover got 1.8x, a hidden back disc 0.25x).
Never weld separate colour primitives: a colour edge inside an island aliases into stair-steps at bake resolution; as
separate islands it is a crisp island edge.

**Device.** OptiX, else CUDA (HIP / Metal / oneAPI where they exist), else CPU; record the one that ran. It is a
byte-affecting input: in the hello-room example CPU bakes repeat byte for byte, OptiX bakes differ run to run by
1/255 in a few texels, and CPU vs OptiX differ in 0.2 % of texels by up to 3/255 (the FBX never changes).
Samples: the example converges at 256 spp for a 1024 atlas; the treatment room used 384 spp for the lit room and
1024 spp for the moving rest-pose bake. Bakes are not denoised here - pay with samples.

## 4. Write the atlas correctly

* 8-bit RGBA PNG written from a **BYTE** image (`images.new(..., float_buffer=False)`, `alpha_mode = "CHANNEL_PACKED"`).
  Blender premultiplies float buffers, and saving a premultiplied float image divides RGB by alpha: with gloss in
  alpha, every matte texel (alpha 0) loses its colour.
* Load atlases for shading with `alpha_mode = "CHANNEL_PACKED"` so the alpha never premultiplies the colour.
* Gate it: IHDR says 8-bit RGBA at the contract size; matte texels keep their RGB; the alpha values inside the
  islands are the materials' gloss values.
* Power-of-two sizes, <= 4096^2 (the budget table in SKILL.md).

## 5. Previews: reference, unlit, mask, cameras.json

Per shot, from the same stage file, never saved:
* `previews/` - the REFERENCE: the authoring materials path-traced under the look definition, denoised. Exception:
  OIDN has no albedo guide on an emission closure and softens emissive textures - render emissive surfaces (or a
  room drawn as emission of its atlas) without the denoiser and composite by mask, as the treatment-room previews did.
* `previews_unlit/` - every surface the emission of its atlas texel, no denoise (nothing to denoise, and denoising
  would blur it). This is what the Quest shows before any runtime relight / reflection.
* `previews_mask/` - flat emission per group (R room, G static machine, B moving parts), rendered with the **Raw**
  view so coverage stays linear; overlays (captions, axes) black so they drop out of every region.
* `cameras.json` - each shot in UNITY coordinates (`positionUnity`, `targetUnity`, `upUnity`, `verticalFovDeg`,
  `aspect`, `resolution`, `nearClipM`, the pose) and the `stage_sha256` it was rendered from. Blender's camera:
  `rotation = (target - loc).to_track_quat("-Z", "Y")` is Unity's `LookRotation(target - pos, up)`; Blender's lens
  with a horizontal sensor fit gives the horizontal FOV, Unity wants the vertical one.

## 6. Gloss in alpha, env map

`gloss = clamp((0.61 - roughness) / 0.65 + 0.25 metallic, 0, 1)` per authoring Principled BSDF (white plastic 0.6,
brushed metal 0.68, rubber / concrete 0): an `EMIT` bake with each material's Surface temporarily routed to
`Emission(gloss)`. Unity adds one reflection fetch scaled by it. For the reflection, render an equirectangular map of
the static scene (emitting its atlases) from a representative point, leave the moving parts out (a part must not
reflect itself), and pin the mapping with a calibration render that exits non-zero if the orientation is off
(treatment room: `u = 0.5 + atan2(d.x, d.z) / 2pi`, `v = 0.5 + asin(d.y) / pi` in the Unity frame).

## 7. Contact shadows for moving parts

Quads a few millimetres above the floor under each moving assembly (7 mm in the treatment room), parented to the joint
that carries it, textured with the irradiance RATIO with / without the caster (grayscale, sRGB-encoded, 1 = no shadow),
drawn multiply with ZWrite off. Because the ratio is relative to the light the floor was baked with, nothing is counted
twice. Keep the quads' camera ray visibility ON while baking them (see pitfalls.md: a bake target with camera
visibility off bakes zeros); drop the other ray types so they do not shade anything else.

## 8. The metric and the gate

`scripts/fidelity.py`, per shot and region:
* **SSIM** - `skimage.metrics.structural_similarity` on 8-bit sRGB, Gaussian weights sigma 1.5,
  `use_sample_covariance=False`, `data_range=255` (Wang et al. 2004), the full map averaged over the region (mean of
  the 3 channels). Structure: noise, blur, missing edges, misaligned geometry.
* **CIEDE2000** - `rgb2lab` (sRGB, D65) then `deltaE_ciede2000` per pixel; mean and p95 over the region. Colour and
  brightness: a wrong view transform, exposure or gamma shows here first.
* **Regions** from the mask: gate the region the bake is responsible for ("machine" = G + B), report the rest.
* **Target**: SSIM >= 0.85 and mean dE <= 6 per shot. Below ~2 a difference is hard to see side by side; 3 - 6 is
  visible in a montage (the treatment room shipped at ~3.7, the remainder being the expected gaps below).

Measured with this method: the treatment room (the worked example in SKILL.md), Unity frames vs the Cycles
previews, machine region mean SSIM 0.898 / mean dE 3.72, 6 of 6 shots on target; the hello-room example, unlit vs
reference, 0.905 / 3.87 at `--quick` and 0.940 / 3.75 at full quality.

Run the same script on Unity captures of the `cameras.json` shots (`--test <unity frames> --resize-test` if the
capture size differs): one metric for "the bake matches Cycles" and "Unity matches the bake".

## 9. Expected gaps (say them in the report, do not chase them)

* the glossy coat of shiny / dark surfaces (not baked by design; the runtime reflection term covers part of it);
* the moving parts' shadows on the room and on each other (baked without them by design);
* poses away from rest (the bake is a rest-pose bake; relight or accept);
* bake and reference noise (more samples; never "fix" it by blurring the reference);
* resolution in close-ups (texel density; check texel / mm per part);
* anti-aliasing: Cycles' pixel filter vs Unity MSAA - a thin 1-2 px band along every edge in the dE heat map.
Read `previews_compare/` (reference | test | dE heat, black 0 .. white >= 12): a gap that follows edges is AA or
alignment, a gap that fills a whole surface is colour / exposure / a missing light, a speckle is noise.
