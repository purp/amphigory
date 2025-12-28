"""Tests for main daemon application - TDD: tests written first."""

import asyncio
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


class TestFormatTaskSummary:
    """Tests for task summary formatting."""

    def test_format_size_gb(self):
        """format_size formats GB correctly."""
        from amphigory_daemon.main import format_size

        # 25 GB
        assert format_size(25 * 1024 ** 3) == "25.00 GB"
        # 1.5 GB
        assert format_size(int(1.5 * 1024 ** 3)) == "1.50 GB"

    def test_format_size_mb(self):
        """format_size formats MB correctly."""
        from amphigory_daemon.main import format_size

        # 500 MB
        assert format_size(500 * 1024 ** 2) == "500.0 MB"

    def test_format_scan_task_summary(self):
        """format_task_summary formats scan results."""
        from datetime import datetime
        from amphigory_daemon.main import format_task_summary
        from amphigory_daemon.models import TaskResponse, TaskStatus, ScanResult, ScannedTrack

        tracks = [
            ScannedTrack(number=0, duration="2:00:00", size_bytes=25_000_000_000,
                         chapters=20, resolution="1920x1080", audio_streams=[], subtitle_streams=[]),
            ScannedTrack(number=1, duration="0:05:00", size_bytes=500_000_000,
                         chapters=1, resolution="1920x1080", audio_streams=[], subtitle_streams=[]),
        ]
        response = TaskResponse(
            task_id="test-scan",
            status=TaskStatus.SUCCESS,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_seconds=45,
            result=ScanResult(disc_name="TEST_MOVIE", disc_type="bluray", tracks=tracks),
        )

        summary = format_task_summary(response)

        assert "TEST_MOVIE" in summary
        assert "bluray" in summary
        assert "2 tracks" in summary
        assert "45s" in summary

    def test_format_rip_task_summary(self):
        """format_task_summary formats rip results with speed."""
        from datetime import datetime
        from amphigory_daemon.main import format_task_summary
        from amphigory_daemon.models import TaskResponse, TaskStatus, RipResult, FileDestination

        response = TaskResponse(
            task_id="test-rip",
            status=TaskStatus.SUCCESS,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_seconds=600,  # 10 minutes
            result=RipResult(
                destination=FileDestination(
                    directory="/data/ripped",
                    filename="Movie (2024).mkv",
                    size_bytes=25 * 1024 ** 3,  # 25 GB
                )
            ),
        )

        summary = format_task_summary(response)

        assert "Movie (2024).mkv" in summary
        assert "25.00 GB" in summary
        assert "600s" in summary
        assert "MB/s" in summary

    def test_format_failed_task_summary(self):
        """format_task_summary formats failed tasks."""
        from datetime import datetime
        from amphigory_daemon.main import format_task_summary
        from amphigory_daemon.models import TaskResponse, TaskStatus, TaskError, ErrorCode

        response = TaskResponse(
            task_id="test-fail",
            status=TaskStatus.FAILED,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_seconds=5,
            error=TaskError(code=ErrorCode.MAKEMKV_FAILED, message="Disc unreadable"),
        )

        summary = format_task_summary(response)

        assert "Failed" in summary
        assert "Disc unreadable" in summary


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
                            mock_client_instance.run_with_reconnect = AsyncMock()
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
    async def test_initialize_starts_webapp_connection_loop(self, tmp_path):
        """initialize() starts the webapp connection loop with auto-reconnect."""
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
                            mock_client_instance.run_with_reconnect = AsyncMock()
                            mock_client.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                            # Verify connection loop was started as a task
                            assert daemon._heartbeat_task is not None
                            # Verify run_with_reconnect was called with correct args
                            mock_client_instance.run_with_reconnect.assert_called_once()
                            call_kwargs = mock_client_instance.run_with_reconnect.call_args.kwargs
                            assert call_kwargs["heartbeat_interval"] == 30
                            assert "on_connect" in call_kwargs
                            assert "on_disconnect" in call_kwargs


