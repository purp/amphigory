# Amphigory Host Daemon Implementation Plan

**Date:** 2025-12-22

**Design Document:** `2025-12-22-amphigory-daemon-design.md`

## Overview

This plan implements the Amphigory host daemon - a macOS menu bar app that bridges the containerized webapp and the optical drive. TDD approach throughout.

## Project Structure

```
daemon/
├── src/
│   └── amphigory_daemon/
│       ├── __init__.py
│       ├── main.py              # Entry point, rumps app
│       ├── config.py            # Configuration loading/caching
│       ├── discovery.py         # makemkvcon discovery
│       ├── tasks.py             # Task queue management
│       ├── makemkv.py           # MakeMKV execution
│       ├── websocket.py         # WebSocket server
│       ├── disc.py              # Disc detection (PyObjC)
│       ├── icons.py             # Menu bar icon states
│       └── models.py            # Dataclasses for tasks/responses
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_discovery.py
│   ├── test_tasks.py
│   ├── test_makemkv.py
│   ├── test_websocket.py
│   └── fixtures/
│       └── ...
├── resources/
│   └── icons/                   # Menu bar icon assets
├── pyproject.toml
└── README.md
```

## Implementation Tasks

### Task 1: Project Setup

**Goal:** Initialize daemon project with dependencies.

**pyproject.toml:**
```toml
[project]
name = "amphigory-daemon"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "rumps>=0.4.0",
    "websockets>=12.0",
    "httpx>=0.27.0",
    "PyYAML>=6.0",
    "pyobjc-framework-Cocoa>=10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amphigory-daemon = "amphigory_daemon.main:main"
```

**Test:** Project installs and imports successfully.

---

### Task 2: Data Models

**Goal:** Define dataclasses for tasks, responses, and configuration.

**models.py:**
```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class TaskType(Enum):
    SCAN = "scan"
    RIP = "rip"

class TaskStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"

class ErrorCode(Enum):
    DISC_EJECTED = "DISC_EJECTED"
    DISC_UNREADABLE = "DISC_UNREADABLE"
    MAKEMKV_FAILED = "MAKEMKV_FAILED"
    MAKEMKV_TIMEOUT = "MAKEMKV_TIMEOUT"
    OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"
    UNKNOWN = "UNKNOWN"

@dataclass
class TrackInfo:
    number: int
    expected_size_bytes: int
    expected_duration: str

@dataclass
class OutputInfo:
    directory: str
    filename: str

@dataclass
class ScanTask:
    id: str
    type: TaskType
    created_at: datetime

@dataclass
class RipTask:
    id: str
    type: TaskType
    created_at: datetime
    track: TrackInfo
    output: OutputInfo

@dataclass
class AudioStream:
    language: str
    codec: str
    channels: int

@dataclass
class SubtitleStream:
    language: str
    format: str

@dataclass
class ScannedTrack:
    number: int
    duration: str
    size_bytes: int
    chapters: int
    resolution: str
    audio_streams: list[AudioStream]
    subtitle_streams: list[SubtitleStream]

@dataclass
class ScanResult:
    disc_name: str
    disc_type: str
    tracks: list[ScannedTrack]

@dataclass
class RipResult:
    output_path: str
    size_bytes: int

@dataclass
class TaskError:
    code: ErrorCode
    message: str
    detail: Optional[str] = None

@dataclass
class TaskResponse:
    task_id: str
    status: TaskStatus
    started_at: datetime
    completed_at: datetime
    duration_seconds: int
    result: Optional[ScanResult | RipResult] = None
    error: Optional[TaskError] = None

@dataclass
class DaemonConfig:
    webapp_url: str
    webapp_basedir: str

@dataclass
class WebappConfig:
    tasks_directory: str
    websocket_port: int
    wiki_url: str
    heartbeat_interval: int
    log_level: str
    makemkv_path: Optional[str] = None
```

**Tests:**
- Dataclasses serialize to/from JSON correctly
- Enums serialize as string values

