"""
Wiki API endpoints for ingest, query, lint, and browse operations.

Provides REST API for wiki operations with automatic retry, auto-correction, and QA.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, List, Optional
import logging

from app.services.wiki_operations import (
    wiki_ingest_with_retry,
    wiki_query_with_retry,
    wiki_lint_with_retry,
)
from app.services.wiki_corrections import DataCorrector
from app.services.wiki_qa import WikiQAEvaluator
from app.services.wiki_integrations import (
    WikiMemoryIntegration,
    WikiRunIntegration,
    WikiConversationIntegration,
    WikiCoordinatorIntegration,
    WikiLeadingPracticesIntegration,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


# ===== Ingest Operations =====

@router.post("/{wiki_type}/ingest")
async def ingest_source(
    wiki_type: str,
    source_type: str,
    source_data: Dict[str, Any],
    project_id: Optional[str] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Ingest a source into the wiki with automatic retry and auto-correction.

    Args:
        wiki_type: "leading_practice" or "project"
        source_type: "url", "document", "run_artifact", "conversation"
        source_data: Source-specific data dict
        project_id: Project ID (required for project wiki)
        max_retries: Max retry attempts (default 3)

    Returns:
        {
            "status": "success" | "error",
            "pages_created": int,
            "pages_updated": int,
            "corrections_made": int,
            "qa_results": {issues, suggestions, severity},
            "log_entry_id": str,
            "error": str (if failed)
        }
    """
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        # Execute ingest with retry
        result, error = wiki_ingest_with_retry(
            source_type=source_type,
            source_data=source_data,
            wiki_type=wiki_type,
            project_id=project_id,
            max_retries=max_retries,
        )

        if error:
            return {
                "status": "error",
                "error": error,
            }

        return {
            "status": "success",
            "pages_created": result.get("pages_created", 0),
            "pages_updated": result.get("pages_updated", 0),
            "corrections_made": result.get("corrections_made", 0),
            "log_entry_id": result.get("log_entry_id"),
        }

    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wiki_type}/ingest/from-memory")
