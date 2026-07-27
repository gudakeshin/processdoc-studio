"""Financial data source integration for external data imports and lineage tracking."""

import csv
import json
from collections import defaultdict
from datetime import datetime
from app.core.tz import IST
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(IST).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    """Read JSON file with fallback."""
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class DataSourceValidator:
    """Validates external data source mappings and integrity."""

    @staticmethod
    def validate_column_mapping(
        source_columns: list[str],
        mapping: dict[str, str],
    ) -> dict[str, Any]:
        """
        Validate that all mapped columns exist in source.

        Args:
            source_columns: List of column names in source data
            mapping: Dict of assumption_name -> source_column_name

        Returns:
            Validation result with issues list
        """
        issues = []

        for assumption_name, source_column in mapping.items():
            if source_column not in source_columns:
                issues.append({
                    "assumption": assumption_name,
                    "severity": "error",
                    "issue": f"Source column '{source_column}' not found in data",
                })

        return {
            "valid": len(issues) == 0,
            "issue_count": len(issues),
            "issues": issues,
        }

    @staticmethod
    def validate_data_types(
        data_rows: list[dict[str, Any]],
        mapping: dict[str, str],
        expected_types: dict[str, str] = None,
    ) -> dict[str, Any]:
        """
        Validate that mapped columns have expected data types.

        Args:
            data_rows: List of data rows
            mapping: Dict of assumption_name -> source_column_name
            expected_types: Optional dict of assumption_name -> expected_type

        Returns:
            Validation result with type issues
        """
        issues = []
        sample_values = {}

        if not data_rows:
            return {
                "valid": True,
                "issue_count": 0,
                "issues": [],
                "sample_values": sample_values,
            }

        for assumption_name, source_column in mapping.items():
            values = []
            for row in data_rows:
                value = row.get(source_column)
                if value is not None:
                    values.append(value)
                    if len(values) >= 3:
                        break

            sample_values[assumption_name] = values

            # Check if values can be coerced to numeric
            if expected_types and expected_types.get(assumption_name) == "numeric":
                for value in values:
                    try:
                        float(value)
                    except (ValueError, TypeError):
                        issues.append({
                            "assumption": assumption_name,
                            "severity": "warning",
                            "issue": f"Non-numeric value detected: {value}",
                        })
                        break

        return {
            "valid": len(issues) == 0,
            "issue_count": len(issues),
            "issues": issues,
            "sample_values": sample_values,
        }


def parse_data_source(
    file_path: str,
    file_type: str = "csv",
) -> dict[str, Any]:
    """
    Parse CSV or Excel data source.

    Args:
        file_path: Path to data file
        file_type: "csv", "xlsx", or "json"

    Returns:
        Parsed data with column info and sample rows
    """
    path = Path(file_path)

    if not path.exists():
        raise ValueError(f"Data source file not found: {file_path}")

    if file_type == "csv":
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        columns = list(rows[0].keys()) if rows else []

        return {
            "file_path": file_path,
            "file_type": "csv",
            "columns": columns,
            "row_count": len(rows),
            "sample_rows": rows[:5],
            "parsed_at": _now_iso(),
        }

    elif file_type == "json":
        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, list):
            rows = data
            columns = list(rows[0].keys()) if rows else []
        elif isinstance(data, dict):
            rows = [data]
            columns = list(data.keys())
        else:
            raise ValueError("JSON must be list of objects or single object")

        return {
            "file_path": file_path,
            "file_type": "json",
            "columns": columns,
            "row_count": len(rows),
            "sample_rows": rows[:5],
            "parsed_at": _now_iso(),
        }

    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def create_data_source_connector(
    model_id: str,
    source_name: str,
    file_path: str,
    file_type: str,
    column_mapping: dict[str, str],
    refresh_schedule: str = "manual",
) -> dict[str, Any]:
    """
    Create a data source connector for a model.

    Args:
        model_id: Model ID
        source_name: Name of data source
        file_path: Path to data source file
        file_type: "csv" or "json"
        column_mapping: Dict of assumption_name -> source_column_name
        refresh_schedule: "manual", "daily", "weekly", "monthly"

    Returns:
        Created connector object
    """
    # Parse source
    source_info = parse_data_source(file_path, file_type)

    # Validate mapping
    validation = DataSourceValidator.validate_column_mapping(
        source_info["columns"],
        column_mapping,
    )

    if not validation["valid"]:
        raise ValueError(f"Column mapping validation failed: {validation['issues']}")

    connector = {
        "id": f"connector_{datetime.now(IST).timestamp()}",
        "model_id": model_id,
        "source_name": source_name,
        "file_path": file_path,
        "file_type": file_type,
        "column_mapping": column_mapping,
        "columns_available": source_info["columns"],
        "refresh_schedule": refresh_schedule,
        "status": "active",
        "created_at": _now_iso(),
        "last_synced_at": None,
        "sync_count": 0,
        "row_count": source_info["row_count"],
    }

    return connector


