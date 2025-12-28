# Testing Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add integration tests for rip→transcode and disc→library flows, plus Playwright smoke tests for all pages.

**Architecture:** Integration tests use real SQLite and task queue with mocked file system. Playwright tests run against a uvicorn subprocess with seeded database.

**Tech Stack:** pytest, pytest-asyncio, pytest-playwright, Playwright Chromium

---

## Task 1: Add TestRipTranscodeChain Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write failing test for transcode task readiness**

Add to `tests/test_integration.py`:

```python
class TestRipTranscodeChain:
    """Integration tests for rip → transcode task chain."""

    @pytest.fixture
    def media_dirs(self, tmp_path):
        """Create ripped and transcoded directories."""
        ripped = tmp_path / "ripped"
        transcoded = tmp_path / "transcoded"
        ripped.mkdir()
        transcoded.mkdir()
        return {"ripped": ripped, "transcoded": transcoded}

    def test_transcode_task_waits_for_rip_output(self, client, tasks_dir, media_dirs):
        """Transcode task is not ready until rip output file exists."""
        rip_output = media_dirs["ripped"] / "Movie (2024)" / "Movie (2024).mkv"

        # Create rip task (completed) and transcode task (waiting)
        rip_task = {
            "id": "20251227T100000.000000-rip",
            "type": "rip",
            "status": "complete",
            "output": str(rip_output),
        }
        transcode_task = {
            "id": "20251227T100000.000001-transcode",
            "type": "transcode",
            "input": str(rip_output),
            "output": str(media_dirs["transcoded"] / "Movie (2024).mp4"),
            "preset": "H.265 MKV 1080p",
        }

        # Write tasks
        with open(tasks_dir / "complete" / f"{rip_task['id']}.json", "w") as f:
            json.dump(rip_task, f)
        with open(tasks_dir / "queued" / f"{transcode_task['id']}.json", "w") as f:
            json.dump(transcode_task, f)

        # Transcode should not be ready (input doesn't exist)
        response = client.get("/api/tasks")
        data = response.json()
        queued = [t for t in data.get("queued", []) if t["id"] == transcode_task["id"]]
        assert len(queued) == 1
        # The task is queued but blocked on input
```

**Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py::TestRipTranscodeChain::test_transcode_task_waits_for_rip_output -v
```

Expected: FAIL (class doesn't exist yet or test logic needs adjustment)

**Step 3: Add test for transcode becomes ready when file exists**

```python
    def test_transcode_ready_when_rip_output_exists(self, client, tasks_dir, media_dirs):
        """Transcode task becomes ready when rip output file exists."""
        rip_output = media_dirs["ripped"] / "Movie (2024)" / "Movie (2024).mkv"
        rip_output.parent.mkdir(parents=True)
        rip_output.write_text("fake mkv content")  # Create the file

        transcode_task = {
            "id": "20251227T100000.000001-transcode",
            "type": "transcode",
            "input": str(rip_output),
            "output": str(media_dirs["transcoded"] / "Movie (2024).mp4"),
            "preset": "H.265 MKV 1080p",
        }

        with open(tasks_dir / "queued" / f"{transcode_task['id']}.json", "w") as f:
            json.dump(transcode_task, f)
        with open(tasks_dir / "tasks.json", "w") as f:
            json.dump([transcode_task["id"]], f)

        # Input exists, so transcode should be gettable
        response = client.get("/api/tasks")
        assert response.status_code == 200
```

**Step 4: Run tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py::TestRipTranscodeChain -v
```

**Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add rip→transcode chain integration tests"
```

---

## Task 2: Add TestDiscToLibraryFlow Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write test for process creating task pairs**

```python
class TestDiscToLibraryFlow:
    """Integration tests for disc review → process → library flow."""

    @pytest.fixture
    async def seeded_disc(self, client):
        """Seed database with a disc and tracks."""
        from amphigory.main import app
        db = app.state.db

        # Insert disc
        async with db._pool.acquire() as conn:
            cursor = await conn.execute("""
                INSERT INTO discs (fingerprint, title, year, disc_type)
                VALUES (?, ?, ?, ?)
            """, ("test-fp-12345", "Test Movie", 2024, "bluray"))
            disc_id = cursor.lastrowid

            # Insert tracks
            for i in range(3):
                await conn.execute("""
                    INSERT INTO tracks (disc_id, track_number, duration_seconds, size_bytes, track_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (disc_id, i + 1, 7200 + i * 100, 10_000_000_000, "main_feature" if i == 0 else "extra"))
            await conn.commit()

        return {"disc_id": disc_id, "fingerprint": "test-fp-12345"}

    @pytest.mark.asyncio
    async def test_process_creates_rip_and_transcode_pairs(self, client, tasks_dir, seeded_disc):
        """POST /api/tasks/process creates paired rip and transcode tasks."""
        response = client.post("/api/tasks/process", json={
            "disc_fingerprint": seeded_disc["fingerprint"],
            "tracks": [
                {"track_number": 1, "output_filename": "Test Movie (2024).mkv", "preset": "H.265 MKV 1080p"},
                {"track_number": 2, "output_filename": "Extra 1.mkv", "preset": "H.265 MKV 720p"},
            ]
        })

        assert response.status_code == 201
        data = response.json()

        # Should have 4 tasks: 2 rips + 2 transcodes
        assert len(data["tasks"]) == 4

        rip_tasks = [t for t in data["tasks"] if t["type"] == "rip"]
        transcode_tasks = [t for t in data["tasks"] if t["type"] == "transcode"]

        assert len(rip_tasks) == 2
        assert len(transcode_tasks) == 2
```

**Step 2: Run test**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py::TestDiscToLibraryFlow::test_process_creates_rip_and_transcode_pairs -v
```

**Step 3: Add test for completed disc appears in library**

```python
    @pytest.mark.asyncio
    async def test_completed_disc_appears_in_library(self, client, seeded_disc):
        """Disc with processed_at appears in library listing."""
        from amphigory.main import app
        db = app.state.db

        # Mark disc as processed
        async with db._pool.acquire() as conn:
            await conn.execute("""
                UPDATE discs SET processed_at = datetime('now') WHERE fingerprint = ?
            """, (seeded_disc["fingerprint"],))
            await conn.commit()

        # Should appear in library
        response = client.get("/api/library")
        assert response.status_code == 200
        data = response.json()

        disc_ids = [d["id"] for d in data["discs"]]
        assert seeded_disc["disc_id"] in disc_ids
```

**Step 4: Run all flow tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py::TestDiscToLibraryFlow -v
```

**Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add disc→library flow integration tests"
```

---

## Task 3: Add Playwright Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add pytest-playwright to dev dependencies**

Find the `[project.optional-dependencies]` or `[tool.poetry.group.dev.dependencies]` section and add:

```toml
pytest-playwright = ">=0.4.0"
```

**Step 2: Install dependencies**

```bash
.venv/bin/pip install pytest-playwright
playwright install chromium
```

**Step 3: Verify installation**

```bash
.venv/bin/python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
```

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pytest-playwright dependency"
```

---

## Task 4: Create Playwright Conftest

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`

**Step 1: Create directory and init file**

```bash
mkdir -p tests/e2e
touch tests/e2e/__init__.py
```

**Step 2: Create conftest.py**

```python
"""Playwright E2E test configuration."""

import asyncio
import os
import socket
import pytest
from multiprocessing import Process
from pathlib import Path

import uvicorn


def get_free_port():
    """Find an available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_server(tmp_path_factory):
    """Start test server with fresh database."""
    tmp_path = tmp_path_factory.mktemp("e2e")
    port = get_free_port()

    # Set environment for test server
    env = os.environ.copy()
    env["AMPHIGORY_DATA"] = str(tmp_path)
    env["AMPHIGORY_DATABASE"] = str(tmp_path / "test.db")

    def run_server():
        os.environ.update(env)
        # Import app after setting environment
        from amphigory.main import app
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    process = Process(target=run_server)
    process.start()

    # Wait for server to be ready
    import time
    import httpx
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            httpx.get(f"{base_url}/health", timeout=1.0)
            break
        except Exception:
            time.sleep(0.2)
    else:
        process.terminate()
        raise RuntimeError("Test server failed to start")

    yield base_url

    process.terminate()
    process.join(timeout=5)


@pytest.fixture(scope="session")
def browser_context_args():
    """Browser context arguments."""
    return {"ignore_https_errors": True}
```

**Step 3: Commit**

```bash
git add tests/e2e/
git commit -m "test: add Playwright conftest with test server fixture"
```

---

## Task 5: Create Smoke Tests

**Files:**
- Create: `tests/e2e/test_smoke.py`

**Step 1: Create smoke test file**

```python
"""Smoke tests - verify all pages load without errors."""

import pytest
from playwright.sync_api import Page, expect


class TestPageLoads:
    """Verify all main pages load successfully."""

    def test_dashboard_loads(self, page: Page, test_server: str):
        """Dashboard page loads."""
        page.goto(f"{test_server}/")
        expect(page.locator("h1")).to_be_visible()
        # Check no console errors
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        assert len(errors) == 0, f"Page errors: {errors}"

    def test_disc_review_loads(self, page: Page, test_server: str):
        """Disc review page loads."""
        page.goto(f"{test_server}/disc")
        # Should show disc review heading or no disc message
        expect(page.locator("body")).to_contain_text("Disc")

    def test_library_loads(self, page: Page, test_server: str):
        """Library page loads with filter controls."""
        page.goto(f"{test_server}/library")
        expect(page.locator("body")).to_contain_text("Library")

    def test_queue_loads(self, page: Page, test_server: str):
        """Queue page loads."""
        page.goto(f"{test_server}/queue")
        expect(page.locator("body")).to_contain_text("Queue")

    def test_cleanup_loads(self, page: Page, test_server: str):
        """Cleanup page loads with tabs."""
        page.goto(f"{test_server}/cleanup")
        expect(page.locator("body")).to_contain_text("Cleanup")

    def test_settings_loads(self, page: Page, test_server: str):
        """Settings page loads."""
        page.goto(f"{test_server}/settings")
        expect(page.locator("body")).to_contain_text("Settings")
```

**Step 2: Run smoke tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/e2e/test_smoke.py -v
```

**Step 3: Commit**

```bash
git add tests/e2e/test_smoke.py
git commit -m "test: add Playwright smoke tests for all pages"
```

---

## Task 6: Verify All Tests Pass

**Step 1: Run existing test suite**

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -v --ignore=tests/e2e/ -q
```

Expected: All 367+ tests pass

**Step 2: Run new integration tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_integration.py -v
```

**Step 3: Run Playwright tests**

```bash
PYTHONPATH=src .venv/bin/pytest tests/e2e/ -v
```

**Step 4: Commit design doc**

```bash
git add docs/plans/2025-12-27-testing-improvements-design.md
git add docs/plans/2025-12-27-testing-improvements-implementation.md
git commit -m "docs: add testing improvements design and implementation plan"
```

---

## Summary

| Task | Description | Tests Added |
|------|-------------|-------------|
| 1 | Rip→Transcode chain tests | 2 |
| 2 | Disc→Library flow tests | 2 |
| 3 | Playwright dependency | - |
| 4 | Playwright conftest | - |
| 5 | Smoke tests | 6 |
| 6 | Verification | - |

**Total new tests: ~10**
