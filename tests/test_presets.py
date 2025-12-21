"""Tests for Handbrake preset management."""

import pytest
import tempfile
from pathlib import Path
import json
import yaml


@pytest.fixture
def temp_preset_dir():
    """Create temporary preset directory with sample presets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        preset_dir = Path(tmpdir)

        # Create a sample preset JSON
        preset_json = {
            "PresetList": [{
                "PresetName": "Test Preset",
                "VideoEncoder": "x265",
            }]
        }
        (preset_dir / "test-preset-v1.json").write_text(json.dumps(preset_json))

        # Create presets.yaml
        config = {
            "active": {
                "dvd": "test-preset-v1",
                "bluray": "test-preset-v1",
                "uhd4k": "test-preset-v1",
            }
        }
        (preset_dir / "presets.yaml").write_text(yaml.dump(config))

        yield preset_dir


@pytest.mark.asyncio
async def test_load_presets(temp_preset_dir):
    """Test loading presets from directory."""
    from amphigory.presets import PresetManager

    manager = PresetManager(temp_preset_dir)
    await manager.load()

    assert "test-preset-v1" in manager.presets
    assert manager.get_active_preset("dvd") == "test-preset-v1"


@pytest.mark.asyncio
async def test_get_preset_for_disc_type(temp_preset_dir):
    """Test getting appropriate preset for disc type."""
    from amphigory.presets import PresetManager

    manager = PresetManager(temp_preset_dir)
    await manager.load()

    preset_path = manager.get_preset_path("dvd")
    assert preset_path.exists()
    assert preset_path.name == "test-preset-v1.json"