---

### Task 3: Configuration Management

**Goal:** Load local config, fetch webapp config, cache config.

**config.py:**
```python
import yaml
import httpx
import json
from pathlib import Path
from .models import DaemonConfig, WebappConfig

CONFIG_DIR = Path.home() / ".config" / "amphigory"
LOCAL_CONFIG = CONFIG_DIR / "daemon.yaml"
CACHED_CONFIG = CONFIG_DIR / "cached_config.json"

def load_local_config() -> DaemonConfig:
    """Load webapp_url and webapp_basedir from local yaml."""
    ...

async def fetch_webapp_config(webapp_url: str) -> WebappConfig:
    """Fetch /config.json from webapp."""
    ...

def cache_webapp_config(config: WebappConfig) -> None:
    """Write config to cached_config.json."""
    ...

def load_cached_config() -> WebappConfig | None:
    """Load cached config if available."""
    ...

async def get_config() -> tuple[DaemonConfig, WebappConfig]:
    """Load local config, fetch webapp config (with cache fallback)."""
    ...
```

**Tests:**
- `load_local_config()` reads yaml correctly
- `fetch_webapp_config()` parses JSON response
- `cache_webapp_config()` writes valid JSON
- `load_cached_config()` returns None when no cache
- `get_config()` falls back to cache when webapp unreachable

---

### Task 4: makemkvcon Discovery

**Goal:** Find makemkvcon binary on the system.

**discovery.py:**
```python
import shutil
from pathlib import Path

SEARCH_PATHS = [
    "/opt/homebrew/bin/makemkvcon",
    "/usr/local/bin/makemkvcon",
    "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon",
]

def discover_makemkvcon(configured_path: str | None = None) -> Path | None:
    """
    Find makemkvcon binary.

    1. Use configured_path if provided
    2. Check $PATH via shutil.which()
    3. Check SEARCH_PATHS in order

    Returns Path to binary or None if not found.
    """
    ...
```

**Tests:**
- Returns configured path if provided and exists
- Finds binary in $PATH
- Falls back to search paths
- Returns None when not found

---

### Task 5: Task Queue Management

**Goal:** Read tasks.json, pick next task, move between directories, write responses.

**tasks.py:**
```python
import json
from pathlib import Path
from datetime import datetime
from .models import ScanTask, RipTask, TaskResponse

class TaskQueue:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.tasks_json = base_dir / "tasks.json"
        self.queued_dir = base_dir / "queued"
        self.in_progress_dir = base_dir / "in_progress"
        self.complete_dir = base_dir / "complete"

    def ensure_directories(self) -> None:
        """Create queue directories if they don't exist."""
        ...

    def get_task_order(self) -> list[str]:
        """Read tasks.json and return ordered list of task IDs."""
        ...

    def get_next_task(self) -> ScanTask | RipTask | None:
        """
        Find next task to process:
        1. Read tasks.json for order
        2. Find first ID with file in queued/
        3. Move file to in_progress/
        4. Parse and return task
        """
        ...

    def complete_task(self, response: TaskResponse) -> None:
        """
        Write response to complete/, delete from in_progress/.
        """
        ...

    def recover_crashed_tasks(self) -> None:
        """
        On startup, move any tasks in in_progress/ back to queued/.
        """
        ...
```

**Tests:**
- `get_task_order()` returns empty list when no tasks.json
- `get_next_task()` skips missing files, picks first available
- `get_next_task()` moves file to in_progress/
- `complete_task()` writes correct JSON, cleans up in_progress/
- `recover_crashed_tasks()` moves files back to queued/

---

### Task 6: MakeMKV Execution

**Goal:** Run makemkvcon for scan and rip operations with progress parsing.

