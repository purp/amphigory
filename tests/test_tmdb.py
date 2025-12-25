import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestTMDBSearch:
    @pytest.mark.asyncio
    async def test_search_returns_movie_results(self):
        """TMDB search returns list of matching movies."""
        from amphigory.tmdb import search_movies

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": 603, "title": "The Matrix", "release_date": "1999-03-30", "overview": "A hacker..."},
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("The Matrix")

        assert len(results) == 1
        assert results[0]["title"] == "The Matrix"
        assert results[0]["year"] == 1999

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self):
        """TMDB search can filter by year."""
        from amphigory.tmdb import search_movies

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": 603, "title": "The Matrix", "release_date": "1999-03-30", "overview": "A hacker..."},
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("The Matrix", year=1999)

        # Verify the year parameter was passed
        call_args = mock_instance.get.call_args
        assert call_args[1]['params']['year'] == 1999

    @pytest.mark.asyncio
    async def test_search_without_api_key_returns_empty(self):
        """TMDB search returns empty list when API key is missing."""
        from amphigory.tmdb import search_movies

        with patch('amphigory.tmdb.TMDB_API_KEY', ''):
            results = await search_movies("The Matrix")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_api_error(self):
        """TMDB search returns empty list on API error."""
        from amphigory.tmdb import search_movies

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("The Matrix")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_missing_release_date(self):
        """TMDB search handles movies without release dates."""
        from amphigory.tmdb import search_movies

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": 123, "title": "Unreleased Movie", "overview": "Coming soon..."},
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("Unreleased Movie")

        assert len(results) == 1
        assert results[0]["year"] is None
