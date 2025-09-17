#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess, sys, os, json, time
from pathlib import Path
from statistics import mean
from datetime import datetime
import pandas as pd
import numpy as np
import optuna

# === Config ===
CITIES = [
    "Karlsruhe, Germany",
    "Berlin, Germany",
    "Paris, France",
    "Vienna, Austria",
    "Los Angeles, USA",
]

K = 4
DIST = 5000
ROAD_VER = "all_1"
LANE_VER = "v1"
SEEDS = [0, 1, 2]   # Keep small for Optuna speed
TRIALS = 100

# === Unique run tag & output paths ===
RUN_TAG = f"5cities_k{K}_d{DIST}_{ROAD_VER}_{LANE_VER}_seeds{len(SEEDS)}_{datetime.now():%Y%m%d_%H%M}"

KAHIP_PY = os.path.abspath("KaHIP.py")
CSV_TRIALS = os.path.expanduser(f"~/thesis/min_balanced_cut/unified/abg_trials_optuna_{RUN_TAG}.csv")
OPTUNA_TRIALS_CSV = os.path.expanduser(f"~/thesis/min_balanced_cut/unified/optuna_trials_{RUN_TAG}.csv")
BEST_JSON = os.path.expanduser(f"~/thesis/min_balanced_cut/unified/best_abg_{RUN_TAG}.json")
CONV_CSV = os.path.expanduser(f"~/thesis/min_balanced_cut/unified/optuna_convergence_{RUN_TAG}.csv")

def run_once(place, alpha, beta, gamma, seed):
    cmd = [
        sys.executable, KAHIP_PY,
        "--place", place, "--k", str(K), "--dist", str(DIST),
        "--road_type_version", ROAD_VER, "--lane_weight_version", LANE_VER,
        "--alpha", str(alpha), "--beta", str(beta), "--gamma", str(gamma),
        "--csv_path", CSV_TRIALS, "--seed", str(seed),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("[ERR]", place, "seed", seed, p.stderr.strip())
    return p.returncode

def _has(df, name):  # small helper to avoid KeyError if schema drifts
    return name in df.columns

def objective(trial):
    alpha = trial.suggest_float("alpha", 0.5, 2.0)
    beta  = trial.suggest_float("beta",  0.5, 2.0)
    gamma = trial.suggest_float("gamma", 0.0, 2.0)

    # Run SAME (alpha,beta,gamma) across all cities x seeds
    for city in CITIES:
        for s in SEEDS:
            rc = run_once(city, alpha, beta, gamma, s)
            if rc != 0:
                # penalize failed runs
                return 1e9

    # Aggregate the fresh results for this (alpha,beta,gamma)
    df = pd.read_csv(CSV_TRIALS)

    # robust float matching with tolerance
    mask = (
        np.isclose(df["alpha"].astype(float), alpha, rtol=0, atol=1e-8) &
        np.isclose(df["beta"].astype(float),  beta,  rtol=0, atol=1e-8) &
        np.isclose(df["gamma"].astype(float), gamma, rtol=0, atol=1e-8)
    )
    # fixed params
    if _has(df, "k"):     mask &= (df["k"] == K)
    if _has(df, "dist"):  mask &= (df["dist"] == DIST)

    # correct column is "road_type_version" (NOT weight_version)
    if _has(df, "road_type_version"):
        mask &= (df["road_type_version"] == ROAD_VER)
    if _has(df, "lane_weight_version"):
        mask &= (df["lane_weight_version"] == LANE_VER)

    df_sub = df[mask]

    if df_sub.empty:
        # nothing matched — return large penalty so Optuna steers away
        return 1e9

    avg_cut = float(df_sub["cut_ratio"].mean())

    # Log trial summary
    os.makedirs(os.path.dirname(OPTUNA_TRIALS_CSV), exist_ok=True)
    write_header = not os.path.exists(OPTUNA_TRIALS_CSV)
    with open(OPTUNA_TRIALS_CSV, "a") as f:
        if write_header:
            f.write("trial,alpha,beta,gamma,avg_cut_ratio,rows,cities,seeds\n")
        f.write(f"{trial.number},{alpha},{beta},{gamma},{avg_cut},{len(df_sub)},{len(CITIES)},{len(SEEDS)}\n")

    return avg_cut

def main():
    study = optuna.create_study(direction="minimize")
    best_vals = []
    for _ in range(TRIALS):
        study.optimize(objective, n_trials=1, catch=(Exception,))
        best_vals.append(study.best_value)

        # write convergence
        os.makedirs(os.path.dirname(CONV_CSV), exist_ok=True)
        pd.DataFrame({"trial": list(range(1, len(best_vals)+1)),
                      "best_so_far": best_vals}).to_csv(CONV_CSV, index=False)

    # save best json (with full context)
    res = {
        "best_params": study.best_params,
        "best_value": study.best_value,
        "space": {"alpha": [0.5, 2.0], "beta": [0.5, 2.0], "gamma": [0.0, 2.0]},
        "cities": CITIES, "seeds": SEEDS, "k": K, "dist": DIST,
        "road_type_version": ROAD_VER, "lane_weight_version": LANE_VER,
        "run_tag": RUN_TAG,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    with open(BEST_JSON, "w") as f:
        json.dump(res, f, indent=2)

    print("[DONE] Optuna finished.")
    print(" -", os.path.basename(OPTUNA_TRIALS_CSV))
    print(" -", os.path.basename(BEST_JSON))
    print(" -", os.path.basename(CONV_CSV))
    print(" -", os.path.basename(CSV_TRIALS))

if __name__ == "__main__":
    main()
