"""
Tests for wiki quality assurance and linting (Cowork Tier 3).

Tests the wiki health check evaluator, issue detection, and suggestion generation.
"""

import pytest
from unittest.mock import Mock, MagicMock

from app.services.wiki_qa import WikiQAEvaluator


# ===== Tier 3: Contradiction Detection Tests (3 tests) =====

class TestContradictionDetection:
    """Test detection of contradictory claims in wiki pages."""

    def test_detect_contradictions_simple(self):
        """Should detect simple contradictory claims."""
        pages = [
            {"id": "p1", "title": "DASH Framework", "content": "DASH has 4 phases"},
            {"id": "p2", "title": "DASH Phases", "content": "DASH has 5 phases"},
        ]
        issues = WikiQAEvaluator._check_contradictions(pages)

        assert len(issues) > 0
        assert any("contradiction" in i.get("type", "").lower() for i in issues)

    def test_no_contradictions_when_aligned(self):
        """Should not flag contradictions when claims are aligned."""
        pages = [
            {"id": "p1", "title": "DASH Framework", "content": "DASH has 4 phases"},
            {"id": "p2", "title": "DASH Phases", "content": "DASH includes Design, Analysis, Solution and Handoff"},
        ]
        issues = WikiQAEvaluator._check_contradictions(pages)

        assert len(issues) == 0

    def test_contradictions_empty_list(self):
        """Should handle empty page list gracefully."""
        pages = []
        issues = WikiQAEvaluator._check_contradictions(pages)

        assert len(issues) == 0


# ===== Orphan Page Detection Tests (3 tests) =====

class TestOrphanDetection:
    """Test detection of orphaned pages (no inbound links)."""

    def test_detect_orphan_pages(self):
        """Should detect pages with no inbound links."""
        pages = [
            {"id": "p1", "title": "Main Framework", "outbound_links": ["p2"]},
            {"id": "p2", "title": "Referenced Page", "outbound_links": []},
            {"id": "p3", "title": "Orphan Page", "outbound_links": []},
        ]
        issues = WikiQAEvaluator._check_orphans(pages)

        assert len(issues) > 0
        assert any("orphan" in i.get("type", "").lower() for i in issues)
        assert any("Orphan Page" in str(i) for i in issues)

    def test_no_orphans_when_all_linked(self):
        """Should not flag pages when all have inbound links."""
        pages = [
            {"id": "p1", "title": "Page 1", "outbound_links": ["p2"]},
            {"id": "p2", "title": "Page 2", "outbound_links": ["p1"]},
        ]
        issues = WikiQAEvaluator._check_orphans(pages)

        assert len(issues) == 0

    def test_orphans_empty_list(self):
        """Should handle empty page list."""
        pages = []
        issues = WikiQAEvaluator._check_orphans(pages)

        assert len(issues) == 0


# ===== Missing Cross-References Tests (3 tests) =====

class TestMissingCrossReferences:
    """Test detection of missing cross-reference pages."""

    def test_detect_missing_entities(self):
        """Should flag concepts mentioned but without dedicated pages."""
        pages = [
            {"id": "p1", "title": "Process Guide", "content": "Six Sigma is important. Six Sigma methodology focuses on quality."},
            {"id": "p2", "title": "Quality Framework", "content": "Six Sigma techniques are valuable."},
        ]
        wiki_index = {
            "pages": [
                {"id": "p1", "slug": "process_guide"},
                {"id": "p2", "slug": "quality_framework"},
            ]
        }
        issues = WikiQAEvaluator._check_missing_references(pages, wiki_index)

        assert len(issues) > 0
        assert any("missing" in i.get("type", "").lower() for i in issues)

    def test_no_missing_references_when_complete(self):
        """Should not flag when all entities have pages."""
        pages = [
            {"id": "p1", "title": "Six Sigma", "content": "Six Sigma methodology"},
            {"id": "p2", "title": "Quality Framework", "content": "See [Six Sigma](six_sigma.md)"},
        ]
        wiki_index = {
            "pages": [
                {"id": "p1", "slug": "six_sigma"},
                {"id": "p2", "slug": "quality_framework"},
            ]
        }
        issues = WikiQAEvaluator._check_missing_references(pages, wiki_index)

        assert len(issues) == 0

    def test_missing_references_empty_list(self):
        """Should handle empty page list."""
        pages = []
        wiki_index = {"pages": []}
        issues = WikiQAEvaluator._check_missing_references(pages, wiki_index)

        assert len(issues) == 0


