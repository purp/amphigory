# UI Improvements Design

**Status:** ✅ Implemented
**Date:** 2025-12-26

## Overview

Three improvements to the Amphigory UI:
1. Persist TMDB/IMDB metadata when user approves a match
2. Show timing info for current task and fix progress bar
3. Add expandable details for completed tasks

---

## 1. Disc Review - Persist TMDB/IMDB Selection

**Problem:** When user selects a TMDB search result, the metadata (TMDB ID, IMDB ID, title, year) is stored in JavaScript variables and lost on page refresh.

**Solution:** Save metadata to the `discs` table (which already has `tmdb_id`, `imdb_id` columns) when user explicitly approves.

### Trigger Points

Metadata is saved when user:
- Clicks "Save Disc Info" button in the disc information section
- Clicks "Process Selected Tracks" (saves as part of creating rip tasks)

### API Endpoint

```
POST /api/disc/metadata
{
  "fingerprint": "abc123...",
  "tmdb_id": "123456",
  "imdb_id": "tt1234567",
  "title": "Howl's Moving Castle",
  "year": 2004
}
```

Updates `discs` table columns: `tmdb_id`, `imdb_id`, `title`, `year`

### UI Changes

- Add "Save Disc Info" button next to title/year inputs
- "Process Selected Tracks" also triggers the save
- On page load, if disc has stored metadata, pre-populate fields and show TMDB/IMDB links

---

## 2. Queue Page - Current Task Timing & Progress Fix

**Problem:**
- Current task shows no timing information
- Progress bar never advances (daemon sends progress but webapp doesn't relay it)

### Progress Bar Fix

- Daemon sends `{"type": "progress", "task_id": "...", "percent": 45, ...}` to webapp
- Webapp currently ignores this message type
- **Fix:** Add handler in `main.py:websocket_endpoint` to broadcast progress to browser clients
- Browser's `websocket.js` already handles progress messages correctly

### Current Task Timing

- Add "Started: HH:MM:SS" showing when task began
- Add "Elapsed: Xm XXs" showing time since start (updates every second)
- Hover on truncated task ID shows full ID via `title` attribute tooltip

### UI Layout

```
┌─────────────────────────────────────────────────────┐
│ rip          20251226T1... [hover shows full ID]    │
│ Started: 2:34 PM · Elapsed: 3m 42s                  │
│ ████████████░░░░░░░░░░░░  45% - 2:15 remaining      │
└─────────────────────────────────────────────────────┘
```

---

## 3. Queue Page - Completed Task Details

**Problem:** Completed tasks show minimal info with no way to see details.

**Solution:** Click a completed task row to expand/collapse inline details.

### Expanded View Shows

- **All tasks:** Full task ID, start time, end time, duration
- **Rip tasks:** Output directory, output filename, track number
- **Failed tasks:** Error code and message

### Duration Format

- `32s` for short tasks
- `45m 32s` for medium tasks
- `1h 23m 45s` for long tasks

### UI Layout (Expanded)

```
┌─────────────────────────────────────────────────────┐
│ ✓ success    rip    20251225T2... ▼                 │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Task ID: 20251225T205623.860835-rip             │ │
│ │ Started: Dec 25, 8:56 PM                        │ │
│ │ Completed: Dec 25, 9:42 PM                      │ │
│ │ Duration: 45m 32s                               │ │
│ │ Output Dir: /media/ripped                       │ │
│ │ Output File: Howl's Moving Castle (2004).mkv    │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Failed Task Layout

```
│ │ Error: [Errno 30] Read-only file system: '/media' │ │
```

---

## Data Sources

### Completed Task JSON Structure

```json
{
  "task_id": "2025-12-25T20:56:23.860835-rip",
  "status": "success",
  "started_at": "2025-12-25T20:56:24.566282",
  "completed_at": "2025-12-25T21:42:15.123456",
  "duration_seconds": 2751,
  "result": {
    "destination": {
      "directory": "/media/ripped",
      "filename": "Howl's Moving Castle (2004).mkv"
    }
  }
}
```

For failed tasks:
```json
{
  "status": "failed",
  "error": {
    "code": "UNKNOWN",
    "message": "Unexpected error",
    "detail": "[Errno 30] Read-only file system: '/media'"
  }
}
```
