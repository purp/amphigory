import os
from typing import List, Dict, Any, Optional
import httpx

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


async def search_movies(query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """Search TMDB for movies matching query."""
    if not TMDB_API_KEY:
        return []

    params = {"api_key": TMDB_API_KEY, "query": query}
    if year:
        params["year"] = year

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{TMDB_BASE_URL}/search/movie", params=params)
        if response.status_code != 200:
            return []
        data = response.json()

        results = []
        for movie in data.get("results", []):
            release_date = movie.get("release_date", "")
            year = int(release_date[:4]) if release_date else None
            results.append({
                "id": movie["id"],
                "title": movie["title"],
                "year": year,
                "overview": movie.get("overview", ""),
            })
        return results
