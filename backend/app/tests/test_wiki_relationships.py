"""
Tests for wiki relationship extraction and graph building.

Tests Priority 1: Relationship Extraction & Graph Building
"""

from app.services.wiki_operations import (
    _extract_relationships,
)


class TestRelationshipExtraction:
    """Test explicit and inferred relationship extraction."""

    def test_extract_explicit_links(self):
        """Test extraction of [[Page Name]] explicit links."""
        content = """
# Test Page

This page references [[Financial Framework]] and [[Process Design]].

Some other content.
        """

        all_page_ids = ["test_page", "financial_framework", "process_design"]
        all_page_titles = ["Test Page", "Financial Framework", "Process Design"]

        rels = _extract_relationships("test_page", content, all_page_ids, all_page_titles)

        # Should find 2 explicit links
        explicit_rels = [r for r in rels if r["confidence"] == "EXPLICIT"]
        assert len(explicit_rels) == 2

        target_ids = [r["target_id"] for r in explicit_rels]
        assert "financial_framework" in target_ids
        assert "process_design" in target_ids

        # Check confidence scores
        for rel in explicit_rels:
            assert rel["confidence_score"] == 1.0
            assert rel["relation_type"] == "references"

    def test_extract_inferred_links(self):
        """Test extraction of page title mentions as inferred links."""
        content = """
# Test Page

The Financial Framework is important. We use Financial Framework principles.
The Financial Framework helps with planning.

Some other content with different text.
        """

        all_page_ids = ["test_page", "financial_framework"]
        all_page_titles = ["Test Page", "Financial Framework"]

        rels = _extract_relationships("test_page", content, all_page_ids, all_page_titles)

        # Should find 1 inferred link (3 mentions >= 2 threshold)
        inferred_rels = [r for r in rels if r["confidence"] == "INFERRED"]
        assert len(inferred_rels) == 1

        rel = inferred_rels[0]
        assert rel["target_id"] == "financial_framework"
        assert rel["relation_type"] == "mentions"
        assert 0.5 <= rel["confidence_score"] <= 0.95

    def test_skip_self_references(self):
        """Test that self-references are skipped."""
        content = """
# Test Page

Test Page mentions Test Page internally. Test Page is important.
        """

        all_page_ids = ["test_page"]
        all_page_titles = ["Test Page"]

        rels = _extract_relationships("test_page", content, all_page_ids, all_page_titles)

        # Should not find self-reference
        assert len(rels) == 0

    def test_nonexistent_target_skipped(self):
        """Test that links to non-existent pages are skipped."""
        content = """
# Test Page

This references [[Nonexistent Page]] which doesn't exist.
        """

        all_page_ids = ["test_page"]
        all_page_titles = ["Test Page"]

        rels = _extract_relationships("test_page", content, all_page_ids, all_page_titles)

        # Should not find link to nonexistent page
        assert len(rels) == 0

    def test_mixed_relationships(self):
        """Test extraction of both explicit and inferred links."""
        content = """
# DASH Framework

The DASH Framework references [[Financial Model]] for analysis.

Organizational process is important. Organizational process helps with planning.
Organizational process is key to success.
        """

        all_page_ids = ["dash_framework", "financial_model", "organizational_process"]
        all_page_titles = ["DASH Framework", "Financial Model", "Organizational Process"]

        rels = _extract_relationships("dash_framework", content, all_page_ids, all_page_titles)

        # Should find 1 explicit (Financial Model) + 1 inferred (Organizational Process)
        explicit = [r for r in rels if r["confidence"] == "EXPLICIT"]
        inferred = [r for r in rels if r["confidence"] == "INFERRED"]

        assert len(explicit) == 1
        assert len(inferred) == 1
        assert explicit[0]["target_id"] == "financial_model"
        assert inferred[0]["target_id"] == "organizational_process"


class TestRelationshipCounts:
    """Test relationship counting and statistics."""

    def test_calculate_inbound_outbound_counts(self):
        """Test calculation of inbound/outbound link counts."""
        relationships = [
            {
                "source_id": "page_a",
                "target_id": "page_b",
                "relation_type": "references",
                "confidence": "EXPLICIT",
                "confidence_score": 1.0,
                "source_location": "L10",
                "created_at": "2026-04-12T00:00:00Z",
            },
            {
                "source_id": "page_a",
                "target_id": "page_c",
                "relation_type": "mentions",
                "confidence": "INFERRED",
                "confidence_score": 0.75,
                "source_location": "L15",
                "created_at": "2026-04-12T00:00:00Z",
            },
            {
                "source_id": "page_b",
                "target_id": "page_a",
                "relation_type": "references",
                "confidence": "EXPLICIT",
                "confidence_score": 1.0,
                "source_location": "L5",
                "created_at": "2026-04-12T00:00:00Z",
            },
        ]

        # Build counts dict
        counts = {}
        for rel in relationships:
            source = rel["source_id"]
            target = rel["target_id"]

            if source not in counts:
                counts[source] = {"outbound": 0, "inbound": 0}
            if target not in counts:
                counts[target] = {"outbound": 0, "inbound": 0}

            counts[source]["outbound"] += 1
            counts[target]["inbound"] += 1

        # Verify counts
        assert counts["page_a"]["outbound"] == 2
        assert counts["page_a"]["inbound"] == 1
        assert counts["page_b"]["outbound"] == 1
        assert counts["page_b"]["inbound"] == 1
        assert counts["page_c"]["outbound"] == 0
        assert counts["page_c"]["inbound"] == 1
