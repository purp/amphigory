# Phase 3: Pipeline Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Amphigory pipeline with automatic transcoding, library catalog, storage cleanup, wiki integration, and E2E testing.

**Architecture:** Extend webapp with background job runner for transcoding, new API routers for library/cleanup/wiki operations, and new HTML templates. Uses existing TranscoderService, JobQueue, and PresetManager. Playwright for UI testing.

**Tech Stack:** Python/FastAPI, SQLite, Jinja2 templates, HTMX, pytest, pytest-playwright

---

## Task 1: Database Schema Extensions

**Files:**
- Modify: `src/amphigory/database.py:8-94` (SCHEMA and migrations)
- Modify: `tests/test_database.py`

**Goal:** Add reprocessing flags to discs table, preset_name to tracks table.

**Step 1: Write failing tests**

Add to `tests/test_database.py`:

```python
class TestPhase3SchemaExtensions:
    @pytest.mark.asyncio
    async def test_discs_table_has_reprocessing_columns(self, db):
        """Discs table has needs_reprocessing, reprocessing_type, reprocessing_notes columns."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(discs)")
            columns = {row["name"] for row in await cursor.fetchall()}

        assert "needs_reprocessing" in columns
        assert "reprocessing_type" in columns
        assert "reprocessing_notes" in columns

    @pytest.mark.asyncio
    async def test_tracks_table_has_preset_name(self, db):
        """Tracks table has preset_name column."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(tracks)")
            columns = {row["name"] for row in await cursor.fetchall()}

        assert "preset_name" in columns

    @pytest.mark.asyncio
    async def test_can_flag_disc_for_reprocessing(self, db):
        """Can set reprocessing flags on a disc."""
        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, needs_reprocessing, reprocessing_type, reprocessing_notes)
                   VALUES (?, ?, ?, ?)""",
                ("Test Movie", True, "re-transcode", "comb artifacts on extras"),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT needs_reprocessing, reprocessing_type, reprocessing_notes FROM discs WHERE title = ?",
                ("Test Movie",),
            )
            row = await cursor.fetchone()

        assert row["needs_reprocessing"] == 1
        assert row["reprocessing_type"] == "re-transcode"
        assert row["reprocessing_notes"] == "comb artifacts on extras"
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestPhase3SchemaExtensions -v
```

Expected: FAIL - columns don't exist

**Step 3: Update SCHEMA and add migrations**

In `src/amphigory/database.py`, add to SCHEMA (around line 28, after `tvdb_id TEXT`):

```python
    -- Reprocessing flags
    needs_reprocessing BOOLEAN DEFAULT FALSE,
    reprocessing_type TEXT,
    reprocessing_notes TEXT
```

In tracks table (around line 61, after `air_date DATE`):

```python
    -- Transcode preset used
    preset_name TEXT
```

Add to `_run_migrations()` method (after the tracks column migrations):

```python
        # Migration: Add reprocessing flags to discs table
        if "needs_reprocessing" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN needs_reprocessing BOOLEAN DEFAULT FALSE")
        if "reprocessing_type" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN reprocessing_type TEXT")
        if "reprocessing_notes" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN reprocessing_notes TEXT")

        # Migration: Add preset_name to tracks table
        if "preset_name" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN preset_name TEXT")
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestPhase3SchemaExtensions -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/database.py tests/test_database.py
git commit -m "feat: add reprocessing flags and preset_name to schema"
```

---

## Task 2: Resolution-Based Preset Recommendation

**Files:**
- Create: `src/amphigory/preset_selector.py`
- Create: `tests/test_preset_selector.py`

**Goal:** Given track resolution, recommend appropriate HandBrake preset.

**Step 1: Write failing tests**

Create `tests/test_preset_selector.py`:

```python
"""Tests for resolution-based preset selection."""

import pytest
from amphigory.preset_selector import recommend_preset, parse_resolution


class TestParseResolution:
    def test_parse_1080p(self):
        assert parse_resolution("1920x1080") == (1920, 1080)

    def test_parse_720p(self):
        assert parse_resolution("1280x720") == (1280, 720)

    def test_parse_4k(self):
        assert parse_resolution("3840x2160") == (3840, 2160)

    def test_parse_sd_ntsc(self):
        assert parse_resolution("720x480") == (720, 480)

    def test_parse_sd_pal(self):
        assert parse_resolution("720x576") == (720, 576)

    def test_parse_none_returns_none(self):
        assert parse_resolution(None) is None

    def test_parse_empty_returns_none(self):
        assert parse_resolution("") is None

    def test_parse_invalid_returns_none(self):
        assert parse_resolution("invalid") is None


class TestRecommendPreset:
    def test_4k_recommends_uhd(self):
        assert recommend_preset(3840, 2160) == "uhd"

    def test_1080p_recommends_bluray(self):
        assert recommend_preset(1920, 1080) == "bluray"

    def test_1080i_recommends_bluray(self):
        assert recommend_preset(1920, 1080) == "bluray"

    def test_720p_recommends_dvd(self):
        assert recommend_preset(1280, 720) == "dvd"

    def test_sd_ntsc_recommends_dvd(self):
        assert recommend_preset(720, 480) == "dvd"

    def test_sd_pal_recommends_dvd(self):
        assert recommend_preset(720, 576) == "dvd"

    def test_unknown_resolution_recommends_dvd(self):
        """Default to DVD preset for unknown resolutions."""
        assert recommend_preset(640, 480) == "dvd"

    def test_none_resolution_recommends_dvd(self):
        assert recommend_preset(None, None) == "dvd"
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_preset_selector.py -v
```

Expected: FAIL - module doesn't exist

**Step 3: Implement preset_selector.py**

Create `src/amphigory/preset_selector.py`:

```python
"""Resolution-based preset recommendation for transcoding."""

import re
from typing import Optional, Tuple


def parse_resolution(resolution: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse resolution string (e.g., '1920x1080') into (width, height) tuple.

    Args:
        resolution: Resolution string in format 'WIDTHxHEIGHT'

    Returns:
        Tuple of (width, height) or None if parsing fails
    """
    if not resolution:
        return None

    match = re.match(r"(\d+)x(\d+)", resolution)
    if not match:
        return None

    return (int(match.group(1)), int(match.group(2)))


def recommend_preset(width: Optional[int], height: Optional[int]) -> str:
    """Recommend a preset category based on video resolution.

    Args:
        width: Video width in pixels
        height: Video height in pixels

    Returns:
        Preset category: 'uhd', 'bluray', or 'dvd'
    """
    if width is None or height is None:
        return "dvd"

    # 4K/UHD: 3840x2160 or higher
    if width >= 3840 or height >= 2160:
        return "uhd"

    # 1080p/Blu-ray: 1920x1080 or higher (but not 4K)
    if width >= 1920 or height >= 1080:
        return "bluray"

    # Everything else: DVD preset (720p, SD, etc.)
    return "dvd"
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_preset_selector.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/preset_selector.py tests/test_preset_selector.py
git commit -m "feat: add resolution-based preset recommendation"
```

---

## Task 3: Enhanced Naming with IMDB Tags

**Files:**
- Modify: `src/amphigory/naming.py`
- Modify: `tests/test_naming.py`

**Goal:** Add IMDB tag support and language variants to filename generation.

**Step 1: Write failing tests**

Add to `tests/test_naming.py`:

```python
class TestGenerateTrackFilenameWithImdb:
    def test_main_feature_with_imdb(self):
        """Main feature includes IMDB tag."""
        result = generate_track_filename(
            track_type="main_feature",
            movie_title="Coco",
            year=2017,
            track_name="",
            language="en",
            imdb_id="tt2380307",
        )
        assert result == "Coco (2017) {imdb-tt2380307}.mkv"

    def test_alternate_language_with_imdb(self):
        """Alternate language version includes both IMDB and language tag."""
        result = generate_track_filename(
            track_type="main_feature",
            movie_title="Coco",
            year=2017,
            track_name="",
            language="es",
            imdb_id="tt2380307",
        )
        assert result == "Coco (2017) {imdb-tt2380307} {lang-es}.mkv"

    def test_unknown_alternate_language(self):
        """Unknown alternate language uses alt1, alt2, etc."""
        result = generate_track_filename(
            track_type="main_feature",
            movie_title="Coco",
            year=2017,
            track_name="",
            language="alt1",
            imdb_id="tt2380307",
        )
        assert result == "Coco (2017) {imdb-tt2380307} {lang-alt1}.mkv"

    def test_extras_dont_get_imdb_tag(self):
        """Extras use simple naming without IMDB."""
        result = generate_track_filename(
            track_type="trailers",
            movie_title="Coco",
            year=2017,
            track_name="Trailer 1",
            language="en",
            imdb_id="tt2380307",
        )
        assert result == "Trailer 1-trailer.mkv"


class TestGenerateOutputDirectoryWithImdb:
    def test_movie_dir_with_imdb(self):
        """Movie directory includes IMDB tag."""
        result = generate_output_directory(
            base_path="/media/movies",
            movie_title="Coco",
            year=2017,
            track_type="main_feature",
            imdb_id="tt2380307",
        )
        assert result == Path("/media/movies/Coco (2017) {imdb-tt2380307}")

    def test_extras_dir_with_imdb(self):
        """Extras directory includes IMDB in parent."""
        result = generate_output_directory(
            base_path="/media/movies",
            movie_title="Coco",
            year=2017,
            track_type="featurettes",
            imdb_id="tt2380307",
        )
        assert result == Path("/media/movies/Coco (2017) {imdb-tt2380307}/Featurettes")
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_naming.py::TestGenerateTrackFilenameWithImdb -v
PYTHONPATH=src .venv/bin/pytest tests/test_naming.py::TestGenerateOutputDirectoryWithImdb -v
```

