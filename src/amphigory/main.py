"""FastAPI application entry point."""

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect


class QuietAccessFilter(logging.Filter):
    """Filter out noisy polling endpoints from access logs."""
    QUIET_PATHS = (
        "/api/disc/status-html",
        "/api/settings/daemons",
        "/api/tasks/active-html",
        "/ws",
        "/static/",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for path in self.QUIET_PATHS:
            if path in message:
                return False  # Don't log these at all
        return True
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from amphigory.database import Database
from amphigory.config import get_config
from amphigory.api import disc_router, tracks_router, settings_router, tasks_router, drives_router, library_router, cleanup_router
from amphigory.api.presets import router as presets_router
from amphigory.websocket import manager
from amphigory.task_processor import TaskProcessor

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _configure_logging():
    """Add custom filters to uvicorn's access logger.

    Note: Duplicate prevention is handled by config/logging.yaml.
    This just adds our custom filter for noisy polling endpoints.
    """
    logging.getLogger("uvicorn.access").addFilter(QuietAccessFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    _configure_logging()

    # Log the effective logging level
    root_level = logging.getLogger().getEffectiveLevel()
    logging.getLogger("uvicorn").info(f"Logging level: {logging.getLevelName(root_level)}")

    # Initialize database
    config = get_config()
    app.state.db = Database(config.database_path)
    await app.state.db.initialize()

    # Start task processor
    import os
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))

    def progress_callback(progress: dict):
        # Broadcast to all connected clients
        asyncio.create_task(manager.broadcast({
            "type": "progress",
            **progress,
        }))

    app.state.task_processor = TaskProcessor(
        db=app.state.db,
        tasks_dir=data_dir / "tasks",
        transcoded_dir=config.transcoded_dir,
        preset_dir=config.preset_dir,
        progress_callback=progress_callback,
    )
    await app.state.task_processor.start()

    yield

    # Cleanup
    try:
        await app.state.task_processor.stop()
    finally:
        await app.state.db.close()


