"""Multi-factor track classification for identifying main features and extras."""

from dataclasses import dataclass
from typing import Dict, List
from amphigory_daemon.models import ScannedTrack


@dataclass
class ClassifiedTrack:
    """A track with classification and confidence score.

    Attributes:
        track: The original scanned track
        classification: Track type (main_feature, trailers, featurettes, deleted_scenes, other)
        confidence: Confidence level (high, medium, low)
        score: Weighted score used for classification
    """
    track: ScannedTrack
    classification: str
    confidence: str
    score: float


def _parse_duration_to_seconds(duration: str) -> int:
    """Parse duration string (HH:MM:SS) to seconds.

    Args:
        duration: Duration string in format HH:MM:SS

    Returns:
        Total seconds as integer, or 0 if parsing fails
    """
    try:
        parts = duration.split(":")
        if len(parts) != 3:
            return 0
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except (ValueError, IndexError):
        return 0


def _calculate_score(track: ScannedTrack) -> float:
    """Calculate weighted score for a track based on multiple factors.

    Scoring weights:
    - Duration: 40% (only if > 1 hour)
    - Chapter count: 25% (only if > 10 chapters)
    - Audio track richness: 20%
    - Subtitle count: 15%

    Args:
        track: The track to score

    Returns:
        Weighted score between 0.0 and 1.0
    """
    score = 0.0
    duration_seconds = _parse_duration_to_seconds(track.duration)

    # Duration component (40% weight, only if > 1 hour)
    if duration_seconds > 3600:
        # Normalize to typical feature length (2-3 hours)
        # Anything over 1 hour gets partial credit, maxing at 2.5 hours
        duration_score = min((duration_seconds - 3600) / (2.5 * 3600 - 3600), 1.0)
        score += duration_score * 0.40

    # Chapter count component (25% weight, only if > 10 chapters)
    if track.chapter_count > 10:
        # Normalize to typical chapter counts (10-30)
        chapter_score = min((track.chapter_count - 10) / 20.0, 1.0)
        score += chapter_score * 0.25

    # Audio track richness (20% weight)
    # Count unique languages and prefer higher channel counts
    audio_score = 0.0
    if track.audio_streams:
        unique_languages = len(set(a.language for a in track.audio_streams))
        # 1-2 languages = partial, 3+ = full credit
        audio_score = min(unique_languages / 3.0, 1.0)
    score += audio_score * 0.20

    # Subtitle count (15% weight)
    subtitle_score = 0.0
    if track.subtitle_streams:
        # 1-2 subs = partial, 4+ = full credit
        subtitle_score = min(len(track.subtitle_streams) / 4.0, 1.0)
    score += subtitle_score * 0.15

    return score


def _classify_extra(
    track: ScannedTrack,
    main_duration: int = 0,
    main_size: int = 0
) -> str:
    """Classify non-main feature tracks by duration and similarity to main.

    A track is classified as 'feature' (alternate version) if:
    - Duration is within 10% of main feature AND
    - Size is within 20% of main feature

    Otherwise, duration ranges:
    - 90-150 seconds: trailers
    - < 90 seconds: other
    - 300-3600 seconds: featurettes
    - 150-300 seconds: deleted_scenes

    Args:
        track: The track to classify
        main_duration: Duration of main feature in seconds (for feature detection)
        main_size: Size of main feature in bytes (for feature detection)

    Returns:
        Classification string
    """
    duration_seconds = _parse_duration_to_seconds(track.duration)

    # Check if this looks like an alternate version of the main feature
    if main_duration > 0 and main_size > 0:
        duration_diff = abs(duration_seconds - main_duration) / main_duration if main_duration else 1.0
        size_diff = abs(track.size_bytes - main_size) / main_size if main_size else 1.0

        # Within 10% duration and 20% size = likely an alternate feature
        if duration_diff <= 0.10 and size_diff <= 0.20:
            return "feature"

    if duration_seconds < 90:
        return "other"
    elif duration_seconds <= 150:
        return "trailers"
    elif duration_seconds <= 300:
        return "deleted_scenes"
    elif duration_seconds <= 3600:
        return "featurettes"
    else:
        # Long extras still get classified as featurettes
        return "featurettes"


def deduplicate_by_segment(tracks: List[ScannedTrack]) -> List[ScannedTrack]:
    """Remove tracks with identical segment maps, keeping lowest track number.

    Args:
        tracks: List of scanned tracks

    Returns:
        Deduplicated list of tracks
    """
    seen_segments = {}
    result = []

    for track in sorted(tracks, key=lambda t: t.number):
        segment_map = track.segment_map
        if segment_map and segment_map in seen_segments:
            # Skip this duplicate
            continue
        if segment_map:
            seen_segments[segment_map] = track
        result.append(track)

    return result