Expected: FAIL - function signature doesn't accept imdb_id

**Step 3: Update naming.py**

Update `generate_track_filename()` signature and implementation:

```python
def generate_track_filename(
    track_type: str,
    movie_title: str,
    year: int,
    track_name: str,
    language: str,
    imdb_id: str = "",
) -> str:
    """Generate a Plex-compatible filename for a track.

    Args:
        track_type: Type of track (main_feature, trailers, featurettes, etc.)
        movie_title: The movie title
        year: The movie release year
        track_name: The name of the track
        language: Language code (e.g., 'en', 'fr', 'alt1')
        imdb_id: IMDB ID (e.g., 'tt2380307')

    Returns:
        Plex-compatible filename with .mkv extension
    """
    if not isinstance(year, int) or year < 1900 or year > 2100:
        raise ValueError(f"Year must be between 1900 and 2100, got: {year}")

    sanitized_title = sanitize_filename(movie_title)

    # Main feature naming
    if track_type == 'main_feature':
        base_name = f"{sanitized_title} ({year})"

        # Add IMDB tag if provided
        if imdb_id:
            base_name += f" {{imdb-{imdb_id}}}"

        # Check if this is an alternate language version
        if language and language.lower() not in ('en', 'en-us', 'english'):
            base_name += f" {{lang-{language}}}"

        return f"{base_name}.mkv"

    # Extras naming: "Track Name-suffix.mkv" (no IMDB tag)
    sanitized_track_name = sanitize_filename(track_name)
    suffix = PLEX_SUFFIXES.get(track_type, '-other')
    return f"{sanitized_track_name}{suffix}.mkv"
```

Update `generate_output_directory()` signature and implementation:

```python
def generate_output_directory(
    base_path: Union[str, Path],
    movie_title: str,
    year: int,
    track_type: str,
    imdb_id: str = "",
) -> Path:
    """Generate output directory path following Plex conventions.

    Args:
        base_path: Base directory for movies
        movie_title: The movie title
        year: The movie release year
        track_type: Type of track
        imdb_id: IMDB ID (e.g., 'tt2380307')

    Returns:
        Path object for the output directory
    """
    base = Path(base_path)

    if not isinstance(year, int) or year < 1900 or year > 2100:
        raise ValueError(f"Year must be between 1900 and 2100, got: {year}")

    sanitized_title = sanitize_filename(movie_title)

    # Movie directory: "Title (Year) {imdb-id}"
    dir_name = f"{sanitized_title} ({year})"
    if imdb_id:
        dir_name += f" {{imdb-{imdb_id}}}"

    movie_dir = base / dir_name

    if track_type == 'main_feature':
        return movie_dir

    subdir = PLEX_DIRECTORIES.get(track_type, 'Other')
    return movie_dir / subdir
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_naming.py -v
```

Expected: PASS (all tests including new ones)

**Step 5: Commit**

```bash
git add src/amphigory/naming.py tests/test_naming.py
git commit -m "feat: add IMDB tags and language variants to naming"
```

---

## Task 4: Library API - List and Filter

**Files:**
- Create: `src/amphigory/api/library.py`
- Create: `tests/test_library_api.py`

**Goal:** GET /api/library endpoint with filtering and sorting.

**Step 1: Write failing tests**

Create `tests/test_library_api.py`:

```python
"""Tests for Library API."""

import pytest
from httpx import AsyncClient, ASGITransport
from amphigory.main import app
from amphigory.database import Database


@pytest.fixture
async def seeded_db(tmp_path):
    """Database with sample discs."""
    db = Database(tmp_path / "test.db")
    await db.initialize()

    async with db.connection() as conn:
        # Insert sample discs
        await conn.execute(
            """INSERT INTO discs (title, year, disc_type, media_type, processed_at, needs_reprocessing)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("Coco", 2017, "bluray", "movie", "2024-12-25T10:00:00", False),
        )
        await conn.execute(
            """INSERT INTO discs (title, year, disc_type, media_type, processed_at, needs_reprocessing, reprocessing_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("The Polar Express", 2004, "bluray", "movie", "2024-12-20T10:00:00", True, "re-transcode"),
        )
        await conn.execute(
            """INSERT INTO discs (title, year, disc_type, media_type, fingerprint)
               VALUES (?, ?, ?, ?, ?)""",
            ("Unprocessed Disc", 2020, "dvd", "movie", "fp123"),
        )
        await conn.commit()

    app.state.db = db
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_list_all_discs(seeded_db):
    """GET /api/library returns all discs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 3


@pytest.mark.asyncio
async def test_filter_by_status_complete(seeded_db):
    """Filter by status=complete returns processed discs without flags."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library?status=complete")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 1
    assert data["discs"][0]["title"] == "Coco"


@pytest.mark.asyncio
async def test_filter_by_status_needs_attention(seeded_db):
    """Filter by status=needs_attention returns flagged discs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library?status=needs_attention")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 1
    assert data["discs"][0]["title"] == "The Polar Express"


@pytest.mark.asyncio
async def test_filter_by_status_not_processed(seeded_db):
    """Filter by status=not_processed returns discs without processed_at."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library?status=not_processed")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 1
    assert data["discs"][0]["title"] == "Unprocessed Disc"


@pytest.mark.asyncio
async def test_filter_by_disc_type(seeded_db):
    """Filter by disc_type."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library?disc_type=dvd")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 1
    assert data["discs"][0]["disc_type"] == "dvd"


@pytest.mark.asyncio
async def test_search_by_title(seeded_db):
    """Search by title substring."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library?search=polar")

    assert response.status_code == 200
    data = response.json()
    assert len(data["discs"]) == 1
    assert "Polar" in data["discs"][0]["title"]
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_library_api.py -v
```

Expected: FAIL - endpoint doesn't exist

**Step 3: Implement library.py**

Create `src/amphigory/api/library.py`:

```python
"""Library API for browsing processed discs."""

from typing import Optional, List
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/library", tags=["library"])


class DiscSummary(BaseModel):
    """Summary of a disc for list view."""
    id: int
    title: str
    year: Optional[int]
    disc_type: Optional[str]
    media_type: str
    track_count: int
    processed_at: Optional[str]
    status: str  # 'complete', 'needs_attention', 'not_processed'
    reprocessing_type: Optional[str]


class LibraryResponse(BaseModel):
    """Response for library listing."""
    discs: List[DiscSummary]
    total: int


@router.get("", response_model=LibraryResponse)
async def list_discs(
    request: Request,
    status: Optional[str] = Query(None, description="Filter: complete, needs_attention, not_processed"),
    disc_type: Optional[str] = Query(None, description="Filter: dvd, bluray, uhd"),
    media_type: Optional[str] = Query(None, description="Filter: movie, tv, music"),
    search: Optional[str] = Query(None, description="Search title"),
) -> LibraryResponse:
    """List all discs with optional filtering."""
    db = request.app.state.db

    # Build query with filters
    conditions = []
    params = []

    if status == "complete":
        conditions.append("processed_at IS NOT NULL AND (needs_reprocessing IS NULL OR needs_reprocessing = 0)")
    elif status == "needs_attention":
        conditions.append("needs_reprocessing = 1")
    elif status == "not_processed":
        conditions.append("processed_at IS NULL")

    if disc_type:
        conditions.append("disc_type = ?")
        params.append(disc_type)

    if media_type:
        conditions.append("media_type = ?")
        params.append(media_type)

    if search:
        conditions.append("title LIKE ?")
        params.append(f"%{search}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    async with db.connection() as conn:
        # Get discs
        cursor = await conn.execute(
            f"""SELECT d.*, COUNT(t.id) as track_count
                FROM discs d
                LEFT JOIN tracks t ON t.disc_id = d.id
                WHERE {where_clause}
                GROUP BY d.id
                ORDER BY d.processed_at DESC NULLS LAST, d.title ASC""",
            params,
        )
        rows = await cursor.fetchall()

    discs = []
    for row in rows:
        # Determine status
        if row["processed_at"] is None:
            disc_status = "not_processed"
        elif row["needs_reprocessing"]:
            disc_status = "needs_attention"
        else:
            disc_status = "complete"

        discs.append(DiscSummary(
            id=row["id"],
            title=row["title"],
            year=row["year"],
            disc_type=row["disc_type"],
            media_type=row["media_type"] or "movie",
            track_count=row["track_count"],
            processed_at=row["processed_at"],
            status=disc_status,
            reprocessing_type=row["reprocessing_type"],
        ))

    return LibraryResponse(discs=discs, total=len(discs))
```

