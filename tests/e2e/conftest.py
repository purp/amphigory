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
