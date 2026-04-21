"""
Wiki operations with Cowork Tier 1 retry logic.

Handles ingest, query, and lint operations with automatic retry on transient failures.
Uses exponential backoff formula: min(1.5, 0.25 * 2^attempt)
"""

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.services.wiki_ingest import _migrate_meta_directory, _parse_source

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


def search_wiki(
    query: str,
    *,
    project_id: str | None = None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """BM25 search over project wiki pages.

    Reuses TieredContextEngine (which has its own mtime cache) so repeated
    calls within a session are cheap.  Returns results ordered by relevance.

    Return format mirrors web_search / search_leading_practices:
        [{"id": str, "title": str, "snippet": str, "score": float}, ...]
    """
    try:
        from app.services.retrieval import TieredContextEngine

        engine = TieredContextEngine()
        chunks = engine._load_wiki_chunks(project_id)
        if not chunks:
            return []

        scores = engine._bm25_scores(chunks, query or "")
        ranked = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)
        results: list[dict[str, Any]] = []
        for idx, score in ranked[:max_results]:
            chunk = chunks[idx]
            # Extract title from the [Wiki: title] prefix.
            m = re.search(r"\[Wiki:\s*([^\]]+)\]", chunk)
            title = m.group(1).strip() if m else f"Page {idx + 1}"
            # Snippet: body without the prefix line, capped at 600 chars.
            body = chunk[m.end():].strip() if m else chunk
            snippet = body[:600]
            chunk_id = hashlib.sha256(chunk[:128].encode()).hexdigest()[:16]
            results.append({"id": chunk_id, "title": title, "snippet": snippet, "score": round(score, 4)})
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_wiki failed: %s", exc)
        return []


def wiki_ingest_with_retry(
    source_type: str,
    source_data: dict,
    wiki_type: str = "project",
    project_id: str | None = None,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> tuple[dict | None, str | None]:
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
            from app.services.storage import workspace_path

            if wiki_type == "leading_practice":
                wiki_dir = workspace_path("leading_practices") / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)
            elif project_id:
                wiki_dir = workspace_path(project_id) / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)

            # Parse and extract
            extracted = _parse_source(source_type, source_data, project_id)
            if not extracted:
                return None, f"Failed to extract content from {source_type} source"
            _mark_user_edited_pages(wiki_type, project_id, extracted.get("title", ""))

            # Create/update wiki pages
            pages_result = _update_wiki_pages(
                extracted, wiki_type, project_id
            )

            # Update graph through canonical wiki_graph path. Evented mode can defer heavy work.
            index_result = {"changed_pages": 0, "elapsed_time_seconds": 0, "performance_improvement_percent": 0}
            if bool(getattr(settings, "wiki_evented_graph_rebuild_enabled", False)):
                from app.services.wiki_ingest import emit_wiki_change_event
                emit_wiki_change_event(
                    wiki_type=wiki_type,
                    project_id=project_id,
                    change_type="ingest",
                    changed_page_ids=pages_result.get("page_ids", []),
                )
                if bool(getattr(settings, "wiki_evented_graph_rebuild_fallback_sync_enabled", True)):
                    from app.services.wiki_graph import build_relationships_incremental
                    index_result = build_relationships_incremental(wiki_type, project_id)
            else:
                from app.services.wiki_graph import build_relationships_incremental
                index_result = build_relationships_incremental(wiki_type, project_id)

            # Auto-generate synthesis pages (emergent insights from connected knowledge)
            synthesis_result = {}
            if bool(getattr(settings, "wiki_synthesis_on_ingest_enabled", True)):
                synthesis_result = _try_generate_synthesis_pages(wiki_type, project_id)

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
                "page_ids": pages_result.get("page_ids", []),
                "corrections_made": len(pages_result.get("corrections", [])),
                "log_entry_id": log_entry_id,
                "synthesis_pages_created": synthesis_result.get("created", 0),
                "performance": {
                    "changed_pages": index_result.get("changed_pages", 0),
                    "elapsed_time_seconds": index_result.get("elapsed_time_seconds", 0),
                    "performance_improvement_percent": index_result.get("performance_improvement_percent", 0),
                }
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


