"""Tests for disc repository functions."""

import pytest
import json
from datetime import datetime
from pathlib import Path
from amphigory.database import Database
from amphigory.api import disc_repository


@pytest.fixture
async def db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def db_path(tmp_path, db):
    """Provide database path for repository functions."""
    db_path = tmp_path / "test.db"
    # Temporarily set the db path for the repository module
    original_get_db = disc_repository.get_db_path
    disc_repository.get_db_path = lambda: db_path
    yield db_path
    disc_repository.get_db_path = original_get_db


class TestGetDiscByFingerprint:
    """Tests for get_disc_by_fingerprint function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disc_not_found(self, db, db_path):
        """Returns None when no disc matches fingerprint."""
        result = await disc_repository.get_disc_by_fingerprint("nonexistent_fp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_disc_when_found(self, db, db_path):
        """Returns disc data when fingerprint matches."""
        # Insert a test disc
        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint, year, disc_type, imdb_id)
                   VALUES (?, ?, ?, ?, ?)""",
                ("Test Movie", "fp_test123", 2020, "bluray", "tt1234567"),
            )
            await conn.commit()

        result = await disc_repository.get_disc_by_fingerprint("fp_test123")

        assert result is not None
        assert result["title"] == "Test Movie"
        assert result["fingerprint"] == "fp_test123"
        assert result["year"] == 2020
        assert result["disc_type"] == "bluray"
        assert result["imdb_id"] == "tt1234567"
        assert "id" in result

    @pytest.mark.asyncio
    async def test_returns_disc_with_scan_data(self, db, db_path):
        """Returns disc with scan_data as JSON."""
        scan_data = {
            "disc_name": "TEST_DISC",
            "tracks": [{"index": 0, "duration": 7200}]
        }

        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint, scan_data)
                   VALUES (?, ?, ?)""",
                ("Movie with Scan", "fp_scan123", json.dumps(scan_data)),
            )
            await conn.commit()

        result = await disc_repository.get_disc_by_fingerprint("fp_scan123")

        assert result is not None
        assert result["title"] == "Movie with Scan"
        assert result["scan_data"] == json.dumps(scan_data)


class TestSaveDiscScan:
    """Tests for save_disc_scan function."""

    @pytest.mark.asyncio
    async def test_creates_new_disc_with_scan_data(self, db, db_path):
        """Creates new disc when fingerprint doesn't exist."""
        scan_data = {
            "disc_name": "NEW_DISC_2020",
            "tracks": [{"index": 0, "duration": 5400}]
        }

        disc_id = await disc_repository.save_disc_scan(
            "fp_new123",
            scan_data,
            title="New Movie"
        )

        assert disc_id > 0

        # Verify disc was created
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM discs WHERE id = ?",
                (disc_id,)
            )
            row = await cursor.fetchone()

            assert row is not None
            assert row["title"] == "New Movie"
            assert row["fingerprint"] == "fp_new123"
            assert row["scan_data"] == json.dumps(scan_data)
            assert row["scanned_at"] is not None

    @pytest.mark.asyncio
    async def test_uses_disc_name_from_scan_data_when_no_title(self, db, db_path):
        """Uses disc_name from scan_data when title not provided."""
        scan_data = {
            "disc_name": "AUTO_TITLE_DISC",
            "tracks": []
        }

        disc_id = await disc_repository.save_disc_scan(
            "fp_auto123",
            scan_data
        )

        # Verify disc was created with disc_name as title
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT title FROM discs WHERE id = ?",
                (disc_id,)
            )
            row = await cursor.fetchone()

            assert row["title"] == "AUTO_TITLE_DISC"

    @pytest.mark.asyncio
    async def test_updates_existing_disc_scan_data(self, db, db_path):
        """Updates scan_data when disc already exists."""
        # Create initial disc
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint, scan_data)
                   VALUES (?, ?, ?)""",
                ("Existing Movie", "fp_existing123", json.dumps({"old": "data"})),
            )
            await conn.commit()
            existing_id = cursor.lastrowid

        # Update with new scan data
        new_scan_data = {
            "disc_name": "UPDATED_DISC",
            "tracks": [{"index": 0, "duration": 9000}]
        }

        disc_id = await disc_repository.save_disc_scan(
            "fp_existing123",
            new_scan_data
        )

        # Should return same ID
        assert disc_id == existing_id

        # Verify scan_data was updated
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT scan_data, scanned_at FROM discs WHERE id = ?",
                (disc_id,)
            )
            row = await cursor.fetchone()

            assert row["scan_data"] == json.dumps(new_scan_data)
            assert row["scanned_at"] is not None

    @pytest.mark.asyncio
    async def test_preserves_title_when_updating(self, db, db_path):
        """Preserves original title when updating existing disc."""
        # Create initial disc
        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Original Title", "fp_preserve123"),
            )
            await conn.commit()

        # Update scan data without providing title
        scan_data = {"disc_name": "DIFFERENT_NAME"}
        await disc_repository.save_disc_scan("fp_preserve123", scan_data)

        # Verify title wasn't changed
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT title FROM discs WHERE fingerprint = ?",
                ("fp_preserve123",)
            )
            row = await cursor.fetchone()

            assert row["title"] == "Original Title"


class TestGetDiscScanData:
    """Tests for get_disc_scan_data function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disc_not_found(self, db, db_path):
        """Returns None when no disc matches fingerprint."""
        result = await disc_repository.get_disc_scan_data("nonexistent_fp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_scan_data(self, db, db_path):
        """Returns None when disc exists but has no scan_data."""
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("No Scan Data", "fp_noscan123"),
            )
            await conn.commit()

        result = await disc_repository.get_disc_scan_data("fp_noscan123")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_parsed_scan_data(self, db, db_path):
        """Returns scan_data as parsed JSON dict."""
        scan_data = {
            "disc_name": "SCAN_DATA_TEST",
            "tracks": [
                {"index": 0, "duration": 7200, "title": "Main Feature"},
                {"index": 1, "duration": 300, "title": "Bonus"}
            ],
            "metadata": {"disc_size_mb": 45000}
        }

        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint, scan_data)
                   VALUES (?, ?, ?)""",
                ("Movie", "fp_getscan123", json.dumps(scan_data)),
            )
            await conn.commit()

        result = await disc_repository.get_disc_scan_data("fp_getscan123")

        assert result is not None
        assert isinstance(result, dict)
        assert result == scan_data
        assert result["disc_name"] == "SCAN_DATA_TEST"
        assert len(result["tracks"]) == 2
        assert result["metadata"]["disc_size_mb"] == 45000
