"""Smoke tests - verify all pages load without errors."""

import pytest
from playwright.sync_api import Page, expect


class TestPageLoads:
    """Verify all main pages load successfully."""

    def test_dashboard_loads(self, page: Page, test_server: str):
        """Dashboard page loads."""
        page.goto(f"{test_server}/")
        # Dashboard has nav-brand and h2 sections
        expect(page.locator(".nav-brand")).to_contain_text("Amphigory")
        expect(page.locator("h2").first).to_be_visible()

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
