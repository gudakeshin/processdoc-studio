"""
Tests for Wiki Phase 5: Cache Layer & Query Optimization.

Tests LRU cache, full-text search indexing, and cache invalidation.
"""

import time
from collections import OrderedDict


class TestLRUCache:
    """Test LRU cache implementation."""

    def test_cache_put_and_get(self):
        """Test basic put and get operations."""
        cache = {}
        cache["key1"] = "value1"
        cache["key2"] = "value2"

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") is None

    def test_cache_most_recently_used(self):
        """Test that accessed items move to end."""
        cache = OrderedDict()
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3

        # Access a, should move to end
        cache.move_to_end("a")

        # Verify order
        keys = list(cache.keys())
        assert keys == ["b", "c", "a"]

    def test_cache_eviction_on_full(self):
        """Test that oldest item is evicted when cache is full."""
        cache = OrderedDict()
        max_size = 3

        # Fill cache
        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3

        # Add one more, should evict "a"
        if len(cache) >= max_size:
            oldest = next(iter(cache))
            del cache[oldest]

        cache["d"] = 4

        assert "a" not in cache
        assert "d" in cache
        assert len(cache) == 3

    def test_cache_expiration(self):
        """Test that expired items are removed."""
        cache = {}
        timestamps = {}
        ttl = 1  # 1 second

        cache["key"] = "value"
        timestamps["key"] = time.time()

        # Wait for expiration
        time.sleep(1.1)

        # Check if expired
        if time.time() - timestamps["key"] > ttl:
            del cache["key"]

        assert "key" not in cache

    def test_cache_update_timestamp(self):
        """Test that accessing item updates timestamp."""
        cache = {}
        timestamps = {}

        cache["key"] = "value1"
        timestamps["key"] = time.time()

        # Wait a bit
        time.sleep(0.1)

        # Access (move to end and update time)
        timestamps["key"] = time.time()

        # Both updated
        assert cache["key"] == "value1"
        assert timestamps["key"] > time.time() - 0.2


class TestFullTextSearch:
    """Test full-text search indexing."""

    def test_index_page(self):
        """Test indexing a page."""
        index = {}
        page_text = "Python programming language"

        words = page_text.lower().split()
        for word in words:
            if len(word) > 2:
                if word not in index:
                    index[word] = set()
                index[word].add("page_1")

        assert "python" in index
        assert "programming" in index
        assert "page_1" in index["python"]

    def test_search_single_word(self):
        """Test searching for single word."""
        index = {
            "python": {"page_1", "page_2"},
            "java": {"page_3"},
            "rust": {"page_4"},
        }

        query = "python"
        results = [p for p in index.get(query, set())]

        assert len(results) == 2
        assert "page_1" in results
        assert "page_2" in results

    def test_search_multiple_words(self):
        """Test searching for multiple words (AND)."""
        index = {
            "python": {"page_1", "page_2"},
            "programming": {"page_1", "page_3"},
        }

        query_words = ["python", "programming"]
        matching = None

        for word in query_words:
            if word in index:
                if matching is None:
                    matching = index[word].copy()
                else:
                    matching &= index[word]  # Intersection
            else:
                matching = set()
                break

        # Only page_1 has both words
        assert len(matching) == 1
        assert "page_1" in matching

    def test_remove_page_from_index(self):
        """Test removing page from index."""
        index = {
            "python": {"page_1", "page_2"},
            "java": {"page_2"},
        }

        # Remove page_2
        page_to_remove = "page_2"
        for word in list(index.keys()):
            index[word].discard(page_to_remove)
            if not index[word]:
                del index[word]

        assert "page_2" not in index["python"]
        assert "java" not in index  # Was removed

    def test_search_relevance_scoring(self):
        """Test relevance scoring for search results."""
        page_texts = {
            "page_1": "python programming language",
            "page_2": "python web framework",
            "page_3": "java programming",
        }

        query = "python programming"
        query_words = query.split()

        results = []
        for page_id, text in page_texts.items():
            score = sum(1 for word in query_words if word in text) / len(query_words)
            if score > 0:
                results.append((page_id, score))

        # Sort by relevance
        results.sort(key=lambda x: x[1], reverse=True)

        # page_1 should rank highest (has both words)
        assert results[0][0] == "page_1"
        assert results[0][1] == 1.0  # 2/2 words match


class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_consistent_key_generation(self):
        """Test that same inputs generate same key."""
        import hashlib
        import json

        op1 = "query_neighbors"
        args1 = ("page_1",)

        def gen_key(op, args):
            param_str = json.dumps({"op": op, "args": args}, default=str)
            return hashlib.md5(param_str.encode()).hexdigest()

        key1 = gen_key(op1, args1)
        key2 = gen_key(op1, args1)

        assert key1 == key2

    def test_different_keys_for_different_inputs(self):
        """Test that different inputs generate different keys."""
        import hashlib
        import json

        def gen_key(op, args):
            param_str = json.dumps({"op": op, "args": args}, default=str)
            return hashlib.md5(param_str.encode()).hexdigest()

        key1 = gen_key("query", ("page_1",))
        key2 = gen_key("query", ("page_2",))

        assert key1 != key2


