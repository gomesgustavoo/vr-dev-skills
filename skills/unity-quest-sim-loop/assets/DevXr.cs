using System;
using System.Linq;
using UnityEditor;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;
using UnityEngine.XR.OpenXR.Features.Interactions;

namespace __NS__.EditorTools
{
    /// <summary>
    /// Turn the desktop into a test rig: OpenXR in editor Play Mode, the Meta XR Simulator as
    /// the runtime, and the Meta XR Operator API layer so an agent can drive the app.
    /// Template from the unity-quest-sim-loop skill: replace __NS__, __MENU__ and __SCENE__
    /// (the scene to play, e.g. "Assets/Scenes/Main.unity"). The editor assembly needs
    /// Unity.XR.Management(.Editor) and Unity.XR.OpenXR(.Editor) if it has an asmdef.
    ///
    /// THREE THINGS HAVE TO BE TRUE and each fails silently on its own:
    ///   1. A STANDALONE OpenXR loader exists (ApplyStandalone). An Android-only project has
    ///      none, so Play Mode starts no OpenXR session and nothing can attach.
    ///   2. The Operator is activated: registers its layer in the Standalone OpenXR API Layers
    ///      feature. Persisted (EditorPrefs + settings asset).
    ///   3. The simulator is the active runtime: Meta sets XR_RUNTIME_JSON with
    ///      Environment.SetEnvironmentVariable - PROCESS scope - so it does NOT survive an
    ///      editor restart. The InitializeOnLoad hook re-applies it every session.
    ///
    /// Meta's activation classes are internal; their menu items are the public surface.
    /// ExecuteMenuItem returns false when the item is disabled (already active, or binaries
    /// missing), so the result is logged, never assumed.
    ///
    /// Cold start with no human:  Unity.exe -projectPath . -executeMethod __NS__.EditorTools.DevXr.CliPlay
    /// (scripts/editor-play.ps1 does that and answers the scene-recovery dialog).
    /// </summary>
    [InitializeOnLoad]
    public static class DevXr
    {
        private const string EnabledKey = "__NS__.DevXr";
        private const string AutoPlayKey = "__NS__.DevXr.AutoPlay";
        private const string ScenePath = "__SCENE__";

        /// <summary>Editor frames to wait after the domain settles before entering Play Mode.
        /// EnterPlaymode during an import is ignored or bounces straight back out.</summary>
        private const int AutoPlayDelayFrames = 120;

        private const string OperatorActivate = "Meta/Meta XR Operator/Activate";
        private const string OperatorStatus = "Meta/Meta XR Operator/Status";
        private const string SimulatorActivate = "Meta/Meta XR Simulator/Activate";
        private const string SimulatorDeactivate = "Meta/Meta XR Simulator/Deactivate";
        private const string SelectedRuntimeEnv = "XR_SELECTED_RUNTIME_JSON";

        private static int _autoPlayCountdown;

        static DevXr()
        {
            // Asset-import WORKERS are Unity.exe processes that load editor assemblies too. They
            // have no Play Mode and must not consume the auto-play pref or touch the simulator.
            if (AssetDatabase.IsAssetImportWorkerProcess()) return;

            if (EditorPrefs.GetBool(AutoPlayKey, false) && !EditorApplication.isPlayingOrWillChangePlaymode)
            {
                _autoPlayCountdown = AutoPlayDelayFrames;
                EditorApplication.update += PumpAutoPlay;
            }

            EditorApplication.playModeStateChanged += LoadOperatorLayerOnOlderSdks;

            if (!EditorPrefs.GetBool(EnabledKey, false)) return;
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable(SelectedRuntimeEnv))) return;

