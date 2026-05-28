"""
Wiki quality assurance and linting for data quality (Cowork Tier 3).

Performs comprehensive health checks on wiki content:
- Contradiction detection (conflicting claims)
- Orphan page detection (no inbound links)
- Missing cross-references (mentioned but no page)
- Broken links (references to non-existent pages)
- Coverage gaps (frequently mentioned but under-explored)
- Divergence check (project vs LP alignment)
- Staleness check (outdated pages)
"""

import logging
import re
from datetime import datetime, timedelta
from app.core.tz import IST
from typing import Any

logger = logging.getLogger(__name__)


class WikiQAEvaluator:
    """Evaluate wiki quality and health."""

    @staticmethod
    def evaluate_wiki_health(
        pages: list[dict[str, Any]],
        wiki_index: dict[str, Any],
        log_entries: list[dict[str, Any]],
        days_threshold: int = 30,
    ) -> dict[str, Any]:
        """
        Perform comprehensive wiki health check.

        Runs all health checks and aggregates issues, suggestions, and severity.

        Args:
            pages: All wiki pages to check
            wiki_index: Wiki index with catalog of pages
            log_entries: Operation log entries
            days_threshold: Days to consider page "stale"

        Returns:
            {
                "passed": bool,
                "issues": list[issue_dict],
                "suggestions": list[suggestion_dict],
                "severity": "low"|"medium"|"high",
                "issues_count": int,
                "suggestions_count": int,
            }
        """
        issues = []

        # Run all health checks
        issues.extend(WikiQAEvaluator._check_contradictions(pages))
        issues.extend(WikiQAEvaluator._check_orphans(pages))
        issues.extend(WikiQAEvaluator._check_missing_references(pages, wiki_index))
        issues.extend(WikiQAEvaluator._check_broken_links(pages, wiki_index))
        issues.extend(WikiQAEvaluator._check_coverage_gaps(pages))
        issues.extend(WikiQAEvaluator._check_staleness(pages, log_entries, days_threshold))

        # Generate suggestions from issues
        suggestions = WikiQAEvaluator._generate_suggestions(issues, pages)

        # Calculate severity
        severity = "low"
        if len(issues) >= 10:
            severity = "high"
        elif len(issues) >= 1:
            severity = "medium"

        result = {
            "passed": len(issues) == 0,
            "issues": issues,
            "suggestions": suggestions,
            "severity": severity,
            "issues_count": len(issues),
            "suggestions_count": len(suggestions),
        }

        logger.info(f"Wiki health check complete: {len(issues)} issues, severity={severity}")
        return result

    @staticmethod
    def _check_contradictions(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Detect contradictory claims across pages.

        Identifies pages that make conflicting statements about the same topic.

        Returns:
            List of contradiction issues
        """
        issues = []

        if not pages:
            return issues

        # Simple heuristic: look for conflicting numeric claims about the same topic
        for i, page1 in enumerate(pages):
            content1 = page1.get("content", "").lower()
            title1 = page1.get("title", "").lower()

            for page2 in pages[i + 1:]:
                content2 = page2.get("content", "").lower()
                title2 = page2.get("title", "").lower()

                # Check if pages share common keywords (same topic)
                words1 = set(title1.split())
                words2 = set(title2.split())
                common = words1 & words2

                if common:
                    # Look for conflicting numeric claims
                    numbers1 = re.findall(r'\d+', content1)
                    numbers2 = re.findall(r'\d+', content2)

                    # If they mention the same topic but different numbers, flag it
                    if numbers1 and numbers2 and numbers1[0] != numbers2[0]:
                        # Likely contradiction
                        issues.append({
                            "type": "contradiction",
                            "page1_id": page1.get("id"),
                            "page1_title": page1.get("title"),
                            "page2_id": page2.get("id"),
                            "page2_title": page2.get("title"),
                            "suggestion": f"Verify conflicting claims in '{page1.get('title')}' and '{page2.get('title')}'",
                        })

        return issues

    @staticmethod
    def _check_orphans(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Detect orphaned pages (no inbound links).

        Identifies pages that are never referenced from other pages.

        Returns:
            List of orphan page issues
        """
        issues = []

        if not pages:
            return issues

        # Build reverse link map
        all_outbound = set()
        for page in pages:
            outbound = page.get("outbound_links", [])
            if isinstance(outbound, list):
                all_outbound.update(outbound)

        # Find pages with no inbound links
        for page in pages:
            page_id = page.get("id")
            if page_id not in all_outbound and len(pages) > 1:  # Don't flag orphans in single-page wiki
                issues.append({
                    "type": "orphan_page",
                    "page_id": page_id,
                    "page_title": page.get("title"),
                    "suggestion": f"Page '{page.get('title')}' has no inbound links. Consider adding cross-references or deleting if obsolete.",
                })

        return issues

    @staticmethod
    def _check_missing_references(
        pages: list[dict[str, Any]],
        wiki_index: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Detect missing pages for frequently mentioned concepts.

        Identifies entities/concepts mentioned in multiple pages but without dedicated pages.

        Returns:
            List of missing reference issues
        """
        issues = []

        if not pages:
            return issues

        # Collect all valid page slugs
        valid_pages = wiki_index.get("pages", [])
        valid_slugs = {p.get("slug") for p in valid_pages}

        # Count concept mentions across all pages
        concept_mentions = {}
        for page in pages:
            page.get("content", "").lower()
            # Simple approach: extract capitalized terms (likely concepts)
            # This is a heuristic and would be more sophisticated in production
            concepts = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', page.get("content", ""))
            for concept in concepts:
                concept_slug = concept.lower().replace(" ", "_")
                if concept_slug not in valid_slugs:
                    concept_mentions[concept] = concept_mentions.get(concept, 0) + 1

        # Flag concepts mentioned frequently but without pages
        for concept, count in concept_mentions.items():
            if count >= 3:  # Mentioned in 3+ pages
                issues.append({
                    "type": "missing_reference",
                    "concept": concept,
                    "mention_count": count,
                    "suggestion": f"Concept '{concept}' mentioned {count} times but no dedicated page. Consider creating entity page.",
                })

        return issues

    @staticmethod
    def _check_broken_links(
        pages: list[dict[str, Any]],
        wiki_index: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Detect broken cross-references.

        Identifies links pointing to non-existent pages.

        Returns:
            List of broken link issues
        """
        issues = []

        if not pages:
            return issues

        # Collect valid page slugs
        valid_pages = wiki_index.get("pages", [])
        valid_slugs = {p.get("slug") for p in valid_pages}

        # Check each page's outbound links
        for page in pages:
            outbound = page.get("outbound_links", [])
            if isinstance(outbound, list):
                for link_target in outbound:
                    if link_target not in valid_slugs:
                        issues.append({
                            "type": "broken_link",
                            "page_id": page.get("id"),
                            "page_title": page.get("title"),
                            "broken_link": link_target,
                            "suggestion": f"Page '{page.get('title')}' links to non-existent page '{link_target}'",
                        })

        return issues

    @staticmethod
    def _check_coverage_gaps(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Detect under-explored topics.

        Identifies frequently mentioned topics that lack dedicated coverage.

        Returns:
            List of coverage gap issues
        """
        issues = []

        if not pages:
            return issues

        # Count term frequencies
        term_frequency = {}
        for page in pages:
            content = page.get("content", "").lower()
            # Extract terms (simplified: split by whitespace and filter)
            words = re.findall(r'\b\w+\b', content)
            for word in words:
                if len(word) > 5:  # Only count substantial terms
                    term_frequency[word] = term_frequency.get(word, 0) + 1

        # Check if frequently mentioned terms have coverage
        for term, freq in term_frequency.items():
            if freq >= 4:  # Mentioned 4+ times
                # Check if there's a page about this term
                has_page = any(term in p.get("title", "").lower() for p in pages)
                if not has_page:
                    issues.append({
                        "type": "coverage_gap",
                        "term": term,
                        "mention_count": freq,
                        "suggestion": f"Term '{term}' mentioned {freq} times. Consider creating dedicated page or consolidating coverage.",
                    })

        return issues

    @staticmethod
    def _check_divergence(
        project_pages: list[dict[str, Any]],
        lp_pages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Detect divergence between project wiki and LP wiki.

        Identifies where project practices diverge from leading practices
        and should be documented.

        Returns:
            List of divergence issues
        """
        issues = []

        if not project_pages or not lp_pages:
            return issues

        # Simple heuristic: look for "Despite", "Unlike", "Although" patterns
        # that indicate intentional divergence
        divergence_indicators = ["despite", "unlike", "although", "instead of", "rather than"]

        for page in project_pages:
            content = page.get("content", "").lower()

            for indicator in divergence_indicators:
                if indicator in content:
                    # Found potential divergence statement
                    issues.append({
                        "type": "divergence",
                        "page_id": page.get("id"),
                        "page_title": page.get("title"),
                        "suggestion": f"Page '{page.get('title')}' documents divergence from leading practices. Ensure justification is clear.",
                    })
                    break

        return issues

    @staticmethod
    def _check_staleness(
        pages: list[dict[str, Any]],
        log_entries: list[dict[str, Any]],
        days_threshold: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Detect stale pages that haven't been updated despite newer relevant ingests.

        Returns:
            List of staleness issues
        """
        issues = []

        if not pages:
            return issues

        now = datetime.now(IST)
        threshold_date = now - timedelta(days=days_threshold)

        for page in pages:
            updated_at_str = page.get("updated_at")
            if not updated_at_str:
                continue

            try:
                updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                # Make naive datetimes aware for comparison
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=IST)
            except (ValueError, AttributeError):
                continue

            # Check if page is stale
            if updated_at < threshold_date:
                # Check if there are newer ingests on related topics
                page_title = page.get("title", "").lower()
                newer_ingests = []

                for log in log_entries:
                    log_ts_str = log.get("timestamp")
                    if not log_ts_str:
                        continue

                    try:
                        log_ts = datetime.fromisoformat(log_ts_str.replace("Z", "+00:00"))
                        # Make naive datetimes aware for comparison
                        if log_ts.tzinfo is None:
                            log_ts = log_ts.replace(tzinfo=IST)
                    except (ValueError, AttributeError):
                        continue

                    if log_ts > updated_at:
                        # Check if log is about related topic
                        source_name = log.get("source_name", "").lower()
                        # Simple keyword matching
                        if _has_common_keywords(page_title, source_name):
                            newer_ingests.append(log)

                if newer_ingests:
                    issues.append({
                        "type": "stale_page",
                        "page_id": page.get("id"),
                        "page_title": page.get("title"),
                        "last_updated": updated_at_str,
                        "newer_ingests": len(newer_ingests),
                        "suggestion": f"Page '{page.get('title')}' hasn't been updated in {days_threshold}+ days despite {len(newer_ingests)} newer related ingest(s).",
                    })

        return issues

    @staticmethod
    def _generate_suggestions(
        issues: list[dict[str, Any]],
        pages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Generate actionable suggestions from detected issues.

        Returns:
            List of suggestions with recommended actions
        """
        suggestions = []

        # Group issues by type
        by_type = {}
        for issue in issues:
            issue_type = issue.get("type", "")
            if issue_type not in by_type:
                by_type[issue_type] = []
            by_type[issue_type].append(issue)

        # Generate type-specific suggestions
        if "orphan_page" in by_type:
            suggestions.append({
                "action": "review_orphans",
                "description": f"Review {len(by_type['orphan_page'])} orphaned page(s). Delete if obsolete or add cross-references.",
                "priority": "medium",
            })

        if "broken_link" in by_type:
            suggestions.append({
                "action": "fix_broken_links",
                "description": f"Fix {len(by_type['broken_link'])} broken link(s). Create missing pages or update references.",
                "priority": "high",
            })

        if "contradiction" in by_type:
            suggestions.append({
                "action": "resolve_contradictions",
                "description": f"Resolve {len(by_type['contradiction'])} conflicting claim(s). Verify facts and align statements.",
                "priority": "high",
            })

        if "stale_page" in by_type:
            suggestions.append({
                "action": "refresh_stale_pages",
                "description": f"Review and refresh {len(by_type['stale_page'])} stale page(s) in light of newer sources.",
                "priority": "medium",
            })

        if "coverage_gap" in by_type:
            suggestions.append({
                "action": "improve_coverage",
                "description": f"Improve coverage for {len(by_type['coverage_gap'])} under-explored topic(s).",
                "priority": "low",
            })

        if "missing_reference" in by_type:
            suggestions.append({
                "action": "create_entity_pages",
                "description": f"Create {len(by_type['missing_reference'])} new entity page(s) for frequently mentioned concepts.",
                "priority": "medium",
            })

        return suggestions


# ===== Helper Functions =====

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
