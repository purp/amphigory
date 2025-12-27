"""Common utilities for API modules."""

from datetime import datetime

VALID_TASK_TYPES = {"scan", "rip", "transcode"}


def generate_task_id(task_type: str) -> str:
    """Generate a human-readable task ID.

    Format: YYYYMMDDTHHMMSS.ffffff-{task_type}
    Example: 20241224T143015.123456-scan

    Uses ISO8601 basic format (no hyphens/colons) to avoid issues with
    macOS filesystems where colons become path separators.

    Args:
        task_type: Type of task (scan, rip, etc.)

    Returns:
        Human-readable task ID with timestamp and type

    Raises:
        ValueError: If task_type is not valid
    """
    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Invalid task_type: {task_type}. Must be one of {VALID_TASK_TYPES}")
    now = datetime.now()
    # ISO8601 basic format: YYYYMMDDTHHMMSS.ffffff (no hyphens or colons)
    timestamp = now.strftime("%Y%m%dT%H%M%S") + f".{now.microsecond:06d}"
    return f"{timestamp}-{task_type}"
