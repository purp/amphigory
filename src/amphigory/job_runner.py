"""Background job runner for transcoding."""

import asyncio
from pathlib import Path
from typing import Callable

from amphigory.database import Database
from amphigory.jobs import JobQueue, JobType, JobStatus
from amphigory.presets import PresetManager
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.preset_selector import parse_resolution, recommend_preset


class JobRunner:
    """Background task that polls the job queue and runs transcodes."""

    def __init__(
        self,
        db: Database,
        inbox_dir: Path | str,
        preset_dir: Path | str,
        progress_callback: Callable[[TranscodeProgress], None] | None = None,
    ):
        """Initialize the job runner.

        Args:
            db: Database instance
            inbox_dir: Directory where transcoded files are saved
            preset_dir: Directory containing HandBrake presets
            progress_callback: Optional callback for transcode progress updates
        """
        self.db = db
        self.inbox_dir = Path(inbox_dir)
        self.preset_dir = Path(preset_dir)
        self.progress_callback = progress_callback
        self.job_queue = JobQueue(db)
        self.transcoder = TranscoderService()
        self.preset_manager = PresetManager(preset_dir)
        self._running = False
        self._task = None

    async def start(self) -> None:
        """Start the job runner loop.

        Polls for jobs every 5 seconds.
        """
        if self._running:
            return

        self._running = True
        # Load presets once at startup
        await self.preset_manager.load()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the job runner."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        """Main loop that polls for jobs."""
        while self._running:
            try:
                # Process one job if available
                await self.process_one_job()
                # Wait 5 seconds before checking for next job
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception:
                # Log error but continue running
                await asyncio.sleep(5)

    async def process_one_job(self) -> bool:
        """Process one transcode job from the queue.

        Returns:
            True if a job was processed, False if queue was empty
        """
        # Get next transcode job
        job = await self.job_queue.get_next_job(JobType.TRANSCODE)
        if not job:
            return False

        job_id = job["id"]
        track_id = job["track_id"]

        try:
            # Load presets if not already loaded
            if not self.preset_manager.presets:
                await self.preset_manager.load()

            # Mark job as running
            await self.job_queue.update_job(job_id, status=JobStatus.RUNNING)

            # Get track info from database (JOIN with discs)
            async with self.db.connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT
                        t.id,
                        t.ripped_path,
                        t.resolution,
                        t.track_number,
                        d.title,
                        d.year,
                        d.disc_type
                    FROM tracks t
                    JOIN discs d ON t.disc_id = d.id
                    WHERE t.id = ?
                    """,
                    (track_id,),
                )
                track = await cursor.fetchone()

            if not track:
                raise Exception(f"Track {track_id} not found")

            # Verify ripped file exists
            ripped_path = Path(track["ripped_path"])
            if not ripped_path.exists():
                raise Exception(f"Ripped file not found: {ripped_path}")

            # Create output directory: inbox_dir / "{title} ({year})"
            title = track["title"]
            year = track["year"]
            output_dir = self.inbox_dir / f"{title} ({year})"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Output path: output_dir / "{stem}.mp4"
            output_path = output_dir / f"{ripped_path.stem}.mp4"

            # Get preset based on resolution
            resolution_tuple = parse_resolution(track["resolution"])
            if resolution_tuple:
                width, height = resolution_tuple
            else:
                # Default to DVD if resolution can't be parsed
                width, height = None, None

            # Recommend preset category (dvd, bluray, uhd)
            preset_category = recommend_preset(width, height)

            # Get the active preset name for this category
            preset_name = self.preset_manager.get_active_preset(preset_category)
            if not preset_name:
                raise Exception(f"No active preset for category: {preset_category}")

            # Get preset file path
            preset_path = self.preset_manager.get_preset_path(preset_category)
            if not preset_path:
                raise Exception(f"Preset file not found for: {preset_name}")

            # Run transcode
            success = await self.transcoder.transcode(
                input_path=ripped_path,
                output_path=output_path,
                preset_path=preset_path,
                preset_name=preset_name,
                progress_callback=self.progress_callback,
            )

            if not success:
                raise Exception("Transcode failed")

            # Update track status and transcoded_path on success
            async with self.db.connection() as conn:
                await conn.execute(
                    """
                    UPDATE tracks
                    SET status = ?, transcoded_path = ?, preset_name = ?
                    WHERE id = ?
                    """,
                    ("complete", str(output_path), preset_name, track_id),
                )
                await conn.commit()

            # Mark job complete
            await self.job_queue.update_job(job_id, status=JobStatus.COMPLETE, progress=100)

            return True

        except Exception as e:
            # Mark job as failed with error message
            await self.job_queue.update_job(
                job_id,
                status=JobStatus.FAILED,
                error_message=str(e),
            )
            return True
