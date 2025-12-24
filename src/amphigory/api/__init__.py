"""API routers."""

from amphigory.api.disc import router as disc_router
from amphigory.api.jobs import router as jobs_router
from amphigory.api.settings import router as settings_router
from amphigory.api.tasks import router as tasks_router

__all__ = ["disc_router", "jobs_router", "settings_router", "tasks_router"]
