# gui/visualize.py

import os
from typing import Optional, Dict, Iterable, Tuple, Any, List

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from math import atan2

# 允许在 core/config.py 中自定义输出目录与文件名模板
try:
    from core.config import OUTPUT_DIR, HTML_NAME_TEMPLATE
except Exception:
    OUTPUT_DIR = "./outputs"
    HTML_NAME_TEMPLATE = "OSM_{safe_place}_k{k}.html"


# ------------------------ 工具函数 ------------------------

def _to_wgs84(gdf: Optional[gpd.GeoDataFrame]) -> Optional[gpd.GeoDataFrame]:
    """确保 GeoDataFrame 为 WGS84，经纬度坐标。"""
    if gdf is None or len(gdf) == 0:
        return gdf
    try:
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            return gdf.to_crs(epsg=4326)
    except Exception:
        return gdf
    return gdf


def _ensure_col(df: gpd.GeoDataFrame, name: str, default: Any) -> gpd.GeoDataFrame:
    """若缺列名则补一个默认值。"""
    if name not in df.columns:
        df = df.copy()
        df[name] = default
    return df


def _ensure_eid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """确保存在 'eid' 唯一 ID 列。"""
    if "eid" in gdf.columns:
        return gdf
    gdf = gdf.copy()
    for c in ("edge_id", "id", "osmid"):
        if c in gdf.columns:
            gdf["eid"] = gdf[c].astype(str)
            return gdf
    gdf["eid"] = gdf.index.astype(str)
    return gdf


def _detect_id_col(gdf: gpd.GeoDataFrame) -> str:
    """自动识别可作为唯一 ID 的列名。"""
    for c in ("eid", "edge_id", "id", "osmid"):
        if c in gdf.columns:
            return c
    return "eid"


# ---- 放在文件顶部工具区：替换你现有的 _normalize_diff ----
def _normalize_diff(diff: Optional[Dict]) -> Dict[str, list]:
    """
    兼容各种 diff 结构：
    - {"added":[...], "changed":[...], "removed":[...]}
    - {"added":{"edges":[...]},"removed":{"edges":[...]}}
    - 键名可能是 added_edges/removed_edges/modified/new/deleted 等
    统一返回 {"added":[str], "changed":[str], "removed":[str]}
    """
    def _pull(section):
        if section is None:
            return []
        # 直接是列表
        if isinstance(section, (list, tuple, set)):
            return list(section)
        # 可能是 dict，取常见字段
        if isinstance(section, dict):
            for key in ("edges", "edge_ids", "ids", "list"):
                if key in section and isinstance(section[key], (list, tuple, set)):
                    return list(section[key])
        # 其它类型直接丢弃
        return []

    if not diff:
        return {"added": [], "changed": [], "removed": []}

    added   = _pull(diff.get("added")   or diff.get("add")      or diff.get("new")          or diff.get("added_edges"))
    changed = _pull(diff.get("changed") or diff.get("modified") or diff.get("changed_edges"))
    removed = _pull(diff.get("removed") or diff.get("deleted")  or diff.get("removed_edges"))

    # 统一转为字符串，方便与 GDF 的 eid 匹配
    return {
        "added":   [str(x) for x in added],
        "changed": [str(x) for x in changed],
        "removed": [str(x) for x in removed],
    }



def _subset_by_ids(gdf: gpd.GeoDataFrame, id_col: str, ids: Iterable[str]) -> gpd.GeoDataFrame:
    ids = list(ids) if ids is not None else []
    if len(ids) == 0:
        return gdf.iloc[0:0].copy()
    s = set(map(str, ids))
    return gdf[gdf[id_col].astype(str).isin(s)].copy()


def _edge_mid_xy(geom) -> Optional[Tuple[float, float]]:
    """获取线段中点（lon, lat）。"""
    try:
        pt = geom.interpolate(0.5, normalized=True)
        return (pt.x, pt.y)
    except Exception:
        try:
            coords = list(geom.coords)
            return ((coords[0][0] + coords[-1][0]) / 2.0, (coords[0][1] + coords[-1][1]) / 2.0)
        except Exception:
            return None


def _tooltip_cols(gdf: gpd.GeoDataFrame, candidates: Iterable[str]) -> List[str]:
    """仅选择 gdf 中存在的列名作为 tooltip。"""
    cols = []
    for c in candidates:
        if c in gdf.columns:
            cols.append(c)
    return cols


# ------------------------ 指标统计 ------------------------

