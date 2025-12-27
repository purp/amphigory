"""Background task processor for webapp (transcode/insert tasks)."""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from amphigory.database import Database
from amphigory.presets import PresetManager
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.preset_selector import parse_resolution, recommend_preset

logger = logging.getLogger(__name__)

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
        inbox_dir: Path | str,
        preset_dir: Path | str,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.db = db
        self.tasks_dir = Path(tasks_dir)
        self.inbox_dir = Path(inbox_dir)
        self.preset_dir = Path(preset_dir)
        self.progress_callback = progress_callback
        self.transcoder = TranscoderService()
        self.preset_manager = PresetManager(preset_dir)
        self._running = False
        self._task = None

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
        """Start the task processor loop."""
        if self._running:
            return
        self._running = True
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
        """Main loop that polls for tasks."""
        while self._running:
            try:
                await self.process_one_task()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error processing task: {e}")
                await asyncio.sleep(5)

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

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get preset
        preset_name = task_data.get("preset")

        # Auto-select preset based on resolution if not specified
        if not preset_name:
            preset_category = "bluray"  # Default
            preset_name = self.preset_manager.get_active_preset(preset_category)
        else:
            preset_category = "bluray"  # Preset category for provided preset

        preset_path = self.preset_manager.get_preset_path(preset_category)

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

        # Run transcode
        success = await self.transcoder.transcode(
            input_path=input_path,
            output_path=output_path,
            preset_path=preset_path,
            preset_name=preset_name,
            progress_callback=progress_cb,
        )

        if not success:
            raise Exception("Transcode failed")

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
        # TODO: Implement insert task (move from inbox to Plex)
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
        if in_progress_file.exists():
            in_progress_file.unlink()

        if response.get("status") == "failed":
            failed_file = self.failed_dir / f"{task_id}.json"
            with open(failed_file, "w") as f:
                json.dump(response, f, indent=2)
