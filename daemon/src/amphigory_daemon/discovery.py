"""Discovery of makemkvcon binary on the system."""

import shutil
from pathlib import Path
from typing import Optional


# Search paths for makemkvcon in order of preference (after $PATH)
SEARCH_PATHS = [
    "/opt/homebrew/bin/makemkvcon",       # Apple Silicon Homebrew
    "/usr/local/bin/makemkvcon",          # Intel Homebrew
    "/Applications/MakeMKV.app/Contents/MacOS/makemkvcon",  # App bundle
]


def discover_makemkvcon(configured_path: Optional[str] = None) -> Optional[Path]:
    """
    Find makemkvcon binary on the system.

    Search order:
    1. Configured path (if provided and exists)
    2. $PATH via shutil.which()
    3. Common installation locations (SEARCH_PATHS)

    Args:
        configured_path: Optional explicit path to makemkvcon

    Returns:
        Path to makemkvcon if found, None otherwise
    """
    # 1. Check configured path first
    if configured_path is not None:
        path = Path(configured_path)
        if path.exists():
            return path
        return None

    # 2. Check $PATH
    which_result = shutil.which("makemkvcon")
    if which_result is not None:
        return Path(which_result)

    # 3. Check common installation locations
    for search_path in SEARCH_PATHS:
        path = Path(search_path)
        if path.exists():
            return path

    return None
