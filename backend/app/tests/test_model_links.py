"""Test suite for model linking and cross-model references."""

import pytest

from app.services.model_links import (
    ModelLinkValidator,
    build_model_dependency_graph,
    create_model_link,
    get_link_impact,
    list_model_links,
    resolve_cell_reference,
    sync_linked_cells,
    validate_all_links,
)


class TestModelLinkValidator:
    """Test model link validation."""

    def test_validate_cell_reference_valid(self):
        """Test valid cell references."""
        assert ModelLinkValidator.validate_cell_reference("A1") is True
        assert ModelLinkValidator.validate_cell_reference("Z99") is True
        assert ModelLinkValidator.validate_cell_reference("AA100") is True
        assert ModelLinkValidator.validate_cell_reference("AAA1000") is True

    def test_validate_cell_reference_invalid(self):
        """Test invalid cell references."""
        assert ModelLinkValidator.validate_cell_reference("1A") is False  # Number first
        assert ModelLinkValidator.validate_cell_reference("A") is False   # No number
        assert ModelLinkValidator.validate_cell_reference("1") is False   # No letter
        assert ModelLinkValidator.validate_cell_reference("") is False    # Empty
        assert ModelLinkValidator.validate_cell_reference(None) is False  # None
        assert ModelLinkValidator.validate_cell_reference("A1B2") is False  # Mixed

    def test_detect_circular_direct(self):
        """Test detection of direct circular dependency."""
        links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
            }
        ]

        # Adding link from B to A would create cycle
        is_circular = ModelLinkValidator.detect_circular_dependency(
            "model_b",
            "model_a",
            links,
        )

        assert is_circular is True

    def test_detect_circular_indirect(self):
        """Test detection of indirect circular dependency."""
        links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
            },
            {
                "source_model_id": "model_b",
                "target_model_id": "model_c",
            },
        ]

        # Adding link from C to A would create A->B->C->A cycle
        is_circular = ModelLinkValidator.detect_circular_dependency(
            "model_c",
            "model_a",
            links,
        )

        assert is_circular is True

    def test_detect_no_circular(self):
        """Test when no circular dependency exists."""
        links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
            },
        ]

        # Adding link from C to B doesn't create cycle
        is_circular = ModelLinkValidator.detect_circular_dependency(
            "model_c",
            "model_b",
            links,
        )

        assert is_circular is False


class TestCreateModelLink:
    """Test model link creation."""

    def test_create_link_basic(self):
        """Test basic link creation."""
        link = create_model_link(
            source_model_id="revenue_model",
            source_cell_ref="B5",
            target_model_id="profit_model",
            target_cell_ref="A2",
            all_links=[],
        )

        assert link["source_model_id"] == "revenue_model"
        assert link["source_cell_ref"] == "B5"
        assert link["target_model_id"] == "profit_model"
        assert link["target_cell_ref"] == "A2"
        assert link["status"] == "active"

    def test_create_link_self_reference(self):
        """Test that self-referencing links are rejected."""
        with pytest.raises(ValueError):
            create_model_link(
                source_model_id="model_a",
                source_cell_ref="A1",
                target_model_id="model_a",
                target_cell_ref="B1",
                all_links=[],
            )

    def test_create_link_invalid_source_cell(self):
        """Test invalid source cell reference."""
        with pytest.raises(ValueError):
            create_model_link(
                source_model_id="model_a",
                source_cell_ref="1A",  # Invalid
                target_model_id="model_b",
                target_cell_ref="B1",
                all_links=[],
            )

    def test_create_link_circular_dependency(self):
        """Test rejection of circular dependencies."""
        existing_links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
            }
        ]

        with pytest.raises(ValueError) as exc_info:
            create_model_link(
                source_model_id="model_b",
                source_cell_ref="A1",
                target_model_id="model_a",
                target_cell_ref="B1",
                all_links=existing_links,
            )

        assert "circular" in str(exc_info.value).lower()


class TestLinkDependencies:
    """Test dependency graph and impact analysis."""

    def test_build_dependency_graph(self):
        """Test building dependency graph."""
        links = [
            {"source_model_id": "model_a", "target_model_id": "model_b", "status": "active"},
            {"source_model_id": "model_a", "target_model_id": "model_c", "status": "active"},
            {"source_model_id": "model_b", "target_model_id": "model_d", "status": "active"},
        ]

        graph = build_model_dependency_graph(links)

        # model_a has dependents b and c
        assert "model_b" in graph["dependents"].get("model_a", [])
        assert "model_c" in graph["dependents"].get("model_a", [])

        # model_b depends on model_a
        assert "model_a" in graph["dependencies"].get("model_b", [])

    def test_get_link_impact_direct(self):
        """Test impact analysis for direct dependents."""
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "target_model_id": "model_b",
                "target_cell_ref": "A1",
                "status": "active",
            },
            {
                "id": "link_2",
                "source_model_id": "model_a",
                "target_model_id": "model_c",
                "target_cell_ref": "B1",
                "status": "active",
            },
        ]

        impact = get_link_impact("model_a", links)

        assert impact["changed_model"] == "model_a"
        assert impact["directly_affected_links"] == 2
        assert "model_b" in impact["affected_models"]
        assert "model_c" in impact["affected_models"]

    def test_get_link_impact_indirect(self):
        """Test impact analysis for indirect dependents."""
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "target_model_id": "model_b",
                "target_cell_ref": "A1",
                "status": "active",
            },
            {
                "id": "link_2",
                "source_model_id": "model_b",
                "target_model_id": "model_c",
                "target_cell_ref": "B1",
                "status": "active",
            },
        ]

        impact = get_link_impact("model_a", links)

        # Changes to model_a affect model_b directly
        # model_b changes should affect model_c indirectly
        assert "model_b" in impact["affected_models"]
        assert "model_c" in impact["affected_models"]


