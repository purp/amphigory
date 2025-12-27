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
    async def test_tracks_table_has_makemkv_name(self, db):
        """Tracks table has makemkv_name column for MakeMKV internal track name."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(tracks)")
            columns = {row["name"] for row in await cursor.fetchall()}

        assert "makemkv_name" in columns

    @pytest.mark.asyncio
    async def test_tracks_table_has_classification_score(self, db):
        """Tracks table has classification_score column for numeric confidence."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(tracks)")
            columns = {row["name"] for row in await cursor.fetchall()}

        assert "classification_score" in columns

    @pytest.mark.asyncio
    async def test_can_store_makemkv_name(self, db):
        """Can store and retrieve makemkv_name on a track."""
        async with db.connection() as conn:
            await conn.execute("INSERT INTO discs (title) VALUES (?)", ("Test Disc",))
            await conn.commit()

            cursor = await conn.execute("SELECT id FROM discs WHERE title = ?", ("Test Disc",))
            disc_id = (await cursor.fetchone())["id"]

            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, makemkv_name)
                   VALUES (?, ?, ?)""",
                (disc_id, 0, "B1_t04.mkv"),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT makemkv_name FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row["makemkv_name"] == "B1_t04.mkv"

    @pytest.mark.asyncio
    async def test_can_store_classification_score(self, db):
        """Can store and retrieve classification_score as REAL."""
        async with db.connection() as conn:
            await conn.execute("INSERT INTO discs (title) VALUES (?)", ("Test Disc",))
            await conn.commit()

            cursor = await conn.execute("SELECT id FROM discs WHERE title = ?", ("Test Disc",))
            disc_id = (await cursor.fetchone())["id"]

            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, classification_score)
                   VALUES (?, ?, ?)""",
                (disc_id, 0, 0.85),
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT classification_score FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert abs(row["classification_score"] - 0.85) < 0.001

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


class TestScanDataMigration:
    """Tests for migrating existing scan_data to tracks table."""

    @pytest.mark.asyncio
    async def test_migrates_existing_scan_data_to_tracks(self):
        """Existing discs with scan_data get tracks populated during migration."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Step 1: Create a full database then insert disc with scan_data but no tracks
            db = Database(db_path)
            await db.initialize()

            # Insert a disc with scan_data directly (simulating existing data)
            scan_data = {
                "disc_name": "Test Movie",
                "tracks": [
                    {
                        "number": 0,
                        "duration": "1:45:30",
                        "size_bytes": 25000000000,
                        "chapters": 24,
                        "resolution": "1920x1080",
                        "classification": "main_feature",
                        "confidence": "high",
                        "score": 0.95,
                        "segment_map": "1,2,3",
                        "makemkv_name": "B1_t00.mkv",
                        "audio_streams": [{"codec": "DTS-HD MA", "language": "English"}],
                        "subtitle_streams": [{"language": "English"}],
                    },
                    {
                        "number": 1,
                        "duration": "5:30",
                        "size_bytes": 500000000,
                        "chapters": 1,
                        "resolution": "1920x1080",
                        "classification": "extra",
                        "confidence": "medium",
                        "score": 0.75,
                        "makemkv_name": "B1_t01.mkv",
                    },
                ],
            }
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (title, fingerprint, scan_data) VALUES (?, ?, ?)",
                    ("Test Movie", "fp_abc123", json.dumps(scan_data)),
                )
                await conn.commit()
            await db.close()

            # Step 2: Re-open database and run migrations again (should populate tracks)
            db2 = Database(db_path)
            await db2.initialize()

            # Step 3: Verify tracks were created
            async with db2.connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM tracks ORDER BY track_number"
                )
                tracks = [dict(row) for row in await cursor.fetchall()]

            assert len(tracks) == 2

            # Verify first track (main feature)
            assert tracks[0]["track_number"] == 0
            assert tracks[0]["duration_seconds"] == 1 * 3600 + 45 * 60 + 30  # 6330 seconds
            assert tracks[0]["size_bytes"] == 25000000000
            assert tracks[0]["chapter_count"] == 24
            assert tracks[0]["resolution"] == "1920x1080"
            assert tracks[0]["track_type"] == "main_feature"
            assert tracks[0]["classification_confidence"] == "high"
            assert abs(tracks[0]["classification_score"] - 0.95) < 0.001
            assert tracks[0]["makemkv_name"] == "B1_t00.mkv"
            assert tracks[0]["segment_map"] == "1,2,3"
            assert tracks[0]["status"] == "discovered"

            # Verify second track (extra)
            assert tracks[1]["track_number"] == 1
            assert tracks[1]["duration_seconds"] == 5 * 60 + 30  # 330 seconds
            assert tracks[1]["track_type"] == "extra"

            await db2.close()

    @pytest.mark.asyncio
    async def test_skips_discs_without_scan_data(self):
        """Discs with NULL scan_data are skipped during migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and insert a disc WITHOUT scan_data
            db = Database(db_path)
            await db.initialize()

            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                    ("Old Movie", "fp_old123"),
                )
                await conn.commit()
            await db.close()

            # Re-open and run migrations
            db2 = Database(db_path)
            await db2.initialize()

            # Verify no tracks were created
            async with db2.connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) as count FROM tracks")
                row = await cursor.fetchone()

            assert row["count"] == 0

            await db2.close()

    @pytest.mark.asyncio
    async def test_migration_is_idempotent(self):
        """Running migration twice doesn't duplicate tracks."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and insert disc with scan_data
            db = Database(db_path)
            await db.initialize()

            scan_data = {
                "disc_name": "Test Movie",
                "tracks": [
                    {"number": 0, "duration": "1:30:00", "classification": "main_feature"},
                    {"number": 1, "duration": "5:00", "classification": "extra"},
                ],
            }
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (title, fingerprint, scan_data) VALUES (?, ?, ?)",
                    ("Test Movie", "fp_abc123", json.dumps(scan_data)),
                )
                await conn.commit()
            await db.close()

            # Run migrations FIRST time (should populate tracks)
            db2 = Database(db_path)
            await db2.initialize()
            await db2.close()

            # Run migrations SECOND time
            db3 = Database(db_path)
            await db3.initialize()

            # Verify we still only have 2 tracks (not 4)
            async with db3.connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) as count FROM tracks")
                row = await cursor.fetchone()

            assert row["count"] == 2

            await db3.close()


class TestInsertedPathMigration:
    """Test inserted_path column migration."""

    @pytest.mark.asyncio
    async def test_tracks_table_has_inserted_path_column(self, db):
        """Tracks table should have inserted_path column after migration."""
        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(tracks)")
            columns = {row[1] for row in await cursor.fetchall()}

        assert "inserted_path" in columns
