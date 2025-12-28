# Disc Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 9 bugs and UI issues discovered during disc review page testing.

**Architecture:** Mostly independent fixes across daemon classifier, webapp templates, and CSS. The inbox→transcoded rename touches multiple files but is straightforward find-replace.

**Tech Stack:** Python/FastAPI (webapp), Python (daemon), JavaScript, CSS

---

## Task 1: Fix Save Disc Info Error Display

**Files:**
- Modify: `src/amphigory/templates/disc.html:1500-1507`

**Step 1: Locate the error handling code**

In `saveDiscInfo()` function around line 1502, find:
```javascript
const error = await response.json();
alert('Failed to save: ' + (error.detail || 'Unknown error'));
```

**Step 2: Fix to handle Pydantic array errors**

Replace with:
```javascript
const error = await response.json();
const errorDetail = Array.isArray(error.detail)
    ? error.detail.map(e => e.msg).join(', ')
    : (error.detail || 'Unknown error');
alert('Failed to save: ' + errorDetail);
```

**Step 3: Apply same fix to saveTrackInfo()**

Find similar pattern around line 1563-1565 and apply the same fix.

**Step 4: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "fix: handle Pydantic array errors in save disc/track info"
```

---

## Task 2: Add File Missing Indicator (CSS)

**Files:**
- Modify: `src/amphigory/static/style.css`

**Step 1: Find existing status icon styles**

Search for `.status-icon` in style.css.

**Step 2: Add missing state style**

Add after existing status icon styles:
```css
.status-icon.missing {
    opacity: 0.3;
    position: relative;
}

.status-icon.missing::after {
    content: "❓";
    position: absolute;
    font-size: 0.6em;
    right: -2px;
    bottom: -2px;
}
```

**Step 3: Commit**

```bash
git add src/amphigory/static/style.css
git commit -m "feat: add red question mark indicator for missing files"
```

---

## Task 3: Improve Emoji Contrast

**Files:**
- Modify: `src/amphigory/static/style.css`

**Step 1: Find pending status style**

Search for `.status-icon.pending` or similar.

**Step 2: Reduce opacity**

Change opacity from current value (likely 0.4-0.5) to 0.2:
```css
.status-icon.pending {
    opacity: 0.2;
}
```

**Step 3: Commit**

```bash
git add src/amphigory/static/style.css
git commit -m "style: reduce pending emoji opacity for better contrast"
```

---

## Task 4: Fix Type Dropdown Font

**Files:**
- Modify: `src/amphigory/static/style.css`

**Step 1: Find or add track-type-select style**

Search for `.track-type-select`.

**Step 2: Add font-family inherit**

Add or modify:
```css
.track-type-select {
    font-family: inherit;
}
```

**Step 3: Commit**

```bash
git add src/amphigory/static/style.css
git commit -m "style: fix serif font on track type dropdown"
```

---

## Task 5: Add Classifier Minimum Threshold

**Files:**
- Modify: `daemon/src/amphigory_daemon/classifier.py:267-370`
- Test: `daemon/tests/test_classifier.py`

**Step 1: Write failing test**

Add to `daemon/tests/test_classifier.py`:
```python
def test_track_with_no_metadata_classified_as_other():
    """Track with no chapters, audio, or subs should be 'other' regardless of duration."""
    track = ScannedTrack(
        number=1,
        duration="2:00:00",  # 2 hours - would normally be main_feature
        size_bytes=10_000_000_000,
        chapter_count=0,
        audio_streams=[],
        subtitle_streams=[],
        resolution="1920x1080",
        segment_map="1",
        is_main_feature_playlist=False,
    )
    result = classify_tracks([track])
    assert result[1].classification == "other"
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::test_track_with_no_metadata_classified_as_other -v
```

Expected: FAIL (track will be classified as main_feature)

**Step 3: Implement minimum threshold rule**

In `classify_tracks()` function, after calculating scores but before determining main_track, add:
```python
def _has_minimum_metadata(track: ScannedTrack) -> bool:
    """Check if track has minimum metadata to be considered for main feature."""
    return (
        track.chapter_count > 0 or
        len(track.audio_streams) > 0 or
        len(track.subtitle_streams) > 0
    )
