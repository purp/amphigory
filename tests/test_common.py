"""Tests for common API utilities."""

import re
import pytest
from datetime import datetime

from amphigory.api.common import generate_task_id, VALID_TASK_TYPES


def test_generate_task_id_valid_scan():
    """Test that generate_task_id works with 'scan' task type."""
    task_id = generate_task_id("scan")

    # Check format: YYYY-MM-DDTHH:MM:SS.ffffff-scan
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-scan$'
    assert re.match(pattern, task_id), f"Task ID format invalid: {task_id}"

    # Check it ends with -scan
    assert task_id.endswith("-scan")


def test_generate_task_id_valid_rip():
    """Test that generate_task_id works with 'rip' task type."""
    task_id = generate_task_id("rip")

    # Check format: YYYY-MM-DDTHH:MM:SS.ffffff-rip
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-rip$'
    assert re.match(pattern, task_id), f"Task ID format invalid: {task_id}"

    # Check it ends with -rip
    assert task_id.endswith("-rip")


def test_generate_task_id_invalid_type():
    """Test that generate_task_id raises ValueError for invalid task type."""
    with pytest.raises(ValueError) as exc_info:
        generate_task_id("invalid")

    assert "Invalid task_type: invalid" in str(exc_info.value)
    assert "Must be one of" in str(exc_info.value)


def test_generate_task_id_empty_type():
    """Test that generate_task_id raises ValueError for empty task type."""
    with pytest.raises(ValueError) as exc_info:
        generate_task_id("")

    assert "Invalid task_type:" in str(exc_info.value)


def test_generate_task_id_timestamp_format():
    """Test that the timestamp in task ID is a valid ISO format."""
    task_id = generate_task_id("scan")

    # Extract timestamp part (everything before the last dash)
    timestamp_str = task_id.rsplit("-", 1)[0]

    # Should be parseable as ISO format
    parsed = datetime.fromisoformat(timestamp_str)
    assert isinstance(parsed, datetime)


def test_generate_task_id_unique():
    """Test that consecutive calls generate unique IDs."""
    task_id1 = generate_task_id("scan")
    task_id2 = generate_task_id("scan")

    # They should be different (due to microsecond precision)
    # Note: There's a tiny chance they could be the same if called
    # in the same microsecond, but very unlikely
    assert task_id1 != task_id2


def test_valid_task_types_constant():
    """Test that VALID_TASK_TYPES contains expected values."""
    assert "scan" in VALID_TASK_TYPES
    assert "rip" in VALID_TASK_TYPES
    assert len(VALID_TASK_TYPES) == 2
