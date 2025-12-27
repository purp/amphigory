# Resume Interrupted Flows Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to resume processing of partially-processed discs without re-doing completed steps.

**Architecture:** Detect known discs by fingerprint, show processing state per track with 💿🎬📺 icons, intelligently skip completed steps when resuming.

**Tech Stack:** SQLite, FastAPI, aiosqlite, HTMX, vanilla JavaScript, pytest

---

## Task 1: Add inserted_path Column to Tracks Table

**Files:**
- Modify: `src/amphigory/database.py:160-220` (add migration)
- Test: `tests/test_database.py`

**Step 1: Write the failing test**

```python
# In tests/test_database.py, add to existing test class or create new one:

class TestInsertedPathMigration:
    """Test inserted_path column migration."""

    @pytest.mark.asyncio
    async def test_tracks_table_has_inserted_path_column(self, db):
        """Tracks table should have inserted_path column after migration."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(tracks)")
            columns = {row[1] for row in await cursor.fetchall()}

        assert "inserted_path" in columns
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestInsertedPathMigration -v`
Expected: FAIL with AssertionError (inserted_path not in columns)

**Step 3: Write minimal implementation**

In `src/amphigory/database.py`, add to `_run_migrations` method after the existing tracks column checks:

```python
        # Migration: Add inserted_path column to tracks table
        if "inserted_path" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN inserted_path TEXT")
```

Also add to the SCHEMA tracks table definition (for new databases):
```sql
    inserted_path TEXT,
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestInsertedPathMigration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/database.py tests/test_database.py
git commit -m "feat: add inserted_path column to tracks table"
```

---

## Task 2: Add get_disc_with_tracks Repository Function

**Files:**
- Modify: `src/amphigory/api/disc_repository.py`
- Test: `tests/test_disc_repository.py`

**Step 1: Write the failing test**

```python
class TestGetDiscWithTracks:
    """Tests for get_disc_with_tracks function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disc_not_found(self, db, db_path):
        """Returns None when no disc matches fingerprint."""
        result = await disc_repository.get_disc_with_tracks("nonexistent_fp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_disc_with_tracks(self, db, db_path):
        """Returns disc with its tracks when fingerprint matches."""
        # Insert test disc
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint, year, imdb_id)
                   VALUES (?, ?, ?, ?)""",
                ("Test Movie", "fp_with_tracks", 2020, "tt1234567"),
            )
            disc_id = cursor.lastrowid

            # Insert test tracks
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name,
                   duration_seconds, size_bytes, resolution, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (disc_id, 1, "main_feature", "Test Movie (2020)", 7200, 25000000000, "1920x1080", "discovered"),
            )
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name,
                   duration_seconds, size_bytes, resolution, ripped_path, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (disc_id, 2, "featurettes", "Making Of", 2700, 5000000000, "1920x1080",
                 "/media/ripped/Test Movie/Making Of.mkv", "ripped"),
            )
            await conn.commit()

        result = await disc_repository.get_disc_with_tracks("fp_with_tracks")

        assert result is not None
        assert result["disc"]["title"] == "Test Movie"
        assert result["disc"]["fingerprint"] == "fp_with_tracks"
        assert len(result["tracks"]) == 2
        assert result["tracks"][0]["track_number"] == 1
        assert result["tracks"][0]["status"] == "discovered"
        assert result["tracks"][1]["track_number"] == 2
        assert result["tracks"][1]["ripped_path"] == "/media/ripped/Test Movie/Making Of.mkv"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_repository.py::TestGetDiscWithTracks -v`
Expected: FAIL with AttributeError (get_disc_with_tracks not defined)

**Step 3: Write minimal implementation**

```python
async def get_disc_with_tracks(fingerprint: str) -> Optional[dict]:
    """
    Get a disc and all its tracks by fingerprint.

    Args:
        fingerprint: SHA256 hex string fingerprint of the disc

    Returns:
        Dict with "disc" (disc info) and "tracks" (list of track dicts),
        or None if disc not found.
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        # Get disc
        cursor = await db.execute(
            "SELECT * FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        disc_row = await cursor.fetchone()
        if not disc_row:
            return None

        disc = dict(disc_row)
        disc_id = disc["id"]

        # Get tracks
        cursor = await db.execute(
            "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
            (disc_id,)
        )
        track_rows = await cursor.fetchall()
        tracks = [dict(row) for row in track_rows]

        return {"disc": disc, "tracks": tracks}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_repository.py::TestGetDiscWithTracks -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc_repository.py tests/test_disc_repository.py
git commit -m "feat: add get_disc_with_tracks repository function"
```

---

## Task 3: Add API Endpoint GET /api/disc/by-fingerprint/{fingerprint}

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

