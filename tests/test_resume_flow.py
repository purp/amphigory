"""Integration tests for resume interrupted flows feature."""

import pytest
from unittest.mock import patch

from amphigory.database import Database


class TestResumeFlow:
    """Test the full resume flow from known disc to processing."""

    @pytest.fixture
    def tasks_dir(self, tmp_path):
        """Create a temporary tasks directory structure."""
        tasks = tmp_path / "tasks"
        (tasks / "queued").mkdir(parents=True)
        (tasks / "in_progress").mkdir(parents=True)
        (tasks / "complete").mkdir(parents=True)
        return tasks

    @pytest.fixture
    def client(self, tasks_dir):
        """Create test client with mocked tasks directory."""
        with patch.dict("os.environ", {"AMPHIGORY_DATA": str(tasks_dir.parent)}):
            from amphigory.main import app
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                yield client

    @pytest.fixture
    async def disc_with_mixed_tracks(self, tasks_dir):
        """Create a disc with tracks in various states."""
        db_path = tasks_dir.parent / "amphigory.db"
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

            # Track 1: Fully processed (all paths set, status='complete')
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                   ripped_path, transcoded_path, inserted_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    1,
                    "main_feature",
                    "Main Feature",
                    "complete",
                    "/media/ripped/t1.mkv",
                    "/media/inbox/t1.mp4",
                    "/media/plex/t1.mp4",
                ),
            )

            # Track 2: Transcoded only (ripped_path and transcoded_path set, no inserted_path)
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                   ripped_path, transcoded_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    2,
                    "featurettes",
                    "Making Of",
                    "transcoded",
                    "/media/ripped/t2.mkv",
                    "/media/inbox/t2.mp4",
                ),
            )

            # Track 3: Ripped only (ripped_path set only)
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                   ripped_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    3,
                    "deleted_scenes",
                    "Deleted Scene",
                    "ripped",
                    "/media/ripped/t3.mkv",
                ),
            )

            # Track 4: Unprocessed (no paths set, status='discovered')
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (disc_id, 4, "trailers", "Trailer", "discovered"),
            )

            await conn.commit()

        return disc_id

    @pytest.mark.asyncio
    async def test_get_disc_by_fingerprint_returns_all_tracks(
        self, client, tasks_dir, disc_with_mixed_tracks
    ):
        """GET /api/disc/by-fingerprint returns disc with all tracks."""
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200

        data = response.json()
        assert data["disc"]["title"] == "Test Movie"
        assert data["disc"]["fingerprint"] == "resume_test_fp"
        assert data["disc"]["year"] == 2020
        assert data["disc"]["imdb_id"] == "tt1234567"

        # Verify all 4 tracks are returned
        assert len(data["tracks"]) == 4

        # Verify tracks are ordered by track_number
        track_numbers = [t["track_number"] for t in data["tracks"]]
        assert track_numbers == [1, 2, 3, 4]

        # Verify track states
        tracks_by_number = {t["track_number"]: t for t in data["tracks"]}

        # Track 1: Fully processed
        assert tracks_by_number[1]["status"] == "complete"
        assert tracks_by_number[1]["ripped_path"] == "/media/ripped/t1.mkv"
        assert tracks_by_number[1]["transcoded_path"] == "/media/inbox/t1.mp4"
        assert tracks_by_number[1]["inserted_path"] == "/media/plex/t1.mp4"

        # Track 2: Transcoded only
        assert tracks_by_number[2]["status"] == "transcoded"
        assert tracks_by_number[2]["ripped_path"] == "/media/ripped/t2.mkv"
        assert tracks_by_number[2]["transcoded_path"] == "/media/inbox/t2.mp4"
        assert tracks_by_number[2]["inserted_path"] is None

        # Track 3: Ripped only
        assert tracks_by_number[3]["status"] == "ripped"
        assert tracks_by_number[3]["ripped_path"] == "/media/ripped/t3.mkv"
        assert tracks_by_number[3]["transcoded_path"] is None
        assert tracks_by_number[3]["inserted_path"] is None

        # Track 4: Unprocessed
        assert tracks_by_number[4]["status"] == "discovered"
        assert tracks_by_number[4]["ripped_path"] is None
        assert tracks_by_number[4]["transcoded_path"] is None
        assert tracks_by_number[4]["inserted_path"] is None

    @pytest.mark.asyncio
    async def test_verify_files_shows_correct_state(
        self, client, tasks_dir, disc_with_mixed_tracks
    ):
        """Verify files endpoint correctly reports file existence (test with no paths set = all false)."""
        # Get the track ID for the unprocessed track (track 4)
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200

        tracks = response.json()["tracks"]
        unprocessed_track = next(t for t in tracks if t["track_number"] == 4)
        track_id = unprocessed_track["id"]

        # Verify files for unprocessed track - should all be false
        verify_response = client.get(f"/api/tracks/{track_id}/verify-files")
        assert verify_response.status_code == 200

        data = verify_response.json()
        assert data["ripped_exists"] is False
        assert data["ripped_path"] is None
        assert data["transcoded_exists"] is False
        assert data["transcoded_path"] is None
        assert data["inserted_exists"] is False
        assert data["inserted_path"] is None

    @pytest.mark.asyncio
    async def test_verify_files_with_paths_but_missing_files(
        self, client, tasks_dir, disc_with_mixed_tracks
    ):
        """Verify files correctly reports exists=False when path is set but file is missing."""
        # Get the track ID for the fully processed track (track 1)
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200

        tracks = response.json()["tracks"]
        complete_track = next(t for t in tracks if t["track_number"] == 1)
        track_id = complete_track["id"]

        # Verify files - paths are set but files don't exist
        verify_response = client.get(f"/api/tracks/{track_id}/verify-files")
        assert verify_response.status_code == 200

        data = verify_response.json()
        # Paths are set but files don't exist on disk
        assert data["ripped_path"] == "/media/ripped/t1.mkv"
        assert data["ripped_exists"] is False
        assert data["transcoded_path"] == "/media/inbox/t1.mp4"
        assert data["transcoded_exists"] is False
        assert data["inserted_path"] == "/media/plex/t1.mp4"
        assert data["inserted_exists"] is False

    @pytest.mark.asyncio
    async def test_reset_clears_all_paths(
        self, client, tasks_dir, disc_with_mixed_tracks
    ):
        """Reset track clears all paths and resets status to 'discovered'."""
        # Get the track ID for the fully processed track (track 1)
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200

        tracks = response.json()["tracks"]
        complete_track = next(t for t in tracks if t["track_number"] == 1)
        track_id = complete_track["id"]

        # Verify track has paths before reset
        assert complete_track["ripped_path"] == "/media/ripped/t1.mkv"
        assert complete_track["transcoded_path"] == "/media/inbox/t1.mp4"
        assert complete_track["inserted_path"] == "/media/plex/t1.mp4"
        assert complete_track["status"] == "complete"

        # Reset the track
        reset_response = client.post(f"/api/tracks/{track_id}/reset")
        assert reset_response.status_code == 200
        assert reset_response.json()["status"] == "reset"

        # Verify paths are cleared and status is reset
        updated_response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert updated_response.status_code == 200

        updated_tracks = updated_response.json()["tracks"]
        updated_track = next(t for t in updated_tracks if t["track_number"] == 1)

        assert updated_track["ripped_path"] is None
        assert updated_track["transcoded_path"] is None
        assert updated_track["inserted_path"] is None
        assert updated_track["status"] == "discovered"

    @pytest.mark.asyncio
    async def test_reset_deletes_existing_files(
        self, client, tasks_dir, disc_with_mixed_tracks, tmp_path
    ):
        """Reset track deletes files from disk when they exist."""
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create actual test files
        ripped_file = tmp_path / "ripped_test.mkv"
        ripped_file.write_text("ripped content")
        transcoded_file = tmp_path / "transcoded_test.mp4"
        transcoded_file.write_text("transcoded content")

        # Get disc_id from the fixture
        disc_id = disc_with_mixed_tracks

        # Create a new track with paths pointing to real files
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, track_name, status,
                   ripped_path, transcoded_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    5,
                    "extra",
                    "Extra Content",
                    "transcoded",
                    str(ripped_file),
                    str(transcoded_file),
                ),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        # Verify files exist before reset
        assert ripped_file.exists()
        assert transcoded_file.exists()

        # Reset the track
        reset_response = client.post(f"/api/tracks/{track_id}/reset")
        assert reset_response.status_code == 200

        # Verify files were deleted
        assert not ripped_file.exists()
        assert not transcoded_file.exists()

    @pytest.mark.asyncio
    async def test_save_updates_disc_and_tracks(
        self, client, tasks_dir, disc_with_mixed_tracks
    ):
        """Save endpoint updates disc and track info."""
        disc_id = disc_with_mixed_tracks

        # Get current state
        response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert response.status_code == 200
        data = response.json()

        # Get track IDs
        tracks = data["tracks"]
        track_1 = next(t for t in tracks if t["track_number"] == 1)
        track_2 = next(t for t in tracks if t["track_number"] == 2)

        # Update disc and tracks
        save_response = client.post(
            f"/api/disc/{disc_id}/save",
            json={
                "disc": {"title": "Updated Movie Title", "year": 2021, "imdb_id": "tt9999999"},
                "tracks": [
                    {
                        "id": track_1["id"],
                        "track_name": "Updated Main Feature",
                        "track_type": "main_feature",
                        "preset_name": "HQ 1080p",
                    },
                    {
                        "id": track_2["id"],
                        "track_name": "Updated Making Of",
                        "track_type": "featurettes",
                        "preset_name": "Standard",
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        assert save_response.json()["status"] == "saved"

        # Verify updates persisted
        updated_response = client.get("/api/disc/by-fingerprint/resume_test_fp")
        assert updated_response.status_code == 200

        updated_data = updated_response.json()

        # Check disc updates
        assert updated_data["disc"]["title"] == "Updated Movie Title"
        assert updated_data["disc"]["year"] == 2021
        assert updated_data["disc"]["imdb_id"] == "tt9999999"

        # Check track updates
        updated_tracks = {t["track_number"]: t for t in updated_data["tracks"]}
        assert updated_tracks[1]["track_name"] == "Updated Main Feature"
        assert updated_tracks[1]["preset_name"] == "HQ 1080p"
        assert updated_tracks[2]["track_name"] == "Updated Making Of"
        assert updated_tracks[2]["preset_name"] == "Standard"

        # Verify paths were NOT overwritten by save
        assert updated_tracks[1]["ripped_path"] == "/media/ripped/t1.mkv"
        assert updated_tracks[1]["transcoded_path"] == "/media/inbox/t1.mp4"
        assert updated_tracks[1]["inserted_path"] == "/media/plex/t1.mp4"

    @pytest.mark.asyncio
    async def test_save_returns_404_for_unknown_disc(self, client, tasks_dir):
        """Save returns 404 for non-existent disc_id."""
        # Initialize database first
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        response = client.post(
            "/api/disc/99999/save", json={"disc": {}, "tracks": []}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reset_returns_404_for_unknown_track(self, client, tasks_dir):
        """Reset returns 404 for non-existent track_id."""
        # Initialize database first
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        response = client.post("/api/tracks/99999/reset")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_files_returns_404_for_unknown_track(self, client, tasks_dir):
        """Verify files returns 404 for non-existent track_id."""
        # Initialize database first
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        response = client.get("/api/tracks/99999/verify-files")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_disc_by_fingerprint_returns_404_for_unknown(
        self, client, tasks_dir
    ):
        """GET /api/disc/by-fingerprint returns 404 for unknown fingerprint."""
        # Initialize database first
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        response = client.get("/api/disc/by-fingerprint/nonexistent_fp_12345")
        assert response.status_code == 404
