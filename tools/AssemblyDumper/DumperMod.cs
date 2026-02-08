using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using MelonLoader;

[assembly: MelonInfo(typeof(AssemblyDumper.DumperMod), "AssemblyDumper", "2.0.0", "debug")]
[assembly: MelonGame("sega-interactive", "Sinmai")]

namespace AssemblyDumper
{
    public class DumperMod : MelonMod
    {
        public override void OnApplicationStart()
        {
            LoggerInstance.Msg("=== Assembly Dumper v2 Starting ===");
            string dumpDir = Path.Combine(MelonUtils.BaseDirectory, "DumpedAssemblies");
            Directory.CreateDirectory(dumpDir);

            try
            {
                DeepAnalysis(dumpDir);
            }
            catch (Exception ex)
            {
                LoggerInstance.Error("Analysis failed: " + ex.ToString());
            }

            LoggerInstance.Msg("=== Assembly Dumper v2 Finished ===");
        }

        private void DeepAnalysis(string dumpDir)
        {
            Assembly asmCSharp = null;
            foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (asm.GetName().Name == "Assembly-CSharp")
                {
                    asmCSharp = asm;
                    break;
                }
            }

            if (asmCSharp == null)
            {
                LoggerInstance.Error("Assembly-CSharp not found!");
                return;
            }

            Type[] types;
            try { types = asmCSharp.GetTypes(); }
            catch (ReflectionTypeLoadException ex) { types = ex.Types; }

            // 1) Build Cue enum maps
            Type sysVoiceCueType = null;
            Type partnerVoiceCueType = null;
            Dictionary<int, string> sysCueMap = new Dictionary<int, string>();
            Dictionary<int, string> partnerCueMap = new Dictionary<int, string>();

            foreach (Type t in types)
            {
                if (t == null) continue;
                if (t.Name == "Cue" && t.IsEnum)
                {
                    if (t.Namespace != null && t.Namespace.Contains("Voice_000001"))
                    {
                        sysVoiceCueType = t;
                        foreach (object v in Enum.GetValues(t))
                        {
                            sysCueMap[(int)v] = Enum.GetName(t, v);
                        }
                    }
                    else if (t.Namespace != null && t.Namespace.Contains("Voice_Partner"))
                    {
                        if (partnerVoiceCueType == null)
                        {
                            partnerVoiceCueType = t;
                            foreach (object v in Enum.GetValues(t))
                            {
                                partnerCueMap[(int)v] = Enum.GetName(t, v);
                            }
                        }
                    }
                }
            }

            LoggerInstance.Msg("System voice cues: " + sysCueMap.Count.ToString());
            LoggerInstance.Msg("Partner voice cues: " + partnerCueMap.Count.ToString());

