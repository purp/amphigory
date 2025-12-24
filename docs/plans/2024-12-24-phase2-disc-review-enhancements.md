# Phase 2: Disc Review Enhancements

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the Disc Review page with intelligent track classification, reordering, title editing, IMDB matching, and Plex-compatible naming.

**Architecture:** Extend database schema to store full scan metadata, implement multi-factor scoring algorithm for track classification, add drag-and-drop reordering UI, integrate TMDB API for movie matching, generate Plex-compatible output paths.

**Tech Stack:** Python, SQLite, FastAPI, Jinja2, JavaScript (drag-and-drop), TMDB API

**Research Reference:** See `docs/Optical Media Classification Research Report.md` for classification algorithm details and Plex naming conventions.

---

## Task 1: Extend Database Schema

**Files:**
- Modify: `src/amphigory/database.py`
- Test: `tests/test_database.py`

**Context:** Add columns for full scan metadata storage, multi-factor scoring inputs, and TV show support.

### Step 1: Write failing test for new tracks columns

```python
# In tests/test_database.py, add:

import pytest
from pathlib import Path
import tempfile

class TestSchemaExtensions:
    @pytest.mark.asyncio
    async def test_tracks_table_has_classification_columns(self):
        """Tracks table includes classification and metadata columns."""
        from amphigory.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.db")
            await db.initialize()

            async with db.connection() as conn:
                cursor = await conn.execute("PRAGMA table_info(tracks)")
                columns = {row[1] for row in await cursor.fetchall()}

            # New columns for classification
            assert "track_name" in columns
            assert "classification_confidence" in columns
            assert "language" in columns
            assert "resolution" in columns
            assert "audio_tracks" in columns
            assert "subtitle_tracks" in columns
            assert "chapter_count" in columns
            assert "segment_map" in columns

            # TV show columns
            assert "season_number" in columns
            assert "episode_number" in columns
            assert "episode_end_number" in columns
            assert "air_date" in columns
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestSchemaExtensions::test_tracks_table_has_classification_columns -v`

Expected: FAIL with AssertionError (columns not found)

### Step 3: Update tracks table schema

In `src/amphigory/database.py`, update the `tracks` table definition:

```sql
-- Individual tracks ripped from a disc
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    disc_id INTEGER REFERENCES discs(id),
    track_number INTEGER,
    track_type TEXT,
    original_name TEXT,
    final_name TEXT,
    duration_seconds INTEGER,
    size_bytes INTEGER,
    ripped_path TEXT,
    transcoded_path TEXT,
    preset_id INTEGER REFERENCES presets(id),
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Classification metadata
    track_name TEXT,
    classification_confidence TEXT,
    language TEXT,
    resolution TEXT,
    audio_tracks JSON,
    subtitle_tracks JSON,
    chapter_count INTEGER,
    segment_map TEXT,

    -- TV show support
    season_number INTEGER,
    episode_number INTEGER,
    episode_end_number INTEGER,
    air_date DATE
);
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestSchemaExtensions::test_tracks_table_has_classification_columns -v`

Expected: PASS

### Step 5: Write failing test for new discs columns

```python
# In tests/test_database.py, add to TestSchemaExtensions:

@pytest.mark.asyncio
async def test_discs_table_has_media_type_columns(self):
    """Discs table includes media type and external ID columns."""
    from amphigory.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        await db.initialize()

        async with db.connection() as conn:
            cursor = await conn.execute("PRAGMA table_info(discs)")
            columns = {row[1] for row in await cursor.fetchall()}

        assert "media_type" in columns
        assert "show_name" in columns
        assert "tmdb_id" in columns
        assert "tvdb_id" in columns
```

### Step 6: Run test to verify it fails

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestSchemaExtensions::test_discs_table_has_media_type_columns -v`

Expected: FAIL

### Step 7: Update discs table schema

In `src/amphigory/database.py`, update the `discs` table definition:

```sql
-- Processed discs
CREATE TABLE IF NOT EXISTS discs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    disc_type TEXT,
    disc_release_year INTEGER,
    edition_notes TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,

    -- Media type and TV support
    media_type TEXT DEFAULT 'movie',
    show_name TEXT,
    tmdb_id TEXT,
    tvdb_id TEXT
);
```

### Step 8: Run test to verify it passes

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py::TestSchemaExtensions::test_discs_table_has_media_type_columns -v`

Expected: PASS

### Step 9: Run all database tests

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_database.py -v`

Expected: All tests PASS

### Step 10: Commit

```bash
git add src/amphigory/database.py tests/test_database.py
git commit -m "$(cat <<'EOF'
feat: extend database schema for classification and TV support

Tracks table additions:
- track_name, classification_confidence, language
- resolution, audio_tracks (JSON), subtitle_tracks (JSON)
- chapter_count, segment_map (for deduplication)
- season_number, episode_number, episode_end_number, air_date

Discs table additions:
- media_type ('movie' or 'tv')
- show_name, tmdb_id, tvdb_id

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Enhance MakeMKV Parser for Full Metadata

**Files:**
- Modify: `daemon/src/amphigory_daemon/makemkv.py`
- Test: `daemon/tests/test_makemkv.py`

**Context:** Parse additional TINFO fields: chapter count (8), segment map (26), and look for FPL_MainFeature marker. Parse SINFO for audio/subtitle track details.

### Step 1: Write failing test for chapter count parsing

```python
# In daemon/tests/test_makemkv.py, add:

class TestEnhancedParsing:
    def test_parse_chapter_count(self):
        """Parser extracts chapter count from TINFO field 8."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
TINFO:0,8,0,"24"
TINFO:0,10,0,"25.5 GB"
'''
        result = parse_scan_output(output)

        assert len(result.tracks) == 1
        assert result.tracks[0].chapter_count == 24
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_chapter_count -v`

Expected: FAIL (chapter_count attribute missing or not parsed)

### Step 3: Add chapter_count to Track dataclass and parser

In `daemon/src/amphigory_daemon/makemkv.py`:

1. Add `chapter_count: int = 0` to the Track dataclass
2. In `parse_scan_output()`, handle TINFO field 8:

```python
elif attr_id == 8:  # Chapter count
    tracks[title_idx].chapter_count = int(value)
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_chapter_count -v`

