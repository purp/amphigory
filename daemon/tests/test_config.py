"""Tests for configuration management - TDD: tests written first."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


class TestLoadLocalConfig:
    def test_loads_valid_yaml(self, tmp_path):
        """Load daemon config from valid YAML file."""
        from amphigory_daemon.config import load_local_config
        from amphigory_daemon.models import DaemonConfig

        config_dir = tmp_path / ".config" / "amphigory"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/beehive-docker/amphigory",
        }))

        config = load_local_config(config_file)

        assert isinstance(config, DaemonConfig)
        assert config.webapp_url == "http://localhost:8080"
        assert config.webapp_basedir == "/opt/beehive-docker/amphigory"

    def test_raises_on_missing_file(self, tmp_path):
        """Raise FileNotFoundError when config file doesn't exist."""
        from amphigory_daemon.config import load_local_config

        missing_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            load_local_config(missing_file)

    def test_raises_on_missing_required_fields(self, tmp_path):
        """Raise ValueError when required fields are missing."""
        from amphigory_daemon.config import load_local_config

        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            # Missing webapp_basedir
        }))

        with pytest.raises(ValueError, match="webapp_basedir"):
            load_local_config(config_file)


class TestFetchWebappConfig:
    @pytest.mark.asyncio
    async def test_fetches_config_from_webapp(self):
        """Fetch and parse config from webapp's /config.json endpoint."""
        from amphigory_daemon.config import fetch_webapp_config
        from amphigory_daemon.models import WebappConfig
        from unittest.mock import MagicMock

        mock_response_data = {
            "tasks_directory": "/tasks",
            "websocket_port": 9847,
            "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
            "heartbeat_interval": 10,
            "log_level": "info",
            "makemkv_path": None,
        }

        with patch("amphigory_daemon.config.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            config = await fetch_webapp_config("http://localhost:8080")

        assert isinstance(config, WebappConfig)
        assert config.tasks_directory == "/tasks"
        assert config.websocket_port == 9847

    @pytest.mark.asyncio
    async def test_raises_on_connection_error(self):
        """Raise ConnectionError when webapp is unreachable."""
        from amphigory_daemon.config import fetch_webapp_config
        import httpx

        with patch("amphigory_daemon.config.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ConnectionError):
                await fetch_webapp_config("http://localhost:8080")


class TestCacheWebappConfig:
    def test_caches_config_to_file(self, tmp_path):
        """Write config to cached_config.json."""
        from amphigory_daemon.config import cache_webapp_config
        from amphigory_daemon.models import WebappConfig

        cache_file = tmp_path / "cached_config.json"
        config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=9847,
            wiki_url="http://gollum.meyer.home/Amphigory/Home",
            heartbeat_interval=10,
            log_level="info",
            makemkv_path=None,
        )

        cache_webapp_config(config, cache_file)

        assert cache_file.exists()
        cached = json.loads(cache_file.read_text())
        assert cached["tasks_directory"] == "/tasks"
        assert cached["websocket_port"] == 9847


class TestLoadCachedConfig:
    def test_loads_cached_config(self, tmp_path):
        """Load config from cache file."""
        from amphigory_daemon.config import load_cached_config
        from amphigory_daemon.models import WebappConfig

        cache_file = tmp_path / "cached_config.json"
        cache_file.write_text(json.dumps({
            "tasks_directory": "/tasks",
            "websocket_port": 9847,
            "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
            "heartbeat_interval": 10,
            "log_level": "info",
            "makemkv_path": None,
        }))

        config = load_cached_config(cache_file)

        assert isinstance(config, WebappConfig)
        assert config.websocket_port == 9847

    def test_returns_none_when_no_cache(self, tmp_path):
        """Return None when cache file doesn't exist."""
        from amphigory_daemon.config import load_cached_config

        missing_file = tmp_path / "nonexistent.json"
        config = load_cached_config(missing_file)

        assert config is None


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_fetches_from_webapp_and_caches(self, tmp_path):
        """Fetch config from webapp and cache it."""
        from amphigory_daemon.config import get_config
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from unittest.mock import MagicMock

        # Create local config
        local_config_file = tmp_path / "daemon.yaml"
        local_config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/beehive-docker/amphigory",
        }))

        cache_file = tmp_path / "cached_config.json"

        mock_webapp_config = {
            "tasks_directory": "/tasks",
            "websocket_port": 9847,
            "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
            "heartbeat_interval": 10,
            "log_level": "info",
            "makemkv_path": None,
        }

        with patch("amphigory_daemon.config.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_webapp_config
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            daemon_config, webapp_config = await get_config(
                local_config_file, cache_file
            )

        assert isinstance(daemon_config, DaemonConfig)
        assert isinstance(webapp_config, WebappConfig)
        assert daemon_config.webapp_url == "http://localhost:8080"
        assert webapp_config.tasks_directory == "/tasks"
        assert cache_file.exists()

    @pytest.mark.asyncio
    async def test_falls_back_to_cache_when_webapp_unreachable(self, tmp_path):
        """Use cached config when webapp is offline."""
        from amphigory_daemon.config import get_config
        import httpx

        # Create local config
        local_config_file = tmp_path / "daemon.yaml"
        local_config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/beehive-docker/amphigory",
        }))

        # Create cache
        cache_file = tmp_path / "cached_config.json"
        cache_file.write_text(json.dumps({
            "tasks_directory": "/tasks",
            "websocket_port": 9847,
            "wiki_url": "http://gollum.meyer.home/Amphigory/Home",
            "heartbeat_interval": 10,
            "log_level": "info",
            "makemkv_path": None,
        }))

        with patch("amphigory_daemon.config.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            daemon_config, webapp_config = await get_config(
                local_config_file, cache_file
            )

        assert webapp_config.tasks_directory == "/tasks"

    @pytest.mark.asyncio
    async def test_raises_when_no_webapp_and_no_cache(self, tmp_path):
        """Raise error when webapp unreachable and no cache exists."""
        from amphigory_daemon.config import get_config
        import httpx

        local_config_file = tmp_path / "daemon.yaml"
        local_config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/beehive-docker/amphigory",
        }))

        cache_file = tmp_path / "nonexistent_cache.json"

        with patch("amphigory_daemon.config.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ConnectionError, match="cache"):
                await get_config(local_config_file, cache_file)
