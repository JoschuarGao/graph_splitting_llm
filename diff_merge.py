# diff_merge.py
# Minimal, self-contained merge engine: diff → inherit → optional micro-refine → optional local-opt refine
# Graph format assumed: JSON with {"nodes": {...}, "edges": {...}}
# Each edge: {"u": "n1", "v": "n2", "geom": [[x,y],...], "partition": int, "type": str, "lanes": int, "length": float, "cut": bool}

from __future__ import annotations
import json, math, argparse, time
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set, Any, Iterable, Optional

# ---------- I/O ----------

def load_graph(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        G = json.load(f)
    if "nodes" not in G or "edges" not in G:
        raise ValueError("graph json must have 'nodes' and 'edges'")

    # ⭐ 这里加：按 eid 重新建键（容错）
    E = G.get("edges", {})
    # 看前几个条目判断是否需要 rekey
    need_rekey = False
    for k, v in list(E.items())[:10]:
        if isinstance(v, dict) and "eid" in v and str(k) != str(v["eid"]):
            need_rekey = True
            break
    if need_rekey:
        newE = {}
        for k, v in E.items():
            ek = str(v.get("eid", k))
            newE[ek] = v
        G["edges"] = newE

    build_index(G)
    return G


def save_graph(G: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(G, f, ensure_ascii=False, indent=2)

def build_index(G: Dict[str, Any]) -> None:
    """Build helper maps: node_to_edges, degree, partitions load, cut list."""
    node_to_edges = defaultdict(list)
    for eid, e in G["edges"].items():
        node_to_edges[e["u"]].append(eid)
        node_to_edges[e["v"]].append(eid)
    G["node_to_edges"] = node_to_edges
    # optional: mark cut edges if not present
    if not all(("cut" in e) for e in G["edges"].values()):
        compute_cut_flags(G)

# ---------- basic cut flags ----------

def compute_cut_flags(G: Dict[str, Any]) -> None:
    for e in G["edges"].values():
        p = e.get("partition")
        u, v = e["u"], e["v"]
        p_u = _majority_partition_of_node(G, u)
        p_v = _majority_partition_of_node(G, v)
        e["cut"] = (p_u is not None and p_v is not None and p_u != p_v) or (p is None)

def _majority_partition_of_node(G: Dict[str, Any], nid: str) -> Optional[int]:
    parts = []
    for eid in G["node_to_edges"].get(nid, []):
        p = G["edges"][eid].get("partition")
        if p is not None:
            parts.append(p)
    if not parts:
        return None
    c = Counter(parts)
    return c.most_common(1)[0][0]

# ---------- diff ----------

def diff_graphs(G_old: Dict[str, Any], G_new: Dict[str, Any]) -> Dict[str, List[str]]:
    added, removed, changed, unchanged = [], [], [], []
    old = G_old["edges"]; new = G_new["edges"]
    for eid, e in new.items():
        if eid not in old:
            e["status"] = "added"; added.append(eid); continue
        e0 = old[eid]
        if _edge_changed(e0, e):
            e["status"] = "changed"; changed.append(eid)
        else:
            e["status"] = "unchanged"; unchanged.append(eid)
    for eid in old:
        if eid not in new:
            removed.append(eid)
    return {"added": added, "removed": removed, "changed": changed, "unchanged": unchanged}

def _edge_changed(e0: Dict[str, Any], e1: Dict[str, Any]) -> bool:
    def _neq(a, b): 
        if a is None and b is None: return False
        return a != b
    # treat these as semantic changes; tune as needed
    if _neq(e0.get("lanes"), e1.get("lanes")): return True
    if _neq(e0.get("type"), e1.get("type")): return True
    if abs(float(e0.get("length", 0.0)) - float(e1.get("length", 0.0))) > 1e-3: return True
    return False

# ---------- scheme 1: neighbor-inherit ----------

def merge_inherit(G_old: Dict[str, Any], G_new: Dict[str, Any], diff: Dict[str, List[str]],
                  load_balance_hint: bool = True) -> None:
    part_sizes = _partition_load(G_old)
    for eid in diff["added"] + diff["changed"]:
        _assign_partition_inherit(eid, G_old, G_new, part_sizes if load_balance_hint else None)

def _partition_load(G: Dict[str, Any]) -> Dict[int, int]:
    load = defaultdict(int)
    for e in G["edges"].values():
        p = e.get("partition")
        if p is not None:
            load[int(p)] += 1
    return dict(load)

def _assign_partition_inherit(eid: str, G_old: Dict[str, Any], G_new: Dict[str, Any],
                              part_sizes: Optional[Dict[int, int]] = None) -> int:
    e = G_new["edges"][eid]
    u, v = e["u"], e["v"]
    neigh_parts = []
    for nid in (u, v):
        for ne in G_old.get("node_to_edges", {}).get(nid, []):
            p = G_old["edges"][ne].get("partition")
            if p is not None:
                neigh_parts.append(int(p))
    chosen: Optional[int] = None
    if neigh_parts:
        cnt = Counter(neigh_parts)
        best = cnt.most_common()
        top_freq = best[0][1]
        cands = [p for p, c in best if c == top_freq]
        if len(cands) == 1 or not part_sizes:
            chosen = cands[0]
        else:
            chosen = min(cands, key=lambda p: part_sizes.get(p, 0))
    else:
        # fallback: use majority partition of endpoints in NEW graph
        p_u = _majority_partition_of_node(G_new, u)
        p_v = _majority_partition_of_node(G_new, v)
        if p_u is not None and p_v is not None and p_u == p_v:
            chosen = int(p_u)
        else:
            chosen = int(p_u or p_v or 0)
    e["partition"] = chosen
    return chosen

# ---------- boundary micro-refine (safe tiny tweak inside scheme 1) ----------

def needs_boundary_micro_refine(eid: str, G_old: Dict[str, Any], G_new: Dict[str, Any],
                                dist_to_cut_m: float = 20.0,
                                imbalance_tol: float = 0.01) -> bool:
    """Heuristics: near a cut, vote tie, or load overflow."""
    e = G_new["edges"][eid]
    # vote tie?
    u, v = e["u"], e["v"]
    parts = []
    for nid in (u, v):
        for ne in G_old.get("node_to_edges", {}).get(nid, []):
            p = G_old["edges"][ne].get("partition")
            if p is not None: parts.append(int(p))
    if parts:
        cnt = Counter(parts)
        if len(parts) >= 2 and len([1 for c in cnt.values() if c == max(cnt.values())]) > 1:
            return True
    # near a cut?
    if _near_cut(G_old, e, dist_to_cut_m):
        return True
    # crude load check after inherit:
    chosen = e.get("partition")
    if chosen is not None:
        loads = _partition_load(G_new)  # after inherit
        avg = max(1.0, sum(loads.values()) / max(1, len(loads)))
        if loads.get(int(chosen), 0) > (1.0 + imbalance_tol) * avg:
            return True
    return False

def _near_cut(G: Dict[str, Any], e: Dict[str, Any], d: float) -> bool:
    # approximate: if any incident old edge was marked cut, treat as near-cut
    for nid in (e["u"], e["v"]):
        for ne in G.get("node_to_edges", {}).get(nid, []):
            if G["edges"][ne].get("cut", False):
                return True
    return False

def micro_refine_boundary(G_new: Dict[str, Any], seed_eids: List[str],
                          r_hops: int = 1, move_budget: int = 30) -> None:
    """Tiny local hill-climb between the 2 most relevant partitions around seeds."""
    V, E = collect_halo(G_new, seed_eids, r_hops=r_hops, edge_limit=400)
    if not E: return
    # only allow moves between existing partitions in halo
    parts = Counter([G_new["edges"][eid].get("partition") for eid in E if G_new["edges"][eid].get("partition") is not None])
    allow = set([p for p,_ in parts.most_common(3)])  # 2~3 parts
    moved = 0
    # greedy: try flipping edge partition to majority of its endpoints' neighborhoods if it reduces cut
    base_cut = _halo_cut(G_new, E)
    improved = True
    while improved and moved < move_budget:
        improved = False
        for eid in list(E):
            pe = G_new["edges"][eid].get("partition")
            if pe is None: continue
            if pe not in allow: continue
            best_p = _best_partition_local(G_new, eid, allow)
            if best_p is None or best_p == pe: continue
            # test change
            old_p = pe
            G_new["edges"][eid]["partition"] = best_p
            new_cut = _halo_cut(G_new, E)
            if new_cut <= base_cut:
                base_cut = new_cut
                moved += 1
                improved = True
            else:
                # revert
                G_new["edges"][eid]["partition"] = old_p
        # stop if no progress
    # done

def _best_partition_local(G: Dict[str, Any], eid: str, allow: Set[int]) -> Optional[int]:
    e = G["edges"][eid]
    u, v = e["u"], e["v"]
    votes = []
    for nid in (u, v):
        for ne in G["node_to_edges"].get(nid, []):
            if ne == eid: continue
            p = G["edges"][ne].get("partition")
            if p is not None and int(p) in allow:
                votes.append(int(p))
    if not votes:
        return None
    return Counter(votes).most_common(1)[0][0]

def _halo_cut(G: Dict[str, Any], E: Iterable[str]) -> int:
    cut = 0
    for eid in E:
        e = G["edges"][eid]
        p = e.get("partition")
        u, v = e["u"], e["v"]
        pu = _majority_partition_of_node(G, u)
        pv = _majority_partition_of_node(G, v)
        if pu is not None and pv is not None and pu != pv:
            cut += 1
        elif p is None:
            cut += 1
    return cut

# ---------- scheme 2: local optimize on halo (broader than micro) ----------

def collect_halo(G: Dict[str, Any], seed_edges: List[str], r_hops: int = 2, edge_limit: int = 5000) -> Tuple[Set[str], Set[str]]:
    V: Set[str] = set()
    E: Set[str] = set(seed_edges)
    frontier = set()
    for eid in seed_edges:
        e = G["edges"][eid]
        V.add(e["u"]); V.add(e["v"])
        frontier.add(e["u"]); frontier.add(e["v"])
    hops = 0
    while hops < r_hops and len(E) < edge_limit and frontier:
        nxt = set()
        for nid in frontier:
            for eid in G["node_to_edges"].get(nid, []):
                if eid not in E:
                    E.add(eid)
                u, v = G["edges"][eid]["u"], G["edges"][eid]["v"]
                if u not in V: V.add(u); nxt.add(u)
                if v not in V: V.add(v); nxt.add(v)
        frontier = nxt
        hops += 1
    return V, E

def local_opt_refine(G_new: Dict[str, Any], seed_edges: List[str],
                     r_hops: int = 2, max_iter: int = 5) -> None:
    """Light k-way label-propagation style refine on halo. No external libs."""
    V, E = collect_halo(G_new, seed_edges, r_hops=r_hops, edge_limit=20000)
    if not E: return
    # partitions present in halo
    parts = set()
    for eid in E:
        p = G_new["edges"][eid].get("partition")
        if p is not None: parts.add(int(p))
    if not parts:
        return
    # LP-like iterations over edges: move to majority of incident partitions if reduces cut
    prev_cut = _halo_cut(G_new, E)
    for _ in range(max_iter):
        changed = 0
        for eid in list(E):
            p_old = G_new["edges"][eid].get("partition")
            p_new = _best_partition_local(G_new, eid, parts)
            if p_new is None or p_new == p_old: continue
            G_new["edges"][eid]["partition"] = p_new
            if _halo_cut(G_new, E) <= prev_cut:
                prev_cut = _halo_cut(G_new, E)
                changed += 1
            else:
                G_new["edges"][eid]["partition"] = p_old  # revert
        if changed == 0:
            break

# ---------- front API ----------

def merge_driver(base_graph: str, new_graph: str, out_graph: str,
                 strategy: str = "inherit", micro_refine: bool = True,
                 r_hops_micro: int = 1, move_budget: int = 30,
                 r_hops_local: int = 2) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, List[str]]]:
    G_old = load_graph(base_graph)
    G_new = load_graph(new_graph)
    diff = diff_graphs(G_old, G_new)

    # scheme 1: inherit
    merge_inherit(G_old, G_new, diff, load_balance_hint=True)

    # optional micro-refine if near boundary
    if micro_refine:
        seeds = [eid for eid in diff["added"] + diff["changed"] if needs_boundary_micro_refine(eid, G_old, G_new)]
        if seeds:
            micro_refine_boundary(G_new, seeds, r_hops=r_hops_micro, move_budget=move_budget)

    # scheme 2: local optimize (on demand)
    if strategy == "local":
        seeds = diff["added"] + diff["changed"]
        if seeds:
            local_opt_refine(G_new, seeds, r_hops=r_hops_local, max_iter=6)

    # done
    save_graph(G_new, out_graph)
    return G_old, G_new, diff

# ---------- CLI ----------

def _cli():
    ap = argparse.ArgumentParser(description="Graph merge (inherit / local refine) + diff")
    ap.add_argument("--base_graph", required=True)
    ap.add_argument("--new_graph", required=True)
    ap.add_argument("--out_graph", required=True)
    ap.add_argument("--strategy", choices=["inherit","local"], default="inherit")
    ap.add_argument("--micro_refine", action="store_true", default=False)
    ap.add_argument("--micro_r_hops", type=int, default=1)
    ap.add_argument("--micro_move_budget", type=int, default=30)
    ap.add_argument("--local_r_hops", type=int, default=2)
    args = ap.parse_args()

    t0 = time.time()
    merge_driver(args.base_graph, args.new_graph, args.out_graph,
                 strategy=args.strategy,
                 micro_refine=args.micro_refine,
                 r_hops_micro=args.micro_r_hops,
                 move_budget=args.micro_move_budget,
                 r_hops_local=args.local_r_hops)
    print(f"[merge] done in {time.time()-t0:.2f}s")

if __name__ == "__main__":
    _cli()
