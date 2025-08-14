# core/partition_fallback.py
import networkx as nx
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, LineString
from sklearn.cluster import SpectralClustering


def spectral_partition(G, k):
    """
    Perform simple spectral clustering as a fallback partitioning method
    when KaHIP is not available.

    Args:
        G (nx.Graph): Input graph.
        k (int): Number of partitions/clusters.

    Returns:
        dict: Mapping of node -> assigned partition index.
    """
    # Create adjacency matrix from the graph
    A = nx.to_numpy_array(G)

    # Apply spectral clustering on the adjacency matrix
    sc = SpectralClustering(
        n_clusters=k,
        affinity='precomputed',
        assign_labels='kmeans',
        random_state=0
    )
    labels = sc.fit_predict(A)

    # Map each node to its assigned partition label
    assignment = dict(zip(G.nodes(), labels))
    return assignment


def gdfs_from_assignment(G, assignment):
    """
    Generate GeoDataFrames for nodes and edges based on partition assignments.

    Args:
        G (nx.Graph): Input graph with node coordinates.
        assignment (dict): Mapping of node -> partition index.

    Returns:
        tuple: (nodes_gdf, edges_gdf)
            nodes_gdf (gpd.GeoDataFrame): GeoDataFrame of nodes with partition info.
            edges_gdf (gpd.GeoDataFrame): GeoDataFrame of edges with partition info.
    """
    # Create nodes GeoDataFrame
    nodes = []
    for node, data in G.nodes(data=True):
        nodes.append({
            "node": node,
            "x": data["x"],
            "y": data["y"],
            "geometry": Point(data["x"], data["y"]),
            "partition": assignment[node]
        })
    nodes_gdf = gpd.GeoDataFrame(nodes, crs="EPSG:4326")

    # Create edges GeoDataFrame
    edges = []
    for u, v, data in G.edges(data=True):
        edges.append({
            "u": u,
            "v": v,
            "geometry": LineString([
                (G.nodes[u]["x"], G.nodes[u]["y"]),
                (G.nodes[v]["x"], G.nodes[v]["y"])
            ]),
            "same_partition": int(assignment[u] == assignment[v]),
            "partition_u": assignment[u],
            "partition_v": assignment[v]
        })
    edges_gdf = gpd.GeoDataFrame(edges, crs="EPSG:4326")

    return nodes_gdf, edges_gdf
