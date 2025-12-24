"""Tests for configuration management - TDD: tests written first."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


class TestDaemonConfigModel:
    """Tests for DaemonConfig model with new fields."""

    def test_daemon_config_has_daemon_id_field(self):
        """DaemonConfig has optional daemon_id field."""
        from amphigory_daemon.models import DaemonConfig

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            daemon_id="purp@beehive",
        )
        assert config.daemon_id == "purp@beehive"

    def test_daemon_config_daemon_id_optional(self):
        """DaemonConfig daemon_id defaults to None."""
        from amphigory_daemon.models import DaemonConfig

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
        )
        assert config.daemon_id is None

    def test_daemon_config_has_makemkvcon_path_field(self):
        """DaemonConfig has optional makemkvcon_path field."""
        from amphigory_daemon.models import DaemonConfig

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )
        assert config.makemkvcon_path == "/usr/local/bin/makemkvcon"

    def test_daemon_config_makemkvcon_path_optional(self):
        """DaemonConfig makemkvcon_path defaults to None."""
        from amphigory_daemon.models import DaemonConfig

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
        )
        assert config.makemkvcon_path is None

    def test_daemon_config_has_updated_at_field(self):
        """DaemonConfig has optional updated_at field."""
        from amphigory_daemon.models import DaemonConfig
        from datetime import datetime

        now = datetime.now()
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            updated_at=now,
        )
        assert config.updated_at == now


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

    def test_loads_optional_daemon_id(self, tmp_path):
        """Load daemon config with daemon_id."""
        from amphigory_daemon.config import load_local_config

        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/amphigory",
            "daemon_id": "purp@beehive",
        }))

        config = load_local_config(config_file)
        assert config.daemon_id == "purp@beehive"

    def test_loads_optional_makemkvcon_path(self, tmp_path):
        """Load daemon config with makemkvcon_path."""
        from amphigory_daemon.config import load_local_config

        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:8080",
            "webapp_basedir": "/opt/amphigory",
            "makemkvcon_path": "/usr/local/bin/makemkvcon",
        }))

        config = load_local_config(config_file)
        assert config.makemkvcon_path == "/usr/local/bin/makemkvcon"

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


class TestSaveLocalConfig:
    """Tests for save_local_config function."""

    def test_saves_config_to_file(self, tmp_path):
        """save_local_config writes config to YAML file."""
        from amphigory_daemon.config import save_local_config
        from amphigory_daemon.models import DaemonConfig

        config_file = tmp_path / "daemon.yaml"
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            daemon_id="purp@beehive",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )

        save_local_config(config, config_file)

        assert config_file.exists()
        saved = yaml.safe_load(config_file.read_text())
        assert saved["webapp_url"] == "http://localhost:8080"
        assert saved["webapp_basedir"] == "/opt/amphigory"
        assert saved["daemon_id"] == "purp@beehive"
        assert saved["makemkvcon_path"] == "/usr/local/bin/makemkvcon"

    def test_saves_config_creates_parent_dirs(self, tmp_path):
        """save_local_config creates parent directories if needed."""
        from amphigory_daemon.config import save_local_config
        from amphigory_daemon.models import DaemonConfig

        config_file = tmp_path / "nested" / "dir" / "daemon.yaml"
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
        )

        save_local_config(config, config_file)

        assert config_file.exists()

    def test_saves_config_includes_updated_at(self, tmp_path):
        """save_local_config includes updated_at timestamp."""
        from amphigory_daemon.config import save_local_config
        from amphigory_daemon.models import DaemonConfig
        from datetime import datetime

        config_file = tmp_path / "daemon.yaml"
        now = datetime.now()
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            updated_at=now,
        )

        save_local_config(config, config_file)

        saved = yaml.safe_load(config_file.read_text())
        assert "updated_at" in saved

    def test_saves_config_omits_none_values(self, tmp_path):
        """save_local_config omits fields that are None."""
        from amphigory_daemon.config import save_local_config
        from amphigory_daemon.models import DaemonConfig

        config_file = tmp_path / "daemon.yaml"
        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/opt/amphigory",
            # daemon_id and makemkvcon_path are None
        )

        save_local_config(config, config_file)

        saved = yaml.safe_load(config_file.read_text())
        assert "daemon_id" not in saved
        assert "makemkvcon_path" not in saved


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


class TestValidateConfig:
    """Tests for config validation on startup."""

    def test_validate_makemkvcon_path_exists(self, tmp_path):
        """validate_config returns valid when makemkvcon_path exists."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        # Create a fake makemkvcon executable
        fake_makemkv = tmp_path / "makemkvcon"
        fake_makemkv.touch()
        fake_makemkv.chmod(0o755)

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path=str(fake_makemkv),
        )

        result = validate_config(config)
        assert result.makemkvcon_valid is True

    def test_validate_makemkvcon_path_missing(self, tmp_path):
        """validate_config returns invalid when makemkvcon_path doesn't exist."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path="/nonexistent/path/makemkvcon",
        )

        result = validate_config(config)
        assert result.makemkvcon_valid is False
        assert "not found" in result.makemkvcon_error.lower()

    def test_validate_makemkvcon_path_none(self, tmp_path):
        """validate_config returns invalid when makemkvcon_path is None."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path=None,
        )

        result = validate_config(config)
        assert result.makemkvcon_valid is False

    def test_validate_webapp_basedir_exists(self, tmp_path):
        """validate_config returns valid when webapp_basedir exists."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        fake_makemkv = tmp_path / "makemkvcon"
        fake_makemkv.touch()
        fake_makemkv.chmod(0o755)

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path=str(fake_makemkv),
        )

        result = validate_config(config)
        assert result.basedir_valid is True

    def test_validate_webapp_basedir_missing(self, tmp_path):
        """validate_config returns invalid when webapp_basedir doesn't exist."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        fake_makemkv = tmp_path / "makemkvcon"
        fake_makemkv.touch()
        fake_makemkv.chmod(0o755)

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir="/nonexistent/path/data",
            makemkvcon_path=str(fake_makemkv),
        )

        result = validate_config(config)
        assert result.basedir_valid is False
        assert "not found" in result.basedir_error.lower()

    def test_validate_config_is_valid_when_all_pass(self, tmp_path):
        """validate_config.is_valid returns True when all checks pass."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        fake_makemkv = tmp_path / "makemkvcon"
        fake_makemkv.touch()
        fake_makemkv.chmod(0o755)

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path=str(fake_makemkv),
        )

        result = validate_config(config)
        assert result.is_valid is True

    def test_validate_config_is_invalid_when_any_fail(self, tmp_path):
        """validate_config.is_valid returns False when any check fails."""
        from amphigory_daemon.config import validate_config
        from amphigory_daemon.models import DaemonConfig

        basedir = tmp_path / "data"
        basedir.mkdir()

        config = DaemonConfig(
            webapp_url="http://localhost:8080",
            webapp_basedir=str(basedir),
            makemkvcon_path="/nonexistent/makemkvcon",
        )

        result = validate_config(config)
        assert result.is_valid is False