**makemkv.py:**
```python
import asyncio
from pathlib import Path
from typing import AsyncIterator
from .models import ScanResult, ScannedTrack, ErrorCode

@dataclass
class Progress:
    percent: int
    eta_seconds: int | None
    current_size_bytes: int | None
    speed: str | None

async def scan_disc(
    makemkv_path: Path
) -> AsyncIterator[Progress | ScanResult | ErrorCode]:
    """
    Run makemkvcon -r info disc:0
    Yield Progress updates, then final ScanResult or ErrorCode.
    """
    ...

async def rip_track(
    makemkv_path: Path,
    track_number: int,
    output_dir: Path,
    output_filename: str,
) -> AsyncIterator[Progress | Path | ErrorCode]:
    """
    Run makemkvcon mkv disc:0 <track> <output_dir>
    Yield Progress updates, then final output Path or ErrorCode.
    """
    ...

def parse_scan_output(output: str) -> ScanResult:
    """Parse makemkvcon info output into ScanResult."""
    # Reuse parsing logic from webapp's makemkv.py
    ...

def parse_progress_line(line: str) -> Progress | None:
    """Parse PRGV/PRGT lines into Progress."""
    ...
```

**Tests:**
- `parse_scan_output()` handles real makemkvcon output
- `parse_progress_line()` extracts percentage and ETA
- Error conditions return appropriate ErrorCode

---

### Task 7: WebSocket Server

**Goal:** Run WebSocket server, broadcast messages, handle webapp connection.

**websocket.py:**
```python
import asyncio
import websockets
from websockets.server import WebSocketServerProtocol
from typing import Any
from datetime import datetime

class WebSocketServer:
    def __init__(self, port: int, heartbeat_interval: int):
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.clients: set[WebSocketServerProtocol] = set()
        self._server = None

    async def start(self) -> None:
        """Start WebSocket server."""
        ...

    async def stop(self) -> None:
        """Stop WebSocket server."""
        ...

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        ...

    async def send_progress(self, task_id: str, percent: int,
                           eta_seconds: int | None,
                           current_size_bytes: int | None,
                           speed: str | None) -> None:
        """Send progress update."""
        ...

    async def send_disc_event(self, event: str, device: str,
                             volume_name: str | None = None) -> None:
        """Send disc inserted/ejected event."""
        ...

    async def send_heartbeat(self, queue_depth: int,
                            current_task: str | None,
                            paused: bool) -> None:
        """Send periodic heartbeat."""
        ...

    async def send_sync(self, state: dict[str, Any]) -> None:
        """Send full state sync on reconnect."""
        ...

    def has_clients(self) -> bool:
        """Check if any clients are connected."""
        ...
```

**Tests:**
- Server starts and accepts connections
- `broadcast()` sends to all clients
- Messages are valid JSON with correct structure
- Handles client disconnect gracefully

---

### Task 8: Disc Detection (macOS)

**Goal:** Detect disc insertion/ejection using macOS notifications.

**disc.py:**
```python
from typing import Callable
from Foundation import NSWorkspace, NSNotificationCenter
from AppKit import NSWorkspaceDidMountNotification, NSWorkspaceDidUnmountNotification

class DiscDetector:
    def __init__(
        self,
        on_insert: Callable[[str, str], None],  # device, volume_name
        on_eject: Callable[[str], None],        # device
    ):
        self.on_insert = on_insert
        self.on_eject = on_eject
        self._observer = None

    def start(self) -> None:
        """Register for mount/unmount notifications."""
        ...

    def stop(self) -> None:
        """Unregister notifications."""
        ...

    def _handle_mount(self, notification) -> None:
        """Filter for optical discs, call on_insert."""
        ...

    def _handle_unmount(self, notification) -> None:
        """Call on_eject."""
        ...

    def get_current_disc(self) -> tuple[str, str] | None:
        """Check if a disc is currently inserted, return (device, volume)."""
        ...
```

**Tests:**
- Manual/integration test with real disc
- `get_current_disc()` returns None when no disc

---

### Task 9: Menu Bar Icons

**Goal:** Generate/manage menu bar icon states.

