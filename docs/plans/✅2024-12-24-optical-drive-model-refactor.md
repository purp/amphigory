# Optical Drive Model Refactor Implementation Plan

> **Status:** COMPLETED on 2024-12-24
>
> All 15 tasks completed successfully. All tests pass (134 webapp tests, 213 daemon tests).
> Documentation updated in README.md and post-launch-followups.md.

---

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor disc state management to use an OpticalDrive model in the daemon with fingerprint-based disc identification, database-backed persistence, and bidirectional WebSocket communication.

**Architecture:** The daemon owns all optical drive state (disc presence, scan status, scan results) via an OpticalDrive model. The webapp queries the daemon via WebSocket and stores disc/track data in SQLite keyed by fingerprint. Fingerprints are generated quickly (<5 sec) per media type to identify known discs without rescanning.

**Tech Stack:** Python dataclasses, aiosqlite, websockets, PyObjC (macOS disc detection)

---

## Phase 1: Daemon - OpticalDrive Model

### Task 1: Create OpticalDrive Model

**Files:**
- Create: `daemon/src/amphigory_daemon/drive.py`
- Test: `daemon/tests/test_drive.py`

**Step 1: Write the failing test**

```python
# daemon/tests/test_drive.py
"""Tests for OpticalDrive model."""

import pytest
from amphigory_daemon.drive import OpticalDrive, DriveState, ScanStatus


class TestOpticalDriveModel:
    """Tests for OpticalDrive dataclass."""

    def test_create_drive_with_daemon_id_and_device(self):
        """Can create drive with daemon_id and device."""
        drive = OpticalDrive(
            daemon_id="purp@beehive:dev",
            device="/dev/rdisk6",
        )
        assert drive.daemon_id == "purp@beehive:dev"
        assert drive.device == "/dev/rdisk6"
        assert drive.state == DriveState.EMPTY

    def test_drive_id_format(self):
        """Drive ID combines daemon_id and device with colon."""
        drive = OpticalDrive(
            daemon_id="purp@beehive:dev",
            device="/dev/rdisk6",
        )
        # Format: daemon_id:device (device without /dev/ prefix)
        assert drive.drive_id == "purp@beehive:dev:rdisk6"

    def test_drive_starts_empty(self):
        """New drive starts in EMPTY state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        assert drive.state == DriveState.EMPTY
        assert drive.disc_volume is None
        assert drive.fingerprint is None
        assert drive.scan_status is None
        assert drive.scan_result is None

    def test_drive_state_enum_values(self):
        """DriveState enum has expected values."""
        assert DriveState.EMPTY.value == "empty"
        assert DriveState.DISC_INSERTED.value == "disc_inserted"
        assert DriveState.SCANNING.value == "scanning"
        assert DriveState.SCANNED.value == "scanned"
        assert DriveState.RIPPING.value == "ripping"

    def test_scan_status_enum_values(self):
        """ScanStatus enum has expected values."""
        assert ScanStatus.PENDING.value == "pending"
        assert ScanStatus.IN_PROGRESS.value == "in_progress"
        assert ScanStatus.COMPLETE.value == "complete"
        assert ScanStatus.FAILED.value == "failed"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'amphigory_daemon.drive'"

**Step 3: Write minimal implementation**

```python
# daemon/src/amphigory_daemon/drive.py
"""OpticalDrive model for tracking drive and disc state."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class DriveState(Enum):
    """State of the optical drive."""
    EMPTY = "empty"
    DISC_INSERTED = "disc_inserted"
    SCANNING = "scanning"
    SCANNED = "scanned"
    RIPPING = "ripping"


class ScanStatus(Enum):
    """Status of a scan operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class OpticalDrive:
    """
    Model representing an optical drive and its current state.

    The daemon maintains one OpticalDrive instance per physical drive.
    State changes are pushed to the webapp via WebSocket.
    """
    daemon_id: str
    device: str  # e.g., "/dev/rdisk6"

    # Drive state
    state: DriveState = DriveState.EMPTY

    # Disc info (when disc inserted)
    disc_volume: Optional[str] = None  # Volume name
    disc_type: Optional[str] = None  # "cd", "dvd", "bluray"
    fingerprint: Optional[str] = None  # Quick disc identifier

    # Scan state
    scan_status: Optional[ScanStatus] = None
    scan_task_id: Optional[str] = None
    scan_result: Optional[dict] = None  # Cached scan result
    scan_error: Optional[str] = None

    # Rip state (for current rip operation)
    rip_task_id: Optional[str] = None
    rip_track_number: Optional[int] = None
    rip_progress: Optional[int] = None  # 0-100

    # Timestamps
    disc_inserted_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def drive_id(self) -> str:
        """
        Unique identifier for this drive.

        Format: {daemon_id}:{device_name}
        Example: purp@beehive:dev:rdisk6
        """
        # Strip /dev/ prefix from device
        device_name = self.device.replace("/dev/", "")
        return f"{self.daemon_id}:{device_name}"
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/drive.py daemon/tests/test_drive.py
git commit -m "feat(daemon): add OpticalDrive model with state enums"
```

---

### Task 2: Add Drive State Mutation Methods

**Files:**
- Modify: `daemon/src/amphigory_daemon/drive.py`
- Test: `daemon/tests/test_drive.py`

**Step 1: Write the failing tests**

```python
# Add to daemon/tests/test_drive.py

