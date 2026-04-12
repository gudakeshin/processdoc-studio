"""
Wiki operations with Cowork Tier 1 retry logic.

Handles ingest, query, and lint operations with automatic retry on transient failures.
Uses exponential backoff formula: min(1.5, 0.25 * 2^attempt)
"""

import time
import json
import logging
from typing import Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Tier 1 retry constants
MAX_RETRY_ATTEMPTS = 3
BASE_RETRY_DELAY = 0.25  # seconds


def exponential_backoff(attempt: int) -> float:
    """
    Calculate exponential backoff delay using Cowork pattern: min(1.5, 0.25 * 2^attempt)

    Args:
        attempt: Zero-indexed attempt number (0, 1, 2, ...)

    Returns:
        Delay in seconds (never exceeds 1.5s)

    Examples:
        exponential_backoff(0) -> 0.25
        exponential_backoff(1) -> 0.5
        exponential_backoff(2) -> 1.0
        exponential_backoff(3) -> 1.5 (capped)
        exponential_backoff(10) -> 1.5 (capped)
    """
    return min(1.5, BASE_RETRY_DELAY * (2 ** attempt))


class TransientError(Exception):
    """Errors that should trigger a retry."""
    pass


class NonTransientError(Exception):
    """Errors that should fail immediately without retry."""
    pass


def classify_error(error: Exception) -> str:
    """
    Classify an error as transient or non-transient.

    Transient errors (safe to retry):
    - TimeoutError, ConnectionError, ConnectionResetError
    - ServiceUnavailable (5xx), RateLimitError
    - Generic Exception (unknown)

    Non-transient errors (fail immediately):
    - ValueError, ValidationError (validation failures)
    - KeyError, AttributeError (programming errors)
    - FileNotFoundError (missing resource)
    - TypeError, SchemaError (data structure mismatch)

    Args:
        error: The exception to classify

    Returns:
        "transient" or "non_transient"
    """
    transient_types = (
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        BrokenPipeError,
        EOFError,
    )

    non_transient_types = (
        ValueError,
        KeyError,
        FileNotFoundError,
        TypeError,
        AttributeError,
        AssertionError,
    )

    # Check by type
    if isinstance(error, transient_types):
        return "transient"
    if isinstance(error, non_transient_types):
        return "non_transient"

    # Check by error message/name
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    if any(x in error_str or x in error_type for x in [
        "timeout", "unavailable", "ratelimit", "rate_limit",
        "connection", "reset", "broken", "eof"
    ]):
        return "transient"

    if any(x in error_str or x in error_type for x in [
        "validation", "schema", "invalid", "mismatch"
    ]):
        return "non_transient"

    # Default to transient (fail safely by retrying)
    return "transient"


