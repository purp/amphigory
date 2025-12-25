# Amphigory Implementation Plan

> **Status:** ✅ SUPERSEDED - Architecture evolved to daemon+webapp split
>
> This original plan was created before deciding to split into a native macOS daemon
> and Docker-hosted webapp. The foundational tasks (1-3, 8-11) were completed.
> Tasks 4-7 (preset management, job queue, ripping/transcoding services) were
> reimplemented differently in the daemon architecture. Tasks 12-20 were either
> completed differently or are tracked in post-launch-followups.md.
>
> See `2025-12-22-amphigory-daemon-implementation.md` for the actual daemon work.

---

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a webapp that automates optical media ripping, transcoding, and Plex library organization.

**Architecture:** Python/FastAPI backend with SQLite database, running in Docker. Polls for disc insertion, orchestrates MakeMKV for ripping and HandBrakeCLI for transcoding, with WebSocket-based real-time progress updates to a functional web UI.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Jinja2 templates, HTMX for reactivity, WebSockets, Docker

---

## Phase 1: Project Foundation

### Task 1: Project Structure and Dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `src/amphigory/__init__.py`
- Create: `src/amphigory/main.py`
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `.dockerignore`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "amphigory"
version = "0.1.0"
description = "Automated optical media ripping and transcoding for Plex"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.6",
    "aiosqlite>=0.19.0",
    "websockets>=12.0",
    "httpx>=0.25.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

**Step 2: Create requirements.txt (for Docker)**

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
jinja2>=3.1.0
python-multipart>=0.0.6
aiosqlite>=0.19.0
websockets>=12.0
httpx>=0.25.0
pyyaml>=6.0
```

**Step 3: Create src/amphigory/__init__.py**

```python
"""Amphigory - Automated optical media ripping and transcoding for Plex."""

__version__ = "0.1.0"
```

**Step 4: Create src/amphigory/main.py**

```python
"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Amphigory",
    description="Automated optical media ripping and transcoding for Plex",
    version="0.1.0",
)

# Will be configured after templates directory exists
# templates = Jinja2Templates(directory="src/amphigory/templates")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
```

**Step 5: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    libdvdcss2 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install MakeMKV
# Note: This is a placeholder - actual MakeMKV installation is more complex
# and may require building from source or using a pre-built package
RUN echo "MakeMKV installation placeholder - see docs for actual setup"

# Install HandBrakeCLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    handbrake-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for data
RUN mkdir -p /data /media/ripped /media/plex/inbox /media/plex/data /wiki

ENV PYTHONPATH=/app/src
ENV AMPHIGORY_CONFIG=/config
ENV AMPHIGORY_DATA=/data

EXPOSE 8080

CMD ["uvicorn", "amphigory.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Step 6: Create .dockerignore**

```
.git
.gitignore
__pycache__
*.pyc
*.pyo
.pytest_cache
.ruff_cache
.coverage
htmlcov
*.egg-info
dist
build
.env
.venv
venv
docs/plans
tests
```

**Step 7: Verify project loads**

Run: `cd /Users/purp/work/amphigory && python -c "from src.amphigory.main import app; print('OK')"`
Expected: `OK`

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: initial project structure and dependencies"
```

---

### Task 2: Database Schema and Models

**Files:**
- Create: `src/amphigory/database.py`
- Create: `src/amphigory/models.py`
- Create: `tests/test_database.py`

**Step 1: Write failing test for database initialization**

```python
# tests/test_database.py
"""Tests for database initialization and models."""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.mark.asyncio
async def test_database_initialization(temp_db_path):
    """Test that database initializes with correct schema."""
    from amphigory.database import Database

    db = Database(temp_db_path)
    await db.initialize()

    # Verify tables exist
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

    assert "discs" in tables
    assert "tracks" in tables
    assert "presets" in tables
    assert "jobs" in tables

    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_database.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'amphigory.database'"

**Step 3: Create src/amphigory/database.py**

```python
"""Database connection and initialization."""

import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

SCHEMA = """
-- Processed discs
CREATE TABLE IF NOT EXISTS discs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    disc_type TEXT,
    disc_release_year INTEGER,
    edition_notes TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Individual tracks ripped from a disc
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    disc_id INTEGER REFERENCES discs(id),
    track_number INTEGER,
    track_type TEXT,
    original_name TEXT,
    final_name TEXT,
    duration_seconds INTEGER,
    size_bytes INTEGER,
    ripped_path TEXT,
    transcoded_path TEXT,
    preset_id INTEGER REFERENCES presets(id),
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Handbrake presets with versioning
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    disc_type TEXT,
    preset_json TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

-- Job queue for ripping and transcoding
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    track_id INTEGER REFERENCES tracks(id),
    job_type TEXT,
    status TEXT DEFAULT 'queued',
    progress INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_track_id ON jobs(track_id);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database with schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    async def close(self) -> None:
        """Close any open connections."""
        pass  # Connections are managed per-request
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_database.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add database schema and initialization"
```

---

### Task 3: MakeMKV Output Parser

**Files:**
- Create: `src/amphigory/makemkv.py`
- Create: `tests/test_makemkv.py`
- Create: `tests/fixtures/makemkv_output.txt`

**Step 1: Create test fixture with real MakeMKV output**

Save a sample of the MakeMKV output we captured earlier to `tests/fixtures/makemkv_output.txt`.

**Step 2: Write failing test for parser**

```python
# tests/test_makemkv.py
"""Tests for MakeMKV output parsing."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_output():
    """Load sample MakeMKV output."""
    fixture_path = Path(__file__).parent / "fixtures" / "makemkv_output.txt"
    return fixture_path.read_text()


def test_parse_disc_info(sample_output):
    """Test parsing disc-level information."""
    from amphigory.makemkv import parse_makemkv_output

    result = parse_makemkv_output(sample_output)

    assert result.disc_type == "bluray"
    assert result.volume_name == "LOGICAL_VOLUME_ID"
    assert result.device_path == "/dev/rdisk4"


