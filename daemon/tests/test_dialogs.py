"""Tests for custom dialogs - TDD: tests written first."""

import pytest
from unittest.mock import MagicMock, patch


class TestConfigDialog:
    """Tests for the configuration dialog."""

    def test_config_dialog_exists(self):
        """ConfigDialog class exists."""
        from amphigory_daemon.dialogs import ConfigDialog

        assert ConfigDialog is not None

    def test_config_dialog_has_url_field(self):
        """ConfigDialog has a URL field."""
        from amphigory_daemon.dialogs import ConfigDialog

        dialog = ConfigDialog()
        assert hasattr(dialog, "url_field")

    def test_config_dialog_has_directory_field(self):
        """ConfigDialog has a directory field."""
        from amphigory_daemon.dialogs import ConfigDialog

        dialog = ConfigDialog()
        assert hasattr(dialog, "directory_field")

    def test_config_dialog_can_set_initial_values(self):
        """ConfigDialog accepts initial values for fields."""
        from amphigory_daemon.dialogs import ConfigDialog

        dialog = ConfigDialog(
            initial_url="http://test:6199",
            initial_directory="/test/path",
        )

        assert dialog.initial_url == "http://test:6199"
        assert dialog.initial_directory == "/test/path"

    def test_config_dialog_has_wiki_url(self):
        """ConfigDialog stores wiki URL for help link."""
        from amphigory_daemon.dialogs import ConfigDialog

        dialog = ConfigDialog(wiki_url="https://example.com/wiki")
        assert dialog.wiki_url == "https://example.com/wiki"

    def test_config_dialog_run_returns_result(self):
        """ConfigDialog.run() returns a result object."""
        from amphigory_daemon.dialogs import ConfigDialog, DialogResult

        # We can't easily test the actual dialog without mocking AppKit
        # but we can verify the interface exists
        dialog = ConfigDialog()
        assert hasattr(dialog, "run")
        assert callable(dialog.run)


class TestDialogResult:
    """Tests for dialog result."""

    def test_dialog_result_has_cancelled_flag(self):
        """DialogResult has cancelled flag."""
        from amphigory_daemon.dialogs import DialogResult

        result = DialogResult(cancelled=True)
        assert result.cancelled is True

    def test_dialog_result_has_url(self):
        """DialogResult has url field."""
        from amphigory_daemon.dialogs import DialogResult

        result = DialogResult(cancelled=False, url="http://test:6199")
        assert result.url == "http://test:6199"

    def test_dialog_result_has_directory(self):
        """DialogResult has directory field."""
        from amphigory_daemon.dialogs import DialogResult

        result = DialogResult(cancelled=False, directory="/test/path")
        assert result.directory == "/test/path"