```python
class TestGetDiscByFingerprint:
    """Tests for GET /api/disc/by-fingerprint/{fingerprint} endpoint."""

    def test_returns_404_when_disc_not_found(self, client):
        """Returns 404 when fingerprint not in database."""
        response = client.get("/api/disc/by-fingerprint/nonexistent123")
        assert response.status_code == 404

    def test_returns_disc_with_tracks(self, client, db_with_disc_and_tracks):
        """Returns disc info and tracks for known fingerprint."""
        response = client.get("/api/disc/by-fingerprint/test_fingerprint_123")
        assert response.status_code == 200

        data = response.json()
        assert "disc" in data
        assert "tracks" in data
        assert data["disc"]["fingerprint"] == "test_fingerprint_123"
        assert isinstance(data["tracks"], list)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestGetDiscByFingerprint -v`
Expected: FAIL with 404 (endpoint not found)

**Step 3: Write minimal implementation**

```python
@router.get("/by-fingerprint/{fingerprint}")
async def get_disc_by_fingerprint_endpoint(fingerprint: str):
    """Get disc and tracks by fingerprint.

    Returns:
        Dict with "disc" and "tracks" keys.
    """
    result = await disc_repository.get_disc_with_tracks(fingerprint)
    if not result:
        raise HTTPException(status_code=404, detail="Disc not found")

    # Parse scan_data JSON if present
    if result["disc"].get("scan_data"):
        result["disc"]["scan_data"] = json.loads(result["disc"]["scan_data"])

    # Parse audio_tracks and subtitle_tracks JSON for each track
    for track in result["tracks"]:
        if track.get("audio_tracks"):
            track["audio_tracks"] = json.loads(track["audio_tracks"])
        if track.get("subtitle_tracks"):
            track["subtitle_tracks"] = json.loads(track["subtitle_tracks"])

    return result
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestGetDiscByFingerprint -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: add GET /api/disc/by-fingerprint/{fingerprint} endpoint"
```

---

## Task 4: Add API Endpoint POST /api/disc/{disc_id}/save

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

```python
class TestSaveDiscAndTracks:
    """Tests for POST /api/disc/{disc_id}/save endpoint."""

    def test_saves_disc_info(self, client, db_with_disc_and_tracks):
        """Updates disc title, year, imdb_id."""
        response = client.post("/api/disc/1/save", json={
            "disc": {
                "title": "Updated Title",
                "year": 2021,
                "imdb_id": "tt9999999"
            },
            "tracks": []
        })
        assert response.status_code == 200

        # Verify changes persisted
        get_response = client.get("/api/disc/by-fingerprint/test_fingerprint_123")
        data = get_response.json()
        assert data["disc"]["title"] == "Updated Title"
        assert data["disc"]["year"] == 2021
        assert data["disc"]["imdb_id"] == "tt9999999"

    def test_saves_track_info(self, client, db_with_disc_and_tracks):
        """Updates track names, types, presets."""
        response = client.post("/api/disc/1/save", json={
            "disc": {},
            "tracks": [
                {"id": 1, "track_name": "New Name", "track_type": "featurettes", "preset_name": "HQ 1080p"}
            ]
        })
        assert response.status_code == 200

    def test_returns_404_for_unknown_disc(self, client):
        """Returns 404 for non-existent disc_id."""
        response = client.post("/api/disc/99999/save", json={"disc": {}, "tracks": []})
        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestSaveDiscAndTracks -v`
Expected: FAIL with 404 (endpoint not found)

**Step 3: Write minimal implementation**

```python
class SaveDiscRequest(BaseModel):
    """Request body for saving disc and track edits."""
    disc: dict = {}
    tracks: list[dict] = []


@router.post("/{disc_id}/save")
async def save_disc_and_tracks(disc_id: int, request: SaveDiscRequest):
    """Save disc and track edits to database.

    Updates disc info (title, year, imdb_id) and track info
    (track_name, track_type, preset_name) without overwriting paths.
    """
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        # Check disc exists
        cursor = await db.execute("SELECT id FROM discs WHERE id = ?", (disc_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update disc fields if provided
        disc_updates = []
        disc_values = []
        for field in ["title", "year", "imdb_id"]:
            if field in request.disc and request.disc[field] is not None:
                disc_updates.append(f"{field} = ?")
                disc_values.append(request.disc[field])

        if disc_updates:
            disc_values.append(disc_id)
            await db.execute(
                f"UPDATE discs SET {', '.join(disc_updates)} WHERE id = ?",
                disc_values
            )

        # Update tracks
        for track_data in request.tracks:
            track_id = track_data.get("id")
            if not track_id:
                continue

            track_updates = []
            track_values = []
            for field in ["track_name", "track_type", "preset_name"]:
                if field in track_data and track_data[field] is not None:
                    track_updates.append(f"{field} = ?")
                    track_values.append(track_data[field])

            if track_updates:
                track_values.append(track_id)
                await db.execute(
                    f"UPDATE tracks SET {', '.join(track_updates)} WHERE id = ?",
                    track_values
                )

        await db.commit()

    return {"status": "saved"}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestSaveDiscAndTracks -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: add POST /api/disc/{disc_id}/save endpoint"
```