Register router in `src/amphigory/api/__init__.py`:

```python
from amphigory.api.library import router as library_router
# Add to routers list
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_library_api.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/library.py src/amphigory/api/__init__.py tests/test_library_api.py
git commit -m "feat: add library API with filtering and search"
```

---

## Task 5: Library API - Detail and Flag

**Files:**
- Modify: `src/amphigory/api/library.py`
- Modify: `tests/test_library_api.py`

**Goal:** GET /api/library/{id} for details, PATCH /api/library/{id}/flag for reprocessing flags.

**Step 1: Write failing tests**

Add to `tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_get_disc_detail(seeded_db):
    """GET /api/library/{id} returns disc with tracks."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First get the list to find an ID
        list_response = await client.get("/api/library")
        disc_id = list_response.json()["discs"][0]["id"]

        response = await client.get(f"/api/library/{disc_id}")

    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "tracks" in data


@pytest.mark.asyncio
async def test_get_disc_not_found(seeded_db):
    """GET /api/library/{id} returns 404 for missing disc."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/library/99999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_flag_disc_for_reprocessing(seeded_db):
    """PATCH /api/library/{id}/flag sets reprocessing flags."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/library")
        disc_id = list_response.json()["discs"][0]["id"]

        response = await client.patch(
            f"/api/library/{disc_id}/flag",
            json={
                "needs_reprocessing": True,
                "reprocessing_type": "re-rip",
                "reprocessing_notes": "main feature has artifacts",
            },
        )

    assert response.status_code == 200

    # Verify flag was set
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(f"/api/library/{disc_id}")

    data = detail.json()
    assert data["needs_reprocessing"] is True
    assert data["reprocessing_type"] == "re-rip"
    assert data["reprocessing_notes"] == "main feature has artifacts"


@pytest.mark.asyncio
async def test_clear_reprocessing_flag(seeded_db):
    """PATCH /api/library/{id}/flag with needs_reprocessing=False clears flag."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Find the flagged disc
        list_response = await client.get("/api/library?status=needs_attention")
        disc_id = list_response.json()["discs"][0]["id"]

        # Clear the flag
        response = await client.patch(
            f"/api/library/{disc_id}/flag",
            json={"needs_reprocessing": False},
        )

    assert response.status_code == 200

    # Verify flag was cleared
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(f"/api/library/{disc_id}")

    data = detail.json()
    assert data["needs_reprocessing"] is False
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_library_api.py::test_get_disc_detail -v
PYTHONPATH=src .venv/bin/pytest tests/test_library_api.py::test_flag_disc_for_reprocessing -v
```

Expected: FAIL - endpoints don't exist

**Step 3: Add endpoints to library.py**

```python
class DiscDetail(BaseModel):
    """Full disc details with tracks."""
    id: int
    title: str
    year: Optional[int]
    disc_type: Optional[str]
    media_type: str
    imdb_id: Optional[str]
    tmdb_id: Optional[str]
    fingerprint: Optional[str]
    processed_at: Optional[str]
    needs_reprocessing: bool
    reprocessing_type: Optional[str]
    reprocessing_notes: Optional[str]
    tracks: List[dict]


class FlagRequest(BaseModel):
    """Request to flag disc for reprocessing."""
    needs_reprocessing: bool
    reprocessing_type: Optional[str] = None
    reprocessing_notes: Optional[str] = None


@router.get("/{disc_id}", response_model=DiscDetail)
async def get_disc_detail(request: Request, disc_id: int) -> DiscDetail:
    """Get full details for a disc including tracks."""
    db = request.app.state.db

    async with db.connection() as conn:
        # Get disc
        cursor = await conn.execute("SELECT * FROM discs WHERE id = ?", (disc_id,))
        disc = await cursor.fetchone()

        if not disc:
            raise HTTPException(status_code=404, detail="Disc not found")

        # Get tracks
        cursor = await conn.execute(
            "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
            (disc_id,),
        )
        tracks = [dict(row) for row in await cursor.fetchall()]

    return DiscDetail(
        id=disc["id"],
        title=disc["title"],
        year=disc["year"],
        disc_type=disc["disc_type"],
        media_type=disc["media_type"] or "movie",
        imdb_id=disc["imdb_id"],
        tmdb_id=disc["tmdb_id"],
        fingerprint=disc["fingerprint"],
        processed_at=disc["processed_at"],
        needs_reprocessing=bool(disc["needs_reprocessing"]),
        reprocessing_type=disc["reprocessing_type"],
        reprocessing_notes=disc["reprocessing_notes"],
        tracks=tracks,
    )


@router.patch("/{disc_id}/flag")
async def flag_disc(request: Request, disc_id: int, flag: FlagRequest) -> dict:
    """Set or clear reprocessing flag on a disc."""
    db = request.app.state.db

    async with db.connection() as conn:
        # Verify disc exists
        cursor = await conn.execute("SELECT id FROM discs WHERE id = ?", (disc_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update flags
        await conn.execute(
            """UPDATE discs
               SET needs_reprocessing = ?,
                   reprocessing_type = ?,
                   reprocessing_notes = ?
               WHERE id = ?""",
            (
                flag.needs_reprocessing,
                flag.reprocessing_type if flag.needs_reprocessing else None,
                flag.reprocessing_notes if flag.needs_reprocessing else None,
                disc_id,
            ),
        )
        await conn.commit()

    return {"status": "ok"}
```

Add import at top:
```python
from fastapi import APIRouter, Request, Query, HTTPException
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_library_api.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/library.py tests/test_library_api.py
git commit -m "feat: add library detail and flag endpoints"
```

---

## Task 6: Library HTML Page

**Files:**
- Create: `src/amphigory/templates/library.html`
- Modify: `src/amphigory/main.py` (add route)
- Modify: `src/amphigory/templates/base.html` (add nav link)

**Goal:** HTML page for browsing library with filters and detail expansion.

**Step 1: Write failing test**

Add to `tests/test_main.py`:

```python
@pytest.mark.asyncio
async def test_library_page_loads(client):
    """Library page loads successfully."""
    response = await client.get("/library")
    assert response.status_code == 200
    assert "Library" in response.text
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_main.py::test_library_page_loads -v
```

Expected: FAIL - route doesn't exist

**Step 3: Create template and route**

Create `src/amphigory/templates/library.html`:

```html
{% extends "base.html" %}

{% block title %}Library - Amphigory{% endblock %}

{% block content %}
<div class="library-page">
    <h1>Library</h1>

    <!-- Filters -->
    <div class="filters">
        <select id="status-filter" onchange="applyFilters()">
            <option value="">All Status</option>
            <option value="complete">Complete</option>
            <option value="needs_attention">Needs Attention</option>
            <option value="not_processed">Not Processed</option>
        </select>

        <select id="disc-type-filter" onchange="applyFilters()">
            <option value="">All Disc Types</option>
            <option value="uhd">UHD</option>
            <option value="bluray">Blu-ray</option>
            <option value="dvd">DVD</option>
        </select>

        <select id="media-type-filter" onchange="applyFilters()">
            <option value="">All Media Types</option>
            <option value="movie">Movie</option>
            <option value="tv">TV</option>
            <option value="music">Music</option>
        </select>

        <input type="text" id="search-input" placeholder="Search titles..."
               onkeyup="debounceSearch()">
    </div>

    <!-- Disc table -->
    <div id="disc-list"
         hx-get="/api/library"
         hx-trigger="load"
         hx-target="#disc-list">
        <p>Loading...</p>
    </div>
</div>

<script>
let searchTimeout;

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(applyFilters, 300);
}

function applyFilters() {
    const status = document.getElementById('status-filter').value;
    const discType = document.getElementById('disc-type-filter').value;
    const mediaType = document.getElementById('media-type-filter').value;
    const search = document.getElementById('search-input').value;

    let url = '/api/library/html?';
    if (status) url += `status=${status}&`;
    if (discType) url += `disc_type=${discType}&`;
    if (mediaType) url += `media_type=${mediaType}&`;
    if (search) url += `search=${encodeURIComponent(search)}&`;

    htmx.ajax('GET', url, '#disc-list');
}

async function toggleDetails(discId) {
    const row = document.getElementById(`disc-${discId}`);
    const detailsRow = document.getElementById(`details-${discId}`);

    if (detailsRow) {
        detailsRow.remove();
        return;
    }

    const response = await fetch(`/api/library/${discId}`);
    const disc = await response.json();

    const newRow = document.createElement('tr');
    newRow.id = `details-${discId}`;
    newRow.className = 'details-row';
    newRow.innerHTML = `
        <td colspan="7">
            <div class="disc-details">
                <h3>${disc.title} (${disc.year || 'N/A'})</h3>
                <p><strong>IMDB:</strong> ${disc.imdb_id || 'N/A'} |
                   <strong>Disc Type:</strong> ${disc.disc_type || 'N/A'}</p>

                <h4>Tracks</h4>
                <table class="tracks-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Type</th>
                            <th>Final Name</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${disc.tracks.map(t => `
                            <tr>
                                <td>${t.track_number || '-'}</td>
                                <td>${t.track_type || '-'}</td>
                                <td>${t.final_name || '-'}</td>
                                <td>${t.status || '-'}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>

                <div class="actions">
                    ${disc.transcoded_path ? `
                        <a href="file://${disc.transcoded_path}" class="btn btn-secondary">
                            Show in Finder
                        </a>
                    ` : ''}
                    <button onclick="showFlagDialog(${disc.id})" class="btn btn-warning">
                        Flag for Reprocessing
                    </button>
                </div>
            </div>
        </td>
    `;
    row.after(newRow);
}

function showFlagDialog(discId) {
    const type = prompt('Flag type (re-rip, re-transcode, missing-tracks):');
    if (!type) return;

    const notes = prompt('Notes (optional):');

    fetch(`/api/library/${discId}/flag`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            needs_reprocessing: true,
            reprocessing_type: type,
            reprocessing_notes: notes || null,
        }),
    }).then(() => applyFilters());
}
</script>