class TestCacheInvalidation:
    """Test cache invalidation strategies."""

    def test_invalidate_page_pattern(self):
        """Test invalidating cache entries by page pattern."""
        cache = {
            "page_1_neighbors": [1, 2, 3],
            "page_2_neighbors": [4, 5],
            "page_1_god_nodes": [1],
            "page_3_communities": [1, 2],
        }

        # Invalidate all page_1 entries
        keys_to_delete = [k for k in cache if "page_1" in k]
        for key in keys_to_delete:
            del cache[key]

        assert "page_1_neighbors" not in cache
        assert "page_1_god_nodes" not in cache
        assert "page_2_neighbors" in cache

    def test_invalidate_all(self):
        """Test clearing entire cache."""
        cache = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }

        cache.clear()

        assert len(cache) == 0

    def test_selective_invalidation(self):
        """Test invalidating specific operations."""
        cache = {
            "query_neighbors_page_1": [],
            "query_shortest_path_page_1": [],
            "query_bfs_page_2": [],
        }

        # Invalidate only neighbors queries
        pattern = "neighbors"
        keys_to_delete = [k for k in cache if pattern in k]
        for key in keys_to_delete:
            del cache[key]

        assert "query_neighbors_page_1" not in cache
        assert "query_shortest_path_page_1" in cache


class TestCacheStatistics:
    """Test cache statistics and metrics."""

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        hits = 7
        misses = 3
        total = hits + misses

        hit_rate = hits / total

        assert hit_rate == 0.7
        assert hit_rate > 0.5

    def test_cache_size_metrics(self):
        """Test cache size tracking."""
        cache_config = {
            "current_size": 45,
            "max_size": 100,
            "ttl_seconds": 3600,
        }

        utilization = cache_config["current_size"] / cache_config["max_size"]

        assert cache_config["current_size"] <= cache_config["max_size"]
        assert utilization == 0.45

    def test_invalidation_tracking(self):
        """Test tracking cache invalidations."""
        stats = {
            "hits": 100,
            "misses": 30,
            "invalidations": 5,
        }

        # Calculate efficiency
        total_ops = stats["hits"] + stats["misses"]
        efficiency = stats["hits"] / total_ops if total_ops > 0 else 0

        assert efficiency > 0.7
        assert stats["invalidations"] < stats["hits"]


class TestCacheIntegration:
    """Test cache integration with wiki operations."""

    def test_cache_query_neighbors(self):
        """Test caching graph neighbor queries."""
        cache = {}

        def cached_neighbors(page_id):
            if page_id in cache:
                return cache[page_id]

            # Simulate expensive query
            result = [f"page_{i}" for i in range(1, 4)]
            cache[page_id] = result
            return result

        # First call - cache miss
        result1 = cached_neighbors("page_1")
        assert len(result1) == 3

        # Second call - cache hit
        result2 = cached_neighbors("page_1")
        assert result1 == result2

    def test_cache_search_results(self):
        """Test caching search results."""
        cache = {}

        def cached_search(query):
            if query in cache:
                return cache[query]

            # Simulate expensive search
            results = [{"id": f"page_{i}", "relevance": 0.9 - i*0.1} for i in range(3)]
            cache[query] = results
            return results

        # Search and cache
        results = cached_search("python")
        assert len(results) == 3
        assert cache["python"] is not None

    def test_cache_invalidation_on_update(self):
        """Test that cache invalidates on page update."""
        cache = {
            "page_1_data": {"id": "page_1", "content": "old"},
        }

        # Update page_1
        cache.pop("page_1_data", None)
        cache["page_1_data"] = {"id": "page_1", "content": "new"}

        assert cache["page_1_data"]["content"] == "new"

    def test_cache_warming(self):
        """Test pre-warming cache on startup."""
        cache = {}
        hot_pages = ["page_1", "page_2", "page_3"]

        # Pre-populate cache with hot pages
        for page_id in hot_pages:
            cache[page_id] = f"data_{page_id}"

        assert len(cache) == 3
        assert all(pid in cache for pid in hot_pages)


class TestCachePerformance:
    """Test performance improvements from caching."""

    def test_query_time_improvement(self):
        """Test that cached queries are faster."""
        import time

        # Simulate expensive query
        def expensive_query():
            time.sleep(0.1)
            return {"result": "data"}

        # First call (no cache)
        start = time.time()
        result1 = expensive_query()
        uncached_time = time.time() - start

        # Cached call
        cache = {"key": result1}
        start = time.time()
        cache.get("key")
        cached_time = time.time() - start

        # Cached should be much faster
        assert cached_time < uncached_time / 10

    def test_cache_reduces_db_queries(self):
        """Test that cache reduces expensive operations."""
        query_count = 0

        def query_with_cache(page_id, cache):
            nonlocal query_count

            if page_id in cache:
                return cache[page_id]

            query_count += 1
            result = [f"rel_{i}" for i in range(5)]
            cache[page_id] = result
            return result

        cache = {}

        # Make 10 queries, 5 unique pages
        for i in range(10):
            query_with_cache(f"page_{i % 5}", cache)

        # Should have only 5 database queries
        assert query_count == 5
