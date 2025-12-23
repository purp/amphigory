"""Shared pytest fixtures for webapp tests."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def test_client(tmp_path):
    """Create a test client for the FastAPI app."""
    import os
    from fastapi.testclient import TestClient

    # Set up test environment
    os.environ["AMPHIGORY_DATA"] = str(tmp_path / "data")
    os.environ["AMPHIGORY_CONFIG"] = str(tmp_path / "config")

    # Create required directories
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "presets").mkdir()

    from amphigory.main import app

    with TestClient(app) as client:
        yield client
