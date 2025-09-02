import os, time, re, hashlib
import pandas as pd
from math import atan2
import folium
import geopandas as gpd
from core.config import OUTPUT_DIR, HTML_NAME_TEMPLATE  

# ===== Diff 可视化工具（新增） =====

def _detect_id_col(gdf):
    """自动识别边的唯一ID列名"""
    for c in ["eid", "edge_id", "id", "osmid"]:
        if c in gdf.columns:
            return c
    raise ValueError("未找到边ID列，请在 edges_gdf 中加入 eid/edge_id/id/osmid 之一。")

def _ensure_eid(gdf):
    """确保 GeoDataFrame 中有 'eid' 列，如果没有就自动生成"""
    if "eid" in gdf.columns:
        return gdf
    gdf = gdf.copy()
    if "edge_id" in gdf.columns:
        gdf["eid"] = gdf["edge_id"].astype(str)
    elif "id" in gdf.columns:
        gdf["eid"] = gdf["id"].astype(str)
    elif "osmid" in gdf.columns:
        gdf["eid"] = gdf["osmid"].astype(str)
    else:
        # 如果没有任何 ID 信息，就用索引来生成
        gdf["eid"] = gdf.index.astype(str)
    return gdf


def _subset_by_ids(gdf, id_col, id_list):
    if not id_list:
        return gdf.iloc[0:0].copy()  # 空集
    ids = set(id_list)
    return gdf[gdf[id_col].isin(ids)].copy()

# Extended statistics: include total_weight / cut_edge_weight_sum / weight_ratio
def compute_cut_stats(edges_gdf: gpd.GeoDataFrame) -> dict:
    """
    Compute statistics for the partitioned edges.

    Returns:
        dict containing:
            edges: total number of edges
            cut_edge_count: number of cut edges
            total_weight: sum of weights for all edges
            cut_edge_weight_sum: sum of weights for cut edges
            cut_ratio: cut edges / total edges
            weight_ratio: cut edge weight sum / total edge weight
    """
    if edges_gdf is None or edges_gdf.empty:  # Handle empty dataframe
        return dict(
            edges=0,
            cut_edge_count=0,
            total_weight=0.0,
            cut_edge_weight_sum=0.0,
            cut_ratio=0.0,
            weight_ratio=0.0
        )

    # Ensure 'is_cut' is boolean
    is_cut = edges_gdf.get("is_cut", False)
    try:
        is_cut = is_cut.astype(bool)
    except Exception:
        # If mixed types, force convert to bool: non-zero/non-empty => True
        is_cut = is_cut.apply(lambda x: bool(x))

    # Get weight column; if missing, treat as 1.0
    w = edges_gdf.get("weight", 1.0)
    try:
        if hasattr(w, "astype"):  # Series
            w = w.astype(float)
        else:  # Scalar value
            w = pd.Series([float(w)] * len(edges_gdf), index=edges_gdf.index)
    except Exception:
        # If conversion fails, fallback to all 1.0
        w = pd.Series([1.0] * len(edges_gdf), index=edges_gdf.index)

    total = int(len(edges_gdf))
    cut_count = int(is_cut.sum())
    total_weight = float(w.sum()) if total else 0.0
    cut_weight_sum = float(w[is_cut].sum()) if cut_count else 0.0
    cut_ratio = (cut_count / total) if total else 0.0
    weight_ratio = (cut_weight_sum / total_weight) if total_weight > 0 else 0.0

    return dict(
        edges=total,
        cut_edge_count=cut_count,
        total_weight=total_weight,
        cut_edge_weight_sum=cut_weight_sum,
        cut_ratio=cut_ratio,
        weight_ratio=weight_ratio
    )


