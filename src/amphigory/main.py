"""FastAPI application entry point."""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from amphigory.database import Database
from amphigory.config import get_config
from amphigory.api import disc_router, jobs_router
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Amphigory",
            "disc_status": "No disc detected",
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


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
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_text()
            # Could process commands here if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)