            // delayCall: menu items are not all registered inside a static constructor.
            EditorApplication.delayCall += () =>
            {
                bool ok = EnsureSimulatorRuntime();
                Debug.Log("[__NS__] dev XR: re-activated the simulator for this editor session (" +
                          (ok ? "ok" : "menu item unavailable - already active, or not installed") + ").");
            };
        }

        /// <summary>
        /// Meta XR Operator on a Meta SDK that does not ship it (before Core SDK 205).
        ///
        /// The Operator is a plain OpenXR API layer (a DLL + JSON manifest), independent of the SDK's
        /// C#. Meta's own enabler loads it for Play Mode by setting XR_API_LAYER_PATH and
        /// XR_ENABLE_API_LAYERS on ExitingEditMode and clearing them on EnteredEditMode; this does the
        /// same with a copy of the layer kept outside the project (%USERPROFILE%\meta-xr-operator\layer\x64,
        /// or META_XR_OPERATOR_LAYER_DIR). The openxr_* tools (poses, input, composited capture) then work;
        /// the app's own tools come through DevRemote's /tool routes instead of the Operator.
        /// Skipped when the SDK has Meta's activator - that one owns the layer.
        /// </summary>
        private static void LoadOperatorLayerOnOlderSdks(PlayModeStateChange state)
        {
            if (!EditorPrefs.GetBool(EnabledKey, false)) return;
            if (Type.GetType("Meta.XR.Editor.MetaXROperatorActivator, Meta.XR.Editor.MetaXROperator") != null) return;

            if (state == PlayModeStateChange.ExitingEditMode)
            {
                string dir = null;
                foreach (var candidate in new[]
                {
                    Environment.GetEnvironmentVariable("META_XR_OPERATOR_LAYER_DIR"),
                    System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "meta-xr-operator", "layer", "x64"),
                })
                {
                    if (!string.IsNullOrEmpty(candidate) && System.IO.File.Exists(System.IO.Path.Combine(candidate, "XrApiLayer_METAX_operator.json")))
                    { dir = candidate; break; }
                }
                if (dir == null)
                {
                    Debug.LogWarning("[__NS__] dev XR: this Meta SDK has no Operator and no layer copy was found - copy " +
                                     "Editor/MetaXROperator/x64 from a com.meta.xr.sdk.core 205+ package to %USERPROFILE%\\meta-xr-operator\\layer\\x64.");
                    return;
                }
                Environment.SetEnvironmentVariable("XR_API_LAYER_PATH", dir);
                Environment.SetEnvironmentVariable("XR_ENABLE_API_LAYERS", "XR_APILAYER_METAX_operator");
                Debug.Log("[__NS__] dev XR: Meta XR Operator layer loaded for Play Mode from " + dir + " (SDK without a built-in Operator).");
            }
            else if (state == PlayModeStateChange.EnteredEditMode)
            {
                Environment.SetEnvironmentVariable("XR_API_LAYER_PATH", null);
                Environment.SetEnvironmentVariable("XR_ENABLE_API_LAYERS", null);
            }
        }

        /// <summary>The pref is cleared BEFORE entering play: entering Play Mode is itself a
        /// domain reload, and a pref still set on the other side loops play/stop forever.</summary>
        private static void PumpAutoPlay()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            if (--_autoPlayCountdown > 0) return;
            EditorApplication.update -= PumpAutoPlay;
            EditorPrefs.SetBool(AutoPlayKey, false);
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            Debug.Log("[__NS__] dev XR: entering Play Mode in the simulator.");
            EditorApplication.EnterPlaymode();
        }

        /// <summary>
        /// Meta's "Activate", done by hand, for when its menu item is unavailable although a
        /// simulator IS installed. Returns true if the simulator is (now) the runtime.
        ///
        /// Meta's detector reads ONLY the per-user xrsim:// handler whenever that key exists.
        /// On 2026-09-24 the simulator's own auto-updater replaced the per-user v205 install
        /// with a system-wide v207 (C:\Program Files\MetaXRSimulator\v207.0) WHILE the editor
        /// was playing on it - which also closed the editor - and left the per-user key
        /// pointing at a deleted exe. Unity then reported the simulator "not installed", the
        /// menu item stayed disabled, and Play Mode ran on the default OpenXR runtime with no
        /// Operator ("[MetaXRFeature] Feature is unavailable"). This sets the same
        /// process-scoped variables Meta's activation sets, from whichever registered handler
        /// still points at a real install. No registry is touched.
        /// </summary>
        internal static bool EnsureSimulatorRuntime()
        {
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable(SelectedRuntimeEnv))) return true;
            if (EditorApplication.ExecuteMenuItem(SimulatorActivate) &&
                !string.IsNullOrEmpty(Environment.GetEnvironmentVariable(SelectedRuntimeEnv))) return true;
