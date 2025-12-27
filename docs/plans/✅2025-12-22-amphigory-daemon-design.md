# Amphigory Host Daemon Design Document

**Date:** 2025-12-22

**Status:** ✅ Implemented

## Overview

The Amphigory host daemon bridges the gap between the containerized webapp and the macOS optical drive. Docker Desktop for Mac runs in a VM, making direct device passthrough impossible. The daemon runs natively on macOS, handles disc detection and MakeMKV operations, and communicates with the webapp via WebSocket and a file-based task queue.

### Goals

- Enable optical drive access from the containerized webapp
- Provide native macOS integration (menu bar, disc notifications)
- Support both attended and unattended operation modes
- Maintain reliable task processing even when webapp is offline

### Non-Goals (for v1)

- Multiple simultaneous disc drives
- Remote daemon management
- Automatic disc ejection

## Architecture

### Components

| Component | Technology | Role |
|-----------|------------|------|
| Host Daemon | Python + rumps | Menu bar app, disc detection, MakeMKV execution |
| Webapp | FastAPI (Docker) | Orchestration, UI, job management |
| Communication | WebSocket + filesystem | Real-time status + durable task queue |

### Communication Flow

```
┌─────────────────────┐     WebSocket      ┌─────────────────────┐
│                     │◄──────────────────►│                     │
│   Webapp (Docker)   │                    │   Host Daemon       │
│                     │    File Queue      │   (macOS native)    │
│                     │◄──────────────────►│                     │
└─────────────────────┘                    └─────────────────────┘
        │                                          │
        │ /media/ripped                            │ /dev/rdisk4
        │ (mounted volume)                         │ (optical drive)
        ▼                                          ▼
┌─────────────────────┐                    ┌─────────────────────┐
│   Shared Storage    │                    │   Optical Drive     │
└─────────────────────┘                    └─────────────────────┘
```

## Daemon Configuration

The daemon maintains minimal local configuration. Most settings come from the webapp.

### Local Config (`~/.config/amphigory/daemon.yaml`)

```yaml
webapp_url: http://localhost:8080
webapp_basedir: /opt/beehive-docker/amphigory
```

### Webapp Config (`GET /config.json`)

```json
{
  "tasks_directory": "/tasks",
  "websocket_port": 9847,
  "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
  "heartbeat_interval": 10,
  "log_level": "info",
  "makemkv_path": null
}
```

### Path Resolution

The daemon combines its local `webapp_basedir` with paths from webapp config:

```
{webapp_basedir}{tasks_directory}
/opt/beehive-docker/amphigory/tasks
```

### Config Caching

On successful fetch of `/config.json`, daemon caches to `~/.config/amphigory/cached_config.json`. If webapp is unreachable on startup, daemon uses cached config.

### makemkvcon Discovery

If `makemkv_path` is `null`, daemon auto-discovers in order:

1. `which makemkvcon` (check $PATH)
2. `/opt/homebrew/bin/makemkvcon` (Apple Silicon Homebrew)
3. `/usr/local/bin/makemkvcon` (Intel Homebrew)
4. `/Applications/MakeMKV.app/Contents/MacOS/makemkvcon` (app bundle)

If not found, daemon shows error in menu bar and refuses to process tasks.

## File-Based Task Queue

The task queue uses the filesystem for durability. Tasks persist across daemon restarts and webapp disconnections.

### Directory Structure

```
/opt/beehive-docker/amphigory/tasks/
├── tasks.json              # Ordered list of task IDs (webapp maintains)
├── queued/                 # Tasks waiting to be processed
│   └── 20251221-143052-001.json
├── in_progress/            # Currently being processed (max 1)
│   └── 20251221-143045-001.json
└── complete/               # Results ready for webapp
    └── 20251221-143030-001.json
```

### Ownership Model

| Actor | Responsibilities |
|-------|------------------|
| Webapp | Writes tasks to `queued/`, maintains `tasks.json`, reads/deletes from `complete/` |
| Daemon | Reads `tasks.json` for priority, moves tasks `queued/` → `in_progress/`, writes to `complete/`, deletes from `in_progress/`, crash recovery |

### Task Selection

When ready to process a task, the daemon:

1. Reads `tasks.json` to get the ordered list of task IDs
2. Iterates through the list in order
3. For each ID, checks if `queued/{id}.json` exists
4. Picks the first task ID that has a corresponding file in `queued/`
5. Skips any IDs whose files are missing (webapp may have removed them)

This allows the webapp to reprioritize by reordering `tasks.json` or cancel tasks by deleting their files from `queued/`.

### Crash Recovery

On startup, daemon checks `in_progress/` directory:
- If task file exists, previous run crashed mid-task
- Move task back to `queued/` (will be retried)
- Or mark as failed in `complete/` if retries exhausted

