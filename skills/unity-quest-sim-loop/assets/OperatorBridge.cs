#if DEVELOPMENT_BUILD || UNITY_EDITOR
using Meta.XR;
using UnityEngine;
using UnityEngine.XR.OpenXR;

namespace __NS__.App
{
    /// <summary>
    /// Forwards every AgentTools tool to Meta XR Operator, so the same tools answer over MCP in the
    /// editor AND on a headset running a development build. Template from the unity-quest-sim-loop
    /// skill: replace __NS__.
    ///
    /// ONLY for Meta XR Core SDK 205+ (MetaXROperatorExternalTool does not exist in 203 - leave this
    /// file out there; DevRemote still serves the tools in the editor). No asmdef versionDefine
    /// guard on purpose: in an Assembly-CSharp project such a symbol is never defined and the file
    /// would silently compile to nothing.
    ///
    /// Do NOT call MetaXROperatorDefaultTools.RegisterAll: OVRManager registers the unity_* tools
    /// itself when the layer is present.
    /// </summary>
    public sealed class OperatorBridge : MonoBehaviour
    {
        private const string AgenticExtension = "XR_METAX1_agentic_external_tool";
        private const string OperatorLayer = "XR_APILAYER_METAX_operator";

        private static bool _layerSeen;
        private float _nextTry;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Boot()
        {
            var go = new GameObject("OperatorBridge") { hideFlags = HideFlags.HideAndDontSave };
            DontDestroyOnLoad(go);
            go.AddComponent<OperatorBridge>();
        }

        private void Update()
        {
            // The OpenXR instance can come up after Start in the editor: retry once a second for a minute.
            if (_layerSeen || Time.unscaledTime > 60f || Time.unscaledTime < _nextTry) return;
            _nextTry = Time.unscaledTime + 1f;
            if (!OperatorAvailable()) return;
            _layerSeen = true;
            foreach (var tool in AgentTools.All) Forward(tool);
            AgentTools.Registered += Forward;   // tools registered later still reach the Operator
            Debug.Log("[__NS__] operator bridge: forwarded the agent tools to Meta XR Operator.");
        }

        private static void Forward(AgentTools.Tool tool)
        {
            var ps = new AgenticToolParameter[tool.Params.Length];
            for (int i = 0; i < ps.Length; i++)
            {
                var p = tool.Params[i];
                ps[i] = new AgenticToolParameter
                {
                    Name = p.Name, Description = p.Description, IsRequired = p.Required,
                    ParamType = p.Type == "number" ? XrAgenticExternalToolParameterTypeMETAX1.Number
                              : p.Type == "boolean" ? XrAgenticExternalToolParameterTypeMETAX1.Boolean
                              : XrAgenticExternalToolParameterTypeMETAX1.String,
                };
            }
            string name = tool.Name;
            MetaXROperatorExternalTool.RegisterAgenticTool(name, tool.Description, ps.Length > 0 ? ps : null,
                args => AgentTools.TryInvoke(name, args, out var result) ? result : result);
        }

        /// <summary>Meta's own test: the extension is enabled, OR the Operator layer is enabled in the OpenXR
        /// API Layers feature (how the EDITOR gets it on OpenXR 1.17+).</summary>
        private static bool OperatorAvailable()
        {
            if (OpenXRRuntime.IsExtensionEnabled(AgenticExtension)) return true;
            var layers = OpenXRSettings.Instance != null
                ? OpenXRSettings.Instance.GetFeature<UnityEngine.XR.OpenXR.Features.ApiLayersFeature>()
                : null;
            return layers != null && layers.enabled && layers.apiLayers != null && layers.apiLayers.IsEnabled(OperatorLayer);
        }
    }
}
#endif
