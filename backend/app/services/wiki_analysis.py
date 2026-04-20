"""
wiki_analysis.py — Wiki graph analysis helpers.

Handles community detection, god node detection, graph queries,
and performance metrics. All state files use the .meta/ subdirectory.
"""
import json
import logging
from datetime import UTC

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

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

        # Load relationships from .meta/
        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
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
        from app.services.wiki_graph import _load_page_manifest
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
        _LOG.warning(f"Error getting performance metrics: {e}")
        return {
            "total_pages": 0,
            "relationships_count": 0,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

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

        # Load relationships from .meta/
        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
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
        _LOG.error(f"Error detecting communities: {e}")
        return {
            "total_communities": 0,
            "communities": {},
            "page_community_map": {},
        }


# ---------------------------------------------------------------------------
# God node detection
# ---------------------------------------------------------------------------

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

        # Load relationships from .meta/
        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
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
        _LOG.error(f"Error detecting god nodes: {e}")
        return {"god_nodes": [], "total_pages": 0, "avg_importance": 0.0}


def _save_god_nodes(
    wiki_type: str,
    project_id: str | None,
    god_nodes_data: dict,
) -> bool:
    """Save god nodes (important pages) to .meta/god_nodes.json."""
    try:
        from datetime import datetime

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        meta_dir = wiki_dir / ".meta"
        meta_dir.mkdir(exist_ok=True)
        god_nodes_file = meta_dir / "god_nodes.json"

        god_nodes_file.write_text(json.dumps({
            "total_pages": god_nodes_data["total_pages"],
            "avg_importance": god_nodes_data["avg_importance"],
            "god_nodes": god_nodes_data["god_nodes"],
            "last_updated": datetime.now(UTC).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        _LOG.error(f"Error saving god nodes: {e}")
        return False


# ---------------------------------------------------------------------------
# Graph loading & querying
# ---------------------------------------------------------------------------

def load_wiki_graph(wiki_type: str, project_id: str | None) -> tuple:
    """
    Load wiki relationship graph from .meta/relationships.json.

    Returns:
        (G, page_titles): NetworkX graph and mapping of page_id to page_title
    """
    from app.services.wiki_graph import _load_wiki_graph as _graph_load
    return _graph_load(wiki_type, project_id)


def _query_graph_bfs(
    G,
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
        _LOG.warning(f"Error in BFS: {e}")
        return []


def _query_graph_shortest_path(
    G,
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
        _LOG.warning(f"Error finding shortest path: {e}")
        return None


def _query_graph_neighbors(
    G,
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
        _LOG.warning(f"Error getting neighbors: {e}")
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
        G, page_titles = load_wiki_graph(wiki_type, project_id)

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
        _LOG.error(f"Error executing graph query: {e}")
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

        # Check .meta/ first, fall back to old location
        god_nodes_file = wiki_dir / ".meta" / "god_nodes.json"
        if not god_nodes_file.exists():
            god_nodes_file = wiki_dir / "god_nodes.json"
        if not god_nodes_file.exists():
            return []

        god_nodes_data = json.loads(god_nodes_file.read_text())
        return god_nodes_data.get("god_nodes", [])[:limit]
    except Exception as e:
        _LOG.warning(f"Error loading god nodes: {e}")
        return []


def _save_communities(
    wiki_type: str,
    project_id: str | None,
    communities_data: dict,
) -> bool:
    """Save community assignments to .meta/communities.json."""
    try:
        from datetime import datetime

        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        meta_dir = wiki_dir / ".meta"
        meta_dir.mkdir(exist_ok=True)
        communities_file = meta_dir / "communities.json"

        communities_file.write_text(json.dumps({
            "total_communities": communities_data["total_communities"],
            "communities": communities_data["communities"],
            "page_community_map": communities_data["page_community_map"],
            "last_updated": datetime.now(UTC).isoformat(),
        }, indent=2))

        return True
    except Exception as e:
        _LOG.error(f"Error saving communities: {e}")
        return False


def _get_community_for_page(wiki_type: str, project_id: str | None, page_id: str) -> dict | None:
    """Get community information for a specific page."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        # Check .meta/ first, fall back to old location
        communities_file = wiki_dir / ".meta" / "communities.json"
        if not communities_file.exists():
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
        _LOG.warning(f"Error loading community for page {page_id}: {e}")
        return None


def get_relationship_counts(wiki_type: str, project_id: str | None) -> dict:
    """
    Load relationship statistics from .meta/relationships.json.

    Returns dict with inbound/outbound counts per page.
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        # Check .meta/ first, fall back to old location
        relationships_file = wiki_dir / ".meta" / "relationships.json"
        if not relationships_file.exists():
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
        _LOG.warning(f"Error loading relationship counts: {e}")
        return {}
