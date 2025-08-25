#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os, sys, math, time, subprocess
from pathlib import Path
from datetime import datetime

# -------------- 工具：读写 JSON ----------------

def load_json(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(obj: dict, p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

# -------------- 共形缩放/锚点归一 ----------------

def _conformal_from_base(base_vec: dict, anchor_key: str, tau: float, clip_min=None, clip_max=None):
    """
    base_vec: {category: weight}  —— 来自基准版本（如 "motorway1_rankup_1"）
    anchor_key: 锚点类别，比如 road_type 选 'primary'；lane 选 '1'
    tau: 张力/对比度，tau>1 放大差异；tau<1 压缩差异；tau=1 原样
    返回: 新的 {category: new_weight}，其中 anchor==1
    """
    if anchor_key not in base_vec:
        raise ValueError(f"Anchor '{anchor_key}' not found in base vector keys: {list(base_vec.keys())[:10]}...")

    # 确保正数
    eps = 1e-9
    a = max(float(base_vec[anchor_key]), eps)

    out = {}
    for k, w in base_vec.items():
        w = max(float(w), eps)
        rel = w / a
        new_w = (rel ** tau)  # 锚点会变成 1^tau == 1
        if clip_min is not None: new_w = max(clip_min, new_w)
        if clip_max is not None: new_w = min(clip_max, new_w)
        out[k] = new_w
    # 精修：把锚点设为 1（防止浮点误差）
    out[anchor_key] = 1.0
    return out

def build_conformal_versions_for_road(base_json: dict, base_version: str, anchor_key: str, taus: list):
    """
    输入原始 road_type_weights.json 的 dict（含多个版本），从 base_version 抽出向量做共形缩放，生成新版本。
    返回 (new_json_dict, version_names)
    """
    if base_version not in base_json:
        raise ValueError(f"Road base version '{base_version}' not found in road_type_weights.json")
    base_vec = base_json[base_version]
    new_json = dict(base_json)  # 保留原内容
    new_versions = []
    for tau in taus:
        vname = f"conformal_rt_tau{tau:g}_anchor_{anchor_key}"
        new_json[vname] = _conformal_from_base(base_vec, anchor_key, tau)
        new_versions.append(vname)
    return new_json, new_versions

def build_conformal_versions_for_lane(base_json: dict, base_version: str, anchor_key: str, taus: list):
    """
    输入原始 lane_weight_version.json 的 dict（含多个版本），从 base_version 抽出向量做共形缩放，生成新版本。
    返回 (new_json_dict, version_names)
    """
    if base_version not in base_json:
        raise ValueError(f"Lane base version '{base_version}' not found in lane_weight_version.json")
    base_vec = base_json[base_version]
    new_json = dict(base_json)
    new_versions = []
    for tau in taus:
        vname = f"conformal_lane_tau{tau:g}_anchor_{anchor_key}"
        new_json[vname] = _conformal_from_base(base_vec, anchor_key, tau)
        new_versions.append(vname)
    return new_json, new_versions

# -------------- 批量运行 KaHIP ----------------

def run_kahip_one(place, k, dist, alpha, beta, gamma,
                  road_json_path, lane_json_path,
                  road_version, lane_version,
                  csv_path, cache_dir, seed, py=sys.executable):
    cmd = [
        py, "KaHIP.py",
        "--place", place,
        "--k", str(k),
        "--dist", str(dist),
        "--cache_dir", cache_dir,
        "--lane_weight_path", str(lane_json_path),
        "--road_type_path", str(road_json_path),
        "--alpha", str(alpha),
        "--beta",  str(beta),
        "--gamma", str(gamma),
        "--road_type_version", road_version,
        "--lane_weight_version", lane_version,
        "--csv_path", str(csv_path),
        "--seed", str(seed),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = time.time() - t0
    ok = (proc.returncode == 0)
    return ok, dt, proc.stdout, proc.stderr

# -------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--places", nargs="+", required=True)
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--dist", type=int, default=3000)
    ap.add_argument("--alpha", type=float, required=True)
    ap.add_argument("--beta",  type=float, required=True)
    ap.add_argument("--gamma", type=float, required=True)
    ap.add_argument("--seeds", nargs="+", type=int, default=[0,1,2])

    ap.add_argument("--road-base-json", default="road_type_weights.json")
    ap.add_argument("--lane-base-json", default="lane_weight_version.json")
    ap.add_argument("--road-base-version", default="motorway1_rankup_1")
    ap.add_argument("--lane-base-version", default="more_lanes_heavier")

    ap.add_argument("--road-anchor", default="primary",
                    help="道路种类锚点（例如 primary）。会被固定为1。")
    ap.add_argument("--lane-anchor", default="1",
                    help="车道数锚点（字符串形式，如 '1'）。会被固定为1。")

    ap.add_argument("--road-spreads", nargs="+", type=float, default=[0.5, 1.0, 2.0],
                    help="道路种类的 tau 列表，>1放大差异，<1压缩差异。")
    ap.add_argument("--lane-spreads", nargs="+", type=float, default=[0.5, 1.0, 2.0],
                    help="车道数的 tau 列表，>1放大差异，<1压缩差异。")

    ap.add_argument("--mode", choices=["road-only","lane-only","both"], default="both",
                    help="只探索道路/只探索车道/两者同时笛卡尔积。")
    ap.add_argument("--csv", required=True, help="统一的结果 CSV（会追加写入）。")
    ap.add_argument("--out-json-dir", default="generated_weights",
                    help="输出新的 JSON 文件目录（不会覆盖原始 JSON）。")
    ap.add_argument("--cache-dir", default=str(Path.home()/ "thesis" / "min_balanced_cut" / "cache"))
    ap.add_argument("--py", default=sys.executable, help="调用 KaHIP.py 的 python 解释器路径")

    args = ap.parse_args()

    # 1) 构造新的 JSON（包含 conformal 版本）
    road_base = load_json(Path(args.road_base_json))
    lane_base = load_json(Path(args.lane_base_json))

    road_json_new = dict(road_base)
    lane_json_new = dict(lane_base)

    road_versions = [args.road_base_version]  # 总是包含原始基准
    lane_versions = [args.lane_base_version]

    if args.mode in ("road-only", "both"):
        road_json_new, new_r = build_conformal_versions_for_road(
            road_base, args.road_base_version, args.road_anchor, args.road_spreads
        )
        road_versions += new_r

    if args.mode in ("lane-only", "both"):
        lane_json_new, new_l = build_conformal_versions_for_lane(
            lane_base, args.lane_base_version, args.lane_anchor, args.lane_spreads
        )
        lane_versions += new_l

    out_dir = Path(args.out_json_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    road_json_path = out_dir / "road_type_weights_conformal.json"
    lane_json_path = out_dir / "lane_weight_version_conformal.json"
    save_json(road_json_new, road_json_path)
    save_json(lane_json_new, lane_json_path)
    print(f"[info] wrote: {road_json_path}")
    print(f"[info] wrote: {lane_json_path}")

    # 2) 组合要跑的版本
    road_list = road_versions if args.mode != "lane-only" else [args.road_base_version]
    lane_list = lane_versions if args.mode != "road-only" else [args.lane_base_version]

    # 3) 批量跑
    total_jobs = len(args.places) * len(args.seeds) * len(road_list) * len(lane_list)
    print(f"[plan] jobs = {total_jobs}  "
          f"(places={len(args.places)}, seeds={len(args.seeds)}, "
          f"road_versions={len(road_list)}, lane_versions={len(lane_list)})")

    jobs_done = 0
    for place in args.places:
        for seed in args.seeds:
            for rv in road_list:
                for lv in lane_list:
                    ok, dt, out, err = run_kahip_one(
                        place=place, k=args.k, dist=args.dist,
                        alpha=args.alpha, beta=args.beta, gamma=args.gamma,
                        road_json_path=road_json_path, lane_json_path=lane_json_path,
                        road_version=rv, lane_version=lv,
                        csv_path=args.csv, cache_dir=args.cache_dir,
                        seed=seed, py=args.py
                    )
                    jobs_done += 1
                    tag = f"{place} seed={seed} rv={rv} lv={lv}"
                    if ok:
                        print(f"[{jobs_done}/{total_jobs}] OK {tag}  ({dt:.1f}s)")
                    else:
                        print(f"[{jobs_done}/{total_jobs}] FAIL {tag}  ({dt:.1f}s)")
                        # 打印一小段错误帮助定位
                        print("STDERR (tail):", err.splitlines()[-5:])

    print("[done] all jobs submitted. Results appended to:", args.csv)

if __name__ == "__main__":
    main()
