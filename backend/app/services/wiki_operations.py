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
    """Parse source and extract key information. (To be implemented in Phase 2)"""
    # Stub: return basic extracted content
    return {
        "title": source_data.get("title", "Untitled"),
        "content": source_data.get("content", ""),
        "source_url": source_data.get("url", ""),
        "entities": [],
        "concepts": [],
    }


def _update_wiki_pages(extracted: dict, wiki_type: str, project_id: Optional[str]) -> dict:
    """Create/update wiki pages from extracted content. (To be implemented in Phase 2)"""
    # Stub: return mock result
    return {
        "created": 0,
        "updated": 0,
        "page_ids": [],
        "corrections": [],
    }


def _update_wiki_index(wiki_type: str, project_id: Optional[str]) -> dict:
    """Regenerate wiki index from all pages. (To be implemented in Phase 2)"""
    # Stub
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
    """Append operation to wiki log. (To be implemented in Phase 2)"""
    # Stub: return a mock log entry ID
    return f"log_{int(datetime.now(timezone.utc).timestamp())}"


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