def identify_alternate_mains(
    tracks: List[ScannedTrack],
    classified: Dict[int, ClassifiedTrack]
) -> List[int]:
    """Identify alternate language versions of the main feature.

    Alternate mains have:
    - Same duration (within 1%) as the main feature
    - Same chapter count as the main feature
    - Different track number than the main feature

    Args:
        tracks: List of all tracks
        classified: Dictionary of classified tracks

    Returns:
        List of track numbers identified as alternates
    """
    # Find the main feature
    main_track_num = None
    main_track = None
    for num, ct in classified.items():
        if ct.classification == "main_feature":
            main_track_num = num
            main_track = ct.track
            break

    if main_track is None:
        return []

    main_duration = _parse_duration_to_seconds(main_track.duration)
    main_chapters = main_track.chapter_count

    alternates = []
    for track in tracks:
        if track.number == main_track_num:
            continue

        track_duration = _parse_duration_to_seconds(track.duration)
        if main_duration == 0:
            continue

        duration_diff = abs(track_duration - main_duration) / main_duration

        if (duration_diff <= 0.01 and  # Within 1%
            track.chapter_count == main_chapters):
            alternates.append(track.number)

    return alternates


def smart_order_tracks(
    tracks: List[ScannedTrack],
    classified: Dict[int, ClassifiedTrack]
) -> List[ScannedTrack]:
    """
    Order tracks for optimal processing:
    1. Main feature (native language - lowest track number among mains)
    2. Alternate language main features (by track number)
    3. All others by duration descending

    Args:
        tracks: List of all scanned tracks
        classified: Dictionary of classified tracks

    Returns:
        Ordered list of tracks
    """
    # Find the main feature
    main_track = None
    for num, ct in classified.items():
        if ct.classification == "main_feature":
            main_track = ct.track
            break

    # Get alternate main features
    alternates = identify_alternate_mains(tracks, classified)

    # Build ordered list
    ordered = []

    # 1. Main first (if exists)
    if main_track is not None:
        ordered.append(main_track)

    # 2. Alternates sorted by track number
    alternate_tracks = [t for t in tracks if t.number in alternates]
    alternate_tracks.sort(key=lambda t: t.number)
    ordered.extend(alternate_tracks)

    # 3. All others sorted by duration descending
    main_and_alternates = set([main_track.number] if main_track else []) | set(alternates)
    other_tracks = [t for t in tracks if t.number not in main_and_alternates]
    other_tracks.sort(key=lambda t: _parse_duration_to_seconds(t.duration), reverse=True)
    ordered.extend(other_tracks)

    return ordered


def classify_tracks(tracks: List[ScannedTrack]) -> Dict[int, ClassifiedTrack]:
    """Classify tracks using multi-factor weighted scoring.

    Process:
    1. Check for FPL_MainFeature marker (trust MakeMKV's detection)
    2. Calculate weighted scores for each track
    3. Determine confidence based on score gap between top two tracks
    4. Classify non-main tracks by duration

    Args:
        tracks: List of scanned tracks

    Returns:
        Dictionary mapping track number to ClassifiedTrack
    """
    if not tracks:
        return {}

    # First check if any track has the FPL_MainFeature marker
    fpl_main = None
    for track in tracks:
        if track.is_main_feature_playlist:
            fpl_main = track
            break

    # Calculate scores for all tracks
    scored_tracks = []
    for track in tracks:
        score = _calculate_score(track)
        scored_tracks.append((track, score))

    # Sort by score descending, then by track number ascending (prefer lower track numbers)
    scored_tracks.sort(key=lambda x: (-x[1], x[0].number))

    # Determine main feature
    main_track = None
    main_score = 0.0
    confidence = "high"

    if fpl_main is not None:
        # Trust MakeMKV's FPL marker
        main_track = fpl_main
        main_score = next(score for t, score in scored_tracks if t.number == fpl_main.number)
    else:
        # Find all tracks that could be main features (duration > 1 hour OR chapters > 10)
        main_candidates = []
        for track, score in scored_tracks:
            duration_seconds = _parse_duration_to_seconds(track.duration)
            if duration_seconds > 3600 or track.chapter_count > 10:
                main_candidates.append((track, score))

        if main_candidates:
            # Find the highest score
            max_score = max(score for _, score in main_candidates)

            # Find all candidates within 1% of the max score
            threshold = max_score * 0.01
            top_candidates = [
                (track, score) for track, score in main_candidates
                if max_score - score <= threshold
            ]

            # Among the top candidates, pick the one with the lowest track number
            top_candidates.sort(key=lambda x: x[0].number)
            main_track, main_score = top_candidates[0]

    # Calculate confidence based on score gap (only if we have a main track)
    if main_track is not None and len(scored_tracks) > 1:
        second_score = scored_tracks[1][1]
        score_gap = main_score - second_score

        if score_gap > 0.3:
            confidence = "high"
        elif score_gap > 0.15:
            confidence = "medium"
        else:
            confidence = "low"

    # Get main feature duration and size for feature detection
    main_duration = 0
    main_size = 0
    if main_track is not None:
        main_duration = _parse_duration_to_seconds(main_track.duration)
        main_size = main_track.size_bytes

    # Build classification results
    result = {}
    for track, score in scored_tracks:
        if main_track is not None and track.number == main_track.number:
            classification = "main_feature"
            track_confidence = confidence
        else:
            classification = _classify_extra(track, main_duration, main_size)
            # Features (alternate versions) get medium confidence since detection is heuristic
            track_confidence = "medium" if classification == "feature" else "high"

        result[track.number] = ClassifiedTrack(
            track=track,
            classification=classification,
            confidence=track_confidence,
            score=score,
        )

    return result
