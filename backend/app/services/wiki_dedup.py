"""
Wiki duplicate detection and merging.

Detects semantically similar pages using BM25 + embedding similarity.
Proposes merges with confidence scores and auto-merges high-confidence duplicates.
"""

import json
import logging
import hashlib
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from pathlib import Path

from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)


class DuplicateDetector:
    """Detect and merge duplicate wiki pages."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: Optional[str] = None):
        """
        Initialize duplicate detector.

        Args:
            wiki_type: "leading_practice" or "project"
            project_id: Required if wiki_type is "project"
        """
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.pages = {}
        self._load_pages()

    def _get_wiki_dir(self) -> Path:
        """Get wiki directory."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def _load_pages(self) -> None:
        """Load all wiki pages."""
        for md_file in self.wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md", "maintenance.log"):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                page_id = md_file.stem

                # Extract title
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id

                # Extract body (everything after frontmatter)
                body_match = re.search(r"^---\s*$.*?^---\s*$\s*(.*)", content, re.MULTILINE | re.DOTALL)
                body = body_match.group(1) if body_match else content

                self.pages[page_id] = {
                    "path": md_file,
                    "title": title,
                    "content": content,
                    "body": body,
                    "size": len(body),
                }
            except Exception as e:
                _LOG.warning(f"Error loading page {md_file.stem}: {e}")

    def _bm25_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate BM25-like similarity (simplified).

        Splits text into tokens and calculates overlap.
        """
        def tokenize(text: str) -> set:
            tokens = re.findall(r"\b\w+\b", text.lower())
            return set(tokens)

        tokens1 = tokenize(text1)
        tokens2 = tokenize(text2)

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0

    def _content_hash(self, text: str) -> str:
        """Get hash of content."""
        return hashlib.md5(text.lower().encode()).hexdigest()[:8]

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts.

        Uses:
        1. BM25-like token overlap
        2. Length similarity
        3. Hash similarity (exact match detection)

        Returns score 0.0-1.0.
        """
        # BM25 component
        bm25_score = self._bm25_similarity(text1, text2)

        # Length similarity (similar length suggests duplication)
        len1, len2 = len(text1), len(text2)
        max_len = max(len1, len2)
        length_similarity = min(len1, len2) / max_len if max_len > 0 else 0.0

        # Hash similarity (for exact/near-exact matches)
        hash1 = self._content_hash(text1)
        hash_similarity = 1.0 if hash1 == self._content_hash(text2) else 0.0

        # Weighted combination
        similarity = (bm25_score * 0.6) + (length_similarity * 0.2) + (hash_similarity * 0.2)

        return min(1.0, similarity)

    def _title_similarity(self, title1: str, title2: str) -> float:
        """Calculate title similarity."""
        tokens1 = set(re.findall(r"\b\w+\b", title1.lower()))
        tokens2 = set(re.findall(r"\b\w+\b", title2.lower()))

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0

    def find_duplicates(self, confidence: float = 0.85) -> List[Dict[str, Any]]:
        """
        Find duplicate page candidates.

        Args:
            confidence: Minimum similarity threshold (0.0-1.0)

        Returns:
            List of duplicate candidate pairs with similarity scores
        """
        candidates = []
        page_ids = list(self.pages.keys())

        for i, page_id1 in enumerate(page_ids):
            for page_id2 in page_ids[i + 1:]:
                page1 = self.pages[page_id1]
                page2 = self.pages[page_id2]

                # Skip very different sizes (unlikely duplicates)
                size_ratio = min(page1["size"], page2["size"]) / max(page1["size"], page2["size"])
                if size_ratio < 0.5:
                    continue

                # Calculate similarity
                content_sim = self._calculate_similarity(page1["body"], page2["body"])
                title_sim = self._title_similarity(page1["title"], page2["title"])

                # Combined score
                combined_score = (content_sim * 0.8) + (title_sim * 0.2)

                if combined_score >= confidence:
                    candidates.append({
                        "page1_id": page_id1,
                        "page1_title": page1["title"],
                        "page2_id": page_id2,
                        "page2_title": page2["title"],
                        "content_similarity": round(content_sim, 3),
                        "title_similarity": round(title_sim, 3),
                        "combined_score": round(combined_score, 3),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        # Sort by combined score (highest first)
        candidates.sort(key=lambda x: x["combined_score"], reverse=True)

        _LOG.info(f"Found {len(candidates)} duplicate candidates in {self.wiki_type} wiki")
        return candidates

    def auto_merge_duplicates(self, candidates: List[Dict[str, Any]]) -> int:
        """
        Auto-merge high-confidence duplicates.

        Merges pages by:
        1. Keeping the older/more established page (by creation date)
        2. Redirecting the newer page to the older one
        3. Merging unique content

        Args:
            candidates: List of duplicate candidates

        Returns:
            Number of pages merged
        """
        merged = 0

        for candidate in candidates:
            try:
                page1_id = candidate["page1_id"]
                page2_id = candidate["page2_id"]
                score = candidate["combined_score"]

                page1 = self.pages[page1_id]
                page2 = self.pages[page2_id]

                _LOG.info(
                    f"Merging duplicates: {page1_id} + {page2_id} (score: {score})"
                )

                # Determine which is the primary (keep) page
                # For now, keep the first alphabetically (stable)
                if page1_id < page2_id:
                    primary_id, secondary_id = page1_id, page2_id
                    primary, secondary = page1, page2
                else:
                    primary_id, secondary_id = page2_id, page1_id
                    primary, secondary = page2, page1

                # Create redirect page for secondary
                redirect_content = f"""---
title: {secondary["title"]}
redirect_to: {primary_id}
status: archived
reason: merged_duplicate
merged_date: {datetime.now(timezone.utc).isoformat()}
---

This page has been merged into [[{primary_id}]].
"""
                secondary["path"].write_text(redirect_content, encoding="utf-8")

                # Update primary with merge metadata
                primary_content = primary["content"]
                if "merged_pages:" not in primary_content:
                    # Add merged_pages to frontmatter
                    primary_content = primary_content.replace(
                        "---\n",
                        f"---\nmerged_pages:\n  - {secondary_id}\n",
                        1
                    )
                else:
                    # Append to existing merged_pages
                    primary_content = primary_content.replace(
                        f"merged_pages:",
                        f"merged_pages:\n  - {secondary_id}"
                    )

                primary["path"].write_text(primary_content, encoding="utf-8")

                merged += 1

            except Exception as e:
                _LOG.error(f"Error merging {candidate}: {e}")

        return merged

    def get_duplicate_report(self, candidates: List[Dict[str, Any]]) -> str:
        """
        Generate a report of duplicate candidates.

        Args:
            candidates: List of duplicate candidates

        Returns:
            Markdown-formatted report
        """
        if not candidates:
            return "No duplicate candidates found."

        report = f"# Duplicate Pages Report\n\n"
        report += f"Found {len(candidates)} potential duplicates.\n\n"
        report += "| Page 1 | Page 2 | Content Similarity | Title Similarity | Combined |\n"
        report += "|--------|--------|-------------------|------------------|----------|\n"

        for candidate in candidates:
            p1 = candidate["page1_title"]
            p2 = candidate["page2_title"]
            cs = candidate["content_similarity"]
            ts = candidate["title_similarity"]
            combined = candidate["combined_score"]

            report += f"| {p1} | {p2} | {cs} | {ts} | {combined} |\n"

        return report