def test_parse_tracks(sample_output):
    """Test parsing track information."""
    from amphigory.makemkv import parse_makemkv_output

    result = parse_makemkv_output(sample_output)

    assert len(result.tracks) > 0

    # Check main feature (title 0)
    main = result.tracks[0]
    assert main.title_id == 0
    assert main.duration_str == "1:39:56"
    assert main.size_bytes == 11397666816
    assert main.resolution == "1920x1080"
    assert main.suggested_name == "title_t00.mkv"


def test_classify_tracks(sample_output):
    """Test heuristic track classification."""
    from amphigory.makemkv import parse_makemkv_output, classify_tracks

    result = parse_makemkv_output(sample_output)
    classified = classify_tracks(result.tracks)

    # Should identify one main feature
    main_features = [t for t in classified if t.classification == "main"]
    assert len(main_features) == 1
    assert main_features[0].title_id == 0
```

**Step 3: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_makemkv.py -v`
Expected: FAIL with import error

**Step 4: Create src/amphigory/makemkv.py**

```python
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
```

**Step 5: Create test fixture**

Create `tests/fixtures/makemkv_output.txt` with sample output from the Polar Express disc scan (truncated for essential data).

**Step 6: Run tests to verify they pass**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_makemkv.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: add MakeMKV output parser with track classification"
```

---

### Task 4: Preset Management

**Files:**
- Create: `src/amphigory/presets.py`
- Create: `tests/test_presets.py`
- Modify: `config/presets/presets.yaml`

**Step 1: Write failing test**

```python
# tests/test_presets.py
"""Tests for Handbrake preset management."""

import pytest
import tempfile
from pathlib import Path
import json
import yaml


@pytest.fixture
def temp_preset_dir():
    """Create temporary preset directory with sample presets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        preset_dir = Path(tmpdir)

        # Create a sample preset JSON
        preset_json = {
            "PresetList": [{
                "PresetName": "Test Preset",
                "VideoEncoder": "x265",
            }]
        }
        (preset_dir / "test-preset-v1.json").write_text(json.dumps(preset_json))

        # Create presets.yaml
        config = {
            "active": {
                "dvd": "test-preset-v1",
                "bluray": "test-preset-v1",
                "uhd4k": "test-preset-v1",
            }
        }
        (preset_dir / "presets.yaml").write_text(yaml.dump(config))

        yield preset_dir


@pytest.mark.asyncio
async def test_load_presets(temp_preset_dir):
    """Test loading presets from directory."""
    from amphigory.presets import PresetManager

    manager = PresetManager(temp_preset_dir)
    await manager.load()

    assert "test-preset-v1" in manager.presets
    assert manager.get_active_preset("dvd") == "test-preset-v1"


@pytest.mark.asyncio
async def test_get_preset_for_disc_type(temp_preset_dir):
    """Test getting appropriate preset for disc type."""
    from amphigory.presets import PresetManager

    manager = PresetManager(temp_preset_dir)
    await manager.load()

    preset_path = manager.get_preset_path("dvd")
    assert preset_path.exists()
    assert preset_path.name == "test-preset-v1.json"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_presets.py -v`
Expected: FAIL

**Step 3: Create src/amphigory/presets.py**

```python
"""Handbrake preset management."""

import json
import yaml
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Preset:
    """A Handbrake preset."""
    name: str
    version: str
    disc_type: str | None
    file_path: Path
    preset_data: dict


class PresetManager:
    """Manages Handbrake presets."""

    def __init__(self, preset_dir: Path | str):
        self.preset_dir = Path(preset_dir)
        self.presets: dict[str, Preset] = {}
        self.active_presets: dict[str, str] = {}  # disc_type -> preset_name

    async def load(self) -> None:
        """Load all presets from directory."""
        # Load config
        config_path = self.preset_dir / "presets.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                self.active_presets = config.get("active", {})

        # Load preset JSON files
        for preset_file in self.preset_dir.glob("*.json"):
            try:
                with open(preset_file) as f:
                    data = json.load(f)

                name = preset_file.stem  # e.g., "dvd-h265-720p-v1"

                # Parse version from name if present
                version = "1"
                if "-v" in name:
                    parts = name.rsplit("-v", 1)
                    if parts[1].isdigit():
                        version = parts[1]

                self.presets[name] = Preset(
                    name=name,
                    version=version,
                    disc_type=self._infer_disc_type(name),
                    file_path=preset_file,
                    preset_data=data,
                )
            except (json.JSONDecodeError, IOError):
                continue

    def _infer_disc_type(self, name: str) -> str | None:
        """Infer disc type from preset name."""
        name_lower = name.lower()
        if "dvd" in name_lower:
            return "dvd"
        elif "uhd" in name_lower or "4k" in name_lower or "2160" in name_lower:
            return "uhd4k"
        elif "bluray" in name_lower or "blu-ray" in name_lower or "1080" in name_lower:
            return "bluray"
        return None

    def get_active_preset(self, disc_type: str) -> str | None:
        """Get the active preset name for a disc type."""
        return self.active_presets.get(disc_type)

    def get_preset_path(self, disc_type: str) -> Path | None:
        """Get the file path for the active preset for a disc type."""
        preset_name = self.get_active_preset(disc_type)
        if preset_name and preset_name in self.presets:
            return self.presets[preset_name].file_path
        return None

    def get_preset(self, name: str) -> Preset | None:
        """Get a preset by name."""
        return self.presets.get(name)

    def list_presets(self, disc_type: str | None = None) -> list[Preset]:
        """List all presets, optionally filtered by disc type."""
        presets = list(self.presets.values())
        if disc_type:
            presets = [p for p in presets if p.disc_type == disc_type]
        return presets
```

**Step 4: Create initial presets.yaml**

```yaml
# config/presets/presets.yaml
# Maps disc types to active preset names

active:
  dvd: dvd-h265-720p-v1
  bluray: bluray-h265-1080p-v1
  uhd4k: uhd4k-h265-2160p-v1
```

**Step 5: Run tests**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_presets.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Handbrake preset management"
```

---

## Phase 2: Core Pipeline

### Task 5: Job Queue System

**Files:**
- Create: `src/amphigory/jobs.py`
- Create: `tests/test_jobs.py`

**Step 1: Write failing test**

```python
# tests/test_jobs.py
"""Tests for job queue system."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
async def db():
    """Create a temporary database."""
    from amphigory.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest.mark.asyncio
