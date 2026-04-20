"""
Wiki schema analyzer for adaptive schema evolution (Phase 3).

Analyzes wiki content to detect emerging patterns and evolve schema accordingly.
Discovers new categories, relationship types, and synthesis rules from wiki content.
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)


class SchemaAnalyzer:
    """Analyze wiki patterns and recommend schema updates."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """Initialize schema analyzer."""
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.schema_file = self.wiki_dir / "SCHEMA.md"

    def _get_wiki_dir(self) -> Path:
        """Get wiki directory."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def _load_schema(self) -> dict[str, Any]:
        """Load current schema."""
        try:
            if not self.schema_file.exists():
                return {"categories": [], "relationship_types": [], "synthesis_triggers": []}

            content = self.schema_file.read_text(encoding="utf-8")
            # Extract structured sections (simplified)
            return {
                "raw_content": content,
                "categories": self._extract_list_from_section(content, "Page Categories"),
                "relationship_types": self._extract_list_from_section(content, "Relationship Types"),
                "synthesis_triggers": self._extract_list_from_section(content, "Synthesis Triggers"),
            }
        except Exception as e:
            _LOG.warning(f"Error loading schema: {e}")
            return {}

    def _extract_list_from_section(self, content: str, section: str) -> list[str]:
        """Extract bullet list from markdown section."""
        pattern = rf"## {section}.*?(?=## |$)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            section_content = match.group(0)
            items = re.findall(r"^-\s+([^:\n]+)", section_content, re.MULTILINE)
            return items

        return []

    def detect_emerging_categories(self) -> list[dict[str, Any]]:
        """
        Detect categories used in pages that aren't formalized in schema.

        Analyzes frontmatter "category" fields to find patterns.

        Returns:
            List of emerging categories with frequency
        """
        try:
            categories_found = Counter()
            schema = self._load_schema()
            known_categories = set(schema.get("categories", []))

            for md_file in self.wiki_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md", "SCHEMA.md", "maintenance.log"):
                    continue

                content = md_file.read_text(encoding="utf-8")
                category_match = re.search(r"^category:\s*([^\n]+)", content, re.MULTILINE)

                if category_match:
                    category = category_match.group(1).strip().strip('"\'')
                    if category and category not in known_categories:
                        categories_found[category] += 1

            # Return categories found in 2+ pages
            emerging = [
                {
                    "category": cat,
                    "frequency": count,
                    "recommendation": f"Formalize '{cat}' in schema (found in {count} pages)",
                }
                for cat, count in categories_found.most_common() if count >= 2
            ]

            return emerging

        except Exception as e:
            _LOG.error(f"Error detecting emerging categories: {e}")
            return []

    def detect_emerging_relationships(self) -> list[dict[str, Any]]:
        """
        Detect relationship patterns not yet in schema.

        Analyzes frequently used contextual phrases around links.

        Returns:
            List of emerging relationship patterns
        """
        try:
            schema = self._load_schema()
            known_types = set(schema.get("relationship_types", []))

            # Extract contextual patterns around all links
            patterns = Counter()

            for md_file in self.wiki_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md", "SCHEMA.md", "maintenance.log"):
                    continue

                content = md_file.read_text(encoding="utf-8")

                # Find all [[...]] links and extract surrounding context
                for match in re.finditer(r"\[\[([^\]]+)\]\]", content):
                    start = max(0, match.start() - 50)
                    end = min(len(content), match.end() + 50)
                    context = content[start:end]

                    # Extract key phrases (words before/after link)
                    phrases = re.findall(r"\b([a-z]+(?:_[a-z]+)*)\b", context.lower())
                    for phrase in phrases:
                        if phrase not in known_types and len(phrase) > 3:
                            patterns[phrase] += 1

            # Find frequently occurring relationship phrases
            emerging = [
                {
                    "pattern": phrase,
                    "frequency": count,
                    "recommendation": f"Consider formalizing '{phrase}' as relationship type (found {count} times)",
                }
                for phrase, count in patterns.most_common(10) if count >= 5
            ]

            return emerging

        except Exception as e:
            _LOG.error(f"Error detecting emerging relationships: {e}")
            return []

    def detect_synthesis_opportunities(self) -> list[dict[str, Any]]:
        """
        Detect orphaned clusters that could benefit from synthesis pages.

        Identifies groups of related pages with no parent/synthesis page.

        Returns:
            List of synthesis opportunities
        """
        try:
            # Load relationships
            relationships_file = self.wiki_dir / ".meta" / "relationships.json"
            if not relationships_file.exists():
                return []

            rels_data = json.loads(relationships_file.read_text())
            relationships = rels_data.get("relationships", [])

            # Build graph of relationships
            graph = defaultdict(set)
            for rel in relationships:
                source = rel.get("source_id", "")
                target = rel.get("target_id", "")
                if source and target:
                    graph[source].add(target)
                    graph[target].add(source)

            # Find clusters (connected components)
            visited = set()
            clusters = []

            def dfs(node: str, cluster: set) -> None:
                if node in visited:
                    return
                visited.add(node)
                cluster.add(node)
                for neighbor in graph.get(node, set()):
                    dfs(neighbor, cluster)

            for page_id in graph:
                if page_id not in visited:
                    cluster = set()
                    dfs(page_id, cluster)
                    if len(cluster) >= 3:  # Only clusters of 3+ pages
                        clusters.append(cluster)

            # Check if clusters have synthesis pages
            opportunities = []
            schema = self._load_schema()
            schema.get("synthesis_triggers", [])

            for cluster in clusters:
                # Check if any page in cluster is marked as synthesis
                has_synthesis = False
                for page_id in cluster:
                    page_file = self.wiki_dir / f"{page_id}.md"
                    if page_file.exists():
                        content = page_file.read_text(encoding="utf-8")
                        if "category: synthesis" in content or "semantic_type: synthesis" in content:
                            has_synthesis = True
                            break

                if not has_synthesis and len(cluster) >= 3:
                    # Get cluster topic from page titles
                    page_titles = []
                    for page_id in list(cluster)[:3]:
                        page_file = self.wiki_dir / f"{page_id}.md"
                        if page_file.exists():
                            title_match = re.search(
                                r"^title:\s*['\"]?([^'\"\\n]+)",
                                page_file.read_text(encoding="utf-8"),
                                re.MULTILINE
                            )
                            if title_match:
                                page_titles.append(title_match.group(1))

                    opportunities.append({
                        "cluster_size": len(cluster),
                        "page_ids": list(cluster)[:5],
                        "sample_titles": page_titles,
                        "recommendation": f"Create synthesis page for cluster of {len(cluster)} related pages",
                    })

            return opportunities

        except Exception as e:
            _LOG.error(f"Error detecting synthesis opportunities: {e}")
            return []

    def get_schema_recommendations(self) -> dict[str, Any]:
        """
        Generate comprehensive schema evolution recommendations.

        Returns:
            {
                "categories": [emerging categories],
                "relationships": [emerging relationships],
                "syntheses": [synthesis opportunities],
                "analysis_date": ISO timestamp
            }
        """
        return {
            "analysis_date": datetime.now(UTC).isoformat(),
            "wiki_type": self.wiki_type,
            "project_id": self.project_id,
            "emerging_categories": self.detect_emerging_categories(),
            "emerging_relationships": self.detect_emerging_relationships(),
            "synthesis_opportunities": self.detect_synthesis_opportunities(),
        }

    def save_recommendations(self) -> str:
        """
        Save schema recommendations to file.

        Returns:
            Path to recommendations file
        """
        try:
            meta_dir = self.wiki_dir / ".meta"
            meta_dir.mkdir(exist_ok=True)

            recommendations = self.get_schema_recommendations()
            recommendations_file = meta_dir / "schema_recommendations.json"

            recommendations_file.write_text(
                json.dumps(recommendations, indent=2),
                encoding="utf-8"
            )

            _LOG.info(f"Saved schema recommendations to {recommendations_file}")
            return str(recommendations_file)

        except Exception as e:
            _LOG.error(f"Error saving recommendations: {e}")
            return ""

    def version_schema(self, version: str) -> bool:
        """
        Create a version checkpoint of the schema.

        Args:
            version: Version string (e.g., "1.1")

        Returns:
            True if successful
        """
        try:
            if not self.schema_file.exists():
                return False

            versioned_file = self.schema_file.with_stem(f"SCHEMA_v{version}")
            schema_content = self.schema_file.read_text(encoding="utf-8")
            versioned_file.write_text(schema_content, encoding="utf-8")

            _LOG.info(f"Versioned schema as {versioned_file.name}")
            return True

        except Exception as e:
            _LOG.error(f"Error versioning schema: {e}")
            return False


def analyze_schema(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Analyze wiki schema and get evolution recommendations.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        Schema analysis results
    """
    analyzer = SchemaAnalyzer(wiki_type, project_id)
    recommendations = analyzer.get_schema_recommendations()
    analyzer.save_recommendations()

    return {
        "status": "success",
        **recommendations,
    }


def detect_emerging_categories(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Detect emerging page categories."""
    analyzer = SchemaAnalyzer(wiki_type, project_id)
    return analyzer.detect_emerging_categories()


def detect_synthesis_opportunities(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Detect clusters that need synthesis pages."""
    analyzer = SchemaAnalyzer(wiki_type, project_id)
    return analyzer.detect_synthesis_opportunities()
