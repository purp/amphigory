"""Tests for data models - TDD: tests written first."""

import json
from datetime import datetime
from dataclasses import asdict

import pytest


class TestTaskType:
    def test_scan_type_value(self):
        from amphigory_daemon.models import TaskType
        assert TaskType.SCAN.value == "scan"

    def test_rip_type_value(self):
        from amphigory_daemon.models import TaskType
        assert TaskType.RIP.value == "rip"


class TestTaskStatus:
    def test_success_value(self):
        from amphigory_daemon.models import TaskStatus
        assert TaskStatus.SUCCESS.value == "success"

    def test_failed_value(self):
        from amphigory_daemon.models import TaskStatus
        assert TaskStatus.FAILED.value == "failed"


class TestErrorCode:
    def test_all_error_codes_exist(self):
        from amphigory_daemon.models import ErrorCode
        expected = [
            "DISC_EJECTED",
            "DISC_UNREADABLE",
            "MAKEMKV_FAILED",
            "MAKEMKV_TIMEOUT",
            "OUTPUT_WRITE_FAILED",
            "TASK_CANCELLED",
            "UNKNOWN",
        ]
        for code in expected:
            assert hasattr(ErrorCode, code)
            assert ErrorCode[code].value == code


class TestScanTask:
    def test_create_scan_task(self):
        from amphigory_daemon.models import ScanTask, TaskType
        task = ScanTask(
            id="20251221-143045-001",
            type=TaskType.SCAN,
            created_at=datetime(2025, 12, 21, 14, 30, 45),
        )
        assert task.id == "20251221-143045-001"
        assert task.type == TaskType.SCAN
        assert task.created_at == datetime(2025, 12, 21, 14, 30, 45)

    def test_scan_task_from_dict(self):
        from amphigory_daemon.models import ScanTask, TaskType, task_from_dict
        data = {
            "id": "20251221-143045-001",
            "type": "scan",
            "created_at": "2025-12-21T14:30:45Z",
        }
        task = task_from_dict(data)
        assert isinstance(task, ScanTask)
        assert task.id == "20251221-143045-001"
        assert task.type == TaskType.SCAN


class TestTaskFromDictWithInputOutput:
    """Test parsing task with input/output dependency fields."""

    def test_task_from_dict_with_input_output(self):
        """Test parsing task with input/output dependency fields."""
        from amphigory_daemon.models import task_from_dict

        data = {
            "id": "20251227T143052.123456-rip",
            "type": "rip",
            "created_at": "2025-12-27T14:30:52.123456",
            "input": None,
            "output": "/media/ripped/Movie (2024)/Movie (2024).mkv",
            "track": {"number": 1, "expected_size_bytes": 1000, "expected_duration": "1:30:00"},
            "output_info": {"directory": "/media/ripped/Movie (2024)/", "filename": "Movie (2024).mkv"},
        }
        task = task_from_dict(data)
        assert task.input_path is None
        assert task.output_path == "/media/ripped/Movie (2024)/Movie (2024).mkv"

    def test_scan_task_has_input_output_fields(self):
        """Test that scan tasks have input_path/output_path fields."""
        from amphigory_daemon.models import ScanTask, TaskType, task_from_dict

        data = {
            "id": "20251227T143052.123456-scan",
            "type": "scan",
            "created_at": "2025-12-27T14:30:52.123456",
        }
        task = task_from_dict(data)
        assert isinstance(task, ScanTask)
        assert task.input_path is None
        assert task.output_path is None


class TestRipTask:
    def test_create_rip_task(self):
        from amphigory_daemon.models import RipTask, TaskType, TrackInfo, OutputInfo
        task = RipTask(
            id="20251221-143052-001",
            type=TaskType.RIP,
            created_at=datetime(2025, 12, 21, 14, 30, 52),
            track=TrackInfo(
                number=0,
                expected_size_bytes=11397666816,
                expected_duration="1:39:56",
            ),
            output=OutputInfo(
                directory="/media/ripped/The Polar Express (2004) {imdb-tt0338348}",
                filename="The Polar Express (2004) {imdb-tt0338348}.mkv",
            ),
        )
        assert task.id == "20251221-143052-001"
        assert task.track.number == 0
        assert task.output.filename == "The Polar Express (2004) {imdb-tt0338348}.mkv"

    def test_rip_task_from_dict(self):
        from amphigory_daemon.models import RipTask, TaskType, task_from_dict
        data = {
            "id": "20251221-143052-001",
            "type": "rip",
            "created_at": "2025-12-21T14:30:52Z",
            "track": {
                "number": 0,
                "expected_size_bytes": 11397666816,
                "expected_duration": "1:39:56",
            },
            "output": {
                "directory": "/media/ripped/Movie (2004) {imdb-tt0000000}",
                "filename": "Movie (2004) {imdb-tt0000000}.mkv",
            },
        }
        task = task_from_dict(data)
        assert isinstance(task, RipTask)
        assert task.track.number == 0


