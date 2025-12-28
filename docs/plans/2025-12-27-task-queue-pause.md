# Task Queue Pause Mechanism

## Overview

A shared filesystem-based pause mechanism that both the webapp and daemon respect. When paused, neither component picks up new tasks from the queue.

## Design

### Marker File
- Location: `{tasks_dir}/PAUSED`
- Presence = paused, absence = running
- Simple text file (can contain timestamp or reason, but presence is what matters)
- Can be created/removed manually via CLI for debugging

### Components

**Webapp:**
- GET `/api/tasks/pause-status` - Returns `{"paused": bool, "paused_at": timestamp|null}`
- POST `/api/tasks/pause` - Creates PAUSED file, returns new status
- POST `/api/tasks/resume` - Removes PAUSED file, returns new status
- Task Queue page shows pause state with toggle button
- WebSocket broadcasts pause state changes to all clients

**Daemon:**
- Checks for PAUSED file at start of each task loop iteration
- When PAUSED file exists, skips task pickup (like existing PauseMode.IMMEDIATE)
- Menu bar "Pause" action creates PAUSED file (syncs with filesystem)
- Menu bar shows paused state from filesystem

---

## Implementation Tasks

### Task 1: Webapp pause status API

**Files:** `src/amphigory/api/tasks.py`, `tests/test_tasks_api.py`

**Tests (write first):**
- `test_pause_status_returns_false_when_no_marker`
- `test_pause_status_returns_true_when_marker_exists`
- `test_pause_creates_marker_file`
- `test_pause_returns_paused_true`
- `test_resume_removes_marker_file`
- `test_resume_returns_paused_false`
- `test_pause_is_idempotent`
- `test_resume_is_idempotent`

**Implementation:**
- Add `get_pause_status()` helper that checks for `tasks_dir/PAUSED`
- Add `GET /api/tasks/pause-status` endpoint
- Add `POST /api/tasks/pause` endpoint (creates marker with timestamp)
- Add `POST /api/tasks/resume` endpoint (removes marker)

### Task 2: Webapp respects pause when listing tasks

**Files:** `src/amphigory/api/tasks.py`, `tests/test_tasks_api.py`

**Tests (write first):**
- `test_list_tasks_includes_pause_status`

**Implementation:**
- `GET /api/tasks` response includes `paused: bool` field

### Task 3: Task Queue page UI for pause

**Files:** `src/amphigory/templates/queue.html`, `src/amphigory/static/style.css`

**Tests:** Manual verification (UI)

**Implementation:**
- Add pause/resume button in page header
- Show "PAUSED" banner when paused
- Button toggles between "Pause Queue" and "Resume Queue"
- Fetch pause status on page load
- Update UI when pause state changes

### Task 4: Daemon checks filesystem pause marker

**Files:** `daemon/src/amphigory_daemon/main.py`, `daemon/tests/test_main.py`

**Tests (write first):**
- `test_task_loop_skips_when_paused_file_exists`
- `test_task_loop_processes_when_no_paused_file`
- `test_menu_pause_creates_paused_file`
- `test_menu_resume_removes_paused_file`

**Implementation:**
- Add `is_queue_paused()` method that checks for PAUSED file
- Modify `run_task_loop` to check filesystem marker (replace in-memory PauseMode)
- Update menu bar toggle to create/remove PAUSED file
- Menu reflects filesystem state on refresh

### Task 5: WebSocket pause notifications

**Files:** `src/amphigory/main.py`, `src/amphigory/templates/queue.html`

**Tests:** Manual verification (real-time updates)

**Implementation:**
- Broadcast `queue_paused` event when pause/resume endpoints called
- Queue page listens for event and updates UI
- Dashboard could also show indicator (future enhancement)