class TestConfigChangeHandling:
    """Tests for handling webapp config changes."""

    @pytest.mark.asyncio
    async def test_initialize_sets_on_config_change_callback(self, tmp_path):
        """initialize() sets up the config change callback on WebSocket server."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml

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
                        mock_ws_instance.on_config_change = None  # Start with None
                        mock_ws.return_value = mock_ws_instance
                        with patch("amphigory_daemon.main.WebAppClient") as mock_client:
                            mock_client_instance = MagicMock()
                            mock_client_instance.run_with_reconnect = AsyncMock()
                            mock_client.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                        # Verify on_config_change callback was set to a callable
                        assert mock_ws_instance.on_config_change is not None
                        assert callable(mock_ws_instance.on_config_change)

    @pytest.mark.asyncio
    async def test_on_config_change_refetches_config(self, tmp_path):
        """Config change callback refetches config from webapp."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml

        config_file = tmp_path / "daemon.yaml"
        config_file.write_text(yaml.dump({
            "webapp_url": "http://localhost:6199",
            "webapp_basedir": str(tmp_path),
        }))
        cache_file = tmp_path / "cached_config.json"

        daemon = AmphigoryDaemon()
        original_config = WebappConfig(
            tasks_directory="/tasks",
            websocket_port=8765,
            wiki_url="http://localhost/wiki",
            heartbeat_interval=30,
            log_level="INFO",
            makemkv_path=None,
        )

        with patch("amphigory_daemon.main.get_config", new_callable=AsyncMock) as mock_get_config:
            mock_get_config.return_value = (
                DaemonConfig(
                    webapp_url="http://localhost:6199",
                    webapp_basedir=str(tmp_path),
                ),
                original_config,
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
                        mock_ws_instance.on_config_change = None
                        mock_ws.return_value = mock_ws_instance
                        with patch("amphigory_daemon.main.WebAppClient") as mock_client:
                            mock_client_instance = MagicMock()
                            mock_client_instance.run_with_reconnect = AsyncMock()
                            mock_client.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                        # Get the callback that was set
                        callback = mock_ws_instance.on_config_change

        # Set up mock for fetch_webapp_config and call the callback
        with patch("amphigory_daemon.main.fetch_webapp_config", new_callable=AsyncMock) as mock_fetch:
            updated_config = WebappConfig(
                tasks_directory="/tasks",
                websocket_port=8765,
                wiki_url="http://localhost/wiki",
                heartbeat_interval=60,  # Changed!
                log_level="DEBUG",  # Changed!
                makemkv_path=None,
            )
            mock_fetch.return_value = updated_config

            # Call the callback (it's async)
            await callback()

            # Verify fetch was called with the webapp URL
            mock_fetch.assert_called_once_with("http://localhost:6199")

            # Verify config was updated
            assert daemon.webapp_config.heartbeat_interval == 60
            assert daemon.webapp_config.log_level == "DEBUG"


class TestStorageHandling:
    """Tests for storage unavailable handling."""

    def test_is_storage_available_returns_true_when_accessible(self, tmp_path):
        """is_storage_available returns True when storage dir exists."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        assert daemon.is_storage_available() is True

    def test_is_storage_available_returns_false_when_missing(self):
        """is_storage_available returns False when storage dir doesn't exist."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = "/nonexistent/path/that/does/not/exist"

        assert daemon.is_storage_available() is False

    def test_is_storage_available_returns_false_when_config_missing(self):
        """is_storage_available returns False when daemon_config is None."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = None

        assert daemon.is_storage_available() is False


class TestDiscEjectHandler:
    """Tests for disc ejection handler with path-based callback."""

    def test_on_disc_eject_clears_state(self):
        """on_disc_eject clears disc state when called with volume path."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.icons import ActivityState

        daemon = AmphigoryDaemon()
        daemon.current_disc = ("/dev/rdisk5", "TEST_DISC")
        daemon.activity_state = ActivityState.IDLE_DISC

        daemon.on_disc_eject("/Volumes/TEST_DISC")

        assert daemon.current_disc is None
        assert daemon.activity_state == ActivityState.IDLE_EMPTY


class TestOpticalDriveIntegration:
    """Tests for OpticalDrive integration in daemon."""

    @pytest.mark.asyncio
    async def test_daemon_creates_optical_drive(self):
        """Daemon creates OpticalDrive on initialize."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        # Mock the config setup
        daemon.daemon_config = type('obj', (object,), {
            'daemon_id': 'test@host',
            'webapp_url': 'http://localhost:8000',
            'webapp_basedir': '/tmp/test',
            'makemkvcon_path': '/usr/bin/makemkvcon',
        })()

        # Create optical drive manually (normally done in initialize)
        daemon.optical_drive = OpticalDrive(
            daemon_id=daemon.daemon_config.daemon_id,
            device="/dev/rdisk4",
        )

        assert daemon.optical_drive is not None
        assert daemon.optical_drive.daemon_id == 'test@host'
        assert daemon.optical_drive.state.value == 'empty'

    @pytest.mark.asyncio
    async def test_disc_insert_updates_optical_drive(self, tmp_path):
        """on_disc_insert updates OpticalDrive model."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive, DriveState

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk0",
        )

        # Create mock DVD structure for fingerprinting
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"mock ifo")

        # Simulate disc insert
        daemon.on_disc_insert("/dev/rdisk4", "MY_MOVIE", str(tmp_path))

        assert daemon.optical_drive.state == DriveState.DISC_INSERTED
        assert daemon.optical_drive.disc_volume == "MY_MOVIE"
        assert daemon.optical_drive.device == "/dev/rdisk4"

    @pytest.mark.asyncio
    async def test_disc_eject_updates_optical_drive(self):
        """on_disc_eject updates OpticalDrive model."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive, DriveState

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk4",
        )
        daemon.optical_drive.insert_disc(volume="MY_MOVIE", disc_type="dvd")

        # Simulate disc eject
        daemon.on_disc_eject("/Volumes/MY_MOVIE")

        assert daemon.optical_drive.state == DriveState.EMPTY
        assert daemon.optical_drive.disc_volume is None

    def test_detect_disc_type_dvd_via_drutil(self):
        """_detect_disc_type returns 'dvd' when drutil reports DVD-ROM."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        drutil_output = """
 Vendor   Product           Rev
 HL-DT-ST BD-RE BU40N       1.02

           Type: DVD-ROM              Name: /dev/disk8
       Sessions: 1                  Tracks: 1
