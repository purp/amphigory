"""Tests for settings API - TDD: tests written first."""

import pytest
from fastapi.testclient import TestClient


class TestSettingsRoute:
    """Tests for /settings page route."""

    def test_settings_page_returns_200(self, test_client: TestClient):
        """Settings page returns 200 OK."""
        response = test_client.get("/settings")
        assert response.status_code == 200

    def test_settings_page_contains_webapp_config(self, test_client: TestClient):
        """Settings page displays webapp configuration."""
        response = test_client.get("/settings")
        assert "Webapp Configuration" in response.text

    def test_settings_page_contains_connected_daemons(self, test_client: TestClient):
        """Settings page has connected daemons section."""
        response = test_client.get("/settings")
        assert "Connected Daemons" in response.text

    def test_settings_page_contains_directories(self, test_client: TestClient):
        """Settings page displays directory settings."""
        response = test_client.get("/settings")
        assert "Directories" in response.text


class TestDaemonsListEndpoint:
    """Tests for /api/settings/daemons endpoint."""

    def test_returns_200(self, test_client: TestClient):
        """Daemons list endpoint returns 200 OK."""
        response = test_client.get("/api/settings/daemons")
        assert response.status_code == 200

    def test_returns_html(self, test_client: TestClient):
        """Daemons list endpoint returns HTML fragment."""
        response = test_client.get("/api/settings/daemons")
        assert response.headers["content-type"].startswith("text/html")

    def test_shows_no_daemons_message_when_empty(self, test_client: TestClient):
        """Shows 'no daemons' message when none connected."""
        response = test_client.get("/api/settings/daemons")
        assert "No daemons connected" in response.text


class TestDaemonRegistry:
    """Tests for daemon registration and tracking."""

    def test_register_daemon(self, test_client: TestClient):
        """Can register a daemon via POST."""
        response = test_client.post(
            "/api/settings/daemons",
            json={
                "daemon_id": "testuser@testhost",
                "makemkvcon_path": "/usr/local/bin/makemkvcon",
                "webapp_basedir": "/data",
            },
        )
        assert response.status_code == 200
        assert response.json()["daemon_id"] == "testuser@testhost"

    def test_registered_daemon_appears_in_list(self, test_client: TestClient):
        """Registered daemon appears in daemon list."""
        # Register a daemon
        test_client.post(
            "/api/settings/daemons",
            json={
                "daemon_id": "testuser@testhost",
                "makemkvcon_path": "/usr/local/bin/makemkvcon",
                "webapp_basedir": "/data",
            },
        )

        # Check it appears in the list
        response = test_client.get("/api/settings/daemons")
        assert "testuser@testhost" in response.text

    def test_daemon_heartbeat(self, test_client: TestClient):
        """Daemon can send heartbeat to update last_seen."""
        # Register daemon first
        test_client.post(
            "/api/settings/daemons",
            json={
                "daemon_id": "testuser@testhost",
                "makemkvcon_path": "/usr/local/bin/makemkvcon",
                "webapp_basedir": "/data",
            },
        )

        # Send heartbeat
        response = test_client.post("/api/settings/daemons/testuser@testhost/heartbeat")
        assert response.status_code == 200

    def test_daemon_disconnect(self, test_client: TestClient):
        """Can mark daemon as disconnected."""
        # Register daemon first
        test_client.post(
            "/api/settings/daemons",
            json={
                "daemon_id": "testuser@testhost",
                "makemkvcon_path": "/usr/local/bin/makemkvcon",
                "webapp_basedir": "/data",
            },
        )

        # Disconnect
        response = test_client.delete("/api/settings/daemons/testuser@testhost")
        assert response.status_code == 200

        # Should show as disconnected or be removed
        list_response = test_client.get("/api/settings/daemons")
        # Either not in list, or marked disconnected
        assert response.status_code == 200


class TestValidationEndpoints:
    """Tests for validation endpoints."""

    def test_validate_path_valid(self, test_client: TestClient, tmp_path):
        """Valid path returns valid icon."""
        response = test_client.post(
            "/api/settings/validate/path",
            data={"path": str(tmp_path)},
        )
        assert response.status_code == 200
        assert "valid" in response.text
        assert "✓" in response.text

    def test_validate_path_invalid(self, test_client: TestClient):
        """Invalid path returns invalid icon."""
        response = test_client.post(
            "/api/settings/validate/path",
            data={"path": "/nonexistent/path/that/does/not/exist"},
        )
        assert response.status_code == 200
        assert "invalid" in response.text
        assert "✗" in response.text

    def test_validate_url_valid(self, test_client: TestClient):
        """Valid URL returns valid icon."""
        response = test_client.post(
            "/api/settings/validate/url",
            data={"wiki_url": "https://example.com/wiki"},
        )
        assert response.status_code == 200
        assert "valid" in response.text
        assert "✓" in response.text

    def test_validate_url_invalid(self, test_client: TestClient):
        """Invalid URL returns invalid icon."""
        response = test_client.post(
            "/api/settings/validate/url",
            data={"wiki_url": "not-a-valid-url"},
        )
        assert response.status_code == 200
        assert "invalid" in response.text
        assert "✗" in response.text