class TestResolveCellReference:
    """Test cell reference resolution."""

    def test_resolve_linked_cell(self):
        """Test resolving a linked cell."""
        links = [
            {
                "source_model_id": "source_model",
                "source_cell_ref": "A1",
                "target_model_id": "target_model",
                "target_cell_ref": "B5",
                "status": "active",
                "id": "link_123",
            }
        ]

        result = resolve_cell_reference("target_model", "B5", 100, links)

        assert result["is_linked"] is True
        assert result["source_model_id"] == "source_model"
        assert result["source_cell_ref"] == "A1"
        assert result["resolution_type"] == "linked"

    def test_resolve_local_cell(self):
        """Test resolving a local (non-linked) cell."""
        result = resolve_cell_reference("model_a", "A1", 50, [])

        assert result["is_linked"] is False
        assert result["resolution_type"] == "local"
        assert result["current_value"] == 50


class TestSyncLinkedCells:
    """Test syncing linked cell values."""

    def test_sync_linked_cells_basic(self):
        """Test basic cell sync."""
        assumptions = {"Revenue": 1000, "COGS": 400}
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "Revenue",
                "target_model_id": "model_b",
                "target_cell_ref": "A1",
                "status": "active",
            },
        ]

        result = sync_linked_cells("model_a", assumptions, links)

        assert result["synced_cell_count"] == 1
        assert result["error_count"] == 0

    def test_sync_linked_cells_missing_source(self):
        """Test sync with missing source cell."""
        assumptions = {"Revenue": 1000}
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "COGS",  # Not in assumptions
                "target_model_id": "model_b",
                "target_cell_ref": "A1",
                "status": "active",
            },
        ]

        result = sync_linked_cells("model_a", assumptions, links)

        assert result["synced_cell_count"] == 0
        assert result["error_count"] == 1

    def test_sync_linked_cells_multiple(self):
        """Test syncing multiple cells."""
        assumptions = {"Revenue": 1000, "COGS": 400, "OpEx": 200}
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "Revenue",
                "target_model_id": "model_b",
                "target_cell_ref": "A1",
                "status": "active",
            },
            {
                "id": "link_2",
                "source_model_id": "model_a",
                "source_cell_ref": "COGS",
                "target_model_id": "model_b",
                "target_cell_ref": "A2",
                "status": "active",
            },
        ]

        result = sync_linked_cells("model_a", assumptions, links)

        assert result["synced_cell_count"] == 2
        assert result["error_count"] == 0


class TestValidateLinks:
    """Test link validation."""

    def test_validate_links_clean(self):
        """Test validation of clean links."""
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "A1",
                "target_model_id": "model_b",
                "target_cell_ref": "B1",
            },
        ]

        result = validate_all_links(links)

        assert result["valid_links"] == 1
        assert result["issue_count"] == 0
        assert result["health"] == "good"

    def test_validate_links_circular(self):
        """Test validation detects circular dependency."""
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "A1",
                "target_model_id": "model_b",
                "target_cell_ref": "B1",
            },
            {
                "id": "link_2",
                "source_model_id": "model_b",
                "source_cell_ref": "B1",
                "target_model_id": "model_a",
                "target_cell_ref": "A1",
            },
        ]

        result = validate_all_links(links)

        assert result["issue_count"] > 0
        assert result["health"] in ["warning", "critical"]

    def test_validate_links_invalid_cell(self):
        """Test validation detects invalid cell references."""
        links = [
            {
                "id": "link_1",
                "source_model_id": "model_a",
                "source_cell_ref": "INVALID",
                "target_model_id": "model_b",
                "target_cell_ref": "B1",
            },
        ]

        result = validate_all_links(links)

        assert result["issue_count"] > 0


class TestListModelLinks:
    """Test listing model links."""

    def test_list_all_links(self):
        """Test listing all links."""
        links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
                "created_at": "2024-01-01",
            },
            {
                "source_model_id": "model_b",
                "target_model_id": "model_c",
                "created_at": "2024-01-02",
            },
        ]

        result = list_model_links(links)

        assert len(result) == 2

    def test_list_filtered_links(self):
        """Test listing filtered links for specific model."""
        links = [
            {
                "source_model_id": "model_a",
                "target_model_id": "model_b",
            },
            {
                "source_model_id": "model_b",
                "target_model_id": "model_c",
            },
        ]

        result = list_model_links(links, filter_model_id="model_b")

        # Should include both links (model_b as source and target)
        assert len(result) == 2


class TestIntegration:
    """Integration tests for model linking."""

    def test_complete_linking_workflow(self):
        """Test complete linking workflow."""
        # Create links
        link1 = create_model_link(
            "revenue_model", "A1", "expense_model", "B1", []
        )
        link2 = create_model_link(
            "expense_model", "A2", "profit_model", "C1", [link1]
        )

        links = [link1, link2]

        # Get impact
        impact = get_link_impact("revenue_model", links)
        assert impact["affected_model_count"] == 2

        # Build graph
        graph = build_model_dependency_graph(links)
        assert "expense_model" in graph["dependents"].get("revenue_model", [])

        # Sync cells
        assumptions = {"A1": 1000, "A2": 500}
        sync_result = sync_linked_cells("revenue_model", assumptions, links)
        assert sync_result["synced_cell_count"] >= 1

        # Validate
        validation = validate_all_links(links)
        assert validation["valid_links"] == 2
        assert validation["issue_count"] == 0