def compute_cut_stats(edges_gdf: Optional[gpd.GeoDataFrame]) -> dict:
    """
    统计指标：
    - edges: 总边数
    - cut_edge_count: 被切割的边数
    - total_weight: 全部边的权重和（缺省用 1.0）
    - cut_edge_weight_sum: 被切割边的权重和
    - cut_ratio: cut / edges
    - weight_ratio: cut_edge_weight_sum / total_weight
    """
    if edges_gdf is None or len(edges_gdf) == 0:
        return dict(
            edges=0,
            cut_edge_count=0,
            total_weight=0.0,
            cut_edge_weight_sum=0.0,
            cut_ratio=0.0,
            weight_ratio=0.0
        )

    df = edges_gdf.copy()

    if "is_cut" not in df.columns:
        if "part_u" in df.columns and "part_v" in df.columns:
            df["is_cut"] = (df["part_u"] != df["part_v"])
        else:
            df["is_cut"] = False
    try:
        df["is_cut"] = df["is_cut"].astype(bool)
    except Exception:
        df["is_cut"] = df["is_cut"].apply(lambda x: bool(x))

    if "weight" in df.columns:
        try:
            w = df["weight"].astype("float64")
        except Exception:
            w = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    else:
        w = pd.Series([1.0] * len(df), index=df.index, dtype="float64")

    total = int(len(df))
    cut_count = int(df["is_cut"].sum())
    total_weight = float(w.sum()) if total else 0.0
    cut_weight_sum = float(w[df["is_cut"]].sum()) if cut_count else 0.0

    return dict(
        edges=total,
        cut_edge_count=cut_count,
        total_weight=total_weight,
        cut_edge_weight_sum=cut_weight_sum,
        cut_ratio=(cut_count / total) if total else 0.0,
        weight_ratio=(cut_weight_sum / total_weight) if total_weight > 0 else 0.0
    )


# ------------------------ 地图渲染 ------------------------

