"""MakeMKV CLI output parsing and disc operations."""

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class DiscType(str, Enum):
    DVD = "dvd"
    BLURAY = "bluray"
    UHD4K = "uhd4k"


class TrackType(str, Enum):
    MAIN = "main"
    FEATURETTE = "featurette"
    DELETED_SCENE = "deleted_scene"
    TRAILER = "trailer"
    INTERVIEW = "interview"
    SHORT = "short"
    UNKNOWN = "unknown"


@dataclass
class AudioStream:
    """Audio stream information."""
    index: int
    language: str
    language_code: str
    codec: str
    channels: int
    bitrate: str


@dataclass
class SubtitleStream:
    """Subtitle stream information."""
    index: int
    language: str
    language_code: str
    codec: str
    forced: bool = False


@dataclass
class Track:
    """A single track/title from the disc."""
    title_id: int
    duration_str: str
    duration_seconds: int
    size_bytes: int
    size_human: str
    source_filename: str
    suggested_name: str
    chapter_count: int
    resolution: str
    video_codec: str
    audio_streams: list[AudioStream] = field(default_factory=list)
    subtitle_streams: list[SubtitleStream] = field(default_factory=list)
    classification: TrackType = TrackType.UNKNOWN


@dataclass
class DiscInfo:
    """Parsed disc information."""
    disc_type: str
    volume_name: str
    device_path: str
    tracks: list[Track] = field(default_factory=list)


def parse_duration_to_seconds(duration_str: str) -> int:
    """Convert duration string like '1:39:56' to seconds."""
    parts = duration_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def parse_makemkv_output(output: str) -> DiscInfo:
    """Parse makemkvcon info output into structured data."""
    disc_info = DiscInfo(
        disc_type="unknown",
        volume_name="",
        device_path="",
        tracks=[],
    )

    # Track data collectors
    track_data: dict[int, dict] = {}
    stream_data: dict[int, dict[int, dict]] = {}  # track_id -> stream_id -> data

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Parse DRV lines for device info
        if line.startswith("DRV:"):
            parts = line[4:].split(",")
            if len(parts) >= 7 and parts[1] == "2":  # Drive with disc
                disc_info.device_path = parts[6].strip('"')
                disc_info.volume_name = parts[5].strip('"')

        # Parse CINFO for disc type
        elif line.startswith("CINFO:"):
            parts = line[6:].split(",", 2)
            if len(parts) >= 3:
                field_id = int(parts[0])
                value = parts[2].strip('"')
                if field_id == 1 and "Blu-ray" in value:
                    disc_info.disc_type = "bluray"
                elif field_id == 1 and "DVD" in value:
                    disc_info.disc_type = "dvd"

        # Parse TINFO for track metadata
        elif line.startswith("TINFO:"):
            match = re.match(r'TINFO:(\d+),(\d+),\d+,"?([^"]*)"?', line)
            if match:
                track_id = int(match.group(1))
                field_id = int(match.group(2))
                value = match.group(3)

                if track_id not in track_data:
                    track_data[track_id] = {"title_id": track_id}

                if field_id == 8:
                    track_data[track_id]["chapter_count"] = int(value) if value else 0
                elif field_id == 9:
                    track_data[track_id]["duration_str"] = value
                    track_data[track_id]["duration_seconds"] = parse_duration_to_seconds(value)
                elif field_id == 10:
                    track_data[track_id]["size_human"] = value
                elif field_id == 11:
                    track_data[track_id]["size_bytes"] = int(value) if value else 0
                elif field_id == 16:
                    track_data[track_id]["source_filename"] = value
                elif field_id == 27:
                    track_data[track_id]["suggested_name"] = value

        # Parse SINFO for stream metadata
        elif line.startswith("SINFO:"):
            match = re.match(r'SINFO:(\d+),(\d+),(\d+),\d+,"?([^"]*)"?', line)
            if match:
                track_id = int(match.group(1))
                stream_id = int(match.group(2))
                field_id = int(match.group(3))
                value = match.group(4)

                if track_id not in stream_data:
                    stream_data[track_id] = {}
                if stream_id not in stream_data[track_id]:
                    stream_data[track_id][stream_id] = {}

                stream_data[track_id][stream_id][field_id] = value

    # Build Track objects
    for track_id, data in sorted(track_data.items()):
        # Get video resolution from stream 0
        resolution = "unknown"
        video_codec = "unknown"
        audio_streams = []
        subtitle_streams = []

        if track_id in stream_data:
            for stream_id, sdata in stream_data[track_id].items():
                stream_type = sdata.get(1, "")

                if stream_type == "Video" or sdata.get(1) == "6201":
                    resolution = sdata.get(19, "unknown")
                    video_codec = sdata.get(7, "unknown")

                elif stream_type == "Audio" or sdata.get(1) == "6202":
                    audio_streams.append(AudioStream(
                        index=stream_id,
                        language=sdata.get(4, "Unknown"),
                        language_code=sdata.get(3, "und"),
                        codec=sdata.get(7, "unknown"),
                        channels=int(sdata.get(14, 2)),
                        bitrate=sdata.get(13, ""),
                    ))

                elif stream_type == "Subtitles" or sdata.get(1) == "6203":
                    forced = "forced" in sdata.get(30, "").lower()
                    subtitle_streams.append(SubtitleStream(
                        index=stream_id,
                        language=sdata.get(4, "Unknown"),
                        language_code=sdata.get(3, "und"),
                        codec=sdata.get(7, "unknown"),
                        forced=forced,
                    ))

        track = Track(
            title_id=track_id,
            duration_str=data.get("duration_str", "0:00:00"),
            duration_seconds=data.get("duration_seconds", 0),
            size_bytes=data.get("size_bytes", 0),
            size_human=data.get("size_human", "0 B"),
            source_filename=data.get("source_filename", ""),
            suggested_name=data.get("suggested_name", f"title_{track_id}.mkv"),
            chapter_count=data.get("chapter_count", 0),
            resolution=resolution,
            video_codec=video_codec,
            audio_streams=audio_streams,
            subtitle_streams=subtitle_streams,
        )
        disc_info.tracks.append(track)

    return disc_info


def classify_tracks(tracks: list[Track]) -> list[Track]:
    """Apply heuristic classification to tracks based on duration and metadata."""
    for track in tracks:
        duration_min = track.duration_seconds / 60

        if duration_min >= 80:
            track.classification = TrackType.MAIN
        elif duration_min >= 20:
            track.classification = TrackType.FEATURETTE
        elif duration_min >= 5:
            track.classification = TrackType.DELETED_SCENE
        elif duration_min >= 1:
            track.classification = TrackType.TRAILER
        else:
            track.classification = TrackType.SHORT

    return tracks


async def scan_disc(drive_index: int = 0) -> DiscInfo | None:
    """Scan a disc and return parsed information."""
    try:
        result = subprocess.run(
            ["makemkvcon", "-r", "info", f"disc:{drive_index}"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return parse_makemkv_output(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


async def check_for_disc() -> tuple[bool, str | None]:
    """Check if any disc is present in any drive."""
    try:
        result = subprocess.run(
            ["makemkvcon", "-r", "info", "disc:9999"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in result.stdout.split("\n"):
            if line.startswith("DRV:"):
                parts = line[4:].split(",")
                if len(parts) >= 7 and parts[1] == "2":  # Drive with disc
                    return True, parts[6].strip('"')
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False, None
