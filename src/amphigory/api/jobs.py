"""API endpoints for job management."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from amphigory.jobs import JobQueue, JobType, JobStatus

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/active", response_class=HTMLResponse)
async def get_active_jobs_html(request: Request):
    """Return active jobs as HTML fragment for HTMX."""
    db = request.app.state.db
    queue = JobQueue(db)

    # Get running jobs
    async with db.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY started_at DESC",
            (JobStatus.RUNNING.value,),
        )
        running_jobs = [dict(row) for row in await cursor.fetchall()]

    if not running_jobs:
        return '<p class="no-jobs">No active jobs</p>'

    html = ""
    for job in running_jobs:
        html += f'''
        <div class="job-item">
            <div class="job-info">
                <span class="job-type">{job["job_type"].title()}</span>
                <span class="job-track">Track {job["track_id"]}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-bar-fill" style="width: {job["progress"]}%"></div>
            </div>
            <span class="progress-text">{job["progress"]}%</span>
        </div>
        '''

    return html


@router.get("/queue")
async def get_job_queue(request: Request):
    """Get all queued jobs."""
    db = request.app.state.db
    queue = JobQueue(db)

    jobs = await queue.get_queue()
    return {"jobs": jobs}


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int):
    """Cancel a queued job."""
    db = request.app.state.db
    queue = JobQueue(db)

    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.QUEUED.value:
        raise HTTPException(status_code=400, detail="Can only cancel queued jobs")

    await queue.cancel_job(job_id)
    return {"status": "cancelled"}


@router.post("/{job_id}/priority")
async def update_job_priority(request: Request, job_id: int, priority: int):
    """Update a job's priority."""
    db = request.app.state.db
    queue = JobQueue(db)

    await queue.reorder_job(job_id, priority)
    return {"status": "updated"}
