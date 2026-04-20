"""Model linking service for cross-model cell references and consolidation."""

import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


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


class ModelLinkValidator:
    """Validates model links for circular dependencies and integrity."""

    @staticmethod
    def detect_circular_dependency(
        source_model_id: str,
        target_model_id: str,
        all_links: list[dict[str, Any]],
    ) -> bool:
        """
        Detect if adding a link would create a circular dependency.

        Args:
            source_model_id: Model being linked to
            target_model_id: Model doing the linking
            all_links: List of all existing links

        Returns:
            True if circular dependency detected, False otherwise
        """
        # Build graph of existing links
        graph = defaultdict(list)
        for link in all_links:
            graph[link.get("source_model_id")].append(link.get("target_model_id"))

        # Add the proposed link
        graph[source_model_id].append(target_model_id)

        # BFS to detect cycle from target_model_id
        visited = set()
        queue = deque([target_model_id])

        while queue:
            model_id = queue.popleft()
            if model_id == source_model_id:
                return True  # Cycle detected

            if model_id in visited:
                continue

            visited.add(model_id)
            queue.extend(graph.get(model_id, []))

        return False

    @staticmethod
    def validate_cell_reference(cell_ref: str) -> bool:
        """
        Validate cell reference format (e.g., "A1", "Z99").

        Args:
            cell_ref: Cell reference string

        Returns:
            True if valid, False otherwise
        """
        if not cell_ref or not isinstance(cell_ref, str):
            return False

        # Simple validation: starts with letter(s), followed by numbers
        cell_ref = cell_ref.strip().upper()
        if len(cell_ref) < 2:
            return False

        # Check letters part
        i = 0
        while i < len(cell_ref) and cell_ref[i].isalpha():
            i += 1

        if i == 0 or i == len(cell_ref):
            return False

        # Check numbers part
        return cell_ref[i:].isdigit()


