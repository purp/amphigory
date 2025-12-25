"""Plex-compatible track naming and directory structure generation."""

from pathlib import Path
from typing import Union


# Invalid filename characters that need to be removed
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

# Plex suffix mappings for extras (lowercase, no spaces)
PLEX_SUFFIXES = {
    'behind_the_scenes': '-behindthescenes',
    'deleted_scenes': '-deleted',
    'featurettes': '-featurette',
    'interviews': '-interview',
    'scenes': '-scene',
    'shorts': '-short',
    'trailers': '-trailer',
    'other': '-other',
}

# Plex directory mappings for extras (Title Case)
PLEX_DIRECTORIES = {
    'behind_the_scenes': 'Behind The Scenes',
    'deleted_scenes': 'Deleted Scenes',
    'featurettes': 'Featurettes',
    'interviews': 'Interviews',
    'scenes': 'Scenes',
    'shorts': 'Shorts',
    'trailers': 'Trailers',
    'other': 'Other',
}


def sanitize_filename(name: str) -> str:
    """Remove invalid filename characters and prevent path traversal.

    Args:
        name: The filename or path component to sanitize

    Returns:
        Sanitized string with invalid characters removed

    Raises:
        ValueError: If the sanitized result is empty or whitespace-only
    """
    # Check for empty/whitespace-only input
    if not name or not name.strip():
        raise ValueError("Filename cannot be empty or whitespace-only")

    # Remove invalid filename characters
    result = name
    for char in INVALID_FILENAME_CHARS:
        result = result.replace(char, '')

    # Prevent path traversal by removing '..' sequences
    result = result.replace('..', '')

    # Strip leading/trailing whitespace and dots
    result = result.strip()
    result = result.strip('.')

    # Check if sanitization resulted in empty string
    if not result:
        raise ValueError("Filename sanitization resulted in empty string")

    return result


def generate_track_filename(
    track_type: str,
    movie_title: str,
    year: int,
    track_name: str,
    language: str
) -> str:
    """Generate a Plex-compatible filename for a track.

    Args:
        track_type: Type of track (main_feature, trailers, featurettes, etc.)
        movie_title: The movie title
        year: The movie release year
        track_name: The name of the track
        language: Language code (e.g., 'en', 'fr')

    Returns:
        Plex-compatible filename with .mkv extension

    Raises:
        ValueError: If required inputs are invalid

    Examples:
        Main feature: "The Matrix (1999).mkv"
        Alternate language: "The Matrix (1999) - fr.mkv"
        Extras: "Making Of-featurette.mkv"
    """
    # Validate year is reasonable
    if not isinstance(year, int) or year < 1900 or year > 2100:
        raise ValueError(f"Year must be between 1900 and 2100, got: {year}")

    # Sanitize inputs (will raise ValueError if empty/whitespace-only)
    sanitized_title = sanitize_filename(movie_title)
    sanitized_track_name = sanitize_filename(track_name)

    # Main feature naming
    if track_type == 'main_feature':
        # Check if this is an alternate language version (not en/en-us/english)
        if language and language.lower() not in ('en', 'en-us', 'english'):
            return f"{sanitized_title} ({year}) - {language}.mkv"
        else:
            return f"{sanitized_title} ({year}).mkv"

    # Extras naming: "Track Name-suffix.mkv"
    suffix = PLEX_SUFFIXES.get(track_type, '-other')
    return f"{sanitized_track_name}{suffix}.mkv"


def generate_output_directory(
    base_path: Union[str, Path],
    movie_title: str,
    year: int,
    track_type: str
) -> Path:
    """Generate output directory path following Plex conventions.

    Args:
        base_path: Base directory for movies (e.g., '/media/movies')
        movie_title: The movie title
        year: The movie release year
        track_type: Type of track (main_feature, trailers, featurettes, etc.)

    Returns:
        Path object for the output directory

    Raises:
        ValueError: If required inputs are invalid

    Examples:
        Main feature: "/media/movies/The Matrix (1999)"
        Extras: "/media/movies/The Matrix (1999)/Behind The Scenes"
    """
    # Convert base_path to Path if it's a string
    base = Path(base_path)

    # Validate year is reasonable
    if not isinstance(year, int) or year < 1900 or year > 2100:
        raise ValueError(f"Year must be between 1900 and 2100, got: {year}")

    # Sanitize movie title (will raise ValueError if empty/whitespace-only)
    sanitized_title = sanitize_filename(movie_title)

    # Movie directory: "Title (Year)"
    movie_dir = base / f"{sanitized_title} ({year})"

    # Main feature goes in the movie directory
    if track_type == 'main_feature':
        return movie_dir

    # Extras go in subdirectories
    subdir = PLEX_DIRECTORIES.get(track_type, 'Other')
    return movie_dir / subdir
