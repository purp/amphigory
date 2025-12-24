"""Tests for main daemon application - TDD: tests written first."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock


# Default values to try on first run
DEFAULT_WEBAPP_URL = "http://localhost:6199"
DEFAULT_WEBAPP_BASEDIR = "/opt/amphigory"


class TestDaemonIdGeneration:
    """Tests for daemon ID generation."""

    def test_generate_daemon_id_returns_string(self):
        """generate_daemon_id returns a string."""
        from amphigory_daemon.main import generate_daemon_id

        result = generate_daemon_id()

        assert isinstance(result, str)

    def test_generate_daemon_id_contains_username(self):
        """Daemon ID contains the username."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {"USER": "testuser"}):
            with patch("socket.gethostname", return_value="testhost"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = False
                    result = generate_daemon_id()

        assert "testuser" in result

    def test_generate_daemon_id_contains_hostname(self):
        """Daemon ID contains the short hostname."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {"USER": "testuser"}):
            with patch("socket.gethostname", return_value="testhost.example.com"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = False
                    result = generate_daemon_id()

        assert "testhost" in result
        assert "example.com" not in result

    def test_generate_daemon_id_format(self):
        """Daemon ID follows username@hostname format."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {"USER": "purp"}):
            with patch("socket.gethostname", return_value="beehive.meyer.home"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = False
                    result = generate_daemon_id()

        assert result == "purp@beehive"

    def test_generate_daemon_id_adds_dev_suffix_for_tty(self):
        """Daemon ID has :dev suffix when running from TTY."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {"USER": "purp"}):
            with patch("socket.gethostname", return_value="beehive"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = True
                    result = generate_daemon_id()

        assert result == "purp@beehive:dev"

    def test_generate_daemon_id_no_dev_suffix_for_non_tty(self):
        """Daemon ID has no :dev suffix when not running from TTY."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {"USER": "purp"}):
            with patch("socket.gethostname", return_value="beehive"):
                with patch("sys.stdin") as mock_stdin:
                    mock_stdin.isatty.return_value = False
                    result = generate_daemon_id()

        assert result == "purp@beehive"
        assert ":dev" not in result

    def test_generate_daemon_id_handles_missing_user(self):
        """Daemon ID handles missing USER env var."""
        from amphigory_daemon.main import generate_daemon_id

        with patch.dict("os.environ", {}, clear=True):
            with patch("os.environ.get", return_value="unknown"):
                with patch("socket.gethostname", return_value="testhost"):
                    with patch("sys.stdin") as mock_stdin:
                        mock_stdin.isatty.return_value = False
                        result = generate_daemon_id()

        assert "@" in result


class TestColdStartMode:
    """Tests for cold-start mode and auto-configuration."""

    def test_has_default_webapp_url(self):
        """Module defines a default webapp URL to try."""
        from amphigory_daemon.main import DEFAULT_WEBAPP_URL

        assert DEFAULT_WEBAPP_URL == "http://localhost:6199"

    def test_has_default_webapp_basedir(self):
        """Module defines a default webapp basedir to try."""
        from amphigory_daemon.main import DEFAULT_WEBAPP_BASEDIR

        assert DEFAULT_WEBAPP_BASEDIR == "/opt/amphigory"

    def test_is_configured_returns_false_when_config_missing(self, tmp_path):
        """is_configured returns False when local config file doesn't exist."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        nonexistent = tmp_path / "nonexistent" / "daemon.yaml"

        result = daemon.is_configured(nonexistent)

        assert result is False

    def test_is_configured_returns_true_when_config_exists(self, tmp_path):
        """is_configured returns True when local config file exists."""
        from amphigory_daemon.main import AmphigoryDaemon

        config_file = tmp_path / "daemon.yaml"
        config_file.write_text("webapp_url: http://localhost:3000\nwebapp_basedir: /app")

        daemon = AmphigoryDaemon()
        result = daemon.is_configured(config_file)

        assert result is True

    def test_cold_start_sets_needs_config_overlay(self):
        """Daemon in cold-start mode has NEEDS_CONFIG overlay."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.icons import StatusOverlay

        daemon = AmphigoryDaemon()

        daemon.enter_cold_start_mode()

        assert StatusOverlay.NEEDS_CONFIG in daemon.status_overlays

    def test_cold_start_mode_stored_as_flag(self):
        """Cold-start mode is tracked via a flag."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        assert daemon.cold_start_mode is False

        daemon.enter_cold_start_mode()

        assert daemon.cold_start_mode is True

    def test_cold_start_disables_most_menu_items(self):
        """Cold-start mode disables all menu items except Settings, Open Webapp, Quit."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        daemon.enter_cold_start_mode()

        # These should be enabled (have callbacks)
        assert daemon.settings_item.callback is not None
        assert daemon.open_webapp_item.callback is not None
        assert daemon.quit_item.callback is not None

        # These should be disabled (no callback)
        assert daemon.disc_item.callback is None
        assert daemon.progress_item.callback is None
        assert daemon.pause_item.callback is None
        assert daemon.pause_now_item.callback is None
        assert daemon.help_item.callback is None
        assert daemon.restart_item.callback is None

    def test_exit_cold_start_removes_needs_config_overlay(self):
        """Exiting cold-start mode removes NEEDS_CONFIG overlay."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.icons import StatusOverlay

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        daemon.exit_cold_start_mode()

        assert StatusOverlay.NEEDS_CONFIG not in daemon.status_overlays
        assert daemon.cold_start_mode is False

    def test_exit_cold_start_re_enables_menu_items(self):
        """Exiting cold-start mode re-enables previously disabled menu items."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        daemon.exit_cold_start_mode()

        # Pause items should be re-enabled
        assert daemon.pause_item.callback is not None
        assert daemon.pause_now_item.callback is not None


class TestAutoConfiguration:
    """Tests for automatic configuration with default values."""

    @pytest.mark.asyncio
    async def test_check_default_url_returns_url_when_reachable(self):
        """check_default_url returns URL when webapp is reachable."""
        from amphigory_daemon.main import AmphigoryDaemon, DEFAULT_WEBAPP_URL
        from amphigory_daemon.models import WebappConfig

        daemon = AmphigoryDaemon()

        mock_config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=8765,
            wiki_url="http://localhost:6199/wiki",
            heartbeat_interval=30,
            log_level="INFO",
            makemkv_path=None,
        )

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config
            result = await daemon.check_default_url()

        assert result == DEFAULT_WEBAPP_URL

    @pytest.mark.asyncio
    async def test_check_default_url_returns_none_when_unreachable(self):
        """check_default_url returns None when webapp is not reachable."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = ConnectionError("Cannot connect")
            result = await daemon.check_default_url()

        assert result is None

    def test_check_default_directory_returns_path_when_exists(self, tmp_path):
        """check_default_directory returns path when directory exists."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        test_dir = tmp_path / "amphigory"
        test_dir.mkdir()

        with patch("amphigory_daemon.main.DEFAULT_WEBAPP_BASEDIR", str(test_dir)):
            result = daemon.check_default_directory()

        assert result == str(test_dir)

    def test_check_default_directory_returns_none_when_missing(self):
        """check_default_directory returns None when directory doesn't exist."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.DEFAULT_WEBAPP_BASEDIR", "/nonexistent/path/amphigory"):
            result = daemon.check_default_directory()

        assert result is None

    def test_found_values_stored_on_daemon(self):
        """Daemon stores found URL and directory for dialog."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        assert hasattr(daemon, "found_url")
        assert hasattr(daemon, "found_directory")

    @pytest.mark.asyncio
    async def test_try_default_config_succeeds_when_webapp_reachable(self, tmp_path):
        """try_default_config saves config when webapp responds at default URL."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import WebappConfig

        daemon = AmphigoryDaemon()
        config_file = tmp_path / "daemon.yaml"

        # Mock successful fetch from webapp
        mock_config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=8765,
            wiki_url="http://localhost:3000/wiki",
            heartbeat_interval=30,
            log_level="INFO",
            makemkv_path=None,
        )

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config

            result = await daemon.try_default_config(config_file)

        assert result is True
        assert config_file.exists()

    @pytest.mark.asyncio
    async def test_try_default_config_fails_when_webapp_unreachable(self, tmp_path):
        """try_default_config returns False when webapp is not reachable."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        config_file = tmp_path / "daemon.yaml"

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = ConnectionError("Cannot connect")

            result = await daemon.try_default_config(config_file)

        assert result is False
        assert not config_file.exists()

    @pytest.mark.asyncio
    async def test_try_default_config_writes_correct_yaml(self, tmp_path):
        """try_default_config writes webapp_url and webapp_basedir to yaml."""
        from amphigory_daemon.main import AmphigoryDaemon, DEFAULT_WEBAPP_URL, DEFAULT_WEBAPP_BASEDIR
        from amphigory_daemon.models import WebappConfig
        import yaml

        daemon = AmphigoryDaemon()
        config_file = tmp_path / "daemon.yaml"

        mock_config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=8765,
            wiki_url="http://localhost:3000/wiki",
            heartbeat_interval=30,
            log_level="INFO",
            makemkv_path=None,
        )

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config

            await daemon.try_default_config(config_file)

        # Verify the file contents
        with open(config_file) as f:
            data = yaml.safe_load(f)

        assert data["webapp_url"] == DEFAULT_WEBAPP_URL
        assert data["webapp_basedir"] == DEFAULT_WEBAPP_BASEDIR


