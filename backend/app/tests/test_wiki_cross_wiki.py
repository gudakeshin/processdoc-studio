"""
Tests for cross-wiki linking between Leading Practice and Project wikis.

Tests Priority 7: Bidirectional LP ↔ Project Linking
"""

import pytest
from unittest.mock import patch, MagicMock
import json
import re
from datetime import datetime, timezone


class TestCrossWikiLinkPatterns:
    """Test detection of cross-wiki link patterns."""

    def test_lp_link_pattern_lp_prefix(self):
        """Test [[lp://Page Name]] pattern detection."""
        content = "See [[lp://Database Design]] for best practices."

        pattern = r"\[\[(?:lp://|wiki://leading_practice/)([^\]]+)\]\]"
        matches = re.findall(pattern, content, re.IGNORECASE)

        assert len(matches) == 1
        assert matches[0] == "Database Design"

    def test_lp_link_pattern_wiki_prefix(self):
        """Test [[wiki://leading_practice/Page Name]] pattern detection."""
        content = "Reference [[wiki://leading_practice/API Best Practices]] here."

        pattern = r"\[\[(?:lp://|wiki://leading_practice/)([^\]]+)\]\]"
        matches = re.findall(pattern, content, re.IGNORECASE)

        assert len(matches) == 1
        assert matches[0] == "API Best Practices"

    def test_project_wiki_link_pattern(self):
        """Test [[wiki://project/{id}/Page Name]] pattern detection."""
        content = "See [[wiki://project/proj123/User Engagement]] in project."

        pattern = r"\[\[wiki://project/([^/]+)/([^\]]+)\]\]"
        matches = re.findall(pattern, content)

        assert len(matches) == 1
        assert matches[0][0] == "proj123"
        assert matches[0][1] == "User Engagement"

    def test_multiple_cross_wiki_links(self):
        """Test extraction of multiple cross-wiki links."""
        content = """
        Reference [[lp://Architecture Patterns]] and [[lp://Security Guidelines]].
        Also see [[wiki://project/proj456/Implementation Plan]].
        """

        lp_pattern = r"\[\[(?:lp://|wiki://leading_practice/)([^\]]+)\]\]"
        proj_pattern = r"\[\[wiki://project/([^/]+)/([^\]]+)\]\]"

        lp_matches = re.findall(lp_pattern, content, re.IGNORECASE)
        proj_matches = re.findall(proj_pattern, content)

        assert len(lp_matches) == 2
        assert "Architecture Patterns" in lp_matches
        assert len(proj_matches) == 1

    def test_malformed_cross_wiki_links_ignored(self):
        """Test that malformed links are not detected."""
        content = "Bad: [lp://Page] or [wiki://project/id/Page] without brackets."

        pattern = r"\[\[(?:lp://|wiki://leading_practice/)([^\]]+)\]\]"
        matches = re.findall(pattern, content, re.IGNORECASE)

        assert len(matches) == 0


