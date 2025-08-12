import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CACHE_DIR = os.path.join(ROOT_DIR, "cached_maps")
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 改成你本机 KaHIP.py 的真实路径
KAHIP_PY_PATH = ("User/Desktop/Masterarbeit/KaHIP.py")

# 映射 GUI 参数 → 你的 KaHIP.py CLI
ARG_MAP = {
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

    "csv_path": "--csv_path"
}


HTML_NAME_TEMPLATE = "partition_{safe_place}_k{k}.html"
