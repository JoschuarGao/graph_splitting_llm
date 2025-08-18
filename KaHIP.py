import networkx as nx
import os
import osmnx as ox
import matplotlib.pyplot as plt
import math
import tempfile
import argparse
import kaminpar
import json
import csv
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from collections import defaultdict
from shapely.geometry import LineString
from datetime import datetime
from pyproj import Transformer


def load_weights(version="all_1", path="road_type_weights.json"):
    """Load road type weights from JSON file."""
    with open(path, "r") as f:
        all_weights = json.load(f)
    return all_weights[version]


def load_lane_weights(version=None, path="lane_weight_version.json"):
    """Load lane weight configuration from JSON file."""
    if version and path and os.path.isfile(path):
        with open(path, "r") as f:
            all_weights = json.load(f)
            return all_weights.get(version, None)
    return None

# Highway filtering utilities
def _edge_has_allowed_highway(edge_data, allowed: set) -> bool:
    """edge_data['highway'] may be str or list; keep if it matches any in allowed."""
    if allowed is None:
        return True
    hw = edge_data.get("highway")
    if hw is None:
        return False
    if isinstance(hw, (list, tuple, set)):
        return any((str(h) in allowed) for h in hw)
    return str(hw) in allowed

def filter_graph_by_highway(G: nx.Graph, allowed: set) -> nx.Graph:
    """Return a subgraph containing only edges with highway types in allowed (preserving node attributes)."""
    if allowed is None:
        return G
    H = G.__class__()  # Preserve graph type
    H.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        if _edge_has_allowed_highway(data, allowed):
            H.add_edge(u, v, **data)
    return H



def write_metis_weighted(G, path):
    """
    Write a weighted graph in METIS format for KaMinPar input.
    """
    node_list = list(G.nodes())
    node_map = {node: idx+1 for idx, node in enumerate(node_list)}
    written_edges = set()
    edge_lines = [""] * len(node_list)

    for u, v in G.edges():
        edge_key = tuple(sorted((u, v)))
        if edge_key in written_edges:
            continue
        written_edges.add(edge_key)

        edge_data = G.get_edge_data(u, v)
        weight = edge_data.get("weight", 1)
        weight = int(weight) if weight > 0 else 1

        u_idx = node_map[u] - 1
        v_idx = node_map[v] - 1

        edge_lines[u_idx] += f"{node_map[v]} {weight} "
        edge_lines[v_idx] += f"{node_map[u]} {weight} "

    with open(path, "w") as f:
        f.write(f"{len(node_list)} {len(written_edges)} 1\n")
        for line in edge_lines:
            f.write(line + "\n")
    return node_list


def generate_csv_path(base_dir=None):
    """
    Generate a unique CSV file path based on today's date and run index.
    """
    base_dir = base_dir or os.environ.get("RESULT_BASE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "result")
    csv_dir = base_dir
    today_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(csv_dir, exist_ok=True)

    existing_files = [
        f for f in os.listdir(csv_dir)
        if f.startswith("results_" + today_str)
    ]
    run_index = len(existing_files) + 1
    return os.path.join(csv_dir, f"results_{today_str}_run_{run_index:04d}.csv")


def save_result_to_csv(city, version, k, cut_count, cut_weight, total_weight, csv_path, lane_weight_version=None, alpha=1.0, beta=1.0, gamma=0.1):
    """
    Append partition results to a CSV file, creating headers if file does not exist.
    """
    file_exists = os.path.isfile(csv_path)
    with open(csv_path, mode="a", newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "city", "weight_version", "lane_weight_version", "k",
                "cut_edge_count", "cut_edge_weight_sum", "total_weight",
                "alpha", "beta", "gamma", "cut_ratio"
            ])

        cut_ratio = cut_weight / total_weight if total_weight > 0 else 0
        writer.writerow([
            city, version, lane_weight_version, k,
            cut_count, cut_weight, total_weight,
            alpha, beta, gamma, f"{cut_ratio:.4f}"
        ])


