"""FastAPI application entry point."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from amphigory.database import Database
from amphigory.config import get_config
from amphigory.api import disc_router, jobs_router, settings_router, tasks_router
from amphigory.websocket import manager

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Initialize database
    config = get_config()
    app.state.db = Database(config.database_path)
    await app.state.db.initialize()

    yield

    # Cleanup
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
app.include_router(jobs_router)
app.include_router(settings_router)
app.include_router(tasks_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": "Amphigory",
            "disc_status": "No disc detected",
        },
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
                "inbox_dir": str(config.inbox_dir),
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
    return {
        "tasks_directory": str(data_dir / "tasks"),
        "websocket_port": 8765,
        "wiki_url": "https://gollum/amphigory",
        "heartbeat_interval": 30,
        "log_level": "INFO",
        "makemkv_path": None,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    import json
    from datetime import datetime
    from amphigory.api.settings import _daemons, RegisteredDaemon

    await manager.connect(websocket)
    daemon_id = None
    logger.info("WebSocket connection opened")

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
                        _daemons[daemon_id] = RegisteredDaemon(
                            daemon_id=daemon_id,
                            makemkvcon_path=message.get("makemkvcon_path"),
                            webapp_basedir=message.get("webapp_basedir", ""),
                            connected_at=now,
                            last_seen=now,
                        )
                        logger.info(f"Daemon registered: {daemon_id}")

                elif msg_type == "disc_event" and daemon_id:
                    # Update disc status for daemon
                    if daemon_id in _daemons:
                        event = message.get("event")
                        if event == "inserted":
                            _daemons[daemon_id].disc_inserted = True
                            _daemons[daemon_id].disc_device = message.get("device")
                            _daemons[daemon_id].disc_volume = message.get("volume_name")
                        elif event == "ejected":
                            _daemons[daemon_id].disc_inserted = False
                            _daemons[daemon_id].disc_device = None
                            _daemons[daemon_id].disc_volume = None

                elif msg_type == "heartbeat" and daemon_id:
                    # Update last_seen on heartbeat
                    if daemon_id in _daemons:
                        _daemons[daemon_id].last_seen = datetime.now()

            except json.JSONDecodeError:
                pass  # Ignore malformed messages

    except WebSocketDisconnect:
        # Remove daemon on disconnect
        if daemon_id:
            logger.info(f"WebSocket connection closed: {daemon_id}")
            if daemon_id in _daemons:
                del _daemons[daemon_id]
        else:
            logger.info("WebSocket connection closed")
        manager.disconnect(websocket)
