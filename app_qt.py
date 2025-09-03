# app_qt.py
"""
OSM Partition Viewer
"""
import time
import os
import sys
import json
import subprocess
import geopandas as gpd

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QTextEdit, QGroupBox, QFormLayout, QComboBox,
    QCheckBox, QFileDialog
)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView

# Project imports
from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR
from diff_merge import merge_driver  # only merge_driver; avoid name clash
from shapely.geometry import LineString, Point

# Fixed configuration file names
ROAD_TYPE_FILE = "road_type_weights.json"
LANE_WEIGHT_FILE = "lane_weight_version.json"


# ---------------- Pipeline Thread ----------------
class PipelineThread(QThread):
    """
    Runs the partitioning pipeline in a background thread
    to keep the UI responsive.
    """
    finished = pyqtSignal(dict)   # {'html': str, 'stats': dict, 'cache_key': tuple}
    log = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, params: dict, cache_key: tuple, parent=None):
        super().__init__(parent)
        self.params = params
        self.cache_key = cache_key

    def run(self):
        try:
            p = self.params
            self.log.emit(
                (
                    "Params: place='{place}', dist={dist}, k={k}, "
                    "alpha/beta/gamma=({alpha:.2f},{beta:.2f},{gamma:.2f}), "
                    "road_type_ver={road_ver}, lane_weight_ver={lane_ver}"
                ).format(**p)
            )

            # 1) Load graph from OSM or cache
            G = load_graph(p['place'], dist=p['dist'])
            self.log.emit(f"- Graph size: nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

            # 2) Run KaHIP partitioning
            self.log.emit("- Running KaHIP partitioning…")
            json_path = run_kahip(
                place=p['place'], k=p['k'], dist=p['dist'],
                alpha=p['alpha'], beta=p['beta'], gamma=p['gamma'],
                road_type_version=p['road_ver'],
                road_type_path=ROAD_TYPE_FILE,
                lane_weight_version=p['lane_ver'],
            )
            self.log.emit(f"- KaHIP JSON: {json_path}")

            # 3) Parse results and compute statistics
            data = read_kahip_json(json_path)
            nodes_gdf, edges_gdf = parse_from_json(G, data)
            print(edges_gdf.columns)
            import osmnx as ox
            G_updated = ox.graph_from_gdfs(nodes_gdf,edges_gdf)
            ox.settings.all_oneway=True
            ox.settings.useful_tags_way.append("part_u")
            ox.settings.useful_tags_way.append("part_v")
            ox.settings.useful_tags_way.append("is_cut")
            ox.settings.useful_tags_way.append("part")
            ox.io.save_graph_xml(G_updated,filepath='/home/yushugao/test.osm')

            stats = compute_cut_stats(edges_gdf)
            self.log.emit(
                "- Stats: edges={edges}, cut_edges={cut_edge_count}, "
                "total_w={total_weight:.4f}, cut_w={cut_edge_weight_sum:.4f}, "
                "cut_ratio={cut_ratio:.4f}, weight_ratio={weight_ratio:.4f}"
                .format(**{k: stats.get(k, 0) for k in (
                    "edges","cut_edge_count","total_weight","cut_edge_weight_sum","cut_ratio","weight_ratio"
                )})
            )

            # 4) Render Folium map and save HTML
            html = make_map(nodes_gdf, edges_gdf, p['place'], p['k'])
            self.log.emit(f"- HTML map: {html}")

            # Done
            self.finished.emit({'html': html, 'stats': stats, 'cache_key': self.cache_key})
        except Exception as e:
            self.error.emit(str(e))


# ---------------- Main Window ----------------
class MainWindow(QMainWindow):
    """
    Main application window for the OSM Partition Viewer.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSM Partition Viewer")
        self.resize(1200, 800)

        # Parameters state
        self.params = {"alpha": 1.00, "beta": 1.00, "gamma": 1.00}
        self._scale = 100  # slider scale (step = 0.01)

        # UI state
        self._map_cache = {}
        self._running = False
        self._has_ever_run = False
        self._pending_manual = False
        self._manual_dirty_style = "background:#ffe9a8;"
        self._mode = "run"  # 'run' | 'baseline' | 'update'

        # Debounce timer for auto-runs
        self._debounce_auto = QTimer(self)
        self._debounce_auto.setSingleShot(True)
        self._debounce_auto.setInterval(200)
        self._debounce_auto.timeout.connect(self.on_params_finalized)

        # Baseline state (for merge)
        self._baseline_paths = None   # dict: {merge_json}
        self._baseline_edges = None   # gpd.GeoDataFrame
        self._baseline_nodes = None   # gpd.GeoDataFrame

        # ---- Layout ----
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # Left column
        left = QVBoxLayout()
        root.addLayout(left, 0)

        # Place / dist / k
        row1 = QHBoxLayout(); left.addLayout(row1)
        row1.addWidget(QLabel("Place"))
        self.edit_place = QLineEdit("Karlsruhe, Germany"); row1.addWidget(self.edit_place, 1)

        row2 = QHBoxLayout(); left.addLayout(row2)
        row2.addWidget(QLabel("dist [m]"))
        self.spin_dist = QSpinBox(); self.spin_dist.setRange(100, 50000); self.spin_dist.setValue(5000)
        row2.addWidget(self.spin_dist)
        row2.addWidget(QLabel("k"))
        self.spin_k = QSpinBox(); self.spin_k.setRange(2, 64); self.spin_k.setValue(4)
        row2.addWidget(self.spin_k)

        # Alpha / beta / gamma sliders
        def add_param_slider(caption: str, key: str, init_float: float = 1.00):
            box = QHBoxLayout(); left.addLayout(box)
            box.addWidget(QLabel(caption))

            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, int(5.00 * self._scale))     # 0.00 ~ 5.00
            s.setValue(int(init_float * self._scale))
            s.setSingleStep(1)
            s.setPageStep(10)
            box.addWidget(s, 1)

            val_label = QLabel(f"{init_float:.2f}")
            val_label.setMinimumWidth(48)
            val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            box.addWidget(val_label)

            s.valueChanged.connect(lambda v: self._on_slider_change(v, key, val_label))
            return s, val_label

        self.sld_alpha, self.lbl_alpha_val = add_param_slider("alpha", "alpha", 1.00)
        self.sld_beta,  self.lbl_beta_val  = add_param_slider("beta",  "beta",  1.00)
        self.sld_gamma, self.lbl_gamma_val = add_param_slider("gamma", "gamma", 1.00)

        # Version selectors
        row3 = QHBoxLayout(); left.addLayout(row3)
        row3.addWidget(QLabel("road_type_version"))
        self.cmb_road_ver = QComboBox(); row3.addWidget(self.cmb_road_ver, 1)

        row3b = QHBoxLayout(); left.addLayout(row3b)
        row3b.addWidget(QLabel("lane_weight_version"))
        self.cmb_lane_ver = QComboBox(); row3b.addWidget(self.cmb_lane_ver, 1)

        # Versions reload
        row_reload = QHBoxLayout(); left.addLayout(row_reload)
        self.btn_reload_versions = QPushButton("Reload versions")
        row_reload.addWidget(self.btn_reload_versions)
        self.btn_reload_versions.clicked.connect(self._load_version_lists)

        # Run
        self.btn_run = QPushButton("Run"); left.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self._on_run_clicked)

        # Baseline & merge
        self.btn_set_baseline = QPushButton("Run as baseline")
        left.addWidget(self.btn_set_baseline)
        self.btn_set_baseline.clicked.connect(self._on_set_baseline)

        self.btn_merge_new = QPushButton("Update")
        left.addWidget(self.btn_merge_new)
        self.btn_merge_new.clicked.connect(self._on_merge_new)

        self.btn_load_json = QPushButton("Load local JSON and merge")
        left.addWidget(self.btn_load_json)
        self.btn_load_json.clicked.connect(self._on_load_json)

        # Toggle for showing update layers
        self.chk_show_updates = QCheckBox("Show updates overlays by default")
        self.chk_show_updates.setChecked(False)
        left.addWidget(self.chk_show_updates)

        # Open output folder
        self.btn_open = QPushButton("Open output folder"); left.addWidget(self.btn_open)
        self.btn_open.clicked.connect(lambda: self._open_dir(OUTPUT_DIR))

        # Top summary
        self.top_summary = QLabel("—")
        self.top_summary.setStyleSheet("color:#222; font-weight:600;")
        left.addWidget(self.top_summary)

        # Statistics box
        self.stats_box = QGroupBox("Partition Statistics")
        stats_layout = QFormLayout(self.stats_box)
        self.lbl_edges = QLabel("-")
        self.lbl_cut_cnt = QLabel("-")
        self.lbl_total_w = QLabel("-")
        self.lbl_cut_w = QLabel("-")
        self.lbl_cut_ratio = QLabel("-")
        self.lbl_w_ratio = QLabel("-")
        stats_layout.addRow("Edges", self.lbl_edges)
        stats_layout.addRow("Cut edges", self.lbl_cut_cnt)
        stats_layout.addRow("Total weight", self.lbl_total_w)
        stats_layout.addRow("Cut weight sum", self.lbl_cut_w)
        stats_layout.addRow("Cut ratio", self.lbl_cut_ratio)
        stats_layout.addRow("Weight ratio", self.lbl_w_ratio)
        left.addWidget(self.stats_box)

        # Run log
        left.addWidget(QLabel("Run Log / Metrics"))
        self.txt = QTextEdit(); self.txt.setReadOnly(True); left.addWidget(self.txt, 1)

        # Right column (map)
        self.web = QWebEngineView(self)
        root.addWidget(self.web, 1)

        # Bind param changes
        self._wire_param_changes()

        # Load versions into combo boxes
        self._load_version_lists(default_road="all_1", default_lane="all_1")

    # ---------- Load available versions ----------
    def _load_version_lists(self, default_road="all_1", default_lane="v1"):
        def _keys_from_json(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return list(data.keys()) if isinstance(data, dict) else []
            except Exception as e:
                self._log(f"[WARN] Cannot read {path}: {e}")
                return []

        road_keys = _keys_from_json(ROAD_TYPE_FILE)
        lane_keys = _keys_from_json(LANE_WEIGHT_FILE)

        self.cmb_road_ver.blockSignals(True)
        self.cmb_road_ver.clear()
        if road_keys:
            self.cmb_road_ver.addItems(road_keys)
            idx = self.cmb_road_ver.findText(default_road)
            self.cmb_road_ver.setCurrentIndex(max(0, idx))
        else:
            self.cmb_road_ver.addItems([default_road])
        self.cmb_road_ver.blockSignals(False)

        self.cmb_lane_ver.blockSignals(True)
        self.cmb_lane_ver.clear()
        if lane_keys:
            self.cmb_lane_ver.addItems(lane_keys)
            idx = self.cmb_lane_ver.findText(default_lane)
            self.cmb_lane_ver.setCurrentIndex(max(0, idx))
        else:
            self.cmb_lane_ver.addItems([default_lane])
        self.cmb_lane_ver.blockSignals(False)

        self._log(f"[Versions] road_type={self.cmb_road_ver.currentText()}, lane_weight={self.cmb_lane_ver.currentText()}")

    # ---------- KaHIP CLI integration for baseline/merge ----------
    def _run_kahip_cli(self, place: str, k: int, dist: int, road_ver: str, lane_ver: str) -> dict:
        cmd = [
            sys.executable, "KaHIP.py",
            "--place", place,
            "--k", str(k),
            "--dist", str(dist),
            "--road_type_version", road_ver,
            "--lane_weight_version", lane_ver,
            "--csv_path", os.path.expanduser("~/thesis/min_balanced_cut/unified/doe_results.csv")
        ]
        self._log(f"[KaHIP] {' '.join(cmd)}")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        merge_json = run_tag = None
        lines = []
        for line in p.stdout:
            line = line.rstrip()
            lines.append(line)
            self._log(line)
            if line.startswith("MERGE_JSON="):
                merge_json = line.split("=", 1)[1].strip()
            elif line.startswith("RUN_TAG="):
                run_tag = line.split("=", 1)[1].strip()
        code = p.wait()
        if code != 0:
            tail = "\n".join(lines[-30:])  # 最近 30 行
            raise RuntimeError(f"KaHIP.py exited with non-zero return code ({code}). Tail:\n{tail}")
        if not merge_json:
            tail = "\n".join(lines[-30:])
            raise RuntimeError(f"Could not parse MERGE_JSON=... from KaHIP.py output.\nTail:\n{tail}")
        return dict(merge_json=merge_json, run_tag=run_tag)


    # ---------- Build GDFs from merge JSON ----------
    def _gdf_from_merge_json(self, merge_json_path: str):
        with open(merge_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes = data.get("nodes", {})
        edges = data.get("edges", {})

        nd_rows = []
        for nid, nd in nodes.items():
            nd_rows.append({"nid": nid, "x": nd.get("x"), "y": nd.get("y"), "geometry": Point(nd.get("x"), nd.get("y"))})
        nodes_gdf = gpd.GeoDataFrame(nd_rows, geometry="geometry", crs="EPSG:4326")

        ed_rows = []
        for eid, e in edges.items():
            coords = e.get("geom") or []
            geom = LineString(coords) if len(coords) >= 2 else None
            is_cut_val = bool(e.get("cut", False))
            ed_rows.append({
                "eid": eid,
                "u": e.get("u"),
                "v": e.get("v"),
                # 兼容可视化：part_u/part_v 不在 JSON 时退化为单列 partition
                "partition": e.get("partition"),
                "part_u": e.get("part_u", e.get("partition")),
                "part_v": e.get("part_v", e.get("partition")),
                "type": e.get("type"),
                "lanes": e.get("lanes"),
                "length": e.get("length"),
                "is_cut": is_cut_val,
                "geometry": geom
            })
        edges_gdf = gpd.GeoDataFrame(ed_rows, geometry="geometry", crs="EPSG:4326")
        # 丢掉无几何的行，避免后续渲染报错
        edges_gdf = edges_gdf[edges_gdf["geometry"].notna()].copy()
        try:
            edges_gdf = edges_gdf[~edges_gdf.geometry.is_empty]
        except Exception:
            pass
        return nodes_gdf, edges_gdf

    # ---------- Buttons ----------
    def _on_set_baseline(self):
        self._mode = "baseline"
        p = self._gather_params()
        paths = self._run_kahip_cli(
            place=p["place"], k=p["k"], dist=p["dist"],
            road_ver=p["road_ver"], lane_ver=p["lane_ver"]
        )
        self._baseline_paths = paths

        nodes_gdf, edges_gdf = self._gdf_from_merge_json(paths["merge_json"])
        self._baseline_edges = edges_gdf
        self._baseline_nodes = nodes_gdf

        html = make_map(nodes_gdf, edges_gdf, p['place'], p['k'], diff=None, show_updates_default=False)
        self._load_html(html)
        self._update_stats_panel(compute_cut_stats(edges_gdf))

        self._log(f"[Baseline] MERGE_JSON = {paths['merge_json']}")
        self.statusBar().showMessage("Baseline set and rendered.")

    def _on_merge_new(self):
        self._mode = "update"

        if not self._baseline_paths:
            self._on_error("Please set a baseline first (Run as baseline).")
            return

        p = self._gather_params()
        new_paths = self._run_kahip_cli(
            place=p["place"], k=p["k"], dist=p["dist"],
            road_ver=p["road_ver"], lane_ver=p["lane_ver"]
        )

        out_merged = os.path.join(os.path.dirname(new_paths["merge_json"]),
                                  f"merged_{new_paths.get('run_tag','r')}.json")
        _, _, diff = merge_driver(
            base_graph=self._baseline_paths["merge_json"],
            new_graph=new_paths["merge_json"],
            out_graph=out_merged,
            strategy="inherit",
            micro_refine=True,
            r_hops_micro=1,
            move_budget=30,
            r_hops_local=2
        )

            # 规范化一次键名，避免不同返回结构
        def _normalize_diff(d):
            if not isinstance(d, dict):
                return {"added": [], "changed": [], "removed": []}
            def _list(s): return [str(x) for x in (s or [])]
            return {
                "added":   _list(d.get("added")   or d.get("added_edges")   or d.get("new")),
                "changed": _list(d.get("changed") or d.get("changed_edges") or d.get("modified")),
                "removed": _list(d.get("removed") or d.get("removed_edges") or d.get("deleted")),
            }

        diff = _normalize_diff(diff)
        self._log(f"[Diff] added={len(diff['added'])}, changed={len(diff['changed'])}, removed={len(diff['removed'])}")
        if len(diff['added'])+len(diff['changed'])+len(diff['removed']) == 0:
            self._log("[Diff] Empty diff. If you expected changes, likely the IDs did not match. Check _norm_osmid() and eid columns.")

        nodes_new, edges_new = self._gdf_from_merge_json(new_paths["merge_json"])
        show_default = self.chk_show_updates.isChecked()

        html = make_map(
            nodes_gdf=nodes_new,
            edges_gdf=edges_new,
            place=p["place"],
            k=p["k"],
            edges_gdf_old=self._baseline_edges,
            diff=diff,
            show_updates_default=show_default
        )
        self._load_html(html)
        self._update_stats_panel(compute_cut_stats(edges_new))
        self.statusBar().showMessage("Merged and rendered.")

    def _on_load_json(self):
        """
        Merge a local merge_json with current baseline; or set it as baseline if none.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Select local merge JSON", "", "JSON Files (*.json)")
        if not path:
            return

        if not self._baseline_paths:
            try:
                nodes_gdf, edges_gdf = self._gdf_from_merge_json(path)
                self._baseline_paths = {"merge_json": path}
                self._baseline_nodes = nodes_gdf
                self._baseline_edges = edges_gdf
                html = make_map(nodes_gdf, edges_gdf, self.edit_place.text().strip(), int(self.spin_k.value()),
                                diff=None, show_updates_default=False)
                self._load_html(html)
                self._update_stats_panel(compute_cut_stats(edges_gdf))
                self._log(f"[Baseline] Loaded from local JSON: {path}")
                self.statusBar().showMessage("Baseline set from local JSON.")
                self._mode = "baseline"
            except Exception as e:
                self._on_error(f"Failed to load baseline from local JSON: {e}")
            return

        try:
            out_merged = os.path.join(os.path.dirname(path), "merged_from_local.json")
            _, _, diff = merge_driver(
                base_graph=self._baseline_paths["merge_json"],
                new_graph=path,
                out_graph=out_merged,
                strategy="inherit",
                micro_refine=True,
                r_hops_micro=1,
                move_budget=30,
                r_hops_local=2
            )
            nodes_new, edges_new = self._gdf_from_merge_json(path)
            show_default = self.chk_show_updates.isChecked()

            html = make_map(
                nodes_gdf=nodes_new,
                edges_gdf=edges_new,
                place=self.edit_place.text().strip(),
                k=int(self.spin_k.value()),
                edges_gdf_old=self._baseline_edges,
                diff=diff,
                show_updates_default=show_default
            )
            self._load_html(html)
            self._update_stats_panel(compute_cut_stats(edges_new))
            self.statusBar().showMessage("Merged (baseline vs local JSON) and rendered.")
            self._log(f"[Merge] Local JSON merged: {path}")
            self._mode = "update"
        except Exception as e:
            self._on_error(f"Failed to merge local JSON: {e}")

    # ---------- Parameter change bindings ----------
    def _wire_param_changes(self):
        for w in [self.sld_alpha, self.sld_beta, self.sld_gamma]:
            w.valueChanged.connect(self._on_auto_params_changed)
        for w in [self.spin_dist, self.spin_k]:
            w.valueChanged.connect(self._on_manual_param_changed)
        self.edit_place.textChanged.connect(self._on_manual_param_changed)
        self.cmb_road_ver.currentIndexChanged.connect(self._on_manual_param_changed)
        self.cmb_lane_ver.currentIndexChanged.connect(self._on_manual_param_changed)

    def _on_slider_change(self, v: int, key: str, value_label: QLabel):
        val = v / self._scale
        value_label.setText(f"{val:.2f}")
        self.params[key] = val
        self._debounce_auto.start()

    def _on_auto_params_changed(self, *args):
        # Only allow auto re-run when in 'run' mode
        if self._mode != "run":
            return
        if not self._has_ever_run:
            return
        if self._pending_manual:
            return
        if self._running:
            self._debounce_auto.stop()
            return
        self._debounce_auto.start()

    def _on_manual_param_changed(self, *args):
        if self._pending_manual:
            return
        self._pending_manual = True
        self._debounce_auto.stop()
        self._log("Parameters changed that require a manual run. Click 'Run' to apply.")
        self.btn_run.setStyleSheet(self._manual_dirty_style)

    # ---------- Run pipeline ----------
    def _on_run_clicked(self):
        self._mode = "run"
        self._run_partition_async()

    def on_params_finalized(self):
        if self._mode != "run":
            return
        if not self._has_ever_run:
            return
        if self._pending_manual:
            return
        if self._running:
            return
        self._run_partition_async()

    def _run_partition_async(self):
        if self._running:
            self._log("[Skip] A run is already in progress.")
            return

        self._pending_manual = False
        self.btn_run.setStyleSheet("")

        params = self._gather_params()
        key = tuple(sorted(params.items()))

        if key in self._map_cache and os.path.exists(self._map_cache[key]['html']):
            self._log(f"[Cache hit] {self._map_cache[key]['html']}")
            self._load_html(self._map_cache[key]['html'])
            self._update_stats_panel(self._map_cache[key]['stats'])
            self._has_ever_run = True
            return

        self._log("[Cache miss] running pipeline…")
        self.btn_run.setEnabled(False)
        self._running = True

        self._thread = PipelineThread(params, cache_key=key, parent=self)
        self._thread.log.connect(self._log)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_finished_thread)
        self._thread.start()

    def _on_finished_thread(self, payload: dict):
        html = payload['html']
        stats = payload['stats']
        key = payload['cache_key']

        self._map_cache[key] = {'html': html, 'stats': stats}
        self._load_html(html)
        self._update_stats_panel(stats)

        self.btn_run.setEnabled(True)
        self._running = False
        self._pending_manual = False
        self.btn_run.setStyleSheet("")
        self._has_ever_run = True
        self._log("Done.")

    # ---------- Param collection ----------
    def _gather_params(self) -> dict:
        return dict(
            place=self.edit_place.text().strip(),
            dist=int(self.spin_dist.value()),
            k=int(self.spin_k.value()),
            alpha=self.sld_alpha.value() / self._scale,
            beta=self.sld_beta.value() / self._scale,
            gamma=self.sld_gamma.value() / self._scale,
            road_ver=self.cmb_road_ver.currentText().strip() or "all_1",
            lane_ver=self.cmb_lane_ver.currentText().strip() or "all_1",
        )

    # ---------- Utilities ----------
    def _load_html(self, html_path: str):
        abs_path = os.path.abspath(html_path)
        self._log(f"[View] {abs_path}")
        # 加一个时间戳 query，避免 QWebEngine 用缓存
        url = QUrl.fromLocalFile(abs_path)
        url.setQuery(f"t={int(time.time())}")
        self.web.setUrl(url)


    def _open_dir(self, path: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as e:
            self._on_error(str(e))

    def _log(self, msg: str):
        self.txt.append(msg)
        self.txt.verticalScrollBar().setValue(self.txt.verticalScrollBar().maximum())

    def _on_error(self, msg: str):
        self._log(f"[ERROR] {msg}")
        self.btn_run.setEnabled(True)
        self._running = False

    def _update_stats_panel(self, s: dict):
        def fnum(x):
            try:
                if isinstance(x, int) or float(x).is_integer():
                    return str(int(float(x)))
                return f"{float(x):.4f}"
            except Exception:
                return str(x)

        edges = s.get("edges", 0)
        cut_cnt = s.get("cut_edge_count", 0)
        total_w = s.get("total_weight", 0.0)
        cut_w = s.get("cut_edge_weight_sum", 0.0)
        cut_ratio = s.get("cut_ratio", 0.0)
        w_ratio = s.get("weight_ratio", 0.0)

        self.lbl_edges.setText(fnum(edges))
        self.lbl_cut_cnt.setText(fnum(cut_cnt))
        self.lbl_total_w.setText(fnum(total_w))
        self.lbl_cut_w.setText(fnum(cut_w))
        self.lbl_cut_ratio.setText(fnum(cut_ratio))
        self.lbl_w_ratio.setText(fnum(w_ratio))

        self.top_summary.setText(
            f"Edges: {fnum(edges)} | Cut: {fnum(cut_cnt)} "
            f"| Total_w: {fnum(total_w)} | Cut_w: {fnum(cut_w)} "
            f"| Cut_ratio: {fnum(cut_ratio)} | Weight_ratio: {fnum(w_ratio)}"
        )


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