Expected: PASS

### Step 5: Write failing test for segment map parsing

```python
# In daemon/tests/test_makemkv.py, add:

def test_parse_segment_map(self):
    """Parser extracts segment map from TINFO field 26."""
    from amphigory_daemon.makemkv import parse_scan_output

    output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
TINFO:0,26,0,"1,2,3,4,5"
'''
    result = parse_scan_output(output)

    assert len(result.tracks) == 1
    assert result.tracks[0].segment_map == "1,2,3,4,5"
```

### Step 6: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_segment_map -v`

Expected: FAIL

### Step 7: Add segment_map to Track dataclass and parser

In `daemon/src/amphigory_daemon/makemkv.py`:

1. Add `segment_map: str = ""` to the Track dataclass
2. In `parse_scan_output()`, handle TINFO field 26:

```python
elif attr_id == 26:  # Segment map
    tracks[title_idx].segment_map = value
```

### Step 8: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_segment_map -v`

Expected: PASS

### Step 9: Write failing test for FPL_MainFeature detection

```python
# In daemon/tests/test_makemkv.py, add:

def test_detect_fpl_main_feature(self):
    """Parser detects MakeMKV's FPL_MainFeature marker."""
    from amphigory_daemon.makemkv import parse_scan_output

    output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"0:02:30"
TINFO:1,2,0,"Title #2 (FPL_MainFeature)"
TINFO:1,9,0,"1:45:30"
TINFO:2,2,0,"Title #3"
TINFO:2,9,0,"1:45:30"
'''
    result = parse_scan_output(output)

    assert len(result.tracks) == 3
    assert result.tracks[0].is_main_feature_playlist is False
    assert result.tracks[1].is_main_feature_playlist is True
    assert result.tracks[2].is_main_feature_playlist is False
```

### Step 10: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_detect_fpl_main_feature -v`

Expected: FAIL

### Step 11: Add is_main_feature_playlist to Track and detection logic

In `daemon/src/amphigory_daemon/makemkv.py`:

1. Add `is_main_feature_playlist: bool = False` to the Track dataclass
2. In `parse_scan_output()`, when handling field 2 (title name):

```python
if attr_id == 2:  # Title name
    tracks[title_idx].name = value
    if "(FPL_MainFeature)" in value:
        tracks[title_idx].is_main_feature_playlist = True
```

### Step 12: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_detect_fpl_main_feature -v`

Expected: PASS

### Step 13: Write failing test for audio track parsing from SINFO

```python
# In daemon/tests/test_makemkv.py, add:

def test_parse_audio_tracks_from_sinfo(self):
    """Parser extracts audio track details from SINFO lines."""
    from amphigory_daemon.makemkv import parse_scan_output

    output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
SINFO:0,1,1,0,"TrueHD"
SINFO:0,1,3,0,"English"
SINFO:0,1,4,0,"7.1"
SINFO:0,2,1,0,"AC3"
SINFO:0,2,3,0,"French"
SINFO:0,2,4,0,"5.1"
'''
    result = parse_scan_output(output)

    assert len(result.tracks) == 1
    audio = result.tracks[0].audio_streams
    assert len(audio) == 2
    assert audio[0].codec == "TrueHD"
    assert audio[0].language == "English"
    assert audio[0].channels == "7.1"
    assert audio[1].codec == "AC3"
    assert audio[1].language == "French"
```

### Step 14: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_audio_tracks_from_sinfo -v`

Expected: FAIL (audio_streams not fully populated)

### Step 15: Enhance SINFO parsing for audio tracks

In `daemon/src/amphigory_daemon/makemkv.py`, update the SINFO parsing to capture codec (1), language (3), and channels (4) attributes for audio streams.

### Step 16: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py::TestEnhancedParsing::test_parse_audio_tracks_from_sinfo -v`

Expected: PASS

### Step 17: Run all makemkv tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_makemkv.py -v`

Expected: All tests PASS

### Step 18: Commit

```bash
git add daemon/src/amphigory_daemon/makemkv.py daemon/tests/test_makemkv.py
git commit -m "$(cat <<'EOF'
feat: enhance MakeMKV parser for multi-factor classification

New parsed fields:
- chapter_count (TINFO field 8)
- segment_map (TINFO field 26) for deduplication
- is_main_feature_playlist (FPL_MainFeature marker)
- Full audio stream details (codec, language, channels)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement Multi-Factor Track Classification

**Files:**
- Create: `daemon/src/amphigory_daemon/classifier.py`
- Test: `daemon/tests/test_classifier.py`

**Context:** Implement weighted scoring algorithm from research: duration (40%), chapters (25%), audio richness (20%), subtitles (15%). Include segment deduplication.

### Step 1: Write failing test for multi-factor scoring

```python
# Create daemon/tests/test_classifier.py:

import pytest
from dataclasses import dataclass

class TestMultiFactorClassification:
    def test_classify_identifies_main_feature_by_score(self):
        """Classifier uses multi-factor scoring to identify main feature."""
        from amphigory_daemon.classifier import classify_tracks
        from amphigory_daemon.makemkv import Track, AudioStream

        tracks = [
            Track(
                number=0,
                duration_seconds=150,  # 2.5 min - trailer
                chapter_count=1,
                audio_streams=[AudioStream(language="en", codec="AC3", channels="2.0")],
                subtitle_streams=[],
            ),
            Track(
                number=1,
                duration_seconds=6300,  # 1:45 - main feature
                chapter_count=24,
                audio_streams=[
                    AudioStream(language="en", codec="TrueHD", channels="7.1"),
                    AudioStream(language="en", codec="AC3", channels="5.1"),
                    AudioStream(language="fr", codec="AC3", channels="5.1"),
                ],
                subtitle_streams=[
                    {"language": "en"},
                    {"language": "fr"},
                    {"language": "es"},
                ],
            ),
            Track(
                number=2,
                duration_seconds=900,  # 15 min - featurette
                chapter_count=3,
                audio_streams=[AudioStream(language="en", codec="AC3", channels="5.1")],
                subtitle_streams=[{"language": "en"}],
            ),
        ]

        result = classify_tracks(tracks)

        assert result[1].classification == "main_feature"
        assert result[1].confidence == "high"
        assert result[0].classification == "trailers"
        assert result[2].classification == "featurettes"
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestMultiFactorClassification::test_classify_identifies_main_feature_by_score -v`

Expected: FAIL (module doesn't exist)

### Step 3: Create classifier module with multi-factor scoring

Create `daemon/src/amphigory_daemon/classifier.py`:

```python
"""Track classification using multi-factor scoring algorithm.

Based on research findings:
- Duration: 40% weight (strongest indicator)
- Chapter count: 25% weight
- Audio track richness: 20% weight
- Subtitle count: 15% weight

References:
- docs/Optical Media Classification Research Report.md
"""