async def test_create_rip_job(db):
    """Test creating a rip job."""
    from amphigory.jobs import JobQueue, JobType

    queue = JobQueue(db)

    job_id = await queue.create_job(
        track_id=1,
        job_type=JobType.RIP,
        priority=10,
    )

    assert job_id is not None

    job = await queue.get_job(job_id)
    assert job["job_type"] == "rip"
    assert job["status"] == "queued"
    assert job["priority"] == 10


@pytest.mark.asyncio
async def test_job_ordering(db):
    """Test that jobs are returned in priority order."""
    from amphigory.jobs import JobQueue, JobType

    queue = JobQueue(db)

    # Create jobs with different priorities
    await queue.create_job(track_id=1, job_type=JobType.RIP, priority=5)
    await queue.create_job(track_id=2, job_type=JobType.RIP, priority=10)
    await queue.create_job(track_id=3, job_type=JobType.RIP, priority=1)

    # Get next job should return highest priority
    next_job = await queue.get_next_job(JobType.RIP)
    assert next_job["track_id"] == 2  # priority 10


@pytest.mark.asyncio
async def test_update_job_progress(db):
    """Test updating job progress."""
    from amphigory.jobs import JobQueue, JobType, JobStatus

    queue = JobQueue(db)
    job_id = await queue.create_job(track_id=1, job_type=JobType.RIP)

    await queue.update_job(job_id, status=JobStatus.RUNNING, progress=50)

    job = await queue.get_job(job_id)
    assert job["status"] == "running"
    assert job["progress"] == 50
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_jobs.py -v`
Expected: FAIL

**Step 3: Create src/amphigory/jobs.py**

```python
"""Job queue management for ripping and transcoding."""

from enum import Enum
from typing import Any
from datetime import datetime

from amphigory.database import Database


class JobType(str, Enum):
    RIP = "rip"
    TRANSCODE = "transcode"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobQueue:
    """Manages the job queue for ripping and transcoding."""

    def __init__(self, db: Database):
        self.db = db

    async def create_job(
        self,
        track_id: int,
        job_type: JobType,
        priority: int = 0,
    ) -> int:
        """Create a new job in the queue."""
        async with self.db.connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO jobs (track_id, job_type, status, priority)
                VALUES (?, ?, ?, ?)
                """,
                (track_id, job_type.value, JobStatus.QUEUED.value, priority),
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_job(self, job_id: int) -> dict[str, Any] | None:
        """Get a job by ID."""
        async with self.db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def get_next_job(self, job_type: JobType | None = None) -> dict[str, Any] | None:
        """Get the next queued job, optionally filtered by type."""
        async with self.db.connection() as conn:
            if job_type:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ? AND job_type = ?
                    ORDER BY priority DESC, id ASC
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value, job_type.value),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY priority DESC, id ASC
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value,),
                )
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def update_job(
        self,
        job_id: int,
        status: JobStatus | None = None,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update job status and progress."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
            if status == JobStatus.RUNNING:
                updates.append("started_at = ?")
                params.append(datetime.now().isoformat())
            elif status in (JobStatus.COMPLETE, JobStatus.FAILED):
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())

        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)

        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if updates:
            params.append(job_id)
            async with self.db.connection() as conn:
                await conn.execute(
                    f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                await conn.commit()

    async def get_queue(self, job_type: JobType | None = None) -> list[dict[str, Any]]:
        """Get all queued jobs."""
        async with self.db.connection() as conn:
            if job_type:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ? AND job_type = ?
                    ORDER BY priority DESC, id ASC
                    """,
                    (JobStatus.QUEUED.value, job_type.value),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY priority DESC, id ASC
                    """,
                    (JobStatus.QUEUED.value,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def reorder_job(self, job_id: int, new_priority: int) -> None:
        """Change a job's priority."""
        async with self.db.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET priority = ? WHERE id = ? AND status = ?",
                (new_priority, job_id, JobStatus.QUEUED.value),
            )
            await conn.commit()

    async def cancel_job(self, job_id: int) -> None:
        """Cancel a queued job."""
        await self.update_job(job_id, status=JobStatus.CANCELLED)
```

**Step 4: Run tests**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_jobs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add job queue system for ripping and transcoding"
```

---

### Task 6: Ripping Service

**Files:**
- Create: `src/amphigory/services/ripper.py`
- Create: `tests/test_ripper.py`

**Step 1: Write failing test**

```python
# tests/test_ripper.py
"""Tests for ripping service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


@pytest.mark.asyncio
async def test_rip_command_construction():
    """Test that rip commands are constructed correctly."""
    from amphigory.services.ripper import RipperService

    ripper = RipperService(output_dir=Path("/media/ripped"))

    cmd = ripper.build_rip_command(
        drive_index=0,
        title_index=5,
        output_dir=Path("/media/ripped/Test Movie (2024)"),
    )

    assert cmd[0] == "makemkvcon"
    assert "mkv" in cmd
    assert "disc:0" in cmd
    assert "5" in cmd  # title index
    assert "/media/ripped/Test Movie (2024)" in cmd


@pytest.mark.asyncio
async def test_parse_rip_progress():
    """Test parsing progress from MakeMKV output."""
    from amphigory.services.ripper import RipperService

    ripper = RipperService(output_dir=Path("/media/ripped"))

    # Sample progress line
    line = 'PRGV:100,200,500'
    progress = ripper.parse_progress(line)
    assert progress == 40  # 200/500 * 100

    line2 = 'PRGC:1,5,"Copying title 1"'
    progress2 = ripper.parse_progress(line2)
    # PRGC is current/total so 1/5 = 20%
    assert progress2 == 20
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_ripper.py -v`
Expected: FAIL

**Step 3: Create src/amphigory/services/ripper.py**

