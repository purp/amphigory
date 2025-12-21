"""Tests for MakeMKV output parsing."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_output():
    """Load sample MakeMKV output."""
    fixture_path = Path(__file__).parent / "fixtures" / "makemkv_output.txt"
    return fixture_path.read_text()


def test_parse_disc_info(sample_output):
    """Test parsing disc-level information."""
    from amphigory.makemkv import parse_makemkv_output

    result = parse_makemkv_output(sample_output)

    assert result.disc_type == "bluray"
    assert result.volume_name == "LOGICAL_VOLUME_ID"
    assert result.device_path == "/dev/rdisk4"


def test_parse_tracks(sample_output):
    """Test parsing track information."""
    from amphigory.makemkv import parse_makemkv_output

    result = parse_makemkv_output(sample_output)

    assert len(result.tracks) > 0

    # Check main feature (title 0)
    main = result.tracks[0]
    assert main.title_id == 0
    assert main.duration_str == "1:39:56"
    assert main.size_bytes == 11397666816
    assert main.resolution == "1920x1080"
    assert main.suggested_name == "title_t00.mkv"


def test_classify_tracks(sample_output):
    """Test heuristic track classification."""
    from amphigory.makemkv import parse_makemkv_output, classify_tracks

    result = parse_makemkv_output(sample_output)
    classified = classify_tracks(result.tracks)

    # Should identify one main feature
    main_features = [t for t in classified if t.classification == "main"]
    assert len(main_features) == 1
    assert main_features[0].title_id == 0
