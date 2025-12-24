"""Main Amphigory daemon application - macOS menu bar app."""

import asyncio
import logging
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import rumps
import yaml

from .config import get_config, load_local_config, fetch_webapp_config, validate_config
from .dialogs import ConfigDialog
from .discovery import discover_makemkvcon
from .disc import DiscDetector
from .icons import ActivityState, StatusOverlay, get_icon_name
from .makemkv import (
    Progress,
    build_rip_command,
    build_scan_command,
    parse_progress_line,
    parse_scan_output,
)
from .models import (
    DaemonConfig,
    WebappConfig,
    ScanTask,
    RipTask,
    TaskResponse,
    TaskStatus,
    TaskError,
    ErrorCode,
    ScanResult,
    RipResult,
)
from .tasks import TaskQueue
from .websocket import WebSocketServer, WebAppClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default paths
CONFIG_DIR = Path.home() / ".config" / "amphigory"
LOCAL_CONFIG_FILE = CONFIG_DIR / "daemon.yaml"
CACHED_CONFIG_FILE = CONFIG_DIR / "cached_config.json"

# Default values for auto-configuration
DEFAULT_WEBAPP_URL = "http://localhost:6199"
DEFAULT_WEBAPP_BASEDIR = "/opt/amphigory"
WIKI_DOC_ROOT_URL = "https://gollum/amphigory"


def generate_daemon_id() -> str:
    """
    Generate a unique daemon ID based on username and hostname.

    Format: username@hostname (e.g., purp@beehive)
    Adds :dev suffix when running from an interactive terminal (TTY),
    which indicates a development/debugging session.

    Returns:
        Daemon ID string
    """
    import os
    import socket
    import sys

    username = os.environ.get("USER", "unknown")
    # Use short hostname (before first dot)
    hostname = socket.gethostname().split(".")[0]
    base_id = f"{username}@{hostname}"

    # Add :dev suffix for interactive terminal sessions
    if sys.stdin.isatty():
        return f"{base_id}:dev"
    return base_id


class PauseMode(Enum):
    """Pause mode for the daemon."""
    NONE = auto()
    AFTER_TRACK = auto()
    IMMEDIATE = auto()


@dataclass
class ScanCache:
    """Cached scan result."""
    device: str
    result: ScanResult
    scanned_at: datetime


