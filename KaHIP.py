import networkx as nx
import os
import ast
import osmnx as ox
import matplotlib.pyplot as plt
import math
import tempfile
import argparse
import kaminpar
import json
import csv
import numpy as np
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import itertools
from collections import defaultdict
from shapely.geometry import LineString
from datetime import datetime


def load_weights(version="all_1", path="road_type_weights.json"):
    with open(path, "r") as f:
        all_weights = json.load(f)
    return all_weights[version]


def load_lane_weights(version=None, path="lane_weight_version.json"):
    if version and path and os.path.isfile(path):
        with open(path, "r") as f:
            all_weights = json.load(f)
            return all_weights.get(version, None)
    return None


def write_metis_weighted(G, path):
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
            f.write(line +"\n")

def save_result_to_csv(city, version, k, cut_count, cut_weight, total_weight, csv_path, lane_weight_version=None, alpha=1.0, beta=1.0, gamma=0.1):
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
    
    pos = {node: (data["x"], data["y"]) for node, data in G.nodes(data=True) if "x" in data and "y" in data}
    weights = [data.get("weight", 1.0) for _, _, data in G.edges(data=True)]

    if not weights or not pos:
        print("Insufficient data for plotting edge weights.")
        return

    norm = mcolors.Normalize(vmin=min(weights), vmax=max(weights))
    cmap = cm.viridis
    edge_colors = [cmap(norm(weight)) for weight in weights]

    fig, ax = plt.subplots(figsize=(10, 10))
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

