# Database Normalization: Tracks Table

**Status:** Design Complete
**Date:** 2025-12-26

## Problem

Track data from disc scans is stored as a JSON blob in `discs.scan_data` instead of being normalized into the `tracks` table. The `tracks` table has a rich schema but is never populated during normal operation.

## Solution

Normalize track data into the `tracks` table while keeping `scan_data` as a cache for convenience. The `tracks` table becomes the source of truth for track information and status.

## Track Lifecycle

```
discovered → selected → ripping → ripped → transcoding → complete
                ↓           ↓
            deselected   failed
```

- **On scan**: Insert all tracks with `status='discovered'`
- **On selection**: Update selected tracks to `status='selected'`
- **On rip start**: Update to `status='ripping'`
- **On rip complete**: Update to `status='ripped'`, store output file info
- **On transcode complete**: Update to `status='complete'`

## Schema Changes

### New Columns for `tracks` Table

```sql
ALTER TABLE tracks ADD COLUMN makemkv_name TEXT;
ALTER TABLE tracks ADD COLUMN classification_confidence TEXT;
ALTER TABLE tracks ADD COLUMN classification_score REAL;
```

### Field Mapping

| scan_data field | tracks column | Transformation |
|-----------------|---------------|----------------|
| `number` | `track_number` | Direct |
| `duration` | `duration_seconds` | Parse "1:39:56" → 5996 |
| `size_bytes` | `size_bytes` | Direct |
| `chapters` | `chapter_count` | Direct |
| `resolution` | `resolution` | Direct |
| `audio_streams[]` | `audio_tracks` | JSON array |
| `subtitle_streams[]` | `subtitle_tracks` | JSON array |
| `classification` | `track_type` | Direct |
| `confidence` | `classification_confidence` | Direct |
| `score` | `classification_score` | Direct |
| `segment_map` | `segment_map` | Direct |
| `makemkv_name` | `makemkv_name` | Direct (new) |

## Implementation

### Core Change: `save_disc_scan()`

```python
def save_disc_scan(db, fingerprint: str, scan_data: dict) -> int:
    """Save scan results, creating disc and track records."""
    # 1. Upsert disc record (existing logic)
    disc_id = _upsert_disc(db, fingerprint, scan_data)

    # 2. Clear old tracks for this disc (rescan case)
    db.execute("DELETE FROM tracks WHERE disc_id = ?", (disc_id,))

    # 3. Insert new tracks
    for track in scan_data.get("tracks", []):
        _insert_track(db, disc_id, track)

    return disc_id
```

### Helper: Duration Parsing

```python
def parse_duration(duration_str: str) -> int:
    """Parse "1:39:56" to seconds (5996)."""
    parts = duration_str.split(":")
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s
    return int(parts[0])
```

### Migration

For existing databases with populated `scan_data`:

```python
def migrate_scan_data_to_tracks(db):
    """One-time migration of existing scan_data to tracks table."""
    discs = db.execute("SELECT id, scan_data FROM discs WHERE scan_data IS NOT NULL").fetchall()
    for disc_id, scan_data_json in discs:
        scan_data = json.loads(scan_data_json)
        for track in scan_data.get("tracks", []):
            _insert_track(db, disc_id, track)
```

## Query Benefits

```sql
-- Find all main features longer than 90 minutes
SELECT d.title, t.duration_seconds
FROM tracks t JOIN discs d ON t.disc_id = d.id
WHERE t.track_type = 'main_feature' AND t.duration_seconds > 5400;

-- Find discs with Atmos audio
SELECT DISTINCT d.title FROM discs d
JOIN tracks t ON d.id = t.disc_id
WHERE t.audio_tracks LIKE '%Atmos%';

-- Track ripping progress
SELECT status, COUNT(*) FROM tracks GROUP BY status;

-- Get tracks for a disc (replaces JSON parsing)
SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number;
```

## Files to Modify

1. `src/amphigory/database.py` - Add migration, new columns
2. `src/amphigory/api/disc_repository.py` - Update `save_disc_scan()`, add track insertion
3. `src/amphigory/api/disc.py` - Update endpoints to use tracks table
4. `tests/test_database.py` - Test migrations and track insertion
5. `tests/test_disc_repository.py` - Test normalized track operations

## Backward Compatibility

- `scan_data` JSON blob remains populated for caching
- Existing code reading `scan_data` continues to work
- New code should prefer `tracks` table queries
- Gradual migration: update consumers one at a time
