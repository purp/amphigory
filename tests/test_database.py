"""Tests for database initialization and models."""

import pytest
import tempfile
import os
from pathlib import Path
import aiosqlite
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


class TestSchemaExtensions:
    @pytest.mark.asyncio
    async def test_tracks_table_has_classification_columns(self):
        """Tracks table includes classification and metadata columns."""
        from amphigory.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.db")
            await db.initialize()

            async with db.connection() as conn:
                cursor = await conn.execute("PRAGMA table_info(tracks)")
                columns = {row[1] for row in await cursor.fetchall()}

            # New columns for classification
            assert "track_name" in columns
            assert "classification_confidence" in columns
            assert "language" in columns
            assert "resolution" in columns
            assert "audio_tracks" in columns
            assert "subtitle_tracks" in columns
            assert "chapter_count" in columns
            assert "segment_map" in columns

            # TV show columns
            assert "season_number" in columns
            assert "episode_number" in columns
            assert "episode_end_number" in columns
            assert "air_date" in columns

    @pytest.mark.asyncio
    async def test_discs_table_has_media_type_columns(self):
        """Discs table includes media type and external ID columns."""
        from amphigory.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.db")
            await db.initialize()

            async with db.connection() as conn:
                cursor = await conn.execute("PRAGMA table_info(discs)")
                columns = {row[1] for row in await cursor.fetchall()}

            assert "media_type" in columns
            assert "show_name" in columns
            assert "tmdb_id" in columns
            assert "tvdb_id" in columns


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

        # SQLite stores BOOLEAN TRUE as 1
        assert row["needs_reprocessing"] == 1
        assert row["reprocessing_type"] == "re-transcode"
        assert row["reprocessing_notes"] == "comb artifacts on extras"

    @pytest.mark.asyncio
    async def test_needs_reprocessing_defaults_to_false(self, db):
        """needs_reprocessing defaults to FALSE when not specified."""
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO discs (title) VALUES (?)",
                ("Test Movie",),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT needs_reprocessing FROM discs WHERE title = ?",
                ("Test Movie",),
            )
            row = await cursor.fetchone()

        # SQLite stores BOOLEAN FALSE as 0
        assert row["needs_reprocessing"] == 0

    @pytest.mark.asyncio
    async def test_can_store_and_retrieve_preset_name(self, db):
        """Can store and retrieve preset_name on a track."""
        async with db.connection() as conn:
            # First insert a disc
            await conn.execute(
                "INSERT INTO discs (title) VALUES (?)",
                ("Test Disc",),
            )
            await conn.commit()

            cursor = await conn.execute("SELECT id FROM discs WHERE title = ?", ("Test Disc",))
            disc_row = await cursor.fetchone()
            disc_id = disc_row["id"]

            # Now insert a track with preset_name
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, preset_name)
                   VALUES (?, ?, ?)""",
                (disc_id, 1, "H.265 MKV 1080p30"),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT preset_name FROM tracks WHERE disc_id = ? AND track_number = ?",
                (disc_id, 1),
            )
            row = await cursor.fetchone()

        assert row["preset_name"] == "H.265 MKV 1080p30"

    @pytest.mark.asyncio
    async def test_migration_backward_compatibility(self):
        """Migrations properly add new columns to existing databases."""
        from amphigory.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Step 1: Create database with old schema (without Phase 3 columns)
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute("""
                    CREATE TABLE discs (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        year INTEGER,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("""
                    CREATE TABLE tracks (
                        id INTEGER PRIMARY KEY,
                        disc_id INTEGER REFERENCES discs(id),
                        track_number INTEGER,
                        status TEXT DEFAULT 'pending'
                    )
                """)
                await conn.commit()

            # Step 2: Initialize database (runs migrations)
            db = Database(db_path)
            await db.initialize()

            # Step 3: Verify new columns exist
            async with db.connection() as conn:
                # Check discs table has Phase 3 columns
                cursor = await conn.execute("PRAGMA table_info(discs)")
                discs_columns = {row["name"] for row in await cursor.fetchall()}

                assert "needs_reprocessing" in discs_columns
                assert "reprocessing_type" in discs_columns
                assert "reprocessing_notes" in discs_columns

                # Check tracks table has preset_name
                cursor = await conn.execute("PRAGMA table_info(tracks)")
                tracks_columns = {row["name"] for row in await cursor.fetchall()}

                assert "preset_name" in tracks_columns

            await db.close()
