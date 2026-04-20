"""
Wiki API endpoints for ingest, query, lint, and browse operations.

Provides REST API for wiki operations with automatic retry, auto-correction, and QA.
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services.wiki_analytics import get_wiki_recommender
from app.services.wiki_cache import get_wiki_cache
from app.services.wiki_integrations import (
    WikiConversationIntegration,
    WikiCoordinatorIntegration,
    WikiLeadingPracticesIntegration,
    WikiRunIntegration,
)
from app.services.wiki_operations import (
    _build_cross_wiki_relationships,
    _detect_changed_pages,
    _get_cross_wiki_references,
    _get_wiki_performance_metrics,
    wiki_ingest_with_retry,
    wiki_lint_with_retry,
    wiki_query_with_retry,
)

logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PAGE_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_WIKI_VIEW_ROLES = frozenset({"Owner", "Editor", "Viewer"})
_WIKI_EDIT_ROLES = frozenset({"Owner", "Editor"})


def _wiki_lp_admin_emails() -> frozenset[str]:
    raw = (settings.wiki_lp_admin_emails or "").strip()
    if not raw:
        return frozenset()
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def _wiki_require_access(
    wiki_type: str,
    project_id: str | None,
    user: User,
    db: Session,
    *,
    mutating: bool,
) -> None:
    """Enforce auth + project role for project wiki; LP mutations require an admin allowlist.

    - ``wiki_type=project``: ``require_project_role`` on ``project_id`` (view vs. edit roles).
    - ``wiki_type=leading_practice``:
        * reads: any authenticated user (caller already passed ``get_current_user``).
        * mutations: allowed only for emails listed in ``settings.wiki_lp_admin_emails``.
          If the allowlist is empty AND ``processdoc_env == "development"``, mutations are
          permitted (preserves the historical dev-only behavior); in staging/production an
          empty allowlist denies all LP mutations so the shared LP wiki cannot be edited by
          any authenticated user.
    """
    if wiki_type not in ("leading_practice", "project"):
        raise HTTPException(status_code=400, detail="Invalid wiki_type")
    if wiki_type == "project":
        if not project_id or not _PROJECT_ID_RE.match(project_id):
            raise HTTPException(status_code=400, detail="Invalid or missing project_id")
        roles = _WIKI_EDIT_ROLES if mutating else _WIKI_VIEW_ROLES
        require_project_role(project_id, roles, user, db)
        return
    # leading_practice
    if not mutating:
        return
    admins = _wiki_lp_admin_emails()
    if admins:
        if (user.email or "").strip().lower() not in admins:
            raise HTTPException(status_code=403, detail="Leading-practice wiki mutations are restricted to admins")
        return
    # No allowlist configured — only allow mutations in development.
    env = (settings.processdoc_env or "development").strip().lower()
    if env != "development":
        raise HTTPException(
            status_code=403,
            detail="Leading-practice wiki mutations require wiki_lp_admin_emails to be configured",
        )


router = APIRouter(prefix="/api/wiki", tags=["wiki"])


# ===== Ingest Operations =====

@router.post("/{wiki_type}/ingest")
async def ingest_source(
    wiki_type: str,
    source_type: str,
    source_data: dict[str, Any],
    project_id: str | None = None,
    max_retries: int = 3,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/ingest/from-memory")
async def ingest_memory_item(
    wiki_type: str,
    memory_item: dict[str, Any],
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Ingest a memory item into wiki.

    Args:
        wiki_type: "leading_practice" or "project"
        memory_item: Memory item dict with id, type, content, metadata (or memory_id / memory_content from UI)
        project_id: Project ID

    Returns:
        {status, page, error}
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    raw = dict(memory_item or {})
    if raw.get("memory_id") is not None and raw.get("id") is None:
        meta: dict[str, Any] = {}
        if raw.get("title"):
            meta["title"] = raw.get("title")
        raw = {
            "id": raw.get("memory_id"),
            "type": raw.get("memory_type", "fact"),
            "content": raw.get("memory_content", ""),
            "metadata": meta,
            "category": raw.get("category"),
        }

    try:
        source_data = {
            "memory_id": raw.get("id"),
            "memory_type": raw.get("type", "fact"),
            "memory_content": raw.get("content", ""),
            "title": (raw.get("metadata") or {}).get("title") or raw.get("title"),
            "category_hint": raw.get("category"),
        }
        result, error = wiki_ingest_with_retry(
            source_type="memory",
            source_data=source_data,
            wiki_type=wiki_type,
            project_id=project_id,
            max_retries=3,
        )

        if error:
            return {"status": "error", "error": error}

        from app.services.storage import workspace_path

        page_ids = (result or {}).get("page_ids") or []
        page_id = page_ids[0] if page_ids else None
        title = str(source_data.get("title") or "Untitled")
        category = str(raw.get("category") or "concept")
        confidence = "medium"
        if page_id:
            if wiki_type == "leading_practice":
                wiki_dir = workspace_path("leading_practices") / "wiki"
            else:
                wiki_dir = workspace_path(project_id) / "wiki"
            pf = wiki_dir / f"{page_id}.md"
            if pf.exists():
                text = pf.read_text(encoding="utf-8")
                m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
                if m:
                    for line in m.group(1).split("\n"):
                        if ":" not in line:
                            continue
                        k, v = line.split(":", 1)
                        k, v = k.strip(), v.strip().strip('"')
                        if k == "title":
                            title = v
                        elif k == "category":
                            category = v
                        elif k == "confidence":
                            confidence = v

        pid = page_id or ""
        return {
            "status": "success",
            "page_id": pid,
            "title": title,
            "category": category,
            "page": {
                "id": pid,
                "title": title,
                "category": category,
                "confidence": confidence,
            },
        }

    except Exception as e:
        logger.error(f"Memory ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/ingest/from-run")
async def ingest_run_artifacts(
    wiki_type: str,
    run_id: str,
    run_summary: dict[str, Any],
    artifacts: list[dict[str, Any]],
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/ingest/from-conversation")
async def ingest_conversation(
    wiki_type: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/sync-documents")
async def sync_project_documents_to_wiki(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ingest every file from the project workspace ``source_docs`` folder into the project wiki."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type != "project" or not project_id:
        raise HTTPException(status_code=400, detail="sync-documents requires project wiki and project_id")

    from app.services.storage import workspace_path

    source_dir = workspace_path(project_id) / "source_docs"
    if not source_dir.is_dir():
        return {
            "status": "success",
            "ingested": 0,
            "skipped": 0,
            "errors": [],
            "message": "source_docs directory not found",
        }

    ingested = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        result, err = wiki_ingest_with_retry(
            source_type="document",
            source_data={"filename": path.name},
            wiki_type=wiki_type,
            project_id=project_id,
            max_retries=2,
        )
        if err:
            errors.append({"file": path.name, "error": err})
        elif result and (result.get("pages_created", 0) + result.get("pages_updated", 0)) > 0:
            ingested += 1
        else:
            skipped += 1

    return {"status": "success", "ingested": ingested, "skipped": skipped, "errors": errors}


@router.post("/project/{project_id}/vault/init")
async def init_obsidian_vault(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Initialize Obsidian-compatible vault layout for a project."""
    _wiki_require_access("project", project_id, user, db, mutating=True)
    from app.services.storage import ensure_obsidian_vault_layout

    details = ensure_obsidian_vault_layout(project_id)
    return {"status": "success", **details}


