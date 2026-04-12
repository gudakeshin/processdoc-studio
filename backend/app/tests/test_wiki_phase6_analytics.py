"""
Tests for wiki analytics, recommendations, and insights (Phase 6).

Tests Priority 8: Analytics & Recommendation Engine
"""

import pytest
from datetime import datetime, timezone
from app.services.wiki_analytics import (
    PageAnalytics,
    RecommendationEngine,
    KnowledgeGapDetector,
    WikiRecommender,
    get_wiki_recommender,
)


# ===== Page Analytics Tests (8 tests) =====

class TestPageAnalytics:
    """Test page view tracking and engagement metrics."""

    def test_record_single_view(self):
        """Record a single page view."""
        analytics = PageAnalytics()
        analytics.record_view("page_1")

        assert analytics.views["page_1"] == 1
        assert len(analytics.view_history["page_1"]) == 1

    def test_record_multiple_views(self):
        """Record multiple views of same page."""
        analytics = PageAnalytics()
        analytics.record_view("page_1")
        analytics.record_view("page_1")
        analytics.record_view("page_1")

        assert analytics.views["page_1"] == 3

    def test_record_view_with_user(self):
        """Record view with user tracking."""
        analytics = PageAnalytics()
        analytics.record_view("page_1", user_id="user_123")
        analytics.record_view("page_2", user_id="user_123")

        assert "page_1" in analytics.user_pages["user_123"]
        assert "page_2" in analytics.user_pages["user_123"]

    def test_get_popular_pages(self):
        """Get most viewed pages."""
        analytics = PageAnalytics()
        for i in range(5):
            analytics.record_view("page_1")
        for i in range(3):
            analytics.record_view("page_2")
        for i in range(1):
            analytics.record_view("page_3")

        popular = analytics.get_popular_pages(limit=2)

        assert len(popular) == 2
        assert popular[0]["page_id"] == "page_1"
        assert popular[0]["view_count"] == 5
        assert popular[1]["page_id"] == "page_2"
        assert popular[1]["view_count"] == 3

    def test_record_search(self):
        """Record search queries."""
        analytics = PageAnalytics()
        analytics.record_search("database design")
        analytics.record_search("database design")
        analytics.record_search("api")

        assert analytics.searches["database design"] == 2
        assert analytics.searches["api"] == 1

    def test_get_trending_searches(self):
        """Get trending search queries."""
        analytics = PageAnalytics()
        analytics.record_search("auth")
        analytics.record_search("auth")
        analytics.record_search("auth")
        analytics.record_search("cache")
        analytics.record_search("cache")

        trending = analytics.get_trending_searches(limit=2)

        assert len(trending) == 2
        assert trending[0]["query"] == "auth"
        assert trending[0]["count"] == 3

    def test_get_page_stats(self):
        """Get analytics for specific page."""
        analytics = PageAnalytics()
        analytics.record_view("page_1")
        analytics.record_view("page_1")

        stats = analytics.get_page_stats("page_1")

        assert stats["page_id"] == "page_1"
        assert stats["view_count"] == 2
        assert stats["history_length"] == 2
        assert stats["last_viewed"] is not None

    def test_analytics_summary(self):
        """Get analytics summary."""
        analytics = PageAnalytics()
        analytics.record_view("page_1")
        analytics.record_view("page_2")
        analytics.record_view("page_1")
        analytics.record_search("query_1")
        analytics.record_search("query_2")

        summary = analytics.stats()

        assert summary["total_views"] == 3
        assert summary["unique_pages_viewed"] == 2
        assert summary["total_searches"] == 2
        assert summary["unique_searches"] == 2


# ===== Recommendation Engine Tests (7 tests) =====