"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_output, stderr="")
            result = daemon._detect_disc_type()

        assert result == "dvd"

    def test_detect_disc_type_bluray_via_drutil(self):
        """_detect_disc_type returns 'bluray' when drutil reports BD-ROM."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        drutil_output = """
 Vendor   Product           Rev
 HL-DT-ST BD-RE BU40N       1.02

           Type: BD-ROM               Name: /dev/disk8
       Sessions: 1                  Tracks: 1
"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_output, stderr="")
            result = daemon._detect_disc_type()

        assert result == "bluray"

    def test_detect_disc_type_cd_via_drutil(self):
        """_detect_disc_type returns 'cd' when drutil reports CD-ROM."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        drutil_output = """
 Vendor   Product           Rev
 HL-DT-ST BD-RE BU40N       1.02

           Type: CD-ROM               Name: /dev/disk8
       Sessions: 1                  Tracks: 1
"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_output, stderr="")
            result = daemon._detect_disc_type()

        assert result == "cd"

    def test_detect_disc_type_unknown_defaults_to_cd(self):
        """_detect_disc_type returns 'cd' for unknown disc types."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        drutil_output = """
 Vendor   Product           Rev
 HL-DT-ST BD-RE BU40N       1.02

           Type: Unknown              Name: /dev/disk8
