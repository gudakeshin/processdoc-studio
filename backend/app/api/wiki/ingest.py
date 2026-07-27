"""Wiki ingest, document sync, orphan cleanup, vault, and artifact listing routes.

Moved verbatim from the former single-module app/api/wiki.py.
"""

from typing import Any
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.wiki._common import logger, _PAGE_STEM_RE, _wiki_require_access
from app.api.wiki._router import router
from app.core.auth import get_current_user
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.services.langfuse_tracing import langfuse_event, langfuse_span
from app.services.wiki_integrations import WikiConversationIntegration, WikiRunIntegration
from app.services.wiki_operations import wiki_ingest_with_retry

import logging
logger = logging.getLogger(__name__)


# ===== Ingest Operations =====

@router.post("/{wiki_type}/ingest")
@limiter.limit("10/minute")
async def ingest_source(
    request: Request,
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

    trace_id = project_id or f"lp:{wiki_type}"
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
            logger.warning("Wiki ingest failed for %s/%s: %s", wiki_type, source_type, error)
            langfuse_event(
                trace_id=trace_id,
                name="wiki.ingest.error",
                level="WARNING",
                metadata={"wiki_type": wiki_type, "source_type": source_type, "error": error},
            )
            return {
                "status": "error",
                "error": error,
            }

        langfuse_span(
            trace_id=trace_id,
            name="wiki.ingest",
            input_payload={"wiki_type": wiki_type, "source_type": source_type},
            output_payload={
                "pages_created": result.get("pages_created", 0),
                "pages_updated": result.get("pages_updated", 0),
                "corrections_made": result.get("corrections_made", 0),
            },
        )
        return {
            "status": "success",
            "pages_created": result.get("pages_created", 0),
            "pages_updated": result.get("pages_updated", 0),
            "corrections_made": result.get("corrections_made", 0),
            "log_entry_id": result.get("log_entry_id"),
        }

    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        langfuse_event(
            trace_id=trace_id,
            name="wiki.ingest.error",
            level="ERROR",
            metadata={"wiki_type": wiki_type, "source_type": source_type, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{wiki_type}/ingest/from-memory")
@limiter.limit("10/minute")
async def ingest_memory_item(
    request: Request,
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

    return {
        "status": "success",
        "ingested": ingested,
        "synced": ingested,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/{wiki_type}/cleanup-orphans")
async def cleanup_orphan_wiki_pages(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete wiki pages that are unclassified, not user-edited, and have no incoming links."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.storage import workspace_path
    from app.services.wiki_ingest import _is_user_edited_page, _read_frontmatter_field

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    elif project_id:
        wiki_dir = workspace_path(project_id) / "wiki"
    else:
        raise HTTPException(status_code=400, detail="project_id required for project wiki")

    if not wiki_dir.is_dir():
        return {"status": "success", "deleted": 0, "kept": 0, "pages": []}

    md_files = [f for f in wiki_dir.glob("*.md")
                if f.name not in ("index.md", "log.md", "WIKI_SCHEMA.md")]

    # Build set of page_ids referenced by [[page_id|...]] anywhere in the wiki.
    referenced: set[str] = set()
    link_re = re.compile(r"\[\[([a-z0-9_]+)(?:\|[^\]]*)?\]\]")
    for f in md_files:
        try:
            for m in link_re.finditer(f.read_text(encoding="utf-8")):
                if m.group(1) != f.stem:
                    referenced.add(m.group(1))
        except Exception as exc:
            logger.debug("%s: suppressed error: %s", 'cleanup_orphan_wiki_pages', exc)
            continue

    deleted: list[str] = []
    kept = 0
    for f in md_files:
        category = _read_frontmatter_field(f, "category")
        if category != "unclassified":
            kept += 1
            continue
        if _is_user_edited_page(f):
            kept += 1
            continue
        if f.stem in referenced:
            kept += 1
            continue
        try:
            f.unlink()
            deleted.append(f.stem)
        except Exception as exc:
            logger.warning(f"Failed to delete orphan wiki page {f}: {exc}")
            kept += 1

    return {
        "status": "success",
        "deleted": len(deleted),
        "kept": kept,
        "pages": deleted,
    }


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
