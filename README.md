<<<<<<< HEAD
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
            
        -   Render Folium via `gui.visualize.make_map(...)` (HTML)
            
    -   `app_gui` (Tkinter)
        
        -   Sliders → call **process_place** in `KaHIP.py` (in-process)
            
        -   Reads a temp CSV line → shows cut metrics
            
-   **Fallback**
    
    -   `core.partition_fallback.spectral_partition(...)` → simple spectral clustering if KaHIP/KaMinPar unavailable
        
    -   `core.partition_fallback.gdfs_from_assignment(...)` → builds GeoDataFrames from a node→partition dict


## 4. Data Flow

### 4.1  **Input**
    
    -   Place name (`--place`, e.g., `"Karlsruhe, Germany"`)
        
    -   Parameters: `k, alpha, beta, gamma, road_type_version, lane_weight_version`
        
    -   Weight files: `road_type_weights.json`, `lane_weight_version.json`
        
### 4.2  **Processing**
    
    -   `osm_loader.load_graph(place, dist)` → GraphML cache under `cached_maps/`
        
    -   Assign edge weights in `KaHIP.py`:
        
        -   road type (base weight)
            
        -   lane factor (from lane version table)
            
        -   length factor (smoothed / bounded), then combine by `alpha/beta/gamma`
            
    -   `write_metis_weighted(...)` → METIS
        
    -   `KaMinPar` → partition vector
        
    -   Compute cut edges, cut ratios
        
### 4.3  **Output**
    
    -   **PNG** (`result/<place>/<version>/<YYYY-MM-DD>/[run...].png`)
        
    -   **CSV** appended metrics (same date dir or configured `csv_path`)
        
    -   **JSON** edges with partition labels (`.../edges_partitions_k{k}.json`)
        
    -   **Folium HTML** maps (`outputs/partition_<place>_k<k>.html` via `visualize.make_map`)

## 5.  Parameter Semantics

-   `k` : number of partitions
    
-   `alpha` : weight for **road_type** base weight
    
-   `beta` : weight for **lane_count** factor
    
-   `gamma` : weight for **length-derived** factor
    
-   `road_type_version` : selects a key from `road_type_weights.json`
    
-   `lane_weight_version` : selects a key from `lane_weight_version.json`
    

> GUIs ensure versions exist (dropdown from JSON keys).  
> `kahip_runner.py` sets defaults and builds the correct KaHIP CLI args.
## 6. How to run
### 6.1 CLI
python KaHIP.py \
  --place "Karlsruhe, Germany" \
  --k 4 --dist 5000 \
  --road_type_version all_1 --road_type_path road_type_weights.json \
  --lane_weight_version all_1 --lane_weight_path lane_weight_version.json \
  --alpha 1.0 --beta 1.0 --gamma 0.1 \
  --csv_path results.csv
python app_qt.py
### 6.2 GUI
#### 6.2.1 PyQt 
Adjust sliders (alpha/beta/gamma), pick versions from dropdown, click "Run / Update"
#### 6.2.2 Tkinter
python graph_partition_gui.py
### 6.3 Batch
python run_experiments_from_json.py
Iterates over parameter_combinations_part1.json and appends to the daily CSV

## 7. Outputs & Conventions

-   **Results root**: taken from env `RESULT_BASE`, else `./result/`
    
-   Per run:
    
    -   Figures: `result/<safe_place>/<version>/<YYYY-MM-DD>/<lane_ver_?>run{N}_k{k}_a{alpha}_b{beta}_g{gamma}.png`
        
    -   JSON: `.../<lane_ver_?>edges_partitions_k{k}.json`
        
    -   CSV: appended line with `cut_edge_count`, `cut_edge_weight_sum`, `total_weight`, `cut_ratio`, parameters
        
-   Folium HTML (GUI): `outputs/partition_<safe_place>_k<k>.html`## Outputs & Conventions

-   **Results root**: taken from env `RESULT_BASE`, else `./result/`
    
-   Per run:
    
    -   Figures: `result/<safe_place>/<version>/<YYYY-MM-DD>/<lane_ver_?>run{N}_k{k}_a{alpha}_b{beta}_g{gamma}.png`
        
    -   JSON: `.../<lane_ver_?>edges_partitions_k{k}.json`
        
    -   CSV: appended line with `cut_edge_count`, `cut_edge_weight_sum`, `total_weight`, `cut_ratio`, parameters
        
-   Folium HTML (GUI): `outputs/partition_<safe_place>_k<k>.html`
## 8. File-by-File Details

-   **`KaHIP.py`**  
    CLI pipeline: load/calc weights → write METIS → run KaMinPar → compute cut edges → export PNG/CSV/JSON.  
    Provides `process_place(...)` for GUIs.
    
-   **`core/config.py`**  
    Global paths (CACHE_DIR, OUTPUT_DIR, RESULT_BASE), CLI arg map (`KAHIP_CLI_ARGS`), HTML filename template.
    
-   **`core/kahip_runner.py`**  
    Builds the KaHIP command (`python KaHIP.py --...`) from a params dict, runs it, and **infers** the expected JSON path (with lane version prefix fallback). Returns that JSON path to the GUI.
    
-   **`core/osm_loader.py`**  
    `load_graph(place, dist)` → OSMnx download or GraphML cache; always returns an undirected NetworkX graph.
    
-   **`core/results_reader.py`**  
    `read_kahip_json(path)` & `parse_from_json(G, data)`; maps KaHIP JSON fields back to the exact `(u,v,key)` in OSMnx GeoDataFrames; flags `is_cut`.
    
-   **`core/partition_fallback.py`**  
    `spectral_partition(G,k)` & `gdfs_from_assignment(...)` – backup method when KaHIP is unavailable; produces `nodes_gdf`, `edges_gdf`.
    
-   **`gui/visualize.py`**  
    `compute_cut_stats(edges_gdf)` and `make_map(nodes_gdf, edges_gdf, place, k)`: render colored internal edges by partition, overlay dashed cut boundaries, sample nodes; save HTML to `outputs/`.
    
-   **`app_qt.py`**  
    PyQt5 UI: parameter controls, debounce, background thread (`PipelineThread`) to call `kahip_runner.run_kahip`, map embed via `QWebEngineView`, stats panel.
    
-   **`gui/app_gui.py`**  
    Tkinter embedding; alternative lightweight GUI wrapper around the same pipeline primitives.
    
-   **`graph_partition_gui.py`**  
    Minimal Tkinter GUI with sliders; calls `process_place(...)` directly; parses temp CSV to show metrics.
    
-   **`run_experiments_from_json.py`**  
    Batch runner: for each param set in JSON, `subprocess.run([python, KaHIP.py, ...])`, append metrics to a unified CSV.
## 9. Tips

-   If a **version key** like `motorway1_rankup_1` isn’t in the JSON weight files, GUIs should block run and prompt to select an existing version.
    
-   When GUIs call `run_kahip(...)`, they **fix** `road_type_path` to `road_type_weights.json` and only pass version strings—ensure those files are present in the working directory.



=======
# graph_splitting_llm
Add llm to the graph splitting software
>>>>>>> d1213c09374b1ad7d656042d70d246e4faa987ab