"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=drutil_output, stderr="")
            result = daemon._detect_disc_type()

        assert result == "cd"

    def test_detect_disc_type_handles_drutil_failure(self):
        """_detect_disc_type returns 'cd' if drutil fails."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = daemon._detect_disc_type()

        assert result == "cd"


class TestWakeDisc:
    """Tests for _wake_disc method (active spin-up via makemkvcon)."""

    def test_wake_disc_runs_makemkvcon_info(self):
        """_wake_disc runs makemkvcon info disc:9999 command to wake drive."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.config import DaemonConfig

        daemon = AmphigoryDaemon()
        daemon.daemon_config = DaemonConfig(
            webapp_url="http://localhost:6199",
            webapp_basedir="/tmp",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )

        with patch("subprocess.run") as mock_run:
            # Simulate output with the device listed
            mock_run.return_value = MagicMock(
                returncode=1,  # "Fails" because disc:9999 doesn't exist
                stdout='DRV:0,2,999,1,"BD-RE","DISC","/dev/rdisk8"',
                stderr=""
            )

            result = daemon._wake_disc("/dev/rdisk8")

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "/usr/local/bin/makemkvcon" in call_args
            assert "--cache=1" in call_args
            assert "info" in call_args
            assert "disc:9999" in call_args
            assert result is True

    def test_wake_disc_returns_false_without_config(self):
        """_wake_disc returns False if no config (no makemkvcon path)."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = None

        result = daemon._wake_disc("/dev/rdisk8")

        assert result is False

    def test_wake_disc_succeeds_even_with_nonzero_returncode(self):
        """_wake_disc returns True even when disc:9999 'fails' (expected)."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.config import DaemonConfig

        daemon = AmphigoryDaemon()
        daemon.daemon_config = DaemonConfig(
            webapp_url="http://localhost:6199",
            webapp_basedir="/tmp",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )

        with patch("subprocess.run") as mock_run:
            # disc:9999 returns non-zero but still wakes the drive
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="DRV:0,256,999,0,\"\",\"\",\"\"",  # Empty drive listing
                stderr="Failed to open disc"
            )

            result = daemon._wake_disc("/dev/rdisk8")

            # Still succeeds - drive was queried and woke up
            assert result is True

    def test_wake_disc_handles_timeout(self):
        """_wake_disc returns False on timeout."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.config import DaemonConfig
        import subprocess

        daemon = AmphigoryDaemon()
        daemon.daemon_config = DaemonConfig(
            webapp_url="http://localhost:6199",
            webapp_basedir="/tmp",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="makemkvcon", timeout=30)

            result = daemon._wake_disc("/dev/rdisk8")

            assert result is False

    def test_on_disc_insert_wakes_disc_before_detecting_type(self, tmp_path):
        """on_disc_insert calls _wake_disc before _detect_disc_type."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive
        from amphigory_daemon.config import DaemonConfig

        daemon = AmphigoryDaemon()
        daemon.daemon_config = DaemonConfig(
            webapp_url="http://localhost:6199",
            webapp_basedir="/tmp",
            makemkvcon_path="/usr/local/bin/makemkvcon",
        )
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk0",
        )

        # Create DVD structure for fingerprinting
        (tmp_path / "VIDEO_TS").mkdir()
        (tmp_path / "VIDEO_TS" / "VIDEO_TS.IFO").write_bytes(b"mock ifo")

        call_order = []

        def mock_wake(device):
            call_order.append("wake")
            return True

        def mock_detect():
            call_order.append("detect")
            return "dvd"

        daemon._wake_disc = mock_wake
        daemon._detect_disc_type = mock_detect

        daemon.on_disc_insert("/dev/rdisk8", "TEST_DISC", str(tmp_path))

        # Wake should be called before detect
        assert call_order == ["wake", "detect"]


