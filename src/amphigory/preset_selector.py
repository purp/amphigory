"""Resolution-based preset recommendation for transcoding."""

import re
from typing import Optional, Tuple


def parse_resolution(resolution: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse resolution string (e.g., '1920x1080') into (width, height) tuple.

    Args:
        resolution: Resolution string in format 'WIDTHxHEIGHT'

    Returns:
        Tuple of (width, height) or None if parsing fails
    """
    if not resolution:
        return None

    match = re.match(r"(\d+)x(\d+)", resolution)
    if not match:
        return None

    return (int(match.group(1)), int(match.group(2)))


def recommend_preset(width: Optional[int], height: Optional[int]) -> str:
    """Recommend a preset category based on video resolution.

    Args:
        width: Video width in pixels
        height: Video height in pixels

    Returns:
        Preset category: 'uhd', 'bluray', or 'dvd'
    """
    if width is None or height is None:
        return "dvd"

    # 4K/UHD: 3840x2160 or higher
    if width >= 3840 or height >= 2160:
        return "uhd"

    # 1080p/Blu-ray: 1920x1080 or higher (but not 4K)
    if width >= 1920 or height >= 1080:
        return "bluray"

    # Everything else: DVD preset (720p, SD, etc.)
    return "dvd"
