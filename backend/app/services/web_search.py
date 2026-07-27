from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.cache import cache_service
from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)
_RATE_LOCK = threading.Lock()
_RATE_STATE: dict[str, dict[str, Any]] = {}
_HTTP_CLIENT = httpx.Client(timeout=15.0)

# Singleflight: prevents duplicate concurrent requests for the same cache_key.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}


class WebSearchService:
    """Multi-provider web search: Tavily, Brave, Google.

    Notes:
    - If provider API keys are missing, returns an empty list (safe local mode).
    - Results are cached for 5 minutes via CacheService.
    - Rate limiting is per-project, best-effort 60 requests/min.
    - Provider selection: project preference > global defaults (Brave > Tavily > Google).
    """

    def __init__(self) -> None:
        self._brave_url = "https://api.search.brave.com/res/v1/web/search"
        self._tavily_url = "https://api.tavily.com/search"
        self._google_url = "https://www.googleapis.com/customsearch/v1"

    def _hash_key(self, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    def _rate_limited(self, project_id: str | None) -> bool:
        if not project_id:
            return False

        limit = 60
        window_s = 60
        key = f"rate:web_search:{project_id}"
        now = time.time()

        with _RATE_LOCK:
            state = _RATE_STATE.get(key)
            if not state or now >= float(state.get("reset_at", 0)):
                _RATE_STATE[key] = {"count": 1, "reset_at": now + window_s}
                return False

            if int(state.get("count", 0)) >= limit:
                return True

            state["count"] = int(state.get("count", 0)) + 1
            return False

    def _load_project_settings(self, project_id: str | None) -> dict[str, Any]:
        """Load settings from workspace/{project_id}/settings.json."""
        if not project_id:
            return {}
        try:
            settings_path = workspace_path(project_id) / "settings.json"
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            _LOG.warning("%s: suppressed error: %s", '_load_project_settings', exc)
        return {}

    def _resolve_provider_chain(self, project_id: str | None) -> list[tuple[str, str]]:
        """Resolve provider chain: (provider_name, api_key).

        Returns list of (provider, key) tuples in priority order.
        Empty key means provider is configured but key is missing (skip it).
        """
        chain: list[tuple[str, str]] = []
        project_settings = self._load_project_settings(project_id)

        # Check for project-level preference
        preferred = project_settings.get("web_search_provider", "").strip().lower()

        if preferred == "tavily":
            api_key = project_settings.get("tavily_api_key") or settings.tavily_api_key
            if api_key:
                chain.append(("tavily", api_key))
            # Add fallbacks
            if settings.brave_search_api_key:
                chain.append(("brave", settings.brave_search_api_key))
            if settings.google_custom_search_api_key and settings.google_custom_search_cx:
                chain.append(("google", settings.google_custom_search_api_key))
        elif preferred == "google":
            if settings.google_custom_search_api_key and settings.google_custom_search_cx:
                chain.append(("google", settings.google_custom_search_api_key))
            # Add fallbacks
            if settings.brave_search_api_key:
                chain.append(("brave", settings.brave_search_api_key))
            if settings.tavily_api_key and settings.tavily_provider_enabled:
                chain.append(("tavily", settings.tavily_api_key))
        else:
            # Default: Brave > Tavily > Google
            if settings.brave_search_api_key:
                chain.append(("brave", settings.brave_search_api_key))
            if settings.tavily_api_key and settings.tavily_provider_enabled:
                chain.append(("tavily", settings.tavily_api_key))
            if settings.google_custom_search_api_key and settings.google_custom_search_cx:
                chain.append(("google", settings.google_custom_search_api_key))

        return chain

    def _search_brave(self, query: str, api_key: str) -> list[dict[str, Any]]:
        """Search via Brave API."""
        try:
            headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
            params = {"q": query, "count": 5}
            resp = _HTTP_CLIENT.get(self._brave_url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                web = data.get("web") or {}
                results = []
                for r in (web.get("results") or [])[:5]:
                    url = r.get("url") or ""
                    if url:
                        results.append(
                            {
                                "id": self._hash_key(url),
                                "url": url,
                                "title": r.get("title") or "",
                                "snippet": r.get("description") or r.get("content") or "",
                            }
                        )
                return results
        except Exception as e:
            _LOG.debug(f"Brave search failed: {e}")
        return []

    def _search_tavily(self, query: str, api_key: str) -> list[dict[str, Any]]:
        """Search via Tavily API."""
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"query": query, "max_results": 5, "include_answer": False}
            resp = _HTTP_CLIENT.post(self._tavily_url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in (data.get("results") or [])[:5]:
                    url = r.get("url") or ""
                    if url:
                        results.append(
                            {
                                "id": self._hash_key(url),
                                "url": url,
                                "title": r.get("title") or "",
                                "snippet": r.get("content") or "",
                            }
                        )
                return results
        except Exception as e:
            _LOG.debug(f"Tavily search failed: {e}")
        return []

    def _search_google(self, query: str, api_key: str) -> list[dict[str, Any]]:
        """Search via Google Custom Search API."""
        try:
            google_cx = settings.google_custom_search_cx
            if not google_cx:
                return []
            params = {"q": query, "key": api_key, "cx": google_cx}
            resp = _HTTP_CLIENT.get(self._google_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for it in (data.get("items") or [])[:5]:
                    url = it.get("link") or ""
                    if url:
                        results.append(
                            {
                                "id": self._hash_key(url),
                                "url": url,
                                "title": it.get("title") or "",
                                "snippet": it.get("snippet") or "",
                            }
                        )
                return results
        except Exception as e:
            _LOG.debug(f"Google search failed: {e}")
        return []

    def search(self, query: str, project_id: str | None = None) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        project_key = project_id or "global"
        cache_key = f"websearch:{project_key}:{self._hash_key(q)}"

        # Fast path: already cached.
        cached = cache_service.get(cache_key)
        if cached and isinstance(cached, dict) and isinstance(cached.get("results"), list):
            return cached["results"]

        # Singleflight: if an identical query is already in-flight, wait for it rather than
        # issuing a duplicate request. This prevents concurrent agents from hitting the same
        # search provider multiple times for the same query.
        with _INFLIGHT_LOCK:
            if cache_key in _INFLIGHT:
                waiter_event = _INFLIGHT[cache_key]
                is_owner = False
            else:
                waiter_event = threading.Event()
                _INFLIGHT[cache_key] = waiter_event
                is_owner = True

        if not is_owner:
            waiter_event.wait(timeout=15.0)
            cached = cache_service.get(cache_key)
            return cached.get("results", []) if isinstance(cached, dict) else []

        # This thread is the owner: perform the actual search.
        try:
            if self._rate_limited(project_id):
                return []

            results: list[dict[str, Any]] = []
            provider_chain = self._resolve_provider_chain(project_id)

            # Try each provider in sequence
            for provider_name, api_key in provider_chain:
                try:
                    if provider_name == "brave":
                        results = self._search_brave(q, api_key)
                    elif provider_name == "tavily":
                        results = self._search_tavily(q, api_key)
                    elif provider_name == "google":
                        results = self._search_google(q, api_key)

                    if results:
                        break
                except Exception as e:
                    _LOG.debug(f"Provider {provider_name} failed: {e}")
                    continue

            cache_service.set(cache_key, {"results": results, "query": q}, ttl_seconds=300)
            return results
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(cache_key, None)
            waiter_event.set()


web_search_service = WebSearchService()

