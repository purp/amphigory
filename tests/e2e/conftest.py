"""Playwright E2E test configuration."""

import os
import socket
import subprocess
import sys
import time
import pytest

import httpx


def get_free_port():
    """Find an available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def test_server(tmp_path_factory):
    """Start test server with fresh database."""
    tmp_path = tmp_path_factory.mktemp("e2e")
    port = get_free_port()

    # Set environment for test server
    env = os.environ.copy()
    env["AMPHIGORY_DATA"] = str(tmp_path)
    env["AMPHIGORY_DATABASE"] = str(tmp_path / "test.db")
    env["PYTHONPATH"] = "src"

    # Create tasks directories (needed by app startup)
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "queued").mkdir(parents=True)
    (tasks_dir / "in_progress").mkdir(parents=True)
    (tasks_dir / "complete").mkdir(parents=True)

    # Start uvicorn as subprocess
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "amphigory.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            httpx.get(f"{base_url}/health", timeout=1.0)
            break
        except Exception:
            time.sleep(0.2)
    else:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"Test server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield base_url

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="session")
def browser_context_args():
    """Browser context arguments."""
    return {"ignore_https_errors": True}
