"""
wiki_lint.py — Wiki quality/health check helpers (Tier 3 QA).

Handles broken link detection, orphan detection, missing entity detection,
contradictions, coverage gaps, staleness, and overall wiki QA evaluation.
"""
import json
import logging
import re
from datetime import UTC, datetime

try:
    import yaml
except ImportError:
    yaml = None

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_broken_links(wiki_type: str, project_id: str | None) -> list:
    """
    Check for broken links in wiki pages.

    Detects [[Page Name]] references to non-existent pages.
    """
    try:
        import re

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        # Get all page IDs
        page_ids = set()
        page_titles = {}
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md"):
                page_id = md_file.stem
                page_ids.add(page_id)

                content = md_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id
                page_titles[page_id] = title

        # Check for broken links
        issues = []
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md"):
                continue

            page_id = md_file.stem
            content = md_file.read_text(encoding="utf-8")

            # Find [[Page Name]] patterns
            links = re.findall(r"\[\[([^\]]+)\]\]", content)

            for link_text in links:
                link_id = link_text.lower().replace(" ", "_").replace(".", "")[:50]

                # Check if target exists
                if link_id not in page_ids:
                    issues.append({
                        "type": "broken_link",
                        "severity": "medium",
                        "page_id": page_id,
                        "page_title": page_titles.get(page_id, page_id),
                        "target": link_text,
                        "target_id": link_id,
                        "message": f"Broken link: [[{link_text}]] references non-existent page",
                    })

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking broken links: {e}")
        return []


def _check_orphaned_pages(wiki_type: str, project_id: str | None) -> list:
    """
    Find orphaned pages (no inbound links).

    Pages with zero inbound links may need to be merged or deleted.
    """
    try:
        import re

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        # Load relationship counts
        rel_counts = get_relationship_counts(wiki_type, project_id)
        page_titles = {}

        # Get all page titles
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md"):
                page_id = md_file.stem
                content = md_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id
                page_titles[page_id] = title

        # Find orphaned pages
        issues = []
        for page_id, title in page_titles.items():
            inbound = rel_counts.get(page_id, {}).get("inbound", 0)

            if inbound == 0:
                issues.append({
                    "type": "orphaned_page",
                    "severity": "low",
                    "page_id": page_id,
                    "page_title": title,
                    "inbound_links": 0,
                    "message": f"Orphaned page: {title} has no inbound links (consider merging or deleting)",
                })

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking orphaned pages: {e}")
        return []


def _check_missing_entities(wiki_type: str, project_id: str | None) -> list:
    """
    Find missing entities: concepts mentioned 5+ times without dedicated page.

    Suggests creating pages for frequently-mentioned concepts.
    """
    try:
        import re
        from collections import Counter

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        # Collect all page titles and content
        page_titles = {}
        all_text = ""

        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md"):
                page_id = md_file.stem
                content = md_file.read_text(encoding="utf-8")

                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id
                page_titles[page_id] = title
                all_text += " " + content

        # Find capitalized phrases (potential entity names)
        phrases = re.findall(r"\b([A-Z][a-z]+ (?:[A-Z][a-z]+)*)\b", all_text)
        phrase_counts = Counter(phrases)

        # Find frequently mentioned phrases without dedicated pages
        issues = []
        for phrase, count in phrase_counts.most_common(50):
            if count >= 5:
                # Check if a page exists for this phrase
                phrase_id = phrase.lower().replace(" ", "_").replace(".", "")[:50]

                if phrase_id not in page_titles and phrase not in [t.lower() for t in page_titles.values()]:
                    issues.append({
                        "type": "missing_entity",
                        "severity": "low",
                        "entity_name": phrase,
                        "mention_count": count,
                        "message": f"Missing entity: '{phrase}' mentioned {count} times without dedicated page",
                    })

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking missing entities: {e}")
        return []