from dataclasses import dataclass
from typing import List, Dict, Any

from .makemkv import Track


@dataclass
class ClassifiedTrack:
    """Track with classification results."""
    track: Track
    classification: str
    confidence: str  # 'high', 'medium', 'low'
    score: float


def classify_tracks(tracks: List[Track]) -> Dict[int, ClassifiedTrack]:
    """
    Classify tracks using multi-factor weighted scoring.

    Returns dict mapping track number to ClassifiedTrack.
    """
    if not tracks:
        return {}

    # Check for FPL_MainFeature marker first (95% accuracy)
    for track in tracks:
        if track.is_main_feature_playlist:
            # Trust MakeMKV's detection
            return _classify_with_known_main(tracks, track.number)

    # Calculate max values for normalization
    max_duration = max(t.duration_seconds for t in tracks) or 1
    max_chapters = max(t.chapter_count for t in tracks) or 1
    max_audio = max(len(t.audio_streams) for t in tracks) or 1
    max_subs = max(len(t.subtitle_streams) for t in tracks) or 1

    # Score each track
    scores = {}
    for track in tracks:
        score = 0.0

        # Duration (40% weight) - only if > 1 hour
        if track.duration_seconds > 3600:
            score += 40 * (track.duration_seconds / max_duration)

        # Chapter count (25% weight) - only if > 10 chapters
        if track.chapter_count > 10:
            score += 25 * (track.chapter_count / max_chapters)

        # Audio track richness (20% weight)
        score += 20 * (len(track.audio_streams) / max_audio)

        # Subtitle count (15% weight)
        if max_subs > 0:
            score += 15 * (len(track.subtitle_streams) / max_subs)

        scores[track.number] = score

    # Rank by score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Determine confidence
    if len(ranked) >= 2:
        top_score = ranked[0][1]
        second_score = ranked[1][1]
        if top_score > 0 and (top_score - second_score) / top_score > 0.3:
            main_confidence = "high"
        elif top_score > second_score:
            main_confidence = "medium"
        else:
            main_confidence = "low"
    else:
        main_confidence = "high" if ranked else "low"

    # Build results
    main_track_num = ranked[0][0] if ranked else None
    track_map = {t.number: t for t in tracks}

    results = {}
    for track in tracks:
        if track.number == main_track_num:
            classification = "main_feature"
            confidence = main_confidence
        else:
            classification = _classify_extra(track)
            confidence = "medium"

        results[track.number] = ClassifiedTrack(
            track=track,
            classification=classification,
            confidence=confidence,
            score=scores.get(track.number, 0),
        )

    return results


def _classify_extra(track: Track) -> str:
    """Classify non-main-feature tracks by duration."""
    duration = track.duration_seconds

    # Trailers: ~2 minutes (90-150 seconds)
    if 90 <= duration <= 150:
        return "trailers"

    # Very short: likely menu or junk
    if duration < 90:
        return "other"

    # Featurettes: 5-60 minutes
    if 300 <= duration <= 3600:
        return "featurettes"

    # Longer extras
    if duration > 3600:
        # Could be alternate cut or bonus feature
        return "other"

    # 2.5-5 minutes: could be deleted scene or short
    return "deleted_scenes"


def _classify_with_known_main(tracks: List[Track], main_num: int) -> Dict[int, ClassifiedTrack]:
    """Classify when main feature is known from FPL_MainFeature."""
    results = {}
    for track in tracks:
        if track.number == main_num:
            results[track.number] = ClassifiedTrack(
                track=track,
                classification="main_feature",
                confidence="high",
                score=100.0,
            )
        else:
            results[track.number] = ClassifiedTrack(
                track=track,
                classification=_classify_extra(track),
                confidence="medium",
                score=0.0,
            )
    return results


def deduplicate_by_segment(tracks: List[Track]) -> List[Track]:
    """
    Remove duplicate tracks that share the same segment map.

    Keeps the track with the lowest number (typically the "canonical" one).
    """
    seen_segments = {}
    unique = []

    for track in sorted(tracks, key=lambda t: t.number):
        if not track.segment_map:
            unique.append(track)
            continue

        if track.segment_map not in seen_segments:
            seen_segments[track.segment_map] = track.number
            unique.append(track)
        # else: skip duplicate

    return unique
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestMultiFactorClassification::test_classify_identifies_main_feature_by_score -v`

Expected: PASS

### Step 5: Write test for segment deduplication

```python
# In daemon/tests/test_classifier.py, add:

def test_deduplicate_removes_segment_duplicates(self):
    """Deduplication removes tracks with identical segment maps."""
    from amphigory_daemon.classifier import deduplicate_by_segment
    from amphigory_daemon.makemkv import Track

    tracks = [
        Track(number=0, segment_map="1,2,3,4,5", duration_seconds=6300),
        Track(number=1, segment_map="1,2,3,4,5", duration_seconds=6300),  # Duplicate
        Track(number=2, segment_map="6,7", duration_seconds=900),
        Track(number=3, segment_map="1,2,3,4,5", duration_seconds=6300),  # Duplicate
    ]

    unique = deduplicate_by_segment(tracks)

    assert len(unique) == 2
    assert unique[0].number == 0  # Kept first
    assert unique[1].number == 2
```

### Step 6: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestMultiFactorClassification::test_deduplicate_removes_segment_duplicates -v`

Expected: PASS

### Step 7: Write test for trailer detection (~2 min)

