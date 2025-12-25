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
            """INSERT INTO discs (title, year, disc_type, media_type, fingerprint, processed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("Unprocessed Disc", 2020, "dvd", "movie", "fp123", None),
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
