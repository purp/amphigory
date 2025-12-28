"""Tests for multi-factor track classification."""

import pytest
from amphigory_daemon.classifier import (
    ClassifiedTrack,
    classify_tracks,
    deduplicate_by_segment,
    identify_alternate_mains,
    _classify_extra,
)
from amphigory_daemon.models import ScannedTrack, AudioStream, SubtitleStream


class TestMultiFactorClassification:
    def test_classify_identifies_main_feature_by_score(self):
        """Classifier uses multi-factor scoring to identify main feature."""
        # Create a clear main feature: long duration, many chapters, rich audio, many subs
        main_track = ScannedTrack(
            number=1,
            duration="01:45:30",  # 1h 45m 30s - over 1 hour
            size_bytes=5_000_000_000,
            chapters=20,  # > 10 chapters
            chapter_count=20,
            resolution="1920x1080",
            audio_streams=[
                AudioStream(language="eng", codec="DTS-HD", channels=8),
                AudioStream(language="spa", codec="AC3", channels=6),
                AudioStream(language="fre", codec="AC3", channels=6),
            ],
            subtitle_streams=[
                SubtitleStream(language="eng", format="PGS"),
                SubtitleStream(language="spa", format="PGS"),
                SubtitleStream(language="fre", format="PGS"),
                SubtitleStream(language="ger", format="PGS"),
            ],
            segment_map="1,2,3,4,5",
        )

        # Create a short extra
        extra_track = ScannedTrack(
            number=2,
            duration="00:02:30",  # 2m 30s
            size_bytes=100_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="6,7",
        )

        tracks = [main_track, extra_track]
        classified = classify_tracks(tracks)

        # Check main feature was identified
        assert 1 in classified
        assert classified[1].classification == "main_feature"
        assert classified[1].score > 0

        # Check extra was identified
        assert 2 in classified
        assert classified[2].classification == "trailers"

    def test_classify_respects_fpl_mainfeature_marker(self):
        """If a track has is_main_feature_playlist=True, it should be main regardless of score."""
        # Create a track with FPL marker but modest specs
        fpl_track = ScannedTrack(
            number=3,
            duration="01:30:00",
            size_bytes=4_000_000_000,
            chapters=15,
            chapter_count=15,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1,2,3",
            is_main_feature_playlist=True,
        )

        # Create a track with better specs but no FPL marker
        better_track = ScannedTrack(
            number=1,
            duration="01:50:00",
            size_bytes=6_000_000_000,
            chapters=25,
            chapter_count=25,
            resolution="1920x1080",
            audio_streams=[
                AudioStream(language="eng", codec="DTS-HD", channels=8),
                AudioStream(language="spa", codec="AC3", channels=6),
                AudioStream(language="fre", codec="AC3", channels=6),
            ],
            subtitle_streams=[
                SubtitleStream(language="eng", format="PGS"),
                SubtitleStream(language="spa", format="PGS"),
            ],
            segment_map="4,5,6",
        )

        tracks = [better_track, fpl_track]
        classified = classify_tracks(tracks)

        # FPL marker should win
        assert classified[3].classification == "main_feature"
        assert classified[1].classification != "main_feature"

    def test_deduplicate_removes_segment_duplicates(self):
        """Deduplication removes tracks with identical segment maps."""
        track1 = ScannedTrack(
            number=1,
            duration="01:30:00",
            size_bytes=4_000_000_000,
            chapters=15,
            chapter_count=15,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1,2,3,4,5",
        )

        # Duplicate segment map, different track number
        track2 = ScannedTrack(
            number=2,
            duration="01:30:00",
            size_bytes=4_000_000_000,
            chapters=15,
            chapter_count=15,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="spa", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1,2,3,4,5",  # Same as track1
        )

        # Different segment map
        track3 = ScannedTrack(
            number=3,
            duration="00:05:00",
            size_bytes=200_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="6,7,8",
        )

        tracks = [track1, track2, track3]
        deduplicated = deduplicate_by_segment(tracks)

        # Should keep track 1 (lowest number) and track 3 (different segments)
        assert len(deduplicated) == 2
        track_numbers = [t.number for t in deduplicated]
        assert 1 in track_numbers
        assert 3 in track_numbers
        assert 2 not in track_numbers

    def test_classify_trailers_by_duration(self):
        """Tracks around 2 minutes are classified as trailers."""
        # 90-150 seconds should be trailers
        trailer1 = ScannedTrack(
            number=1,
            duration="00:01:35",  # 95 seconds
            size_bytes=100_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1",
        )

        trailer2 = ScannedTrack(
            number=2,
            duration="00:02:20",  # 140 seconds
            size_bytes=120_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="2",
        )

        tracks = [trailer1, trailer2]
        classified = classify_tracks(tracks)

        assert classified[1].classification == "trailers"
        assert classified[2].classification == "trailers"

    def test_classify_featurettes_by_duration(self):
        """Tracks 5-60 minutes are classified as featurettes."""
        featurette = ScannedTrack(
            number=1,
            duration="00:15:30",  # 930 seconds, in 300-3600 range
            size_bytes=500_000_000,
            chapters=5,
            chapter_count=5,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1,2",
        )

        tracks = [featurette]
        classified = classify_tracks(tracks)

        assert classified[1].classification == "featurettes"

    def test_classify_deleted_scenes_by_duration(self):
        """Tracks 2.5-5 minutes are classified as deleted_scenes."""
        deleted_scene = ScannedTrack(
            number=1,
            duration="00:03:45",  # 225 seconds, in 150-300 range
            size_bytes=150_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1",
        )

        tracks = [deleted_scene]
        classified = classify_tracks(tracks)

        assert classified[1].classification == "deleted_scenes"

    def test_classify_other_for_very_short(self):
        """Tracks under 90 seconds are classified as other."""
        short_track = ScannedTrack(
            number=1,
            duration="00:00:45",  # 45 seconds
            size_bytes=50_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="1",
        )

        tracks = [short_track]
        classified = classify_tracks(tracks)

        assert classified[1].classification == "other"

    def test_identify_alternate_language_main_features(self):
        """Tracks with same duration/chapters as main are alternates."""
        main_track = ScannedTrack(
            number=1,
            duration="01:45:30",
            size_bytes=5_000_000_000,
            chapters=20,
            chapter_count=20,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="DTS-HD", channels=8)],
            subtitle_streams=[],
            segment_map="1,2,3",
        )

        # Same duration (within 1%) and chapter count, higher track number
        alternate = ScannedTrack(
            number=2,
            duration="01:45:35",  # Within 1% of main
            size_bytes=5_100_000_000,
            chapters=20,
            chapter_count=20,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="spa", codec="DTS-HD", channels=8)],
            subtitle_streams=[],
            segment_map="4,5,6",
        )

        tracks = [main_track, alternate]
        classified = classify_tracks(tracks)

        # Identify alternates
        alternates = identify_alternate_mains(tracks, classified)

        assert 2 in alternates
        assert classified[1].classification == "main_feature"

    def test_confidence_high_when_clear_winner(self):
        """Confidence is high when there's a clear score gap."""
        # Very strong main feature
        main_track = ScannedTrack(
            number=1,
            duration="02:15:00",
            size_bytes=8_000_000_000,
            chapters=30,
            chapter_count=30,
            resolution="1920x1080",
            audio_streams=[
                AudioStream(language="eng", codec="DTS-HD", channels=8),
                AudioStream(language="spa", codec="AC3", channels=6),
                AudioStream(language="fre", codec="AC3", channels=6),
            ],
            subtitle_streams=[
                SubtitleStream(language="eng", format="PGS"),
                SubtitleStream(language="spa", format="PGS"),
            ],
            segment_map="1,2,3",
        )

        # Weak extra
        extra = ScannedTrack(
            number=2,
            duration="00:02:00",
            size_bytes=100_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
            subtitle_streams=[],
            segment_map="4",
        )

        tracks = [main_track, extra]
        classified = classify_tracks(tracks)

        assert classified[1].confidence == "high"

    def test_confidence_low_when_ambiguous(self):
        """Confidence is low when scores are close."""
        # Two similar tracks
        track1 = ScannedTrack(
            number=1,
            duration="01:30:00",
            size_bytes=4_500_000_000,
            chapters=15,
            chapter_count=15,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=6)],
            subtitle_streams=[SubtitleStream(language="eng", format="PGS")],
            segment_map="1,2,3",
        )

        track2 = ScannedTrack(
            number=2,
            duration="01:32:00",
            size_bytes=4_600_000_000,
            chapters=16,
            chapter_count=16,
            resolution="1920x1080",
            audio_streams=[AudioStream(language="eng", codec="AC3", channels=6)],
            subtitle_streams=[SubtitleStream(language="eng", format="PGS")],
            segment_map="4,5,6",
        )

        tracks = [track1, track2]
        classified = classify_tracks(tracks)

        # Main feature should have low confidence due to similar scores
        main_track_num = None
        for num, ct in classified.items():
            if ct.classification == "main_feature":
                main_track_num = num
                break

        assert main_track_num is not None
        assert classified[main_track_num].confidence in ["low", "medium"]


