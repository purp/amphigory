"""Service for ripping discs with MakeMKV."""

import asyncio
import subprocess
from pathlib import Path
from typing import AsyncGenerator, Callable
from dataclasses import dataclass


@dataclass
class RipProgress:
    """Progress update from ripping."""
    percent: int
    message: str
    title_index: int | None = None
    bytes_done: int = 0
    bytes_total: int = 0


class RipperService:
    """Manages disc ripping with MakeMKV."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def build_rip_command(
        self,
        drive_index: int,
        title_index: int,
        output_dir: Path,
    ) -> list[str]:
        """Build the makemkvcon command for ripping."""
        return [
            "makemkvcon",
            "mkv",
            f"disc:{drive_index}",
            str(title_index),
            str(output_dir),
        ]

    def parse_progress(self, line: str) -> int | None:
        """Parse progress from MakeMKV output line.

        MakeMKV progress formats:
        - PRGV:current,total,max - Overall progress (current/max * 100)
        - PRGC:current,total,"message" - Current/total items
        - PRGT:current,total,"message" - Title progress
        """
        if line.startswith("PRGV:"):
            parts = line[5:].split(",")
            if len(parts) >= 3:
                current = int(parts[1])
                total = int(parts[2])
                if total > 0:
                    return int(current / total * 100)

        elif line.startswith("PRGC:") or line.startswith("PRGT:"):
            parts = line[5:].split(",")
            if len(parts) >= 2:
                current = int(parts[0])
                total = int(parts[1])
                if total > 0:
                    return int(current / total * 100)

        return None

    async def rip_title(
        self,
        drive_index: int,
        title_index: int,
        output_dir: Path,
        progress_callback: Callable[[RipProgress], None] | None = None,
    ) -> Path | None:
        """Rip a single title from disc.

        Returns the path to the ripped file on success, None on failure.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_rip_command(drive_index, title_index, output_dir)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_progress = 0
        output_file: Path | None = None

        async for line in process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()

            # Parse progress
            progress = self.parse_progress(line_str)
            if progress is not None and progress != last_progress:
                last_progress = progress
                if progress_callback:
                    progress_callback(RipProgress(
                        percent=progress,
                        message=f"Ripping: {progress}%",
                        title_index=title_index,
                    ))

            # Look for output file path
            if line_str.startswith("MSG:") and "saved to" in line_str.lower():
                # Try to extract output path
                pass

        await process.wait()

        if process.returncode == 0:
            # Find the output file
            mkv_files = list(output_dir.glob("*.mkv"))
            if mkv_files:
                # Return the most recently created file
                output_file = max(mkv_files, key=lambda p: p.stat().st_mtime)

        return output_file

    async def rip_titles(
        self,
        drive_index: int,
        titles: list[int],
        output_dir: Path,
        progress_callback: Callable[[int, RipProgress], None] | None = None,
    ) -> dict[int, Path | None]:
        """Rip multiple titles sequentially.

        Returns a mapping of title_index -> output_path.
        """
        results = {}

        for title_index in titles:
            def wrapped_callback(progress: RipProgress):
                if progress_callback:
                    progress_callback(title_index, progress)

            result = await self.rip_title(
                drive_index,
                title_index,
                output_dir,
                wrapped_callback,
            )
            results[title_index] = result

        return results
