import os
import folium
import geopandas as gpd
from core.config import OUTPUT_DIR, HTML_NAME_TEMPLATE  # 改为包内绝对导入

def compute_cut_stats(edges_gdf: gpd.GeoDataFrame) -> dict:
    total = len(edges_gdf)
    cut_count = int(edges_gdf.get("is_cut", 0).sum()) if total else 0
    cut_ratio = (cut_count / total) if total else 0.0
    return dict(edges=total, cut_edge_count=cut_count, cut_ratio=cut_ratio)

def make_map(nodes_gdf: gpd.GeoDataFrame,
             edges_gdf: gpd.GeoDataFrame,
             place: str,
             k: int) -> str:
    """
    两层地图：
      - 内部边（part_u == part_v）按 partition 上色
      - 切割边（part_u != part_v 或 is_cut==True）红色虚线
    返回 HTML 文件路径。
    需要 edges_gdf 至少包含：geometry, part_u, part_v；可选 is_cut, highway, length。
    """
    # 基础校验
    for col in ("geometry", "part_u", "part_v"):
        if col not in edges_gdf.columns:
            raise ValueError(f"edges_gdf 缺少必要列: {col}")

    # 衍生列
    if "is_cut" not in edges_gdf.columns:
        edges_gdf = edges_gdf.copy()
        edges_gdf["is_cut"] = edges_gdf["part_u"] != edges_gdf["part_v"]

    internal_edges = edges_gdf[edges_gdf["is_cut"] == False]
    cut_edges = edges_gdf[edges_gdf["is_cut"] == True]

    # 地图中心
    center = None
    try:
        if nodes_gdf is not None and len(nodes_gdf):
            center = [nodes_gdf.geometry.y.mean(), nodes_gdf.geometry.x.mean()]
    except Exception:
        pass
    if center is None and len(edges_gdf):
        # 用边的中点近似
        try:
            cx = edges_gdf.geometry.centroid.x.mean()
            cy = edges_gdf.geometry.centroid.y.mean()
            center = [cy, cx]
        except Exception:
            center = [0, 0]

    fmap = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    # 内部边：按 partition 着色（使用 explore 的 categorical colormap）
    if len(internal_edges):
        internal_edges.explore(
            m=fmap,
            column="part_u",
            cmap="tab20",
            tiles="cartodbpositron",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in internal_edges.columns],
            name="Internal edges",
            style_kwds=dict(weight=3, opacity=0.9)
        )

    # 切割边：红色虚线
    if len(cut_edges):
        cut_edges.explore(
            m=fmap,
            color="red",
            style_kwds=dict(weight=4, opacity=0.95, dashArray="6,6"),
            name="Cut edges",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in cut_edges.columns]
        )

    folium.LayerControl(collapsed=False).add_to(fmap)
    safe = place.replace(",", "").replace(" ", "_")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME_TEMPLATE.format(safe_place=safe, k=k))
    fmap.save(html_path)
    return html_path