class TestClassifyExtra:
    def test_classify_extra_trailers(self):
        """Test classification of trailers (90-150s)."""
        track = ScannedTrack(
            number=1,
            duration="00:02:00",  # 120 seconds
            size_bytes=100_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[],
            subtitle_streams=[],
            segment_map="1",
        )

        assert _classify_extra(track) == "trailers"

    def test_classify_extra_other(self):
        """Test classification of very short content (<90s)."""
        track = ScannedTrack(
            number=1,
            duration="00:01:00",  # 60 seconds
            size_bytes=50_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[],
            subtitle_streams=[],
            segment_map="1",
        )

        assert _classify_extra(track) == "other"

    def test_classify_extra_featurettes(self):
        """Test classification of featurettes (300-3600s)."""
        track = ScannedTrack(
            number=1,
            duration="00:20:00",  # 1200 seconds
            size_bytes=800_000_000,
            chapters=3,
            chapter_count=3,
            resolution="1920x1080",
            audio_streams=[],
            subtitle_streams=[],
            segment_map="1,2",
        )

        assert _classify_extra(track) == "featurettes"

    def test_classify_extra_deleted_scenes(self):
        """Test classification of deleted scenes (150-300s)."""
        track = ScannedTrack(
            number=1,
            duration="00:04:00",  # 240 seconds
            size_bytes=150_000_000,
            chapters=1,
            chapter_count=1,
            resolution="1920x1080",
            audio_streams=[],
            subtitle_streams=[],
            segment_map="1",
        )

        assert _classify_extra(track) == "deleted_scenes"

    def test_classify_extra_long_featurette(self):
        """Tracks over 1 hour that aren't main features are classified as featurettes."""
        track = ScannedTrack(
            number=1,
            duration="01:30:00",  # 1.5 hours - long but not main feature
            size_bytes=5_000_000_000,
            chapters=5,  # Not enough chapters to be main
            chapter_count=5,
            resolution="1920x1080",
            audio_streams=[],
            subtitle_streams=[],
            segment_map="1",
        )

        assert _classify_extra(track) == "featurettes"