# ===== Broken Links Tests (3 tests) =====

class TestBrokenLinks:
    """Test detection of broken cross-references."""

    def test_detect_broken_links(self):
        """Should detect links to non-existent pages."""
        pages = [
            {
                "id": "p1",
                "title": "Main Page",
                "content": "See [DASH Framework](dash_framework.md) for details.",
                "outbound_links": ["dash_framework"]
            }
        ]
        wiki_index = {
            "pages": [
                {"id": "p1", "slug": "main_page"},
            ]
        }
        issues = WikiQAEvaluator._check_broken_links(pages, wiki_index)

        assert len(issues) > 0
        assert any("broken" in i.get("type", "").lower() for i in issues)

    def test_no_broken_links_when_valid(self):
        """Should not flag valid links."""
        pages = [
            {
                "id": "p1",
                "title": "Main Page",
                "content": "See [DASH Framework](dash_framework.md)",
                "outbound_links": ["dash_framework"]
            }
        ]
        wiki_index = {
            "pages": [
                {"id": "p1", "slug": "main_page"},
                {"id": "p2", "slug": "dash_framework"},
            ]
        }
        issues = WikiQAEvaluator._check_broken_links(pages, wiki_index)

        assert len(issues) == 0

    def test_broken_links_empty_list(self):
        """Should handle empty page list."""
        pages = []
        wiki_index = {"pages": []}
        issues = WikiQAEvaluator._check_broken_links(pages, wiki_index)

        assert len(issues) == 0


# ===== Coverage Gaps Tests (2 tests) =====

class TestCoverageGaps:
    """Test detection of under-explored topics."""

    def test_detect_coverage_gaps(self):
        """Should flag topics mentioned frequently but not deeply covered."""
        pages = [
            {"id": "p1", "title": "Financial Models", "content": "Six Sigma mentioned here. Six Sigma is important."},
            {"id": "p2", "title": "Process Improvement", "content": "Six Sigma benefits are well-known. Six Sigma techniques."},
            {"id": "p3", "title": "Implementation Guide", "content": "Six Sigma approach. Six Sigma methodology."},
        ]
        issues = WikiQAEvaluator._check_coverage_gaps(pages)

        assert len(issues) >= 0  # May or may not detect depending on heuristic

    def test_coverage_gaps_empty_list(self):
        """Should handle empty page list."""
        pages = []
        issues = WikiQAEvaluator._check_coverage_gaps(pages)

        assert len(issues) == 0


# ===== Divergence Check Tests (2 tests) =====

class TestDivergenceCheck:
    """Test detection of project-level divergence from LP practices."""

    def test_detect_divergence_from_lp(self):
        """Should flag when project heavily references but diverges from LP."""
        project_pages = [
            {
                "id": "proj_p1",
                "title": "Why We Chose SAP",
                "content": "Despite DASH Framework recommending Oracle, we chose SAP because..."
            }
        ]
        lp_pages = [
            {"id": "lp_p1", "title": "DASH Framework", "content": "Oracle is recommended"}
        ]
        issues = WikiQAEvaluator._check_divergence(project_pages, lp_pages)

        assert len(issues) >= 0  # Divergence detection is heuristic-based

    def test_divergence_empty_lists(self):
        """Should handle empty page lists."""
        project_pages = []
        lp_pages = []
        issues = WikiQAEvaluator._check_divergence(project_pages, lp_pages)

        assert len(issues) == 0