#if UNITY_EDITOR_WIN
            foreach (var root in new[] { Microsoft.Win32.Registry.CurrentUser, Microsoft.Win32.Registry.LocalMachine })
            {
                using (var key = root.OpenSubKey(@"SOFTWARE\Classes\xrsim\shell\open\command"))
                {
                    var command = key?.GetValue("") as string;
                    if (string.IsNullOrEmpty(command)) continue;
                    string exe = command.StartsWith("\"")
                        ? command.Substring(1, Math.Max(0, command.IndexOf('"', 1) - 1))
                        : command.Replace(" %1", "").Trim();
                    string dir = System.IO.Path.GetDirectoryName(exe);
                    string json = dir == null ? null : System.IO.Path.Combine(dir, "meta_openxr_simulator.json");
                    if (json == null || !System.IO.File.Exists(json)) continue;

                    Environment.SetEnvironmentVariable("XR_RUNTIME_JSON", json);
                    Environment.SetEnvironmentVariable(SelectedRuntimeEnv, json);
                    string config = System.IO.Path.Combine(dir, "config", "sim_core_configuration.json");
                    if (System.IO.File.Exists(config)) Environment.SetEnvironmentVariable("META_XRSIM_CONFIG_JSON", config);
                    Debug.LogWarning("[__NS__] dev XR: Meta's simulator Activate was unavailable; pointed this " +
                                     "editor at " + json + " by hand. A per-user xrsim:// handler probably points at " +
                                     "a removed install (the simulator's auto-updater leaves one behind).");
                    return true;
                }
            }