---

## Task 5: Add API Endpoint GET /api/tracks/{track_id}/verify-files

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

```python
class TestVerifyTrackFiles:
    """Tests for GET /api/tracks/{track_id}/verify-files endpoint."""

    def test_returns_all_false_for_no_paths(self, client, db_with_disc_and_tracks):
        """Returns all exists=false when no paths set."""
        response = client.get("/api/tracks/1/verify-files")
        assert response.status_code == 200

        data = response.json()
        assert data["ripped_exists"] is False
        assert data["transcoded_exists"] is False
        assert data["inserted_exists"] is False

    def test_returns_true_when_file_exists(self, client, db_with_disc_and_tracks, tmp_path, monkeypatch):
        """Returns exists=true when file is present on disk."""
        # Create a test file
        ripped_file = tmp_path / "test.mkv"
        ripped_file.write_text("test content")

        # Update track to have this path
        import asyncio
        import aiosqlite
        from amphigory.api import disc_repository

        async def set_path():
            async with aiosqlite.connect(disc_repository.get_db_path()) as db:
                await db.execute(
                    "UPDATE tracks SET ripped_path = ? WHERE id = 1",
                    (str(ripped_file),)
                )
                await db.commit()
        asyncio.run(set_path())

        response = client.get("/api/tracks/1/verify-files")
        assert response.status_code == 200

        data = response.json()
        assert data["ripped_exists"] is True

    def test_returns_404_for_unknown_track(self, client):
        """Returns 404 for non-existent track_id."""
        response = client.get("/api/tracks/99999/verify-files")
        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestVerifyTrackFiles -v`
Expected: FAIL with 404 (endpoint not found)

**Step 3: Write minimal implementation**

```python
class VerifyFilesResponse(BaseModel):
    """Response for file verification."""
    ripped_exists: bool
    ripped_path: Optional[str] = None
    transcoded_exists: bool
    transcoded_path: Optional[str] = None
    inserted_exists: bool
    inserted_path: Optional[str] = None


@router.get("/tracks/{track_id}/verify-files", response_model=VerifyFilesResponse)
async def verify_track_files(track_id: int) -> VerifyFilesResponse:
    """Check if a track's output files exist on disk."""
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT ripped_path, transcoded_path, inserted_path FROM tracks WHERE id = ?",
            (track_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Track not found")

        track = dict(row)

        ripped_path = track.get("ripped_path")
        transcoded_path = track.get("transcoded_path")
        inserted_path = track.get("inserted_path")

        return VerifyFilesResponse(
            ripped_exists=bool(ripped_path and Path(ripped_path).exists()),
            ripped_path=ripped_path,
            transcoded_exists=bool(transcoded_path and Path(transcoded_path).exists()),
            transcoded_path=transcoded_path,
            inserted_exists=bool(inserted_path and Path(inserted_path).exists()),
            inserted_path=inserted_path,
        )
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestVerifyTrackFiles -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: add GET /api/tracks/{track_id}/verify-files endpoint"
```

---

## Task 6: Add API Endpoint POST /api/tracks/{track_id}/reset

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

```python
class TestResetTrack:
    """Tests for POST /api/tracks/{track_id}/reset endpoint."""

    def test_clears_paths_in_database(self, client, db_with_disc_and_tracks):
        """Clears ripped_path, transcoded_path, inserted_path."""
        import asyncio
        import aiosqlite
        from amphigory.api import disc_repository

        # Set paths first
        async def set_paths():
            async with aiosqlite.connect(disc_repository.get_db_path()) as db:
                await db.execute(
                    """UPDATE tracks
                       SET ripped_path = '/test/ripped.mkv',
                           transcoded_path = '/test/transcoded.mp4',
                           inserted_path = '/test/inserted.mp4',
                           status = 'complete'
                       WHERE id = 1""",
                )
                await db.commit()
        asyncio.run(set_paths())

        response = client.post("/api/tracks/1/reset")
        assert response.status_code == 200

        # Verify paths cleared
        async def check_paths():
            async with aiosqlite.connect(disc_repository.get_db_path()) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT ripped_path, transcoded_path, inserted_path, status FROM tracks WHERE id = 1"
                )
                return dict(await cursor.fetchone())

        track = asyncio.run(check_paths())
        assert track["ripped_path"] is None
        assert track["transcoded_path"] is None
        assert track["inserted_path"] is None
        assert track["status"] == "discovered"

    def test_deletes_existing_files(self, client, db_with_disc_and_tracks, tmp_path):
        """Deletes files from disk when they exist."""
        import asyncio
        import aiosqlite
        from amphigory.api import disc_repository

        # Create test files
        ripped = tmp_path / "ripped.mkv"
        ripped.write_text("ripped content")
        transcoded = tmp_path / "transcoded.mp4"
        transcoded.write_text("transcoded content")

        # Set paths in DB
        async def set_paths():
            async with aiosqlite.connect(disc_repository.get_db_path()) as db:
                await db.execute(
                    """UPDATE tracks
                       SET ripped_path = ?, transcoded_path = ?
                       WHERE id = 1""",
                    (str(ripped), str(transcoded))
                )
                await db.commit()
        asyncio.run(set_paths())

        response = client.post("/api/tracks/1/reset")
        assert response.status_code == 200

        # Verify files deleted
        assert not ripped.exists()
        assert not transcoded.exists()

    def test_returns_404_for_unknown_track(self, client):
        """Returns 404 for non-existent track_id."""
        response = client.post("/api/tracks/99999/reset")
        assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestResetTrack -v`
