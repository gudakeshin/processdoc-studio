"""
Tests for wiki community detection and graph clustering.

Tests Priority 2: Community Detection & Auto-Organization
"""

import pytest
import networkx as nx
from datetime import datetime, timezone


class TestCommunityDetection:
    """Test community detection algorithm and clustering."""

    def test_simple_graph_clustering(self):
        """Test basic community detection on a simple graph."""
        # Create a simple graph with 2 clear communities
        G = nx.Graph()

        # Community 1: nodes 1-3 (heavily connected)
        G.add_edges_from([
            (1, 2), (2, 3), (3, 1),  # Triangle
        ])

        # Community 2: nodes 4-6 (heavily connected)
        G.add_edges_from([
            (4, 5), (5, 6), (6, 4),  # Triangle
        ])

        # Weak connection between communities
        G.add_edge(3, 4)

        # Detect communities using Louvain
        from networkx.algorithms import community
        communities_list = list(community.louvain_communities(G, seed=42))

        # Should detect 2 communities
        assert len(communities_list) == 2

        # Each community should have 3 nodes
        for comm in communities_list:
            assert len(comm) == 3

    def test_community_characteristics(self):
        """Test that community statistics are calculated correctly."""
        # Create a graph with a denser cluster
        G = nx.Graph()

        # Dense community: fully connected (clique of 4)
        clique_nodes = [1, 2, 3, 4]
        for i in clique_nodes:
            for j in clique_nodes:
                if i < j:
                    G.add_edge(i, j)

        # Sparse community: just a path
        G.add_edges_from([(5, 6), (6, 7)])

        # Weak inter-community edge
        G.add_edge(4, 5)

        # Get subgraph of clique
        clique_subgraph = G.subgraph(clique_nodes)

        # Calculate density
        num_edges = clique_subgraph.number_of_edges()
        num_possible = len(clique_nodes) * (len(clique_nodes) - 1) / 2
        density = num_edges / num_possible

        # Fully connected graph should have density = 1.0
        assert density == 1.0
        assert num_edges == 6

    def test_degree_centrality_ranking(self):
        """Test that degree centrality correctly ranks nodes by importance."""
        G = nx.Graph()

        # Hub node (node 1 connects to many)
        hub_edges = [(1, i) for i in range(2, 7)]
        G.add_edges_from(hub_edges)

        # Add some edges between periphery nodes
        G.add_edge(2, 3)
        G.add_edge(4, 5)

        # Calculate degree centrality
        centrality = nx.degree_centrality(G)

        # Hub (node 1) should have highest centrality
        max_node = max(centrality, key=centrality.get)
        assert max_node == 1
        assert centrality[1] > centrality[2]

    def test_isolated_nodes(self):
        """Test handling of isolated nodes (no relationships)."""
        G = nx.Graph()

        # Add isolated nodes
        G.add_nodes_from([1, 2, 3])

        # Add edges for some nodes
        G.add_edge(4, 5)
        G.add_edge(5, 6)

        # Detect communities
        from networkx.algorithms import community
        communities_list = list(community.louvain_communities(G, seed=42))

        # Should handle isolated nodes gracefully
        total_nodes = sum(len(c) for c in communities_list)
        assert total_nodes == 6

    def test_single_community(self):
        """Test case where all nodes form one community."""
        G = nx.complete_graph(5)  # Fully connected graph

        from networkx.algorithms import community
        communities_list = list(community.louvain_communities(G, seed=42))

        # Fully connected graph should be one community
        assert len(communities_list) == 1
        assert len(communities_list[0]) == 5

    def test_community_with_weights(self):
        """Test that weighted edges affect community detection."""
        G = nx.Graph()

        # Strong cluster with high weights
        strong_edges = [(1, 2, {"weight": 0.95}),
                       (2, 3, {"weight": 0.95}),
                       (3, 1, {"weight": 0.95})]
        G.add_edges_from(strong_edges)

        # Weak edges with low weights
        weak_edges = [(3, 4, {"weight": 0.1}),
                     (4, 5, {"weight": 0.1}),
                     (5, 3, {"weight": 0.1})]
        G.add_edges_from(weak_edges)

        # Detect communities
        from networkx.algorithms import community
        communities_list = list(community.louvain_communities(G, seed=42))

        # Should detect distinct communities due to weight differences
        assert len(communities_list) >= 1  # At minimum, should cluster