def wiki_ingest_with_retry(
    source_type: str,
    source_data: dict,
    wiki_type: str = "project",
    project_id: Optional[str] = None,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Ingest a source into the wiki with automatic retry on transient failures.

    Workflow:
    1. Parse source
    2. Extract key takeaways
    3. Create/update wiki pages
    4. Update index
    5. Append to log

    Args:
        source_type: Type of source ("url", "document", "run_artifact", "conversation")
        source_data: Data dict with source information
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (None for LP wiki)
        max_retries: Maximum retry attempts

    Returns:
        Tuple[result_dict, error_string]
        - On success: ({pages_created, pages_updated, corrections_made, log_entry_id}, None)
        - On failure: (None, error_message)

    Transient errors trigger retry with exponential backoff.
    Non-transient errors fail immediately.
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.debug(f"Wiki ingest attempt {attempt + 1}/{max_retries} | source={source_type}")

            # Parse and extract
            extracted = _parse_source(source_type, source_data)
            if not extracted:
                return None, f"Failed to extract content from {source_type} source"

            # Create/update wiki pages
            pages_result = _update_wiki_pages(
                extracted, wiki_type, project_id
            )

            # Update index
            index_result = _update_wiki_index(wiki_type, project_id)

            # Log the operation
            log_entry_id = _append_wiki_log(
                wiki_type, project_id, "ingest",
                source_name=extracted.get("title", source_type),
                pages_touched=pages_result.get("page_ids", []),
                corrections_made=pages_result.get("corrections", []),
            )

            result = {
                "pages_created": pages_result.get("created", 0),
                "pages_updated": pages_result.get("updated", 0),
                "corrections_made": len(pages_result.get("corrections", [])),
                "log_entry_id": log_entry_id,
            }

            logger.info(f"Wiki ingest success on attempt {attempt + 1} | {result}")
            return result, None

        except Exception as e:
            error_class = classify_error(e)
            last_error = str(e)

            if error_class == "non_transient":
                logger.error(f"Wiki ingest non-transient error: {e}")
                return None, last_error

            # Transient error: retry if not last attempt
            if attempt < max_retries - 1:
                delay = exponential_backoff(attempt)
                logger.warning(
                    f"Wiki ingest transient error (attempt {attempt + 1}): {e} | "
                    f"retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"Wiki ingest failed after {max_retries} attempts: {e}"
                )
                return None, last_error

    return None, last_error


def wiki_query_with_retry(
    question: str,
    wiki_type: str = "project",
    project_id: Optional[str] = None,
    include_qa: bool = False,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Query the wiki with automatic retry on transient failures.

    Workflow:
    1. Search wiki index
    2. Retrieve relevant pages
    3. Synthesize answer
    4. (Optional) Run QA evaluation

    Args:
        question: The question to ask
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (None for LP wiki)
        include_qa: Whether to run optional QA evaluation
        max_retries: Maximum retry attempts

    Returns:
        Tuple[result_dict, error_string]
        - On success: ({answer, citations, source_pages, qa_result?}, None)
        - On failure: (None, error_message)
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.debug(f"Wiki query attempt {attempt + 1}/{max_retries} | question={question[:50]}")

            # Search index
            index = _get_wiki_index(wiki_type, project_id)
            if not index:
                return None, f"Wiki index not found for {wiki_type}/{project_id}"

            # Retrieve relevant pages
            pages = _search_wiki_pages(question, index, wiki_type, project_id)
            if not pages:
                return None, "No relevant pages found in wiki"

            # Synthesize answer
            answer = _synthesize_answer(question, pages)

            # (Optional) Run QA
            qa_result = None
            if include_qa:
                qa_result = _evaluate_answer_quality(answer, pages, question)

            result = {
                "answer": answer,
                "citations": _extract_citations(pages),
                "source_pages": [p["id"] for p in pages],
                "qa_result": qa_result,
            }

            logger.info(f"Wiki query success on attempt {attempt + 1}")
            return result, None

        except Exception as e:
            error_class = classify_error(e)
            last_error = str(e)

            if error_class == "non_transient":
                logger.error(f"Wiki query non-transient error: {e}")
                return None, last_error

            # Transient error: retry if not last attempt
            if attempt < max_retries - 1:
                delay = exponential_backoff(attempt)
                logger.warning(
                    f"Wiki query transient error (attempt {attempt + 1}): {e} | "
                    f"retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"Wiki query failed after {max_retries} attempts: {e}")
                return None, last_error

    return None, last_error


def wiki_lint_with_retry(
    wiki_type: str = "project",
    project_id: Optional[str] = None,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Run wiki health check (lint) with automatic retry on transient failures.

    Checks for:
    - Contradictions
    - Orphaned pages
    - Missing cross-references
    - Broken links
    - Coverage gaps
    - Staleness

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (None for LP wiki)
        max_retries: Maximum retry attempts

    Returns:
        Tuple[result_dict, error_string]
        - On success: ({issues, suggestions, severity}, None)
        - On failure: (None, error_message)
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.debug(f"Wiki lint attempt {attempt + 1}/{max_retries}")

            # Run health checks
            all_pages = _get_all_wiki_pages(wiki_type, project_id)
            if not all_pages:
                return {"issues": [], "suggestions": [], "severity": "low"}, None

            # Check for issues
            issues = []
            issues.extend(_check_contradictions(all_pages))
            issues.extend(_check_orphans(all_pages))
            issues.extend(_check_broken_links(all_pages))
            issues.extend(_check_coverage_gaps(all_pages))
            issues.extend(_check_staleness(all_pages))

            # Generate suggestions
            suggestions = _generate_lint_suggestions(issues, all_pages)

            # Calculate severity
            severity = "low" if len(issues) < 5 else "medium" if len(issues) < 10 else "high"

            # Log the lint operation
            _append_wiki_log(
                wiki_type, project_id, "lint",
                qa_results=json.dumps({
                    "passed": len(issues) == 0,
                    "issues_count": len(issues),
                    "suggestions_count": len(suggestions),
                    "severity": severity,
                })
            )

            result = {
                "issues": issues,
                "suggestions": suggestions,
                "severity": severity,
                "issues_count": len(issues),
            }

            logger.info(f"Wiki lint success on attempt {attempt + 1} | found {len(issues)} issues")
            return result, None

        except Exception as e:
            error_class = classify_error(e)
            last_error = str(e)

            if error_class == "non_transient":
                logger.error(f"Wiki lint non-transient error: {e}")
                return None, last_error

            # Transient error: retry if not last attempt
            if attempt < max_retries - 1:
                delay = exponential_backoff(attempt)
                logger.warning(
                    f"Wiki lint transient error (attempt {attempt + 1}): {e} | "
                    f"retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"Wiki lint failed after {max_retries} attempts: {e}")
                return None, last_error

    return None, last_error


# ===== Helper Functions (Stubs for Phase 2+) =====

def _parse_source(source_type: str, source_data: dict) -> Optional[dict]:
    """Parse source and extract key information."""
    try:
        if source_type == "document":
            # For documents, filename is in source_data
            filename = source_data.get("filename", "")
            project_id = source_data.get("project_id", "")

            if not filename or not project_id:
                logger.warning(f"Document ingest missing filename or project_id: {source_data}")
                return None

            from app.services.storage import workspace_path
            import hashlib

            source_file = workspace_path(project_id) / "source_docs" / filename

            # Try to read the source file directly as fallback
            if source_file.exists():
                try:
                    content = source_file.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()

                    # First try to get parsed document
                    parsed_docs_dir = workspace_path(project_id) / "parsed_docs"
                    if parsed_docs_dir.exists():
                        parsed_file = parsed_docs_dir / f"{digest}.json"
                        if parsed_file.exists():
                            try:
                                parsed_data = json.loads(parsed_file.read_text())
                                logger.debug(f"Using parsed document for {filename}")
                                return {
                                    "title": filename,
                                    "content": parsed_data.get("text", ""),
                                    "source_url": f"document://{project_id}/{filename}",
                                    "chunk_count": parsed_data.get("chunk_count", 0),
                                    "entities": [],
                                    "concepts": [],
                                }
                            except json.JSONDecodeError as je:
                                logger.warning(f"Failed to parse JSON for {filename}: {je}")

                    # Fallback: extract text directly from source file
                    logger.debug(f"Using fallback text extraction for {filename}")
                    text = _extract_text_from_file(filename, content)
                    return {
                        "title": filename,
                        "content": text,
                        "source_url": f"document://{project_id}/{filename}",
                        "chunk_count": max(1, len(text) // 1200),  # Estimate chunks
                        "entities": [],
                        "concepts": [],
                    }
                except Exception as read_err:
                    logger.error(f"Error reading source file {filename}: {read_err}")
                    return None
            else:
                logger.warning(f"Source file not found: {source_file}")
                return None

        # For other source types, return basic extracted content
        return {
            "title": source_data.get("title", "Untitled"),
            "content": source_data.get("content", ""),
            "source_url": source_data.get("url", ""),
            "entities": [],
            "concepts": [],
        }
    except Exception as e:
        logger.error(f"Error parsing source: {e}")
        return None


def _extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract text from file bytes (simple fallback)."""
    try:
        lower = (filename or "").lower()

        # Try UTF-8 first
        if lower.endswith((".txt", ".md", ".csv", ".json")):
            return content.decode("utf-8", errors="ignore")

        # For binary formats, at least try to decode
        return content.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"Failed to extract text from {filename}: {e}")
        return f"[Unable to extract text from {filename}]"


def _update_wiki_pages(extracted: dict, wiki_type: str, project_id: Optional[str]) -> dict:
    """Create/update wiki pages from extracted content and rebuild relationships."""
    try:
        if not extracted or not extracted.get("content"):
            return {"created": 0, "updated": 0, "page_ids": [], "corrections": []}

        from app.services.storage import workspace_path

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)

        # Create a document page
        page_title = extracted.get("title", "Document")
        page_id = page_title.lower().replace(" ", "_").replace(".", "")[:50]

        # Create frontmatter
        frontmatter = {
            "title": page_title,
            "category": "artifact",
            "confidence": "medium",
            "source_count": 1,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Format content with frontmatter
        content_text = "---\n"
        for key, value in frontmatter.items():
            if isinstance(value, str):
                content_text += f'{key}: "{value}"\n'
            else:
                content_text += f"{key}: {value}\n"
        content_text += "---\n\n"
        content_text += f"# {page_title}\n\n"

        # Add first 500 chars of content
        preview = extracted.get("content", "")[:500]
        content_text += preview + "\n\n"
        content_text += f"[{extracted.get('chunk_count', 0)} chunks from source]\n"

        # Save page
        page_file = wiki_dir / f"{page_id}.md"
        page_file.write_text(content_text)

        # Rebuild relationships for all pages after adding new page
        rel_result = _build_and_persist_relationships(wiki_type, project_id)
        logger.info(f"Rebuilt relationships: {rel_result}")

        return {
            "created": 1,
            "updated": 0,
            "page_ids": [page_id],
            "corrections": [],
        }
    except Exception as e:
        logger.error(f"Error updating wiki pages: {e}")
        return {"created": 0, "updated": 0, "page_ids": [], "corrections": []}


def _update_wiki_index(wiki_type: str, project_id: Optional[str]) -> dict:
    """Regenerate wiki index from all pages."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {"page_count": 0}

        # Count markdown files
        md_files = list(wiki_dir.glob("*.md"))
        page_count = len([f for f in md_files if f.name != "index.md" and f.name != "log.md"])

        # Create basic index
        index_content = f"# Wiki Index\n\n{page_count} pages\n"
        index_file = wiki_dir / "index.md"
        index_file.write_text(index_content)

        return {"page_count": page_count}
    except Exception as e:
        logger.error(f"Error updating wiki index: {e}")
        return {"page_count": 0}


def _append_wiki_log(
    wiki_type: str,
    project_id: Optional[str],
    operation: str,
    source_name: Optional[str] = None,
    pages_touched: Optional[list] = None,
    corrections_made: Optional[list] = None,
    qa_results: Optional[str] = None,
) -> str:
    """Append operation to wiki log."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        log_file = wiki_dir / "log.md"

        # Create log entry
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"\n## {timestamp}\n"
        entry += f"**Operation:** {operation}\n"
        if source_name:
            entry += f"**Source:** {source_name}\n"
        if pages_touched:
            entry += f"**Pages:** {', '.join(pages_touched)}\n"

        # Append to log
        if log_file.exists():
            log_content = log_file.read_text()
            log_file.write_text(log_content + entry)
        else:
            log_file.write_text("# Wiki Log\n" + entry)

        log_entry_id = f"log_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        return log_entry_id
    except Exception as e:
        logger.error(f"Error appending to wiki log: {e}")
        return f"log_{int(datetime.now(timezone.utc).timestamp())}"


def _extract_relationships(
    source_page_id: str,
    content: str,
    all_page_ids: list[str],
    all_page_titles: list[str],
) -> list[dict]:
    """
    Extract explicit and inferred relationships from page content.

    Explicit: [[Page Name]] links
    Inferred: Page title mentions in content

    Args:
        source_page_id: ID of the page being analyzed
        content: Page content (markdown)
        all_page_ids: All available page IDs for reference
        all_page_titles: All available page titles for mention detection

    Returns:
        List of relationship dicts with structure:
        {
            "source_id": str,
            "target_id": str,
            "relation_type": "references" | "mentions",
            "confidence": "EXPLICIT" | "INFERRED",
            "confidence_score": float,
            "source_location": str (e.g., "L42"),
            "created_at": ISO timestamp
        }
    """
    import re
    relationships = []

    try:
        # Extract explicit links: [[Page Name]]
        explicit_pattern = r"\[\[([^\]]+)\]\]"
        for match in re.finditer(explicit_pattern, content):
            target_name = match.group(1).strip()
            # Try to match with available pages
            target_id = target_name.lower().replace(" ", "_").replace(".", "")[:50]

            # Only add if target exists
            if target_id in all_page_ids or any(t.lower() == target_name.lower() for t in all_page_titles):
                relationships.append({
                    "source_id": source_page_id,
                    "target_id": target_id,
                    "relation_type": "references",
                    "confidence": "EXPLICIT",
                    "confidence_score": 1.0,
                    "source_location": f"L{content[:match.start()].count(chr(10)) + 1}",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

        # Extract inferred links: page title mentions
        for idx, title in enumerate(all_page_titles):
            if title.lower() == all_page_titles[all_page_ids.index(source_page_id)].lower():
                # Skip self-references
                continue

            # Count mentions (case-insensitive, word boundary)
            pattern = r"\b" + re.escape(title) + r"\b"
            matches = list(re.finditer(pattern, content, re.IGNORECASE))

            if len(matches) >= 2:  # Require at least 2 mentions for inferred
                target_id = all_page_ids[idx]
                # Skip if already explicit
                if not any(r["target_id"] == target_id for r in relationships):
                    confidence_score = min(0.95, 0.5 + (len(matches) * 0.1))  # 0.5-0.95
                    relationships.append({
                        "source_id": source_page_id,
                        "target_id": target_id,
                        "relation_type": "mentions",
                        "confidence": "INFERRED",
                        "confidence_score": confidence_score,
                        "source_location": f"L{content[:matches[0].start()].count(chr(10)) + 1}",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
    except Exception as e:
        logger.warning(f"Error extracting relationships from {source_page_id}: {e}")

    return relationships


def _build_and_persist_relationships(
    wiki_type: str,
    project_id: Optional[str],
) -> dict:
    """
    Build complete relationship graph from all wiki pages and persist to relationships.json.

    Returns:
        {
            "total_relationships": int,
            "pages_with_links": int,
            "average_links_per_page": float
        }
    """
    try:
        from app.services.storage import workspace_path
        from pathlib import Path
        import re

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {"total_relationships": 0, "pages_with_links": 0, "average_links_per_page": 0}

        # Collect all pages
        pages = {}
        page_ids = []
        page_titles = []

        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md", "relationships.json"):
                continue

            page_id = md_file.stem
            content = md_file.read_text(encoding="utf-8")

            # Extract title from frontmatter
            title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
            title = title_match.group(1) if title_match else page_id.replace("_", " ").title()

            pages[page_id] = {
                "title": title,
                "file": md_file,
                "content": content
            }
            page_ids.append(page_id)
            page_titles.append(title)

        # Extract relationships for each page
        all_relationships = []
        pages_with_links = 0

        for page_id, page_data in pages.items():
            relationships = _extract_relationships(
                page_id,
                page_data["content"],
                page_ids,
                page_titles
            )
            all_relationships.extend(relationships)
            if relationships:
                pages_with_links += 1

        # Persist to relationships.json
        relationships_file = wiki_dir / "relationships.json"
        relationships_file.write_text(json.dumps({
            "total": len(all_relationships),
            "relationships": all_relationships,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        # Detect communities from the relationship graph
        communities_data = _detect_communities(wiki_type, project_id)
        _save_communities(wiki_type, project_id, communities_data)
        logger.info(f"Detected {communities_data['total_communities']} communities")

        avg_links = len(all_relationships) / max(len(pages), 1) if pages else 0

        return {
            "total_relationships": len(all_relationships),
            "pages_with_links": pages_with_links,
            "average_links_per_page": round(avg_links, 2),
            "total_communities": communities_data["total_communities"],
        }
    except Exception as e:
        logger.error(f"Error building relationships: {e}")
        return {"total_relationships": 0, "pages_with_links": 0, "average_links_per_page": 0}


def _detect_communities(
    wiki_type: str,
    project_id: Optional[str],
) -> dict:
    """
    Detect communities (functional clusters) from wiki relationship graph using Louvain algorithm.

    Louvain algorithm optimizes modularity to find natural clustering.
    Returns stable, meaningful communities based on edge density.

    Returns:
        {
            "total_communities": int,
            "communities": {
                community_id: {
                    "page_ids": [page_id, ...],
                    "top_concepts": [page_title, ...],
                    "size": int,
                    "density": float (0.0-1.0)
                }
            },
            "page_community_map": {page_id: community_id, ...}
        }
    """
    try:
        import networkx as nx
        from networkx.algorithms import community
        from app.services.storage import workspace_path
        import json

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {
                "total_communities": 0,
                "communities": {},
                "page_community_map": {},
            }

        # Load relationships
        relationships_file = wiki_dir / "relationships.json"
        if not relationships_file.exists():
            return {
                "total_communities": 0,
                "communities": {},
                "page_community_map": {},
            }

        rels_data = json.loads(relationships_file.read_text())
        relationships = rels_data.get("relationships", [])

        # Build undirected graph (treat relationships as edges)
        G = nx.Graph()

        # Add nodes (all pages)
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md", "relationships.json"):
                G.add_node(md_file.stem)

        # Add edges from relationships
        for rel in relationships:
            source = rel["source_id"]
            target = rel["target_id"]
            weight = rel.get("confidence_score", 0.5)
            G.add_edge(source, target, weight=weight)

        # Detect communities using Louvain algorithm (modularity optimization)
        communities_list = list(community.louvain_communities(G, seed=42))

        # Build communities dict
        communities = {}
        page_community_map = {}
        page_titles = {}

        # First pass: load all page titles
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md", "relationships.json"):
                page_id = md_file.stem
                content = md_file.read_text(encoding="utf-8")
                import re
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id.replace("_", " ").title()
                page_titles[page_id] = title

        # Build community details
        for community_id, nodes in enumerate(communities_list):
            page_ids = list(nodes)
            subgraph = G.subgraph(page_ids)

            # Calculate community density
            num_edges = subgraph.number_of_edges()
            num_possible_edges = len(page_ids) * (len(page_ids) - 1) / 2
            density = num_edges / num_possible_edges if num_possible_edges > 0 else 0

            # Get top concepts (by degree centrality within community)
            if page_ids:
                degree_centrality = nx.degree_centrality(subgraph)
                top_pages = sorted(
                    degree_centrality.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]
                top_concepts = [page_titles.get(pid, pid) for pid, _ in top_pages]
            else:
                top_concepts = []

            communities[str(community_id)] = {
                "page_ids": page_ids,
                "top_concepts": top_concepts,
                "size": len(page_ids),
                "density": round(density, 3),
            }

            # Map pages to communities
            for page_id in page_ids:
                page_community_map[page_id] = community_id

        return {
            "total_communities": len(communities),
            "communities": communities,
            "page_community_map": page_community_map,
        }

    except Exception as e:
        logger.error(f"Error detecting communities: {e}")
        return {
            "total_communities": 0,
            "communities": {},
            "page_community_map": {},
        }


def _save_communities(
    wiki_type: str,
    project_id: Optional[str],
    communities_data: dict,
) -> bool:
    """Save community assignments to communities.json."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        communities_file = wiki_dir / "communities.json"

        communities_file.write_text(json.dumps({
            "total_communities": communities_data["total_communities"],
            "communities": communities_data["communities"],
            "page_community_map": communities_data["page_community_map"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        logger.error(f"Error saving communities: {e}")
        return False


def _get_community_for_page(wiki_type: str, project_id: Optional[str], page_id: str) -> Optional[dict]:
    """Get community information for a specific page."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        communities_file = wiki_dir / "communities.json"
        if not communities_file.exists():
            return None

        communities_data = json.loads(communities_file.read_text())
        community_id = communities_data["page_community_map"].get(page_id)

        if community_id is None:
            return None

        return {
            "community_id": community_id,
            **communities_data["communities"][str(community_id)],
        }
    except Exception as e:
        logger.warning(f"Error loading community for page {page_id}: {e}")
        return None


def _get_relationship_counts(wiki_type: str, project_id: Optional[str]) -> dict:
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
        logger.warning(f"Error loading relationship counts: {e}")
        return {}


def _get_wiki_index(wiki_type: str, project_id: Optional[str]) -> Optional[dict]:
    """Get current wiki index. (To be implemented in Phase 2)"""
    # Stub
    return {"pages": []}


def _search_wiki_pages(question: str, index: dict, wiki_type: str, project_id: Optional[str]) -> list:
    """Search wiki pages by relevance. (To be implemented in Phase 2)"""
    # Stub
    return []


def _synthesize_answer(question: str, pages: list) -> str:
    """Synthesize answer from pages. (To be implemented in Phase 2)"""
    # Stub
    return f"Answer to '{question}' (not yet implemented)"


def _extract_citations(pages: list) -> list:
    """Extract citations from pages. (To be implemented in Phase 2)"""
    # Stub
    return []


def _evaluate_answer_quality(answer: str, pages: list, question: str) -> Optional[dict]:
    """Evaluate answer quality. (To be implemented in Phase 3)"""
    # Stub
    return None


def _get_all_wiki_pages(wiki_type: str, project_id: Optional[str]) -> list:
    """Get all wiki pages. (To be implemented in Phase 3)"""
    # Stub
    return []


def _check_contradictions(pages: list) -> list:
    """Check for contradictory claims. (To be implemented in Phase 3)"""
    # Stub
    return []


def _check_orphans(pages: list) -> list:
    """Check for orphaned pages. (To be implemented in Phase 3)"""
    # Stub
    return []


def _check_broken_links(pages: list) -> list:
    """Check for broken references. (To be implemented in Phase 3)"""
    # Stub
    return []


def _check_coverage_gaps(pages: list) -> list:
    """Check for under-explored topics. (To be implemented in Phase 3)"""
    # Stub
    return []


def _check_staleness(pages: list) -> list:
    """Check for stale pages. (To be implemented in Phase 3)"""
    # Stub
    return []


def _generate_lint_suggestions(issues: list, pages: list) -> list:
    """Generate suggestions from lint issues. (To be implemented in Phase 3)"""
    # Stub
    return []
