#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace __NS__.App
{
    /// <summary>
    /// The app's agent tools, written once and served two ways. Template from the
    /// unity-quest-sim-loop skill: replace __NS__.
    ///
    ///   - Over DevRemote (editor, ANY Meta SDK): POST http://127.0.0.1:8731/tool/NAME with the
    ///     JSON arguments as the body; GET /tools lists them. DevRemote finds this class by
    ///     reflection, so the editor assembly needs no reference to it. scripts/op.py merges these
    ///     into its tool list and routes calls, so to an agent they look like Operator tools.
    ///   - Through Meta XR Operator (SDK 205+, editor and development builds): OperatorBridge.cs
    ///     registers every tool here with MetaXROperatorExternalTool, parameters included.
    ///
    /// Why not Operator-only: MetaXROperatorExternalTool does not exist before Meta XR Core SDK
    /// 205, while the Operator's own openxr_* tools work on older SDKs when the layer is loaded
    /// by environment variable (DevXr does that). This keeps app tools available either way.
    ///
    /// Register from a bootstrap's Awake/Start:
    ///   AgentTools.Register("myapp_get_state", "What the app is showing.", _ => StateJson());
    ///   AgentTools.Register("myapp_open_tab", "Open a tab by name.", p => OpenTab(AgentTools.Str(p, "tab")),
    ///       new AgentTools.Param("tab", "string", "Tab name from myapp_get_state.", true));
    /// Every body runs on the main thread (DevRemote and the Operator both marshal to it) and every
    /// exception becomes {"error": ...} - a tool that answers with its own error is far more useful
    /// than one that takes the app down.
    /// </summary>
    public static class AgentTools
    {
        public sealed class Param
        {
            public readonly string Name, Type, Description;
            public readonly bool Required;
            /// <param name="type">"string", "number" or "boolean".</param>
            public Param(string name, string type, string description, bool required = false)
            {
                Name = name; Type = type; Description = description; Required = required;
            }
        }

        public sealed class Tool
        {
            public string Name, Description;
            public Param[] Params;
            public Func<string, string> Body;
        }

        private static readonly Dictionary<string, Tool> _tools = new Dictionary<string, Tool>();

        /// <summary>Raised after each Register, so a bridge can forward tools added late.</summary>
        public static event Action<Tool> Registered;

        public static IEnumerable<Tool> All => _tools.Values;

        // Enter Play Mode Options can skip the domain reload; start every session empty.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetForPlaySession() => _tools.Clear();

        public static void Register(string name, string description, Func<string, string> body, params Param[] parameters)
        {
            var tool = new Tool { Name = name, Description = description, Params = parameters ?? new Param[0], Body = body };
            _tools[name] = tool;
            Registered?.Invoke(tool);
        }

        /// <summary>Called by DevRemote through reflection. Keep the signature.</summary>
        public static bool TryInvoke(string name, string json, out string result)
        {
            if (!_tools.TryGetValue(name ?? "", out var tool))
            {
                result = Error("no tool '" + name + "' (registered: " + string.Join(", ", _tools.Keys) + ")");
                return false;
            }
            try { result = tool.Body(string.IsNullOrWhiteSpace(json) ? "{}" : json) ?? "{}"; }
            catch (Exception e) { result = Error(e.GetType().Name + ": " + e.Message); }
            return true;
        }

        /// <summary>Called by DevRemote through reflection: [{"name","description","params":[...]}].</summary>
        public static string ListJson()
        {
            var sb = new StringBuilder("[");
            bool first = true;
            foreach (var t in _tools.Values)
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append("{\"name\":").Append(Q(t.Name)).Append(",\"description\":").Append(Q(t.Description)).Append(",\"params\":[");
                for (int i = 0; i < t.Params.Length; i++)
                {
                    var p = t.Params[i];
                    if (i > 0) sb.Append(',');
                    sb.Append("{\"name\":").Append(Q(p.Name)).Append(",\"type\":").Append(Q(p.Type))
                      .Append(",\"description\":").Append(Q(p.Description)).Append(",\"required\":").Append(p.Required ? "true" : "false").Append('}');
                }
                sb.Append("]}");
            }
            return sb.Append(']').ToString();
        }

        // ---- tiny JSON helpers, so tools need no JSON package -----------------------------------

        public static string Error(string message) => "{\"error\":" + Q(message) + "}";

        /// <summary>JSON string literal.</summary>
        public static string Q(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s ?? "")
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        public static string V3(Vector3 v) => "{\"x\":" + F(v.x) + ",\"y\":" + F(v.y) + ",\"z\":" + F(v.z) + "}";
        public static string F(float f) => f.ToString("0.#####", System.Globalization.CultureInfo.InvariantCulture);

        /// <summary>A string argument, or the fallback. Flat JSON objects only - enough for tool args.</summary>
        public static string Str(string json, string key, string fallback = "")
        {
            var raw = Raw(json, key);
            if (raw == null || raw.Length < 2 || raw[0] != '"') return fallback;
            return raw.Substring(1, raw.Length - 2).Replace("\\\"", "\"").Replace("\\\\", "\\");
        }

        public static float Num(string json, string key, float fallback = 0f)
        {
            var raw = Raw(json, key);
            return raw != null && float.TryParse(raw, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : fallback;
        }

        public static bool Bool(string json, string key, bool fallback = false)
        {
            var raw = Raw(json, key);
            return raw == "true" ? true : raw == "false" ? false : fallback;
        }

        private static string Raw(string json, string key)
        {
            if (string.IsNullOrEmpty(json)) return null;
            int k = json.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (k < 0) return null;
            int colon = json.IndexOf(':', k + key.Length + 2);
            if (colon < 0) return null;
            int i = colon + 1;
            while (i < json.Length && char.IsWhiteSpace(json[i])) i++;
            if (i >= json.Length) return null;
            if (json[i] == '"')
            {
                int j = i + 1;
                while (j < json.Length && (json[j] != '"' || json[j - 1] == '\\')) j++;
                return j < json.Length ? json.Substring(i, j - i + 1) : null;
            }
            int end = i;
            while (end < json.Length && json[end] != ',' && json[end] != '}' && !char.IsWhiteSpace(json[end])) end++;
            return json.Substring(i, end - i);
        }
    }
}
#endif
