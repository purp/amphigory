import os
from typing import List, Dict, Any, Optional
import httpx

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


async def search_movies(query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """Search TMDB for movies matching query."""
    if not TMDB_API_KEY:
        return []

    # Helper to parse results
    def parse_results(data):
        results = []
        for movie in data.get("results", []):
            movie_id = movie.get("id")
            title = movie.get("title")
            if not movie_id or not title:
                continue  # Skip malformed entries

            release_date = movie.get("release_date", "")
            try:
                movie_year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
            except (ValueError, TypeError):
                movie_year = None

            results.append({
                "id": movie_id,
                "title": title,
                "year": movie_year,
                "overview": movie.get("overview", ""),
            })
        return results

    try:
        async with httpx.AsyncClient() as client:
            # First try with year if provided
            params = {"api_key": TMDB_API_KEY, "query": query}
            if year:
                params["year"] = year

            response = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params)
            if response.status_code != 200:
                return []

            results = parse_results(response.json())

            # If no results with year, retry without year filter
            if not results and year:
                params_no_year = {"api_key": TMDB_API_KEY, "query": query}
                response = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params_no_year)
                if response.status_code == 200:
                    results = parse_results(response.json())

            return results
    except (httpx.RequestError, httpx.TimeoutException):
        return []


async def get_external_ids(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Get external IDs (IMDB, etc.) for a TMDB movie.

    Args:
        tmdb_id: The TMDB movie ID

    Returns:
        Dictionary with external IDs like {"imdb_id": "tt0347149", ...} or None on error
    """
    if not TMDB_API_KEY:
        return None

    params = {"api_key": TMDB_API_KEY}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TMDB_BASE_URL}/movie/{tmdb_id}/external_ids",
                params=params
            )
            if response.status_code != 200:
                return None
            return response.json()
    except (httpx.RequestError, httpx.TimeoutException):
        return None