```python
# In daemon/tests/test_classifier.py, add:

def test_classify_trailers_by_duration(self):
    """Tracks around 2 minutes are classified as trailers."""
    from amphigory_daemon.classifier import classify_tracks
    from amphigory_daemon.makemkv import Track

    tracks = [
        Track(number=0, duration_seconds=6300, chapter_count=20),  # Main
        Track(number=1, duration_seconds=120, chapter_count=1),   # 2 min - trailer
        Track(number=2, duration_seconds=135, chapter_count=1),   # 2:15 - trailer
        Track(number=3, duration_seconds=90, chapter_count=1),    # 1:30 - trailer
        Track(number=4, duration_seconds=60, chapter_count=1),    # 1 min - too short
    ]

    result = classify_tracks(tracks)

    assert result[1].classification == "trailers"
    assert result[2].classification == "trailers"
    assert result[3].classification == "trailers"
    assert result[4].classification == "other"  # Too short for trailer
```

### Step 8: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestMultiFactorClassification::test_classify_trailers_by_duration -v`

Expected: PASS

### Step 9: Write test for alternate language main features

```python
# In daemon/tests/test_classifier.py, add:

def test_identify_alternate_language_main_features(self):
    """Tracks with same duration/chapters as main but higher number are alternates."""
    from amphigory_daemon.classifier import classify_tracks, identify_alternate_mains
    from amphigory_daemon.makemkv import Track, AudioStream

    tracks = [
        Track(
            number=0,
            duration_seconds=6300,
            chapter_count=24,
            audio_streams=[AudioStream(language="en", codec="TrueHD", channels="7.1")],
        ),
        Track(
            number=1,
            duration_seconds=6300,  # Same duration
            chapter_count=24,       # Same chapters
            audio_streams=[AudioStream(language="fr", codec="TrueHD", channels="7.1")],
        ),
        Track(
            number=2,
            duration_seconds=6300,
            chapter_count=24,
            audio_streams=[AudioStream(language="de", codec="TrueHD", channels="7.1")],
        ),
        Track(number=3, duration_seconds=120, chapter_count=1),  # Trailer
    ]

    classified = classify_tracks(tracks)
    alternates = identify_alternate_mains(tracks, classified)

    assert classified[0].classification == "main_feature"
    assert 1 in alternates
    assert 2 in alternates
    assert 3 not in alternates
```

### Step 10: Add identify_alternate_mains function

```python
# In daemon/src/amphigory_daemon/classifier.py, add:

def identify_alternate_mains(
    tracks: List[Track],
    classified: Dict[int, ClassifiedTrack]
) -> List[int]:
    """
    Identify tracks that are alternate language versions of the main feature.

    These are tracks with:
    - Same duration (within 1%) as main feature
    - Same chapter count as main feature
    - Higher track number than main feature

    Returns list of track numbers that are alternates.
    """
    # Find main feature
    main_track = None
    for num, ct in classified.items():
        if ct.classification == "main_feature":
            main_track = ct.track
            break

    if not main_track:
        return []

    alternates = []
    for track in tracks:
        if track.number <= main_track.number:
            continue

        # Check duration within 1%
        duration_diff = abs(track.duration_seconds - main_track.duration_seconds)
        if main_track.duration_seconds > 0:
            duration_pct = duration_diff / main_track.duration_seconds
            if duration_pct > 0.01:
                continue

        # Check same chapter count
        if track.chapter_count != main_track.chapter_count:
            continue

        alternates.append(track.number)

    return alternates
```

### Step 11: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestMultiFactorClassification::test_identify_alternate_language_main_features -v`

Expected: PASS

### Step 12: Run all classifier tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py -v`

Expected: All tests PASS

### Step 13: Commit

```bash
git add daemon/src/amphigory_daemon/classifier.py daemon/tests/test_classifier.py
git commit -m "$(cat <<'EOF'
feat: implement multi-factor track classification

Weighted scoring algorithm:
- Duration: 40% (if > 1 hour)
- Chapter count: 25% (if > 10 chapters)
- Audio richness: 20%
- Subtitle count: 15%

Additional features:
- FPL_MainFeature marker detection (95% accuracy)
- Segment map deduplication
- Trailer detection (~2 min duration)
- Alternate language main feature identification

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Smart Default Track Ordering

**Files:**
- Modify: `daemon/src/amphigory_daemon/classifier.py`
- Test: `daemon/tests/test_classifier.py`

**Context:** Order tracks: main feature first, alternate language mains, then others by duration descending.

### Step 1: Write failing test for smart ordering

```python
# In daemon/tests/test_classifier.py, add:

class TestSmartOrdering:
    def test_order_main_first_then_alternates_then_by_duration(self):
        """Smart ordering puts main first, alternates next, then by duration."""
        from amphigory_daemon.classifier import smart_order_tracks, classify_tracks
        from amphigory_daemon.makemkv import Track, AudioStream

        tracks = [
            Track(number=0, duration_seconds=120),    # Trailer
            Track(number=1, duration_seconds=6300, chapter_count=24,
                  audio_streams=[AudioStream(language="en")]),  # Main
            Track(number=2, duration_seconds=900),    # 15 min featurette
            Track(number=3, duration_seconds=6300, chapter_count=24,
                  audio_streams=[AudioStream(language="fr")]),  # Alternate
            Track(number=4, duration_seconds=1800),   # 30 min featurette
        ]

        classified = classify_tracks(tracks)
        ordered = smart_order_tracks(tracks, classified)

        # Main first
        assert ordered[0].number == 1
        # Alternate second
        assert ordered[1].number == 3
        # Then by duration descending
        assert ordered[2].number == 4   # 30 min
        assert ordered[3].number == 2   # 15 min
        assert ordered[4].number == 0   # 2 min trailer
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestSmartOrdering -v`

Expected: FAIL

### Step 3: Implement smart_order_tracks

```python
# In daemon/src/amphigory_daemon/classifier.py, add:

