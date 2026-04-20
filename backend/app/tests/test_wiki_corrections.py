"""
Tests for wiki auto-correction (Cowork Tier 2).

Tests the correction of common wiki data quality issues:
- Malformed frontmatter
- Broken references
- Inconsistent formatting
- Data type mismatches
- Duplicate content
- Stale references
"""

import json
from datetime import UTC, datetime

from app.services.wiki_corrections import DataCorrector

# ===== Tier 2: Frontmatter Correction Tests (8 tests) =====

class TestDataCorrectorFrontmatter:
    """Test frontmatter correction (missing fields, invalid values)."""

    def test_correct_frontmatter_adds_missing_category(self):
        """Should auto-detect and add missing category."""
        page = {
            "frontmatter": "{}",
            "content": "This is a comparison between A and B",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["category"] in {"entity", "concept", "comparison", "template", "synthesis", "artifact"}
        assert "category" in str(corrections).lower()

    def test_correct_frontmatter_adds_missing_source_count(self):
        """Should add missing source_count from source_ids."""
        page = {
            "frontmatter": "{}",
            "source_run_ids": '["run_1", "run_2"]',
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["source_count"] == 2
        assert any("source_count" in c.lower() for c in corrections)

    def test_correct_frontmatter_adds_missing_last_updated(self):
        """Should add missing last_updated timestamp."""
        page = {
            "frontmatter": "{}",
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert "last_updated" in fm
        assert any("last_updated" in c.lower() for c in corrections)

    def test_correct_frontmatter_adds_missing_confidence(self):
        """Should add missing confidence with default value."""
        page = {
            "frontmatter": "{}",
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["confidence"] == "medium"
        assert any("confidence" in c.lower() for c in corrections)

    def test_correct_frontmatter_snaps_invalid_confidence(self):
        """Should snap invalid confidence to valid option."""
        page = {
            "frontmatter": json.dumps({"confidence": "very_high"}),
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["confidence"] in {"low", "medium", "high"}
        assert any("snap" in c.lower() or "confidence" in c.lower() for c in corrections)

    def test_correct_frontmatter_preserves_valid_fields(self):
        """Should preserve already-valid frontmatter fields."""
        page = {
            "frontmatter": json.dumps({"category": "entity", "confidence": "high"}),
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["category"] == "entity"
        assert fm["confidence"] == "high"

    def test_correct_frontmatter_empty_frontmatter(self):
        """Should handle empty frontmatter gracefully."""
        page = {
            "frontmatter": "{}",
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        # Should have added at least some fields
        assert len(fm) > 0
        assert len(corrections) > 0

    def test_correct_frontmatter_all_missing_fields(self):
        """Should handle completely empty frontmatter."""
        page = {
            "frontmatter": "{}",
            "source_run_ids": "[]",
            "content": "Content",
        }
        corrected, corrections = DataCorrector.correct_frontmatter(page)

        fm = json.loads(corrected["frontmatter"])
        assert "category" in fm
        assert "source_count" in fm
        assert "last_updated" in fm
        assert "confidence" in fm
        assert len(corrections) >= 4


# ===== Tier 2: Reference Correction Tests (3 tests) =====

class TestDataCorrectorReferences:
    """Test broken reference detection and correction."""

    def test_correct_references_detects_broken_links(self):
        """Should detect links to non-existent pages."""
        page = {
            "content": "[See DASH Framework](DASH_Framework.md)\n[Also see Nonexistent](Nonexistent.md)",
            "id": "p1",
        }
        wiki_index = {
            "pages": [
                {"slug": "DASH_Framework.md", "title": "DASH Framework"},
            ]
        }

        corrected, corrections = DataCorrector.correct_references(page, wiki_index)

        assert any("broken" in c.lower() or "Nonexistent" in c for c in corrections)

    def test_correct_references_ignores_valid_links(self):
        """Should not flag valid links."""
        page = {
            "content": "[See DASH Framework](DASH_Framework.md)",
            "id": "p1",
        }
        wiki_index = {
            "pages": [
                {"slug": "DASH_Framework.md", "title": "DASH Framework"},
            ]
        }

        corrected, corrections = DataCorrector.correct_references(page, wiki_index)

        assert len(corrections) == 0 or all("broken" not in c.lower() for c in corrections)

    def test_correct_references_empty_content(self):
        """Should handle pages with no links gracefully."""
        page = {
            "content": "Just plain text, no links here.",
            "id": "p1",
        }
        wiki_index = {"pages": []}

        corrected, corrections = DataCorrector.correct_references(page, wiki_index)

        assert len(corrections) == 0


# ===== Tier 2: Formatting Correction Tests (5 tests) =====

class TestDataCorrectorFormatting:
    """Test formatting normalization."""

    def test_correct_formatting_normalizes_list_markers(self):
        """Should normalize * list markers to -."""
        text = "* Item 1\n* Item 2"
        corrected, corrections = DataCorrector.correct_formatting(text)

        assert "- Item 1" in corrected
        assert "- Item 2" in corrected
        assert any("list" in c.lower() for c in corrections)

    def test_correct_formatting_normalizes_blank_lines(self):
        """Should normalize multiple blank lines to single blank."""
        text = "Line 1\n\n\n\nLine 2"
        corrected, corrections = DataCorrector.correct_formatting(text)

        assert "Line 1\n\nLine 2" in corrected
        assert any("blank" in c.lower() for c in corrections)

    def test_correct_formatting_removes_trailing_whitespace(self):
        """Should remove trailing whitespace from lines."""
        text = "Line 1   \nLine 2  \nLine 3"
        corrected, corrections = DataCorrector.correct_formatting(text)

        lines = corrected.split('\n')
        assert all(not line.endswith(' ') for line in lines)
        assert any("trailing" in c.lower() or "whitespace" in c.lower() for c in corrections)

    def test_correct_formatting_no_changes_needed(self):
        """Should return empty corrections list if formatting is correct."""
        text = "- Item 1\n- Item 2\n\nNext section"
        corrected, corrections = DataCorrector.correct_formatting(text)

        assert corrected == text
        assert len(corrections) == 0

    def test_correct_formatting_multiple_issues(self):
        """Should handle multiple formatting issues in one pass."""
        text = "* Item 1   \n\n\n\n* Item 2  "
        corrected, corrections = DataCorrector.correct_formatting(text)

        assert "- Item 1" in corrected
        assert "- Item 2" in corrected
        assert len(corrections) >= 2


# ===== Tier 2: Data Type Correction Tests (4 tests) =====

class TestDataCorrectorDataTypes:
    """Test data type conversion and validation."""

    def test_correct_data_types_converts_string_source_count(self):
        """Should convert string source_count to int."""
        page = {
            "frontmatter": json.dumps({"source_count": "5"}),
        }
        corrected, corrections = DataCorrector.correct_data_types(page)

        fm = json.loads(corrected["frontmatter"])
        assert isinstance(fm["source_count"], int)
        assert fm["source_count"] == 5
        assert any("convert" in c.lower() for c in corrections)

    def test_correct_data_types_handles_invalid_source_count(self):
        """Should set source_count to 0 if conversion fails."""
        page = {
            "frontmatter": json.dumps({"source_count": "not_a_number"}),
        }
        corrected, corrections = DataCorrector.correct_data_types(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["source_count"] == 0
        assert any("could not convert" in c.lower() for c in corrections)

    def test_correct_data_types_snaps_invalid_confidence(self):
        """Should snap invalid confidence to medium."""
        page = {
            "frontmatter": json.dumps({"confidence": "VERY_HIGH"}),
        }
        corrected, corrections = DataCorrector.correct_data_types(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["confidence"] == "medium"
        assert any("snap" in c.lower() for c in corrections)

    def test_correct_data_types_preserves_valid_types(self):
        """Should not modify already-valid data types."""
        page = {
            "frontmatter": json.dumps({"source_count": 5, "confidence": "high"}),
        }
        corrected, corrections = DataCorrector.correct_data_types(page)

        fm = json.loads(corrected["frontmatter"])
        assert fm["source_count"] == 5
        assert fm["confidence"] == "high"
        assert len(corrections) == 0


# ===== Tier 2: Duplication Detection Tests (3 tests) =====

class TestDataCorrectorDuplication:
    """Test duplicate content detection."""

    def test_correct_duplication_detects_similar_titles(self):
        """Should detect pages with very similar titles."""
        pages = [
            {"id": "p1", "category": "entity", "title": "DASH Framework"},
            {"id": "p2", "category": "entity", "title": "DASH Framework Overview"},
        ]
        all_pages, suggestions = DataCorrector.correct_duplication(pages)

        assert len(suggestions) > 0
        assert any("duplicate" in s.get("type", "").lower() for s in suggestions)

    def test_correct_duplication_ignores_different_titles(self):
        """Should not flag pages with clearly different titles."""
        pages = [
            {"id": "p1", "category": "entity", "title": "DASH Framework"},
            {"id": "p2", "category": "entity", "title": "Lean Six Sigma"},
        ]
        all_pages, suggestions = DataCorrector.correct_duplication(pages)

        assert len(suggestions) == 0

    def test_correct_duplication_empty_list(self):
        """Should handle empty page list gracefully."""
        pages = []
        all_pages, suggestions = DataCorrector.correct_duplication(pages)

        assert len(suggestions) == 0


# ===== Tier 2: Stale Reference Detection Tests (3 tests) =====

class TestDataCorrectorStaleReferences:
    """Test stale reference detection."""

    def test_correct_stale_references_detects_stale_content(self):
        """Should detect pages with newer related ingests."""
        now = datetime.now(UTC).isoformat()
        old_date = "2020-01-01T00:00:00+00:00"

        page = {
            "title": "Financial Modeling Best Practices",
            "updated_at": old_date,
            "id": "p1",
        }
        log_entries = [
            {
                "timestamp": now,
                "source_name": "Financial Modeling Updates 2024",
                "operation": "ingest",
            }
        ]

        corrected, corrections = DataCorrector.correct_stale_references(page, log_entries)

        assert any("stale" in c.lower() for c in corrections)

    def test_correct_stale_references_ignores_unrelated_ingests(self):
        """Should not flag staleness for unrelated topics."""
        now = datetime.now(UTC).isoformat()
        old_date = "2020-01-01T00:00:00+00:00"

        page = {
            "title": "Financial Modeling",
            "updated_at": old_date,
            "id": "p1",
        }
        log_entries = [
            {
                "timestamp": now,
                "source_name": "Marketing Strategy Update",
                "operation": "ingest",
            }
        ]

        corrected, corrections = DataCorrector.correct_stale_references(page, log_entries)

        # Should not flag as stale since the ingest is unrelated
        assert len(corrections) == 0 or all("stale" not in c.lower() for c in corrections)

    def test_correct_stale_references_no_log_entries(self):
        """Should handle missing log gracefully."""
        page = {
            "title": "Some Topic",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "id": "p1",
        }
        log_entries = []

        corrected, corrections = DataCorrector.correct_stale_references(page, log_entries)

        assert len(corrections) == 0


# ===== Tier 2: Citation Correction Tests (2 tests) =====

class TestDataCorrectorCitations:
    """Test missing citation detection and addition."""

    def test_correct_missing_citations_adds_citations(self):
        """Should add citations block if missing."""
        answer = "The answer is found in the best practices."
        source_pages = [
            {"id": "p1", "title": "Best Practices Page"},
            {"id": "p2", "title": "Guide Page"},
        ]

        corrected, corrections = DataCorrector.correct_missing_citations(answer, source_pages)

        assert "Sources:" in corrected or "Citation" in corrected
        assert "Best Practices Page" in corrected
        assert "Guide Page" in corrected
        assert any("citation" in c.lower() for c in corrections)

    def test_correct_missing_citations_skips_if_present(self):
        """Should not add citations if already present."""
        answer = "The answer is here.\n\n**Sources:**\n- Page 1"
        source_pages = [
            {"id": "p1", "title": "Page 1"},
        ]

        corrected, corrections = DataCorrector.correct_missing_citations(answer, source_pages)

        # Should return original since citations already present
        assert len(corrections) == 0


# ===== Integration Tests (5 tests) =====

class TestDataCorrectorIntegration:
    """Integration tests combining multiple corrections."""

    def test_all_corrections_work_independently(self):
        """Each correction method should work independently."""
        # Test that each method doesn't have side effects on others
        page = {
            "id": "p1",
            "title": "Test Page",
            "content": "* Item 1\n\n\n* Item 2",
            "frontmatter": json.dumps({"confidence": "INVALID"}),
            "source_run_ids": "[]",
        }

        # Apply frontmatter correction
        corrected1, corr1 = DataCorrector.correct_frontmatter(page)
        assert len(corr1) > 0

        # Apply formatting correction
        corrected2, corr2 = DataCorrector.correct_formatting(page["content"])
        assert len(corr2) > 0

        # Apply data type correction
        corrected3, corr3 = DataCorrector.correct_data_types(page)
        assert len(corr3) > 0

    def test_correction_returns_proper_tuple(self):
        """All correction methods should return (corrected_item, list_of_corrections)."""
        page = {"frontmatter": "{}", "content": "Test"}
        wiki_index = {"pages": []}

        # Test each method returns proper tuple
        result1 = DataCorrector.correct_frontmatter(page)
        assert isinstance(result1, tuple) and len(result1) == 2
        assert isinstance(result1[1], list)

        result2 = DataCorrector.correct_references(page, wiki_index)
        assert isinstance(result2, tuple) and len(result2) == 2

        result3 = DataCorrector.correct_formatting("test")
        assert isinstance(result3, tuple) and len(result3) == 2

        result4 = DataCorrector.correct_data_types(page)
        assert isinstance(result4, tuple) and len(result4) == 2

        result5 = DataCorrector.correct_duplication([page])
        assert isinstance(result5, tuple) and len(result5) == 2

        result6 = DataCorrector.correct_stale_references(page, [])
        assert isinstance(result6, tuple) and len(result6) == 2

        result7 = DataCorrector.correct_missing_citations("answer", [])
        assert isinstance(result7, tuple) and len(result7) == 2

    def test_sequential_corrections_work(self):
        """Should be able to apply corrections sequentially."""
        page = {
            "frontmatter": json.dumps({"confidence": "INVALID"}),
            "content": "* Item 1\n\n\n* Item 2",
            "source_run_ids": "[]",
        }

        # Apply corrections in sequence
        page, c1 = DataCorrector.correct_data_types(page)
        page["content"], c2 = DataCorrector.correct_formatting(page["content"])
        page, c3 = DataCorrector.correct_frontmatter(page)

        # Should have made corrections in each step
        total_corrections = len(c1) + len(c2) + len(c3)
        assert total_corrections > 0

    def test_correction_audit_trail(self):
        """Corrections list should serve as audit trail."""
        page = {
            "frontmatter": "{}",
            "source_run_ids": "[]",
            "content": "Content",
        }

        corrected, corrections = DataCorrector.correct_frontmatter(page)

        # Each correction should be human-readable
        assert all(isinstance(c, str) and len(c) > 0 for c in corrections)
        # Should be able to understand what was fixed
        assert all(c[0].isupper() for c in corrections)  # Capitalized sentences

    def test_no_data_loss_on_correction(self):
        """Corrections should never lose data."""
        page = {
            "id": "original_id",
            "title": "Original Title",
            "frontmatter": json.dumps({"custom_field": "value"}),
            "content": "Important content that must be preserved",
            "source_run_ids": "[]",
        }

        corrected, corrections = DataCorrector.correct_frontmatter(page)

        # Original fields should be preserved
        assert corrected["id"] == page["id"]
        assert corrected["title"] == page["title"]
        assert corrected["content"] == page["content"]

        # Custom fields in frontmatter should be preserved
        fm = json.loads(corrected["frontmatter"])
        assert fm.get("custom_field") == "value"
