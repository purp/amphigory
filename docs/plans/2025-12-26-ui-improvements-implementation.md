# UI Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist TMDB/IMDB metadata, fix progress bar, add task timing and completed task details.

**Architecture:** Backend adds one new endpoint for metadata persistence. WebSocket handler relays progress messages. Frontend adds timing display and expandable task details.

**Tech Stack:** FastAPI, aiosqlite, JavaScript, HTML/CSS

---

## Task 1: Add metadata update endpoint

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

Add to `tests/test_disc_api.py`:

```python
class TestDiscMetadata:
    """Tests for POST /api/disc/metadata."""

    @pytest.fixture
    def db_with_disc(self, tmp_path, monkeypatch):
        """Create a test database with a disc."""
        import asyncio
        from amphigory.database import Database
        from amphigory.api import disc_repository

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        asyncio.get_event_loop().run_until_complete(db.initialize())
        monkeypatch.setattr(disc_repository, "get_db_path", lambda: db_path)

        # Create a disc with fingerprint
        async def create_disc():
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (fingerprint, title) VALUES (?, ?)",
                    ("abc123fingerprint", "Unknown Disc")
                )
                await conn.commit()
        asyncio.get_event_loop().run_until_complete(create_disc())

        return db_path

    def test_updates_disc_metadata(self, client, db_with_disc):
        """POST /api/disc/metadata updates disc record."""
        response = client.post("/api/disc/metadata", json={
            "fingerprint": "abc123fingerprint",
            "tmdb_id": "129",
            "imdb_id": "tt0347149",
            "title": "Howl's Moving Castle",
            "year": 2004
        })

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] is True

    def test_metadata_persists_in_database(self, client, db_with_disc):
        """Metadata is stored in discs table."""
        import asyncio
        import aiosqlite

        client.post("/api/disc/metadata", json={
            "fingerprint": "abc123fingerprint",
            "tmdb_id": "129",
            "imdb_id": "tt0347149",
            "title": "Howl's Moving Castle",
            "year": 2004
        })

        async def check_db():
            async with aiosqlite.connect(db_with_disc) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT tmdb_id, imdb_id, title, year FROM discs WHERE fingerprint = ?",
                    ("abc123fingerprint",)
                )
                row = await cursor.fetchone()
                return dict(row)

        result = asyncio.get_event_loop().run_until_complete(check_db())
        assert result["tmdb_id"] == "129"
        assert result["imdb_id"] == "tt0347149"
        assert result["title"] == "Howl's Moving Castle"
        assert result["year"] == 2004

    def test_returns_404_for_unknown_fingerprint(self, client, db_with_disc):
        """Returns 404 if fingerprint not found."""
        response = client.post("/api/disc/metadata", json={
            "fingerprint": "unknown_fingerprint",
            "tmdb_id": "129",
            "title": "Test",
            "year": 2024
        })

        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestDiscMetadata -v`
Expected: FAIL with "404" or missing endpoint

**Step 3: Write minimal implementation**

Add to `src/amphigory/api/disc.py`:

```python
from pydantic import BaseModel
from typing import Optional

class UpdateMetadataRequest(BaseModel):
    fingerprint: str
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None


@router.post("/metadata")
async def update_disc_metadata(request: UpdateMetadataRequest):
    """Update disc metadata by fingerprint."""
    from amphigory.api.disc_repository import get_db_path
    import aiosqlite

    async with aiosqlite.connect(get_db_path()) as db:
        # Check disc exists
        cursor = await db.execute(
            "SELECT id FROM discs WHERE fingerprint = ?",
            (request.fingerprint,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update metadata
        await db.execute(
            """UPDATE discs
               SET tmdb_id = ?, imdb_id = ?, title = ?, year = ?
               WHERE fingerprint = ?""",
            (request.tmdb_id, request.imdb_id, request.title, request.year, request.fingerprint)
        )
        await db.commit()

    return {"updated": True}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestDiscMetadata -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: add POST /api/disc/metadata endpoint"
```

---

## Task 2: Add "Save Disc Info" button

**Files:**
- Modify: `src/amphigory/templates/disc.html`
- Modify: `src/amphigory/static/style.css`