def make_map(
    nodes_gdf: Optional[gpd.GeoDataFrame],
    edges_gdf: gpd.GeoDataFrame,
    place: str,
    k: int,
    edges_gdf_old: Optional[gpd.GeoDataFrame] = None,
    diff: Optional[Dict] = None,
    show_updates_default: bool = False
) -> str:
    """
    生成交互式 Folium HTML 地图。
    """
    # 空图兜底
    if edges_gdf is None or len(edges_gdf) == 0:
        m = folium.Map(tiles="cartodbpositron", zoom_start=12)
        return _save_map(m, place, k)

    # CRS -> WGS84
    nodes_gdf = _to_wgs84(nodes_gdf)
    edges_gdf = _to_wgs84(edges_gdf)
    if edges_gdf_old is not None and len(edges_gdf_old) > 0:
        edges_gdf_old = _to_wgs84(edges_gdf_old)

    # 必要列
    if "geometry" not in edges_gdf.columns:
        raise ValueError("edges_gdf 缺少 'geometry' 列。")

    # 过滤空几何
    edges_gdf = edges_gdf[edges_gdf["geometry"].notna()].copy()
    try:
        edges_gdf = edges_gdf[~edges_gdf.geometry.is_empty]
    except Exception:
        pass
    if len(edges_gdf) == 0:
        m = folium.Map(tiles="cartodbpositron", zoom_start=12)
        return _save_map(m, place, k)

    # part_u / part_v / is_cut 容错
    edges_gdf = _ensure_col(edges_gdf, "part_u", 0)
    edges_gdf = _ensure_col(edges_gdf, "part_v", 0)
    if "is_cut" not in edges_gdf.columns:
        edges_gdf = edges_gdf.copy()
        edges_gdf["is_cut"] = (edges_gdf["part_u"] != edges_gdf["part_v"])

    # 内部边与切割边
    internal_edges = edges_gdf[~edges_gdf["is_cut"]].copy()
    cut_edges      = edges_gdf[edges_gdf["is_cut"]].copy()

    # 选择用于着色的“分区列”：优先 part_u，其次 partition；都没有就置零
    if "part_u" in internal_edges.columns:
        label_series = internal_edges["part_u"]
    elif "partition" in internal_edges.columns:
        label_series = internal_edges["partition"]
    else:
        label_series = pd.Series([0] * len(internal_edges), index=internal_edges.index)

    # 将任意类型分区标签 factorize 成整数标签；NaN -> -1
    codes, _ = pd.factorize(label_series, sort=True)
    internal_edges["_part_code"] = codes
    # 明确 categories：去掉 -1，转 list，避免 numpy 数组在 if 中引发歧义
    cats = [int(c) for c in pd.unique(codes) if int(c) != -1]
    cats = sorted(cats)
    if len(cats) == 0:
        cats = [0]

    # Internal edges layer — 离散着色
    if len(internal_edges) > 0:
        m = internal_edges.explore(
            column="_part_code",
            categorical=True,                # 离散上色
            categories=cats,                 # 显式提供类别
            cmap="tab20",
            tiles="cartodbpositron",
            tooltip=_tooltip_cols(internal_edges, ["highway", "length", "part_u", "part_v", "partition"]),
            name="Internal edges",
            style_kwds=dict(weight=2.0, opacity=0.95)
        )
    else:
        m = folium.Map(tiles="cartodbpositron", zoom_start=12)

    # 切割边层
    if len(cut_edges) > 0:
        # 先加切割边可视
        cut_edges.explore(
            m=m,
            color="#111111",
            style_kwds=dict(weight=3.0, opacity=1.0, dashArray="6,6"),
            name="Cut edges",
            tooltip=_tooltip_cols(cut_edges, ["highway", "length", "part_u", "part_v"])
        )

        # 画分区对的示意线（仅当 part_u/part_v 都非空）
        mask_valid_cut = cut_edges["part_u"].notna() & cut_edges["part_v"].notna()
        ce = cut_edges[mask_valid_cut].copy()
        if len(ce) > 0:
            def _pair(row):
                pu, pv = row["part_u"], row["part_v"]
                try:
                    return tuple(sorted((int(pu), int(pv))))
                except Exception:
                    if (pu is None) or (pv is None):
                        return None
                    try:
                        return tuple(sorted((pu, pv)))
                    except Exception:
                        return None

            ce["pair"] = ce.apply(_pair, axis=1)
            ce = ce[ce["pair"].notna()]
            ce["midxy"] = ce.geometry.apply(_edge_mid_xy)
            ce = ce[ce["midxy"].notna()]

            for _, g in ce.groupby("pair"):
                if len(g) < 2:
                    continue
                xs = [xy[0] for xy in g["midxy"]]
                ys = [xy[1] for xy in g["midxy"]]
                cx, cy = (sum(xs) / len(xs), sum(ys) / len(ys))
                ordered = sorted(g["midxy"].tolist(), key=lambda xy: atan2(xy[1] - cy, xy[0] - cx))
                # folium 需要 (lat, lon)
                locations = [(lat, lon) for (lon, lat) in ordered]
                folium.PolyLine(
                    locations=locations,
                    color="#000000",
                    weight=2.0,
                    opacity=0.9,
                    dash_array="2,6"
                ).add_to(m)

    # 节点层（抽样避免过密）
    if nodes_gdf is not None and len(nodes_gdf) > 0:
        nodes_vis = nodes_gdf
        if len(nodes_vis) > 1200:
            nodes_vis = nodes_vis.sample(1200, random_state=0)
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
            tooltip=False
        )

    # 视野适配
    try:
        bounds_gdf = edges_gdf if len(edges_gdf) > 0 else nodes_gdf
        if bounds_gdf is not None and len(bounds_gdf) > 0:
            minx, miny, maxx, maxy = bounds_gdf.total_bounds
            m.fit_bounds([[miny, minx], [maxy, maxx]])
    except Exception:
        pass

    # ---------- 差异覆盖层 ----------
        # ---------- 差异覆盖层 ----------
    if diff is not None:
        diff = _normalize_diff(diff)

        new_df = _ensure_eid(edges_gdf)
        old_df = _ensure_eid(edges_gdf_old) if edges_gdf_old is not None else None

        id_new = _detect_id_col(new_df)
        added_gdf   = _subset_by_ids(new_df, id_new, diff["added"])
        changed_gdf = _subset_by_ids(new_df, id_new, diff["changed"])

        removed_gdf = None
        if old_df is not None:
            id_old = _detect_id_col(old_df)
            removed_gdf = _subset_by_ids(old_df, id_old, diff["removed"])
            removed_gdf = _to_wgs84(removed_gdf)

        # 为了让你“一眼看见”，名字里带数量；颜色粗细也更醒目
        if added_gdf is not None and len(added_gdf) > 0:
            added_gdf.explore(
                m=m,
                name=f"Updates: Added ({len(added_gdf)})",
                color="#00ff00",
                style_kwds=dict(weight=5.0, opacity=1.0),
                tooltip=[c for c in ("highway", "length", "part_u", "part_v", id_new) if c in added_gdf.columns],
                show=show_updates_default
            )

        if changed_gdf is not None and len(changed_gdf) > 0:
            changed_gdf.explore(
                m=m,
                name=f"Updates: Changed ({len(changed_gdf)})",
                color="#ff8c00",
                style_kwds=dict(weight=4.0, opacity=1.0),
                tooltip=[c for c in ("highway", "length", "part_u", "part_v", id_new) if c in changed_gdf.columns],
                show=show_updates_default
            )

        if removed_gdf is not None and len(removed_gdf) > 0:
            removed_gdf.explore(
                m=m,
                name=f"Updates: Removed ({len(removed_gdf)})",
                color="#ff0000",
                style_kwds=dict(weight=4.0, opacity=1.0, dashArray="8,6"),
                tooltip=[c for c in ("highway", "length", "part_u", "part_v") if c in removed_gdf.columns],
                show=show_updates_default
            )


    folium.LayerControl(collapsed=False).add_to(m)
    return _save_map(m, place, k)


def _save_map(m: folium.Map, place: str, k: int) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe = place.replace(",", "").replace(" ", "_")
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME_TEMPLATE.format(safe_place=safe, k=k))
    m.save(html_path)
    return html_path