class TestStartupFlow:
    """Tests for initialization and startup flow."""

    @pytest.mark.asyncio
    async def test_initialize_tries_defaults_when_no_config(self, tmp_path):
        """initialize tries auto-config when local config doesn't exist."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import WebappConfig, DaemonConfig

        daemon = AmphigoryDaemon()
        config_file = tmp_path / "daemon.yaml"
        cache_file = tmp_path / "cached_config.json"

        mock_webapp_config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=8765,
            wiki_url="http://localhost:6199/wiki",
            heartbeat_interval=30,
            log_level="INFO",
            makemkv_path=None,
        )
        mock_daemon_config = DaemonConfig(
            webapp_url="http://localhost:6199",
            webapp_basedir=str(tmp_path / "webapp"),
        )

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_webapp_config
            with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = (mock_daemon_config, mock_webapp_config)
                with patch("amphigory_daemon.main.discover_makemkvcon") as mock_discover:
                    mock_discover.return_value = Path("/usr/local/bin/makemkvcon")
                    # Also patch WebSocketServer and DiscDetector to avoid real initialization
                    with patch("amphigory_daemon.main.WebSocketServer") as mock_ws:
                        mock_ws.return_value.start = AsyncMock()
                        with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                            mock_disc.return_value.start = MagicMock()
                            mock_disc.return_value.get_current_disc = MagicMock(return_value=None)

                            result = await daemon.initialize(config_file, cache_file)

        # Should have auto-configured
        assert config_file.exists()
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_enters_cold_start_when_auto_config_fails(self, tmp_path):
        """initialize enters cold-start mode when auto-config fails."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.icons import StatusOverlay

        daemon = AmphigoryDaemon()
        config_file = tmp_path / "daemon.yaml"
        cache_file = tmp_path / "cached_config.json"

        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = ConnectionError("Cannot connect")

            result = await daemon.initialize(config_file, cache_file)

        # Should be in cold-start mode
        assert daemon.cold_start_mode is True
        assert StatusOverlay.NEEDS_CONFIG in daemon.status_overlays
        assert result is False


