# Task Dependencies & Unified Queue Design

## Overview

Unify the daemon's filesystem-based task queue and webapp's database-based job queue into a single filesystem queue with file-based dependency resolution. This enables submitting all tasks for a track at once (rip + transcode) with dependent tasks waiting for their input files to appear.

## Architecture

### Processor Responsibilities

| Component | Task Types | Reason |
|-----------|-----------|--------|
| **Daemon** | scan, rip | Needs macOS optical drive access |
| **Webapp** | transcode, insert | Has HandBrake, Plex paths |

Both observe the same filesystem queue, each processing their own task types.

### Dependency Model

Dependencies are resolved by **file existence**, not task IDs:

- Each task has an `input` field (path to required input file, null for scan)
- Each task has an `output` field (path where result is written)
- A task is ready to run when `input` is null OR the file exists
- Atomic completion: write to temp location, rename when done

This approach:
- Requires no dependency bookkeeping
- Makes state visible via `ls`
- Allows retries to "just work" (new task produces the file, waiting tasks proceed)

## Task Structure

```json
{
  "id": "20251227T143052.123456-transcode",
  "type": "scan" | "rip" | "transcode" | "insert",
  "created_at": "2025-12-27T14:30:52.123456",
  "input": "/media/ripped/Movie (2024)/Movie (2024).mkv",
  "output": "/media/inbox/Movie (2024)/Movie (2024).mkv",

  "track": { ... },            // rip: track number, expected size, etc.
  "preset": "H.265 MKV 1080p"  // transcode: HandBrake preset
}
```

**Truncated task ID format:** `HHMM.ffffff-type` (e.g., `1430.123456-rip`)
- Used in all UI displays for brevity
- Extracted via regex: `\d{4}\.\d{6}-[^\.]+`

## Directory Structure

```
{tasks_dir}/
├── tasks.json              # Ordered array of task IDs (position = priority)
├── queued/                 # Waiting to run (dependencies may or may not be met)
├── in_progress/            # Currently being processed (one per processor)
├── complete/               # Finished (success or failure)
└── failed/                 # Copies of failed tasks needing review
```

## Task Lifecycle

1. **Created:** Written to `queued/`, ID appended to `tasks.json`
2. **Claimed:** Moved to `in_progress/` by processor
3. **Completed:** Response written to `complete/`, removed from `in_progress/`
4. **If failed:** Also copied to `failed/` for review UI
5. **Resubmit:** New task to `queued/`, removed from `failed/`
6. **Cleanup:** Old `complete/` entries removed after 24h

## Processor Claim Logic

1. Read `tasks.json` for ordering
2. Filter to IDs ending with processor's types (e.g., `-rip`, `-transcode`)
3. For each matching ID in order:
   - Read `queued/{id}.json`
   - If `input` is null OR file exists → claim it (move to `in_progress/`)
   - Otherwise continue to next
4. Process claimed task

This minimizes file reads by filtering on filename before opening.

## Priority & Ordering

- Position in `tasks.json` determines priority (earlier = higher)
- Default behavior is FIFO (append to end)
- Reordering writes `tasks.json` with new order
- Progress is WebSocket-only (not persisted)

## "Process" Action

When user clicks "Process Selected Tracks":

For each selected track, create two tasks:

1. **Rip task:** `input: null`, `output: /media/ripped/.../track.mkv`
2. **Transcode task:** `input: /media/ripped/.../track.mkv`, `output: /media/inbox/.../track.mkv`

Transcode's `input` matches rip's `output`, creating the dependency.

## Task Type Registry

```python
class TaskType(Enum):
    SCAN = "scan"
    RIP = "rip"
    TRANSCODE = "transcode"
    INSERT = "insert"

TASK_OWNERS = {
    TaskType.SCAN: "daemon",
    TaskType.RIP: "daemon",
    TaskType.TRANSCODE: "webapp",
    TaskType.INSERT: "webapp",
}
```

## Failed Tasks & Resubmit Flow

### Failed Tasks UI (Queue page section)

For each task in `failed/`:
- Task type and truncated ID
- Error message
- Editable fields for user-set parameters
- List of downstream tasks (scan `queued/` for matching `input`, include transitive deps)
- "Resubmit Task" button
- "Cancel This Task" button
- Checkbox: "Also cancel downstream tasks" (default unchecked)

### Resubmit Flow

1. Create new task in `queued/` with (possibly edited) parameters
2. If `output` changed:
   - Scan `queued/` for tasks whose `input` matches old output
   - Create replacement tasks with updated `input` (cascade `output` changes)
   - Cancel original downstream tasks (move to `complete/` with `status: "cancelled"`)
3. Remove task from `failed/`
4. Original failure record stays in `complete/`

### Cancel Flow

1. Remove task from `failed/`
2. If checkbox checked, cancel all downstream tasks

## Task Display Component

Standard display used everywhere (Dashboard, Queue page sections):

```
┌─────────────────────────────────────────────────────────┐
│ 1430.123456-rip    Queued    2m 34s                   ▶ │
│ 1430.234567-transcode    In Progress    45s    34%    ▶ │
└─────────────────────────────────────────────────────────┘
```

**Fields:**
- Truncated task ID
- Status (Queued, In Progress, Complete, Failed, Cancelled)
- Elapsed time in status
- % complete (if known)
- Expand button for details

**Expanded view:**
- Full task ID
- Created timestamp
- Input/output paths
- Type-specific fields
- Error message (if failed)

**Behavior:**
- Expanded state preserved across polls (track in JS, re-expand after DOM update)

## Webapp Task Processor

Replaces `JobRunner`:

- Background task polling every 5 seconds
- Claims tasks ending in `-transcode` or `-insert`
- Processes one task at a time
- Streams progress via WebSocket to browsers
- Updates `tracks` table on completion (`transcoded_path`, `status`)
- Forwards daemon task progress to browsers (daemon → webapp → browsers)

## Migration

### Remove
- `jobs` table from database
- `src/amphigory/jobs.py`
- `src/amphigory/job_runner.py`
- `src/amphigory/api/jobs.py`
- Related tests

### Add
- Shared task queue library
- Webapp task processor
- Failed Tasks UI
- Task display component

### Rename
- "Active Jobs" → "Active Tasks"
- `/api/jobs/*` → absorb into `/api/tasks/*`

## Future Optimizations

- `dependencies.json` index for faster downstream task lookups (if scanning `queued/` becomes slow)
