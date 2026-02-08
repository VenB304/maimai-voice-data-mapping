#!/usr/bin/env python3
"""
Voice Extractor and Renamer for maimai Partner Voice Data

This script:
1. Reads partner names from PartnerSort.xml
2. Parses AWB files to extract HCA audio tracks
3. Creates organized folders: "[PartnerName]_PartnerSoundData"
4. Renames tracks based on voice_action_mapping.csv

Usage:
    python rename_partner_voices.py <partner_sound_data_dir> [--output <output_dir>]
    
Example:
    python rename_partner_voices.py ./PartnerSoundData --output ./output
"""

import os
import sys
import csv
import argparse
import struct
import shutil
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass
class VoiceMapping:
    """Mapping from cue index to action name"""
    cue_index: int
    vo_id: str
    action_name: str
    description: str


@dataclass
class PartnerInfo:
    """Partner ID and name mapping"""
    partner_id: int
    name: str


def load_voice_mapping(csv_path: str) -> Dict[int, VoiceMapping]:
    """Load voice action mappings from CSV file"""
    mappings = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cue_index = int(row['cue_index'])
            mappings[cue_index] = VoiceMapping(
                cue_index=cue_index,
                vo_id=row['vo_id'],
                action_name=row['action_name'],
                description=row.get('description', '')
            )
    return mappings


