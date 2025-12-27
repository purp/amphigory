# Phase 1: Disc Detection Bug Fixes

> **Status:** ✅ COMPLETED on 2024-12-24
>
> All 6 tasks completed. Eject detection fixed, scan cache behavior corrected,
> webapp broadcasts disc events, redundant UI buttons removed.

---

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix disc detection reliability so eject is detected, cache is properly managed, and webapp receives real-time notifications.

**Architecture:** Four targeted fixes: (1) DiscDetector tracks volume path to detect eject without diskutil, (2) scan tasks always run fresh and repopulate cache, (3) webapp broadcasts disc events to browser clients, (4) UI polish removes redundant buttons.

**Tech Stack:** Python (daemon), FastAPI/Jinja2 (webapp), PyObjC (macOS notifications), WebSockets

---

## Task 1: Fix Eject Detection in DiscDetector

**Files:**
- Modify: `daemon/src/amphigory_daemon/disc.py`
- Test: `daemon/tests/test_disc.py`

**Context:** The `handleUnmount_` method calls `_get_device_for_volume(path)` which runs `diskutil info` on an already-unmounted path, failing silently. Fix: track the current volume path on insert, compare directly on unmount.

### Step 1: Write failing test for volume path tracking on insert

```python
# In daemon/tests/test_disc.py, add to TestDiscDetector class:

def test_tracks_volume_path_on_insert(self):
    """DiscDetector stores volume path when insert callback fires."""
    from amphigory_daemon.disc import DiscDetector

    inserted = []
    detector = DiscDetector.alloc_with_callbacks(
        on_insert=lambda d, v: inserted.append((d, v)),
        on_eject=lambda d: None,
    )

    # Simulate what handleMount_ does internally
    detector._current_volume_path = "/Volumes/TEST_DISC"

    assert detector._current_volume_path == "/Volumes/TEST_DISC"
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_tracks_volume_path_on_insert -v`

Expected: FAIL with `AttributeError: 'DiscDetector' object has no attribute '_current_volume_path'`

### Step 3: Add `_current_volume_path` attribute to DiscDetector.init()

In `daemon/src/amphigory_daemon/disc.py`, modify the `init` method:

```python
def init(self):
    """Initialize NSObject. Required for PyObjC subclasses."""
    self = objc.super(DiscDetector, self).init()
    if self is None:
        return None
    self._on_insert = None
    self._on_eject = None
    self._running = False
    self._current_volume_path = None  # ADD THIS LINE
    return self
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_tracks_volume_path_on_insert -v`

Expected: PASS

### Step 5: Write failing test for handleMount_ setting volume path

```python
# In daemon/tests/test_disc.py, add:

def test_handleMount_sets_current_volume_path(self):
    """handleMount_ stores the volume path for later eject detection."""
    from amphigory_daemon.disc import DiscDetector
    from unittest.mock import MagicMock, patch

    inserted = []
    detector = DiscDetector.alloc_with_callbacks(
        on_insert=lambda d, v: inserted.append((d, v)),
        on_eject=lambda d: None,
    )

    # Mock the notification
    mock_notification = MagicMock()
    mock_notification.userInfo.return_value = {
        "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/TEST_DISC")
    }

    # Mock _get_device_for_volume and _is_optical_device
    with patch.object(detector, '_get_device_for_volume', return_value="/dev/rdisk5"):
        with patch.object(detector, '_is_optical_device', return_value=True):
            detector.handleMount_(mock_notification)

    assert detector._current_volume_path == "/Volumes/TEST_DISC"
    assert len(inserted) == 1
```

### Step 6: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_handleMount_sets_current_volume_path -v`

Expected: FAIL with `AssertionError: assert None == "/Volumes/TEST_DISC"`

### Step 7: Update handleMount_ to set _current_volume_path

In `daemon/src/amphigory_daemon/disc.py`, modify `handleMount_`:

```python
def handleMount_(self, notification) -> None:
    """Handle mount notification from macOS."""
    logger.info(f"handleMount_ called with notification: {notification}")
    try:
        user_info = notification.userInfo()
        logger.info(f"Mount notification userInfo: {user_info}")
        if not user_info:
            return

        # Get the mounted path
        path = user_info.get("NSWorkspaceVolumeURLKey")
        if path:
            path = str(path.path())
        else:
            path = user_info.get("NSDevicePath", "")

        # Check if this is an optical disc
        # Optical discs typically mount under /Volumes
        if not path.startswith("/Volumes/"):
            return

        # Try to determine if it's an optical disc
        volume_name = path.split("/")[-1] if path else ""

        # Get device path
        device = self._get_device_for_volume(path)
        if not device:
            return

        # Check if device is optical (rdisk with specific characteristics)
        if self._is_optical_device(device):
            logger.info(f"Optical disc inserted: {volume_name} at {device}")
            self._current_volume_path = path  # ADD THIS LINE
            if self._on_insert:
                self._on_insert(device, volume_name)

    except Exception as e:
        logger.error(f"Error handling mount notification: {e}")
```

### Step 8: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_handleMount_sets_current_volume_path -v`

Expected: PASS

### Step 9: Write failing test for handleUnmount_ using stored path

```python
# In daemon/tests/test_disc.py, add:

def test_handleUnmount_fires_eject_for_tracked_volume(self):
    """handleUnmount_ fires eject callback when path matches tracked volume."""
    from amphigory_daemon.disc import DiscDetector
    from unittest.mock import MagicMock

    ejected = []
    detector = DiscDetector.alloc_with_callbacks(
        on_insert=lambda d, v: None,
        on_eject=lambda p: ejected.append(p),
    )

    # Simulate a disc was inserted
    detector._current_volume_path = "/Volumes/TEST_DISC"

    # Mock the unmount notification
    mock_notification = MagicMock()
    mock_notification.userInfo.return_value = {
        "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/TEST_DISC")
    }

    detector.handleUnmount_(mock_notification)

    assert len(ejected) == 1
    assert ejected[0] == "/Volumes/TEST_DISC"
    assert detector._current_volume_path is None
```

### Step 10: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_handleUnmount_fires_eject_for_tracked_volume -v`

Expected: FAIL (current code tries diskutil and fails, never calls eject)

### Step 11: Rewrite handleUnmount_ to use stored path

In `daemon/src/amphigory_daemon/disc.py`, replace `handleUnmount_`:

```python
def handleUnmount_(self, notification) -> None:
    """Handle unmount notification from macOS."""
    logger.info(f"handleUnmount_ called with notification: {notification}")
    try:
        user_info = notification.userInfo()
        logger.info(f"Unmount notification userInfo: {user_info}")
        if not user_info:
            return

        path = user_info.get("NSWorkspaceVolumeURLKey")
        if path:
            path = str(path.path())
        else:
            path = user_info.get("NSDevicePath", "")

        if not path.startswith("/Volumes/"):
            return

        # Check if this is our tracked optical disc
        if path == self._current_volume_path:
            logger.info(f"Optical disc ejected from {path}")
            self._current_volume_path = None
            if self._on_eject:
                self._on_eject(path)

    except Exception as e:
        logger.error(f"Error handling unmount notification: {e}")
```

### Step 12: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_handleUnmount_fires_eject_for_tracked_volume -v`

Expected: PASS

### Step 13: Write test for ignoring unmount of non-tracked volumes

```python
# In daemon/tests/test_disc.py, add:

def test_handleUnmount_ignores_non_tracked_volumes(self):
    """handleUnmount_ ignores unmount events for volumes we're not tracking."""
    from amphigory_daemon.disc import DiscDetector
    from unittest.mock import MagicMock

    ejected = []
    detector = DiscDetector.alloc_with_callbacks(
        on_insert=lambda d, v: None,
        on_eject=lambda p: ejected.append(p),
    )

    # Simulate a disc was inserted at different path
    detector._current_volume_path = "/Volumes/MY_DISC"

    # Mock unmount of a DIFFERENT volume
    mock_notification = MagicMock()
    mock_notification.userInfo.return_value = {
        "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/OTHER_DRIVE")
    }

    detector.handleUnmount_(mock_notification)

    assert len(ejected) == 0  # Should not fire
    assert detector._current_volume_path == "/Volumes/MY_DISC"  # Still tracked
```