def make_map(nodes_gdf: gpd.GeoDataFrame,
             edges_gdf: gpd.GeoDataFrame,
             place: str,
             k: int,
             edges_gdf_old: gpd.GeoDataFrame | None = None,
             diff: dict | None = None,
             show_updates_default: bool = False  
             ) -> str:

    """
    Create an interactive Folium map to visualize partitioned road networks.

    Args:
        nodes_gdf: GeoDataFrame of nodes
        edges_gdf: GeoDataFrame of edges
        place: Place name (used in file naming)
        k: Number of partitions

    Returns:
        Path to the saved HTML map
    """
    def to_wgs84(gdf):
        """Convert GeoDataFrame to WGS84 CRS if necessary."""
        if gdf is None or gdf.empty:
            return gdf
        try:
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                return gdf.to_crs(epsg=4326)
        except Exception:
            pass
        return gdf

    # Ensure correct CRS
    nodes_gdf = to_wgs84(nodes_gdf)
    edges_gdf = to_wgs84(edges_gdf)

    # Ensure required columns exist
    for col in ("geometry", "part_u", "part_v"):
        if col not in edges_gdf.columns:
            raise ValueError(f"edges_gdf missing required column: {col}")

    # Add 'is_cut' column if missing
    if "is_cut" not in edges_gdf.columns:
        edges_gdf = edges_gdf.copy()
        edges_gdf["is_cut"] = edges_gdf["part_u"] != edges_gdf["part_v"]

    # Separate internal and cut edges
    internal_edges = edges_gdf[~edges_gdf["is_cut"]]
    cut_edges = edges_gdf[edges_gdf["is_cut"]]

    # Internal edges layer
    if len(internal_edges):
        m = internal_edges.explore(
            column="part_u",
            cmap="tab20",
            tiles="cartodbpositron",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in internal_edges.columns],
            name="Internal edges",
            style_kwds=dict(weight=2.0, opacity=0.95)  # Slightly thicker and more opaque lines
        )
    else:
        m = folium.Map(tiles="cartodbpositron", zoom_start=12)

    # Cut edges layer
    if len(cut_edges):
        cut_edges.explore(
            m=m,
            color="#111111",  # Dark color for strong contrast
            style_kwds=dict(weight=3.0, opacity=1.0, dashArray="6,6"),
            name="Cut edges",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in cut_edges.columns]
        )
        ce = cut_edges.copy()

        # Partition pair (unordered)
        def _pair(row):
            return tuple(sorted((int(row["part_u"]), int(row["part_v"]))))
        ce["pair"] = ce.apply(_pair, axis=1)

        # Get edge midpoints (prefer shapely.interpolate)
        def _mid_xy(geom):
            try:
                pt = geom.interpolate(0.5, normalized=True)
                return (pt.x, pt.y)  # (lon, lat)
            except Exception:
                coords = list(geom.coords)
                x = (coords[0][0] + coords[-1][0]) / 2.0
                y = (coords[0][1] + coords[-1][1]) / 2.0
                return (x, y)

        ce["midxy"] = ce.geometry.apply(_mid_xy)

        # Group by pair and draw dashed lines between midpoints
        for pair, g in ce.groupby("pair"):
            if len(g) < 2:
                continue

            # Sort midpoints by polar angle around centroid for smoother connection
            xs = [xy[0] for xy in g["midxy"]]
            ys = [xy[1] for xy in g["midxy"]]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)

            ordered = sorted(g["midxy"].tolist(), key=lambda xy: atan2(xy[1] - cy, xy[0] - cx))
            # Folium expects (lat, lon), but we have (lon, lat)
            locations = [(lat, lon) for (lon, lat) in ordered]

            folium.PolyLine(
                locations=locations,
                color="#000000",
                weight=2.0,
                opacity=0.9,
                dash_array="2,6"  # Short dashed line for clearer boundary
            ).add_to(m)

    # Node layer (optional): sample to reduce clutter, smaller gray semi-transparent circles
    if nodes_gdf is not None and not nodes_gdf.empty:
        sample_size = min(len(nodes_gdf), 1000)
        nodes_vis = nodes_gdf.sample(sample_size, random_state=0) if len(nodes_gdf) > sample_size else nodes_gdf

        nodes_vis.explore(
            m=m,
            name="Nodes (thinned)",
            marker_type="circle",
            color="#888888",
            marker_kwds={
                "radius": 2,
                "fill": True,
                "fillColor": "#aaaaaa",
                "fillOpacity": 0.35,
                "opacity": 0.35,
                "weight": 0.5
            },
            tooltip=False  # Disable node tooltip to avoid excessive hover popups
        )

    # Adjust map bounds to fit data
    try:
        bounds_gdf = cut_edges if len(cut_edges) else internal_edges
        if len(bounds_gdf):
            minx, miny, maxx, maxy = bounds_gdf.total_bounds
            m.fit_bounds([[miny, minx], [maxy, maxx]])
    except Exception:
        pass

    
    if diff is not None:
        # 先确保新旧GDF都带有 'eid'（容错：若无则自动生成）
        edges_gdf = _ensure_eid(edges_gdf)
        if edges_gdf_old is not None:
            edges_gdf_old = _ensure_eid(edges_gdf_old)

        try:
            id_col_new = _detect_id_col(edges_gdf)
        except Exception:
            id_col_new = None

        # Added / Changed 从 “新图” 里取几何
        if id_col_new is not None:
            added_gdf   = _subset_by_ids(edges_gdf, id_col_new, diff.get("added", []))
            changed_gdf = _subset_by_ids(edges_gdf, id_col_new, diff.get("changed", []))
        else:
            added_gdf   = edges_gdf.iloc[0:0].copy()
            changed_gdf = edges_gdf.iloc[0:0].copy()

        # Removed 从 “旧图” 里取几何
        removed_gdf = None
        id_col_old = None
        if edges_gdf_old is not None:
            try:
                id_col_old = _detect_id_col(edges_gdf_old)
                removed_gdf = _subset_by_ids(edges_gdf_old, id_col_old, diff.get("removed", []))
                removed_gdf = to_wgs84(removed_gdf)
            except Exception:
                removed_gdf = None

        # 三层样式：新增=粗线；修改=中等；删除=虚线
        if added_gdf is not None and len(added_gdf):
            added_gdf.explore(
                m=m,
                name="Updates: Added edges",
                tooltip=[c for c in ["highway", "length", "part_u", "part_v", id_col_new] if c and c in added_gdf.columns],
                style_kwds=dict(weight=4.0, opacity=0.95),
                show=show_updates_default  
            )
        if changed_gdf is not None and len(changed_gdf):
            changed_gdf.explore(
                m=m,
                name="Updates: Changed edges",
                tooltip=[c for c in ["highway", "length", "part_u", "part_v", id_col_new] if c and c in changed_gdf.columns],
                style_kwds=dict(weight=3.0, opacity=0.95),
                show=show_updates_default  
            )
        if removed_gdf is not None and len(removed_gdf):
            removed_gdf.explore(
                m=m,
                name="Updates: Removed edges",
                tooltip=[c for c in ["highway", "length", "part_u", "part_v", id_col_old] if c and c in removed_gdf.columns],
                color="#000000",
                style_kwds=dict(weight=3.0, opacity=0.95, dashArray="6,6"),
                show=show_updates_default 
            )


    folium.LayerControl(collapsed=False).add_to(m)

    # Save HTML map
    safe = place.replace(",", "").replace(" ", "_")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME_TEMPLATE.format(safe_place=safe, k=k))
    m.save(html_path)
    return html_path