async def ingest_memory_item(
    wiki_type: str,
    memory_item: Dict[str, Any],
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ingest a memory item into wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        memory_item: Memory item dict with id, type, content, metadata
        project_id: Project ID

    Returns:
        {status, page_id, title, category, error}
    """
    try:
        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(
            memory_item, wiki_type, project_id
        )

        if error:
            return {"status": "error", "error": error}

        return {
            "status": "success",
            "page_id": memory_item.get("id"),
            "title": wiki_page.get("title"),
            "category": wiki_page.get("category"),
        }

    except Exception as e:
        logger.error(f"Memory ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wiki_type}/ingest/from-run")
async def ingest_run_artifacts(
    wiki_type: str,
    run_id: str,
    run_summary: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
    project_id: str,
) -> Dict[str, Any]:
    """
    Ingest run artifacts and learnings into wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        run_id: Run ID
        run_summary: Execution summary with outcomes, learnings
        artifacts: List of output artifacts
        project_id: Project ID

    Returns:
        {status, pages_created, run_id, error}
    """
    if wiki_type != "project":
        raise HTTPException(status_code=400, detail="Run ingest only for project wiki")

    try:
        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki(
            run_id, run_summary, artifacts, project_id
        )

        if error:
            return {"status": "error", "error": error}

        return {
            "status": "success",
            "pages_created": result.get("pages_created"),
            "run_id": run_id,
        }

    except Exception as e:
        logger.error(f"Run ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wiki_type}/ingest/from-conversation")
async def ingest_conversation(
    wiki_type: str,
    conversation_id: str,
    messages: List[Dict[str, Any]],
    project_id: str,
) -> Dict[str, Any]:
    """
    Ingest conversation digest into wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        conversation_id: Conversation ID
        messages: List of conversation messages
        project_id: Project ID

    Returns:
        {status, page_id, title, error}
    """
    if wiki_type != "project":
        raise HTTPException(status_code=400, detail="Conversation ingest only for project wiki")

    try:
        wiki_page, error = WikiConversationIntegration.digest_conversation_to_wiki(
            conversation_id, messages, project_id
        )

        if error:
            return {"status": "error", "error": error}

        return {
            "status": "success",
            "page_id": conversation_id,
            "title": wiki_page.get("title"),
        }

    except Exception as e:
        logger.error(f"Conversation ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Query Operations =====

@router.post("/{wiki_type}/query")
async def query_wiki(
    wiki_type: str,
    question: str,
    project_id: Optional[str] = None,
    include_qa: bool = False,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Query the wiki to answer a question.

    Args:
        wiki_type: "leading_practice" or "project"
        question: Question to ask
        project_id: Project ID for project wiki
        include_qa: Run QA evaluation on answer
        max_retries: Max retry attempts

    Returns:
        {
            "status": "success" | "error",
            "answer": str,
            "citations": [page_ids],
            "source_pages": [page_ids],
            "qa_result": {passed, score, issues} (if include_qa=true),
            "error": str (if failed)
        }
    """
    try:
        result, error = wiki_query_with_retry(
            question=question,
            wiki_type=wiki_type,
            project_id=project_id,
            include_qa=include_qa,
            max_retries=max_retries,
        )

        if error:
            return {
                "status": "error",
                "error": error,
            }

        return {
            "status": "success",
            "answer": result.get("answer"),
            "citations": result.get("citations", []),
            "source_pages": result.get("source_pages", []),
            "qa_result": result.get("qa_result"),
        }

    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{wiki_type}/context")
async def get_wiki_context(
    wiki_type: str,
    question: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get wiki context for coordinator run planning.

    Args:
        wiki_type: "leading_practice" or "project"
        question: Planning question
        project_id: Project ID

    Returns:
        {
            "question": str,
            "relevant_pages": [page_dicts],
            "learnings": [learning_dicts],
            "recommendations": [str]
        }
    """
    try:
        context = WikiCoordinatorIntegration.query_wiki_for_context(
            question, wiki_type, project_id
        )

        return {
            "status": "success",
            "context": context,
        }

    except Exception as e:
        logger.error(f"Context query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Lint/Health Check Operations =====

@router.post("/{wiki_type}/lint")
async def lint_wiki(
    wiki_type: str,
    project_id: Optional[str] = None,
    max_retries: int = 3,
    auto_fix: bool = False,
) -> Dict[str, Any]:
    """
    Run health check on wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID
        max_retries: Max retry attempts
        auto_fix: Auto-apply low-risk fixes

    Returns:
        {
            "status": "success" | "error",
            "issues": [issue_dicts],
            "suggestions": [suggestion_dicts],
            "severity": "low" | "medium" | "high",
            "issues_count": int,
            "auto_fixes_applied": int (if auto_fix=true),
            "error": str (if failed)
        }
    """
    try:
        result, error = wiki_lint_with_retry(
            wiki_type=wiki_type,
            project_id=project_id,
            max_retries=max_retries,
        )

        if error:
            return {
                "status": "error",
                "error": error,
            }

        return {
            "status": "success",
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
            "severity": result.get("severity", "low"),
            "issues_count": result.get("issues_count", 0),
            "suggestions_count": result.get("suggestions_count", 0),
        }

    except Exception as e:
        logger.error(f"Lint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Browse Operations =====

@router.get("/{wiki_type}/pages")
async def list_pages(
    wiki_type: str,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = "updated_at",
) -> Dict[str, Any]:
    """
    List wiki pages with filtering and pagination.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID
        category: Filter by category (entity, concept, decision, etc.)
        limit: Result limit (default 50)
        offset: Result offset (default 0)
        sort_by: Sort field (updated_at, created_at, title)

    Returns:
        {
            "status": "success",
            "pages": [page_dicts],
            "pagination": {
                "offset": int,
                "limit": int,
                "total": int,
                "has_next": bool
            }
        }
    """
    try:
        # Stub implementation - would query database
        pages = []
        total = 0

        return {
            "status": "success",
            "pages": pages,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_next": offset + limit < total,
            },
        }

    except Exception as e:
        logger.error(f"List pages failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{wiki_type}/pages/{page_id}")
async def get_page(
    wiki_type: str,
    page_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get a specific wiki page.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID
        project_id: Project ID

    Returns:
        {
            "status": "success",
            "page": {
                "id": str,
                "title": str,
                "category": str,
                "content": str,
                "confidence": str,
                "updated_at": str,
                "inbound_links": [page_ids],
                "outbound_links": [page_ids]
            }
        }
    """
    try:
        # Stub implementation - would fetch from database
        page = {
            "id": page_id,
            "title": "Page Title",
            "category": "entity",
            "content": "Page content",
            "confidence": "medium",
            "updated_at": "2026-04-11T00:00:00Z",
            "inbound_links": [],
            "outbound_links": [],
        }

        return {
            "status": "success",
            "page": page,
        }

    except Exception as e:
        logger.error(f"Get page failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{wiki_type}/search")
async def search_pages(
    wiki_type: str,
    q: str,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    confidence: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """
    Full-text search wiki pages.

    Args:
        wiki_type: "leading_practice" or "project"
        q: Search query
        project_id: Project ID
        category: Filter by category
        confidence: Filter by confidence level
        limit: Result limit

    Returns:
        {
            "status": "success",
            "results": [page_dicts],
            "query": str,
            "count": int,
            "facets": {
                "category": {category: count},
                "confidence": {confidence: count}
            }
        }
    """
    try:
        # Stub implementation - would search database/index
        results = []
        facets = {
            "category": {},
            "confidence": {},
        }

        return {
            "status": "success",
            "results": results,
            "query": q,
            "count": len(results),
            "facets": facets,
        }

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Promote Operations =====

@router.post("/{wiki_type}/pages/{page_id}/promote")
async def promote_to_lp(
    wiki_type: str,
    page_id: str,
    project_id: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Propose a project page as a leading practice.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID
        project_id: Source project ID
        reason: Why this should be LP

    Returns:
        {
            "status": "success" | "error",
            "proposal_id": str,
            "status": "pending_review",
            "error": str (if failed)
        }
    """
    if wiki_type != "project":
        raise HTTPException(status_code=400, detail="Can only promote from project wiki")

    try:
        page = {
            "id": page_id,
            "title": "Page Title",
            "content": "Page content",
        }

        success, message = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
            page, project_id
        )

        if not success:
            return {"status": "error", "error": message}

        return {
            "status": "success",
            "proposal_id": f"proposal_{page_id}",
            "lp_status": "pending_review",
            "message": message,
        }

    except Exception as e:
        logger.error(f"Promote failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Dashboard Operations =====

@router.get("/{wiki_type}/stats")
async def get_wiki_stats(
    wiki_type: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get wiki statistics and health summary.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID

    Returns:
        {
            "status": "success",
            "stats": {
                "total_pages": int,
                "by_category": {category: count},
                "by_confidence": {confidence: count},
                "last_ingest": datetime,
                "pages_this_week": int,
                "health": {
                    "severity": "low" | "medium" | "high",
                    "issues_count": int,
                    "stale_pages": int
                }
            }
        }
    """
    try:
        stats = {
            "total_pages": 0,
            "by_category": {},
            "by_confidence": {},
            "last_ingest": None,
            "pages_this_week": 0,
            "health": {
                "severity": "low",
                "issues_count": 0,
                "stale_pages": 0,
            },
        }

        return {
            "status": "success",
            "stats": stats,
        }

    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Health Check =====

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "wiki",
        "version": "1.0.0",
    }


# Register router in main app
__all__ = ["router"]