class TestFingerprintOnInsert:
    """Tests for fingerprint generation during disc insertion."""

    def test_fingerprint_generated_on_disc_insert(self, tmp_path):
        """on_disc_insert generates fingerprint when volume_path has DVD structure."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk0",
        )

        # Create mock DVD structure for fingerprinting
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"mock ifo data")

        # Simulate disc insert with volume_path
        daemon.on_disc_insert("/dev/rdisk4", "MY_MOVIE", str(tmp_path))

        # Assert fingerprint was generated and set
        assert daemon.optical_drive.fingerprint is not None
        assert len(daemon.optical_drive.fingerprint) > 0

    @pytest.mark.asyncio
    async def test_websocket_request_handler_registered(self, tmp_path):
        """After initialization, get_drive_status handler is registered with webapp_client."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.models import DaemonConfig, WebappConfig
        from amphigory_daemon.config import ConfigValidationResult
        import yaml

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
                        with patch("amphigory_daemon.main.WebAppClient") as mock_client_class:
                            mock_client_instance = MagicMock()
                            mock_client_instance.run_with_reconnect = AsyncMock()
                            mock_client_instance.on_request = MagicMock()
                            mock_client_class.return_value = mock_client_instance
                            with patch("amphigory_daemon.main.DiscDetector") as mock_disc:
                                mock_disc_instance = MagicMock()
                                mock_disc_instance.get_current_disc.return_value = None
                                mock_disc.return_value = mock_disc_instance
                                with patch("amphigory_daemon.main.TaskQueue"):
                                    await daemon.initialize(config_file, cache_file)

                        # Verify on_request was called with get_drive_status
                        mock_client_instance.on_request.assert_called_once()
                        call_args = mock_client_instance.on_request.call_args
                        assert call_args[0][0] == "get_drive_status"
                        # Verify a handler was provided
                        assert callable(call_args[0][1])

    @pytest.mark.asyncio
    async def test_handle_get_drive_status_returns_drive_dict(self):
        """_handle_get_drive_status returns the drive's to_dict() output."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk4",
        )

        # Call handler
        result = await daemon._handle_get_drive_status({})

        # Verify it returns the drive's dict representation
        assert isinstance(result, dict)
        assert result["daemon_id"] == "test@host"
        assert result["device"] == "/dev/rdisk4"
        assert "state" in result

    @pytest.mark.asyncio
    async def test_webapp_client_send_disc_event_on_insert(self, tmp_path):
        """webapp_client.send_disc_event is called when disc is inserted."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk0",
        )

        # Mock webapp_client
        mock_webapp_client = MagicMock()
        mock_webapp_client.is_connected.return_value = True
        mock_webapp_client.send_disc_event = AsyncMock()
        mock_webapp_client.send_fingerprint_event = AsyncMock()
        daemon.webapp_client = mock_webapp_client

        # Create mock DVD structure
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"mock ifo")

        # Simulate disc insert
        daemon.on_disc_insert("/dev/rdisk4", "TEST_DISC", str(tmp_path))

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify send_disc_event was called with correct args
        mock_webapp_client.send_disc_event.assert_called_once_with(
            "inserted", "/dev/rdisk4", "TEST_DISC"
        )

        # Verify send_fingerprint_event was also called
        mock_webapp_client.send_fingerprint_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_server_send_disc_event_on_insert(self, tmp_path):
        """ws_server.send_disc_event is called when disc is inserted."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk0",
        )

        # Mock ws_server
        mock_ws_server = MagicMock()
        mock_ws_server.send_disc_event = AsyncMock()
        mock_ws_server.send_fingerprint_event = AsyncMock()
        daemon.ws_server = mock_ws_server

        # Create mock DVD structure
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"mock ifo")

        # Simulate disc insert
        daemon.on_disc_insert("/dev/rdisk4", "TEST_DISC", str(tmp_path))

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify send_disc_event was called
        mock_ws_server.send_disc_event.assert_called_once_with(
            "inserted", "/dev/rdisk4", "TEST_DISC"
        )

        # Verify send_fingerprint_event was also called
        mock_ws_server.send_fingerprint_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_webapp_client_send_disc_event_on_eject(self):
        """webapp_client.send_disc_event is called when disc is ejected."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk4",
        )
        daemon.optical_drive.insert_disc(volume="TEST_DISC", disc_type="dvd")

        # Mock webapp_client
        mock_webapp_client = MagicMock()
        mock_webapp_client.is_connected.return_value = True
        mock_webapp_client.send_disc_event = AsyncMock()
        daemon.webapp_client = mock_webapp_client

        # Simulate disc eject
        daemon.on_disc_eject("/Volumes/TEST_DISC")

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify send_disc_event was called
        mock_webapp_client.send_disc_event.assert_called_once()
        call_args = mock_webapp_client.send_disc_event.call_args
        assert call_args[0][0] == "ejected"
        assert call_args[1]["volume_path"] == "/Volumes/TEST_DISC"

    @pytest.mark.asyncio
    async def test_ws_server_send_disc_event_on_eject(self):
        """ws_server.send_disc_event is called when disc is ejected."""
        from amphigory_daemon.main import AmphigoryDaemon
        from amphigory_daemon.drive import OpticalDrive

        daemon = AmphigoryDaemon()
        daemon.optical_drive = OpticalDrive(
            daemon_id='test@host',
            device="/dev/rdisk4",
        )
        daemon.optical_drive.insert_disc(volume="TEST_DISC", disc_type="dvd")

        # Mock ws_server
        mock_ws_server = MagicMock()
        mock_ws_server.send_disc_event = AsyncMock()
        daemon.ws_server = mock_ws_server

        # Simulate disc eject
        daemon.on_disc_eject("/Volumes/TEST_DISC")

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify send_disc_event was called
        mock_ws_server.send_disc_event.assert_called_once()
        call_args = mock_ws_server.send_disc_event.call_args
        assert call_args[0][0] == "ejected"
        assert call_args[1]["volume_path"] == "/Volumes/TEST_DISC"


