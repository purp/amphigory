"""Application configuration."""

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""
    database_path: Path
    preset_dir: Path
    ripped_dir: Path
    transcoded_dir: Path
    plex_dir: Path
    wiki_dir: Path


def get_config() -> Config:
    """Load configuration from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    config_dir = Path(os.environ.get("AMPHIGORY_CONFIG", "/config"))

    return Config(
        database_path=data_dir / "amphigory.db",
        preset_dir=config_dir / "presets",
        ripped_dir=Path(os.environ.get("AMPHIGORY_RIPPED_DIR", "/media/ripped")),
        transcoded_dir=Path(os.environ.get("AMPHIGORY_TRANSCODED_DIR", "/media/transcoded")),
        plex_dir=Path(os.environ.get("AMPHIGORY_PLEX_DIR", "/media/plex/data")),
        wiki_dir=Path(os.environ.get("AMPHIGORY_WIKI_DIR", "/wiki")),
    )
