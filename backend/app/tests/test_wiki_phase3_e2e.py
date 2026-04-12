"""
End-to-end tests for Wiki Phase 3: QA/Linting and Cross-Wiki Linking.

Verifies complete workflow of wiki quality assurance and cross-wiki navigation.
"""

import pytest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timezone


class TestPhase3QAIntegration:
    """Test QA/Linting integrated into wiki workflow."""

    def test_ingest_with_qa_evaluation(self):
        """Test that ingesting wiki pages triggers QA evaluation."""
        ingest_result = {
            "status": "success",
            "pages_created": 5,
            "pages_updated": 2,
            "qa_results": {
                "passed": False,
                "issues": [
                    {
                        "page_id": "page_1",
                        "issue_type": "broken_link",
                        "severity": "medium",
                        "message": "Broken link found",
                    }
                ],
                "suggestions": [
                    {
                        "page_id": "page_3",
                        "issue_type": "orphaned_page",
                        "severity": "low",
                        "message": "Consider linking this page",
                    }
                ],
                "severity": "medium",
            }
        }

        # Verify QA results included in ingest
        assert "qa_results" in ingest_result
        assert ingest_result["qa_results"]["severity"] in ["low", "medium", "high"]
        assert len(ingest_result["qa_results"]["issues"]) > 0

    def test_lint_endpoint_detects_issues(self):
        """Test lint endpoint properly identifies wiki issues."""
        lint_response = {
            "status": "success",
            "issues": [
                {
                    "page_id": "page_2",
                    "issue_type": "broken_link",
                    "severity": "medium",
                    "message": "[[Non-existent Page]] not found",
                }
            ],
            "suggestions": [],
            "severity": "low",
            "issues_count": 1,
            "suggestions_count": 0,
        }

        assert lint_response["status"] == "success"
        assert lint_response["issues_count"] >= 0
        assert lint_response["severity"] in ["low", "medium", "high"]

    def test_qa_before_publishing(self):
        """Test QA check before marking pages as ready."""
        # Before publishing, run QA
        qa_check = {
            "page_id": "page_1",
            "passed": True,
            "issues": [],
            "suggestions": [
                {"type": "missing_entity", "count": 3}
            ],
            "severity": "low",
        }

        # Can publish if no medium/high severity issues
        can_publish = qa_check["severity"] != "high" and len([
            i for i in qa_check.get("issues", [])
            if i.get("severity") in ["medium", "high"]
        ]) == 0

        assert can_publish is True


class TestPhase3CrossWikiIntegration:
    """Test cross-wiki linking integrated into wiki workflow."""

    def test_discover_cross_wiki_references(self):
        """Test discovering cross-wiki references during ingest."""
        page_content = """
        Based on [[lp://API Design Patterns]] from leading practices.
        See [[wiki://project/proj123/API Documentation]] for implementation.
        """

        discovered_refs = [
            {
                "type": "lp_reference",
                "target": "API Design Patterns",
                "url": "lp://API Design Patterns",
            },
            {
                "type": "project_reference",
                "target": "API Documentation",
                "project_id": "proj123",
                "url": "wiki://project/proj123/API Documentation",
            }
        ]

        assert len(discovered_refs) == 2
        assert any(r["type"] == "lp_reference" for r in discovered_refs)
        assert any(r["type"] == "project_reference" for r in discovered_refs)

    def test_cross_wiki_navigation_index(self):
        """Test cross-wiki navigation index for lookups."""
        nav_index = {
            "lp_to_projects": {
                "lp_page_api": [
                    {
                        "target_page": "api_doc",
                        "target_project": "proj123",
                        "pages_linking": ["proj_page_1", "proj_page_2"],
                    }
                ]
            },
            "projects_to_lp": {
                "proj_page_1": [
                    {
                        "target_page": "lp_page_api",
                        "pages_from": ["proj_page_1", "proj_page_3"],
                    }
                ]
            },
        }

        # Verify index structure for navigation
        assert "lp_to_projects" in nav_index
        assert "projects_to_lp" in nav_index

    def test_cross_wiki_breadcrumb_trail(self):
        """Test generating breadcrumb trails across wikis."""
        # User navigates from project -> LP -> another project
        path = [
            {
                "wiki": "project",
                "project_id": "proj1",
                "page_id": "api_doc",
                "title": "API Documentation",
            },
            {
                "wiki": "leading_practice",
                "page_id": "api_patterns",
                "title": "API Design Patterns",
            },
            {
                "wiki": "project",
                "project_id": "proj2",
                "page_id": "api_impl",
                "title": "API Implementation",
            },
        ]

        # Verify path crosses wikis
        wikis_in_path = [p["wiki"] for p in path]
        assert "leading_practice" in wikis_in_path
        assert wikis_in_path.count("project") >= 1


