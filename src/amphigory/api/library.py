"""Library API for browsing processed discs."""

from typing import Optional, List
from fastapi import APIRouter, Request, Query
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
