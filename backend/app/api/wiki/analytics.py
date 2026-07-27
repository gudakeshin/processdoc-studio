"""Wiki dashboard, cross-wiki, performance, cache, and analytics routes.

Moved verbatim from the former single-module app/api/wiki.py.
"""

from datetime import datetime
from typing import Any
import json
import re

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.wiki._common import logger, _wiki_dir_for, _wiki_require_access
from app.api.wiki._router import router
from app.api.wiki.graph import validate_wiki_relationships_route
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.tz import IST
from app.db.models import User
from app.db.session import get_db
from app.services.wiki_analytics import get_wiki_recommender
from app.services.wiki_cache import get_wiki_cache
from app.services.wiki_lint import get_lint_summary
from app.services.wiki_operations import _build_cross_wiki_relationships, _detect_changed_pages, _get_cross_wiki_references, _get_wiki_performance_metrics


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
            now = datetime.now(IST)
            week_ago = now - timedelta(days=7)

            for md_file in wiki_dir.glob("*.md"):
                # Skip special files
                if md_file.name in ("index.md", "log.md", "relationships.json"):
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")
                    mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=IST)

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
                        last_ingest = mtime

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
            "last_ingest": last_ingest.isoformat() if last_ingest is not None else None,
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


@router.get("/{wiki_type}/health/scorecard")
async def get_wiki_health_scorecard(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Unified health scorecard for wiki quality and freshness."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not bool(getattr(settings, "wiki_health_scorecard_enabled", True)):
        raise HTTPException(status_code=404, detail="Wiki health scorecard is disabled")
    try:
        stats_payload = await get_wiki_stats(wiki_type, project_id, user=user, db=db)
        validation = await validate_wiki_relationships_route(wiki_type, project_id, user=user, db=db)
        lint_summary = get_lint_summary(wiki_type, project_id)
        wiki_dir = _wiki_dir_for(wiki_type, project_id)
        maintenance_log = wiki_dir / "maintenance.log"
        maintenance_updated_at = None
        if maintenance_log.exists():
            maintenance_updated_at = datetime.fromtimestamp(maintenance_log.stat().st_mtime, tz=IST).isoformat()
        return {
            "status": "success",
            "scorecard": {
                "stats": stats_payload.get("stats", {}),
                "relationship_validation": {
                    "total_relationships": validation.get("total_relationships", 0),
                    "issues_count": len(validation.get("issues", [])),
                    "by_type": validation.get("by_type", {}),
                },
                "lint": lint_summary,
                "freshness": {
                    "last_ingest": stats_payload.get("stats", {}).get("last_ingest"),
                    "maintenance_updated_at": maintenance_updated_at,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scorecard query failed: {e}")
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
        from app.services.wiki_operations import _get_god_nodes

        # Touch the cache singleton and load the hot data sets (god nodes +
        # cross-wiki relationships). Both calls populate/persist their caches.
        get_wiki_cache()
        god_nodes = _get_god_nodes(wiki_type, project_id, limit=50)
        relationships = _build_cross_wiki_relationships(wiki_type, project_id)
        total_links = relationships.get("total_links", 0) if isinstance(relationships, dict) else 0

        return {
            "status": "success",
            "pages_cached": len(god_nodes),
            "relationships_cached": total_links,
            "message": f"Warmed {len(god_nodes)} god nodes and {total_links} cross-wiki links",
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
            "recorded_at": datetime.now(IST).isoformat(),
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
            "recorded_at": datetime.now(IST).isoformat(),
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
            "updated_at": datetime.now(IST).isoformat(),
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