**Step 1: Add button HTML**

In `src/amphigory/templates/disc.html`, find the disc info section (around line 20-40) and add the save button after the year input:

```html
<button type="button" class="btn btn-secondary" id="save-disc-info-btn" onclick="saveDiscInfo()" disabled>
    Save Disc Info
</button>
```

**Step 2: Add JavaScript function**

Add to the `<script>` section in `disc.html`:

```javascript
async function saveDiscInfo() {
    const fingerprint = scanResult?.fingerprint;
    if (!fingerprint) {
        alert('No disc fingerprint available');
        return;
    }

    const title = document.getElementById('movie-title').value.trim();
    const year = document.getElementById('movie-year').value.trim();

    if (!title || !year) {
        alert('Please enter title and year');
        return;
    }

    try {
        const response = await fetch('/api/disc/metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                fingerprint: fingerprint,
                tmdb_id: window.selectedTMDBId || null,
                imdb_id: window.selectedIMDBId || null,
                title: title,
                year: parseInt(year)
            })
        });

        if (response.ok) {
            // Visual feedback
            const btn = document.getElementById('save-disc-info-btn');
            btn.textContent = 'Saved!';
            btn.disabled = true;
            setTimeout(() => {
                btn.textContent = 'Save Disc Info';
                btn.disabled = false;
            }, 2000);
        } else {
            const error = await response.json();
            alert('Failed to save: ' + (error.detail || 'Unknown error'));
        }
    } catch (error) {
        alert('Failed to save: ' + error.message);
    }
}

// Enable save button when TMDB result is selected
function enableSaveButton() {
    const btn = document.getElementById('save-disc-info-btn');
    if (btn) btn.disabled = false;
}
```

**Step 3: Enable button when TMDB selected**

In `selectTMDBResult()` function, add call to enable button (after setting window.selectedTMDBId):

```javascript
enableSaveButton();
```

**Step 4: Manual test**

1. Start webapp: `PYTHONPATH=src uvicorn amphigory.main:app --reload`
2. Navigate to /disc with a scanned disc
3. Search TMDB and select a result
4. Verify "Save Disc Info" button is enabled
5. Click it and verify success feedback

**Step 5: Commit**

```bash
git add src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "feat: add Save Disc Info button to disc review page"
```

---

## Task 3: Save metadata on "Process Selected Tracks"

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Update processSelectedTracks function**

Find `processSelectedTracks()` in `disc.html` and add metadata save at the start:

```javascript
async function processSelectedTracks() {
    // Save disc metadata first (if we have TMDB/IMDB data)
    const fingerprint = scanResult?.fingerprint;
    const title = document.getElementById('movie-title').value.trim();
    const year = document.getElementById('movie-year').value.trim();

    if (fingerprint && title && year && (window.selectedTMDBId || window.selectedIMDBId)) {
        try {
            await fetch('/api/disc/metadata', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fingerprint: fingerprint,
                    tmdb_id: window.selectedTMDBId || null,
                    imdb_id: window.selectedIMDBId || null,
                    title: title,
                    year: parseInt(year)
                })
            });
        } catch (error) {
            console.error('Failed to save metadata:', error);
            // Continue with processing even if metadata save fails
        }
    }

    // ... rest of existing processSelectedTracks code
```

**Step 2: Manual test**

1. On /disc page with scanned disc
2. Search TMDB and select result
3. Select some tracks
4. Click "Process Selected Tracks"
5. Check database: `sqlite3 data/amphigory.db "SELECT tmdb_id, imdb_id, title FROM discs"`

