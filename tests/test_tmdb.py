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

    @pytest.mark.asyncio
    async def test_search_handles_apostrophes(self):
        """TMDB search correctly handles titles with apostrophes."""
        from amphigory.tmdb import search_movies

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": 4935, "title": "Howl's Moving Castle", "release_date": "2004-11-20", "overview": "A studio ghibli film"},
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("Howl's Moving Castle")

        # Verify the query was passed correctly (httpx handles URL encoding)
        call_args = mock_instance.get.call_args
        assert call_args[1]['params']['query'] == "Howl's Moving Castle"

        assert len(results) == 1
        assert results[0]["title"] == "Howl's Moving Castle"
        assert results[0]["year"] == 2004

    @pytest.mark.asyncio
    async def test_search_falls_back_without_year_if_no_results(self):
        """If year-filtered search returns no results, retry without year."""
        from amphigory.tmdb import search_movies

        # First call with year returns empty, second without year returns results
        mock_response_empty = MagicMock()
        mock_response_empty.status_code = 200
        mock_response_empty.json.return_value = {"results": []}

        mock_response_with_results = MagicMock()
        mock_response_with_results.status_code = 200
        mock_response_with_results.json.return_value = {
            "results": [
                {"id": 4935, "title": "Howl's Moving Castle", "release_date": "2004-11-20", "overview": "A studio ghibli film"}
            ]
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = [mock_response_empty, mock_response_with_results]
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                results = await search_movies("Howl's Moving Castle", year=2004)

        # Verify two calls were made
        assert mock_instance.get.call_count == 2

        # First call should have year parameter
        first_call = mock_instance.get.call_args_list[0]
        assert first_call[1]['params']['year'] == 2004

        # Second call should not have year parameter
        second_call = mock_instance.get.call_args_list[1]
        assert 'year' not in second_call[1]['params']

        # Should return results from second call
        assert len(results) == 1
        assert results[0]["title"] == "Howl's Moving Castle"


class TestTMDBExternalIds:
    @pytest.mark.asyncio
    async def test_get_external_ids_returns_imdb_id(self):
        """get_external_ids returns IMDB ID and other external IDs."""
        from amphigory.tmdb import get_external_ids

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 4935,
            "imdb_id": "tt0347149",
            "facebook_id": "HowlsMovingCastle",
            "instagram_id": None,
            "twitter_id": None,
        }

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                result = await get_external_ids(4935)

        assert result is not None
        assert result["imdb_id"] == "tt0347149"
        assert result["id"] == 4935

    @pytest.mark.asyncio
    async def test_get_external_ids_without_api_key_returns_none(self):
        """get_external_ids returns None when API key is missing."""
        from amphigory.tmdb import get_external_ids

        with patch('amphigory.tmdb.TMDB_API_KEY', ''):
            result = await get_external_ids(4935)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_external_ids_handles_api_error(self):
        """get_external_ids returns None on API error."""
        from amphigory.tmdb import get_external_ids

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                result = await get_external_ids(999999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_external_ids_handles_network_error(self):
        """get_external_ids returns None on network error."""
        from amphigory.tmdb import get_external_ids
        import httpx

        with patch('amphigory.tmdb.httpx.AsyncClient') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.RequestError("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with patch('amphigory.tmdb.TMDB_API_KEY', 'test_key'):
                result = await get_external_ids(4935)

        assert result is None
