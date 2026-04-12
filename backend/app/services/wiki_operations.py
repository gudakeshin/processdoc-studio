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

    Checks for (Tier 3 QA):
    - Broken links (medium severity)
    - Orphaned pages (low severity)
    - Missing entities (low severity)

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (None for LP wiki)
        max_retries: Maximum retry attempts

    Returns:
        Tuple[result_dict, error_string]
        - On success: ({issues, suggestions, severity, summary}, None)
        - On failure: (None, error_message)
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.debug(f"Wiki lint attempt {attempt + 1}/{max_retries}")

            # Run Tier 3 QA evaluation
            qa_result = _evaluate_wiki_qa(wiki_type, project_id)

            # Log the lint operation
            _append_wiki_log(
                wiki_type, project_id, "lint",
                qa_results=json.dumps({
                    "passed": qa_result.get("passed", False),
                    "issues_count": len(qa_result.get("issues", [])),
                    "suggestions_count": len(qa_result.get("suggestions", [])),
                    "severity": qa_result.get("severity", "low"),
                    "summary": qa_result.get("summary", {}),
                })
            )

            result = {
                "issues": qa_result.get("issues", []),
                "suggestions": qa_result.get("suggestions", []),
                "severity": qa_result.get("severity", "low"),
                "issues_count": len(qa_result.get("issues", [])),
                "suggestions_count": len(qa_result.get("suggestions", [])),
                "summary": qa_result.get("summary", {}),
            }

            logger.info(f"Wiki lint success on attempt {attempt + 1} | found {result['issues_count']} issues")
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


