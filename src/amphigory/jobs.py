"""Job queue management for ripping and transcoding."""

from enum import Enum
from typing import Any
from datetime import datetime

from amphigory.database import Database


class JobType(str, Enum):
    RIP = "rip"
    TRANSCODE = "transcode"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobQueue:
    """Manages the job queue for ripping and transcoding."""

    def __init__(self, db: Database):
        self.db = db

    async def create_job(
        self,
        track_id: int,
        job_type: JobType,
        priority: int = 0,
    ) -> int:
        """Create a new job in the queue."""
        async with self.db.connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO jobs (track_id, job_type, status, priority)
                VALUES (?, ?, ?, ?)
                """,
                (track_id, job_type.value, JobStatus.QUEUED.value, priority),
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_job(self, job_id: int) -> dict[str, Any] | None:
        """Get a job by ID."""
        async with self.db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def get_next_job(self, job_type: JobType | None = None) -> dict[str, Any] | None:
        """Get the next queued job, optionally filtered by type."""
        async with self.db.connection() as conn:
            if job_type:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ? AND job_type = ?
                    ORDER BY priority DESC, id ASC
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value, job_type.value),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY priority DESC, id ASC
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value,),
                )
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def update_job(
        self,
        job_id: int,
        status: JobStatus | None = None,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update job status and progress."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
            if status == JobStatus.RUNNING:
                updates.append("started_at = ?")
                params.append(datetime.now().isoformat())
            elif status in (JobStatus.COMPLETE, JobStatus.FAILED):
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())

        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)

        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if updates:
            params.append(job_id)
            async with self.db.connection() as conn:
                await conn.execute(
                    f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                await conn.commit()

    async def get_queue(self, job_type: JobType | None = None) -> list[dict[str, Any]]:
        """Get all queued jobs."""
        async with self.db.connection() as conn:
            if job_type:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ? AND job_type = ?
                    ORDER BY priority DESC, id ASC
                    """,
                    (JobStatus.QUEUED.value, job_type.value),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY priority DESC, id ASC
                    """,
                    (JobStatus.QUEUED.value,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def reorder_job(self, job_id: int, new_priority: int) -> None:
        """Change a job's priority."""
        async with self.db.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET priority = ? WHERE id = ? AND status = ?",
                (new_priority, job_id, JobStatus.QUEUED.value),
            )
            await conn.commit()

    async def cancel_job(self, job_id: int) -> None:
        """Cancel a queued job."""
        await self.update_job(job_id, status=JobStatus.CANCELLED)