def plot_edge_weights(G, save_path=None, title="Edge Weight Visualization"):
    """
    Visualize edge weights on the graph using a color map.
    """
    transformer = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)

    lon_lat_pos = {
        node: (data["x"], data["y"])
        for node, data in G.nodes(data=True)
        if "x" in data and "y" in data
    }
    pos = {
        node: transformer.transform(x, y)
        for node, (x, y) in lon_lat_pos.items()
    }

    weights = [data.get("weight", 1.0) for _, _, data in G.edges(data=True)]
    if not weights or not pos:
        print("Insufficient data for plotting edge weights.")
        return

    norm = mcolors.Normalize(vmin=min(weights), vmax=max(weights))
    cmap = cm.get_cmap("tab20")
    edge_colors = [cmap(norm(weight)) for weight in weights]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_facecolor("black")

    xticks = ax.get_xticks()
    yticks = ax.get_yticks()
    ax.set_xticks(xticks)
    ax.set_yticks(yticks)
    ax.set_xticklabels([f"{val/1000:.1f} km" for val in xticks], fontsize=10, color="white")
    ax.set_yticklabels([f"{val/1000:.1f} km" for val in yticks], fontsize=10, color="white")
    ax.tick_params(axis='both', colors='white')
    ax.set_xlabel("Easting (km)", color="white")
    ax.set_ylabel("Northing (km)", color="white")

    nx.draw_networkx_edges(
        G, pos,
        edge_color=edge_colors,
        edge_cmap=cmap,
        edge_vmin=min(weights),
        edge_vmax=max(weights),
        width=2,
        ax=ax
    )
    nx.draw_networkx_nodes(G, pos, node_size=1, ax=ax)

    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax)
    cbar.set_label("Edge Weight")

    ax.set_title(title)
    ax.set_axis_off()

    if save_path:
        plt.savefig(save_path, dpi=300)
        print(f"Edge weight map saved to: {save_path}")
    else:
        plt.show()


