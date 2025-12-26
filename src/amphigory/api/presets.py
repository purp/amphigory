"""API endpoints for preset management."""

from fastapi import APIRouter

from amphigory.presets import PresetManager
from amphigory.preset_selector import parse_resolution, recommend_preset
from amphigory.config import get_config

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
async def list_presets():
    """List all available presets."""
    config = get_config()
    manager = PresetManager(config.preset_dir)
    await manager.load()

    return {
        "presets": [
            {"name": p.name, "disc_type": p.disc_type}
            for p in manager.list_presets()
        ],
        "active": manager.active_presets,  # Maps disc_type -> preset_name
    }


@router.get("/recommend")
async def recommend_preset_for_resolution(resolution: str | None = None):
    """Get recommended preset category for a resolution."""
    dims = parse_resolution(resolution)
    if dims:
        category = recommend_preset(dims[0], dims[1])
    else:
        category = "dvd"  # Default
    return {"category": category}  # "dvd", "bluray", or "uhd"
