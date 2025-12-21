# Amphigory Design Document

**Date:** 2025-12-21

**Status:** Draft - Pending Approval

## Overview

Amphigory (**A**pple **M**akeMKV **P**lex **H**andbrake **I** **G**uess **O**ther **R**andom letters **Y**ielded the rest) is a webapp that automates the process of ripping optical media, transcoding it, and organizing it for a Plex Media Server.

### Goals

- Automate the manual workflow documented in the wiki's "Media Conversion Notes"
- Reduce hands-on time per disc from ~30 minutes of clicking to ~2 minutes of review
- Maintain quality and organization standards already established
- Track what's been processed for future reference and potential reprocessing

### Non-Goals (for v1)

- TV show support (future iteration)
- Music/CD support (future iteration)
- LLM-powered track identification (start with heuristics)
- Remote access / authentication
- Automatic disc ejection / multi-disc handling

## Architecture

### Stack

| Component | Technology |
|-----------|------------|
| Backend | Python / FastAPI |
| Database | SQLite |
| Real-time updates | WebSockets |
| Ripping | makemkvcon (CLI) |
| Transcoding | HandBrakeCLI |
| Container | Docker (in existing docker-compose) |
| UI | Functional HTML first, dashboard later |

### Container Design

Amphigory runs as a single Docker container added to the existing `/opt/beehive-docker/docker-compose.yaml`.

**Required mounts:**

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `/Volumes/Media Drive 1/Ripped` | `/media/ripped` | Raw MKV files from MakeMKV |
| `/Volumes/Media Drive 1/plex-media-server/inbox` | `/media/plex/inbox` | Staging area for transcoded files |
| `/Volumes/Media Drive 1/plex-media-server/data` | `/media/plex/data` | Final Plex library location |
| `/opt/beehive-docker/gollum/wiki-data` | `/wiki` | Wiki repo for Digital Libraries updates |
| `/opt/beehive-docker/amphigory/config` | `/config` | Presets, database, app config |
| Optical drive device | `/dev/cdrom` | Access to disc drive |

**Container requirements:**
- `makemkvcon` installed
- `HandBrakeCLI` installed
- `git` for wiki commits
- Device passthrough for optical drive

### Database Schema (SQLite)

```sql
-- Processed discs
CREATE TABLE discs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    disc_type TEXT, -- 'dvd', 'bluray', 'uhd4k'
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Individual tracks ripped from a disc
CREATE TABLE tracks (
    id INTEGER PRIMARY KEY,
    disc_id INTEGER REFERENCES discs(id),
    track_number INTEGER,
    track_type TEXT, -- 'main', 'featurette', 'trailer', 'deleted_scene', etc.
    original_name TEXT,
    final_name TEXT,
    duration_seconds INTEGER,
    size_bytes INTEGER,
    ripped_path TEXT,
    transcoded_path TEXT,
    preset_id INTEGER REFERENCES presets(id),
    status TEXT, -- 'pending', 'ripping', 'transcoding', 'complete', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Handbrake presets with versioning
CREATE TABLE presets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    disc_type TEXT, -- 'dvd', 'bluray', 'uhd4k'
    preset_json TEXT NOT NULL, -- Full Handbrake preset as JSON
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

-- Job queue for ripping and transcoding
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    track_id INTEGER REFERENCES tracks(id),
    job_type TEXT, -- 'rip', 'transcode'
    status TEXT, -- 'queued', 'running', 'complete', 'failed'
    progress INTEGER DEFAULT 0, -- 0-100
    priority INTEGER DEFAULT 0, -- Higher = sooner
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);
```

## Workflow

### Phase 1: Disc Detection & Identification

1. **Polling service** runs `makemkvcon -r info disc:9999` every 5 seconds
2. When disc appears, extract metadata:
   - Disc volume name / title
   - Track count, durations, sizes
   - Audio and subtitle track info per track
3. **IMDB lookup** using disc title:
   - Query OMDb API or scrape IMDB search
   - Present top matches if ambiguous
   - Allow manual identification if no match
4. Once identified, store IMDB ID, title, year

### Phase 2: Track Analysis & User Review

1. **List all tracks** with heuristic classification:
   - **Main feature:** Longest track, typically 90-180 minutes for movies
   - **Extras:** Shorter tracks categorized by duration patterns
   - **Duplicates:** Similar duration tracks (often different language graphics - e.g., French/Spanish title cards with same audio/subtitles)

2. **Track type heuristics:**
   | Duration | Likely Type |
   |----------|-------------|
   | 80-200 min | Main feature |
   | 20-60 min | Featurette / Behind the scenes |
   | 5-20 min | Deleted scene / Interview |
   | 1-5 min | Trailer / Short |
   | < 1 min | Menu clip / Promo (skip) |

3. **Present to user:**
   - Suggested track selections with checkboxes
   - Editable names and categories
   - Target folder structure preview
   - (Future: 60-second preview clips per track)

4. **User confirms:**
   - Which tracks to rip
   - Final names and types
   - Folder organization

### Phase 3: Ripping

