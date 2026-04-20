"""
Wiki caching layer for Phase 5: Query optimization and performance.

Implements:
1. LRU cache for wiki queries
2. Full-text search index
3. Query result memoization
4. Cache invalidation on wiki updates
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Cache configuration
DEFAULT_CACHE_TTL = 3600  # 1 hour
MAX_CACHE_SIZE = 1000  # Max cached items
CACHE_INVALIDATION_THRESHOLD = 0.1  # 10% change threshold


class LRUCache:
    """LRU cache implementation for wiki queries."""

    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = DEFAULT_CACHE_TTL):
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of items to cache
            ttl: Time-to-live in seconds for cached items
        """
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()
        self.timestamps = {}

    def get(self, key: str) -> Any | None:
        """Get item from cache (moves to end - most recently used)."""
        if key not in self.cache:
            return None

        # Check if expired
        if time.time() - self.timestamps[key] > self.ttl:
            del self.cache[key]
            del self.timestamps[key]
            return None

        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: Any) -> None:
        """Put item in cache (evicts oldest if full)."""
        if key in self.cache:
            # Update existing
            self.cache.move_to_end(key)
            self.cache[key] = value
            self.timestamps[key] = time.time()
        else:
            # New item
            if len(self.cache) >= self.max_size:
                # Evict oldest (first item)
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                del self.timestamps[oldest_key]

            self.cache[key] = value
            self.timestamps[key] = time.time()

    def invalidate(self, pattern: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: If None, clear all. Otherwise, clear matching keys.

        Returns:
            Number of items invalidated
        """
        if pattern is None:
            count = len(self.cache)
            self.cache.clear()
            self.timestamps.clear()
            return count

        keys_to_delete = [k for k in self.cache if pattern in k]
        for key in keys_to_delete:
            del self.cache[key]
            del self.timestamps[key]
        return len(keys_to_delete)

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
            "hit_rate": getattr(self, "hit_rate", 0),
        }


class FullTextSearchIndex:
    """Full-text search index for wiki pages."""

    def __init__(self):
        """Initialize search index."""
        self.index = {}  # word -> set of page_ids
        self.page_texts = {}  # page_id -> text content

    def index_page(self, page_id: str, text: str, title: str) -> None:
        """
        Index a page for full-text search.

        Args:
            page_id: Page ID
            text: Page body text
            title: Page title
        """
        # Remove old index for this page
        if page_id in self.page_texts:
            old_text = self.page_texts[page_id]
            for word in self._tokenize(old_text):
                if word in self.index:
                    self.index[word].discard(page_id)
                    if not self.index[word]:
                        del self.index[word]

        # Index new content
        combined = f"{title} {text}".lower()
        self.page_texts[page_id] = combined

        for word in self._tokenize(combined):
            if word not in self.index:
                self.index[word] = set()
            self.index[word].add(page_id)

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Search for pages matching query.

        Args:
            query: Search query (space-separated terms)
            limit: Maximum results to return

        Returns:
            List of (page_id, relevance_score) tuples
        """
        query_words = self._tokenize(query)
        if not query_words:
            return []

        # Find pages matching all query words
        matching_pages = None
        for word in query_words:
            if word in self.index:
                if matching_pages is None:
                    matching_pages = self.index[word].copy()
                else:
                    matching_pages &= self.index[word]  # Intersection
            else:
                matching_pages = set()
                break

        if not matching_pages:
            return []

        # Score by number of matching words
        scored = [
            {
                "page_id": page_id,
                "relevance": sum(
                    1 for word in query_words
                    if word in self.page_texts.get(page_id, "")
                ) / len(query_words)
            }
            for page_id in matching_pages
        ]

        # Sort by relevance descending
        scored.sort(key=lambda x: x["relevance"], reverse=True)
        return scored[:limit]

    def remove_page(self, page_id: str) -> None:
        """Remove page from index."""
        if page_id in self.page_texts:
            text = self.page_texts[page_id]
            for word in self._tokenize(text):
                if word in self.index:
                    self.index[word].discard(page_id)
                    if not self.index[word]:
                        del self.index[word]
            del self.page_texts[page_id]

    def stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "indexed_pages": len(self.page_texts),
            "vocabulary_size": len(self.index),
        }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into words."""
        return [
            word for word in text.lower().split()
            if len(word) > 2 and word.isalpha()
        ]


class WikiQueryCache:
    """Unified cache for wiki queries."""

    def __init__(self):
        """Initialize query cache."""
        self.query_cache = LRUCache(max_size=MAX_CACHE_SIZE)
        self.search_index = FullTextSearchIndex()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
        }

    def cache_key(self, operation: str, *args, **kwargs) -> str:
        """Generate cache key from operation and parameters."""
        param_str = json.dumps(
            {
                "op": operation,
                "args": args,
                "kwargs": sorted(kwargs.items())
            },
            default=str,
            sort_keys=True
        )
        return hashlib.md5(param_str.encode(), usedforsecurity=False).hexdigest()

    def get_cached_query(self, key: str) -> Any | None:
        """Get cached query result."""
        result = self.query_cache.get(key)
        if result:
            self.stats["hits"] += 1
        else:
            self.stats["misses"] += 1
        return result

    def cache_query_result(self, key: str, result: Any) -> None:
        """Cache query result."""
        self.query_cache.put(key, result)

    def invalidate_for_changes(self, changed_pages: list[str]) -> int:
        """
        Invalidate cache for changed pages.

        Args:
            changed_pages: List of page IDs that changed

        Returns:
            Number of cache entries invalidated
        """
        invalidated = 0
        for page_id in changed_pages:
            # Invalidate queries involving this page
            invalidated += self.query_cache.invalidate(page_id)
            # Remove from search index
            self.search_index.remove_page(page_id)

        self.stats["invalidations"] += invalidated
        logger.info(f"Cache invalidation: {invalidated} entries cleared")
        return invalidated

    def clear_all(self) -> None:
        """Clear all caches."""
        self.query_cache.invalidate()
        self.search_index = FullTextSearchIndex()
        logger.info("All caches cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        hit_rate = (
            self.stats["hits"] / (self.stats["hits"] + self.stats["misses"])
            if (self.stats["hits"] + self.stats["misses"]) > 0
            else 0
        )

        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": round(hit_rate, 3),
            "invalidations": self.stats["invalidations"],
            "query_cache": self.query_cache.stats(),
            "search_index": self.search_index.stats(),
        }


# Global cache instance
_wiki_cache = WikiQueryCache()


def cached_query(ttl: int = DEFAULT_CACHE_TTL):
    """
    Decorator for caching wiki query results.

    Args:
        ttl: Time-to-live in seconds

    Returns:
        Decorated function with caching
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Generate cache key
            key = _wiki_cache.cache_key(func.__name__, *args, **kwargs)

            # Check cache
            cached_result = _wiki_cache.get_cached_query(key)
            if cached_result is not None:
                logger.debug(f"Cache hit: {func.__name__}")
                return cached_result

            # Execute and cache
            logger.debug(f"Cache miss: {func.__name__}")
            result = func(*args, **kwargs)
            _wiki_cache.cache_query_result(key, result)
            return result

        return wrapper
    return decorator


def get_wiki_cache() -> WikiQueryCache:
    """Get global wiki cache instance."""
    return _wiki_cache