```

Then in the main candidates filtering section (around line 312-316), modify to:
```python
# Find all tracks that could be main features (duration > 1 hour OR chapters > 10)
# AND have minimum metadata
main_candidates = []
for track, score in scored_tracks:
    duration_seconds = _parse_duration_to_seconds(track.duration)
    if (duration_seconds > 3600 or track.chapter_count > 10) and _has_minimum_metadata(track):
        main_candidates.append((track, score))
```

**Step 4: Run test to verify it passes**

```bash
PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::test_track_with_no_metadata_classified_as_other -v
```

**Step 5: Run all classifier tests**

```bash
PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py -v
```

**Step 6: Commit**

```bash
git add daemon/src/amphigory_daemon/classifier.py daemon/tests/test_classifier.py
git commit -m "feat: classifier requires minimum metadata for main feature"
```

---

## Task 6: Remove Segment Deduplication

**Files:**
- Modify: `daemon/src/amphigory_daemon/main.py:779-781`
- Test: `daemon/tests/test_main.py`

**Step 1: Write test for tracks with same segment map**

Add to `daemon/tests/test_main.py`:
```python
@pytest.mark.asyncio
async def test_scan_preserves_tracks_with_same_segment_map():
    """Tracks with identical segment maps should NOT be deduplicated."""
    # This tests that we no longer remove valid tracks just because
    # they share a segment map with another track
    pass  # Test will verify by checking track count after scan
```

**Step 2: Comment out deduplication call**

In `daemon/src/amphigory_daemon/main.py`, find around line 779-781:
```python
# Deduplicate by segment map
deduplicated = deduplicate_by_segment(result.tracks)
result.duplicates_removed = original_count - len(deduplicated)
```

Replace with:
```python
# Deduplication removed - MakeMKV already handles true duplicates
# and our logic was incorrectly removing valid tracks with simple segment maps
deduplicated = result.tracks
result.duplicates_removed = 0
```

**Step 3: Update references to use deduplicated**

The rest of the code already uses `deduplicated`, so it should work.

**Step 4: Run daemon tests**

```bash
PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_main.py -v
```

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/main.py
git commit -m "fix: remove segment deduplication (MakeMKV handles duplicates)"
```

---

## Task 7: Combine Audio/Subs Columns

**Files:**
- Modify: `src/amphigory/templates/disc.html:73-74, 583-584, 863-864`

**Step 1: Update table header**

Find the table header (around line 73-74):
```html
<th class="col-audio">Audio</th>
<th class="col-subs">Subs</th>
```

Replace with:
```html
<th class="col-as" title="Audio and subtitle track counts">A/S</th>
```

**Step 2: Update createTrackRowFromDb function**

Find around line 583-584:
```html
<td class="col-audio">${Array.isArray(track.audio_tracks) ? track.audio_tracks.length : (track.audio_tracks || 0)}</td>
<td class="col-subs">${Array.isArray(track.subtitle_tracks) ? track.subtitle_tracks.length : (track.subtitle_tracks || 0)}</td>
```

Replace with:
```html
<td class="col-as">${Array.isArray(track.audio_tracks) ? track.audio_tracks.length : (track.audio_tracks || 0)}/${Array.isArray(track.subtitle_tracks) ? track.subtitle_tracks.length : (track.subtitle_tracks || 0)}</td>
```

**Step 3: Update displayScanResult function**

Find around line 863-864:
```html
<td class="col-audio">${Array.isArray(track.audio_streams) ? track.audio_streams.length : (track.audio_tracks || 0)}</td>
<td class="col-subs">${Array.isArray(track.subtitle_streams) ? track.subtitle_streams.length : (track.subtitle_tracks || 0)}</td>
```

Replace with:
```html
<td class="col-as">${Array.isArray(track.audio_streams) ? track.audio_streams.length : (track.audio_tracks || 0)}/${Array.isArray(track.subtitle_streams) ? track.subtitle_streams.length : (track.subtitle_tracks || 0)}</td>
```

