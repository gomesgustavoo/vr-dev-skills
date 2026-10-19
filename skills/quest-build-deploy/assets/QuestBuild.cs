using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace __NS__.EditorTools
{
    /// <summary>
    /// Headless Quest builds with build gates. Template from the quest-build-deploy skill: replace
    /// __NS__ (root namespace) and __MENU__ (menu root), and put it in an Editor folder / assembly.
    ///
    ///   Unity -batchmode -quit -projectPath P -buildTarget Android -logFile build.log
    ///         -executeMethod __NS__.EditorTools.QuestBuild.Cli      [-apkPath Build/App.apk]
    ///         -executeMethod __NS__.EditorTools.QuestBuild.CliDev   (DEVELOPMENT build: agent tools, Operator layer)
    ///         -executeMethod __NS__.EditorTools.QuestBuild.CliGates (gates only, no APK)
    ///
    /// The quest-build-deploy skill's scripts/unity_build.ps1 runs these and waits on the process.
    ///
    /// Every log line a script may wait for starts with "[QuestBuild]" or "[QuestBuildGates]", and the
    /// last one is always "[QuestBuild] result=..." (or "refusing" / "FAILED"): copy markers from HERE,
    /// never type them from memory.
    ///
    /// GATES. Any static method in an Editor assembly marked [QuestBuildGate] that returns
    /// IEnumerable&lt;string&gt; is a gate: it yields one message per failure (nothing = pass). Every build
    /// runs every gate first and refuses to build on a failure, so a broken scene never costs a
    /// 20-minute APK. Write the message as the bug LOOKS in the headset ("the sky is drawn over every
    /// opaque object"), and watch each new gate fail once with the bug restored.
    /// </summary>
    public static class QuestBuild
    {
        [AttributeUsage(AttributeTargets.Method)]
        public sealed class QuestBuildGateAttribute : Attribute { }

        public static void Cli() => Exit(() => Build(false, Arg("-apkPath") ?? DefaultApk(false)));
        public static void CliDev() => Exit(() => Build(true, Arg("-apkPath") ?? DefaultApk(true)));
        public static void CliGates() => Exit(() => RunGates() == 0);

        [MenuItem("__MENU__/Build/Build Quest APK")]
        private static void MenuBuild() => Build(false, DefaultApk(false));

        [MenuItem("__MENU__/Build/Build Quest APK (Development)")]
        private static void MenuBuildDev() => Build(true, DefaultApk(true));

        [MenuItem("__MENU__/Build/Run Build Gates")]
        private static void MenuGates() => RunGates();

        public static string DefaultApk(bool dev)
        {
            string name = string.Join("_", PlayerSettings.productName.Split(Path.GetInvalidFileNameChars()));
            return Path.Combine("Build", name + (dev ? "-dev" : "") + ".apk");
        }

        public static bool Build(bool dev, string apk)
        {
            if (RunGates() != 0)
            {
                Debug.LogError("[QuestBuild] refusing to build: a gate failed (see the [QuestBuildGates] FAIL lines)");
                return false;
            }
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android &&
                !EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android))
            {
                Debug.LogError("[QuestBuild] FAILED: could not switch the build target to Android (is Android Build Support installed?)");
                return false;
            }
            string[] scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
            if (scenes.Length == 0)
            {
                Debug.LogError("[QuestBuild] FAILED: no enabled scene in File > Build Profiles / Build Settings");
                return false;
            }
            string full = Path.GetFullPath(apk);
            Directory.CreateDirectory(Path.GetDirectoryName(full));
            if (File.Exists(full)) File.Delete(full);   // a stale APK must never pass for a new one

            var options = new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = full,
                target = BuildTarget.Android,
                targetGroup = BuildTargetGroup.Android,
                // Meta's build processor adds the XR Operator layer to DEVELOPMENT builds only.
                options = dev ? BuildOptions.Development : BuildOptions.None,
            };
            Debug.Log("[QuestBuild] building " + (dev ? "DEVELOPMENT" : "release") + " -> " + full +
                      " (" + scenes.Length + " scene(s))");
            BuildReport report = BuildPipeline.BuildPlayer(options);
            BuildSummary s = report.summary;
            bool ok = s.result == BuildResult.Succeeded && File.Exists(full);
            Debug.Log("[QuestBuild] result=" + s.result + " errors=" + s.totalErrors + " warnings=" + s.totalWarnings +
                      " sizeMB=" + (s.totalSize / (1024.0 * 1024.0)).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) +
                      " minutes=" + s.totalTime.TotalMinutes.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) +
                      " dev=" + dev + " apk=" + full);
            return ok;
        }

        /// <summary>Runs every [QuestBuildGate]; returns the number of failures.</summary>
        public static int RunGates()
        {
            int failures = 0, gates = 0;
            foreach (var method in TypeCache.GetMethodsWithAttribute<QuestBuildGateAttribute>()
                         .OrderBy(m => m.DeclaringType.FullName + "." + m.Name, StringComparer.Ordinal))
            {
                string name = method.DeclaringType.Name + "." + method.Name;
                gates++;
                List<string> messages;
                try
                {
                    var result = method.Invoke(null, null) as IEnumerable<string>;
                    messages = result != null ? result.Where(m => !string.IsNullOrEmpty(m)).ToList() : new List<string>();
                }
                catch (Exception e)
                {
                    // A gate that throws has not proven anything: count it as a failure, never a pass.
                    messages = new List<string> { "threw " + (e.InnerException ?? e).GetType().Name + ": " + (e.InnerException ?? e).Message };
                }
                if (messages.Count == 0)
                {
                    Debug.Log("[QuestBuildGates] PASS " + name);
                    continue;
                }
                failures += messages.Count;
                foreach (string m in messages) Debug.LogError("[QuestBuildGates] FAIL " + name + ": " + m);
            }
            Debug.Log("[QuestBuildGates] " + (failures == 0 ? "ALL PASS" : failures + " FAILURE(S)") + " (" + gates + " gate(s))");
            return failures;
        }

        private static string Arg(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        private static void Exit(Func<bool> body)
        {
            int code = 1;
            try { code = body() ? 0 : 1; }
            catch (Exception e) { Debug.LogError("[QuestBuild] FAILED: " + e); }
            EditorApplication.Exit(code);
        }
    }

    /// <summary>An example gate: delete or replace with your own. Gates read the project; they never fix it.</summary>
    internal static class ExampleQuestGates
    {
        [QuestBuild.QuestBuildGate]
        private static IEnumerable<string> AndroidIsArm64Il2Cpp()
        {
            if (PlayerSettings.GetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Android) != ScriptingImplementation.IL2CPP)
                yield return "the Android scripting backend is not IL2CPP: the Horizon Store requires 64-bit (ARM64 needs IL2CPP)";
            if ((PlayerSettings.Android.targetArchitectures & AndroidArchitecture.ARM64) == 0)
                yield return "ARM64 is not a target architecture: the build will not install on Quest";
        }
    }
}