class TestTaskResponse:
    def test_rip_result_with_source_destination(self):
        """RipResult uses source at response level, destination in result."""
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource,
            FileDestination, response_to_dict
        )
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:59:45",
                size_bytes=12345678901,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )
        d = response_to_dict(response)
        assert d["task_id"] == "20251221-143052-001"
        assert d["status"] == "success"
        assert d["duration_seconds"] == 868

        # Source should be at top level (disc info)
        assert d["source"]["disc_fingerprint"] == "abc123def456"
        assert d["source"]["track_number"] == 4
        assert d["source"]["makemkv_track_name"] == "B1_t04.mkv"
        assert d["source"]["duration"] == "1:59:45"
        assert d["source"]["size_bytes"] == 12345678901

        # Destination should be in result (file info)
        assert d["result"]["destination"]["directory"] == "/media/ripped/Movie"
        assert d["result"]["destination"]["filename"] == "Movie.mkv"
        assert d["result"]["destination"]["size_bytes"] == 11397666816

    def test_rip_result_source_with_optional_fields(self):
        """DiscSource handles optional fields gracefully."""
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource,
            FileDestination, response_to_dict
        )
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint=None,  # May not be available
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration=None,
                size_bytes=None,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )
        d = response_to_dict(response)
        assert d["source"]["disc_fingerprint"] is None
        assert d["source"]["duration"] is None
        assert d["source"]["size_bytes"] is None

    def test_failure_response_to_dict(self):
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, TaskError, ErrorCode, response_to_dict
        )
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.FAILED,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 35, 12),
            duration_seconds=257,
            error=TaskError(
                code=ErrorCode.DISC_EJECTED,
                message="Disc was ejected during rip",
                detail="makemkvcon exited with code 1",
            ),
        )
        d = response_to_dict(response)
        assert d["status"] == "failed"
        assert d["error"]["code"] == "DISC_EJECTED"
        assert d["error"]["message"] == "Disc was ejected during rip"


class TestScanResult:
    def test_scan_result_structure(self):
        from amphigory_daemon.models import (
            ScanResult, ScannedTrack, AudioStream, SubtitleStream
        )
        result = ScanResult(
            disc_name="THE_POLAR_EXPRESS",
            disc_type="bluray",
            tracks=[
                ScannedTrack(
                    number=0,
                    duration="1:39:56",
                    size_bytes=11397666816,
                    chapters=24,
                    resolution="1920x1080",
                    audio_streams=[
                        AudioStream(language="eng", codec="TrueHD", channels=6)
                    ],
                    subtitle_streams=[
                        SubtitleStream(language="eng", format="PGS")
                    ],
                )
            ],
        )
        assert result.disc_name == "THE_POLAR_EXPRESS"
        assert len(result.tracks) == 1
        assert result.tracks[0].audio_streams[0].codec == "TrueHD"

    def test_scan_result_with_classification(self):
        """ScanResult includes classification data."""
        from amphigory_daemon.models import (
            ScanResult, ScannedTrack, AudioStream, SubtitleStream
        )
        result = ScanResult(
            disc_name="TEST_DISC",
            disc_type="bluray",
            tracks=[
                ScannedTrack(
                    number=0,
                    duration="1:45:00",
                    size_bytes=5000000000,
                    chapters=24,
                    chapter_count=24,
                    resolution="1920x1080",
                    audio_streams=[
                        AudioStream(language="eng", codec="DTS-HD", channels=8)
                    ],
                    subtitle_streams=[
                        SubtitleStream(language="eng", format="PGS")
                    ],
                    classification="main_feature",
                    confidence="high",
                    score=0.85,
                )
            ],
            duplicates_removed=2,
        )
        assert result.duplicates_removed == 2
        assert result.tracks[0].classification == "main_feature"
        assert result.tracks[0].confidence == "high"
        assert result.tracks[0].score == 0.85

    def test_scan_result_serialization_includes_classification(self):
        """ScanResult serialization includes classification fields."""
        from amphigory_daemon.models import (
            ScanResult, ScannedTrack, AudioStream, SubtitleStream,
            TaskResponse, TaskStatus, response_to_dict
        )
        result = ScanResult(
            disc_name="TEST_DISC",
            disc_type="bluray",
            tracks=[
                ScannedTrack(
                    number=0,
                    duration="1:45:00",
                    size_bytes=5000000000,
                    chapters=24,
                    chapter_count=24,
                    resolution="1920x1080",
                    audio_streams=[],
                    subtitle_streams=[],
                    classification="main_feature",
                    confidence="high",
                    score=0.85,
                )
            ],
            duplicates_removed=1,
        )
        response = TaskResponse(
            task_id="test-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 25, 10, 0, 0),
            completed_at=datetime(2025, 12, 25, 10, 1, 0),
            duration_seconds=60,
            result=result,
        )
        d = response_to_dict(response)
        assert d["result"]["duplicates_removed"] == 1
        assert d["result"]["tracks"][0]["classification"] == "main_feature"
        assert d["result"]["tracks"][0]["confidence"] == "high"
        assert d["result"]["tracks"][0]["score"] == 0.85


class TestDaemonConfig:
    def test_daemon_config(self):
        from amphigory_daemon.models import DaemonConfig
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/beehive-docker/amphigory",
        )
        assert config.webapp_url == "http://localhost:8080"
        assert config.webapp_basedir == "/opt/beehive-docker/amphigory"


class TestWebappConfig:
    def test_webapp_config(self):
        from amphigory_daemon.models import WebappConfig
        config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=9847,
            wiki_url="http://gollum.meyer.home/Amphigory/Home",
            heartbeat_interval=10,
            log_level="info",
            makemkv_path=None,
        )
        assert config.tasks_directory == "/tasks"
        assert config.websocket_port == 9847
        assert config.makemkv_path is None

    def test_webapp_config_from_dict(self):
        from amphigory_daemon.models import WebappConfig, webapp_config_from_dict
        data = {
            "tasks_directory": "/tasks",
            "websocket_port": 9847,
            "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
            "heartbeat_interval": 10,
            "log_level": "info",
            "makemkv_path": None,
        }
        config = webapp_config_from_dict(data)
        assert isinstance(config, WebappConfig)
        assert config.websocket_port == 9847
