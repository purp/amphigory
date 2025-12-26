"""Tests for job runner."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
async def db():
    """Create a temporary database."""
    from amphigory.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest.fixture
def preset_dir(tmp_path):
    """Create a temporary preset directory."""
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()

    # Create a test preset JSON file
    preset_file = preset_dir / "dvd-h265-720p-v1.json"
    preset_file.write_text('{"PresetList": [{"PresetName": "dvd-h265-720p-v1"}]}')

    # Create presets.yaml with active presets
    presets_yaml = preset_dir / "presets.yaml"
    presets_yaml.write_text("""
active:
  dvd: dvd-h265-720p-v1
  bluray: bluray-h265-1080p-v1
  uhd: uhd-h265-2160p-v1
""")

    return preset_dir


@pytest.fixture
def inbox_dir(tmp_path):
    """Create a temporary inbox directory."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return inbox


@pytest.fixture
def ripped_file(tmp_path):
    """Create a test ripped file."""
    ripped_dir = tmp_path / "ripped"
    ripped_dir.mkdir()
    test_file = ripped_dir / "test_track.mkv"
    test_file.write_text("fake mkv data")
    return test_file


@pytest.mark.asyncio
async def test_runner_processes_queued_transcode_job(db, inbox_dir, preset_dir, ripped_file):
    """Test that the runner picks up and completes a transcode job."""
    from amphigory.jobs import JobQueue, JobType, JobStatus
    from amphigory.job_runner import JobRunner

    # Create a disc and track
    async with db.connection() as conn:
        cursor = await conn.execute(
            """INSERT INTO discs (title, year, disc_type)
               VALUES (?, ?, ?)""",
            ("Test Movie", 2020, "dvd")
        )
        disc_id = cursor.lastrowid

        cursor = await conn.execute(
            """INSERT INTO tracks (disc_id, track_number, ripped_path, status, resolution)
               VALUES (?, ?, ?, ?, ?)""",
            (disc_id, 1, str(ripped_file), "ripped", "720x480")
        )
        track_id = cursor.lastrowid
        await conn.commit()

    # Create a transcode job
    queue = JobQueue(db)
    job_id = await queue.create_job(track_id, JobType.TRANSCODE)

    # Mock the transcoder to avoid running HandBrakeCLI
    progress_calls = []

    def mock_progress(progress):
        progress_calls.append(progress)

    runner = JobRunner(db, inbox_dir, preset_dir, progress_callback=mock_progress)

    # Mock the transcode method
    async def mock_transcode(input_path, output_path, preset_path, preset_name, progress_callback=None):
        # Call the progress callback if provided
        if progress_callback:
            from amphigory.services.transcoder import TranscodeProgress
            progress_callback(TranscodeProgress(percent=50))
            progress_callback(TranscodeProgress(percent=100))
        # Create the output file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake mp4 data")
        return True

    runner.transcoder.transcode = mock_transcode

    # Process the job
    result = await runner.process_one_job()

    # Verify job was processed
    assert result is True

    # Verify job status
    job = await queue.get_job(job_id)
    assert job["status"] == "complete"

    # Verify track was updated
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT status, transcoded_path, preset_name FROM tracks WHERE id = ?",
            (track_id,)
        )
        track = await cursor.fetchone()
        assert track["status"] == "complete"
        assert track["transcoded_path"] is not None
        assert "Test Movie (2020)" in track["transcoded_path"]
        assert track["preset_name"] == "dvd-h265-720p-v1"

    # Verify progress callback was called
    assert len(progress_calls) > 0


@pytest.mark.asyncio
async def test_runner_updates_track_status(db, inbox_dir, preset_dir, ripped_file):
    """Test that the runner updates track status to complete."""
    from amphigory.jobs import JobQueue, JobType
    from amphigory.job_runner import JobRunner

    # Create a disc and track
    async with db.connection() as conn:
        cursor = await conn.execute(
            """INSERT INTO discs (title, year, disc_type)
               VALUES (?, ?, ?)""",
            ("Another Movie", 2021, "dvd")
        )
        disc_id = cursor.lastrowid

        cursor = await conn.execute(
            """INSERT INTO tracks (disc_id, track_number, ripped_path, status, resolution)
               VALUES (?, ?, ?, ?, ?)""",
            (disc_id, 1, str(ripped_file), "ripped", "720x480")
        )
        track_id = cursor.lastrowid
        await conn.commit()

    # Create a transcode job
    queue = JobQueue(db)
    await queue.create_job(track_id, JobType.TRANSCODE)

    runner = JobRunner(db, inbox_dir, preset_dir)

    # Mock the transcode method
    async def mock_transcode(input_path, output_path, preset_path, preset_name, progress_callback=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake mp4 data")
        return True

    runner.transcoder.transcode = mock_transcode

    # Process the job
    await runner.process_one_job()

    # Verify track status changed
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT status FROM tracks WHERE id = ?",
            (track_id,)
        )
        track = await cursor.fetchone()
        assert track["status"] == "complete"


@pytest.mark.asyncio
async def test_runner_handles_missing_file(db, inbox_dir, preset_dir):
    """Test that the runner marks job as failed if ripped file is missing."""
    from amphigory.jobs import JobQueue, JobType, JobStatus
    from amphigory.job_runner import JobRunner

    # Create a disc and track with non-existent file
    async with db.connection() as conn:
        cursor = await conn.execute(
            """INSERT INTO discs (title, year, disc_type)
               VALUES (?, ?, ?)""",
            ("Missing Movie", 2022, "dvd")
        )
        disc_id = cursor.lastrowid

        cursor = await conn.execute(
            """INSERT INTO tracks (disc_id, track_number, ripped_path, status, resolution)
               VALUES (?, ?, ?, ?, ?)""",
            (disc_id, 1, "/nonexistent/file.mkv", "ripped", "720x480")
        )
        track_id = cursor.lastrowid
        await conn.commit()

    # Create a transcode job
    queue = JobQueue(db)
    job_id = await queue.create_job(track_id, JobType.TRANSCODE)

    runner = JobRunner(db, inbox_dir, preset_dir)

    # Process the job
    result = await runner.process_one_job()

    # Verify job was processed (returns True even on failure)
    assert result is True

    # Verify job status is failed
    job = await queue.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error_message"] is not None
    assert "not found" in job["error_message"].lower()


@pytest.mark.asyncio
async def test_runner_returns_false_on_empty_queue(db, inbox_dir, preset_dir):
    """Test that the runner returns False when no jobs are queued."""
    from amphigory.job_runner import JobRunner

    runner = JobRunner(db, inbox_dir, preset_dir)

    # Process when queue is empty
    result = await runner.process_one_job()

    # Should return False
    assert result is False
