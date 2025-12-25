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
