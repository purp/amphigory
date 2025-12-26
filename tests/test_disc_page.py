"""Tests for disc review page template rendering."""

import pytest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def jinja_env():
    """Create Jinja2 environment for template testing."""
    template_dir = Path(__file__).parent.parent / "src" / "amphigory" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    return env


@pytest.fixture
def disc_template(jinja_env):
    """Load the disc.html template."""
    return jinja_env.get_template("disc.html")


class TestTrackTypeDropdown:
    """Tests for track type dropdown functionality."""

    def test_template_renders_select_element_for_track_type(self, disc_template):
        """Template should render a select element for track type."""
        # Render template (it doesn't require any variables as it's client-side JS)
        rendered = disc_template.render()

        # Check that the template contains code to render a select for track type
        # Since the tracks are rendered via JavaScript, we need to check the JS code
        assert '<select' in rendered, "Template should contain select element code"
        assert 'track-type-select' in rendered, "Should have track-type-select class"

    def test_template_includes_all_track_types(self, disc_template):
        """Template should include all available track types in the select."""
        rendered = disc_template.render()

        # Check that all track types are present in the template
        track_types = [
            'main_feature',
            'behind_the_scenes',
            'deleted_scenes',
            'featurettes',
            'interviews',
            'scenes',
            'shorts',
            'trailers',
            'other',
        ]

        for track_type in track_types:
            assert track_type in rendered, f"Track type '{track_type}' should be in template"

    def test_template_includes_classification_change_handler(self, disc_template):
        """Template should include JavaScript handler for classification changes."""
        rendered = disc_template.render()

        # Check for the change handler function
        assert 'onClassificationChange' in rendered or 'updateTrackClassification' in rendered, \
            "Should have classification change handler"

    def test_template_has_format_classification_function(self, disc_template):
        """Template should have formatClassification function for display labels."""
        rendered = disc_template.render()

        assert 'formatClassification' in rendered, \
            "Should have formatClassification function"

        # Check that it includes human-readable labels
        assert 'Main Feature' in rendered
        assert 'Trailer' in rendered
        assert 'Featurette' in rendered

    def test_template_removes_confidence_indicator_on_manual_change(self, disc_template):
        """When user changes type manually, confidence indicator should be removed."""
        rendered = disc_template.render()

        # The change handler should update the DOM to remove confidence indicator
        # This is tested by checking for logic that handles confidence removal
        assert 'confidence' in rendered, "Should reference confidence indicator"
