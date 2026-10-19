using System;
using System.Collections.Generic;
using System.Net;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEditor.Compilation;
using UnityEngine;

namespace __NS__.EditorTools
{
    /// <summary>
    /// A four-route HTTP server that lets a script enter and leave Play Mode.
    ///
    /// WHY NOT THE UNITY MCP BRIDGE. Unity ships one (com.unity.ai.assistant), and on this
    /// machine it answers every AI client with "Connection revoked" - a known regression
    /// the sibling project documented at length after losing a day to it. Meta's own
    /// AI Agent Bridge has compilation and test-runner tools but no way to press Play.
    /// Meta XR Operator, which is the thing worth driving, only exists once the app is
    /// RUNNING. So the single missing verb in the whole desktop loop is "start playing",
    /// and this supplies exactly that and nothing else.
    ///
    /// It is off by default and opt-in per machine (EditorPrefs), it binds to loopback
    /// only, and it exposes no way to read or write project files - the surface is four
    /// verbs a developer could do with two clicks.
    ///
    ///     GET  /status   {"isPlaying":false,"isCompiling":false,"errors":[...]}
    ///     POST /play     enter Play Mode
    ///     POST /stop     leave Play Mode
    ///     POST /compile  request a script compilation
    ///     POST /refresh  import changed assets (shaders, textures) without editor focus
    ///     GET  /tools        the app's agent tools (AgentTools.ListJson), in Play Mode
    ///     POST /tool/NAME    call one; body = JSON arguments; answer = the tool's JSON
    ///
    /// The /tool routes serve AgentTools (runtime) over HTTP, so an app's own tools work on ANY
    /// Meta SDK - including those without MetaXROperatorExternalTool (pre-205). AgentTools is
    /// found by reflection: no reference from this editor assembly, and a project without it
    /// still compiles (the routes then answer an error).
    ///
    /// THE LISTENER MUST DIE BEFORE A DOMAIN RELOAD. Unity tears the managed domain down
    /// on every script compile; a listener left bound keeps the port until the editor
    /// exits, and the next reload then fails to bind with an error that reads like a
    /// permissions problem. AssemblyReloadEvents.beforeAssemblyReload is the hook.
    ///
    /// If binding is refused outright (HttpListenerException 5), Windows needs a one-time
    /// URL reservation:
    ///     netsh http add urlacl url=http://127.0.0.1:8731/ user=%USERNAME%
    ///
    /// Menu: __MENU__ > Dev > Remote Control (toggle). Template from the unity-quest-sim-loop skill:
    /// replace __NS__ (root namespace) and __MENU__ (menu root).
    /// </summary>
    [InitializeOnLoad]
    public static class DevRemote
    {
        private const string EnabledKey = "__NS__.DevRemote";
        /// <summary>8731 first. If it stays taken, the next free one up to 8739 - see Start().</summary>
        private const int FirstPort = 8731, LastPort = 8739;
        private static int _port = FirstPort;
        private static string Prefix => "http://127.0.0.1:" + _port + "/";
        private const int MaxErrors = 40;

        private static HttpListener _listener;
        private static Thread _thread;

        /// <summary>Work the HTTP thread needs done on the main thread, and its answer.</summary>
        private static readonly Queue<Action> _pending = new Queue<Action>();

        private static readonly List<string> _errors = new List<string>();

        static DevRemote()
        {
            // Asset-import WORKERS are Unity.exe processes that load the editor assemblies
            // too. One of them bound 8731 before the editor did, so the editor could not, and
            // every request went to a process with no Play Mode to press.
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;

            EditorApplication.update += Pump;
            EditorApplication.update += RetryBind;
            Application.logMessageReceived += OnLog;
            AssemblyReloadEvents.beforeAssemblyReload += Stop;
            // Also let go BEFORE the Play Mode reload begins: a listener still bound when the
            // domain went down (a reload that came with a forced recompile) leaked its socket
            // for the life of the process, and every later bind in this editor failed.
            EditorApplication.playModeStateChanged += s =>
            {
                if (s == PlayModeStateChange.ExitingEditMode || s == PlayModeStateChange.ExitingPlayMode) Stop();
                // Leaving Play Mode reloads the domain only when a script changed meanwhile. Without
                // one this static constructor never runs again, so a clean stop left the remote dark
                // for the rest of the session (reload.py / run_scenario.py timed out, and the next
                // agent had to kill the editor). Come back up on arrival instead; Start() is a no-op
                // when a reload already started it.
                else if ((s == PlayModeStateChange.EnteredEditMode || s == PlayModeStateChange.EnteredPlayMode) &&
                         EditorPrefs.GetBool(EnabledKey, false)) Start();
            };
            EditorApplication.quitting += Stop;

            if (EditorPrefs.GetBool(EnabledKey, false)) Start();
        }

