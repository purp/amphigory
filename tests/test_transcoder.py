"""Tests for transcoding service."""

import pytest
from pathlib import Path


def test_transcode_command_construction():
    """Test that transcode commands are constructed correctly."""
    from amphigory.services.transcoder import TranscoderService

    transcoder = TranscoderService()

    cmd = transcoder.build_transcode_command(
        input_path=Path("/media/ripped/movie.mkv"),
        output_path=Path("/media/plex/inbox/Movie (2024)/Movie (2024).mp4"),
        preset_path=Path("/config/presets/bluray-h265-1080p-v1.json"),
        preset_name="Blu Ray - H.265 1080p",
    )

    assert cmd[0] == "HandBrakeCLI"
    assert "-i" in cmd
    assert "/media/ripped/movie.mkv" in cmd
    assert "-o" in cmd
    assert "Movie (2024).mp4" in cmd[-1] or "/media/plex/inbox" in " ".join(cmd)


def test_parse_transcode_progress():
    """Test parsing progress from HandBrake output."""
    from amphigory.services.transcoder import TranscoderService

    transcoder = TranscoderService()

    # Sample HandBrake progress line
    line = "Encoding: task 1 of 1, 45.23 % (87.45 fps, avg 92.31 fps, ETA 00h12m34s)"
    progress = transcoder.parse_progress(line)
    assert progress == 45

    line2 = "Encoding: task 1 of 1, 100.00 %"
    progress2 = transcoder.parse_progress(line2)
    assert progress2 == 100
