import json
import numpy as np
import networkx as nx
import osmnx as ox
import geopandas as gpd
from typing import Dict, Any, Tuple

def read_kahip_json(json_path: str) -> Dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_from_json(G: nx.Graph, data: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:

    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

    if "edges" not in data:
        raise ValueError("JSON 缺少 'edges' 字段。")

    # 将 (u,v,key) 做映射，填回 edges_gdf
    mapping = {}
    for e in data["edges"]:
        u = e["u"]; v = e["v"]
        k = e.get("key", 0)  # 你的 JSON 未写 key，就按 0 处理
        pu = int(e.get("partition_u", -1))
        pv = int(e.get("partition_v", -1))
        cut = bool(e.get("is_cut", pu != pv))
        mapping[(u, v, k)] = (pu, pv, cut)

    part_u_arr, part_v_arr, is_cut_arr = [], [], []
    for u, v, k in G.edges(keys=True):
        pu, pv, cut = mapping.get((u, v, k), mapping.get((v, u, k), (-1, -1, False)))
        part_u_arr.append(pu)
        part_v_arr.append(pv)
        is_cut_arr.append(cut)

    edges_gdf = edges_gdf.copy()
    edges_gdf["part_u"] = part_u_arr
    edges_gdf["part_v"] = part_v_arr
    edges_gdf["is_cut"] = is_cut_arr
    edges_gdf["part"]   = np.where(edges_gdf["is_cut"], -1, edges_gdf["part_u"])

    nodes_gdf["part"] = -1

    return nodes_gdf, edges_gdf
