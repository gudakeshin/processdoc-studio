"""Wiki page browse, preview, related, detail, search, and promote routes.

Moved verbatim from the former single-module app/api/wiki.py.
"""

from datetime import datetime
from typing import Any
import json
import re

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.wiki._common import logger, _PAGE_STEM_RE, _wiki_require_access
from app.api.wiki._router import router
from app.core.auth import get_current_user
from app.core.tz import IST
from app.db.models import User
from app.db.session import get_db
from app.services.wiki_integrations import WikiLeadingPracticesIntegration


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
    updated_at = datetime.fromtimestamp(updated_ts, tz=IST).isoformat()

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
    """Related pages via typed relationships, community, and synthesis (Second Brain discovery)."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not _PAGE_STEM_RE.match(page_id):
        raise HTTPException(status_code=400, detail="Invalid page_id")

    import json
    from app.services.storage import workspace_path
    from app.services.wiki_relationships import RelationshipGraph, get_transitive_related_pages

    related_pages: list[dict[str, Any]] = []

    # 1. Typed relationships (existing)
    related_ids = get_transitive_related_pages(page_id, wiki_type, project_id, max_depth=max_depth)
    graph = RelationshipGraph(wiki_type, project_id)
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
        related_pages.append({"page_id": tid, "relation_type": rtype, "confidence": conf, "source": "relationship"})

    # 2. Community peers (Louvain clustering)
    try:
        if wiki_type == "leading_practice":
            communities_file = workspace_path("leading_practices") / "wiki" / ".meta" / "communities.json"
        else:
            communities_file = workspace_path(project_id) / "wiki" / ".meta" / "communities.json"

        if communities_file.exists():
            communities = json.loads(communities_file.read_text(encoding="utf-8"))
            page_community = communities.get(page_id)
            if page_community is not None:
                for other_id, other_comm in communities.items():
                    if other_comm == page_community and other_id != page_id:
                        # Check if already in related_pages
                        if not any(p["page_id"] == other_id for p in related_pages):
                            related_pages.append({
                                "page_id": other_id,
                                "relation_type": "community_peer",
                                "confidence": 0.7,
                                "source": "community"
                            })
    except Exception:
        pass  # Community data not available

    # 3. Synthesis pages referencing this page
    try:
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        for md_file in wiki_dir.glob("synthesis_*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if f"[[{page_id}" in content or f"|{page_id}]" in content or page_id in content:
                    synth_id = md_file.stem
                    if not any(p["page_id"] == synth_id for p in related_pages):
                        related_pages.append({
                            "page_id": synth_id,
                            "relation_type": "synthesis",
                            "confidence": 0.8,
                            "source": "synthesis"
                        })
            except Exception:
                pass
    except Exception:
        pass  # Synthesis scanning not available

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
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=IST).isoformat()
        created_at = datetime.fromtimestamp(stat.st_ctime, tz=IST).isoformat()

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
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=IST).isoformat()

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
