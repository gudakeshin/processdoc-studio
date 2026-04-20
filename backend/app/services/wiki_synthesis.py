"""
Wiki synthesis engine for autonomous knowledge generation (Phase 5).

Implements intelligent synthesis following Karpathy's Second Brain:
- Auto-generate synthesis pages for related page clusters
- Detect and resolve contradictions across pages
- Create insight/principle pages from relationship patterns
- Fill knowledge gaps with LLM-generated content

This is the final intelligence layer making the wiki truly autonomous.
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


class SynthesisEngine:
    """Generate synthesis pages and insights from wiki content."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """Initialize synthesis engine."""
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

    def _load_relationships(self) -> list[dict[str, Any]]:
        """Load relationships from storage."""
        try:
            relationships_file = self.wiki_dir / ".meta" / "relationships.json"
            if relationships_file.exists():
                data = json.loads(relationships_file.read_text())
                return data.get("relationships", [])
            return []
        except Exception as e:
            _LOG.warning(f"Error loading relationships: {e}")
            return []

    def _get_page_content(self, page_id: str) -> str | None:
        """Get content of a wiki page."""
        try:
            page_file = self.wiki_dir / f"{page_id}.md"
            if page_file.exists():
                return page_file.read_text(encoding="utf-8")
            return None
        except Exception as e:
            _LOG.warning(f"Error reading page {page_id}: {e}")
            return None

    def _extract_page_title(self, content: str) -> str:
        """Extract title from page content."""
        match = re.search(r"^title:\s*['\"]?([^'\"\\n]+)", content, re.MULTILINE)
        return match.group(1) if match else "Untitled"

    def _extract_key_concepts(self, content: str) -> list[str]:
        """Extract key concepts from page content."""
        # Extract from "Key Concepts" section or headers
        concepts = []

        # Look for "Key Concepts" section
        key_concepts_match = re.search(
            r"## Key Concepts\s*\n((?:[-*]\s+.+\n)*)",
            content,
            re.MULTILINE
        )

        if key_concepts_match:
            lines = key_concepts_match.group(1).split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("-") or line.startswith("*"):
                    concept = line.lstrip("-* ").split(":")[0].strip()
                    if concept:
                        concepts.append(concept)

        # Also extract section headers
        headers = re.findall(r"^###?\s+([^\n]+)", content, re.MULTILINE)
        concepts.extend([h.strip() for h in headers if h.strip()])

        return list(set(concepts))[:10]

    def _load_storyline_draft(self) -> dict[str, Any]:
        """Load optional storyline draft for synthesis guidance."""
        try:
            draft_file = self.wiki_dir / ".meta" / "storyline_draft.json"
            if not draft_file.exists():
                return {}
            payload = json.loads(draft_file.read_text(encoding="utf-8"))
            if "data" in payload and isinstance(payload.get("data"), dict):
                payload = payload["data"]
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def find_synthesis_clusters(self) -> list[dict[str, Any]]:
        """
        Find page clusters that need synthesis pages.

        Returns:
            List of clusters with pages that should be synthesized
        """
        try:
            relationships = self._load_relationships()

            # Build graph from relationships
            graph = defaultdict(set)
            for rel in relationships:
                source = rel.get("source_id", "")
                target = rel.get("target_id", "")
                if source and target:
                    graph[source].add(target)
                    graph[target].add(source)

            # Find connected components (clusters)
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

                    # Only include clusters of 3+ pages without synthesis
                    if len(cluster) >= 3:
                        # Check if cluster already has synthesis page
                        has_synthesis = False
                        for page_id_in_cluster in cluster:
                            content = self._get_page_content(page_id_in_cluster)
                            if content and "category: synthesis" in content:
                                has_synthesis = True
                                break

                        if not has_synthesis:
                            # Get titles and concepts
                            titles = []
                            all_concepts = []
                            for pid in list(cluster)[:5]:
                                content = self._get_page_content(pid)
                                if content:
                                    titles.append(self._extract_page_title(content))
                                    all_concepts.extend(self._extract_key_concepts(content))

                            clusters.append({
                                "cluster_size": len(cluster),
                                "page_ids": sorted(list(cluster)),
                                "sample_titles": titles[:3],
                                "key_concepts": list(set(all_concepts))[:5],
                                "score": len(cluster) * (len(all_concepts) / max(len(all_concepts), 1)),
                            })

            # Sort by score
            clusters.sort(key=lambda x: x["score"], reverse=True)
            return clusters

        except Exception as e:
            _LOG.error(f"Error finding synthesis clusters: {e}")
            return []

    def detect_contradictions(self) -> list[dict[str, Any]]:
        """
        Detect contradictory claims across pages.

        Looks for pages linked with "contradicts" relationship or
        conflicting statements about the same concepts.

        Returns:
            List of contradictions detected
        """
        try:
            relationships = self._load_relationships()
            contradictions = []

            # Find explicit contradictions
            for rel in relationships:
                if rel.get("relation_type") == "contradicts":
                    source_id = rel.get("source_id", "")
                    target_id = rel.get("target_id", "")

                    source_content = self._get_page_content(source_id)
                    target_content = self._get_page_content(target_id)

                    if source_content and target_content:
                        source_title = self._extract_page_title(source_content)
                        target_title = self._extract_page_title(target_content)

                        contradictions.append({
                            "type": "explicit_contradiction",
                            "severity": "high",
                            "page1_id": source_id,
                            "page1_title": source_title,
                            "page2_id": target_id,
                            "page2_title": target_title,
                            "recommendation": f"Create comparison page to clarify differences between '{source_title}' and '{target_title}'",
                        })

            return contradictions

        except Exception as e:
            _LOG.error(f"Error detecting contradictions: {e}")
            return []

    def find_pattern_principles(self) -> list[dict[str, Any]]:
        """
        Discover principles from relationship patterns.

        Analyzes relationship types to extract high-level principles.

        Returns:
            List of discovered principles
        """
        try:
            relationships = self._load_relationships()
            principle_patterns = defaultdict(int)

            # Count relationship patterns
            for rel in relationships:
                rel_type = rel.get("relation_type", "")
                if rel_type and rel_type != "mentions":
                    principle_patterns[rel_type] += 1

            principles = []

            # Generate principles from patterns
            pattern_definitions = {
                "parent_of": "Hierarchical Organization: Knowledge is hierarchically organized",
                "refines": "Iterative Improvement: Concepts build on and improve each other",
                "example_of": "Exemplification: Abstract ideas have concrete implementations",
                "implements": "Concretization: Concepts have real-world applications",
                "contradicts": "Disambiguation: Some concepts require clarification through comparison",
            }

            for pattern, count in principle_patterns.most_common():
                if pattern in pattern_definitions and count >= 3:
                    principles.append({
                        "principle": pattern_definitions[pattern],
                        "pattern": pattern,
                        "evidence_count": count,
                        "confidence": min(0.95, 0.6 + (count / 10) * 0.35),
                        "recommendation": f"Document '{pattern}' pattern in schema (found {count} instances)",
                    })

            return principles

        except Exception as e:
            _LOG.error(f"Error finding principles: {e}")
            return []

    def generate_synthesis_content(
        self,
        cluster_pages: list[str],
        cluster_concepts: list[str],
    ) -> str:
        """
        Generate synthesis page content for a cluster using Claude.

        Falls back to a structural template when Claude is unavailable.
        """
        try:
            page_info = []
            for page_id in cluster_pages[:5]:
                content = self._get_page_content(page_id)
                if content:
                    title = self._extract_page_title(content)
                    # Strip frontmatter for the LLM context
                    body = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL).strip()
                    page_info.append({"id": page_id, "title": title, "body": body[:600]})

            synthesis_title = f"Synthesis: {', '.join(cluster_concepts[:2])}"
            now = datetime.now(UTC).isoformat()
            linked_entities = "\n".join(f"  - {pid}" for pid in cluster_pages[:5])

            frontmatter = (
                f'---\ntitle: "{synthesis_title}"\ncategory: synthesis\n'
                f"semantic_type: synthesis\nstatus: published\ncreated_at: {now}\n"
                f"_auto_generated: true\nlinked_entities:\n{linked_entities}\n---\n\n"
            )

            try:
                from app.services.claude import claude_generate, is_claude_enabled
                if not is_claude_enabled():
                    raise RuntimeError("Claude disabled")
                storyline = self._load_storyline_draft()
                storyline_hint = ""
                if storyline:
                    storyline_hint = (
                        "\n\nStoryline drafting hints (if relevant to this cluster):\n"
                        f"{json.dumps(storyline.get('sections', []), indent=2)}\n"
                    )

                context_blocks = "\n\n".join(
                    f"### {p['title']} ([[{p['id']}]])\n{p['body']}"
                    for p in page_info
                )
                body = claude_generate(
                    system=(
                        "You are a wiki curator following Karpathy's second-brain model. "
                        "Given a cluster of related wiki pages, write a synthesis page in Markdown that:\n"
                        "1. Opens with a 2-3 sentence overview connecting the pages\n"
                        "2. Identifies 2-4 key themes that span the pages\n"
                        "3. Notes any contradictions or tensions between pages\n"
                        "4. Proposes a recommended reading order with brief rationale\n"
                        "5. Uses [[page_id|Title]] wiki-link syntax for every page reference\n"
                        "Do NOT include frontmatter — start directly with ## Overview. "
                        "Be concise; aim for 300-500 words."
                    ),
                    user=(
                        f"Synthesise these {len(page_info)} related wiki pages:\n\n"
                        f"{context_blocks}{storyline_hint}"
                    ),
                    max_tokens=900,
                )
            except Exception as claude_err:
                _LOG.warning(f"Claude synthesis unavailable, using template: {claude_err}")
                # Structural fallback (no LLM)
                page_links = "\n".join(f"- [[{p['id']}|{p['title']}]]" for p in page_info)
                concepts_str = "\n".join(f"- {c}" for c in cluster_concepts[:5])
                body = (
                    f"## Overview\n\nThis page synthesises insights from "
                    f"{len(cluster_pages)} related pages.\n\n"
                    f"## Pages\n\n{page_links}\n\n"
                    f"## Key Concepts\n\n{concepts_str}\n\n"
                    f"*Auto-generated synthesis — Claude unavailable at creation time.*\n"
                )

            return frontmatter + body

        except Exception as e:
            _LOG.error(f"Error generating synthesis content: {e}")
            return ""

    def create_synthesis_pages(self, max_pages: int = 5) -> dict[str, Any]:
        """
        Create synthesis pages for discovered clusters.

        Args:
            max_pages: Maximum number of synthesis pages to create

        Returns:
            {
                "created": int,
                "skipped": int,
                "pages": [page_ids]
            }
        """
        try:
            clusters = self.find_synthesis_clusters()
            created = 0
            skipped = 0
            pages = []

            for cluster in clusters[:max_pages]:
                try:
                    # Create synthesis page ID
                    concepts_slug = "_".join(
                        cluster["key_concepts"][0].lower().replace(" ", "_")
                        for i in range(min(2, len(cluster["key_concepts"])))
                    )
                    page_id = f"synthesis_{concepts_slug}_{cluster['cluster_size']}"[:50]

                    # Generate content
                    content = self.generate_synthesis_content(
                        cluster["page_ids"],
                        cluster["key_concepts"]
                    )

                    # Write synthesis page
                    page_file = self.wiki_dir / f"{page_id}.md"
                    page_file.write_text(content, encoding="utf-8")

                    created += 1
                    pages.append(page_id)
                    _LOG.info(f"Created synthesis page: {page_id}")

                except Exception as e:
                    _LOG.warning(f"Error creating synthesis page for cluster: {e}")
                    skipped += 1

            return {
                "status": "success",
                "created": created,
                "skipped": skipped,
                "pages": pages,
            }

        except Exception as e:
            _LOG.error(f"Error creating synthesis pages: {e}")
            return {"status": "error", "error": str(e)}

    def get_synthesis_insights(self) -> dict[str, Any]:
        """
        Get comprehensive synthesis insights for wiki.

        Returns:
            {
                "synthesis_clusters": [clusters],
                "contradictions": [contradictions],
                "principles": [principles],
                "opportunities": int
            }
        """
        return {
            "status": "success",
            "wiki_type": self.wiki_type,
            "analysis_date": datetime.now(UTC).isoformat(),
            "synthesis_clusters": self.find_synthesis_clusters(),
            "contradictions": self.detect_contradictions(),
            "principles": self.find_pattern_principles(),
            "opportunities": len(self.find_synthesis_clusters()),
        }


def get_synthesis_insights(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Get comprehensive synthesis insights."""
    engine = SynthesisEngine(wiki_type, project_id)
    return engine.get_synthesis_insights()


def create_synthesis_pages(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Create synthesis pages for discovered clusters."""
    engine = SynthesisEngine(wiki_type, project_id)
    return engine.create_synthesis_pages(max_pages)


def detect_contradictions(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Detect contradictions in wiki."""
    engine = SynthesisEngine(wiki_type, project_id)
    return engine.detect_contradictions()


def find_pattern_principles(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Discover principles from relationship patterns."""
    engine = SynthesisEngine(wiki_type, project_id)
    return engine.find_pattern_principles()