**Step 3: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: save disc metadata when processing tracks"
```

---

## Task 4: Pre-populate metadata on page load

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Modify: `src/amphigory/templates/disc.html`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

Add to `tests/test_disc_api.py`:

```python
class TestGetDiscMetadata:
    """Tests for GET /api/disc/metadata/{fingerprint}."""

    def test_returns_metadata_for_known_disc(self, client, db_with_disc):
        """Returns stored metadata for disc."""
        import asyncio
        import aiosqlite

        # First store some metadata
        async def store_metadata():
            async with aiosqlite.connect(db_with_disc) as conn:
                await conn.execute(
                    """UPDATE discs SET tmdb_id = ?, imdb_id = ?, title = ?, year = ?
                       WHERE fingerprint = ?""",
                    ("129", "tt0347149", "Howl's Moving Castle", 2004, "abc123fingerprint")
                )
                await conn.commit()
        asyncio.get_event_loop().run_until_complete(store_metadata())

        response = client.get("/api/disc/metadata/abc123fingerprint")

        assert response.status_code == 200
        data = response.json()
        assert data["tmdb_id"] == "129"
        assert data["imdb_id"] == "tt0347149"
        assert data["title"] == "Howl's Moving Castle"
        assert data["year"] == 2004

    def test_returns_404_for_unknown_fingerprint(self, client, db_with_disc):
        """Returns 404 for unknown fingerprint."""
        response = client.get("/api/disc/metadata/unknown_fp")
        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestGetDiscMetadata -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `src/amphigory/api/disc.py`:

```python
@router.get("/metadata/{fingerprint}")
async def get_disc_metadata(fingerprint: str):
    """Get disc metadata by fingerprint."""
    from amphigory.api.disc_repository import get_db_path
    import aiosqlite

    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT tmdb_id, imdb_id, title, year FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Disc not found")

        return {
            "tmdb_id": row["tmdb_id"],
            "imdb_id": row["imdb_id"],
            "title": row["title"],
            "year": row["year"]
        }
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestGetDiscMetadata -v`
Expected: PASS

**Step 5: Add frontend pre-population**

In `disc.html`, update `displayScanResult()` to fetch and apply saved metadata:

```javascript
async function displayScanResult(result) {
    scanResult = result;

    // Check for saved metadata
    if (result.fingerprint) {
        try {
            const metaResponse = await fetch(`/api/disc/metadata/${result.fingerprint}`);
            if (metaResponse.ok) {
                const metadata = await metaResponse.json();
                if (metadata.title) {
                    document.getElementById('movie-title').value = metadata.title;
                }
                if (metadata.year) {
                    document.getElementById('movie-year').value = metadata.year;
                }
                if (metadata.tmdb_id) {
                    window.selectedTMDBId = metadata.tmdb_id;
                }
                if (metadata.imdb_id) {
                    window.selectedIMDBId = metadata.imdb_id;
                    // Show metadata links
                    showMetadataLinks(metadata.title, metadata.tmdb_id, metadata.imdb_id);
                }
            }
        } catch (error) {
            console.log('No saved metadata for disc');
        }
    }

    // ... rest of existing displayScanResult code
}

function showMetadataLinks(title, tmdbId, imdbId) {
    const metadataLinksDiv = document.getElementById('metadata-links');
    if (!metadataLinksDiv) return;

    metadataLinksDiv.innerHTML = '';

    if (tmdbId) {
        const tmdbLink = document.createElement('a');
        tmdbLink.href = `https://www.themoviedb.org/movie/${tmdbId}`;
        tmdbLink.target = '_blank';
        tmdbLink.textContent = title || 'TMDB';
        tmdbLink.style.marginRight = '0.5rem';
        metadataLinksDiv.appendChild(tmdbLink);
    }

    if (imdbId) {
        const imdbLink = document.createElement('a');
        imdbLink.href = `https://www.imdb.com/title/${imdbId}`;
        imdbLink.target = '_blank';
        imdbLink.textContent = 'IMDB';
        metadataLinksDiv.appendChild(imdbLink);
    }
}
```

**Step 6: Commit**

```bash
git add src/amphigory/api/disc.py src/amphigory/templates/disc.html tests/test_disc_api.py
git commit -m "feat: pre-populate disc metadata from database on page load"
```

---

## Task 5: Relay progress messages in webapp WebSocket

**Files:**
- Modify: `src/amphigory/main.py`
- Test: `tests/test_main.py`

**Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
class TestProgressRelay:
    """Tests for progress message relay."""

    @pytest.mark.asyncio
    async def test_progress_message_broadcast_to_clients(self):
        """Progress messages from daemon are broadcast to browser clients."""
        from fastapi.testclient import TestClient
        from amphigory.main import app

        with TestClient(app) as client:
            # Connect as browser client
            with client.websocket_connect("/ws") as browser_ws:
                # Connect as daemon
                with client.websocket_connect("/ws") as daemon_ws:
                    # Register daemon
                    daemon_ws.send_json({
                        "type": "daemon_config",
                        "daemon_id": "test-daemon",
                        "makemkvcon_path": "/usr/bin/makemkvcon"
                    })

                    # Send progress from daemon
                    daemon_ws.send_json({
                        "type": "progress",
                        "task_id": "test-task-123",
                        "percent": 45,
                        "eta_seconds": 120
                    })

                    # Browser should receive progress
                    # Note: May need to skip daemon_config broadcast first
                    msg = browser_ws.receive_json(timeout=1)
                    # Skip if it's the daemon_config broadcast
                    if msg.get("type") == "daemon_config":
                        msg = browser_ws.receive_json(timeout=1)

                    assert msg["type"] == "progress"
                    assert msg["task_id"] == "test-task-123"
                    assert msg["percent"] == 45
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_main.py::TestProgressRelay -v`
Expected: FAIL (timeout or wrong message type)

