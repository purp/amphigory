"""Unified task queue for Amphigory daemon and webapp."""

import json
import shutil
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskOwner(Enum):
    """Owner of a task type - determines which component processes it."""
    DAEMON = "daemon"
    WEBAPP = "webapp"


# Map task type suffixes to their owners
# Daemon handles: scan, rip (hardware-dependent tasks)
# Webapp handles: transcode, insert (software tasks)
TASK_OWNERS: dict[str, TaskOwner] = {
    "scan": TaskOwner.DAEMON,
    "rip": TaskOwner.DAEMON,
    "transcode": TaskOwner.WEBAPP,
    "insert": TaskOwner.WEBAPP,
}


class UnifiedTaskQueue:
    """
    Unified file-based task queue for both daemon and webapp.

    Directory structure:
        base_dir/
        ├── tasks.json          # Ordered list of task IDs
        ├── queued/             # Tasks waiting to be processed
        ├── in_progress/        # Currently being processed
        ├── complete/           # Successfully completed tasks
        └── failed/             # Failed tasks (for retry/review)

    Task ownership:
        - DAEMON: scan, rip (hardware-dependent)
        - WEBAPP: transcode, insert (software tasks)

    Dependency resolution:
        - Tasks with an 'input' field wait for that file to exist
        - This enables file-based task chaining (rip -> transcode -> insert)
    """

    def __init__(self, base_dir: Path):
        """
        Initialize unified task queue.

        Args:
            base_dir: Base directory for task queue
        """
        self.base_dir = Path(base_dir)
        self.tasks_json = self.base_dir / "tasks.json"
        self.queued_dir = self.base_dir / "queued"
        self.in_progress_dir = self.base_dir / "in_progress"
        self.complete_dir = self.base_dir / "complete"
        self.failed_dir = self.base_dir / "failed"

    def ensure_directories(self) -> None:
        """Create queue directories if they don't exist."""
        self.queued_dir.mkdir(parents=True, exist_ok=True)
        self.in_progress_dir.mkdir(parents=True, exist_ok=True)
        self.complete_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

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

    def _save_task_order(self, order: list[str]) -> None:
        """
        Save task order to tasks.json.

        Args:
            order: List of task IDs in priority order
        """
        with open(self.tasks_json, "w") as f:
            json.dump(order, f, indent=2)

    def create_task(self, task_data: dict) -> None:
        """
        Create a new task in the queue.

        Args:
            task_data: Task dictionary with 'id', 'type', 'created_at', etc.
        """
        task_id = task_data["id"]

        # Write task file to queued/
        task_file = self.queued_dir / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f, indent=2)

        # Add to tasks.json order
        order = self.get_task_order()
        if task_id not in order:
            order.append(task_id)
            self._save_task_order(order)

    def _get_task_owner(self, task_type: str) -> Optional[TaskOwner]:
        """
        Determine which component owns a task type.

        Args:
            task_type: Type of task (scan, rip, transcode, insert)

        Returns:
            TaskOwner or None if unknown type
        """
        return TASK_OWNERS.get(task_type)

    def _check_input_dependency(self, task_data: dict) -> bool:
        """
        Check if a task's input dependency is satisfied.

        Args:
            task_data: Task dictionary

        Returns:
            True if input is None or file exists, False otherwise
        """
        input_path = task_data.get("input")
        if input_path is None:
            return True
        return Path(input_path).exists()

    def get_next_task(self, owner: TaskOwner) -> Optional[dict]:
        """
        Find next task to process for a specific owner.

        1. Read tasks.json for order
        2. Find first ID with file in queued/ that:
           - Belongs to the specified owner
           - Has satisfied input dependencies
        3. Move file to in_progress/
        4. Return task data

        Args:
            owner: TaskOwner requesting a task

        Returns:
            Task dictionary, or None if no eligible tasks
        """
        task_order = self.get_task_order()

        for task_id in task_order:
            queued_file = self.queued_dir / f"{task_id}.json"
            if not queued_file.exists():
                continue

            # Load task data
            with open(queued_file) as f:
                task_data = json.load(f)

            # Check owner
            task_owner = self._get_task_owner(task_data.get("type", ""))
            if task_owner != owner:
                continue

            # Check input dependency
            if not self._check_input_dependency(task_data):
                continue

            # Move to in_progress
            in_progress_file = self.in_progress_dir / f"{task_id}.json"
            shutil.move(str(queued_file), str(in_progress_file))

            return task_data

        return None

    def complete_task(self, task_id: str, response: dict) -> None:
        """
        Complete a task with a response.

        Writes response to complete/ and removes from in_progress/.
        If the response indicates failure, also copies to failed/.

        Args:
            task_id: ID of the task to complete
            response: Response dictionary with status, result, error, etc.
        """
        # Write response to complete/
        complete_file = self.complete_dir / f"{task_id}.json"
        with open(complete_file, "w") as f:
            json.dump(response, f, indent=2)

        # If failed, also copy to failed/
        if response.get("status") == "failed":
            failed_file = self.failed_dir / f"{task_id}.json"
            with open(failed_file, "w") as f:
                json.dump(response, f, indent=2)

        # Delete from in_progress/
        in_progress_file = self.in_progress_dir / f"{task_id}.json"
        if in_progress_file.exists():
            in_progress_file.unlink()

    def get_failed_tasks(self) -> list[dict]:
        """
        Get all failed tasks.

        Returns:
            List of failed task response dictionaries
        """
        failed_tasks = []
        for task_file in sorted(self.failed_dir.glob("*.json")):
            with open(task_file) as f:
                failed_tasks.append(json.load(f))
        return failed_tasks

    def remove_from_failed(self, task_id: str) -> bool:
        """
        Remove a task from the failed directory.

        Args:
            task_id: ID of the task to remove

        Returns:
            True if removed, False if not found
        """
        failed_file = self.failed_dir / f"{task_id}.json"
        if failed_file.exists():
            failed_file.unlink()
            return True
        return False

    def get_downstream_tasks(self, output_path: str) -> list[dict]:
        """
        Find tasks that depend on a given output path.

        This is useful for determining which tasks will become ready
        when a task completes successfully.

        Args:
            output_path: Path to check as input for other tasks

        Returns:
            List of task dictionaries that have this path as input
        """
        downstream = []
        task_order = self.get_task_order()

        for task_id in task_order:
            queued_file = self.queued_dir / f"{task_id}.json"
            if not queued_file.exists():
                continue

            with open(queued_file) as f:
                task_data = json.load(f)

            if task_data.get("input") == output_path:
                downstream.append(task_data)

        return downstream

    def recover_crashed_tasks(self, owner: TaskOwner) -> int:
        """
        On startup, move any tasks in in_progress/ back to queued/.

        Only recovers tasks belonging to the specified owner.

        Args:
            owner: Owner of tasks to recover

        Returns:
            Number of tasks recovered
        """
        recovered = 0
        for task_file in self.in_progress_dir.glob("*.json"):
            with open(task_file) as f:
                task_data = json.load(f)

            task_owner = self._get_task_owner(task_data.get("type", ""))
            if task_owner == owner:
                queued_file = self.queued_dir / task_file.name
                shutil.move(str(task_file), str(queued_file))
                recovered += 1

        return recovered