def sync_data_source(
    connector: dict[str, Any],
    model_assumptions: dict[str, Any],
) -> dict[str, Any]:
    """
    Sync data from external source into model assumptions.

    Args:
        connector: Connector object from create_data_source_connector
        model_assumptions: Current model assumptions dict

    Returns:
        Sync result with updated assumptions and lineage
    """
    file_path = connector["file_path"]
    file_type = connector["file_type"]
    column_mapping = connector["column_mapping"]

    # Parse source
    source_info = parse_data_source(file_path, file_type)
    rows = source_info["sample_rows"]

    if not rows:
        return {
            "connector_id": connector["id"],
            "synced_at": _now_iso(),
            "updated_assumptions": {},
            "error_count": 1,
            "errors": [{"error": "No data rows in source"}],
            "lineage": {},
        }

    # Use first row as values
    source_row = rows[0]

    updated_assumptions = {}
    lineage = {}
    errors = []

    for assumption_name, source_column in column_mapping.items():
        try:
            value = source_row.get(source_column)

            if value is None:
                errors.append({
                    "assumption": assumption_name,
                    "error": f"Column {source_column} not found in row",
                })
                continue

            # Try to coerce to numeric
            try:
                numeric_value = float(value)
            except (ValueError, TypeError):
                numeric_value = value

            old_value = model_assumptions.get(assumption_name)
            updated_assumptions[assumption_name] = numeric_value

            lineage[assumption_name] = {
                "source_name": connector["source_name"],
                "source_column": source_column,
                "old_value": old_value,
                "new_value": numeric_value,
                "synced_at": _now_iso(),
            }

        except Exception as e:
            errors.append({
                "assumption": assumption_name,
                "error": str(e),
            })

    return {
        "connector_id": connector["id"],
        "synced_at": _now_iso(),
        "updated_assumptions": updated_assumptions,
        "error_count": len(errors),
        "errors": errors,
        "lineage": lineage,
    }


def list_data_sources(
    all_connectors: list[dict[str, Any]],
    filter_model_id: str = None,
) -> list[dict[str, Any]]:
    """
    List all data source connectors.

    Args:
        all_connectors: List of all connectors
        filter_model_id: Optional filter by model ID

    Returns:
        Filtered list of connectors
    """
    connectors = all_connectors

    if filter_model_id:
        connectors = [c for c in connectors if c.get("model_id") == filter_model_id]

    return sorted(connectors, key=lambda x: x.get("created_at", ""), reverse=True)


def get_data_lineage(
    model_id: str,
    sync_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Get data lineage for a model - trace assumptions back to sources.

    Args:
        model_id: Model ID
        sync_history: List of sync results from sync_data_source

    Returns:
        Lineage report showing assumption origins
    """
    lineage_map = {}

    for sync_result in sync_history:
        for assumption_name, lineage_entry in sync_result.get("lineage", {}).items():
            if assumption_name not in lineage_map:
                lineage_map[assumption_name] = []

            lineage_map[assumption_name].append(lineage_entry)

    # Get latest source for each assumption
    latest_sources = {}
    for assumption_name, entries in lineage_map.items():
        if entries:
            latest_sources[assumption_name] = entries[-1]

    return {
        "model_id": model_id,
        "assumption_count": len(latest_sources),
        "assumptions_with_sources": latest_sources,
        "total_syncs": len(sync_history),
        "lineage_map": lineage_map,
    }


def detect_data_drift(
    current_assumptions: dict[str, Any],
    previous_assumptions: dict[str, Any],
    threshold_pct: float = 5.0,
) -> dict[str, Any]:
    """
    Detect drift in assumption values between syncs.

    Args:
        current_assumptions: Latest assumption values
        previous_assumptions: Previous assumption values
        threshold_pct: Threshold % to flag as significant drift

    Returns:
        Drift analysis report
    """
    drifts = []

    all_assumptions = set(list(current_assumptions.keys()) + list(previous_assumptions.keys()))

    for assumption in all_assumptions:
        current_val = current_assumptions.get(assumption)
        prev_val = previous_assumptions.get(assumption)

        if current_val is None or prev_val is None:
            continue

        try:
            current_num = float(current_val)
            prev_num = float(prev_val)

            if prev_num == 0:
                pct_change = 100.0 if current_num != 0 else 0.0
            else:
                pct_change = abs((current_num - prev_num) / prev_num * 100)

            if pct_change > threshold_pct:
                drifts.append({
                    "assumption": assumption,
                    "previous_value": prev_num,
                    "current_value": current_num,
                    "pct_change": float(round(pct_change, 1)),
                    "severity": "high" if pct_change > 20 else "medium",
                })

        except (ValueError, TypeError):
            pass

    return {
        "drift_count": len(drifts),
        "drifts": sorted(drifts, key=lambda x: x["pct_change"], reverse=True),
        "analysis_performed_at": _now_iso(),
    }


def build_data_lineage_graph(
    connectors: list[dict[str, Any]],
    sync_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build a graph showing data lineage relationships.

    Args:
        connectors: List of data source connectors
        sync_history: List of sync results

    Returns:
        Lineage graph with nodes and edges
    """
    # Build connector lookup
    connector_map = {c["id"]: c for c in connectors}

    # Track assumptions to sources
    assumption_to_sources = defaultdict(list)

    for sync_result in sync_history:
        connector_id = sync_result.get("connector_id")
        connector = connector_map.get(connector_id)

        if not connector:
            continue

        for assumption, lineage_entry in sync_result.get("lineage", {}).items():
            assumption_to_sources[assumption].append({
                "source_name": connector["source_name"],
                "source_id": connector_id,
                "column": lineage_entry.get("source_column"),
                "synced_at": lineage_entry.get("synced_at"),
            })

    # Build graph nodes and edges
    nodes = []
    edges = []

    # Add source nodes
    for connector in connectors:
        nodes.append({
            "id": connector["id"],
            "type": "data_source",
            "label": connector["source_name"],
            "file_path": connector["file_path"],
        })

    # Add assumption nodes and edges
    for assumption, sources in assumption_to_sources.items():
        nodes.append({
            "id": f"assumption_{assumption}",
            "type": "assumption",
            "label": assumption,
        })

        for source in sources:
            edges.append({
                "from": source["source_id"],
                "to": f"assumption_{assumption}",
                "label": source["column"],
                "last_synced": source["synced_at"],
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "assumption_count": len(assumption_to_sources),
    }