#endif
            Debug.LogError("[__NS__] dev XR: no Meta XR Simulator install found - Play Mode will run on the " +
                           "default OpenXR runtime with no Operator. Install it: npx -y metavr tools install xrsim");
            return false;
        }

        [MenuItem("__MENU__/Dev/Activate XR Operator + Simulator")]
        public static void Activate()
        {
            ApplyStandalone();
            bool op = EditorApplication.ExecuteMenuItem(OperatorActivate);
            bool sim = EnsureSimulatorRuntime();
            EditorPrefs.SetBool(EnabledKey, true);
            Debug.Log("[__NS__] dev XR: operator activate=" + op + ", simulator activate=" + sim +
                      " (false usually means already active).");
            EditorApplication.ExecuteMenuItem(OperatorStatus);
        }

        [MenuItem("__MENU__/Dev/Deactivate Simulator")]
        public static void DeactivateSimulator()
        {
            EditorPrefs.SetBool(EnabledKey, false);
            EditorApplication.ExecuteMenuItem(SimulatorDeactivate);
        }

        /// <summary>
        /// Open the scene, activate Operator + simulator, and arm Play - from a cold GUI start.
        /// NOT batchmode: Play Mode needs a real graphics device for an OpenXR swapchain, and
        /// the process has to stay alive for the agent to talk to it.
        /// </summary>
        public static void CliPlay()
        {
            try
            {
                ApplyStandalone();
                EditorPrefs.SetBool(EnabledKey, true);
                // Script changes while playing: RECOMPILE AFTER FINISHED PLAYING (1). The default
                // reloads the domain mid-play, which the Interaction SDK and MRUK do not survive.
                EditorPrefs.SetInt("ScriptCompilationDuringPlay", 1);
                // DevRemote (loopback :8731) is opt-in per machine and project; the loop needs it, so a
                // scripted cold start turns it on. It starts on the next domain load (entering Play).
                DevRemote.EnsureRunning();

                if (!string.IsNullOrEmpty(ScenePath) && !ScenePath.StartsWith("__"))
                    UnityEditor.SceneManagement.EditorSceneManager.OpenScene(
                        ScenePath, UnityEditor.SceneManagement.OpenSceneMode.Single);

                bool op = EditorApplication.ExecuteMenuItem(OperatorActivate);
                bool sim = EnsureSimulatorRuntime();
                Debug.Log("[__NS__] dev XR: operator=" + op + " simulator=" + sim + "; " + SelectedRuntimeEnv +
                          "='" + (Environment.GetEnvironmentVariable(SelectedRuntimeEnv) ?? "") + "'.");

                // A PREF, NOT A delayCall: opening a scene can trigger an import and a domain
                // reload, which throws every registered delayCall away - silently.
                EditorPrefs.SetBool(AutoPlayKey, true);
                // ...and arm it NOW as well: the pref only re-arms after a domain reload, and when the
                // scene was already open nothing reloads - Play never started and nothing said why.
                if (_autoPlayCountdown <= 0)
                {
                    _autoPlayCountdown = AutoPlayDelayFrames;
                    EditorApplication.update += PumpAutoPlay;
                }
                Debug.Log("[__NS__] dev XR: armed auto-play.");
            }
            catch (Exception e)
            {
                Debug.LogError("[__NS__] dev XR CliPlay threw: " + e);
            }
        }

        /// <summary>Headless half: everything that persists (the simulator env var would die
        /// with the batchmode process, so it is left to the GUI editor).</summary>
        public static void Cli()
        {
            try
            {
                ApplyStandalone();
                bool op = EditorApplication.ExecuteMenuItem(OperatorActivate);
                EditorPrefs.SetBool(EnabledKey, true);
                Debug.Log("[__NS__] dev XR (headless): standalone XR configured, operator activate=" + op);
                EditorApplication.Exit(0);
            }
            catch (Exception e)
            {
                Debug.LogError("[__NS__] dev XR setup threw: " + e);
                EditorApplication.Exit(1);
            }
        }

        // ---- Standalone OpenXR for editor Play Mode (never touches the Android settings) ----

        private const string OpenXrLoaderType = "UnityEngine.XR.OpenXR.OpenXRLoader";
        private const string MetaFeatureSetId = "com.meta.openxr.featureset.metaxr";

        public static void ApplyStandalone()
        {
            const BuildTargetGroup group = BuildTargetGroup.Standalone;
            EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.k_SettingsKey, out XRGeneralSettingsPerBuildTarget perTarget);
            if (perTarget == null)
            {
                const string path = "Assets/XR/XRGeneralSettingsPerBuildTarget.asset";
                perTarget = AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>(path);
                if (perTarget == null)
                {
                    perTarget = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
                    System.IO.Directory.CreateDirectory("Assets/XR");
                    AssetDatabase.CreateAsset(perTarget, path);
                }
                EditorBuildSettings.AddConfigObject(XRGeneralSettings.k_SettingsKey, perTarget, true);
            }
            if (!perTarget.HasManagerSettingsForBuildTarget(group))
                perTarget.CreateDefaultManagerSettingsForBuildTarget(group);
            var settings = perTarget.SettingsForBuildTarget(group);

            var manager = settings.Manager;
            if (manager == null)
            {
                manager = ScriptableObject.CreateInstance<XRManagerSettings>();
                manager.name = group + " Providers";
                AssetDatabase.AddObjectToAsset(manager, settings);
                settings.Manager = manager;
            }
            manager.automaticLoading = true;
            manager.automaticRunning = true;
            if (!XRPackageMetadataStore.AssignLoader(manager, OpenXrLoaderType, group))
                Debug.LogError("[__NS__] could not assign the OpenXR loader for Standalone.");

            var featureSet = OpenXRFeatureSetManager.GetFeatureSetWithId(group, MetaFeatureSetId);
            if (featureSet != null)
            {
                featureSet.isEnabled = true;
                OpenXRFeatureSetManager.SetFeaturesFromEnabledFeatureSets(group);
            }
            else Debug.LogError("[__NS__] Meta XR feature set not found - is com.meta.xr.sdk.core imported?");

            // The Operator is an API layer; without this feature there is nowhere to register it.
            Enable<ApiLayersFeature>(group);
            // The simulator pretends to be a Quest with Touch controllers. With no interaction
            // profile the runtime binds no controller and everything reads "not connected".
            Enable<MetaQuestTouchPlusControllerProfile>(group);
            Enable<OculusTouchControllerProfile>(group);

            var openXr = OpenXRSettings.GetSettingsForBuildTargetGroup(group);
            if (openXr != null)
            {
                openXr.renderMode = OpenXRSettings.RenderMode.SinglePassInstanced;
                EditorUtility.SetDirty(openXr);
            }
            EditorUtility.SetDirty(settings);
            EditorUtility.SetDirty(manager);
            AssetDatabase.SaveAssets();

            var active = manager.activeLoaders?.Select(l => l.name).ToArray() ?? new string[0];
            if (active.Length == 0)
                Debug.LogError("[__NS__] no active Standalone loaders - Play Mode would start no OpenXR session.");
        }

        private static void Enable<T>(BuildTargetGroup group) where T : OpenXRFeature
        {
            var feature = OpenXRSettings.GetSettingsForBuildTargetGroup(group)?.GetFeature<T>();
            if (feature == null) { Debug.LogError("[__NS__] OpenXR feature " + typeof(T).Name + " not found."); return; }
            feature.enabled = true;
            EditorUtility.SetDirty(feature);
            FeatureHelpers.RefreshFeatures(group);
        }
    }
}
