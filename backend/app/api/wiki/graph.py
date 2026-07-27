"""Wiki relationship, community, god-node, and graph query/stats/data routes.

Moved verbatim from the former single-module app/api/wiki.py.
"""

from datetime import datetime
from typing import Any
import json
import re

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.wiki._common import logger, _wiki_require_access
from app.api.wiki._router import router
from app.core.auth import get_current_user
from app.db.models import User
from app.db.session import get_db


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