<style>
.filters {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
}

.filters select, .filters input {
    padding: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
}

.disc-table {
    width: 100%;
    border-collapse: collapse;
}

.disc-table th, .disc-table td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
}

.disc-table tr:hover {
    background: var(--bg-hover);
    cursor: pointer;
}

.status-complete { color: var(--success-color); }
.status-needs_attention { color: var(--warning-color); }
.status-not_processed { color: var(--muted-color); }

.details-row {
    background: var(--bg-secondary);
}

.disc-details {
    padding: 1rem;
}

.tracks-table {
    width: 100%;
    margin: 1rem 0;
}

.actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
}
</style>
{% endblock %}
```

Add route to `src/amphigory/main.py`:

```python
@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    """Library page."""
    return templates.TemplateResponse(request, "library.html", {})
```

Add HTML endpoint to `src/amphigory/api/library.py`:

```python
from fastapi.responses import HTMLResponse

@router.get("/html", response_class=HTMLResponse)
async def list_discs_html(
    request: Request,
    status: Optional[str] = None,
    disc_type: Optional[str] = None,
    media_type: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Return HTML table of discs for HTMX."""
    response = await list_discs(request, status, disc_type, media_type, search)

    if not response.discs:
        return "<p>No discs found.</p>"

    rows = []
    for disc in response.discs:
        status_class = f"status-{disc.status}"
        status_icon = {"complete": "✓", "needs_attention": "⚠", "not_processed": "○"}.get(disc.status, "")

        rows.append(f"""
            <tr id="disc-{disc.id}" onclick="toggleDetails({disc.id})">
                <td>{disc.title}</td>
                <td>{disc.year or '-'}</td>
                <td>{disc.disc_type or '-'}</td>
                <td>{disc.media_type}</td>
                <td>{disc.track_count}</td>
                <td>{disc.processed_at[:10] if disc.processed_at else '-'}</td>
                <td class="{status_class}">{status_icon} {disc.status.replace('_', ' ').title()}</td>
            </tr>
        """)

    return f"""
        <table class="disc-table">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Year</th>
                    <th>Disc Type</th>
                    <th>Media Type</th>
                    <th>Tracks</th>
                    <th>Processed</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        <p>{response.total} disc(s)</p>
    """
```

Add nav link to `src/amphigory/templates/base.html` (in the nav section):

```html
<a href="/library">Library</a>
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_main.py::test_library_page_loads -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/templates/library.html src/amphigory/main.py src/amphigory/api/library.py src/amphigory/templates/base.html
git commit -m "feat: add library page with filtering and details"
```

---

## Task 7: Cleanup API - Ripped Files

**Files:**
- Create: `src/amphigory/api/cleanup.py`
- Create: `tests/test_cleanup_api.py`

**Goal:** GET /api/cleanup/ripped and DELETE /api/cleanup/ripped endpoints.

**Step 1: Write failing tests**

Create `tests/test_cleanup_api.py`:

```python
"""Tests for Cleanup API."""

import pytest
import os
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from amphigory.main import app


@pytest.fixture
def mock_ripped_dir(tmp_path, monkeypatch):
    """Create mock ripped directory structure."""
    ripped = tmp_path / "ripped"
    ripped.mkdir()

    # Movie 1: fully transcoded
    movie1 = ripped / "Coco (2017) {imdb-tt2380307}"
    movie1.mkdir()
    (movie1 / "title00.mkv").write_bytes(b"x" * 1000)

    # Movie 2: not transcoded
    movie2 = ripped / "The Polar Express (2004)"
    movie2.mkdir()
    (movie2 / "title00.mkv").write_bytes(b"x" * 2000)
    (movie2 / "title01.mkv").write_bytes(b"x" * 500)

    monkeypatch.setenv("AMPHIGORY_RIPPED_DIR", str(ripped))
    return ripped


@pytest.mark.asyncio
async def test_list_ripped_folders(mock_ripped_dir):
    """GET /api/cleanup/ripped returns folder info."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/ripped")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 2
    assert data["total_size"] > 0


@pytest.mark.asyncio
async def test_ripped_folder_includes_size(mock_ripped_dir):
    """Each folder includes name, size, file_count."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/ripped")

    folder = response.json()["folders"][0]
    assert "name" in folder
    assert "size" in folder
    assert "file_count" in folder
    assert "age_days" in folder


@pytest.mark.asyncio
async def test_delete_ripped_folder(mock_ripped_dir):
    """DELETE /api/cleanup/ripped removes folders."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Get folder names
        list_response = await client.get("/api/cleanup/ripped")
        folder_name = list_response.json()["folders"][0]["name"]

        # Delete it
        response = await client.request(
            "DELETE",
            "/api/cleanup/ripped",
            json={"folders": [folder_name]},
        )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1

    # Verify it's gone
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/cleanup/ripped")

    assert len(list_response.json()["folders"]) == 1


@pytest.mark.asyncio
async def test_delete_prevents_path_traversal(mock_ripped_dir):
    """DELETE /api/cleanup/ripped rejects path traversal."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            "DELETE",
            "/api/cleanup/ripped",
            json={"folders": ["../../../etc/passwd"]},
        )

    assert response.status_code == 400
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_cleanup_api.py -v
```

Expected: FAIL - endpoint doesn't exist

**Step 3: Implement cleanup.py**

Create `src/amphigory/api/cleanup.py`:

```python
"""Cleanup API for managing ripped and inbox files."""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


def get_ripped_dir() -> Path:
    """Get ripped directory from environment."""
    return Path(os.environ.get("AMPHIGORY_RIPPED_DIR", "/media/ripped"))


def get_inbox_dir() -> Path:
    """Get inbox directory from environment."""
    return Path(os.environ.get("AMPHIGORY_INBOX_DIR", "/media/plex/inbox"))


class FolderInfo(BaseModel):
    """Information about a folder."""
    name: str
    size: int  # bytes
    file_count: int
    age_days: int
    transcode_status: Optional[str] = None  # For ripped folders


class RippedListResponse(BaseModel):
    """Response for listing ripped folders."""
    folders: List[FolderInfo]
    total_size: int


class DeleteRequest(BaseModel):
    """Request to delete folders."""
    folders: List[str]


class DeleteResponse(BaseModel):
    """Response after deletion."""
    deleted: int
    errors: List[str]


def get_folder_size(path: Path) -> int:
    """Calculate total size of folder in bytes."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def get_folder_age_days(path: Path) -> int:
    """Calculate folder age in days from modification time."""
    mtime = path.stat().st_mtime
    age_seconds = datetime.now().timestamp() - mtime
    return int(age_seconds / 86400)


def count_files(path: Path) -> int:
    """Count files in folder."""
    return sum(1 for entry in path.rglob("*") if entry.is_file())


def validate_folder_name(name: str) -> bool:
    """Validate folder name to prevent path traversal."""
    if not name:
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return True


@router.get("/ripped", response_model=RippedListResponse)
async def list_ripped_folders() -> RippedListResponse:
    """List folders in ripped directory with metadata."""
    ripped_dir = get_ripped_dir()

    if not ripped_dir.exists():
        return RippedListResponse(folders=[], total_size=0)

    folders = []
    total_size = 0

    for entry in sorted(ripped_dir.iterdir()):
        if entry.is_dir():
            size = get_folder_size(entry)
            total_size += size

            folders.append(FolderInfo(
                name=entry.name,
                size=size,
                file_count=count_files(entry),
                age_days=get_folder_age_days(entry),
                transcode_status="unknown",  # TODO: check jobs table
            ))

    return RippedListResponse(folders=folders, total_size=total_size)


