#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace __NS__.App
{
    /// <summary>
    /// The generic agent tools every Quest app wants, registered into AgentTools. Works on any
    /// Meta SDK (served by DevRemote in the editor; by the Operator too where OperatorBridge is
    /// installed). Template from the unity-quest-sim-loop skill: replace __NS__ and __PREFIX__.
    ///
    /// Call AppAgentTools.RegisterAll() once from a bootstrap's Awake (or let the
    /// RuntimeInitializeOnLoad hook below do it). Then write the app's own tools in a second file (see the
    /// DicomSegVR example in references/setup.md): a __PREFIX___get_state with the app's real
    /// state - everything a test would otherwise guess from a picture - and add one tool per thing
    /// an agent needs to DO without a hand (open a tab, load a sample, press a named button).
    /// </summary>
    public static class AppAgentTools
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        public static void RegisterAll()
        {
            AgentTools.Register("__PREFIX___get_scene",
                "__NS__: active scene, time, fps. The app-specific __PREFIX___get_state (what is loaded, which screen) lives in your own tools file.",
                _ => StateJson());

            AgentTools.Register("__PREFIX___get_input_state",
                "__NS__: per side, the active Interaction SDK ray interactor's origin/direction (Unity world) and what it hovers.",
                _ => InputStateJson());

            AgentTools.Register("__PREFIX___snapshot",
                "__NS__: render the centre eye offscreen at any size and vertical fov to a PNG; returns its path. " +
                "Passthrough apps: the background is transparent here - use openxr_capture_composited_image for what the user sees.",
                p => SnapshotJson((int)AgentTools.Num(p, "width", 1600), (int)AgentTools.Num(p, "height", 1200),
                                  AgentTools.Num(p, "fov", 60), AgentTools.Str(p, "name", "snapshot")),
                new AgentTools.Param("width", "number", "Pixels, default 1600."),
                new AgentTools.Param("height", "number", "Pixels, default 1200."),
                new AgentTools.Param("fov", "number", "Vertical field of view in degrees, default 60."),
                new AgentTools.Param("name", "string", "File name stem."));

            AgentTools.Register("__PREFIX___debug_renderers",
                "__NS__: renderers whose hierarchy path contains the text - active, visible, material, shader, texture, " +
                "the colour actually drawn (property block first), queue, layer, bounds.",
                p => RenderersJson(AgentTools.Str(p, "contains")),
                new AgentTools.Param("contains", "string", "Substring of the hierarchy path.", true));
        }

        private static string StateJson()
        {
            // TODO: the app's own state (what is loaded, which screen/tab/mode, what the UI shows).
            return "{\"scene\":" + AgentTools.Q(SceneManager.GetActiveScene().name) +
                   ",\"time\":" + AgentTools.F(Time.time) +
                   ",\"fps\":" + AgentTools.F(Time.smoothDeltaTime > 0 ? Mathf.Round(1f / Time.smoothDeltaTime) : 0) + "}";
        }

        private static string InputStateJson()
        {
            // First ACTIVE ray interactor per side. The ISDK ray comes from the GRIP pose plus Meta's offset,
            // not the OpenXR aim pose - scripts/aimfix.py relies on this answer. Delete if no Interaction SDK.
            var sb = new StringBuilder("{");
            bool left = false, right = false;
            foreach (var ri in Object.FindObjectsByType<Oculus.Interaction.RayInteractor>(FindObjectsSortMode.None))
            {
                if (!ri.isActiveAndEnabled) continue;
                string path = PathOf(ri.transform);
                bool isLeft = path.IndexOf("Left", StringComparison.OrdinalIgnoreCase) >= 0;
                bool isRight = !isLeft && path.IndexOf("Right", StringComparison.OrdinalIgnoreCase) >= 0;
                if ((!isLeft && !isRight) || (isLeft && left) || (isRight && right)) continue;
                if (sb.Length > 1) sb.Append(',');
                var ray = ri.Ray;
                sb.Append(isLeft ? "\"left\":" : "\"right\":")
                  .Append("{\"interactor\":").Append(AgentTools.Q(path))
                  .Append(",\"state\":").Append(AgentTools.Q(ri.State.ToString()))
                  .Append(",\"rayOrigin\":").Append(AgentTools.V3(ray.origin))
                  .Append(",\"rayDirection\":").Append(AgentTools.V3(ray.direction))
                  .Append(",\"hovered\":").Append(AgentTools.Q(ri.Interactable != null ? PathOf(ri.Interactable.transform) : ""))
                  .Append('}');
                if (isLeft) left = true; else right = true;
            }
            return sb.Append('}').ToString();
        }

        private static string SnapshotJson(int width, int height, float fov, string name)
        {
            var rig = Object.FindFirstObjectByType<OVRCameraRig>();
            var eye = rig != null ? rig.centerEyeAnchor : (Camera.main != null ? Camera.main.transform : null);
            var source = eye != null ? eye.GetComponent<Camera>() : null;
            if (source == null) return AgentTools.Error("no centre-eye camera");
            width = Mathf.Clamp(width, 64, 4096);
            height = Mathf.Clamp(height, 64, 4096);

            var go = new GameObject("__PREFIX___snapshot");
            var rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4 };
            try
            {
                var cam = go.AddComponent<Camera>();
                cam.CopyFrom(source);                       // same clear flags, skybox, culling mask, clip planes
                if (UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline == null)
                    cam.stereoTargetEye = StereoTargetEyeMask.None;   // URP warns on every set; renders mono anyway
                cam.transform.SetPositionAndRotation(eye.position, eye.rotation);
                cam.fieldOfView = Mathf.Clamp(fov, 5f, 150f);
                cam.aspect = width / (float)height;
                cam.targetTexture = rt;
                cam.enabled = false;
                cam.Render();

                var prev = RenderTexture.active;
                RenderTexture.active = rt;
                var tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                RenderTexture.active = prev;

                // Editor: <project>/Temp/<prefix>-snapshots (Unity wipes Temp at every launch - copy keepers).
                string dir = System.IO.Path.Combine(Application.isEditor
                    ? System.IO.Path.Combine(Application.dataPath, "../Temp") : Application.persistentDataPath, "__PREFIX__-snapshots");
                System.IO.Directory.CreateDirectory(dir);
                string safe = string.Join("_", (name ?? "snapshot").Split(System.IO.Path.GetInvalidFileNameChars()));
                string path = System.IO.Path.GetFullPath(System.IO.Path.Combine(dir, safe + ".png"));
                System.IO.File.WriteAllBytes(path, tex.EncodeToPNG());
                Object.Destroy(tex);
                return "{\"path\":" + AgentTools.Q(path) + ",\"width\":" + width + ",\"height\":" + height + "}";
            }
            finally
            {
                rt.Release();
                Object.Destroy(rt);
                Object.Destroy(go);
            }
        }

        private static readonly MaterialPropertyBlock _block = new MaterialPropertyBlock();

        private static string RenderersJson(string contains)
        {
            if (string.IsNullOrEmpty(contains)) return AgentTools.Error("contains is required");
            var sb = new StringBuilder("{\"renderers\":[");
            int n = 0;
            foreach (var r in Object.FindObjectsByType<Renderer>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                string path = PathOf(r.transform);
                if (path.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0) continue;
                var m = r.sharedMaterial;
                Texture main = null;
                if (m != null)
                {
                    if (m.HasProperty("_BaseMap")) main = m.GetTexture("_BaseMap");
                    if (main == null && m.HasProperty("_MainTex")) main = m.GetTexture("_MainTex");
                }
                // The colour the renderer DRAWS: a MaterialPropertyBlock overrides the shared material, and
                // per-object colours usually live there. Reading only the material lies.
                string colour = "", source = "material";
                if (r.HasPropertyBlock())
                {
                    r.GetPropertyBlock(_block);
                    if (_block.HasColor("_BaseColor")) { colour = _block.GetColor("_BaseColor").ToString("F2"); source = "propertyBlock"; }
                    else if (_block.HasColor("_Color")) { colour = _block.GetColor("_Color").ToString("F2"); source = "propertyBlock"; }
                }
                if (colour == "" && m != null && m.HasProperty("_BaseColor")) colour = m.GetColor("_BaseColor").ToString("F2");
                else if (colour == "" && m != null && m.HasProperty("_Color")) colour = m.GetColor("_Color").ToString("F2");

                if (n++ > 0) sb.Append(',');
                sb.Append("{\"path\":").Append(AgentTools.Q(path))
                  .Append(",\"active\":").Append(r.gameObject.activeInHierarchy ? "true" : "false")
                  .Append(",\"enabled\":").Append(r.enabled ? "true" : "false")
                  .Append(",\"visible\":").Append(r.isVisible ? "true" : "false")
                  .Append(",\"material\":").Append(AgentTools.Q(m != null ? m.name : "(none)"))
                  .Append(",\"shader\":").Append(AgentTools.Q(m != null && m.shader != null ? m.shader.name : "(none)"))
                  .Append(",\"mainTexture\":").Append(AgentTools.Q(main != null ? main.name + " " + main.width + "x" + main.height : "(none)"))
                  .Append(",\"color\":").Append(AgentTools.Q(colour)).Append(",\"colorSource\":").Append(AgentTools.Q(source))
                  .Append(",\"queue\":").Append(m != null ? m.renderQueue : 0)
                  .Append(",\"layer\":").Append(AgentTools.Q(LayerMask.LayerToName(r.gameObject.layer)))
                  .Append(",\"boundsSize\":").Append(AgentTools.V3(r.bounds.size)).Append('}');
                if (n >= 60) break;
            }
            return sb.Append("],\"count\":").Append(n).Append('}').ToString();
        }

        public static string PathOf(Transform t)
        {
            string path = t.name;
            for (var p = t.parent; p != null; p = p.parent) path = p.name + "/" + path;
            return path;
        }
    }
}
#endif