class TestConfigurationDialog:
    """Tests for configuration dialog when cold-start mode is active."""

    def test_show_config_dialog_callable(self):
        """Daemon has a show_config_dialog method."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        assert hasattr(daemon, "show_config_dialog")
        assert callable(daemon.show_config_dialog)

    def test_show_config_dialog_creates_dialog(self):
        """show_config_dialog creates a ConfigDialog."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.dialogs import DialogResult

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.ConfigDialog") as mock_dialog_class:
            mock_dialog = MagicMock()
            mock_dialog.run.return_value = DialogResult(cancelled=True)
            mock_dialog_class.return_value = mock_dialog
            daemon.show_config_dialog()

            mock_dialog_class.assert_called_once()

    def test_config_dialog_saves_on_ok(self, tmp_path):
        """Config dialog saves settings when user clicks Save."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.dialogs import DialogResult

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        config_file = tmp_path / "daemon.yaml"

        with patch("amphigory_daemon.main.ConfigDialog") as mock_dialog_class:
            mock_dialog = MagicMock()
            mock_dialog.run.return_value = DialogResult(
                cancelled=False,
                url="http://myserver:6199",
                directory="/my/path",
            )
            mock_dialog_class.return_value = mock_dialog
            with patch("amphigory_daemon.main.LOCAL_CONFIG_FILE", config_file):
                daemon.show_config_dialog()

        assert config_file.exists()

    def test_config_dialog_does_not_save_on_cancel(self, tmp_path):
        """Config dialog doesn't save when user clicks Cancel."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.dialogs import DialogResult

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        config_file = tmp_path / "daemon.yaml"

        with patch("amphigory_daemon.main.ConfigDialog") as mock_dialog_class:
            mock_dialog = MagicMock()
            mock_dialog.run.return_value = DialogResult(cancelled=True)
            mock_dialog_class.return_value = mock_dialog
            with patch("amphigory_daemon.main.LOCAL_CONFIG_FILE", config_file):
                daemon.show_config_dialog()

        assert not config_file.exists()

    def test_config_dialog_includes_wiki_url(self):
        """Config dialog is created with wiki URL."""
        from amphigory_daemon.main import AmphigoryDaemon, WIKI_DOC_ROOT_URL
        from amphigory_daemon.dialogs import DialogResult

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.ConfigDialog") as mock_dialog_class:
            mock_dialog = MagicMock()
            mock_dialog.run.return_value = DialogResult(cancelled=True)
            mock_dialog_class.return_value = mock_dialog
            daemon.show_config_dialog()

            # Check wiki_url was passed
            call_kwargs = mock_dialog_class.call_args.kwargs
            assert "wiki_url" in call_kwargs
            assert WIKI_DOC_ROOT_URL in call_kwargs["wiki_url"]

    def test_settings_in_cold_start_shows_dialog(self):
        """Clicking Settings in cold-start mode shows config dialog."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        with patch.object(daemon, "show_config_dialog") as mock_dialog:
            # Trigger the settings callback
            daemon.open_settings(None)

            mock_dialog.assert_called_once()

    def test_open_webapp_in_cold_start_shows_dialog(self):
        """Clicking Open Webapp in cold-start mode shows config dialog."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.enter_cold_start_mode()

        with patch.object(daemon, "show_config_dialog") as mock_dialog:
            # Trigger the open webapp callback
            daemon.open_webapp(None)

            mock_dialog.assert_called_once()


