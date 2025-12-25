"""MakeMKV execution and output parsing for Amphigory daemon."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import (
    ScanResult,
    ScannedTrack,
    AudioStream,
    SubtitleStream,
)


@dataclass
class Progress:
    """Progress update from MakeMKV."""
    percent: int
    eta_seconds: Optional[int] = None
    current_size_bytes: Optional[int] = None
    speed: Optional[str] = None


def parse_progress_line(line: str) -> Optional[Progress]:
    """
    Parse a MakeMKV output line for progress information.

    MakeMKV progress lines:
    - PRGV:current,total,max - Overall progress (use total/max for %)
    - PRGC:current,total - Current operation progress

    Args:
        line: A line of MakeMKV output

    Returns:
        Progress object if line contains progress, None otherwise
    """
    line = line.strip()

    # PRGV: overall progress - PRGV:current,total,max
    if line.startswith("PRGV:"):
        parts = line[5:].split(",")
        if len(parts) >= 3:
            try:
                total = int(parts[1])
                max_val = int(parts[2])
                if max_val > 0:
                    percent = int((total / max_val) * 100)
                    return Progress(percent=percent)
            except ValueError:
                pass

    # PRGC: current operation progress - PRGC:current,total
    if line.startswith("PRGC:"):
        parts = line[5:].split(",")
        if len(parts) >= 2:
            try:
                current = int(parts[0])
                total = int(parts[1])
                if total > 0:
                    percent = int((current / total) * 100)
                    return Progress(percent=percent)
            except ValueError:
                pass

    return None


def parse_scan_output(output: str) -> ScanResult:
    """
    Parse makemkvcon info output into ScanResult.

    Args:
        output: Complete output from makemkvcon -r info disc:0

    Returns:
        ScanResult with disc info and tracks
    """
    lines = output.strip().split("\n")

    disc_name = ""
    disc_type_raw = ""
    tracks: dict[int, dict] = {}  # track_num -> track data

    for line in lines:
        line = line.strip()

        # CINFO:2 = disc name
        if line.startswith("CINFO:2,"):
            match = re.search(r'CINFO:2,\d+,"([^"]*)"', line)
            if match:
                disc_name = match.group(1)

        # CINFO:30 = disc type
        if line.startswith("CINFO:30,"):
            match = re.search(r'CINFO:30,\d+,"([^"]*)"', line)
            if match:
                disc_type_raw = match.group(1)

        # TINFO:track_num,field_id,code,value
        if line.startswith("TINFO:"):
            match = re.match(r'TINFO:(\d+),(\d+),\d+,"?([^"]*)"?', line)
            if match:
                track_num = int(match.group(1))
                field_id = int(match.group(2))
                value = match.group(3).strip('"')

                if track_num not in tracks:
                    tracks[track_num] = {
                        "number": track_num,
                        "duration": "",
                        "size_bytes": 0,
                        "chapters": 0,
                        "resolution": "",
                        "audio_streams": [],
                        "subtitle_streams": [],
                        "chapter_count": 0,
                        "segment_map": "",
                        "is_main_feature_playlist": False,
                    }

                if field_id == 2:  # Title name - check for FPL_MainFeature
                    if "(FPL_MainFeature)" in value:
                        tracks[track_num]["is_main_feature_playlist"] = True
                elif field_id == 9:  # Duration
                    tracks[track_num]["duration"] = value
                elif field_id == 11:  # Size in bytes
                    try:
                        tracks[track_num]["size_bytes"] = int(value)
                    except (ValueError, TypeError):
                        tracks[track_num]["size_bytes"] = 0
                elif field_id == 8:  # Chapter count
                    try:
                        chapter_count = int(value)
                        tracks[track_num]["chapters"] = chapter_count
                        tracks[track_num]["chapter_count"] = chapter_count
                    except (ValueError, TypeError):
                        tracks[track_num]["chapters"] = 0
                        tracks[track_num]["chapter_count"] = 0
                elif field_id == 26:  # Segment map
                    tracks[track_num]["segment_map"] = value

        # SINFO:track_num,stream_num,field_id,code,value
        if line.startswith("SINFO:"):
            match = re.match(r'SINFO:(\d+),(\d+),(\d+),(\d+),"?([^"]*)"?', line)
            if match:
                track_num = int(match.group(1))
                stream_num = int(match.group(2))
                field_id = int(match.group(3))
                code = int(match.group(4))
                value = match.group(5).strip('"')

                if track_num not in tracks:
                    continue

                track = tracks[track_num]

                # Field 1 can be stream type code OR codec name (string)
                if field_id == 1:
                    if code == 6201:  # Video
                        pass  # We handle video fields separately
                    elif code == 6202:  # Audio
                        # Ensure we have enough audio stream entries
                        while len(track["audio_streams"]) <= stream_num:
                            track["audio_streams"].append({
                                "language": "",
                                "codec": "",
                                "channels": 0,
                            })
                    elif code == 6203:  # Subtitle
                        while len(track["subtitle_streams"]) <= stream_num:
                            track["subtitle_streams"].append({
                                "language": "",
                                "format": "",
                            })
                    else:
                        # Field 1 with code 0 may contain codec as string
                        while len(track["audio_streams"]) <= stream_num:
                            track["audio_streams"].append({
                                "language": "",
                                "codec": "",
                                "channels": 0,
                            })
                        if stream_num < len(track["audio_streams"]):
                            track["audio_streams"][stream_num]["codec"] = value

                # Field 19 = resolution (for video)
                elif field_id == 19:
                    track["resolution"] = value

                # Field 3 = language code or language name
                elif field_id == 3:
                    # Check if this is for an audio stream
                    # Only create audio stream if we haven't created subtitle streams yet
                    # or if the stream number is clearly within audio range
                    if stream_num < len(track["audio_streams"]):
                        track["audio_streams"][stream_num]["language"] = value
                    elif len(track["subtitle_streams"]) > 0:
                        # Likely a subtitle stream
                        idx = stream_num - len(track["audio_streams"])
                        if idx < len(track["subtitle_streams"]):
                            track["subtitle_streams"][idx]["language"] = value
                    else:
                        # Ambiguous - create as audio stream
                        while len(track["audio_streams"]) <= stream_num:
                            track["audio_streams"].append({
                                "language": "",
                                "codec": "",
                                "channels": 0,
                            })
                        track["audio_streams"][stream_num]["language"] = value

                # Field 4 = channels (audio) or language name - can be string like "7.1" or int
                elif field_id == 4:
                    # Only apply to existing audio streams (don't create new ones)
                    if stream_num < len(track["audio_streams"]):
                        # Keep as string if it contains decimal, otherwise try to parse as int
                        if "." in value:
                            track["audio_streams"][stream_num]["channels"] = value
                        else:
                            try:
                                track["audio_streams"][stream_num]["channels"] = int(value)
                            except ValueError:
                                # Could be a language name, ignore for now
                                pass

                # Field 13 = codec name (audio)
                elif field_id == 13:
                    if stream_num < len(track["audio_streams"]):
                        track["audio_streams"][stream_num]["codec"] = value

                # Field 14 = channels (audio)
                elif field_id == 14:
                    if stream_num < len(track["audio_streams"]):
                        try:
                            track["audio_streams"][stream_num]["channels"] = int(value)
                        except ValueError:
                            pass

                # Field 5 = subtitle format
                elif field_id == 5:
                    # Subtitles use different stream numbering
                    for sub in track["subtitle_streams"]:
                        if not sub["format"]:
                            sub["format"] = value
                            break

    # Determine disc type
    disc_type = "dvd"
    if "BD-ROM" in disc_type_raw or "Blu-ray" in disc_type_raw:
        disc_type = "bluray"
        # Check for UHD by looking at resolution
        for track_data in tracks.values():
            if "3840" in track_data.get("resolution", ""):
                disc_type = "uhd4k"
                break
    elif "DVD" in disc_type_raw:
        disc_type = "dvd"

    # Convert track dicts to ScannedTrack objects
    scanned_tracks = []
    for track_num in sorted(tracks.keys()):
        t = tracks[track_num]
        scanned_tracks.append(ScannedTrack(
            number=t["number"],
            duration=t["duration"],
            size_bytes=t["size_bytes"],
            chapters=t["chapters"],
            resolution=t["resolution"],
            audio_streams=[
                AudioStream(
                    language=a["language"],
                    codec=a["codec"],
                    channels=a["channels"],
                )
                for a in t["audio_streams"]
                if a["language"] or a["codec"]  # Filter empty
            ],
            subtitle_streams=[
                SubtitleStream(
                    language=s["language"],
                    format=s["format"],
                )
                for s in t["subtitle_streams"]
                if s["language"] or s["format"]  # Filter empty
            ],
            chapter_count=t["chapter_count"],
            segment_map=t["segment_map"],
            is_main_feature_playlist=t["is_main_feature_playlist"],
        ))

    return ScanResult(
        disc_name=disc_name,
        disc_type=disc_type,
        tracks=scanned_tracks,
    )


def build_scan_command(makemkv_path: Path) -> list[str]:
    """
    Build makemkvcon command for scanning disc info.

    Args:
        makemkv_path: Path to makemkvcon binary

    Returns:
        Command list for subprocess
    """
    return [str(makemkv_path), "-r", "info", "disc:0"]


def build_rip_command(
    makemkv_path: Path,
    track_number: int,
    output_dir: Path,
) -> list[str]:
    """
    Build makemkvcon command for ripping a track.

    Args:
        makemkv_path: Path to makemkvcon binary
        track_number: Track number to rip
        output_dir: Directory to write output

    Returns:
        Command list for subprocess
    """
    return [
        str(makemkv_path),
        "-r",
        "mkv",
        "disc:0",
        str(track_number),
        str(output_dir),
    ]
