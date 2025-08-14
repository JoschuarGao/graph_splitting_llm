"""
Interactive map generation utilities for OSM partition visualization.

This module provides:
  1) compute_cut_stats: summarize basic cut statistics from an edges GeoDataFrame.
  2) make_map: build an interactive Folium map that colors internal edges by
     partition and overlays cut edges as dashed red lines. The map is saved to
     OUTPUT_DIR using HTML_NAME_TEMPLATE from core.config.

Expected columns on edges_gdf:
  - geometry: Shapely LineString geometry in WGS84 (EPSG:4326) for display
  - part_u, part_v: integer partition IDs for the two endpoints
  - (optional) is_cut: boolean indicating whether an edge is a cut edge

Notes:
• If "is_cut" is absent, it will be derived from (part_u != part_v).
• The map centers on the mean node coordinates when nodes_gdf is provided;
  otherwise it falls back to the centroid of edges.
"""

# Imports & configuration
import os
import folium
import geopandas as gpd
from core.config import OUTPUT_DIR, HTML_NAME_TEMPLATE


# Statistics: count edges and cut edges, compute cut ratio
def compute_cut_stats(edges_gdf: gpd.GeoDataFrame) -> dict:
    """Compute basic cut statistics from an edges GeoDataFrame.

    Parameters
    ----------
    edges_gdf : gpd.GeoDataFrame
        Edge table. Must contain at least 'geometry'. If it includes 'is_cut'
        or ('part_u','part_v'), those will be used to detect cut edges.

    Returns
    -------
    dict
        A dictionary with keys:
          - edges: total number of edges
          - cut_edge_count: number of edges crossing partitions
          - cut_ratio: cut_edge_count / edges (0.0 if edges == 0)
    """
    total = len(edges_gdf)
    if total == 0:
        return dict(edges=0, cut_edge_count=0, cut_ratio=0.0)

    # Prefer an explicit 'is_cut' column if present; otherwise infer from parts
    if "is_cut" in edges_gdf.columns:
        cut_count = int(edges_gdf["is_cut"].sum())
    elif {"part_u", "part_v"}.issubset(edges_gdf.columns):
        cut_count = int((edges_gdf["part_u"] != edges_gdf["part_v"]).sum())
    else:
        cut_count = 0

    cut_ratio = (cut_count / total) if total else 0.0
    return dict(edges=total, cut_edge_count=cut_count, cut_ratio=cut_ratio)


# Map rendering: draw partitions and cut edges using Folium
def make_map(
    nodes_gdf: gpd.GeoDataFrame,
    edges_gdf: gpd.GeoDataFrame,
    place: str,
    k: int,
) -> str:
    """Create an interactive Folium map showing partitions and cut edges.

    The function expects partition annotations on edges and renders:
      • Internal edges (part_u == part_v) colored by partition using a
        categorical colormap.
      • Cut edges (part_u != part_v) as emphasized red dashed lines.

    Parameters
    ----------
    nodes_gdf : gpd.GeoDataFrame
        Node table used to estimate a sensible initial map center.
    edges_gdf : gpd.GeoDataFrame
        Edge table with columns: 'geometry', 'part_u', 'part_v' (and optional
        'is_cut').
    place : str
        Place name used for output file naming.
    k : int
        Number of partitions for display/metadata only.

    Returns
    -------
    str
        Absolute path to the saved HTML file under OUTPUT_DIR.
    """

    # Basic validation of required columns 
    for col in ("geometry", "part_u", "part_v"):
        if col not in edges_gdf.columns:
            raise ValueError(f"edges_gdf is missing required column: {col}")

    # Derive 'is_cut' if necessary 
    if "is_cut" not in edges_gdf.columns:
        edges_gdf = edges_gdf.copy()
        edges_gdf["is_cut"] = edges_gdf["part_u"] != edges_gdf["part_v"]

    internal_edges = edges_gdf[edges_gdf["is_cut"] == False]
    cut_edges = edges_gdf[edges_gdf["is_cut"] == True]

    # Determine a reasonable map center 
    center = None
    try:
        if nodes_gdf is not None and len(nodes_gdf):
            center = [nodes_gdf.geometry.y.mean(), nodes_gdf.geometry.x.mean()]
    except Exception:
        # Fallback to edge centroids if node coordinates are unavailable
        pass

    if center is None and len(edges_gdf):
        try:
            cx = edges_gdf.geometry.centroid.x.mean()
            cy = edges_gdf.geometry.centroid.y.mean()
            center = [cy, cx]
        except Exception:
            center = [0, 0]

    # Base Folium map
    fmap = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    # Internal edges: color by partition
    if len(internal_edges):
        internal_edges.explore(
            m=fmap,
            column="part_u",
            cmap="tab20",
            tiles="cartodbpositron",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in internal_edges.columns],
            name="Internal edges",
            style_kwds=dict(weight=3, opacity=0.9),
        )

    # Cut edges: red dashed overlay
    if len(cut_edges):
        cut_edges.explore(
            m=fmap,
            color="red",
            style_kwds=dict(weight=4, opacity=0.95, dashArray="6,6"),
            name="Cut edges",
            tooltip=[c for c in ["highway", "length", "part_u", "part_v"] if c in cut_edges.columns],
        )

    # Layer control and HTML export 
    folium.LayerControl(collapsed=False).add_to(fmap)
    safe = place.replace(",", "").replace(" ", "_")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME_TEMPLATE.format(safe_place=safe, k=k))
    fmap.save(html_path)
    return html_path
