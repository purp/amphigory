"""Tests for disc repository functions."""

import pytest
import json
from datetime import datetime
from pathlib import Path
from amphigory.database import Database
from amphigory.api import disc_repository
from amphigory.api.disc_repository import parse_duration, insert_track, get_tracks_for_disc


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


class TestParseDuration:
    """Tests for parse_duration function."""

    def test_parses_hours_minutes_seconds(self):
        """Parses 'H:MM:SS' format to total seconds."""
        assert parse_duration("1:39:56") == 5996  # 1*3600 + 39*60 + 56
        assert parse_duration("2:00:00") == 7200  # 2 hours
        assert parse_duration("0:30:00") == 1800  # 30 minutes

    def test_parses_minutes_seconds(self):
        """Parses 'M:SS' format to total seconds."""
        assert parse_duration("5:30") == 330  # 5*60 + 30
        assert parse_duration("90:00") == 5400  # 90 minutes
        assert parse_duration("0:45") == 45  # 45 seconds

    def test_parses_seconds_only(self):
        """Parses raw seconds as integer."""
        assert parse_duration("120") == 120
        assert parse_duration("0") == 0

    def test_returns_zero_for_empty_string(self):
        """Returns 0 for empty or None input."""
        assert parse_duration("") == 0
        assert parse_duration(None) == 0

    def test_handles_large_values(self):
        """Handles long durations correctly."""
        # 10 hours, 30 minutes, 45 seconds
        assert parse_duration("10:30:45") == 37845