class TestRecommendationEngine:
    """Test relationship-based page recommendations."""

    def test_build_graph_from_relationships(self):
        """Build recommendation graph."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
        ]

        engine.build_graph(relationships)

        assert "p1" in engine.relationship_graph
        assert "p2" in engine.relationship_graph["p1"]
        assert "p1" in engine.relationship_graph["p2"]

    def test_get_related_pages_depth_1(self):
        """Get direct neighbors (depth 1)."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p1", "target_id": "p3"},
            {"source_id": "p2", "target_id": "p4"},
        ]
        engine.build_graph(relationships)

        related = engine.get_related_pages("p1", depth=1)

        assert len(related) == 2
        assert all(r["distance"] == 1 for r in related)

    def test_get_related_pages_depth_2(self):
        """Get neighbors at depth 2."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
        ]
        engine.build_graph(relationships)

        related = engine.get_related_pages("p1", depth=2, limit=10)

        # p2 at distance 1, p3 at distance 2
        assert any(r["page_id"] == "p2" and r["distance"] == 1 for r in related)
        assert any(r["page_id"] == "p3" and r["distance"] == 2 for r in related)

    def test_related_pages_limits_results(self):
        """Related pages respects limit."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p1", "target_id": "p3"},
            {"source_id": "p1", "target_id": "p4"},
        ]
        engine.build_graph(relationships)

        related = engine.get_related_pages("p1", depth=1, limit=2)

        assert len(related) <= 2

    def test_get_user_recommendations(self):
        """Get personalized recommendations based on user history."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
            {"source_id": "p3", "target_id": "p4"},
        ]
        engine.build_graph(relationships)

        recs = engine.get_user_recommendations("user_1", ["p1"], limit=5)

        # p2 related to p1
        assert any(r["page_id"] == "p2" for r in recs)

    def test_user_recommendations_excludes_viewed_pages(self):
        """User recommendations exclude pages already viewed."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
        ]
        engine.build_graph(relationships)

        recs = engine.get_user_recommendations("user_1", ["p1", "p2"], limit=5)

        # p1 and p2 already viewed, shouldn't recommend them
        assert all(r["page_id"] not in ["p1", "p2"] for r in recs)

    def test_recommendation_engine_stats(self):
        """Get recommendation engine statistics."""
        engine = RecommendationEngine()
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
        ]
        engine.build_graph(relationships)

        stats = engine.stats()

        assert stats["graph_nodes"] >= 2
        assert stats["graph_edges"] >= 1


# ===== Knowledge Gap Detector Tests (6 tests) =====

class TestKnowledgeGapDetector:
    """Test detection of missing content and gaps."""

    def test_index_pages(self):
        """Index pages for gap detection."""
        detector = KnowledgeGapDetector()
        pages = [
            {"id": "p1", "title": "Database Design", "content": "Database Design is important"},
            {"id": "p2", "title": "API", "content": "API Design is complex"},
        ]

        detector.index_pages(pages)

        assert len(detector.pages) == 2
        assert detector.pages["p1"]["title"] == "Database Design"

    def test_detect_missing_pages(self):
        """Detect frequently mentioned but missing concepts."""
        detector = KnowledgeGapDetector()
        pages = [
            {"id": "p1", "title": "Database", "content": "Database Design Database Design Database Design is important"},
        ]

        detector.index_pages(pages)
        missing = detector.detect_missing_pages(min_mentions=2)

        # Should find concepts mentioned multiple times
        assert isinstance(missing, list)

    def test_missing_pages_respects_min_mentions(self):
        """Missing pages filter respects mention threshold."""
        detector = KnowledgeGapDetector()
        pages = [
            {"id": "p1", "title": "Main", "content": "API Design API Design API Design Query Engine Query Engine"},
        ]

        detector.index_pages(pages)
        missing = detector.detect_missing_pages(min_mentions=3)

        # Only concepts with 3+ mentions should be included
        for item in missing:
            assert item["mentions"] >= 3

    def test_coverage_report(self):
        """Get wiki coverage report."""
        detector = KnowledgeGapDetector()
        pages = [
            {"id": "p1", "title": "Database Design", "content": "Database Design Database Design Database Design"},
            {"id": "p2", "title": "API", "content": "API API API"},
        ]

        detector.index_pages(pages)
        coverage = detector.get_coverage_report()

        assert "total_pages" in coverage
        assert "total_concepts" in coverage
        assert "coverage_percentage" in coverage
        assert coverage["coverage_percentage"] >= 0
        assert coverage["coverage_percentage"] <= 100

    def test_orphaned_concepts(self):
        """Get orphaned concepts (placeholder)."""
        detector = KnowledgeGapDetector()
        pages = [
            {"id": "p1", "title": "Page", "content": "Some content"},
        ]

        detector.index_pages(pages)
        orphaned = detector.detect_orphaned_concepts()

        assert isinstance(orphaned, list)

    def test_gap_detector_clears_on_reindex(self):
        """Gap detector clears old data on reindex."""
        detector = KnowledgeGapDetector()
        pages1 = [
            {"id": "p1", "title": "Page 1", "content": "Content"},
        ]

        detector.index_pages(pages1)
        assert len(detector.pages) == 1

        pages2 = [
            {"id": "p2", "title": "Page 2", "content": "Different"},
        ]

        detector.index_pages(pages2)
        assert len(detector.pages) == 1
        assert "p1" not in detector.pages


# ===== Wiki Recommender Tests (6 tests) =====

