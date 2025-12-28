"""Background task processor for webapp (transcode/insert tasks)."""

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from amphigory.database import Database
from amphigory.presets import PresetManager
from amphigory.services.transcoder import TranscoderService, TranscodeProgress, TranscodeResult
from amphigory.preset_selector import parse_resolution, recommend_preset

logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / 1024:.0f} KB"


def format_duration(seconds: int) -> str:
    """Format duration in human-readable form."""
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h{minutes}m"
    elif seconds >= 60:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m{secs}s"
    else:
        return f"{seconds}s"

WEBAPP_TASK_TYPES = {"transcode", "insert"}


def parse_eta_to_seconds(eta_str: str) -> int | None:
    """Parse HandBrake ETA string like '00h12m34s' to seconds.

    Args:
        eta_str: ETA string in format "NNhNNmNNs"

    Returns:
        Total seconds, or None if parsing fails
    """
    if not eta_str:
        return None
    match = re.match(r"(\d+)h(\d+)m(\d+)s", eta_str)
    if match:
        hours, minutes, seconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds
    return None


class TaskProcessor:
    """Background task processor for transcode and insert tasks."""

    def __init__(
        self,
        db: Database,
        tasks_dir: Path | str,
        transcoded_dir: Path | str,
        preset_dir: Path | str,
        progress_callback: Optional[Callable[[dict], None]] = None,
        max_concurrent_transcodes: int = 2,
    ):
        self.db = db
        self.tasks_dir = Path(tasks_dir)
        self.transcoded_dir = Path(transcoded_dir)
        self.preset_dir = Path(preset_dir)
        self.progress_callback = progress_callback
        self.max_concurrent_transcodes = max_concurrent_transcodes
        self.transcoder = TranscoderService()
        self.preset_manager = PresetManager(preset_dir)
        self._running = False
        self._task = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def queued_dir(self) -> Path:
        return self.tasks_dir / "queued"

    @property
    def in_progress_dir(self) -> Path:
        return self.tasks_dir / "in_progress"

    @property
    def complete_dir(self) -> Path:
        return self.tasks_dir / "complete"

    @property
    def failed_dir(self) -> Path:
        return self.tasks_dir / "failed"

    def get_task_order(self) -> list[str]:
        """Read tasks.json for ordering."""
        tasks_json = self.tasks_dir / "tasks.json"
        if not tasks_json.exists():
            return []
        with open(tasks_json) as f:
            return json.load(f)

    def _is_input_ready(self, task_data: dict) -> bool:
        """Check if task's input file exists."""
        input_path = task_data.get("input")
        if input_path is None:
            return True
        return Path(input_path).exists()

    async def start(self) -> None:
        """Start the task processor with concurrent workers."""
        if self._running:
            return
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent_transcodes)
        await self.preset_manager.load()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the task processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        """Main loop that polls for tasks and spawns concurrent workers."""
        active_tasks: set[asyncio.Task] = set()

        while self._running:
            try:
                # Clean up completed tasks
                done = {t for t in active_tasks if t.done()}
                for t in done:
                    try:
                        t.result()  # Raise exceptions from completed tasks
                    except Exception as e:
                        logger.exception(f"Worker task failed: {e}")
                active_tasks -= done

                # Spawn new workers up to the concurrency limit
                while len(active_tasks) < self.max_concurrent_transcodes:
                    task_data = await self.get_next_task()
                    if not task_data:
                        break  # No more tasks available
                    worker = asyncio.create_task(self._process_task_with_semaphore(task_data))
                    active_tasks.add(worker)

                await asyncio.sleep(2)  # Poll interval
            except asyncio.CancelledError:
                # Cancel all active workers on shutdown
                for t in active_tasks:
                    t.cancel()
                break
            except Exception as e:
                logger.exception(f"Error in task loop: {e}")
                await asyncio.sleep(5)

    async def _process_task_with_semaphore(self, task_data: dict) -> None:
        """Process a task with semaphore-controlled concurrency."""
        async with self._semaphore:
            task_id = task_data["id"]
            task_type = task_data.get("type")

            try:
                if task_type == "transcode":
                    await self._process_transcode(task_data)
                elif task_type == "insert":
                    await self._process_insert(task_data)
            except Exception as e:
                logger.exception(f"Task {task_id} failed: {e}")
                await self._complete_task(task_id, {
                    "task_id": task_id,
                    "status": "failed",
                    "error": {"message": str(e)},
                })

    async def get_next_task(self) -> Optional[dict]:
        """Get next task for webapp (transcode/insert)."""
        task_order = self.get_task_order()

        for task_id in task_order:
            # Filter by task type suffix
            task_type = task_id.rsplit("-", 1)[-1] if "-" in task_id else None
            if task_type not in WEBAPP_TASK_TYPES:
                continue

            queued_file = self.queued_dir / f"{task_id}.json"
            if not queued_file.exists():
                continue

            with open(queued_file) as f:
                task_data = json.load(f)

            # Check input dependency
            if not self._is_input_ready(task_data):
                continue

            # Claim task by moving to in_progress
            in_progress_file = self.in_progress_dir / f"{task_id}.json"
            shutil.move(str(queued_file), str(in_progress_file))

            return task_data

        return None

    async def process_one_task(self) -> bool:
        """Process one task from the queue."""
        task_data = await self.get_next_task()
        if not task_data:
            return False

        task_id = task_data["id"]
        task_type = task_data.get("type")

        try:
            if task_type == "transcode":
                await self._process_transcode(task_data)
            elif task_type == "insert":
                await self._process_insert(task_data)

            return True
        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            await self._complete_task(task_id, {
                "task_id": task_id,
                "status": "failed",
                "error": {"message": str(e)},
            })
            return True

    async def _process_transcode(self, task_data: dict) -> None:
        """Process a transcode task."""
        task_id = task_data["id"]
        input_path = Path(task_data["input"])
        output_path = Path(task_data["output"])
        start_time = time.time()

        # Ensure output directory exists
        ## TODO: trim filename off of output_path before creating directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get preset
        preset_name = task_data.get("preset")

        # Auto-select preset based on resolution if not specified
        ## TODO: raise an exception if we don't have a valid, loadable preset
        if not preset_name:
            error_msg = f"Transcode failed - no preset name in task)"
            raise Exception(error_msg)

        preset_path = self.preset_manager.get_preset_path(preset_category)
        if not preset_path:
            error_msg = f"Transcode failed - no preset path for '{preset_name}')"
            raise Exception(error_msg)

        # Progress callback wrapper
        def progress_cb(p: TranscodeProgress):
            if self.progress_callback:
                eta_seconds = parse_eta_to_seconds(p.eta) if p.eta else None
                self.progress_callback({
                    "type": "progress",
                    "task_id": task_id,
                    "percent": p.percent,
                    "eta_seconds": eta_seconds,
                })

        # Build and log the transcode command for manual testing
        cmd = self.transcoder.build_transcode_command(
            input_path=input_path,
            output_path=output_path,
            preset_path=preset_path,
            preset_name=preset_name,
        )
        logger.info(f"Transcode command: {' '.join(str(c) for c in cmd)}")

        # Run transcode
        result = await self.transcoder.transcode(
            input_path=input_path,
            output_path=output_path,
            preset_path=preset_path,
            preset_name=preset_name,
            progress_callback=progress_cb,
        )

        if not result.success:
            error_msg = f"Transcode failed (exit code {result.return_code})"
            if result.error_output:
                error_msg += f": {result.error_output}"
            raise Exception(error_msg)

        # Log summary stats
        duration = int(time.time() - start_time)
        output_size = output_path.stat().st_size if output_path.exists() else 0
        input_size = input_path.stat().st_size if input_path.exists() else 0
        ratio = (output_size / input_size * 100) if input_size > 0 else 0
        logger.info(
            f"Transcode: {output_path.name}, {format_size(input_size)} → {format_size(output_size)} "
            f"({ratio:.0f}%), {format_duration(duration)}"
        )

        await self._complete_task(task_id, {
            "task_id": task_id,
            "status": "success",
            "result": {
                "output": str(output_path),
            },
        })

    async def _process_insert(self, task_data: dict) -> None:
        """Process an insert task (move to Plex library)."""
        task_id = task_data["id"]
        # TODO: Implement insert task (move from transcoded to Plex)
        await self._complete_task(task_id, {
            "task_id": task_id,
            "status": "success",
        })

    async def _complete_task(self, task_id: str, response: dict) -> None:
        """Write task completion and clean up."""
        complete_file = self.complete_dir / f"{task_id}.json"
        with open(complete_file, "w") as f:
            json.dump(response, f, indent=2)

        in_progress_file = self.in_progress_dir / f"{task_id}.json"

        if response.get("status") == "failed":
            # Read original task data and merge with response
            original_task_data = {}
            if in_progress_file.exists():
                with open(in_progress_file) as f:
                    original_task_data = json.load(f)

            # Merge: original task data + response (response wins on conflict)
            failed_data = {**original_task_data, **response}
            failed_file = self.failed_dir / f"{task_id}.json"
            with open(failed_file, "w") as f:
                json.dump(failed_data, f, indent=2)

        if in_progress_file.exists():
            in_progress_file.unlink()
