# core/osm_loader.py
import os
import json
import hashlib
import osmnx as ox
import networkx as nx

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _safe(s: str) -> str:
    return s.replace(",", "").replace(" ", "_")

def _cache_paths(place: str, dist: int):
    safe = _safe(place)
    # ⛳ 关键：把 dist 放进缓存文件名里
    base = f"{safe}_d{int(dist)}"
    return {
        "graphml": os.path.join(CACHE_DIR, f"{base}.graphml"),
        "meta":    os.path.join(CACHE_DIR, f"{base}.json"),
    }

def load_graph(place: str, dist: int = 5000, network_type: str = "drive") -> nx.MultiDiGraph:
    """
    下载/读取以 place 为中心、半径 dist(米) 的道路图。
    缓存命中时直接读取缓存；缓存键包含 dist，避免“总是 5000”问题。
    """
    p = _cache_paths(place, dist)
    if os.path.exists(p["graphml"]):
        try:
            G = ox.load_graphml(p["graphml"])
            print(f"[OSM] cache hit -> {p['graphml']} (dist={dist})")
            return G
        except Exception:
            pass  # 如损坏则重下

    print(f"[OSM] fetching from OSM: place='{place}', dist={dist}m ...")
    # 你当前项目如果是基于地点+半径，推荐用 graph_from_address + dist
    # 若是用地名 polygon，请改成 graph_from_place，并移除 dist。
    G = ox.graph_from_address(place, dist=dist, network_type=network_type, simplify=False)

    # 存缓存
    ox.save_graphml(G, p["graphml"])
    with open(p["meta"], "w", encoding="utf-8") as f:
        json.dump({"place": place, "dist": dist}, f)
    print(f"[OSM] saved cache -> {p['graphml']} (dist={dist})")
    return G
