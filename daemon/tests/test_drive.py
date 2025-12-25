"""Tests for OpticalDrive model."""

import pytest
from amphigory_daemon.drive import OpticalDrive, DriveState, ScanStatus


class TestOpticalDriveModel:
    """Tests for OpticalDrive dataclass."""

    def test_create_drive_with_daemon_id_and_device(self):
        """Can create drive with daemon_id and device."""
        drive = OpticalDrive(
            daemon_id="purp@beehive:dev",
            device="/dev/rdisk6",
        )
        assert drive.daemon_id == "purp@beehive:dev"
        assert drive.device == "/dev/rdisk6"
        assert drive.state == DriveState.EMPTY

    def test_drive_id_format(self):
        """Drive ID combines daemon_id and device with colon."""
        drive = OpticalDrive(
            daemon_id="purp@beehive:dev",
            device="/dev/rdisk6",
        )
        # Format: daemon_id:device (device without /dev/ prefix)
        assert drive.drive_id == "purp@beehive:dev:rdisk6"

    def test_drive_starts_empty(self):
        """New drive starts in EMPTY state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        assert drive.state == DriveState.EMPTY
        assert drive.disc_volume is None
        assert drive.fingerprint is None
        assert drive.scan_status is None
        assert drive.scan_result is None

    def test_drive_state_enum_values(self):
        """DriveState enum has expected values."""
        assert DriveState.EMPTY.value == "empty"
        assert DriveState.DISC_INSERTED.value == "disc_inserted"
        assert DriveState.SCANNING.value == "scanning"
        assert DriveState.SCANNED.value == "scanned"
        assert DriveState.RIPPING.value == "ripping"

    def test_scan_status_enum_values(self):
        """ScanStatus enum has expected values."""
        assert ScanStatus.PENDING.value == "pending"
        assert ScanStatus.IN_PROGRESS.value == "in_progress"
        assert ScanStatus.COMPLETE.value == "complete"
        assert ScanStatus.FAILED.value == "failed"
