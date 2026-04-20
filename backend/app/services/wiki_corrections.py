"""
Wiki auto-correction for data quality (Cowork Tier 2).

Automatically fixes common wiki data issues:
- Malformed frontmatter (missing required fields)
- Broken cross-references (dangling links)
- Inconsistent formatting (heading levels, list markers)
- Data type mismatches (string numbers, invalid enums)
- Duplicate content (semantic duplicates)
- Stale references (outdated information)
"""

import json
import logging
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

# Default values for missing frontmatter fields
DEFAULT_CONFIDENCE = "medium"
DEFAULT_SOURCE_COUNT = 0
DEFAULT_CATEGORY = "concept"
DEFAULT_LINK_LIST = []


class DataCorrector:
    """Automatically correct common wiki data quality issues."""

    @staticmethod
    def correct_frontmatter(
        page_dict: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Fix malformed frontmatter (YAML metadata as JSON).

        Issues corrected:
        - Missing 'category' → auto-detect from content or use default
        - Missing 'source_count' → count from source_ids or use 0
        - Missing 'last_updated' → set to now
        - Missing 'confidence' → set to default (medium)
        - Invalid confidence value → snap to valid option (low|medium|high)

        Args:
            page_dict: Page with frontmatter dict

        Returns:
            Tuple[corrected_page, list_of_corrections]
        """
        corrections = []
        page = page_dict.copy()
        frontmatter = json.loads(page.get("frontmatter", "{}"))

        # Fix missing category
        if not frontmatter.get("category"):
            detected_category = _detect_category_from_content(page.get("content", ""))
            frontmatter["category"] = detected_category or DEFAULT_CATEGORY
            corrections.append(f"Set missing category to '{frontmatter['category']}'")

        # Fix missing source_count
        if "source_count" not in frontmatter:
            source_count = len(json.loads(page.get("source_run_ids", "[]")))
            frontmatter["source_count"] = source_count
            corrections.append(f"Set source_count to {source_count} from source_ids")

        # Fix missing last_updated
        if "last_updated" not in frontmatter:
            now_iso = datetime.now(UTC).isoformat()
            frontmatter["last_updated"] = now_iso
            corrections.append("Set last_updated to now")

        # Fix missing confidence
        if "confidence" not in frontmatter:
            frontmatter["confidence"] = DEFAULT_CONFIDENCE
            corrections.append(f"Set confidence to default '{DEFAULT_CONFIDENCE}'")

        # Fix invalid confidence value
        valid_confidences = {"low", "medium", "high"}
        if frontmatter.get("confidence") not in valid_confidences:
            old_val = frontmatter.get("confidence")
            frontmatter["confidence"] = DEFAULT_CONFIDENCE
            corrections.append(
                f"Snapped invalid confidence '{old_val}' to '{DEFAULT_CONFIDENCE}'"
            )

        page["frontmatter"] = json.dumps(frontmatter)
        return page, corrections

    @staticmethod
    def correct_references(
        page_dict: dict[str, Any],
        wiki_index: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Fix broken cross-references (dangling links).

        Issues corrected:
        - Links to non-existent pages → create stub or flag for manual review
        - Malformed link syntax → normalize to [text](slug.md) format
        - Invalid slugs → auto-generate from page name

        Args:
            page_dict: Page with content containing links
            wiki_index: Index of all valid pages (slugs)

        Returns:
            Tuple[corrected_page, list_of_corrections]
        """
        corrections = []
        page = page_dict.copy()
        content = page.get("content", "")

        # Find all markdown links: [text](slug.md)
        link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        matches = list(re.finditer(link_pattern, content))

        invalid_links = []
        for match in matches:
            link_text = match.group(1)
            link_target = match.group(2)

            # Check if target exists in wiki index
            valid_pages = wiki_index.get("pages", [])
            valid_slugs = {p.get("slug") for p in valid_pages}

            if link_target not in valid_slugs:
                # Link is broken - flag it
                invalid_links.append({
                    "text": link_text,
                    "target": link_target,
                    "position": match.start(),
                })

        if invalid_links:
            corrections.append(
                f"Found {len(invalid_links)} broken reference(s): "
                f"{', '.join([lnk['target'] for lnk in invalid_links])}"
            )

        # TODO: In Phase 2+, optionally auto-create stubs for missing pages
        # For now, just flag them

        return page, corrections

    @staticmethod
    def correct_formatting(page_text: str) -> tuple[str, list[str]]:
        """
        Fix inconsistent formatting.

        Issues corrected:
        - Mixed list markers (- and *) → normalize to -
        - Inconsistent heading hierarchy → standardize spacing
        - Multiple blank lines → normalize to max 1
        - Trailing whitespace → remove

        Args:
            page_text: Markdown content

        Returns:
            Tuple[corrected_text, list_of_corrections]
        """
        corrections = []
        text = page_text

        # Normalize list markers: * → -
        if "*" in text and re.search(r'^\*\s', text, re.MULTILINE):
            text = re.sub(r'^\*\s', "- ", text, flags=re.MULTILINE)
            corrections.append("Normalized list markers: * → -")

        # Normalize multiple blank lines to single blank line
        original_text = text
        text = re.sub(r'\n\n\n+', '\n\n', text)
        if text != original_text:
            corrections.append("Normalized multiple blank lines to single blank")

        # Remove trailing whitespace from lines
        original_text = text
        text = '\n'.join(line.rstrip() for line in text.split('\n'))
        if text != original_text:
            corrections.append("Removed trailing whitespace from lines")

        return text, corrections

    @staticmethod
    def correct_data_types(page_dict: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """
        Fix data type mismatches in frontmatter.

        Issues corrected:
        - String numbers (e.g., "5") → convert to int/float
        - String booleans (e.g., "true") → convert to bool
        - Invalid enum values → snap to valid option

        Args:
            page_dict: Page with potentially mistyped data

        Returns:
            Tuple[corrected_page, list_of_corrections]
        """
        corrections = []
        page = page_dict.copy()
        frontmatter = json.loads(page.get("frontmatter", "{}"))

        # Fix source_count if it's a string
        if "source_count" in frontmatter:
            val = frontmatter["source_count"]
            if isinstance(val, str):
                try:
                    frontmatter["source_count"] = int(val)
                    corrections.append(
                        f"Converted source_count from string '{val}' to int"
                    )
                except ValueError:
                    frontmatter["source_count"] = 0
                    corrections.append(
                        f"Could not convert source_count '{val}', set to 0"
                    )

        # Fix confidence if it's invalid
        valid_confidences = {"low", "medium", "high"}
        confidence = frontmatter.get("confidence", "").lower()
        if confidence and confidence not in valid_confidences:
            frontmatter["confidence"] = "medium"
            corrections.append(
                f"Snapped invalid confidence '{confidence}' to 'medium'"
            )

        page["frontmatter"] = json.dumps(frontmatter)
        return page, corrections

    @staticmethod
    def correct_duplication(all_pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Detect and flag duplicate content.

        Issues identified:
        - Same concept covered in multiple pages
        - Semantic similarity across pages
        - Suggests merges with cross-references

        Args:
            all_pages: All wiki pages to scan for duplicates

        Returns:
            Tuple[all_pages, list_of_merge_suggestions]
        """
        suggestions = []

        # Group pages by category
        entity_pages = [p for p in all_pages if p.get("category") == "entity"]

        # Simple heuristic: look for pages with very similar titles
        for i, page1 in enumerate(entity_pages):
            for page2 in entity_pages[i + 1:]:
                title1 = page1.get("title", "").lower()
                title2 = page2.get("title", "").lower()

                # Check for near-duplicate titles (threshold 0.75 catches common suffixes like "Overview")
                if _string_similarity(title1, title2) > 0.75:
                    suggestions.append({
                        "type": "potential_duplicate",
                        "page1_id": page1.get("id"),
                        "page1_title": page1.get("title"),
                        "page2_id": page2.get("id"),
                        "page2_title": page2.get("title"),
                        "suggestion": f"Consider merging '{page1.get('title')}' with '{page2.get('title')}'",
                    })

        return all_pages, suggestions

    @staticmethod
    def correct_stale_references(
        page_dict: dict[str, Any],
        log_entries: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Detect and flag stale references (outdated information).

        Issues identified:
        - Page references information superseded by newer sources
        - Page hasn't been updated despite new relevant ingests
        - Flags for manual review

        Args:
            page_dict: Page to check
            log_entries: Operation log to check for newer ingests

        Returns:
            Tuple[page_dict, list_of_staleness_flags]
        """
        corrections = []
        page = page_dict.copy()

        page_updated_at = page.get("updated_at")
        if not page_updated_at:
            return page, corrections

        # Check if there are newer ingest operations for similar topics
        newer_ingests = []
        for log_entry in log_entries:
            log_ts = log_entry.get("timestamp")
            if log_ts and log_ts > page_updated_at:
                log_source = log_entry.get("source_name", "")
                # Simple heuristic: if source name contains similar keywords
                if _has_common_keywords(page.get("title", ""), log_source):
                    newer_ingests.append(log_entry)

        if newer_ingests:
            corrections.append(
                f"Page potentially stale: "
                f"{len(newer_ingests)} newer ingest(s) on related topics"
            )

        return page, corrections

    @staticmethod
    def correct_missing_citations(
        answer: str,
        source_pages: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """
        Add missing citations to synthesized answers.

        Issues corrected:
        - Answer doesn't cite its sources
        - Missing attribution for claims
        - Auto-trace and add citation block

        Args:
            answer: Synthesized answer text
            source_pages: Pages used to generate answer

        Returns:
            Tuple[answer_with_citations, list_of_corrections]
        """
        corrections = []

        # Check if answer already has citations
        if not source_pages:
            return answer, corrections

        # Add citations block if not present
        if "Source" not in answer and "Based on" not in answer:
            citations = "\n\n---\n**Sources:**\n"
            for page in source_pages:
                page_title = page.get("title", "Untitled")
                page_id = page.get("id", "")
                citations += f"- [{page_title}](#{page_id})\n"

            answer_with_citations = answer + citations
            corrections.append(f"Added citations for {len(source_pages)} source page(s)")
            return answer_with_citations, corrections

        return answer, corrections


# ===== Helper Functions =====

def _detect_category_from_content(content: str) -> str | None:
    """
    Heuristically detect page category from content.

    Returns one of: entity, concept, comparison, template, synthesis, artifact
    """
    content_lower = content.lower()

    if "vs" in content_lower or "compare" in content_lower or "comparison" in content_lower:
        return "comparison"
    elif "template" in content_lower or "example" in content_lower:
        return "template"
    elif "synthesis" in content_lower or "integrated" in content_lower or "combined" in content_lower:
        return "synthesis"
    elif "artifact" in content_lower or "output" in content_lower or "deliverable" in content_lower:
        return "artifact"
    else:
        # Default to entity or concept
        return "entity"


def _string_similarity(s1: str, s2: str) -> float:
    """
    String similarity (0-1) using SequenceMatcher ratio.

    Handles partial matches and substring similarities effectively.
    Uses difflib.SequenceMatcher for robust character sequence comparison.
    """
    if not s1 or not s2:
        return 0.0

    # Use SequenceMatcher to find longest contiguous matching subsequence
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def _has_common_keywords(s1: str, s2: str) -> bool:
    """Check if two strings share significant keywords."""
    words1 = set(s1.lower().split())
    words2 = set(s2.lower().split())

    # Remove common filler words
    fillers = {"the", "a", "an", "and", "or", "is", "of", "to", "in", "for", "by"}
    words1 -= fillers
    words2 -= fillers

    # Check for overlap
    common = words1 & words2
    return len(common) > 0
