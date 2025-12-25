"""Tests for Plex-compatible track naming functionality."""

import pytest
from pathlib import Path
from amphigory.naming import (
    sanitize_filename,
    generate_track_filename,
    generate_output_directory,
)


class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_removes_invalid_characters(self):
        """Test that invalid filename characters are removed."""
        assert sanitize_filename('Movie: The Sequel') == 'Movie The Sequel'
        assert sanitize_filename('Title/Name') == 'TitleName'
        assert sanitize_filename('File<Name>') == 'FileName'
        assert sanitize_filename('Path\\To\\File') == 'PathToFile'
        assert sanitize_filename('Question?') == 'Question'
        assert sanitize_filename('Wild*card') == 'Wildcard'
        assert sanitize_filename('Pipe|Name') == 'PipeName'
        assert sanitize_filename('"Quoted"') == 'Quoted'

    def test_preserves_valid_characters(self):
        """Test that valid characters are preserved."""
        assert sanitize_filename('Movie (1999)') == 'Movie (1999)'
        assert sanitize_filename('Title - Subtitle') == 'Title - Subtitle'
        # Note: trailing dots are stripped for security
        assert sanitize_filename('Name & Co.') == 'Name & Co'

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            sanitize_filename('')

    def test_handles_whitespace_only(self):
        """Test handling of whitespace-only strings."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            sanitize_filename('   ')
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            sanitize_filename('\t\n')

    def test_prevents_path_traversal(self):
        """Test that path traversal attempts are prevented."""
        assert sanitize_filename('../etc/passwd') == 'etcpasswd'
        assert sanitize_filename('..\\windows\\system32') == 'windowssystem32'
        assert sanitize_filename('file..name') == 'filename'

    def test_strips_leading_trailing_dots(self):
        """Test that leading and trailing dots are stripped."""
        assert sanitize_filename('.hidden') == 'hidden'
        assert sanitize_filename('file.') == 'file'
        assert sanitize_filename('..file..') == 'file'

    def test_strips_leading_trailing_whitespace(self):
        """Test that leading and trailing whitespace are stripped."""
        assert sanitize_filename('  file  ') == 'file'
        assert sanitize_filename('\tfile\n') == 'file'

    def test_sanitization_results_in_empty_string(self):
        """Test that ValueError is raised when sanitization results in empty string."""
        with pytest.raises(ValueError, match="resulted in empty string"):
            sanitize_filename('...')
        with pytest.raises(ValueError, match="resulted in empty string"):
            sanitize_filename('::://')
        with pytest.raises(ValueError, match="resulted in empty string"):
            sanitize_filename('....')
        with pytest.raises(ValueError, match="resulted in empty string"):
            sanitize_filename('<>?*|')


class TestGenerateTrackFilename:
    """Test track filename generation."""

    def test_main_feature_naming(self):
        """Test main feature naming: 'Title (Year).mkv'."""
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='en'
        )
        assert filename == 'The Matrix (1999).mkv'

    def test_main_feature_with_special_characters(self):
        """Test main feature with special characters in title."""
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='Movie: The Sequel',
            year=2020,
            track_name='Main Feature',
            language='en'
        )
        assert filename == 'Movie The Sequel (2020).mkv'

    def test_alternate_language_naming(self):
        """Test alternate language naming: 'Title (Year) - Language.mkv'."""
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='French Version',
            language='fr'
        )
        assert filename == 'The Matrix (1999) - fr.mkv'

    def test_english_variants_no_language_suffix(self):
        """Test that en, en-us, and english variants don't get language suffix."""
        # Test 'en'
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='en'
        )
        assert filename == 'The Matrix (1999).mkv'

        # Test 'en-us'
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='en-us'
        )
        assert filename == 'The Matrix (1999).mkv'

        # Test 'english'
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='english'
        )
        assert filename == 'The Matrix (1999).mkv'

        # Test 'EN-US' (case insensitive)
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='EN-US'
        )
        assert filename == 'The Matrix (1999).mkv'

        # Test 'English' (case insensitive)
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='English'
        )
        assert filename == 'The Matrix (1999).mkv'

    def test_trailer_naming(self):
        """Test trailer naming: 'Name-trailer.mkv'."""
        filename = generate_track_filename(
            track_type='trailers',
            movie_title='The Matrix',
            year=1999,
            track_name='Theatrical Trailer',
            language='en'
        )
        assert filename == 'Theatrical Trailer-trailer.mkv'

    def test_featurette_naming(self):
        """Test featurette naming: 'Name-featurette.mkv'."""
        filename = generate_track_filename(
            track_type='featurettes',
            movie_title='The Matrix',
            year=1999,
            track_name='Making Of',
            language='en'
        )
        assert filename == 'Making Of-featurette.mkv'

    def test_behind_the_scenes_naming(self):
        """Test behind the scenes naming."""
        filename = generate_track_filename(
            track_type='behind_the_scenes',
            movie_title='The Matrix',
            year=1999,
            track_name='Behind The Scenes',
            language='en'
        )
        assert filename == 'Behind The Scenes-behindthescenes.mkv'

    def test_deleted_scenes_naming(self):
        """Test deleted scenes naming."""
        filename = generate_track_filename(
            track_type='deleted_scenes',
            movie_title='The Matrix',
            year=1999,
            track_name='Deleted Scene 1',
            language='en'
        )
        assert filename == 'Deleted Scene 1-deleted.mkv'

    def test_interviews_naming(self):
        """Test interviews naming."""
        filename = generate_track_filename(
            track_type='interviews',
            movie_title='The Matrix',
            year=1999,
            track_name='Director Interview',
            language='en'
        )
        assert filename == 'Director Interview-interview.mkv'

    def test_scenes_naming(self):
        """Test scenes naming."""
        filename = generate_track_filename(
            track_type='scenes',
            movie_title='The Matrix',
            year=1999,
            track_name='Fight Scene',
            language='en'
        )
        assert filename == 'Fight Scene-scene.mkv'

    def test_shorts_naming(self):
        """Test shorts naming."""
        filename = generate_track_filename(
            track_type='shorts',
            movie_title='The Matrix',
            year=1999,
            track_name='Animatrix Short',
            language='en'
        )
        assert filename == 'Animatrix Short-short.mkv'

    def test_other_naming(self):
        """Test other extras naming."""
        filename = generate_track_filename(
            track_type='other',
            movie_title='The Matrix',
            year=1999,
            track_name='Other Extra',
            language='en'
        )
        assert filename == 'Other Extra-other.mkv'

    def test_track_name_sanitization(self):
        """Test that track names are sanitized."""
        filename = generate_track_filename(
            track_type='trailers',
            movie_title='The Matrix',
            year=1999,
            track_name='Trailer: Extended Cut',
            language='en'
        )
        assert filename == 'Trailer Extended Cut-trailer.mkv'

    def test_year_validation(self):
        """Test that year validation works correctly."""
        # Valid year
        filename = generate_track_filename(
            track_type='main_feature',
            movie_title='The Matrix',
            year=1999,
            track_name='Main Feature',
            language='en'
        )
        assert filename == 'The Matrix (1999).mkv'

        # Year too old
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            generate_track_filename(
                track_type='main_feature',
                movie_title='The Matrix',
                year=1800,
                track_name='Main Feature',
                language='en'
            )

        # Year too new
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            generate_track_filename(
                track_type='main_feature',
                movie_title='The Matrix',
                year=2150,
                track_name='Main Feature',
                language='en'
            )

    def test_empty_movie_title(self):
        """Test that empty movie title raises ValueError."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            generate_track_filename(
                track_type='main_feature',
                movie_title='',
                year=1999,
                track_name='Main Feature',
                language='en'
            )

    def test_empty_track_name(self):
        """Test that empty track name raises ValueError."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            generate_track_filename(
                track_type='trailers',
                movie_title='The Matrix',
                year=1999,
                track_name='',
                language='en'
            )