            // 2) Find SoundManager method tokens for PlayVoice/PlayPartnerVoice etc
            Dictionary<int, string> voiceMethodTokens = new Dictionary<int, string>();
            foreach (Type t in types)
            {
                if (t == null) continue;
                if (t.Name == "SoundManager" || t.Name == "SeManager")
                {
                    foreach (MethodInfo m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                    {
                        if (m.Name.Contains("Voice") || m.Name.Contains("Play") || m.Name.Contains("Cue"))
                        {
                            try
                            {
                                int token = m.MetadataToken;
                                voiceMethodTokens[token] = t.Name + "." + m.Name;
                            }
                            catch { }
                        }
                    }
                }
                // Also track wrapper methods
                if (t.Name == "StateEntry" || t.Name == "MapBehaviour" || t.Name == "CodeReadControllerBase")
                {
                    foreach (MethodInfo m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                    {
                        if (m.Name.Contains("Voice") || m.Name.Contains("Play"))
                        {
                            try
                            {
                                int token = m.MetadataToken;
                                voiceMethodTokens[token] = t.Name + "." + m.Name;
                            }
                            catch { }
                        }
                    }
                }
            }

            LoggerInstance.Msg("Tracked voice method tokens: " + voiceMethodTokens.Count.ToString());

            // 3) Scan ALL methods for IL patterns that reference Cue constants + voice calls
            string outPath = Path.Combine(dumpDir, "deep_voice_analysis.txt");
            string csvPath = Path.Combine(dumpDir, "voice_calls.csv");

            using (StreamWriter w = new StreamWriter(outPath))
            using (StreamWriter csv = new StreamWriter(csvPath))
            {
                w.WriteLine("=== Deep Voice Analysis ===");
                w.WriteLine("Date: " + DateTime.Now.ToString());
                w.WriteLine("System Cue values: " + sysCueMap.Count.ToString());
                w.WriteLine("Partner Cue values: " + partnerCueMap.Count.ToString());
                w.WriteLine("Voice method tokens tracked: " + voiceMethodTokens.Count.ToString());
                w.WriteLine();

                // Write cue maps
                w.WriteLine("=== System Voice Cue Map ===");
                foreach (KeyValuePair<int, string> kv in sysCueMap)
                {
                    w.WriteLine("  " + kv.Value + " = " + kv.Key.ToString());
                }
                w.WriteLine();

                w.WriteLine("=== Partner Voice Cue Map ===");
                foreach (KeyValuePair<int, string> kv in partnerCueMap)
                {
                    w.WriteLine("  " + kv.Value + " = " + kv.Key.ToString());
                }
                w.WriteLine();

                w.WriteLine("=== Voice Method Tokens ===");
                foreach (KeyValuePair<int, string> kv in voiceMethodTokens)
                {
                    w.WriteLine("  0x" + kv.Key.ToString("X8") + " = " + kv.Value);
                }
                w.WriteLine();

                csv.WriteLine("CallerType,CallerMethod,CueValue,CueName,VoiceMethodCalled,ILOffset");

                w.WriteLine("=== Scanning all methods for voice call patterns ===");
                w.WriteLine();

                int totalMethods = 0;
                int callsFound = 0;

                foreach (Type t in types)
                {
                    if (t == null) continue;
                    MethodInfo[] methods;
                    try { methods = t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly); }
                    catch { continue; }

                    foreach (MethodInfo m in methods)
                    {
                        totalMethods++;
                        try
                        {
                            MethodBody body = m.GetMethodBody();
                            if (body == null) continue;
                            byte[] il = body.GetILAsByteArray();
                            if (il == null || il.Length < 4) continue;

                            // Scan IL for ldc.i4 followed by call/callvirt to voice methods
                            // Also scan for general patterns of Cue enum loads
                            List<int> loadedConstants = new List<int>();
                            int i = 0;
                            while (i < il.Length)
                            {
                                byte op = il[i];

                                // Track integer constants loaded
                                // ldc.i4.0 through ldc.i4.8 (0x16-0x1E)
                                if (op >= 0x16 && op <= 0x1E)
                                {
                                    loadedConstants.Add(op - 0x16);
                                    i++;
                                    continue;
                                }
                                // ldc.i4.m1 (0x15)
                                if (op == 0x15)
                                {
                                    loadedConstants.Add(-1);
                                    i++;
                                    continue;
                                }
                                // ldc.i4.s (0x1F) - signed byte
                                if (op == 0x1F && i + 1 < il.Length)
                                {
                                    loadedConstants.Add((sbyte)il[i + 1]);
                                    i += 2;
                                    continue;
                                }
                                // ldc.i4 (0x20) - int32
                                if (op == 0x20 && i + 4 < il.Length)
                                {
                                    int val = il[i + 1] | (il[i + 2] << 8) | (il[i + 3] << 16) | (il[i + 4] << 24);
                                    loadedConstants.Add(val);
                                    i += 5;
                                    continue;
                                }

                                // call (0x28) or callvirt (0x6F) - 4-byte token
                                if ((op == 0x28 || op == 0x6F) && i + 4 < il.Length)
                                {
                                    int token = il[i + 1] | (il[i + 2] << 8) | (il[i + 3] << 16) | (il[i + 4] << 24);

                                    string methodName;
                                    if (voiceMethodTokens.TryGetValue(token, out methodName))
                                    {
                                        // Found a voice method call! Check what constants were loaded before it
                                        foreach (int c in loadedConstants)
                                        {
                                            string cueName = "";
                                            bool isSys = sysCueMap.TryGetValue(c, out cueName);
                                            bool isPartner = false;
                                            string partName = "";
                                            if (!isSys)
                                            {
                                                isPartner = partnerCueMap.TryGetValue(c, out partName);
                                                if (isPartner) cueName = partName;
                                            }

                                            if (isSys || isPartner)
                                            {
                                                string entry = string.Format("[{0}.{1}] calls {2} with Cue {3} ({4}) at IL offset {5}",
                                                    t.FullName, m.Name, methodName, cueName, c, i);
                                                w.WriteLine(entry);
                                                callsFound++;

                                                csv.WriteLine(string.Format("{0},{1},{2},{3},{4},{5}",
                                                    EscapeCsv(t.FullName), EscapeCsv(m.Name),
                                                    c, EscapeCsv(cueName), EscapeCsv(methodName), i));
                                            }
                                        }
                                    }

                                    // Try to resolve via reflection too
                                    try
                                    {
                                        MethodBase resolved = asmCSharp.ManifestModule.ResolveMethod(token);
                                        if (resolved != null)
                                        {
                                            string rName = resolved.DeclaringType.Name + "." + resolved.Name;
                                            if (rName.Contains("Voice") || rName.Contains("Play"))
                                            {
                                                foreach (int c in loadedConstants)
                                                {
                                                    string cueName = "";
                                                    bool isSys = sysCueMap.TryGetValue(c, out cueName);
                                                    bool isPartner = false;
                                                    string partName = "";
                                                    if (!isSys)
                                                    {
                                                        isPartner = partnerCueMap.TryGetValue(c, out partName);
                                                        if (isPartner) cueName = partName;
                                                    }
                                                    if ((isSys || isPartner) && !voiceMethodTokens.ContainsKey(token))
                                                    {
                                                        string entry = string.Format("[{0}.{1}] calls {2} with Cue {3} ({4}) at IL offset {5} (resolved)",
                                                            t.FullName, m.Name, rName, cueName, c, i);
                                                        w.WriteLine(entry);
                                                        callsFound++;

                                                        csv.WriteLine(string.Format("{0},{1},{2},{3},{4},{5}",
                                                            EscapeCsv(t.FullName), EscapeCsv(m.Name),
                                                            c, EscapeCsv(cueName), EscapeCsv(rName), i));
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    catch { }

                                    loadedConstants.Clear();
                                    i += 5;
                                    continue;
                                }

                                // Other call-like opcodes clear the constant stack
                                if (op == 0x26 || op == 0x2A) // pop, ret
                                {
                                    loadedConstants.Clear();
                                }

                                // Handle variable-length opcodes
                                // Most single-byte opcodes
                                if (op <= 0x14 || (op >= 0x25 && op <= 0x2B) || (op >= 0x57 && op <= 0x72 && op != 0x6F))
                                {
                                    i++;
                                    continue;
                                }
                                // Inline method/field/type token (4 bytes): call, callvirt, ldfld, stfld, etc.
                                if (op == 0x73 || op == 0x74 || op == 0x75 || op == 0x79 || op == 0x7B || op == 0x7C || op == 0x7D || op == 0x7E || op == 0x7F || op == 0x80 || op == 0x81 || op == 0xA3 || op == 0xA4 || op == 0xA5 || op == 0x8D || op == 0x8C)
                                {
                                    i += 5;
                                    continue;
                                }
                                // Inline branch (4 bytes): br, brfalse, brtrue, etc
                                if (op >= 0x38 && op <= 0x44)
                                {
                                    i += 5;
                                    continue;
                                }
                                // Short inline branch (1 byte): br.s, brfalse.s, etc
                                if (op >= 0x2B && op <= 0x37)
                                {
                                    i += 2;
                                    continue;
                                }
                                // switch
                                if (op == 0x45 && i + 4 < il.Length)
                                {
                                    int n = il[i + 1] | (il[i + 2] << 8) | (il[i + 3] << 16) | (il[i + 4] << 24);
                                    i += 5 + 4 * n;
                                    continue;
                                }
                                // Two-byte opcodes (0xFE prefix)
                                if (op == 0xFE && i + 1 < il.Length)
                                {
                                    byte op2 = il[i + 1];
                                    if (op2 <= 0x06) // ceq, cgt, etc
                                    {
                                        i += 2;
                                        continue;
                                    }
                                    if (op2 == 0x09 || op2 == 0x0E || op2 == 0x0F || op2 == 0x11 || op2 == 0x12) // ldarg, starg
                                    {
                                        i += 4;
                                        continue;
                                    }
                                    if (op2 == 0x0C || op2 == 0x0D) // ldloc, stloc
                                    {
                                        i += 4;
                                        continue;
                                    }
                                    if (op2 == 0x16) // constrained
                                    {
                                        i += 6;
                                        continue;
                                    }
                                    i += 2;
                                    continue;
                                }
                                // ldstr (0x72) - inline string token
                                if (op == 0x72)
                                {
                                    i += 5;
                                    continue;
                                }
                                // Default: advance 1
                                i++;
                            }
                        }
                        catch { }
                    }
                }

                w.WriteLine();
                w.WriteLine("=== Summary ===");
                w.WriteLine("Total methods scanned: " + totalMethods.ToString());
                w.WriteLine("Voice calls with Cue constants found: " + callsFound.ToString());

                // 4) Also dump ALL methods that take a Cue parameter, with full IL + resolved tokens
                w.WriteLine();
                w.WriteLine("=== ALL methods taking Cue parameter (full detail) ===");
                w.WriteLine();

                foreach (Type t in types)
                {
                    if (t == null) continue;
                    MethodInfo[] methods;
                    try { methods = t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly); }
                    catch { continue; }

                    foreach (MethodInfo m in methods)
                    {
                        bool hasCueParam = false;
                        foreach (ParameterInfo p in m.GetParameters())
                        {
                            if (p.ParameterType.Name == "Cue")
                            {
                                hasCueParam = true;
                                break;
                            }
                        }

                        bool isVoiceMethod = m.Name.Contains("Voice") || m.Name.Contains("voice");

                        if (!hasCueParam && !isVoiceMethod) continue;

                        try
                        {
                            MethodBody body = m.GetMethodBody();
                            if (body == null) continue;
                            byte[] il = body.GetILAsByteArray();
                            if (il == null) continue;

                            string sig = FormatMethod(m);
                            w.WriteLine("[" + t.FullName + "] " + sig);
                            w.WriteLine("  Token: 0x" + m.MetadataToken.ToString("X8"));
                            w.WriteLine("  IL(" + il.Length.ToString() + "): " + BitConverter.ToString(il).Replace("-", " "));

                            // Resolve method calls in IL
                            w.Write("  Calls: ");
                            int ci = 0;
                            while (ci < il.Length)
                            {
                                byte op = il[ci];
                                if ((op == 0x28 || op == 0x6F) && ci + 4 < il.Length)
                                {
                                    int token = il[ci + 1] | (il[ci + 2] << 8) | (il[ci + 3] << 16) | (il[ci + 4] << 24);
                                    try
                                    {
                                        MethodBase resolved = asmCSharp.ManifestModule.ResolveMethod(token);
                                        if (resolved != null)
                                        {
                                            w.Write(resolved.DeclaringType.Name + "." + resolved.Name + " ");
                                        }
                                    }
                                    catch
                                    {
                                        w.Write("?0x" + token.ToString("X8") + " ");
                                    }
                                    ci += 5;
                                    continue;
                                }
                                if (op == 0xFE && ci + 1 < il.Length) { ci += 2; continue; }
                                if (op == 0x20 && ci + 4 < il.Length) { ci += 5; continue; }
                                if (op == 0x1F && ci + 1 < il.Length) { ci += 2; continue; }
                                if (op == 0x72 && ci + 4 < il.Length) { ci += 5; continue; }
                                if ((op == 0x28 || op == 0x6F || op == 0x73 || op == 0x7B || op == 0x7C || op == 0x7D || op == 0x7E || op == 0x7F || op == 0x80) && ci + 4 < il.Length)
                                { ci += 5; continue; }
                                if (op == 0x45 && ci + 4 < il.Length)
                                {
                                    int n = il[ci + 1] | (il[ci + 2] << 8) | (il[ci + 3] << 16) | (il[ci + 4] << 24);
                                    ci += 5 + 4 * n;
                                    continue;
                                }
                                if (op >= 0x38 && op <= 0x44) { ci += 5; continue; }
                                if (op >= 0x2B && op <= 0x37) { ci += 2; continue; }
                                ci++;
                            }
                            w.WriteLine();

                            // List locals
                            if (body.LocalVariables.Count > 0)
                            {
                                string locStr = "  Locals: ";
                                foreach (LocalVariableInfo lv in body.LocalVariables)
                                {
                                    locStr += "[" + lv.LocalIndex.ToString() + "]" + lv.LocalType.Name + " ";
                                }
                                w.WriteLine(locStr);
                            }
                            w.WriteLine();
                        }
                        catch { }
                    }
                }

                // 5) Bonus: Find all classes with PlayVoice/PlayPartnerVoice wrappers
                w.WriteLine("=== Classes with Voice wrapper methods ===");
                foreach (Type t in types)
                {
                    if (t == null) continue;
                    List<string> voiceMethods = new List<string>();
                    try
                    {
                        foreach (MethodInfo m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
                        {
                            if (m.Name.Contains("Voice") || m.Name.Contains("voice"))
                            {
                                voiceMethods.Add(FormatMethod(m));
                            }
                        }
                    }
                    catch { }

                    if (voiceMethods.Count > 0)
                    {
                        w.WriteLine(t.FullName + ":");
                        foreach (string vm in voiceMethods)
                        {
                            w.WriteLine("  " + vm);
                        }
                    }
                }

                // 6) Timeline voice data: find VoicePlayableBehaviour/VoicePlayableAsset fields
                w.WriteLine();
                w.WriteLine("=== Timeline Voice Types ===");
                foreach (Type t in types)
                {
                    if (t == null) continue;
                    if (t.Name.Contains("VoicePlayable") || t.Name.Contains("VoiceTimeline"))
                    {
                        w.WriteLine(t.FullName + ":");
                        foreach (FieldInfo f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                        {
                            w.WriteLine("  Field: " + f.FieldType.Name + " " + f.Name);
                        }
                        foreach (PropertyInfo p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                        {
                            w.WriteLine("  Prop: " + p.PropertyType.Name + " " + p.Name);
                        }
                        foreach (MethodInfo m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
                        {
                            try
                            {
                                MethodBody body = m.GetMethodBody();
                                if (body != null)
                                {
                                    byte[] il2 = body.GetILAsByteArray();
                                    if (il2 != null)
                                    {
                                        w.WriteLine("  Method: " + m.Name + " IL=" + il2.Length.ToString() + " bytes");
                                        w.WriteLine("    " + BitConverter.ToString(il2).Replace("-", " "));
                                    }
                                }
                            }
                            catch { }
                        }
                    }
                }

                // 7) ConstParameter voice constants
                w.WriteLine();
                w.WriteLine("=== ConstParameter voice-related ===");
                foreach (Type t in types)
                {
                    if (t == null) continue;
                    if (t.Name == "ConstParameter")
                    {
                        foreach (FieldInfo f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                        {
                            if (f.Name.Contains("Voice") || f.Name.Contains("voice") || f.Name.Contains("Dialog"))
                            {
                                try
                                {
                                    object val = f.GetValue(null);
                                    w.WriteLine("  " + f.FieldType.Name + " " + f.Name + " = " + (val != null ? val.ToString() : "null"));
                                }
                                catch
                                {
                                    w.WriteLine("  " + f.FieldType.Name + " " + f.Name + " (could not read)");
                                }
                            }
                        }
                    }
                }
            }

            LoggerInstance.Msg("Deep analysis saved to: " + outPath);
            LoggerInstance.Msg("CSV saved to: " + csvPath);
        }

        private string FormatMethod(MethodInfo m)
        {
            ParameterInfo[] parms = m.GetParameters();
            string s = m.ReturnType.Name + " " + m.Name + "(";
            for (int i = 0; i < parms.Length; i++)
            {
                if (i > 0) s += ", ";
                s += parms[i].ParameterType.Name + " " + parms[i].Name;
            }
            return s + ")";
        }

        private string EscapeCsv(string s)
        {
            if (s == null) return "";
            if (s.Contains(",") || s.Contains("\""))
            {
                return "\"" + s.Replace("\"", "\"\"") + "\"";
            }
            return s;
        }
    }
}