def smart_order_tracks(
    tracks: List[Track],
    classified: Dict[int, ClassifiedTrack]
) -> List[Track]:
    """
    Order tracks for optimal processing:
    1. Main feature (native language - lowest track number among mains)
    2. Alternate language main features (by track number)
    3. All others by duration descending
    """
    track_map = {t.number: t for t in tracks}
    alternates = identify_alternate_mains(tracks, classified)

    main_num = None
    for num, ct in classified.items():
        if ct.classification == "main_feature":
            main_num = num
            break

    ordered = []

    # 1. Main feature first
    if main_num is not None and main_num in track_map:
        ordered.append(track_map[main_num])

    # 2. Alternates by track number
    for alt_num in sorted(alternates):
        if alt_num in track_map:
            ordered.append(track_map[alt_num])

    # 3. Others by duration descending
    others = [
        t for t in tracks
        if t.number != main_num and t.number not in alternates
    ]
    others.sort(key=lambda t: t.duration_seconds, reverse=True)
    ordered.extend(others)

    return ordered
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_classifier.py::TestSmartOrdering -v`

Expected: PASS

### Step 5: Commit

```bash
git add daemon/src/amphigory_daemon/classifier.py daemon/tests/test_classifier.py
git commit -m "$(cat <<'EOF'
feat: add smart track ordering

Orders tracks for optimal processing:
1. Main feature (native language)
2. Alternate language main features
3. All others by duration descending

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Track Reordering UI (Drag-and-Drop)

**Files:**
- Modify: `src/amphigory/templates/disc.html`
- Modify: `src/amphigory/static/style.css`

**Context:** Add drag-and-drop reordering to tracks table. Use HTML5 drag-and-drop API (no external libraries).

### Step 1: Add drag-and-drop attributes to track rows

In `src/amphigory/templates/disc.html`, update the track row template:

```javascript
tbody.innerHTML = result.tracks.map((track, index) => `
    <tr class="track-row ${track.classification === 'main_feature' ? 'main-feature' : ''}"
        draggable="true"
        data-track-index="${index}"
        ondragstart="handleDragStart(event)"
        ondragover="handleDragOver(event)"
        ondrop="handleDrop(event)"
        ondragend="handleDragEnd(event)">
        <!-- ... existing columns ... -->
    </tr>
`).join('');
```

### Step 2: Add drag-and-drop JavaScript handlers

```javascript
// Add to disc.html script section:

let draggedRow = null;

function handleDragStart(e) {
    draggedRow = e.target.closest('tr');
    draggedRow.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const targetRow = e.target.closest('tr');
    if (targetRow && targetRow !== draggedRow) {
        const tbody = targetRow.parentNode;
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const draggedIdx = rows.indexOf(draggedRow);
        const targetIdx = rows.indexOf(targetRow);

        if (draggedIdx < targetIdx) {
            targetRow.after(draggedRow);
        } else {
            targetRow.before(draggedRow);
        }
    }
}

function handleDrop(e) {
    e.preventDefault();
}

function handleDragEnd(e) {
    draggedRow.classList.remove('dragging');
    draggedRow = null;
    updateTrackOrder();
}

function updateTrackOrder() {
    // Update scanResult.tracks to match new DOM order
    const tbody = document.getElementById('tracks-body');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const newOrder = rows.map(row => {
        const trackNum = parseInt(row.querySelector('input[name="tracks"]').value);
        return scanResult.tracks.find(t => (t.number || scanResult.tracks.indexOf(t)) === trackNum);
    });
    scanResult.tracks = newOrder;
}
```

### Step 3: Add drag-and-drop CSS

In `src/amphigory/static/style.css`:

```css
/* Drag and drop */
.track-row {
    cursor: grab;
}

.track-row.dragging {
    opacity: 0.5;
    background: var(--bg-hover);
}

.track-row:active {
    cursor: grabbing;
}

.tracks-table tbody tr {
    transition: transform 0.1s ease;
}
```

### Step 4: Add drag handle column (optional, for better UX)

Add a grip icon column to make it clearer rows can be dragged:

```html
<th class="col-drag"></th>
<!-- ... other headers ... -->

<!-- In row template: -->
<td class="col-drag">
    <span class="drag-handle">⋮⋮</span>
</td>
```

```css
.col-drag {
    width: 30px;
    text-align: center;
}

.drag-handle {
    cursor: grab;
    color: var(--text-muted);
    user-select: none;
}
```

### Step 5: Test manually

Run webapp, load disc page, verify:
- Rows can be dragged and reordered
- Visual feedback during drag
- Order persists when submitting

### Step 6: Commit

```bash
git add src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "$(cat <<'EOF'
feat: add drag-and-drop track reordering

- HTML5 drag-and-drop on track rows
- Visual feedback during drag (opacity, cursor)
- Drag handle column for clarity
- Track order updates in scanResult when reordered

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Disc Title Entry Field

**Files:**
- Modify: `src/amphigory/templates/disc.html`
- Modify: `src/amphigory/api/disc.py`

**Context:** Add editable title field that defaults to scanned disc name.

### Step 1: Add title input field to disc.html

After the scan section, before tracks table:

```html
<section class="disc-info card" id="disc-info-section" style="display: none;">
    <div class="form-row">
        <label for="disc-title">Title:</label>
        <input type="text" id="disc-title" name="disc_title"
               class="setting-input" placeholder="Enter disc title">
    </div>
    <div class="form-row">
        <label for="disc-year">Year:</label>
        <input type="number" id="disc-year" name="disc_year"
               class="setting-input setting-input-small" placeholder="YYYY">
    </div>
</section>
```

### Step 2: Populate title from scan result

In `displayScanResult()`:

```javascript
function displayScanResult(result) {
    // Show disc info section
    const infoSection = document.getElementById('disc-info-section');
    infoSection.style.display = 'block';

    // Populate title (editable)
    document.getElementById('disc-title').value = result.disc_name || '';

    // ... rest of existing code ...
}
```

### Step 3: Include title in rip submission

Update `submitRipTasks()` to include the user-entered title:

```javascript
const discTitle = document.getElementById('disc-title').value;
const discYear = document.getElementById('disc-year').value;

// Include in each rip task
body: JSON.stringify({
    track_number: trackNumber,
    output_filename: `${discTitle || scanResult.disc_name}_track${trackNumber}.mkv`,
    output_directory: outputDir,
    disc_title: discTitle,
    disc_year: discYear ? parseInt(discYear) : null,
}),
```

### Step 4: Add CSS for form layout

```css
.disc-info {
    margin-bottom: 1.5rem;
}

