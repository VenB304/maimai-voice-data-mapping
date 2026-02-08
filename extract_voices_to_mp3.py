#!/usr/bin/env python3
"""
maimai DX Voice Extractor
Extracts voice lines from CRI AWB archives and converts them to MP3.

Uses vgmstream-cli to decode HCA audio from AWB subsongs,
then pipes through ffmpeg to produce MP3 files named by VO_ID.

Output structure:
  output/
    SystemVoice_SoundData/
      VO_000001.mp3
      VO_000002.mp3
      ...
    でらっくま_Derakkuma_SoundData/
      VO_000080.mp3
      VO_000081.mp3
      ...

Usage:
    python extract_voices_to_mp3.py
    python extract_voices_to_mp3.py --output-dir MyOutput
    python extract_voices_to_mp3.py --partners-only
    python extract_voices_to_mp3.py --system-only
    python extract_voices_to_mp3.py --partner-id 11
"""

import os
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional

# Fix Windows console encoding for Japanese characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
VGMSTREAM_CLI = SCRIPT_DIR / "vgmstream-win64" / "vgmstream-cli.exe"
FFMPEG_PATH = Path(os.environ.get("FFMPEG_PATH", r"C:\Users\Ven\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"))
PARTNER_SOUND_DIR = SCRIPT_DIR / "PartnerSoundData"
SYSTEM_SOUND_DIR = SCRIPT_DIR / "SystemVoiceData"
PARTNER_MAPPING_DIR = SCRIPT_DIR / "partner_mapping"
PARTNER_SORT_XML = PARTNER_MAPPING_DIR / "PartnerSort.xml"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output_voices"

# MP3 encoding quality (ffmpeg -q:a value, 0=best 9=worst, 2=~190kbps VBR)
MP3_QUALITY = 2

# HCA decryption key for CRI audio (64-bit integer)
# vgmstream reads this from a .hcakey file placed next to the AWB files
HCA_KEY = "9170825592834449000"