class TestOpticalDriveStateMutations:
    """Tests for OpticalDrive state mutation methods."""

    def test_insert_disc_updates_state(self):
        """insert_disc() updates state to DISC_INSERTED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")

        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        assert drive.state == DriveState.DISC_INSERTED
        assert drive.disc_volume == "MY_MOVIE"
        assert drive.disc_type == "bluray"
        assert drive.disc_inserted_at is not None

    def test_insert_disc_clears_previous_scan(self):
        """insert_disc() clears any previous scan state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.scan_result = {"tracks": []}
        drive.scan_status = ScanStatus.COMPLETE

        drive.insert_disc(volume="NEW_DISC", disc_type="dvd")

        assert drive.scan_result is None
        assert drive.scan_status is None
        assert drive.fingerprint is None

    def test_eject_disc_resets_to_empty(self):
        """eject_disc() resets drive to EMPTY state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.scan_result = {"tracks": []}

        drive.eject_disc()

        assert drive.state == DriveState.EMPTY
        assert drive.disc_volume is None
        assert drive.disc_type is None
        assert drive.fingerprint is None
        assert drive.scan_result is None
        assert drive.scan_status is None

    def test_start_scan_updates_state(self):
        """start_scan() transitions to SCANNING state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        drive.start_scan(task_id="scan-123")

        assert drive.state == DriveState.SCANNING
        assert drive.scan_status == ScanStatus.IN_PROGRESS
        assert drive.scan_task_id == "scan-123"

    def test_complete_scan_stores_result(self):
        """complete_scan() stores result and transitions to SCANNED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.start_scan(task_id="scan-123")

        result = {"disc_name": "MY_MOVIE", "tracks": [{"number": 1}]}
        drive.complete_scan(result=result)

        assert drive.state == DriveState.SCANNED
        assert drive.scan_status == ScanStatus.COMPLETE
        assert drive.scan_result == result

    def test_fail_scan_stores_error(self):
        """fail_scan() stores error and returns to DISC_INSERTED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.start_scan(task_id="scan-123")

        drive.fail_scan(error="Disc unreadable")

        assert drive.state == DriveState.DISC_INSERTED
        assert drive.scan_status == ScanStatus.FAILED
        assert drive.scan_error == "Disc unreadable"

    def test_to_dict_serializes_state(self):
        """to_dict() returns JSON-serializable representation."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        data = drive.to_dict()

        assert data["drive_id"] == "test:rdisk0"
        assert data["state"] == "disc_inserted"
        assert data["disc_volume"] == "MY_MOVIE"
        assert data["disc_type"] == "bluray"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py::TestOpticalDriveStateMutations -v`
Expected: FAIL with "AttributeError: 'OpticalDrive' object has no attribute 'insert_disc'"

**Step 3: Write minimal implementation**

Add these methods to the `OpticalDrive` class in `daemon/src/amphigory_daemon/drive.py`:

```python
    def insert_disc(self, volume: str, disc_type: str) -> None:
        """
        Handle disc insertion.

        Args:
            volume: Volume name of the disc
            disc_type: Type of disc ("cd", "dvd", "bluray")
        """
        # Clear any previous state
        self.scan_result = None
        self.scan_status = None
        self.scan_task_id = None
        self.scan_error = None
        self.fingerprint = None
        self.rip_task_id = None
        self.rip_track_number = None
        self.rip_progress = None

        # Set new disc info
        self.state = DriveState.DISC_INSERTED
        self.disc_volume = volume
        self.disc_type = disc_type
        self.disc_inserted_at = datetime.now()
        self.last_updated = datetime.now()

    def eject_disc(self) -> None:
        """Handle disc ejection - reset to empty state."""
        self.state = DriveState.EMPTY
        self.disc_volume = None
        self.disc_type = None
        self.fingerprint = None
        self.disc_inserted_at = None
        self.scan_result = None
        self.scan_status = None
        self.scan_task_id = None
        self.scan_error = None
        self.rip_task_id = None
        self.rip_track_number = None
        self.rip_progress = None
        self.last_updated = datetime.now()

    def start_scan(self, task_id: str) -> None:
        """
        Start a scan operation.

        Args:
            task_id: ID of the scan task
        """
        self.state = DriveState.SCANNING
        self.scan_status = ScanStatus.IN_PROGRESS
        self.scan_task_id = task_id
        self.scan_error = None
        self.last_updated = datetime.now()

    def complete_scan(self, result: dict) -> None:
        """
        Complete a scan operation successfully.

        Args:
            result: Scan result with disc_name, tracks, etc.
        """
        self.state = DriveState.SCANNED
        self.scan_status = ScanStatus.COMPLETE
        self.scan_result = result
        self.scan_error = None
        self.last_updated = datetime.now()

    def fail_scan(self, error: str) -> None:
        """
        Mark scan as failed.

        Args:
            error: Error message
        """
        self.state = DriveState.DISC_INSERTED
        self.scan_status = ScanStatus.FAILED
        self.scan_error = error
        self.last_updated = datetime.now()

    def to_dict(self) -> dict:
        """
        Convert to JSON-serializable dictionary.

        Returns:
            Dict representation of drive state
        """
        return {
            "drive_id": self.drive_id,
            "daemon_id": self.daemon_id,
            "device": self.device,
            "state": self.state.value,
            "disc_volume": self.disc_volume,
            "disc_type": self.disc_type,
            "fingerprint": self.fingerprint,
            "scan_status": self.scan_status.value if self.scan_status else None,
            "scan_task_id": self.scan_task_id,
            "scan_result": self.scan_result,
            "scan_error": self.scan_error,
            "rip_task_id": self.rip_task_id,
            "rip_track_number": self.rip_track_number,
            "rip_progress": self.rip_progress,
            "disc_inserted_at": self.disc_inserted_at.isoformat() if self.disc_inserted_at else None,
            "last_updated": self.last_updated.isoformat(),
        }
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/drive.py daemon/tests/test_drive.py
git commit -m "feat(daemon): add OpticalDrive state mutation methods"
```

---

## Phase 2: Daemon - Fingerprint Generation

### Task 3: Create Fingerprint Generator

**Files:**
- Create: `daemon/src/amphigory_daemon/fingerprint.py`
- Test: `daemon/tests/test_fingerprint.py`

**Step 1: Write the failing tests**

```python
# daemon/tests/test_fingerprint.py
"""Tests for disc fingerprint generation."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from amphigory_daemon.fingerprint import generate_fingerprint, FingerprintError