```python
"""Service for ripping discs with MakeMKV."""

import asyncio
import subprocess
from pathlib import Path
from typing import AsyncGenerator, Callable
from dataclasses import dataclass


@dataclass
class RipProgress:
    """Progress update from ripping."""
    percent: int
    message: str
    title_index: int | None = None
    bytes_done: int = 0
    bytes_total: int = 0


class RipperService:
    """Manages disc ripping with MakeMKV."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def build_rip_command(
        self,
        drive_index: int,
        title_index: int,
        output_dir: Path,
    ) -> list[str]:
        """Build the makemkvcon command for ripping."""
        return [
            "makemkvcon",
            "mkv",
            f"disc:{drive_index}",
            str(title_index),
            str(output_dir),
        ]

    def parse_progress(self, line: str) -> int | None:
        """Parse progress from MakeMKV output line.

        MakeMKV progress formats:
        - PRGV:current,total,max - Overall progress (current/max * 100)
        - PRGC:current,total,"message" - Current/total items
        - PRGT:current,total,"message" - Title progress
        """
        if line.startswith("PRGV:"):
            parts = line[5:].split(",")
            if len(parts) >= 3:
                current = int(parts[1])
                total = int(parts[2])
                if total > 0:
                    return int(current / total * 100)

        elif line.startswith("PRGC:") or line.startswith("PRGT:"):
            parts = line[5:].split(",")
            if len(parts) >= 2:
                current = int(parts[0])
                total = int(parts[1])
                if total > 0:
                    return int(current / total * 100)

        return None

    async def rip_title(
        self,
        drive_index: int,
        title_index: int,
        output_dir: Path,
        progress_callback: Callable[[RipProgress], None] | None = None,
    ) -> Path | None:
        """Rip a single title from disc.

        Returns the path to the ripped file on success, None on failure.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_rip_command(drive_index, title_index, output_dir)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_progress = 0
        output_file: Path | None = None

        async for line in process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()

            # Parse progress
            progress = self.parse_progress(line_str)
            if progress is not None and progress != last_progress:
                last_progress = progress
                if progress_callback:
                    progress_callback(RipProgress(
                        percent=progress,
                        message=f"Ripping: {progress}%",
                        title_index=title_index,
                    ))

            # Look for output file path
            if line_str.startswith("MSG:") and "saved to" in line_str.lower():
                # Try to extract output path
                pass

        await process.wait()

        if process.returncode == 0:
            # Find the output file
            mkv_files = list(output_dir.glob("*.mkv"))
            if mkv_files:
                # Return the most recently created file
                output_file = max(mkv_files, key=lambda p: p.stat().st_mtime)

        return output_file

    async def rip_titles(
        self,
        drive_index: int,
        titles: list[int],
        output_dir: Path,
        progress_callback: Callable[[int, RipProgress], None] | None = None,
    ) -> dict[int, Path | None]:
        """Rip multiple titles sequentially.

        Returns a mapping of title_index -> output_path.
        """
        results = {}

        for title_index in titles:
            def wrapped_callback(progress: RipProgress):
                if progress_callback:
                    progress_callback(title_index, progress)

            result = await self.rip_title(
                drive_index,
                title_index,
                output_dir,
                wrapped_callback,
            )
            results[title_index] = result

        return results
```

**Step 4: Create __init__.py for services**

```python
# src/amphigory/services/__init__.py
"""Amphigory services."""
```

**Step 5: Run tests**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_ripper.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add ripping service with progress parsing"
```

---

### Task 7: Transcoding Service

**Files:**
- Create: `src/amphigory/services/transcoder.py`
- Create: `tests/test_transcoder.py`

**Step 1: Write failing test**

```python
# tests/test_transcoder.py
"""Tests for transcoding service."""

import pytest
from pathlib import Path


def test_transcode_command_construction():
    """Test that transcode commands are constructed correctly."""
    from amphigory.services.transcoder import TranscoderService

    transcoder = TranscoderService()

    cmd = transcoder.build_transcode_command(
        input_path=Path("/media/ripped/movie.mkv"),
        output_path=Path("/media/plex/inbox/Movie (2024)/Movie (2024).mp4"),
        preset_path=Path("/config/presets/bluray-h265-1080p-v1.json"),
        preset_name="Blu Ray - H.265 1080p",
    )

    assert cmd[0] == "HandBrakeCLI"
    assert "-i" in cmd
    assert "/media/ripped/movie.mkv" in cmd
    assert "-o" in cmd
    assert "Movie (2024).mp4" in cmd[-1] or "/media/plex/inbox" in " ".join(cmd)


def test_parse_transcode_progress():
    """Test parsing progress from HandBrake output."""
    from amphigory.services.transcoder import TranscoderService

    transcoder = TranscoderService()

    # Sample HandBrake progress line
    line = "Encoding: task 1 of 1, 45.23 % (87.45 fps, avg 92.31 fps, ETA 00h12m34s)"
    progress = transcoder.parse_progress(line)
    assert progress == 45

    line2 = "Encoding: task 1 of 1, 100.00 %"
    progress2 = transcoder.parse_progress(line2)
    assert progress2 == 100
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_transcoder.py -v`
Expected: FAIL

**Step 3: Create src/amphigory/services/transcoder.py**

```python
"""Service for transcoding with HandBrake."""

import asyncio
import re
from pathlib import Path
from typing import Callable
from dataclasses import dataclass


@dataclass
class TranscodeProgress:
    """Progress update from transcoding."""
    percent: int
    fps: float = 0.0
    avg_fps: float = 0.0
    eta: str = ""
    message: str = ""


