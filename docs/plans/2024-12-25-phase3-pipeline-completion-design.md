# Phase 3: Pipeline Completion Design

**Date:** 2024-12-25

**Status:** Approved

## Overview

Phase 3 completes the Amphigory pipeline by adding automatic transcoding, a library catalog, storage cleanup tools, wiki integration, and end-to-end testing.

### Goals

- Automate transcoding after ripping completes
- Provide a searchable catalog of processed discs with reprocessing flags
- Enable storage management for temporary ripped files and inbox
- Export processing history to Gollum wiki
- Add integration and UI tests for confidence in the full pipeline

### Non-Goals (for Phase 3)

- TV show episode matching (future)
- Music/CD support (future)
- Preset documentation pages in wiki (future enhancement)
- Real hardware E2E tests (save for specific problems)

## 1. Transcoding Workflow

### Trigger

When daemon completes a rip task and writes the response to `complete/`, the webapp detects this and automatically queues a transcode job.

### Preset Selection

Resolution-based recommendation with user override:

| Track Resolution | Recommended Preset |
|------------------|-------------------|
| 3840x2160 | UHD preset |
| 1920x1080+ | Blu-ray preset |
| 1280x720 | DVD preset |
| 720x480/576 (SD) | DVD preset |

Logic:
1. Parse track resolution from scan data
2. Map to appropriate preset
3. Show recommendation on Disc Review page
4. User can override via dropdown before processing

### Disc Review Flow

1. **Scan disc** → show tracks with classification and confidence
2. **User searches TMDB** → captures TMDB ID, extracts IMDB ID
3. **Generate folder name:** `{Title} ({Year}) {imdb-tt#######}`
4. **Generate per-track final names:**
   - Main feature: `{Title} ({Year}) {imdb-tt#######}.mp4`
   - Alternate language: `{Title} ({Year}) {imdb-tt#######} {lang-es}.mp4` or `{lang-alt1}`
   - Extras: `Trailer-1.mp4`, `Featurette-1.mp4`, etc.
5. **Show preset recommendation** per track (resolution-based)
6. **User reviews/edits**, system validates for conflicts (duplicate names)
7. **"Process Disc"** → enqueue rip tasks → daemon rips → webapp transcodes

### Execution

- Webapp runs background job runner (asyncio task)
- Polls `jobs` table for queued transcode jobs
- Uses existing `TranscoderService.transcode()`
- Broadcasts progress via WebSocket
- Updates track status and `transcoded_path` on completion

### Output

- Transcoded files: `/media/plex/inbox/{Movie Name (Year) {imdb-id}}/`
- Extras in subdirectories: `Featurettes/`, `Trailers/`, etc.

## 2. Library Page

### Purpose

Catalog of all processed discs with flagging for reprocessing.

### Main View

Searchable, sortable, filterable table:

| Column | Description |
|--------|-------------|
| Title | Disc title |
| Year | Release year |
| Type | DVD / Blu-ray / UHD |
| Content | Movie / TV / Music |
| Tracks | Number of tracks processed |
| Processed | Date processed |
| Status | ✓ Complete / ⚠ Needs Attention / ○ Not Processed |

Click row to expand/navigate to disc details.

### Filters

- Content type (Movie, TV, Music)
- Disc type (DVD, Blu-ray, UHD)
- Status (All, Complete, Needs Attention, Not Processed)
- Text search on title

### Disc Detail View

