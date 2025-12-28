"""Database connection and initialization."""

import json
import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Union


def _parse_duration(duration_str: Optional[Union[str, int]]) -> int:
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

SCHEMA = """
-- Processed discs
CREATE TABLE IF NOT EXISTS discs (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    disc_type TEXT,
    disc_release_year INTEGER,
    edition_notes TEXT,
    scan_data TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scanned_at TIMESTAMP,
    notes TEXT,

    -- Media type and TV support
    media_type TEXT DEFAULT 'movie',
    show_name TEXT,
    tmdb_id TEXT,
    tvdb_id TEXT,

    -- Reprocessing flags
    needs_reprocessing BOOLEAN DEFAULT FALSE,
    reprocessing_type TEXT,
    reprocessing_notes TEXT
);

-- Individual tracks ripped from a disc
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    disc_id INTEGER REFERENCES discs(id),
    track_number INTEGER,
    track_type TEXT,
    original_name TEXT,
    final_name TEXT,
    duration_seconds INTEGER,
    size_bytes INTEGER,
    ripped_path TEXT,
    transcoded_path TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Classification metadata
    track_name TEXT,
    classification_confidence TEXT,
    language TEXT,
    resolution TEXT,
    audio_tracks JSON,
    subtitle_tracks JSON,
    chapter_count INTEGER,
    segment_map TEXT,

    -- TV show support
    season_number INTEGER,
    episode_number INTEGER,
    episode_end_number INTEGER,
    air_date DATE,

    -- Transcode preset used
    preset_name TEXT,

    -- MakeMKV internal track name (e.g., "B1_t04.mkv")
    makemkv_name TEXT,
    -- Numeric classification confidence (0.0-1.0)
    classification_score REAL,
    -- Final path after insertion into Plex library
    inserted_path TEXT
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database with schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.executescript(SCHEMA)
            await self._run_migrations(conn)
            await conn.commit()

    async def _run_migrations(self, conn: aiosqlite.Connection) -> None:
        """Run database migrations for schema updates."""
        # Check if fingerprint column exists in discs table
        cursor = await conn.execute("PRAGMA table_info(discs)")
        discs_columns = {row[1] for row in await cursor.fetchall()}

        # Migration: Add fingerprint, scan_data, scanned_at columns (Task 6)
        # Note: SQLite doesn't allow ADD COLUMN with UNIQUE constraint,
        # so we add the column first, then create a unique index
        if "fingerprint" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN fingerprint TEXT")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_discs_fingerprint ON discs(fingerprint)")
        if "scan_data" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN scan_data TEXT")
        if "scanned_at" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN scanned_at TIMESTAMP")

        # Migration: Add media type and TV support columns to discs table
        if "media_type" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN media_type TEXT DEFAULT 'movie'")
        if "show_name" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN show_name TEXT")
        if "tmdb_id" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN tmdb_id TEXT")
        if "tvdb_id" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN tvdb_id TEXT")

        # Check tracks table columns
        cursor = await conn.execute("PRAGMA table_info(tracks)")
        tracks_columns = {row[1] for row in await cursor.fetchall()}

        # Migration: Add classification and TV show columns to tracks table
        if "track_name" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN track_name TEXT")
        if "classification_confidence" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN classification_confidence TEXT")
        if "language" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN language TEXT")
        if "resolution" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN resolution TEXT")
        if "audio_tracks" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN audio_tracks JSON")
        if "subtitle_tracks" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN subtitle_tracks JSON")
        if "chapter_count" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN chapter_count INTEGER")
        if "segment_map" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN segment_map TEXT")
        if "season_number" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN season_number INTEGER")
        if "episode_number" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN episode_number INTEGER")
        if "episode_end_number" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN episode_end_number INTEGER")
        if "air_date" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN air_date DATE")

        # Migration: Add reprocessing flags to discs table
        if "needs_reprocessing" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN needs_reprocessing BOOLEAN DEFAULT FALSE")
        if "reprocessing_type" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN reprocessing_type TEXT")
        if "reprocessing_notes" not in discs_columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN reprocessing_notes TEXT")

        # Migration: Add preset_name to tracks table
        if "preset_name" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN preset_name TEXT")

        # Migration: Add makemkv_name and classification_score to tracks table
        if "makemkv_name" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN makemkv_name TEXT")
        if "classification_score" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN classification_score REAL")

        # Migration: Add inserted_path column to tracks table
        if "inserted_path" not in tracks_columns:
            await conn.execute("ALTER TABLE tracks ADD COLUMN inserted_path TEXT")

        # Migration: Populate tracks from scan_data for existing discs
        # Only migrate discs that have scan_data but no tracks (idempotent)
        cursor = await conn.execute(
            """SELECT d.id, d.scan_data
               FROM discs d
               LEFT JOIN tracks t ON t.disc_id = d.id
               WHERE d.scan_data IS NOT NULL
               GROUP BY d.id
               HAVING COUNT(t.id) = 0"""
        )
        discs_to_migrate = await cursor.fetchall()

        for disc_row in discs_to_migrate:
            disc_id = disc_row[0]
            scan_data_json = disc_row[1]

            try:
                scan_data = json.loads(scan_data_json)
            except (json.JSONDecodeError, TypeError):
                continue  # Skip invalid JSON

            for track_data in scan_data.get("tracks", []):
                duration_seconds = _parse_duration(track_data.get("duration"))
                audio_tracks = (
                    json.dumps(track_data.get("audio_streams"))
                    if track_data.get("audio_streams")
                    else None
                )
                subtitle_tracks = (
                    json.dumps(track_data.get("subtitle_streams"))
                    if track_data.get("subtitle_streams")
                    else None
                )

                await conn.execute(
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
                        "discovered",  # Default status for migrated tracks
                    ),
                )

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    async def close(self) -> None:
        """Close any open connections."""
        pass  # Connections are managed per-request