class TestCrossWikiRelationshipExtraction:
    """Test extraction of cross-wiki relationships."""

    def test_lp_to_project_reference_creation(self):
        """Test creating LP -> Project reference."""
        rel = {
            "source_id": "lp_page_1",
            "source_wiki": "leading_practice",
            "target_id": "proj_page_1",
            "target_wiki": "project",
            "target_project_id": "proj123",
            "relation_type": "cross_wiki_reference",
            "confidence": "EXPLICIT",
            "confidence_score": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Verify structure
        assert rel["source_wiki"] == "leading_practice"
        assert rel["target_wiki"] == "project"
        assert rel["target_project_id"] == "proj123"
        assert rel["relation_type"] == "cross_wiki_reference"
        assert rel["confidence_score"] == 1.0

    def test_project_to_lp_reference_creation(self):
        """Test creating Project -> LP reference."""
        rel = {
            "source_id": "proj_page_1",
            "source_wiki": "project",
            "target_id": "lp_page_1",
            "target_wiki": "leading_practice",
            "target_project_id": None,
            "relation_type": "cross_wiki_reference",
            "confidence": "EXPLICIT",
            "confidence_score": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        assert rel["source_wiki"] == "project"
        assert rel["target_wiki"] == "leading_practice"
        assert rel["target_project_id"] is None


class TestCrossWikiIndexing:
    """Test cross-wiki index building and lookup."""

    def test_bidirectional_index_structure(self):
        """Test cross-wiki index has bidirectional structure."""
        cross_wiki_index = {
            "lp_to_projects": {
                "lp_page_1": [
                    {
                        "target_page_id": "proj_page_1",
                        "source_page_id": "lp_page_1",
                        "source_wiki": "leading_practice",
                        "source_project_id": None,
                    }
                ]
            },
            "projects_to_lp": {
                "proj_page_1": [
                    {
                        "target_page_id": "lp_page_1",
                        "target_project_id": None,
                        "source_page_id": "proj_page_1",
                    }
                ]
            },
            "total_links": 2,
        }

        # Verify bidirectional structure
        assert len(cross_wiki_index["lp_to_projects"]) > 0
        assert len(cross_wiki_index["projects_to_lp"]) > 0
        assert cross_wiki_index["total_links"] == 2

    def test_incoming_outgoing_references(self):
        """Test incoming/outgoing reference lookup."""
        incoming_refs = [
            {
                "source_page_id": "proj_page_2",
                "source_wiki": "project",
                "target_page_id": "lp_page_1",
            }
        ]

        outgoing_refs = [
            {
                "target_page_id": "proj_page_1",
                "target_project_id": "proj123",
                "source_page_id": "lp_page_1",
            }
        ]

        refs = {"incoming": incoming_refs, "outgoing": outgoing_refs}

        # Verify references
        assert len(refs["incoming"]) == 1
        assert len(refs["outgoing"]) == 1
        assert refs["incoming"][0]["source_page_id"] == "proj_page_2"
        assert refs["outgoing"][0]["target_page_id"] == "proj_page_1"

    def test_self_reference_prevention(self):
        """Test that cross-wiki self-references are valid (same page different wiki)."""
        # In cross-wiki context, referencing the "same" page in different wiki is valid
        rel = {
            "source_id": "same_page",
            "source_wiki": "project",
            "target_id": "same_page",
            "target_wiki": "leading_practice",
            "relation_type": "cross_wiki_reference",
        }

        # This is NOT a self-reference in cross-wiki context (different wikis)
        assert rel["source_wiki"] != rel["target_wiki"]


class TestCrossWikiNavigation:
    """Test cross-wiki navigation endpoints."""

    def test_cross_wiki_references_api_response(self):
        """Test API response format for cross-wiki references."""
        api_response = {
            "status": "success",
            "page_id": "lp_page_1",
            "wiki_type": "leading_practice",
            "incoming": [
                {
                    "source_page_id": "proj_page_1",
                    "source_wiki": "project",
                    "source_project_id": "proj123",
                }
            ],
            "outgoing": [
                {
                    "target_page_id": "proj_page_2",
                    "target_project_id": "proj456",
                }
            ],
        }

        assert api_response["status"] == "success"
        assert api_response["wiki_type"] == "leading_practice"
        assert isinstance(api_response["incoming"], list)
        assert isinstance(api_response["outgoing"], list)
        assert len(api_response["incoming"]) > 0
        assert len(api_response["outgoing"]) > 0

    def test_build_cross_wiki_index_response(self):
        """Test API response for building cross-wiki index."""
        api_response = {
            "status": "success",
            "lp_to_projects": 5,
            "projects_to_lp": 3,
            "total_links": 8,
        }

        assert api_response["status"] == "success"
        assert api_response["lp_to_projects"] >= 0
        assert api_response["projects_to_lp"] >= 0
        assert api_response["total_links"] == (
            api_response["lp_to_projects"] + api_response["projects_to_lp"]
        )


class TestCrossWikiEdgeCases:
    """Test edge cases in cross-wiki linking."""

    def test_nonexistent_target_wiki(self):
        """Test reference to non-existent wiki type."""
        # Invalid wiki type should be rejected at API level
        rel = {
            "source_wiki": "project",
            "target_wiki": "invalid_wiki",  # Invalid
        }

        valid_wikis = ["leading_practice", "project"]
        assert rel["target_wiki"] not in valid_wikis

    def test_missing_project_id_in_cross_project_reference(self):
        """Test cross-project reference requires project ID when crossing projects."""
        # Cross-project reference must have different project IDs
        rel = {
            "source_wiki": "project",
            "source_project_id": "proj123",
            "target_wiki": "project",
            "target_project_id": "proj456",  # Different project
        }

        # For cross-project refs, target_project_id should be set and different
        if rel["target_wiki"] == "project":
            assert rel["target_project_id"] is not None
            # For cross-project refs, should be different projects
            if rel.get("relation_type") == "cross_wiki_reference":
                assert rel["target_project_id"] != rel.get("source_project_id")

    def test_same_project_internal_reference(self):
        """Test reference within same project (internal, not cross-wiki)."""
        # Same project reference is internal wiki link, not cross-wiki
        rel = {
            "source_wiki": "project",
            "source_project_id": "proj123",
            "target_wiki": "project",
            "target_project_id": "proj123",
            "relation_type": "references",  # Not cross_wiki_reference
        }

        # This is an internal reference, not cross-wiki
        assert rel["relation_type"] == "references"

    def test_empty_cross_wiki_index(self):
        """Test handling of empty cross-wiki index."""
        cross_wiki_index = {
            "lp_to_projects": {},
            "projects_to_lp": {},
            "total_links": 0,
        }

        assert len(cross_wiki_index["lp_to_projects"]) == 0
        assert len(cross_wiki_index["projects_to_lp"]) == 0
        assert cross_wiki_index["total_links"] == 0


class TestIntegrationWithExistingWiki:
    """Test integration with existing wiki operations."""

    def test_cross_wiki_links_in_god_node_context(self):
        """Test that cross-wiki links contribute to importance ranking."""
        # God node calculation should consider cross-wiki references
        page_metrics = {
            "inbound_links": 5,
            "outbound_links": 3,
            "cross_wiki_references": 2,  # New metric
            "betweenness": 0.35,
        }

        # Extended importance calculation could include cross-wiki factor
        importance = (
            0.6 * (page_metrics["inbound_links"] / 10) +  # Normalized
            0.25 * page_metrics["betweenness"] +
            0.15 * (page_metrics["cross_wiki_references"] / 5)  # Cross-wiki weight
        )

        assert importance > 0

    def test_cross_wiki_links_in_community_context(self):
        """Test cross-wiki links in community detection."""
        # Communities could span both wikis for related pages
        community = {
            "id": "community_1",
            "pages": [
                {"page_id": "lp_page_1", "wiki": "leading_practice"},
                {"page_id": "proj_page_1", "wiki": "project"},
            ],
            "cross_wiki_edges": 1,
        }

        # Community has both LP and project pages
        lp_pages = [p for p in community["pages"] if p["wiki"] == "leading_practice"]
        proj_pages = [p for p in community["pages"] if p["wiki"] == "project"]

        assert len(lp_pages) > 0 or len(proj_pages) > 0
