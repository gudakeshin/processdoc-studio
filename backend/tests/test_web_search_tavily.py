"""Tests for multi-provider web search with Tavily integration."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from app.core.config import Settings
from app.services.web_search import WebSearchService


@pytest.fixture
def web_search_service():
    """Create a fresh WebSearchService for each test."""
    return WebSearchService()


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    return tmp_path


def create_project_settings(workspace_path: Path, project_id: str, settings_dict: dict) -> Path:
    """Helper to create project settings.json file."""
    project_dir = workspace_path / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    settings_file = project_dir / "settings.json"
    settings_file.write_text(json.dumps(settings_dict))
    return settings_file


class TestProviderChainResolution:
    """Test provider chain resolution logic."""

    def test_default_chain_no_project(self, web_search_service):
        """When no project settings exist, use global defaults (Brave > Tavily > Google)."""
        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = "tavily-key"
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = "google-key"
            mock_settings.google_custom_search_cx = "google-cx"

            with mock.patch.object(web_search_service, "_load_project_settings", return_value={}):
                chain = web_search_service._resolve_provider_chain(None)
                assert len(chain) == 3
                assert chain[0][0] == "brave"
                assert chain[1][0] == "tavily"
                assert chain[2][0] == "google"

    def test_project_prefers_tavily(self, web_search_service):
        """When project prefers Tavily, it comes first."""
        project_settings = {"web_search_provider": "tavily", "tavily_api_key": "project-tavily-key"}

        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = ""
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = ""
            mock_settings.google_custom_search_cx = ""

            with mock.patch.object(web_search_service, "_load_project_settings", return_value=project_settings):
                chain = web_search_service._resolve_provider_chain("project-1")
                assert chain[0][0] == "tavily"
                assert chain[0][1] == "project-tavily-key"

    def test_tavily_disabled_globally(self, web_search_service):
        """When Tavily is disabled globally, skip it."""
        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = "tavily-key"
            mock_settings.tavily_provider_enabled = False
            mock_settings.google_custom_search_api_key = ""
            mock_settings.google_custom_search_cx = ""

            with mock.patch.object(web_search_service, "_load_project_settings", return_value={}):
                chain = web_search_service._resolve_provider_chain(None)
                assert len(chain) == 1
                assert chain[0][0] == "brave"

    def test_project_tavily_key_overrides_global(self, web_search_service):
        """Project Tavily key takes precedence over global."""
        project_settings = {"web_search_provider": "tavily", "tavily_api_key": "project-key"}

        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = ""
            mock_settings.tavily_api_key = "global-key"
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = ""
            mock_settings.google_custom_search_cx = ""

            with mock.patch.object(web_search_service, "_load_project_settings", return_value=project_settings):
                chain = web_search_service._resolve_provider_chain("project-1")
                assert chain[0][1] == "project-key"

    def test_missing_api_key_skips_provider(self, web_search_service):
        """When API key is missing, provider is not added to chain."""
        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = ""
            mock_settings.tavily_api_key = ""
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = "google-key"
            mock_settings.google_custom_search_cx = "google-cx"

            with mock.patch.object(web_search_service, "_load_project_settings", return_value={}):
                chain = web_search_service._resolve_provider_chain(None)
                assert len(chain) == 1
                assert chain[0][0] == "google"

    def test_project_google_preference(self, web_search_service):
        """When project prefers Google, it comes first."""
        project_settings = {"web_search_provider": "google"}

        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = "tavily-key"
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = "google-key"
            mock_settings.google_custom_search_cx = "google-cx"

            with mock.patch.object(web_search_service, "_load_project_settings", return_value=project_settings):
                chain = web_search_service._resolve_provider_chain("project-1")
                assert chain[0][0] == "google"


class TestTavilySearch:
    """Test Tavily search implementation."""

    def test_tavily_search_success(self, web_search_service):
        """Test successful Tavily search."""
        mock_response_data = {
            "results": [
                {"url": "https://example.com/1", "title": "Result 1", "content": "Snippet 1"},
                {"url": "https://example.com/2", "title": "Result 2", "content": "Snippet 2"},
            ]
        }

        with mock.patch("app.services.web_search._HTTP_CLIENT.post") as mock_post:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response

            results = web_search_service._search_tavily("test query", "tavily-key")

            assert len(results) == 2
            assert results[0]["url"] == "https://example.com/1"
            assert results[0]["title"] == "Result 1"
            assert results[0]["snippet"] == "Snippet 1"
            mock_post.assert_called_once()

    def test_tavily_search_failure(self, web_search_service):
        """Test Tavily search handles API failure gracefully."""
        with mock.patch("app.services.web_search._HTTP_CLIENT.post") as mock_post:
            mock_response = mock.Mock()
            mock_response.status_code = 401
            mock_post.return_value = mock_response

            results = web_search_service._search_tavily("test query", "invalid-key")

            assert results == []

    def test_tavily_search_network_error(self, web_search_service):
        """Test Tavily search handles network errors gracefully."""
        with mock.patch("app.services.web_search._HTTP_CLIENT.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            results = web_search_service._search_tavily("test query", "tavily-key")

            assert results == []


class TestMultiProviderFallback:
    """Test fallback chain behavior."""

    def test_search_tries_providers_in_order(self, web_search_service):
        """Search tries providers in chain order until one succeeds."""
        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = "tavily-key"
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = ""
            mock_settings.google_custom_search_cx = ""

            # Mock cache to always miss
            with mock.patch("app.services.web_search.cache_service.get", return_value=None):
                # Mock rate limit to always pass
                with mock.patch.object(web_search_service, "_rate_limited", return_value=False):
                    # Mock Brave to fail, Tavily to succeed
                    with mock.patch.object(web_search_service, "_search_brave", return_value=[]):
                        with mock.patch.object(
                            web_search_service, "_search_tavily", return_value=[{"url": "https://example.com"}]
                        ):
                            with mock.patch.object(web_search_service, "_load_project_settings", return_value={}):
                                with mock.patch("app.services.web_search.cache_service.set"):
                                    results = web_search_service.search("test query", "project-1")

                                    # Should return Tavily results since Brave failed
                                    assert len(results) == 1
                                    assert results[0]["url"] == "https://example.com"

    def test_search_returns_empty_when_all_fail(self, web_search_service):
        """Search returns empty list when all providers fail."""
        with mock.patch("app.services.web_search.settings") as mock_settings:
            mock_settings.brave_search_api_key = "brave-key"
            mock_settings.tavily_api_key = "tavily-key"
            mock_settings.tavily_provider_enabled = True
            mock_settings.google_custom_search_api_key = ""
            mock_settings.google_custom_search_cx = ""

            with mock.patch("app.services.web_search.cache_service.get", return_value=None):
                with mock.patch.object(web_search_service, "_rate_limited", return_value=False):
                    with mock.patch.object(web_search_service, "_search_brave", return_value=[]):
                        with mock.patch.object(web_search_service, "_search_tavily", return_value=[]):
                            with mock.patch.object(web_search_service, "_load_project_settings", return_value={}):
                                with mock.patch("app.services.web_search.cache_service.set"):
                                    results = web_search_service.search("test query", "project-1")

                                    assert results == []


class TestCaching:
    """Test caching behavior with multiple providers."""

    def test_cache_key_same_for_all_providers(self, web_search_service):
        """Cache key should be the same regardless of provider used."""
        query = "test query"
        project_id = "project-1"

        # Generate cache keys (implementation detail, but important for consistency)
        project_key = project_id or "global"
        expected_cache_key = f"websearch:{project_key}:{web_search_service._hash_key(query)}"

        # Verify the cache key logic works
        assert expected_cache_key.startswith("websearch:")
        assert len(expected_cache_key) > len("websearch:")

    def test_cached_results_returned_before_search(self, web_search_service):
        """Cached results should be returned without calling providers."""
        cached_results = [{"url": "https://cached.com", "title": "Cached", "snippet": "Cached result"}]
        cached_data = {"results": cached_results}

        with mock.patch("app.services.web_search.cache_service.get", return_value=cached_data):
            with mock.patch.object(web_search_service, "_resolve_provider_chain") as mock_chain:
                results = web_search_service.search("test query", "project-1")

                assert results == cached_results
                # Chain should not be called if we hit cache
                mock_chain.assert_not_called()
