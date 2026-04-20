"""
Wiki relationship type system with transitive inference.

Implements typed relationships (Phase 2) following Karpathy's Second Brain:
- Relationship types: parent_of, example_of, refines, contradicts, deprecated_by, implements, related_to
- Auto-classification of relationships using semantic context
- Transitive inference (A refines B + B parent_of C => A related_to C)
- Relationship validation and conflict detection
"""

import json
import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)


# Relationship type definitions
RELATIONSHIP_TYPES = {
    "parent_of": {
        "description": "A is a broader category containing B",
        "reverse": "child_of",
        "is_hierarchical": True,
    },
    "example_of": {
        "description": "A exemplifies or demonstrates B",
        "reverse": "has_example",
        "is_hierarchical": False,
    },
    "refines": {
        "description": "A improves or extends B",
        "reverse": "is_refined_by",
        "is_hierarchical": False,
    },
    "contradicts": {
        "description": "A conflicts with B",
        "reverse": "contradicts",
        "is_symmetric": True,
    },
    "deprecated_by": {
        "description": "A is superseded by B",
        "reverse": "deprecates",
        "is_hierarchical": True,
    },
    "implements": {
        "description": "A is a concrete implementation of B",
        "reverse": "is_implemented_by",
        "is_hierarchical": False,
    },
    "related_to": {
        "description": "A is loosely related to B",
        "reverse": "related_to",
        "is_symmetric": True,
    },
    "mentions": {
        "description": "A mentions B (inferred from content)",
        "reverse": "mentioned_by",
        "is_hierarchical": False,
    },
    "references": {
        "description": "A explicitly references B",
        "reverse": "referenced_by",
        "is_hierarchical": False,
    },
}


class RelationshipClassifier:
    """Auto-classify relationships using semantic context."""

    def __init__(self):
        """Initialize classifier with relationship keywords."""
        self.keywords = {
            "parent_of": [
                "category", "type", "class", "form", "kind", "subset", "part of", "component",
            ],
            "example_of": [
                "example", "instance", "case", "illustration", "demonstration", "e.g.", "such as",
            ],
            "refines": [
                "improve", "extend", "enhance", "build on", "develop", "advance", "evolved from",
                "more sophisticated", "iterates on", "next version",
            ],
            "contradicts": [
                "conflict", "contradict", "disagree", "opposite", "however", "but", "contrast",
                "unlike", "different from", "contradictory",
            ],
            "deprecated_by": [
                "replaced by", "superseded", "deprecated", "obsolete", "old", "outdated",
                "legacy", "no longer used",
            ],
            "implements": [
                "implements", "implementation", "concrete", "realizes", "fulfills", "applies",
                "execution", "instantiation",
            ],
        }

    def classify(self, source_page: str, target_page: str, context: str) -> tuple[str, float]:
        """
        Classify relationship type based on context.

        Args:
            source_page: Source page ID
            target_page: Target page ID
            context: Text context around the link

        Returns:
            (relationship_type, confidence_score)
        """
        context_lower = context.lower()
        scores = defaultdict(float)

        # Score based on keywords
        for rel_type, keywords in self.keywords.items():
            for keyword in keywords:
                if keyword in context_lower:
                    scores[rel_type] += 1.0

        # Default to related_to if no matches
        if not scores:
            return "related_to", 0.3

        # Find best match
        best_type = max(scores, key=scores.get)
        max_score = scores[best_type]
        sum(len(k) for k in self.keywords.values())

        # Normalize confidence (0.5-1.0)
        confidence = 0.5 + (min(max_score, 3.0) / 3.0) * 0.5

        return best_type, round(confidence, 2)


