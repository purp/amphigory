# Disc Review Page Fixes - Design

## Overview

A collection of bug fixes and UI improvements for the disc review page discovered during testing.

## Fixes

### 1. Save Disc Info Error Display

**Problem**: Error shows `[object Object]` instead of a readable message.

**Root cause**: Pydantic validation errors return `detail` as an array of error objects, not a string. The client code assumes it's always a string.

**Fix**: Handle both string and array formats:
```javascript
const errorDetail = Array.isArray(error.detail)
    ? error.detail.map(e => e.msg).join(', ')
    : (error.detail || 'Unknown error');
```

### 2. File Missing Indicator

**Problem**: When a path is set but file doesn't exist (data loss), the status icon just shows dimmed. Should be more alarming.

**Fix**: Add CSS for `.status-icon.missing` that superimposes a small red question mark over the dimmed emoji using `::after` pseudo-element.

### 3. Emoji Contrast

**Problem**: Not enough visual difference between done and pending status icons.

**Fix**: Reduce opacity on `.status-icon.pending` from current value to ~0.2 (currently likely ~0.5).

### 4. Type Dropdown Font

**Problem**: Track type `<select>` uses serif font instead of matching the rest of the UI.

**Fix**: Add `font-family: inherit` to `.track-type-select` in CSS.

### 5. Classifier Minimum Threshold

**Problem**: Track with missing info (no chapters, no audio, no subs) still classified as "Main Feature" based on duration alone.

**Fix**: In `classify_tracks()`, add rule: if track has `chapter_count == 0` AND `len(audio_streams) == 0` AND `len(subtitle_streams) == 0`, classify as "other" regardless of duration/score.

### 6. Remove Segment Deduplication

**Problem**: `deduplicate_by_segment()` removes valid tracks that share simple segment maps (e.g., "1") with other tracks. MakeMKV already handles true duplicates.

**Fix**: Remove `deduplicate_by_segment()` call from scan processing. Keep the function for now (may be useful later with better logic).

### 7. Combine Audio/Subs Columns

**Problem**: Audio and Subs take two separate columns, wasting space.

**Fix**:
- Merge into single "A/S" column header
- Display as `{audio_count}/{sub_count}` (e.g., "3/2")
- Header tooltip: "Audio and subtitle track counts"

### 8. Disc Folder Field

**Problem**: "Output Directory" field is ambiguous and in wrong location. Shows full path but each component uses different prefixes.

**Fix**:
- Rename to "Disc Folder"
- Move to Disc Information section (above "Set Track Names")
- Auto-populate when:
  - TMDB result selected: `{title} ({year}) {imdb-{id}}` (if IMDB available)
  - "Save Disc Info" clicked: same format
- User can edit if needed
- Remove old "Output Directory" field from rip options section

### 9. Rename inbox → transcoded

**Problem**: "inbox" terminology is outdated after architecture changes.

**Fix**: Rename throughout:
- Config: `inbox_dir` → `transcoded_dir`
- Paths: `/media/inbox/` → `/media/transcoded/`
- UI labels: "Inbox" → "Transcoded"
- Docker mounts updated accordingly

## Files Affected

**Daemon:**
- `daemon/src/amphigory_daemon/classifier.py` - minimum threshold rule, keep deduplicate function
- `daemon/src/amphigory_daemon/main.py` - remove deduplicate call

**Webapp:**
- `src/amphigory/templates/disc.html` - error handling, A/S column, disc folder field
- `src/amphigory/static/style.css` - missing indicator, emoji contrast, dropdown font
- `src/amphigory/config.py` - inbox → transcoded rename
- `src/amphigory/task_processor.py` - inbox → transcoded
- Various API files - inbox → transcoded

**Config:**
- `docker-compose.amphigory.yaml` - mount point naming
- `Dockerfile` - any inbox references
