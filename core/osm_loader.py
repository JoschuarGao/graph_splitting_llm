# core/osm_loader.py
import os
import osmnx as ox
import networkx as nx
from pathlib import Path
from core.config import CACHE_DIR  # 确保在 config 里定义了缓存目录

# Disable OSMnx console logging
ox.settings.log_console = False


def _safe(name: str) -> str:
    """将地名转为安全文件名"""
    return name.replace(", ", "_").replace(",", "").replace(" ", "_")


def load_graph(place: str, dist: int = 20000) -> nx.Graph:
    """
    下载或从缓存加载 OSM 路网，并以无向图返回。
    缓存文件名包含 dist，避免不同半径命中同一缓存。
    """
    # 确保缓存目录存在
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

    safe_place = _safe(place)
    cache_path = os.path.join(CACHE_DIR, f"{safe_place}_d{dist}.graphml")  # <<< 关键

    if os.path.exists(cache_path):
        # 命中缓存
        G = ox.load_graphml(cache_path)
        # print(f"[OSM] cache hit -> {cache_path}")
    else:
        # 下载并缓存
        # 你原来的构图方式保持不变
        G = ox.graph_from_address(place, dist=dist, network_type="drive")
        ox.save_graphml(G, cache_path)
        # print(f"[OSM] cache saved -> {cache_path}")

    # 转无向
    if G.is_directed():
        G = G.to_undirected()

    return G
