import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Cache directory for downloaded OSM maps
CACHE_DIR = os.path.join(ROOT_DIR, "cached_maps")
# Output directory for generated artifacts (HTML maps, etc.)
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Result directory and KaHIP configuration
# Base directory for storing KaHIP results; can be overridden by environment variable RESULT_BASE
RESULT_BASE = os.environ.get("RESULT_BASE") or os.path.join(ROOT_DIR, "result")
os.makedirs(RESULT_BASE, exist_ok=True)

# Path to the KaHIP Python runner script; can be overridden by environment variable KAHIP_PY_PATH
KAHIP_PY_PATH = os.environ.get("KAHIP_PY_PATH") or os.path.join(ROOT_DIR, "KaHIP.py")

# CLI argument mapping for KaHIP.py
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

# Backward compatibility (in case other modules still use ARG_MAP)
ARG_MAP = KAHIP_CLI_ARGS

# Output preferences
# Default preferred output formats
PREFERRED_OUTPUT = ["json", "csv"]

# HTML output filename pattern for Folium maps
HTML_NAME_TEMPLATE = "partition_{safe_place}_k{k}.html"
