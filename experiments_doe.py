
import os, sys, csv, time, subprocess
from pathlib import Path
from datetime import datetime

KAHIP_PY = Path("KaHIP.py")
RESULT_ROOT = Path.home() / "thesis" / "min_balanced_cut"   
UNIFIED_CSV = RESULT_ROOT / "unified" / "doe_results.csv"


FIXED = dict(
    place="Karlsruhe, Germany",
    k=6,
    dist=5000,
    cache_dir=str(RESULT_ROOT / "cache"),
    lane_weight_path="lane_weight_version.json",
    road_type_path="road_type_weights.json",
)


ROAD_TYPE_VERS = ["all_1", "motorway1_rankup_1", "motorway1_rankdown_1"]
LANE_VERS      = ["all_1", "more_lanes_heavier", "less_lanes_heavier"]
ALPHAS = [0.5, 1.0, 2.0]
BETAS  = [0.5, 1.0, 2.0]
GAMMAS = [0.5, 1.0, 2.0]



FIELDS = ["ts","place","k","dist",
          "alpha","beta","gamma","road_type_version","lane_weight_version",
          "cut_edge_count","cut_edge_weight_sum","total_weight","cut_ratio",
          "png_path","json_path","run_seconds"]

def ensure(p: Path): p.parent.mkdir(parents=True, exist_ok=True)

def run_once(params: dict) -> dict:
    argmap = {
        "place":"--place","k":"--k","dist":"--dist",
        "cache_dir":"--cache_dir",
        "lane_weight_path":"--lane_weight_path","lane_weight_version":"--lane_weight_version",
        "road_type_path":"--road_type_path","road_type_version":"--road_type_version",
        "alpha":"--alpha","beta":"--beta","gamma":"--gamma",
        "csv_path":"--csv_path"
    }
    cmd = [sys.executable, str(KAHIP_PY)]
    for k,v in params.items():
        if k in argmap and v is not None:
            cmd.extend([argmap[k], str(v)])

    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = time.time() - t0
    if proc.returncode != 0:
        print("CMD:", " ".join(cmd))
        print("STDERR:", proc.stderr)
        raise SystemExit("KaHIP.py failed")

    last = {}
    if UNIFIED_CSV.exists():
        with open(UNIFIED_CSV, "r", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader: last = r
    if not last:
        print("[WARN] No row read from UNIFIED_CSV. Did KaHIP.py append stats to --csv_path?")
    last["run_seconds"] = f"{dt:.2f}"
    return last

def main():
    ensure(UNIFIED_CSV)
    write_header = not UNIFIED_CSV.exists()
    with open(UNIFIED_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header: w.writeheader()

        for rtv in ROAD_TYPE_VERS:
            for lnv in LANE_VERS:
                for a in ALPHAS:
                    for b in BETAS:
                        for g in GAMMAS:
                            params = dict(FIXED)
                            params.update(
                                alpha=a, beta=b, gamma=g,
                                road_type_version=rtv,
                                lane_weight_version=lnv,
                                csv_path=str(UNIFIED_CSV)
                            )
                            print(">>", params["place"], "k=", params["k"], "abg=", a,b,g, rtv, lnv)
                            row = run_once(params)
                            out = {
                                "ts": datetime.now().isoformat(timespec="seconds"),
                                "place": params["place"], "k": params["k"],
                                "dist": params["dist"],
                                "alpha": a, "beta": b, "gamma": g,
                                "road_type_version": rtv, "lane_weight_version": lnv,
                                "cut_edge_count": row.get("cut_edge_count",""),
                                "cut_edge_weight_sum": row.get("cut_edge_weight_sum",""),
                                "total_weight": row.get("total_weight",""),
                                "cut_ratio": row.get("cut_ratio",""),
                                "png_path": row.get("png_path",""),
                                "json_path": row.get("json_path",""),
                                "run_seconds": row.get("run_seconds","")
                            }
                            w.writerow(out); f.flush()
    print("DONE ->", UNIFIED_CSV)

if __name__ == "__main__":
    main()