class TranscoderService:
    """Manages video transcoding with HandBrake."""

    def build_transcode_command(
        self,
        input_path: Path,
        output_path: Path,
        preset_path: Path,
        preset_name: str,
    ) -> list[str]:
        """Build the HandBrakeCLI command for transcoding."""
        return [
            "HandBrakeCLI",
            "-i", str(input_path),
            "-o", str(output_path),
            "--preset-import-file", str(preset_path),
            "-Z", preset_name,
        ]

    def parse_progress(self, line: str) -> int | None:
        """Parse progress from HandBrake output line.

        HandBrake progress format:
        Encoding: task 1 of 1, 45.23 % (87.45 fps, avg 92.31 fps, ETA 00h12m34s)
        """
        match = re.search(r"(\d+\.?\d*)\s*%", line)
        if match:
            return int(float(match.group(1)))
        return None

    def parse_full_progress(self, line: str) -> TranscodeProgress | None:
        """Parse full progress info from HandBrake output."""
        if "Encoding:" not in line:
            return None

        percent = 0
        fps = 0.0
        avg_fps = 0.0
        eta = ""

        # Parse percentage
        pct_match = re.search(r"(\d+\.?\d*)\s*%", line)
        if pct_match:
            percent = int(float(pct_match.group(1)))

        # Parse FPS
        fps_match = re.search(r"\((\d+\.?\d*)\s*fps", line)
        if fps_match:
            fps = float(fps_match.group(1))

        # Parse average FPS
        avg_match = re.search(r"avg\s*(\d+\.?\d*)\s*fps", line)
        if avg_match:
            avg_fps = float(avg_match.group(1))

        # Parse ETA
        eta_match = re.search(r"ETA\s*(\d+h\d+m\d+s)", line)
        if eta_match:
            eta = eta_match.group(1)

        return TranscodeProgress(
            percent=percent,
            fps=fps,
            avg_fps=avg_fps,
            eta=eta,
            message=line.strip(),
        )

    async def transcode(
        self,
        input_path: Path,
        output_path: Path,
        preset_path: Path,
        preset_name: str,
        progress_callback: Callable[[TranscodeProgress], None] | None = None,
    ) -> bool:
        """Transcode a video file.

        Returns True on success, False on failure.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = self.build_transcode_command(
            input_path, output_path, preset_path, preset_name
        )

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_progress = 0

        async for line in process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()

            if progress_callback:
                progress = self.parse_full_progress(line_str)
                if progress and progress.percent != last_progress:
                    last_progress = progress.percent
                    progress_callback(progress)

        await process.wait()

        return process.returncode == 0 and output_path.exists()

    async def get_video_info(self, input_path: Path) -> dict | None:
        """Get video information using HandBrake scan."""
        cmd = [
            "HandBrakeCLI",
            "-i", str(input_path),
            "--scan",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        output, _ = await process.communicate()
        output_str = output.decode("utf-8", errors="replace")

        # Parse resolution
        info = {}
        res_match = re.search(r"(\d+)x(\d+)", output_str)
        if res_match:
            info["width"] = int(res_match.group(1))
            info["height"] = int(res_match.group(2))

        return info if info else None
```

**Step 4: Run tests**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_transcoder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add transcoding service with progress parsing"
```

---

## Phase 3: Web Interface

### Task 8: Basic Web Server and Templates

**Files:**
- Modify: `src/amphigory/main.py`
- Create: `src/amphigory/templates/base.html`
- Create: `src/amphigory/templates/index.html`
- Create: `src/amphigory/static/style.css`

**Step 1: Update main.py with template support**

```python
# src/amphigory/main.py
"""FastAPI application entry point."""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from amphigory.database import Database
from amphigory.config import get_config

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Initialize database
    config = get_config()
    app.state.db = Database(config.database_path)
    await app.state.db.initialize()

    yield

    # Cleanup
    await app.state.db.close()


app = FastAPI(
    title="Amphigory",
    description="Automated optical media ripping and transcoding for Plex",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Amphigory",
            "disc_status": "No disc detected",
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
```

**Step 2: Create base template**

```html
<!-- src/amphigory/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Amphigory{% endblock %}</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body>
    <nav class="navbar">
        <div class="nav-brand">
            <a href="/">Amphigory</a>
        </div>
        <div class="nav-links">
            <a href="/" class="{% if active_page == 'home' %}active{% endif %}">Dashboard</a>
            <a href="/queue" class="{% if active_page == 'queue' %}active{% endif %}">Queue</a>
            <a href="/library" class="{% if active_page == 'library' %}active{% endif %}">Library</a>
            <a href="/cleanup" class="{% if active_page == 'cleanup' %}active{% endif %}">Cleanup</a>
        </div>
    </nav>

    <main class="container">
        {% block content %}{% endblock %}
    </main>

    <footer class="footer">
        <p>Amphigory - Apple MakeMKV Plex Handbrake I Guess Other Random letters Yielded the rest</p>
    </footer>

    {% block scripts %}{% endblock %}
</body>
</html>
```

**Step 3: Create index template**

```html
<!-- src/amphigory/templates/index.html -->
{% extends "base.html" %}

{% block title %}Dashboard - Amphigory{% endblock %}

{% block content %}
<div class="dashboard">
    <section class="disc-status card">
        <h2>Disc Status</h2>
        <div id="disc-info" hx-get="/api/disc/status" hx-trigger="every 5s" hx-swap="innerHTML">
            <p class="status-message">{{ disc_status }}</p>
        </div>
    </section>

    <section class="current-jobs card">
        <h2>Active Jobs</h2>
        <div id="active-jobs" hx-get="/api/jobs/active" hx-trigger="every 2s" hx-swap="innerHTML">
            <p class="no-jobs">No active jobs</p>
        </div>
    </section>

    <section class="quick-actions card">
        <h2>Quick Actions</h2>
        <button hx-post="/api/disc/scan" hx-swap="none" class="btn btn-primary">
            Scan Disc
        </button>
    </section>
</div>
{% endblock %}
```

**Step 4: Create CSS styles**

```css
/* src/amphigory/static/style.css */
:root {
    --primary: #2563eb;
    --primary-dark: #1d4ed8;
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text: #1e293b;
    --text-muted: #64748b;
    --border: #e2e8f0;
    --success: #22c55e;
    --warning: #f59e0b;
    --error: #ef4444;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

.navbar {
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.nav-brand a {
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--primary);
    text-decoration: none;
}

.nav-links a {
    margin-left: 2rem;
    color: var(--text-muted);
    text-decoration: none;
}

.nav-links a:hover,
.nav-links a.active {
    color: var(--primary);
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

.card {
    background: var(--card-bg);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.card h2 {
    margin-bottom: 1rem;
    font-size: 1.25rem;
}

.btn {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;
}

.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover {
    background: var(--primary-dark);
}

.status-message {
    color: var(--text-muted);
}

.progress-bar {
    background: var(--border);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
}

.progress-bar-fill {
    background: var(--primary);
    height: 100%;
    transition: width 0.3s ease;
}

.footer {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
    font-size: 0.875rem;
}

/* Dashboard specific */
.dashboard {
    display: grid;
    gap: 1.5rem;
}

@media (min-width: 768px) {
    .dashboard {
        grid-template-columns: repeat(2, 1fr);
    }

    .disc-status {
        grid-column: span 2;
    }
}
```

**Step 5: Create config module**

```python
# src/amphigory/config.py
"""Application configuration."""

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""
    database_path: Path
    preset_dir: Path
    ripped_dir: Path
    inbox_dir: Path
    plex_dir: Path
    wiki_dir: Path


def get_config() -> Config:
    """Load configuration from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    config_dir = Path(os.environ.get("AMPHIGORY_CONFIG", "/config"))

    return Config(
        database_path=data_dir / "amphigory.db",
        preset_dir=config_dir / "presets",
        ripped_dir=Path(os.environ.get("AMPHIGORY_RIPPED_DIR", "/media/ripped")),
        inbox_dir=Path(os.environ.get("AMPHIGORY_INBOX_DIR", "/media/plex/inbox")),
        plex_dir=Path(os.environ.get("AMPHIGORY_PLEX_DIR", "/media/plex/data")),
        wiki_dir=Path(os.environ.get("AMPHIGORY_WIKI_DIR", "/wiki")),
    )