        [MenuItem("__MENU__/Dev/Remote Control (toggle)")]
        private static void Toggle()
        {
            bool on = !EditorPrefs.GetBool(EnabledKey, false);
            EditorPrefs.SetBool(EnabledKey, on);
            if (on) Start(); else Stop();
        }

        [MenuItem("__MENU__/Dev/Remote Control (toggle)", true)]
        private static bool ToggleValidate()
        {
            Menu.SetChecked("__MENU__/Dev/Remote Control (toggle)",
                EditorPrefs.GetBool(EnabledKey, false));
            return true;
        }

        /// <summary>Headless entry: turn it on for this project and exit.</summary>
        public static void CliEnable()
        {
            EditorPrefs.SetBool(EnabledKey, true);
            Debug.Log("[__NS__] dev remote enabled; it starts with the next editor load.");
            EditorApplication.Exit(0);
        }

        /// <summary>Turn the remote on for this machine and start it now (DevXr.CliPlay calls this).</summary>
        public static void EnsureRunning()
        {
            EditorPrefs.SetBool(EnabledKey, true);
            Start();
        }

        private static void Start()
        {
            if (_listener != null) return;

            try
            {
                _listener = new HttpListener();
                _listener.Prefixes.Add(Prefix);
                _listener.Start();
            }
            catch (Exception e)
            {
                _listener = null;
                // A port still held by an editor that was just killed frees itself within
                // seconds; giving up here left the whole session without a remote. Retry for
                // a minute before concluding it is a real conflict.
                // After ~10 s the holder is not a dying editor but a socket leaked inside THIS
                // process, which no retry frees: move to the next port and say where.
                if (_bindAttempts >= 5 && _port < LastPort)
                {
                    _port++;
                    _bindAttempts = 0;
                    _retryAt = EditorApplication.timeSinceStartup + 0.5;
                    return;
                }
                if (_bindAttempts++ < 30)
                {
                    _retryAt = EditorApplication.timeSinceStartup + 2.0;
                    if (_bindAttempts == 1)
                        Debug.Log("[__NS__] dev remote: " + Prefix + " busy (" + e.Message + "); retrying.");
                    return;
                }
                Debug.LogWarning("[__NS__] dev remote could not bind " + Prefix + ": " +
                                 e.Message + "\nOne-time fix on Windows: netsh http add urlacl " +
                                 "url=" + Prefix + " user=%USERNAME%");
                return;
            }

            _thread = new Thread(Serve) { IsBackground = true, Name = "__NS__ DevRemote" };
            _thread.Start();
            Debug.Log("[__NS__] dev remote listening on " + Prefix);
            // Scripts find a non-default port by probing 8731-8739, or read it here.
            try { System.IO.File.WriteAllText(System.IO.Path.Combine(Application.dataPath, "../Temp/DevRemote.port"), _port.ToString()); }
            catch { }
        }

        private static int _bindAttempts;
        private static double _retryAt = -1.0;

        private static void RetryBind()
        {
            if (_listener != null || _retryAt < 0.0 || EditorApplication.timeSinceStartup < _retryAt) return;
            _retryAt = -1.0;
            if (EditorPrefs.GetBool(EnabledKey, false)) Start();
        }

        private static void Stop()
        {
            if (_listener == null) return;
            // Abort, not just Stop: it closes the listening socket even with a GetContext pending.
            try { _listener.Abort(); } catch { }
            try { _listener.Close(); } catch { }
            _listener = null;
            _thread = null;
        }

        private static void Serve()
        {
            while (true)
            {
                HttpListenerContext ctx;
                var listener = _listener;
                if (listener == null) return;
                try { ctx = listener.GetContext(); }
                catch { return; } // Stop() closed it, or the domain is going away.

                string body;
                try { body = Handle(ctx); }
                catch (Exception e) { body = Json("error", e.Message); }

                var bytes = Encoding.UTF8.GetBytes(body);
                try
                {
                    ctx.Response.ContentType = "application/json";
                    ctx.Response.ContentLength64 = bytes.Length;
                    ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
                    ctx.Response.OutputStream.Close();
                }
                catch { }
            }
        }

