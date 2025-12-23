"""Tests for makemkvcon discovery - TDD: tests written first."""

from pathlib import Path
from unittest.mock import patch

import pytest


class TestDiscoverMakemkvcon:
    def test_returns_configured_path_if_exists(self, tmp_path):
        """Use explicitly configured path if it exists."""
        from amphigory_daemon.discovery import discover_makemkvcon

        # Create a fake makemkvcon
        fake_bin = tmp_path / "makemkvcon"
        fake_bin.touch()
        fake_bin.chmod(0o755)

        result = discover_makemkvcon(configured_path=str(fake_bin))

        assert result == fake_bin

    def test_returns_none_for_nonexistent_configured_path(self, tmp_path):
        """Return None if configured path doesn't exist."""
        from amphigory_daemon.discovery import discover_makemkvcon

        missing = tmp_path / "nonexistent" / "makemkvcon"

        result = discover_makemkvcon(configured_path=str(missing))

        assert result is None

    def test_finds_in_path(self, tmp_path):
        """Find makemkvcon via shutil.which (in $PATH)."""
        from amphigory_daemon.discovery import discover_makemkvcon

        fake_bin = tmp_path / "makemkvcon"
        fake_bin.touch()
        fake_bin.chmod(0o755)

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = str(fake_bin)

            result = discover_makemkvcon()

        assert result == fake_bin

    def test_searches_homebrew_paths(self, tmp_path):
        """Search Homebrew paths when not in $PATH."""
        from amphigory_daemon.discovery import discover_makemkvcon

        # Create fake homebrew binary
        homebrew_path = tmp_path / "opt" / "homebrew" / "bin"
        homebrew_path.mkdir(parents=True)
        fake_bin = homebrew_path / "makemkvcon"
        fake_bin.touch()
        fake_bin.chmod(0o755)

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = None  # Not in PATH

            with patch("amphigory_daemon.discovery.SEARCH_PATHS", [str(fake_bin)]):
                result = discover_makemkvcon()

        assert result == fake_bin

    def test_searches_app_bundle(self, tmp_path):
        """Search inside MakeMKV.app bundle."""
        from amphigory_daemon.discovery import discover_makemkvcon

        # Create fake app bundle path
        app_path = tmp_path / "Applications" / "MakeMKV.app" / "Contents" / "MacOS"
        app_path.mkdir(parents=True)
        fake_bin = app_path / "makemkvcon"
        fake_bin.touch()
        fake_bin.chmod(0o755)

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("amphigory_daemon.discovery.SEARCH_PATHS", [str(fake_bin)]):
                result = discover_makemkvcon()

        assert result == fake_bin

    def test_returns_none_when_not_found(self):
        """Return None when makemkvcon cannot be found anywhere."""
        from amphigory_daemon.discovery import discover_makemkvcon

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = None

            with patch("amphigory_daemon.discovery.SEARCH_PATHS", [
                "/nonexistent/path1/makemkvcon",
                "/nonexistent/path2/makemkvcon",
            ]):
                result = discover_makemkvcon()

        assert result is None

    def test_search_order_configured_first(self, tmp_path):
        """Configured path takes precedence over PATH and search paths."""
        from amphigory_daemon.discovery import discover_makemkvcon

        configured_bin = tmp_path / "configured" / "makemkvcon"
        configured_bin.parent.mkdir(parents=True)
        configured_bin.touch()
        configured_bin.chmod(0o755)

        path_bin = tmp_path / "path" / "makemkvcon"
        path_bin.parent.mkdir(parents=True)
        path_bin.touch()
        path_bin.chmod(0o755)

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = str(path_bin)

            result = discover_makemkvcon(configured_path=str(configured_bin))

        # Should return configured, not the one from PATH
        assert result == configured_bin

    def test_search_order_path_before_search_paths(self, tmp_path):
        """PATH takes precedence over hardcoded search paths."""
        from amphigory_daemon.discovery import discover_makemkvcon

        path_bin = tmp_path / "path" / "makemkvcon"
        path_bin.parent.mkdir(parents=True)
        path_bin.touch()
        path_bin.chmod(0o755)

        search_bin = tmp_path / "search" / "makemkvcon"
        search_bin.parent.mkdir(parents=True)
        search_bin.touch()
        search_bin.chmod(0o755)

        with patch("amphigory_daemon.discovery.shutil.which") as mock_which:
            mock_which.return_value = str(path_bin)

            with patch("amphigory_daemon.discovery.SEARCH_PATHS", [str(search_bin)]):
                result = discover_makemkvcon()

        assert result == path_bin