class TestStartupValidation:
    """Tests for config validation on startup."""

    @pytest.mark.asyncio
    async def test_initialize_calls_validate_config(self, tmp_path):
        """initialize() calls validate_config after loading config."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        import yaml

        # Create a config file
        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:6199",
            "webapp_basedir": str(tmp_path),
        }))
        cache_file = tmp_path / "cached_config.json"

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get_config:
            mock_get_config.return_value = (
                DaemonConfig(
                    webapp_url="http://localhost:6199",
                    webapp_basedir=str(tmp_path),
                ),
                WebappConfig(
                    tasks_directory="/tasks",
                    websocket_port=8765,
                    wiki_url="http://localhost/wiki",
                    heartbeat_interval=30,
                    log_level="INFO",
                    makemkv_path=None,
                ),
            )
            with patch("amphigory_daemon.main.validate_config") as mock_validate:
                from amphigory_daemon.config import ConfigValidationResult
                mock_validate.return_value = ConfigValidationResult(
                    makemkvcon_valid=True,
                    makemkvcon_error=None,
                    basedir_valid=True,
                    basedir_error=None,
                )
                with patch("amphigory_daemon.main.discover_makemkvcon") as mock_discover:
                    mock_discover.return_value = Path("/usr/bin/makemkvcon")
                    with patch("amphigory_daemon.main.WebSocketServer"):
                        with patch("amphigory_daemon.main.WebAppClient"):
                            with patch("amphigory_daemon.main.DiscDetector"):
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_logs_validation_errors(self, tmp_path, caplog):
        """initialize() logs validation errors."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml
        import logging

        # Create a config file
        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:6199",
            "webapp_basedir": "/nonexistent/path",
        }))
        cache_file = tmp_path / "cached_config.json"

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get_config:
            mock_get_config.return_value = (
                DaemonConfig(
                    webapp_url="http://localhost:6199",
                    webapp_basedir="/nonexistent/path",
                ),
                WebappConfig(
                    tasks_directory="/tasks",
                    websocket_port=8765,
                    wiki_url="http://localhost/wiki",
                    heartbeat_interval=30,
                    log_level="INFO",
                    makemkv_path=None,
                ),
            )
            with patch("amphigory_daemon.main.validate_config") as mock_validate:
                mock_validate.return_value = ConfigValidationResult(
                    makemkvcon_valid=False,
                    makemkvcon_error="makemkvcon not found at /usr/bin/makemkvcon",
                    basedir_valid=False,
                    basedir_error="Data directory not found at /nonexistent/path",
                )
                with patch("amphigory_daemon.main.discover_makemkvcon") as mock_discover:
                    mock_discover.return_value = Path("/usr/bin/makemkvcon")
                    with patch("amphigory_daemon.main.WebSocketServer"):
                        with patch("amphigory_daemon.main.WebAppClient"):
                            with patch("amphigory_daemon.main.DiscDetector"):
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    with caplog.at_level(logging.WARNING):
                                        await daemon.initialize(config_file, cache_file)

        # Check that validation errors were logged
        assert "makemkvcon not found" in caplog.text or "Data directory not found" in caplog.text

    @pytest.mark.asyncio
    async def test_initialize_continues_with_partial_validation(self, tmp_path):
        """initialize() continues even when validation has errors (non-fatal)."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml

        # Create a config file
        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:6199",
            "webapp_basedir": str(tmp_path),
        }))
        cache_file = tmp_path / "cached_config.json"

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get_config:
            mock_get_config.return_value = (
                DaemonConfig(
                    webapp_url="http://localhost:6199",
                    webapp_basedir=str(tmp_path),
                ),
                WebappConfig(
                    tasks_directory="/tasks",
                    websocket_port=8765,
                    wiki_url="http://localhost/wiki",
                    heartbeat_interval=30,
                    log_level="INFO",
                    makemkv_path=None,
                ),
            )
            with patch("amphigory_daemon.main.validate_config") as mock_validate:
                # basedir is valid but makemkvcon is not (yet)
                mock_validate.return_value = ConfigValidationResult(
                    makemkvcon_valid=False,
                    makemkvcon_error="makemkvcon path not configured",
                    basedir_valid=True,
                    basedir_error=None,
                )
                with patch("amphigory_daemon.main.discover_makemkvcon") as mock_discover:
                    mock_discover.return_value = Path("/usr/bin/makemkvcon")
                    with patch("amphigory_daemon.main.WebSocketServer") as mock_ws:
                        mock_ws_instance = MagicMock()
                        mock_ws_instance.start = AsyncMock()
                        mock_ws.return_value = mock_ws_instance
                        with patch("amphigory_daemon.main.WebAppClient") as mock_client:
                            mock_client_instance = MagicMock()
                            mock_client_instance.connect = AsyncMock()
                            mock_client_instance.send_daemon_config = AsyncMock()
                            mock_client.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    result = await daemon.initialize(config_file, cache_file)

        # Should still succeed - makemkvcon discovery happens after validation
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_starts_heartbeat_loop(self, tmp_path):
        """initialize() starts the heartbeat loop after connecting to webapp."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml

        # Create a config file
        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:6199",
            "webapp_basedir": str(tmp_path),
        }))
        cache_file = tmp_path / "cached_config.json"

        daemon = AmphigoryDaemon()

        with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get_config:
            mock_get_config.return_value = (
                DaemonConfig(
                    webapp_url="http://localhost:6199",
                    webapp_basedir=str(tmp_path),
                ),
                WebappConfig(
                    tasks_directory="/tasks",
                    websocket_port=8765,
                    wiki_url="http://localhost/wiki",
                    heartbeat_interval=30,
                    log_level="INFO",
                    makemkv_path=None,
                ),
            )
            with patch("amphigory_daemon.main.validate_config") as mock_validate:
                mock_validate.return_value = ConfigValidationResult(
                    makemkvcon_valid=True,
                    makemkvcon_error=None,
                    basedir_valid=True,
                    basedir_error=None,
                )
                with patch("amphigory_daemon.main.discover_makemkvcon") as mock_discover:
                    mock_discover.return_value = Path("/usr/bin/makemkvcon")
                    with patch("amphigory_daemon.main.WebSocketServer") as mock_ws:
                        mock_ws_instance = MagicMock()
                        mock_ws_instance.start = AsyncMock()
                        mock_ws.return_value = mock_ws_instance
                        with patch("amphigory_daemon.main.WebAppClient") as mock_client:
                            mock_client_instance = MagicMock()
                            mock_client_instance.connect = AsyncMock()
                            mock_client_instance.send_daemon_config = AsyncMock()
                            mock_client_instance.start_heartbeat_loop = AsyncMock()
                            mock_client.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                            # Verify heartbeat loop was started as a task
                            assert daemon._heartbeat_task is not None