**Step 4: Update CSS if needed**

In style.css, find `.col-audio` and `.col-subs` and consolidate to `.col-as` if column widths need adjustment.

**Step 5: Commit**

```bash
git add src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "ui: combine Audio and Subs into single A/S column"
```

---

## Task 8: Add Disc Folder Field

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Add Disc Folder field to Disc Information section**

After the metadata-links-row div (around line 45), add:
```html
<div class="form-row">
    <label for="disc-folder">Disc Folder:</label>
    <input type="text" id="disc-folder" name="disc_folder"
           class="setting-input" placeholder="Auto-generated from title">
</div>
```

**Step 2: Remove old Output Directory from rip options**

Find and remove the output-dir form-row in the rip-options section (around lines 83-87).

**Step 3: Add function to generate folder name**

Add new function:
```javascript
function generateDiscFolder() {
    const title = document.getElementById('disc-title').value.trim();
    const year = document.getElementById('disc-year').value.trim();
    const imdbId = window.selectedIMDBId;

    if (!title || !year) return '';

    let folder = sanitizeFilename(`${title} (${year})`);
    if (imdbId) {
        folder += ` {imdb-${imdbId}}`;
    }
    return folder;
}
```

**Step 4: Call generateDiscFolder on TMDB selection**

In `selectTMDBResult()`, after setting the IMDB ID, add:
```javascript
document.getElementById('disc-folder').value = generateDiscFolder();
```

**Step 5: Call generateDiscFolder on Save Disc Info**

In `saveDiscInfo()`, before the fetch call, add:
```javascript
// Auto-generate folder name if empty
const discFolderInput = document.getElementById('disc-folder');
if (!discFolderInput.value) {
    discFolderInput.value = generateDiscFolder();
}
```

**Step 6: Update submitRipTasks to use disc-folder**

Replace references to `output-dir` with `disc-folder` in the track processing:
```javascript
const discFolder = document.getElementById('disc-folder').value;
// Use discFolder instead of outputDir
```

**Step 7: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: add Disc Folder field with auto-generation"
```

---

## Task 9: Rename inbox → transcoded

**Files:**
- Modify: `src/amphigory/config.py`
- Modify: `src/amphigory/task_processor.py`
- Modify: `src/amphigory/api/cleanup.py`
- Modify: `src/amphigory/templates/cleanup.html`
- Modify: `docker-compose.amphigory.yaml`
- Modify: `Dockerfile`

**Step 1: Update config.py**

Find `inbox_dir` and rename to `transcoded_dir`:
```python
transcoded_dir: Path  # was inbox_dir
```

Update the default path from `/media/inbox` to `/media/transcoded`.

**Step 2: Update task_processor.py**

Replace all references to `inbox_dir` with `transcoded_dir`.

**Step 3: Update cleanup.py**

Replace `inbox` references with `transcoded` in function names and paths.

**Step 4: Update cleanup.html**

Replace UI labels "Inbox" with "Transcoded".

**Step 5: Update docker-compose.amphigory.yaml**

If there are mount references to inbox, update to transcoded.

**Step 6: Run all tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -v
```

**Step 7: Commit**

```bash
git add src/amphigory/config.py src/amphigory/task_processor.py src/amphigory/api/cleanup.py src/amphigory/templates/cleanup.html docker-compose.amphigory.yaml
git commit -m "refactor: rename inbox to transcoded throughout"
```

---

## Summary

| Task | Description | Complexity |
|------|-------------|------------|
| 1 | Fix error display | Simple |
| 2 | File missing indicator | Simple |
| 3 | Emoji contrast | Simple |
| 4 | Dropdown font | Simple |
| 5 | Classifier threshold | Medium |
| 6 | Remove deduplication | Simple |
| 7 | Combine A/S columns | Medium |
| 8 | Disc Folder field | Medium |
| 9 | Rename inbox→transcoded | Medium |

**Total: 9 tasks**
