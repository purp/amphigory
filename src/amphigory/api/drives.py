"""API endpoints for optical drives."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from amphigory.api.settings import _daemons

router = APIRouter(prefix="/api/drives", tags=["drives"])


class DriveResponse(BaseModel):
    """Response model for a drive."""
    drive_id: str
    daemon_id: str
    device: Optional[str] = None
    state: str = "unknown"
    disc_inserted: bool = False
    disc_volume: Optional[str] = None
    disc_type: Optional[str] = None
    fingerprint: Optional[str] = None
    scan_status: Optional[str] = None


class DrivesListResponse(BaseModel):
    """Response model for list of drives."""
    drives: list[DriveResponse]


@router.get("", response_model=DrivesListResponse)
async def list_drives():
    """List all connected optical drives.

    Returns drive information from all connected daemons.
    """
    drives = []
    for daemon_id, daemon in _daemons.items():
        # Create drive_id from daemon_id and device
        device_name = daemon.disc_device.replace("/dev/", "") if daemon.disc_device else "unknown"
        drive_id = f"{daemon_id}:{device_name}"

        drives.append(DriveResponse(
            drive_id=drive_id,
            daemon_id=daemon_id,
            device=daemon.disc_device,
            state="disc_inserted" if daemon.disc_inserted else "empty",
            disc_inserted=daemon.disc_inserted,
            disc_volume=daemon.disc_volume,
        ))

    return DrivesListResponse(drives=drives)


@router.get("/{drive_id}")
async def get_drive(drive_id: str):
    """Get status of a specific drive.

    Args:
        drive_id: Drive identifier in format daemon_id:device
    """
    # Parse drive_id to get daemon_id
    parts = drive_id.rsplit(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")

    daemon_id = parts[0]

    if daemon_id not in _daemons:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")

    daemon = _daemons[daemon_id]
    device_name = daemon.disc_device.replace("/dev/", "") if daemon.disc_device else "unknown"

    return DriveResponse(
        drive_id=f"{daemon_id}:{device_name}",
        daemon_id=daemon_id,
        device=daemon.disc_device,
        state="disc_inserted" if daemon.disc_inserted else "empty",
        disc_inserted=daemon.disc_inserted,
        disc_volume=daemon.disc_volume,
    )
