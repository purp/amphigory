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
    notes TEXT
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        columns = {row[1] for row in await cursor.fetchall()}

        # Migration: Add fingerprint, scan_data, scanned_at columns (Task 6)
        if "fingerprint" not in columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN fingerprint TEXT UNIQUE")
        if "scan_data" not in columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN scan_data TEXT")
        if "scanned_at" not in columns:
            await conn.execute("ALTER TABLE discs ADD COLUMN scanned_at TIMESTAMP")

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    async def close(self) -> None:
        """Close any open connections."""
        pass  # Connections are managed per-request