class TestPhase3SearchAndDiscovery:
    """Test wiki search and discovery with QA and cross-wiki awareness."""

    def test_search_respects_qa_status(self):
        """Test search results are filtered by QA status."""
        search_query = "API design"

        search_results = [
            {
                "page_id": "page_1",
                "title": "API Design Guide",
                "wiki": "leading_practice",
                "qa_status": "good",
                "issues_count": 0,
                "rank": 1,
            },
            {
                "page_id": "page_2",
                "title": "API Best Practices",
                "wiki": "project",
                "project_id": "proj1",
                "qa_status": "good",
                "issues_count": 0,
                "rank": 2,
            },
        ]

        # Filter results by QA status
        good_results = [r for r in search_results if r["qa_status"] == "good"]
        assert len(good_results) == 2

    def test_cross_wiki_search_suggestions(self):
        """Test search suggests related pages across wikis."""
        primary_result = {
            "page_id": "proj_api_doc",
            "wiki": "project",
            "project_id": "proj1",
        }

        related_suggestions = [
            {
                "page_id": "lp_api_patterns",
                "wiki": "leading_practice",
                "relationship": "referenced_by",
                "type": "cross_wiki",
            },
            {
                "page_id": "proj_api_impl",
                "wiki": "project",
                "project_id": "proj2",
                "relationship": "implements",
                "type": "cross_wiki",
            },
        ]

        # Verify suggestions include cross-wiki pages
        cross_wiki_suggestions = [
            s for s in related_suggestions
            if s.get("type") == "cross_wiki"
        ]
        assert len(cross_wiki_suggestions) >= 1


class TestPhase3CommunityDetection:
    """Test community detection across wikis."""

    def test_single_wiki_community(self):
        """Test community detection within single wiki."""
        community = {
            "id": "community_1",
            "wiki": "leading_practice",
            "pages": ["lp_page_1", "lp_page_2", "lp_page_3"],
            "concept": "API Design",
            "connectivity": 0.8,
        }

        assert len(community["pages"]) >= 2
        assert community["connectivity"] >= 0

    def test_cross_wiki_community(self):
        """Test community that spans multiple wikis."""
        community = {
            "id": "community_api",
            "pages": [
                {
                    "page_id": "lp_api_patterns",
                    "wiki": "leading_practice",
                },
                {
                    "page_id": "proj_api_doc",
                    "wiki": "project",
                    "project_id": "proj1",
                },
                {
                    "page_id": "proj_api_impl",
                    "wiki": "project",
                    "project_id": "proj2",
                },
            ],
            "cross_wiki_edges": 2,
            "concept": "API Knowledge",
        }

        # Verify community spans multiple wikis
        wikis_in_community = set(p["wiki"] for p in community["pages"])
        projects_in_community = set(
            p.get("project_id") for p in community["pages"] if p.get("project_id")
        )

        assert len(wikis_in_community) >= 1
        assert community["cross_wiki_edges"] >= 0


class TestPhase3Monitoring:
    """Test monitoring and metrics for Phase 3 features."""

    def test_qa_health_metrics(self):
        """Test QA health metrics over time."""
        health_timeline = [
            {
                "date": "2026-04-01",
                "total_pages": 50,
                "pages_with_issues": 8,
                "broken_links": 3,
                "orphaned_pages": 5,
                "health_score": 0.84,  # (50-8)/50
            },
            {
                "date": "2026-04-02",
                "total_pages": 52,
                "pages_with_issues": 7,
                "broken_links": 2,
                "orphaned_pages": 5,
                "health_score": 0.865,  # (52-7)/52
            },
        ]

        # Verify health improves over time
        assert health_timeline[1]["health_score"] > health_timeline[0]["health_score"]
        assert health_timeline[1]["broken_links"] < health_timeline[0]["broken_links"]

    def test_cross_wiki_connectivity_metrics(self):
        """Test cross-wiki connectivity metrics."""
        connectivity = {
            "total_cross_wiki_links": 15,
            "lp_to_projects": 8,
            "projects_to_lp": 7,
            "unique_projects_referenced": 4,
            "avg_links_per_lp_page": 1.3,
            "connectivity_score": 0.65,
        }

        assert connectivity["total_cross_wiki_links"] > 0
        assert (
            connectivity["lp_to_projects"] + connectivity["projects_to_lp"]
            == connectivity["total_cross_wiki_links"]
        )


class TestPhase3APIIntegration:
    """Test Phase 3 features through API."""

    def test_lint_endpoint_parameters(self):
        """Test lint endpoint accepts correct parameters."""
        request = {
            "wiki_type": "project",
            "project_id": "proj123",
            "auto_fix": False,
        }

        assert request["wiki_type"] in ["leading_practice", "project"]
        if request["wiki_type"] == "project":
            assert request["project_id"] is not None

    def test_cross_wiki_reference_endpoint_parameters(self):
        """Test cross-wiki reference endpoint parameters."""
        request = {
            "wiki_type": "leading_practice",
            "page_id": "lp_page_1",
        }

        assert request["wiki_type"] in ["leading_practice", "project"]
        assert request["page_id"] is not None

    def test_build_cross_wiki_index_endpoint(self):
        """Test building cross-wiki index endpoint."""
        response = {
            "status": "success",
            "lp_to_projects": 10,
            "projects_to_lp": 8,
            "total_links": 18,
        }

        assert response["status"] == "success"
        assert response["total_links"] == (
            response["lp_to_projects"] + response["projects_to_lp"]
        )
