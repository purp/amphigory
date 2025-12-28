"""Tests for disc fingerprint generation."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from amphigory_daemon.fingerprint import (
    generate_fingerprint,
    generate_fingerprint_from_drutil,
    FingerprintError,
)


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


class TestDrutilFingerprint:
    """Tests for generate_fingerprint_from_drutil function."""

    def test_returns_string_fingerprint(self):
        """generate_fingerprint_from_drutil returns a string with prefix."""
        drutil_xml = '''<?xml version="1.0"?>
            <statusdoc>
                <usedSpace blockCount="3940480" msf="875:39:55"/>
                <mediaType value="DVD-ROM"/>
                <sessionCount value="1"/>
                <trackCount value="1"/>
            </statusdoc>
        '''
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            result = generate_fingerprint_from_drutil("dvd", "TEST_DISC")

        assert isinstance(result, str)
        assert result.startswith("dvd-")
        assert len(result) == 68  # "dvd-" + 64 hex chars

    def test_different_block_counts_produce_different_fingerprints(self):
        """Different block counts produce different fingerprints."""
        drutil_xml1 = '<usedSpace blockCount="3940480"/><mediaType value="DVD-ROM"/>'
        drutil_xml2 = '<usedSpace blockCount="4000000"/><mediaType value="DVD-ROM"/>'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml1, stderr="")
            fp1 = generate_fingerprint_from_drutil("dvd")

            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml2, stderr="")
            fp2 = generate_fingerprint_from_drutil("dvd")

        assert fp1 != fp2

    def test_same_inputs_produce_same_fingerprint(self):
        """Same inputs produce same fingerprint (deterministic)."""
        drutil_xml = '<usedSpace blockCount="3940480"/><mediaType value="DVD-ROM"/>'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            fp1 = generate_fingerprint_from_drutil("dvd", "TEST")
            fp2 = generate_fingerprint_from_drutil("dvd", "TEST")

        assert fp1 == fp2

    def test_raises_error_when_drutil_fails(self):
        """Raises FingerprintError when drutil fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            with pytest.raises(FingerprintError):
                generate_fingerprint_from_drutil("dvd")

    def test_raises_error_when_no_block_count(self):
        """Raises FingerprintError when blockCount not in output."""
        drutil_xml = '<mediaType value="DVD-ROM"/>'  # No blockCount
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            with pytest.raises(FingerprintError):
                generate_fingerprint_from_drutil("dvd")

    def test_includes_track_info_in_fingerprint(self):
        """Fingerprint includes per-track startAddress and size."""
        # Same block count but different track layouts
        drutil_xml1 = '''
            <usedSpace blockCount="3940480"/>
            <mediaType value="DVD-ROM"/>
            <trackInfoList>
                <trackinfo>
                    <startAddress msf="0:00:00"/>
                    <size msf="875:39:55"/>
                </trackinfo>
            </trackInfoList>
        '''
        drutil_xml2 = '''
            <usedSpace blockCount="3940480"/>
            <mediaType value="DVD-ROM"/>
            <trackInfoList>
                <trackinfo>
                    <startAddress msf="0:02:00"/>
                    <size msf="873:39:55"/>
                </trackinfo>
            </trackInfoList>
        '''

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml1, stderr="")
            fp1 = generate_fingerprint_from_drutil("dvd")

            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml2, stderr="")
            fp2 = generate_fingerprint_from_drutil("dvd")

        assert fp1 != fp2

    def test_includes_lead_out_address(self):
        """Fingerprint includes lastLeadOutStartAddress."""
        drutil_xml1 = '''
            <usedSpace blockCount="3940480"/>
            <lastLeadOutStartAddress msf="875:39:55"/>
        '''
        drutil_xml2 = '''
            <usedSpace blockCount="3940480"/>
            <lastLeadOutStartAddress msf="876:00:00"/>
        '''

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml1, stderr="")
            fp1 = generate_fingerprint_from_drutil("dvd")

            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml2, stderr="")
            fp2 = generate_fingerprint_from_drutil("dvd")

        assert fp1 != fp2

    def test_handles_multiple_tracks(self):
        """Fingerprint handles discs with multiple tracks."""
        drutil_xml = '''
            <usedSpace blockCount="3940480"/>
            <trackInfoList>
                <trackinfo>
                    <startAddress msf="0:00:00"/>
                    <size msf="100:00:00"/>
                </trackinfo>
                <trackinfo>
                    <startAddress msf="100:00:00"/>
                    <size msf="200:00:00"/>
                </trackinfo>
            </trackInfoList>
        '''

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            result = generate_fingerprint_from_drutil("dvd")

        assert isinstance(result, str)
        assert result.startswith("dvd-")

    def test_bluray_prefix(self):
        """Blu-ray discs get br- prefix."""
        drutil_xml = '<usedSpace blockCount="12345678"/>'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            result = generate_fingerprint_from_drutil("bluray")

        assert result.startswith("br-")

    def test_cd_prefix(self):
        """CDs get cd- prefix."""
        drutil_xml = '<usedSpace blockCount="123456"/>'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_xml, stderr="")
            result = generate_fingerprint_from_drutil("cd")

        assert result.startswith("cd-")
