"""Tests for disc detection - basic structure tests, full testing requires macOS."""

import pytest


class TestDiscDetector:
    def test_can_create_detector(self):
        """DiscDetector can be instantiated with callbacks."""
        from amphigory_daemon.disc import DiscDetector

        def on_insert(device, volume):
            pass

        def on_eject(device):
            pass

        detector = DiscDetector.alloc_with_callbacks(
            on_insert=on_insert, on_eject=on_eject
        )

        assert detector._on_insert == on_insert
        assert detector._on_eject == on_eject

    def test_has_required_methods(self):
        """DiscDetector has required interface methods."""
        from amphigory_daemon.disc import DiscDetector

        detector = DiscDetector.alloc_with_callbacks(
            on_insert=lambda d, v: None,
            on_eject=lambda d: None,
        )

        assert hasattr(detector, "start")
        assert hasattr(detector, "stop")
        assert hasattr(detector, "get_current_disc")
        assert callable(detector.start)
        assert callable(detector.stop)
        assert callable(detector.get_current_disc)
