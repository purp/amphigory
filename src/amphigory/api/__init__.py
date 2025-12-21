"""API routers."""

from amphigory.api.disc import router as disc_router
from amphigory.api.jobs import router as jobs_router

__all__ = ["disc_router", "jobs_router"]