# English translations for partner names
# Japanese name -> English romanization
PARTNER_TRANSLATIONS: Dict[str, str] = {
    "でらっくま": "Derakkuma",
    "らいむっくま＆れもんっくま": "Raimikkuma & Remonkkuma",
    "乙姫": "Otohime",
    "ラズ": "Razu",
    "シフォン": "Chiffon",
    "ソルト": "Salt",
    "しゃま": "Shama",
    "みるく": "Milk",
    "乙姫（すぷらっしゅ）": "Otohime (Splash)",
    "しゃま（ゆにばーす）": "Shama (Universe)",
    "みるく（ゆにばーす）": "Milk (Universe)",
    "ちびみるく": "Chibi Milk",
    "百合咲ミカ": "Yurisaki Mika",
    "ラズ（ふぇすてぃばる）": "Razu (Festival)",
    "シフォン（ふぇすてぃばる）": "Chiffon (Festival)",
    "ソルト（ふぇすてぃばる）": "Salt (Festival)",
    "黒姫": "Kurohime",
    "ずんだもん": "Zundamon",
    "乙姫（ばでぃーず）": "Otohime (BUDDiES)",
    "らいむっくま＆れもんっくま（ばでぃーず）": "Raimikkuma & Remonkkuma (BUDDiES)",
    "ラズ（ばでぃーず）": "Razu (BUDDiES)",
    "ソルト（ぷりずむ）": "Salt (PRiSM)",
    "みるく（ぷりずむ）": "Milk (PRiSM)",
    "超てんちゃん": "Cho Tenchan",
    "リズ": "Rizu",
    "シフォン（さーくる）": "Chiffon (CiRCLE)",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PartnerInfo:
    """Partner character information."""
    id: int
    id_str: str          # e.g. "000011"
    name_jp: str         # Japanese name
    name_en: str         # English translation
    folder_name: str     # Output folder name
    awb_path: Path       # Path to AWB file
    acb_path: Path       # Path to ACB file


@dataclass
class SubsongInfo:
    """Information about a single subsong/track in an AWB."""
    index: int           # 1-based subsong index
    stream_name: str     # e.g. "VO_000001"
    sample_rate: int
    channels: int
    duration_sec: float
    total_samples: int


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_hcakey_files(hca_key: Optional[str] = None) -> None:
    """
    Create .hcakey files in AWB directories so vgmstream can decrypt HCA audio.
    The file is named '.hcakey' (starts with a dot) and contains the key as text.
    vgmstream reads this automatically for all files in the same directory.
    """
    key = hca_key or HCA_KEY
    if not key:
        return

    for directory in [PARTNER_SOUND_DIR, SYSTEM_SOUND_DIR]:
        if not directory.exists():
            continue
        key_file = directory / ".hcakey"
        if not key_file.exists() or key_file.read_text().strip() != key:
            key_file.write_text(key, encoding="ascii")
            print(f"  Created {key_file}")


def check_dependencies() -> bool:
    """Verify that vgmstream-cli and ffmpeg are available."""
    ok = True

    if not VGMSTREAM_CLI.exists():
        print(f"ERROR: vgmstream-cli not found at: {VGMSTREAM_CLI}")
        print("       Download from https://github.com/vgmstream/vgmstream/releases")
        ok = False

    if not FFMPEG_PATH.exists():
        print(f"ERROR: ffmpeg not found at: {FFMPEG_PATH}")
        print("       Install from https://ffmpeg.org/download.html")
        print("       Or set FFMPEG_PATH environment variable")
        ok = False
    else:
        try:
            result = subprocess.run(
                [str(FFMPEG_PATH), "-version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                print("ERROR: ffmpeg returned an error")
                ok = False
        except subprocess.TimeoutExpired:
            print("ERROR: ffmpeg timed out")
            ok = False

    return ok


def get_subsong_count(awb_path: Path) -> int:
    """Get the number of subsongs in an AWB file using vgmstream."""
    try:
        result = subprocess.run(
            [str(VGMSTREAM_CLI), "-m", "-s", "1", str(awb_path)],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            if "stream count:" in line:
                return int(line.split(":")[-1].strip())
    except Exception as e:
        print(f"  Warning: Could not get subsong count: {e}")
    return 0


def get_subsong_info(awb_path: Path, subsong_index: int) -> Optional[SubsongInfo]:
    """Get metadata for a specific subsong."""
    try:
        result = subprocess.run(
            [str(VGMSTREAM_CLI), "-m", "-s", str(subsong_index), str(awb_path)],
            capture_output=True, text=True, timeout=30
        )

        info = SubsongInfo(
            index=subsong_index,
            stream_name="",
            sample_rate=0,
            channels=0,
            duration_sec=0.0,
            total_samples=0,
        )

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("stream name:"):
                info.stream_name = line.split(":", 1)[1].strip()
            elif line.startswith("sample rate:"):
                info.sample_rate = int(line.split(":")[1].strip().split()[0])
            elif line.startswith("channels:"):
                info.channels = int(line.split(":")[1].strip())
            elif line.startswith("stream total samples:"):
                parts = line.split(":")
                samples_part = parts[1].strip().split()[0]
                info.total_samples = int(samples_part)
                # Extract duration from parentheses
                if "(" in line and "seconds)" in line:
                    dur_str = line.split("(")[1].split("seconds")[0].strip()
                    try:
                        # Handle M:SS.mmm format
                        if ":" in dur_str:
                            m, s = dur_str.split(":")
                            info.duration_sec = int(m) * 60 + float(s)
                        else:
                            info.duration_sec = float(dur_str)
                    except ValueError:
                        pass

        return info if info.stream_name else None

    except Exception as e:
        print(f"  Warning: Could not get subsong info for #{subsong_index}: {e}")
        return None


def extract_subsong_to_mp3(
    awb_path: Path,
    subsong_index: int,
    output_path: Path,
    mp3_quality: int = MP3_QUALITY,
) -> bool:
    """Extract a single subsong from AWB and convert to MP3 via pipe."""
    try:
        # vgmstream decodes HCA to WAV on stdout
        vgm_proc = subprocess.Popen(
            [str(VGMSTREAM_CLI), "-s", str(subsong_index), "-p", str(awb_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        # ffmpeg reads WAV from stdin, writes MP3
        ffmpeg_proc = subprocess.Popen(
            [
                str(FFMPEG_PATH), "-y",
                "-i", "pipe:0",
                "-codec:a", "libmp3lame",
                "-q:a", str(mp3_quality),
                str(output_path),
            ],
            stdin=vgm_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Allow vgmstream to receive SIGPIPE if ffmpeg exits
        vgm_proc.stdout.close()
        ffmpeg_proc.communicate(timeout=60)
        vgm_proc.wait(timeout=60)

        return output_path.exists() and output_path.stat().st_size > 0

    except Exception as e:
        print(f"    ERROR extracting subsong #{subsong_index}: {e}")
        return False


# =============================================================================
# Partner Functions
# =============================================================================

def load_partner_names() -> Dict[int, str]:
    """Load partner ID -> Japanese name mapping from PartnerSort.xml."""
    names: Dict[int, str] = {}

    if not PARTNER_SORT_XML.exists():
        print(f"Warning: PartnerSort.xml not found at {PARTNER_SORT_XML}")
        return names

    tree = ET.parse(str(PARTNER_SORT_XML))
    root = tree.getroot()

    for string_id in root.findall(".//StringID"):
        id_elem = string_id.find("id")
        str_elem = string_id.find("str")
        if id_elem is not None and str_elem is not None:
            partner_id = int(id_elem.text)
            name = str_elem.text or f"Partner_{partner_id}"
            names[partner_id] = name

    return names


def get_partner_list() -> List[PartnerInfo]:
    """Build list of all partners with their file paths and names."""
    partner_names = load_partner_names()
    partners: List[PartnerInfo] = []

    if not PARTNER_SOUND_DIR.exists():
        print(f"Warning: PartnerSoundData directory not found at {PARTNER_SOUND_DIR}")
        return partners

    for awb_file in sorted(PARTNER_SOUND_DIR.glob("Voice_Partner_*.awb")):
        # Extract ID from filename: Voice_Partner_000011.awb -> 000011
        id_str = awb_file.stem.replace("Voice_Partner_", "")
        partner_id = int(id_str)

        acb_file = awb_file.with_suffix(".acb")
        if not acb_file.exists():
            print(f"Warning: ACB file missing for partner {id_str}")
            continue

        name_jp = partner_names.get(partner_id, f"Partner_{partner_id}")
        name_en = PARTNER_TRANSLATIONS.get(name_jp, f"Partner{partner_id}")

        # Sanitize folder name (replace filesystem-unsafe characters)
        safe_jp = name_jp
        for ch in r'\/:*?"<>|':
            safe_jp = safe_jp.replace(ch, "_")

        folder_name = f"{safe_jp}_{name_en}_SoundData"

        partners.append(PartnerInfo(
            id=partner_id,
            id_str=id_str,
            name_jp=name_jp,
            name_en=name_en,
            folder_name=folder_name,
            awb_path=awb_file,
            acb_path=acb_file,
        ))

    return partners


# =============================================================================
# Extraction Logic
# =============================================================================

def extract_awb(
    awb_path: Path,
    output_dir: Path,
    label: str = "",
) -> tuple[int, int]:
    """
    Extract all subsongs from an AWB to MP3 files named by stream name (VO_ID).
    Handles duplicate stream names by appending _v01, _v02, etc.
    Handles multi-cue streams (semicolon-separated) by using the first name.
    Skips very short placeholder tracks (< 0.6s) that are likely silent stubs.

    Returns (success_count, total_count).
    """
    total = get_subsong_count(awb_path)
    if total == 0:
        print(f"  No subsongs found in {awb_path.name}")
        return (0, 0)

    output_dir.mkdir(parents=True, exist_ok=True)

    # First pass: collect all stream names to detect duplicates
    subsong_infos: list[Optional[SubsongInfo]] = []
    for i in range(1, total + 1):
        subsong_infos.append(get_subsong_info(awb_path, i))

    # Count occurrences of each stream name (after sanitizing)
    name_counts: Dict[str, int] = {}
    for info in subsong_infos:
        if info and info.stream_name:
            clean_name = _sanitize_stream_name(info.stream_name)
            name_counts[clean_name] = name_counts.get(clean_name, 0) + 1

    # Track which variant number we're on for each duplicate name
    name_variant: Dict[str, int] = {}

    success = 0
    skipped = 0
    for i, info in enumerate(subsong_infos, 1):
        if not info or not info.stream_name:
            print(f"  [{i:3d}/{total}] Skipping subsong #{i} (no stream name)")
            continue

        # Skip very short placeholder/silent tracks
        if info.duration_sec < 0.6:
            print(f"  [{i:3d}/{total}] {info.stream_name} ({info.duration_sec:.1f}s) -> SKIPPED (placeholder/silent)")
            skipped += 1
            continue

        # Sanitize multi-cue names like "VO_000119; VO_000120; VO_000121; VO_000122"
        clean_name = _sanitize_stream_name(info.stream_name)

        # Handle duplicates by appending variant number
        if name_counts[clean_name] > 1:
            name_variant[clean_name] = name_variant.get(clean_name, 0) + 1
            variant = name_variant[clean_name]
            mp3_name = f"{clean_name}_v{variant:02d}.mp3"
        else:
            mp3_name = f"{clean_name}.mp3"

        mp3_path = output_dir / mp3_name

        # Progress indicator
        dur_str = f"{info.duration_sec:.1f}s" if info.duration_sec > 0 else "?"
        print(f"  [{i:3d}/{total}] {info.stream_name} ({dur_str}) -> {mp3_name}")

        if extract_subsong_to_mp3(awb_path, i, mp3_path):
            success += 1
        else:
            print(f"    FAILED: {mp3_name}")

    if skipped > 0:
        print(f"\n  Note: {skipped} placeholder/silent tracks skipped")

    return (success, total - skipped)


def _sanitize_stream_name(stream_name: str) -> str:
    """
    Clean up a stream name for use as a filename.
    Handles multi-cue names like "VO_000119; VO_000120; VO_000121; VO_000122"
    by taking only the first name.
    """
    # If semicolon-separated, take the first name
    if ";" in stream_name:
        stream_name = stream_name.split(";")[0].strip()

    # Remove any filesystem-unsafe characters
    for ch in r'\/:*?"<>|':
        stream_name = stream_name.replace(ch, "_")

    return stream_name


def process_system_voice(output_base: Path) -> None:
    """Extract system voice data."""
    print("=" * 60)
    print("SYSTEM VOICE")
    print("=" * 60)

    awb_path = SYSTEM_SOUND_DIR / "Voice_000001.awb"
    if not awb_path.exists():
        print(f"ERROR: System voice AWB not found at {awb_path}")
        return

    output_dir = output_base / "SystemVoice_SoundData"
    success, total = extract_awb(awb_path, output_dir, "System Voice")
    print(f"\n  Done: {success}/{total} tracks extracted to {output_dir.name}/")
    print()


def process_partners(
    output_base: Path,
    partner_id_filter: Optional[int] = None,
) -> None:
    """Extract partner voice data."""
    partners = get_partner_list()
    if not partners:
        print("No partner data found.")
        return

    if partner_id_filter is not None:
        partners = [p for p in partners if p.id == partner_id_filter]
        if not partners:
            print(f"Partner ID {partner_id_filter} not found.")
            return

    for idx, partner in enumerate(partners, 1):
        print("=" * 60)
        print(f"PARTNER [{idx}/{len(partners)}]: {partner.name_jp} ({partner.name_en})")
        print(f"  ID: {partner.id_str}  |  AWB: {partner.awb_path.name}")
        print("=" * 60)

        output_dir = output_base / partner.folder_name
        success, total = extract_awb(partner.awb_path, output_dir, partner.name_en)
        print(f"\n  Done: {success}/{total} tracks -> {partner.folder_name}/")
        print()


# =============================================================================
# Main
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract maimai DX voice lines from AWB archives to MP3"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR.name})",
    )
    parser.add_argument(
        "--system-only",
        action="store_true",
        help="Extract system voice only",
    )
    parser.add_argument(
        "--partners-only",
        action="store_true",
        help="Extract partner voices only",
    )
    parser.add_argument(
        "--partner-id",
        type=int,
        default=None,
        help="Extract a specific partner by ID (e.g. 11 for 乙姫)",
    )
    parser.add_argument(
        "--mp3-quality", "-q",
        type=int,
        default=MP3_QUALITY,
        choices=range(0, 10),
        help="MP3 VBR quality (0=best, 9=worst, default=2 ~190kbps)",
    )
    parser.add_argument(
        "--hca-key",
        type=str,
        default=None,
        help="HCA decryption key (64-bit integer). Default uses built-in key.",
    )

    args = parser.parse_args()
    output_base = Path(args.output_dir).resolve()

    # Ensure stdout can handle Japanese characters on Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print()
    print("maimai DX Voice Extractor")
    print("========================")
    print(f"Output: {output_base}")
    print()

    # Check tools
    if not check_dependencies():
        sys.exit(1)

    print("Dependencies OK: vgmstream-cli + ffmpeg")
    print()

    # Ensure HCA decryption key files are in place
    ensure_hcakey_files(args.hca_key)
    print()

    # Determine what to extract
    do_system = not args.partners_only
    do_partners = not args.system_only

    if args.partner_id is not None:
        do_system = False
        do_partners = True

    # Run extraction
    if do_system:
        process_system_voice(output_base)

    if do_partners:
        process_partners(output_base, partner_id_filter=args.partner_id)

    print("=" * 60)
    print("ALL DONE")
    print(f"Output directory: {output_base}")
    print("=" * 60)


if __name__ == "__main__":
    main()
