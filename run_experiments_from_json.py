import json
import subprocess
import os

# 加载组合参数
with open("parameter_combinations_part1.json", "r") as f:
    param_combos = json.load(f)

for idx, combo in enumerate(param_combos):
    print(f"▶️ Running {idx+1}/{len(param_combos)}: {combo['place']} k={combo['k']}")
    
    cmd = [
    "python3", "KaHIP.py",
    "--place", combo["place"],
    "--road_type_weights", json.dumps(combo["road_type_weights"]),
    "--lane_weights", json.dumps(combo["lane_weights"]),
    "--k", str(combo["k"]),
    "--alpha", str(combo["alpha"]),
    "--beta", str(combo["beta"]),
    "--gamma", str(combo["gamma"]),
    "--csv_path", os.path.expanduser("~/Desktop/masterarbeit/result/results.csv")
]
    subprocess.run(cmd)
