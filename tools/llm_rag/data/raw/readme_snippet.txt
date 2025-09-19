# min_balanced_cut_road_networks_osm (branch: `version_with_CutRatio`)

Graph partitioning for OpenStreetMap road networks using KaHIP/KaMinPar, with interactive GUIs (PyQt5 / Tkinter), Folium map rendering, and batch experiment tooling. This branch adds cut-ratio–aware pipelines and richer visualization.

## 1. Features

-   OSM download/cache → weighted graph build (road type / lane count / length)
    
-   Partition using KaMinPar (METIS format)
    
-   Metrics: cut edges, cut weight sum, total weight, cut ratio
    
-   Visualization: static figures + interactive Folium maps
    
-   GUIs: PyQt5 (`app_qt.py`) and Tkinter (`app_gui.py`)
    
-   Batch runs from JSON parameter sets
## 2. Project Structure & Responsibilities
```plaintext
min_balanced_cut/
├── KaHIP.py                    # CLI entry: load OSM, build weights, run KaMinPar, save PNG/CSV/JSON
├── app_qt.py                   # PyQt5 GUI: run pipeline in a thread, show map & stats
├── graph_partition_gui.py      # Tkinter GUI: simple parameter sliders + live run
├── run_experiments_from_json.py# Batch runner via subprocess calling KaHIP.py
│
├── core/
│   ├── config.py               # Paths, KaHIP CLI arg map, output templates
│   ├── kahip_runner.py         # Build command to call KaHIP.py; infer expected output paths
│   ├── osm_loader.py           # Load/download OSM graph, cache as GraphML
│   ├── results_reader.py       # Read KaHIP JSON → map (u,v,key) to GeoDataFrame partitions
│   └── partition_fallback.py   # Spectral clustering fallback + GDF builders
│
├── gui/
│   ├── visualize.py            # Folium map: color partitions, draw cut edges & boundary dashes
│   └── app_gui.py              # Tkinter embedding (alt GUI wrapper)
│
├── road_type_weights.json      # Road-type weight versions (dict of versions → per-type weights)
├── lane_weight_version.json    # Lane-count weight versions (dict of versions → factors)
├── parameter_combinations_part1.json  # Batch experiment parameter sets
│
├── cached_maps/                # (ignored) GraphML cache by place
├── outputs/                    # (ignored) Folium HTML maps, temp CSV, etc.
└── result/                     # (ignored) Dated run outputs: PNG, CSV, JSON by place/version/date
```



## 3. Call Graph
-   **CLI and  Batch**
    
    -   `run_experiments_from_json.py` → _(subprocess)_ → `KaHIP.py`
        
    -   `KaHIP.py`
        
        -   loads **weights** from `road_type_weights.json` / `lane_weight_version.json`
            
        -   loads/caches OSM via **osmnx**
            
        -   writes **METIS** file → calls **KaMinPar**
            
        -   **outputs**:
            
            -   PNG figures (overall + per-partition)
                
            -   CSV line per run (metrics)
                
            -   JSON `{ "edges": [ {u,v,partition_u,partition_v,weight,is_cut}, ... ] }`
                
-   **GUIs**
    
    -   `app_qt.py` (PyQt5)
        
        -   UI → collect params → **thread** → `core.kahip_runner.run_kahip(...)`
            
        -   `run_kahip` → _(subprocess)_ → `KaHIP.py` (same as CLI)
            
        -   Parse KaHIP JSON via `core.results_reader.parse_from_json(...)`
            
        -   Compute metrics via `gui.visualize.compute_cut_stats(...)`
            