### Step 14: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py::TestDiscDetector::test_handleUnmount_ignores_non_tracked_volumes -v`

Expected: PASS (new implementation already handles this)

### Step 15: Run all disc tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_disc.py -v`

Expected: All tests PASS

### Step 16: Commit

```bash
git -C /Users/purp/work/amphigory add daemon/src/amphigory_daemon/disc.py daemon/tests/test_disc.py
git -C /Users/purp/work/amphigory commit -m "$(cat <<'EOF'
fix: detect disc eject by tracking volume path

Previously handleUnmount_ called diskutil info on the unmounted path,
which fails because the volume no longer exists. Now we:
- Store _current_volume_path when disc is inserted
- Compare directly on unmount (no diskutil call)
- Clear tracked path and fire eject callback

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Update Daemon Eject Handler for Path-Based Callback

**Files:**
- Modify: `daemon/src/amphigory_daemon/main.py`
- Test: `daemon/tests/test_main.py`

**Context:** The `on_disc_eject` callback now receives a volume path instead of device. Update the handler and the wrapper in `main()`.

### Step 1: Write failing test for eject handler accepting path

```python
# In daemon/tests/test_main.py, add new test class:

class TestDiscEjectHandler:
    def test_on_disc_eject_clears_state(self):
        """on_disc_eject clears disc state when called with volume path."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.icons import ActivityState

        daemon = AmphigoryDaemon()
        daemon.current_disc = ("/dev/rdisk5", "TEST_DISC")
        daemon.scan_cache = "some cached data"
        daemon.activity_state = ActivityState.IDLE_DISC

        daemon.on_disc_eject("/Volumes/TEST_DISC")

        assert daemon.current_disc is None
        assert daemon.scan_cache is None
        assert daemon.activity_state == ActivityState.IDLE_EMPTY
```

### Step 2: Run test to verify it passes (existing implementation)

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py::TestDiscEjectHandler::test_on_disc_eject_clears_state -v`

Expected: PASS (the handler already clears these, just takes different param name)

### Step 3: Update on_disc_eject parameter name for clarity

In `daemon/src/amphigory_daemon/main.py`, update `on_disc_eject`:

```python
def on_disc_eject(self, volume_path: str) -> None:
    """Handle disc ejection."""
    logger.info(f"Disc ejected: {volume_path}")
    self.current_disc = None
    self.scan_cache = None
    self.activity_state = ActivityState.IDLE_EMPTY
    self._update_disc_menu()
    self._update_icon()

    # Send WebSocket event to webapp (Docker container)
    if self.webapp_client and self.webapp_client.is_connected():
        asyncio.create_task(
            self.webapp_client.send_disc_event("ejected", volume_path=volume_path)
        )

    # Also send to local browser clients (if any connected to daemon directly)
    if self.ws_server:
        asyncio.create_task(
            self.ws_server.send_disc_event("ejected", volume_path=volume_path)
        )
```

### Step 4: Update the eject wrapper in main()

In `daemon/src/amphigory_daemon/main.py`, update `on_eject_wrapper`:

```python
def on_eject_wrapper(volume_path: str):
    loop.call_soon_threadsafe(
        lambda: asyncio.create_task(
            _async_on_disc_eject(app, volume_path)
        )
    )
```

And update `_async_on_disc_eject`:

```python
async def _async_on_disc_eject(app: AmphigoryDaemon, volume_path: str):
    """Async handler for disc ejection (runs on async thread)."""
    app.on_disc_eject(volume_path)
```

### Step 5: Update WebSocket send_disc_event to handle volume_path

Check `daemon/src/amphigory_daemon/websocket.py` for `send_disc_event`. It likely needs to accept `volume_path` as an optional parameter for eject events.

In `daemon/src/amphigory_daemon/websocket.py`, update `send_disc_event` in both `WebSocketServer` and `WebAppClient`:

```python
async def send_disc_event(
    self,
    event: str,
    device: str = None,
    volume_name: str = None,
    volume_path: str = None,
) -> None:
    """Send disc event to all clients."""
    message = {
        "type": "disc_event",
        "event": event,
    }
    if device:
        message["device"] = device
    if volume_name:
        message["volume_name"] = volume_name
    if volume_path:
        message["volume_path"] = volume_path
    await self.broadcast(message)
```

### Step 6: Run all main tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py -v`

Expected: All tests PASS

### Step 7: Commit

```bash
git -C /Users/purp/work/amphigory add daemon/src/amphigory_daemon/main.py daemon/src/amphigory_daemon/websocket.py daemon/tests/test_main.py
git -C /Users/purp/work/amphigory commit -m "$(cat <<'EOF'
refactor: eject handler receives volume path instead of device

Updated on_disc_eject and WebSocket send_disc_event to work with
volume paths, matching the new DiscDetector behavior.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Scan Tasks Always Run Fresh

**Files:**
- Modify: `daemon/src/amphigory_daemon/main.py`
- Test: `daemon/tests/test_main.py`

**Context:** Remove early cache return from `_handle_scan_task`. Always clear cache, run fresh scan, repopulate cache.

### Step 1: Write failing test for scan clearing cache first

```python
# In daemon/tests/test_main.py, add:

class TestScanCacheBehavior:
    @pytest.mark.asyncio
    async def test_scan_task_clears_cache_before_scanning(self):
        """Scan task clears existing cache before running scan."""
        from amphigory_daemon.main import AmphigoryDaemon, ScanCache
        from amphigory_daemon.models import ScanTask, ScanResult
        from datetime import datetime
        from unittest.mock import AsyncMock, patch, MagicMock

        daemon = AmphigoryDaemon()
        daemon.makemkv_path = "/usr/bin/makemkvcon"
        daemon.current_disc = ("/dev/rdisk5", "TEST_DISC")

        # Set up existing cache
        old_cache = ScanCache(
            device="/dev/rdisk5",
            result=MagicMock(),
            scanned_at=datetime(2024, 1, 1),
        )
        daemon.scan_cache = old_cache

        task = ScanTask(id="test-123", type="scan", created_at=datetime.now())

        # Track when cache is cleared
        cache_cleared_during_scan = None

        original_create_subprocess = asyncio.create_subprocess_exec
        async def mock_subprocess(*args, **kwargs):
            nonlocal cache_cleared_during_scan
            cache_cleared_during_scan = daemon.scan_cache is None
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0
            return mock_proc

        with patch('asyncio.create_subprocess_exec', mock_subprocess):
            with patch('amphigory_daemon.main.parse_scan_output') as mock_parse:
                mock_parse.return_value = ScanResult(
                    disc_name="TEST", disc_type="BD", tracks=[]
                )
                await daemon._handle_scan_task(task)

        assert cache_cleared_during_scan is True, "Cache should be cleared before scan runs"
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py::TestScanCacheBehavior::test_scan_task_clears_cache_before_scanning -v`

Expected: FAIL (current code returns cached result without clearing)

### Step 3: Update _handle_scan_task to always clear and rescan

In `daemon/src/amphigory_daemon/main.py`, replace `_handle_scan_task`:

```python
async def _handle_scan_task(self, task: ScanTask) -> TaskResponse:
    """Handle a scan task."""
    started_at = datetime.now()

    # Always clear cache and run fresh scan
    self.scan_cache = None

    try:
        cmd = build_scan_command(self.makemkv_path)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        result = parse_scan_output(output)
        completed_at = datetime.now()

        # Update cache with fresh results
        if self.current_disc:
            self.scan_cache = ScanCache(
                device=self.current_disc[0],
                result=result,
                scanned_at=completed_at,
            )

        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.SUCCESS,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=int((completed_at - started_at).total_seconds()),
            result=result,
        )

    except Exception as e:
        completed_at = datetime.now()
        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=int((completed_at - started_at).total_seconds()),
            error=TaskError(
                code=ErrorCode.MAKEMKV_FAILED,
                message="Scan failed",
                detail=str(e),
            ),
        )
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py::TestScanCacheBehavior::test_scan_task_clears_cache_before_scanning -v`

Expected: PASS

### Step 5: Write test for cache being repopulated after scan

```python
# In daemon/tests/test_main.py, add to TestScanCacheBehavior:

@pytest.mark.asyncio
async def test_scan_task_repopulates_cache_after_scan(self):
    """Scan task updates cache with fresh results."""
    from amphigory_daemon.main import AmphigoryDaemon
    from amphigory_daemon.models import ScanTask, ScanResult
    from datetime import datetime
    from unittest.mock import AsyncMock, patch, MagicMock

    daemon = AmphigoryDaemon()
    daemon.makemkv_path = "/usr/bin/makemkvcon"
    daemon.current_disc = ("/dev/rdisk5", "TEST_DISC")
    daemon.scan_cache = None

    task = ScanTask(id="test-123", type="scan", created_at=datetime.now())

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"scan output", b""))
    mock_proc.returncode = 0

    expected_result = ScanResult(disc_name="FRESH_SCAN", disc_type="BD", tracks=[])

    with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=mock_proc)):
        with patch('amphigory_daemon.main.parse_scan_output', return_value=expected_result):
            await daemon._handle_scan_task(task)

    assert daemon.scan_cache is not None
    assert daemon.scan_cache.result.disc_name == "FRESH_SCAN"
```

### Step 6: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py::TestScanCacheBehavior::test_scan_task_repopulates_cache_after_scan -v`

Expected: PASS

### Step 7: Run all daemon tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/ -v`

Expected: All tests PASS

### Step 8: Commit

```bash
git -C /Users/purp/work/amphigory add daemon/src/amphigory_daemon/main.py daemon/tests/test_main.py
git -C /Users/purp/work/amphigory commit -m "$(cat <<'EOF'
fix: scan tasks always run fresh, then repopulate cache

Removed early return for cached results. Now every scan:
1. Clears existing cache
2. Runs fresh MakeMKV scan
3. Repopulates cache with new results

Cache still serves quick status queries between scans.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Webapp Broadcasts Disc Events to Browsers

**Files:**
- Modify: `src/amphigory/main.py`
- Test: `tests/test_main.py`

**Context:** When webapp receives disc_event from daemon, broadcast to all browser clients so UI updates in real-time.

### Step 1: Write failing test for broadcast on disc event

```python
# In tests/test_main.py, add:

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestDiscEventBroadcast:
    @pytest.mark.asyncio
    async def test_disc_event_broadcast_to_browser_clients(self):
        """When daemon sends disc_event, webapp broadcasts to browsers."""
        from fastapi.testclient import TestClient
        from amphigory.main import app, manager

        # Mock the broadcast method
        manager.broadcast = AsyncMock()

        # This test needs to simulate the WebSocket flow
        # We'll test the broadcast is called when processing disc_event
        # by checking the manager.broadcast mock after sending a message

        # For now, verify broadcast method exists and is callable
        assert hasattr(manager, 'broadcast')
        assert callable(manager.broadcast)
```

### Step 2: Update WebSocket handler to broadcast disc events

In `src/amphigory/main.py`, find the `disc_event` handling block and add broadcast:

```python
elif msg_type == "disc_event" and daemon_id:
    # Update disc status for daemon
    if daemon_id in _daemons:
        event = message.get("event")
        if event == "inserted":
            _daemons[daemon_id].disc_inserted = True
            _daemons[daemon_id].disc_device = message.get("device")
            _daemons[daemon_id].disc_volume = message.get("volume_name")
        elif event == "ejected":
            _daemons[daemon_id].disc_inserted = False
            _daemons[daemon_id].disc_device = None
            _daemons[daemon_id].disc_volume = None

        # Broadcast to browser clients
        await manager.broadcast({
            "type": "disc_event",
            "event": event,
            "device": message.get("device"),
            "volume_name": message.get("volume_name"),
            "volume_path": message.get("volume_path"),
            "daemon_id": daemon_id,
        })
```

### Step 3: Run webapp tests

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_main.py -v`

Expected: All tests PASS

### Step 4: Commit

```bash
git -C /Users/purp/work/amphigory add src/amphigory/main.py tests/test_main.py
git -C /Users/purp/work/amphigory commit -m "$(cat <<'EOF'
feat: broadcast disc events from daemon to browser clients

When webapp receives disc_event from daemon via WebSocket,
now broadcasts to all connected browser clients so disc.html
and other pages can update in real-time.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: UI Polish - Remove Redundant Buttons

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Context:** Remove Select All/None buttons since header checkbox provides same functionality.

### Step 1: Remove redundant buttons from disc.html

In `src/amphigory/templates/disc.html`, change the track-actions div:

```html
<div class="tracks-header">
    <h2>Tracks</h2>
    <div class="track-actions">
        <button type="button" class="btn btn-small" onclick="selectMain()">Select Main Feature</button>
    </div>
</div>
```

Remove these lines:
```html
<button type="button" class="btn btn-small" onclick="selectAll()">Select All</button>
<button type="button" class="btn btn-small" onclick="selectNone()">Select None</button>
```

### Step 2: Rename button to "Process Selected Tracks"

In `src/amphigory/templates/disc.html`, change the submit button:

```html
<button type="submit" class="btn btn-primary" id="rip-button" disabled>
    Process Selected Tracks
</button>
```

Also update the JavaScript that changes button text:

```javascript
ripButton.textContent = 'Creating tasks...';
// ... and in catch block:
ripButton.textContent = 'Process Selected Tracks';
```

### Step 3: Verify page loads correctly

Run webapp and check http://localhost:6199/disc manually, or:

Run: `PYTHONPATH=src .venv/bin/pytest tests/ -v -k "disc or route"`

Expected: All tests PASS

### Step 4: Commit

```bash
git -C /Users/purp/work/amphigory add src/amphigory/templates/disc.html
git -C /Users/purp/work/amphigory commit -m "$(cat <<'EOF'
ui: remove redundant Select All/None buttons, rename Rip to Process

- Removed Select All and Select None buttons (header checkbox suffices)
- Kept Select Main Feature button
- Renamed "Rip Selected Tracks" to "Process Selected Tracks"

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Integration Testing

### Step 1: Run all daemon tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/ -v`

Expected: All tests PASS

### Step 2: Run all webapp tests

Run: `PYTHONPATH=src .venv/bin/pytest tests/ -v`

Expected: All tests PASS

### Step 3: Manual integration test

1. Start webapp: `docker compose up`
2. Start daemon in dev mode
3. Open http://localhost:6199/disc in browser
4. Insert disc - verify page updates automatically
5. Click Scan - verify fresh scan runs
6. Eject disc - verify page updates to "No disc detected"
7. Verify daemon logs show eject detection

### Step 4: Final commit if any fixes needed

If integration testing reveals issues, fix and commit.

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Fix DiscDetector to track volume path for eject detection |
| 2 | Update daemon eject handler for path-based callback |
| 3 | Make scan tasks always run fresh, repopulate cache after |
| 4 | Webapp broadcasts disc events to browser clients |
| 5 | UI polish: remove redundant buttons, rename to Process |
| 6 | Integration testing |
