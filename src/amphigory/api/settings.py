"""API endpoints for settings and daemon management."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


router = APIRouter(prefix="/api/settings", tags=["settings"])


class DaemonRegistration(BaseModel):
    """Daemon registration request."""
    daemon_id: str
    makemkvcon_path: Optional[str] = None
    webapp_basedir: str


class RegisteredDaemon(BaseModel):
    """Registered daemon info."""
    daemon_id: str
    makemkvcon_path: Optional[str] = None
    webapp_basedir: str
    git_sha: Optional[str] = None
    connected_at: datetime
    last_seen: datetime
    # Disc status (updated via WebSocket)
    disc_inserted: bool = False
    disc_device: Optional[str] = None
    disc_volume: Optional[str] = None


# In-memory daemon registry (will be replaced by proper storage later)
_daemons: dict[str, RegisteredDaemon] = {}


def get_daemons() -> dict[str, RegisteredDaemon]:
    """Get the daemon registry."""
    return _daemons


def clear_daemons() -> None:
    """Clear daemon registry (for testing)."""
    _daemons.clear()


def _validate_path(path: str) -> bool:
    """Check if a path exists and is accessible."""
    try:
        return Path(path).exists()
    except Exception:
        return False


def _format_relative_time(dt: datetime) -> str:
    """Format datetime as relative time string."""
    delta = datetime.now() - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago"


@router.get("/daemons", response_class=HTMLResponse)
async def list_daemons_html():
    """Return HTML fragment of connected daemons for HTMX."""
    if not _daemons:
        return '<p class="no-daemons">No daemons connected</p>'

    html_parts = []
    for daemon in _daemons.values():
        status_class = "connected"
        status_text = "Connected"
        last_seen = _format_relative_time(daemon.last_seen)

        # Note: Don't validate daemon paths here - they're on the daemon's machine,
        # not in this container. The daemon validates its own paths.
        makemkv_display = daemon.makemkvcon_path or "not configured"

        html_parts.append(f'''
        <div class="daemon-item">
            <div class="daemon-header">
                <span class="daemon-id">{daemon.daemon_id}</span>
                <span class="daemon-status {status_class}">{status_text}</span>
            </div>
            <div class="daemon-config">
                <div class="daemon-config-item">
                    <span class="daemon-config-label">makemkvcon</span>
                    <span class="daemon-config-value">{makemkv_display}</span>
                </div>
                <div class="daemon-config-item">
                    <span class="daemon-config-label">Data Directory</span>
                    <span class="daemon-config-value">{daemon.webapp_basedir}</span>
                </div>
            </div>
            <div class="daemon-details">
                Last seen: {last_seen}
            </div>
        </div>
        ''')

    return "\n".join(html_parts)


@router.post("/validate/path", response_class=HTMLResponse)
async def validate_path(request: Request):
    """Validate a path exists. Returns validation icon HTML."""
    form = await request.form()
    # Get the first form value (could be any path field)
    path = None
    for key, value in form.items():
        path = value
        break

    if path and _validate_path(path):
        return '<span class="validation-icon valid">✓</span>'
    return '<span class="validation-icon invalid">✗</span>'


@router.post("/validate/url", response_class=HTMLResponse)
async def validate_url(request: Request):
    """Validate a URL is well-formed. Returns validation icon HTML."""
    form = await request.form()
    url = None
    for key, value in form.items():
        url = value
        break

    if url:
        try:
            result = urlparse(url)
            if result.scheme in ('http', 'https') and result.netloc:
                return '<span class="validation-icon valid">✓</span>'
        except Exception:
            pass
    return '<span class="validation-icon invalid">✗</span>'


@router.post("/daemons")
async def register_daemon(registration: DaemonRegistration) -> RegisteredDaemon:
    """Register a daemon."""
    now = datetime.now()
    daemon = RegisteredDaemon(
        daemon_id=registration.daemon_id,
        makemkvcon_path=registration.makemkvcon_path,
        webapp_basedir=registration.webapp_basedir,
        connected_at=now,
        last_seen=now,
    )
    _daemons[registration.daemon_id] = daemon
    return daemon


@router.post("/daemons/{daemon_id}/heartbeat")
async def daemon_heartbeat(daemon_id: str):
    """Update daemon last_seen time."""
    if daemon_id not in _daemons:
        raise HTTPException(status_code=404, detail="Daemon not found")

    _daemons[daemon_id].last_seen = datetime.now()
    return {"status": "ok"}


@router.delete("/daemons/{daemon_id}")
async def disconnect_daemon(daemon_id: str):
    """Remove a daemon from registry."""
    if daemon_id in _daemons:
        del _daemons[daemon_id]
    return {"status": "ok"}
