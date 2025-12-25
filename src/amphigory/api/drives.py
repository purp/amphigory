"""API endpoints for optical drives."""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from amphigory.api.settings import _daemons
from amphigory.websocket import manager

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

    Returns fresh drive information from all connected daemons via WebSocket.
    """
    drives = []
    for daemon_id in _daemons.keys():
        try:
            # Query daemon for fresh drive state via WebSocket
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )

            # Determine if disc is inserted based on state
            state = drive_data.get("state", "unknown")
            disc_inserted = state in ["disc_inserted", "scanning", "scanned", "ripping"]

            drives.append(DriveResponse(
                drive_id=drive_data.get("drive_id", f"{daemon_id}:unknown"),
                daemon_id=daemon_id,
                device=drive_data.get("device"),
                state=state,
                disc_inserted=disc_inserted,
                disc_volume=drive_data.get("disc_volume"),
                disc_type=drive_data.get("disc_type"),
                fingerprint=drive_data.get("fingerprint"),
                scan_status=drive_data.get("scan_status"),
            ))
        except (KeyError, asyncio.TimeoutError):
            # Daemon not connected or timed out - skip this daemon
            pass

    return DrivesListResponse(drives=drives)


@router.get("/{drive_id}")
async def get_drive(drive_id: str):
    """Get status of a specific drive.

    Args:
        drive_id: Drive identifier in format daemon_id:device

    Returns fresh drive information from the daemon via WebSocket.
    """
    # Parse drive_id to get daemon_id
    parts = drive_id.rsplit(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")

    daemon_id = parts[0]

    if daemon_id not in _daemons:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")

    try:
        # Query daemon for fresh drive state via WebSocket
        drive_data = await manager.request_from_daemon(
            daemon_id, "get_drive_status", {}, timeout=5.0
        )

        # Determine if disc is inserted based on state
        state = drive_data.get("state", "unknown")
        disc_inserted = state in ["disc_inserted", "scanning", "scanned", "ripping"]

        return DriveResponse(
            drive_id=drive_data.get("drive_id", f"{daemon_id}:unknown"),
            daemon_id=daemon_id,
            device=drive_data.get("device"),
            state=state,
            disc_inserted=disc_inserted,
            disc_volume=drive_data.get("disc_volume"),
            disc_type=drive_data.get("disc_type"),
            fingerprint=drive_data.get("fingerprint"),
            scan_status=drive_data.get("scan_status"),
        )
    except (KeyError, asyncio.TimeoutError):
        # Daemon not connected or timed out
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found")
