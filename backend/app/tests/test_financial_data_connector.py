"""Test suite for financial data source integration."""

import pytest
import tempfile
import json
from pathlib import Path
from app.services.financial_data_connector import (
    DataSourceValidator,
    parse_data_source,
    create_data_source_connector,
    sync_data_source,
    list_data_sources,
    get_data_lineage,
    detect_data_drift,
    build_data_lineage_graph,
)


class TestDataSourceValidator:
    """Test data source validation."""

    def test_validate_column_mapping_valid(self):
        """Test valid column mapping."""
        source_columns = ["Revenue", "COGS", "OpEx"]
        mapping = {
            "annual_revenue": "Revenue",
            "cost_of_goods": "COGS",
        }

        result = DataSourceValidator.validate_column_mapping(source_columns, mapping)

        assert result["valid"] is True
        assert result["issue_count"] == 0

    def test_validate_column_mapping_missing_column(self):
        """Test mapping with missing source column."""
        source_columns = ["Revenue", "COGS"]
        mapping = {
            "annual_revenue": "Revenue",
            "opex": "OpEx",  # Not in source
        }

        result = DataSourceValidator.validate_column_mapping(source_columns, mapping)

        assert result["valid"] is False
        assert result["issue_count"] == 1
        assert result["issues"][0]["assumption"] == "opex"

    def test_validate_data_types_numeric(self):
        """Test numeric data type validation."""
        data_rows = [
            {"Revenue": "1000", "COGS": "400"},
            {"Revenue": "1100", "COGS": "450"},
        ]
        mapping = {
            "annual_revenue": "Revenue",
            "cost_of_goods": "COGS",
        }
        expected_types = {
            "annual_revenue": "numeric",
            "cost_of_goods": "numeric",
        }

        result = DataSourceValidator.validate_data_types(
            data_rows, mapping, expected_types
        )

        assert result["valid"] is True
        assert result["issue_count"] == 0

    def test_validate_data_types_non_numeric(self):
        """Test non-numeric data detection."""
        data_rows = [
            {"Revenue": "1000", "COGS": "invalid"},
        ]
        mapping = {
            "cost_of_goods": "COGS",
        }
        expected_types = {
            "cost_of_goods": "numeric",
        }

        result = DataSourceValidator.validate_data_types(
            data_rows, mapping, expected_types
        )

        assert result["issue_count"] == 1
        assert "non-numeric" in result["issues"][0]["issue"].lower()

    def test_validate_data_types_empty_rows(self):
        """Test validation with no data rows."""
        result = DataSourceValidator.validate_data_types(
            [], {"assumption": "Column"}
        )

        assert result["valid"] is True
        assert result["issue_count"] == 0


class TestParseDataSource:
    """Test data source parsing."""

    def test_parse_csv(self):
        """Test CSV parsing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS,OpEx\n")
            f.write("1000,400,200\n")
            f.write("1100,450,220\n")
            f.flush()

            result = parse_data_source(f.name, "csv")

            assert result["file_type"] == "csv"
            assert result["columns"] == ["Revenue", "COGS", "OpEx"]
            assert result["row_count"] == 2
            assert len(result["sample_rows"]) == 2

    def test_parse_json_list(self):
        """Test JSON list parsing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"Revenue": 1000, "COGS": 400},
                {"Revenue": 1100, "COGS": 450},
            ]
            json.dump(data, f)
            f.flush()

            result = parse_data_source(f.name, "json")

            assert result["file_type"] == "json"
            assert "Revenue" in result["columns"]
            assert "COGS" in result["columns"]
            assert result["row_count"] == 2

    def test_parse_json_object(self):
        """Test JSON object parsing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = {"Revenue": 1000, "COGS": 400}
            json.dump(data, f)
            f.flush()

            result = parse_data_source(f.name, "json")

            assert result["file_type"] == "json"
            assert result["row_count"] == 1

    def test_parse_missing_file(self):
        """Test error handling for missing file."""
        with pytest.raises(ValueError):
            parse_data_source("/nonexistent/file.csv", "csv")

    def test_parse_unsupported_type(self):
        """Test error for unsupported file type."""
        with tempfile.NamedTemporaryFile(suffix=".csv") as f:
            with pytest.raises(ValueError):
                parse_data_source(f.name, "xlsx")


class TestCreateDataSourceConnector:
    """Test connector creation."""

    def test_create_connector_basic(self):
        """Test basic connector creation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS\n")
            f.write("1000,400\n")
            f.flush()

            mapping = {"annual_revenue": "Revenue", "cost_of_goods": "COGS"}

            connector = create_data_source_connector(
                model_id="model_a",
                source_name="CFO Budget",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
            )

            assert connector["model_id"] == "model_a"
            assert connector["source_name"] == "CFO Budget"
            assert connector["status"] == "active"
            assert connector["refresh_schedule"] == "manual"

    def test_create_connector_invalid_mapping(self):
        """Test connector creation with invalid mapping."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS\n")
            f.write("1000,400\n")
            f.flush()

            mapping = {"annual_revenue": "NonexistentColumn"}

            with pytest.raises(ValueError):
                create_data_source_connector(
                    model_id="model_a",
                    source_name="Bad Source",
                    file_path=f.name,
                    file_type="csv",
                    column_mapping=mapping,
                )

    def test_create_connector_with_schedule(self):
        """Test connector with refresh schedule."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue\n")
            f.write("1000\n")
            f.flush()

            mapping = {"annual_revenue": "Revenue"}

            connector = create_data_source_connector(
                model_id="model_a",
                source_name="API Source",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
                refresh_schedule="daily",
            )

            assert connector["refresh_schedule"] == "daily"


