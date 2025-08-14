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

# Helpers
def _safe(s: str) -> str:
    """Sanitize a string for use in file names by removing commas and spaces."""
    return s.replace(",", "").replace(" ", "_")


def build_kahip_cmd(params: Dict[str, Any]) -> list:
    """
    Build the command-line argument list for invoking KaHIP.py based on argparse names.
    """
    if not os.path.isfile(KAHIP_PY_PATH):
        raise FileNotFoundError(f"KaHIP.py not found: {KAHIP_PY_PATH}")

    cmd = [sys.executable, KAHIP_PY_PATH]

    def add_arg(name: str, value):
        """Append CLI argument if it exists and is not None."""
        if value is None:
            return
        if name not in KAHIP_CLI_ARGS:
            return
        cmd.extend([KAHIP_CLI_ARGS[name], str(value)])

    # Basic parameters
    for key in ["place", "k", "dist", "cache_dir", "alpha", "beta", "gamma", "csv_path"]:
        add_arg(key, params.get(key))

    # Road type weights (version + path)
    add_arg("road_type_version", params.get("road_type_version"))
    add_arg("road_type_path",    params.get("road_type_path"))

    # Lane weights (version + path)
    add_arg("lane_weight_version", params.get("lane_weight_version"))
    add_arg("lane_weight_path",    params.get("lane_weight_path"))

    return cmd


def _expected_json_path(params: Dict[str, Any]) -> str:
    """
    Construct the expected output JSON path based on parameters and today's date.
    """
    base_dir   = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver   = params.get("road_type_version") or "unknown"
    today_str  = datetime.now().strftime("%Y-%m-%d")
    k          = int(params["k"])

    lane_ver = params.get("lane_weight_version")
    fname = f"{lane_ver}_edges_partitions_k{k}.json" if lane_ver else f"edges_partitions_k{k}.json"

    return os.path.join(base_dir, safe_place, road_ver, today_str, fname)


def _fallback_find_json(params: Dict[str, Any]) -> Optional[str]:
    """
    Attempt to locate a JSON file in the expected output folder if the exact expected path is missing.
    Returns the most recently modified matching file, or None if not found.
    """
    base_dir   = RESULT_BASE
    safe_place = _safe(params["place"])
    road_ver   = params.get("road_type_version") or "unknown"
    today_str  = datetime.now().strftime("%Y-%m-%d")
    k          = int(params["k"])
    date_dir   = os.path.join(base_dir, safe_place, road_ver, today_str)

    if not os.path.isdir(date_dir):
        return None

    cands = [
        os.path.join(date_dir, f)
        for f in os.listdir(date_dir)
        if f.endswith(".json") and f.endswith(f"edges_partitions_k{k}.json")
    ]
    if not cands:
        return None
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]


def run_kahip(params: Dict[str, Any] = None, **kwargs) -> str:
    """
    Run KaHIP.py with the provided parameters and return the path to the generated JSON output.

    Supports two usage patterns:
      run_kahip(params=dict(...))
      run_kahip(place=..., k=..., ...)

    Returns

    str
        Path to the KaHIP-generated JSON file.
    """
    # Merge params and kwargs into a single dictionary
    if params is None:
        params = kwargs
    else:
        params = {**params, **kwargs}

    # Provide default values for optional parameters
    params.setdefault("cache_dir", CACHE_DIR)
    params.setdefault("csv_path",  os.path.join(OUTPUT_DIR, "results.csv"))

    # Validate required parameters (must match KaHIP.py argparse requirements)
    required = ["place", "k", "dist", "road_type_version", "lane_weight_version"]
    missing = [r for r in required if not params.get(r)]
    if missing:
        raise ValueError(f"Missing required parameters: {missing} (these are required in KaHIP.py)")

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

    # Determine the expected JSON path
    json_path = _expected_json_path(params)
    if not os.path.exists(json_path):
        alt = _fallback_find_json(params)
        if alt:
            return alt
        raise FileNotFoundError(
            "KaHIP output JSON not found.\n"
            f"Expected path: {json_path}\n"
            "Make sure KaHIP.py wrote the JSON (edges_partitions_k{k}.json or lane_version-prefixed file).\n"
            f"STDOUT:\n{proc.stdout}"
        )
    return json_path
