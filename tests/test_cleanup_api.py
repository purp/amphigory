"""Tests for Cleanup API."""

import json
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from amphigory.main import app


@pytest.fixture
async def cleanup_env(tmp_path, monkeypatch):
    """Set up test environment with temp directories."""
    ripped = tmp_path / "ripped"
    transcoded = tmp_path / "transcoded"
    plex = tmp_path / "plex"

    ripped.mkdir()
    transcoded.mkdir()
    plex.mkdir()

    # Create Plex subdirectories
    (plex / "Movies").mkdir()
    (plex / "TV-Shows").mkdir()
    (plex / "Music").mkdir()

    monkeypatch.setenv("AMPHIGORY_RIPPED_DIR", str(ripped))
    monkeypatch.setenv("AMPHIGORY_TRANSCODED_DIR", str(transcoded))
    monkeypatch.setenv("AMPHIGORY_PLEX_DIR", str(plex))

    return {
        "ripped": ripped,
        "transcoded": transcoded,
        "plex": plex,
    }


@pytest.mark.asyncio
async def test_list_ripped_folders(cleanup_env):
    """GET /api/cleanup/ripped returns folder info."""
    ripped = cleanup_env["ripped"]

    # Create test folders with files
    folder1 = ripped / "Movie1"
    folder1.mkdir()
    (folder1 / "test.mkv").write_text("x" * 1000)

    folder2 = ripped / "Movie2"
    folder2.mkdir()
    (folder2 / "test1.mkv").write_text("x" * 2000)
    (folder2 / "test2.mkv").write_text("x" * 3000)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/ripped")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 2
    assert data["total_size"] == 6000


@pytest.mark.asyncio
async def test_ripped_folder_includes_size(cleanup_env):
    """Each folder has name, size, file_count, age_days."""
    ripped = cleanup_env["ripped"]

    folder = ripped / "TestMovie"
    folder.mkdir()
    (folder / "file1.mkv").write_text("x" * 1024)
    (folder / "file2.mkv").write_text("x" * 2048)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/ripped")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 1

    folder_info = data["folders"][0]
    assert folder_info["name"] == "TestMovie"
    assert folder_info["size"] == 3072
    assert folder_info["file_count"] == 2
    assert "age_days" in folder_info
    assert folder_info["age_days"] >= 0


