from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.cache import cache_service


_RATE_LOCK = threading.Lock()
_RATE_STATE: dict[str, dict[str, Any]] = {}
_HTTP_CLIENT = httpx.Client(timeout=15.0)


class WebSearchService:
    """
    web_search(query): Brave primary, Google fallback (optional).

    Notes:
    - If provider API keys are missing, returns an empty list (safe local mode).
    - Results are cached for 5 minutes via CacheService.
    - Rate limiting is per-project, best-effort 60 requests/min.
    """

    def __init__(self) -> None:
        self._primary_url = "https://api.search.brave.com/res/v1/web/search"

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

    def search(self, query: str, project_id: str | None = None) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        project_key = project_id or "global"
        cache_key = f"websearch:{project_key}:{self._hash_key(q)}"
        cached = cache_service.get(cache_key)
        if cached and isinstance(cached, dict) and isinstance(cached.get("results"), list):
            return cached["results"]

        if self._rate_limited(project_id):
            return []

        results: list[dict[str, Any]] = []

        brave_key = settings.brave_search_api_key
        google_key = settings.google_custom_search_api_key
        google_cx = settings.google_custom_search_cx

        # Brave primary provider
        if brave_key:
            try:
                headers = {"X-Subscription-Token": brave_key, "Accept": "application/json"}
                params = {"q": q, "count": 5}
                resp = _HTTP_CLIENT.get(self._primary_url, headers=headers, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    web = data.get("web") or {}
                    brave_results = web.get("results") or []
                    for r in brave_results[:5]:
                        url = r.get("url") or ""
                        if not url:
                            continue
                        results.append(
                            {
                                "id": self._hash_key(url),
                                "url": url,
                                "title": r.get("title") or "",
                                "snippet": r.get("description") or r.get("content") or "",
                            }
                        )
            except Exception:
                # Provider failures should not crash the entire run.
                results = []

        # Google fallback (optional)
        if not results and google_key and google_cx:
            try:
                params = {"q": q, "key": google_key, "cx": google_cx}
                resp = _HTTP_CLIENT.get("https://www.googleapis.com/customsearch/v1", params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items") or []
                    for it in items[:5]:
                        url = it.get("link") or ""
                        if not url:
                            continue
                        results.append(
                            {
                                "id": self._hash_key(url),
                                "url": url,
                                "title": it.get("title") or "",
                                "snippet": it.get("snippet") or "",
                            }
                        )
            except Exception:
                results = []

        cache_service.set(cache_key, {"results": results, "query": q}, ttl_seconds=300)
        return results


web_search_service = WebSearchService()