Expected: FAIL with 404 (endpoint not found)

**Step 3: Write minimal implementation**

```python
@router.post("/tracks/{track_id}/reset")
async def reset_track(track_id: int):
    """Reset a track for reprocessing.

    Deletes any existing files and clears paths in database.
    """
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        # Get current paths
        cursor = await db.execute(
            "SELECT ripped_path, transcoded_path, inserted_path FROM tracks WHERE id = ?",
            (track_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Track not found")

        track = dict(row)

        # Delete files if they exist
        for path_key in ["ripped_path", "transcoded_path", "inserted_path"]:
            path = track.get(path_key)
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass  # Ignore errors (e.g., permission denied)

        # Clear paths and reset status
        await db.execute(
            """UPDATE tracks
               SET ripped_path = NULL,
                   transcoded_path = NULL,
                   inserted_path = NULL,
                   status = 'discovered'
               WHERE id = ?""",
            (track_id,)
        )
        await db.commit()

    return {"status": "reset"}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestResetTrack -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: add POST /api/tracks/{track_id}/reset endpoint"
```

---

## Task 7: Update Dashboard Status HTML for Known Discs

**Files:**
- Modify: `src/amphigory/api/disc.py:296-350` (get_disc_status_html function)
- Test: `tests/test_disc_api.py`

**Step 1: Write the failing test**

```python
class TestDiscStatusHtmlKnownDisc:
    """Tests for disc status HTML with known discs."""

    def test_shows_fingerprint_prefix(self, client, db_with_disc_and_tracks, mock_daemon_with_disc):
        """Shows fingerprint prefix for all discs."""
        response = client.get("/api/disc/status-html")
        assert response.status_code == 200
        # Fingerprint prefix (first 7 chars) should appear
        assert "test_fi" in response.text or "test_fingerprint" in response.text

    def test_shows_track_count_for_known_disc(self, client, db_with_disc_and_tracks, mock_daemon_with_disc):
        """Shows track count for known discs."""
        response = client.get("/api/disc/status-html")
        assert "tracks" in response.text.lower()

    def test_shows_review_disc_button_for_known_disc(self, client, db_with_disc_and_tracks, mock_daemon_with_disc):
        """Shows 'Review Disc' button instead of 'Scan Disc' for known discs."""
        response = client.get("/api/disc/status-html")
        assert "Review Disc" in response.text

    def test_shows_scan_disc_button_for_unknown_disc(self, client, mock_daemon_with_unknown_disc):
        """Shows 'Scan Disc' button for unknown discs."""
        response = client.get("/api/disc/status-html")
        assert "Scan Disc" in response.text
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestDiscStatusHtmlKnownDisc -v`
Expected: FAIL (may need fixture setup, or assertions fail)

**Step 3: Write minimal implementation**

Update the `get_disc_status_html` function to show different content based on whether disc is known:

