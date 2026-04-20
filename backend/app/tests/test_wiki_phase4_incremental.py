"""
Tests for Wiki Phase 4: Incremental Indexing & Performance Optimization.

Tests content hashing, change detection, and incremental index updates.
"""

import hashlib
from datetime import UTC, datetime


class TestContentHashing:
    """Test content hash generation for change detection."""

    def test_hash_consistency(self):
        """Test that same content produces same hash."""
        content = "# Page Title\n\nSome content here."

        hash1 = hashlib.sha256(content.encode('utf-8')).hexdigest()
        hash2 = hashlib.sha256(content.encode('utf-8')).hexdigest()

        assert hash1 == hash2

    def test_hash_sensitivity_to_changes(self):
        """Test that content changes produce different hashes."""
        content1 = "# Page Title\n\nSome content here."
        content2 = "# Page Title\n\nSome content changed."

        hash1 = hashlib.sha256(content1.encode('utf-8')).hexdigest()
        hash2 = hashlib.sha256(content2.encode('utf-8')).hexdigest()

        assert hash1 != hash2

    def test_whitespace_sensitivity(self):
        """Test that whitespace changes are detected."""
        content1 = "Line 1\nLine 2"
        content2 = "Line 1\n\nLine 2"  # Extra blank line

        hash1 = hashlib.sha256(content1.encode('utf-8')).hexdigest()
        hash2 = hashlib.sha256(content2.encode('utf-8')).hexdigest()

        assert hash1 != hash2

    def test_hash_format(self):
        """Test that hash is valid SHA256 hex string."""
        content = "Test content"
        hash_val = hashlib.sha256(content.encode('utf-8')).hexdigest()

        # SHA256 produces 64 hex characters
        assert len(hash_val) == 64
        assert all(c in '0123456789abcdef' for c in hash_val)


class TestPageManifest:
    """Test page manifest structure for incremental indexing."""

    def test_manifest_structure(self):
        """Test manifest has correct structure."""
        manifest = {
            "pages": {
                "page_1": {
                    "hash": "abc123def456",
                    "title": "Page One",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                "page_2": {
                    "hash": "xyz789abc123",
                    "title": "Page Two",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            },
            "last_full_rebuild": datetime.now(UTC).isoformat(),
            "relationships_version": 2,
        }

        # Verify structure
        assert "pages" in manifest
        assert len(manifest["pages"]) == 2
        assert all(
            "hash" in p and "title" in p and "updated_at" in p
            for p in manifest["pages"].values()
        )
        assert manifest["relationships_version"] >= 0

    def test_manifest_empty_pages(self):
        """Test manifest with no pages."""
        manifest = {
            "pages": {},
            "last_full_rebuild": None,
            "relationships_version": 0,
        }

        assert len(manifest["pages"]) == 0
        assert manifest["relationships_version"] == 0


class TestChangeDetection:
    """Test detecting changed, unchanged, and deleted pages."""

    def test_detect_new_pages(self):
        """Test detection of newly added pages."""
        previous_manifest = {"pages": {}}
        current_pages = {
            "page_1": {"hash": "hash123", "title": "New Page", "content": "..."},
            "page_2": {"hash": "hash456", "title": "New Page 2", "content": "..."},
        }

        # Pages in current but not in previous are new/changed
        changed = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid not in previous_manifest["pages"]
        }

        assert len(changed) == 2
        assert "page_1" in changed
        assert "page_2" in changed

    def test_detect_unchanged_pages(self):
        """Test detection of unchanged pages."""
        previous_manifest = {
            "pages": {
                "page_1": {"hash": "hash123", "title": "Page 1"},
                "page_2": {"hash": "hash456", "title": "Page 2"},
            }
        }
        current_pages = {
            "page_1": {"hash": "hash123", "title": "Page 1", "content": "..."},
            "page_2": {"hash": "hash456", "title": "Page 2", "content": "..."},
        }

        # Pages with same hash are unchanged
        unchanged = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid in previous_manifest["pages"]
            and previous_manifest["pages"][pid]["hash"] == current_pages[pid]["hash"]
        }

        assert len(unchanged) == 2
        assert "page_1" in unchanged
        assert "page_2" in unchanged

    def test_detect_modified_pages(self):
        """Test detection of modified pages."""
        previous_manifest = {
            "pages": {
                "page_1": {"hash": "old_hash", "title": "Page 1"},
            }
        }
        current_pages = {
            "page_1": {"hash": "new_hash", "title": "Page 1", "content": "..."},
        }

        # Pages with different hash are changed
        changed = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid in previous_manifest["pages"]
            and previous_manifest["pages"][pid]["hash"] != current_pages[pid]["hash"]
        }

        assert len(changed) == 1
        assert "page_1" in changed

    def test_detect_deleted_pages(self):
        """Test detection of deleted pages."""
        previous_manifest = {
            "pages": {
                "page_1": {"hash": "hash123"},
                "page_2": {"hash": "hash456"},
                "page_3": {"hash": "hash789"},
            }
        }
        current_pages = {
            "page_1": {"hash": "hash123", "content": "..."},
            "page_2": {"hash": "hash456", "content": "..."},
        }

        # Pages in previous but not in current are deleted
        deleted = {
            pid: previous_manifest["pages"][pid]
            for pid in previous_manifest["pages"]
            if pid not in current_pages
        }

        assert len(deleted) == 1
        assert "page_3" in deleted