def _mark_user_edited_pages(wiki_type: str, project_id: str | None, incoming_title: str) -> None:
    """Mark externally edited pages so future ingests merge instead of overwrite."""
    try:
        changed_pages, _, _ = _detect_changed_pages(wiki_type, project_id)
        incoming_page_id = re.sub(r"[^a-z0-9_]", "", incoming_title.lower().replace(" ", "_"))[:50]
        for page_id, page_data in changed_pages.items():
            if page_id == incoming_page_id:
                continue
            content = page_data.get("content", "")
            fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
            if not fm_match:
                continue
            frontmatter = fm_match.group(1)
            body = fm_match.group(2)
            if "user_edited:" in frontmatter:
                continue
            updated_frontmatter = f"{frontmatter}\nuser_edited: true"
            page_text = f"---\n{updated_frontmatter}\n---\n{body}"
            page_data["file"].write_text(page_text, encoding="utf-8")
    except Exception:
        # Best effort: never block ingest.
        return


def wiki_query_with_retry(
    question: str,
    wiki_type: str = "project",
    project_id: str | None = None,
    include_qa: bool = False,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> tuple[dict | None, str | None]:
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
            from app.services.storage import workspace_path

            if wiki_type == "leading_practice":
                wiki_dir = workspace_path("leading_practices") / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)
            elif project_id:
                wiki_dir = workspace_path(project_id) / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)

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
    project_id: str | None = None,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> tuple[dict | None, str | None]:
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
            from app.services.storage import workspace_path

            if wiki_type == "leading_practice":
                wiki_dir = workspace_path("leading_practices") / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)
            elif project_id:
                wiki_dir = workspace_path(project_id) / "wiki"
                wiki_dir.mkdir(parents=True, exist_ok=True)
                _migrate_meta_directory(wiki_dir)

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


def _llm_enrich_page(raw_title: str, content: str) -> dict:
    """Use Claude to generate a structured wiki page from document content. Falls back gracefully."""
    try:
        from app.services.claude import claude_generate_json, is_claude_enabled
        if not is_claude_enabled():
            return {}

        snippet = content[:6000]
        result = claude_generate_json(
            system=(
                "You are a knowledge-management assistant. Given a document, produce a structured "
                "wiki page. Be concise and precise. Return only valid JSON."
            ),
            user=(
                f"Document filename: {raw_title}\n\n"
                f"Document content:\n{snippet}\n\n"
                "Return JSON with these fields:\n"
                '{"title": "short title, 3-6 words, no org name prefix (e.g. \'P2P Kickoff Meeting\' not \'Varroc BPR P2P Transformation Kickoff Meeting\')", '
                '"summary": "2-3 sentence executive summary", '
                '"category": "document|reference|note|artifact", '
                '"semantic_type": "topic|concept|process|project|resource", '
                '"confidence": "high|medium|low", '
                '"key_insights": ["concise insight 1", "concise insight 2", ...], '
                '"sections": [{"heading": "Section title", "body": "section content"}]}'
            ),
            temperature=0.1,
            max_tokens=1500,
        )
        return result if isinstance(result, dict) else {}
    except Exception as e:
        logger.warning(f"LLM enrichment failed, falling back to basic format: {e}")
        return {}


def _update_wiki_pages(extracted: dict, wiki_type: str, project_id: str | None) -> dict:
    """Delegate page writes to the canonical wiki_ingest implementation."""
    try:
        from app.services.wiki_ingest import _update_wiki_pages as _ingest_update_wiki_pages

        return _ingest_update_wiki_pages(extracted, wiki_type, project_id)
    except Exception as e:
        logger.error(f"Error updating wiki pages via wiki_ingest: {e}")
        return {"created": 0, "updated": 0, "page_ids": [], "corrections": []}


def _try_generate_synthesis_pages(wiki_type: str, project_id: str | None) -> dict:
    """Auto-generate synthesis pages after ingest (Second Brain emergence layer).

    Called after graph rebuild, non-blocking. Synthesis pages connect clusters of related
    pages, surfacing emergent insights. Limited to 3 pages per ingest to keep light.

    Returns:
        {"status": "success|skipped|error", "created": int, "pages": list, ...}
    """
    try:
        from app.services.wiki_synthesis import SynthesisEngine

        engine = SynthesisEngine(wiki_type=wiki_type, project_id=project_id)
        result = engine.create_synthesis_pages(max_pages=3)
        if result.get("created", 0) > 0:
            logger.info(f"Auto-generated {result['created']} synthesis pages | wiki_type={wiki_type}")
        return result
    except Exception as e:
        logger.warning(f"Synthesis page generation failed (non-blocking): {e}")
        return {"status": "skipped", "error": str(e), "created": 0}


