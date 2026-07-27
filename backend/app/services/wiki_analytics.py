"""
Wiki analytics and recommendations for Phase 6.

Implements:
1. Page view tracking and analytics
2. Recommendation engine (collaborative filtering)
3. Knowledge graph gap detection
4. Trending topics and hot pages
5. User behavior analytics
"""

import logging
from collections import defaultdict
from datetime import datetime
from app.core.tz import IST
from typing import Any

logger = logging.getLogger(__name__)


class PageAnalytics:
    """Track and analyze page views and engagement."""

    def __init__(self):
        """Initialize page analytics."""
        self.views = defaultdict(int)  # page_id -> view_count
        self.searches = defaultdict(int)  # search_term -> count
        self.view_history = defaultdict(list)  # page_id -> [timestamp, ...]
        self.user_pages = defaultdict(set)  # user_id -> set of viewed pages

    def record_view(self, page_id: str, user_id: str | None = None) -> None:
        """
        Record a page view.

        Args:
            page_id: Page ID being viewed
            user_id: Optional user ID for behavior tracking
        """
        self.views[page_id] += 1
        self.view_history[page_id].append(datetime.now(IST).isoformat())

        if user_id:
            self.user_pages[user_id].add(page_id)

        logger.debug(f"View recorded: {page_id}")

    def record_search(self, query: str, result_count: int = 0) -> None:
        """
        Record a search query.

        Args:
            query: Search query string
            result_count: Number of results returned
        """
        self.searches[query] += 1
        logger.debug(f"Search recorded: {query} ({result_count} results)")

    def get_popular_pages(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get most viewed pages.

        Args:
            limit: Number of pages to return

        Returns:
            List of {page_id, view_count} dicts sorted by popularity
        """
        sorted_pages = sorted(
            self.views.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [
            {"page_id": page_id, "view_count": count}
            for page_id, count in sorted_pages[:limit]
        ]

    def get_trending_searches(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get trending search queries.

        Args:
            limit: Number of searches to return

        Returns:
            List of {query, count} dicts sorted by frequency
        """
        sorted_searches = sorted(
            self.searches.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [
            {"query": query, "count": count}
            for query, count in sorted_searches[:limit]
        ]

    def get_page_stats(self, page_id: str) -> dict[str, Any]:
        """
        Get analytics for a specific page.

        Args:
            page_id: Page ID

        Returns:
            {view_count, last_viewed, view_history_length}
        """
        return {
            "page_id": page_id,
            "view_count": self.views[page_id],
            "last_viewed": (
                self.view_history[page_id][-1]
                if self.view_history[page_id]
                else None
            ),
            "history_length": len(self.view_history[page_id]),
        }

    def get_user_pages(self, user_id: str) -> list[str]:
        """Get pages viewed by a user."""
        return list(self.user_pages[user_id])

    def stats(self) -> dict[str, Any]:
        """Get analytics summary."""
        return {
            "total_views": sum(self.views.values()),
            "unique_pages_viewed": len(self.views),
            "total_searches": sum(self.searches.values()),
            "unique_searches": len(self.searches),
            "tracked_users": len(self.user_pages),
        }


class RecommendationEngine:
    """Generate page recommendations based on relationships and user behavior."""

    def __init__(self):
        """Initialize recommendation engine."""
        self.relationship_graph = {}  # page_id -> [related_pages]
        self.user_history = defaultdict(list)  # user_id -> [page_ids]

    def build_graph(self, relationships: list[dict[str, Any]]) -> None:
        """
        Build recommendation graph from relationships.

        Args:
            relationships: List of relationship dicts with source_id, target_id
        """
        self.relationship_graph.clear()

        for rel in relationships:
            source = rel.get("source_id")
            target = rel.get("target_id")

            if source not in self.relationship_graph:
                self.relationship_graph[source] = []
            if target not in self.relationship_graph:
                self.relationship_graph[target] = []

            # Add bidirectional links
            if target not in self.relationship_graph[source]:
                self.relationship_graph[source].append(target)
            if source not in self.relationship_graph[target]:
                self.relationship_graph[target].append(source)

    def get_related_pages(
        self,
        page_id: str,
        depth: int = 1,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get pages related to given page.

        Args:
            page_id: Starting page
            depth: How many hops to traverse (1-2)
            limit: Max results

        Returns:
            List of {page_id, distance, relevance} dicts
        """
        if page_id not in self.relationship_graph:
            return []

        visited = set()
        results = []
        queue = [(page_id, 0)]

        while queue and len(results) < limit:
            current, distance = queue.pop(0)

            if current in visited or distance > depth:
                continue

            visited.add(current)

            if current != page_id:
                # Relevance inversely proportional to distance
                relevance = 1.0 / (distance ** 0.5)
                results.append({
                    "page_id": current,
                    "distance": distance,
                    "relevance": round(relevance, 3),
                })

            if distance < depth:
                for neighbor in self.relationship_graph.get(current, []):
                    if neighbor not in visited:
                        queue.append((neighbor, distance + 1))

        return sorted(results, key=lambda x: x["relevance"], reverse=True)[:limit]

    def get_user_recommendations(
        self,
        user_id: str,
        user_pages: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get personalized recommendations based on user viewing history.

        Args:
            user_id: User ID
            user_pages: Pages user has viewed
            limit: Max recommendations

        Returns:
            List of {page_id, score, reason} dicts
        """
        if not user_pages:
            return []

        recommendations = defaultdict(float)

        # For each page user viewed, find related pages
        for page_id in user_pages:
            related = self.get_related_pages(page_id, depth=2, limit=10)

            for rel in related:
                if rel["page_id"] not in user_pages:
                    recommendations[rel["page_id"]] += rel["relevance"]

        # Sort by score and return top N
        sorted_recs = sorted(
            recommendations.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return [
            {
                "page_id": page_id,
                "score": round(score, 3),
                "reason": "Related to pages you viewed",
            }
            for page_id, score in sorted_recs[:limit]
        ]

    def stats(self) -> dict[str, Any]:
        """Get recommendation engine statistics."""
        total_edges = sum(len(pages) for pages in self.relationship_graph.values()) // 2
        return {
            "graph_nodes": len(self.relationship_graph),
            "graph_edges": total_edges,
            "avg_degree": (
                total_edges * 2 / len(self.relationship_graph)
                if self.relationship_graph
                else 0
            ),
        }


class KnowledgeGapDetector:
    """Detect gaps and missing content in wiki knowledge graph."""

    def __init__(self):
        """Initialize gap detector."""
        self.pages = {}  # page_id -> {title, content, tags}
        self.mentions = defaultdict(int)  # concept -> mention_count

    def index_pages(self, pages: list[dict[str, Any]]) -> None:
        """
        Index pages for gap detection.

        Args:
            pages: List of page dicts with id, title, content
        """
        self.pages.clear()
        self.mentions.clear()

        for page in pages:
            page_id = page.get("id")
            self.pages[page_id] = {
                "title": page.get("title", ""),
                "content": page.get("content", ""),
            }

            # Extract capitalized phrases as concepts
            words = page.get("content", "").split()
            for i in range(len(words) - 1):
                if (words[i][0].isupper() and words[i+1][0].isupper()):
                    concept = f"{words[i]} {words[i+1]}"
                    self.mentions[concept] += 1

    def detect_missing_pages(self, min_mentions: int = 3) -> list[dict[str, Any]]:
        """
        Detect frequently mentioned concepts without dedicated pages.

        Args:
            min_mentions: Minimum mentions to consider as missing

        Returns:
            List of {concept, mentions, suggested_action} dicts
        """
        missing = []
        existing_titles = {p["title"].lower() for p in self.pages.values()}

        for concept, count in self.mentions.items():
            if count >= min_mentions and concept.lower() not in existing_titles:
                missing.append({
                    "concept": concept,
                    "mentions": count,
                    "suggested_action": f"Create page for '{concept}'",
                })

        # Sort by mention count
        return sorted(missing, key=lambda x: x["mentions"], reverse=True)

    def detect_orphaned_concepts(self, max_inbound: int = 0) -> list[dict[str, Any]]:
        """
        Detect pages that are isolated in the knowledge graph.

        A page is "orphaned" when its title appears in at most ``max_inbound``
        other pages' content — nothing references it, so it sits as an island.

        Args:
            max_inbound: Maximum inbound references for a page to count as orphaned.

        Returns:
            List of {page_id, title, inbound_references, suggested_action} dicts,
            most isolated first.
        """
        orphaned = []
        for page_id, page in self.pages.items():
            title = (page.get("title") or "").strip()
            if not title:
                continue
            title_lower = title.lower()
            inbound = sum(
                1
                for other_id, other in self.pages.items()
                if other_id != page_id and title_lower in (other.get("content") or "").lower()
            )
            if inbound <= max_inbound:
                orphaned.append({
                    "page_id": page_id,
                    "title": title,
                    "inbound_references": inbound,
                    "suggested_action": f"Link '{title}' from related pages or merge if redundant",
                })

        return sorted(orphaned, key=lambda x: x["inbound_references"])

    def get_coverage_report(self) -> dict[str, Any]:
        """
        Get wiki coverage report.

        Returns:
            {total_pages, total_concepts, coverage_percentage, gaps}
        """
        total_concepts = len(self.mentions)
        covered_concepts = sum(
            1 for concept in self.mentions
            if concept.lower() in {p["title"].lower() for p in self.pages.values()}
        )

        coverage = (
            (covered_concepts / total_concepts * 100)
            if total_concepts > 0
            else 0
        )

        return {
            "total_pages": len(self.pages),
            "total_concepts": total_concepts,
            "covered_concepts": covered_concepts,
            "coverage_percentage": round(coverage, 1),
            "missing_concepts": total_concepts - covered_concepts,
        }


class WikiRecommender:
    """Unified wiki recommender combining all analytics."""

    def __init__(self):
        """Initialize recommender."""
        self.analytics = PageAnalytics()
        self.engine = RecommendationEngine()
        self.gap_detector = KnowledgeGapDetector()

    def update_from_wiki(self, pages: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> None:
        """
        Update recommender with current wiki state.

        Args:
            pages: List of wiki pages
            relationships: List of relationships
        """
        self.engine.build_graph(relationships)
        self.gap_detector.index_pages(pages)

    def get_recommendations(
        self,
        page_id: str,
        user_id: str | None = None,
        user_pages: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get all recommendation types for a page.

        Args:
            page_id: Current page
            user_id: Optional user ID
            user_pages: Optional user's viewed pages

        Returns:
            {related_pages, personalized, gaps, trending}
        """
        related = self.engine.get_related_pages(page_id, limit=5)
        personalized = (
            self.engine.get_user_recommendations(user_id, user_pages or [], limit=5)
            if user_pages
            else []
        )
        gaps = self.gap_detector.detect_missing_pages(min_mentions=3)
        trending = self.analytics.get_popular_pages(limit=5)

        return {
            "page_id": page_id,
            "related_pages": related,
            "personalized_recommendations": personalized,
            "missing_pages": gaps[:3],
            "trending_pages": trending,
        }

    def get_insights(self) -> dict[str, Any]:
        """Get wiki insights and analytics."""
        return {
            "analytics": self.analytics.stats(),
            "recommendation_engine": self.engine.stats(),
            "coverage": self.gap_detector.get_coverage_report(),
        }


# Global recommender instance
_wiki_recommender = WikiRecommender()


def get_wiki_recommender() -> WikiRecommender:
    """Get global wiki recommender instance."""
    return _wiki_recommender