def create_model_link(
    source_model_id: str,
    source_cell_ref: str,
    target_model_id: str,
    target_cell_ref: str,
    all_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Create a link from one model cell to another.

    Args:
        source_model_id: Model being referenced
        source_cell_ref: Cell reference in source (e.g., "A1")
        target_model_id: Model doing the referencing
        target_cell_ref: Cell reference in target (e.g., "B5")
        all_links: List of existing links for validation

    Returns:
        Created link object

    Raises:
        ValueError: If validation fails
    """
    # Validation
    if source_model_id == target_model_id:
        raise ValueError("Cannot link a model to itself")

    if not ModelLinkValidator.validate_cell_reference(source_cell_ref):
        raise ValueError(f"Invalid source cell reference: {source_cell_ref}")

    if not ModelLinkValidator.validate_cell_reference(target_cell_ref):
        raise ValueError(f"Invalid target cell reference: {target_cell_ref}")

    # Check for circular dependency
    if ModelLinkValidator.detect_circular_dependency(source_model_id, target_model_id, all_links):
        raise ValueError(f"Creating link would create circular dependency: {target_model_id} → {source_model_id}")

    link = {
        "id": f"link_{datetime.now(UTC).timestamp()}",
        "source_model_id": source_model_id,
        "source_cell_ref": source_cell_ref.upper(),
        "target_model_id": target_model_id,
        "target_cell_ref": target_cell_ref.upper(),
        "status": "active",
        "created_at": _now_iso(),
        "last_synced_at": None,
    }

    return link


def build_model_dependency_graph(all_links: list[dict[str, Any]]) -> dict[str, list[str]]:
    """
    Build a dependency graph showing which models depend on which.

    Args:
        all_links: List of all model links

    Returns:
        Dictionary mapping model IDs to their dependent models
    """
    graph = defaultdict(list)
    reverse_graph = defaultdict(list)

    for link in all_links:
        if link.get("status") == "active":
            source = link.get("source_model_id")
            target = link.get("target_model_id")
            graph[source].append(target)
            reverse_graph[target].append(source)

    return {
        "dependents": dict(graph),  # Models that depend on this model
        "dependencies": dict(reverse_graph),  # Models this model depends on
    }


def get_link_impact(
    model_id: str,
    all_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Analyze impact of changes to a model on dependent models.

    Args:
        model_id: Model that changed
        all_links: List of all links

    Returns:
        Impact analysis
    """
    graph = build_model_dependency_graph(all_links)
    dependents = graph.get("dependents", {})

    # Find all models that depend on this one (directly or indirectly)
    affected_models = set()
    queue = deque([model_id])
    visited = set()

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        # Find all models that depend on current
        for model in dependents.get(current, []):
            affected_models.add(model)
            queue.append(model)

    # Count affected links
    affected_links = [
        link for link in all_links
        if link.get("source_model_id") == model_id and link.get("status") == "active"
    ]

    return {
        "changed_model": model_id,
        "directly_affected_links": len(affected_links),
        "affected_models": list(affected_models),
        "affected_model_count": len(affected_models),
        "affected_links": [
            {
                "id": link.get("id"),
                "target_model": link.get("target_model_id"),
                "cell_ref": link.get("target_cell_ref"),
            }
            for link in affected_links
        ],
    }


def resolve_cell_reference(
    model_id: str,
    cell_ref: str,
    cell_value: float | str,
    all_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Resolve a cell reference - if it links to another model, get the source value.

    Args:
        model_id: Model containing the cell
        cell_ref: Cell reference
        cell_value: Current cell value (fallback if no link)
        all_links: List of all links

    Returns:
        Resolution result with source info
    """
    cell_ref = cell_ref.upper()

    # Find link where target is this cell
    for link in all_links:
        if (link.get("target_model_id") == model_id and
            link.get("target_cell_ref") == cell_ref and
            link.get("status") == "active"):

            return {
                "cell_ref": cell_ref,
                "model_id": model_id,
                "is_linked": True,
                "source_model_id": link.get("source_model_id"),
                "source_cell_ref": link.get("source_cell_ref"),
                "current_value": cell_value,
                "link_id": link.get("id"),
                "status": "active",
                "resolution_type": "linked",
            }

    return {
        "cell_ref": cell_ref,
        "model_id": model_id,
        "is_linked": False,
        "current_value": cell_value,
        "resolution_type": "local",
    }


def list_model_links(
    all_links: list[dict[str, Any]],
    filter_model_id: str = None,
) -> list[dict[str, Any]]:
    """
    List all model links with optional filtering.

    Args:
        all_links: List of all links
        filter_model_id: Optional model ID to filter by (as source or target)

    Returns:
        Filtered list of links with metadata
    """
    links = all_links

    if filter_model_id:
        links = [
            link for link in links
            if link.get("source_model_id") == filter_model_id or
               link.get("target_model_id") == filter_model_id
        ]

    return sorted(links, key=lambda x: x.get("created_at", ""), reverse=True)


def sync_linked_cells(
    model_id: str,
    model_assumptions: dict[str, Any],
    all_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Sync cells that are linked to other models.

    Args:
        model_id: Model being synced
        model_assumptions: Current model assumptions/cells
        all_links: List of all links

    Returns:
        Sync result with updated values
    """
    synced_cells = {}
    sync_errors = []

    # Find all links where this model is the source
    outbound_links = [
        link for link in all_links
        if link.get("source_model_id") == model_id and link.get("status") == "active"
    ]

    for link in outbound_links:
        source_cell = link.get("source_cell_ref")

        # Get value from source model
        source_value = model_assumptions.get(source_cell)

        if source_value is not None:
            synced_cells[link.get("id")] = {
                "link_id": link.get("id"),
                "source_cell": source_cell,
                "target_model": link.get("target_model_id"),
                "target_cell": link.get("target_cell_ref"),
                "value": source_value,
                "synced_at": _now_iso(),
            }
        else:
            sync_errors.append({
                "link_id": link.get("id"),
                "error": f"Source cell {source_cell} not found in model {model_id}",
            })

    return {
        "model_id": model_id,
        "synced_cell_count": len(synced_cells),
        "error_count": len(sync_errors),
        "synced_cells": synced_cells,
        "errors": sync_errors,
        "synced_at": _now_iso(),
    }


def validate_all_links(all_links: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Validate all links for integrity issues.

    Args:
        all_links: List of all links

    Returns:
        Validation report
    """
    issues = []
    valid_count = 0

    for link in all_links:
        link_id = link.get("id")

        # Check circular dependency
        remaining_links = [lnk for lnk in all_links if lnk.get("id") != link_id]
        if ModelLinkValidator.detect_circular_dependency(
            link.get("source_model_id"),
            link.get("target_model_id"),
            remaining_links,
        ):
            issues.append({
                "link_id": link_id,
                "severity": "high",
                "issue": "Circular dependency detected",
            })
        else:
            valid_count += 1

        # Check cell references
        if not ModelLinkValidator.validate_cell_reference(link.get("source_cell_ref")):
            issues.append({
                "link_id": link_id,
                "severity": "high",
                "issue": f"Invalid source cell reference: {link.get('source_cell_ref')}",
            })

        if not ModelLinkValidator.validate_cell_reference(link.get("target_cell_ref")):
            issues.append({
                "link_id": link_id,
                "severity": "high",
                "issue": f"Invalid target cell reference: {link.get('target_cell_ref')}",
            })

    return {
        "total_links": len(all_links),
        "valid_links": valid_count,
        "issue_count": len(issues),
        "issues": issues,
        "health": "good" if not issues else "warning" if len(issues) < 3 else "critical",
    }
