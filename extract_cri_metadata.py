#!/usr/bin/env python3
"""
CRI HCA Metadata Extractor
Extracts comprehensive metadata from CRI HCA audio files in AWB and ACB archives.

Usage:
    python extract_cri_metadata.py <directory> [--verbose] [--key <hex_key>]

Example:
    python extract_cri_metadata.py Voice --verbose
"""

import os
import sys
import struct
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class HCAMetadata:
    """Metadata extracted from an HCA audio file header."""
    index: int
    file_id: int
    size: int
    # Format info
    version: int = 0
    data_offset: int = 0
    # Audio info
    sample_rate: int = 0
    channel_count: int = 0
    block_count: int = 0
    block_size: int = 0
    # Calculated
    duration_sec: float = 0.0
    total_samples: int = 0
    # Loop info
    has_loop: bool = False
    loop_start_block: int = 0
    loop_end_block: int = 0
    loop_count: int = 0
    loop_start_sample: int = 0
    loop_end_sample: int = 0
    # Encryption
    cipher_type: int = 0  # 0=none, 1=type1, 56=type56
    is_encrypted: bool = False
    # Volume
    volume: float = 1.0
    # Comment
    comment: str = ""
    # Validity
    is_valid: bool = False
    error: str = ""


@dataclass
class AWBMetadata:
    """Metadata extracted from an AWB (AFS2) archive."""
    path: str
    magic: str = ""
    file_count: int = 0
    alignment: int = 0
    embedded_key: int = 0
    size_length: int = 0
    tracks: List[HCAMetadata] = field(default_factory=list)
    is_valid: bool = False
    error: str = ""


@dataclass
class ACBMetadata:
    """Metadata extracted from an ACB (UTF) archive."""
    path: str
    name: str = ""
    version: int = 0
    cue_count: int = 0
    waveform_count: int = 0
    cue_names: List[str] = field(default_factory=list)
    waveforms: List[Dict[str, Any]] = field(default_factory=list)
    stream_awb_names: List[str] = field(default_factory=list)
    has_memory_awb: bool = False
    memory_awb_size: int = 0
    is_valid: bool = False
    error: str = ""


@dataclass
class ArchiveMetadata:
    """Combined metadata for an ACB/AWB pair."""
    base_name: str
    acb: Optional[ACBMetadata] = None
    awb: Optional[AWBMetadata] = None
    total_tracks: int = 0
    total_duration_sec: float = 0.0


# =============================================================================
# UTF (ACB) Parser
# =============================================================================

def find_zero(data: bytes, start: int) -> int:
    """Find the next null byte."""
    while start < len(data) and data[start] != 0:
        start += 1
    return start


