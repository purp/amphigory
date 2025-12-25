"""Tests for resolution-based preset selection."""

import pytest
from amphigory.preset_selector import recommend_preset, parse_resolution


class TestParseResolution:
    def test_parse_1080p(self):
        assert parse_resolution("1920x1080") == (1920, 1080)

    def test_parse_720p(self):
        assert parse_resolution("1280x720") == (1280, 720)

    def test_parse_4k(self):
        assert parse_resolution("3840x2160") == (3840, 2160)

    def test_parse_sd_ntsc(self):
        assert parse_resolution("720x480") == (720, 480)

    def test_parse_sd_pal(self):
        assert parse_resolution("720x576") == (720, 576)

    def test_parse_none_returns_none(self):
        assert parse_resolution(None) is None

    def test_parse_empty_returns_none(self):
        assert parse_resolution("") is None

    def test_parse_invalid_returns_none(self):
        assert parse_resolution("invalid") is None


class TestRecommendPreset:
    def test_4k_recommends_uhd(self):
        assert recommend_preset(3840, 2160) == "uhd"

    def test_1080p_recommends_bluray(self):
        assert recommend_preset(1920, 1080) == "bluray"

    def test_1080i_recommends_bluray(self):
        assert recommend_preset(1920, 1080) == "bluray"

    def test_720p_recommends_dvd(self):
        assert recommend_preset(1280, 720) == "dvd"

    def test_sd_ntsc_recommends_dvd(self):
        assert recommend_preset(720, 480) == "dvd"

    def test_sd_pal_recommends_dvd(self):
        assert recommend_preset(720, 576) == "dvd"

    def test_unknown_resolution_recommends_dvd(self):
        """Default to DVD preset for unknown resolutions."""
        assert recommend_preset(640, 480) == "dvd"

    def test_none_resolution_recommends_dvd(self):
        assert recommend_preset(None, None) == "dvd"
