"""Data models for Amphigory daemon tasks, responses, and configuration."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Union


class TaskType(Enum):
    """Type of task to process."""
    SCAN = "scan"
    RIP = "rip"


class TaskStatus(Enum):
    """Status of a completed task."""
    SUCCESS = "success"
    FAILED = "failed"


class ErrorCode(Enum):
    """Error codes for failed tasks."""
    DISC_EJECTED = "DISC_EJECTED"
    DISC_UNREADABLE = "DISC_UNREADABLE"
    MAKEMKV_FAILED = "MAKEMKV_FAILED"
    MAKEMKV_TIMEOUT = "MAKEMKV_TIMEOUT"
    OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class TrackInfo:
    """Information about a track to rip."""
    number: int
    expected_size_bytes: int
    expected_duration: str


@dataclass
class OutputInfo:
    """Output path information for a rip task."""
    directory: str
    filename: str


@dataclass
class ScanTask:
    """A task to scan a disc for track information."""
    id: str
    type: TaskType
    created_at: datetime


@dataclass
class RipTask:
    """A task to rip a specific track from a disc."""
    id: str
    type: TaskType
    created_at: datetime
    track: TrackInfo
    output: OutputInfo


@dataclass
class AudioStream:
    """Audio stream information from a scanned track."""
    language: str
    codec: str
    channels: Union[int, str]


@dataclass
class SubtitleStream:
    """Subtitle stream information from a scanned track."""
    language: str
    format: str


@dataclass
class ScannedTrack:
    """Information about a track discovered during disc scan.

    Note: chapters and chapter_count are aliases - both contain the same value.
    chapters is kept for backwards compatibility with existing JSON serialization.
    """
    number: int
    duration: str
    size_bytes: int
    chapters: int
    resolution: str
    audio_streams: list[AudioStream]
    subtitle_streams: list[SubtitleStream]
    chapter_count: int = 0
    segment_map: str = ""
    is_main_feature_playlist: bool = False


@dataclass
class ScanResult:
    """Result of a disc scan operation."""
    disc_name: str
    disc_type: str
    tracks: list[ScannedTrack]


@dataclass
class RipResult:
    """Result of a successful rip operation."""
    output_path: str
    size_bytes: int


@dataclass
class TaskError:
    """Error information for a failed task."""
    code: ErrorCode
    message: str
    detail: Optional[str] = None


@dataclass
class TaskResponse:
    """Response for a completed task (success or failure)."""
    task_id: str
    status: TaskStatus
    started_at: datetime
    completed_at: datetime
    duration_seconds: int
    result: Optional[Union[ScanResult, RipResult]] = None
    error: Optional[TaskError] = None


@dataclass
class DaemonConfig:
    """Local daemon configuration (from daemon.yaml)."""
    webapp_url: str
    webapp_basedir: str
    daemon_id: Optional[str] = None
    makemkvcon_path: Optional[str] = None
    updated_at: Optional[datetime] = None


@dataclass
class WebappConfig:
    """Configuration fetched from webapp's /config.json."""
    tasks_directory: str
    websocket_port: int
    wiki_url: str
    heartbeat_interval: int
    log_level: str
    makemkv_path: Optional[str] = None


def _parse_datetime(s: str) -> datetime:
    """Parse ISO format datetime string."""
    # Handle 'Z' suffix for UTC
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)


def _format_datetime(dt: datetime) -> str:
    """Format datetime as ISO string with Z suffix."""
    return dt.isoformat().replace('+00:00', 'Z')


def task_from_dict(data: dict) -> Union[ScanTask, RipTask]:
    """Parse a task from a dictionary (loaded from JSON)."""
    task_type = TaskType(data["type"])
    created_at = _parse_datetime(data["created_at"])

    if task_type == TaskType.SCAN:
        return ScanTask(
            id=data["id"],
            type=task_type,
            created_at=created_at,
        )
    elif task_type == TaskType.RIP:
        track_data = data["track"]
        output_data = data["output"]
        return RipTask(
            id=data["id"],
            type=task_type,
            created_at=created_at,
            track=TrackInfo(
                number=track_data["number"],
                expected_size_bytes=track_data["expected_size_bytes"],
                expected_duration=track_data["expected_duration"],
            ),
            output=OutputInfo(
                directory=output_data["directory"],
                filename=output_data["filename"],
            ),
        )
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def response_to_dict(response: TaskResponse) -> dict:
    """Convert a TaskResponse to a dictionary for JSON serialization."""
    result = {
        "task_id": response.task_id,
        "status": response.status.value,
        "started_at": _format_datetime(response.started_at),
        "completed_at": _format_datetime(response.completed_at),
        "duration_seconds": response.duration_seconds,
    }

    if response.result is not None:
        if isinstance(response.result, RipResult):
            result["result"] = {
                "output_path": response.result.output_path,
                "size_bytes": response.result.size_bytes,
            }
        elif isinstance(response.result, ScanResult):
            result["result"] = {
                "disc_name": response.result.disc_name,
                "disc_type": response.result.disc_type,
                "tracks": [
                    {
                        "number": t.number,
                        "duration": t.duration,
                        "size_bytes": t.size_bytes,
                        "chapters": t.chapters,
                        "resolution": t.resolution,
                        "audio_streams": [
                            {"language": a.language, "codec": a.codec, "channels": a.channels}
                            for a in t.audio_streams
                        ],
                        "subtitle_streams": [
                            {"language": s.language, "format": s.format}
                            for s in t.subtitle_streams
                        ],
                        "chapter_count": t.chapter_count,
                        "segment_map": t.segment_map,
                        "is_main_feature_playlist": t.is_main_feature_playlist,
                    }
                    for t in response.result.tracks
                ],
            }

    if response.error is not None:
        result["error"] = {
            "code": response.error.code.value,
            "message": response.error.message,
        }
        if response.error.detail:
            result["error"]["detail"] = response.error.detail

    return result


def webapp_config_from_dict(data: dict) -> WebappConfig:
    """Parse WebappConfig from a dictionary (loaded from JSON)."""
    return WebappConfig(
        tasks_directory=data["tasks_directory"],
        websocket_port=data["websocket_port"],
        wiki_url=data["wiki_url"],
        heartbeat_interval=data["heartbeat_interval"],
        log_level=data["log_level"],
        makemkv_path=data.get("makemkv_path"),
    )
