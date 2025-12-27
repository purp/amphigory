# Resume Interrupted Flows Design

> ✅ **COMPLETED** - Implemented in commit 166afe4

**Goal:** Allow users to resume processing of partially-processed discs without re-doing completed steps.

**Architecture:** Detect known discs by fingerprint, show processing state per track, intelligently skip completed steps when resuming.

**Tech Stack:** SQLite, FastAPI, HTMX, vanilla JavaScript

---

## Disc States

Derived from aggregating track states:

| State | Description |
|-------|-------------|
| Never seen | No track info in database |
| Scanned, not processed | Track info exists, no paths set |
| Partially processed | Some tracks have some paths set |
| Fully processed | All tracks have all paths set |

## Track States

Derived from path columns:

| ripped_path | transcoded_path | inserted_path | State |
|-------------|-----------------|---------------|-------|
| NULL | NULL | NULL | Unprocessed |
| set | NULL | NULL | Ripped only |
| set | set | NULL | Transcoded, awaiting insert |
| set | set | set | Fully processed |

## Database Changes

**New column on `tracks` table:**

```sql
ALTER TABLE tracks ADD COLUMN inserted_path TEXT;
```

- `inserted_path`: Final location in Plex library after insertion

## Visual Representation

**Three icons representing pipeline stages:**

| Step | Icon | Meaning |
|------|------|---------|
| Ripped | 💿 | Raw MKV extracted from disc |
| Transcoded | 🎬 | Converted to final format in inbox |
| Inserted | 📺 | In Plex library, ready to watch |

**CSS states for each icon:**

| State | CSS Treatment |
|-------|---------------|
| Done + file exists | Green (or default color) |
| Done + file missing | Red, with warning indicator |
| Not done yet | Gray, opacity 0.3 |

## Dashboard Behavior

**When disc is inserted and fingerprinted:**

| Disc State | Display |
|------------|---------|
| Known | `Disc detected: {title} ({fingerprint[:7]})` |
| Unknown | `Disc detected: {volume_name} ({fingerprint[:7]})` |

**Track count shown for known discs:**
```
Disc detected: Howl's Moving Castle (a1b2c3d)
6 tracks
[Review Disc]
```

**Button logic:**

| Disc State | Button Text |
|------------|-------------|
| Unknown | "Scan Disc" |
| Known | "Review Disc" |

## Disc Review Page Behavior

**On page load for known disc:**

1. Fetch disc + tracks from database by fingerprint
2. Verify file existence for all paths (eager, on page load)
3. Populate all fields from DB data (don't overwrite existing values)
4. Show track table with status icons
5. Auto-select all unprocessed or partially processed tracks

**Button rename:**
- "Load Previous Scan" → "Reload from DB"

**Track row columns (in order):**

| ☑ | # | Track Name | Type | Duration | Size | Resolution | A/S | Preset | Status | Reset |
|---|---|------------|------|----------|------|------------|-----|--------|--------|-------|
| ☑ | 1 | Howl's Moving Castle (2004) | Main Feature | 1:59:00 | 24.5 GB | 1920x1080 | 2/3 | HQ 1080p | 💿🎬📺 | ↺ |
| ☑ | 2 | Deleted Scene 1 | Deleted Scene | 0:03:45 | 512 MB | 1920x1080 | 1/0 | HQ 1080p | 💿🎬📺 | ↺ |

- A/S = Audio tracks / Subtitle tracks
- Status icons colored by state
- ↺ Reset link for partially processed tracks

## Processing Flow

**When user clicks "Process Selected Tracks":**

1. **Save all page data to database first:**
   - Disc: title, year, imdb_id
   - Tracks: track_name, track_type, preset_name

2. **For each selected track, check files from end to start:**

   | inserted exists? | transcoded exists? | ripped exists? | Action |
   |------------------|-------------------|----------------|--------|
   | Yes | * | * | Skip (done) |
   | No | Yes | * | Insert only |
   | No | No | Yes | Transcode → Insert |
   | No | No | No | Rip → Transcode → Insert |

3. **Reset overrides everything:**
   - Delete ripped file if exists
   - Delete transcoded file if exists
   - Delete inserted file if exists
   - Clear ripped_path, transcoded_path, inserted_path in database
   - Then: Rip → Transcode → Insert

## API Changes

**New endpoints:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/disc/by-fingerprint/{fingerprint}` | Fetch disc + tracks from DB |
| POST | `/api/disc/{disc_id}/save` | Save disc + track edits to DB |
| POST | `/api/tracks/{track_id}/reset` | Delete files, clear paths, mark for reprocessing |
| GET | `/api/tracks/{track_id}/verify-files` | Check if ripped/transcoded/inserted files exist |

**Modified endpoints:**

| Endpoint | Change |
|----------|--------|
| `/api/disc/status` | Include `is_known`, `track_count` when fingerprint matches DB |
| `/api/disc/status-html` | Render "Review Disc" vs "Scan Disc" button based on known state |

**Deferred (for insert feature):**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/tracks/{track_id}/insert` | Move transcoded file to Plex library |

## Deferred Items

- **Insert functionality**: Moving transcoded files to Plex library
- **Background file verification**: If eager check on page load is too slow, switch to async verification with spinner → result pattern