```

**Step 6: Test the server locally**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src AMPHIGORY_DATA=./data AMPHIGORY_CONFIG=./config uvicorn amphigory.main:app --reload`
Expected: Server starts, http://localhost:8000 shows dashboard

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: add web interface with dashboard template"
```

---

### Task 9: API Endpoints for Disc Operations

**Files:**
- Create: `src/amphigory/api/__init__.py`
- Create: `src/amphigory/api/disc.py`
- Modify: `src/amphigory/main.py` (add router)

**Step 1: Create API router for disc operations**

```python
# src/amphigory/api/disc.py
"""API endpoints for disc operations."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amphigory.makemkv import scan_disc, check_for_disc, classify_tracks

router = APIRouter(prefix="/api/disc", tags=["disc"])


class DiscStatusResponse(BaseModel):
    """Disc status response."""
    has_disc: bool
    device_path: str | None = None
    disc_type: str | None = None
    volume_name: str | None = None
    track_count: int = 0


@router.get("/status")
async def get_disc_status(request: Request) -> DiscStatusResponse:
    """Check current disc status."""
    has_disc, device_path = await check_for_disc()

    if not has_disc:
        return DiscStatusResponse(has_disc=False)

    return DiscStatusResponse(
        has_disc=True,
        device_path=device_path,
    )


@router.post("/scan")
async def scan_current_disc(request: Request):
    """Scan the disc and return track information."""
    disc_info = await scan_disc(drive_index=0)

    if not disc_info:
        raise HTTPException(status_code=404, detail="No disc found or scan failed")

    # Classify tracks
    classified_tracks = classify_tracks(disc_info.tracks)

    return {
        "disc_type": disc_info.disc_type,
        "volume_name": disc_info.volume_name,
        "device_path": disc_info.device_path,
        "tracks": [
            {
                "title_id": t.title_id,
                "duration": t.duration_str,
                "size": t.size_human,
                "resolution": t.resolution,
                "classification": t.classification.value,
                "audio_tracks": len(t.audio_streams),
                "subtitle_tracks": len(t.subtitle_streams),
            }
            for t in classified_tracks
        ],
    }


# HTML fragment for HTMX
@router.get("/status", response_class=HTMLResponse)
async def get_disc_status_html(request: Request):
    """Return disc status as HTML fragment for HTMX."""
    has_disc, device_path = await check_for_disc()

    if not has_disc:
        return '<p class="status-message">No disc detected</p>'

    return f'''
    <div class="disc-detected">
        <p class="status-message status-success">Disc detected at {device_path}</p>
        <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
            Scan Disc
        </button>
    </div>
    '''
```

**Step 2: Create API __init__.py**

```python
# src/amphigory/api/__init__.py
"""API routers."""

from amphigory.api.disc import router as disc_router

__all__ = ["disc_router"]
```

**Step 3: Update main.py to include router**

Add to `src/amphigory/main.py`:

```python
from amphigory.api import disc_router

# After app creation
app.include_router(disc_router)
```

**Step 4: Test endpoints**

Run: `curl http://localhost:8000/api/disc/status`
Expected: JSON response with disc status

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add API endpoints for disc operations"
```

---

### Task 10: WebSocket for Real-time Progress

**Files:**
- Create: `src/amphigory/websocket.py`
- Create: `src/amphigory/api/jobs.py`
- Modify: `src/amphigory/main.py` (add WebSocket endpoint)

**Step 1: Create WebSocket manager**

```python
# src/amphigory/websocket.py
"""WebSocket connection management."""

from fastapi import WebSocket
from typing import Any
import json


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]):
        """Send a message to all connected clients."""
        json_message = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(json_message)
            except Exception:
                self.disconnect(connection)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]):
        """Send a message to a specific client."""
        await websocket.send_text(json.dumps(message))


# Global connection manager
manager = ConnectionManager()
```

**Step 2: Create jobs API**

```python
# src/amphigory/api/jobs.py
"""API endpoints for job management."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from amphigory.jobs import JobQueue, JobType, JobStatus

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/active", response_class=HTMLResponse)
async def get_active_jobs_html(request: Request):
    """Return active jobs as HTML fragment for HTMX."""
    db = request.app.state.db
    queue = JobQueue(db)

    # Get running jobs
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY started_at DESC",
            (JobStatus.RUNNING.value,),
        )
        running_jobs = [dict(row) for row in await cursor.fetchall()]

    if not running_jobs:
        return '<p class="no-jobs">No active jobs</p>'

    html = ""
    for job in running_jobs:
        html += f'''
        <div class="job-item">
            <div class="job-info">
                <span class="job-type">{job["job_type"].title()}</span>
                <span class="job-track">Track {job["track_id"]}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-bar-fill" style="width: {job["progress"]}%"></div>
            </div>
            <span class="progress-text">{job["progress"]}%</span>
        </div>
        '''

    return html