class TestSmartOrdering:
    def test_order_main_first_then_alternates_then_by_duration(self):
        """Smart ordering puts main first, alternates next, then by duration."""
        from amphigory_daemon.classifier import smart_order_tracks, classify_tracks
        from amphigory_daemon.models import ScannedTrack, AudioStream

        tracks = [
            ScannedTrack(
                number=0,
                duration="00:02:00",  # Trailer - 120s
                size_bytes=100_000_000,
                chapters=1,
                chapter_count=1,
                resolution="1920x1080",
                audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
                subtitle_streams=[],
                segment_map="1",
            ),
            ScannedTrack(
                number=1,
                duration="01:45:00",  # Main - 1h 45m
                size_bytes=5_000_000_000,
                chapters=24,
                chapter_count=24,
                resolution="1920x1080",
                audio_streams=[AudioStream(language="eng", codec="DTS-HD", channels=8)],
                subtitle_streams=[],
                segment_map="2,3,4",
            ),
            ScannedTrack(
                number=2,
                duration="00:15:00",  # 15 min featurette
                size_bytes=500_000_000,
                chapters=3,
                chapter_count=3,
                resolution="1920x1080",
                audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
                subtitle_streams=[],
                segment_map="5",
            ),
            ScannedTrack(
                number=3,
                duration="01:45:00",  # Alternate main - 1h 45m
                size_bytes=5_000_000_000,
                chapters=24,
                chapter_count=24,
                resolution="1920x1080",
                audio_streams=[AudioStream(language="fre", codec="DTS-HD", channels=8)],
                subtitle_streams=[],
                segment_map="6,7,8",
            ),
            ScannedTrack(
                number=4,
                duration="00:30:00",  # 30 min featurette
                size_bytes=800_000_000,
                chapters=5,
                chapter_count=5,
                resolution="1920x1080",
                audio_streams=[AudioStream(language="eng", codec="AC3", channels=2)],
                subtitle_streams=[],
                segment_map="9",
            ),
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


def test_track_with_no_metadata_classified_as_other():
    """Track with no chapters, audio, or subs should be 'other' regardless of duration."""
    track = ScannedTrack(
        number=1,
        duration="2:00:00",  # 2 hours - would normally be main_feature
        size_bytes=10_000_000_000,
        chapters=0,
        chapter_count=0,
        audio_streams=[],
        subtitle_streams=[],
        resolution="1920x1080",
        segment_map="1",
        is_main_feature_playlist=False,
    )
    result = classify_tracks([track])
    assert result[1].classification == "other"