```python
@router.get("/status-html", response_class=HTMLResponse)
async def get_disc_status_html(request: Request):
    """Return disc status as HTML fragment for HTMX."""
    for daemon_id in list(_daemons.keys()):
        try:
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )
            if drive_data.get("state") in ["disc_inserted", "scanning", "scanned", "ripping"]:
                disc_volume = drive_data.get("disc_volume") or "Unknown"
                disc_device = drive_data.get("device") or ""
                fingerprint = drive_data.get("fingerprint") or ""
                fp_short = fingerprint[:7] if fingerprint else ""

                # Check if disc is known in database
                known_disc_info = None
                track_count = 0
                if fingerprint:
                    known_disc_info = await disc_repository.get_disc_by_fingerprint(fingerprint)
                    if known_disc_info:
                        track_count = await disc_repository.get_track_count_by_fingerprint(fingerprint)

                if known_disc_info:
                    # Known disc - show title, track count, Review button
                    title = known_disc_info.get("title", disc_volume)
                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {title} ({fp_short})</p>
                    <p class="status-detail">{track_count} tracks</p>
                    <a href="/disc" class="btn btn-primary">Review Disc</a>
                </div>
                '''
                else:
                    # Unknown disc - show volume name, fingerprint, Scan button
                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_volume} ({fp_short})</p>
                    <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
                        Scan Disc
                    </button>
                </div>
                '''
        except (KeyError, asyncio.TimeoutError):
            pass

    # No disc detected
    return '''
    <div class="no-disc">
        <p class="status-message">No disc detected</p>
    </div>
    '''
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_disc_api.py::TestDiscStatusHtmlKnownDisc -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/disc.py tests/test_disc_api.py
git commit -m "feat: update dashboard status HTML for known discs"
```

---

## Task 8: Add Track Status Icons CSS

**Files:**
- Modify: `src/amphigory/static/style.css`

**Step 1: Add CSS for status icons**

```css
/* Track processing status icons */
.track-status {
    display: inline-flex;
    gap: 0.25rem;
    font-size: 1rem;
}

.track-status .status-icon {
    opacity: 0.3;
    transition: opacity 0.2s, color 0.2s;
}

.track-status .status-icon.done {
    opacity: 1;
    color: var(--success-color, #28a745);
}

.track-status .status-icon.missing {
    opacity: 1;
    color: var(--danger-color, #dc3545);
    text-decoration: line-through;
}

.track-status .status-icon.pending {
    opacity: 0.3;
}

/* Reset link */
.reset-link {
    color: var(--muted-color, #6c757d);
    cursor: pointer;
    font-size: 0.875rem;
}

.reset-link:hover {
    color: var(--danger-color, #dc3545);
}
```

**Step 2: Commit**

```bash
git add src/amphigory/static/style.css
git commit -m "feat: add CSS for track status icons"
```

---

## Task 9: Update Disc Review Page - Auto-load from Database

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Update checkDiscStatus function**

Update the disc review page JavaScript to automatically load from database for known discs:

```javascript
async function checkDiscStatus() {
    try {
        const response = await fetch('/api/disc/status');
        const data = await response.json();

        const statusText = document.getElementById('disc-status-text');
        const scanSection = document.getElementById('scan-section');

        if (data.has_disc) {
            // Check if we have cached scan results in memory
            try {
                const scanResponse = await fetch('/api/disc/current-scan');
                if (scanResponse.ok) {
                    scanResult = await scanResponse.json();
                    displayScanResult(scanResult);
                    return;
                }
            } catch (err) {
                // No cached scan in memory - check database
            }

            // Get fingerprint and check database
            const fpResponse = await fetch('/api/disc/lookup-fingerprint');
            if (fpResponse.ok) {
                const discInfo = await fpResponse.json();
                const fingerprint = discInfo.fingerprint;
                const fpShort = fingerprint ? fingerprint.substring(0, 7) : '';

                if (discInfo.id) {
                    // Known disc - auto-load from database
                    statusText.textContent = `Known disc: ${discInfo.title} (${fpShort})`;
                    await loadFromDatabase(fingerprint);

                    scanSection.innerHTML = `
                        <button class="btn btn-secondary" onclick="loadFromDatabase('${fingerprint}')">
                            Reload from DB
                        </button>
                        <button class="btn btn-secondary" onclick="startScan()" style="margin-left: 0.5rem;">
                            Rescan Disc
                        </button>
                    `;
                    return;
                }
            }

            // Unknown disc - show scan button
            statusText.textContent = `Disc: ${data.volume_name || 'Unknown'} (${data.device_path})`;
            scanSection.innerHTML = `
                <button class="btn btn-primary" onclick="startScan()">
                    Scan Disc
                </button>
            `;
        } else {
            // No disc
            statusText.textContent = 'No disc detected';
            scanSection.innerHTML = `<button class="btn btn-secondary" onclick="checkDiscStatus()">Refresh</button>`;
            scanResult = null;
            document.getElementById('disc-info-section').style.display = 'none';
            document.getElementById('tracks-section').style.display = 'none';
        }
    } catch (error) {
        console.error('Error checking disc status:', error);
    }
}

async function loadFromDatabase(fingerprint) {
    try {
        const response = await fetch(`/api/disc/by-fingerprint/${fingerprint}`);
        if (!response.ok) throw new Error('Failed to load disc');

        const data = await response.json();

        // Populate disc info fields from database
        if (data.disc.title) document.getElementById('movie-title').value = data.disc.title;
        if (data.disc.year) document.getElementById('movie-year').value = data.disc.year;
        if (data.disc.imdb_id) document.getElementById('imdb-id').value = data.disc.imdb_id;

        // Store disc ID for saving
        window.currentDiscId = data.disc.id;

        // Convert tracks to scan result format and verify files
        await displayTracksFromDatabase(data.tracks);

        document.getElementById('disc-info-section').style.display = 'block';
        document.getElementById('tracks-section').style.display = 'block';
    } catch (error) {
        console.error('Error loading from database:', error);
    }
}
```