def parse_utf(data: bytes, offset: int = 0) -> Optional[Dict[str, Any]]:
    """Parse a CRI UTF table (used in ACB files)."""
    if len(data) < offset + 8:
        return None
    
    # Check magic
    magic = data[offset:offset+4]
    if magic != b'@UTF':
        return None
    
    pos = offset + 4
    data_size = struct.unpack('>I', data[pos:pos+4])[0]
    pos += 4
    
    # Parse header
    base = pos
    unknown = struct.unpack('>H', data[pos:pos+2])[0]
    pos += 2
    value_offset = struct.unpack('>H', data[pos:pos+2])[0]
    pos += 2
    string_offset = struct.unpack('>I', data[pos:pos+4])[0]
    pos += 4
    data_offset = struct.unpack('>I', data[pos:pos+4])[0]
    pos += 4
    name_offset = struct.unpack('>I', data[pos:pos+4])[0]
    pos += 4
    element_count = struct.unpack('>H', data[pos:pos+2])[0]
    pos += 2
    value_size = struct.unpack('>H', data[pos:pos+2])[0]
    pos += 2
    page_count = struct.unpack('>I', data[pos:pos+4])[0]
    pos += 4
    
    # Get table name
    string_base = base + string_offset
    name_pos = string_base + name_offset
    name_end = find_zero(data, name_pos)
    table_name = data[name_pos:name_end].decode('utf-8', errors='replace')
    
    # Parse pages
    pages = []
    first_pos = pos
    value_pos = base + value_offset
    
    for page_idx in range(page_count):
        pos = first_pos
        page = {}
        
        for elem_idx in range(element_count):
            type_byte = data[pos]
            pos += 1
            
            # Get key name
            key_str_offset = struct.unpack('>I', data[pos:pos+4])[0]
            pos += 4
            key_pos = string_base + key_str_offset
            key_end = find_zero(data, key_pos)
            key = data[key_pos:key_end].decode('utf-8', errors='replace')
            
            method = (type_byte >> 5) & 0x7
            value_type = type_byte & 0x1F
            value = None
            
            if method > 0:
                read_pos = pos if method == 1 else value_pos
                
                if value_type == 0x10:  # int8
                    value = struct.unpack('b', data[read_pos:read_pos+1])[0]
                    read_pos += 1
                elif value_type == 0x11:  # uint8
                    value = data[read_pos]
                    read_pos += 1
                elif value_type == 0x12:  # int16
                    value = struct.unpack('>h', data[read_pos:read_pos+2])[0]
                    read_pos += 2
                elif value_type == 0x13:  # uint16
                    value = struct.unpack('>H', data[read_pos:read_pos+2])[0]
                    read_pos += 2
                elif value_type == 0x14:  # int32
                    value = struct.unpack('>i', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                elif value_type == 0x15:  # uint32
                    value = struct.unpack('>I', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                elif value_type == 0x16:  # int64
                    value = struct.unpack('>q', data[read_pos:read_pos+8])[0]
                    read_pos += 8
                elif value_type == 0x17:  # uint64
                    value = struct.unpack('>Q', data[read_pos:read_pos+8])[0]
                    read_pos += 8
                elif value_type == 0x18:  # float32
                    value = struct.unpack('>f', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                elif value_type == 0x19:  # float64
                    value = struct.unpack('>d', data[read_pos:read_pos+8])[0]
                    read_pos += 8
                elif value_type == 0x1A:  # string
                    str_offset = struct.unpack('>I', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                    str_pos = string_base + str_offset
                    str_end = find_zero(data, str_pos)
                    value = data[str_pos:str_end].decode('utf-8', errors='replace')
                elif value_type == 0x1B:  # data (embedded table or binary)
                    buf_offset = struct.unpack('>I', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                    buf_len = struct.unpack('>I', data[read_pos:read_pos+4])[0]
                    read_pos += 4
                    buf_start = base + data_offset + buf_offset
                    buf_data = data[buf_start:buf_start+buf_len]
                    # Try to parse as nested UTF
                    nested = parse_utf(buf_data, 0)
                    value = nested if nested else buf_data
                
                if method == 1:
                    pos = read_pos
                else:
                    value_pos = read_pos
            
            page[key] = value
        
        pages.append(page)
    
    return {
        'name': table_name,
        'pages': pages,
        'page_count': page_count,
        'element_count': element_count
    }


def parse_acb(file_path: str) -> ACBMetadata:
    """Parse an ACB file and extract metadata."""
    meta = ACBMetadata(path=file_path)
    
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        utf = parse_utf(data)
        if not utf or not utf['pages']:
            meta.error = "Failed to parse UTF table"
            return meta
        
        acb = utf['pages'][0]
        meta.name = acb.get('Name', '')
        meta.version = acb.get('Version', 0)
        
        # Parse CueNameTable
        cue_name_table = acb.get('CueNameTable')
        if isinstance(cue_name_table, dict) and 'pages' in cue_name_table:
            for page in cue_name_table['pages']:
                name = page.get('CueName', '')
                if name:
                    meta.cue_names.append(name)
        
        meta.cue_count = len(meta.cue_names)
        
        # Parse WaveformTable
        waveform_table = acb.get('WaveformTable')
        if isinstance(waveform_table, dict) and 'pages' in waveform_table:
            for page in waveform_table['pages']:
                wf = {
                    'id': page.get('Id', 0),
                    'streaming': page.get('Streaming', 0),
                    'encode_type': page.get('EncodeType', 0),
                    'memory_awb_id': page.get('MemoryAwbId', 0),
                    'stream_awb_id': page.get('StreamAwbId', 0),
                    'stream_awb_port': page.get('StreamAwbPortNo', 0),
                }
                meta.waveforms.append(wf)
        
        meta.waveform_count = len(meta.waveforms)
        
        # Check for embedded AWB
        awb_file = acb.get('AwbFile')
        if isinstance(awb_file, bytes) and len(awb_file) > 0:
            meta.has_memory_awb = True
            meta.memory_awb_size = len(awb_file)
        
        # Get external AWB names
        stream_awb_hash = acb.get('StreamAwbHash')
        if isinstance(stream_awb_hash, dict) and 'pages' in stream_awb_hash:
            for page in stream_awb_hash['pages']:
                name = page.get('Name', '')
                if name:
                    meta.stream_awb_names.append(name)
        
        meta.is_valid = True
        
    except Exception as e:
        meta.error = str(e)
    
    return meta


# =============================================================================
# AFS2 (AWB) Parser
# =============================================================================

def parse_awb(file_path: str) -> AWBMetadata:
    """Parse an AWB file and extract metadata."""
    meta = AWBMetadata(path=file_path)
    
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        if len(data) < 16:
            meta.error = "File too small"
            return meta
        
        # Check magic
        magic = data[0:4]
        if magic != b'AFS2':
            meta.error = f"Invalid magic: {magic}"
            return meta
        
        meta.magic = magic.decode('ascii')
        
        pos = 4
        unknown1 = data[pos]; pos += 1
        meta.size_length = data[pos]; pos += 1
        unknown2 = data[pos]; pos += 1
        unknown3 = data[pos]; pos += 1
        
        meta.file_count = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
        meta.alignment = struct.unpack('<H', data[pos:pos+2])[0]; pos += 2
        meta.embedded_key = struct.unpack('<H', data[pos:pos+2])[0]; pos += 2
        
        # Read file IDs
        file_ids = []
        for i in range(meta.file_count):
            file_id = struct.unpack('<H', data[pos:pos+2])[0]; pos += 2
            file_ids.append(file_id)
        
        # Read file offsets
        if meta.size_length == 2:
            start = struct.unpack('<H', data[pos:pos+2])[0]; pos += 2
        elif meta.size_length == 4:
            start = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
        else:
            meta.error = f"Unknown size length: {meta.size_length}"
            return meta
        
        # Align start
        if meta.alignment > 0:
            mod = start % meta.alignment
            if mod != 0:
                start += meta.alignment - mod
        
        # Read file sizes and parse HCA headers
        for i in range(meta.file_count):
            if meta.size_length == 2:
                end = struct.unpack('<H', data[pos:pos+2])[0]; pos += 2
            else:
                end = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
            
            file_data = data[start:end]
            hca_meta = parse_hca(file_data, i, file_ids[i] if i < len(file_ids) else i)
            hca_meta.size = end - start
            meta.tracks.append(hca_meta)
            
            start = end
            if meta.alignment > 0:
                mod = start % meta.alignment
                if mod != 0:
                    start += meta.alignment - mod
        
        meta.is_valid = True
        
    except Exception as e:
        meta.error = str(e)
    
    return meta


# =============================================================================
# HCA Parser
# =============================================================================

def parse_hca(data: bytes, index: int = 0, file_id: int = 0) -> HCAMetadata:
    """Parse an HCA file header and extract metadata."""
    meta = HCAMetadata(index=index, file_id=file_id, size=len(data))
    
    try:
        if len(data) < 8:
            meta.error = "Data too small for HCA header"
            return meta
        
        pos = 0
        
        # HCA magic (may be masked with 0x7F)
        magic = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
        if (magic & 0x7F7F7F7F) != 0x00414348:  # "HCA\0"
            meta.error = f"Invalid HCA magic: {hex(magic)}"
            return meta
        
        meta.version = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
        meta.data_offset = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
        
        # fmt chunk
        fmt_magic = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
        if (fmt_magic & 0x7F7F7F7F) != 0x00746D66:  # "fmt\0"
            meta.error = "Missing fmt chunk"
            return meta
        
        # Channel count and sample rate (packed)
        ch_sr = struct.unpack('>I', data[pos:pos+4])[0]; pos += 4
        meta.channel_count = (ch_sr >> 24) & 0xFF
        meta.sample_rate = ch_sr & 0xFFFFFF
        
        meta.block_count = struct.unpack('>I', data[pos:pos+4])[0]; pos += 4
        mute_header = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
        mute_footer = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
        
        # Validate
        if not (1 <= meta.channel_count <= 16):
            meta.error = f"Invalid channel count: {meta.channel_count}"
            return meta
        if not (1 <= meta.sample_rate <= 0x7FFFFF):
            meta.error = f"Invalid sample rate: {meta.sample_rate}"
            return meta
        
        # comp/dec chunk
        comp_magic = struct.unpack('<I', data[pos:pos+4])[0]; pos += 4
        meta.block_size = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
        pos += 2  # r01, r02
        
        if (comp_magic & 0x7F7F7F7F) == 0x706D6F63:  # "comp"
            pos += 8  # Skip comp-specific fields
        elif (comp_magic & 0x7F7F7F7F) == 0x00636564:  # "dec\0"
            pos += 4  # Skip dec-specific fields
        
        # Parse remaining chunks until data_offset
        while pos + 4 <= meta.data_offset and pos + 4 <= len(data):
            chunk_magic = struct.unpack('<I', data[pos:pos+4])[0]
            chunk_id = chunk_magic & 0x7F7F7F7F
            pos += 4
            
            if chunk_id == 0x00726276:  # "vbr\0"
                pos += 4
            elif chunk_id == 0x00687461:  # "ath\0"
                pos += 2
            elif chunk_id == 0x706F6F6C:  # "loop"
                meta.has_loop = True
                meta.loop_start_block = struct.unpack('>I', data[pos:pos+4])[0]; pos += 4
                meta.loop_end_block = struct.unpack('>I', data[pos:pos+4])[0]; pos += 4
                meta.loop_count = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
                pos += 2  # r1
            elif chunk_id == 0x68706963:  # "ciph"
                meta.cipher_type = struct.unpack('>H', data[pos:pos+2])[0]; pos += 2
                meta.is_encrypted = meta.cipher_type != 0
            elif chunk_id == 0x00617672:  # "rva\0"
                meta.volume = struct.unpack('>f', data[pos:pos+4])[0]; pos += 4
            elif chunk_id == 0x6D6D6F63:  # "comm"
                comm_len = data[pos]; pos += 1
                if comm_len > 0 and pos + comm_len <= len(data):
                    meta.comment = data[pos:pos+comm_len].decode('utf-8', errors='replace').rstrip('\x00')
                    pos += comm_len
            elif chunk_id == 0x00646170:  # "pad\0"
                break
            elif chunk_id == 0:  # End
                break
            else:
                # Unknown chunk, try to continue
                break
        
        # Calculate duration
        # HCA uses 1024 samples per block
        samples_per_block = 1024
        meta.total_samples = meta.block_count * samples_per_block
        if meta.sample_rate > 0:
            meta.duration_sec = meta.total_samples / meta.sample_rate
        
        # Calculate loop points in samples
        if meta.has_loop:
            meta.loop_start_sample = meta.loop_start_block * samples_per_block
            meta.loop_end_sample = meta.loop_end_block * samples_per_block
        
        meta.is_valid = True
        
    except Exception as e:
        meta.error = str(e)
    
    return meta


# =============================================================================
# Directory Scanner
# =============================================================================

def scan_directory(directory: str) -> List[ArchiveMetadata]:
    """Scan a directory for ACB/AWB files and group them."""
    archives = {}
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            if file_lower.endswith('.acb') or file_lower.endswith('.awb'):
                base_name = os.path.splitext(file)[0]
                full_path = os.path.join(root, file)
                
                key = os.path.join(root, base_name)
                if key not in archives:
                    archives[key] = ArchiveMetadata(base_name=base_name)
                
                if file_lower.endswith('.acb'):
                    archives[key].acb = parse_acb(full_path)
                else:
                    archives[key].awb = parse_awb(full_path)
    
    # Calculate totals
    result = []
    for key, archive in archives.items():
        if archive.awb and archive.awb.tracks:
            archive.total_tracks = len(archive.awb.tracks)
            archive.total_duration_sec = sum(t.duration_sec for t in archive.awb.tracks if t.is_valid)
        result.append(archive)
    
    return result


# =============================================================================
# Console Output
# =============================================================================

def format_duration(seconds: float) -> str:
    """Format duration as MM:SS.mmm"""
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:06.3f}"


def print_archive(archive: ArchiveMetadata, verbose: bool = False):
    """Print archive metadata to console."""
    print(f"\n{'='*70}")
    print(f"[Archive] {archive.base_name}")
    print(f"{'='*70}")
    
    # ACB info
    if archive.acb:
        acb = archive.acb
        if acb.is_valid:
            print(f"\n[ACB Metadata]")
            print(f"   Name: {acb.name}")
            if acb.cue_count > 0:
                print(f"   Cue Names: {acb.cue_count}")
            if acb.waveform_count > 0:
                print(f"   Waveforms: {acb.waveform_count}")
            if acb.has_memory_awb:
                print(f"   Embedded AWB: {acb.memory_awb_size:,} bytes")
            if acb.stream_awb_names:
                print(f"   External AWBs: {', '.join(acb.stream_awb_names)}")
        else:
            print(f"\n[ERROR] ACB Error: {acb.error}")
    
    # AWB info
    if archive.awb:
        awb = archive.awb
        if awb.is_valid:
            print(f"\n[AWB Metadata]")
            print(f"   Format: {awb.magic}")
            print(f"   Tracks: {awb.file_count}")
            print(f"   Alignment: {awb.alignment} bytes")
            if awb.embedded_key > 0:
                print(f"   Embedded Key: 0x{awb.embedded_key:04X}")
            print(f"   Total Duration: {format_duration(archive.total_duration_sec)}")
            
            # Track details
            if verbose and awb.tracks:
                print(f"\n   {'#':>4} {'Rate':>6} {'Ch':>2} {'Duration':>10} {'Blocks':>7} {'Size':>10} {'Loop':>5} {'Enc':>4}")
                print(f"   {'-'*4} {'-'*6} {'-'*2} {'-'*10} {'-'*7} {'-'*10} {'-'*5} {'-'*4}")
                
                for track in awb.tracks:
                    if track.is_valid:
                        loop_str = "Yes" if track.has_loop else "-"
                        enc_str = f"T{track.cipher_type}" if track.is_encrypted else "-"
                        print(f"   {track.index+1:>4} {track.sample_rate:>6} {track.channel_count:>2} "
                              f"{format_duration(track.duration_sec):>10} {track.block_count:>7} "
                              f"{track.size:>10,} {loop_str:>5} {enc_str:>4}")
                    else:
                        print(f"   {track.index+1:>4} {'ERROR':>6} - {track.error}")
            
            # Summary stats
            valid_tracks = [t for t in awb.tracks if t.is_valid]
            if valid_tracks:
                sample_rates = set(t.sample_rate for t in valid_tracks)
                channels = set(t.channel_count for t in valid_tracks)
                encrypted = sum(1 for t in valid_tracks if t.is_encrypted)
                looping = sum(1 for t in valid_tracks if t.has_loop)
                
                print(f"\n   [Summary]")
                print(f"      Sample Rates: {', '.join(f'{r} Hz' for r in sorted(sample_rates))}")
                print(f"      Channel Configs: {', '.join(f'{c}ch' for c in sorted(channels))}")
                if encrypted > 0:
                    print(f"      Encrypted: {encrypted}/{len(valid_tracks)} tracks")
                if looping > 0:
                    print(f"      Looping: {looping}/{len(valid_tracks)} tracks")
        else:
            print(f"\n[ERROR] AWB Error: {awb.error}")
    
    # Cue names (if ACB has them)
    if archive.acb and archive.acb.cue_names and verbose:
        print(f"\n   [Cue Names]")
        for i, name in enumerate(archive.acb.cue_names):
            print(f"      {i+1:>4}: {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract metadata from CRI HCA audio files in AWB/ACB archives"
    )
    parser.add_argument("directory", help="Directory to scan for ACB/AWB files")
    parser.add_argument("-v", "--verbose", action="store_true", 
                        help="Show detailed track information")
    parser.add_argument("-k", "--key", help="Decryption key (hex) - for future use")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a valid directory")
        sys.exit(1)
    
    print(f"Scanning: {os.path.abspath(args.directory)}")
    archives = scan_directory(args.directory)
    
    if not archives:
        print("No ACB/AWB files found.")
        sys.exit(0)
    
    # Sort by name
    archives.sort(key=lambda a: a.base_name)
    
    for archive in archives:
        print_archive(archive, verbose=args.verbose)
    
    # Overall summary
    print(f"\n{'='*70}")
    print(f"OVERALL SUMMARY")
    print(f"{'='*70}")
    print(f"   Archives found: {len(archives)}")
    total_tracks = sum(a.total_tracks for a in archives)
    total_duration = sum(a.total_duration_sec for a in archives)
    print(f"   Total tracks: {total_tracks}")
    print(f"   Total duration: {format_duration(total_duration)}")


if __name__ == "__main__":
    main()
