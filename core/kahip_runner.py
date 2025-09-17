import os
import sys
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional

from core.config import (
    KAHIP_PY_PATH,
    KAHIP_CLI_ARGS,  
    OUTPUT_DIR,
    CACHE_DIR,
    RESULT_BASE,
)

def _safe(s: str) -> str:
    return s.replace(",", "").replace(" ", "_")

def build_kahip_cmd(params: Dict[str, Any]) -> list:
    """按 KaHIP.py 的 argparse 名称组装命令行。"""
    if not os.path.isfile(KAHIP_PY_PATH):
        raise FileNotFoundError(f"KaHIP.py 未找到：{KAHIP_PY_PATH}")

    cmd = [sys.executable, KAHIP_PY_PATH]

    def add_arg(name: str, value):
        if value is None:
            return
        if name not in KAHIP_CLI_ARGS:
            return
        cmd.extend([KAHIP_CLI_ARGS[name], str(value)])

    # Basic Parameters 
    for key in ["place", "k", "dist", "cache_dir", "alpha", "beta", "gamma", "csv_path"]:
        add_arg(key, params.get(key))

    # Road Type Weights（Version + PATH）
    add_arg("road_type_version", params.get("road_type_version"))
    add_arg("road_type_path",    params.get("road_type_path"))

    # Lane weights（Version + PATH）
    add_arg("lane_weight_version", params.get("lane_weight_version"))
    add_arg("lane_weight_path",    params.get("lane_weight_path"))

    return cmd

def _expected_json_path(params: Dict[str, Any]) -> str:
    base_dir   = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver   = params.get("road_type_version") or "unknown"
    today_str  = datetime.now().strftime("%Y-%m-%d")
    k          = int(params["k"])
    dist       = int(params["dist"])

    # 文件名包含 dist，优先使用 lane_ver 前缀（如果你 KaHIP.py 如此输出）
    lane_ver = params.get("lane_weight_version")
    if lane_ver:
        fname = f"{lane_ver}_edges_partitions_d{dist}_k{k}.json"
    else:
        fname = f"edges_partitions_d{dist}_k{k}.json"

    return os.path.join(base_dir, safe_place, road_ver, today_str, fname)

def _fallback_find_json(params: Dict[str, Any]) -> Optional[str]:
    base_dir   = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver   = params.get("road_type_version") or "unknown"
    today_str  = datetime.now().strftime("%Y-%m-%d")
    k          = int(params["k"])
    dist       = int(params["dist"])

    date_dir = os.path.join(base_dir, safe_place, road_ver, today_str)
    if not os.path.isdir(date_dir):
        return None

    # 只匹配包含 d{dist}_k{k} 的 json（避免误用老半径的文件）
    suffix = f"edges_partitions_d{dist}_k{k}.json"
    cands = [
        os.path.join(date_dir, f)
        for f in os.listdir(date_dir)
        if f.endswith(".json") and f.endswith(suffix)
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]

def run_kahip(params: Dict[str, Any] = None, **kwargs) -> str:
    """
    兼容两种用法：
      run_kahip(params=dict(...))
      run_kahip(place=..., k=..., ...)
    返回:KaHIP.py 生成的 JSON 路径
    """
    # 统一成 dict
    if params is None:
        params = kwargs
    else:
        # 允许 dict + 额外 kwargs 覆盖
        params = {**params, **kwargs}

    # 默认值补齐
    params.setdefault("cache_dir", CACHE_DIR)
    params.setdefault("csv_path",  os.path.join(OUTPUT_DIR, "results.csv"))

    # 必要参数检查（按你 KaHIP.py 的 argparse 要求）
    required = ["place", "k", "dist", "road_type_version", "lane_weight_version"]
    missing = [r for r in required if not params.get(r)]
    if missing:
        raise ValueError(f"缺少必要参数：{missing}（这些在 KaHIP.py 中是必填的）")

    # 组装并执行
    cmd = build_kahip_cmd(params)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if proc.returncode != 0:
        raise RuntimeError(
            "KaHIP.py 执行失败：\n"
            f"CMD: {' '.join(cmd)}\n"
            f"STDERR:\n{proc.stderr}\n"
            f"STDOUT:\n{proc.stdout}"
        )

    # 推断输出 JSON 路径
    json_path = _expected_json_path(params)
    if not os.path.exists(json_path):
        alt = _fallback_find_json(params)
        if alt:
            return alt
        raise FileNotFoundError(
            "未找到 KaHIP 输出 JSON。\n"
            f"期望路径：{json_path}\n"
            "请确认 KaHIP.py 已写出 JSON（edges_partitions_k{k}.json 或 lane_version_ 前缀文件）。\n"
            f"STDOUT:\n{proc.stdout}"
        )
    return json_path
