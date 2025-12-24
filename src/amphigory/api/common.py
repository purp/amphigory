"""Common utilities for API modules."""

from datetime import datetime

VALID_TASK_TYPES = {"scan", "rip"}


def generate_task_id(task_type: str) -> str:
    """Generate a human-readable task ID.

    Format: YYYY-MM-DDTHH:MM:SS.ffffff-{task_type}
    Example: 2024-12-24T14:30:15.123456-scan

    Args:
        task_type: Type of task (scan, rip, etc.)

    Returns:
        Human-readable task ID with timestamp and type

    Raises:
        ValueError: If task_type is not valid
    """
    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Invalid task_type: {task_type}. Must be one of {VALID_TASK_TYPES}")
    timestamp = datetime.now().isoformat(timespec='microseconds')
    return f"{timestamp}-{task_type}"
