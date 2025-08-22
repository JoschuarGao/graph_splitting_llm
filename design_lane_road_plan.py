#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
design_lane_road_plan.py
生成 (place × lane × road × seed) 的全因子实验计划。
- road 列名按你的数据写成 "weight version"
- 固定 k=6, alpha=beta=gamma=1（可按需要修改）

用法（从 CSV 抽取唯一取值，指定两个随机种子）：
python design_lane_road_plan.py \
  --csv unified/doe_results.csv \
  --seeds 0 1 \
  --out plan_lane_road.csv

或手动指定列表：
python design_lane_road_plan.py \
  --cities "Karlsruhe, Germany" "Berlin, Germany" \
  --lanes all_1 lanes_up lanes_down \
  --roads MinorPlus Equal MajorPlus \
  --seeds 0 1 \
  --out plan_lane_road.csv
"""
import argparse
import numpy as np
import pandas as pd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="可选：从现有结果 CSV 中抽取 cities/lanes/roads 的唯一值")
    ap.add_argument("--cities", nargs="*", default=None)
    ap.add_argument("--lanes", nargs="*", default=None)
    ap.add_argument("--roads", nargs="*", default=None)  # 这会写入列名 "weight version"
    ap.add_argument("--seeds", nargs="*", type=int, default=[0,1])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.csv:
        df = pd.read_csv(args.csv)
        df.columns = [c.strip() for c in df.columns]
        if args.cities is None and "place" in df.columns:
            args.cities = sorted(df["place"].dropna().astype(str).unique().tolist())
        # lane 候选
        for name in ["lane_weight_version","lane version","lane_version","lnv","laneWeightVersion"]:
            if args.lanes is None and name in df.columns:
                args.lanes = sorted(df[name].dropna().astype(str).unique().tolist())
                break
        # road 候选（含 "weight version"）
        for name in ["road_type_version","road version","road_version","rtv","road_type","roadTypeVersion","weight version"]:
            if args.roads is None and name in df.columns:
                args.roads = sorted(df[name].dropna().astype(str).unique().tolist())
                break

    if not args.cities or not args.roads:
        raise SystemExit("需要提供 cities 与 roads（可用 --cities/--roads 或 --csv 自动提取）。")
    if args.lanes is None:
        # 允许没有 lane 时只做单因子 road 计划
        args.lanes = ["all_1"]

    rows = []
    for city in args.cities:
        for lane in args.lanes:
            for road in args.roads:
                for sd in args.seeds:
                    rows.append({
                        "place": city,
                        "lane_weight_version": lane,
                        "weight version": road,   # 按你的列名写出
                        "seed": sd,
                        # 固定项
                        "k": 6, "alpha": 1.0, "beta": 1.0, "gamma": 1.0
                    })
    plan = pd.DataFrame(rows)
    plan = plan.sample(frac=1.0, random_state=42).reset_index(drop=True)
    plan.to_csv(args.out, index=False)
    print("Saved plan:", args.out)
    print(plan.head())

if __name__ == "__main__":
    main()