def _save_persistent_graph(
    wiki_type: str,
    project_id: Optional[str],
) -> bool:
    """
    Save persistent graph.json for fast querying without re-extraction.

    Stores NetworkX adjacency format for quick loading.
    """
    try:
        import networkx as nx
        from networkx.readwrite import json_graph
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        G, page_titles = _load_wiki_graph(wiki_type, project_id)

        # Convert to JSON-serializable format
        graph_json = json_graph.node_link_data(G)

        # Save graph
        graph_file = wiki_dir / "graph.json"
        graph_file.write_text(json.dumps({
            "graph": graph_json,
            "page_titles": page_titles,
            "metadata": {
                "node_count": G.number_of_nodes(),
                "edge_count": G.number_of_edges(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        }, indent=2))

        logger.info(f"Saved persistent graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return True

    except Exception as e:
        logger.error(f"Error saving persistent graph: {e}")
        return False


def _load_persistent_graph(
    wiki_type: str,
    project_id: Optional[str],
) -> tuple:
    """
    Load persistent graph from graph.json for fast queries.

    Returns:
        (G, page_titles, metadata) or (None, {}, None) on error
    """
    try:
        from networkx.readwrite import json_graph
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        graph_file = wiki_dir / "graph.json"
        if not graph_file.exists():
            return None, {}, None

        graph_data = json.loads(graph_file.read_text())
        G = json_graph.node_link_graph(graph_data["graph"])
        page_titles = graph_data.get("page_titles", {})
        metadata = graph_data.get("metadata", {})

        return G, page_titles, metadata

    except Exception as e:
        logger.warning(f"Error loading persistent graph: {e}")
        return None, {}, None


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

        # Detect god nodes (most important pages)
        god_nodes_data = _detect_god_nodes(wiki_type, project_id)
        _save_god_nodes(wiki_type, project_id, god_nodes_data)
        logger.info(f"Detected {len(god_nodes_data['god_nodes'])} god nodes")

        # Save persistent graph for fast queries (Phase 2)
        _save_persistent_graph(wiki_type, project_id)

        avg_links = len(all_relationships) / max(len(pages), 1) if pages else 0

        return {
            "total_relationships": len(all_relationships),
            "pages_with_links": pages_with_links,
            "average_links_per_page": round(avg_links, 2),
            "total_communities": communities_data["total_communities"],
            "god_nodes_count": len(god_nodes_data["god_nodes"]),
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


def _detect_god_nodes(
    wiki_type: str,
    project_id: Optional[str],
) -> dict:
    """
    Detect 'god nodes' (most-important pages) using combined centrality metrics.

    God nodes are pages that:
    - Have many inbound links (widely referenced)
    - Bridge multiple communities (high betweenness centrality)
    - Act as hubs in the knowledge graph

    Importance score = 0.6 * normalized_inbound + 0.4 * betweenness_centrality

    Returns:
        {
            "god_nodes": [
                {
                    "page_id": str,
                    "page_title": str,
                    "importance_score": float (0.0-1.0),
                    "inbound_links": int,
                    "betweenness_centrality": float,
                    "rank": int (1-based)
                },
                ...
            ],
            "total_pages": int,
            "avg_importance": float
        }
    """
    try:
        import networkx as nx
        from app.services.storage import workspace_path
        import json
        import re

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {"god_nodes": [], "total_pages": 0, "avg_importance": 0.0}

        # Load relationships
        relationships_file = wiki_dir / "relationships.json"
        if not relationships_file.exists():
            return {"god_nodes": [], "total_pages": 0, "avg_importance": 0.0}

        rels_data = json.loads(relationships_file.read_text())
        relationships = rels_data.get("relationships", [])

        # Build undirected graph
        G = nx.Graph()

        # Add all pages as nodes
        page_titles = {}
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md", "relationships.json"):
                page_id = md_file.stem
                content = md_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id.replace("_", " ").title()
                G.add_node(page_id)
                page_titles[page_id] = title

        # Add edges from relationships
        for rel in relationships:
            source = rel["source_id"]
            target = rel["target_id"]
            weight = rel.get("confidence_score", 0.5)
            G.add_edge(source, target, weight=weight)

        if len(G.nodes()) == 0:
            return {"god_nodes": [], "total_pages": 0, "avg_importance": 0.0}

        # Calculate metrics
        # 1. Inbound link count (normalized)
        inbound_counts = {}
        for node in G.nodes():
            inbound_counts[node] = G.degree(node)

        max_inbound = max(inbound_counts.values()) if inbound_counts else 1
        normalized_inbound = {
            node: count / max_inbound for node, count in inbound_counts.items()
        }

        # 2. Betweenness centrality (already normalized 0-1)
        try:
            betweenness = nx.betweenness_centrality(G, weight="weight")
        except:
            betweenness = {node: 0.0 for node in G.nodes()}

        # 3. Combined importance score
        god_nodes_list = []
        importance_scores = {}

        for page_id in G.nodes():
            inbound_norm = normalized_inbound.get(page_id, 0.0)
            between = betweenness.get(page_id, 0.0)

            # Combined score: 60% inbound links, 40% betweenness
            importance = 0.6 * inbound_norm + 0.4 * between
            importance_scores[page_id] = importance

            god_nodes_list.append({
                "page_id": page_id,
                "page_title": page_titles.get(page_id, page_id),
                "importance_score": round(importance, 3),
                "inbound_links": inbound_counts[page_id],
                "betweenness_centrality": round(between, 3),
                "rank": 0,  # Will be assigned after sorting
            })

        # Sort by importance (descending)
        god_nodes_list.sort(key=lambda x: x["importance_score"], reverse=True)

        # Assign ranks
        for rank, node in enumerate(god_nodes_list, 1):
            node["rank"] = rank

        # Calculate average importance
        avg_importance = (
            sum(importance_scores.values()) / len(importance_scores)
            if importance_scores else 0.0
        )

        return {
            "god_nodes": god_nodes_list,
            "total_pages": len(G.nodes()),
            "avg_importance": round(avg_importance, 3),
        }

    except Exception as e:
        logger.error(f"Error detecting god nodes: {e}")
        return {"god_nodes": [], "total_pages": 0, "avg_importance": 0.0}


def _save_god_nodes(
    wiki_type: str,
    project_id: Optional[str],
    god_nodes_data: dict,
) -> bool:
    """Save god nodes (important pages) to god_nodes.json."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        god_nodes_file = wiki_dir / "god_nodes.json"

        god_nodes_file.write_text(json.dumps({
            "total_pages": god_nodes_data["total_pages"],
            "avg_importance": god_nodes_data["avg_importance"],
            "god_nodes": god_nodes_data["god_nodes"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        logger.error(f"Error saving god nodes: {e}")
        return False


def _load_wiki_graph(wiki_type: str, project_id: Optional[str]) -> tuple:
    """
    Load wiki relationship graph from relationships.json.

    Returns:
        (G, page_titles): NetworkX graph and mapping of page_id to page_title
    """
    try:
        import networkx as nx
        from app.services.storage import workspace_path
        import json
        import re

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        # Load relationships
        relationships_file = wiki_dir / "relationships.json"
        if not relationships_file.exists():
            return nx.Graph(), {}

        rels_data = json.loads(relationships_file.read_text())
        relationships = rels_data.get("relationships", [])

        # Build graph
        G = nx.Graph()
        page_titles = {}

        # Add all pages
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name not in ("index.md", "log.md", "relationships.json"):
                page_id = md_file.stem
                content = md_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id.replace("_", " ").title()
                G.add_node(page_id)
                page_titles[page_id] = title

        # Add edges
        for rel in relationships:
            source = rel["source_id"]
            target = rel["target_id"]
            weight = rel.get("confidence_score", 0.5)
            G.add_edge(source, target, weight=weight, confidence=rel["confidence"])

        return G, page_titles

    except Exception as e:
        logger.error(f"Error loading wiki graph: {e}")
        return nx.Graph(), {}


def _query_graph_bfs(
    G: Any,
    start_node: str,
    max_distance: int = 3,
    max_results: int = 20,
) -> list:
    """
    Breadth-first search from a starting node.

    Returns list of (node, distance, path) tuples.
    """
    try:
        import networkx as nx

        results = []
        visited = set()
        queue = [(start_node, 0, [start_node])]

        while queue and len(results) < max_results:
            current, distance, path = queue.pop(0)

            if current in visited:
                continue
            visited.add(current)

            if distance > 0:  # Don't include start node
                results.append({
                    "node_id": current,
                    "distance": distance,
                    "path": path,
                })

            if distance < max_distance:
                for neighbor in G.neighbors(current):
                    if neighbor not in visited:
                        queue.append((neighbor, distance + 1, path + [neighbor]))

        return results

    except Exception as e:
        logger.warning(f"Error in BFS: {e}")
        return []


def _query_graph_shortest_path(
    G: Any,
    start_node: str,
    end_node: str,
) -> Optional[dict]:
    """
    Find shortest path between two nodes.
    """
    try:
        import networkx as nx

        if start_node not in G or end_node not in G:
            return None

        try:
            path = nx.shortest_path(G, start_node, end_node, weight="weight")
            return {
                "start": start_node,
                "end": end_node,
                "path": path,
                "distance": len(path) - 1,
                "hop_count": len(path) - 1,
            }
        except nx.NetworkXNoPath:
            return None

    except Exception as e:
        logger.warning(f"Error finding shortest path: {e}")
        return None


def _query_graph_neighbors(
    G: Any,
    node_id: str,
) -> list:
    """
    Get immediate neighbors of a node.
    """
    try:
        results = []
        if node_id in G:
            for neighbor in G.neighbors(node_id):
                edge_data = G.get_edge_data(node_id, neighbor)
                results.append({
                    "node_id": neighbor,
                    "distance": 1,
                    "weight": edge_data.get("weight", 0.5) if edge_data else 0.5,
                    "confidence": edge_data.get("confidence", "INFERRED") if edge_data else "INFERRED",
                })
        return results
    except Exception as e:
        logger.warning(f"Error getting neighbors: {e}")
        return []


def _execute_graph_query(
    wiki_type: str,
    project_id: Optional[str],
    query: str,
    query_type: str = "neighbors",
    start_node: Optional[str] = None,
    end_node: Optional[str] = None,
    max_distance: int = 3,
    max_results: int = 20,
) -> dict:
    """
    Execute a graph query (traversal) on the wiki relationship graph.

    Query types:
    - neighbors: Get direct connections to a page
    - bfs: Breadth-first search from a page
    - shortest_path: Find shortest path between two pages
    - related: Find pages related by name (legacy keyword search)

    Returns:
        {
            "query": str,
            "query_type": str,
            "start_node": str (optional),
            "results": [
                {
                    "node_id": str,
                    "distance": int,
                    "path": [str] (optional),
                    "weight": float (optional)
                },
                ...
            ],
            "total_results": int,
            "truncated": bool,
            "reason": str (optional)
        }
    """
    try:
        G, page_titles = _load_wiki_graph(wiki_type, project_id)

        if not G.nodes():
            return {
                "query": query,
                "query_type": query_type,
                "results": [],
                "total_results": 0,
                "truncated": False,
            }

        results = []

        if query_type == "neighbors" and start_node:
            results = _query_graph_neighbors(G, start_node)

        elif query_type == "bfs" and start_node:
            results = _query_graph_bfs(G, start_node, max_distance, max_results)

        elif query_type == "shortest_path" and start_node and end_node:
            path_result = _query_graph_shortest_path(G, start_node, end_node)
            if path_result:
                results = [path_result]

        elif query_type == "related" and start_node:
            # Find pages with similar names or high similarity
            results = _query_graph_neighbors(G, start_node)
            # Add pages with similar titles (optional semantic similarity)

        return {
            "query": query,
            "query_type": query_type,
            "start_node": start_node,
            "end_node": end_node if query_type == "shortest_path" else None,
            "results": results[:max_results],
            "total_results": len(results),
            "truncated": len(results) > max_results,
            "reason": "max_results limit exceeded" if len(results) > max_results else None,
        }

    except Exception as e:
        logger.error(f"Error executing graph query: {e}")
        return {
            "query": query,
            "query_type": query_type,
            "results": [],
            "total_results": 0,
            "truncated": False,
            "error": str(e),
        }


def _get_god_nodes(wiki_type: str, project_id: Optional[str], limit: int = 10) -> list:
    """Get top N god nodes (most important pages)."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        god_nodes_file = wiki_dir / "god_nodes.json"
        if not god_nodes_file.exists():
            return []

        god_nodes_data = json.loads(god_nodes_file.read_text())
        return god_nodes_data.get("god_nodes", [])[:limit]
    except Exception as e:
        logger.warning(f"Error loading god nodes: {e}")
        return []


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


def _check_broken_links(wiki_type: str, project_id: Optional[str]) -> list:
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
        logger.warning(f"Error checking broken links: {e}")
        return []


def _check_orphaned_pages(wiki_type: str, project_id: Optional[str]) -> list:
    """
    Find orphaned pages (no inbound links).

    Pages with zero inbound links may need to be merged or deleted.
    """
    try:
        from app.services.storage import workspace_path
        import re
        import json

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return []

        # Load relationship counts
        rel_counts = _get_relationship_counts(wiki_type, project_id)
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
        logger.warning(f"Error checking orphaned pages: {e}")
        return []


def _check_missing_entities(wiki_type: str, project_id: Optional[str]) -> list:
    """
    Find missing entities: concepts mentioned 5+ times without dedicated page.

    Suggests creating pages for frequently-mentioned concepts.
    """
    try:
        import re
        from app.services.storage import workspace_path
        from collections import Counter

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
        logger.warning(f"Error checking missing entities: {e}")
        return []


def _evaluate_wiki_qa(wiki_type: str, project_id: Optional[str]) -> dict:
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
            }
        }
    """
    try:
        issues = []

        # Run all checks
        broken_links = _check_broken_links(wiki_type, project_id)
        orphaned_pages = _check_orphaned_pages(wiki_type, project_id)
        missing_entities = _check_missing_entities(wiki_type, project_id)

        issues.extend(broken_links)
        issues.extend(orphaned_pages)
        issues.extend(missing_entities)

        # Separate issues and suggestions
        real_issues = [i for i in issues if i.get("severity") in ["medium", "high"]]
        suggestions = [i for i in issues if i.get("severity") == "low"]

        # Determine severity
        if len(real_issues) > 10:
            severity = "high"
        elif len(real_issues) > 5:
            severity = "medium"
        else:
            severity = "low"

        return {
            "passed": len(real_issues) == 0,
            "issues": real_issues,
            "suggestions": suggestions,
            "severity": severity,
            "summary": {
                "broken_links": len(broken_links),
                "orphaned_pages": len(orphaned_pages),
                "missing_entities": len(missing_entities),
                "total_issues": len(real_issues),
            }
        }

    except Exception as e:
        logger.error(f"Error in wiki QA evaluation: {e}")
        return {
            "passed": False,
            "issues": [],
            "suggestions": [],
            "severity": "high",
            "error": str(e),
        }


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