class TestFingerprintGeneration:
    """Tests for generate_fingerprint function."""

    def test_returns_string_fingerprint(self, tmp_path):
        """generate_fingerprint returns a string."""
        # Create mock DVD structure
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"fake ifo content 12345")
        (video_ts / "VTS_01_0.IFO").write_bytes(b"fake vts content 67890")

        result = generate_fingerprint(str(tmp_path), "dvd")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_dvd_fingerprint_uses_ifo_files(self, tmp_path):
        """DVD fingerprint incorporates IFO file hashes."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"ifo content")

        fp1 = generate_fingerprint(str(tmp_path), "dvd")

        # Change IFO content
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"different content")

        fp2 = generate_fingerprint(str(tmp_path), "dvd")

        assert fp1 != fp2

    def test_bluray_fingerprint_uses_mpls_files(self, tmp_path):
        """Blu-ray fingerprint incorporates MPLS file hashes."""
        bdmv = tmp_path / "BDMV" / "PLAYLIST"
        bdmv.mkdir(parents=True)
        (bdmv / "00000.mpls").write_bytes(b"playlist content")

        result = generate_fingerprint(str(tmp_path), "bluray")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_fingerprint_includes_volume_name(self, tmp_path):
        """Fingerprint incorporates volume name."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"content")

        # Same content, different volume names
        fp1 = generate_fingerprint(str(tmp_path), "dvd", volume_name="MOVIE_A")
        fp2 = generate_fingerprint(str(tmp_path), "dvd", volume_name="MOVIE_B")

        assert fp1 != fp2

    def test_fingerprint_is_deterministic(self, tmp_path):
        """Same disc produces same fingerprint."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"consistent content")

        fp1 = generate_fingerprint(str(tmp_path), "dvd", volume_name="TEST")
        fp2 = generate_fingerprint(str(tmp_path), "dvd", volume_name="TEST")

        assert fp1 == fp2

    def test_raises_error_for_missing_structure(self, tmp_path):
        """Raises FingerprintError if disc structure not found."""
        with pytest.raises(FingerprintError):
            generate_fingerprint(str(tmp_path), "dvd")

    def test_cd_fingerprint_placeholder(self, tmp_path):
        """CD fingerprint returns placeholder (future: use TOC)."""
        # CDs don't have filesystem structure we can easily mock
        # For now, just check it doesn't crash
        result = generate_fingerprint(str(tmp_path), "cd", volume_name="AUDIO_CD")
        assert isinstance(result, str)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_fingerprint.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'amphigory_daemon.fingerprint'"

**Step 3: Write minimal implementation**

```python
# daemon/src/amphigory_daemon/fingerprint.py
"""Disc fingerprint generation for quick identification."""

import hashlib
from pathlib import Path
from typing import Optional


class FingerprintError(Exception):
    """Error generating disc fingerprint."""
    pass


def generate_fingerprint(
    volume_path: str,
    disc_type: str,
    volume_name: Optional[str] = None,
) -> str:
    """
    Generate a fingerprint for a disc.

    Fingerprints are designed to be:
    - Fast to generate (< 5 seconds)
    - Unique per disc pressing
    - Stable across reads

    Args:
        volume_path: Mount path (e.g., /Volumes/MOVIE)
        disc_type: "cd", "dvd", or "bluray"
        volume_name: Optional volume name to include

    Returns:
        Hex string fingerprint

    Raises:
        FingerprintError: If disc structure not found
    """
    hasher = hashlib.sha256()

    # Include disc type and volume name
    hasher.update(f"type:{disc_type}".encode())
    if volume_name:
        hasher.update(f"volume:{volume_name}".encode())

    path = Path(volume_path)

    if disc_type == "dvd":
        _hash_dvd_structure(path, hasher)
    elif disc_type == "bluray":
        _hash_bluray_structure(path, hasher)
    elif disc_type == "cd":
        _hash_cd_structure(path, hasher, volume_name)
    else:
        raise FingerprintError(f"Unknown disc type: {disc_type}")

    return hasher.hexdigest()


def _hash_dvd_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash DVD structure (VIDEO_TS/*.IFO files)."""
    video_ts = path / "VIDEO_TS"
    if not video_ts.exists():
        raise FingerprintError("DVD structure not found (no VIDEO_TS)")

    # Hash all IFO files (small, contain disc structure)
    ifo_files = sorted(video_ts.glob("*.IFO"))
    if not ifo_files:
        raise FingerprintError("No IFO files found in VIDEO_TS")

    for ifo in ifo_files:
        hasher.update(f"file:{ifo.name}".encode())
        hasher.update(ifo.read_bytes())