@router.get("/project/{project_id}/vault/path")
async def get_obsidian_vault_path(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the filesystem path of the project Obsidian vault."""
    _wiki_require_access("project", project_id, user, db, mutating=False)
    from app.services.storage import workspace_path

    return {"status": "success", "vault_path": str(workspace_path(project_id))}


@router.get("/{wiki_type}/artifacts")
async def list_wiki_pages_for_run(
    wiki_type: str,
    run_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List wiki pages linked to a run (via frontmatter ``source_run_id``)."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type != "project" or not project_id:
        raise HTTPException(status_code=400, detail="artifacts listing requires project wiki and project_id")
    if not run_id or not _PAGE_STEM_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run_id")

    from app.services.storage import workspace_path

    wiki_dir = workspace_path(project_id) / "wiki"
    artifacts: list[dict[str, Any]] = []
    if not wiki_dir.exists():
        return {"status": "success", "artifacts": []}

    for md_file in sorted(wiki_dir.glob("*.md")):
        if md_file.name in ("index.md", "log.md"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            fm: dict[str, str] = {}
            m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if m:
                for line in m.group(1).split("\n"):
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            if fm.get("source_run_id") != run_id:
                continue
            artifacts.append(
                {
                    "id": md_file.stem,
                    "name": fm.get("title", md_file.stem),
                    "type": fm.get("semantic_type", "artifact"),
                    "category": fm.get("category", "artifact"),
                    "created_at": fm.get("last_updated", fm.get("created_at", "")),
                }
            )
        except Exception as ex:
            logger.warning(f"artifacts scan skip {md_file.name}: {ex}")

    return {"status": "success", "artifacts": artifacts}


@router.get("/{wiki_type}/memory/{memory_id}/pages")
async def list_wiki_pages_for_memory(
    wiki_type: str,
    memory_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List wiki pages created from a given memory item id."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type != "project" or not project_id:
        raise HTTPException(status_code=400, detail="memory pages requires project wiki and project_id")
    if not memory_id or not _PAGE_STEM_RE.match(memory_id):
        raise HTTPException(status_code=400, detail="Invalid memory_id")

    from app.services.storage import workspace_path

    wiki_dir = workspace_path(project_id) / "wiki"
    pages: list[dict[str, Any]] = []
    if not wiki_dir.exists():
        return {"status": "success", "pages": []}

    for md_file in sorted(wiki_dir.glob("*.md")):
        if md_file.name in ("index.md", "log.md"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            fm: dict[str, str] = {}
            m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if m:
                for line in m.group(1).split("\n"):
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            if fm.get("source_memory_id") != memory_id:
                continue
            pages.append(
                {
                    "id": md_file.stem,
                    "title": fm.get("title", md_file.stem),
                    "category": fm.get("category", "concept"),
                    "confidence": fm.get("confidence", "medium"),
                }
            )
        except Exception as ex:
            logger.warning(f"memory pages scan skip {md_file.name}: {ex}")

    return {"status": "success", "pages": pages}


# ===== Query Operations =====

@router.post("/{wiki_type}/query")
async def query_wiki(
    wiki_type: str,
    question: str,
    project_id: str | None = None,
    include_qa: bool = False,
    max_retries: int = 3,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/context")
async def get_wiki_context(
    wiki_type: str,
    question: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Lint/Health Check Operations =====

@router.post("/{wiki_type}/lint")
async def lint_wiki(
    wiki_type: str,
    project_id: str | None = None,
    max_retries: int = 3,
    auto_fix: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Browse Operations =====

@router.get("/{wiki_type}/pages")
async def list_pages(
    wiki_type: str,
    project_id: str | None = None,
    category: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = "updated_at",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import re

        from app.services.storage import workspace_path
        from app.services.wiki_operations import _get_relationship_counts

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        pages = []

        # Load relationship counts, community assignments, and god node status
        from app.services.wiki_operations import _get_community_for_page, _get_god_nodes
        rel_counts = _get_relationship_counts(wiki_type, project_id)
        god_nodes = _get_god_nodes(wiki_type, project_id, limit=100)
        god_node_ids = {gn["page_id"] for gn in god_nodes}

        # Read markdown files from wiki directory
        if wiki_dir.exists():
            for md_file in sorted(wiki_dir.glob("*.md")):
                # Skip special files
                if md_file.name in ("index.md", "log.md", "relationships.json"):
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")

                    # Parse frontmatter (use page_category — do not shadow query param ``category``)
                    frontmatter = {}
                    title = md_file.stem.replace("_", " ").title()
                    confidence = "medium"
                    page_category = "concept"
                    updated_at = md_file.stat().st_mtime

                    # Extract frontmatter
                    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                    if match:
                        fm_text = match.group(1)
                        for line in fm_text.split("\n"):
                            if ":" in line:
                                key, value = line.split(":", 1)
                                key = key.strip()
                                value = value.strip().strip('"')
                                frontmatter[key] = value

                        title = frontmatter.get("title", title)
                        confidence = frontmatter.get("confidence", confidence)
                        page_category = frontmatter.get("category", page_category)

                    # Extract summary from content
                    summary = None
                    lines = content.split("\n")
                    for line in lines:
                        if line.strip() and not line.startswith("#") and not line.startswith("-") and not line.startswith("["):
                            summary = line.strip()[:200]
                            break

                    # Get relationship counts, community, and god node status
                    page_id = md_file.stem
                    inbound_count = rel_counts.get(page_id, {}).get("inbound", 0)
                    community_info = _get_community_for_page(wiki_type, project_id, page_id)

                    # Check if this is a god node
                    god_node_rank = None
                    if page_id in god_node_ids:
                        for gn in god_nodes:
                            if gn["page_id"] == page_id:
                                god_node_rank = gn["rank"]
                                break

                    # Optional query filter: ``category`` limits to that page category
                    if category and page_category != category:
                        continue

                    page_dict = {
                        "id": page_id,
                        "title": title,
                        "category": page_category,
                        "confidence": confidence,
                        "updated_at": updated_at,
                        "summary": summary,
                        "inbound_links": inbound_count,
                        "outbound_links": rel_counts.get(page_id, {}).get("outbound", 0),
                    }
                    if community_info:
                        page_dict["community_id"] = community_info["community_id"]
                        page_dict["community_concepts"] = community_info.get("top_concepts", [])
                    if god_node_rank:
                        page_dict["god_node_rank"] = god_node_rank
                    pages.append(page_dict)
                except Exception as e:
                    logger.warning(f"Failed to parse wiki page {md_file.name}: {e}")
                    continue

        # Sort pages
        if sort_by == "updated_at":
            pages.sort(key=lambda p: p["updated_at"], reverse=True)
        elif sort_by == "title":
            pages.sort(key=lambda p: p["title"])

        # Apply pagination
        total = len(pages)
        paginated = pages[offset : offset + limit]

        return {
            "status": "success",
            "pages": paginated,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + limit < total,
            },
            "available_categories": ["entity", "concept", "decision", "learning", "template", "artifact"],
            "available_confidence": ["low", "medium", "high"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List pages failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/pages/{page_id}/preview")
async def get_page_preview(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return a short summary of a wiki page for hover previews."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not _PAGE_STEM_RE.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page_id")

    from app.services.storage import workspace_path
    from app.services.wiki_operations import _get_relationship_counts

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required for project wiki")
        wiki_dir = workspace_path(project_id) / "wiki"

    page_path = wiki_dir / f"{page_id}.md"
    if not page_path.is_file():
        raise HTTPException(status_code=404, detail="Page not found")

    content = page_path.read_text(encoding="utf-8")
    title = page_id.replace("_", " ").title()
    category = "artifact"
    confidence = "medium"
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip().strip('"')
            if k == "title":
                title = v
            elif k == "category":
                category = v
            elif k == "confidence":
                confidence = v

    summary = ""
    for line in content.split("\n"):
        ln = line.strip()
        if ln and not ln.startswith("#") and not ln.startswith("-") and not ln.startswith("["):
            summary = ln[:280]
            break

    rel_counts = _get_relationship_counts(wiki_type, project_id)
    rc = rel_counts.get(page_id, {})
    pages_linking = int(rc.get("inbound", 0) or 0)
    outbound_links_count = int(rc.get("outbound", 0) or 0)
    updated_ts = page_path.stat().st_mtime
    updated_at = datetime.fromtimestamp(updated_ts, tz=UTC).isoformat()

    return {
        "status": "success",
        "page": {
            "id": page_id,
            "title": title,
            "category": category,
            "confidence": confidence,
            "summary": summary,
            "updated_at": updated_at,
            "pages_linking": pages_linking,
            "outbound_links_count": outbound_links_count,
        },
    }


@router.get("/{wiki_type}/pages/{page_id}/related")
async def get_related_wiki_pages(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    max_depth: int = Query(2, ge=1, le=5),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Transitively related pages (typed relationship graph)."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not _PAGE_STEM_RE.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page_id")

    from app.services.wiki_relationships import RelationshipGraph, get_transitive_related_pages

    related_ids = get_transitive_related_pages(page_id, wiki_type, project_id, max_depth=max_depth)
    graph = RelationshipGraph(wiki_type, project_id)
    related_pages: list[dict[str, Any]] = []
    for tid in related_ids:
        if tid == page_id:
            continue
        rtype = "related_to"
        conf = 0.5
        for rel in graph.relationships:
            if rel.get("source_id") == page_id and rel.get("target_id") == tid:
                rtype = str(rel.get("relation_type", "related_to"))
                conf = float(rel.get("confidence_score") or rel.get("confidence") or 0.5)
                break
            if rel.get("source_id") == tid and rel.get("target_id") == page_id:
                rtype = str(rel.get("relation_type", "related_to"))
                conf = float(rel.get("confidence_score") or rel.get("confidence") or 0.5)
                break
        related_pages.append({"page_id": tid, "relation_type": rtype, "confidence": conf})

    return {"status": "success", "related_pages": related_pages}


@router.get("/{wiki_type}/pages/{page_id}")
async def get_page(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not _PAGE_STEM_RE.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page_id")
    try:
        from datetime import datetime

        from app.services.storage import workspace_path
        from app.services.wiki_operations import _get_community_for_page

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"  # type: ignore[arg-type]
        md_file = wiki_dir / f"{page_id}.md"
        try:
            md_file.resolve().relative_to(wiki_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid page_id") from None
        if not md_file.exists():
            raise HTTPException(status_code=404, detail="Page not found")

        content = md_file.read_text(encoding="utf-8")
        frontmatter: dict[str, Any] = {}
        body = content
        fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"')
            body = fm_match.group(2)

        title = frontmatter.get("title") or page_id.replace("_", " ").title()
        category = frontmatter.get("category") or "concept"
        confidence = frontmatter.get("confidence") or "medium"

        stat = md_file.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
        created_at = datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat()

        # Resolve same-wiki inbound / outbound links from relationships.json.
        title_by_id: dict[str, str] = {}
        for md in wiki_dir.glob("*.md"):
            if md.name in ("index.md", "log.md"):
                continue
            try:
                head = md.read_text(encoding="utf-8")[:512]
                m = re.search(r'^title:\s*"?([^"\n]+)"?', head, re.MULTILINE)
                title_by_id[md.stem] = (m.group(1).strip() if m else md.stem)
            except Exception as exc:
                logger.debug("title read failed for %s: %s", md.name, exc)
                title_by_id[md.stem] = md.stem

        inbound: list[dict[str, str]] = []
        outbound: list[dict[str, str]] = []
        rels_file = wiki_dir / ".meta" / "relationships.json"
        if not rels_file.exists():
            rels_file = wiki_dir / "relationships.json"
        if rels_file.exists():
            try:
                rels_data = json.loads(rels_file.read_text(encoding="utf-8"))
                for rel in rels_data.get("relationships", []):
                    src = str(rel.get("source_id") or "")
                    tgt = str(rel.get("target_id") or "")
                    if tgt == page_id and src:
                        inbound.append({"id": src, "title": title_by_id.get(src, src), "type": "inbound"})
                    elif src == page_id and tgt:
                        outbound.append({"id": tgt, "title": title_by_id.get(tgt, tgt), "type": "outbound"})
            except Exception as exc:
                logger.debug("relationships.json parse failed: %s", exc)

        community = _get_community_for_page(wiki_type, project_id, page_id) or None

        page = {
            "id": page_id,
            "title": title,
            "category": category,
            "confidence": confidence,
            "content": body.strip(),
            "created_at": frontmatter.get("created_at") or created_at,
            "updated_at": frontmatter.get("updated_at") or updated_at,
            "created_by": frontmatter.get("created_by"),
            "source_memory_ids": [],
            "source_run_ids": [],
            "inbound_links": inbound,
            "outbound_links": outbound,
            "pages_linking_count": len(inbound),
            "frontmatter": frontmatter,
        }
        if community:
            page["community"] = community

        return {"status": "success", "page": page}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get page failed for %s/%s", wiki_type, page_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/search")
async def search_pages(
    wiki_type: str,
    q: str,
    project_id: str | None = None,
    category: str | None = None,
    confidence: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    query_text = (q or "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    try:
        from datetime import datetime

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"  # type: ignore[arg-type]

        results: list[dict[str, Any]] = []
        cat_facets: dict[str, int] = {}
        conf_facets: dict[str, int] = {}

        if wiki_dir.exists():
            q_lower = query_text.lower()
            for md_file in wiki_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md"):
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.debug("search: read failed for %s: %s", md_file.name, exc)
                    continue

                frontmatter: dict[str, str] = {}
                body = content
                fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
                if fm_match:
                    for line in fm_match.group(1).split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            frontmatter[k.strip()] = v.strip().strip('"')
                    body = fm_match.group(2)

                page_title = frontmatter.get("title") or md_file.stem.replace("_", " ").title()
                page_category = frontmatter.get("category") or "concept"
                page_confidence = frontmatter.get("confidence") or "medium"

                if category and page_category != category:
                    continue
                if confidence and page_confidence != confidence:
                    continue

                title_l = page_title.lower()
                body_l = body.lower()
                if q_lower not in title_l and q_lower not in body_l:
                    continue

                score = 0
                if q_lower in title_l:
                    score += 5
                score += body_l.count(q_lower)

                idx = body_l.find(q_lower)
                if idx >= 0:
                    start = max(0, idx - 80)
                    end = min(len(body), idx + len(q_lower) + 80)
                    snippet = body[start:end].strip().replace("\n", " ")
                else:
                    snippet = body.strip()[:200]

                stat = md_file.stat()
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()

                results.append({
                    "id": md_file.stem,
                    "title": page_title,
                    "category": page_category,
                    "confidence": page_confidence,
                    "updated_at": updated_at,
                    "snippet": snippet,
                    "score": score,
                })
                cat_facets[page_category] = cat_facets.get(page_category, 0) + 1
                conf_facets[page_confidence] = conf_facets.get(page_confidence, 0) + 1

        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:limit]

        return {
            "status": "success",
            "results": results,
            "query": query_text,
            "count": len(results),
            "facets": {"category": cat_facets, "confidence": conf_facets},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Wiki search failed for q=%r", query_text)
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Promote Operations =====

@router.post("/{wiki_type}/pages/{page_id}/promote")
async def promote_to_lp(
    wiki_type: str,
    page_id: str,
    project_id: str,
    reason: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Relationship Operations =====

@router.get("/{wiki_type}/relationships/validate")
async def validate_wiki_relationships_route(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Validate relationship graph and return statistics plus issues."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_relationships import validate_relationships

    return validate_relationships(wiki_type, project_id)


@router.post("/{wiki_type}/relationships/classify")
async def classify_wiki_relationships_route(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Auto-classify untyped relationships."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.wiki_relationships import classify_all_relationships

    return classify_all_relationships(wiki_type, project_id)


@router.get("/{wiki_type}/relationships/{page_id}")
async def get_page_relationships(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    relationship_type: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get relationships for a specific page.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID
        project_id: Project ID
        relationship_type: Filter by type ("references", "mentions", etc)

    Returns:
        {
            "status": "success",
            "page_id": str,
            "inbound": [{source_id, relation_type, confidence, confidence_score}],
            "outbound": [{target_id, relation_type, confidence, confidence_score}],
            "total_inbound": int,
            "total_outbound": int
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import json

        from app.services.storage import workspace_path

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        # Load relationships
        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
            relationships_file = wiki_dir / "relationships.json"
        inbound = []
        outbound = []

        if relationships_file.exists():
            rels_data = json.loads(relationships_file.read_text())
            for rel in rels_data.get("relationships", []):
                # Filter by relationship type if specified
                if relationship_type and rel["relation_type"] != relationship_type:
                    continue

                if rel["source_id"] == page_id:
                    outbound.append({
                        "target_id": rel["target_id"],
                        "relation_type": rel["relation_type"],
                        "confidence": rel["confidence"],
                        "confidence_score": rel["confidence_score"],
                    })
                elif rel["target_id"] == page_id:
                    inbound.append({
                        "source_id": rel["source_id"],
                        "relation_type": rel["relation_type"],
                        "confidence": rel["confidence"],
                        "confidence_score": rel["confidence_score"],
                    })

        return {
            "status": "success",
            "page_id": page_id,
            "inbound": inbound,
            "outbound": outbound,
            "total_inbound": len(inbound),
            "total_outbound": len(outbound),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get relationships failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Community Operations =====

@router.get("/{wiki_type}/communities")
async def get_communities(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get all wiki communities (functional clusters).

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID

    Returns:
        {
            "status": "success",
            "total_communities": int,
            "communities": {
                "0": {
                    "page_ids": [page_id, ...],
                    "top_concepts": [concept, ...],
                    "size": int,
                    "density": float
                },
                ...
            },
            "last_updated": ISO datetime
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import json

        from app.services.storage import workspace_path

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        communities_file = wiki_dir / "communities.json"
        if not communities_file.exists():
            return {
                "status": "success",
                "total_communities": 0,
                "communities": {},
                "last_updated": None,
            }

        communities_data = json.loads(communities_file.read_text())

        return {
            "status": "success",
            "total_communities": communities_data["total_communities"],
            "communities": communities_data["communities"],
            "last_updated": communities_data.get("last_updated"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get communities failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/communities/{community_id}")
async def get_community_details(
    wiki_type: str,
    community_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get details for a specific community.

    Args:
        wiki_type: "leading_practice" or "project"
        community_id: Community ID
        project_id: Project ID

    Returns:
        {
            "status": "success",
            "community_id": str,
            "page_ids": [page_id, ...],
            "top_concepts": [concept, ...],
            "size": int,
            "density": float,
            "pages": [page objects with full details]
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import json
        import re

        from app.services.storage import workspace_path

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        communities_file = wiki_dir / "communities.json"
        if not communities_file.exists():
            raise HTTPException(status_code=404, detail="No communities found")

        communities_data = json.loads(communities_file.read_text())
        community = communities_data["communities"].get(community_id)

        if not community:
            raise HTTPException(status_code=404, detail=f"Community {community_id} not found")

        # Load full page details for pages in this community
        pages = []
        for page_id in community["page_ids"]:
            page_file = wiki_dir / f"{page_id}.md"
            if page_file.exists():
                content = page_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else page_id.replace("_", " ").title()

                pages.append({
                    "id": page_id,
                    "title": title,
                })

        return {
            "status": "success",
            "community_id": community_id,
            "page_ids": community["page_ids"],
            "top_concepts": community["top_concepts"],
            "size": community["size"],
            "density": community["density"],
            "pages": pages,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get community details failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== God Node Operations =====

@router.get("/{wiki_type}/god-nodes")
async def get_god_nodes(
    wiki_type: str,
    project_id: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get the most important pages (god nodes) in the wiki.

    God nodes are ranked by:
    - Inbound link count (60% weight): how many pages reference this page
    - Betweenness centrality (40% weight): how much it bridges between communities

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID
        limit: Max results to return (default 10, max 100)

    Returns:
        {
            "status": "success",
            "god_nodes": [
                {
                    "rank": int,
                    "page_id": str,
                    "page_title": str,
                    "importance_score": float (0.0-1.0),
                    "inbound_links": int,
                    "betweenness_centrality": float,
                },
                ...
            ],
            "total_pages": int,
            "avg_importance": float
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        from app.services.wiki_operations import _get_god_nodes

        god_nodes = _get_god_nodes(wiki_type, project_id, limit=limit)

        # Get overall stats
        import json

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        total_pages = 0
        avg_importance = 0.0

        god_nodes_file = wiki_dir / "god_nodes.json"
        if god_nodes_file.exists():
            god_nodes_data = json.loads(god_nodes_file.read_text())
            total_pages = god_nodes_data.get("total_pages", 0)
            avg_importance = god_nodes_data.get("avg_importance", 0.0)

        return {
            "status": "success",
            "god_nodes": god_nodes,
            "total_pages": total_pages,
            "avg_importance": avg_importance,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get god nodes failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Graph Query Operations =====

@router.get("/{wiki_type}/query")
async def query_wiki_graph(
    wiki_type: str,
    q: str,
    query_type: str = Query("neighbors", pattern="^(neighbors|bfs|shortest_path|related)$"),
    start_node: str | None = None,
    end_node: str | None = None,
    max_distance: int = Query(3, ge=1, le=5),
    max_results: int = Query(20, ge=1, le=100),
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Query the wiki knowledge graph using relationship traversal.

    Query types:
    - neighbors: Direct connections to a page
    - bfs: Breadth-first search from a page (distance-based)
    - shortest_path: Shortest path between two pages
    - related: Pages related to a query (by name/semantics)

    Args:
        wiki_type: "leading_practice" or "project"
        q: Query text or page ID
        query_type: Type of query
        start_node: Starting page ID (for neighbors, bfs, shortest_path)
        end_node: Ending page ID (for shortest_path)
        max_distance: Max hops to search (for bfs)
        max_results: Max results to return
        project_id: Project ID

    Returns:
        {
            "status": "success",
            "query": str,
            "query_type": str,
            "results": [
                {
                    "node_id": str,
                    "distance": int,
                    "path": [str] (optional),
                    "confidence": str (optional)
                },
                ...
            ],
            "total_results": int,
            "truncated": bool
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        from app.services.wiki_operations import _execute_graph_query

        # Use start_node from params or try to resolve q as page ID
        node_id = start_node or q

        result = _execute_graph_query(
            wiki_type=wiki_type,
            project_id=project_id,
            query=q,
            query_type=query_type,
            start_node=node_id if query_type in ["neighbors", "bfs", "related"] else None,
            end_node=end_node,
            max_distance=max_distance,
            max_results=max_results,
        )

        return {
            "status": "success",
            **result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/graph/stats")
async def get_graph_stats(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get statistics about the wiki knowledge graph.

    Returns:
        {
            "status": "success",
            "stats": {
                "node_count": int,
                "edge_count": int,
                "avg_degree": float,
                "density": float,
                "last_updated": ISO datetime
            }
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import networkx as nx

        from app.services.wiki_operations import _load_persistent_graph

        G, page_titles, metadata = _load_persistent_graph(wiki_type, project_id)

        if not G or G.number_of_nodes() == 0:
            return {
                "status": "success",
                "stats": {
                    "node_count": 0,
                    "edge_count": 0,
                    "avg_degree": 0.0,
                    "density": 0.0,
                    "last_updated": None,
                }
            }

        # Calculate graph metrics
        density = nx.density(G)
        avg_degree = (2 * G.number_of_edges()) / max(G.number_of_nodes(), 1)

        return {
            "status": "success",
            "stats": {
                "node_count": G.number_of_nodes(),
                "edge_count": G.number_of_edges(),
                "avg_degree": round(avg_degree, 2),
                "density": round(density, 3),
                "last_updated": metadata.get("last_updated") if metadata else None,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get graph stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/graph/data")
async def get_graph_data(
    wiki_type: str,
    project_id: str | None = None,
    limit_nodes: int = Query(80, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return graph nodes/edges for client-side rendering."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        from app.services.wiki_operations import _load_persistent_graph

        G, page_titles, metadata = _load_persistent_graph(wiki_type, project_id)
        if not G or G.number_of_nodes() == 0:
            return {"status": "success", "nodes": [], "edges": [], "metadata": metadata or {}}

        # Keep payload bounded for UI responsiveness.
        nodes = list(G.nodes())[:limit_nodes]
        node_set = set(nodes)
        edges = []
        for source, target, attrs in G.edges(data=True):
            if source in node_set and target in node_set:
                edges.append({
                    "source": source,
                    "target": target,
                    "weight": float(attrs.get("weight", 0.5)),
                    "confidence": str(attrs.get("confidence", "INFERRED")),
                })

        return {
            "status": "success",
            "nodes": [{"id": n, "title": page_titles.get(n, n)} for n in nodes],
            "edges": edges,
            "metadata": metadata or {},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get graph data failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Dashboard Operations =====

@router.get("/{wiki_type}/stats")
async def get_wiki_stats(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    try:
        import json
        import re
        from datetime import datetime, timedelta

        from app.services.storage import workspace_path
        from app.services.wiki_operations import _get_relationship_counts

        # Determine wiki directory
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            if not project_id:
                raise HTTPException(status_code=400, detail="project_id required for project wiki")
            wiki_dir = workspace_path(project_id) / "wiki"

        by_category = {}
        by_confidence = {}
        total_pages = 0
        last_ingest = None
        pages_this_week = 0
        stale_pages = 0

        # Read wiki pages
        if wiki_dir.exists():
            now = datetime.now(UTC)
            week_ago = now - timedelta(days=7)

            for md_file in wiki_dir.glob("*.md"):
                # Skip special files
                if md_file.name in ("index.md", "log.md", "relationships.json"):
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")
                    mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=UTC)

                    # Parse frontmatter
                    category = "artifact"
                    confidence = "medium"
                    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                    if match:
                        fm_text = match.group(1)
                        for line in fm_text.split("\n"):
                            if ":" in line:
                                key, value = line.split(":", 1)
                                key = key.strip()
                                value = value.strip().strip('"')
                                if key == "category":
                                    category = value
                                elif key == "confidence":
                                    confidence = value

                    total_pages += 1
                    by_category[category] = by_category.get(category, 0) + 1
                    by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

                    if mtime > week_ago:
                        pages_this_week += 1
                    if mtime < week_ago:
                        stale_pages += 1

                    if last_ingest is None or mtime > last_ingest:
                        last_ingest = mtime.isoformat()

                except Exception as e:
                    logger.warning(f"Failed to parse wiki page {md_file.name}: {e}")
                    continue

        # Load relationship and community statistics
        from app.services.wiki_operations import _get_god_nodes
        rel_counts = _get_relationship_counts(wiki_type, project_id)
        total_relationships = 0
        pages_with_links = 0
        for _page_id, counts in rel_counts.items():
            total_relationships += counts.get("outbound", 0)
            if counts.get("inbound", 0) > 0 or counts.get("outbound", 0) > 0:
                pages_with_links += 1

        # Load community statistics
        communities_data = {}
        try:
            communities_file = wiki_dir / "communities.json"
            if communities_file.exists():
                communities_data = json.loads(communities_file.read_text())
        except Exception as e:
            logger.warning(f"Error loading communities: {e}")

        # Load god nodes statistics
        god_nodes = _get_god_nodes(wiki_type, project_id, limit=10)

        stats = {
            "total_pages": total_pages,
            "by_category": by_category,
            "by_confidence": by_confidence,
            "last_ingest": last_ingest,
            "pages_this_week": pages_this_week,
            "health": {
                "severity": "low" if stale_pages < 3 else "medium" if stale_pages < 10 else "high",
                "issues_count": stale_pages,
                "stale_pages": stale_pages,
            },
            "relationships": {
                "total_relationships": total_relationships,
                "pages_with_links": pages_with_links,
                "connectivity": round(pages_with_links / max(total_pages, 1) * 100, 1) if total_pages > 0 else 0,
            },
            "communities": {
                "total_communities": communities_data.get("total_communities", 0),
                "avg_community_size": round(
                    total_pages / max(communities_data.get("total_communities", 1), 1), 1
                ) if total_pages > 0 else 0,
            },
            "god_nodes": {
                "total": len(god_nodes),
                "top_5": [
                    {
                        "rank": gn["rank"],
                        "page_id": gn["page_id"],
                        "page_title": gn["page_title"],
                        "importance_score": gn["importance_score"],
                        "inbound_links": gn["inbound_links"],
                    }
                    for gn in god_nodes[:5]
                ],
            },
        }

        return {
            "status": "success",
            "stats": stats,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Cross-Wiki Navigation =====

@router.post("/{wiki_type}/cross-wiki/build")
async def build_cross_wiki_index(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Build cross-wiki relationship index (LP <-> Project).

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (required for project wiki)

    Returns:
        {
            "status": "success" | "error",
            "lp_to_projects": count,
            "projects_to_lp": count,
            "total_links": int,
            "error": str (if failed)
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        result = _build_cross_wiki_relationships(wiki_type, project_id)

        return {
            "status": "success",
            "lp_to_projects": len(result.get("lp_to_projects", {})),
            "projects_to_lp": len(result.get("projects_to_lp", {})),
            "total_links": result.get("total_links", 0),
        }

    except Exception as e:
        logger.error(f"Cross-wiki index build failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/cross-wiki/references/{page_id}")
async def get_cross_wiki_references(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get cross-wiki references for a page.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success" | "error",
            "page_id": str,
            "wiki_type": str,
            "incoming": [references],
            "outgoing": [references],
            "error": str (if failed)
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        refs = _get_cross_wiki_references(wiki_type, page_id, project_id)

        return {
            "status": "success",
            "page_id": page_id,
            "wiki_type": wiki_type,
            "incoming": refs.get("incoming", []),
            "outgoing": refs.get("outgoing", []),
        }

    except Exception as e:
        logger.error(f"Cross-wiki reference lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Performance Monitoring (Phase 4) =====

@router.get("/{wiki_type}/performance/metrics")
async def get_wiki_performance(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get wiki performance metrics for monitoring.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "total_pages": int,
            "relationships_count": int,
            "last_update": ISO timestamp,
            "incremental_enabled": bool,
            "manifest_version": int,
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        metrics = _get_wiki_performance_metrics(wiki_type, project_id)

        return {
            "status": "success",
            "wiki_type": wiki_type,
            **metrics,
        }

    except Exception as e:
        logger.error(f"Performance metrics query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/performance/changes")
async def detect_wiki_changes(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Detect changed pages since last index update.

    Useful for monitoring indexing efficiency.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "changed_count": int,
            "unchanged_count": int,
            "deleted_count": int,
            "changed_pages": [page_ids],
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        changed, unchanged, deleted = _detect_changed_pages(wiki_type, project_id)

        return {
            "status": "success",
            "wiki_type": wiki_type,
            "changed_count": len(changed),
            "unchanged_count": len(unchanged),
            "deleted_count": len(deleted),
            "changed_pages": list(changed.keys()),
        }

    except Exception as e:
        logger.error(f"Change detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Cache Management (Phase 5) =====

@router.get("/cache/stats")
async def get_cache_statistics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Get wiki query cache statistics.

    Returns:
        {
            "status": "success",
            "hits": int,
            "misses": int,
            "hit_rate": float (0-1),
            "query_cache": {
                "size": int,
                "max_size": int,
                "ttl_seconds": int,
            },
            "search_index": {
                "indexed_pages": int,
                "vocabulary_size": int,
            },
        }
    """
    try:
        cache = get_wiki_cache()
        stats = cache.get_stats()

        return {
            "status": "success",
            **stats,
        }

    except Exception as e:
        logger.error(f"Cache stats query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cache/invalidate")
async def invalidate_cache(
    pattern: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Invalidate cache entries.

    Args:
        pattern: If provided, invalidate entries matching pattern. If None, clear all.

    Returns:
        {
            "status": "success",
            "invalidated_count": int,
            "message": str,
        }
    """
    try:
        cache = get_wiki_cache()

        if pattern is None:
            cache.clear_all()
            return {
                "status": "success",
                "invalidated_count": 0,
                "message": "All caches cleared",
            }
        else:
            invalidated = cache.query_cache.invalidate(pattern)
            return {
                "status": "success",
                "invalidated_count": invalidated,
                "message": f"Invalidated {invalidated} entries matching pattern '{pattern}'",
            }

    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cache/warmup")
async def warmup_cache(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Pre-warm cache with hot data (god nodes, communities, etc).

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "pages_cached": int,
            "message": str,
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        # In practice, this would load god nodes and communities
        # For now, it's a placeholder that demonstrates the pattern
        get_wiki_cache()

        return {
            "status": "success",
            "pages_cached": 0,
            "message": "Cache warmup requested (implementation depends on god nodes/communities loading)",
        }

    except Exception as e:
        logger.error(f"Cache warmup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/cache/search")
async def search_wiki(
    wiki_type: str,
    query: str,
    project_id: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Search wiki using cached full-text index.

    Args:
        wiki_type: "leading_practice" or "project"
        query: Search query (space-separated terms)
        project_id: Project ID (for project wiki)
        limit: Maximum results (default 10)

    Returns:
        {
            "status": "success",
            "query": str,
            "results": [{"page_id": str, "relevance": float}],
            "result_count": int,
            "cached": bool,
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        cache = get_wiki_cache()
        results = cache.search_index.search(query, limit=limit)

        return {
            "status": "success",
            "query": query,
            "results": results,
            "result_count": len(results),
            "cached": True,
        }

    except Exception as e:
        logger.error(f"Wiki search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Analytics & Recommendations (Phase 6) =====

@router.post("/{wiki_type}/analytics/view")
async def record_page_view(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    user_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Record a page view for analytics.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Page ID being viewed
        project_id: Project ID (for project wiki)
        user_id: Optional user ID for behavior tracking

    Returns:
        {
            "status": "success",
            "page_id": str,
            "recorded_at": ISO timestamp
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        recommender.analytics.record_view(page_id, user_id=user_id)

        return {
            "status": "success",
            "page_id": page_id,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        logger.error(f"Record view failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/analytics/search")
async def record_search(
    wiki_type: str,
    query: str,
    result_count: int = 0,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Record a search query for analytics.

    Args:
        wiki_type: "leading_practice" or "project"
        query: Search query text
        result_count: Number of results returned
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "query": str,
            "recorded_at": ISO timestamp
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        recommender.analytics.record_search(query, result_count=result_count)

        return {
            "status": "success",
            "query": query,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        logger.error(f"Record search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/analytics/popular-pages")
async def get_popular_pages(
    wiki_type: str,
    project_id: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get most viewed pages (trending).

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)
        limit: Max results (default 10)

    Returns:
        {
            "status": "success",
            "popular_pages": [
                {"page_id": str, "view_count": int},
                ...
            ],
            "count": int
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        popular = recommender.analytics.get_popular_pages(limit=limit)

        return {
            "status": "success",
            "popular_pages": popular,
            "count": len(popular),
        }

    except Exception as e:
        logger.error(f"Get popular pages failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/analytics/trending-searches")
async def get_trending_searches(
    wiki_type: str,
    project_id: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get trending search queries.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)
        limit: Max results (default 10)

    Returns:
        {
            "status": "success",
            "trending_searches": [
                {"query": str, "count": int},
                ...
            ],
            "count": int
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        trending = recommender.analytics.get_trending_searches(limit=limit)

        return {
            "status": "success",
            "trending_searches": trending,
            "count": len(trending),
        }

    except Exception as e:
        logger.error(f"Get trending searches failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/recommendations/{page_id}")
async def get_page_recommendations(
    wiki_type: str,
    page_id: str,
    project_id: str | None = None,
    user_id: str | None = None,
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get recommendations for a specific page.

    Returns related pages, personalized recommendations, missing pages, and trending pages.

    Args:
        wiki_type: "leading_practice" or "project"
        page_id: Current page ID
        project_id: Project ID (for project wiki)
        user_id: Optional user ID for personalized recommendations
        limit: Max results per recommendation type (default 5)

    Returns:
        {
            "status": "success",
            "page_id": str,
            "related_pages": [
                {"page_id": str, "distance": int, "relevance": float},
                ...
            ],
            "personalized_recommendations": [
                {"page_id": str, "score": float, "reason": str},
                ...
            ],
            "missing_pages": [
                {"concept": str, "mentions": int, "suggested_action": str},
                ...
            ],
            "trending_pages": [
                {"page_id": str, "view_count": int},
                ...
            ]
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()

        # Get user's viewed pages if user_id provided
        user_pages = None
        if user_id:
            user_pages = recommender.analytics.get_user_pages(user_id)

        recs = recommender.get_recommendations(
            page_id=page_id,
            user_id=user_id,
            user_pages=user_pages,
        )

        return {
            "status": "success",
            "page_id": page_id,
            "related_pages": recs["related_pages"][:limit],
            "personalized_recommendations": recs["personalized_recommendations"][:limit],
            "missing_pages": recs["missing_pages"][:3],
            "trending_pages": recs["trending_pages"][:limit],
        }

    except Exception as e:
        logger.error(f"Get recommendations failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/analytics/update")
async def update_analytics_from_wiki(
    wiki_type: str,
    pages: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Update recommender with current wiki state.

    Args:
        wiki_type: "leading_practice" or "project"
        pages: List of wiki pages (with id, title, content)
        relationships: List of relationships (with source_id, target_id)
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "pages_indexed": int,
            "relationships_loaded": int,
            "updated_at": ISO timestamp
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        recommender.update_from_wiki(pages, relationships)

        return {
            "status": "success",
            "pages_indexed": len(pages),
            "relationships_loaded": len(relationships),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        logger.error(f"Update analytics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{wiki_type}/insights")
async def get_wiki_insights(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get comprehensive wiki insights and analytics.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Project ID (for project wiki)

    Returns:
        {
            "status": "success",
            "analytics": {
                "total_views": int,
                "unique_pages_viewed": int,
                "total_searches": int,
                "unique_searches": int,
                "tracked_users": int
            },
            "recommendation_engine": {
                "graph_nodes": int,
                "graph_edges": int,
                "avg_degree": float
            },
            "coverage": {
                "total_pages": int,
                "total_concepts": int,
                "covered_concepts": int,
                "coverage_percentage": float,
                "missing_concepts": int
            }
        }
    """
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if wiki_type not in ["leading_practice", "project"]:
        raise HTTPException(status_code=400, detail="Invalid wiki_type")

    if wiki_type == "project" and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    try:
        recommender = get_wiki_recommender()
        insights = recommender.get_insights()

        return {
            "status": "success",
            **insights,
        }

    except Exception as e:
        logger.error(f"Get insights failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===== Schema, synthesis & refresh =====

@router.get("/{wiki_type}/schema/analyze")
async def analyze_wiki_schema(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze wiki content against schema conventions and suggest evolution."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.wiki_schema_analyzer import analyze_schema

    return analyze_schema(wiki_type, project_id)


@router.get("/{wiki_type}/schema", response_class=PlainTextResponse)
async def get_wiki_schema_markdown(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Return ``WIKI_SCHEMA.md`` for editing in the UI."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.storage import workspace_path
    from app.services.wiki_ingest import _ensure_wiki_schema

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required for project wiki")
        wiki_dir = workspace_path(project_id) / "wiki"

    wiki_dir.mkdir(parents=True, exist_ok=True)
    _ensure_wiki_schema(wiki_dir)
    schema_path = wiki_dir / "WIKI_SCHEMA.md"
    text = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@router.put("/{wiki_type}/schema")
async def put_wiki_schema_markdown(
    wiki_type: str,
    payload: dict[str, Any],
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Replace ``WIKI_SCHEMA.md`` (conventions for ingest/query)."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="JSON body must include string 'content'")

    from app.services.storage import workspace_path
    from app.services.wiki_ingest import _ensure_wiki_schema

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required for project wiki")
        wiki_dir = workspace_path(project_id) / "wiki"

    wiki_dir.mkdir(parents=True, exist_ok=True)
    _ensure_wiki_schema(wiki_dir)
    (wiki_dir / "WIKI_SCHEMA.md").write_text(content, encoding="utf-8")
    return {"status": "success"}


@router.get("/{wiki_type}/synthesis/insights")
async def get_wiki_synthesis_insights(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_synthesis import get_synthesis_insights

    data = get_synthesis_insights(wiki_type, project_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "synthesis failed"))
    return data


@router.post("/{wiki_type}/synthesis/create")
async def create_wiki_synthesis_pages(
    wiki_type: str,
    project_id: str | None = None,
    max_pages: int = Query(5, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.wiki_synthesis import create_synthesis_pages

    data = create_synthesis_pages(wiki_type, project_id, max_pages=max_pages)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "synthesis create failed"))
    return data


@router.get("/{wiki_type}/refresh/schedule")
async def get_wiki_refresh_schedule(
    wiki_type: str,
    project_id: str | None = None,
    batch_size: int = Query(10, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_refresh import get_refresh_schedule

    return get_refresh_schedule(wiki_type, project_id, batch_size=batch_size)


@router.post("/{wiki_type}/sources/check-freshness")
async def post_wiki_check_source_freshness(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_refresh import check_wiki_source_freshness

    data = check_wiki_source_freshness(wiki_type, project_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "freshness check failed"))
    return data


# ===== Health Check =====

@router.get("/health")
async def health_check(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "wiki",
        "version": "1.0.0",
    }


# Register router in main app
__all__ = ["router"]