def _update_wiki_index(wiki_type: str, project_id: str | None) -> dict:
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
    project_id: str | None,
    operation: str,
    source_name: str | None = None,
    pages_touched: list | None = None,
    corrections_made: list | None = None,
    qa_results: str | None = None,
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
        timestamp = datetime.now(UTC).isoformat()
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

        log_entry_id = f"log_{int(datetime.now(UTC).timestamp() * 1000)}"
        return log_entry_id
    except Exception as e:
        logger.error(f"Error appending to wiki log: {e}")
        return f"log_{int(datetime.now(UTC).timestamp())}"


def _extract_relationships(
    source_page_id: str,
    content: str,
    all_page_ids: list[str],
    all_page_titles: list[str],
) -> list[dict]:
    from app.services.wiki_graph import _extract_relationships as _graph_extract_relationships
    return _graph_extract_relationships(source_page_id, content, all_page_ids, all_page_titles)


def _extract_cross_wiki_relationships(
    source_page_id: str,
    source_wiki_type: str,
    content: str,
    project_id: str | None = None,
) -> list[dict]:
    """
    Extract cross-wiki relationships (LP <-> Project wiki links).

    Supports patterns:
    - [[lp://Page Name]] - Leading Practice wiki
    - [[wiki://leading_practice/Page Name]]
    - [[wiki://project/{project_id}/Page Name]]

    Args:
        source_page_id: ID of source page
        source_wiki_type: "leading_practice" or "project"
        content: Page content
        project_id: Project ID (for project wiki)

    Returns:
        List of cross-wiki relationship dicts with structure:
        {
            "source_id": str,
            "source_wiki": "leading_practice" | "project",
            "target_id": str,
            "target_wiki": "leading_practice" | "project",
            "target_project_id": str (if target is project),
            "relation_type": "cross_wiki_reference",
            "confidence": "EXPLICIT",
            "confidence_score": float,
            "created_at": ISO timestamp
        }
    """
    import re
    cross_wiki_rels = []

    try:
        # Pattern for explicit cross-wiki links
        # [[lp://Page Name]] or [[wiki://leading_practice/Page Name]]
        lp_pattern = r"\[\[(?:lp://|wiki://leading_practice/)([^\]]+)\]\]"
        for match in re.finditer(lp_pattern, content, re.IGNORECASE):
            target_name = match.group(1).strip()
            target_id = target_name.lower().replace(" ", "_").replace(".", "")[:50]

            cross_wiki_rels.append({
                "source_id": source_page_id,
                "source_wiki": source_wiki_type,
                "target_id": target_id,
                "target_wiki": "leading_practice",
                "target_project_id": None,
                "relation_type": "cross_wiki_reference",
                "confidence": "EXPLICIT",
                "confidence_score": 1.0,
                "created_at": datetime.now(UTC).isoformat(),
            })

        # Pattern for cross-project wiki links
        # [[wiki://project/{project_id}/Page Name]]
        proj_pattern = r"\[\[wiki://project/([^/]+)/([^\]]+)\]\]"
        for match in re.finditer(proj_pattern, content):
            target_project_id = match.group(1)
            target_name = match.group(2).strip()
            target_id = target_name.lower().replace(" ", "_").replace(".", "")[:50]

            cross_wiki_rels.append({
                "source_id": source_page_id,
                "source_wiki": source_wiki_type,
                "target_id": target_id,
                "target_wiki": "project",
                "target_project_id": target_project_id,
                "relation_type": "cross_wiki_reference",
                "confidence": "EXPLICIT",
                "confidence_score": 1.0,
                "created_at": datetime.now(UTC).isoformat(),
            })

    except Exception as e:
        logger.warning(f"Error extracting cross-wiki relationships from {source_page_id}: {e}")

    return cross_wiki_rels


