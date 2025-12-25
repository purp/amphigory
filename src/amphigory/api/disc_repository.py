"""Repository for fingerprint-based disc lookup and storage."""

import json
from datetime import datetime
from typing import Optional
import aiosqlite
from pathlib import Path
import os


def get_db_path() -> Path:
    """Get database path from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    return data_dir / "amphigory.db"


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
    Save or update a disc's scan data.

    If disc exists (by fingerprint), updates scan_data and scanned_at.
    If disc doesn't exist, creates new disc with title.

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
            await db.commit()
            return disc_id
        else:
            # Create new disc
            # Use provided title or fallback to disc_name from scan_data
            disc_title = title or scan_data.get("disc_name", "Unknown Disc")

            cursor = await db.execute(
                """INSERT INTO discs (title, fingerprint, scan_data, scanned_at)
                   VALUES (?, ?, ?, ?)""",
                (disc_title, fingerprint, scan_data_json, scanned_at)
            )
            await db.commit()
            return cursor.lastrowid


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