## Task JSON Formats

### Scan Task

```json
{
  "id": "20251221-143045-001",
  "type": "scan",
  "created_at": "2025-12-21T14:30:45Z"
}
```

### Rip Task

```json
{
  "id": "20251221-143052-001",
  "type": "rip",
  "created_at": "2025-12-21T14:30:52Z",
  "track": {
    "number": 0,
    "expected_size_bytes": 11397666816,
    "expected_duration": "1:39:56"
  },
  "output": {
    "directory": "/media/ripped/The Polar Express (2004) {imdb-tt0338348}",
    "filename": "The Polar Express (2004) {imdb-tt0338348}.mkv"
  }
}
```

## Response JSON Formats

### Scan Success

```json
{
  "task_id": "20251221-143045-001",
  "status": "success",
  "started_at": "2025-12-21T14:30:45Z",
  "completed_at": "2025-12-21T14:30:52Z",
  "duration_seconds": 7,
  "result": {
    "disc_name": "THE_POLAR_EXPRESS",
    "disc_type": "bluray",
    "tracks": [
      {
        "number": 0,
        "duration": "1:39:56",
        "size_bytes": 11397666816,
        "chapters": 24,
        "resolution": "1920x1080",
        "audio_streams": [
          {"language": "eng", "codec": "TrueHD", "channels": 6}
        ],
        "subtitle_streams": [
          {"language": "eng", "format": "PGS"}
        ]
      }
    ]
  }
}
```

### Rip Success

```json
{
  "task_id": "20251221-143052-001",
  "status": "success",
  "started_at": "2025-12-21T14:30:55Z",
  "completed_at": "2025-12-21T14:45:23Z",
  "duration_seconds": 868,
  "result": {
    "output_path": "/media/ripped/The Polar Express (2004) {imdb-tt0338348}/The Polar Express (2004) {imdb-tt0338348}.mkv",
    "size_bytes": 11397666816
  }
}
```

### Failure Response

```json
{
  "task_id": "20251221-143052-001",
  "status": "failed",
  "started_at": "2025-12-21T14:30:55Z",
  "completed_at": "2025-12-21T14:35:12Z",
  "duration_seconds": 257,
  "error": {
    "code": "DISC_EJECTED",
    "message": "Disc was ejected during rip",
    "detail": "makemkvcon exited with code 1 after 4m17s"
  }
}
```

### Error Codes

| Code | Description |
|------|-------------|
| `DISC_EJECTED` | Disc removed during operation |
| `DISC_UNREADABLE` | MakeMKV can't read the disc |
| `MAKEMKV_FAILED` | General MakeMKV error with exit code |
| `MAKEMKV_TIMEOUT` | Process hung, was killed |
| `OUTPUT_WRITE_FAILED` | Disk full or permission error |
| `TASK_CANCELLED` | User cancelled via pause/stop |
| `UNKNOWN` | Unexpected error; check `detail` field |

## WebSocket Protocol

The daemon runs a WebSocket server. The webapp connects to it.

### Connection Lifecycle

1. Daemon starts WebSocket server on configured port (default 9847)
2. Webapp connects on startup
3. Webapp retries with exponential backoff (1s, 2s, 4s... max 30s) if connection fails
4. On reconnect, daemon sends sync message with current state

### Message Types

#### Progress Update (daemon → webapp)

```json
{
  "type": "progress",
  "task_id": "20251221-143052-001",
  "percent": 47,
  "eta_seconds": 412,
  "current_size_bytes": 5356823040,
  "speed": "42.3 MB/s"
}
```

#### Status Change (daemon → webapp)

```json
{
  "type": "status",
  "task_id": "20251221-143052-001",
  "status": "started"
}
```

```json
{
  "type": "status",
  "task_id": "20251221-143052-001",
  "status": "completed"
}
```

#### Disc Events (daemon → webapp)

```json
{
  "type": "disc",
  "event": "inserted",
  "device": "/dev/rdisk4",
  "volume_name": "THE_POLAR_EXPRESS"
}
```

```json
{
  "type": "disc",
  "event": "ejected",
  "device": "/dev/rdisk4"
}
```

#### Heartbeat (daemon → webapp)

Sent every `heartbeat_interval` seconds (default 10):

```json
{
  "type": "heartbeat",
  "timestamp": "2025-12-21T14:30:52Z",
  "queue_depth": 3,
  "current_task": "20251221-143052-001",
  "paused": false
}
```

#### Daemon Status (daemon → webapp)

```json
{
  "type": "daemon",
  "event": "connected"
}
```

```json
{
  "type": "daemon",
  "event": "paused",
  "reason": "user_requested"
}
```

#### State Sync (daemon → webapp, on reconnect)