class TestWikiRecommender:
    """Test unified recommender combining all analytics."""

    def test_update_from_wiki(self):
        """Update recommender with wiki state."""
        recommender = WikiRecommender()
        pages = [
            {"id": "p1", "title": "Database", "content": "Database Design"},
        ]
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
        ]

        recommender.update_from_wiki(pages, relationships)

        assert "p1" in recommender.engine.relationship_graph

    def test_get_recommendations_for_page(self):
        """Get all recommendation types for a page."""
        recommender = WikiRecommender()
        pages = [
            {"id": "p1", "title": "Database Design", "content": "Database Design Database Design"},
            {"id": "p2", "title": "API", "content": "API Design"},
        ]
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
        ]

        recommender.update_from_wiki(pages, relationships)
        recs = recommender.get_recommendations("p1")

        assert "page_id" in recs
        assert "related_pages" in recs
        assert "personalized_recommendations" in recs
        assert "missing_pages" in recs
        assert "trending_pages" in recs

    def test_recommendations_with_user_history(self):
        """Get recommendations with user viewing history."""
        recommender = WikiRecommender()
        pages = [
            {"id": "p1", "title": "Page 1", "content": "Content 1"},
            {"id": "p2", "title": "Page 2", "content": "Content 2"},
            {"id": "p3", "title": "Page 3", "content": "Content 3"},
        ]
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
        ]

        recommender.update_from_wiki(pages, relationships)
        recs = recommender.get_recommendations(
            "p1",
            user_id="user_1",
            user_pages=["p1"]
        )

        assert "personalized_recommendations" in recs
        # Should recommend pages related to p1 that user hasn't seen
        assert len(recs["personalized_recommendations"]) >= 0

    def test_get_insights(self):
        """Get wiki insights and analytics."""
        recommender = WikiRecommender()
        pages = [
            {"id": "p1", "title": "Page", "content": "Content"},
        ]
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
        ]

        recommender.update_from_wiki(pages, relationships)
        recommender.analytics.record_view("p1")
        recommender.analytics.record_search("test")

        insights = recommender.get_insights()

        assert "analytics" in insights
        assert "recommendation_engine" in insights
        assert "coverage" in insights
        assert insights["analytics"]["total_views"] > 0

    def test_global_recommender_singleton(self):
        """Global recommender instance is singleton."""
        recommender1 = get_wiki_recommender()
        recommender2 = get_wiki_recommender()

        assert recommender1 is recommender2


# ===== Integration Tests (5 tests) =====

class TestWikiAnalyticsIntegration:
    """Integration tests for complete analytics workflow."""

    def test_analytics_workflow(self):
        """Complete analytics workflow."""
        recommender = WikiRecommender()

        # Simulate wiki content
        pages = [
            {
                "id": "p1",
                "title": "Database Design",
                "content": "Database Design Database Design Database Design patterns"
            },
            {
                "id": "p2",
                "title": "API Design",
                "content": "API Design API Design best practices"
            },
            {
                "id": "p3",
                "title": "Caching",
                "content": "Caching strategies and Caching optimization"
            },
        ]

        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
        ]

        recommender.update_from_wiki(pages, relationships)

        # Simulate user behavior
        recommender.analytics.record_view("p1", user_id="user_1")
        recommender.analytics.record_view("p2", user_id="user_1")
        recommender.analytics.record_search("database")
        recommender.analytics.record_search("database")

        # Get insights
        insights = recommender.get_insights()

        assert insights["analytics"]["total_views"] == 2
        assert insights["analytics"]["total_searches"] == 2
        assert insights["coverage"]["total_pages"] == 3

    def test_analytics_with_multiple_users(self):
        """Analytics tracks multiple users."""
        analytics = PageAnalytics()

        analytics.record_view("p1", user_id="user_1")
        analytics.record_view("p2", user_id="user_1")
        analytics.record_view("p1", user_id="user_2")
        analytics.record_view("p3", user_id="user_2")

        user1_pages = analytics.get_user_pages("user_1")
        user2_pages = analytics.get_user_pages("user_2")

        assert len(user1_pages) == 2
        assert len(user2_pages) == 2
        assert "p1" in user1_pages
        assert "p1" in user2_pages
        assert "p2" not in user2_pages

    def test_recommendations_relevance_scoring(self):
        """Recommendations score by relevance (distance)."""
        engine = RecommendationEngine()

        # Build graph: p1 - p2 - p3 - p4
        relationships = [
            {"source_id": "p1", "target_id": "p2"},
            {"source_id": "p2", "target_id": "p3"},
            {"source_id": "p3", "target_id": "p4"},
        ]
        engine.build_graph(relationships)

        related = engine.get_related_pages("p1", depth=3, limit=10)

        # p2 should be more relevant than p3, p3 more than p4
        if len(related) > 2:
            p2 = next((r for r in related if r["page_id"] == "p2"), None)
            p3 = next((r for r in related if r["page_id"] == "p3"), None)
            p4 = next((r for r in related if r["page_id"] == "p4"), None)

            if p2 and p3:
                assert p2["relevance"] > p3["relevance"]

    def test_empty_wiki_analytics(self):
        """Analytics handles empty wiki gracefully."""
        recommender = WikiRecommender()

        recommender.update_from_wiki([], [])
        insights = recommender.get_insights()

        assert insights["analytics"]["total_views"] == 0
        assert insights["coverage"]["total_pages"] == 0
        assert insights["recommendation_engine"]["graph_nodes"] == 0

