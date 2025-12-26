"""Tests for presets API endpoint."""

import pytest
import json
import yaml
from pathlib import Path


@pytest.fixture
def test_client_with_presets(tmp_path):
    """Create a test client with presets configured."""
    import os
    from fastapi.testclient import TestClient

    # Set up test environment
    os.environ["AMPHIGORY_DATA"] = str(tmp_path / "data")
    os.environ["AMPHIGORY_CONFIG"] = str(tmp_path / "config")

    # Create required directories
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    preset_dir = tmp_path / "config" / "presets"
    preset_dir.mkdir()

    # Create sample preset JSON files
    dvd_preset = {"PresetList": [{"PresetName": "DVD Preset"}]}
    bluray_preset = {"PresetList": [{"PresetName": "Bluray Preset"}]}
    uhd_preset = {"PresetList": [{"PresetName": "UHD Preset"}]}

    (preset_dir / "dvd-h265-720p.json").write_text(json.dumps(dvd_preset))
    (preset_dir / "bluray-h265-1080p.json").write_text(json.dumps(bluray_preset))
    (preset_dir / "uhd-h265-2160p.json").write_text(json.dumps(uhd_preset))

    # Create presets.yaml mapping
    config = {
        "active": {
            "dvd": "dvd-h265-720p",
            "bluray": "bluray-h265-1080p",
            "uhd4k": "uhd-h265-2160p",
        }
    }
    (preset_dir / "presets.yaml").write_text(yaml.dump(config))

    from amphigory.main import app

    with TestClient(app) as client:
        yield client


class TestPresetsAPI:
    """Tests for /api/presets endpoint."""

    def test_list_presets_returns_all_presets(self, test_client_with_presets):
        """GET /api/presets should return all available presets."""
        response = test_client_with_presets.get("/api/presets")

        assert response.status_code == 200
        data = response.json()

        # Should have presets list
        assert "presets" in data
        assert len(data["presets"]) == 3

        # Verify preset names are returned
        preset_names = [p["name"] for p in data["presets"]]
        assert "dvd-h265-720p" in preset_names
        assert "bluray-h265-1080p" in preset_names
        assert "uhd-h265-2160p" in preset_names

    def test_list_presets_returns_active_mappings(self, test_client_with_presets):
        """GET /api/presets should return active preset mappings."""
        response = test_client_with_presets.get("/api/presets")

        assert response.status_code == 200
        data = response.json()

        # Should have active mappings
        assert "active" in data
        assert data["active"]["dvd"] == "dvd-h265-720p"
        assert data["active"]["bluray"] == "bluray-h265-1080p"
        assert data["active"]["uhd4k"] == "uhd-h265-2160p"

    def test_list_presets_empty_directory(self, test_client):
        """GET /api/presets with empty preset dir should return empty list."""
        response = test_client.get("/api/presets")

        assert response.status_code == 200
        data = response.json()
        assert data["presets"] == []
        assert data["active"] == {}