1. **Create folder structure:**
   ```
   /media/ripped/<Movie> (YYYY) {imdb-tt#######}/
   /media/plex/inbox/<Movie> (YYYY) {imdb-tt#######}/
   /media/plex/inbox/<Movie> (YYYY) {imdb-tt#######}/Featurettes/
   /media/plex/inbox/<Movie> (YYYY) {imdb-tt#######}/Deleted Scenes/
   ...etc based on selected extras
   ```

2. **Queue rip jobs:**
   - Main feature first (priority)
   - User can reorder queue
   - User can remove items from queue

3. **Execute ripping:**
   - Run `makemkvcon mkv disc:0 <track> <output_dir>`
   - Stream progress to UI via WebSocket
   - Update job status in database

4. **On track completion:**
   - Immediately queue transcoding job
   - Allows rip and transcode to run in parallel

### Phase 4: Transcoding

1. **Detect source format** from resolution/metadata:
   - DVD: 720x480 or 720x576
   - Blu-ray: 1920x1080
   - UHD 4K: 3840x2160

2. **Select preset:**
   - Match disc type to active preset
   - Store preset ID with track record

3. **Execute transcoding:**
   - Run `HandBrakeCLI -i <input> -o <output> --preset-import-file <preset.json> --preset <name>`
   - Output directly to `/media/plex/inbox/...` with final name
   - Stream progress to UI

4. **Track preset usage:**
   - Record which preset version was used
   - Enables future "reprocess with new preset" feature

### Phase 5: Review & Finalization

1. **Verify completion:**
   - All transcodes finished successfully
   - Output files exist and have reasonable sizes

2. **Present final structure:**
   - Tree view of `/media/plex/inbox/<Movie>/`
   - File sizes and durations
   - Any warnings or issues

3. **User confirmation:**
   - "Move to Plex library" button
   - Move from `inbox` to `/media/plex/data/Movies/`

4. **Update database:**
   - Mark disc as complete
   - Record final paths

### Phase 6: Library Management

Instead of directly editing the wiki, Amphigory provides its own library view:

1. **Library page in webapp:**
   - List all processed discs from database
   - Sortable by title, date, format, preset
   - Filterable (e.g., "show all DVDs using preset v1")
   - Identify candidates for reprocessing

2. **Markdown export:**
   - Generate wiki-compatible markdown
   - Organized by format (DVD, Blu-ray, UHD 4K)
   - Alphabetical within sections
   - One-click write to `/wiki/Digital Libraries.md`

### Phase 7: Cleanup

Separate UI for managing the `/media/ripped` directory:

1. **Tree view of ripped files:**
   - Show folder structure
   - Annotate with database info (disc title, date processed, status)
   - Show file sizes

2. **Selection and deletion:**
   - Multi-select folders/files
   - Delete selected items
   - Confirm before deletion

3. **Orphan detection:**
   - Identify files not in database
   - Identify database entries with missing files

## UI Components (v1)

### Main Dashboard
- Current disc status (none / detected / processing)
- Active job progress (rip and transcode)
- Quick actions

### Disc Review Page
- Track list with checkboxes, names, types
- IMDB info display
- Folder structure preview
- "Start Processing" button

### Queue Page
- Ripping queue with progress bars
- Transcoding queue with progress bars
- Drag to reorder
- Remove from queue

### Library Page
- Searchable/sortable list of processed discs
- Export to wiki button
- Reprocess candidates view

### Cleanup Page
- File tree of `/media/ripped`
- Database annotations
- Delete selected

## Presets Management

Presets stored in filesystem at `/config/presets/`:

```
/config/presets/
├── dvd-h265-720p-v1.json
├── bluray-h265-1080p-v1.json
├── uhd4k-h265-2160p-v1.json
└── presets.yaml  # Maps disc types to active presets
```

**presets.yaml example:**
```yaml
active:
  dvd: dvd-h265-720p-v1
  bluray: bluray-h265-1080p-v1
  uhd4k: uhd4k-h265-2160p-v1
```

When a preset is updated:
1. Export new JSON from Handbrake GUI
2. Save with incremented version (e.g., `dvd-h265-720p-v2.json`)
3. Update `presets.yaml` to point to new version
4. Old presets remain for reference

Database also stores preset JSON for complete reproducibility.

## Future Iterations

### Iteration 2: Enhanced Track Identification
- 60-second preview generation per track
- LLM-powered track identification using Claude API
- Better duplicate detection

### Iteration 3: TV Shows
- Season/episode detection
- Different naming conventions
- Series metadata lookup (TVDB)

### Iteration 4: Music/CDs
- CD ripping support
- Audio transcoding (FLAC, MP3)
- MusicBrainz integration

### Iteration 5: Full Dashboard
- Charts and statistics
- Processing history graphs
- Storage usage tracking
- Notifications

### Iteration 6: Host Helper
- Native macOS daemon for instant disc detection
- Push notifications on completion
- Menu bar status

## Open Questions

1. **Optical drive device path on macOS:** Need to determine exact device path to pass through to container. May need experimentation.

2. **OMDb API key:** Do we need one, or should we scrape IMDB directly?

3. **Preset export:** Need to export current Handbrake presets from GUI before implementation.

## Implementation Plan

*To be created after design approval.*