def get_relationship_counts(wiki_type: str, project_id: str | None) -> dict:
    """
    Load relationship statistics from relationships.json.

    Returns dict with inbound/outbound counts per page.
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
            # Fallback to old location
            relationships_file = wiki_dir / "relationships.json"
        if not relationships_file.exists():
            return {}

        rels_data = json.loads(relationships_file.read_text())

        # Build inbound/outbound counts
        counts = {}
        for rel in rels_data.get("relationships", []):
            source_id = rel["source_id"]
            target_id = rel["target_id"]

            if source_id not in counts:
                counts[source_id] = {"outbound": 0, "inbound": 0}
            if target_id not in counts:
                counts[target_id] = {"outbound": 0, "inbound": 0}

            counts[source_id]["outbound"] += 1
            counts[target_id]["inbound"] += 1

        return counts
    except Exception as e:
        _LOG.warning(f"Error loading relationship counts: {e}")
        return {}


# ---------------------------------------------------------------------------
# Expanded checks (Phase 3+)
# ---------------------------------------------------------------------------

def _get_all_wiki_pages(wiki_type: str, project_id: str | None) -> list:
    """Get all wiki pages with full metadata."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        pages = []
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md"):
                continue

            page_id = md_file.stem
            content = md_file.read_text(encoding="utf-8")

            # Extract metadata from frontmatter
            title = page_id
            category = "concept"
            semantic_type = "concept"
            created_at = None
            last_updated = None

            fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if fm_match:
                try:
                    if yaml:
                        fm_data = yaml.safe_load(fm_match.group(1))
                        if fm_data:
                            title = fm_data.get("title", page_id)
                            category = fm_data.get("category", "concept")
                            semantic_type = fm_data.get("semantic_type", "concept")
                            created_at = fm_data.get("created_at")
                            last_updated = fm_data.get("last_updated")
                except Exception:  # noqa: BLE001, S110 — best-effort, non-fatal
                    pass

            # Extract body
            body = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL).strip()

            pages.append({
                "page_id": page_id,
                "title": title,
                "category": category,
                "semantic_type": semantic_type,
                "created_at": created_at,
                "last_updated": last_updated,
                "content": body,
                "word_count": len(body.split()),
                "file": md_file,
            })

        return pages

    except Exception as e:
        _LOG.warning(f"Error getting all wiki pages: {e}")
        return []


def _check_contradictions(pages: list) -> list:
    """
    Check for contradictory claims across pages.

    Detects when pages claim opposite things about the same concept.
    """
    try:
        if not pages:
            return []

        issues = []

        # Build a map of claimed facts (topic: {property: [values]})
        facts = {}
        for page in pages:
            page_id = page.get("page_id", "")
            title = page.get("title", page_id)
            content = page.get("content", "")

            # Extract sentences with "is", "are", "means", "definition"
            sentences = re.split(r'[.!?]\s+', content)

            for sentence in sentences:
                # Look for definition-like statements
                if re.search(r'\b(is|are|means|defined as|refers to)\b', sentence, re.IGNORECASE):
                    # Extract subject and predicate
                    match = re.search(r'^([A-Z][^.!?]*?)\s+(?:is|are|means|defined as|refers to)\s+(.+?)$', sentence, re.IGNORECASE)
                    if match:
                        subject = match.group(1).strip().lower()[:50]
                        predicate = match.group(2).strip().lower()[:100]

                        if subject not in facts:
                            facts[subject] = {}
                        if "definitions" not in facts[subject]:
                            facts[subject]["definitions"] = []

                        facts[subject]["definitions"].append({
                            "value": predicate,
                            "page_id": page_id,
                            "page_title": title,
                        })

        # Check for contradictions
        for subject, properties in facts.items():
            for _prop, values in properties.items():
                if len(values) > 1:
                    # Check if definitions differ significantly
                    unique_values = set(v["value"] for v in values)
                    if len(unique_values) > 1:
                        issues.append({
                            "type": "contradiction",
                            "severity": "high",
                            "subject": subject,
                            "conflicting_claims": [
                                {
                                    "claim": v["value"],
                                    "from_page": v["page_title"],
                                }
                                for v in values
                            ],
                            "message": f"Contradictory definitions for '{subject}' across pages",
                        })

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking contradictions: {e}")
        return []


def _check_coverage_gaps(pages: list) -> list:
    """
    Check for under-explored topics.

    Identifies pages that are too short or lack sufficient detail.
    """
    try:
        if not pages:
            return []

        issues = []

        for page in pages:
            page_id = page.get("page_id", "")
            title = page.get("title", page_id)
            word_count = page.get("word_count", 0)
            content = page.get("content", "")

            # Check length thresholds
            if word_count < 50:
                issues.append({
                    "type": "coverage_gap",
                    "severity": "low",
                    "page_id": page_id,
                    "page_title": title,
                    "word_count": word_count,
                    "message": f"Stub page: '{title}' has only {word_count} words (consider expanding)",
                })
            elif word_count < 100:
                issues.append({
                    "type": "coverage_gap",
                    "severity": "low",
                    "page_id": page_id,
                    "page_title": title,
                    "word_count": word_count,
                    "message": f"Short page: '{title}' could be expanded with more context",
                })

            # Check for missing sections (intro, details, examples)
            has_examples = bool(re.search(r"\b(example|e\.g\.|for instance)\b", content, re.IGNORECASE))

            if not has_examples and word_count > 100:
                issues.append({
                    "type": "coverage_gap",
                    "severity": "low",
                    "page_id": page_id,
                    "page_title": title,
                    "message": f"Missing examples: '{title}' lacks concrete examples or use cases",
                })

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking coverage gaps: {e}")
        return []