def _build_cross_wiki_relationships(
    wiki_type: str,
    project_id: str | None = None,
) -> dict:
    """
    Build and persist cross-wiki relationships between LP and Project wikis.

    Creates bidirectional index for fast cross-wiki navigation.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "lp_to_projects": {lp_page_id: [project_refs]},
            "projects_to_lp": {project_page_id: [lp_refs]},
            "total_links": int,
        }
    """
    from app.services.storage import workspace_path

    try:
        lp_to_projects = {}
        projects_to_lp = {}

        # Get all pages in this wiki
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        pages_file = wiki_dir / "pages.json"
        if not pages_file.exists():
            return {"lp_to_projects": {}, "projects_to_lp": {}, "total_links": 0}

        pages_data = json.loads(pages_file.read_text())
        all_pages = pages_data.get("pages", [])

        # Extract cross-wiki references from each page
        for page in all_pages:
            page_id = page.get("id")
            content = page.get("content", "")
            cross_refs = _extract_cross_wiki_relationships(page_id, wiki_type, content, project_id)

            for ref in cross_refs:
                if ref["target_wiki"] == "leading_practice":
                    if page_id not in lp_to_projects:
                        lp_to_projects[page_id] = []
                    lp_to_projects[page_id].append({
                        "target_page_id": ref["target_id"],
                        "source_page_id": page_id,
                        "source_wiki": wiki_type,
                        "source_project_id": project_id,
                    })
                elif ref["target_wiki"] == "project":
                    if page_id not in projects_to_lp:
                        projects_to_lp[page_id] = []
                    projects_to_lp[page_id].append({
                        "target_page_id": ref["target_id"],
                        "target_project_id": ref["target_project_id"],
                        "source_page_id": page_id,
                    })

        # Save cross-wiki index
        cross_wiki_file = wiki_dir / "cross_wiki_links.json"
        cross_wiki_file.write_text(json.dumps({
            "lp_to_projects": lp_to_projects,
            "projects_to_lp": projects_to_lp,
            "total_links": len(lp_to_projects) + len(projects_to_lp),
            "last_updated": datetime.now(UTC).isoformat(),
        }, indent=2))

        logger.info(f"Built cross-wiki relationships: {len(lp_to_projects)} LP refs, {len(projects_to_lp)} Project refs")
        return {
            "lp_to_projects": lp_to_projects,
            "projects_to_lp": projects_to_lp,
            "total_links": len(lp_to_projects) + len(projects_to_lp),
        }

    except Exception as e:
        logger.error(f"Error building cross-wiki relationships: {e}")
        return {"lp_to_projects": {}, "projects_to_lp": {}, "total_links": 0}


def _get_cross_wiki_references(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
) -> dict:
    """
    Get cross-wiki references for a specific page.

    Returns pages from the other wiki that reference this page.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID
        project_id: Project ID (for project wiki)

    Returns:
        {
            "incoming": [references_from_other_wiki],
            "outgoing": [references_to_other_wiki],
        }
    """
    from app.services.storage import workspace_path

    try:
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        cross_wiki_file = wiki_dir / "cross_wiki_links.json"
        if not cross_wiki_file.exists():
            return {"incoming": [], "outgoing": []}

        cross_data = json.loads(cross_wiki_file.read_text())

        # Get incoming and outgoing references for this page
        lp_to_projects = cross_data.get("lp_to_projects", {})
        projects_to_lp = cross_data.get("projects_to_lp", {})

        incoming = []
        outgoing = []

        if wiki_type == "leading_practice":
            # Get LP pages referencing this one (from projects)
            for project_pages in projects_to_lp.values():
                for ref in project_pages:
                    if ref.get("target_page_id") == page_id:
                        incoming.append(ref)

            # Get Project pages this LP page references
            if page_id in lp_to_projects:
                outgoing = lp_to_projects[page_id]

        else:  # project wiki
            # Get Project pages referencing this one (from LP)
            for lp_pages in lp_to_projects.values():
                for ref in lp_pages:
                    if ref.get("target_page_id") == page_id:
                        incoming.append(ref)

            # Get LP pages this project page references
            if page_id in projects_to_lp:
                outgoing = projects_to_lp[page_id]

        return {"incoming": incoming, "outgoing": outgoing}

    except Exception as e:
        logger.warning(f"Error getting cross-wiki references for {page_id}: {e}")
        return {"incoming": [], "outgoing": []}