**icons.py:**
```python
from enum import Enum, auto
from pathlib import Path

class ActivityState(Enum):
    IDLE_EMPTY = auto()
    IDLE_DISC = auto()
    WORKING = auto()

class StatusOverlay(Enum):
    NONE = auto()
    PAUSED = auto()
    DISCONNECTED = auto()
    ERROR = auto()

def get_icon(
    activity: ActivityState,
    overlays: set[StatusOverlay] | None = None
) -> str:
    """
    Return path to icon for given state.
    Icons are pre-generated PNG files in resources/icons/.
    """
    ...

# Icon filenames follow pattern:
# idle_empty.png, idle_empty_paused.png, idle_empty_disconnected.png, etc.
```

**Tests:**
- All icon combinations have corresponding files
- `get_icon()` returns valid paths

---

### Task 10: Main Application (rumps)

**Goal:** Tie everything together in a menu bar app.

**main.py:**
```python
import rumps
import asyncio
from .config import get_config
from .discovery import discover_makemkvcon
from .tasks import TaskQueue
from .websocket import WebSocketServer
from .disc import DiscDetector
from .icons import get_icon, ActivityState, StatusOverlay

class AmphigoryDaemon(rumps.App):
    def __init__(self):
        super().__init__("Amphigory", quit_button=None)
        self.daemon_config = None
        self.webapp_config = None
        self.makemkv_path = None
        self.task_queue = None
        self.ws_server = None
        self.disc_detector = None
        self.current_task = None
        self.paused = False
        self.scan_cache = None

        # Menu items
        self.disc_item = rumps.MenuItem("No disc inserted")
        self.progress_item = rumps.MenuItem("")
        self.queue_item = rumps.MenuItem("")

    def build_menu(self) -> list:
        """Build menu structure."""
        return [
            self.disc_item,
            None,  # separator
            self.progress_item,
            self.queue_item,
            None,
            rumps.MenuItem("Open Webapp...", callback=self.open_webapp),
            rumps.MenuItem("Help & Documentation...", callback=self.open_help),
            None,
            rumps.MenuItem("Pause After Track", callback=self.toggle_pause),
            rumps.MenuItem("Restart Daemon", callback=self.restart),
            rumps.MenuItem("Preferences...", callback=self.open_preferences),
            rumps.MenuItem("Quit", callback=self.quit),
        ]

    async def initialize(self) -> bool:
        """Load config, discover makemkv, setup components."""
        ...

    async def run_task_loop(self) -> None:
        """Main loop: process tasks from queue."""
        ...

    def on_disc_insert(self, device: str, volume_name: str) -> None:
        """Handle disc insertion, start proactive scan."""
        ...

    def on_disc_eject(self, device: str) -> None:
        """Handle disc ejection, clear cache."""
        ...

    def update_icon(self) -> None:
        """Update menu bar icon based on current state."""
        ...

    # ... callback methods for menu items ...

def main():
    app = AmphigoryDaemon()
    # Run async initialization and task loop alongside rumps
    ...
```

**Tests:**
- Integration tests for menu building
- State transitions update icon correctly

---

### Task 11: Proactive Scanning

**Goal:** Automatically scan disc on insertion, cache results.