**Step 3: Write minimal implementation**

In `src/amphigory/main.py`, find the WebSocket message handler (around line 287-295) and add progress handling:

```python
                elif msg_type == "progress" and daemon_id:
                    # Relay progress to browser clients
                    await manager.broadcast({
                        "type": "progress",
                        "task_id": message.get("task_id"),
                        "percent": message.get("percent"),
                        "eta_seconds": message.get("eta_seconds"),
                        "current_size_bytes": message.get("current_size_bytes"),
                        "speed": message.get("speed"),
                    })
```

Add this after the `elif msg_type == "heartbeat"` block.

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_main.py::TestProgressRelay -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/main.py tests/test_main.py
git commit -m "feat: relay progress messages from daemon to browser clients"
```

---

## Task 6: Add timing to current task display

**Files:**
- Modify: `src/amphigory/templates/queue.html`
- Modify: `src/amphigory/static/style.css`

**Step 1: Update renderCurrentTask function**

In `queue.html`, replace the `renderCurrentTask()` function:

```javascript
function formatTime(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatElapsed(startDateStr) {
    const start = new Date(startDateStr);
    const now = new Date();
    const seconds = Math.floor((now - start) / 1000);

    if (seconds < 60) return `${seconds}s`;

    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;

    if (minutes < 60) return `${minutes}m ${secs}s`;

    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m ${secs}s`;
}

let elapsedInterval = null;

function renderCurrentTask() {
    const container = document.getElementById('current-task');

    // Clear any existing interval
    if (elapsedInterval) {
        clearInterval(elapsedInterval);
        elapsedInterval = null;
    }

    if (tasks.in_progress.length === 0) {
        container.innerHTML = '<p class="text-muted">No task currently running</p>';
        return;
    }

    const task = tasks.in_progress[0];
    const startedAt = task.started_at;

    container.innerHTML = `
        <div class="task-item task-running">
            <div class="task-header">
                <span class="task-type">${task.type}</span>
                <span class="task-id" title="${task.id}">${task.id.substring(0, 12)}...</span>
            </div>
            <div class="task-timing">
                Started: ${startedAt ? formatTime(startedAt) : 'Unknown'} ·
                Elapsed: <span id="elapsed-time">${startedAt ? formatElapsed(startedAt) : '--'}</span>
            </div>
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-bar-fill" id="progress-${task.id}" style="width: 0%"></div>
                </div>
                <span class="progress-text" id="progress-text-${task.id}">Processing...</span>
            </div>
        </div>
    `;

    // Update elapsed time every second
    if (startedAt) {
        elapsedInterval = setInterval(() => {
            const elapsedEl = document.getElementById('elapsed-time');
            if (elapsedEl) {
                elapsedEl.textContent = formatElapsed(startedAt);
            }
        }, 1000);
    }
}
```

**Step 2: Add CSS for timing**

Add to `src/amphigory/static/style.css`:

```css
.task-timing {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: 0.25rem 0 0.5rem 0;
}

.task-id {
    cursor: help;
}
```

**Step 3: Ensure started_at is returned by API**

Check that `/api/tasks` returns `started_at` for in_progress tasks. The task file in `in_progress/` should have this field set by the daemon.

**Step 4: Manual test**

1. Start a rip task
2. Navigate to /queue
3. Verify start time and elapsed time appear
4. Verify elapsed updates every second
5. Hover over task ID to see full ID

**Step 5: Commit**

```bash
git add src/amphigory/templates/queue.html src/amphigory/static/style.css
git commit -m "feat: add start time and elapsed time to current task"
```

---

## Task 7: Add expandable completed task details

**Files:**
- Modify: `src/amphigory/templates/queue.html`
- Modify: `src/amphigory/static/style.css`

**Step 1: Update renderCompletedTasks function**

Replace in `queue.html`:

```javascript
function formatDuration(seconds) {
    if (!seconds) return '--';

    if (seconds < 60) return `${seconds}s`;

    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;

    if (minutes < 60) return `${minutes}m ${secs}s`;

    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m ${secs}s`;
}

function formatDateTime(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    return date.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

function renderCompletedTasks() {
    const container = document.getElementById('completed-tasks');

    if (tasks.completed.length === 0) {
        container.innerHTML = '<p class="text-muted">No completed tasks</p>';
        return;
    }

    // Show most recent first, limit to 10
    const recentTasks = tasks.completed.slice(0, 10);

    container.innerHTML = recentTasks.map(task => `
        <div class="task-item task-${task.status}" onclick="toggleTaskDetails('${task.id}')">
            <div class="task-header">
                <span class="task-status status-${task.status}">${task.status}</span>
                <span class="task-type">${task.type || 'task'}</span>
                <span class="task-id" title="${task.id}">${task.id.substring(0, 12)}...</span>
                <span class="task-expand">▼</span>
            </div>
            <div class="task-details" id="details-${task.id}" style="display: none;">
                <div class="detail-row"><span class="detail-label">Task ID:</span> ${task.id}</div>
                <div class="detail-row"><span class="detail-label">Started:</span> ${formatDateTime(task.started_at)}</div>
                <div class="detail-row"><span class="detail-label">Completed:</span> ${formatDateTime(task.completed_at)}</div>
                <div class="detail-row"><span class="detail-label">Duration:</span> ${formatDuration(task.duration_seconds)}</div>
                ${task.result?.destination ? `
                    <div class="detail-row"><span class="detail-label">Output Dir:</span> ${task.result.destination.directory || '--'}</div>
                    <div class="detail-row"><span class="detail-label">Output File:</span> ${task.result.destination.filename || '--'}</div>
                ` : ''}
                ${task.error ? `
                    <div class="detail-row detail-error"><span class="detail-label">Error:</span> ${task.error.detail || task.error.message || 'Unknown error'}</div>
                ` : ''}
            </div>
        </div>
    `).join('');
}

function toggleTaskDetails(taskId) {
    const details = document.getElementById(`details-${taskId}`);
    if (details) {
        const isHidden = details.style.display === 'none';
        details.style.display = isHidden ? 'block' : 'none';

        // Toggle arrow
        const parent = details.parentElement;
        const arrow = parent.querySelector('.task-expand');
        if (arrow) {
            arrow.textContent = isHidden ? '▲' : '▼';
        }
    }
}
```

**Step 2: Add CSS for details**

Add to `src/amphigory/static/style.css`:

```css
.task-item {
    cursor: pointer;
}

.task-expand {
    margin-left: auto;
    color: var(--text-muted);
    font-size: 0.75rem;
}

.task-details {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.75rem;
    margin-top: 0.5rem;
    font-size: 0.85rem;
}

.detail-row {
    margin-bottom: 0.25rem;
}

.detail-label {
    color: var(--text-muted);
    min-width: 100px;
    display: inline-block;
}

.detail-error {
    color: var(--danger);
}
```

**Step 3: Ensure API returns full task data**

The `/api/tasks` endpoint needs to return `started_at`, `completed_at`, `duration_seconds`, `result`, and `error` for completed tasks. Check `src/amphigory/api/tasks.py` - the `list_tasks` function should read full task data from complete/ files.

**Step 4: Manual test**

1. Have some completed tasks (or create test files in data/tasks/complete/)
2. Navigate to /queue
3. Click a completed task to expand
4. Verify all fields display correctly
5. Click again to collapse

**Step 5: Commit**

```bash
git add src/amphigory/templates/queue.html src/amphigory/static/style.css
git commit -m "feat: add expandable details for completed tasks"
```

---

## Task 8: Ensure API returns complete task data

**Files:**
- Modify: `src/amphigory/api/tasks.py`
- Test: `tests/test_tasks_api.py`

**Step 1: Write the failing test**

Add to `tests/test_tasks_api.py`:

```python
class TestListTasksFullData:
    """Tests for full task data in list response."""

    def test_completed_task_includes_timing_fields(self, client, tasks_dir):
        """Completed tasks include started_at, completed_at, duration_seconds."""
        # Create a completed task file
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251225T120000.000000-rip",
            "status": "success",
            "started_at": "2025-12-25T12:00:00.000000",
            "completed_at": "2025-12-25T12:45:32.000000",
            "duration_seconds": 2732,
            "result": {
                "destination": {
                    "directory": "/media/ripped",
                    "filename": "Movie.mkv"
                }
            }
        }
        with open(complete_dir / "20251225T120000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        completed = [t for t in data["tasks"] if t["status"] == "success"]
        assert len(completed) >= 1

        task = completed[0]
        assert "started_at" in task
        assert "completed_at" in task
        assert "duration_seconds" in task
        assert task["result"]["destination"]["filename"] == "Movie.mkv"

    def test_failed_task_includes_error(self, client, tasks_dir):
        """Failed tasks include error details."""
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251225T130000.000000-rip",
            "status": "failed",
            "started_at": "2025-12-25T13:00:00.000000",
            "completed_at": "2025-12-25T13:00:01.000000",
            "duration_seconds": 1,
            "error": {
                "code": "IO_ERROR",
                "message": "Read-only file system",
                "detail": "[Errno 30] Read-only file system: '/media'"
            }
        }
        with open(complete_dir / "20251225T130000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks")
        data = response.json()

        failed = [t for t in data["tasks"] if t["status"] == "failed"]
        assert len(failed) >= 1
        assert "error" in failed[0]
        assert failed[0]["error"]["detail"] == "[Errno 30] Read-only file system: '/media'"
```

**Step 2: Run test to verify current behavior**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tasks_api.py::TestListTasksFullData -v`

**Step 3: Update list_tasks if needed**

In `src/amphigory/api/tasks.py`, ensure `list_tasks()` returns full data for completed tasks:

```python
@router.get("", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    """List all tasks across all states."""
    tasks_dir = get_tasks_dir()
    all_tasks = []

    # Helper to read task file
    def read_task(path: Path, status: str) -> dict:
        with open(path) as f:
            data = json.load(f)

        # For completed tasks, return full response data
        if status in ("success", "failed"):
            return {
                "id": data.get("task_id", path.stem),
                "type": data.get("type"),
                "status": data.get("status", status),
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
                "duration_seconds": data.get("duration_seconds"),
                "result": data.get("result"),
                "error": data.get("error"),
            }

        # For queued/in_progress, return basic info
        return {
            "id": data.get("id", path.stem),
            "type": data.get("type"),
            "status": status,
            "started_at": data.get("started_at"),
        }

    # Read from each directory
    for subdir, status in [("queued", "queued"), ("in_progress", "in_progress"), ("complete", None)]:
        dir_path = tasks_dir / subdir
        if dir_path.exists():
            for task_file in dir_path.glob("*.json"):
                try:
                    # For complete/, status comes from file content
                    with open(task_file) as f:
                        file_status = json.load(f).get("status", "success") if status is None else status
                    task = read_task(task_file, file_status if status is None else status)
                    all_tasks.append(task)
                except (json.JSONDecodeError, IOError):
                    continue

    return TaskListResponse(tasks=all_tasks)
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tasks_api.py::TestListTasksFullData -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/tasks.py tests/test_tasks_api.py
git commit -m "feat: return full task data in list endpoint for completed tasks"
```

---

## Final: Run all tests and push

**Step 1: Run full test suite**

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -v
```

Expected: All tests pass

**Step 2: Push all commits**

```bash
git push origin main
```
