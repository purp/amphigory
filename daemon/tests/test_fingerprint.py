"""Tests for disc fingerprint generation."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from amphigory_daemon.fingerprint import generate_fingerprint, FingerprintError


class TestFingerprintGeneration:
    """Tests for generate_fingerprint function."""

    def test_returns_string_fingerprint(self, tmp_path):
        """generate_fingerprint returns a string."""
        # Create mock DVD structure
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"fake ifo content 12345")
        (video_ts / "VTS_01_0.IFO").write_bytes(b"fake vts content 67890")

        result = generate_fingerprint(str(tmp_path), "dvd")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_dvd_fingerprint_uses_ifo_files(self, tmp_path):
        """DVD fingerprint incorporates IFO file hashes."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"ifo content")

        fp1 = generate_fingerprint(str(tmp_path), "dvd")

        # Change IFO content
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"different content")

        fp2 = generate_fingerprint(str(tmp_path), "dvd")

        assert fp1 != fp2

    def test_bluray_fingerprint_uses_mpls_files(self, tmp_path):
        """Blu-ray fingerprint incorporates MPLS file hashes."""
        bdmv = tmp_path / "BDMV" / "PLAYLIST"
        bdmv.mkdir(parents=True)
        (bdmv / "00000.mpls").write_bytes(b"playlist content")

        result = generate_fingerprint(str(tmp_path), "bluray")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_fingerprint_includes_volume_name(self, tmp_path):
        """Fingerprint incorporates volume name."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"content")

        # Same content, different volume names
        fp1 = generate_fingerprint(str(tmp_path), "dvd", volume_name="MOVIE_A")
        fp2 = generate_fingerprint(str(tmp_path), "dvd", volume_name="MOVIE_B")

        assert fp1 != fp2

    def test_fingerprint_is_deterministic(self, tmp_path):
        """Same disc produces same fingerprint."""
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"consistent content")

        fp1 = generate_fingerprint(str(tmp_path), "dvd", volume_name="TEST")
        fp2 = generate_fingerprint(str(tmp_path), "dvd", volume_name="TEST")

        assert fp1 == fp2

    def test_raises_error_for_missing_structure(self, tmp_path):
        """Raises FingerprintError if disc structure not found."""
        with pytest.raises(FingerprintError):
            generate_fingerprint(str(tmp_path), "dvd")

    def test_cd_fingerprint_placeholder(self, tmp_path):
        """CD fingerprint returns placeholder (future: use TOC)."""
        # CDs don't have filesystem structure we can easily mock
        # For now, just check it doesn't crash
        result = generate_fingerprint(str(tmp_path), "cd", volume_name="AUDIO_CD")
        assert isinstance(result, str)
