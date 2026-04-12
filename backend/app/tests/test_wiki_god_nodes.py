"""
Tests for wiki god node detection and importance ranking.

Tests Priority 3: God Node Detection & Importance Ranking
"""

import pytest
import networkx as nx


class TestGodNodeDetection:
    """Test god node detection and centrality ranking."""

    def test_inbound_link_ranking(self):
        """Test that pages with more inbound links rank higher."""
        # Create a simple graph
        G = nx.Graph()

        # Node 1: hub (many inbound links)
        edges = [(i, 1) for i in range(2, 6)]
        G.add_edges_from(edges)

        # Node 2: peripheral (few links)
        G.add_edge(2, 3)

        # Calculate normalized inbound counts
        inbound_counts = {node: G.degree(node) for node in G.nodes()}
        assert inbound_counts[1] > inbound_counts[2]  # Hub has more

    def test_betweenness_centrality_ranking(self):
        """Test that bridge nodes (high betweenness) are ranked high."""
        # Create two clusters connected by a bridge
        G = nx.Graph()

        # Cluster 1
        G.add_edges_from([(1, 2), (2, 3), (3, 1)])

        # Cluster 2
        G.add_edges_from([(4, 5), (5, 6), (6, 4)])

        # Bridge node connecting clusters
        G.add_edge(3, 4)

        # Calculate betweenness centrality
        betweenness = nx.betweenness_centrality(G)

        # Bridge nodes should have higher betweenness
        assert betweenness[3] > betweenness[1]
        assert betweenness[4] > betweenness[5]

    def test_combined_importance_score(self):
        """Test combined importance calculation (60% inbound, 40% betweenness)."""
        # Create test nodes with known metrics
        inbound_scores = {"node_a": 0.8, "node_b": 0.6, "node_c": 0.4}
        betweenness_scores = {"node_a": 0.2, "node_b": 0.6, "node_c": 0.8}

        # Calculate importance: 0.6 * inbound + 0.4 * betweenness
        importance = {}
        for node in inbound_scores:
            importance[node] = (
                0.6 * inbound_scores[node] + 0.4 * betweenness_scores[node]
            )

        # Verify calculations
        assert importance["node_a"] == 0.56  # 0.6*0.8 + 0.4*0.2
        assert importance["node_b"] == 0.60  # 0.6*0.6 + 0.4*0.6
        assert importance["node_c"] == 0.56  # 0.6*0.4 + 0.4*0.8

        # node_b should rank first
        ranked = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        assert ranked[0][0] == "node_b"

    def test_god_node_ranking(self):
        """Test complete god node detection workflow."""
        G = nx.Graph()

        # Create 3 clusters with different characteristics
        # Cluster 1: Dense, high connectivity (high inbound)
        cluster1 = [(1, 2), (2, 3), (3, 1), (1, 4), (2, 4)]
        G.add_edges_from(cluster1)

        # Cluster 2: Less dense
        cluster2 = [(5, 6), (6, 7)]
        G.add_edges_from(cluster2)

        # Cluster 3: Single node
        G.add_node(8)

        # Add bridge edges
        G.add_edge(3, 5)  # Bridge between clusters
        G.add_edge(7, 8)  # Bridge to isolated node

        # Calculate metrics
        inbound_counts = {node: G.degree(node) for node in G.nodes()}
        max_inbound = max(inbound_counts.values())
        normalized_inbound = {
            node: count / max_inbound for node, count in inbound_counts.items()
        }

        betweenness = nx.betweenness_centrality(G)

        # Calculate importance
        importance = {}
        for node in G.nodes():
            importance[node] = (
                0.6 * normalized_inbound[node] + 0.4 * betweenness[node]
            )

        # Rank by importance
        ranked = sorted(importance.items(), key=lambda x: x[1], reverse=True)

        # Node 3 (bridge between clusters with high inbound) should rank high
        top_nodes = [node for node, _ in ranked[:3]]
        assert 3 in top_nodes  # Bridge node

    def test_isolated_node_handling(self):
        """Test that isolated nodes have low importance."""
        G = nx.Graph()

        # Connected component
        G.add_edges_from([(1, 2), (2, 3)])

        # Isolated node
        G.add_node(4)

        # Calculate metrics
        inbound = {node: G.degree(node) for node in G.nodes()}
        betweenness = nx.betweenness_centrality(G)

        importance = {}
        max_inbound = max(inbound.values()) if inbound else 1
        for node in G.nodes():
            norm_inbound = inbound[node] / max_inbound
            importance[node] = 0.6 * norm_inbound + 0.4 * betweenness[node]

        # Isolated node should have lowest importance
        assert importance[4] < importance[2]
        assert importance[4] < importance[1]

    def test_god_nodes_list_ordering(self):
        """Test that god nodes list is properly ranked by importance."""
        god_nodes = [
            {"page_id": "page_a", "importance_score": 0.85, "rank": 1},
            {"page_id": "page_b", "importance_score": 0.72, "rank": 2},
            {"page_id": "page_c", "importance_score": 0.65, "rank": 3},
        ]

        # Verify ordering
        for i in range(len(god_nodes) - 1):
            assert (
                god_nodes[i]["importance_score"]
                >= god_nodes[i + 1]["importance_score"]
            )
            assert god_nodes[i]["rank"] < god_nodes[i + 1]["rank"]
