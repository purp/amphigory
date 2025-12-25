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


class TestOpticalDriveStateMutations:
    """Tests for OpticalDrive state mutation methods."""

    def test_insert_disc_updates_state(self):
        """insert_disc() updates state to DISC_INSERTED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")

        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        assert drive.state == DriveState.DISC_INSERTED
        assert drive.disc_volume == "MY_MOVIE"
        assert drive.disc_type == "bluray"
        assert drive.disc_inserted_at is not None

    def test_insert_disc_clears_previous_scan(self):
        """insert_disc() clears any previous scan state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.scan_result = {"tracks": []}
        drive.scan_status = ScanStatus.COMPLETE

        drive.insert_disc(volume="NEW_DISC", disc_type="dvd")

        assert drive.scan_result is None
        assert drive.scan_status is None
        assert drive.fingerprint is None

    def test_eject_disc_resets_to_empty(self):
        """eject_disc() resets drive to EMPTY state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.scan_result = {"tracks": []}

        drive.eject_disc()

        assert drive.state == DriveState.EMPTY
        assert drive.disc_volume is None
        assert drive.disc_type is None
        assert drive.fingerprint is None
        assert drive.scan_result is None
        assert drive.scan_status is None

    def test_start_scan_updates_state(self):
        """start_scan() transitions to SCANNING state."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        drive.start_scan(task_id="scan-123")

        assert drive.state == DriveState.SCANNING
        assert drive.scan_status == ScanStatus.IN_PROGRESS
        assert drive.scan_task_id == "scan-123"

    def test_complete_scan_stores_result(self):
        """complete_scan() stores result and transitions to SCANNED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.start_scan(task_id="scan-123")

        result = {"disc_name": "MY_MOVIE", "tracks": [{"number": 1}]}
        drive.complete_scan(result=result)

        assert drive.state == DriveState.SCANNED
        assert drive.scan_status == ScanStatus.COMPLETE
        assert drive.scan_result == result

    def test_fail_scan_stores_error(self):
        """fail_scan() stores error and returns to DISC_INSERTED."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")
        drive.start_scan(task_id="scan-123")

        drive.fail_scan(error="Disc unreadable")

        assert drive.state == DriveState.DISC_INSERTED
        assert drive.scan_status == ScanStatus.FAILED
        assert drive.scan_error == "Disc unreadable"

    def test_to_dict_serializes_state(self):
        """to_dict() returns JSON-serializable representation."""
        drive = OpticalDrive(daemon_id="test", device="/dev/rdisk0")
        drive.insert_disc(volume="MY_MOVIE", disc_type="bluray")

        data = drive.to_dict()

        assert data["drive_id"] == "test:rdisk0"
        assert data["state"] == "disc_inserted"
        assert data["disc_volume"] == "MY_MOVIE"
        assert data["disc_type"] == "bluray"