@router.get("/queue")
async def get_job_queue(request: Request):
    """Get all queued jobs."""
    db = request.app.state.db
    queue = JobQueue(db)

    jobs = await queue.get_queue()
    return {"jobs": jobs}


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int):
    """Cancel a queued job."""
    db = request.app.state.db
    queue = JobQueue(db)

    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.QUEUED.value:
        raise HTTPException(status_code=400, detail="Can only cancel queued jobs")

    await queue.cancel_job(job_id)
    return {"status": "cancelled"}


@router.post("/{job_id}/priority")
async def update_job_priority(request: Request, job_id: int, priority: int):
    """Update a job's priority."""
    db = request.app.state.db
    queue = JobQueue(db)

    await queue.reorder_job(job_id, priority)
    return {"status": "updated"}
```

**Step 3: Add WebSocket endpoint to main.py**

```python
from fastapi import WebSocket, WebSocketDisconnect
from amphigory.websocket import manager
from amphigory.api import disc_router, jobs_router

# Add router
app.include_router(jobs_router)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_text()
            # Could process commands here if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

**Step 4: Update api/__init__.py**

```python
# src/amphigory/api/__init__.py
"""API routers."""

from amphigory.api.disc import router as disc_router
from amphigory.api.jobs import router as jobs_router

__all__ = ["disc_router", "jobs_router"]
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add WebSocket for real-time progress updates"
```

---

## Phase 4: Integration and Docker

### Task 11: Docker Compose Integration

**Files:**
- Modify: `Dockerfile` (finalize)
- Create: `docker-compose.amphigory.yaml`

**Step 1: Finalize Dockerfile**

Update `Dockerfile` with complete MakeMKV and HandBrake installation.

**Step 2: Create docker-compose file for amphigory**

```yaml
# docker-compose.amphigory.yaml
# Add this to /opt/beehive-docker/docker-compose.yaml or run separately

services:
  amphigory:
    build:
      context: /Users/purp/work/amphigory
      dockerfile: Dockerfile
    container_name: amphigory
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=America/Los_Angeles
      - AMPHIGORY_DATA=/data
      - AMPHIGORY_CONFIG=/config
      - AMPHIGORY_RIPPED_DIR=/media/ripped
      - AMPHIGORY_INBOX_DIR=/media/plex/inbox
      - AMPHIGORY_PLEX_DIR=/media/plex/data
      - AMPHIGORY_WIKI_DIR=/wiki
      # MakeMKV license key
      - MAKEMKV_KEY=${MAKEMKV_KEY}
    volumes:
      - /opt/beehive-docker/amphigory/data:/data
      - /opt/beehive-docker/amphigory/config:/config
      - /Volumes/Media Drive 1/Ripped:/media/ripped
      - /Volumes/Media Drive 1/plex-media-server/inbox:/media/plex/inbox
      - /Volumes/Media Drive 1/plex-media-server/data:/media/plex/data
      - /opt/beehive-docker/gollum/wiki-data:/wiki
    devices:
      - /dev/rdisk4:/dev/cdrom
    privileged: true  # May be needed for optical drive access
```

**Step 3: Create host directory structure**

```bash
mkdir -p /opt/beehive-docker/amphigory/{data,config/presets}
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add Docker configuration for deployment"
```

---

### Task 12: Pipeline Orchestrator

**Files:**
- Create: `src/amphigory/pipeline.py`
- Create: `tests/test_pipeline.py`

This task creates the main orchestrator that coordinates:
1. Disc detection
2. Track selection
3. Ripping jobs
4. Transcoding jobs
5. File organization

**Step 1: Write failing test**

```python
# tests/test_pipeline.py
"""Tests for pipeline orchestration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_pipeline_creates_folder_structure():
    """Test that pipeline creates correct folder structure."""
    from amphigory.pipeline import Pipeline

    with patch.object(Path, 'mkdir') as mock_mkdir:
        pipeline = Pipeline(
            ripped_dir=Path("/media/ripped"),
            inbox_dir=Path("/media/plex/inbox"),
            plex_dir=Path("/media/plex/data"),
        )

        paths = pipeline.create_folder_structure(
            title="The Polar Express",
            year=2004,
            imdb_id="tt0338348",
            extras_types=["Featurettes", "Trailers"],
        )

        assert "ripped" in paths
        assert "inbox" in paths
        assert "The Polar Express (2004) {imdb-tt0338348}" in str(paths["ripped"])
```

**Step 2: Create src/amphigory/pipeline.py**