class RelationshipGraph:
    """Manage typed relationships and transitive inference."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """Initialize relationship graph."""
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.classifier = RelationshipClassifier()
        self.relationships: list[dict[str, Any]] = []
        self.reverse_index: dict[str, list[str]] = defaultdict(list)
        self._load_relationships()

    def _get_wiki_dir(self) -> Path:
        """Get wiki directory."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def _load_relationships(self) -> None:
        """Load relationships from storage."""
        try:
            relationships_file = self.wiki_dir / ".meta" / "relationships.json"
            if not relationships_file.exists():
                relationships_file = self.wiki_dir / "relationships.json"

            if relationships_file.exists():
                data = json.loads(relationships_file.read_text())
                self.relationships = data.get("relationships", [])

                # Build reverse index
                for rel in self.relationships:
                    target = rel.get("target_id", "")
                    source = rel.get("source_id", "")
                    if target and source:
                        self.reverse_index[target].append(source)
        except Exception as e:
            _LOG.warning(f"Error loading relationships: {e}")

    def classify_relationships(self) -> int:
        """
        Auto-classify all relationships with types.

        Returns count of classified relationships.
        """
        classified = 0

        try:
            for rel in self.relationships:
                if "relation_type" in rel and rel["relation_type"] not in ["references", "mentions"]:
                    continue  # Already typed

                # Get context around the link
                source_id = rel.get("source_id", "")
                target_id = rel.get("target_id", "")

                page_file = self.wiki_dir / f"{source_id}.md"
                if page_file.exists():
                    content = page_file.read_text(encoding="utf-8")
                    # Find context around target mention
                    pattern = r"\[\[" + re.escape(target_id) + r"\]\]"
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        start = max(0, match.start() - 100)
                        end = min(len(content), match.end() + 100)
                        context = content[start:end]

                        rel_type, confidence = self.classifier.classify(
                            source_id, target_id, context
                        )
                        rel["relation_type"] = rel_type
                        rel["confidence_score"] = confidence
                        classified += 1

            self._persist_relationships()
            _LOG.info(f"Classified {classified} relationships")
            return classified

        except Exception as e:
            _LOG.error(f"Error classifying relationships: {e}")
            return 0

    def get_transitive_relationships(self, page_id: str, max_depth: int = 2) -> set[str]:
        """
        Get all pages transitively related to a page.

        Follows relationship chains:
        - A parent_of B + B parent_of C => A parent_of C (transitive)
        - A refines B + B parent_of C => A related_to C (inferred)

        Args:
            page_id: Starting page ID
            max_depth: Maximum chain depth

        Returns:
            Set of related page IDs
        """
        related = set()
        visited = set()
        queue = [(page_id, 0, None)]  # (page_id, depth, incoming_rel_type)

        while queue:
            current, depth, incoming_rel_type = queue.pop(0)

            if current in visited or depth > max_depth:
                continue

            visited.add(current)

            # Find all relationships from this page
            for rel in self.relationships:
                if rel.get("source_id") != current:
                    continue

                target = rel.get("target_id", "")
                rel_type = rel.get("relation_type", "related_to")

                if target and target != page_id:
                    # Determine transitive type
                    transitive_type = self._compute_transitive_type(
                        incoming_rel_type, rel_type
                    )

                    related.add(target)
                    queue.append((target, depth + 1, transitive_type))

        return related

    def _compute_transitive_type(self, incoming: str | None, outgoing: str) -> str:
        """
        Compute transitive relationship type.

        Rules:
        - parent_of + parent_of => parent_of
        - parent_of + refines => parent_of (or refines)
        - refines + parent_of => related_to
        - Any + contradicts => contradicts
        """
        if not incoming:
            return outgoing

        # Contradictions propagate
        if incoming == "contradicts" or outgoing == "contradicts":
            return "contradicts"

        # Hierarchical relationships compose
        if incoming == "parent_of" and outgoing == "parent_of":
            return "parent_of"

        # Default to related_to
        return "related_to"

    def validate_relationships(self) -> list[dict[str, Any]]:
        """
        Validate relationships for conflicts and inconsistencies.

        Returns:
            List of validation issues
        """
        issues = []

        try:
            # Check for circular contradictions
            for rel in self.relationships:
                if rel.get("relation_type") == "contradicts":
                    source = rel.get("source_id", "")
                    target = rel.get("target_id", "")

                    # Find if target also contradicts source (should be OK)
                    any(
                        r.get("source_id") == target and r.get("target_id") == source
                        and r.get("relation_type") == "contradicts"
                        for r in self.relationships
                    )

            # Check for hierarchical cycles (A parent_of B parent_of A)
            parent_rels = [r for r in self.relationships if r.get("relation_type") == "parent_of"]
            for rel in parent_rels:
                source = rel.get("source_id", "")
                target = rel.get("target_id", "")

                # Follow chain
                visited = {target}
                queue = [target]

                while queue:
                    current = queue.pop(0)
                    for p_rel in parent_rels:
                        if p_rel.get("source_id") == current:
                            next_target = p_rel.get("target_id", "")
                            if next_target == source:
                                issues.append({
                                    "type": "hierarchical_cycle",
                                    "severity": "high",
                                    "cycle": f"{source} -> {target} -> ... -> {source}",
                                    "message": "Circular parent_of relationship detected",
                                })
                            elif next_target not in visited:
                                visited.add(next_target)
                                queue.append(next_target)

            _LOG.info(f"Found {len(issues)} relationship validation issues")
            return issues

        except Exception as e:
            _LOG.error(f"Error validating relationships: {e}")
            return []

    def _persist_relationships(self) -> None:
        """Save relationships to storage."""
        try:
            meta_dir = self.wiki_dir / ".meta"
            meta_dir.mkdir(exist_ok=True)

            relationships_file = meta_dir / "relationships.json"
            relationships_file.write_text(
                json.dumps({
                    "total": len(self.relationships),
                    "relationships": self.relationships,
                    "relationship_types": list(RELATIONSHIP_TYPES.keys()),
                    "last_updated": datetime.now(UTC).isoformat(),
                }, indent=2),
                encoding="utf-8"
            )

            _LOG.info(f"Persisted {len(self.relationships)} relationships")

        except Exception as e:
            _LOG.error(f"Error persisting relationships: {e}")

    def get_relationship_stats(self) -> dict[str, Any]:
        """Get statistics about relationships."""
        type_counts = defaultdict(int)
        for rel in self.relationships:
            rel_type = rel.get("relation_type", "unknown")
            type_counts[rel_type] += 1

        return {
            "total_relationships": len(self.relationships),
            "by_type": dict(type_counts),
            "pages_with_relationships": len(set(r.get("source_id") for r in self.relationships)),
            "average_relationships_per_page": round(
                len(self.relationships) / max(len(set(r.get("source_id") for r in self.relationships)), 1),
                2
            ),
        }


def classify_all_relationships(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Auto-classify all relationships in a wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        Classification results
    """
    graph = RelationshipGraph(wiki_type, project_id)
    classified = graph.classify_relationships()
    stats = graph.get_relationship_stats()

    return {
        "status": "success",
        "classified": classified,
        **stats,
    }


def get_transitive_related_pages(
    page_id: str,
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
    max_depth: int = 2,
) -> list[str]:
    """Get transitively related pages for a given page."""
    graph = RelationshipGraph(wiki_type, project_id)
    related = graph.get_transitive_relationships(page_id, max_depth)
    return sorted(list(related))


def validate_relationships(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Validate relationships in a wiki."""
    graph = RelationshipGraph(wiki_type, project_id)
    issues = graph.validate_relationships()
    stats = graph.get_relationship_stats()

    return {
        "status": "success",
        "issues": issues,
        "issue_count": len(issues),
        **stats,
    }
