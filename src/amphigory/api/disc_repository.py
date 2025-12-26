"""Repository for fingerprint-based disc lookup and storage."""

import json
from datetime import datetime
from typing import Optional, Union
import aiosqlite
from pathlib import Path
import os


def parse_duration(duration_str: Optional[Union[str, int]]) -> int:
    """
    Parse a duration string to total seconds.

    Supports formats:
    - "H:MM:SS" (hours:minutes:seconds)
    - "M:SS" (minutes:seconds)
    - "S" (seconds only)
    - Integer (already in seconds)

    Args:
        duration_str: Duration string like "1:39:56", integer seconds, or None

    Returns:
        Total seconds as integer. Returns 0 for empty/None input.
    """
    if not duration_str:
        return 0

    # If already an integer, return it directly
    if isinstance(duration_str, int):
        return duration_str

    parts = duration_str.split(":")
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s
    else:
        return int(parts[0]) if parts[0] else 0


def get_db_path() -> Path:
    """Get database path from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    return data_dir / "amphigory.db"


async def insert_track(db, disc_id: int, track_data: dict) -> int:
    """
    Insert a track record from scan_data into the tracks table.

    Args:
        db: Database instance
        disc_id: ID of the parent disc
        track_data: Track dict from scan_data["tracks"][]

    Returns:
        ID of the inserted track row
    """
    # Parse duration string to seconds
    duration_seconds = parse_duration(track_data.get("duration"))

    # JSON serialize audio/subtitle streams
    audio_tracks = json.dumps(track_data.get("audio_streams")) if track_data.get("audio_streams") else None
    subtitle_tracks = json.dumps(track_data.get("subtitle_streams")) if track_data.get("subtitle_streams") else None

    async with db.connection() as conn:
        cursor = await conn.execute(
            """INSERT INTO tracks (
                disc_id,
                track_number,
                duration_seconds,
                size_bytes,
                chapter_count,
                resolution,
                track_type,
                classification_confidence,
                classification_score,
                segment_map,
                makemkv_name,
                audio_tracks,
                subtitle_tracks,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                disc_id,
                track_data.get("number"),
                duration_seconds if duration_seconds else None,
                track_data.get("size_bytes"),
                track_data.get("chapters"),
                track_data.get("resolution"),
                track_data.get("classification"),
                track_data.get("confidence"),
                track_data.get("score"),
                track_data.get("segment_map"),
                track_data.get("makemkv_name"),
                audio_tracks,
                subtitle_tracks,
                "discovered",  # Default status for newly scanned tracks
            ),
        )
        await conn.commit()
        return cursor.lastrowid


async def get_disc_by_fingerprint(fingerprint: str) -> Optional[dict]:
    """
    Look up a disc by its fingerprint.

    Args:
        fingerprint: SHA256 hex string fingerprint of the disc

    Returns:
        Dict with disc info (id, title, year, disc_type, etc.) or None if not found
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def save_disc_scan(
    fingerprint: str,
    scan_data: dict,
    title: Optional[str] = None,
) -> int:
    """
    Save or update a disc's scan data and populate tracks table.

    If disc exists (by fingerprint), updates scan_data and scanned_at.
    If disc doesn't exist, creates new disc with title.
    Always clears existing tracks and inserts new ones from scan_data.

    Args:
        fingerprint: SHA256 hex string fingerprint of the disc
        scan_data: Dict containing scan information (will be JSON serialized)
        title: Optional title for the disc. If not provided, uses scan_data["disc_name"]

    Returns:
        Disc ID (existing or newly created)
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        # Check if disc already exists
        cursor = await db.execute(
            "SELECT id FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        existing = await cursor.fetchone()

        scan_data_json = json.dumps(scan_data)
        scanned_at = datetime.now().isoformat()

        if existing:
            # Update existing disc
            disc_id = existing["id"]
            await db.execute(
                """UPDATE discs
                   SET scan_data = ?, scanned_at = ?
                   WHERE id = ?""",
                (scan_data_json, scanned_at, disc_id)
            )
        else:
            # Create new disc
            # Use provided title or fallback to disc_name from scan_data
            disc_title = title or scan_data.get("disc_name", "Unknown Disc")

            cursor = await db.execute(
                """INSERT INTO discs (title, fingerprint, scan_data, scanned_at)
                   VALUES (?, ?, ?, ?)""",
                (disc_title, fingerprint, scan_data_json, scanned_at)
            )
            disc_id = cursor.lastrowid

        # Clear existing tracks for this disc (rescan case)
        await db.execute("DELETE FROM tracks WHERE disc_id = ?", (disc_id,))

        # Insert tracks from scan_data
        for track_data in scan_data.get("tracks", []):
            duration_seconds = parse_duration(track_data.get("duration"))
            audio_tracks = json.dumps(track_data.get("audio_streams")) if track_data.get("audio_streams") else None
            subtitle_tracks = json.dumps(track_data.get("subtitle_streams")) if track_data.get("subtitle_streams") else None

            await db.execute(
                """INSERT INTO tracks (
                    disc_id, track_number, duration_seconds, size_bytes,
                    chapter_count, resolution, track_type, classification_confidence,
                    classification_score, segment_map, makemkv_name,
                    audio_tracks, subtitle_tracks, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    track_data.get("number"),
                    duration_seconds if duration_seconds else None,
                    track_data.get("size_bytes"),
                    track_data.get("chapters"),
                    track_data.get("resolution"),
                    track_data.get("classification"),
                    track_data.get("confidence"),
                    track_data.get("score"),
                    track_data.get("segment_map"),
                    track_data.get("makemkv_name"),
                    audio_tracks,
                    subtitle_tracks,
                    "discovered",
                ),
            )

        await db.commit()
        return disc_id


async def get_track_count_by_fingerprint(fingerprint: str) -> int:
    """
    Get the count of tracks for a disc by its fingerprint.

    Args:
        fingerprint: SHA256 hex string fingerprint of the disc

    Returns:
        Number of tracks for the disc, or 0 if disc not found
    """
    async with aiosqlite.connect(get_db_path()) as db:
        # First get the disc_id
        cursor = await db.execute(
            "SELECT id FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        row = await cursor.fetchone()
        if not row:
            return 0

        disc_id = row[0]

        # Count tracks for this disc
        cursor = await db.execute(
            "SELECT COUNT(*) FROM tracks WHERE disc_id = ?",
            (disc_id,)
        )
        count_row = await cursor.fetchone()
        return count_row[0] if count_row else 0


async def get_disc_scan_data(fingerprint: str) -> Optional[dict]:
    """
    Get cached scan data for a disc.

    Args:
        fingerprint: SHA256 hex string fingerprint of the disc

    Returns:
        The scan_data as a parsed dict, or None if disc not found or no scan data
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT scan_data FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        row = await cursor.fetchone()

        if row and row["scan_data"]:
            return json.loads(row["scan_data"])
        return None


async def get_tracks_for_disc(disc_id: int) -> list[dict]:
    """
    Get all tracks for a disc by disc_id.

    Args:
        disc_id: ID of the disc

    Returns:
        List of track dicts ordered by track_number ASC.
        Returns empty list if disc not found or has no tracks.
    """
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
            (disc_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
