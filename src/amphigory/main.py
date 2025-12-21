"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Amphigory",
    description="Automated optical media ripping and transcoding for Plex",
    version="0.1.0",
)

# Will be configured after templates directory exists
# templates = Jinja2Templates(directory="src/amphigory/templates")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