def process_place(place,road_type_weights,version, k=3,dist=5000, cache_dir='./cached_maps', csv_path="results.csv",
                  lane_weight_config=None, lane_weight_version=None,alpha=1.0, beta=1.0, gamma=0.1):

    
    safe_name = place.replace(",","").replace(" ","_")
    os.makedirs(cache_dir,exist_ok=True)
    cache_path = os.path.join(cache_dir,f"{safe_name}.graphml")

    if os.path.exists(cache_path):
        G_original = ox.load_graphml(cache_path)
    else:
        G_original = ox.graph_from_address(place, dist=dist, network_type="drive")
        ox.save_graphml(G_original, cache_path)
    # if an exact place name inputed, then only the map of this region will be downloaded, otherwise, the map of the whole city will be download
    G_original = G_original.to_undirected()
    G = nx.Graph(G_original)
    G.remove_edges_from(nx.selfloop_edges(G))

    # weights
    for u, v, data in G.edges(data=True):
        highway = data.get("highway", "unclassified")
        if isinstance(highway, list):
            highway = highway[0]
        base_weight = road_type_weights.get(highway, road_type_weights.get("default",1))

        # get the number of lanes
        lanes =  data.get("lanes")
        try:
            lane_count = int(lanes) if lanes else 1
        except:
            lane_count = 1

        if lane_weight_config:
            lane_factor = lane_weight_config.get(str(lane_count),lane_weight_config.get("default",1.0))
        else:
            lane_factor = 1

        # get the lenth of the roads
        length = data.get("length",1)
        # set weight with softmax function
        length_factor = max(0.1, 1/math.exp((length-500)/100)+1)
       
        #set the upperor lower limit of the weight to avoid the weight being too large or too small
        # alpha, beta, gamma = 1.0, 1.0, 0.1
        scaled_weight = math.log1p(length_factor)
        total_weight = alpha*base_weight + beta*lane_factor + gamma*scaled_weight
        data["weight"] = max(0.2, min(total_weight, 10))
        

    # METIS
    tmp_graph_path = tempfile.NamedTemporaryFile(suffix=".metis", delete=False).name
    write_metis_weighted(G, tmp_graph_path)

    # KaMinPar partition

    instance = kaminpar.KaMinPar(num_threads=1, ctx=kaminpar.default_context())
    graph = kaminpar.load_graph(tmp_graph_path, kaminpar.GraphFileFormat.METIS, compress=False)
    partition = instance.compute_partition(graph, k=k, eps=0.1)

    # color
    cmap = plt.get_cmap("tab20")
    color_map = [cmap(i / k) for i in range(k)]

    # 构建映射
    node_list = list(G.nodes())
    node_to_partition = {node: partition[i] for i, node in enumerate(node_list)}

    #node_colors = []
    #for node in G_original.nodes():
        # if some nodes were droped in the simple graph, then they will be set as partition 0
        #part = node_to_partition.get(node, 0 )
        #node_colors.append(color_map[part])

    #fig, ax = plt.subplots(figsize=(10, 10))
    #ax.set_facecolor("white")
    #ox.plot_graph(G_original, node_color=node_colors, node_size=10, ax=ax, show=False, close=False)


    # get the cutted edges
    # 统计总权重
    total_weight = sum(data.get("weight", 1.0) for _, _, data in G.edges(data=True))
    cut_weight_total = sum(
        G.get_edge_data(u, v).get("weight", 1.0)
        for u, v in G.edges()
        if node_to_partition[u] != node_to_partition[v]
    )
    cut_ratio = cut_weight_total / total_weight if total_weight > 0 else 0
    cut_edges = []
    cut_weight_total = 0
    #cut_edges_weights 
    for u, v in G.edges():
        pu, pv = node_to_partition[u], node_to_partition[v]
        if pu != pv:
            u_xy = (G.nodes[u]['x'], G.nodes[u]['y'])
            v_xy = (G.nodes[v]['x'], G.nodes[v]['y'])
            cut_edges.append((u_xy, v_xy, pu, pv))

            edge_data = G.get_edge_data(u,v)
            weight = edge_data.get("weight",1)
            cut_weight_total += weight

    pos = {node: (data["x"], data["y"]) for node, data in G.nodes(data=True) if "x" in data and "y" in data}
    weights = [data.get("weight", 1.0) for _, _, data in G.edges(data=True)]
    norm = mcolors.Normalize(vmin=min(weights), vmax=max(weights))
    cmap = cm.viridis
    edge_colors = [cmap(norm(weight)) for weight in weights]

    fig, ax = plt.subplots(figsize=(10, 10))

    #cut_edge_list = []
    #uncut_edge_list = []

    #for u,v in G.edges():
        #pu, pv = node_to_partition(u, -1), node_to_partition.get(v, -1)
        #if pu != pv:
            #cut_edge_list.append((u,v))
        #else:
            #uncut_edge_list.append((u,v))

    nx.draw_networkx_edges(G, pos, edge_color=edge_colors, edge_cmap=cmap,
                           edge_vmin=min(weights), edge_vmax=max(weights), width=0.5, ax=ax)
    nx.draw_networkx_nodes(G, pos, node_size=1, ax=ax)
    #edge_labels = {
        #(u,v):f"{d.get('weight',1):.1f}"
        #for u,v,d in G.edges(data=True)
    #}
    #nx.draw_networkx_edge_labels(
        #G,pos,
        #edge_labels=edge_labels,
        #font_size=6,
        #label_pos=0.5,
        #rotate=False,
        #ax=ax
    #)

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


    
    #cluster midpoint
    midpoints_by_region_pair = defaultdict(list)
    for u_xy, v_xy, pu, pv in cut_edges:
        midpoint = ((u_xy[0] + v_xy[0]) / 2, (u_xy[1] + v_xy[1]) / 2)
        key = tuple(sorted((pu, pv)))
        midpoints_by_region_pair[key].append(midpoint)

    

    # 按区域对画连线
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
    ax.set_title(f"Graph Partitioning of {place}", fontsize=14)
    #ax.text(0.75, 0.05, 
            #f"Number of Cut Edges: {len(cut_edges)}\nCut Edge Weight Sum: {cut_weight_total:.2f}",
            #transform=ax.transAxes, fontsize=14, ha='left', va='top', color="black", 
            #bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.3'))

    # save the figure
    """output_dir = "figures"
    os.makedirs(output_dir,exist_ok=True)
    #safe_place = place.replace(",","").replace(" ","_")

    
    
    # current date
    today_str = datetime.now().strftime("%Y-%m-%d")

    existing_files = [
        f for f in os.listdir(output_dir)
        if f.startswith(f"{safe_name}_k{k}") and f.endswith(".png")
    ]
    run_index = len(existing_files) + 1  # 第几次

    # filename
    filename = f"{safe_name}_k{k}_{version}"
    if lane_weight_version:
        filename += f"_{lane_weight_version}"
    filename += f"a_{alpha}_b{beta}_g{gamma}"
    filename += f"_{today_str}_run{run_index}.png"
    save_path = os.path.join(output_dir, filename)


    save_path = os.path.join(output_dir, filename)
    plt.savefig(save_path, dpi=300)"""
    # current date
    today_str = datetime.now().strftime("%Y-%m-%d")

    base_dir = os.path.expanduser("~/Desktop/masterarbeit/result")
    city_dir = os.path.join(base_dir, safe_name)
    version_dir = os.path.join(city_dir, version)
    date_dir = os.path.join(version_dir, today_str)
    os.makedirs(date_dir, exist_ok=True)

    # count the existed run file
    existing_files = [
        f for f in os.listdir(date_dir)
        if f.startswith("run") and f.endswith(".png")
    ]
    run_index = len(existing_files) + 1

    # filename
    filename = f"run{run_index}_k{k}_a{alpha}_b{beta}_g{gamma}.png"
    if lane_weight_version:
        filename = f"{lane_weight_version}_" + filename

    # save the final path
    save_path = os.path.join(date_dir, filename)

    # save the figure
    plt.savefig(save_path, dpi=300)
    print(f"Figure saved to: {save_path}")
    plt.close()

    for pid in range(k):
        sub_nodes = [node for node in G.nodes() if node_to_partition.get(node) == pid]
        subgraph = G.subgraph(sub_nodes).copy()
        sub_pos = {n:(G.nodes[n]["x"], G.nodes[n]["y"]) for n in subgraph.nodes()}

        fig_sub, ax_sub = plt.subplots(figsize=(10,10))
        weights_sub = [data.get("weight", 1.0) for _,_, data in subgraph.edges(data=True)]
        if weights_sub :
            norm_sub = mcolors.Normalize(vmin=min(weights),vmax=max(weights))
            cmap_sub = cm.viridis
            edge_colors = [cmap_sub(norm_sub(w)) for w in weights_sub]
            nx.draw_networkx_edges(subgraph, sub_pos, edge_color=edge_colors, width=2,ax=ax_sub)
        nx.draw_networkx_nodes(subgraph, sub_pos, node_size=1, ax=ax_sub)
        ax_sub.set_title(f"Partition{pid} fo {place}", fontsize=14)
        ax_sub.set_axis_off()

        part_filename = f"partition_{pid}_k{k}_run{run_index}.png"
        part_save_path = os.path.join(date_dir, part_filename)
        plt.savefig(part_save_path, dpi=300)
        print(f"saved sub-partition figure:{part_save_path}")

    print(f"Figure saved to:{save_path}")

    # 保存每条边权重的可视化图
    #weight_map_dir = os.path.join("figures", "edge_weight_maps")
    #os.makedirs(weight_map_dir, exist_ok=True)
    #weight_map_path = os.path.join(weight_map_dir, f"{safe_place}_weights_k{k}_{today_str}_run{run_index}.png")
    #plot_edge_weights(G, save_path=weight_map_path, title=f"{place} - Edge Weights")


    os.remove(tmp_graph_path)
    # record the result
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    save_result_to_csv(
        place, version, k, len(cut_edges), cut_weight_total, total_weight,
        csv_path, lane_weight_version,
        alpha=alpha, beta=beta, gamma=gamma
    )



    # 保存每条边的分区信息（用于 GNN）
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

    # 输出路径
    json_dir = os.path.join(base_dir, safe_name, version, today_str)
    weight_map_dir = os.path.join(base_dir, "edge_weight_maps")
    os.makedirs(json_dir, exist_ok=True)
    json_filename = f"edges_partitions_k{k}.json"
    if lane_weight_version:
        json_filename = f"{lane_weight_version}_" + json_filename
    json_path = os.path.join(json_dir, json_filename)

    with open(json_path, "w") as f_json:
        json.dump({"edges": edge_partition_info}, f_json, indent=2)
    print(f"Partitioned edge info saved to: {json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph Partitioning for a City Road Network")
    parser.add_argument("--place", type=str, required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--dist", type=int, default=5000)
    parser.add_argument("--csv_path", type=str, default=os.path.expanduser("~/Desktop/masterarbeit/result/results.csv"))
    parser.add_argument("--cache_dir", type=str, default="./cached_maps")
    parser.add_argument("--road_type_version", type=str, required=True)
    parser.add_argument("--lane_weight_version", type=str, required=True)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--beta", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=0.1)

    args = parser.parse_args()
    road_type_weights = load_weights(args.road_type_version)
    lane_weight_config = load_lane_weights(args.lane_weight_version)

    process_place(
        place=args.place,
        road_type_weights=road_type_weights,
        version=args.road_type_version,
        k=args.k,
        dist=args.dist,
        cache_dir=args.cache_dir,
        csv_path=args.csv_path,
        lane_weight_config=lane_weight_config,
        lane_weight_version=args.lane_weight_version,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma
    )