"""API endpoints for disc operations."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amphigory.makemkv import scan_disc, check_for_disc, classify_tracks

router = APIRouter(prefix="/api/disc", tags=["disc"])


class DiscStatusResponse(BaseModel):
    """Disc status response."""
    has_disc: bool
    device_path: str | None = None
    disc_type: str | None = None
    volume_name: str | None = None
    track_count: int = 0


@router.get("/status")
async def get_disc_status(request: Request) -> DiscStatusResponse:
    """Check current disc status."""
    has_disc, device_path = await check_for_disc()

    if not has_disc:
        return DiscStatusResponse(has_disc=False)

    return DiscStatusResponse(
        has_disc=True,
        device_path=device_path,
    )


@router.post("/scan")
async def scan_current_disc(request: Request):
    """Scan the disc and return track information."""
    disc_info = await scan_disc(drive_index=0)

    if not disc_info:
        raise HTTPException(status_code=404, detail="No disc found or scan failed")

    # Classify tracks
    classified_tracks = classify_tracks(disc_info.tracks)

    return {
        "disc_type": disc_info.disc_type,
        "volume_name": disc_info.volume_name,
        "device_path": disc_info.device_path,
        "tracks": [
            {
                "title_id": t.title_id,
                "duration": t.duration_str,
                "size": t.size_human,
                "resolution": t.resolution,
                "classification": t.classification.value,
                "audio_tracks": len(t.audio_streams),
                "subtitle_tracks": len(t.subtitle_streams),
            }
            for t in classified_tracks
        ],
    }


@router.get("/status-html", response_class=HTMLResponse)
async def get_disc_status_html(request: Request):
    """Return disc status as HTML fragment for HTMX."""
    has_disc, device_path = await check_for_disc()

    if not has_disc:
        return '<p class="status-message">No disc detected</p>'

    return f'''
    <div class="disc-detected">
        <p class="status-message status-success">Disc detected at {device_path}</p>
        <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
            Scan Disc
        </button>
    </div>
    '''