def _check_staleness(pages: list) -> list:
    """
    Check for stale pages that haven't been updated recently.

    Pages updated >30 days ago are marked for review.
    """
    try:
        from datetime import datetime, timedelta

        if not pages:
            return []

        issues = []
        now = datetime.now(UTC)
        staleness_threshold = now - timedelta(days=30)

        for page in pages:
            page_id = page.get("page_id", "")
            title = page.get("title", page_id)
            last_updated_str = page.get("last_updated")

            if last_updated_str:
                try:
                    # Parse ISO timestamp
                    if isinstance(last_updated_str, str):
                        last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                    else:
                        last_updated = last_updated_str

                    if last_updated < staleness_threshold:
                        days_ago = (now - last_updated).days
                        issues.append({
                            "type": "staleness",
                            "severity": "low",
                            "page_id": page_id,
                            "page_title": title,
                            "last_updated": str(last_updated),
                            "days_since_update": days_ago,
                            "message": f"Stale page: '{title}' last updated {days_ago} days ago (consider reviewing)",
                        })
                except Exception:  # noqa: S110 — best-effort, non-fatal
                    pass

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking staleness: {e}")
        return []


def _generate_lint_suggestions(issues: list, pages: list) -> list:
    """
    Generate actionable suggestions from lint issues.

    Converts detected issues into concrete recommendations for improvement.
    """
    try:
        if not issues:
            return []

        suggestions = []
        issue_types = {}

        # Group issues by type
        for issue in issues:
            issue_type = issue.get("type", "unknown")
            if issue_type not in issue_types:
                issue_types[issue_type] = []
            issue_types[issue_type].append(issue)

        # Generate suggestions based on issue patterns

        # Broken links: suggest creating stubs
        if "broken_link" in issue_types:
            broken = issue_types["broken_link"]
            if len(broken) > 0:
                missing_pages = set(i.get("target", "") for i in broken)
                suggestions.append({
                    "type": "action",
                    "priority": "high",
                    "category": "broken_links",
                    "title": "Create stub pages for broken links",
                    "description": f"Found {len(broken)} broken links. Create stubs for: {', '.join(list(missing_pages)[:5])}",
                    "affected_count": len(broken),
                })

        # Orphaned pages: suggest deletion or linking
        if "orphaned_page" in issue_types:
            orphaned = issue_types["orphaned_page"]
            if len(orphaned) > 0:
                suggestions.append({
                    "type": "action",
                    "priority": "medium",
                    "category": "orphaned_pages",
                    "title": "Review orphaned pages",
                    "description": f"Found {len(orphaned)} orphaned pages with no inbound links. Consider merging or deleting.",
                    "affected_count": len(orphaned),
                    "page_ids": [i.get("page_id") for i in orphaned[:5]],
                })

        # Missing entities: suggest creating pages
        if "missing_entity" in issue_types:
            missing = issue_types["missing_entity"]
            if len(missing) > 0:
                top_missing = sorted(missing, key=lambda x: x.get("mention_count", 0), reverse=True)[:5]
                suggestions.append({
                    "type": "action",
                    "priority": "medium",
                    "category": "missing_entities",
                    "title": "Create pages for frequently mentioned concepts",
                    "description": f"Found {len(missing)} frequently mentioned concepts without dedicated pages",
                    "affected_count": len(missing),
                    "suggested_pages": [
                        f"{e.get('entity_name')} ({e.get('mention_count')} mentions)"
                        for e in top_missing
                    ],
                })

        # Coverage gaps: suggest expanding stubs
        if "coverage_gap" in issue_types:
            gaps = issue_types["coverage_gap"]
            if len(gaps) > 0:
                short_pages = [i for i in gaps if i.get("word_count", 0) < 100]
                suggestions.append({
                    "type": "action",
                    "priority": "low",
                    "category": "coverage_gaps",
                    "title": "Expand short pages",
                    "description": f"Found {len(short_pages)} pages under 100 words that could be expanded with more detail",
                    "affected_count": len(short_pages),
                })

        # Staleness: suggest reviewing old pages
        if "staleness" in issue_types:
            stale = issue_types["staleness"]
            if len(stale) > 0:
                very_old = [i for i in stale if i.get("days_since_update", 0) > 90]
                if very_old:
                    suggestions.append({
                        "type": "action",
                        "priority": "low",
                        "category": "staleness",
                        "title": "Review pages updated >90 days ago",
                        "description": f"Found {len(very_old)} pages that haven't been updated in >90 days",
                        "affected_count": len(very_old),
                    })

        # Contradictions: suggest harmonizing definitions
        if "contradiction" in issue_types:
            contradictions = issue_types["contradiction"]
            if len(contradictions) > 0:
                suggestions.append({
                    "type": "action",
                    "priority": "high",
                    "category": "contradictions",
                    "title": "Resolve contradictory definitions",
                    "description": f"Found {len(contradictions)} topics with conflicting definitions across pages. Standardize definitions.",
                    "affected_count": len(contradictions),
                })

        return suggestions

    except Exception as e:
        _LOG.warning(f"Error generating lint suggestions: {e}")
        return []


