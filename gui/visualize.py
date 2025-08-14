import os, time, re, hashlib
import folium
import geopandas as gpd
from core.config import OUTPUT_DIR, HTML_NAME_TEMPLATE  

def compute_cut_stats(edges_gdf: gpd.GeoDataFrame) -> dict:
    total = len(edges_gdf)
    cut_count = int(edges_gdf.get("is_cut", 0).sum()) if total else 0
    cut_ratio = (cut_count / total) if total else 0.0
    return dict(edges=total, cut_edge_count=cut_count, cut_ratio=cut_ratio)

def make_map(nodes_gdf: gpd.GeoDataFrame,
             edges_gdf: gpd.GeoDataFrame,
             place: str,
             k: int) -> str:
   
    def to_wgs84(gdf):
        if gdf is None or gdf.empty:
            return gdf
        try:
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                return gdf.to_crs(epsg=4326)
        except Exception:
            pass
        return gdf

    nodes_gdf = to_wgs84(nodes_gdf)
    edges_gdf = to_wgs84(edges_gdf)


    for col in ("geometry", "part_u", "part_v"):
        if col not in edges_gdf.columns:
            raise ValueError(f"edges_gdf 缺少必要列: {col}")

    if "is_cut" not in edges_gdf.columns:
        edges_gdf = edges_gdf.copy()
        edges_gdf["is_cut"] = edges_gdf["part_u"] != edges_gdf["part_v"]

    internal_edges = edges_gdf[~edges_gdf["is_cut"]]
    cut_edges = edges_gdf[edges_gdf["is_cut"]]

    # 内部边
    if len(internal_edges):
        m = internal_edges.explore(
            column="part_u",
            cmap="tab20",
            tiles="cartodbpositron",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in internal_edges.columns],
            name="Internal edges",
            style_kwds=dict(weight=3, opacity=0.9)
        )
    else:
        m = folium.Map(tiles="cartodbpositron", zoom_start=12)

    # 切割边
    if len(cut_edges):
        cut_edges.explore(
            m=m,
            color="red",
            style_kwds=dict(weight=4, opacity=0.95, dashArray="6,6"),
            name="Cut edges",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in cut_edges.columns]
        )

    # 节点层（可选）
    if nodes_gdf is not None and not nodes_gdf.empty:
        nodes_gdf.explore(
            m=m,
            color="yellow",
            marker_kwds={"radius": 5},
            tooltip=True,
            name="Nodes"
        )

    try:
        # 用 cut_edges 或 internal_edges 计算边界
        bounds_gdf = cut_edges if len(cut_edges) else internal_edges
        if len(bounds_gdf):
            # bounds 格式 [[miny, minx], [maxy, maxx]]
            minx, miny, maxx, maxy = bounds_gdf.total_bounds  # (minx, miny, maxx, maxy)
            m.fit_bounds([[miny, minx], [maxy, maxx]])
    except Exception:
        pass

    folium.LayerControl(collapsed=False).add_to(m)

    safe = place.replace(",", "").replace(" ", "_")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME_TEMPLATE.format(safe_place=safe, k=k))
    m.save(html_path)
    return html_path
