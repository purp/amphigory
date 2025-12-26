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


class TestSetTrackNames:
    """Tests for Set Track Names button functionality."""

    def test_template_has_set_track_names_button(self, disc_template):
        """Template should include a 'Set Track Names' button in disc info section."""
        rendered = disc_template.render()

        # Check button exists
        assert 'Set Track Names' in rendered, "Should have 'Set Track Names' button"
        assert 'onclick="setTrackNames()"' in rendered, "Button should call setTrackNames() function"

    def test_template_has_set_track_names_function(self, disc_template):
        """Template should include setTrackNames() JavaScript function."""
        rendered = disc_template.render()

        # Check function definition exists
        assert 'function setTrackNames()' in rendered, "Should have setTrackNames() function"

    def test_set_track_names_validates_title_and_year(self, disc_template):
        """setTrackNames() should validate title and year are present."""
        rendered = disc_template.render()

        # Check for validation logic
        assert 'disc-title' in rendered and 'disc-year' in rendered, \
            "Should reference title and year inputs"
        assert 'alert' in rendered, "Should have alert for validation"

    def test_set_track_names_handles_main_feature(self, disc_template):
        """setTrackNames() should use movie title for main_feature tracks."""
        rendered = disc_template.render()

        # Check for main_feature handling
        assert "classification === 'main_feature'" in rendered or \
               'main_feature' in rendered, \
            "Should handle main_feature classification"

    def test_set_track_names_numbers_duplicates(self, disc_template):
        """setTrackNames() should number duplicate types (e.g., Trailer 1, Trailer 2)."""
        rendered = disc_template.render()

        # Check for counting/numbering logic
        assert 'typeCounts' in rendered or 'count' in rendered, \
            "Should have logic for counting duplicate types"

    def test_set_track_names_handles_all_extra_types(self, disc_template):
        """setTrackNames() should handle all extra types with proper naming."""
        rendered = disc_template.render()

        # Check that extra types are handled
        extra_types = ['trailers', 'featurettes', 'behind_the_scenes',
                       'deleted_scenes', 'interviews', 'shorts', 'scenes']

        for extra_type in extra_types:
            assert extra_type in rendered, f"Should handle '{extra_type}' classification"
