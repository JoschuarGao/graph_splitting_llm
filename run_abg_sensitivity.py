#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess, sys, os
import pandas as pd

# ===== Fixed settings you can change =====
CITIES = ["Los Angeles, USA"]
SEEDS  = [0, 1, 2, 3, 4]             # multi-seed
K_LIST = [2, 4, 8]                   # <-- explore k here
DIST   = 5000
ROAD_VER = "all_1"
LANE_VER = "v1"

# Results (same base folder as before)
BASE_DIR = os.path.expanduser("~/thesis/min_balanced_cut/unified")
TRIALS_CSV = os.path.expanduser("~/thesis/min_balanced_cut/unified/abg_trials_LA.csv")
SUMMARY_ALPHA   = os.path.join(BASE_DIR, "summary_alpha_grid.csv")
SUMMARY_BETA    = os.path.join(BASE_DIR, "summary_beta_grid.csv")
SUMMARY_GAMMA   = os.path.join(BASE_DIR, "summary_gamma_grid.csv")
SUMMARY_ALL_IN1 = os.path.join(BASE_DIR, "summary_all_params_by_k.csv")  # new: combined

KAHIP = os.path.abspath("KaHIP.py")

def run_once(place, k, a, b, g, seed):
    cmd = [
        sys.executable, KAHIP,
        "--place", place,
        "--k", str(k),
        "--dist", str(DIST),
        "--road_type_version", ROAD_VER,
        "--lane_weight_version", LANE_VER,
        "--alpha", str(a),
        "--beta",  str(b),
        "--gamma", str(g),
        "--csv_path", TRIALS_CSV,
        "--seed", str(seed),
    ]
    print("[RUN]", " ".join(cmd))
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.returncode != 0:
        print("[ERR]", res.stderr)
    else:
        # print the last line as a simple heartbeat
        lines = res.stdout.strip().splitlines()
        if lines:
            print(lines[-1])

def summarize():
    """Create per-k summaries for alpha/beta/gamma, plus one combined table."""
    if not os.path.exists(TRIALS_CSV):
        print("[WARN] no trials file found:", TRIALS_CSV)
        return

    df = pd.read_csv(TRIALS_CSV)
    # keep only rows from this configuration
    df = df[(df["weight_version"]==ROAD_VER) &
            (df["lane_weight_version"]==LANE_VER) &
            (df["dist"]==DIST) &
            (df["k"].isin(K_LIST))]

    # ---- Alpha grid (gamma=0, beta=1) ----
    a_vals = [0.5, 1.0, 1.5, 2.0]
    df_a = df[(df["gamma"]==0.0) & (df["beta"]==1.0) & (df["alpha"].isin(a_vals))]
    if not df_a.empty:
        sum_a = (df_a
                 .groupby(["k","alpha"], as_index=False)["cut_ratio"]
                 .agg(['mean','std'])
                 .reset_index())
        sum_a.columns = ["k","alpha","mean_cut_ratio","std_cut_ratio"]
        sum_a.to_csv(SUMMARY_ALPHA, index=False)
        print("[WRITE]", SUMMARY_ALPHA)

    # ---- Beta grid (gamma=0, alpha=1) ----
    b_vals = [0.5, 1.0, 1.5, 2.0]
    df_b = df[(df["gamma"]==0.0) & (df["alpha"]==1.0) & (df["beta"].isin(b_vals))]
    if not df_b.empty:
        sum_b = (df_b
                 .groupby(["k","beta"], as_index=False)["cut_ratio"]
                 .agg(['mean','std'])
                 .reset_index())
        sum_b.columns = ["k","beta","mean_cut_ratio","std_cut_ratio"]
        sum_b.to_csv(SUMMARY_BETA, index=False)
        print("[WRITE]", SUMMARY_BETA)

    # ---- Gamma grid (alpha=1, beta=1) ----
    g_vals = [0.0, 0.5, 1.0, 1.5]
    df_g = df[(df["alpha"]==1.0) & (df["beta"]==1.0) & (df["gamma"].isin(g_vals))]
    if not df_g.empty:
        sum_g = (df_g
                 .groupby(["k","gamma"], as_index=False)["cut_ratio"]
                 .agg(['mean','std'])
                 .reset_index())
        sum_g.columns = ["k","gamma","mean_cut_ratio","std_cut_ratio"]
        sum_g.to_csv(SUMMARY_GAMMA, index=False)
        print("[WRITE]", SUMMARY_GAMMA)

    # ---- One compact summary (stacked) ----
    # we add a common schema: [k, param, name, value, mean, std]
    frames = []
    if not df_a.empty:
        tmp = sum_a.copy()
        tmp["param"] = "alpha"
        tmp.rename(columns={"alpha":"value"}, inplace=True)
        tmp["name"] = "A1(alpha|beta=1,gamma=0)"
        frames.append(tmp[["k","param","name","value","mean_cut_ratio","std_cut_ratio"]])
    if not df_b.empty:
        tmp = sum_b.copy()
        tmp["param"] = "beta"
        tmp.rename(columns={"beta":"value"}, inplace=True)
        tmp["name"] = "A1(beta|alpha=1,gamma=0)"
        frames.append(tmp[["k","param","name","value","mean_cut_ratio","std_cut_ratio"]])
    if not df_g.empty:
        tmp = sum_g.copy()
        tmp["param"] = "gamma"
        tmp.rename(columns={"gamma":"value"}, inplace=True)
        tmp["name"] = "A2(gamma|alpha=1,beta=1)"
        frames.append(tmp[["k","param","name","value","mean_cut_ratio","std_cut_ratio"]])

    if frames:
        all_in1 = pd.concat(frames, ignore_index=True)
        all_in1.sort_values(by=["param","k","value"], inplace=True)
        all_in1.to_csv(SUMMARY_ALL_IN1, index=False)
        print("[WRITE]", SUMMARY_ALL_IN1)

def main():
    os.makedirs(os.path.dirname(TRIALS_CSV), exist_ok=True)

    for K in K_LIST:
        print("\n=== K =", K, "===")

        # A1 alpha: gamma=0, beta=1
        for a in [0.5, 1.0, 1.5, 2.0]:
            for city in CITIES:
                for s in SEEDS:
                    run_once(city, K, a, 1.0, 0.0, s)

        # A1 beta: gamma=0, alpha=1
        for b in [0.5, 1.0, 1.5, 2.0]:
            for city in CITIES:
                for s in SEEDS:
                    run_once(city, K, 1.0, b, 0.0, s)

        # A2 gamma: alpha=1, beta=1
        for g in [0.0, 0.5, 1.0, 1.5]:
            for city in CITIES:
                for s in SEEDS:
                    run_once(city, K, 1.0, 1.0, g, s)

    summarize()

if __name__ == "__main__":
    main()
