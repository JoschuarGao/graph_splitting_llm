import os

# Root and Directory Configuration
# Get the root directory of the project (parent of current file's parent folder)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directory for cached map files
CACHE_DIR = os.path.join(ROOT_DIR, "cached_maps")

# Directory for general outputs
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")

# Create necessary directories if they don't exist
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Result Directory Configuration
# Base directory for result storage (can be overridden by environment variable)
RESULT_BASE = os.environ.get("RESULT_BASE") or os.path.join(ROOT_DIR, "result")
os.makedirs(RESULT_BASE, exist_ok=True)


# KaHIP Script Path
# Path to KaHIP.py (can be overridden by environment variable)
KAHIP_PY_PATH = os.environ.get("KAHIP_PY_PATH") or os.path.join(ROOT_DIR, "KaHIP.py")


# KaHIP CLI Argument Mapping
# Mapping between parameter names and KaHIP.py CLI arguments
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

# Backward compatibility (if other files mistakenly use ARG_MAP)
ARG_MAP = KAHIP_CLI_ARGS

# Output Preferences
# Preferred output formats
PREFERRED_OUTPUT = ["json", "csv"]

# Template for HTML map output file name
HTML_NAME_TEMPLATE = "partition_{safe_place}_d{dist}_k{k}.html"