class AmphigoryDaemon(rumps.App):
    """
    Amphigory menu bar daemon application.

    Handles:
    - Disc detection and proactive scanning
    - Task queue processing (rip tasks)
    - WebSocket communication with webapp
    - Menu bar UI
    """

    def __init__(self):
        super().__init__("Amphigory", quit_button=None)

        # Configuration
        self.daemon_config: Optional[DaemonConfig] = None
        self.webapp_config: Optional[WebappConfig] = None
        self.makemkv_path: Optional[Path] = None

        # Components
        self.task_queue: Optional[TaskQueue] = None
        self.ws_server: Optional[WebSocketServer] = None
        self.webapp_client: Optional[WebAppClient] = None
        self.disc_detector: Optional[DiscDetector] = None

        # State
        self.current_task: Optional[ScanTask | RipTask] = None
        self.current_progress: int = 0
        self.pause_mode = PauseMode.NONE
        self.scan_cache: Optional[ScanCache] = None
        self.current_disc: Optional[tuple[str, str]] = None  # (device, volume)
        self._running = False
        self._task_loop: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Activity state
        self.activity_state = ActivityState.IDLE_EMPTY
        self.status_overlays: set[StatusOverlay] = set()

        # Cold-start mode
        self.cold_start_mode = False
        self.found_url: Optional[str] = None
        self.found_directory: Optional[str] = None

        # Build menu
        self._build_menu()

    def _build_menu(self) -> None:
        """Build the menu bar dropdown."""
        self.disc_item = rumps.MenuItem("No disc inserted")
        self.disc_item.set_callback(None)

        self.progress_item = rumps.MenuItem("")
        self.progress_item.set_callback(None)

        self.queue_item = rumps.MenuItem("")
        self.queue_item.set_callback(None)

        self.pause_item = rumps.MenuItem("Pause After Track")
        self.pause_now_item = rumps.MenuItem("Pause Now")

        # Store all menu items as instance variables for cold-start mode
        self.open_webapp_item = rumps.MenuItem("Open Webapp...", callback=self.open_webapp)
        self.help_item = rumps.MenuItem("Help & Documentation...", callback=self.open_help)
        self.restart_item = rumps.MenuItem("Restart Daemon", callback=self.restart_daemon)
        self.settings_item = rumps.MenuItem("Settings...", callback=self.open_settings)
        self.quit_item = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [
            self.disc_item,
            None,  # separator
            self.progress_item,
            self.queue_item,
            None,
            self.open_webapp_item,
            self.help_item,
            None,
            self.pause_item,
            self.pause_now_item,
            self.restart_item,
            self.settings_item,
            self.quit_item,
        ]

    @rumps.clicked("Pause After Track")
    def toggle_pause(self, sender):
        """Toggle pause after current track."""
        if self.pause_mode == PauseMode.AFTER_TRACK:
            self.pause_mode = PauseMode.NONE
            sender.title = "Pause After Track"
        else:
            self.pause_mode = PauseMode.AFTER_TRACK
            sender.title = "▶ Resume"
        self._update_overlays()

    @rumps.clicked("Pause Now")
    def pause_now(self, sender):
        """Pause immediately after current operation."""
        self.pause_mode = PauseMode.IMMEDIATE
        self._update_overlays()

    def open_webapp(self, _):
        """Open webapp in browser."""
        if self.cold_start_mode:
            self.show_config_dialog()
        elif self.daemon_config:
            webbrowser.open(self.daemon_config.webapp_url)

    def open_help(self, _):
        """Open help documentation."""
        if self.webapp_config:
            webbrowser.open(self.webapp_config.wiki_url)

    def open_settings(self, _):
        """Open settings in webapp."""
        if self.cold_start_mode:
            self.show_config_dialog()
        elif self.daemon_config:
            webbrowser.open(f"{self.daemon_config.webapp_url}/settings")

    def restart_daemon(self, _):
        """Restart the daemon."""
        logger.info("Restart requested")
        # In a real implementation, this would restart the process
        rumps.notification(
            "Amphigory",
            "Restart",
            "Daemon restart requested. Please restart manually.",
        )

    def quit_app(self, _):
        """Quit the application."""
        logger.info("Quit requested")
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.ws_server:
            asyncio.create_task(self.ws_server.stop())
        if self.disc_detector:
            self.disc_detector.stop()
        rumps.quit_application()

    async def _handle_config_change(self) -> None:
        """Handle webapp config change notification."""
        if not self.daemon_config:
            return

        try:
            new_config = await fetch_webapp_config(self.daemon_config.webapp_url)
            self.webapp_config = new_config
            logger.info("Webapp config refreshed")
        except ConnectionError as e:
            logger.warning(f"Failed to refresh webapp config: {e}")

    def is_storage_available(self) -> bool:
        """
        Check if webapp storage is available.

        Returns:
            True if storage directory exists and is accessible
        """
        if not self.daemon_config:
            return False
        return Path(self.daemon_config.webapp_basedir).exists()

    def _update_icon(self) -> None:
        """Update the menu bar icon based on current state."""
        icon_name = get_icon_name(self.activity_state, self.status_overlays or None)
        # In a real implementation, this would set the actual icon
        # self.icon = get_icon_path(...)
        logger.debug(f"Icon updated to: {icon_name}")

    def _update_overlays(self) -> None:
        """Update status overlays based on current state."""
        self.status_overlays.clear()

        if self.pause_mode != PauseMode.NONE:
            self.status_overlays.add(StatusOverlay.PAUSED)

        if self.ws_server and not self.ws_server.has_clients():
            self.status_overlays.add(StatusOverlay.DISCONNECTED)

        # Also show disconnected if storage is unavailable
        if not self.is_storage_available():
            self.status_overlays.add(StatusOverlay.DISCONNECTED)

        self._update_icon()

    def _update_disc_menu(self) -> None:
        """Update disc item in menu."""
        if self.current_disc:
            device, volume = self.current_disc
            self.disc_item.title = f"Disc: {volume}"
        else:
            self.disc_item.title = "No disc inserted"

    def _update_progress_menu(self) -> None:
        """Update progress items in menu."""
        if self.current_task:
            task_type = "Scanning" if isinstance(self.current_task, ScanTask) else "Ripping"
            self.progress_item.title = f"{task_type}: {self.current_progress}%"
        else:
            self.progress_item.title = ""

    def is_configured(self, config_file: Path) -> bool:
        """
        Check if the daemon has a configuration file.

        Args:
            config_file: Path to daemon.yaml

        Returns:
            True if config file exists
        """
        return config_file.exists()

    def enter_cold_start_mode(self) -> None:
        """
        Enter cold-start mode when configuration is missing.

        Sets NEEDS_CONFIG overlay and disables most menu items.
        """
        self.cold_start_mode = True
        self.status_overlays.add(StatusOverlay.NEEDS_CONFIG)
        self._update_icon()

        # Disable menu items except Settings, Open Webapp, Quit
        self.disc_item.set_callback(None)
        self.progress_item.set_callback(None)
        self.pause_item.set_callback(None)
        self.pause_now_item.set_callback(None)
        self.help_item.set_callback(None)
        self.restart_item.set_callback(None)

    def exit_cold_start_mode(self) -> None:
        """
        Exit cold-start mode after configuration is complete.

        Removes NEEDS_CONFIG overlay and re-enables menu items.
        """
        self.cold_start_mode = False
        self.status_overlays.discard(StatusOverlay.NEEDS_CONFIG)
        self._update_icon()

        # Re-enable menu items
        self.pause_item.set_callback(self.toggle_pause)
        self.pause_now_item.set_callback(self.pause_now)
        self.help_item.set_callback(self.open_help)
        self.restart_item.set_callback(self.restart_daemon)

    async def check_default_url(self) -> Optional[str]:
        """
        Check if the default webapp URL is reachable.

        Returns:
            The URL if reachable, None otherwise
        """
        try:
            await fetch_webapp_config(DEFAULT_WEBAPP_URL)
            logger.info(f"Default webapp URL is reachable: {DEFAULT_WEBAPP_URL}")
            return DEFAULT_WEBAPP_URL
        except ConnectionError:
            logger.info(f"Default webapp URL not reachable: {DEFAULT_WEBAPP_URL}")
            return None

    def check_default_directory(self) -> Optional[str]:
        """
        Check if the default webapp directory exists.

        Returns:
            The path if it exists, None otherwise
        """
        if Path(DEFAULT_WEBAPP_BASEDIR).exists():
            logger.info(f"Default directory exists: {DEFAULT_WEBAPP_BASEDIR}")
            return DEFAULT_WEBAPP_BASEDIR
        logger.info(f"Default directory not found: {DEFAULT_WEBAPP_BASEDIR}")
        return None

    async def try_default_config(self, config_file: Path) -> bool:
        """
        Try to auto-configure using default values.

        Checks default URL and directory independently, storing any found values.
        If both are found, writes configuration to config_file.

        Args:
            config_file: Path to write daemon.yaml

        Returns:
            True if full auto-configuration succeeded (both URL and directory found)
        """
        # Check each default independently
        self.found_url = await self.check_default_url()
        self.found_directory = self.check_default_directory()

        # If both found, save config
        if self.found_url and self.found_directory:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w") as f:
                yaml.dump({
                    "webapp_url": self.found_url,
                    "webapp_basedir": self.found_directory,
                }, f)
            logger.info(f"Auto-configured: {self.found_url}, {self.found_directory}")
            return True

        logger.info(f"Partial auto-config: url={self.found_url}, dir={self.found_directory}")
        return False

    def show_config_dialog(self) -> None:
        """
        Show configuration dialog for cold-start mode.

        Displays a dialog with fields for URL and directory.
        Pre-fills any values found during auto-configuration.
        """
        dialog = ConfigDialog(
            initial_url=self.found_url or "",
            initial_directory=self.found_directory or "",
            wiki_url=f"{WIKI_DOC_ROOT_URL}/Daemon",
        )

        result = dialog.run()
        logger.info("Configuration dialog shown")

        if not result.cancelled:
            webapp_url = result.url.strip() if result.url else ""
            webapp_dir = result.directory.strip() if result.directory else DEFAULT_WEBAPP_BASEDIR

            if webapp_url:
                # Save configuration
                LOCAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(LOCAL_CONFIG_FILE, "w") as f:
                    yaml.dump({
                        "webapp_url": webapp_url,
                        "webapp_basedir": webapp_dir,
                    }, f)
                logger.info(f"Configuration saved: {webapp_url}, {webapp_dir}")

                rumps.notification(
                    "Amphigory",
                    "Configuration Saved",
                    "Please restart the daemon to apply changes.",
                )

    def on_disc_insert(self, device: str, volume_name: str) -> None:
        """Handle disc insertion."""
        logger.info(f"Disc inserted: {volume_name} at {device}")
        self.current_disc = (device, volume_name)
        self.activity_state = ActivityState.IDLE_DISC
        self._update_disc_menu()
        self._update_icon()

        # Send WebSocket event to webapp (Docker container)
        if self.webapp_client and self.webapp_client.is_connected():
            asyncio.create_task(
                self.webapp_client.send_disc_event("inserted", device, volume_name)
            )

        # Also send to local browser clients (if any connected to daemon directly)
        if self.ws_server:
            asyncio.create_task(
                self.ws_server.send_disc_event("inserted", device, volume_name)
            )

        # Start proactive scan
        asyncio.create_task(self._proactive_scan(device))

    def on_disc_eject(self, device: str) -> None:
        """Handle disc ejection."""
        logger.info(f"Disc ejected from {device}")
        self.current_disc = None
        self.scan_cache = None
        self.activity_state = ActivityState.IDLE_EMPTY
        self._update_disc_menu()
        self._update_icon()

        # Send WebSocket event to webapp (Docker container)
        if self.webapp_client and self.webapp_client.is_connected():
            asyncio.create_task(
                self.webapp_client.send_disc_event("ejected", device)
            )

        # Also send to local browser clients (if any connected to daemon directly)
        if self.ws_server:
            asyncio.create_task(
                self.ws_server.send_disc_event("ejected", device)
            )

    async def _proactive_scan(self, device: str) -> None:
        """Run proactive scan in background."""
        if not self.makemkv_path:
            return

        logger.info("Starting proactive scan")
        cmd = build_scan_command(self.makemkv_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            result = parse_scan_output(output)
            self.scan_cache = ScanCache(
                device=device,
                result=result,
                scanned_at=datetime.now(),
            )
            logger.info(f"Proactive scan complete: {len(result.tracks)} tracks")

        except Exception as e:
            logger.error(f"Proactive scan failed: {e}")

    async def initialize(
        self,
        config_file: Optional[Path] = None,
        cache_file: Optional[Path] = None,
    ) -> bool:
        """
        Initialize the daemon.

        Args:
            config_file: Path to daemon.yaml (defaults to LOCAL_CONFIG_FILE)
            cache_file: Path to cached_config.json (defaults to CACHED_CONFIG_FILE)

        Returns:
            True if initialization successful
        """
        if config_file is None:
            config_file = LOCAL_CONFIG_FILE
        if cache_file is None:
            cache_file = CACHED_CONFIG_FILE

        try:
            # Check if we have a config file
            if not self.is_configured(config_file):
                logger.info("No configuration found, trying auto-configuration...")
                if not await self.try_default_config(config_file):
                    logger.info("Auto-configuration failed, entering cold-start mode")
                    self.enter_cold_start_mode()
                    return False

            # Load configuration
            self.daemon_config, self.webapp_config = await get_config(
                config_file, cache_file
            )
            logger.info(f"Configuration loaded from {self.daemon_config.webapp_url}")

            # Validate configuration
            validation = validate_config(self.daemon_config)
            if not validation.is_valid:
                if validation.makemkvcon_error:
                    logger.warning(f"Config validation: {validation.makemkvcon_error}")
                if validation.basedir_error:
                    logger.warning(f"Config validation: {validation.basedir_error}")

            # Generate daemon_id if not set
            if not self.daemon_config.daemon_id:
                self.daemon_config.daemon_id = generate_daemon_id()
                logger.info(f"Generated daemon_id: {self.daemon_config.daemon_id}")

            # Discover makemkvcon
            self.makemkv_path = discover_makemkvcon(
                self.webapp_config.makemkv_path
            )
            if not self.makemkv_path:
                logger.error("makemkvcon not found")
                rumps.notification(
                    "Amphigory",
                    "Error",
                    "makemkvcon not found. Please install MakeMKV.",
                )
                return False
            logger.info(f"makemkvcon found at {self.makemkv_path}")

            # Update daemon_config with discovered makemkvcon path
            self.daemon_config.makemkvcon_path = str(self.makemkv_path)
            self.daemon_config.updated_at = datetime.now()

            # Save updated config locally
            from .config import save_local_config
            save_local_config(self.daemon_config, config_file)
            logger.info("Saved daemon configuration")

            # Initialize task queue
            tasks_dir = Path(self.daemon_config.webapp_basedir) / self.webapp_config.tasks_directory.lstrip("/")
            self.task_queue = TaskQueue(tasks_dir)
            self.task_queue.ensure_directories()
            self.task_queue.recover_crashed_tasks()
            logger.info(f"Task queue initialized at {tasks_dir}")

            # Initialize WebSocket server (for browser connections)
            self.ws_server = WebSocketServer(
                port=self.webapp_config.websocket_port,
                heartbeat_interval=self.webapp_config.heartbeat_interval,
            )
            self.ws_server.on_config_change = self._handle_config_change
            await self.ws_server.start()
            logger.info(f"WebSocket server started on port {self.webapp_config.websocket_port}")

            # Connect to webapp's WebSocket endpoint with auto-reconnect
            webapp_ws_url = f"{self.daemon_config.webapp_url.replace('http', 'ws')}/ws"
            self.webapp_client = WebAppClient(webapp_ws_url)

            def on_webapp_connect():
                self.status_overlays.discard(StatusOverlay.DISCONNECTED)
                self._update_icon()
                # Send current disc status if a disc is inserted
                if self.current_disc and self.webapp_client:
                    device, volume_name = self.current_disc
                    asyncio.create_task(
                        self.webapp_client.send_disc_event("inserted", device, volume_name)
                    )

            def on_webapp_disconnect():
                self.status_overlays.add(StatusOverlay.DISCONNECTED)
                self._update_icon()

            # Start reconnecting connection loop in background
            self._heartbeat_task = asyncio.create_task(
                self.webapp_client.run_with_reconnect(
                    heartbeat_interval=self.webapp_config.heartbeat_interval,
                    daemon_id=self.daemon_config.daemon_id,
                    makemkvcon_path=self.daemon_config.makemkvcon_path,
                    webapp_basedir=self.daemon_config.webapp_basedir,
                    on_connect=on_webapp_connect,
                    on_disconnect=on_webapp_disconnect,
                )
            )
            logger.info(f"Started webapp connection loop to {webapp_ws_url}")

            # Initialize disc detector
            self.disc_detector = DiscDetector(
                on_insert=self.on_disc_insert,
                on_eject=self.on_disc_eject,
            )
            self.disc_detector.start()

            # Check for currently inserted disc
            current = self.disc_detector.get_current_disc()
            if current:
                self.on_disc_insert(*current)

            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False

    async def run_task_loop(self) -> None:
        """Main task processing loop."""
        self._running = True

        while self._running:
            try:
                # Check pause mode
                if self.pause_mode == PauseMode.IMMEDIATE:
                    await asyncio.sleep(1)
                    continue

                # Get next task
                task = self.task_queue.get_next_task()
                if not task:
                    await asyncio.sleep(1)
                    continue

                # Process task
                self.current_task = task
                self.current_progress = 0
                self.activity_state = ActivityState.WORKING
                self._update_progress_menu()
                self._update_icon()

                if self.ws_server:
                    await self.ws_server.send_status(task.id, "started")

                if isinstance(task, ScanTask):
                    response = await self._handle_scan_task(task)
                else:
                    response = await self._handle_rip_task(task)

                # Complete task
                self.task_queue.complete_task(response)

                if self.ws_server:
                    await self.ws_server.send_status(task.id, "completed")

                self.current_task = None
                self.activity_state = (
                    ActivityState.IDLE_DISC if self.current_disc
                    else ActivityState.IDLE_EMPTY
                )
                self._update_progress_menu()
                self._update_icon()

                # Check for pause after track
                if self.pause_mode == PauseMode.AFTER_TRACK:
                    self.pause_mode = PauseMode.IMMEDIATE
                    self.pause_item.title = "▶ Resume"

            except Exception as e:
                logger.error(f"Task loop error: {e}")
                await asyncio.sleep(1)

    async def _handle_scan_task(self, task: ScanTask) -> TaskResponse:
        """Handle a scan task."""
        started_at = datetime.now()

        # Check cache
        if (
            self.scan_cache
            and self.current_disc
            and self.scan_cache.device == self.current_disc[0]
        ):
            logger.info("Using cached scan result")
            completed_at = datetime.now()
            return TaskResponse(
                task_id=task.id,
                status=TaskStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=int((completed_at - started_at).total_seconds()),
                result=self.scan_cache.result,
            )

        # Run fresh scan
        try:
            cmd = build_scan_command(self.makemkv_path)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            result = parse_scan_output(output)
            completed_at = datetime.now()

            return TaskResponse(
                task_id=task.id,
                status=TaskStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=int((completed_at - started_at).total_seconds()),
                result=result,
            )

        except Exception as e:
            completed_at = datetime.now()
            return TaskResponse(
                task_id=task.id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=int((completed_at - started_at).total_seconds()),
                error=TaskError(
                    code=ErrorCode.MAKEMKV_FAILED,
                    message="Scan failed",
                    detail=str(e),
                ),
            )

    async def _handle_rip_task(self, task: RipTask) -> TaskResponse:
        """Handle a rip task."""
        started_at = datetime.now()

        try:
            # Create output directory
            output_dir = Path(task.output.directory)
            output_dir.mkdir(parents=True, exist_ok=True)

            cmd = build_rip_command(
                self.makemkv_path,
                task.track.number,
                output_dir,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream progress
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace")
                progress = parse_progress_line(line_str)

                if progress:
                    self.current_progress = progress.percent
                    self._update_progress_menu()

                    if self.ws_server:
                        await self.ws_server.send_progress(
                            task_id=task.id,
                            percent=progress.percent,
                            eta_seconds=progress.eta_seconds,
                            current_size_bytes=progress.current_size_bytes,
                            speed=progress.speed,
                        )

            await proc.wait()

            if proc.returncode != 0:
                completed_at = datetime.now()
                return TaskResponse(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=int((completed_at - started_at).total_seconds()),
                    error=TaskError(
                        code=ErrorCode.MAKEMKV_FAILED,
                        message="Rip failed",
                        detail=f"Exit code: {proc.returncode}",
                    ),
                )

            output_path = output_dir / task.output.filename
            completed_at = datetime.now()

            return TaskResponse(
                task_id=task.id,
                status=TaskStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=int((completed_at - started_at).total_seconds()),
                result=RipResult(
                    output_path=str(output_path),
                    size_bytes=output_path.stat().st_size if output_path.exists() else 0,
                ),
            )

        except Exception as e:
            completed_at = datetime.now()
            return TaskResponse(
                task_id=task.id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=int((completed_at - started_at).total_seconds()),
                error=TaskError(
                    code=ErrorCode.UNKNOWN,
                    message="Unexpected error",
                    detail=str(e),
                ),
            )


def main():
    """Main entry point."""
    app = AmphigoryDaemon()

    # Run initialization and task loop in background
    async def async_main():
        if await app.initialize():
            await app.run_task_loop()

    # Start async loop in background thread
    import threading

    def run_async():
        asyncio.run(async_main())

    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()

    # Run rumps app (blocks)
    app.run()


if __name__ == "__main__":
    main()
