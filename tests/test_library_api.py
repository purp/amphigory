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
