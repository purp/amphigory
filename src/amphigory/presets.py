"""Handbrake preset management."""

import json
import yaml
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Preset:
    """A Handbrake preset."""
    name: str
    version: str
    disc_type: str | None
    file_path: Path
    preset_data: dict


class PresetManager:
    """Manages Handbrake presets."""

    def __init__(self, preset_dir: Path | str):
        self.preset_dir = Path(preset_dir)
        self.presets: dict[str, Preset] = {}
        self.active_presets: dict[str, str] = {}  # disc_type -> preset_name

    async def load(self) -> None:
        """Load all presets from directory."""
        # Load config
        config_path = self.preset_dir / "presets.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                self.active_presets = config.get("active", {})

        # Load preset JSON files
        for preset_file in self.preset_dir.glob("*.json"):
            try:
                with open(preset_file) as f:
                    data = json.load(f)

                name = preset_file.stem  # e.g., "dvd-h265-720p-v1"

                # Parse version from name if present
                version = "1"
                if "-v" in name:
                    parts = name.rsplit("-v", 1)
                    if parts[1].isdigit():
                        version = parts[1]

                self.presets[name] = Preset(
                    name=name,
                    version=version,
                    disc_type=self._infer_disc_type(name),
                    file_path=preset_file,
                    preset_data=data,
                )
            except (json.JSONDecodeError, IOError):
                continue

    def _infer_disc_type(self, name: str) -> str | None:
        """Infer disc type from preset name."""
        name_lower = name.lower()
        if "dvd" in name_lower:
            return "dvd"
        elif "uhd" in name_lower or "4k" in name_lower or "2160" in name_lower:
            return "uhd4k"
        elif "bluray" in name_lower or "blu-ray" in name_lower or "1080" in name_lower:
            return "bluray"
        return None

    def get_active_preset(self, disc_type: str) -> str | None:
        """Get the active preset name for a disc type."""
        return self.active_presets.get(disc_type)

    def get_preset_path(self, disc_type: str) -> Path | None:
        """Get the file path for the active preset for a disc type."""
        preset_name = self.get_active_preset(disc_type)
        if preset_name and preset_name in self.presets:
            return self.presets[preset_name].file_path
        return None

    def get_preset(self, name: str) -> Preset | None:
        """Get a preset by name."""
        return self.presets.get(name)

    def list_presets(self, disc_type: str | None = None) -> list[Preset]:
        """List all presets, optionally filtered by disc type."""
        presets = list(self.presets.values())
        if disc_type:
            presets = [p for p in presets if p.disc_type == disc_type]
        return presets