**Step 2: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: auto-load disc from database on review page"
```

---

## Task 10: Update Disc Review Page - Track Status Display

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Add displayTracksFromDatabase function**

```javascript
async function displayTracksFromDatabase(tracks) {
    const tbody = document.getElementById('tracks-body');
    tbody.innerHTML = '';

    // Verify files for all tracks
    const verifiedTracks = await Promise.all(tracks.map(async (track) => {
        try {
            const verifyResponse = await fetch(`/api/tracks/${track.id}/verify-files`);
            if (verifyResponse.ok) {
                const verification = await verifyResponse.json();
                return { ...track, verification };
            }
        } catch (e) {
            console.error('Error verifying track files:', e);
        }
        return { ...track, verification: { ripped_exists: false, transcoded_exists: false, inserted_exists: false } };
    }));

    // Determine which tracks to auto-select (unprocessed or partially processed)
    for (const track of verifiedTracks) {
        const v = track.verification;
        const isFullyProcessed = v.inserted_exists;
        const isPartiallyProcessed = (v.ripped_exists || v.transcoded_exists) && !v.inserted_exists;
        const isUnprocessed = !v.ripped_exists && !v.transcoded_exists && !v.inserted_exists;

        const shouldSelect = isUnprocessed || isPartiallyProcessed;
        const showReset = isPartiallyProcessed;

        const row = createTrackRowFromDb(track, shouldSelect, showReset);
        tbody.appendChild(row);
    }

    updateProcessButton();
}

function createTrackRowFromDb(track, selected, showReset) {
    const v = track.verification;

    // Status icons
    const rippedClass = v.ripped_exists ? 'done' : (track.ripped_path ? 'missing' : 'pending');
    const transcodedClass = v.transcoded_exists ? 'done' : (track.transcoded_path ? 'missing' : 'pending');
    const insertedClass = v.inserted_exists ? 'done' : (track.inserted_path ? 'missing' : 'pending');

    const statusIcons = `
        <span class="track-status">
            <span class="status-icon ${rippedClass}" title="Ripped: ${track.ripped_path || 'not set'}">💿</span>
            <span class="status-icon ${transcodedClass}" title="Transcoded: ${track.transcoded_path || 'not set'}">🎬</span>
            <span class="status-icon ${insertedClass}" title="Inserted: ${track.inserted_path || 'not set'}">📺</span>
        </span>
    `;

    const resetLink = showReset
        ? `<span class="reset-link" onclick="resetTrack(${track.id})" title="Reset and reprocess from scratch">↺</span>`
        : '';

    // Audio/Subs count
    const audioCount = track.audio_tracks ? JSON.parse(track.audio_tracks).length : 0;
    const subCount = track.subtitle_tracks ? JSON.parse(track.subtitle_tracks).length : 0;

    // Format duration
    const duration = formatDuration(track.duration_seconds);

    // Format size
    const size = formatSize(track.size_bytes);

    const row = document.createElement('tr');
    row.className = 'track-row';
    row.draggable = true;
    row.dataset.trackId = track.id;

    row.innerHTML = `
        <td><input type="checkbox" name="tracks" value="${track.track_number}" ${selected ? 'checked' : ''}></td>
        <td>${track.track_number}</td>
        <td><input type="text" class="track-name-input" value="${escapeHtml(track.track_name || '')}" data-track-id="${track.id}"></td>
        <td>
            <select class="track-type-select" data-track-id="${track.id}">
                <option value="main_feature" ${track.track_type === 'main_feature' ? 'selected' : ''}>Main Feature</option>
                <option value="featurettes" ${track.track_type === 'featurettes' ? 'selected' : ''}>Featurette</option>
                <option value="deleted_scenes" ${track.track_type === 'deleted_scenes' ? 'selected' : ''}>Deleted Scene</option>
                <option value="behind_the_scenes" ${track.track_type === 'behind_the_scenes' ? 'selected' : ''}>Behind the Scenes</option>
                <option value="trailers" ${track.track_type === 'trailers' ? 'selected' : ''}>Trailer</option>
                <option value="other" ${track.track_type === 'other' ? 'selected' : ''}>Other</option>
            </select>
        </td>
        <td>${duration}</td>
        <td>${size}</td>
        <td>${track.resolution || '-'}</td>
        <td>${audioCount}/${subCount}</td>
        <td><select class="preset-select" data-track-id="${track.id}"></select></td>
        <td>${statusIcons}</td>
        <td>${resetLink}</td>
    `;

    // Populate preset dropdown
    const presetSelect = row.querySelector('.preset-select');
    populatePresetDropdown(presetSelect, track.resolution);
    if (track.preset_name) {
        presetSelect.value = track.preset_name;
    }

    return row;
}

