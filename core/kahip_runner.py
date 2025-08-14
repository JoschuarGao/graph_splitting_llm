import os
import sys
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional

from core.config import (
    KAHIP_PY_PATH,
    KAHIP_CLI_ARGS,  
    OUTPUT_DIR,
    CACHE_DIR,
    RESULT_BASE,
)

# Default File Names for Weights
# These default filenames are used if the calling code does not specify a path.
ROAD_TYPE_FILE = "road_type_weights.json"     
LANE_WEIGHT_FILE = "lane_weight_version.json"


# Helper Functions
def _safe(s: str) -> str:
    """Convert a string to a safe format for filenames by removing commas and replacing spaces with underscores."""
    return s.replace(",", "").replace(" ", "_")


def build_kahip_cmd(params: Dict[str, Any]) -> list:
    """
    Build the command line to execute KaHIP.py based on provided parameters.

    Args:
        params: Dictionary of arguments that match the CLI argument names of KaHIP.py.

    Returns:
        A list representing the command line to be executed.
    """
    if not os.path.isfile(KAHIP_PY_PATH):
        raise FileNotFoundError(f"KaHIP.py not found: {KAHIP_PY_PATH}")

    cmd = [sys.executable, KAHIP_PY_PATH]

    def add_arg(name: str, value):
        """Add an argument to the command if it exists in KAHIP_CLI_ARGS and the value is not None."""
        if value is None:
            return
        if name not in KAHIP_CLI_ARGS:
            return
        cmd.extend([KAHIP_CLI_ARGS[name], str(value)])

    # Basic parameters
    for key in ["place", "k", "dist", "cache_dir", "alpha", "beta", "gamma", "csv_path"]:
        add_arg(key, params.get(key))

    # Road Type Weights (version + path) — if path is missing, use default file
    add_arg("road_type_version", params.get("road_type_version"))
    add_arg("road_type_path", params.get("road_type_path") or ROAD_TYPE_FILE)

    # Lane Weights (version + path) — if path is missing, use default file
    add_arg("lane_weight_version", params.get("lane_weight_version"))
    add_arg("lane_weight_path", params.get("lane_weight_path") or LANE_WEIGHT_FILE)

    return cmd


def _expected_json_path(params: Dict[str, Any]) -> str:
    """
    Construct the expected JSON output path for the KaHIP result based on parameters.
    """
    base_dir = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver = params.get("road_type_version") or "unknown"
    today_str = datetime.now().strftime("%Y-%m-%d")
    k = int(params["k"])

    lane_ver = params.get("lane_weight_version")
    fname = f"{lane_ver}_edges_partitions_k{k}.json" if lane_ver else f"edges_partitions_k{k}.json"

    return os.path.join(base_dir, safe_place, road_ver, today_str, fname)


def _fallback_find_json(params: Dict[str, Any]) -> Optional[str]:
    """
    Fallback: Search for a JSON file matching the expected filename pattern
    in the result directory for today's date.
    """
    base_dir = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver = params.get("road_type_version") or "unknown"
    today_str = datetime.now().strftime("%Y-%m-%d")
    k = int(params["k"])
    date_dir = os.path.join(base_dir, safe_place, road_ver, today_str)
    if not os.path.isdir(date_dir):
        return None

    # Search for matching JSON files (with or without lane_ver prefix)
    cands = [
        os.path.join(date_dir, f)
        for f in os.listdir(date_dir)
        if f.endswith(f"edges_partitions_k{k}.json")
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]


# Main Function to Run KaHIP
def run_kahip(params: Dict[str, Any] = None, **kwargs) -> str:
    """
    Run KaHIP.py with the provided parameters.

    Supports two calling styles:
        run_kahip(params=dict(...))
        run_kahip(place=..., k=..., ...)

    Returns:
        Path to the generated JSON file from KaHIP.py.
    """
    # Merge params and kwargs into a single dictionary
    if params is None:
        params = kwargs
    else:
        params = {**params, **kwargs}

    # Set default values for cache and CSV paths
    params.setdefault("cache_dir", CACHE_DIR)
    params.setdefault("csv_path", os.path.join(OUTPUT_DIR, "results.csv"))

    # Automatically set default weight paths if not provided
    params.setdefault("road_type_path", ROAD_TYPE_FILE)
    params.setdefault("lane_weight_path", LANE_WEIGHT_FILE)

    # Check required parameters (as per KaHIP.py argparse requirements)
    required = ["place", "k", "dist", "road_type_version", "lane_weight_version"]
    missing = [r for r in required if not params.get(r)]
    if missing:
        raise ValueError(f"Missing required parameters: {missing} (these are mandatory in KaHIP.py)")

    # Build and execute the command
    cmd = build_kahip_cmd(params)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if proc.returncode != 0:
        raise RuntimeError(
            "KaHIP.py execution failed:\n"
            f"CMD: {' '.join(cmd)}\n"
            f"STDERR:\n{proc.stderr}\n"
            f"STDOUT:\n{proc.stdout}"
        )

    # Determine the expected JSON output path
    json_path = _expected_json_path(params)
    if not os.path.exists(json_path):
        # Try fallback search
        alt = _fallback_find_json(params)
        if alt:
            return alt
        k = int(params.get("k", -1))  # For error message
        raise FileNotFoundError(
            "KaHIP output JSON not found.\n"
            f"Expected path: {json_path}\n"
            f"Ensure KaHIP.py writes JSON (edges_partitions_k{k}.json or <lane_ver>_edges_partitions_k{k}.json).\n"
            f"STDOUT:\n{proc.stdout}"
        )
    return json_path
