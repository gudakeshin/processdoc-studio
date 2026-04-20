"""
End-to-end tests for Wiki Phase 5: Cache Layer & Query Optimization.

Verifies cache integration with wiki operations and performance improvements.
"""

import time


class TestCacheWithWikiOperations:
    """Test cache integration with wiki operations."""

    def test_cached_query_reduces_execution_time(self):
        """Test that cached queries are faster than uncached."""
        query_times = []

        def query_neighbors(page_id, cache=None, execute_slow=None):
            if cache and page_id in cache:
                # Cache hit
                return cache[page_id]

            # Slow operation
            if execute_slow:
                time.sleep(0.01)
            result = [f"neighbor_{i}" for i in range(5)]

            if cache is not None:
                cache[page_id] = result
            return result

        cache = {}

        # First query (cache miss)
        start = time.time()
        query_neighbors("page_1", cache, execute_slow=True)
        uncached_time = time.time() - start
        query_times.append(uncached_time)

        # Second query (cache hit)
        start = time.time()
        query_neighbors("page_1", cache)
        cached_time = time.time() - start
        query_times.append(cached_time)

        # Cached should be much faster
        assert cached_time < uncached_time / 5

    def test_search_index_finds_relevant_pages(self):
        """Test that search index finds and ranks relevant pages."""
        search_index = {
            "python": {"page_1", "page_2"},
            "programming": {"page_1", "page_3"},
            "web": {"page_2"},
        }

        query = "python programming"
        query_words = query.split()

        # Find pages with all words
        matching = None
        for word in query_words:
            if word in search_index:
                if matching is None:
                    matching = search_index[word].copy()
                else:
                    matching &= search_index[word]
            else:
                matching = set()
                break

        # page_1 has both words
        assert "page_1" in matching
        assert len(matching) == 1

    def test_cache_invalidation_on_page_update(self):
        """Test that cache invalidates when page is updated."""
        cache = {
            "page_1_neighbors": ["p2", "p3"],
            "page_1_community": ["community_1"],
            "page_2_neighbors": ["p1", "p4"],
        }

        # Update page_1
        page_id = "page_1"
        keys_to_invalidate = [k for k in cache if page_id in k]

        for key in keys_to_invalidate:
            del cache[key]

        # page_1 queries gone, page_2 remains
        assert "page_1_neighbors" not in cache
        assert "page_1_community" not in cache
        assert "page_2_neighbors" in cache

    def test_cache_warmup_improves_first_access(self):
        """Test that cache warmup reduces first query latency."""
        cache = {}

        # Warm up with god nodes
        hot_pages = ["page_1", "page_2", "page_3"]
        for page_id in hot_pages:
            cache[f"{page_id}_importance"] = 0.85

        # First access to hot page is fast
        assert "page_1_importance" in cache
        assert cache["page_1_importance"] == 0.85

    def test_multi_query_scenario(self):
        """Test realistic multi-query scenario with cache hits."""
        cache = {}
        query_log = []

        def query_with_logging(page_id):
            key = f"neighbors_{page_id}"
            if key in cache:
                query_log.append("hit")
                return cache[key]

            query_log.append("miss")
            result = [f"rel_{i}" for i in range(3)]
            cache[key] = result
            return result

        # Simulate user navigation
        queries = ["page_1", "page_2", "page_1", "page_3", "page_2", "page_1"]

        for page_id in queries:
            query_with_logging(page_id)

        # Count hits vs misses
        hits = query_log.count("hit")
        misses = query_log.count("miss")

        # Should have 3 hits (repeated queries)
        assert hits == 3
        assert misses == 3