@pytest.mark.asyncio
async def test_delete_ripped_folder(cleanup_env):
    """DELETE /api/cleanup/ripped deletes and confirms gone."""
    ripped = cleanup_env["ripped"]

    # Create test folder
    folder = ripped / "ToDelete"
    folder.mkdir()
    (folder / "test.mkv").write_text("test data")

    # Verify it exists
    assert folder.exists()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            "DELETE",
            "/api/cleanup/ripped",
            json={"folders": ["ToDelete"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 1
    assert len(data["errors"]) == 0

    # Verify it's gone
    assert not folder.exists()


@pytest.mark.asyncio
async def test_delete_prevents_path_traversal(cleanup_env):
    """DELETE rejects path traversal attempts."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test various path traversal patterns
        dangerous_paths = [
            "../../../etc/passwd",
            "../../sensitive",
            "../parent",
            "folder/../../../etc",
            "test/../../etc",
        ]

        for path in dangerous_paths:
            response = await client.request(
                "DELETE",
                "/api/cleanup/ripped",
                json={"folders": [path]},
            )
            # Should fail validation at Pydantic level (422) or be blocked (200 with errors)
            assert response.status_code in [422, 200], f"Failed for path: {path}"

            if response.status_code == 200:
                data = response.json()
                assert data["deleted"] == 0, f"Unexpectedly deleted: {path}"


@pytest.mark.asyncio
async def test_list_transcoded_folders(cleanup_env):
    """GET /api/cleanup/transcoded returns transcoded folder info."""
    transcoded = cleanup_env["transcoded"]

    # Create test folders
    folder1 = transcoded / "TranscodedMovie1"
    folder1.mkdir()
    (folder1 / "movie.mkv").write_text("x" * 5000)

    folder2 = transcoded / "TranscodedMovie2"
    folder2.mkdir()
    (folder2 / "movie.mkv").write_text("x" * 3000)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/transcoded")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 2
    assert data["total_size"] == 8000


@pytest.mark.asyncio
async def test_move_to_plex(cleanup_env):
    """POST /api/cleanup/transcoded/move moves folder to Plex directory."""
    transcoded = cleanup_env["transcoded"]
    plex = cleanup_env["plex"]

    # Create test folder in transcoded
    folder = transcoded / "MovieToMove"
    folder.mkdir()
    test_file = folder / "movie.mkv"
    test_file.write_text("movie content")

    # Verify it's in transcoded
    assert folder.exists()
    assert test_file.exists()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cleanup/transcoded/move",
            json={
                "folders": ["MovieToMove"],
                "destination": "Movies",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["moved"] == 1
    assert len(data["errors"]) == 0

    # Verify it moved to Plex
    assert not folder.exists()  # Gone from transcoded
    new_location = plex / "Movies" / "MovieToMove"
    assert new_location.exists()
    assert (new_location / "movie.mkv").exists()
    assert (new_location / "movie.mkv").read_text() == "movie content"


@pytest.mark.asyncio
async def test_move_to_tv_shows(cleanup_env):
    """Move to TV-Shows destination."""
    transcoded = cleanup_env["transcoded"]
    plex = cleanup_env["plex"]

    folder = transcoded / "TVShow"
    folder.mkdir()
    (folder / "episode.mkv").write_text("episode")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cleanup/transcoded/move",
            json={
                "folders": ["TVShow"],
                "destination": "TV-Shows",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["moved"] == 1

    # Verify moved to TV-Shows
    new_location = plex / "TV-Shows" / "TVShow"
    assert new_location.exists()


@pytest.mark.asyncio
async def test_move_prevents_path_traversal(cleanup_env):
    """POST /api/cleanup/transcoded/move rejects path traversal."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test path traversal in folder names
        response = await client.post(
            "/api/cleanup/transcoded/move",
            json={
                "folders": ["../../etc/passwd"],
                "destination": "Movies",
            },
        )

        # Should fail validation at Pydantic level
        assert response.status_code in [422, 200]
        if response.status_code == 200:
            data = response.json()
            assert data["moved"] == 0


@pytest.mark.asyncio
async def test_move_invalid_destination(cleanup_env):
    """POST /api/cleanup/transcoded/move rejects invalid destination."""
    transcoded = cleanup_env["transcoded"]

    folder = transcoded / "Test"
    folder.mkdir()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cleanup/transcoded/move",
            json={
                "folders": ["Test"],
                "destination": "InvalidDestination",
            },
        )

    # Should fail Pydantic validation
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_multiple_folders(cleanup_env):
    """Delete multiple folders at once."""
    ripped = cleanup_env["ripped"]

    # Create multiple folders
    for i in range(3):
        folder = ripped / f"Folder{i}"
        folder.mkdir()
        (folder / "file.mkv").write_text(f"content{i}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            "DELETE",
            "/api/cleanup/ripped",
            json={"folders": ["Folder0", "Folder1", "Folder2"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 3
    assert len(data["errors"]) == 0

    # Verify all are gone
    for i in range(3):
        assert not (ripped / f"Folder{i}").exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_folder(cleanup_env):
    """Deleting nonexistent folder returns error."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            "DELETE",
            "/api/cleanup/ripped",
            json={"folders": ["DoesNotExist"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 0
    assert len(data["errors"]) == 1
    assert "does not exist" in data["errors"][0].lower()


@pytest.mark.asyncio
async def test_move_multiple_folders(cleanup_env):
    """Move multiple folders at once."""
    transcoded = cleanup_env["transcoded"]
    plex = cleanup_env["plex"]

    # Create multiple folders
    for i in range(3):
        folder = transcoded / f"Movie{i}"
        folder.mkdir()
        (folder / "file.mkv").write_text(f"content{i}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cleanup/transcoded/move",
            json={
                "folders": ["Movie0", "Movie1", "Movie2"],
                "destination": "Movies",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["moved"] == 3
    assert len(data["errors"]) == 0

    # Verify all moved
    for i in range(3):
        assert not (transcoded / f"Movie{i}").exists()
        assert (plex / "Movies" / f"Movie{i}").exists()


@pytest.mark.asyncio
async def test_list_empty_ripped_directory(cleanup_env):
    """List ripped directory when empty."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/ripped")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 0
    assert data["total_size"] == 0


@pytest.mark.asyncio
async def test_list_empty_transcoded_directory(cleanup_env):
    """List transcoded directory when empty."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/cleanup/transcoded")

    assert response.status_code == 200
    data = response.json()
    assert len(data["folders"]) == 0
    assert data["total_size"] == 0