**Add to main.py:**
```python
@dataclass
class ScanCache:
    device: str
    result: ScanResult
    scanned_at: datetime

class AmphigoryDaemon(rumps.App):
    # ... existing code ...

    def on_disc_insert(self, device: str, volume_name: str) -> None:
        """Handle disc insertion."""
        # Send WebSocket event
        asyncio.create_task(
            self.ws_server.send_disc_event("inserted", device, volume_name)
        )
        # Start proactive scan
        asyncio.create_task(self._proactive_scan(device))
        self.update_icon()

    async def _proactive_scan(self, device: str) -> None:
        """Run scan in background, cache result."""
        async for item in scan_disc(self.makemkv_path):
            if isinstance(item, ScanResult):
                self.scan_cache = ScanCache(
                    device=device,
                    result=item,
                    scanned_at=datetime.now()
                )
            # Ignore progress for proactive scan

    async def handle_scan_task(self, task: ScanTask) -> TaskResponse:
        """Process scan task, use cache if available."""
        started_at = datetime.now()

        # Check cache
        if (self.scan_cache and
            self.disc_detector.get_current_disc() and
            self.scan_cache.device == self.disc_detector.get_current_disc()[0]):
            result = self.scan_cache.result
        else:
            # Run fresh scan
            async for item in scan_disc(self.makemkv_path):
                if isinstance(item, ScanResult):
                    result = item
                elif isinstance(item, ErrorCode):
                    return TaskResponse(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        started_at=started_at,
                        completed_at=datetime.now(),
                        duration_seconds=...,
                        error=TaskError(code=item, message=str(item))
                    )

        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.SUCCESS,
            started_at=started_at,
            completed_at=datetime.now(),
            duration_seconds=...,
            result=result
        )
```

**Tests:**
- Proactive scan populates cache
- Scan task uses cached result when valid
- Cache invalidated on disc eject

---

### Task 12: Pause/Resume Functionality

**Goal:** Implement pause controls.

**Add to main.py:**
```python
class PauseMode(Enum):
    NONE = auto()
    AFTER_TRACK = auto()
    IMMEDIATE = auto()

class AmphigoryDaemon(rumps.App):
    def __init__(self):
        # ... existing ...
        self.pause_mode = PauseMode.NONE
        self.pause_after_track_item = rumps.MenuItem(
            "Pause After Track", callback=self.toggle_pause_after_track
        )
        self.pause_now_item = rumps.MenuItem(
            "Pause Now", callback=self.pause_now
        )

    def toggle_pause_after_track(self, sender) -> None:
        """Toggle pause after current track completes."""
        if self.pause_mode == PauseMode.AFTER_TRACK:
            self.pause_mode = PauseMode.NONE
            sender.title = "Pause After Track"
        else:
            self.pause_mode = PauseMode.AFTER_TRACK
            sender.title = "▶ Resume"
        self.update_icon()

    def pause_now(self, sender) -> None:
        """Pause immediately (after current operation)."""
        self.pause_mode = PauseMode.IMMEDIATE
        self.update_icon()

    async def run_task_loop(self) -> None:
        """Main loop with pause support."""
        while True:
            if self.pause_mode == PauseMode.IMMEDIATE:
                await asyncio.sleep(1)
                continue

            task = self.task_queue.get_next_task()
            if not task:
                await asyncio.sleep(1)
                continue

            # Process task...

            if self.pause_mode == PauseMode.AFTER_TRACK:
                self.pause_mode = PauseMode.IMMEDIATE
                # Update menu to show Resume
```

**Tests:**
- Pause after track stops processing after current task
- Pause now stops before next task
- Resume continues processing

---

### Task 13: Integration Testing

**Goal:** End-to-end tests with mocked MakeMKV.

- Test full flow: config load → task pickup → execution → response
- Test WebSocket reconnection and sync
- Test crash recovery
- Test proactive scan + cache hit

---

### Task 14: Packaging

**Goal:** Create distributable app bundle.

- Use py2app or similar to create .app bundle
- Include icon assets
- Create launchd plist for login item
- Document installation process

---

## Execution Order

1. Task 1: Project Setup
2. Task 2: Data Models
3. Task 3: Configuration Management
4. Task 4: makemkvcon Discovery
5. Task 5: Task Queue Management
6. Task 6: MakeMKV Execution
7. Task 7: WebSocket Server
8. Task 8: Disc Detection
9. Task 9: Menu Bar Icons
10. Task 10: Main Application
11. Task 11: Proactive Scanning
12. Task 12: Pause/Resume
13. Task 13: Integration Testing
14. Task 14: Packaging

Tasks 2-6 can be developed and tested independently. Task 10 integrates everything.