# ---------------------------------------------------------------------------
# Full QA evaluation
# ---------------------------------------------------------------------------

def _evaluate_wiki_qa(wiki_type: str, project_id: str | None) -> dict:
    """
    Complete Tier 3 QA evaluation of wiki health.

    Returns:
        {
            "passed": bool,
            "issues": [issue_dicts],
            "suggestions": [suggestion_dicts],
            "severity": "low" | "medium" | "high",
            "summary": {
                "broken_links": int,
                "orphaned_pages": int,
                "missing_entities": int,
                "contradictions": int,
                "coverage_gaps": int,
                "stale_pages": int,
                "total_issues": int,
            }
        }
    """
    try:
        issues = []
        pages = _get_all_wiki_pages(wiki_type, project_id)

        # Run all checks
        broken_links = _check_broken_links(wiki_type, project_id)
        orphaned_pages = _check_orphaned_pages(wiki_type, project_id)
        missing_entities = _check_missing_entities(wiki_type, project_id)
        contradictions = _check_contradictions(pages)
        coverage_gaps = _check_coverage_gaps(pages)
        staleness = _check_staleness(pages)

        issues.extend(broken_links)
        issues.extend(orphaned_pages)
        issues.extend(missing_entities)
        issues.extend(contradictions)
        issues.extend(coverage_gaps)
        issues.extend(staleness)

        # Separate issues by severity
        real_issues = [i for i in issues if i.get("severity") in ["medium", "high"]]
        minor_issues = [i for i in issues if i.get("severity") == "low"]

        # Generate actionable suggestions
        suggestions = _generate_lint_suggestions(issues, pages)

        # Determine severity
        if len(real_issues) > 10:
            severity = "high"
        elif len(real_issues) > 5:
            severity = "medium"
        else:
            severity = "low"

        _LOG.info(
            f"Wiki QA evaluation: {len(real_issues)} critical issues, "
            f"{len(minor_issues)} suggestions, {len(pages)} total pages"
        )

        return {
            "passed": len(real_issues) == 0,
            "issues": real_issues,
            "minor_issues": minor_issues,
            "suggestions": suggestions,
            "severity": severity,
            "summary": {
                "total_pages": len(pages),
                "broken_links": len(broken_links),
                "orphaned_pages": len(orphaned_pages),
                "missing_entities": len(missing_entities),
                "contradictions": len(contradictions),
                "coverage_gaps": len(coverage_gaps),
                "stale_pages": len(staleness),
                "total_issues": len(real_issues),
                "total_suggestions": len(suggestions),
            }
        }

    except Exception as e:
        _LOG.error(f"Error in wiki QA evaluation: {e}")
        return {
            "passed": False,
            "issues": [],
            "suggestions": [],
            "severity": "high",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Enhanced temporal tracking (Phase 1)
# ---------------------------------------------------------------------------

def _check_source_freshness(wiki_type: str, project_id: str | None) -> list:
    """
    Check if wiki pages are out of sync with their sources.

    Detects pages that haven't been updated despite source changes.
    Requires source tracking metadata in page frontmatter.
    """
    try:

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        issues = []

        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md", "maintenance.log"):
                continue

            page_id = md_file.stem
            content = md_file.read_text(encoding="utf-8")

            # Extract metadata
            title = page_id
            sources = []
            last_refreshed = None

            fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if fm_match:
                fm_text = fm_match.group(1)
                title_match = re.search(r"^title:\s*['\"]?([^'\"\\n]+)", fm_text, re.MULTILINE)
                if title_match:
                    title = title_match.group(1)

                # Extract sources and last_refreshed
                sources_match = re.findall(r"^sources:\s*\n((?:\s+-\s+.+\n)*)", fm_text, re.MULTILINE)
                last_refreshed_match = re.search(
                    r"^last_refreshed:\s*['\"]?([^'\"\\n]+)",
                    fm_text,
                    re.MULTILINE
                )

                if sources_match:
                    sources = sources_match[0].split("\n")
                    sources = [s.strip(" -") for s in sources if s.strip()]

                if last_refreshed_match:
                    last_refreshed = last_refreshed_match.group(1)

            # Check source freshness
            if sources and last_refreshed:
                try:
                    last_refreshed_dt = datetime.fromisoformat(
                        last_refreshed.replace("Z", "+00:00")
                    )
                    now = datetime.now(UTC)

                    # If page sources track metadata, check for changes
                    source_metadata_file = wiki_dir / ".meta" / f"{page_id}_sources.json"
                    if source_metadata_file.exists():
                        try:
                            source_data = json.loads(source_metadata_file.read_text())
                            if source_data.get("last_source_check"):
                                last_check = datetime.fromisoformat(
                                    source_data["last_source_check"].replace("Z", "+00:00")
                                )
                                days_since_check = (now - last_check).days

                                if days_since_check > 14:  # Check sources every 2 weeks
                                    issues.append({
                                        "type": "source_outdated",
                                        "severity": "low",
                                        "page_id": page_id,
                                        "page_title": title,
                                        "last_refreshed": str(last_refreshed_dt),
                                        "days_since_refresh": (now - last_refreshed_dt).days,
                                        "sources_count": len(sources),
                                        "message": f"Source freshness: {title} sources not checked in {days_since_check} days",
                                    })
                        except Exception:  # noqa: S110 — best-effort, non-fatal
                            pass

                except Exception:  # noqa: S110 — best-effort, non-fatal
                    pass

        return issues

    except Exception as e:
        _LOG.warning(f"Error checking source freshness: {e}")
        return []


def _get_temporal_metrics(wiki_type: str, project_id: str | None) -> dict:
    """
    Calculate temporal metrics for wiki health.

    Returns metrics about page age, update frequency, and staleness patterns.
    """
    try:

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {}

        now = datetime.now(UTC)
        metrics = {
            "total_pages": 0,
            "average_age_days": 0,
            "pages_updated_this_week": 0,
            "pages_updated_this_month": 0,
            "pages_updated_this_quarter": 0,
            "stale_pages_90d": 0,
            "very_stale_pages_180d": 0,
            "age_distribution": {
                "0_7_days": 0,
                "7_30_days": 0,
                "30_90_days": 0,
                "90_180_days": 0,
                "180plus_days": 0,
            },
        }

        ages = []

        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md", "maintenance.log"):
                continue

            metrics["total_pages"] += 1
            content = md_file.read_text(encoding="utf-8")

            # Extract last_updated
            last_updated = None
            updated_match = re.search(r"^last_updated:\s*['\"]?([^'\"\\n]+)", content, re.MULTILINE)
            if updated_match:
                try:
                    last_updated_str = updated_match.group(1)
                    last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                except Exception:  # noqa: S110 — best-effort, non-fatal
                    pass

            if last_updated:
                age_days = (now - last_updated).days
                ages.append(age_days)

                # Distribution
                if age_days <= 7:
                    metrics["pages_updated_this_week"] += 1
                    metrics["age_distribution"]["0_7_days"] += 1
                elif age_days <= 30:
                    metrics["pages_updated_this_month"] += 1
                    metrics["age_distribution"]["7_30_days"] += 1
                elif age_days <= 90:
                    metrics["pages_updated_this_quarter"] += 1
                    metrics["age_distribution"]["30_90_days"] += 1
                elif age_days <= 180:
                    metrics["stale_pages_90d"] += 1
                    metrics["age_distribution"]["90_180_days"] += 1
                else:
                    metrics["very_stale_pages_180d"] += 1
                    metrics["age_distribution"]["180plus_days"] += 1

        # Calculate average age
        if ages:
            metrics["average_age_days"] = round(sum(ages) / len(ages), 1)

        return metrics

    except Exception as e:
        _LOG.warning(f"Error calculating temporal metrics: {e}")
        return {}
