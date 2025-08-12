import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CACHE_DIR = os.path.join(ROOT_DIR, "cached_maps")
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# KaHIP.py 仍然建议绝对路径；但你也可以放到工程里并用 ROOT_DIR 拼
KAHIP_PY_PATH = "/Users/joschuagao/Desktop/Masterarbeit/KaHIP.py"

KAHIP_CLI_ARGS = {
    "place": "--place",
    "k": "--k",
    "dist": "--dist",
    "cache_dir": "--cache_dir",
    "road_type_version": "--road_type_version",
    "road_type_path": "--road_type_path",
    "lane_weight_version": "--lane_weight_version",
    "lane_weight_path": "--lane_weight_path",
    "alpha": "--alpha",
    "beta": "--beta",
    "gamma": "--gamma",
    "csv_path": "--csv_path",
}
# 兼容旧代码（如果其它文件误用 ARG_MAP）
ARG_MAP = KAHIP_CLI_ARGS



PREFERRED_OUTPUT = ["json", "csv"]
HTML_NAME_TEMPLATE = "partition_{safe_place}_k{k}.html"
