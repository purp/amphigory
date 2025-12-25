"""Tests for database initialization and models."""

import pytest
import tempfile
import os
from pathlib import Path
from amphigory.database import Database


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
async def db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


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

            # Try to insert duplicate fingerprint - should raise
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

    @pytest.mark.asyncio
    async def test_fingerprint_can_be_null(self, db):
        """Fingerprint can be null for discs added before fingerprinting."""
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO discs (title) VALUES (?)",
                ("Old Movie",),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT fingerprint FROM discs WHERE title = ?",
                ("Old Movie",),
            )
            row = await cursor.fetchone()

            assert row["fingerprint"] is None