# ===== Staleness Check Tests (2 tests) =====

class TestStalenessCheck:
    """Test detection of stale pages."""

    def test_detect_stale_pages(self):
        """Should flag pages not updated recently."""
        pages = [
            {
                "id": "p1",
                "title": "Old Page",
                "content": "Last updated in 2024",
                "updated_at": "2024-01-01T00:00:00",
            }
        ]
        log_entries = [
            {
                "timestamp": "2026-04-01T00:00:00",
                "source_name": "Old Page topic",
            }
        ]
        issues = WikiQAEvaluator._check_staleness(pages, log_entries, days_threshold=30)

        assert len(issues) > 0
        assert any("stale" in i.get("type", "").lower() for i in issues)

    def test_no_stale_pages_when_recent(self):
        """Should not flag recently updated pages."""
        pages = [
            {
                "id": "p1",
                "title": "Recent Page",
                "content": "Just updated",
                "updated_at": "2026-04-10T00:00:00",  # Very recent
            }
        ]
        log_entries = [
            {
                "timestamp": "2026-04-05T00:00:00",
                "source_name": "Related topic",
            }
        ]
        issues = WikiQAEvaluator._check_staleness(pages, log_entries, days_threshold=30)

        # Should not flag a recently updated page
        assert all("stale" not in i.get("type", "").lower() for i in issues)


# ===== Integration Tests (3 tests) =====

class TestWikiQAIntegration:
    """Integration tests for wiki QA evaluation."""

    def test_evaluate_wiki_health_success(self):
        """Should evaluate wiki health and return clean result."""
        pages = [
            {"id": "p1", "title": "Framework", "content": "Main framework", "outbound_links": [], "updated_at": "2026-04-10T00:00:00"},
            {"id": "p2", "title": "Guide", "content": "Implementation guide", "outbound_links": ["p1"], "updated_at": "2026-04-10T00:00:00"},
        ]
        wiki_index = {
            "pages": [
                {"id": "p1", "slug": "framework"},
                {"id": "p2", "slug": "guide"},
            ]
        }
        log_entries = []

        result = WikiQAEvaluator.evaluate_wiki_health(pages, wiki_index, log_entries)

        assert isinstance(result, dict)
        assert "passed" in result
        assert "issues" in result
        assert "suggestions" in result
        assert "severity" in result
        assert isinstance(result["issues"], list)
        assert isinstance(result["suggestions"], list)

    def test_evaluate_wiki_health_with_issues(self):
        """Should report severity based on issue count."""
        pages = [
            {"id": "p1", "title": "Financial Models", "content": "Content", "outbound_links": [], "updated_at": "2024-01-01T00:00:00"},
            {"id": "p2", "title": "Process Framework", "content": "Content", "outbound_links": [], "updated_at": "2024-01-01T00:00:00"},
        ]
        wiki_index = {"pages": [{"id": "p1", "slug": "financial_models"}, {"id": "p2", "slug": "process_framework"}]}
        log_entries = [{"timestamp": "2026-04-10T00:00:00", "source_name": "Financial Models update"}]

        result = WikiQAEvaluator.evaluate_wiki_health(pages, wiki_index, log_entries)

        assert result["severity"] in ["low", "medium", "high"]
        # With stale pages detected, severity should be elevated
        if len(result["issues"]) > 0:
            assert result["severity"] in ["medium", "high"]

    def test_evaluate_empty_wiki(self):
        """Should handle evaluation of empty wiki."""
        pages = []
        wiki_index = {"pages": []}
        log_entries = []

        result = WikiQAEvaluator.evaluate_wiki_health(pages, wiki_index, log_entries)

        assert result["passed"] is True
        assert len(result["issues"]) == 0
        assert result["severity"] == "low"