.form-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 0.75rem;
}

.form-row label {
    min-width: 80px;
    font-weight: 500;
}

.setting-input-small {
    width: 100px;
}
```

### Step 5: Commit

```bash
git add src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "$(cat <<'EOF'
feat: add editable disc title and year fields

- Title field defaults to scanned disc name
- Year field for release year
- Both included in rip task submission
- Used for output directory naming

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: TMDB Integration for Movie Matching

**Files:**
- Create: `src/amphigory/tmdb.py`
- Test: `tests/test_tmdb.py`
- Modify: `src/amphigory/templates/disc.html`
- Modify: `src/amphigory/api/disc.py`

**Context:** Search TMDB by title, let user select match, use metadata for naming.

### Step 1: Write failing test for TMDB search

```python
# Create tests/test_tmdb.py:

import pytest
from unittest.mock import patch, AsyncMock

class TestTMDBSearch:
    @pytest.mark.asyncio
    async def test_search_returns_movie_results(self):
        """TMDB search returns list of matching movies."""
        from amphigory.tmdb import search_movies

        mock_response = {
            "results": [
                {
                    "id": 603,
                    "title": "The Matrix",
                    "release_date": "1999-03-30",
                    "overview": "A computer hacker learns...",
                },
                {
                    "id": 604,
                    "title": "The Matrix Reloaded",
                    "release_date": "2003-05-15",
                    "overview": "Six months after...",
                },
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=AsyncMock(json=lambda: mock_response, status_code=200)
            )

            results = await search_movies("The Matrix")

        assert len(results) == 2
        assert results[0]["title"] == "The Matrix"
        assert results[0]["year"] == 1999
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tmdb.py -v`

