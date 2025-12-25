"""Database connection and initialization."""

import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
    tvdb_id TEXT
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
    preset_id INTEGER REFERENCES presets(id),
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
    air_date DATE
);

-- Handbrake presets with versioning
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    disc_type TEXT,
    preset_json TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

-- Job queue for ripping and transcoding
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    track_id INTEGER REFERENCES tracks(id),
    job_type TEXT,
    status TEXT DEFAULT 'queued',
    progress INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_track_id ON jobs(track_id);
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

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    async def close(self) -> None:
        """Close any open connections."""
        pass  # Connections are managed per-request