@router.delete("/ripped", response_model=DeleteResponse)
async def delete_ripped_folders(request: DeleteRequest) -> DeleteResponse:
    """Delete selected folders from ripped directory."""
    ripped_dir = get_ripped_dir()
    deleted = 0
    errors = []

    for name in request.folders:
        # Validate to prevent path traversal
        if not validate_folder_name(name):
            raise HTTPException(status_code=400, detail=f"Invalid folder name: {name}")

        folder_path = ripped_dir / name

        if not folder_path.exists():
            errors.append(f"Folder not found: {name}")
            continue

        if not folder_path.is_relative_to(ripped_dir):
            raise HTTPException(status_code=400, detail=f"Path traversal detected: {name}")

        try:
            shutil.rmtree(folder_path)
            deleted += 1
        except OSError as e:
            errors.append(f"Failed to delete {name}: {e}")

    return DeleteResponse(deleted=deleted, errors=errors)
```

Register router in `src/amphigory/api/__init__.py`.

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_cleanup_api.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/cleanup.py src/amphigory/api/__init__.py tests/test_cleanup_api.py
git commit -m "feat: add cleanup API for ripped files"
```

---

## Task 8: Cleanup API - Inbox Files

**Files:**
- Modify: `src/amphigory/api/cleanup.py`
- Modify: `tests/test_cleanup_api.py`

**Goal:** GET /api/cleanup/inbox and POST /api/cleanup/inbox/move endpoints.

**Step 1: Write failing tests**

Add to `tests/test_cleanup_api.py`:

```python
@pytest.fixture
def mock_inbox_and_plex(tmp_path, monkeypatch):
    """Create mock inbox and Plex directories."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    plex = tmp_path / "plex"
    (plex / "Movies").mkdir(parents=True)
    (plex / "TV-Shows").mkdir(parents=True)

    # Movie in inbox
    movie = inbox / "Coco (2017) {imdb-tt2380307}"
    movie.mkdir()
    (movie / "Coco (2017) {imdb-tt2380307}.mp4").write_bytes(b"x" * 1000)

    monkeypatch.setenv("AMPHIGORY_INBOX_DIR", str(inbox))
    monkeypatch.setenv("AMPHIGORY_PLEX_DIR", str(plex))
    return {"inbox": inbox, "plex": plex}


@pytest.mark.asyncio
async def test_list_inbox_folders(mock_inbox_and_plex):
    """GET /api/cleanup/inbox returns folders by destination."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/inbox")

    assert response.status_code == 200
    data = response.json()
    assert "Movies" in data["sections"]


@pytest.mark.asyncio
async def test_move_inbox_to_plex(mock_inbox_and_plex):
    """POST /api/cleanup/inbox/move moves folders to Plex."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cleanup/inbox/move",
            json={
                "folders": ["Coco (2017) {imdb-tt2380307}"],
                "destination": "Movies",
            },
        )

    assert response.status_code == 200
    assert response.json()["moved"] == 1

    # Verify moved
    plex_movies = mock_inbox_and_plex["plex"] / "Movies"
    assert (plex_movies / "Coco (2017) {imdb-tt2380307}").exists()
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_cleanup_api.py::test_list_inbox_folders -v
PYTHONPATH=src .venv/bin/pytest tests/test_cleanup_api.py::test_move_inbox_to_plex -v
```

Expected: FAIL - endpoints don't exist

**Step 3: Add inbox endpoints**

Add to `src/amphigory/api/cleanup.py`:

```python
def get_plex_dir() -> Path:
    """Get Plex library directory from environment."""
    return Path(os.environ.get("AMPHIGORY_PLEX_DIR", "/media/plex/data"))


class InboxSection(BaseModel):
    """Folders in one section of inbox."""
    folders: List[FolderInfo]
    total_size: int


class InboxListResponse(BaseModel):
    """Response for listing inbox folders by section."""
    sections: dict[str, InboxSection]


class MoveRequest(BaseModel):
    """Request to move folders to Plex."""
    folders: List[str]
    destination: str  # "Movies", "TV-Shows", "Music"


class MoveResponse(BaseModel):
    """Response after moving."""
    moved: int
    errors: List[str]


def infer_plex_destination(folder_name: str) -> str:
    """Infer Plex destination based on folder name/content.

    For now, default to Movies. TODO: detect TV shows by pattern.
    """
    return "Movies"


@router.get("/inbox", response_model=InboxListResponse)
async def list_inbox_folders() -> InboxListResponse:
    """List folders in inbox directory grouped by destination."""
    inbox_dir = get_inbox_dir()

    if not inbox_dir.exists():
        return InboxListResponse(sections={})

    sections: dict[str, list[FolderInfo]] = {
        "Movies": [],
        "TV-Shows": [],
        "Music": [],
    }
    section_sizes: dict[str, int] = {"Movies": 0, "TV-Shows": 0, "Music": 0}

    for entry in sorted(inbox_dir.iterdir()):
        if entry.is_dir():
            size = get_folder_size(entry)
            dest = infer_plex_destination(entry.name)

            folder_info = FolderInfo(
                name=entry.name,
                size=size,
                file_count=count_files(entry),
                age_days=get_folder_age_days(entry),
            )

            sections[dest].append(folder_info)
            section_sizes[dest] += size

    # Build response with only non-empty sections
    result = {}
    for section_name, folders in sections.items():
        if folders:
            result[section_name] = InboxSection(
                folders=folders,
                total_size=section_sizes[section_name],
            )

    return InboxListResponse(sections=result)


@router.post("/inbox/move", response_model=MoveResponse)
async def move_inbox_to_plex(request: MoveRequest) -> MoveResponse:
    """Move folders from inbox to Plex library."""
    inbox_dir = get_inbox_dir()
    plex_dir = get_plex_dir()

    # Validate destination
    valid_destinations = ["Movies", "TV-Shows", "Music"]
    if request.destination not in valid_destinations:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid destination. Must be one of: {valid_destinations}",
        )

    dest_dir = plex_dir / request.destination
    if not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    errors = []

    for name in request.folders:
        if not validate_folder_name(name):
            raise HTTPException(status_code=400, detail=f"Invalid folder name: {name}")

        source = inbox_dir / name
        target = dest_dir / name

        if not source.exists():
            errors.append(f"Folder not found: {name}")
            continue

        try:
            shutil.move(str(source), str(target))
            moved += 1
        except OSError as e:
            errors.append(f"Failed to move {name}: {e}")

    return MoveResponse(moved=moved, errors=errors)
```

**Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_cleanup_api.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/cleanup.py tests/test_cleanup_api.py
git commit -m "feat: add cleanup API for inbox files with move to Plex"
```

---

## Task 9: Cleanup HTML Page

**Files:**
- Create: `src/amphigory/templates/cleanup.html`
- Modify: `src/amphigory/main.py`
- Modify: `src/amphigory/templates/base.html`

**Goal:** HTML page with tabs for Ripped and Inbox management.

**Step 1: Write failing test**

Add to `tests/test_main.py`:

```python
@pytest.mark.asyncio
async def test_cleanup_page_loads(client):
    """Cleanup page loads successfully."""
    response = await client.get("/cleanup")
    assert response.status_code == 200
    assert "Cleanup" in response.text
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_main.py::test_cleanup_page_loads -v
```

**Step 3: Create template and route**

Create `src/amphigory/templates/cleanup.html`:

```html
{% extends "base.html" %}

{% block title %}Cleanup - Amphigory{% endblock %}

{% block content %}
<div class="cleanup-page">
    <h1>Cleanup</h1>

    <!-- Tabs -->
    <div class="tabs">
        <button class="tab active" onclick="showTab('ripped')">Ripped Files</button>
        <button class="tab" onclick="showTab('inbox')">Inbox</button>
    </div>

    <!-- Ripped Tab -->
    <div id="ripped-tab" class="tab-content active">
        <div class="tab-header">
            <button onclick="deleteSelected('ripped')" class="btn btn-danger" id="delete-ripped-btn" disabled>
                Delete Selected
            </button>
            <span id="ripped-selection-info"></span>
        </div>

        <div id="ripped-list"
             hx-get="/api/cleanup/ripped/html"
             hx-trigger="load"
             hx-target="#ripped-list">
            <p>Loading...</p>
        </div>

        <div class="footer" id="ripped-footer">
            Total: <span id="ripped-total-size">-</span> |
            Selected: <span id="ripped-selected-size">0 B</span> (<span id="ripped-selected-count">0</span> folders)
        </div>
    </div>

    <!-- Inbox Tab -->
    <div id="inbox-tab" class="tab-content">
        <div class="tab-header">
            <button onclick="moveSelected()" class="btn btn-primary" id="move-inbox-btn" disabled>
                Move to Plex
            </button>
            <button onclick="deleteSelected('inbox')" class="btn btn-danger" id="delete-inbox-btn" disabled>
                Delete Selected
            </button>
        </div>

        <div id="inbox-list"
             hx-get="/api/cleanup/inbox/html"
             hx-trigger="load"
             hx-target="#inbox-list">
            <p>Loading...</p>
        </div>
    </div>
</div>

<script>
const selectedRipped = new Set();
const selectedInbox = new Set();

function showTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));

    document.querySelector(`[onclick="showTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`${tabName}-tab`).classList.add('active');
}

function toggleFolder(checkbox, tab, folderName, size) {
    const set = tab === 'ripped' ? selectedRipped : selectedInbox;

    if (checkbox.checked) {
        set.add({name: folderName, size: size});
    } else {
        set.forEach(item => {
            if (item.name === folderName) set.delete(item);
        });
    }

    updateSelectionInfo(tab);
}

function updateSelectionInfo(tab) {
    const set = tab === 'ripped' ? selectedRipped : selectedInbox;
    const totalSize = Array.from(set).reduce((sum, item) => sum + item.size, 0);
    const count = set.size;

    if (tab === 'ripped') {
        document.getElementById('ripped-selected-size').textContent = formatSize(totalSize);
        document.getElementById('ripped-selected-count').textContent = count;
        document.getElementById('delete-ripped-btn').disabled = count === 0;
    } else {
        document.getElementById('move-inbox-btn').disabled = count === 0;
        document.getElementById('delete-inbox-btn').disabled = count === 0;
    }
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

async function deleteSelected(tab) {
    const set = tab === 'ripped' ? selectedRipped : selectedInbox;
    const folders = Array.from(set).map(item => item.name);

    if (!confirm(`Delete ${folders.length} folder(s)?`)) return;

    const endpoint = tab === 'ripped' ? '/api/cleanup/ripped' : '/api/cleanup/inbox';

    const response = await fetch(endpoint, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({folders}),
    });

    if (response.ok) {
        set.clear();
        htmx.trigger(`#${tab}-list`, 'refresh');
        updateSelectionInfo(tab);
    }
}

async function moveSelected() {
    const folders = Array.from(selectedInbox).map(item => item.name);
    const destination = prompt('Destination (Movies, TV-Shows, Music):', 'Movies');
    if (!destination) return;

    const response = await fetch('/api/cleanup/inbox/move', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({folders, destination}),
    });

    if (response.ok) {
        selectedInbox.clear();
        htmx.trigger('#inbox-list', 'refresh');
        updateSelectionInfo('inbox');
    }
}
</script>

<style>
.tabs {
    display: flex;
    border-bottom: 2px solid var(--border-color);
    margin-bottom: 1rem;
}

.tab {
    padding: 0.75rem 1.5rem;
    border: none;
    background: none;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
}

.tab.active {
    border-bottom-color: var(--primary-color);
    font-weight: bold;
}

.tab-content {
    display: none;
}

.tab-content.active {
    display: block;
}

.tab-header {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    align-items: center;
}

.folder-table {
    width: 100%;
    border-collapse: collapse;
}

.folder-table th, .folder-table td {
    padding: 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
}

.footer {
    margin-top: 1rem;
    padding: 0.5rem;
    background: var(--bg-secondary);
    border-radius: 4px;
}

.section-header {
    font-weight: bold;
    padding: 0.5rem;
    background: var(--bg-secondary);
    margin-top: 1rem;
}
</style>
{% endblock %}
```

Add HTML endpoints to cleanup.py and route to main.py.

**Step 4: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_main.py::test_cleanup_page_loads -v
```

**Step 5: Commit**

```bash
git add src/amphigory/templates/cleanup.html src/amphigory/main.py src/amphigory/api/cleanup.py src/amphigory/templates/base.html
git commit -m "feat: add cleanup page with ripped and inbox tabs"
```

---

## Task 10: Wiki Generator Service

**Files:**
- Create: `src/amphigory/wiki.py`
- Create: `tests/test_wiki.py`

**Goal:** Service to generate markdown wiki pages for discs.

**Step 1: Write failing tests**

Create `tests/test_wiki.py`:

```python
"""Tests for wiki generation."""

import pytest
from pathlib import Path
from amphigory.wiki import WikiGenerator


@pytest.fixture
def wiki_dir(tmp_path):
    return tmp_path / "wiki" / "Media Library"


@pytest.fixture
def generator(wiki_dir):
    return WikiGenerator(wiki_dir)


class TestDiscPageGeneration:
    def test_generates_disc_page(self, generator, wiki_dir):
        """Generate creates markdown file for disc."""
        disc = {
            "title": "Coco",
            "year": 2017,
            "disc_type": "bluray",
            "media_type": "movie",
            "imdb_id": "tt2380307",
            "tmdb_id": "354912",
            "processed_at": "2024-12-25T10:00:00",
        }
        tracks = [
            {"track_number": 1, "track_type": "main_feature", "duration_seconds": 6300,
             "resolution": "1080p", "status": "complete", "preset_name": "bluray-h265",
             "final_name": "Coco (2017) {imdb-tt2380307}.mkv"},
        ]

        path = generator.generate_disc_page(disc, tracks)

        assert path.exists()
        assert path.name == "Coco-2017.md"

        content = path.read_text()
        assert "# Coco (2017)" in content
        assert "tt2380307" in content
        assert "| 1 |" in content

    def test_page_in_media_type_folder(self, generator, wiki_dir):
        """Disc page created in correct media type folder."""
        disc = {"title": "Test", "year": 2020, "media_type": "movie"}

        path = generator.generate_disc_page(disc, [])

        assert path.parent.name == "Movies"


class TestIndexGeneration:
    def test_generates_index(self, generator, wiki_dir):
        """Generate creates Home.md index."""
        # Create some disc pages first
        discs = [
            {"title": "Coco", "year": 2017, "disc_type": "bluray", "media_type": "movie"},
            {"title": "Old Movie", "year": 1990, "disc_type": "dvd", "media_type": "movie"},
        ]
        for disc in discs:
            generator.generate_disc_page(disc, [])

        path = generator.generate_index()

        assert path.exists()
        assert path.name == "Home.md"

        content = path.read_text()
        assert "# Media Library" in content
        assert "## Movies" in content
        assert "### Blu-ray" in content
        assert "[Coco (2017)]" in content

    def test_index_omits_empty_sections(self, generator, wiki_dir):
        """Index doesn't include sections with no content."""
        disc = {"title": "Test", "year": 2020, "disc_type": "bluray", "media_type": "movie"}
        generator.generate_disc_page(disc, [])

        path = generator.generate_index()
        content = path.read_text()

        assert "## TV Shows" not in content
        assert "## Music" not in content
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_wiki.py -v
```

**Step 3: Implement wiki.py**

Create `src/amphigory/wiki.py`:

```python
"""Wiki generation for Gollum integration."""

from pathlib import Path
from typing import List, Optional
import re


class WikiGenerator:
    """Generates markdown wiki pages for processed discs."""

    MEDIA_TYPE_DIRS = {
        "movie": "Movies",
        "tv": "TV-Shows",
        "music": "Music",
    }

    DISC_TYPE_ORDER = ["uhd", "bluray", "dvd"]
    DISC_TYPE_LABELS = {
        "uhd": "UHD",
        "bluray": "Blu-ray",
        "dvd": "DVD",
    }

    def __init__(self, wiki_dir: Path | str):
        self.wiki_dir = Path(wiki_dir)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize string for use as filename."""
        # Replace spaces with hyphens, remove special chars
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"\s+", "-", name)
        return name

    def _format_duration(self, seconds: Optional[int]) -> str:
        """Format duration in HH:MM:SS."""
        if not seconds:
            return "-"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"

    def generate_disc_page(
        self,
        disc: dict,
        tracks: List[dict],
        notes: str = "",
    ) -> Path:
        """Generate markdown page for a disc.

        Args:
            disc: Disc data dict
            tracks: List of track dicts
            notes: Optional user notes

        Returns:
            Path to generated file
        """
        title = disc.get("title", "Unknown")
        year = disc.get("year", "")
        media_type = disc.get("media_type", "movie")

        # Determine output path
        media_dir = self.wiki_dir / self.MEDIA_TYPE_DIRS.get(media_type, "Movies")
        media_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{self._sanitize_filename(title)}-{year}.md"
        filepath = media_dir / filename

        # Build page content
        lines = [
            f"# {title} ({year})" if year else f"# {title}",
            "",
            "| Field | Value |",
            "|-------|-------|",
        ]

        if disc.get("imdb_id"):
            lines.append(f"| IMDB | [{ disc['imdb_id'] }](https://imdb.com/title/{ disc['imdb_id'] }) |")
        if disc.get("tmdb_id"):
            lines.append(f"| TMDB | [{ disc['tmdb_id'] }](https://themoviedb.org/movie/{ disc['tmdb_id'] }) |")
        if disc.get("disc_type"):
            lines.append(f"| Disc Type | {self.DISC_TYPE_LABELS.get(disc['disc_type'], disc['disc_type'])} |")
        if disc.get("processed_at"):
            lines.append(f"| Processed | {disc['processed_at'][:10]} |")

        # Tracks table
        if tracks:
            lines.extend([
                "",
                "## Tracks",
                "",
                "| # | Type | Duration | Resolution | Ripped | Preset | Final Name |",
                "|---|------|----------|------------|--------|--------|------------|",
            ])

            for track in tracks:
                ripped = "✓" if track.get("status") == "complete" else "✗"
                lines.append(
                    f"| {track.get('track_number', '-')} "
                    f"| {track.get('track_type', '-')} "
                    f"| {self._format_duration(track.get('duration_seconds'))} "
                    f"| {track.get('resolution', '-')} "
                    f"| {ripped} "
                    f"| {track.get('preset_name', '-')} "
                    f"| {track.get('final_name', '-')} |"
                )

        # Notes
        lines.extend([
            "",
            "## Notes",
            "",
            notes or "_(No notes)_",
        ])

        filepath.write_text("\n".join(lines))
        return filepath

    def generate_index(self) -> Path:
        """Generate Home.md index page.

        Returns:
            Path to Home.md
        """
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        index_path = self.wiki_dir / "Home.md"

        lines = ["# Media Library", ""]

        # Collect disc pages by media type and disc type
        for media_type, dir_name in self.MEDIA_TYPE_DIRS.items():
            media_dir = self.wiki_dir / dir_name
            if not media_dir.exists():
                continue

            disc_files = list(media_dir.glob("*.md"))
            if not disc_files:
                continue

            # Parse disc files to get metadata
            discs_by_type: dict[str, list[tuple[str, str, Path]]] = {}

            for filepath in disc_files:
                # Extract title and year from filename (Title-Year.md)
                name = filepath.stem
                parts = name.rsplit("-", 1)
                if len(parts) == 2:
                    title = parts[0].replace("-", " ")
                    year = parts[1]
                else:
                    title = name.replace("-", " ")
                    year = ""

                # Try to infer disc type from content
                content = filepath.read_text()
                disc_type = "dvd"  # default
                if "UHD" in content:
                    disc_type = "uhd"
                elif "Blu-ray" in content:
                    disc_type = "bluray"

                if disc_type not in discs_by_type:
                    discs_by_type[disc_type] = []
                discs_by_type[disc_type].append((title, year, filepath))

            if not discs_by_type:
                continue

            # Add media type section
            section_title = {"movie": "Movies", "tv": "TV Shows", "music": "Music"}.get(media_type, media_type)
            lines.extend([f"## {section_title}", ""])

            # Add disc type subsections in order
            for disc_type in self.DISC_TYPE_ORDER:
                if disc_type not in discs_by_type:
                    continue

                label = self.DISC_TYPE_LABELS.get(disc_type, disc_type)
                lines.extend([f"### {label}", ""])

                for title, year, filepath in sorted(discs_by_type[disc_type]):
                    rel_path = filepath.relative_to(self.wiki_dir)
                    display = f"{title} ({year})" if year else title
                    lines.append(f"- [{display}]({rel_path})")

                lines.append("")

        index_path.write_text("\n".join(lines))
        return index_path
```

