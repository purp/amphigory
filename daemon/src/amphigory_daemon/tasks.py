"""Task queue management for Amphigory daemon."""

import json
import shutil
from pathlib import Path
from typing import Optional, Union

from .models import (
    ScanTask,
    RipTask,
    TaskResponse,
    task_from_dict,
    response_to_dict,
)


class TaskQueue:
    """
    File-based task queue manager.

    Directory structure:
        base_dir/
        ├── tasks.json          # Ordered list of task IDs
        ├── queued/             # Tasks waiting to be processed
        ├── in_progress/        # Currently being processed (max 1)
        └── complete/           # Results ready for webapp
    """

    def __init__(self, base_dir: Path):
        """
        Initialize task queue.

        Args:
            base_dir: Base directory for task queue
        """
        self.base_dir = Path(base_dir)
        self.tasks_json = self.base_dir / "tasks.json"
        self.queued_dir = self.base_dir / "queued"
        self.in_progress_dir = self.base_dir / "in_progress"
        self.complete_dir = self.base_dir / "complete"

    def ensure_directories(self) -> None:
        """Create queue directories if they don't exist."""
        self.queued_dir.mkdir(parents=True, exist_ok=True)
        self.in_progress_dir.mkdir(parents=True, exist_ok=True)
        self.complete_dir.mkdir(parents=True, exist_ok=True)

    def get_task_order(self) -> list[str]:
        """
        Read tasks.json and return ordered list of task IDs.

        Returns:
            List of task IDs in priority order, or empty list if no tasks.json
        """
        if not self.tasks_json.exists():
            return []

        with open(self.tasks_json) as f:
            return json.load(f)

    def get_next_task(self) -> Optional[Union[ScanTask, RipTask]]:
        """
        Find next task to process.

        1. Read tasks.json for order
        2. Find first ID with file in queued/
        3. Move file to in_progress/
        4. Parse and return task

        Returns:
            Next task to process, or None if queue is empty
        """
        task_order = self.get_task_order()

        for task_id in task_order:
            queued_file = self.queued_dir / f"{task_id}.json"
            if queued_file.exists():
                # Move to in_progress
                in_progress_file = self.in_progress_dir / f"{task_id}.json"
                shutil.move(str(queued_file), str(in_progress_file))

                # Parse and return
                with open(in_progress_file) as f:
                    data = json.load(f)
                return task_from_dict(data)

        return None

    def complete_task(self, response: TaskResponse) -> None:
        """
        Write response to complete/, delete from in_progress/.

        Args:
            response: TaskResponse with results or error
        """
        # Write response to complete/
        complete_file = self.complete_dir / f"{response.task_id}.json"
        with open(complete_file, "w") as f:
            json.dump(response_to_dict(response), f, indent=2)

        # Delete from in_progress/
        in_progress_file = self.in_progress_dir / f"{response.task_id}.json"
        if in_progress_file.exists():
            in_progress_file.unlink()

    def recover_crashed_tasks(self) -> None:
        """
        On startup, move any tasks in in_progress/ back to queued/.

        This handles the case where the daemon crashed mid-task.
        """
        for task_file in self.in_progress_dir.iterdir():
            if task_file.suffix == ".json":
                queued_file = self.queued_dir / task_file.name
                shutil.move(str(task_file), str(queued_file))