def _hash_bluray_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash Blu-ray structure (BDMV/PLAYLIST/*.mpls files)."""
    playlist_dir = path / "BDMV" / "PLAYLIST"
    if not playlist_dir.exists():
        raise FingerprintError("Blu-ray structure not found (no BDMV/PLAYLIST)")

    # Hash all MPLS files (playlists, small, define disc structure)
    mpls_files = sorted(playlist_dir.glob("*.mpls"))
    if not mpls_files:
        raise FingerprintError("No MPLS files found in BDMV/PLAYLIST")

    for mpls in mpls_files:
        hasher.update(f"file:{mpls.name}".encode())
        hasher.update(mpls.read_bytes())


def _hash_cd_structure(
    path: Path,
    hasher: hashlib._Hash,
    volume_name: Optional[str],
) -> None:
    """
    Hash CD structure.

    Note: Audio CDs don't have a filesystem we can easily read.
    For now, use volume name as a weak fingerprint.
    Future: Use discid library to read TOC.
    """
    # For now, just use volume name
    # This is a weak fingerprint but functional
    if volume_name:
        hasher.update(f"cd_volume:{volume_name}".encode())
    else:
        hasher.update(b"cd_unknown")
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_fingerprint.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/fingerprint.py daemon/tests/test_fingerprint.py
git commit -m "feat(daemon): add fingerprint generation for disc identification"
```

---

### Task 4: Integrate Fingerprint into OpticalDrive

**Files:**
- Modify: `daemon/src/amphigory_daemon/drive.py`
- Test: `daemon/tests/test_drive.py`

**Step 1: Write the failing tests**

```python
# Add to daemon/tests/test_drive.py

class TestOpticalDriveFingerprintIntegration:
    """Tests for fingerprint integration in OpticalDrive."""

    def test_set_fingerprint_stores_value(self):
        """set_fingerprint() stores the fingerprint."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        drive.set_fingerprint("abc123def456")

        assert drive.fingerprint == "abc123def456"

    def test_fingerprint_included_in_to_dict(self):
        """Fingerprint is included in to_dict() output."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.set_fingerprint("abc123def456")

        data = drive.to_dict()

        assert data["fingerprint"] == "abc123def456"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py::TestOpticalDriveFingerprintIntegration -v`
Expected: FAIL with "AttributeError: 'OpticalDrive' object has no attribute 'set_fingerprint'"

**Step 3: Write minimal implementation**

Add to `OpticalDrive` class in `daemon/src/amphigory_daemon/drive.py`:

```python
    def set_fingerprint(self, fingerprint: str) -> None:
        """
        Set the disc fingerprint.

        Args:
            fingerprint: Hex string fingerprint from generate_fingerprint()
        """
        self.fingerprint = fingerprint
        self.last_updated = datetime.now()
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_drive.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/drive.py daemon/tests/test_drive.py
git commit -m "feat(daemon): integrate fingerprint into OpticalDrive model"
```

---

## Phase 3: Daemon - Bidirectional WebSocket

### Task 5: Add Request Handling to WebAppClient

**Files:**
- Modify: `daemon/src/amphigory_daemon/websocket.py`
- Test: `daemon/tests/test_websocket.py`

**Step 1: Write the failing tests**

```python
# daemon/tests/test_websocket.py (add to existing or create)
"""Tests for WebSocket bidirectional communication."""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from amphigory_daemon.websocket import WebAppClient


class TestWebAppClientRequestHandling:
    """Tests for handling requests from webapp."""

    @pytest.mark.asyncio
    async def test_registers_request_handler(self):
        """Can register a handler for incoming requests."""
        client = WebAppClient("ws://localhost:8000/ws")

        handler = AsyncMock(return_value={"status": "ok"})
        client.on_request("get_drive_status", handler)

        assert "get_drive_status" in client._request_handlers

    @pytest.mark.asyncio
    async def test_handles_request_and_sends_response(self):
        """Handles request message and sends response."""
        client = WebAppClient("ws://localhost:8000/ws")
        client._websocket = AsyncMock()
        client._connected = True

        # Register handler
        async def handle_get_status(params):
            return {"drive_id": "test:rdisk0", "state": "empty"}

        client.on_request("get_drive_status", handle_get_status)

        # Simulate incoming request
        request = {
            "type": "request",
            "request_id": "req-123",
            "method": "get_drive_status",
            "params": {},
        }

        await client._handle_message(request)

        # Verify response was sent
        client._websocket.send.assert_called_once()
        response = json.loads(client._websocket.send.call_args[0][0])
        assert response["type"] == "response"
        assert response["request_id"] == "req-123"
        assert response["result"]["drive_id"] == "test:rdisk0"

    @pytest.mark.asyncio
    async def test_handles_unknown_method(self):
        """Sends error response for unknown method."""
        client = WebAppClient("ws://localhost:8000/ws")
        client._websocket = AsyncMock()
        client._connected = True

        request = {
            "type": "request",
            "request_id": "req-456",
            "method": "unknown_method",
            "params": {},
        }

        await client._handle_message(request)

        # Verify error response was sent
        client._websocket.send.assert_called_once()
        response = json.loads(client._websocket.send.call_args[0][0])
        assert response["type"] == "response"
        assert response["request_id"] == "req-456"
        assert "error" in response
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_websocket.py::TestWebAppClientRequestHandling -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `WebAppClient` class in `daemon/src/amphigory_daemon/websocket.py`:

```python
    def __init__(self, url: str):
        # ... existing init ...
        self._request_handlers: dict[str, Callable] = {}

    def on_request(self, method: str, handler: Callable) -> None:
        """
        Register a handler for incoming requests.

        Args:
            method: Request method name (e.g., "get_drive_status")
            handler: Async function that takes params dict and returns result dict
        """
        self._request_handlers[method] = handler

    async def _handle_message(self, data: dict) -> None:
        """Handle an incoming message from webapp."""
        msg_type = data.get("type")

        if msg_type == "request":
            await self._handle_request(data)

    async def _handle_request(self, data: dict) -> None:
        """Handle an incoming request and send response."""
        request_id = data.get("request_id")
        method = data.get("method")
        params = data.get("params", {})

        handler = self._request_handlers.get(method)

        if handler is None:
            # Unknown method
            response = {
                "type": "response",
                "request_id": request_id,
                "error": {"code": "unknown_method", "message": f"Unknown method: {method}"},
            }
        else:
            try:
                result = await handler(params)
                response = {
                    "type": "response",
                    "request_id": request_id,
                    "result": result,
                }
            except Exception as e:
                response = {
                    "type": "response",
                    "request_id": request_id,
                    "error": {"code": "handler_error", "message": str(e)},
                }

        await self._send(response)
```

Also update `_receive_loop` to call `_handle_message`:

```python
    async def _receive_loop(self) -> None:
        """Background loop to receive messages and detect disconnection."""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connected = False
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_websocket.py::TestWebAppClientRequestHandling -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/websocket.py daemon/tests/test_websocket.py
git commit -m "feat(daemon): add bidirectional WebSocket request handling"
```

---

## Phase 4: Webapp - Database Schema Update

### Task 6: Add Fingerprint to Discs Table

**Files:**
- Modify: `src/amphigory/database.py`
- Test: `tests/test_database.py`

**Step 1: Write the failing test**

```python
# tests/test_database.py
"""Tests for database schema and operations."""

import pytest
import asyncio
from pathlib import Path
from amphigory.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


class TestDiscSchema:
    """Tests for discs table schema."""

    @pytest.mark.asyncio
    async def test_discs_table_has_fingerprint_column(self, db):
        """Discs table has fingerprint column."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(discs)")
            columns = await cursor.fetchall()
            column_names = [col["name"] for col in columns]

            assert "fingerprint" in column_names

    @pytest.mark.asyncio
    async def test_fingerprint_is_unique(self, db):
        """Fingerprint column has unique constraint."""
        async with db.connection() as conn:
            # Insert first disc
            await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Movie A", "fingerprint_123"),
            )
            await conn.commit()

            # Try to insert duplicate fingerprint
            with pytest.raises(Exception):  # sqlite3.IntegrityError
                await conn.execute(
                    "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                    ("Movie B", "fingerprint_123"),
                )

    @pytest.mark.asyncio
    async def test_can_query_by_fingerprint(self, db):
        """Can query disc by fingerprint."""
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO discs (title, fingerprint, disc_type) VALUES (?, ?, ?)",
                ("My Movie", "fp_abc123", "bluray"),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT * FROM discs WHERE fingerprint = ?",
                ("fp_abc123",),
            )
            row = await cursor.fetchone()

            assert row is not None
            assert row["title"] == "My Movie"
            assert row["disc_type"] == "bluray"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_database.py::TestDiscSchema -v`
Expected: FAIL with "fingerprint" not in column_names

**Step 3: Write minimal implementation**

Update `SCHEMA` in `src/amphigory/database.py`:

```python
SCHEMA = """
-- Processed discs
CREATE TABLE IF NOT EXISTS discs (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    disc_type TEXT,
    disc_release_year INTEGER,
    edition_notes TEXT,
    scan_data TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scanned_at TIMESTAMP,
    notes TEXT
);

-- ... rest of schema unchanged ...
"""
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_database.py::TestDiscSchema -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/database.py tests/test_database.py
git commit -m "feat(webapp): add fingerprint column to discs table"
```

---

## Phase 5: Webapp - Drives API

### Task 7: Create Drives API Router

**Files:**
- Create: `src/amphigory/api/drives.py`
- Test: `tests/test_drives_api.py`

**Step 1: Write the failing test**

```python
# tests/test_drives_api.py
"""Tests for drives API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client():
    """Create test client."""
    from amphigory.main import app
    with TestClient(app) as client:
        yield client


class TestDrivesEndpoints:
    """Tests for /api/drives endpoints."""

    def test_get_drives_returns_empty_list_when_no_daemons(self, client):
        """GET /api/drives returns empty list when no daemons connected."""
        from amphigory.api.settings import _daemons
        _daemons.clear()

        response = client.get("/api/drives")

        assert response.status_code == 200
        assert response.json() == {"drives": []}

    def test_get_drive_by_id_returns_404_when_not_found(self, client):
        """GET /api/drives/{drive_id} returns 404 for unknown drive."""
        response = client.get("/api/drives/unknown:rdisk0")

        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_drives_api.py -v`
Expected: FAIL with 404 (no /api/drives route)

**Step 3: Write minimal implementation**

```python
# src/amphigory/api/drives.py
"""API endpoints for optical drives."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from amphigory.api.settings import _daemons

router = APIRouter(prefix="/api/drives", tags=["drives"])


class DriveResponse(BaseModel):
    """Response model for a drive."""
    drive_id: str
    daemon_id: str
    device: str
    state: str
    disc_volume: Optional[str] = None
    disc_type: Optional[str] = None
    fingerprint: Optional[str] = None
    scan_status: Optional[str] = None
    scan_result: Optional[dict] = None


class DrivesListResponse(BaseModel):
    """Response model for list of drives."""
    drives: list[DriveResponse]


@router.get("", response_model=DrivesListResponse)
async def list_drives():
    """List all connected optical drives."""
    # For now, return empty - will be populated when daemon sends drive info
    drives = []
    return DrivesListResponse(drives=drives)


@router.get("/{drive_id}")
async def get_drive(drive_id: str):
    """Get status of a specific drive."""
    # Will be implemented when we have drive state tracking
    raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")
```

Also add to `src/amphigory/api/__init__.py`:

```python
from amphigory.api.drives import router as drives_router
```

And include in `src/amphigory/main.py`:

```python
from amphigory.api import drives_router
# ...
app.include_router(drives_router)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_drives_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/drives.py src/amphigory/api/__init__.py src/amphigory/main.py tests/test_drives_api.py
git commit -m "feat(webapp): add drives API router"
```

---

## Phase 6: Webapp - Bidirectional WebSocket

### Task 8: Add Request/Response to Webapp WebSocket Handler

**Files:**
- Modify: `src/amphigory/main.py`
- Modify: `src/amphigory/websocket.py`
- Test: `tests/test_main.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_main.py

class TestWebSocketRequests:
    """Tests for webapp sending requests to daemon."""

    @pytest.mark.asyncio
    async def test_webapp_can_send_request_to_daemon(self, client):
        """Webapp can send a request message to daemon via WebSocket."""
        from amphigory.websocket import manager

        # This tests that we have the infrastructure to send requests
        # Actual daemon response handling tested elsewhere
        request = {
            "type": "request",
            "request_id": "test-123",
            "method": "get_drive_status",
            "params": {"drive_id": "test:rdisk0"},
        }

        # Should not raise
        await manager.send_to_daemon("test-daemon", request)
```

Note: This test structure will evolve as we implement the full flow.

**Step 2-5: Implementation details for bidirectional WebSocket**

This task involves:
1. Adding `send_to_daemon()` method to WebSocket manager
2. Tracking which WebSocket connection belongs to which daemon
3. Adding request/response correlation

(Detailed implementation code omitted for brevity - follow TDD pattern)

**Commit:**

```bash
git commit -m "feat(webapp): add bidirectional WebSocket for daemon requests"
```

---

## Phase 7: Integration - Wire Up the Model

### Task 9: Daemon Main - Create and Manage OpticalDrive

**Files:**
- Modify: `daemon/src/amphigory_daemon/main.py`
- Test: `daemon/tests/test_main.py`

This task integrates the OpticalDrive model into the daemon's main loop:
1. Create OpticalDrive instance on startup
2. Update model on disc insert/eject events
3. Generate fingerprint after disc insert
4. Register WebSocket request handlers
5. Push state changes via WebSocket

(Detailed implementation follows TDD pattern)

---

### Task 10: Update Disc Detection to Use Model

**Files:**
- Modify: `daemon/src/amphigory_daemon/main.py`
- Modify: `daemon/src/amphigory_daemon/disc.py`

Wire up disc detection callbacks to update OpticalDrive model.

---

### Task 11: Webapp - Query Daemon for Drive State

**Files:**
- Modify: `src/amphigory/api/drives.py`
- Modify: `src/amphigory/main.py`

Update drives API to query daemon via WebSocket instead of local state.

---

### Task 12: Webapp - Fingerprint Lookup in Database

**Files:**
- Create: `src/amphigory/api/disc_repository.py`
- Test: `tests/test_disc_repository.py`

Create repository for fingerprint-based disc lookup and storage.

---

### Task 13: Update Dashboard and Disc Review Pages

**Files:**
- Modify: `src/amphigory/templates/index.html`
- Modify: `src/amphigory/templates/disc.html`
- Modify: `src/amphigory/api/disc.py`

Update UI to use new drive state model.

---

## Phase 8: Cleanup

### Task 14: Remove Legacy State Management

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Modify: `src/amphigory/api/settings.py`

Remove `_current_scan`, `_daemons` dict, and other legacy state once new model is working.

---

### Task 15: Update Tests and Documentation

**Files:**
- Modify: `tests/*.py`
- Modify: `README.md`
- Modify: `docs/plans/post-launch-followups.md`

Update tests for new architecture, add documentation.

---

## WebSocket Events Reference

**Daemon → Webapp (Events):**
- `disc_inserted` - Disc detected, includes fingerprint
- `disc_ejected` - Disc removed
- `scan_started` - Scan task began
- `scan_progress` - Scan progress update (if available)
- `scan_completed` - Scan finished with results
- `scan_failed` - Scan failed with error
- `rip_started` - Rip task began
- `rip_progress` - Rip progress update
- `rip_completed` - Rip finished
- `rip_failed` - Rip failed
- `drive_state_changed` - Generic state change notification

**Webapp → Daemon (Requests):**
- `get_drive_status` - Request current drive state
- `get_drives` - Request list of all drives

**Request/Response Format:**
```json
// Request
{
  "type": "request",
  "request_id": "uuid",
  "method": "get_drive_status",
  "params": {"drive_id": "daemon:device"}
}

// Response
{
  "type": "response",
  "request_id": "uuid",
  "result": {...}
}

// Error Response
{
  "type": "response",
  "request_id": "uuid",
  "error": {"code": "...", "message": "..."}
}
```
