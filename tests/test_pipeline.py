"""Tests for pipeline orchestration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_pipeline_creates_folder_structure():
    """Test that pipeline creates correct folder structure."""
    from amphigory.pipeline import Pipeline

    with patch.object(Path, 'mkdir') as mock_mkdir:
        pipeline = Pipeline(
            ripped_dir=Path("/media/ripped"),
            inbox_dir=Path("/media/plex/inbox"),
            plex_dir=Path("/media/plex/data"),
        )

        paths = pipeline.create_folder_structure(
            title="The Polar Express",
            year=2004,
            imdb_id="tt0338348",
            extras_types=["Featurettes", "Trailers"],
        )

        assert "ripped" in paths
        assert "inbox" in paths
        assert "The Polar Express (2004) {imdb-tt0338348}" in str(paths["ripped"])