```python
"""Pipeline orchestration for the complete rip-transcode workflow."""

import asyncio
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Any

from amphigory.makemkv import DiscInfo, Track, scan_disc, classify_tracks
from amphigory.services.ripper import RipperService, RipProgress
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.jobs import JobQueue, JobType, JobStatus
from amphigory.presets import PresetManager
from amphigory.database import Database


@dataclass
class PipelineConfig:
    """Pipeline configuration."""
    ripped_dir: Path
    inbox_dir: Path
    plex_dir: Path
    preset_manager: PresetManager


@dataclass
class ProcessingJob:
    """A track being processed."""
    track: Track
    track_type: str
    final_name: str
    ripped_path: Path | None = None
    transcoded_path: Path | None = None


class Pipeline:
    """Orchestrates the complete rip-transcode-organize workflow."""

    def __init__(
        self,
        ripped_dir: Path,
        inbox_dir: Path,
        plex_dir: Path,
        preset_manager: PresetManager | None = None,
        db: Database | None = None,
    ):
        self.ripped_dir = ripped_dir
        self.inbox_dir = inbox_dir
        self.plex_dir = plex_dir
        self.preset_manager = preset_manager
        self.db = db

        self.ripper = RipperService(ripped_dir)
        self.transcoder = TranscoderService()

    def format_folder_name(
        self,
        title: str,
        year: int,
        imdb_id: str,
        edition: str | None = None,
    ) -> str:
        """Format folder name according to Plex conventions."""
        name = f"{title} ({year}) {{imdb-{imdb_id}}}"
        if edition:
            name += f" {{edition-{edition}}}"
        return name

    def create_folder_structure(
        self,
        title: str,
        year: int,
        imdb_id: str,
        extras_types: list[str] | None = None,
        edition: str | None = None,
    ) -> dict[str, Path]:
        """Create the folder structure for a movie.

        Returns paths for ripped and inbox directories.
        """
        folder_name = self.format_folder_name(title, year, imdb_id, edition)

        ripped_path = self.ripped_dir / folder_name
        inbox_path = self.inbox_dir / folder_name

        ripped_path.mkdir(parents=True, exist_ok=True)
        inbox_path.mkdir(parents=True, exist_ok=True)

        # Create extras subdirectories
        if extras_types:
            for extra_type in extras_types:
                (inbox_path / extra_type).mkdir(exist_ok=True)

        return {
            "ripped": ripped_path,
            "inbox": inbox_path,
            "folder_name": folder_name,
        }

    async def process_disc(
        self,
        disc_info: DiscInfo,
        title: str,
        year: int,
        imdb_id: str,
        selected_tracks: list[dict],  # [{track_id, track_type, final_name}]
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> bool:
        """Process a disc through the complete pipeline.

        Args:
            disc_info: Scanned disc information
            title: Movie title
            year: Release year
            imdb_id: IMDB ID
            selected_tracks: List of tracks to process with metadata
            progress_callback: Callback(stage, percent, message)

        Returns:
            True if successful, False otherwise
        """
        # Determine extras types from selected tracks
        extras_types = list(set(
            t["track_type"] for t in selected_tracks
            if t["track_type"] != "main"
        ))

        # Create folder structure
        paths = self.create_folder_structure(
            title, year, imdb_id, extras_types
        )

        # Process each track
        for i, track_info in enumerate(selected_tracks):
            track_id = track_info["track_id"]
            track = next(t for t in disc_info.tracks if t.title_id == track_id)

            # Rip
            if progress_callback:
                progress_callback("rip", 0, f"Ripping track {track_id}...")

            ripped_path = await self.ripper.rip_title(
                drive_index=0,
                title_index=track_id,
                output_dir=paths["ripped"],
                progress_callback=lambda p: progress_callback(
                    "rip", p.percent, f"Ripping: {p.percent}%"
                ) if progress_callback else None,
            )

            if not ripped_path:
                return False

            # Determine output path based on track type
            track_type = track_info["track_type"]
            final_name = track_info["final_name"]

            if track_type == "main":
                output_path = paths["inbox"] / f"{final_name}.mp4"
            else:
                output_path = paths["inbox"] / track_type / f"{final_name}.mp4"

            # Transcode
            if progress_callback:
                progress_callback("transcode", 0, f"Transcoding {final_name}...")

            # Get appropriate preset
            preset_name = self.preset_manager.get_active_preset(disc_info.disc_type)
            preset_path = self.preset_manager.get_preset_path(disc_info.disc_type)

            success = await self.transcoder.transcode(
                input_path=ripped_path,
                output_path=output_path,
                preset_path=preset_path,
                preset_name=preset_name,
                progress_callback=lambda p: progress_callback(
                    "transcode", p.percent, f"Transcoding: {p.percent}%"
                ) if progress_callback else None,
            )

            if not success:
                return False

        return True

    async def finalize(
        self,
        folder_name: str,
        destination: str = "Movies",
    ) -> Path:
        """Move processed content from inbox to Plex library.

        Returns the final path.
        """
        source = self.inbox_dir / folder_name
        dest = self.plex_dir / destination / folder_name

        # Move the folder
        import shutil
        shutil.move(str(source), str(dest))

        return dest
```

**Step 3: Run tests**

Run: `cd /Users/purp/work/amphigory && PYTHONPATH=src pytest tests/test_pipeline.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: add pipeline orchestrator for complete workflow"
```

---

## Remaining Tasks (Brief Overview)

### Task 13: Disc Review Page
- Create `src/amphigory/templates/disc_review.html`
- Add track selection UI with checkboxes
- IMDB search integration
- Folder preview

### Task 14: Queue Page
- Create `src/amphigory/templates/queue.html`
- Progress bars for active jobs
- Drag-to-reorder functionality
- Cancel/remove buttons

### Task 15: Library Page
- Create `src/amphigory/templates/library.html`
- Sortable/filterable table of processed discs
- Markdown export functionality

### Task 16: Cleanup Page
- Create `src/amphigory/templates/cleanup.html`
- File tree view of `/media/ripped`
- Multi-select deletion
- Orphan detection

### Task 17: Wiki Integration
- Create `src/amphigory/wiki.py`
- Markdown generation from database
- Git commit automation

### Task 18: Background Polling Service
- Create `src/amphigory/services/poller.py`
- 5-second polling for disc detection
- WebSocket notifications on disc insert

### Task 19: End-to-End Testing
- Integration tests with mock MakeMKV/HandBrake
- UI testing with Playwright or similar

### Task 20: Documentation
- README.md with setup instructions
- API documentation
- User guide

---

## Execution Checklist

- [ ] Task 1: Project structure
- [ ] Task 2: Database schema
- [ ] Task 3: MakeMKV parser
- [ ] Task 4: Preset management
- [ ] Task 5: Job queue
- [ ] Task 6: Ripping service
- [ ] Task 7: Transcoding service
- [ ] Task 8: Web server and templates
- [ ] Task 9: Disc API endpoints
- [ ] Task 10: WebSocket progress
- [ ] Task 11: Docker configuration
- [ ] Task 12: Pipeline orchestrator
- [ ] Tasks 13-20: UI pages and integration

---

**Plan complete and saved to `docs/plans/2025-12-21-amphigory-implementation.md`.**

**Two execution options:**

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** - Open new session in worktree with executing-plans, batch execution with checkpoints

**Which approach?**