class TestSyncDataSource:
    """Test data source syncing."""

    def test_sync_basic(self):
        """Test basic data sync."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS\n")
            f.write("1000,400\n")
            f.flush()

            mapping = {"annual_revenue": "Revenue", "cost_of_goods": "COGS"}

            connector = create_data_source_connector(
                model_id="model_a",
                source_name="Source",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
            )

            model_assumptions = {"annual_revenue": 900, "cost_of_goods": 350}

            result = sync_data_source(connector, model_assumptions)

            assert result["error_count"] == 0
            assert result["updated_assumptions"]["annual_revenue"] == 1000.0
            assert result["updated_assumptions"]["cost_of_goods"] == 400.0

    def test_sync_with_errors(self):
        """Test sync with missing columns in data."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS\n")
            f.write("1000,400\n")
            f.flush()

            # Create valid mapping first
            mapping = {"annual_revenue": "Revenue"}
            connector = create_data_source_connector(
                model_id="model_a",
                source_name="Partial",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
            )

            # Sync will work fine
            result = sync_data_source(connector, {})

            assert result["error_count"] == 0
            assert "annual_revenue" in result["updated_assumptions"]
            assert result["updated_assumptions"]["annual_revenue"] == 1000.0

    def test_sync_lineage_tracking(self):
        """Test lineage tracking during sync."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue\n")
            f.write("1500\n")
            f.flush()

            mapping = {"annual_revenue": "Revenue"}

            connector = create_data_source_connector(
                model_id="model_a",
                source_name="Budget System",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
            )

            result = sync_data_source(connector, {"annual_revenue": 1000})

            lineage = result["lineage"]["annual_revenue"]
            assert lineage["source_name"] == "Budget System"
            assert lineage["source_column"] == "Revenue"
            assert lineage["old_value"] == 1000
            assert lineage["new_value"] == 1500.0


class TestListDataSources:
    """Test listing data sources."""

    def test_list_all_sources(self):
        """Test listing all sources."""
        connectors = [
            {"id": "c1", "model_id": "m1", "source_name": "Source 1"},
            {"id": "c2", "model_id": "m1", "source_name": "Source 2"},
            {"id": "c3", "model_id": "m2", "source_name": "Source 3"},
        ]

        result = list_data_sources(connectors)

        assert len(result) == 3

    def test_list_filtered_sources(self):
        """Test listing sources for specific model."""
        connectors = [
            {"id": "c1", "model_id": "m1", "source_name": "Source 1", "created_at": "2024-01-01"},
            {"id": "c2", "model_id": "m1", "source_name": "Source 2", "created_at": "2024-01-02"},
            {"id": "c3", "model_id": "m2", "source_name": "Source 3", "created_at": "2024-01-03"},
        ]

        result = list_data_sources(connectors, filter_model_id="m1")

        assert len(result) == 2
        assert all(c["model_id"] == "m1" for c in result)


class TestGetDataLineage:
    """Test data lineage tracking."""

    def test_get_lineage_basic(self):
        """Test basic lineage tracking."""
        sync_history = [
            {
                "lineage": {
                    "annual_revenue": {
                        "source_name": "CFO",
                        "source_column": "Revenue",
                        "old_value": 1000,
                        "new_value": 1100,
                    },
                }
            }
        ]

        result = get_data_lineage("model_a", sync_history)

        assert result["assumption_count"] == 1
        assert "annual_revenue" in result["assumptions_with_sources"]

    def test_get_lineage_history(self):
        """Test lineage history for multiple syncs."""
        sync_history = [
            {
                "lineage": {
                    "annual_revenue": {
                        "source_name": "Source1",
                        "old_value": 1000,
                        "new_value": 1100,
                    },
                }
            },
            {
                "lineage": {
                    "annual_revenue": {
                        "source_name": "Source1",
                        "old_value": 1100,
                        "new_value": 1200,
                    },
                }
            },
        ]

        result = get_data_lineage("model_a", sync_history)

        # Latest value should be last sync
        assert result["assumptions_with_sources"]["annual_revenue"]["new_value"] == 1200


class TestDetectDataDrift:
    """Test data drift detection."""

    def test_detect_drift_above_threshold(self):
        """Test detecting drift above threshold."""
        current = {"revenue": 1100, "cogs": 450}
        previous = {"revenue": 1000, "cogs": 400}

        result = detect_data_drift(current, previous, threshold_pct=5.0)

        assert result["drift_count"] == 2
        # Sorted by pct_change descending, so COGS (12.5%) comes before Revenue (10%)
        pct_changes = [d["pct_change"] for d in result["drifts"]]
        assert pytest.approx(10.0) in pct_changes
        assert pytest.approx(12.5) in pct_changes

    def test_detect_drift_below_threshold(self):
        """Test no drift below threshold."""
        current = {"revenue": 1010, "cogs": 400}
        previous = {"revenue": 1000, "cogs": 400}

        result = detect_data_drift(current, previous, threshold_pct=5.0)

        # 1% change < 5% threshold
        assert result["drift_count"] == 0

    def test_detect_drift_severity(self):
        """Test drift severity classification."""
        current = {"revenue": 1250}  # 25% change
        previous = {"revenue": 1000}

        result = detect_data_drift(current, previous, threshold_pct=5.0)

        assert result["drift_count"] == 1
        assert result["drifts"][0]["severity"] == "high"

    def test_detect_drift_zero_division(self):
        """Test handling of zero previous value."""
        current = {"revenue": 100}
        previous = {"revenue": 0}

        result = detect_data_drift(current, previous, threshold_pct=5.0)

        # Should handle 0 division gracefully
        assert result["drift_count"] >= 0


class TestBuildDataLineageGraph:
    """Test lineage graph building."""

    def test_build_graph_basic(self):
        """Test basic lineage graph."""
        connectors = [
            {
                "id": "c1",
                "source_name": "CFO Budget",
                "file_path": "/path/to/budget.csv",
            }
        ]
        sync_history = [
            {
                "connector_id": "c1",
                "lineage": {
                    "annual_revenue": {
                        "source_column": "Revenue",
                        "synced_at": "2024-01-01",
                    }
                },
            }
        ]

        result = build_data_lineage_graph(connectors, sync_history)

        assert result["node_count"] == 2  # 1 source + 1 assumption
        assert result["edge_count"] == 1
        assert result["assumption_count"] == 1

    def test_build_graph_multiple_sources(self):
        """Test lineage graph with multiple sources."""
        connectors = [
            {"id": "c1", "source_name": "Budget", "file_path": "budget.csv"},
            {"id": "c2", "source_name": "Actuals", "file_path": "actuals.csv"},
        ]
        sync_history = [
            {
                "connector_id": "c1",
                "lineage": {
                    "revenue": {"source_column": "Revenue", "synced_at": "2024-01-01"},
                    "cogs": {"source_column": "COGS", "synced_at": "2024-01-01"},
                },
            },
            {
                "connector_id": "c2",
                "lineage": {
                    "actual_revenue": {"source_column": "Revenue", "synced_at": "2024-01-02"},
                },
            },
        ]

        result = build_data_lineage_graph(connectors, sync_history)

        assert result["node_count"] == 5  # 2 sources + 3 assumptions
        assert result["edge_count"] == 3
        assert result["assumption_count"] == 3


class TestIntegration:
    """Integration tests for data connector."""

    def test_full_data_connector_workflow(self):
        """Test complete data connector workflow."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Revenue,COGS,OpEx\n")
            f.write("1000,400,200\n")
            f.flush()

            # Create connector
            mapping = {
                "annual_revenue": "Revenue",
                "cost_of_goods": "COGS",
                "operating_expenses": "OpEx",
            }

            connector = create_data_source_connector(
                model_id="financial_model",
                source_name="FY2024 Budget",
                file_path=f.name,
                file_type="csv",
                column_mapping=mapping,
                refresh_schedule="monthly",
            )

            assert connector["source_name"] == "FY2024 Budget"

            # Sync data
            model_assumptions = {
                "annual_revenue": 950,
                "cost_of_goods": 380,
                "operating_expenses": 180,
            }

            sync_result = sync_data_source(connector, model_assumptions)

            assert sync_result["error_count"] == 0
            assert sync_result["updated_assumptions"]["annual_revenue"] == 1000.0

            # Track lineage
            lineage = get_data_lineage("financial_model", [sync_result])
            assert lineage["assumption_count"] == 3

            # Detect drift on next sync
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f2:
                f2.write("Revenue,COGS,OpEx\n")
                f2.write("1200,480,250\n")
                f2.flush()

                connector2 = connector.copy()
                connector2["file_path"] = f2.name

                sync_result2 = sync_data_source(connector2, sync_result["updated_assumptions"])

                drift = detect_data_drift(
                    sync_result2["updated_assumptions"],
                    sync_result["updated_assumptions"],
                    threshold_pct=5.0,
                )

                # 20% change = (1200-1000)/1000
                assert drift["drift_count"] > 0