class TestFilesystemPauseMarker:
    """Tests for filesystem-based pause marker (Task 4)."""

    def test_is_queue_paused_returns_true_when_paused_file_exists(self, tmp_path):
        """is_queue_paused returns True when PAUSED file exists in tasks dir."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create the tasks directory and PAUSED file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "PAUSED").touch()

        result = daemon.is_queue_paused()

        assert result is True

    def test_is_queue_paused_returns_false_when_no_paused_file(self, tmp_path):
        """is_queue_paused returns False when PAUSED file does not exist."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create the tasks directory but NO PAUSED file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        result = daemon.is_queue_paused()

        assert result is False

    def test_is_queue_paused_returns_false_when_no_config(self):
        """is_queue_paused returns False when daemon_config is None."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = None

        result = daemon.is_queue_paused()

        assert result is False

    @pytest.mark.asyncio
    async def test_task_loop_skips_when_paused_file_exists(self, tmp_path):
        """run_task_loop skips task processing when PAUSED file exists."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create the tasks directory and PAUSED file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "PAUSED").touch()

        # Mock task_queue to track whether get_next_task is called
        mock_task_queue = MagicMock()
        mock_task_queue.get_next_task = MagicMock(return_value=None)
        daemon.task_queue = mock_task_queue

        # Run one iteration of the loop
        daemon._running = True

        async def stop_after_one():
            await asyncio.sleep(0.1)
            daemon._running = False

        # Run task loop with a timeout
        await asyncio.gather(
            daemon.run_task_loop(),
            stop_after_one(),
        )

        # get_next_task should NOT be called because we're paused
        mock_task_queue.get_next_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_loop_processes_when_no_paused_file(self, tmp_path):
        """run_task_loop processes tasks when PAUSED file does not exist."""
        from amphigory_daemon.main import AmphigoryDaemon

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create the tasks directory but NO PAUSED file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Mock task_queue
        mock_task_queue = MagicMock()
        mock_task_queue.get_next_task = MagicMock(return_value=None)
        daemon.task_queue = mock_task_queue

        # Run one iteration of the loop
        daemon._running = True

        async def stop_after_one():
            await asyncio.sleep(0.1)
            daemon._running = False

        # Run task loop with a timeout
        await asyncio.gather(
            daemon.run_task_loop(),
            stop_after_one(),
        )

        # get_next_task SHOULD be called because we're not paused
        mock_task_queue.get_next_task.assert_called()

    def test_menu_pause_creates_paused_file(self, tmp_path):
        """toggle_pause creates PAUSED file when pausing."""
        from amphigory_daemon.main import AmphigoryDaemon, PauseMode

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create tasks directory
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Ensure not paused initially
        daemon.pause_mode = PauseMode.NONE

        # Create a mock menu item sender
        sender = MagicMock()
        sender.title = "Pause After Track"

        # Toggle pause (this should set AFTER_TRACK mode)
        daemon.toggle_pause(sender)

        # PAUSED file should NOT exist yet (AFTER_TRACK doesn't immediately pause)
        assert not (tasks_dir / "PAUSED").exists()

        # Use pause_now to create immediate pause
        daemon.pause_now(sender)

        # NOW PAUSED file should exist
        assert (tasks_dir / "PAUSED").exists()

    def test_menu_resume_removes_paused_file(self, tmp_path):
        """toggle_pause removes PAUSED file when resuming."""
        from amphigory_daemon.main import AmphigoryDaemon, PauseMode

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create tasks directory and PAUSED file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "PAUSED").touch()

        # Set paused state (AFTER_TRACK acts as "paused" for resume)
        daemon.pause_mode = PauseMode.AFTER_TRACK

        # Create a mock menu item sender
        sender = MagicMock()
        sender.title = "Resume"

        # Toggle pause (should resume since we're already in AFTER_TRACK mode)
        daemon.toggle_pause(sender)

        # PAUSED file should be removed
        assert not (tasks_dir / "PAUSED").exists()
        assert daemon.pause_mode == PauseMode.NONE

    def test_pause_now_creates_paused_file(self, tmp_path):
        """pause_now creates PAUSED file for immediate pause."""
        from amphigory_daemon.main import AmphigoryDaemon, PauseMode

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create tasks directory
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Ensure not paused initially
        daemon.pause_mode = PauseMode.NONE

        # Create a mock menu item sender
        sender = MagicMock()

        # Pause now
        daemon.pause_now(sender)

        # PAUSED file should exist
        assert (tasks_dir / "PAUSED").exists()
        assert daemon.pause_mode == PauseMode.IMMEDIATE

    @pytest.mark.asyncio
    async def test_after_track_creates_paused_file_when_task_completes(self, tmp_path):
        """AFTER_TRACK mode creates PAUSED file after a task completes."""
        from amphigory_daemon.main import AmphigoryDaemon, PauseMode
        from amphigory_daemon.models import ScanTask, ScanResult

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create tasks directory
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Set AFTER_TRACK mode
        daemon.pause_mode = PauseMode.AFTER_TRACK

        # Mock task_queue to return one task then None
        from datetime import datetime
        task = ScanTask(id="test-task", type="scan", created_at=datetime.now())
        mock_task_queue = MagicMock()
        mock_task_queue.get_next_task = MagicMock(side_effect=[task, None])
        mock_task_queue.complete_task = MagicMock()
        daemon.task_queue = mock_task_queue

        # Mock scan handling
        mock_result = ScanResult(disc_name="TEST", disc_type="dvd", tracks=[])
        with patch.object(daemon, "_handle_scan_task", new_callable=AsyncMock) as mock_scan:
            from datetime import datetime
            from amphigory_daemon.models import TaskResponse, TaskStatus
            mock_scan.return_value = TaskResponse(
                task_id="test-task",
                status=TaskStatus.SUCCESS,
                started_at=datetime.now(),
                completed_at=datetime.now(),
                duration_seconds=5,
                result=mock_result,
            )

            # Run one iteration of the loop
            daemon._running = True

            async def stop_after_task():
                await asyncio.sleep(0.2)
                daemon._running = False

            # Run task loop with a timeout
            await asyncio.gather(
                daemon.run_task_loop(),
                stop_after_task(),
            )

        # After task completion with AFTER_TRACK, PAUSED file should be created
        assert (tasks_dir / "PAUSED").exists()
        # And mode should transition to IMMEDIATE
        assert daemon.pause_mode == PauseMode.IMMEDIATE

    def test_menu_reflects_filesystem_state_on_pause(self, tmp_path):
        """Menu item title is set correctly when pausing."""
        from amphigory_daemon.main import AmphigoryDaemon, PauseMode

        daemon = AmphigoryDaemon()
        daemon.daemon_config = MagicMock()
        daemon.daemon_config.webapp_basedir = str(tmp_path)

        # Create tasks directory
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Ensure not paused initially
        daemon.pause_mode = PauseMode.NONE

        # The pause_item menu item
        sender = daemon.pause_item

        # Toggle pause
        daemon.toggle_pause(sender)

        # Menu should show resume option (with play icon)
        assert sender.title == "▶ Resume"
