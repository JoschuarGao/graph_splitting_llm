# validate_versions.py
import json, sys, pathlib

LWP = pathlib.Path("lane_weight_version.json")
RTW = pathlib.Path("road_type_weights.json")
PC  = pathlib.Path("parameter_combinations_part1.json")

def load_json(p): 
    with open(p, "r", encoding="utf-8") as f: 
        return json.load(f)

def main():
    lane = load_json(LWP)
    road = load_json(RTW)
    combos = load_json(PC)

    lane_keys = set(lane.keys())
    road_keys = set(road.keys())

    bad = []
    for i, item in enumerate(combos):
        lv = item.get("lane_weight_version")
        rv = item.get("road_type_version")
        if lv not in lane_keys or rv not in road_keys:
            bad.append((i, rv, lv))

    print("Lane versions:", sorted(lane_keys))
    print("Road versions:", sorted(road_keys))
    if bad:
        print("\n[ERROR] Found invalid entries (index, road_type_version, lane_weight_version):")
        for t in bad: print("  ", t)
        sys.exit(1)
    else:
        print("\nAll parameter combinations are valid.")

if __name__ == "__main__":
    main()