        /// <summary>
        /// Runs on the HTTP thread. Everything that touches the editor is marshalled and
        /// waited on, because every Unity API here is main-thread only.
        /// </summary>
        private static string Handle(HttpListenerContext ctx)
        {
            string path = ctx.Request.Url.AbsolutePath.TrimEnd('/');
            string answer = null;

            if (path == "/tools" || path.StartsWith("/tool/", StringComparison.Ordinal))
            {
                string name = path == "/tools" ? null : Uri.UnescapeDataString(path.Substring("/tool/".Length));
                string body = null;
                if (name != null && ctx.Request.HasEntityBody)
                    using (var reader = new System.IO.StreamReader(ctx.Request.InputStream, Encoding.UTF8))
                        body = reader.ReadToEnd();
                RunOnMain(() => answer = CallAgentTools(name, body));
                return answer ?? Json("error", "the editor did not answer in time (compiling, or the tool is slow)");
            }

            switch (path)
            {
                case "/status":
                case "":
                    RunOnMain(() => answer = Status());
                    break;
                case "/play":
                    RunOnMain(() =>
                    {
                        if (!EditorApplication.isPlaying)
                        {
                            // The same words DevXr's auto-play logs, so one marker scopes a log
                            // scan to "this Play session" however Play was pressed.
                            Debug.Log("[__NS__] dev remote: entering Play Mode.");
                            EditorApplication.EnterPlaymode();
                        }
                        answer = Status();
                    });
                    break;
                case "/stop":
                    RunOnMain(() =>
                    {
                        if (EditorApplication.isPlaying) EditorApplication.ExitPlaymode();
                        answer = Status();
                    });
                    break;
                case "/refresh":
                    // Import changed assets now. The editor only auto-refreshes when it has
                    // focus, so a shader edited from outside sat unimported behind a
                    // background editor.
                    RunOnMain(() =>
                    {
                        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                        answer = Status();
                    });
                    break;
                case "/compile":
                    RunOnMain(() =>
                    {
                        CompilationPipeline.RequestScriptCompilation();
                        answer = Status();
                    });
                    break;
                default:
                    ctx.Response.StatusCode = 404;
                    return Json("error", "no route " + path);
            }

            return answer ?? Json("error", "the editor did not answer in time (compiling?)");
        }

        private static System.Reflection.MethodInfo _tryInvoke, _listJson;

        /// <summary>Main thread. name == null lists the tools; otherwise calls one.</summary>
        private static string CallAgentTools(string name, string body)
        {
            if (!EditorApplication.isPlaying) return Json("error", "not in Play Mode - agent tools exist only while the app runs");
            if (_tryInvoke == null || _listJson == null)
            {
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    string an = asm.GetName().Name;
                    if (an.StartsWith("Unity") || an.StartsWith("System") || an.StartsWith("Mono") || an.StartsWith("mscorlib")) continue;
                    Type[] types;
                    try { types = asm.GetTypes(); } catch (System.Reflection.ReflectionTypeLoadException e) { types = e.Types; }
                    foreach (var t in types)
                    {
                        if (t == null || t.Name != "AgentTools" || !t.IsAbstract || !t.IsSealed) continue;
                        _tryInvoke = t.GetMethod("TryInvoke");
                        _listJson = t.GetMethod("ListJson");
                        if (_tryInvoke != null && _listJson != null) break;
                    }
                    if (_tryInvoke != null && _listJson != null) break;
                }
                if (_tryInvoke == null || _listJson == null)
                    return Json("error", "no AgentTools class in the project (add assets/AgentTools.cs from the skill)");
            }
            if (name == null) return (string)_listJson.Invoke(null, null);
            var args = new object[] { name, body ?? "{}", null };
            _tryInvoke.Invoke(null, args);
            return (string)args[2];
        }

        private static void RunOnMain(Action action)
        {
            using (var done = new ManualResetEventSlim(false))
            {
                lock (_pending)
                {
                    _pending.Enqueue(() =>
                    {
                        try { action(); }
                        finally { done.Set(); }
                    });
                }
                // Bounded: while Unity compiles, EditorApplication.update does not tick,
                // and an unbounded wait would hang the caller for the whole compile.
                done.Wait(10000);
            }
        }

        private static void Pump()
        {
            while (true)
            {
                Action next;
                lock (_pending)
                {
                    if (_pending.Count == 0) return;
                    next = _pending.Dequeue();
                }
                try { next(); }
                catch (Exception e) { Debug.LogError("[__NS__] dev remote: " + e); }
            }
        }

        private static void OnLog(string message, string stack, LogType type)
        {
            if (type != LogType.Error && type != LogType.Exception && type != LogType.Assert) return;
            lock (_errors)
            {
                _errors.Add(message);
                if (_errors.Count > MaxErrors) _errors.RemoveAt(0);
            }
        }

        private static string Status()
        {
            var sb = new StringBuilder();
            sb.Append("{\"isPlaying\":").Append(EditorApplication.isPlaying ? "true" : "false");
            sb.Append(",\"isCompiling\":").Append(EditorApplication.isCompiling ? "true" : "false");
            sb.Append(",\"isPaused\":").Append(EditorApplication.isPaused ? "true" : "false");
            sb.Append(",\"errors\":[");
            lock (_errors)
            {
                for (int i = 0; i < _errors.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(Quote(_errors[i]));
                }
            }
            sb.Append("]}");
            return sb.ToString();
        }

        [MenuItem("__MENU__/Dev/Clear Remote Error Log")]
        private static void ClearErrors()
        {
            lock (_errors) _errors.Clear();
        }

        private static string Json(string key, string value) =>
            "{\"" + key + "\":" + Quote(value) + "}";

        private static string Quote(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s ?? string.Empty)
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
    }
}