class TestInsertTrack:
    """Tests for insert_track helper function."""

    @pytest.mark.asyncio
    async def test_inserts_track_with_all_fields(self, db, db_path):
        """Insert track with all scan_data fields mapped correctly."""
        # First create a disc
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_test123"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

        # Track data from scan_data["tracks"][]
        track_data = {
            "number": 0,
            "duration": "1:39:56",
            "size_bytes": 11397666816,
            "chapters": 24,
            "resolution": "1920x1080",
            "audio_streams": [
                {"language": "eng", "codec": "TrueHD", "channels": 6}
            ],
            "subtitle_streams": [
                {"language": "eng", "format": "PGS"}
            ],
            "classification": "main_feature",
            "confidence": "high",
            "score": 0.85,
            "segment_map": "1,2,3",
            "makemkv_name": "B1_t00.mkv",
        }

        await insert_track(db, disc_id, track_data)

        # Verify inserted data
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row["track_number"] == 0
        assert row["duration_seconds"] == 5996  # Parsed from "1:39:56"
        assert row["size_bytes"] == 11397666816
        assert row["chapter_count"] == 24
        assert row["resolution"] == "1920x1080"
        assert row["track_type"] == "main_feature"
        assert row["classification_confidence"] == "high"
        assert row["classification_score"] == 0.85
        assert row["segment_map"] == "1,2,3"
        assert row["makemkv_name"] == "B1_t00.mkv"
        assert row["status"] == "discovered"  # Default status

        # JSON fields
        audio_tracks = json.loads(row["audio_tracks"])
        assert len(audio_tracks) == 1
        assert audio_tracks[0]["codec"] == "TrueHD"

    @pytest.mark.asyncio
    async def test_handles_missing_optional_fields(self, db, db_path):
        """Insert track handles missing optional fields gracefully."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_test456"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

        # Minimal track data
        track_data = {
            "number": 1,
            "duration": "5:30",
        }

        await insert_track(db, disc_id, track_data)

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row["track_number"] == 1
        assert row["duration_seconds"] == 330
        assert row["size_bytes"] is None
        assert row["chapter_count"] is None
        assert row["classification_score"] is None

    @pytest.mark.asyncio
    async def test_parses_duration_correctly(self, db, db_path):
        """Insert track parses duration string to seconds."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_duration789"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

        await insert_track(db, disc_id, {"number": 0, "duration": "2:30:00"})

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT duration_seconds FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row["duration_seconds"] == 9000  # 2.5 hours

    @pytest.mark.asyncio
    async def test_stores_audio_subtitle_as_json(self, db, db_path):
        """Insert track stores audio and subtitle streams as JSON arrays."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_json_test"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

        track_data = {
            "number": 0,
            "duration": "1:00:00",
            "audio_streams": [
                {"language": "eng", "codec": "TrueHD", "channels": 8},
                {"language": "spa", "codec": "AC3", "channels": 6},
            ],
            "subtitle_streams": [
                {"language": "eng", "format": "PGS"},
                {"language": "spa", "format": "PGS"},
            ],
        }

        await insert_track(db, disc_id, track_data)

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT audio_tracks, subtitle_tracks FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        audio = json.loads(row["audio_tracks"])
        subs = json.loads(row["subtitle_tracks"])

        assert len(audio) == 2
        assert audio[0]["channels"] == 8
        assert len(subs) == 2
        assert subs[1]["language"] == "spa"


class TestSaveDiscScanWithTracks:
    """Tests for save_disc_scan populating tracks table."""

    @pytest.mark.asyncio
    async def test_creates_track_rows_on_save(self, db, db_path):
        """save_disc_scan creates track rows for each track in scan_data."""
        scan_data = {
            "disc_name": "TEST_DISC",
            "tracks": [
                {"number": 0, "duration": "1:30:00", "classification": "main_feature"},
                {"number": 1, "duration": "0:05:00", "classification": "extra"},
            ]
        }

        disc_id = await disc_repository.save_disc_scan("fp_tracks_test", scan_data)

        # Verify track rows were created
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
                (disc_id,),
            )
            rows = await cursor.fetchall()

        assert len(rows) == 2
        assert rows[0]["track_number"] == 0
        assert rows[0]["track_type"] == "main_feature"
        assert rows[1]["track_number"] == 1
        assert rows[1]["track_type"] == "extra"

    @pytest.mark.asyncio
    async def test_clears_old_tracks_on_rescan(self, db, db_path):
        """save_disc_scan clears old tracks when rescanning same disc."""
        # First scan with 3 tracks
        scan_data_1 = {
            "disc_name": "TEST_DISC",
            "tracks": [
                {"number": 0, "duration": "1:30:00"},
                {"number": 1, "duration": "0:05:00"},
                {"number": 2, "duration": "0:03:00"},
            ]
        }
        disc_id = await disc_repository.save_disc_scan("fp_rescan_test", scan_data_1)

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()
        assert row["count"] == 3

        # Rescan with only 2 tracks
        scan_data_2 = {
            "disc_name": "TEST_DISC_UPDATED",
            "tracks": [
                {"number": 0, "duration": "1:35:00"},
                {"number": 1, "duration": "0:04:30"},
            ]
        }
        disc_id_2 = await disc_repository.save_disc_scan("fp_rescan_test", scan_data_2)

        # Same disc ID
        assert disc_id_2 == disc_id

        # Only 2 tracks now
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()
        assert row["count"] == 2

    @pytest.mark.asyncio
    async def test_handles_empty_tracks_list(self, db, db_path):
        """save_disc_scan handles scan_data with no tracks."""
        scan_data = {
            "disc_name": "EMPTY_DISC",
            "tracks": []
        }

        disc_id = await disc_repository.save_disc_scan("fp_empty_tracks", scan_data)

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row["count"] == 0

    @pytest.mark.asyncio
    async def test_handles_missing_tracks_key(self, db, db_path):
        """save_disc_scan handles scan_data without tracks key."""
        scan_data = {
            "disc_name": "NO_TRACKS_KEY",
        }

        disc_id = await disc_repository.save_disc_scan("fp_no_tracks_key", scan_data)

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()

        assert row["count"] == 0


class TestGetTracksForDisc:
    """Tests for get_tracks_for_disc function."""

    @pytest.mark.asyncio
    async def test_returns_all_tracks_for_disc_id(self, db, db_path):
        """Returns list of track dicts for given disc_id."""
        # Create a disc with tracks
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_tracks_list"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

            # Insert multiple tracks
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, duration_seconds, track_type)
                   VALUES (?, ?, ?, ?)""",
                (disc_id, 0, 5400, "main_feature"),
            )
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, duration_seconds, track_type)
                   VALUES (?, ?, ?, ?)""",
                (disc_id, 1, 300, "extra"),
            )
            await conn.commit()

        result = await get_tracks_for_disc(disc_id)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["track_number"] == 0
        assert result[0]["duration_seconds"] == 5400
        assert result[0]["track_type"] == "main_feature"
        assert result[1]["track_number"] == 1
        assert result[1]["track_type"] == "extra"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_unknown_disc(self, db, db_path):
        """Returns empty list for non-existent disc_id."""
        result = await get_tracks_for_disc(99999)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_orders_by_track_number(self, db, db_path):
        """Tracks are ordered by track_number ASC."""
        # Create a disc
        async with db.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO discs (title, fingerprint) VALUES (?, ?)",
                ("Test Movie", "fp_tracks_order"),
            )
            await conn.commit()
            disc_id = cursor.lastrowid

            # Insert tracks out of order
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, duration_seconds)
                   VALUES (?, ?, ?)""",
                (disc_id, 5, 100),
            )
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, duration_seconds)
                   VALUES (?, ?, ?)""",
                (disc_id, 1, 200),
            )
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, duration_seconds)
                   VALUES (?, ?, ?)""",
                (disc_id, 3, 300),
            )
            await conn.commit()

        result = await get_tracks_for_disc(disc_id)

        assert len(result) == 3
        assert result[0]["track_number"] == 1
        assert result[1]["track_number"] == 3
        assert result[2]["track_number"] == 5