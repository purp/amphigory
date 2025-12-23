"""Tests for main webapp application."""

import pytest
from fastapi.testclient import TestClient


class TestConfigEndpoint:
    """Tests for /config.json endpoint."""

    def test_config_endpoint_exists(self, test_client):
        """GET /config.json returns 200."""
        response = test_client.get("/config.json")
        assert response.status_code == 200

    def test_config_endpoint_returns_json(self, test_client):
        """GET /config.json returns JSON content type."""
        response = test_client.get("/config.json")
        assert response.headers["content-type"] == "application/json"

    def test_config_contains_tasks_directory(self, test_client):
        """Config includes tasks_directory."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "tasks_directory" in data
        assert isinstance(data["tasks_directory"], str)

    def test_config_contains_websocket_port(self, test_client):
        """Config includes websocket_port."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "websocket_port" in data
        assert isinstance(data["websocket_port"], int)

    def test_config_contains_wiki_url(self, test_client):
        """Config includes wiki_url."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "wiki_url" in data
        assert isinstance(data["wiki_url"], str)

    def test_config_contains_heartbeat_interval(self, test_client):
        """Config includes heartbeat_interval."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "heartbeat_interval" in data
        assert isinstance(data["heartbeat_interval"], int)

    def test_config_contains_log_level(self, test_client):
        """Config includes log_level."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "log_level" in data
        assert isinstance(data["log_level"], str)

    def test_config_contains_makemkv_path(self, test_client):
        """Config includes makemkv_path (can be null)."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "makemkv_path" in data
        # Can be string or None
        assert data["makemkv_path"] is None or isinstance(data["makemkv_path"], str)
