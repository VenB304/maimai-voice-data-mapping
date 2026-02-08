# maimai Voice & Partner Data Mapping

Research project documenting the voice cue system in SEGA's **maimai DX PRiSM Plus (SDEX 1.55)**. Maps all `VO_XXXXXX` voice identifiers to their in-game behavior and context.

## What This Is

A comprehensive mapping of **244 voice cue IDs** (150 System Voice + 94 Partner Voice) to their game functions — what screen they play on, what triggers them, and how they're called in code.

The game uses runtime method body encryption, making standard decompilation impossible. A custom MelonLoader mod was developed to extract decrypted IL bytecodes via .NET Reflection at runtime, enabling analysis of the voice call chains.

## Key Files

| File | Description |
|------|-------------|
| `voice_action_mapping.csv` | The primary deliverable — all 244 voice cues mapped to game context |
| `DOCUMENTATION.md` | Full technical report: methodology, architecture, reproduction steps |
| `tools/AssemblyDumper/DumperMod.cs` | Custom MelonLoader mod source for runtime IL analysis |
| `build_voice_csv.py` | Python script to regenerate the CSV from curated data |
| `tools/AssemblyDumper/voice_calls.csv` | Raw scan output (contains false positives, see docs) |

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `extract_cri_metadata.py` | Extract CRI ACB cue sheet metadata |
| `extract_voices_to_mp3.py` | Convert extracted HCA voice files to MP3 |
| `rename_partner_voices.py` | Rename partner voice files using VO_ID mapping |
| `old scripts/*.ps1` | Earlier PowerShell versions of extraction/processing scripts |

## CSV Columns

| Column | Description |
|--------|-------------|
| `VO_ID` | Voice identifier (e.g., `VO_000017`) |
| `Cue_Index` | Integer index in the ACB cue sheet |
| `Voice_Type` | `System` or `Partner` |
| `ACB_File` | Which `.acb` file contains this cue |
| `Game_Context` | What screen/action triggers this voice |
| `Caller_Methods` | C# methods that reference this cue |
| `Evidence` | `Confirmed` (runtime IL evidence) or `Inferred` (structural/positional) |
| `Also_In_Other_Voice_Map` | Whether the VO_ID exists in both System and Partner enums |
| `Notes` | Additional context |

## Confidence

- **88 / 244 entries (36%)** have confirmed runtime evidence from IL bytecode analysis
- Remaining entries are classified as "Inferred" — see `DOCUMENTATION.md` Section 10 for how to improve coverage

## Requirements for the Mod

- MelonLoader v0.6.x installed on the game
- Compile with: `csc.exe /target:library /reference:MelonLoader.dll /out:AssemblyDumper.dll DumperMod.cs`
- Deploy `AssemblyDumper.dll` to the game's `Mods/` folder

See `DOCUMENTATION.md` for complete reproduction steps.

## License

This repository contains original research tools and documentation only. No game assets, audio files, or copyrighted game code are included.