class TestGenerateOutputDirectory:
    """Test output directory generation."""

    def test_main_feature_directory(self):
        """Test main feature directory: '/base/Title (Year)'."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='main_feature'
        )
        assert directory == Path('/media/movies/The Matrix (1999)')

    def test_behind_the_scenes_directory(self):
        """Test behind the scenes directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='behind_the_scenes'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Behind The Scenes')

    def test_deleted_scenes_directory(self):
        """Test deleted scenes directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='deleted_scenes'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Deleted Scenes')

    def test_featurettes_directory(self):
        """Test featurettes directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='featurettes'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Featurettes')

    def test_interviews_directory(self):
        """Test interviews directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='interviews'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Interviews')

    def test_scenes_directory(self):
        """Test scenes directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='scenes'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Scenes')

    def test_shorts_directory(self):
        """Test shorts directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='shorts'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Shorts')

    def test_trailers_directory(self):
        """Test trailers directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='trailers'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Trailers')

    def test_other_directory(self):
        """Test other extras directory."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='other'
        )
        assert directory == Path('/media/movies/The Matrix (1999)/Other')

    def test_title_sanitization(self):
        """Test that movie titles are sanitized in directory paths."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='Movie: The Sequel',
            year=2020,
            track_type='main_feature'
        )
        assert directory == Path('/media/movies/Movie The Sequel (2020)')

    def test_base_path_as_string(self):
        """Test that base_path can be provided as string."""
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='main_feature'
        )
        assert directory == Path('/media/movies/The Matrix (1999)')

    def test_base_path_as_path(self):
        """Test that base_path can be provided as Path."""
        directory = generate_output_directory(
            base_path=Path('/media/movies'),
            movie_title='The Matrix',
            year=1999,
            track_type='main_feature'
        )
        assert directory == Path('/media/movies/The Matrix (1999)')

    def test_year_validation_in_directory(self):
        """Test that year validation works in directory generation."""
        # Valid year
        directory = generate_output_directory(
            base_path='/media/movies',
            movie_title='The Matrix',
            year=1999,
            track_type='main_feature'
        )
        assert directory == Path('/media/movies/The Matrix (1999)')

        # Year too old
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            generate_output_directory(
                base_path='/media/movies',
                movie_title='The Matrix',
                year=1800,
                track_type='main_feature'
            )

        # Year too new
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            generate_output_directory(
                base_path='/media/movies',
                movie_title='The Matrix',
                year=2150,
                track_type='main_feature'
            )

    def test_empty_movie_title_in_directory(self):
        """Test that empty movie title raises ValueError in directory generation."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            generate_output_directory(
                base_path='/media/movies',
                movie_title='',
                year=1999,
                track_type='main_feature'
            )
