"""Service for transcoding with HandBrake."""

import asyncio
import re
from pathlib import Path
from typing import Callable
from dataclasses import dataclass


@dataclass
class TranscodeProgress:
    """Progress update from transcoding."""
    percent: int
    fps: float = 0.0
    avg_fps: float = 0.0
    eta: str = ""
    message: str = ""


@dataclass
class TranscodeResult:
    """Result of a transcode operation."""
    success: bool
    return_code: int
    error_output: str = ""


class TranscoderService:
    """Manages video transcoding with HandBrake."""

    def build_transcode_command(
        self,
        input_path: Path,
        output_path: Path,
        preset_path: Path,
        preset_name: str,
    ) -> list[str]:
        """Build the HandBrakeCLI command for transcoding."""
        return [
            "HandBrakeCLI",
            "-i", str(input_path),
            "-o", str(output_path),
            "--preset-import-file", str(preset_path),
            "-Z", preset_name,
        ]

    def parse_progress(self, line: str) -> int | None:
        """Parse progress from HandBrake output line.

        HandBrake progress format:
        Encoding: task 1 of 1, 45.23 % (87.45 fps, avg 92.31 fps, ETA 00h12m34s)
        """
        match = re.search(r"(\d+\.?\d*)\s*%", line)
        if match:
            return int(float(match.group(1)))
        return None

    def parse_full_progress(self, line: str) -> TranscodeProgress | None:
        """Parse full progress info from HandBrake output."""
        if "Encoding:" not in line:
            return None

        percent = 0
        fps = 0.0
        avg_fps = 0.0
        eta = ""

        # Parse percentage
        pct_match = re.search(r"(\d+\.?\d*)\s*%", line)
        if pct_match:
            percent = int(float(pct_match.group(1)))

        # Parse FPS
        fps_match = re.search(r"\((\d+\.?\d*)\s*fps", line)
        if fps_match:
            fps = float(fps_match.group(1))

        # Parse average FPS
        avg_match = re.search(r"avg\s*(\d+\.?\d*)\s*fps", line)
        if avg_match:
            avg_fps = float(avg_match.group(1))

        # Parse ETA
        eta_match = re.search(r"ETA\s*(\d+h\d+m\d+s)", line)
        if eta_match:
            eta = eta_match.group(1)

        return TranscodeProgress(
            percent=percent,
            fps=fps,
            avg_fps=avg_fps,
            eta=eta,
            message=line.strip(),
        )

    async def transcode(
        self,
        input_path: Path,
        output_path: Path,
        preset_path: Path,
        preset_name: str,
        progress_callback: Callable[[TranscodeProgress], None] | None = None,
    ) -> TranscodeResult:
        """Transcode a video file.

        Returns TranscodeResult with success, return_code, and error_output.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = self.build_transcode_command(
            input_path, output_path, preset_path, preset_name
        )

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_progress = 0
        error_lines: list[str] = []

        async for line in process.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()

            # Capture error lines (lines with ERROR, error, or fail keywords)
            if any(kw in line_str.lower() for kw in ["error", "fail", "cannot", "invalid"]):
                error_lines.append(line_str)

            if progress_callback:
                progress = self.parse_full_progress(line_str)
                if progress and progress.percent != last_progress:
                    last_progress = progress.percent
                    progress_callback(progress)

        await process.wait()

        success = process.returncode == 0 and output_path.exists()
        return TranscodeResult(
            success=success,
            return_code=process.returncode,
            error_output="\n".join(error_lines),
        )

    async def get_video_info(self, input_path: Path) -> dict | None:
        """Get video information using HandBrake scan."""
        cmd = [
            "HandBrakeCLI",
            "-i", str(input_path),
            "--scan",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        output, _ = await process.communicate()
        output_str = output.decode("utf-8", errors="replace")

        # Parse resolution
        info = {}
        res_match = re.search(r"(\d+)x(\d+)", output_str)
        if res_match:
            info["width"] = int(res_match.group(1))
            info["height"] = int(res_match.group(2))

        return info if info else None
