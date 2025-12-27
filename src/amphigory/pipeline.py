"""Pipeline orchestration for the complete rip-transcode workflow."""

import asyncio
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Any

from amphigory.makemkv import DiscInfo, Track, scan_disc, classify_tracks
from amphigory.services.ripper import RipperService, RipProgress
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.presets import PresetManager
from amphigory.database import Database


@dataclass
class PipelineConfig:
    """Pipeline configuration."""
    ripped_dir: Path
    inbox_dir: Path
    plex_dir: Path
    preset_manager: PresetManager


@dataclass
class ProcessingJob:
    """A track being processed."""
    track: Track
    track_type: str
    final_name: str
    ripped_path: Path | None = None
    transcoded_path: Path | None = None


class Pipeline:
    """Orchestrates the complete rip-transcode-organize workflow."""

    def __init__(
        self,
        ripped_dir: Path,
        inbox_dir: Path,
        plex_dir: Path,
        preset_manager: PresetManager | None = None,
        db: Database | None = None,
    ):
        self.ripped_dir = ripped_dir
        self.inbox_dir = inbox_dir
        self.plex_dir = plex_dir
        self.preset_manager = preset_manager
        self.db = db

        self.ripper = RipperService(ripped_dir)
        self.transcoder = TranscoderService()

    def format_folder_name(
        self,
        title: str,
        year: int,
        imdb_id: str,
        edition: str | None = None,
    ) -> str:
        """Format folder name according to Plex conventions."""
        name = f"{title} ({year}) {{imdb-{imdb_id}}}"
        if edition:
            name += f" {{edition-{edition}}}"
        return name

    def create_folder_structure(
        self,
        title: str,
        year: int,
        imdb_id: str,
        extras_types: list[str] | None = None,
        edition: str | None = None,
    ) -> dict[str, Path]:
        """Create the folder structure for a movie.

        Returns paths for ripped and inbox directories.
        """
        folder_name = self.format_folder_name(title, year, imdb_id, edition)

        ripped_path = self.ripped_dir / folder_name
        inbox_path = self.inbox_dir / folder_name

        ripped_path.mkdir(parents=True, exist_ok=True)
        inbox_path.mkdir(parents=True, exist_ok=True)

        # Create extras subdirectories
        if extras_types:
            for extra_type in extras_types:
                (inbox_path / extra_type).mkdir(exist_ok=True)

        return {
            "ripped": ripped_path,
            "inbox": inbox_path,
            "folder_name": folder_name,
        }

    async def process_disc(
        self,
        disc_info: DiscInfo,
        title: str,
        year: int,
        imdb_id: str,
        selected_tracks: list[dict],  # [{track_id, track_type, final_name}]
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> bool:
        """Process a disc through the complete pipeline.

        Args:
            disc_info: Scanned disc information
            title: Movie title
            year: Release year
            imdb_id: IMDB ID
            selected_tracks: List of tracks to process with metadata
            progress_callback: Callback(stage, percent, message)

        Returns:
            True if successful, False otherwise
        """
        # Determine extras types from selected tracks
        extras_types = list(set(
            t["track_type"] for t in selected_tracks
            if t["track_type"] != "main"
        ))

        # Create folder structure
        paths = self.create_folder_structure(
            title, year, imdb_id, extras_types
        )

        # Process each track
        for i, track_info in enumerate(selected_tracks):
            track_id = track_info["track_id"]
            track = next(t for t in disc_info.tracks if t.title_id == track_id)

            # Rip
            if progress_callback:
                progress_callback("rip", 0, f"Ripping track {track_id}...")

            ripped_path = await self.ripper.rip_title(
                drive_index=0,
                title_index=track_id,
                output_dir=paths["ripped"],
                progress_callback=lambda p: progress_callback(
                    "rip", p.percent, f"Ripping: {p.percent}%"
                ) if progress_callback else None,
            )

            if not ripped_path:
                return False

            # Determine output path based on track type
            track_type = track_info["track_type"]
            final_name = track_info["final_name"]

            if track_type == "main":
                output_path = paths["inbox"] / f"{final_name}.mp4"
            else:
                output_path = paths["inbox"] / track_type / f"{final_name}.mp4"

            # Transcode
            if progress_callback:
                progress_callback("transcode", 0, f"Transcoding {final_name}...")

            # Get appropriate preset
            preset_name = self.preset_manager.get_active_preset(disc_info.disc_type)
            preset_path = self.preset_manager.get_preset_path(disc_info.disc_type)

            success = await self.transcoder.transcode(
                input_path=ripped_path,
                output_path=output_path,
                preset_path=preset_path,
                preset_name=preset_name,
                progress_callback=lambda p: progress_callback(
                    "transcode", p.percent, f"Transcoding: {p.percent}%"
                ) if progress_callback else None,
            )

            if not success:
                return False

        return True

    async def finalize(
        self,
        folder_name: str,
        destination: str = "Movies",
    ) -> Path:
        """Move processed content from inbox to Plex library.

        Returns the final path.
        """
        source = self.inbox_dir / folder_name
        dest = self.plex_dir / destination / folder_name

        # Move the folder
        import shutil
        shutil.move(str(source), str(dest))

        return dest