**Step 4: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_wiki.py -v
```

**Step 5: Commit**

```bash
git add src/amphigory/wiki.py tests/test_wiki.py
git commit -m "feat: add wiki generator for Gollum integration"
```

---

## Task 11: Wiki API Endpoints

**Files:**
- Create: `src/amphigory/api/wiki.py`
- Create: `tests/test_wiki_api.py`

**Goal:** POST /api/wiki/generate and POST /api/wiki/rebuild-index endpoints.

**Step 1: Write failing tests**

Create `tests/test_wiki_api.py`:

```python
"""Tests for Wiki API."""

import pytest
from httpx import AsyncClient, ASGITransport
from amphigory.main import app
from amphigory.database import Database


@pytest.fixture
async def seeded_db_with_disc(tmp_path):
    """Database with a processed disc."""
    db = Database(tmp_path / "test.db")
    await db.initialize()

    async with db.connection() as conn:
        await conn.execute(
            """INSERT INTO discs (id, title, year, disc_type, media_type, imdb_id, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, "Coco", 2017, "bluray", "movie", "tt2380307", "2024-12-25"),
        )
        await conn.execute(
            """INSERT INTO tracks (disc_id, track_number, track_type, status, final_name)
               VALUES (?, ?, ?, ?, ?)""",
            (1, 1, "main_feature", "complete", "Coco (2017).mkv"),
        )
        await conn.commit()

    app.state.db = db
    app.state.wiki_dir = tmp_path / "wiki"
    yield db


@pytest.mark.asyncio
async def test_generate_disc_wiki_page(seeded_db_with_disc):
    """POST /api/wiki/generate creates disc wiki page."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/wiki/generate", json={"disc_id": 1})

    assert response.status_code == 200
    assert "path" in response.json()