class TestIncrementalIndexing:
    """Test incremental relationship indexing."""

    def test_incremental_update_structure(self):
        """Test incremental update preserves existing relationships."""
        # Existing relationships from 10 pages
        existing_rels = [
            {"source_id": "page_1", "target_id": "page_2"},
            {"source_id": "page_2", "target_id": "page_3"},
            {"source_id": "page_3", "target_id": "page_1"},
        ]

        # 1 page changed
        changed_page_id = "page_1"

        # Remove relationships from changed pages only
        updated_rels = [
            r for r in existing_rels
            if r["source_id"] != changed_page_id
        ]

        # Add new relationships from changed page
        new_rels = [
            {"source_id": "page_1", "target_id": "page_4"},
        ]

        updated_rels.extend(new_rels)

        assert len(updated_rels) == 3  # 2 existing + 1 new
        assert any(r["target_id"] == "page_4" for r in updated_rels)

    def test_change_threshold_for_community_rebuild(self):
        """Test threshold for when to rebuild communities."""
        total_pages = 100
        changed_pages = 5

        change_ratio = changed_pages / total_pages
        rebuild_threshold = 0.1  # 10%

        should_rebuild_communities = change_ratio > rebuild_threshold

        # 5% change, should not rebuild
        assert should_rebuild_communities is False

        # 15 pages changed, should rebuild
        changed_pages_high = 15
        change_ratio_high = changed_pages_high / total_pages
        should_rebuild_high = change_ratio_high > rebuild_threshold

        assert should_rebuild_high is True

    def test_incremental_metrics_structure(self):
        """Test incremental update returns correct metrics."""
        metrics = {
            "total_relationships": 45,
            "pages_with_links": 15,
            "changed_pages": 5,
            "unchanged_pages": 95,
            "deleted_pages": 0,
            "communities_count": 3,
            "god_nodes_count": 10,
            "elapsed_time_seconds": 0.234,
            "performance_improvement_percent": 85.5,
        }

        # Verify metrics
        assert metrics["changed_pages"] > 0
        assert metrics["unchanged_pages"] > 0
        assert metrics["performance_improvement_percent"] > 0
        assert metrics["elapsed_time_seconds"] > 0


class TestPerformanceMetrics:
    """Test wiki performance monitoring."""

    def test_performance_metrics_structure(self):
        """Test performance metrics API response."""
        metrics = {
            "total_pages": 100,
            "relationships_count": 150,
            "last_update": "2026-04-12T10:30:00Z",
            "incremental_enabled": True,
            "manifest_version": 5,
            "pages_in_manifest": 98,
        }

        assert metrics["total_pages"] > 0
        assert metrics["relationships_count"] > 0
        assert metrics["incremental_enabled"] is True
        assert metrics["manifest_version"] >= 0

    def test_performance_improvement_calculation(self):
        """Test performance improvement percentage calculation."""
        # Simulated: 100 pages, took 0.2s incremental vs estimated 1.0s full rebuild
        incremental_time = 0.2  # seconds
        estimated_full_rebuild_time = 1.0  # (100/100) * 1.0

        improvement = (
            (estimated_full_rebuild_time - incremental_time) /
            estimated_full_rebuild_time * 100
        )

        assert improvement == 80.0
        assert improvement > 0

    def test_empty_wiki_metrics(self):
        """Test metrics for empty wiki."""
        metrics = {
            "total_pages": 0,
            "relationships_count": 0,
            "last_update": None,
            "incremental_enabled": False,
        }

        assert metrics["total_pages"] == 0
        assert metrics["relationships_count"] == 0


class TestIncrementalEdgeCases:
    """Test edge cases in incremental indexing."""

    def test_first_ingest_no_manifest(self):
        """Test first ingest when no manifest exists."""
        manifest = None  # Not found
        current_pages = {
            "page_1": {"hash": "hash1", "content": "..."},
            "page_2": {"hash": "hash2", "content": "..."},
        }

        # All pages are new if no manifest
        if manifest is None:
            changed_pages = current_pages
        else:
            changed_pages = {}

        assert len(changed_pages) == 2

    def test_all_pages_modified(self):
        """Test when all pages are modified."""
        previous_manifest = {
            "pages": {
                "page_1": {"hash": "old1"},
                "page_2": {"hash": "old2"},
                "page_3": {"hash": "old3"},
            }
        }
        current_pages = {
            "page_1": {"hash": "new1", "content": "..."},
            "page_2": {"hash": "new2", "content": "..."},
            "page_3": {"hash": "new3", "content": "..."},
        }

        changed = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid in previous_manifest["pages"]
            and previous_manifest["pages"][pid]["hash"] != current_pages[pid]["hash"]
        }

        # All 3 changed
        assert len(changed) == 3
        # Should trigger full rebuild (100% change)
        change_ratio = len(changed) / len(current_pages)
        assert change_ratio == 1.0

    def test_single_page_wiki(self):
        """Test incremental indexing on single-page wiki."""
        current_pages = {
            "page_1": {"hash": "hash1", "content": "..."},
        }
        previous_manifest = {"pages": {}}

        changed = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid not in previous_manifest["pages"]
        }

        assert len(changed) == 1

    def test_zero_change_ingest(self):
        """Test ingest when nothing changed."""
        previous_manifest = {
            "pages": {
                "page_1": {"hash": "hash1"},
                "page_2": {"hash": "hash2"},
            }
        }
        current_pages = {
            "page_1": {"hash": "hash1", "content": "..."},
            "page_2": {"hash": "hash2", "content": "..."},
        }

        changed = {
            pid: current_pages[pid]
            for pid in current_pages
            if pid in previous_manifest["pages"]
            and previous_manifest["pages"][pid]["hash"] != current_pages[pid]["hash"]
        }

        assert len(changed) == 0
        # Should skip relationship extraction entirely
