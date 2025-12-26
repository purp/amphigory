"""Tests for MakeMKV execution - TDD: tests written first."""

import pytest


class TestParseProgressLine:
    def test_parses_prgv_percent(self):
        """Parse PRGV line to extract percentage."""
        from amphigory_daemon.makemkv import parse_progress_line

        line = "PRGV:123,456,1000"
        progress = parse_progress_line(line)

        assert progress is not None
        assert progress.percent == 45  # 456/1000 * 100

    def test_parses_prgt_message(self):
        """Parse PRGT line to extract task description."""
        from amphigory_daemon.makemkv import parse_progress_line

        line = 'PRGT:2,0,"Analyzing seamless segments"'
        progress = parse_progress_line(line)

        # PRGT contains task info but not percentage
        assert progress is None  # We focus on PRGV for progress

    def test_returns_none_for_non_progress_line(self):
        """Return None for lines that aren't progress updates."""
        from amphigory_daemon.makemkv import parse_progress_line

        line = 'MSG:1005,0,1,"Reading Disc"'
        progress = parse_progress_line(line)

        assert progress is None

    def test_parses_prgc_current_progress(self):
        """Parse PRGC line for current operation progress."""
        from amphigory_daemon.makemkv import parse_progress_line

        line = "PRGC:50,100"
        progress = parse_progress_line(line)

        assert progress is not None
        assert progress.percent == 50


class TestParseScanOutput:
    def test_parses_disc_info(self):
        """Parse disc name and type from scan output."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''MSG:1005,0,1,"Reading Disc"
CINFO:1,6209,"Disc"
CINFO:2,0,"THE_POLAR_EXPRESS"
CINFO:28,0,"disc:0"
CINFO:30,0,"BD-ROM"
TCOUNT:5
'''
        result = parse_scan_output(output)

        assert result.disc_name == "THE_POLAR_EXPRESS"
        assert result.disc_type == "bluray"

    def test_parses_tracks(self):
        """Parse track information from scan output."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''CINFO:2,0,"THE_POLAR_EXPRESS"
CINFO:30,0,"BD-ROM"
TCOUNT:2
TINFO:0,9,0,"1:39:56"
TINFO:0,10,0,"10.6 GB"
TINFO:0,11,0,"11397666816"
TINFO:0,8,0,"24"
SINFO:0,0,1,6201,"Video"
SINFO:0,0,19,0,"1920x1080"
SINFO:0,1,1,6202,"Audio"
SINFO:0,1,3,0,"eng"
SINFO:0,1,4,0,"English"
SINFO:0,1,13,0,"DTS-HD Master Audio"
SINFO:0,1,14,0,"6"
SINFO:0,2,1,6203,"Subtitles"
SINFO:0,2,3,0,"eng"
SINFO:0,2,5,0,"PGS"
TINFO:1,9,0,"0:05:23"
TINFO:1,10,0,"500 MB"
TINFO:1,11,0,"524288000"
'''
        result = parse_scan_output(output)

        assert len(result.tracks) == 2
        assert result.tracks[0].duration == "1:39:56"
        assert result.tracks[0].size_bytes == 11397666816
        assert result.tracks[0].chapters == 24
        assert result.tracks[0].resolution == "1920x1080"
        assert len(result.tracks[0].audio_streams) == 1
        assert result.tracks[0].audio_streams[0].language == "eng"
        assert result.tracks[0].audio_streams[0].channels == 6

    def test_detects_dvd_disc_type(self):
        """Detect DVD from disc info."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''CINFO:2,0,"SOME_DVD"
CINFO:30,0,"DVD"
TCOUNT:1
'''
        result = parse_scan_output(output)

        assert result.disc_type == "dvd"

    def test_detects_uhd_from_resolution(self):
        """Detect UHD 4K from video resolution."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''CINFO:2,0,"UHD_MOVIE"
CINFO:30,0,"BD-ROM"
TCOUNT:1
TINFO:0,9,0,"2:00:00"
TINFO:0,11,0,"50000000000"
SINFO:0,0,1,6201,"Video"
SINFO:0,0,19,0,"3840x2160"
'''
        result = parse_scan_output(output)

        assert result.disc_type == "uhd4k"


class TestBuildScanCommand:
    def test_builds_info_command(self):
        """Build makemkvcon info command."""
        from amphigory_daemon.makemkv import build_scan_command
        from pathlib import Path

        cmd = build_scan_command(Path("/usr/local/bin/makemkvcon"))

        assert cmd == ["/usr/local/bin/makemkvcon", "-r", "info", "disc:0"]


class TestBuildRipCommand:
    def test_builds_mkv_command(self):
        """Build makemkvcon mkv command for ripping."""
        from amphigory_daemon.makemkv import build_rip_command
        from pathlib import Path

        cmd = build_rip_command(
            makemkv_path=Path("/usr/local/bin/makemkvcon"),
            track_number=0,
            output_dir=Path("/media/ripped/Movie"),
        )

        assert cmd == [
            "/usr/local/bin/makemkvcon",
            "-r",
            "mkv",
            "disc:0",
            "0",
            "/media/ripped/Movie",
        ]


class TestEnhancedParsing:
    def test_parse_chapter_count(self):
        """Parser extracts chapter count from TINFO field 8."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
