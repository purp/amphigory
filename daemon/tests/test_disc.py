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

    def test_tracks_volume_path_on_insert(self):
        """DiscDetector stores volume path when insert callback fires."""
        from amphigory_daemon.disc import DiscDetector
        inserted = []
        detector = DiscDetector.alloc_with_callbacks(
            on_insert=lambda d, v: inserted.append((d, v)),
            on_eject=lambda d: None,
        )
        # Check that _current_volume_path is initialized to None
        assert detector._current_volume_path is None
        # Then verify we can set it
        detector._current_volume_path = "/Volumes/TEST_DISC"
        assert detector._current_volume_path == "/Volumes/TEST_DISC"

    def test_handleMount_sets_current_volume_path(self):
        """handleMount_ stores the volume path for later eject detection."""
        from amphigory_daemon.disc import DiscDetector
        from unittest.mock import MagicMock, patch
        inserted = []
        detector = DiscDetector.alloc_with_callbacks(
            on_insert=lambda d, v: inserted.append((d, v)),
            on_eject=lambda d: None,
        )
        mock_notification = MagicMock()
        mock_notification.userInfo.return_value = {
            "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/TEST_DISC")
        }
        with patch.object(detector, '_get_device_for_volume', return_value="/dev/rdisk5"):
            with patch.object(detector, '_is_optical_device', return_value=True):
                detector.handleMount_(mock_notification)
        assert detector._current_volume_path == "/Volumes/TEST_DISC"
        assert len(inserted) == 1

    def test_handleUnmount_fires_eject_for_tracked_volume(self):
        """handleUnmount_ fires eject callback when path matches tracked volume."""
        from amphigory_daemon.disc import DiscDetector
        from unittest.mock import MagicMock
        ejected = []
        detector = DiscDetector.alloc_with_callbacks(
            on_insert=lambda d, v: None,
            on_eject=lambda p: ejected.append(p),
        )
        detector._current_volume_path = "/Volumes/TEST_DISC"
        mock_notification = MagicMock()
        mock_notification.userInfo.return_value = {
            "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/TEST_DISC")
        }
        detector.handleUnmount_(mock_notification)
        assert len(ejected) == 1
        assert ejected[0] == "/Volumes/TEST_DISC"
        assert detector._current_volume_path is None

    def test_handleUnmount_ignores_non_tracked_volumes(self):
        """handleUnmount_ ignores unmount events for volumes we're not tracking."""
        from amphigory_daemon.disc import DiscDetector
        from unittest.mock import MagicMock
        ejected = []
        detector = DiscDetector.alloc_with_callbacks(
            on_insert=lambda d, v: None,
            on_eject=lambda p: ejected.append(p),
        )
        detector._current_volume_path = "/Volumes/MY_DISC"
        mock_notification = MagicMock()
        mock_notification.userInfo.return_value = {
            "NSWorkspaceVolumeURLKey": MagicMock(path=lambda: "/Volumes/OTHER_DRIVE")
        }
        detector.handleUnmount_(mock_notification)
        assert len(ejected) == 0
        assert detector._current_volume_path == "/Volumes/MY_DISC"