Expected: FAIL (module doesn't exist)

### Step 3: Create TMDB client module

Create `src/amphigory/tmdb.py`:

```python
"""TMDB API client for movie/TV matching."""

import os
from typing import List, Dict, Any, Optional

import httpx

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


async def search_movies(query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Search TMDB for movies matching query.

    Args:
        query: Movie title to search
        year: Optional release year to filter

    Returns:
        List of movie results with id, title, year, overview
    """
    if not TMDB_API_KEY:
        return []

    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
    }
    if year:
        params["year"] = year

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{TMDB_BASE_URL}/search/movie",
            params=params,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        results = []
        for movie in data.get("results", []):
            release_date = movie.get("release_date", "")
            year = int(release_date[:4]) if release_date else None

            results.append({
                "id": movie["id"],
                "title": movie["title"],
                "year": year,
                "overview": movie.get("overview", ""),
                "poster_path": movie.get("poster_path"),
            })

        return results


async def get_movie_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Get detailed movie info from TMDB."""
    if not TMDB_API_KEY:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{TMDB_BASE_URL}/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY},
        )

        if response.status_code != 200:
            return None

        movie = response.json()
        release_date = movie.get("release_date", "")

        return {
            "id": movie["id"],
            "title": movie["title"],
            "year": int(release_date[:4]) if release_date else None,
            "overview": movie.get("overview", ""),
            "imdb_id": movie.get("imdb_id"),
            "runtime": movie.get("runtime"),
            "genres": [g["name"] for g in movie.get("genres", [])],
        }
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tmdb.py -v`

Expected: PASS

### Step 5: Add TMDB search API endpoint

In `src/amphigory/api/disc.py`:

```python
from amphigory.tmdb import search_movies, get_movie_details

@router.get("/search-tmdb")
async def search_tmdb(query: str, year: Optional[int] = None):
    """Search TMDB for movie matches."""
    results = await search_movies(query, year)
    return {"results": results}

@router.get("/tmdb/{tmdb_id}")
async def get_tmdb_movie(tmdb_id: int):
    """Get movie details from TMDB."""
    details = await get_movie_details(tmdb_id)
    if not details:
        raise HTTPException(status_code=404, detail="Movie not found")
    return details
```

### Step 6: Add TMDB search UI to disc.html

Add search button and results area after title field:

```html
<div class="form-row">
    <label for="disc-title">Title:</label>
    <input type="text" id="disc-title" name="disc_title" class="setting-input">
    <button type="button" class="btn btn-small" onclick="searchTMDB()">
        Search TMDB
    </button>
</div>

<div id="tmdb-results" class="tmdb-results" style="display: none;">
    <!-- Populated by JavaScript -->
</div>
```

```javascript
async function searchTMDB() {
    const title = document.getElementById('disc-title').value;
    const year = document.getElementById('disc-year').value;

    if (!title) return;

    const resultsDiv = document.getElementById('tmdb-results');
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '<p class="text-muted">Searching...</p>';

    try {
        const params = new URLSearchParams({ query: title });
        if (year) params.append('year', year);

        const response = await fetch(`/api/disc/search-tmdb?${params}`);
        const data = await response.json();

        if (data.results.length === 0) {
            resultsDiv.innerHTML = '<p class="text-muted">No results found</p>';
            return;
        }

        resultsDiv.innerHTML = data.results.slice(0, 5).map(movie => `
            <div class="tmdb-result" onclick="selectTMDBResult(${movie.id}, '${escapeHtml(movie.title)}', ${movie.year || 'null'})">
                <strong>${escapeHtml(movie.title)}</strong>
                ${movie.year ? `(${movie.year})` : ''}
                <p class="text-muted small">${escapeHtml(movie.overview?.substring(0, 100) || '')}...</p>
            </div>
        `).join('');

    } catch (error) {
        console.error('TMDB search error:', error);
        resultsDiv.innerHTML = '<p class="error">Search failed</p>';
    }
}

function selectTMDBResult(tmdbId, title, year) {
    document.getElementById('disc-title').value = title;
    if (year) document.getElementById('disc-year').value = year;
    document.getElementById('tmdb-results').style.display = 'none';

    // Store TMDB ID for later use
    window.selectedTMDBId = tmdbId;

    // Update output directory based on selection
    updateOutputDirectory(title, year);
}

function updateOutputDirectory(title, year) {
    const outputDir = document.getElementById('output-dir');
    const safeName = title.replace(/[<>:"/\\|?*]/g, '');
    outputDir.value = `/media/movies/${safeName} (${year || 'Unknown'})`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
```

### Step 7: Add TMDB results CSS

```css
.tmdb-results {
    margin-top: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    max-height: 300px;
    overflow-y: auto;
}

.tmdb-result {
    padding: 0.75rem;
    cursor: pointer;
    border-bottom: 1px solid var(--border-color);
}

.tmdb-result:last-child {
    border-bottom: none;
}

.tmdb-result:hover {
    background: var(--bg-hover);
}

.tmdb-result .small {
    font-size: 0.85rem;
    margin-top: 0.25rem;
}
```

### Step 8: Commit

```bash
git add src/amphigory/tmdb.py tests/test_tmdb.py src/amphigory/api/disc.py src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "$(cat <<'EOF'
feat: add TMDB integration for movie matching

- TMDB search by title and optional year
- Search results displayed with title, year, overview
- Clicking result populates title/year fields
- Output directory auto-updates to Plex format
- Stores TMDB ID for database linking

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Plex-Compatible Track Naming

**Files:**
- Create: `src/amphigory/naming.py`
- Test: `tests/test_naming.py`
- Modify: `src/amphigory/templates/disc.html`

**Context:** Generate Plex-compatible filenames based on track type and TMDB match.

### Step 1: Write failing test for movie naming

```python
# Create tests/test_naming.py:

import pytest

class TestPlexNaming:
    def test_main_feature_naming(self):
        """Main feature uses movie title and year."""
        from amphigory.naming import generate_track_filename

        result = generate_track_filename(
            track_type="main_feature",
            movie_title="The Matrix",
            year=1999,
        )

        assert result == "The Matrix (1999).mkv"

    def test_trailer_naming(self):
        """Trailers use suffix convention."""
        from amphigory.naming import generate_track_filename

        result = generate_track_filename(
            track_type="trailers",
            movie_title="The Matrix",
            year=1999,
            track_name="Theatrical Trailer",
        )

        assert result == "Theatrical Trailer-trailer.mkv"

    def test_featurette_naming(self):
        """Featurettes use suffix convention."""
        from amphigory.naming import generate_track_filename

        result = generate_track_filename(
            track_type="featurettes",
            movie_title="The Matrix",
            year=1999,
            track_name="Making Of",
        )

        assert result == "Making Of-featurette.mkv"
```

### Step 2: Run test to verify it fails

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_naming.py -v`

Expected: FAIL

### Step 3: Create naming module

Create `src/amphigory/naming.py`:

```python
"""Plex-compatible file and directory naming.

References:
- https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/
- https://support.plex.tv/articles/local-files-for-trailers-and-extras/
"""

import re
from typing import Optional

# Plex extras suffixes (must be lowercase, no spaces around hyphen)
PLEX_SUFFIXES = {
    "behind_the_scenes": "-behindthescenes",
    "deleted_scenes": "-deleted",
    "featurettes": "-featurette",
    "interviews": "-interview",
    "scenes": "-scene",
    "shorts": "-short",
    "trailers": "-trailer",
    "other": "-other",
}

# Plex extras subdirectories (Title Case with spaces)
PLEX_DIRECTORIES = {
    "behind_the_scenes": "Behind The Scenes",
    "deleted_scenes": "Deleted Scenes",
    "featurettes": "Featurettes",
    "interviews": "Interviews",
    "scenes": "Scenes",
    "shorts": "Shorts",
    "trailers": "Trailers",
    "other": "Other",
}


def sanitize_filename(name: str) -> str:
    """Remove characters not allowed in filenames."""
    # Remove: < > : " / \ | ? *
    return re.sub(r'[<>:"/\\|?*]', '', name)


def generate_track_filename(
    track_type: str,
    movie_title: str,
    year: Optional[int] = None,
    track_name: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """
    Generate Plex-compatible filename for a track.

    Args:
        track_type: Classification (main_feature, trailers, etc.)
        movie_title: Movie title from TMDB or user
        year: Release year
        track_name: User-provided track name (for extras)
        language: Language code (for alternate main features)

    Returns:
        Filename with .mkv extension
    """
    safe_title = sanitize_filename(movie_title)

    if track_type == "main_feature":
        if language and language.lower() not in ("en", "en-us", "english"):
            # Alternate language main feature
            return f"{safe_title} ({year}) - {language}.mkv"
        return f"{safe_title} ({year}).mkv"

    # Extras use suffix naming
    suffix = PLEX_SUFFIXES.get(track_type, "-other")

    if track_name:
        safe_name = sanitize_filename(track_name)
        return f"{safe_name}{suffix}.mkv"

    # Fallback: use track type as name
    return f"{track_type.replace('_', ' ').title()}{suffix}.mkv"


def generate_output_directory(
    base_path: str,
    movie_title: str,
    year: Optional[int] = None,
    track_type: str = "main_feature",
) -> str:
    """
    Generate Plex-compatible output directory path.

    Args:
        base_path: Base movies directory (e.g., /media/movies)
        movie_title: Movie title
        year: Release year
        track_type: Track classification

    Returns:
        Full directory path
    """
    safe_title = sanitize_filename(movie_title)
    movie_dir = f"{safe_title} ({year})" if year else safe_title

    if track_type == "main_feature":
        return f"{base_path}/{movie_dir}"

    # Extras go in subdirectory
    extra_dir = PLEX_DIRECTORIES.get(track_type, "Other")
    return f"{base_path}/{movie_dir}/{extra_dir}"
```

### Step 4: Run test to verify it passes

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_naming.py -v`

Expected: PASS

### Step 5: Write test for directory generation

```python
# In tests/test_naming.py, add:

def test_main_feature_directory(self):
    """Main feature goes in movie root directory."""
    from amphigory.naming import generate_output_directory

    result = generate_output_directory(
        base_path="/media/movies",
        movie_title="The Matrix",
        year=1999,
        track_type="main_feature",
    )

    assert result == "/media/movies/The Matrix (1999)"

def test_extras_directory(self):
    """Extras go in appropriate subdirectory."""
    from amphigory.naming import generate_output_directory

    result = generate_output_directory(
        base_path="/media/movies",
        movie_title="The Matrix",
        year=1999,
        track_type="behind_the_scenes",
    )

    assert result == "/media/movies/The Matrix (1999)/Behind The Scenes"
```

### Step 6: Run tests

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_naming.py -v`

Expected: All PASS

### Step 7: Integrate naming into disc.html

Update track display to show generated filename:

```javascript
function displayScanResult(result) {
    // ... existing code ...

    // Add track name input column
    tbody.innerHTML = result.tracks.map((track, index) => `
        <tr class="track-row" draggable="true" ...>
            <!-- ... existing columns ... -->
            <td class="col-name">
                <input type="text"
                       class="track-name-input"
                       data-track="${track.number || index}"
                       placeholder="${suggestTrackName(track)}"
                       onchange="updateTrackFilename(this)">
            </td>
        </tr>
    `).join('');
}

function suggestTrackName(track) {
    if (track.classification === 'main_feature') {
        return document.getElementById('disc-title').value || 'Main Feature';
    }
    return track.name || `Track ${track.number}`;
}
```

### Step 8: Commit

```bash
git add src/amphigory/naming.py tests/test_naming.py src/amphigory/templates/disc.html
git commit -m "$(cat <<'EOF'
feat: add Plex-compatible track naming

- Main feature: "Title (Year).mkv"
- Extras: "Name-suffix.mkv" (e.g., "Making Of-featurette.mkv")
- Alternate language: "Title (Year) - Language.mkv"
- Directory structure follows Plex conventions
- Extras placed in subdirectories (Behind The Scenes, Trailers, etc.)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Wire Classification to UI

**Files:**
- Modify: `src/amphigory/api/disc.py`
- Modify: `src/amphigory/templates/disc.html`

**Context:** Apply classification to scan results, display confidence, enable smart ordering.

### Step 1: Add classification endpoint

In `src/amphigory/api/disc.py`:

```python
from amphigory.classifier import classify_tracks, smart_order_tracks, deduplicate_by_segment

@router.post("/classify")
async def classify_scan_result(tracks: list[dict]):
    """Apply multi-factor classification to tracks."""
    # Convert to Track objects
    from amphigory_daemon.makemkv import Track, AudioStream

    track_objs = [
        Track(
            number=t.get("number", i),
            duration_seconds=t.get("duration_seconds", 0),
            chapter_count=t.get("chapter_count", 0),
            segment_map=t.get("segment_map", ""),
            audio_streams=[AudioStream(**a) for a in t.get("audio_streams", [])],
            subtitle_streams=t.get("subtitle_streams", []),
        )
        for i, t in enumerate(tracks)
    ]

    # Deduplicate
    unique = deduplicate_by_segment(track_objs)

    # Classify
    classified = classify_tracks(unique)

    # Smart order
    ordered = smart_order_tracks(unique, classified)

    return {
        "tracks": [
            {
                "number": t.number,
                "classification": classified[t.number].classification,
                "confidence": classified[t.number].confidence,
                "score": classified[t.number].score,
            }
            for t in ordered
        ],
        "removed_duplicates": len(track_objs) - len(unique),
    }
```

### Step 2: Update disc.html to use classification

After receiving scan results, call classification endpoint:

```javascript
async function displayScanResult(result) {
    // Classify tracks
    const classifyResponse = await fetch('/api/disc/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(result.tracks),
    });
    const classification = await classifyResponse.json();

    // Merge classification into tracks
    result.tracks = result.tracks.map(track => {
        const classified = classification.tracks.find(c => c.number === track.number);
        return {
            ...track,
            classification: classified?.classification || 'unknown',
            confidence: classified?.confidence || 'low',
        };
    });

    // Reorder tracks based on smart ordering
    const orderedNumbers = classification.tracks.map(t => t.number);
    result.tracks.sort((a, b) => {
        return orderedNumbers.indexOf(a.number) - orderedNumbers.indexOf(b.number);
    });

    // Show duplicate removal message
    if (classification.removed_duplicates > 0) {
        console.log(`Removed ${classification.removed_duplicates} duplicate tracks`);
    }

    // ... rest of display logic ...
}
```

### Step 3: Add confidence indicator to UI

```javascript
// In track row template:
<td class="col-type">
    <span class="track-type type-${track.classification}">
        ${formatClassification(track.classification)}
    </span>
    <span class="confidence confidence-${track.confidence}" title="Confidence: ${track.confidence}">
        ${track.confidence === 'high' ? '●●●' : track.confidence === 'medium' ? '●●○' : '●○○'}
    </span>