TINFO:0,8,0,"24"
'''
        result = parse_scan_output(output)
        assert result.tracks[0].chapter_count == 24

    def test_parse_segment_map(self):
        """Parser extracts segment map from TINFO field 26."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
TINFO:0,26,0,"1,2,3,4,5"
'''
        result = parse_scan_output(output)
        assert result.tracks[0].segment_map == "1,2,3,4,5"

    def test_detect_fpl_main_feature(self):
        """Parser detects MakeMKV's FPL_MainFeature marker."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
TINFO:1,2,0,"Title #2 (FPL_MainFeature)"
TINFO:2,2,0,"Title #3"
'''
        result = parse_scan_output(output)
        assert result.tracks[0].is_main_feature_playlist is False
        assert result.tracks[1].is_main_feature_playlist is True
        assert result.tracks[2].is_main_feature_playlist is False

    def test_parse_audio_tracks_from_sinfo(self):
        """Parser extracts audio track details from SINFO lines."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
SINFO:0,1,1,0,"TrueHD"
SINFO:0,1,3,0,"English"
SINFO:0,1,4,0,"7.1"
SINFO:0,2,1,0,"AC3"
SINFO:0,2,3,0,"French"
SINFO:0,2,4,0,"5.1"
'''
        result = parse_scan_output(output)
        audio = result.tracks[0].audio_streams
        assert len(audio) == 2
        assert audio[0].codec == "TrueHD"
        assert audio[0].language == "English"
        assert audio[0].channels == "7.1"

    def test_handles_malformed_integer_fields(self):
        """Parser handles malformed integer data gracefully."""
        from amphigory_daemon.makemkv import parse_scan_output

        output = '''TINFO:0,2,0,"Title #1"
TINFO:0,9,0,"1:45:30"
TINFO:0,8,0,"not_a_number"
TINFO:0,11,0,"invalid"
'''
        result = parse_scan_output(output)
        # Should default to 0 for malformed data
        assert result.tracks[0].chapters == 0
        assert result.tracks[0].chapter_count == 0
        assert result.tracks[0].size_bytes == 0


class TestFindAndRenameOutput:
    """Tests for finding and renaming MakeMKV output files."""

    def test_renames_new_mkv_file_to_desired_name(self, tmp_path):
        """New .mkv file created by MakeMKV is renamed to desired filename."""
        from amphigory_daemon.makemkv import find_and_rename_output

        # Simulate existing files in directory before MakeMKV runs
        existing_file = tmp_path / "existing_video.mkv"
        existing_file.write_bytes(b"existing content")
        existing_files = {existing_file}

        # Simulate MakeMKV creating a new file with its default naming
        makemkv_output = tmp_path / "B1_t04.mkv"
        makemkv_output.write_bytes(b"ripped content from disc")

        # Call function to find and rename
        result = find_and_rename_output(
            output_dir=tmp_path,
            existing_files=existing_files,
            desired_filename="Howl's Moving Castle (2004).mkv",
        )

        # Should return tuple of (renamed_path, original_filename)
        assert result is not None
        renamed_path, original_filename = result

        expected_path = tmp_path / "Howl's Moving Castle (2004).mkv"
        assert renamed_path == expected_path
        assert renamed_path.exists()
        assert renamed_path.read_bytes() == b"ripped content from disc"

        # Should include original MakeMKV filename for debugging
        assert original_filename == "B1_t04.mkv"

        # Original MakeMKV filename should no longer exist
        assert not makemkv_output.exists()

    def test_returns_none_when_no_new_file_found(self, tmp_path):
        """Returns None if no new .mkv file was created."""
        from amphigory_daemon.makemkv import find_and_rename_output

        # Only existing files, no new ones
        existing_file = tmp_path / "existing_video.mkv"
        existing_file.write_bytes(b"existing content")
        existing_files = {existing_file}

        result = find_and_rename_output(
            output_dir=tmp_path,
            existing_files=existing_files,
            desired_filename="Movie.mkv",
        )

        assert result is None

    def test_handles_multiple_new_files_returns_largest(self, tmp_path):
        """If multiple new files exist, returns the largest one."""
        from amphigory_daemon.makemkv import find_and_rename_output

        existing_files = set()

        # MakeMKV sometimes creates multiple files - we want the largest
        small_file = tmp_path / "B1_t01.mkv"
        small_file.write_bytes(b"small")

        large_file = tmp_path / "B1_t04.mkv"
        large_file.write_bytes(b"this is the large main feature file")

        result = find_and_rename_output(
            output_dir=tmp_path,
            existing_files=existing_files,
            desired_filename="Movie.mkv",
        )

        assert result is not None
        renamed_path, original_filename = result

        expected_path = tmp_path / "Movie.mkv"
        assert renamed_path == expected_path
        assert renamed_path.read_bytes() == b"this is the large main feature file"
        assert original_filename == "B1_t04.mkv"