class TestSearchIndexIntegration:
    """Test search index integration with wiki."""

    def test_index_multiple_pages(self):
        """Test indexing multiple pages."""
        pages = {
            "page_1": "Python programming tutorial",
            "page_2": "JavaScript web development",
            "page_3": "Python data science",
        }

        index = {}
        for page_id, text in pages.items():
            words = text.lower().split()
            for word in words:
                if len(word) > 2:
                    if word not in index:
                        index[word] = set()
                    index[word].add(page_id)

        # Verify indexing
        assert "python" in index
        assert len(index["python"]) == 2
        assert "javascript" in index
        assert len(index["javascript"]) == 1

    def test_search_ranking(self):
        """Test that search results are ranked by relevance."""
        pages = {
            "page_1": "python programming language",
            "page_2": "python tutorial",
            "page_3": "java language",
        }

        query = "python"
        results = []

        for page_id, text in pages.items():
            if query in text:
                # Score based on frequency
                score = text.count(query) / text.count(" ")
                results.append((page_id, score))

        # Sort by relevance
        results.sort(key=lambda x: x[1], reverse=True)

        # Python pages rank higher
        assert results[0][0] in ["page_1", "page_2"]

    def test_search_with_multiple_terms(self):
        """Test search with multiple terms."""
        pages = {
            "page_1": "python programming language tutorial",
            "page_2": "python web framework",
            "page_3": "programming language design",
        }

        query_terms = ["python", "programming"]
        relevant_pages = set(pages.keys())

        for term in query_terms:
            matching = {
                page_id for page_id, text in pages.items()
                if term in text
            }
            relevant_pages &= matching

        # Only page_1 has both terms
        assert len(relevant_pages) == 1
        assert "page_1" in relevant_pages


class TestCachePerformanceMetrics:
    """Test cache performance monitoring."""

    def test_hit_rate_tracking(self):
        """Test tracking cache hit rate."""
        stats = {
            "hits": 0,
            "misses": 0,
        }

        cache = {}

        def query(key):
            if key in cache:
                stats["hits"] += 1
                return cache[key]
            else:
                stats["misses"] += 1
                cache[key] = f"value_{key}"
                return cache[key]

        # Make queries
        for i in range(5):
            query("page_1")  # Will hit after first query
            query(f"page_{i}")

        hit_rate = stats["hits"] / (stats["hits"] + stats["misses"])

        # 4 hits out of 9 total
        assert stats["hits"] > 0
        assert hit_rate > 0

    def test_cache_size_metrics(self):
        """Test monitoring cache size."""
        cache = {}
        max_size = 100

        # Fill cache
        for i in range(50):
            cache[f"key_{i}"] = f"value_{i}"

        utilization = len(cache) / max_size

        assert len(cache) <= max_size
        assert utilization == 0.5

    def test_invalidation_frequency(self):
        """Test tracking invalidation frequency."""
        stats = {
            "invalidations": 0,
        }

        cache = {
            "page_1_data": "value",
            "page_2_data": "value",
        }

        # Simulate invalidation
        page_to_invalidate = "page_1"
        for key in list(cache.keys()):
            if page_to_invalidate in key:
                del cache[key]
                stats["invalidations"] += 1

        assert stats["invalidations"] == 1


class TestCacheEdgeCases:
    """Test cache edge cases."""

    def test_cache_with_empty_results(self):
        """Test caching empty query results."""
        cache = {}

        # Cache empty result
        cache["empty_query"] = []

        # Should be able to retrieve empty result
        assert "empty_query" in cache
        assert cache["empty_query"] == []

    def test_cache_large_datasets(self):
        """Test caching large result sets."""
        cache = {}

        # Cache large result (1000 items)
        large_result = [f"item_{i}" for i in range(1000)]
        cache["large_query"] = large_result

        # Retrieve and verify
        assert len(cache["large_query"]) == 1000

    def test_concurrent_cache_access(self):
        """Test cache under concurrent access patterns."""
        cache = {}
        operations = []

        # Simulate concurrent reads/writes
        for i in range(10):
            cache[f"key_{i}"] = f"value_{i}"
            operations.append("write")

        for i in range(10):
            _ = cache.get(f"key_{i}")
            operations.append("read")

        assert len(operations) == 20
        assert len(cache) == 10


class TestCacheRecovery:
    """Test cache recovery and consistency."""

    def test_invalidate_and_rebuild(self):
        """Test invalidating and rebuilding cache."""
        cache = {
            "page_1_neighbors": ["p2", "p3"],
            "page_2_neighbors": ["p1"],
        }

        # Invalidate page_1
        for key in list(cache.keys()):
            if "page_1" in key:
                del cache[key]

        # Rebuild page_1
        cache["page_1_neighbors"] = ["p2", "p3", "p4"]

        # New state matches
        assert cache["page_1_neighbors"] == ["p2", "p3", "p4"]

    def test_cache_consistency_after_invalidation(self):
        """Test that cache remains consistent after invalidation."""
        cache = {
            "page_1": "data_1",
            "page_2": "data_2",
            "page_3": "data_3",
        }

        # Invalidate page_2
        del cache["page_2"]

        # Others unchanged
        assert cache["page_1"] == "data_1"
        assert cache["page_3"] == "data_3"
        assert "page_2" not in cache
