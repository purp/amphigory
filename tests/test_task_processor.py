"""Tests for TaskProcessor."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from amphigory.task_processor import TaskProcessor


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def temp_tasks_dir(tmp_path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "queued").mkdir(parents=True)
    (tasks_dir / "in_progress").mkdir(parents=True)
    (tasks_dir / "complete").mkdir(parents=True)
    (tasks_dir / "failed").mkdir(parents=True)
    return tasks_dir


def test_task_processor_init(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor initialization."""
    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )
    assert processor.db == mock_db
    assert processor.tasks_dir == temp_tasks_dir


def test_task_processor_filters_by_type(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor only claims transcode/insert tasks."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    # Add a rip task (should be ignored)
    rip_id = "20251227T140000.000000-rip"
    (temp_tasks_dir / "queued" / f"{rip_id}.json").write_text(json.dumps({
        "id": rip_id,
        "type": "rip",
        "input": None,
        "output": "/tmp/test.mkv",
    }))

    # Add tasks.json
    (temp_tasks_dir / "tasks.json").write_text(json.dumps([rip_id]))

    # Should return None (rip is not webapp's task)
    import asyncio
    task = asyncio.run(processor.get_next_task())
    assert task is None


def test_task_processor_checks_input_dependency(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor waits for input file to exist."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    # Add a transcode task with non-existent input
    transcode_id = "20251227T140000.000000-transcode"
    (temp_tasks_dir / "queued" / f"{transcode_id}.json").write_text(json.dumps({
        "id": transcode_id,
        "type": "transcode",
        "input": "/nonexistent/file.mkv",
        "output": "/tmp/out.mkv",
    }))

    (temp_tasks_dir / "tasks.json").write_text(json.dumps([transcode_id]))

    # Should return None (input doesn't exist)
    import asyncio
    task = asyncio.run(processor.get_next_task())
    assert task is None


def test_task_processor_claims_ready_transcode(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor claims transcode task when input exists."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    # Create input file
    input_file = tmp_path / "input.mkv"
    input_file.write_text("fake mkv")

    # Add a transcode task with existing input
    transcode_id = "20251227T140000.000000-transcode"
    (temp_tasks_dir / "queued" / f"{transcode_id}.json").write_text(json.dumps({
        "id": transcode_id,
        "type": "transcode",
        "input": str(input_file),
        "output": str(tmp_path / "output.mp4"),
    }))

    (temp_tasks_dir / "tasks.json").write_text(json.dumps([transcode_id]))

    # Should return the task and move it to in_progress
    import asyncio
    task = asyncio.run(processor.get_next_task())

    assert task is not None
    assert task["id"] == transcode_id
    assert task["type"] == "transcode"

    # Verify file moved from queued to in_progress
    assert not (temp_tasks_dir / "queued" / f"{transcode_id}.json").exists()
    assert (temp_tasks_dir / "in_progress" / f"{transcode_id}.json").exists()


def test_task_processor_claims_insert_task(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor claims insert tasks."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    # Create input file
    input_file = tmp_path / "transcoded.mp4"
    input_file.write_text("fake mp4")

    # Add an insert task
    insert_id = "20251227T140100.000000-insert"
    (temp_tasks_dir / "queued" / f"{insert_id}.json").write_text(json.dumps({
        "id": insert_id,
        "type": "insert",
        "input": str(input_file),
        "output": "/media/movies/Test (2020)/Test (2020).mp4",
    }))

    (temp_tasks_dir / "tasks.json").write_text(json.dumps([insert_id]))

    import asyncio
    task = asyncio.run(processor.get_next_task())

    assert task is not None
    assert task["id"] == insert_id
    assert task["type"] == "insert"


def test_task_processor_respects_order(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor processes tasks in order from tasks.json."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    # Create input files
    input1 = tmp_path / "input1.mkv"
    input1.write_text("fake mkv 1")
    input2 = tmp_path / "input2.mkv"
    input2.write_text("fake mkv 2")

    # Add two transcode tasks
    transcode1 = "20251227T140000.000000-transcode"
    transcode2 = "20251227T140100.000000-transcode"

    (temp_tasks_dir / "queued" / f"{transcode1}.json").write_text(json.dumps({
        "id": transcode1,
        "type": "transcode",
        "input": str(input1),
        "output": str(tmp_path / "out1.mp4"),
    }))
    (temp_tasks_dir / "queued" / f"{transcode2}.json").write_text(json.dumps({
        "id": transcode2,
        "type": "transcode",
        "input": str(input2),
        "output": str(tmp_path / "out2.mp4"),
    }))

    # Order: transcode2 first, then transcode1
    (temp_tasks_dir / "tasks.json").write_text(json.dumps([transcode2, transcode1]))

    import asyncio
    task = asyncio.run(processor.get_next_task())

    # Should get transcode2 first (it's first in order)
    assert task["id"] == transcode2


def test_task_processor_complete_task(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor writes completion file."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    task_id = "20251227T140000.000000-transcode"

    # Create in_progress file
    (temp_tasks_dir / "in_progress" / f"{task_id}.json").write_text(json.dumps({
        "id": task_id,
        "type": "transcode",
    }))

    import asyncio
    asyncio.run(processor._complete_task(task_id, {
        "task_id": task_id,
        "status": "success",
        "result": {"output": "/tmp/out.mp4"},
    }))

    # Verify completion file exists
    complete_file = temp_tasks_dir / "complete" / f"{task_id}.json"
    assert complete_file.exists()

    completion = json.loads(complete_file.read_text())
    assert completion["status"] == "success"

    # Verify in_progress file removed
    assert not (temp_tasks_dir / "in_progress" / f"{task_id}.json").exists()


def test_task_processor_failed_task(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor writes failure files."""
    import json

    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )

    task_id = "20251227T140000.000000-transcode"

    # Create in_progress file
    (temp_tasks_dir / "in_progress" / f"{task_id}.json").write_text(json.dumps({
        "id": task_id,
        "type": "transcode",
    }))

    import asyncio
    asyncio.run(processor._complete_task(task_id, {
        "task_id": task_id,
        "status": "failed",
        "error": {"message": "Test error"},
    }))

    # Verify completion file exists
    complete_file = temp_tasks_dir / "complete" / f"{task_id}.json"
    assert complete_file.exists()

    # Verify failed file also exists
    failed_file = temp_tasks_dir / "failed" / f"{task_id}.json"
    assert failed_file.exists()

    failure = json.loads(failed_file.read_text())
    assert failure["status"] == "failed"
    assert failure["error"]["message"] == "Test error"