```json
{
  "type": "sync",
  "timestamp": "2025-12-21T14:30:52Z",
  "disc": {
    "inserted": true,
    "device": "/dev/rdisk4",
    "volume_name": "THE_POLAR_EXPRESS"
  },
  "current_task": {
    "id": "20251221-143052-001",
    "percent": 47,
    "eta_seconds": 412
  },
  "paused": false,
  "queue_depth": 3
}
```

#### Config Updated (webapp → daemon)

```json
{
  "type": "config_updated"
}
```

Daemon refetches `/config.json` when received.

## Disc Detection

The daemon uses macOS disk notifications (not polling) to detect disc insertion/ejection.

### Proactive Scanning

When a disc is inserted:

1. **Immediate notification:** Daemon sends `disc.inserted` WebSocket message with device and volume name
2. **Background scan:** Daemon immediately starts a MakeMKV scan in the background (takes ~30-60 seconds)
3. **Webapp creates scan task:** Webapp receives insert event and queues a scan task
4. **Fast response:** When daemon processes the scan task, cached results are likely ready

This proactive approach means scan results are often ready before the scan task even arrives. All results flow through the normal task queue (`complete/` directory), keeping task handling in one place.

### Scan Result Caching

The daemon caches the most recent scan result in memory. When a scan task arrives:

- If cached result exists and disc is still inserted: return cached result immediately
- If scan is still in progress: wait for it to complete, then return result
- If no cache (e.g., daemon restarted): run fresh scan

## Menu Bar Interface

### Icon States

The base icon is an optical disc line drawing.

**Activity Icons:**

| State | Icon Description |
|-------|------------------|
| Idle, empty | Disc outline with hollow/empty center (or "?" in center) |
| Idle, disc inserted | Solid disc icon |
| Working | Disc with motion lines or spin indicator |

**Status Overlays (bottom-right corner):**

| Status | Overlay |
|--------|---------|
| Paused | ⏸ pause bars |
| Disconnected | ✕ small X |
| Error | ⚠ warning triangle |

Overlays stack if multiple apply (e.g., paused + disconnected).

### Dropdown Menu

```
┌─────────────────────────────────┐
│ Amphigory                       │
├─────────────────────────────────┤
│ Disc: THE_POLAR_EXPRESS         │  (or "No disc inserted")
├─────────────────────────────────┤
│ Ripping: Track 0                │
│ ██████████░░░░░░░░░░ 47%        │
│ ETA: 6m 52s                     │
│ Queue: 3 tracks                 │
├─────────────────────────────────┤
│ Open Webapp...                  │
│ Help & Documentation...         │  → opens wiki_url in browser
├─────────────────────────────────┤
│ ⏸ Pause After Track             │  (toggles to "▶ Resume" when paused)
│ ⏹ Pause Now                     │  (only shown when working)
│ 🔄 Restart Daemon               │
│ Preferences...                  │  → opens {webapp_url}/config in browser
│ Quit                            │
└─────────────────────────────────┘
```

## Operation Modes

### Attended Mode

User is actively supervising:
- Menu bar shows detailed progress
- Pause controls available
- Errors prompt for user attention

### Unattended Mode

Daemon processes queue autonomously:
- Continues processing until queue empty or error
- Errors logged, task marked failed, continues with next task
- Menu bar shows conservative ETAs

Mode is implicit based on user interaction, not explicitly configured.

## Error Handling

| Scenario | Daemon Behavior |
|----------|-----------------|
| Disc ejected during rip | Write failure response with `DISC_EJECTED`, clear current task |
| MakeMKV fails | Write failure response with `MAKEMKV_FAILED` and exit code |
| MakeMKV hangs | Kill after timeout, write failure response with `MAKEMKV_TIMEOUT` |
| Disc unreadable | Write failure response with `DISC_UNREADABLE` |
| Webapp offline | Continue processing queue, queue up responses in `complete/` |
| Output directory full | Write failure response with `OUTPUT_WRITE_FAILED` |

## Startup Flow

1. Read `~/.config/amphigory/daemon.yaml` for `webapp_url` and `webapp_basedir`
2. Fetch `{webapp_url}/config.json` (or use cached config if unavailable)
3. Discover `makemkvcon` path (or use configured path)
4. Start WebSocket server on configured port
5. Register for macOS disk notifications
6. Check `in_progress/` for crashed tasks (crash recovery)
7. Begin processing queue

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Menu Bar | rumps |
| WebSocket Server | websockets |
| Disk Notifications | PyObjC (NSWorkspace) |
| HTTP Client | httpx |
| Config | PyYAML |

## Future Iterations

- Automatic disc ejection on completion
- Multiple drive support
- Native macOS notifications for completion/errors
