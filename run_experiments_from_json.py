import json
import subprocess
import os
import sys
from datetime import datetime

# ✅ 使用当前 Python 解释器路径（兼容虚拟环境）
python_path = sys.executable

# ✅ 当前日期字符串，用于结果命名
today_str = datetime.now().strftime("%Y-%m-%d")

# ✅ 统一结果 CSV 路径
csv_filename = f"results_{today_str}_full_run.csv"
csv_path = os.path.expanduser(f"~/Desktop/masterarbeit/result/{csv_filename}")

# ✅ 加载组合参数
with open("parameter_combinations_part1.json", "r") as f:
    param_combos = json.load(f)

# ✅ 开始批量运行
for idx, combo in enumerate(param_combos):
    print(f"▶️ Running {idx + 1}/{len(param_combos)}: {combo['place']} k={combo['k']}")

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

    # ✅ 执行 KaHIP.py，传参运行
    subprocess.run(cmd)
