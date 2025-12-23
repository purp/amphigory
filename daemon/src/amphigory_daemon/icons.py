"""Menu bar icon state management for Amphigory daemon."""

from enum import Enum, auto
from pathlib import Path
from typing import Optional, Set


class ActivityState(Enum):
    """Activity state for the base icon."""
    IDLE_EMPTY = auto()   # No disc inserted
    IDLE_DISC = auto()    # Disc inserted, idle
    WORKING = auto()      # Processing a task


class StatusOverlay(Enum):
    """Status overlays that can be applied to the icon."""
    NONE = auto()         # No overlay
    PAUSED = auto()       # Paused (⏸)
    DISCONNECTED = auto() # Webapp disconnected (✕)
    ERROR = auto()        # Error state (⚠)
    NEEDS_CONFIG = auto() # Needs configuration (❓)


# Map activity states to base icon names
_ACTIVITY_NAMES = {
    ActivityState.IDLE_EMPTY: "idle_empty",
    ActivityState.IDLE_DISC: "idle_disc",
    ActivityState.WORKING: "working",
}

# Map overlays to suffix names (sorted order for consistency)
_OVERLAY_NAMES = {
    StatusOverlay.DISCONNECTED: "disconnected",
    StatusOverlay.ERROR: "error",
    StatusOverlay.NEEDS_CONFIG: "needs_config",
    StatusOverlay.PAUSED: "paused",
}


def get_icon_name(
    activity: ActivityState,
    overlays: Optional[Set[StatusOverlay]] = None,
) -> str:
    """
    Get the icon filename for the given state.

    Args:
        activity: Current activity state
        overlays: Set of status overlays to apply

    Returns:
        Icon name (without extension) like "idle_empty" or "working_paused_disconnected"
    """
    base_name = _ACTIVITY_NAMES[activity]

    if not overlays:
        return base_name

    # Filter out NONE and sort for consistent naming
    overlay_suffixes = sorted(
        _OVERLAY_NAMES[o]
        for o in overlays
        if o != StatusOverlay.NONE and o in _OVERLAY_NAMES
    )

    if not overlay_suffixes:
        return base_name

    return f"{base_name}_{'_'.join(overlay_suffixes)}"


def get_icon_path(
    activity: ActivityState,
    overlays: Optional[Set[StatusOverlay]] = None,
    resources_dir: Optional[Path] = None,
) -> Path:
    """
    Get the full path to the icon file for the given state.

    Args:
        activity: Current activity state
        overlays: Set of status overlays to apply
        resources_dir: Directory containing icon files

    Returns:
        Path to icon PNG file
    """
    if resources_dir is None:
        # Default to package resources directory
        resources_dir = Path(__file__).parent.parent.parent / "resources" / "icons"

    icon_name = get_icon_name(activity, overlays)
    return resources_dir / f"{icon_name}.png"


def get_all_icon_names() -> list[str]:
    """
    Get list of all possible icon names.

    Useful for generating/validating icon assets.

    Returns:
        List of all icon name combinations
    """
    names = []

    for activity in ActivityState:
        # Base icon without overlays
        names.append(get_icon_name(activity))

        # Single overlays
        for overlay in StatusOverlay:
            if overlay != StatusOverlay.NONE:
                names.append(get_icon_name(activity, {overlay}))

        # Common overlay combinations
        overlay_combos = [
            {StatusOverlay.PAUSED, StatusOverlay.DISCONNECTED},
            {StatusOverlay.ERROR, StatusOverlay.DISCONNECTED},
        ]
        for combo in overlay_combos:
            names.append(get_icon_name(activity, combo))

    return sorted(set(names))
