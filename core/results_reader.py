import json
import numpy as np
import networkx as nx
import osmnx as ox
import geopandas as gpd
from typing import Dict, Any, Tuple


def read_kahip_json(json_path: str) -> Dict[str, Any]:
    """
    Read and parse a KaHIP output JSON file.

    Args:
        json_path (str): Path to the JSON file.

    Returns:
        dict: Parsed JSON data as a Python dictionary.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_from_json(G: nx.Graph, data: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Parse KaHIP JSON data and map partition results back to the original graph's nodes and edges.

    Args:
        G (nx.Graph): The input NetworkX graph.
        data (dict): Parsed JSON data containing partition results.

    Returns:
        tuple: (nodes_gdf, edges_gdf)
            - nodes_gdf (GeoDataFrame): Node geometries and partition assignments.
            - edges_gdf (GeoDataFrame): Edge geometries with partition and cut information.
    """
    # Convert graph to GeoDataFrames (nodes and edges)
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)
    # Ensure that "edges" key exists in the JSON data
    if "edges" not in data:
        raise ValueError("JSON is missing the 'edges' field.")

    # Map each edge (u, v, key) to its partition_u, partition_v, and cut status
    mapping = {}
    for e in data["edges"]:
        u = e["u"]
        v = e["v"]
        # If the JSON does not contain a 'key', default to 0
        k = e.get("key", 0)
        pu = int(e.get("partition_u", -1))
        pv = int(e.get("partition_v", -1))
        # If 'is_cut' is not provided, infer from partition_u != partition_v
        cut = bool(e.get("is_cut", pu != pv))
        mapping[(u, v, k)] = (pu, pv, cut)

    # Create arrays for partition_u, partition_v, and is_cut for all edges in G
    part_u_arr, part_v_arr, is_cut_arr = [], [], []
    for u, v, k in G.edges(keys=True):
        # Try both (u, v, k) and (v, u, k) for undirected edges
        pu, pv, cut = mapping.get((u, v, k), mapping.get((v, u, k), (-1, -1, False)))
        part_u_arr.append(pu)
        part_v_arr.append(pv)
        is_cut_arr.append(cut)

    # Update edges GeoDataFrame with partition and cut information
    edges_gdf = edges_gdf.copy()
    edges_gdf["part_u"] = part_u_arr
    edges_gdf["part_v"] = part_v_arr
    edges_gdf["is_cut"] = is_cut_arr
    # Set 'part' to partition_u for non-cut edges, else -1
    edges_gdf["part"] = np.where(edges_gdf["is_cut"], -1, edges_gdf["part_u"])

    # Initialize node partition column to -1 (unknown/not assigned)
    nodes_gdf["part"] = -1

    return nodes_gdf, edges_gdf
