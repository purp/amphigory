"""Tests for menu bar icons - TDD: tests written first."""

import pytest


class TestActivityState:
    def test_has_idle_empty_state(self):
        """ActivityState has IDLE_EMPTY."""
        from amphigory_daemon.icons import ActivityState
        assert hasattr(ActivityState, "IDLE_EMPTY")

    def test_has_idle_disc_state(self):
        """ActivityState has IDLE_DISC."""
        from amphigory_daemon.icons import ActivityState
        assert hasattr(ActivityState, "IDLE_DISC")

    def test_has_working_state(self):
        """ActivityState has WORKING."""
        from amphigory_daemon.icons import ActivityState
        assert hasattr(ActivityState, "WORKING")


class TestStatusOverlay:
    def test_has_none_overlay(self):
        """StatusOverlay has NONE."""
        from amphigory_daemon.icons import StatusOverlay
        assert hasattr(StatusOverlay, "NONE")

    def test_has_paused_overlay(self):
        """StatusOverlay has PAUSED."""
        from amphigory_daemon.icons import StatusOverlay
        assert hasattr(StatusOverlay, "PAUSED")

    def test_has_disconnected_overlay(self):
        """StatusOverlay has DISCONNECTED."""
        from amphigory_daemon.icons import StatusOverlay
        assert hasattr(StatusOverlay, "DISCONNECTED")

    def test_has_error_overlay(self):
        """StatusOverlay has ERROR."""
        from amphigory_daemon.icons import StatusOverlay
        assert hasattr(StatusOverlay, "ERROR")

    def test_has_needs_config_overlay(self):
        """StatusOverlay has NEEDS_CONFIG for cold-start mode."""
        from amphigory_daemon.icons import StatusOverlay
        assert hasattr(StatusOverlay, "NEEDS_CONFIG")

    def test_disconnected_overlay_used_for_storage_unavailable(self):
        """DISCONNECTED overlay is reused for storage unavailable."""
        from amphigory_daemon.icons import StatusOverlay
        # DISCONNECTED serves double duty: webapp disconnected OR storage unavailable
        assert hasattr(StatusOverlay, "DISCONNECTED")


class TestGetIconName:
    def test_idle_empty_returns_correct_name(self):
        """get_icon_name returns correct name for idle empty."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.IDLE_EMPTY)
        assert name == "idle_empty"

    def test_idle_disc_returns_correct_name(self):
        """get_icon_name returns correct name for idle with disc."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.IDLE_DISC)
        assert name == "idle_disc"

    def test_working_returns_correct_name(self):
        """get_icon_name returns correct name for working."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.WORKING)
        assert name == "working"

    def test_with_paused_overlay(self):
        """get_icon_name includes paused overlay."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.IDLE_DISC, {StatusOverlay.PAUSED})
        assert name == "idle_disc_paused"

    def test_with_multiple_overlays(self):
        """get_icon_name handles multiple overlays."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(
            ActivityState.WORKING,
            {StatusOverlay.PAUSED, StatusOverlay.DISCONNECTED}
        )
        # Overlays should be sorted for consistent naming
        assert "paused" in name
        assert "disconnected" in name

    def test_none_overlay_ignored(self):
        """NONE overlay doesn't affect name."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.IDLE_EMPTY, {StatusOverlay.NONE})
        assert name == "idle_empty"

    def test_with_needs_config_overlay(self):
        """get_icon_name includes needs_config overlay for cold-start mode."""
        from amphigory_daemon.icons import get_icon_name, ActivityState, StatusOverlay

        name = get_icon_name(ActivityState.IDLE_EMPTY, {StatusOverlay.NEEDS_CONFIG})
        assert name == "idle_empty_needs_config"
