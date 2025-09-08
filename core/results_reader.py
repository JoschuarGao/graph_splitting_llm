# results_reader.py

from typing import Dict, Any, Tuple
import json
import numpy as np
import networkx as nx
import osmnx as ox
import geopandas as gpd


def read_kahip_json(json_path: str) -> Dict[str, Any]:
    """
    Read a KaHIP output JSON file into a Python dict.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _to_int(x, default=0) -> int:
    """
    Coerce a value to int. If it fails, return default.
    Also handles one-element lists/tuples by taking the first item.
    """
    try:
        return int(x)
    except Exception:
        if isinstance(x, (list, tuple)) and len(x) > 0:
            try:
                return int(x[0])
            except Exception:
                pass
    return default


def parse_from_json(
    G: nx.Graph,
    data: Dict[str, Any],
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Map KaHIP partition results from JSON back to the original graph.

    Returns:
        (nodes_gdf, edges_gdf)
        - nodes_gdf: node geometries with a 'part' column (initialized to -1).
        - edges_gdf: edge geometries with columns:
            ['part_u', 'part_v', 'is_cut', 'part', 'u', 'v', 'key', 'eid']
          where:
            - part_u, part_v are partition labels of incident nodes
            - is_cut is True if part_u != part_v
            - part = part_u if not cut else -1
            - eid is a TUPLE (u, v, key) and is hashable
    """
    print("[DBG] results_reader.parse_from_json: ENTER")

    # 1) Convert the NetworkX graph to GeoDataFrames
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

    # 2) Validate JSON schema
    if "edges" not in data:
        raise ValueError("JSON is missing the 'edges' field.")

    # 3) Build a lookup: (u, v, k) -> (part_u, part_v, is_cut)
    #    Accept extra fields (e.g., 'weight', 'is_cut') without error.
    mapping = {}
    for e in data["edges"]:
        u = _to_int(e.get("u"))
        v = _to_int(e.get("v"))
        k = _to_int(e.get("key", 0))  # KaHIP JSON may not have 'key' -> default 0
        pu = _to_int(e.get("partition_u"), -1)
        pv = _to_int(e.get("partition_v"), -1)
        cut = bool(e.get("is_cut", pu != pv))
        # store both directions to be safe on undirected edges
        mapping[(u, v, k)] = (pu, pv, cut)
        mapping[(v, u, k)] = (pu, pv, cut)

    # 4) Build arrays for every edge in G (respect multi-edges via 'keys=True')
    part_u_arr, part_v_arr, is_cut_arr, u_arr, v_arr, k_arr = [], [], [], [], [], []
    for u, v, k in G.edges(keys=True):
        ui = _to_int(u)
        vi = _to_int(v)
        ki = _to_int(k)
        pu, pv, cut = mapping.get((ui, vi, ki), mapping.get((vi, ui, ki), (-1, -1, False)))
        part_u_arr.append(pu)
        part_v_arr.append(pv)
        is_cut_arr.append(cut)
        u_arr.append(ui)
        v_arr.append(vi)
        k_arr.append(ki)

    # 5) Update edges_gdf with partition information
    edges_gdf["u"] = u_arr
    edges_gdf["v"] = v_arr
    edges_gdf["edge_key"] = k_arr
    edges_gdf["part_u"] = part_u_arr
    edges_gdf["part_v"] = part_v_arr
    edges_gdf["is_cut"] = is_cut_arr
    edges_gdf["part"] = np.where(edges_gdf["is_cut"], -1, edges_gdf["part_u"])

    # 旧的 'key' 列直接丢掉（有就删）
    if "key" in edges_gdf.columns:
        edges_gdf = edges_gdf.drop(columns=["key"])

    # 6) Build a hashable edge id column (tuple), NEVER a list
    edges_gdf["eid"] = list(zip(
        edges_gdf["u"].astype(int),
        edges_gdf["v"].astype(int),
        edges_gdf["edge_key"].astype(int),
    ))
    def _deep_tuple(x):
        if isinstance(x, list):
            return tuple(_deep_tuple(i) for i in x)
        if isinstance(x, dict):
            return { _deep_tuple(k): _deep_tuple(v) for k, v in x.items() }
        return x

    for col in ("eid", "u", "v", "edge_key", "part_u", "part_v"):  # 只消毒这些关键列，避免动 geometry
        if col in edges_gdf.columns:
            edges_gdf[col] = edges_gdf[col].apply(_deep_tuple)
    # 7) Final guard: ensure eid is never a list (helps catch future regressions)
    assert edges_gdf["eid"].map(lambda x: not isinstance(x, list)).all(), "eid contains list (should be tuple)"

    # 8) Initialize node partitions (if you later compute node parts, overwrite this)
    nodes_gdf = nodes_gdf.copy()
    nodes_gdf["part"] = -1

    print("[DBG] results_reader.parse_from_json: LEAVE",
          [c for c in ["u", "v", "key", "eid", "part_u", "part_v", "is_cut", "part"] if c in edges_gdf.columns],
          "N_edges=", len(edges_gdf))

    return nodes_gdf, edges_gdf