- All tracks with final names and paths
- "Show in Finder" link (file:/// to containing folder)
- Flag for reprocessing with options:
  - "Re-rip needed"
  - "Re-transcode needed"
  - "Missing tracks to add"
- Notes field for details

### Needs Attention View

Filtered list showing flagged discs with flag type and notes.

## 3. Cleanup Page

### Purpose

Manage temporary storage (ripped MKVs and inbox files).

### Tab 1: Ripped Files (`/media/ripped/`)

- Tree view of folders (one per disc)
- Per-folder info: name, total size, file count, age, transcode status
- Transcode status: "All transcoded" | "In progress" | "Pending" | "Partial"
- Multi-select with checkboxes (disabled for enqueued/in-progress)
- "Delete Selected" with confirmation
- Footer: "Total: X GB | Selected: Y GB (N folders)"

### Tab 2: Inbox Files (`/media/plex/inbox/`)

Sectioned by Plex destination:

- **Movies** → `/media/plex/data/Movies/`
- **TV Shows** → `/media/plex/data/TV-Shows/`
- **Music** → `/media/plex/data/Music/`

Per-folder: name, total size, file count, age. Multi-select with "Move to Plex" and "Delete Selected" actions.

### Safety Features

- Cannot select files currently enqueued for processing
- Confirmation dialog shows items and total size
- "Delete All Completed" bulk action for fully transcoded ripped files

## 4. Wiki Integration

### Structure

```
wiki/
└── Media Library/
    ├── Home.md           # Auto-generated index
    ├── Movies/
    │   ├── Coco-2017.md
    │   └── The-Polar-Express-2004.md
    ├── TV-Shows/
    │   └── ...
    └── Music/
        └── ...
```

### Index Page (Home.md)

```markdown
# Media Library

## Movies

### UHD
- [Movie Title (Year)](Movies/Movie-Title-Year.md)

### Blu-ray
- [Coco (2017)](Movies/Coco-2017.md)

### DVD
- [Another Movie (2005)](Movies/Another-Movie-2005.md)
```

- UHD → Blu-ray → DVD ordering
- Only render sections/subsections with content
- Empty categories omitted

### Per-Disc Page

```markdown
# Coco (2017)

| Field | Value |
|-------|-------|
| IMDB | [tt2380307](https://imdb.com/title/tt2380307) |
| TMDB | [354912](https://themoviedb.org/movie/354912) |
| Disc Type | Blu-ray |
| Processed | 2024-12-25 |

## Tracks

| # | Type | Duration | Resolution | Ripped | Preset | Final Name |
|---|------|----------|------------|--------|--------|------------|
| 1 | Main Feature | 1:45:00 | 1080p | ✓ | bluray-h265 | Coco (2017) {imdb-tt2380307}.mp4 |
| 2 | Featurette | 0:12:34 | 720p | ✓ | dvd-h265 | Featurettes/Featurette-1.mp4 |
| 3 | Trailer | 0:02:15 | 1080p | ✗ | - | - |

## Notes

User notes if any.
```

### Triggers

- Disc page auto-created when processing completes
- Manual "Rebuild Index" button regenerates Home.md
- Wiki location configurable (default: `/wiki/` in data directory)
- Git commit optional (checkbox in settings)

## 5. E2E Testing

### Mock-based Integration Tests

| Test | Coverage |
|------|----------|
| Scan → Review → Process | Mock MakeMKV → Disc Review → Process enqueues jobs |
| Rip completion → Transcode | Mock rip complete → Auto-queue transcode → Mock HandBrake → Track updated |
| Library CRUD | Process → Library listing → Flag → Needs Attention view |
| Cleanup operations | Mock file tree → Select → Delete → Verify |
| Wiki generation | Process → Wiki page created → Index updated |

Mocking approach:
- Fixture files with real MakeMKV/HandBrake output
- Mock `asyncio.create_subprocess_exec`
- In-memory SQLite for tests

### Playwright UI Tests

| Test | Coverage |
|------|----------|
| Disc Review flow | Load → TMDB search → Select tracks → Change preset → Process |
| Library browsing | Filter → Search → Expand disc → Flag |
| Cleanup flow | Switch tabs → Select folders → Delete with confirmation |
| Queue monitoring | View jobs → Progress updates |

Infrastructure:
- pytest-playwright
- Test server with seeded database

## Database Changes

### New Columns for `discs` table

```sql
-- Reprocessing flags
ALTER TABLE discs ADD COLUMN needs_reprocessing BOOLEAN DEFAULT FALSE;
ALTER TABLE discs ADD COLUMN reprocessing_type TEXT;  -- 're-rip', 're-transcode', 'missing-tracks'
ALTER TABLE discs ADD COLUMN reprocessing_notes TEXT;
```

### New Columns for `tracks` table

```sql
-- Preset tracking
ALTER TABLE tracks ADD COLUMN preset_name TEXT;
```

## API Endpoints

### New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/tasks/transcode | Create transcode task |
| GET | /api/library | List processed discs with filters |
| GET | /api/library/{disc_id} | Get disc details |
| PATCH | /api/library/{disc_id}/flag | Set reprocessing flag |
| GET | /api/cleanup/ripped | List ripped folders with status |
| DELETE | /api/cleanup/ripped | Delete selected folders |
| GET | /api/cleanup/inbox | List inbox folders by destination |
| POST | /api/cleanup/inbox/move | Move folders to Plex |
| POST | /api/wiki/generate | Generate disc wiki page |
| POST | /api/wiki/rebuild-index | Rebuild Home.md |

## UI Pages

| Page | Route | Purpose |
|------|-------|---------|
| Library | /library | Disc catalog with filtering |
| Library Detail | /library/{id} | Single disc details |
| Cleanup | /cleanup | Storage management tabs |
| (existing) Disc Review | /disc | Enhanced with preset dropdown |
| (existing) Queue | /queue | Shows transcode jobs too |
