# maimai Voice & Partner Data — Reverse Engineering Report

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Game Technical Profile](#2-game-technical-profile)
3. [Audio System Architecture](#3-audio-system-architecture)
4. [Protection & Obfuscation](#4-protection--obfuscation)
5. [Failed Approaches (What Did NOT Work)](#5-failed-approaches-what-did-not-work)
6. [Successful Approach (What DID Work)](#6-successful-approach-what-did-work)
7. [Code Architecture — Voice System](#7-code-architecture--voice-system)
8. [Voice Data Structures](#8-voice-data-structures)
9. [Interpreting the Scan Results](#9-interpreting-the-scan-results)
10. [Known Limitations & False Positives](#10-known-limitations--false-positives)
11. [File Inventory](#11-file-inventory)
12. [Recommendations for Future Work](#12-recommendations-for-future-work)
13. [Appendix A — Cue Enum Index Listings](#appendix-a--cue-enum-index-listings)
14. [Appendix B — Full Method Signatures](#appendix-b--full-method-signatures)
15. [Appendix C — Partner XML Voice Fields](#appendix-c--partner-xml-voice-fields)

---

## 1. Project Overview

**Goal:** Map every `VO_XXXXXX` voice cue identifier from the SEGA maimai arcade rhythm game to its in-game behavior — what screen it plays on, what triggers it, and whether it's a System Voice or Partner Voice.

**Problem:** The game's decompiled C# code has **encrypted method bodies** — all decompilers produce empty methods. Working code logic can only be obtained from the game's runtime memory.

**Deliverable:** `voice_action_mapping.csv` — a comprehensive mapping of all 244 voice IDs (150 System Voice + 94 Partner Voice) with game context, caller methods, and evidence classification.

**Result:** 88 of 244 entries (36%) have confirmed runtime evidence from IL bytecode analysis. The remaining 156 entries are classified as "Inferred" based on structural position, naming, and adjacency to confirmed entries.

---

## 2. Game Technical Profile

| Property | Value |
|----------|-------|
| **Executable** | `Sinmai.exe` |
| **Engine** | Unity 2018.4.7f1 |
| **Architecture** | x86_64 (64-bit) |
| **Scripting Backend** | Mono (MonoBleedingEdge) — **NOT IL2CPP** |
| **Mono Runtime DLL** | `MonoBleedingEdge\EmbedRuntime\mono-2.0-bdwgc.dll` |
| **Main Game Assembly** | `Sinmai_Data\Managed\Assembly-CSharp.dll` (~3.9 MB on disk) |
| **Audio Middleware** | CRI ADX2 (CriAtomEx) |
| **Audio Format** | HCA encoded in `.acb` / `.awb` container pairs |
| **Mod Framework (pre-installed)** | MelonLoader v0.6.4 + AquaMai v1.4.1 |
| **MelonLoader Proxy** | `version.dll` in game root |
| **Game Path Used** | `D:\maimai_prism_plus\prismPlus\Package\` |

### Key Files in Game Directory

```
Package/
├── Sinmai.exe
├── version.dll                       ← MelonLoader proxy DLL
├── start.bat                         ← Game launcher
├── segatools.ini                     ← Hardware emulation config
├── Sinmai_Data/
│   └── Managed/
│       └── Assembly-CSharp.dll       ← THE target (encrypted method bodies)
├── MonoBleedingEdge/
│   └── EmbedRuntime/
│       └── mono-2.0-bdwgc.dll        ← Mono runtime
├── MelonLoader/
│   └── MelonLoader.dll
├── Mods/
│   ├── AquaMai.dll                   ← Pre-existing mod
│   └── AssemblyDumper.dll            ← Our custom analysis mod
├── UserData/
│   └── DumpedAssemblies/             ← Output from our mod
│       ├── deep_voice_analysis.txt   ← 257 KB, 2484 lines
│       ├── voice_calls.csv
│       └── Assembly-CSharp-dumped.dll← Raw dump (still encrypted — not useful)
└── Option/
    └── Voice_000001/                 ← System voice ACB/AWB
    └── Voice_Partner_XXXXXX/         ← Partner voice ACB/AWB (per partner)
```

---

## 3. Audio System Architecture

### ACB/AWB Cue Sheet System

maimai uses the CRI ADX2 middleware for all audio playback. Voice audio is organized into **cue sheets**:

- **System Voice:** One cue sheet per voice pack, named `Voice_XXXXXX` (e.g., `Voice_000001`). Contains up to 277 cues (indices 0–276, non-contiguous). Loaded into ACB IDs `Voice_1P` and `Voice_2P`.

- **Partner Voice:** One cue sheet per partner character, named `Voice_Partner_XXXXXX` (e.g., `Voice_Partner_000011`). Contains up to 95 cues (indices 0–94). Loaded into ACB IDs `Partner_Voice_1P` and `Partner_Voice_2P`.

### C# Cue Enums

Voice cues are referenced in code via two enums:

```
Namespace: Mai2.Voice_000001
Enum:      Cue
Members:   VO_000001 = 0, VO_000002 = 1, ... VO_000265 = 276  (150 members)

Namespace: Mai2.Voice_Partner_000001
Enum:      Cue
Members:   VO_000080 = 0, VO_000081 = 1, ... VO_000266 = 94   (94 members)
```

**Critical detail:** The VO_ID number (e.g., `VO_000265`) is NOT the cue index. The cue index is the integer value of the enum member. Some VO_IDs exist in BOTH enums with different index values — they represent different audio content played from different ACB files.

### ACB ID Enum (SoundManager.AcbID)

```csharp
enum AcbID {
    Default,             // 0
    Music,               // 1
    Voice_1P,            // 2  ← System voice, player 1
    Voice_2P,            // 3  ← System voice, player 2
    Partner_Voice_1P,    // 4  ← Partner voice, player 1
    Partner_Voice_2P     // 5  ← Partner voice, player 2
}
```

### Player ID Enum (SoundManager.PlayerID)

```csharp
// Relevant voice-related PlayerIDs:
SystemAdvVoice0 = 4,
SystemAdvVoice1 = 5,
Voice           = 8,
PartnerVoice    = 9
```

### Cue Sheet Loading

```
SetVoiceCue(target, voiceID)         → Loads "Voice_XXXXXX" into Voice_1P/2P ACB slots
SetPartnerVoiceCue(target, voiceID)  → Loads "Voice_Partner_XXXXXX" into Partner_Voice_1P/2P
SetPartnerVoiceCueUserEquiped(monId) → Reads user's equipped partner ID, calls SetPartnerVoiceCue
```

The game loads the appropriate cue sheet at runtime based on the player's selected system voice and partner character. Once loaded, `PlayVoice(cue, target)` plays a specific cue from the currently loaded sheet.

---

## 4. Protection & Obfuscation

### The Core Problem

`Assembly-CSharp.dll` uses **runtime method body encryption**. The IL bytecode for every method in the DLL is encrypted on disk. The Mono runtime decrypts method bodies only at JIT compilation time — the DLL file itself never contains readable IL.

### Symptoms

- **ILSpy, dnSpy, dotPeek:** All show empty method bodies: `{ }` or `// Invalid MethodBodyBlock`
- **de4dot:** Produces a "cleaned" DLL (6.2 MB vs 4.1 MB) but method bodies remain empty
- **Hex dump comparison:** The on-disk file is genuinely different from what's in memory at method level
- **The one exception:** Member declarations, field names, enum values, class hierarchies, method signatures — all readable. Only the executable IL is encrypted.

### Consequence

You can see WHAT methods exist and WHAT their parameters are, but not HOW they work. For voice mapping, you can see `PlayVoice(Cue cueIndex, int target)` exists but not where it's called from or with what arguments.

---

## 5. Failed Approaches (What Did NOT Work)

### 5a. Direct Decompilation (ILSpy / dnSpy)

**What was tried:** Opening `Assembly-CSharp.dll` in ILSpy and dnSpy.

**Result:** All 19,551 methods show `{ }` or `// Invalid MethodBodyBlock`. Only the one hardcoded constant `ConstParameter.CommonDialogVoice = Cue.VO_000228` was readable (stored as field initialization, not method body).

**Why it failed:** Method body encryption — the RVA entries in the PE metadata point to encrypted byte ranges.

### 5b. de4dot Deobfuscation

**What was tried:** Running `de4dot Assembly-CSharp.dll` to strip obfuscation.

**Result:** Produced `Assembly-CSharp-cleaned.dll` (6.2 MB, larger than 4.1 MB original). Method bodies still empty.

**Why it failed:** de4dot can strip name obfuscation and some IL-level tricks, but the encryption here operates below the obfuscator level — likely a custom Mono runtime patch or a loader-level encryption.

### 5c. BepInEx + DumpAssemblies

**What was tried:** 
1. Downloaded BepInEx 5.4.23.5 (x64)
2. Installed to game directory
3. Configured `[Preloader] > DumpAssemblies = true` in `BepInEx.cfg`

**Result:** 
- Game launched with a **black screen** — BepInEx's Unity patching conflicted with the game's protection
- BepInEx only dumped `UnityEngine.CoreModule.dll` (the one it patched), not `Assembly-CSharp.dll`
- DumpAssemblies only captures assemblies that BepInEx itself modifies during patching

**Why it failed:** BepInEx patches `UnityEngine.CoreModule` and `mscorlib` — it doesn't touch `Assembly-CSharp` unless a plugin specifically references it. Also, BepInEx's patching mechanism conflicted with the game's anti-tamper measures.

**Cleanup required:** Had to remove the entire BepInEx folder structure and restore `version.dll` (MelonLoader's proxy DLL, which BepInEx's `winhttp.dll` proxy had displaced).

### 5d. ExtremeDumper

**What was tried:** Using ExtremeDumper to dump the in-memory assemblies from the running game process.

**Result:** ExtremeDumper could not see the Unity Mono process modules correctly.

**Why it failed:** ExtremeDumper expects standard CLR hosting, not Unity's embedded Mono runtime.

### 5e. Dump via Mono P/Invoke (mono_image_loaded)

**What was tried:** Custom MelonLoader mod v1 that used P/Invoke into `mono-2.0-bdwgc.dll` to call `mono_image_loaded("Assembly-CSharp")`, retrieved the `MonoImage` struct, and saved the `raw_data` pointer contents to disk.

**Result:** Successfully dumped `Assembly-CSharp-dumped.dll` (3,939,840 bytes) — but it was **byte-identical** to the on-disk original.

**Why it failed:** `mono_image_loaded` returns the raw PE image as loaded from disk. The decryption happens at the per-method JIT level, not at the image level. The MonoImage struct's `raw_data` is the original encrypted file contents.

---

## 6. Successful Approach (What DID Work)

### 6a. .NET Reflection + IL Bytecode Extraction via MelonLoader Mod

**Key Insight:** While the raw DLL bytes are encrypted, .NET Reflection APIs (`MethodBody.GetILAsByteArray()`) return the **decrypted** IL because they go through the Mono runtime's JIT pathway.

**Method:**
1. Write a custom MelonLoader mod in C#
2. Compile with `csc.exe` (Framework 4.0, C# 5 — no modern features)
3. Deploy to `Mods/` folder
4. The mod runs at `OnApplicationStart`, before the game shows anything
5. Use `AppDomain.CurrentDomain.GetAssemblies()` to find `Assembly-CSharp`
6. Iterate all types, find voice-related enums, methods, and call patterns
7. For each method, call `GetMethodBody().GetILAsByteArray()` for real IL
8. Parse the IL bytecode to find `ldc.i4` (constant load) opcodes near voice method `call`/`callvirt` opcodes
9. Resolve method tokens via `Module.ResolveMethod()` to get actual method names
10. Output everything to text files in `UserData/DumpedAssemblies/`

### 6b. Compilation Command

```batch
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe ^
  /target:library ^
  /reference:"D:\maimai_prism_plus\prismPlus\Package\MelonLoader\MelonLoader.dll" ^
  /out:AssemblyDumper.dll ^
  DumperMod.cs
```

**Important constraints:**
- Must use Framework `csc.exe` (C# 5) — no string interpolation (`$"..."`) , no `nameof()`, no pattern matching
- MelonLoader.dll is the only required reference
- The mod accesses `Assembly-CSharp` types purely via reflection at runtime

### 6c. Deployment

```
Copy AssemblyDumper.dll → Package\Mods\AssemblyDumper.dll
Launch game via start.bat
Mod runs automatically, outputs to Package\UserData\DumpedAssemblies\
Close game
```

### 6d. What the Mod Produces

**`deep_voice_analysis.txt`** (257 KB, 2484 lines) — 7 sections:

| Section | Lines | Content |
|---------|-------|---------|
| System Voice Cue Map | 6–157 | All 150 system voice enum entries with integer indices |
| Partner Voice Cue Map | 159–253 | All 94 partner voice enum entries with integer indices |
| Voice Method Tokens | 255–290 | Metadata tokens for all tracked voice/sound methods |
| Scan Results | 292–2213 | **Main data** — every method that loads a Cue constant near a voice call |
| Summary | 2215–2216 | Stats (19,551 methods scanned, 1,920 matches) |
| ALL Cue Parameter Methods | 2218–2419 | Full IL + resolved call chains for voice methods |
| Classes with Voice Wrappers | 2421–2453 | Index of classes that wrap voice calls |
| Timeline Voice Types | 2455–2478 | VoicePlayableAsset/Behaviour field/method details |
| ConstParameter | 2480–2481 | CommonDialogVoice = VO_000228 |

**`voice_calls.csv`** — Tabular format of scan results (has false positives, see Section 10).

### 6e. The Mod Source Code

The mod source is at `tools/AssemblyDumper/DumperMod.cs` (609 lines). Key technical details:

**Cue Constant Detection:**
The mod walks every IL byte stream looking for `ldc.i4` family opcodes (`0x15`–`0x1F` for small constants, `0x20` for int32) and checks whether a `call`/`callvirt` opcode (`0x28`/`0x6F`) follows within 6 opcodes. If the called method's token resolves to a known voice method (PlayVoice, PlayPartnerVoice, etc.), the combination is logged.

**Method Token Resolution:**
IL bytecodes contain 4-byte metadata tokens for method calls. The mod resolves these via `module.ResolveMethod(token)` to get the actual `Type.Method` name. This is how we know a `call` instruction calls `SoundManager.PlayVoice` vs `Animator.Play`.

**Enum Map Construction:**
Uses `Enum.GetValues()` and `Enum.GetName()` on the reflected Cue enum types to build the integer-to-VO_ID mapping. This is 100% reliable — it's the same data the game uses.

---

## 7. Code Architecture — Voice System

### Central Hub: `Manager.SoundManager`

All voice playback flows through the `SoundManager` singleton. Key methods (with confirmed IL sizes from runtime):

```
PlayVoice(Cue cueIndex, Int32 target)           — 67 bytes IL
PlayPartnerVoice(Cue cueIndex, Int32 target)     — 67 bytes IL
PlayAdvertiseVoice(Cue cueIndex, Int32 target)   — 115 bytes IL
PlaySE(Cue cueIndex, Int32 target)               — 54 bytes IL
PlayBGM(Cue cueIndex, Int32 target)              — 98 bytes IL
PlayLoopSE(Cue cueIndex, Int32 target, Int32 id) — 36 bytes IL
StopVoice(Int32 target)                          — 13 bytes IL
SetVoiceCue(Int32 target, Int32 voiceID)         — 33 bytes IL
SetPartnerVoiceCue(Int32 target, Int32 voiceID)  — 33 bytes IL
SetPartnerVoiceCueUserEquiped(Int32 monitorId)   — 35 bytes IL
GetVoiceCueName(Int32 voiceID)                   — 27 bytes IL
GetPartnerVoiceCueName(Int32 voiceID)            — 27 bytes IL
PlayExecute()                                    — 309 bytes IL
```

### Call Flow

```
Game State Code (e.g. NameEntryProcess.OnUpdate)
    ↓ calls
SoundManager.PlayVoice(Cue.VO_000017, targetMonitor)
    ↓ internally calls
SoundManager.GetPlayerID(targetMonitor)  → returns PlayerID
SoundManager.Play(...)                   → CriAtomEx playback
```

### Wrapper Classes

Several game classes wrap `SoundManager` calls for convenience:

| Class | Wrapper Method | What It Does |
|-------|---------------|--------------|
| `StateEntry` | `PlayVoice(Cue, bool force)` | Iterates `EntryMonitor` list, plays voice on each (72 bytes IL) |
| `StateEntry` | `PlaySE(Cue, bool force)` | Same pattern for SE (76 bytes IL) |
| `MapBehaviour` | `PlayVoice(Cue)` | Direct wrapper, gets monitor index (18 bytes IL) |
| `CodeReadControllerBase` | `PlayVoice(Cue)` | Direct wrapper for code read screens (14 bytes IL) |
| `SeManager` | `PlaySE(Cue, Int32)` | Manages SE deduplication with dictionary (35 bytes IL) |

### Timeline Voice Playback

For scripted sequences (results, login bonus, etc.), voice is triggered via Unity Timeline:

```
VoicePlayableAsset (ScriptableObject)
  Fields: Monitor (ExposedReference), MonitorIndex (int), CueCode (string), IsPartnerVoice (bool)
    ↓ CreatePlayable()  [113 bytes IL]
VoicePlayableBehaviour (PlayableBehaviour)
    ↓ OnBehaviourPlay()  [105 bytes IL]
        If IsPartnerVoice → SoundManager.PlayPartnerVoice
        Else             → SoundManager.PlayVoice
```

The `CueCode` string field on `VoicePlayableAsset` means Timeline clips can reference voice cues by string name (e.g., `"VO_000228"`). This allows asset-driven voice without hardcoded enum values — and means some voice mappings may only exist in Timeline asset data, not in C# code.

### Partner Data Voice Fields

Each partner character has XML configuration with voice references:

```xml
<PartnerData>
  <partnerRoomEntryVoice>VO_000265</partnerRoomEntryVoice>
  <intimateUpVoice01>VO_000266</intimateUpVoice01>
  <intimateUpVoice02>なし</intimateUpVoice02>   <!-- "None" in Japanese -->
  <intimateUpVoice03>なし</intimateUpVoice03>
</PartnerData>
```

`PlayIntimateUpVoiceRandom()` (190 bytes IL) parses these strings via `Enum.TryParse`, builds a list of valid cues, and randomly selects one.

---

## 8. Voice Data Structures

### System Voice: 150 Cues in `Voice_000001.acb`

The system voice cue sheet is selected by the player. `Voice_000001` is the default. The same enum is used regardless of which voice pack is loaded — the cue indices are standardized across all voice packs. If a voice pack doesn't include a particular cue, it simply plays nothing.

**Index range:** 0–276 (non-contiguous, 150 members across 277 possible slots)

**Notable gaps:** Indices 9, 13, 15, 20, 22, 24, 32–38, 40–51, 53–63, 65–73, 77–87, 91–108, 111–140, 150–152, 154, 156–161, 163–167, 169, 174, 181, 183, 186–203, 205, 210–221, 226, 232–233, 235–236, 241, 243–249, 251–255, 257–268, 270–275.

### Partner Voice: 94 Cues in `Voice_Partner_XXXXXX.acb`

Each partner character has its own `Voice_Partner_XXXXXX.acb/awb` pair. Not all partners have all 94 cues:

| Tier | Cue Count | Example Partners |
|------|-----------|-----------------|
| Full | 91 cues | Most main characters |
| Near-full | 89 cues | Some characters |
| Minimal | 75 cues | Newer/simpler characters |

**Index range:** 0–94 (nearly contiguous, only index 83 is missing)

### Dual-Map VO_IDs

Some VO_IDs appear in BOTH the System Voice and Partner Voice enum. This is NOT an error — they represent the same **logical voice event** but with **different audio content** in different ACB files:

| VO_ID | System Index | Partner Index | Meaning |
|-------|-------------|---------------|---------|
| VO_000099 | 257 | 7 | Voice line present in both ACBs |
| VO_000101 | 258 | 8 | Voice line present in both ACBs |
| VO_000103 | 251 | 69 | Voice line present in both ACBs |
| VO_000104 | 252 | 70 | Voice line present in both ACBs |
| VO_000109 | 253 | 71 | Voice line present in both ACBs |
| VO_000112 | 254 | 72 | Voice line present in both ACBs |
| VO_000133 | 259 | 26 | Voice line present in both ACBs |
| VO_000142 | 141 | 88 | System: Tab SE / Partner: voice line |
| VO_000151 | 260 | 29 | Voice line present in both ACBs |
| VO_000152 | 261 | 30 | Voice line present in both ACBs |
| VO_000153 | 262 | 31 | Voice line present in both ACBs |
| VO_000155 | 263 | 32 | Voice line present in both ACBs |
| VO_000157 | 264 | 33 | Voice line present in both ACBs |
| VO_000158 | 265 | 34 | Voice line present in both ACBs |
| VO_000159 | 266 | 35 | Voice line present in both ACBs |
| VO_000182 | 267 | 40 | Voice line present in both ACBs |
| VO_000184 | 268 | 41 | Voice line present in both ACBs |
| VO_000187 | 269 | 42 | System: Score kind / Partner: voice line |
| VO_000188 | 270 | 43 | System: Score kind / Partner: voice line |
| VO_000189 | 271 | 44 | Voice line present in both ACBs |
| VO_000206 | 256 | 84 | Voice line present in both ACBs |
| VO_000207 | 206 | 89 | Voice line present in both ACBs |
| VO_000208 | 207 | 90 | Voice line present in both ACBs |
| VO_000209 | 208 | 91 | Voice line present in both ACBs |
| VO_000210 | 209 | 92 | Voice line present in both ACBs |
| VO_000247 | 272 | 59 | Voice line present in both ACBs |
| VO_000253 | 274 | 86 | Voice line present in both ACBs |
| VO_000265 | 276 | 93 | System: voice / Partner: room entry voice |

When the code calls `SoundManager.PlayVoice(Cue.VO_000265)`, it plays from the System Voice ACB (index 276). When it calls `SoundManager.PlayPartnerVoice(Cue.VO_000265)`, it plays from the Partner Voice ACB (index 93).

---

## 9. Interpreting the Scan Results

### How to Read `deep_voice_analysis.txt` Scan Entries

Each line in the scan section follows this format:

```
[CallerType.CallerMethod] calls TargetType.TargetMethod with Cue VO_XXXXXX (index) at IL offset NNN (resolved)
```

**To determine if an entry is a genuine voice call:**

1. **Check `TargetType.TargetMethod`** — Only these are actual voice calls:
   - `SoundManager.PlayVoice` — System voice
   - `SoundManager.PlayPartnerVoice` — Partner voice
   - `SoundManager.PlayAdvertiseVoice` — Attract mode voice
   - `SoundManager.PlaySE` — Sound effect (same cue enum, different logical use)
   - `SoundManager.PlayBGM` — BGM (same enum, different ACB)
   - `SoundManager.StopVoice` — Stop voice playback
   - `StateEntry.PlayVoice` — Wrapper → PlayVoice
   - `MapBehaviour.PlayVoice` — Wrapper → PlayVoice
   - `CodeReadControllerBase.PlayVoice` — Wrapper → PlayVoice

2. **IGNORE these targets** — they are false positives:
   - `Animator.Play` — Unity animation system, integer is animation state hash
   - `NavigationCharacter.Play` — Navigation animation, integer is anim index
   - `MovieController.Play` / `CreateMoviePlayer` — Movie player, integer is movie config
   - `PlayableDirector.*` — Unity Timeline, integer is binding index
   - `AnimationParts.Play` — UI animation trigger
   - `GameManager.set_AutoPlay` — Boolean-as-int parameter
   - `GamePlayManager.*` — Gameplay score/state params
   - `SelectorBackgroundController.Play` — Background animation index
   - Any `get_*` / `set_*` property — Integer is a property value, not a cue

3. **Beware of small integer Cue values** — Cue index 0 (`VO_000001`), 1 (`VO_000002`), 2 (`VO_000003`) etc. are extremely common as non-cue parameters:
   - `0` = Common default/false/zero parameter
   - `1` = True, player index 1, first item
   - `2` = Player count, secondary index
   - `3` = Enum value, counter

   **Rule of thumb:** If the same method call shows `VO_000001`–`VO_000008` at the same IL offset, those integers are likely being used as parameters to a non-voice method, and only *some* values may coincide with actual cue constants.

### How to Read the `ALL Cue Parameter Methods` Section

These entries show the full method detail:

```
[ClassName] ReturnType MethodName(Params)
  Token: 0x06XXXXXX
  IL(N): XX XX XX XX ...          ← Raw IL bytecode
  Calls: Method1 Method2 ...     ← Resolved method calls from the IL
  Locals: [0]Type [1]Type ...    ← Local variable types
```

**This is the most valuable section** for understanding voice call chains. The `Calls:` line shows exactly which methods are invoked, in order. For example:

```
[CollectionProcess] Void PlayIntimateUpVoiceRandom(Int32 monitorId)
  Calls: CollectionInfo.GetCurrentCenterCollectionData ... DataManager.GetPartner
         PartnerData.get_intimateUpVoice01 List`1.Add
         PartnerData.get_intimateUpVoice02 List`1.Add
         PartnerData.get_intimateUpVoice03 List`1.Add
         ... Enum.TryParse ... Random.Range
         SoundManager.SetPartnerVoiceCue ... SoundManager.PlayPartnerVoice
```

This reveals the full logic: get partner data → read intimateUpVoice fields → parse strings to cue enums → randomly select → play.

---

## 10. Known Limitations & False Positives

### 10a. The Integer Ambiguity Problem

The IL bytecode scanner finds ALL integer constants near ALL method calls. Since the Cue enum is backed by plain integers (`int`), any method that takes an `int` parameter can produce a false positive. The scanner reports ~1,920 matches but only ~88 are genuine voice calls.

**How to filter:**
- Check the target method name (see list in Section 9)
- Discard entries where the VO_ID index is 0–8 and the target is NOT a SoundManager/voice method
- Cross-reference: if the same VO_ID appears at the same IL offset via different target methods, the constant is likely a shared integer parameter, not a cue

### 10b. Partner Voice VO_ID Mismatch in Scan

The scanning mod uses the **System Voice** enum names to label Cue constants. When it sees integer value `65` in a `PlayPartnerVoice` call, it reports `VO_000066` (System Voice name for index 65). But in the Partner Voice enum, index 65 is `VO_000249`.

**Correction table for confirmed PlayPartnerVoice calls:**

| Mod Reported | Cue Index | Correct Partner VO_ID | Context |
|---|---|---|---|
| VO_000066 (sys idx 65) | 65 | **VO_000249** | ShopPartnerGetWindow.PlayPartnerVoice |
| VO_000037 (sys idx 36) | 36 | **VO_000164** | ContinueProcess.OnUpdate |
| VO_000040 (sys idx 39) | 39 | **VO_000167** | GameOverProcess.OnUpdate |
| VO_000041 (sys idx 40) | 40 | **VO_000182** | GenreSelectSequence.OnStartSequence |
| VO_000042 (sys idx 41) | 41 | **VO_000184** | MusicSelectSequence.OnStartSequence |
| VO_000045 (sys idx 44) | 44 | **VO_000189** | SortSettingSequence.OnStartSequence |
| VO_000008 (sys idx 7) | 7 | **VO_000099** | DifficultySelectSequence.OnStartSequence |
| VO_000009 (sys idx 8) | 8 | **VO_000101** | MenuSelectSequence.OnStartSequence; VoiceCheck |
| VO_000075 (sys idx 74) | 74 | **VO_000191** | SortSettingSequence.Update sort switch |
| VO_000076 (sys idx 75) | 75 | **VO_000192** | SortSettingSequence.Update sort switch |
| VO_000077 (sys idx 76) | 76 | **VO_000193** | SortSettingSequence.Update sort switch |
| VO_000063 (sys idx 62) | 62 | **VO_000115** | LoginBonusMonitor.GetCharacterFadeOutWait1 |
| VO_000250 | 66 | **VO_000250** | LoginBonusMonitor.Initialize/SelectCard |
| VO_000251 | 67 | **VO_000251** | CollectionProcess.InputPartnerSequence |
| VO_000252 | 68 | **VO_000252** | CollectionProcess.TouchProcess; ResultProcess |
| VO_000166 | 38 | **VO_000166** | GameOverProcess.OnUpdate |
| VO_000190 | 73 | **VO_000190** | SortSettingSequence.Update |
| VO_000194 | 77 | **VO_000194** | SortSettingSequence.Update |
| VO_000195 | 78 | **VO_000195** | SortSettingSequence.Update |
| VO_000197 | 80 | **VO_000197** | SortSettingSequence.Update |
| VO_000198 | 81 | **VO_000198** | SortSettingSequence.Update |
| VO_000199 | 82 | **VO_000199** | SortSettingSequence.Update |

**Why this happens:** The mod builds its `sysCueMap` from `Mai2.Voice_000001.Cue` and uses it for ALL integer-to-name lookups. When an integer matches a system voice index, it reports the system name even if the call is to `PlayPartnerVoice`. A fixed mod should check whether the called method is `PlayPartnerVoice` and use the `partnerCueMap` instead.

### 10c. Timeline/Asset-Driven Voices

Some voices are NOT called from C# code at all — they're embedded in Unity Timeline assets (`VoicePlayableAsset.CueCode` string field). These won't appear in code scanning. To fully map these, you'd need to dump Timeline assets from the game's AssetBundles.

### 10d. Dynamic Cue Selection

Some voices are selected at runtime based on game state (e.g., `MenuSelectSequence.VoiceCheck` uses a `switch` on `MenuType` enum). The scanner only captures what constants are loaded in the method, not the full control flow. Multiple VO_IDs at the same IL offset often indicate a `switch` statement — each value is a different case.

---

## 11. File Inventory

### Workspace Root (`D:\maimai circle voice and partner data\`)

| File | Purpose |
|------|---------|
| `voice_action_mapping.csv` | **Primary deliverable** — 244 mapped voice entries |
| `build_voice_csv.py` | Python script that generates the CSV from hardcoded data |
| `DOCUMENTATION.md` | This file |
| `extract_cri_metadata.py` | Extracts CRI ACB metadata (cue names, indices) |
| `extract_voices_to_mp3.py` | Converts extracted HCA voice files to MP3 |
| `rename_partner_voices.py` | Renames partner voice files using VO_ID mapping |

### `SystemVoiceData/`

| File | Description |
|------|-------------|
| `Voice_000001.acb` | System voice cue sheet (default voice) |
| `Voice_000001.awb` | System voice waveform bank |
| `.hcakey` | HCA decryption key |

### `PartnerSoundData/`

26 partner voice packs (`Voice_Partner_000001` through `Voice_Partner_000035`, with gaps). Each is an `.acb`/`.awb` pair.

### `partner_mapping/`

26 partner directories, each containing `Partner.xml` with character config including `partnerRoomEntryVoice` and `intimateUpVoice01/02/03` fields.

### `tools/AssemblyDumper/`

| File | Description |
|------|-------------|
| `DumperMod.cs` | **The custom MelonLoader mod source** (609 lines, C# 5) |
| `AssemblyDumper.dll` | Compiled mod binary (deploy to Mods folder) |
| `deep_voice_analysis.txt` | **Runtime analysis output** (257 KB, 2484 lines) |
| `voice_calls.csv` | Tabular scan results (contains false positives) |
| `voice_analysis.txt` | Output from mod v1 (less detailed, superseded) |
| `Assembly-CSharp-dumped.dll` | Raw memory dump (encrypted, not useful for decompilation) |

### `tools/`

| Item | Description |
|------|-------------|
| `de4dot/` | Deobfuscation tool (tried, did not resolve encryption) |
| `Assembly-CSharp-cleaned.dll` | de4dot output (still encrypted) |
| `bepinex/` | BepInEx files (tried, caused black screen) |

### `Decomp/`

Full decompiled project from dnSpy export. All `.cs` files have empty method bodies. Useful for class/method/field discovery but not for logic analysis.

### `CriTools-master/`

CRI audio extraction toolkit (ACB/AWB/HCA processing).

### `vgmstream-win64/`

Audio format conversion tool for game audio formats.

---

## 12. Recommendations for Future Work

### 12a. Fix the Partner Voice Name Bug in the Mod

The mod should maintain two separate maps and select the correct one based on whether the call is to `PlayPartnerVoice` vs `PlayVoice`. Modify the scan section of `DumperMod.cs` to check the resolved method name before choosing the cue map for name lookup.

### 12b. Enhanced Mod for Full IL Decompilation

Instead of scanning for integer patterns, build a proper IL disassembler in the mod that:
1. Walks the IL byte stream instruction by instruction
2. Tracks the evaluation stack (simulates push/pop)
3. For each `call`/`callvirt`, knows what values are on the stack
4. Can distinguish `PlayVoice(Cue.VO_000017, 0)` from `PlayVoice(Cue.VO_000001, 17)`

This would eliminate the target-vs-cue ambiguity for small integers.

### 12c. Dump Decompiled C# via Harmony/HarmonyX

Instead of raw IL extraction, use Harmony patches (available through MelonLoader) to hook voice methods at runtime and log every call with full arguments:

```csharp
[HarmonyPatch(typeof(SoundManager), "PlayVoice")]
class VoicePatch {
    static void Prefix(Cue cueIndex, int target) {
        MelonLogger.Msg($"PlayVoice({cueIndex}, {target}) at {Environment.StackTrace}");
    }
}
```

This would capture actual runtime voice calls with stack traces showing EXACTLY what triggered each voice. However, this requires the game to actually reach each screen/state — you'd need to play through the entire game to capture everything.

### 12d. Unity Asset Dump for Timeline Voices

Use a Unity asset extraction tool (e.g., AssetStudio, UABE) to extract `VoicePlayableAsset` ScriptableObjects from the game's asset bundles. These contain `CueCode` strings that map Timeline-driven voices. This would catch voices not referenced in C# code.

### 12e. Cross-Reference with Other Voice Packs

Only `Voice_000001` was analyzed. Comparing cue presence across multiple voice packs (e.g., examining which cue indices are present in each ACB) could reveal which cues are universal vs. character-specific.

### 12f. Live Hooking for Complete Coverage

The most thorough approach:
1. Hook `SoundManager.PlayVoice`, `PlayPartnerVoice`, `PlayAdvertiseVoice`, `PlaySE`, `PlayBGM`
2. Log every call with cue enum value, target, and calling method stack trace
3. Play through every game state systematically
4. Correlate logged calls with game state

This would give 100% coverage for all voices that actually play during testing, with zero false positives.

---

## Appendix A — Cue Enum Index Listings

### System Voice (`Mai2.Voice_000001.Cue`) — 150 entries

| VO_ID | Index | | VO_ID | Index | | VO_ID | Index |
|-------|-------|---|-------|-------|---|-------|-------|
| VO_000001 | 0 | | VO_000054 | 53 | | VO_000185 | 184 |
| VO_000002 | 1 | | VO_000055 | 54 | | VO_000186 | 185 |
| VO_000003 | 2 | | VO_000056 | 55 | | VO_000205 | 204 |
| VO_000004 | 3 | | VO_000057 | 56 | | VO_000207 | 206 |
| VO_000005 | 4 | | VO_000058 | 57 | | VO_000208 | 207 |
| VO_000006 | 5 | | VO_000059 | 58 | | VO_000209 | 208 |
| VO_000007 | 6 | | VO_000060 | 59 | | VO_000210 | 209 |
| VO_000008 | 7 | | VO_000061 | 60 | | VO_000223 | 222 |
| VO_000009 | 8 | | VO_000062 | 61 | | VO_000224 | 223 |
| VO_000011 | 10 | | VO_000063 | 62 | | VO_000225 | 224 |
| VO_000012 | 11 | | VO_000065 | 64 | | VO_000226 | 225 |
| VO_000013 | 12 | | VO_000066 | 65 | | VO_000227 | 226 |
| VO_000015 | 14 | | VO_000075 | 74 | | VO_000228 | 227 |
| VO_000016 | 15 | | VO_000076 | 75 | | VO_000229 | 228 |
| VO_000017 | 16 | | VO_000077 | 76 | | VO_000230 | 229 |
| VO_000018 | 17 | | VO_000089 | 88 | | VO_000231 | 230 |
| VO_000019 | 18 | | VO_000090 | 89 | | VO_000232 | 231 |
| VO_000020 | 19 | | VO_000091 | 90 | | VO_000235 | 234 |
| VO_000022 | 21 | | VO_000110 | 109 | | VO_000238 | 237 |
| VO_000024 | 23 | | VO_000111 | 110 | | VO_000239 | 238 |
| VO_000026 | 25 | | VO_000142 | 141 | | VO_000240 | 239 |
| VO_000027 | 26 | | VO_000143 | 142 | | VO_000241 | 240 |
| VO_000028 | 27 | | VO_000144 | 143 | | VO_000242 | 241 |
| VO_000029 | 28 | | VO_000145 | 144 | | VO_000255 | 242 |
| VO_000030 | 29 | | VO_000146 | 145 | | VO_000256 | 243 |
| VO_000031 | 30 | | VO_000147 | 146 | | VO_000257 | 244 |
| VO_000032 | 31 | | VO_000148 | 147 | | VO_000258 | 245 |
| VO_000033 | 32 | | VO_000149 | 148 | | VO_000259 | 246 |
| VO_000034 | 33 | | VO_000150 | 149 | | VO_000260 | 247 |
| VO_000035 | 34 | | VO_000154 | 153 | | VO_000261 | 248 |
| VO_000036 | 35 | | VO_000156 | 155 | | VO_000262 | 249 |
| VO_000037 | 36 | | VO_000163 | 162 | | VO_000263 | 250 |
| VO_000038 | 37 | | VO_000169 | 168 | | VO_000103 | 251 |
| VO_000040 | 39 | | VO_000170 | 169 | | VO_000104 | 252 |
| VO_000041 | 40 | | VO_000171 | 170 | | VO_000109 | 253 |
| VO_000042 | 41 | | VO_000172 | 171 | | VO_000112 | 254 |
| VO_000043 | 42 | | VO_000173 | 172 | | VO_000114 | 255 |
| VO_000044 | 43 | | VO_000174 | 173 | | VO_000206 | 256 |
| VO_000045 | 44 | | VO_000176 | 175 | | VO_000099 | 257 |
| VO_000046 | 45 | | VO_000177 | 176 | | VO_000101 | 258 |
| VO_000047 | 46 | | VO_000178 | 177 | | VO_000133 | 259 |
| VO_000048 | 47 | | VO_000179 | 178 | | VO_000151 | 260 |
| VO_000049 | 48 | | VO_000180 | 179 | | VO_000152 | 261 |
| VO_000050 | 49 | | VO_000181 | 180 | | VO_000153 | 262 |
| VO_000051 | 50 | | VO_000183 | 182 | | VO_000155 | 263 |
| VO_000052 | 51 | | — | — | | VO_000157 | 264 |
| VO_000053 | 52 | | — | — | | VO_000158 | 265 |
| — | — | | — | — | | VO_000159 | 266 |
| — | — | | — | — | | VO_000182 | 267 |
| — | — | | — | — | | VO_000184 | 268 |
| — | — | | — | — | | VO_000187 | 269 |
| — | — | | — | — | | VO_000188 | 270 |
| — | — | | — | — | | VO_000189 | 271 |
| — | — | | — | — | | VO_000247 | 272 |
| — | — | | — | — | | VO_000248 | 273 |
| — | — | | — | — | | VO_000253 | 274 |
| — | — | | — | — | | VO_000264 | 275 |
| — | — | | — | — | | VO_000265 | 276 |

Note: Entries from index 251 onward were appended in later game updates (non-sequential VO_IDs).

### Partner Voice (`Mai2.Voice_Partner_000001.Cue`) — 94 entries

| VO_ID | Index | | VO_ID | Index |
|-------|-------|---|-------|-------|
| VO_000080 | 0 | | VO_000082 | 60 |
| VO_000081 | 1 | | VO_000083 | 61 |
| VO_000084 | 2 | | VO_000115 | 62 |
| VO_000085 | 3 | | VO_000117 | 63 |
| VO_000086 | 4 | | VO_000248 | 64 |
| VO_000087 | 5 | | VO_000249 | 65 |
| VO_000088 | 6 | | VO_000250 | 66 |
| VO_000099 | 7 | | VO_000251 | 67 |
| VO_000101 | 8 | | VO_000252 | 68 |
| VO_000113 | 9 | | VO_000103 | 69 |
| VO_000114 | 10 | | VO_000104 | 70 |
| VO_000116 | 11 | | VO_000109 | 71 |
| VO_000118 | 12 | | VO_000112 | 72 |
| VO_000119 | 13 | | VO_000190 | 73 |
| VO_000120 | 14 | | VO_000191 | 74 |
| VO_000121 | 15 | | VO_000192 | 75 |
| VO_000122 | 16 | | VO_000193 | 76 |
| VO_000123 | 17 | | VO_000194 | 77 |
| VO_000124 | 18 | | VO_000195 | 78 |
| VO_000125 | 19 | | VO_000196 | 79 |
| VO_000126 | 20 | | VO_000197 | 80 |
| VO_000127 | 21 | | VO_000198 | 81 |
| VO_000128 | 22 | | VO_000199 | 82 |
| VO_000129 | 23 | | *(missing)* | *83* |
| VO_000130 | 24 | | VO_000206 | 84 |
| VO_000131 | 25 | | VO_000243 | 85 |
| VO_000133 | 26 | | VO_000253 | 86 |
| VO_000139 | 27 | | VO_000254 | 87 |
| VO_000141 | 28 | | VO_000142 | 88 |
| VO_000151 | 29 | | VO_000207 | 89 |
| VO_000152 | 30 | | VO_000208 | 90 |
| VO_000153 | 31 | | VO_000209 | 91 |
| VO_000155 | 32 | | VO_000210 | 92 |
| VO_000157 | 33 | | VO_000265 | 93 |
| VO_000158 | 34 | | VO_000266 | 94 |
| VO_000159 | 35 | | | |
| VO_000164 | 36 | | | |
| VO_000165 | 37 | | | |
| VO_000166 | 38 | | | |
| VO_000167 | 39 | | | |
| VO_000182 | 40 | | | |
| VO_000184 | 41 | | | |
| VO_000187 | 42 | | | |
| VO_000188 | 43 | | | |
| VO_000189 | 44 | | | |
| VO_000200 | 45 | | | |
| VO_000201 | 46 | | | |
| VO_000202 | 47 | | | |
| VO_000203 | 48 | | | |
| VO_000204 | 49 | | | |
| VO_000211 | 50 | | | |
| VO_000213 | 51 | | | |
| VO_000214 | 52 | | | |
| VO_000217 | 53 | | | |
| VO_000220 | 54 | | | |
| VO_000222 | 55 | | | |
| VO_000244 | 56 | | | |
| VO_000245 | 57 | | | |
| VO_000246 | 58 | | | |
| VO_000247 | 59 | | | |

---

## Appendix B — Full Method Signatures

### Voice Playback Methods

```
Manager.SoundManager:
  PlayerID PlayVoice(Cue cueIndex, Int32 target)           — 67 bytes IL
  PlayerID PlayPartnerVoice(Cue cueIndex, Int32 target)    — 67 bytes IL
  Void     PlayAdvertiseVoice(Cue cueIndex, Int32 target)  — 115 bytes IL
  PlayerID PlaySE(Cue cueIndex, Int32 target)              — 54 bytes IL
  PlayerID PlayLoopSE(Cue cueIndex, Int32 target, Int32 id)— 36 bytes IL
  PlayerID PlayGameSE(Cue cueIndex, Int32 target, Single volume) — 23 bytes IL
  PlayerID PlayGameSingleSe(Cue cueIndex, Int32 target, PlayerID player, Single volume) — 28 bytes IL
  Void     PlaySystemSE(Cue cueIndex)                      — 17 bytes IL
  Void     PlayBGM(Cue cueIndex, Int32 target)             — 98 bytes IL
  PlayerID PlayJingle(Cue cueIndex, Int32 target)          — 27 bytes IL
  Void     StopVoice(Int32 target)                         — 13 bytes IL

  Void   SetVoiceCue(Int32 target, Int32 voiceID)          — 33 bytes IL
  Void   SetPartnerVoiceCue(Int32 target, Int32 voiceID)   — 33 bytes IL
  Void   SetPartnerVoiceCueUserEquiped(Int32 monitorId)    — 35 bytes IL
  String GetVoiceCueName(Int32 voiceID)                    — 27 bytes IL
  String GetPartnerVoiceCueName(Int32 voiceID)             — 27 bytes IL
  Void   PlayExecute()                                     — 309 bytes IL
```

### Voice Wrapper Methods

```
Process.Entry.State.StateEntry:
  Void PlayVoice(Cue cue, Boolean force)                   — 72 bytes IL
  Void PlaySE(Cue cue, Boolean force)                      — 76 bytes IL

Monitor.MapCore.MapBehaviour:
  PlayerID PlayVoice(Cue cueIndex)                         — 18 bytes IL
  PlayerID PlaySE(Cue cueIndex)                            — 18 bytes IL

Monitor.CodeRead.Controller.CodeReadControllerBase:
  Void PlayVoice(Cue cue)                                  — 14 bytes IL
  Void PlaySE(Cue cue)                                     — 14 bytes IL

Manager.SeManager:
  Void PlaySE(Cue cueIndex, Int32 target)                  — 35 bytes IL
  Void PlaySE_Impl(Cue cue, Int32 index)                   — 51 bytes IL
```

### Partner Voice Logic Methods

```
CollectionProcess:
  IEnumerator PlayPartnerRoomEntryVoice(Int32 monitorId)   — 21 bytes IL (creates coroutine)
  Void PlayIntimateUpVoiceRandom(Int32 monitorId)          — 190 bytes IL (full logic)

ShopPartnerGetWindow:
  IEnumerator PlayPartnerVoice(Int32 monitorId)            — 21 bytes IL (creates coroutine)

Process.SubSequence.MenuSelectSequence:
  Void VoiceCheck()                                        — 68 bytes IL (switch on MenuType)
```

---

## Appendix C — Partner XML Voice Fields

All 26 partner XML files follow this pattern:

```xml
<PartnerData>
  <dataName>partnerXXXXXX</dataName>
  <partnerRoomEntryVoice>VO_000265</partnerRoomEntryVoice>
  <intimateUpVoice01>VO_000266</intimateUpVoice01>
  <intimateUpVoice02>なし</intimateUpVoice02>    <!-- "None" = no voice -->
  <intimateUpVoice03>なし</intimateUpVoice03>
</PartnerData>
```

**Every single partner** uses `VO_000265` for room entry and `VO_000266` for intimate-up voice 1. Partners 000001 through 000035 all have the same XML values for these fields, with `intimateUpVoice02` and `intimateUpVoice03` set to "なし" (None).

The `PlayIntimateUpVoiceRandom` method parses these strings to `Cue` enum values via `Enum.TryParse`, skips "なし" entries, and randomly selects from the valid ones. With only `intimateUpVoice01` being valid for all partners, the "random" selection always plays `VO_000266`.

---

*Document generated from runtime analysis data collected via custom MelonLoader mod. Last analysis run against maimai (Sinmai.exe), Unity 2018.4.7f1, MelonLoader v0.6.4.*
