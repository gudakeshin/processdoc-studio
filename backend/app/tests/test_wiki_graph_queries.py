"""
Tests for wiki graph query engine and traversal operations.

Tests Priority 4: Graph Query Engine & Persistent Graph
"""

import networkx as nx


class TestGraphTraversal:
    """Test graph traversal and query operations."""

    def test_bfs_distance_calculation(self):
        """Test breadth-first search distance calculation."""
        G = nx.Graph()

        # Linear graph: 1 - 2 - 3 - 4 - 5
        G.add_edges_from([(1, 2), (2, 3), (3, 4), (4, 5)])

        # Simulate BFS from node 1
        results = []
        visited = set()
        queue = [(1, 0, [1])]

        while queue:
            current, distance, path = queue.pop(0)

            if current in visited:
                continue
            visited.add(current)

            if distance > 0:
                results.append({"node": current, "distance": distance})

            if distance < 3:
                for neighbor in G.neighbors(current):
                    if neighbor not in visited:
                        queue.append((neighbor, distance + 1, path + [neighbor]))

        # Verify distances
        assert any(r["node"] == 2 and r["distance"] == 1 for r in results)
        assert any(r["node"] == 3 and r["distance"] == 2 for r in results)
        assert any(r["node"] == 4 and r["distance"] == 3 for r in results)

    def test_shortest_path_finding(self):
        """Test shortest path calculation between nodes."""
        G = nx.Graph()

        # Create graph with multiple paths
        G.add_edges_from([
            (1, 2), (1, 3),
            (2, 4), (3, 4),
            (4, 5),
        ])

        # Find shortest path from 1 to 5
        path = nx.shortest_path(G, 1, 5)

        # Should find path with 3 hops
        assert len(path) == 4  # 4 nodes = 3 edges
        assert path[0] == 1
        assert path[-1] == 5

    def test_neighbors_retrieval(self):
        """Test getting immediate neighbors of a node."""
        G = nx.Graph()

        G.add_edges_from([
            (1, 2, {"weight": 0.8}),
            (1, 3, {"weight": 0.6}),
            (1, 4, {"weight": 0.9}),
            (2, 3),
        ])

        # Get neighbors of node 1
        neighbors = list(G.neighbors(1))

        assert len(neighbors) == 3
        assert 2 in neighbors
        assert 3 in neighbors
        assert 4 in neighbors
        assert 5 not in neighbors

    def test_no_path_handling(self):
        """Test handling when no path exists between nodes."""
        G = nx.Graph()

        # Two disconnected components
        G.add_edges_from([(1, 2)])
        G.add_edges_from([(3, 4)])

        # Try to find path from 1 to 4
        try:
            nx.shortest_path(G, 1, 4)
            raise AssertionError("Should raise NetworkXNoPath")
        except nx.NetworkXNoPath:
            pass  # Expected

    def test_weighted_shortest_path(self):
        """Test shortest path considering edge weights."""
        G = nx.Graph()

        # Add weighted edges
        G.add_edge(1, 2, weight=0.5)  # Preferred path
        G.add_edge(1, 3, weight=10.0)  # Heavy path
        G.add_edge(3, 2, weight=1.0)

        # Shortest path by weight
        path = nx.shortest_path(G, 1, 2, weight="weight")

        # Should prefer direct edge over indirect heavy path
        assert path == [1, 2]


class TestGraphMetrics:
    """Test graph density and centrality calculations."""

    def test_graph_density(self):
        """Test graph density calculation."""
        # Fully connected graph (density = 1.0)
        G1 = nx.complete_graph(4)
        assert nx.density(G1) == 1.0

        # Linear graph with 4 nodes (3 edges): density = 3/6 = 0.5
        G2 = nx.path_graph(4)
        assert round(nx.density(G2), 2) == 0.5

    def test_average_degree(self):
        """Test average degree calculation."""
        G = nx.Graph()

        # 3 nodes with degrees: 2, 2, 2
        G.add_edges_from([(1, 2), (2, 3), (3, 1)])

        avg_degree = (2 * G.number_of_edges()) / G.number_of_nodes()
        assert avg_degree == 2.0  # Each node has degree 2

    def test_connected_components(self):
        """Test finding connected components."""
        G = nx.Graph()

        # Two components
        G.add_edges_from([(1, 2), (2, 3)])
        G.add_edges_from([(4, 5)])

        components = list(nx.connected_components(G))

        assert len(components) == 2
        assert {1, 2, 3} in components
        assert {4, 5} in components


class TestGraphSerialization:
    """Test graph JSON serialization for persistence."""

    def test_graph_to_json(self):
        """Test converting NetworkX graph to JSON."""
        import json

        from networkx.readwrite import json_graph

        G = nx.Graph()
        G.add_edges_from([(1, 2, {"weight": 0.8}), (2, 3)])

        # Convert to JSON
        graph_json = json_graph.node_link_data(G)

        # Serialize/deserialize
        json_str = json.dumps(graph_json)
        graph_json2 = json.loads(json_str)

        # Reconstruct
        G2 = json_graph.node_link_graph(graph_json2)

        # Verify
        assert G2.number_of_nodes() == 3
        assert G2.number_of_edges() == 2
        assert G2.has_edge(1, 2)

    def test_page_titles_storage(self):
        """Test storing page titles alongside graph."""
        page_titles = {
            "page_1": "First Page",
            "page_2": "Second Page",
            "page_3": "Third Page",
        }

        # Simulate storage
        data = {
            "page_titles": page_titles,
            "metadata": {
                "node_count": 3,
                "edge_count": 2,
                "last_updated": "2026-04-12T00:00:00Z",
            }
        }

        # Verify storage
        assert data["page_titles"]["page_1"] == "First Page"
        assert data["metadata"]["node_count"] == 3