def _save_persistent_graph(
    wiki_type: str,
    project_id: str | None,
) -> bool:
    """
    Save persistent graph.json for fast querying without re-extraction.

    Stores NetworkX adjacency format for quick loading.
    """
    try:
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
                "last_updated": datetime.now(UTC).isoformat(),
            }
        }, indent=2))

        logger.info(f"Saved persistent graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return True

    except Exception as e:
        logger.error(f"Error saving persistent graph: {e}")
        return False


def _load_persistent_graph(
    wiki_type: str,
    project_id: str | None,
) -> tuple:
    from app.services.wiki_graph import load_persistent_graph
    return load_persistent_graph(wiki_type, project_id)


def _llm_find_relationships(pages: dict) -> list:
    """
    Use Claude to identify semantic relationships between wiki pages.
    Catches connections that regex-based extraction misses (e.g. no [[links]] in content).

    Args:
        pages: {page_id: {"title": str, "content": str}}

    Returns:
        List of relationship dicts with confidence="SEMANTIC"
    """
    try:
        from app.services.claude import claude_generate_json, is_claude_enabled
        if not is_claude_enabled() or len(pages) < 2:
            return []

        import re

        page_list = []
        for pid, data in pages.items():
            content = data.get("content", "")
            # Extract summary from frontmatter or first body paragraph
            sm = re.search(r'^summary:\s*"?([^"\n]+)"?', content, re.MULTILINE)
            if sm:
                summary = sm.group(1)
            else:
                body = re.sub(r"^---.*?---", "", content, flags=re.DOTALL).strip()
                paras = [p.strip() for p in body.split("\n") if p.strip() and not p.startswith("#")]
                summary = paras[0][:200] if paras else ""
            page_list.append({"id": pid, "title": data["title"], "summary": summary})

        result = claude_generate_json(
            system="You are a knowledge management assistant. Identify semantic relationships between wiki pages.",
            user=(
                f"Wiki pages:\n{json.dumps(page_list, indent=2)}\n\n"
                "Identify all pairs of pages that are meaningfully related (share topics, "
                "reference each other's subject matter, or one supports the other). "
                "Return JSON: {\"relationships\": [{\"source_id\": \"page_id\", "
                "\"target_id\": \"page_id\", "
                "\"relation_type\": \"related|supports|extends|references\"}]}"
            ),
            temperature=0.1,
            max_tokens=800,
        )

        if not isinstance(result, dict):
            return []

        all_ids = set(pages.keys())
        now = datetime.now(UTC).isoformat()
        return [
            {
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "relation_type": r.get("relation_type", "related"),
                "confidence": "SEMANTIC",
                "confidence_score": 0.7,
                "source_location": "semantic",
                "created_at": now,
            }
            for r in result.get("relationships", [])
            if isinstance(r, dict)
            and r.get("source_id") in all_ids
            and r.get("target_id") in all_ids
            and r.get("source_id") != r.get("target_id")
        ]
    except Exception as e:
        logger.warning(f"LLM relationship extraction failed: {e}")
        return []


def _build_and_persist_relationships(
    wiki_type: str,
    project_id: str | None,
) -> dict:
    """Delegate relationship rebuilds to the canonical wiki_graph implementation."""
    try:
        from app.services.wiki_graph import _build_and_persist_relationships as _graph_build_and_persist

        return _graph_build_and_persist(wiki_type, project_id)
    except Exception as e:
        logger.error(f"Error building relationships via wiki_graph: {e}")
        return {"total_relationships": 0, "pages_with_links": 0, "average_links_per_page": 0}


# ===== Phase 4: Incremental Indexing & Performance Optimization =====

def _compute_content_hash(content: str) -> str:
    """
    Compute SHA256 hash of page content for change detection.

    Args:
        content: Page content (markdown)

    Returns:
        Hex-encoded SHA256 hash
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _load_page_manifest(wiki_type: str, project_id: str | None) -> dict:
    """
    Load manifest of page hashes for incremental updates.

    Manifest structure:
    {
        "pages": {
            "page_id": {
                "hash": "sha256_hash",
                "title": "Page Title",
                "updated_at": "ISO timestamp"
            }
        },
        "last_full_rebuild": "ISO timestamp",
        "relationships_version": int,
    }

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        Manifest dict or empty dict if not found
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        manifest_file = wiki_dir / ".page_manifest.json"
        if not manifest_file.exists():
            return {"pages": {}, "last_full_rebuild": None, "relationships_version": 0}

        return json.loads(manifest_file.read_text())

    except Exception as e:
        logger.warning(f"Error loading page manifest: {e}")
        return {"pages": {}, "last_full_rebuild": None, "relationships_version": 0}


def _save_page_manifest(wiki_type: str, project_id: str | None, manifest: dict) -> bool:
    """
    Save page manifest for incremental indexing.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)
        manifest: Manifest dict

    Returns:
        True if successful, False otherwise
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        manifest_file = wiki_dir / ".page_manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2))
        return True

    except Exception as e:
        logger.error(f"Error saving page manifest: {e}")
        return False


def _detect_changed_pages(wiki_type: str, project_id: str | None) -> tuple:
    """
    Detect which pages have changed since last update using content hashing.

    Returns:
        (changed_pages, unchanged_pages, deleted_pages)
        where each is a dict mapping page_id to page_data
    """
    from app.services.wiki_graph import detect_changed_pages
    return detect_changed_pages(wiki_type, project_id)


def _build_relationships_incremental(
    wiki_type: str,
    project_id: str | None,
) -> dict:
    """
    Build relationships incrementally by only processing changed pages.

    Skips unchanged pages for 10x faster updates.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "total_relationships": int,
            "pages_with_links": int,
            "changed_pages": int,
            "performance_improvement": float (% time saved)
        }
    """
    from app.services.wiki_graph import build_relationships_incremental
    return build_relationships_incremental(wiki_type, project_id)


def _get_wiki_performance_metrics(wiki_type: str, project_id: str | None) -> dict:
    """
    Get performance metrics for wiki operations.

    Returns:
        {
            "avg_ingest_time": float,
            "avg_query_time": float,
            "total_pages": int,
            "relationships_count": int,
            "last_update": ISO timestamp,
            "incremental_enabled": bool,
        }
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        # Count pages
        page_count = len(list(wiki_dir.glob("*.md"))) - 2  # Exclude index.md, log.md

        # Load relationships
        relationships_file = wiki_dir / "relationships.json"
        relationships_count = 0
        last_update = None
        is_incremental = False

        if relationships_file.exists():
            rel_data = json.loads(relationships_file.read_text())
            relationships_count = rel_data.get("total", 0)
            last_update = rel_data.get("last_updated")
            is_incremental = rel_data.get("incremental_update", False)

        # Load manifest for additional metrics
        manifest = _load_page_manifest(wiki_type, project_id)

        return {
            "total_pages": page_count,
            "relationships_count": relationships_count,
            "last_update": last_update,
            "incremental_enabled": is_incremental,
            "manifest_version": manifest.get("relationships_version", 0),
            "pages_in_manifest": len(manifest.get("pages", {})),
        }

    except Exception as e:
        logger.warning(f"Error getting performance metrics: {e}")
        return {
            "total_pages": 0,
            "relationships_count": 0,
            "error": str(e),
        }


