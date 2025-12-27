"""API routers."""

from amphigory.api.disc import router as disc_router
from amphigory.api.disc import tracks_router
from amphigory.api.settings import router as settings_router
from amphigory.api.tasks import router as tasks_router
from amphigory.api.drives import router as drives_router
from amphigory.api.library import router as library_router
from amphigory.api.cleanup import router as cleanup_router

__all__ = ["disc_router", "tracks_router", "settings_router", "tasks_router", "drives_router", "library_router", "cleanup_router"]