</td>
```

```css
.confidence {
    margin-left: 0.5rem;
    font-size: 0.7rem;
}

.confidence-high { color: var(--success-color); }
.confidence-medium { color: var(--warning-color); }
.confidence-low { color: var(--text-muted); }
```

### Step 4: Commit

```bash
git add src/amphigory/api/disc.py src/amphigory/templates/disc.html src/amphigory/static/style.css
git commit -m "$(cat <<'EOF'
feat: wire classification to disc review UI

- Classification endpoint applies multi-factor scoring
- Tracks reordered by smart ordering
- Confidence indicators (●●● high, ●●○ medium, ●○○ low)
- Duplicate tracks removed via segment deduplication

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Integration Testing

### Step 1: Run all daemon tests

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/ -v`

Expected: All tests PASS

### Step 2: Run all webapp tests

Run: `PYTHONPATH=src .venv/bin/pytest tests/ -v`

Expected: All tests PASS

### Step 3: Manual integration test

1. Start webapp with TMDB_API_KEY set
2. Start daemon
3. Insert disc
4. Verify classification appears with confidence indicators
5. Verify smart ordering (main first)
6. Test drag-and-drop reordering
7. Search TMDB and select match
8. Verify output directory updates
9. Process tracks and verify Plex-compatible naming

### Step 4: Final commit if needed

Fix any integration issues discovered.

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Extend database schema for classification and TV support |
| 2 | Enhance MakeMKV parser (chapters, segments, FPL marker, audio details) |
| 3 | Implement multi-factor classification algorithm |
| 4 | Add smart track ordering |
| 5 | Track reordering UI (drag-and-drop) |
| 6 | Disc title entry field |
| 7 | TMDB integration for movie matching |
| 8 | Plex-compatible track naming |
| 9 | Wire classification to UI |
| 10 | Integration testing |