def process_place(place, road_type_weights, version, k=3, dist=5000, cache_dir='./cached_maps', csv_path="results.csv",
                  lane_weight_config=None, lane_weight_version=None, alpha=1.0, beta=1.0, gamma=0.1,
                  road_types=None, output_dir=None):
    """
    Main function for processing a place:
    - Load or download road network
    - Assign weights to edges
    - Partition the graph using KaMinPar
    - Visualize and save results
    """
    safe_name = place.replace(",", "").replace(" ", "_")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{safe_name}.graphml")

    # Load cached graph or download from OSM
    if os.path.exists(cache_path):
        G_original = ox.load_graphml(cache_path)
    else:
        G_original = ox.graph_from_address(place, dist=dist, network_type="drive")
        ox.save_graphml(G_original, cache_path)

    try:
        from osmnx import utils_graph as _ug
        G_undirected = _ug.get_undirected(G_original, merge_edges=True)
    except Exception:
        try:
            G_undirected = ox.get_undirected(G_original)
        except Exception:
            G_undirected = G_original.to_undirected()
    G = nx.Graph(G_undirected)
    G.remove_edges_from(nx.selfloop_edges(G))


    allowed = None
    if road_types:
        if isinstance(road_types, str):
            allowed = set(t.strip() for t in road_types.split(",") if t.strip())
        else:
            allowed = set(map(str, road_types))
    G = filter_graph_by_highway(G, allowed)
    if G.number_of_edges() == 0:
        raise ValueError("No edges left after filtering by road_types. Try selecting more highway types.")

    # Assign edge weights
    for u, v, data in G.edges(data=True):
        highway = data.get("highway", "unclassified")
        if isinstance(highway, list):
            highway = highway[0]
        base_weight = road_type_weights.get(highway, road_type_weights.get("default", 1))

        # Get lane count
        lanes = data.get("lanes")
        try:
            lane_count = int(lanes) if lanes else 1
        except:
            lane_count = 1

        if lane_weight_config:
            lane_factor = lane_weight_config.get(str(lane_count), lane_weight_config.get("default", 1.0))
        else:
            lane_factor = 1


        # Get road length
        length = data.get("length", 1)
        # Use a smoothed factor for length
        length_factor = max(0.1, 1/math.exp((length-500)/100) + 1)

        # Scale weights with alpha, beta, gamma
        scaled_weight = math.log1p(length_factor)
        total_weight = alpha * base_weight + beta * lane_factor + gamma * scaled_weight
        data["weight"] = max(0.2, min(total_weight, 10))

    SCALE = 1000
    for u, v, data in G.edges(data=True):
        w = data.get("weight", 1.0)
        data["weight"] = int(round(w * SCALE))

    # Write graph to temporary METIS file
    tmp_graph_path = tempfile.NamedTemporaryFile(suffix=".metis", delete=False).name
    node_list = write_metis_weighted(G, tmp_graph_path)

    # Partition the graph using KaMinPar
    instance = kaminpar.KaMinPar(num_threads=1, ctx=kaminpar.default_context())
    graph = kaminpar.load_graph(tmp_graph_path, kaminpar.GraphFileFormat.METIS, compress=False)
    partition = instance.compute_partition(graph, k=k, eps=0.1)

    # Map node to partition
    node_to_partition = {node: partition[i] for i, node in enumerate(node_list)}

    # Collect cut edges
    total_weight = sum(d.get("weight", 1.0) for _, _, d in G.edges(data=True))
    cut_edges = []
    cut_weight_total = 0.0
    for u, v in G.edges():
        pu, pv = node_to_partition[u], node_to_partition[v]
        if pu != pv:
            u_xy = (G.nodes[u]['x'], G.nodes[u]['y'])
            v_xy = (G.nodes[v]['x'], G.nodes[v]['y'])
            cut_edges.append((u_xy, v_xy, pu, pv))
            cut_weight_total += G.get_edge_data(u, v).get("weight", 1.0)

    cut_ratio = cut_weight_total / total_weight if total_weight > 0 else 0

    # Draw partition visualization
    pos = {node: (data["x"], data["y"]) for node, data in G.nodes(data=True) if "x" in data and "y" in data}
    weights = [data.get("weight", 1.0) for _, _, data in G.edges(data=True)]
    norm = mcolors.Normalize(vmin=min(weights), vmax=max(weights))
    cmap = cm.get_cmap("tab20c")
    edge_colors = [cmap(norm(weight)) for weight in weights]

    fig, ax = plt.subplots(figsize=(10, 10))
    nx.draw_networkx_edges(G, pos, edge_color=edge_colors, edge_cmap=cmap,
                           edge_vmin=min(weights), edge_vmax=max(weights), width=0.5, ax=ax)
    nx.draw_networkx_nodes(G, pos, node_size=1, ax=ax)

    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax)
    cbar.set_label("Edge Weight")

    ax.set_title(f"Graph Partitioning of {place}", fontsize=14)
    ax.text(0.05, 0.05,
        f"Number of Cut Edges: {len(cut_edges)}\n"
        f"Cut Edge Weight Sum: {cut_weight_total:.2f}\n"
        f"Cut Ratio: {cut_ratio:.2%}",
        transform=ax.transAxes, fontsize=14, ha='left', va='top', color="black",
        bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.3'))

    # Draw dashed lines between partitions for cut edges
    midpoints_by_region_pair = defaultdict(list)
    for u_xy, v_xy, pu, pv in cut_edges:
        midpoint = ((u_xy[0] + v_xy[0]) / 2, (u_xy[1] + v_xy[1]) / 2)
        key = tuple(sorted((pu, pv)))
        midpoints_by_region_pair[key].append(midpoint)

    for (p1, p2), points in midpoints_by_region_pair.items():
        if len(points) < 2:
            continue
        points_sorted = sorted(points, key=lambda p: (p[0], p[1]))
        line = LineString(points_sorted)
        color_idx = p1 * k + p2
        line_color = cmap((color_idx % 20) / 20)
        x, y = line.xy
        ax.plot(x, y, color=line_color, linewidth=3, alpha=0.9, linestyle='--', label=f"{p1}-{p2}")

    plt.legend()

    # Save main figure
    today_str = datetime.now().strftime("%Y-%m-%d")
    base_dir = output_dir or os.environ.get("RESULT_BASE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "result")
    base_dir = os.path.abspath(os.path.expanduser(base_dir))

    date_dir = os.path.join(base_dir, safe_name, version, today_str)
    os.makedirs(date_dir, exist_ok=True)
    run_index = len([f for f in os.listdir(date_dir) if f.startswith("run") and f.endswith(".png")]) + 1
    filename = f"run{run_index}_k{k}_a{alpha}_b{beta}_g{gamma}.png"
    if lane_weight_version:
        filename = f"{lane_weight_version}_" + filename
    save_path = os.path.join(date_dir, filename)
    plt.savefig(save_path, dpi=300)
    plt.close(fig)
    print(f"Figure saved to: {save_path}")

    # Save sub-partition figures
    for pid in range(k):
        sub_nodes = [node for node in G.nodes() if node_to_partition.get(node) == pid]
        subgraph = G.subgraph(sub_nodes).copy()
        sub_pos = {n: (G.nodes[n]["x"], G.nodes[n]["y"]) for n in subgraph.nodes()}

        fig_sub, ax_sub = plt.subplots(figsize=(10, 10))
        ax_sub.set_facecolor("black")
        weights_sub = [data.get("weight", 1.0) for _, _, data in subgraph.edges(data=True)]
        if weights_sub:
            norm_sub = mcolors.Normalize(vmin=min(weights_sub), vmax=max(weights_sub))
            cmap_sub = cm.get_cmap("tab20c")
            edge_colors = [cmap_sub(norm_sub(w)) for w in weights_sub]
            nx.draw_networkx_edges(subgraph, sub_pos, edge_color=edge_colors, width=2, ax=ax_sub)
        nx.draw_networkx_nodes(subgraph, sub_pos, node_size=1, ax=ax_sub)
        ax_sub.set_title(f"Partition {pid} for {place}", fontsize=14)
        ax_sub.set_axis_off()

        part_filename = f"partition_{pid}_k{k}_run{run_index}.png"
        part_save_path = os.path.join(date_dir, part_filename)
        plt.savefig(part_save_path, dpi=300)
        plt.close(fig_sub)
        print(f"Saved sub-partition figure: {part_save_path}")

    # Save results to CSV
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    save_result_to_csv(place, version, k, len(cut_edges), cut_weight_total, total_weight,
                       csv_path, lane_weight_version, alpha=alpha, beta=beta, gamma=gamma)

    # Save edge partition info for GNN or further analysis
    edge_partition_info = []
    for u, v, data in G.edges(data=True):
        pu, pv = node_to_partition.get(u, -1), node_to_partition.get(v, -1)
        edge_partition_info.append({
            "u": u,
            "v": v,
            "partition_u": pu,
            "partition_v": pv,
            "weight": data.get("weight", 1.0),
            "is_cut": pu != pv
        })

    json_filename = f"edges_partitions_k{k}.json"
    if lane_weight_version:
        json_filename = f"{lane_weight_version}_" + json_filename
    json_path = os.path.join(date_dir, json_filename)
    with open(json_path, "w") as f_json:
        json.dump({"edges": edge_partition_info}, f_json, indent=2)
    print(f"Partitioned edge info saved to: {json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph Partitioning for a City Road Network")
    parser.add_argument("--place", type=str, required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--dist", type=int, default=5000)
    parser.add_argument("--cache_dir", type=str, default="./cached_maps")
    parser.add_argument("--road_type_version", type=str, required=True)
    parser.add_argument("--road_type_path", type=str, default="road_type_weights.json")
    parser.add_argument("--lane_weight_version", type=str, required=True)
    parser.add_argument("--lane_weight_path", type=str, default="lane_weight_version.json")
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--beta", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=0.1)
    parser.add_argument("--csv_path", type=str, default="results.csv")
    parser.add_argument("--output_dir", type=str, default=None,
                        help="Override result base directory (default uses RESULT_BASE or ./result).")
    parser.add_argument("--road_types", type=str, default=None,
                        help="Comma-separated OSM 'highway' types to include (e.g. 'motorway,primary,secondary').")

    args = parser.parse_args()

    # Expand and resolve CSV path
    csv_path = os.path.expanduser(args.csv_path)
    if not os.path.isabs(csv_path):
        base_dir = os.path.abspath(os.path.expanduser(
            os.environ.get("RESULT_BASE") or
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "result")
        ))
        os.makedirs(base_dir, exist_ok=True)
        csv_path = os.path.join(base_dir, csv_path)

    road_type_weights = load_weights(args.road_type_version, args.road_type_path)
    lane_weight_config = load_lane_weights(args.lane_weight_version, args.lane_weight_path)

    process_place(
        place=args.place,
        road_type_weights=road_type_weights,
        version=args.road_type_version,
        k=args.k,
        dist=args.dist,
        cache_dir=args.cache_dir,
        csv_path=csv_path,
        lane_weight_config=lane_weight_config,
        lane_weight_version=args.lane_weight_version,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma,
        road_types=args.road_types,
        output_dir=args.output_dir,
    )

