"""Tests for job queue system."""

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


@pytest.mark.asyncio
async def test_create_rip_job(db):
    """Test creating a rip job."""
    from amphigory.jobs import JobQueue, JobType

    queue = JobQueue(db)

    job_id = await queue.create_job(
        track_id=1,
        job_type=JobType.RIP,
        priority=10,
    )

    assert job_id is not None

    job = await queue.get_job(job_id)
    assert job["job_type"] == "rip"
    assert job["status"] == "queued"
    assert job["priority"] == 10


@pytest.mark.asyncio
async def test_job_ordering(db):
    """Test that jobs are returned in priority order."""
    from amphigory.jobs import JobQueue, JobType

    queue = JobQueue(db)

    # Create jobs with different priorities
    await queue.create_job(track_id=1, job_type=JobType.RIP, priority=5)
    await queue.create_job(track_id=2, job_type=JobType.RIP, priority=10)
    await queue.create_job(track_id=3, job_type=JobType.RIP, priority=1)

    # Get next job should return highest priority
    next_job = await queue.get_next_job(JobType.RIP)
    assert next_job["track_id"] == 2  # priority 10


@pytest.mark.asyncio
async def test_update_job_progress(db):
    """Test updating job progress."""
    from amphigory.jobs import JobQueue, JobType, JobStatus

    queue = JobQueue(db)
    job_id = await queue.create_job(track_id=1, job_type=JobType.RIP)

    await queue.update_job(job_id, status=JobStatus.RUNNING, progress=50)

    job = await queue.get_job(job_id)
    assert job["status"] == "running"
    assert job["progress"] == 50