def load_partner_names(xml_path: str) -> Dict[int, str]:
    """Load partner ID to name mapping from PartnerSort.xml"""
    partners = {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Find all StringID elements inside SortList
        for string_id in root.findall('.//SortList/StringID'):
            id_elem = string_id.find('id')
            str_elem = string_id.find('str')
            if id_elem is not None and str_elem is not None:
                try:
                    partner_id = int(id_elem.text)
                    name = str_elem.text or f"Partner_{partner_id:06d}"
                    partners[partner_id] = name
                except (ValueError, TypeError):
                    continue
    except ET.ParseError as e:
        print(f"Warning: Failed to parse XML: {e}")
    
    return partners



def extract_partner_id_from_filename(filename: str) -> Optional[int]:
    """Extract partner ID from AWB/ACB filename like 'Voice_Partner_000011.awb'"""
    match = re.search(r'Voice_Partner_(\d+)', filename)
    if match:
        return int(match.group(1))
    return None


def parse_awb_tracks(awb_path: str) -> List[Tuple[int, bytes]]:
    """
    Parse AWB file and extract track data.
    Returns list of (track_index, track_data) tuples.
    """
    tracks = []
    
    with open(awb_path, 'rb') as f:
        # Read AFS2 header
        magic = f.read(4)
        if magic != b'AFS2':
            print(f"Warning: {awb_path} is not a valid AWB file (magic: {magic})")
            return tracks
        
        # Parse header
        version = struct.unpack('<I', f.read(4))[0]
        file_count = struct.unpack('<I', f.read(4))[0]
        alignment = struct.unpack('<I', f.read(4))[0]
        
        # Read file IDs
        file_ids = []
        for _ in range(file_count):
            file_ids.append(struct.unpack('<H', f.read(2))[0])
        
        # Align to 4 bytes after IDs
        current_pos = f.tell()
        align_padding = (4 - (current_pos % 4)) % 4
        f.read(align_padding)
        
        # Read file offsets (file_count + 1 entries, last is end marker)
        offsets = []
        for _ in range(file_count + 1):
            offsets.append(struct.unpack('<I', f.read(4))[0])
        
        # Extract each track
        for i in range(file_count):
            start = offsets[i]
            end = offsets[i + 1]
            
            # Align start offset
            if alignment > 0:
                aligned_start = ((start + alignment - 1) // alignment) * alignment
                start = aligned_start
            
            f.seek(start)
            track_data = f.read(end - start)
            tracks.append((i, track_data))
    
    return tracks


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in filenames"""
    # Replace problematic characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name


def process_partner_awb(
    awb_path: str,
    output_dir: str,
    partner_name: str,
    voice_mapping: Dict[int, VoiceMapping],
    extract_hca: bool = True
) -> int:
    """
    Process a single partner AWB file and create renamed output files.
    Returns the number of tracks processed.
    """
    # Create output folder: "[PartnerName]_PartnerSoundData"
    safe_name = sanitize_filename(partner_name)
    partner_output_dir = os.path.join(output_dir, f"{safe_name}_PartnerSoundData")
    os.makedirs(partner_output_dir, exist_ok=True)
    
    # Extract tracks
    tracks = parse_awb_tracks(awb_path)
    
    for track_index, track_data in tracks:
        # Get mapping for this track
        if track_index in voice_mapping:
            mapping = voice_mapping[track_index]
            action_name = mapping.action_name
            vo_id = mapping.vo_id
        else:
            action_name = f"unknown_{track_index:03d}"
            vo_id = f"VO_{track_index:06d}"
        
        # Create filename: "{cue_index:02d}_{action_name}.hca"
        output_filename = f"{track_index:02d}_{action_name}.hca"
        output_path = os.path.join(partner_output_dir, output_filename)
        
        # Write track data
        if extract_hca:
            with open(output_path, 'wb') as out_f:
                out_f.write(track_data)
    
    return len(tracks)


def main():
    parser = argparse.ArgumentParser(
        description="Extract and rename maimai partner voice files"
    )
    parser.add_argument(
        "partner_sound_dir",
        help="Directory containing partner AWB files (e.g., PartnerSoundData)"
    )
    parser.add_argument(
        "--output", "-o",
        default="./output_voices",
        help="Output directory for organized voice files"
    )
    parser.add_argument(
        "--mapping", "-m",
        default="voice_action_mapping.csv",
        help="Path to voice action mapping CSV file"
    )
    parser.add_argument(
        "--partner-xml", "-p",
        default="partner_mapping/PartnerSort.xml",
        help="Path to PartnerSort.xml for partner names"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without extracting files"
    )
    
    args = parser.parse_args()
    
    # Load voice action mapping
    mapping_path = args.mapping
    if not os.path.isabs(mapping_path):
        # Try relative to script directory first
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(script_dir, mapping_path)):
            mapping_path = os.path.join(script_dir, mapping_path)
    
    if not os.path.exists(mapping_path):
        print(f"Error: Voice mapping CSV not found: {mapping_path}")
        print("Create voice_action_mapping.csv with columns: cue_index,vo_id,action_name,description")
        sys.exit(1)
    
    print(f"Loading voice action mapping from: {mapping_path}")
    voice_mapping = load_voice_mapping(mapping_path)
    print(f"  Loaded {len(voice_mapping)} voice mappings")
    
    # Load partner names
    partner_xml_path = args.partner_xml
    if not os.path.isabs(partner_xml_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(script_dir, partner_xml_path)):
            partner_xml_path = os.path.join(script_dir, partner_xml_path)
    
    partner_names = {}
    if os.path.exists(partner_xml_path):
        print(f"Loading partner names from: {partner_xml_path}")
        partner_names = load_partner_names(partner_xml_path)
        print(f"  Loaded {len(partner_names)} partner names")
    else:
        print(f"Warning: Partner XML not found: {partner_xml_path}")
        print("  Will use partner IDs as folder names")
    
    # Find all AWB files in the partner sound directory
    partner_dir = args.partner_sound_dir
    if not os.path.exists(partner_dir):
        print(f"Error: Partner sound directory not found: {partner_dir}")
        sys.exit(1)
    
    awb_files = []
    for root, dirs, files in os.walk(partner_dir):
        for f in files:
            if f.lower().endswith('.awb'):
                awb_files.append(os.path.join(root, f))
    
    if not awb_files:
        print(f"No AWB files found in: {partner_dir}")
        sys.exit(1)
    
    print(f"\nFound {len(awb_files)} AWB files to process")
    
    # Create output directory
    os.makedirs(args.output, exist_ok=True)
    
    # Process each AWB file
    total_tracks = 0
    for awb_path in sorted(awb_files):
        awb_filename = os.path.basename(awb_path)
        partner_id = extract_partner_id_from_filename(awb_filename)
        
        if partner_id is not None and partner_id in partner_names:
            partner_name = partner_names[partner_id]
        elif partner_id is not None:
            partner_name = f"Partner_{partner_id:06d}"
        else:
            # Use filename without extension
            partner_name = os.path.splitext(awb_filename)[0]
        
        print(f"\nProcessing: {awb_filename}")
        print(f"  Partner: {partner_name} (ID: {partner_id})")
        
        if args.dry_run:
            print(f"  [DRY RUN] Would extract to: {args.output}/{sanitize_filename(partner_name)}_PartnerSoundData/")
        else:
            num_tracks = process_partner_awb(
                awb_path=awb_path,
                output_dir=args.output,
                partner_name=partner_name,
                voice_mapping=voice_mapping,
                extract_hca=True
            )
            print(f"  Extracted {num_tracks} tracks")
            total_tracks += num_tracks
    
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Complete!")
    if not args.dry_run:
        print(f"Total tracks extracted: {total_tracks}")
        print(f"Output directory: {args.output}")


if __name__ == "__main__":
    main()
