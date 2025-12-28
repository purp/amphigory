"""Tests for transcoding service."""

import pytest
from pathlib import Path


def test_transcode_command_construction():
    """Test that transcode commands are constructed correctly."""
    from amphigory.services.transcoder import TranscoderService

    transcoder = TranscoderService()

    cmd = transcoder.build_transcode_command(
        input_path=Path("/media/ripped/movie.mkv"),
        output_path=Path("/media/transcoded/Movie (2024)/Movie (2024).mp4"),
        preset_path=Path("/config/presets/bluray-h265-1080p-v1.json"),
        preset_name="Blu Ray - H.265 1080p",
    )

    assert cmd[0] == "HandBrakeCLI"
    assert "-i" in cmd
    assert "/media/ripped/movie.mkv" in cmd
    assert "-o" in cmd
    assert "Movie (2024).mp4" in cmd[-1] or "/media/transcoded" in " ".join(cmd)


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


def test_transcode_result_dataclass_exists():
    """TranscodeResult dataclass should capture success, return_code, and error_output."""
    from amphigory.services.transcoder import TranscodeResult

    # Success case
    success_result = TranscodeResult(success=True, return_code=0, error_output="")
    assert success_result.success is True
    assert success_result.return_code == 0
    assert success_result.error_output == ""

    # Failure case
    error_lines = "ERROR: Opening input file failed\nNo valid source found."
    failure_result = TranscodeResult(
        success=False,
        return_code=1,
        error_output=error_lines,
    )
    assert failure_result.success is False
    assert failure_result.return_code == 1
    assert "Opening input file failed" in failure_result.error_output


@pytest.mark.asyncio
async def test_transcode_returns_result_object(tmp_path):
    """transcode() should return TranscodeResult instead of bool."""
    from amphigory.services.transcoder import TranscoderService, TranscodeResult
    from unittest.mock import patch, AsyncMock, MagicMock

    transcoder = TranscoderService()

    input_file = tmp_path / "input.mkv"
    input_file.write_text("fake video")
    output_file = tmp_path / "output.mp4"
    preset_path = tmp_path / "preset.json"
    preset_path.write_text("{}")

    # Mock subprocess that fails
    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_process.wait = AsyncMock()

    # Simulate HandBrake error output
    error_output = b"ERROR: Opening input file failed\n"

    async def fake_stdout_iter():
        yield error_output
    mock_process.stdout.__aiter__ = lambda self: fake_stdout_iter()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await transcoder.transcode(
            input_path=input_file,
            output_path=output_file,
            preset_path=preset_path,
            preset_name="Test Preset",
        )

    # Should return TranscodeResult, not bool
    assert isinstance(result, TranscodeResult)
    assert result.success is False
    assert result.return_code == 1
    assert "Opening input file failed" in result.error_output