app = FastAPI(
    title="Amphigory",
    description="Automated optical media ripping and transcoding for Plex",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Include API routers
app.include_router(disc_router)
app.include_router(tracks_router)
app.include_router(settings_router)
app.include_router(tasks_router)
app.include_router(drives_router)
app.include_router(library_router)
app.include_router(cleanup_router)
app.include_router(presets_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Amphigory"},
    )


@app.get("/disc", response_class=HTMLResponse)
async def disc_review_page(request: Request):
    """Disc review page for track selection."""
    return templates.TemplateResponse(
        request,
        "disc.html",
        {"active_page": "disc"},
    )


@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    """Queue page showing task status."""
    return templates.TemplateResponse(
        request,
        "queue.html",
        {"active_page": "queue"},
    )


@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    """Library page."""
    return templates.TemplateResponse(request, "library.html", {"active_page": "library"})


@app.get("/cleanup", response_class=HTMLResponse)
async def cleanup_page(request: Request):
    """Cleanup page for managing ripped and transcoded files."""
    return templates.TemplateResponse(request, "cleanup.html", {"active_page": "cleanup"})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    import os
    config = get_config()
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_page": "settings",
            "config": {
                "tasks_directory": str(data_dir / "tasks"),
                "websocket_port": 8765,
                "wiki_url": "https://gollum/amphigory",
                "heartbeat_interval": 30,
                "log_level": "INFO",
            },
            "directories": {
                "ripped_dir": str(config.ripped_dir),
                "transcoded_dir": str(config.transcoded_dir),
                "plex_dir": str(config.plex_dir),
            },
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/version")
async def get_version():
    """Return version info including git SHA.

    The GIT_SHA is set at build time via Docker build arg.
    """
    import os
    return {
        "version": "0.1.0",
        "git_sha": os.environ.get("GIT_SHA", "dev"),
    }


@app.get("/config.json")
async def get_daemon_config():
    """Return configuration for the macOS daemon.

    The daemon fetches this on startup to get runtime settings.
    """
    import os
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    config = get_config()

    # DAEMON_RIPPED_DIR is the host path where daemon writes ripped files
    # Falls back to config.ripped_dir (container path) if not set
    ripped_dir = os.environ.get("DAEMON_RIPPED_DIR") or str(config.ripped_dir)

    return {
        "tasks_directory": str(data_dir / "tasks"),
        "websocket_port": 8765,
        "wiki_url": "https://gollum/amphigory",
        "heartbeat_interval": 30,
        "log_level": "INFO",
        "makemkv_path": None,
        "ripped_directory": ripped_dir,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    import json
    from datetime import datetime
    from amphigory.api.settings import _daemons, RegisteredDaemon

    await manager.connect(websocket)
    daemon_id = None
    # Use uvicorn's logger so it appears in logs (our app logger has no handlers)
    uvi_logger = logging.getLogger("uvicorn")
    uvi_logger.info("WebSocket connection opened")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "daemon_config":
                    # Register daemon when it sends its config
                    daemon_id = message.get("daemon_id")
                    if daemon_id:
                        now = datetime.now()
                        git_sha = message.get("git_sha")
                        _daemons[daemon_id] = RegisteredDaemon(
                            daemon_id=daemon_id,
                            makemkvcon_path=message.get("makemkvcon_path"),
                            webapp_basedir=message.get("webapp_basedir", ""),
                            git_sha=git_sha,
                            connected_at=now,
                            last_seen=now,
                        )
                        sha_info = f" (git: {git_sha})" if git_sha else ""
                        uvi_logger.info(f"Daemon registered: {daemon_id}{sha_info}")

                        # Register daemon connection for request/response
                        manager.register_daemon(daemon_id, websocket)

                elif msg_type == "disc_event" and daemon_id:
                    # Handle disc events (no local state - daemon is source of truth)
                    if daemon_id in _daemons:
                        event = message.get("event")
                        if event == "inserted":
                            uvi_logger.info(f"Disc inserted: {message.get('volume_name')} at {message.get('device')} (daemon: {daemon_id})")
                        elif event == "ejected":
                            uvi_logger.info(f"Disc ejected (daemon: {daemon_id})")
                            # Clear cached scan result
                            from amphigory.api.disc import clear_current_scan
                            clear_current_scan()
                        elif event == "fingerprinted":
                            fingerprint = message.get("fingerprint")
                            uvi_logger.info(f"Disc fingerprinted: {fingerprint[:16] if fingerprint else 'None'}... (daemon: {daemon_id})")

                            # Look up disc in database
                            from amphigory.api.disc_repository import get_disc_by_fingerprint
                            disc = await get_disc_by_fingerprint(fingerprint)
                            if disc:
                                year_str = disc['year'] or fingerprint[:7]
                                uvi_logger.info(f"Known disc: {disc['title']} ({year_str})")

                        # Broadcast to browser clients
                        broadcast_msg = {
                            "type": "disc_event",
                            "event": event,
                            "device": message.get("device"),
                            "volume_name": message.get("volume_name"),
                            "volume_path": message.get("volume_path"),
                            "daemon_id": daemon_id,
                        }
                        # Include fingerprint info if available
                        if event == "fingerprinted":
                            broadcast_msg["fingerprint"] = message.get("fingerprint")
                            if disc:
                                broadcast_msg["known_disc"] = {
                                    "title": disc["title"],
                                    "year": disc["year"],
                                    "disc_type": disc["disc_type"],
                                }
                        await manager.broadcast(broadcast_msg)

                elif msg_type == "response":
                    # Handle response from daemon
                    manager.handle_response(message)

                elif msg_type == "heartbeat" and daemon_id:
                    # Update last_seen on heartbeat
                    if daemon_id in _daemons:
                        _daemons[daemon_id].last_seen = datetime.now()

                elif msg_type == "progress" and daemon_id:
                    # Relay progress to browser clients
                    await manager.broadcast({
                        "type": "progress",
                        "task_id": message.get("task_id"),
                        "percent": message.get("percent"),
                        "eta_seconds": message.get("eta_seconds"),
                        "current_size_bytes": message.get("current_size_bytes"),
                        "speed": message.get("speed"),
                    })

            except json.JSONDecodeError:
                pass  # Ignore malformed messages

    except WebSocketDisconnect:
        # Remove daemon on disconnect
        if daemon_id:
            uvi_logger.info(f"WebSocket connection closed: {daemon_id}")
            if daemon_id in _daemons:
                del _daemons[daemon_id]
            # Unregister daemon
            manager.unregister_daemon(daemon_id)
        else:
            uvi_logger.info("WebSocket connection closed")
        manager.disconnect(websocket)