async function resetTrack(trackId) {
    if (!confirm('This will delete any existing files and start fresh. Continue?')) {
        return;
    }

    try {
        const response = await fetch(`/api/tracks/${trackId}/reset`, { method: 'POST' });
        if (response.ok) {
            // Reload from database to reflect changes
            const fpResponse = await fetch('/api/disc/lookup-fingerprint');
            if (fpResponse.ok) {
                const discInfo = await fpResponse.json();
                await loadFromDatabase(discInfo.fingerprint);
            }
        } else {
            alert('Failed to reset track');
        }
    } catch (error) {
        console.error('Error resetting track:', error);
        alert('Error resetting track');
    }
}
```

**Step 2: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: add track status icons and reset functionality"
```

---

## Task 11: Update Process Selected Tracks - Save Before Processing

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Update processSelectedTracks function**

```javascript
async function processSelectedTracks() {
    // Save all page data to database first
    if (window.currentDiscId) {
        const discData = {
            title: document.getElementById('movie-title').value,
            year: parseInt(document.getElementById('movie-year').value) || null,
            imdb_id: document.getElementById('imdb-id').value || null,
        };

        const tracksData = [];
        document.querySelectorAll('.track-row').forEach(row => {
            const trackId = row.dataset.trackId;
            if (trackId) {
                tracksData.push({
                    id: parseInt(trackId),
                    track_name: row.querySelector('.track-name-input')?.value,
                    track_type: row.querySelector('.track-type-select')?.value,
                    preset_name: row.querySelector('.preset-select')?.value,
                });
            }
        });

        try {
            await fetch(`/api/disc/${window.currentDiscId}/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ disc: discData, tracks: tracksData }),
            });
        } catch (error) {
            console.error('Error saving to database:', error);
        }
    }

    // Continue with existing processing logic...
    // (existing processSelectedTracks code continues here)
}
```

**Step 2: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: save disc and track data before processing"
```

---

## Task 12: Update Processing Flow - Smart Resume Logic

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Add smart resume logic to processing**

Update the processing logic to skip completed steps based on file existence:

```javascript
async function processSelectedTracks() {
    // ... (save logic from Task 11) ...

    const selectedTracks = getSelectedTracks();
    if (selectedTracks.length === 0) {
        alert('No tracks selected');
        return;
    }

    const outputDir = document.getElementById('output-dir').value;

    for (const trackNum of selectedTracks) {
        const row = document.querySelector(`tr.track-row input[value="${trackNum}"]`)?.closest('tr');
        if (!row) continue;

        const trackId = row.dataset.trackId;
        const trackName = row.querySelector('.track-name-input')?.value;
        const trackType = row.querySelector('.track-type-select')?.value;
        const presetName = row.querySelector('.preset-select')?.value;

        // Check what processing is needed
        let needsRip = true;
        let needsTranscode = true;
        let needsInsert = true;

        if (trackId) {
            try {
                const verifyResponse = await fetch(`/api/tracks/${trackId}/verify-files`);
                if (verifyResponse.ok) {
                    const v = await verifyResponse.json();

                    // Work backwards from end state
                    if (v.inserted_exists) {
                        // Fully done - skip everything
                        needsRip = false;
                        needsTranscode = false;
                        needsInsert = false;
                    } else if (v.transcoded_exists) {
                        // Just needs insert
                        needsRip = false;
                        needsTranscode = false;
                    } else if (v.ripped_exists) {
                        // Needs transcode and insert
                        needsRip = false;
                    }
                }
            } catch (e) {
                console.error('Error checking track status:', e);
            }
        }

        // Create tasks based on what's needed
        if (needsRip) {
            await createRipTask(trackNum, trackName, trackType, outputDir);
        }
        // Note: Transcode and insert jobs are created by the job runner
        // after rip completes, or we could add explicit transcode task creation here
    }

    alert(`Processing ${selectedTracks.length} tracks. Check the Queue page for progress.`);
}
```

**Step 2: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: add smart resume logic to skip completed steps"
```

---

## Task 13: Integration Test - Full Resume Flow

**Files:**
- Create: `tests/test_resume_flow.py`

**Step 1: Write integration test**

```python
"""Integration tests for resume interrupted flows feature."""

import pytest
import json
import asyncio
import aiosqlite
from pathlib import Path