@pytest.mark.asyncio
async def test_rebuild_wiki_index(seeded_db_with_disc):
    """POST /api/wiki/rebuild-index regenerates Home.md."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First generate a disc page
        await client.post("/api/wiki/generate", json={"disc_id": 1})

        # Then rebuild index
        response = await client.post("/api/wiki/rebuild-index")

    assert response.status_code == 200
    assert "path" in response.json()
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_wiki_api.py -v
```

**Step 3: Implement wiki API**

Create `src/amphigory/api/wiki.py`:

```python
"""Wiki API for generating Gollum wiki pages."""

from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from amphigory.wiki import WikiGenerator

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


class GenerateRequest(BaseModel):
    """Request to generate a disc page."""
    disc_id: int
    notes: str = ""


class GenerateResponse(BaseModel):
    """Response with generated path."""
    path: str


@router.post("/generate", response_model=GenerateResponse)
async def generate_disc_page(request: Request, body: GenerateRequest) -> GenerateResponse:
    """Generate wiki page for a disc."""
    db = request.app.state.db
    wiki_dir = getattr(request.app.state, "wiki_dir", Path("/data/wiki/Media Library"))

    async with db.connection() as conn:
        cursor = await conn.execute("SELECT * FROM discs WHERE id = ?", (body.disc_id,))
        disc = await cursor.fetchone()

        if not disc:
            raise HTTPException(status_code=404, detail="Disc not found")

        cursor = await conn.execute(
            "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
            (body.disc_id,),
        )
        tracks = [dict(row) for row in await cursor.fetchall()]

    generator = WikiGenerator(wiki_dir)
    path = generator.generate_disc_page(dict(disc), tracks, body.notes)

    return GenerateResponse(path=str(path))


@router.post("/rebuild-index", response_model=GenerateResponse)
async def rebuild_index(request: Request) -> GenerateResponse:
    """Rebuild the wiki index page."""
    wiki_dir = getattr(request.app.state, "wiki_dir", Path("/data/wiki/Media Library"))

    generator = WikiGenerator(wiki_dir)
    path = generator.generate_index()

    return GenerateResponse(path=str(path))
```

Register in `__init__.py`.

**Step 4: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_wiki_api.py -v
```

**Step 5: Commit**

```bash
git add src/amphigory/api/wiki.py src/amphigory/api/__init__.py tests/test_wiki_api.py
git commit -m "feat: add wiki API for generating Gollum pages"
```

---

## Task 12: Transcode Job Runner

**Files:**
- Create: `src/amphigory/job_runner.py`
- Create: `tests/test_job_runner.py`

**Goal:** Background asyncio task that polls jobs table and runs transcodes.

**Step 1: Write failing tests**

Create `tests/test_job_runner.py`:

```python
"""Tests for job runner."""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from amphigory.job_runner import JobRunner
from amphigory.database import Database
from amphigory.jobs import JobQueue, JobType, JobStatus


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database


@pytest.fixture
def mock_transcoder():
    with patch("amphigory.job_runner.TranscoderService") as mock:
        instance = mock.return_value
        instance.transcode = AsyncMock(return_value=True)
        yield instance


@pytest.mark.asyncio
async def test_runner_processes_queued_transcode_job(db, mock_transcoder, tmp_path):
    """Runner picks up and processes queued transcode job."""
    # Setup: create a track and job
    async with db.connection() as conn:
        await conn.execute(
            """INSERT INTO discs (id, title) VALUES (1, 'Test')"""
        )
        await conn.execute(
            """INSERT INTO tracks (id, disc_id, track_number, ripped_path, status)
               VALUES (1, 1, 1, ?, 'ripped')""",
            (str(tmp_path / "test.mkv"),),
        )
        await conn.commit()

    # Create ripped file
    (tmp_path / "test.mkv").write_bytes(b"fake video")

    # Queue a transcode job
    job_queue = JobQueue(db)
    job_id = await job_queue.create_job(track_id=1, job_type=JobType.TRANSCODE)

    # Run the runner for one iteration
    runner = JobRunner(db, inbox_dir=tmp_path / "inbox", preset_dir=tmp_path / "presets")
    runner.transcoder = mock_transcoder

    await runner.process_one_job()

    # Verify job completed
    job = await job_queue.get_job(job_id)
    assert job["status"] == JobStatus.COMPLETE.value


@pytest.mark.asyncio
async def test_runner_updates_track_status(db, mock_transcoder, tmp_path):
    """Runner updates track status after transcode."""
    async with db.connection() as conn:
        await conn.execute("INSERT INTO discs (id, title) VALUES (1, 'Test')")
        await conn.execute(
            """INSERT INTO tracks (id, disc_id, track_number, ripped_path, status)
               VALUES (1, 1, 1, ?, 'ripped')""",
            (str(tmp_path / "test.mkv"),),
        )
        await conn.commit()

    (tmp_path / "test.mkv").write_bytes(b"fake")

    job_queue = JobQueue(db)
    await job_queue.create_job(track_id=1, job_type=JobType.TRANSCODE)

    runner = JobRunner(db, inbox_dir=tmp_path / "inbox", preset_dir=tmp_path / "presets")
    runner.transcoder = mock_transcoder

    await runner.process_one_job()

    async with db.connection() as conn:
        cursor = await conn.execute("SELECT status FROM tracks WHERE id = 1")
        row = await cursor.fetchone()

    assert row["status"] == "complete"
```

**Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_job_runner.py -v
```

**Step 3: Implement job_runner.py**

Create `src/amphigory/job_runner.py`:

```python
"""Background job runner for transcoding."""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable

from amphigory.database import Database
from amphigory.jobs import JobQueue, JobType, JobStatus
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.presets import PresetManager
from amphigory.preset_selector import parse_resolution, recommend_preset

logger = logging.getLogger(__name__)


class JobRunner:
    """Runs transcode jobs from the queue."""

    def __init__(
        self,
        db: Database,
        inbox_dir: Path,
        preset_dir: Path,
        progress_callback: Optional[Callable[[int, TranscodeProgress], None]] = None,
    ):
        self.db = db
        self.inbox_dir = inbox_dir
        self.preset_dir = preset_dir
        self.progress_callback = progress_callback

        self.job_queue = JobQueue(db)
        self.transcoder = TranscoderService()
        self.preset_manager = PresetManager(preset_dir)

        self._running = False
        self._current_job_id: Optional[int] = None

    async def start(self) -> None:
        """Start the job runner loop."""
        self._running = True
        await self.preset_manager.load()

        logger.info("Job runner started")

        while self._running:
            try:
                await self.process_one_job()
            except Exception as e:
                logger.exception(f"Error processing job: {e}")

            await asyncio.sleep(5)  # Poll interval

    async def stop(self) -> None:
        """Stop the job runner."""
        self._running = False
        logger.info("Job runner stopped")

    async def process_one_job(self) -> bool:
        """Process the next available transcode job.

        Returns:
            True if a job was processed, False if queue was empty.
        """
        job = await self.job_queue.get_next_job(JobType.TRANSCODE)
        if not job:
            return False

        job_id = job["id"]
        track_id = job["track_id"]
        self._current_job_id = job_id

        logger.info(f"Starting transcode job {job_id} for track {track_id}")

        # Mark job as running
        await self.job_queue.update_job(job_id, status=JobStatus.RUNNING)

        try:
            # Get track info
            async with self.db.connection() as conn:
                cursor = await conn.execute(
                    """SELECT t.*, d.title, d.year, d.imdb_id
                       FROM tracks t
                       JOIN discs d ON t.disc_id = d.id
                       WHERE t.id = ?""",
                    (track_id,),
                )
                track = dict(await cursor.fetchone())

            ripped_path = Path(track["ripped_path"])
            if not ripped_path.exists():
                raise FileNotFoundError(f"Ripped file not found: {ripped_path}")

            # Determine output path and preset
            # TODO: Use naming module for proper output path
            output_dir = self.inbox_dir / f"{track['title']} ({track['year']})"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{ripped_path.stem}.mp4"

            # Get preset based on resolution
            resolution = parse_resolution(track.get("resolution"))
            if resolution:
                preset_category = recommend_preset(resolution[0], resolution[1])
            else:
                preset_category = "dvd"

            preset_name = self.preset_manager.get_active_preset(preset_category)
            preset_path = self.preset_manager.get_preset_path(preset_category)

            if not preset_name or not preset_path:
                # Fall back to first available preset
                presets = self.preset_manager.list_presets()
                if presets:
                    preset_name = presets[0].name
                    preset_path = presets[0].file_path
                else:
                    raise ValueError("No presets available")

            # Run transcode
            def on_progress(progress: TranscodeProgress):
                asyncio.create_task(
                    self.job_queue.update_job(job_id, progress=progress.percent)
                )
                if self.progress_callback:
                    self.progress_callback(job_id, progress)

            success = await self.transcoder.transcode(
                input_path=ripped_path,
                output_path=output_path,
                preset_path=preset_path,
                preset_name=preset_name,
                progress_callback=on_progress,
            )

            if success:
                # Update track
                async with self.db.connection() as conn:
                    await conn.execute(
                        """UPDATE tracks
                           SET status = 'complete',
                               transcoded_path = ?,
                               preset_name = ?
                           WHERE id = ?""",
                        (str(output_path), preset_name, track_id),
                    )
                    await conn.commit()

                await self.job_queue.update_job(job_id, status=JobStatus.COMPLETE, progress=100)
                logger.info(f"Transcode job {job_id} completed")
            else:
                raise RuntimeError("Transcode failed")

        except Exception as e:
            logger.exception(f"Transcode job {job_id} failed: {e}")
            await self.job_queue.update_job(
                job_id,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

        self._current_job_id = None
        return True
```

**Step 4: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_job_runner.py -v
```

**Step 5: Commit**

```bash
git add src/amphigory/job_runner.py tests/test_job_runner.py
git commit -m "feat: add background job runner for transcoding"
```

---

## Task 13: Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Goal:** Add integration tests for full pipeline flow.

**Step 1: Write integration tests**

Add to `tests/test_integration.py`:

```python
class TestPhase3Integration:
    """Integration tests for Phase 3 pipeline."""

    @pytest.mark.asyncio
    async def test_process_disc_to_library(self, client, tmp_path):
        """Full flow: scan → process → appears in library."""
        # This test would require significant setup
        # Mock scan result, process tracks, verify library listing
        pass

    @pytest.mark.asyncio
    async def test_cleanup_after_transcode(self, client, tmp_path):
        """Cleanup page shows transcoded files as deletable."""
        pass

    @pytest.mark.asyncio
    async def test_wiki_generated_on_process(self, client, tmp_path):
        """Wiki page created when disc processing completes."""
        pass
```

**Step 2: Implement meaningful integration tests**

(Detailed implementation depends on full system setup)

**Step 3: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py::TestPhase3Integration -v
```

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add Phase 3 integration tests"
```

---

## Task 14: Playwright Setup

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_disc_review.py`
- Modify: `pyproject.toml` (add playwright dependency)

**Goal:** Set up Playwright for UI testing.

**Step 1: Add dependency**

Add to `pyproject.toml` dev dependencies:

```toml
pytest-playwright = ">=0.4.0"
```

**Step 2: Create conftest**

Create `tests/e2e/conftest.py`:

```python
"""Playwright test configuration."""

import pytest
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser

from amphigory.main import app
from amphigory.database import Database


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser: Browser):
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()


@pytest.fixture
async def test_server(tmp_path):
    """Start test server with seeded database."""
    import uvicorn
    from multiprocessing import Process

    db = Database(tmp_path / "test.db")
    await db.initialize()
    app.state.db = db

    def run():
        uvicorn.run(app, host="127.0.0.1", port=8765)

    process = Process(target=run)
    process.start()

    await asyncio.sleep(1)  # Wait for server to start

    yield "http://127.0.0.1:8765"

    process.terminate()
    process.join()
```

**Step 3: Create basic UI test**

Create `tests/e2e/test_disc_review.py`:

```python
"""Playwright tests for Disc Review page."""

import pytest
from playwright.async_api import Page, expect


@pytest.mark.asyncio
async def test_disc_page_loads(page: Page, test_server: str):
    """Disc review page loads successfully."""
    await page.goto(f"{test_server}/disc")
    await expect(page.locator("h1")).to_contain_text("Disc Review")


@pytest.mark.asyncio
async def test_library_page_filters(page: Page, test_server: str):
    """Library page filters work."""
    await page.goto(f"{test_server}/library")

    # Check filter dropdowns exist
    await expect(page.locator("#status-filter")).to_be_visible()
    await expect(page.locator("#disc-type-filter")).to_be_visible()
```

**Step 4: Run Playwright tests**

```bash
# Install browsers first
playwright install chromium

# Run tests
PYTHONPATH=src .venv/bin/pytest tests/e2e/ -v
```

**Step 5: Commit**

```bash
git add tests/e2e/ pyproject.toml
git commit -m "test: add Playwright setup and basic UI tests"
```

---

## Execution Order Summary

1. **Task 1:** Database Schema Extensions
2. **Task 2:** Preset Selector
3. **Task 3:** Enhanced Naming
4. **Task 4:** Library API - List/Filter
5. **Task 5:** Library API - Detail/Flag
6. **Task 6:** Library HTML Page
7. **Task 7:** Cleanup API - Ripped
8. **Task 8:** Cleanup API - Inbox
9. **Task 9:** Cleanup HTML Page
10. **Task 10:** Wiki Generator
11. **Task 11:** Wiki API
12. **Task 12:** Transcode Job Runner
13. **Task 13:** Integration Tests
14. **Task 14:** Playwright Setup

Tasks 1-3 are foundational. Tasks 4-11 are largely independent features. Task 12 ties transcoding together. Tasks 13-14 verify everything works.
