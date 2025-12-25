"""Library API for browsing processed discs."""

from typing import Optional, List
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/library", tags=["library"])


class DiscSummary(BaseModel):
    """Summary of a disc for list view."""
    id: int
    title: str
    year: Optional[int]
    disc_type: Optional[str]
    media_type: str
    track_count: int
    processed_at: Optional[str]
    status: str  # 'complete', 'needs_attention', 'not_processed'
    reprocessing_type: Optional[str]


class LibraryResponse(BaseModel):
    """Response for library listing."""
    discs: List[DiscSummary]
    total: int


class DiscDetail(BaseModel):
    """Full disc details with tracks."""
    id: int
    title: str
    year: Optional[int]
    disc_type: Optional[str]
    media_type: str
    imdb_id: Optional[str]
    tmdb_id: Optional[str]
    fingerprint: Optional[str]
    processed_at: Optional[str]
    needs_reprocessing: bool
    reprocessing_type: Optional[str]
    reprocessing_notes: Optional[str]
    tracks: List[dict]


class FlagRequest(BaseModel):
    """Request to flag disc for reprocessing."""
    needs_reprocessing: bool
    reprocessing_type: Optional[str] = None
    reprocessing_notes: Optional[str] = None


@router.get("", response_model=LibraryResponse)
async def list_discs(
    request: Request,
    status: Optional[str] = Query(None, description="Filter: complete, needs_attention, not_processed"),
    disc_type: Optional[str] = Query(None, description="Filter: dvd, bluray, uhd"),
    media_type: Optional[str] = Query(None, description="Filter: movie, tv, music"),
    search: Optional[str] = Query(None, description="Search title (case-insensitive)"),
) -> LibraryResponse:
    """List all discs with optional filtering."""
    db = request.app.state.db

    # Build query with filters
    conditions = []
    params = []

    if status == "complete":
        conditions.append("processed_at IS NOT NULL AND (needs_reprocessing IS NULL OR needs_reprocessing = 0)")
    elif status == "needs_attention":
        conditions.append("needs_reprocessing = 1")
    elif status == "not_processed":
        conditions.append("processed_at IS NULL")

    if disc_type:
        conditions.append("disc_type = ?")
        params.append(disc_type)

    if media_type:
        conditions.append("media_type = ?")
        params.append(media_type)

    if search:
        conditions.append("title LIKE ?")
        params.append(f"%{search}%")

    # SECURITY: where_clause contains only hardcoded SQL fragments, never user input.
    # All user-supplied values are parameterized via the params list.
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    async with db.connection() as conn:
        # Get discs
        cursor = await conn.execute(
            f"""SELECT d.*, COUNT(t.id) as track_count
                FROM discs d
                LEFT JOIN tracks t ON t.disc_id = d.id
                WHERE {where_clause}
                GROUP BY d.id
                ORDER BY d.processed_at DESC NULLS LAST, d.title ASC""",
            params,
        )
        rows = await cursor.fetchall()

    discs = []
    for row in rows:
        # Determine status
        if row["processed_at"] is None:
            disc_status = "not_processed"
        elif row["needs_reprocessing"]:
            disc_status = "needs_attention"
        else:
            disc_status = "complete"

        discs.append(DiscSummary(
            id=row["id"],
            title=row["title"],
            year=row["year"],
            disc_type=row["disc_type"],
            media_type=row["media_type"] or "movie",
            track_count=row["track_count"],
            processed_at=row["processed_at"],
            status=disc_status,
            reprocessing_type=row["reprocessing_type"],
        ))

    return LibraryResponse(discs=discs, total=len(discs))


@router.get("/{disc_id}", response_model=DiscDetail)
async def get_disc_detail(request: Request, disc_id: int) -> DiscDetail:
    """Get full details for a disc including tracks."""
    db = request.app.state.db

    async with db.connection() as conn:
        # Get disc
        cursor = await conn.execute("SELECT * FROM discs WHERE id = ?", (disc_id,))
        disc = await cursor.fetchone()

        if not disc:
            raise HTTPException(status_code=404, detail="Disc not found")

        # Get tracks
        cursor = await conn.execute(
            "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
            (disc_id,),
        )
        tracks = [dict(row) for row in await cursor.fetchall()]

    return DiscDetail(
        id=disc["id"],
        title=disc["title"],
        year=disc["year"],
        disc_type=disc["disc_type"],
        media_type=disc["media_type"] or "movie",
        imdb_id=disc["imdb_id"],
        tmdb_id=disc["tmdb_id"],
        fingerprint=disc["fingerprint"],
        processed_at=disc["processed_at"],
        needs_reprocessing=bool(disc["needs_reprocessing"]),
        reprocessing_type=disc["reprocessing_type"],
        reprocessing_notes=disc["reprocessing_notes"],
        tracks=tracks,
    )


@router.patch("/{disc_id}/flag")
async def flag_disc(request: Request, disc_id: int, flag: FlagRequest) -> dict:
    """Set or clear reprocessing flag on a disc."""
    db = request.app.state.db

    async with db.connection() as conn:
        # Verify disc exists
        cursor = await conn.execute("SELECT id FROM discs WHERE id = ?", (disc_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update flags
        await conn.execute(
            """UPDATE discs
               SET needs_reprocessing = ?,
                   reprocessing_type = ?,
                   reprocessing_notes = ?
               WHERE id = ?""",
            (
                flag.needs_reprocessing,
                flag.reprocessing_type if flag.needs_reprocessing else None,
                flag.reprocessing_notes if flag.needs_reprocessing else None,
                disc_id,
            ),
        )
        await conn.commit()

    return {"status": "ok"}


@router.get("/html", response_class=HTMLResponse)
async def list_discs_html(
    request: Request,
    status: Optional[str] = None,
    disc_type: Optional[str] = None,
    media_type: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Return HTML table of discs for HTMX."""
    response = await list_discs(request, status, disc_type, media_type, search)

    if not response.discs:
        return "<p>No discs found.</p>"

    rows = []
    for disc in response.discs:
        status_class = f"status-{disc.status}"
        status_icon = {"complete": "✓", "needs_attention": "⚠", "not_processed": "○"}.get(disc.status, "")

        rows.append(f"""
            <tr id="disc-{disc.id}" onclick="toggleDetails({disc.id})">
                <td>{disc.title}</td>
                <td>{disc.year or '-'}</td>
                <td>{disc.disc_type or '-'}</td>
                <td>{disc.media_type}</td>
                <td>{disc.track_count}</td>
                <td>{disc.processed_at[:10] if disc.processed_at else '-'}</td>
                <td class="{status_class}">{status_icon} {disc.status.replace('_', ' ').title()}</td>
            </tr>
        """)

    return f"""
        <table class="disc-table">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Year</th>
                    <th>Disc Type</th>
                    <th>Media Type</th>
                    <th>Tracks</th>
                    <th>Processed</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        <p>{response.total} disc(s)</p>
    """