class TestResumeFlow:
    """Test the full resume flow from known disc to processing."""

    @pytest.fixture
    def disc_with_mixed_tracks(self, client, tmp_path, monkeypatch):
        """Create a disc with tracks in various states."""
        from amphigory.api import disc_repository
        from amphigory.database import Database

        db_path = tmp_path / "test.db"
        monkeypatch.setattr(disc_repository, "get_db_path", lambda: db_path)

        async def setup():
            db = Database(db_path)
            await db.initialize()

            async with db.connection() as conn:
                # Create disc
                cursor = await conn.execute(
                    """INSERT INTO discs (title, fingerprint, year, imdb_id)
                       VALUES (?, ?, ?, ?)""",
                    ("Test Movie", "resume_test_fp", 2020, "tt1234567"),
                )
                disc_id = cursor.lastrowid

                # Track 1: Fully processed
                await conn.execute(
                    """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                       ripped_path, transcoded_path, inserted_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (disc_id, 1, "main_feature", "Main Feature", "complete",
                     "/media/ripped/t1.mkv", "/media/inbox/t1.mp4", "/media/plex/t1.mp4"),
                )

                # Track 2: Transcoded only (needs insert)
                await conn.execute(
                    """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                       ripped_path, transcoded_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (disc_id, 2, "featurettes", "Making Of", "transcoded",
                     "/media/ripped/t2.mkv", "/media/inbox/t2.mp4"),
                )

                # Track 3: Ripped only (needs transcode + insert)
                await conn.execute(
                    """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                       ripped_path)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (disc_id, 3, "deleted_scenes", "Deleted Scene", "ripped",
                     "/media/ripped/t3.mkv"),
                )

                # Track 4: Unprocessed
                await conn.execute(
                    """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (disc_id, 4, "trailers", "Trailer", "discovered"),
                )

                await conn.commit()

            return disc_id

        return asyncio.run(setup())

    def test_get_disc_by_fingerprint_returns_all_tracks(self, client, disc_with_mixed_tracks):
        """GET /api/disc/by-fingerprint returns disc with all tracks."""
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200

        data = response.json()
        assert data["disc"]["title"] == "Test Movie"
        assert len(data["tracks"]) == 4

    def test_verify_files_shows_correct_state(self, client, disc_with_mixed_tracks, tmp_path):
        """Verify files endpoint correctly reports file existence."""
        # Track 4 has no paths - all should be false
        response = client.get("/api/tracks/4/verify-files")
        assert response.status_code == 200

        data = response.json()
        assert data["ripped_exists"] is False
        assert data["transcoded_exists"] is False
        assert data["inserted_exists"] is False

    def test_reset_clears_all_paths(self, client, disc_with_mixed_tracks):
        """Reset track clears all paths and resets status."""
        # Reset track 2 (has ripped and transcoded paths)
        response = client.post("/api/tracks/2/reset")
        assert response.status_code == 200

        # Verify paths cleared
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        tracks = response.json()["tracks"]
        track2 = next(t for t in tracks if t["track_number"] == 2)

        assert track2["ripped_path"] is None
        assert track2["transcoded_path"] is None
        assert track2["status"] == "discovered"

    def test_save_updates_disc_and_tracks(self, client, disc_with_mixed_tracks):
        """Save endpoint updates disc and track info."""
        response = client.post("/api/disc/1/save", json={
            "disc": {"title": "Updated Title", "year": 2021},
            "tracks": [{"id": 4, "track_name": "New Trailer Name", "preset_name": "HQ 720p"}]
        })
        assert response.status_code == 200

        # Verify changes
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        data = response.json()

        assert data["disc"]["title"] == "Updated Title"
        assert data["disc"]["year"] == 2021

        track4 = next(t for t in data["tracks"] if t["track_number"] == 4)
        assert track4["track_name"] == "New Trailer Name"
        assert track4["preset_name"] == "HQ 720p"
```

**Step 2: Run integration tests**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_resume_flow.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_resume_flow.py
git commit -m "test: add integration tests for resume flow"
```

---

## Summary

**Total Tasks:** 13

**Database:** 1 migration (inserted_path column)

**API Endpoints:**
- GET `/api/disc/by-fingerprint/{fingerprint}` - fetch disc + tracks
- POST `/api/disc/{disc_id}/save` - save disc + track edits
- GET `/api/tracks/{track_id}/verify-files` - check file existence
- POST `/api/tracks/{track_id}/reset` - delete files, clear paths
- Modified `/api/disc/status-html` - known disc detection

**Frontend:**
- CSS for status icons (💿🎬📺)
- Auto-load from database for known discs
- Track status display with verification
- Reset link per track
- Save before processing
- Smart resume logic

**Deferred:**
- Insert functionality (moving files to Plex library)
