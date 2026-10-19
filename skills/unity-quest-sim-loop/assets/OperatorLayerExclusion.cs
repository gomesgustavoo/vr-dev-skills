using System;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace __NS__.EditorTools
{
    /// <summary>
    /// A development build WITHOUT the Meta XR Operator layer, when QUEST_NO_OPERATOR=1.
    /// Template from the unity-quest-sim-loop skill: replace __NS__, put it in an Editor
    /// assembly, and set the variable in the dev-build script (e.g. a -NoOperator switch).
    ///
    /// Meta's MetaXROperatorBuildProcessor (callbackOrder 0) includes the layer's AAR in every
    /// development build and offers no switch. When the layer itself crashes the app on the
    /// device's OS build (SDK 205 on Horizon OS of 2026-09-24 - see references/device.md), the
    /// dev build must go without it; this runs after Meta's processor and overrides it. The
    /// app's tools then answer over adb (DevCommandChannel + scripts/adbtools.py).
    ///
    /// Grep the build log for "excluding XrApiLayer_METAX_operator" to confirm it took.
    /// </summary>
    internal sealed class OperatorLayerExclusion : IPreprocessBuildWithReport
    {
        public const string EnvVar = "QUEST_NO_OPERATOR";
        private const string AarFileName = "XrApiLayer_METAX_operator_unity_android";

        public int callbackOrder => 100;

        public void OnPreprocessBuild(BuildReport report)
        {
            if (report.summary.platform != BuildTarget.Android) return;
            if (Environment.GetEnvironmentVariable(EnvVar) != "1") return;
            foreach (var importer in PluginImporter.GetAllImporters())
            {
                if (!importer.assetPath.Contains(AarFileName)) continue;
                importer.SetIncludeInBuildDelegate(_ => false);
                Debug.Log("[OperatorLayerExclusion] " + EnvVar + "=1: excluding " + AarFileName +
                          ".aar from this development build; app tools answer over adb.");
                return;
            }
            Debug.LogWarning("[OperatorLayerExclusion] " + EnvVar + "=1 but no " + AarFileName + " importer was found.");
        }
    }
}
