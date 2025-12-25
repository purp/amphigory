"""OpticalDrive model for tracking drive and disc state."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class DriveState(Enum):
    """State of the optical drive."""
    EMPTY = "empty"
    DISC_INSERTED = "disc_inserted"
    SCANNING = "scanning"
    SCANNED = "scanned"
    RIPPING = "ripping"


class ScanStatus(Enum):
    """Status of a scan operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class OpticalDrive:
    """
    Model representing an optical drive and its current state.

    The daemon maintains one OpticalDrive instance per physical drive.
    State changes are pushed to the webapp via WebSocket.
    """
    daemon_id: str
    device: str  # e.g., "/dev/rdisk6"

    # Drive state
    state: DriveState = DriveState.EMPTY

    # Disc info (when disc inserted)
    disc_volume: Optional[str] = None  # Volume name
    disc_type: Optional[str] = None  # "cd", "dvd", "bluray"
    fingerprint: Optional[str] = None  # Quick disc identifier

    # Scan state
    scan_status: Optional[ScanStatus] = None
    scan_task_id: Optional[str] = None
    scan_result: Optional[dict] = None  # Cached scan result
    scan_error: Optional[str] = None

    # Rip state (for current rip operation)
    rip_task_id: Optional[str] = None
    rip_track_number: Optional[int] = None
    rip_progress: Optional[int] = None  # 0-100

    # Timestamps
    disc_inserted_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def drive_id(self) -> str:
        """
        Unique identifier for this drive.

        Format: {daemon_id}:{device_name}
        Example: purp@beehive:dev:rdisk6
        """
        # Strip /dev/ prefix from device
        device_name = self.device.replace("/dev/", "")
        return f"{self.daemon_id}:{device_name}"

    def insert_disc(self, volume: str, disc_type: str) -> None:
        """
        Handle disc insertion.

        Args:
            volume: Volume name of the disc
            disc_type: Type of disc ("cd", "dvd", "bluray")
        """
        # Clear any previous state
        self.scan_result = None
        self.scan_status = None
        self.scan_task_id = None
        self.scan_error = None
        self.fingerprint = None
        self.rip_task_id = None
        self.rip_track_number = None
        self.rip_progress = None

        # Set new disc info
        self.state = DriveState.DISC_INSERTED
        self.disc_volume = volume
        self.disc_type = disc_type
        self.disc_inserted_at = datetime.now()
        self.last_updated = datetime.now()

    def eject_disc(self) -> None:
        """Handle disc ejection - reset to empty state."""
        self.state = DriveState.EMPTY
        self.disc_volume = None
        self.disc_type = None
        self.fingerprint = None
        self.disc_inserted_at = None
        self.scan_result = None
        self.scan_status = None
        self.scan_task_id = None
        self.scan_error = None
        self.rip_task_id = None
        self.rip_track_number = None
        self.rip_progress = None
        self.last_updated = datetime.now()

    def start_scan(self, task_id: str) -> None:
        """
        Start a scan operation.

        Args:
            task_id: ID of the scan task
        """
        self.state = DriveState.SCANNING
        self.scan_status = ScanStatus.IN_PROGRESS
        self.scan_task_id = task_id
        self.scan_error = None
        self.last_updated = datetime.now()

    def complete_scan(self, result: dict) -> None:
        """
        Complete a scan operation successfully.

        Args:
            result: Scan result with disc_name, tracks, etc.
        """
        self.state = DriveState.SCANNED
        self.scan_status = ScanStatus.COMPLETE
        self.scan_result = result
        self.scan_error = None
        self.last_updated = datetime.now()

    def fail_scan(self, error: str) -> None:
        """
        Mark scan as failed.

        Args:
            error: Error message
        """
        self.state = DriveState.DISC_INSERTED
        self.scan_status = ScanStatus.FAILED
        self.scan_error = error
        self.last_updated = datetime.now()

    def set_fingerprint(self, fingerprint: str) -> None:
        """
        Set the disc fingerprint.

        Args:
            fingerprint: Hex string fingerprint from generate_fingerprint()
        """
        self.fingerprint = fingerprint
        self.last_updated = datetime.now()

    def to_dict(self) -> dict:
        """
        Convert to JSON-serializable dictionary.

        Returns:
            Dict representation of drive state
        """
        return {
            "drive_id": self.drive_id,
            "daemon_id": self.daemon_id,
            "device": self.device,
            "state": self.state.value,
            "disc_volume": self.disc_volume,
            "disc_type": self.disc_type,
            "fingerprint": self.fingerprint,
            "scan_status": self.scan_status.value if self.scan_status else None,
            "scan_task_id": self.scan_task_id,
            "scan_result": self.scan_result,
            "scan_error": self.scan_error,
            "rip_task_id": self.rip_task_id,
            "rip_track_number": self.rip_track_number,
            "rip_progress": self.rip_progress,
            "disc_inserted_at": self.disc_inserted_at.isoformat() if self.disc_inserted_at else None,
            "last_updated": self.last_updated.isoformat(),
        }
