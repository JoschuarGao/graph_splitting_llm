import json
import subprocess
import os
import sys
from datetime import datetime

# Use the current Python interpreter path (works with virtual environments)
python_path = sys.executable

# Current date string for naming result files
today_str = datetime.now().strftime("%Y-%m-%d")

# Unified results CSV path
csv_filename = f"results_{today_str}_full_run.csv"
csv_path = os.path.expanduser(f"~/Desktop/masterarbeit/result/{csv_filename}")

# Load parameter combinations from JSON file
with open("parameter_combinations_part1.json", "r") as f:
    param_combos = json.load(f)

# Start batch runs
for idx, combo in enumerate(param_combos):
    print(f" Running {idx + 1}/{len(param_combos)}: {combo['place']} k={combo['k']}")

    cmd = [
        python_path, "KaHIP.py",
        "--place", combo["place"],
        "--road_type_version", combo["road_type_version"],
        "--lane_weight_version", combo["lane_weight_version"],
        "--road_type_path", "road_type_weights.json",
        "--lane_weight_path", "lane_weight_version.json",
        "--k", str(combo["k"]),
        "--alpha", str(combo["alpha"]),
        "--beta", str(combo["beta"]),
        "--gamma", str(combo["gamma"]),
        "--csv_path", csv_path
    ]

    # Run KaHIP.py with the current parameter set
    subprocess.run(cmd)
