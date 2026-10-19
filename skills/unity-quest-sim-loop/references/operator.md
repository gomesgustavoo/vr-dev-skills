# Driving the app through Meta XR Operator

**Meta ships its own Operator skills** inside Core SDK 205+:
`<205 project>/Library/PackageCache/com.meta.xr.sdk.core@*/Editor/MetaXROperator/Skills/`.
The folders are `meta-xr-operator`, `-coordinates`, `-interaction-poke`, `-interaction-grab`,
`-grabbed-objects`, `-unity-test-mechanics` and `-unity-workflow`. They are authoritative for
Interaction SDK pokes and grabs driven by controllers. Two examples:
- **Poke** rides on the **aim** pose, starts outside the surface and pushes in with
  `duration_seconds` 0.5–1.
- **UI buttons fire on release**, so lift before checking.

Read the matching one before a grab or poke test. For apps whose UI takes **fingertip
triggers only** (DicomSegVR), controller pokes don't apply. Use the app's own press and poke
tools (setup.md).

## What's there

The proxy bundles 25 tools that exist before the app registers anything. They list as
`[OFFLINE]` until an app is attached.

| group | tools | notes |
|---|---|---|
| session | `openxr_get_instance_info`, `openxr_get_session_info`, `openxr_get_system_info`, `openxr_get_frame_info`, `openxr_exit_session` | `exit_session` ends Play Mode's XR session; avoid it |
| poses | `openxr_get_head_pose`, `openxr_set_head_pose`, `openxr_get_controller_pose`, `openxr_set_controller_pose` | `duration_seconds` interpolates, which is useful for grabs and drags. `set_head_pose` also re-seeds both controllers (they turn `simulated: true`), so save the grip poses and restore them |
| input | `openxr_set_controller_input`, `openxr_get_active_interaction_profile` | profile check: are controllers bound at all? |
| scene | `openxr_list_spatial_entities` | MR scene anchors |
| capture | `openxr_capture_composited_image` | `{eye}`: the runtime's composited image; works on device and on simulator v207 (v205 said "not instrumented") |
| maths | `math_*`, `convert_unity_pose_to_openxr`, `convert_openxr_pose_to_unity`, `openxr_convert_pose_between_spaces` | the conversions are just the sign flips below |

With the app attached, `OVRManager` also registers Meta's `unity_*` tools: scene graph,
world poses, canvases, and `unity_find_interactables`, which sees uGUI `Selectable`s only.
The app's own `<prefix>_*` tools come on top of those.

Run `python op.py schema TOOL` whenever you're unsure of a parameter. The schemas are
exact, and `additionalProperties` is false, so a misspelled key is an error, not a no-op.

## Coordinates

- OpenXR spaces are right-handed with −z forward; Unity is left-handed with +z forward.
- Between `local_floor` and Unity world (with the rig at the origin): **position**
  `(x, y, z) → (x, y, −z)`, **quaternion** `(x, y, z, w) → (−x, −y, z, w)`. Both maps are
  their own inverse.
- `local_floor` has y = 0 at the floor, and a standing head sits at y ≈ 1.6–1.7.
- If the app recentres or moves the rig, read `openxr_get_head_pose` together with the
  app's own camera pose before assuming the origin.

## Recipes

**Pose both controllers in front of the user, then look.** One batch file keeps one proxy
session, which is faster and deterministic:
```json
[["openxr_set_head_pose", {"position": [0, 1.7, 0], "orientation": [0, 0, 0, 1], "base_space": "local_floor"}],
 ["openxr_set_controller_pose", {"hand": "right", "pose_type": "grip", "position": [0.12, 1.45, -0.3],
   "orientation": [0.3826834, 0, 0, 0.9238795], "base_space": "local_floor"}],
 ["openxr_set_controller_pose", {"hand": "left", "pose_type": "grip", "position": [-0.14, 1.45, -0.3],
   "orientation": [0.3826834, 0, 0, 0.9238795], "base_space": "local_floor"}],
 ["sleep", {"s": 0.4}],
 ["myapp_snapshot", {"width": 1600, "height": 1000, "fov": 95, "name": "wide"}]]
```
`[0.383, 0, 0, 0.924]` is a 45° pitch that points the controllers down at the work area.
To look down, pitch the head with a negative x, e.g. `[-0.2334454, 0, 0, 0.9723699]` = 27°.
Quaternions must be unit length to full precision: compute them as `[sin(a/2)·axis, cos(a/2)]` with 7+
decimals. `0.866` for `0.8660254` made the Interaction SDK log "Quaternion To Matrix conversion failed"
every frame.

**Click a widget through the real input path:**
1. Get the widget's world position from the app (`myapp_list_panels`).
2. `python aimfix.py right 0.15 1.40 0.20 <wx> <wy> <wz>`, which prints the residual error
   and what is hovered.
3. Press:
   `op.py call openxr_set_controller_input '{"hand":"right","component":"Trigger","value":1,"auto_release":true,"hold_duration":0.15}'`.
4. Re-read the state that the click should have changed.

If it didn't change, invoke the widget directly (`myapp_click_widget`):
- Works directly but not through the ray → the aim, the raycast, or the EventSystem path.
- Fails both ways → the handler.

**Grab and move something:** place the grip on it, set `Grip` to 1 (no auto-release), move
with `openxr_set_controller_pose` plus `duration_seconds`, set `Grip` to 0, then read the
object's pose (an app tool, or `unity_get_world_pose`).

**Thumbstick:** `{"hand": "left", "component": "Thumbstick", "sub_component": "X", "value": 0.8, "auto_release": true, "hold_duration": 0.5}`.

**Prove one object's colour (the diff method):** capture ON, toggle only that object off, capture OFF,
toggle back on, capture ON again, then `python imgdiff.py ON.png OFF.png --control ON2.png --expect "#rrggbb"`.
Use the same size and fov for all three. If a UI panel repaints when you click its toggle, add
`--roi x0,y0,x1,y1` around the object. Do it for both composited eyes and the app snapshot when colour
really matters: two independent sources agreeing is the evidence.

**Isolate one structure in a picture:** click "hide all", show the one you want, snapshot
with a narrow fov (20–30°) aimed at it, then restore. This is how you prove "the highlight is
drawn and red" instead of arguing about a crowded frame.

## Reading the answers

- Treat app tool answers as the ground truth for app state. Treat pictures as evidence for
  appearance only.
- A tool that answers `{"error": ..., "tool": ...}` is the app's own try/catch speaking; the
  message is real.
- "External tool callback timed out waiting for main thread" means the app isn't ticking:
  on a device, the headset is off a head; in the editor, it's paused, compiling or stuck.