def _detect_communities(
    wiki_type: str,
    project_id: str | None,
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
        import json

        import networkx as nx
        from networkx.algorithms import community

        from app.services.storage import workspace_path

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
    project_id: str | None,
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
        import json
        import re

        import networkx as nx

        from app.services.storage import workspace_path

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
        except Exception:  # noqa: BLE001 — network algorithm can fail on degenerate graphs
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
    project_id: str | None,
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
            "last_updated": datetime.now(UTC).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        logger.error(f"Error saving god nodes: {e}")
        return False


def _load_wiki_graph(wiki_type: str, project_id: str | None) -> tuple:
    """
    Load wiki relationship graph from relationships.json.

    Returns:
        (G, page_titles): NetworkX graph and mapping of page_id to page_title
    """
    try:
        import json
        import re

        import networkx as nx

        from app.services.storage import workspace_path

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
) -> dict | None:
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
    project_id: str | None,
    query: str,
    query_type: str = "neighbors",
    start_node: str | None = None,
    end_node: str | None = None,
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


def _get_god_nodes(wiki_type: str, project_id: str | None, limit: int = 10) -> list:
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
    project_id: str | None,
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
            "last_updated": datetime.now(UTC).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        logger.error(f"Error saving communities: {e}")
        return False


def _get_community_for_page(wiki_type: str, project_id: str | None, page_id: str) -> dict | None:
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


def _get_relationship_counts(wiki_type: str, project_id: str | None) -> dict:
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
        logger.warning(f"Error checking broken links: {e}")
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
        logger.warning(f"Error checking missing entities: {e}")
        return []


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


def _get_wiki_index(wiki_type: str, project_id: str | None) -> dict | None:
    """Get current wiki index. (To be implemented in Phase 2)"""
    # Stub
    return {"pages": []}


def _search_wiki_pages(question: str, index: dict, wiki_type: str, project_id: str | None) -> list:
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


def _evaluate_answer_quality(answer: str, pages: list, question: str) -> dict | None:
    """Evaluate answer quality. (To be implemented in Phase 3)"""
    # Stub
    return None


def _get_all_wiki_pages(wiki_type: str, project_id: str | None) -> list:
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
