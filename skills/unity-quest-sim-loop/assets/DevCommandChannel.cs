#if DEVELOPMENT_BUILD || UNITY_EDITOR
using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace __NS__.App
{
    /// <summary>
    /// The app's agent tools over adb, for a development build WITHOUT the Meta XR Operator
    /// layer. Template from the unity-quest-sim-loop skill: replace __NS__ and __PREFIX__
    /// (e.g. "myapp"), create one from the bootstrap and call Tick(Time.unscaledTime) in Update.
    ///
    /// WHY (2026-09-26, a production SDK 205 app). After a Horizon OS update every development APK carrying
    /// the SDK 205 Operator layer aborted at launch ("FORTIFY: pthread_mutex_lock called on a
    /// destroyed mutex" inside libXrApiLayer_METAX_operator: Unity's OpenXR plugin creates and
    /// destroys a throwaway instance, the layer tears its MCP server down on that first destroy,
    /// and the thread it starts for the real instance locks the freed mutex). Build without the
    /// layer (OperatorLayerExclusion) and serve the same AgentTools through a file instead;
    /// scripts/adbtools.py is the host side.
    ///
    /// PROTOCOL. The host pushes <see cref="CommandFile"/> into Application.persistentDataPath
    /// under a temporary name and renames it (never read half-written): one {id, tool, args}
    /// object or an array of them. The app reads and deletes it, runs each through
    /// AgentTools.TryInvoke on the main thread, and appends {id, tool, t, result} lines to
    /// <see cref="OutputFile"/>. Five checks a second, one File.Exists when idle.
    /// </summary>
    public sealed class DevCommandChannel
    {
        public const string CommandFile = "__PREFIX__-cmd.json";
        public const string OutputFile = "__PREFIX__-out.jsonl";
        private const float PollSeconds = 0.2f;

        private readonly string _cmd, _out;
        private float _next;

        public DevCommandChannel()
        {
            string dir = Application.persistentDataPath;
            _cmd = Path.Combine(dir, CommandFile);
            _out = Path.Combine(dir, OutputFile);
            Debug.Log("[DevCommandChannel] write " + _cmd + ", read " + _out);
        }

        public void Tick(float now)
        {
            if (now < _next) return;
            _next = now + PollSeconds;
            if (!File.Exists(_cmd)) return;

            string text;
            try
            {
                text = File.ReadAllText(_cmd);
                File.Delete(_cmd);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[DevCommandChannel] could not read " + _cmd + ": " + e.Message);
                return;
            }

            // Minimal parsing without a JSON dependency: the host always sends one object per line
            // of an array, each {"id":"...","tool":"...","args":{...}}. Projects with
            // Newtonsoft.Json should parse properly.
            foreach (var call in Split(text))
            {
                string id = AgentTools.Str(call, "id");
                string tool = AgentTools.Str(call, "tool");
                string args = Field(call, "args") ?? "{}";
                // An unknown tool comes back as {"error": ...} listing the registered ones.
                AgentTools.TryInvoke(tool, args, out string result);
                Append("{\"id\":" + AgentTools.Q(id) + ",\"tool\":" + AgentTools.Q(tool) +
                       ",\"t\":" + AgentTools.F(Time.realtimeSinceStartup) + ",\"result\":" + AsJson(result) + "}");
            }
        }

        private void Append(string line)
        {
            try { File.AppendAllText(_out, line + "\n"); }
            catch (Exception e) { Debug.LogWarning("[DevCommandChannel] could not write " + _out + ": " + e.Message); }
        }

        private static string AsJson(string result)
        {
            string t = (result ?? "").Trim();
            return t.StartsWith("{") || t.StartsWith("[") ? t : AgentTools.Q(result);
        }

        /// <summary>Top-level objects of an object or an array, by brace depth (strings respected).</summary>
        private static System.Collections.Generic.IEnumerable<string> Split(string text)
        {
            int depth = 0, start = -1;
            bool inString = false, escape = false;
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (inString)
                {
                    if (escape) escape = false;
                    else if (c == '\\') escape = true;
                    else if (c == '"') inString = false;
                    continue;
                }
                if (c == '"') inString = true;
                else if (c == '{') { if (depth++ == 0) start = i; }
                else if (c == '}' && --depth == 0 && start >= 0) { yield return text.Substring(start, i - start + 1); start = -1; }
            }
        }

        /// <summary>The raw JSON value of a top-level key whose value is an object.</summary>
        private static string Field(string obj, string key)
        {
            int k = obj.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (k < 0) return null;
            int b = obj.IndexOf('{', k);
            if (b < 0) return null;
            int depth = 0;
            for (int i = b; i < obj.Length; i++)
            {
                if (obj[i] == '{') depth++;
                else if (obj[i] == '}' && --depth == 0) return obj.Substring(b, i - b + 1);
            }
            return null;
        }
    }
}
#endif
