"""
OSM Partition Viewer
"""

import os
import sys
import json
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QTextEdit, QGroupBox, QFormLayout, QComboBox
)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView

# Project imports
from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR

# Fixed configuration file names 
ROAD_TYPE_FILE = "road_type_weights.json"
LANE_WEIGHT_FILE = "lane_weight_version.json"


#  Pipeline Thread 
class PipelineThread(QThread):
    """
    Thread that runs the partitioning pipeline asynchronously
    to avoid blocking the UI.
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
                road_type_path=ROAD_TYPE_FILE,             # Fixed filename
                lane_weight_version=p['lane_ver'],         # Version name only
            )
            self.log.emit(f"- KaHIP JSON: {json_path}")

            # 3) Parse results and compute statistics
            data = read_kahip_json(json_path)
            nodes_gdf, edges_gdf = parse_from_json(G, data)
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

            # Signal completion
            self.finished.emit({'html': html, 'stats': stats, 'cache_key': self.cache_key})
        except Exception as e:
            self.error.emit(str(e))


#  Main Window 
class MainWindow(QMainWindow):
    """
    Main application window for the OSM Partition Viewer.
    Provides controls for setting parameters, running KaHIP,
    and displaying the resulting map and statistics.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSM Partition Viewer")
        self.resize(1200, 800)

        # State variables
        self._map_cache = {}
        self._running = False
        self._has_ever_run = False   # Must click Run for the first time
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._run_partition_async)
        self._pending_manual = False
        self._manual_dirty_style = "background:#ffe9a8;"

        # Layout setup
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # Left column (controls and logs)
        left = QVBoxLayout()
        root.addLayout(left, 0)

        # Place / dist / k inputs
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

        # Alpha / beta / gamma sliders (0–5, represented as 0–500 for precision)
        def add_slider(caption, init=100):
            box = QHBoxLayout(); left.addLayout(box)
            box.addWidget(QLabel(caption))
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0, 500); s.setValue(init)
            box.addWidget(s, 1)
            return s
        self.sld_alpha = add_slider("alpha", 100)
        self.sld_beta  = add_slider("beta", 100)
        self.sld_gamma = add_slider("gamma", 100)

        # Version selectors (dropdown)
        row3 = QHBoxLayout(); left.addLayout(row3)
        row3.addWidget(QLabel("road_type_version"))
        self.cmb_road_ver = QComboBox(); row3.addWidget(self.cmb_road_ver, 1)

        row3b = QHBoxLayout(); left.addLayout(row3b)
        row3b.addWidget(QLabel("lane_weight_version"))
        self.cmb_lane_ver = QComboBox(); row3b.addWidget(self.cmb_lane_ver, 1)

        # Reload version lists button
        row_reload = QHBoxLayout(); left.addLayout(row_reload)
        self.btn_reload_versions = QPushButton("Reload versions")
        row_reload.addWidget(self.btn_reload_versions)
        self.btn_reload_versions.clicked.connect(self._load_version_lists)

        # Run / Update button
        self.btn_run = QPushButton("Run / Update"); left.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self._on_run_clicked)

        # Open output folder button
        self.btn_open = QPushButton("Open output folder"); left.addWidget(self.btn_open)
        self.btn_open.clicked.connect(lambda: self._open_dir(OUTPUT_DIR))

        # Top summary label
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

        # Right column (map display)
        self.web = QWebEngineView(self)
        root.addWidget(self.web, 1)

        # Bind parameter change events
        self._wire_param_changes()

        # Load version options at startup
        self._load_version_lists(default_road="all_1", default_lane="v1")

    #  Load available versions from JSON 
    def _load_version_lists(self, default_road="all_1", default_lane="v1"):
        """
        Load keys from road_type_weights.json and lane_weight_version.json
        into the dropdown selectors.
        """
        def keys_from_json(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return list(data.keys())
                else:
                    self._log(f"[WARN] {path} is not a dict; no keys to load.")
                    return []
            except Exception as e:
                self._log(f"[WARN] Cannot read {path}: {e}")
                return []

        road_keys = keys_from_json(ROAD_TYPE_FILE)
        lane_keys = keys_from_json(LANE_WEIGHT_FILE)

        # Populate road_type_version dropdown
        self.cmb_road_ver.blockSignals(True)
        self.cmb_road_ver.clear()
        if road_keys:
            self.cmb_road_ver.addItems(road_keys)
            idx = self.cmb_road_ver.findText(default_road)
            self.cmb_road_ver.setCurrentIndex(max(0, idx))
        else:
            self.cmb_road_ver.addItems([default_road])
        self.cmb_road_ver.blockSignals(False)

        # Populate lane_weight_version dropdown
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

    #  Parameter change event bindings
    def _wire_param_changes(self):
        # Auto-trigger parameters (alpha, beta, gamma)
        for w in [self.sld_alpha, self.sld_beta, self.sld_gamma]:
            w.valueChanged.connect(self._on_auto_params_changed)
        # Manual-run parameters
        for w in [self.spin_dist, self.spin_k]:
            w.valueChanged.connect(self._on_manual_param_changed)
        self.edit_place.textChanged.connect(self._on_manual_param_changed)
        # Dropdown changes also require manual run
        self.cmb_road_ver.currentIndexChanged.connect(self._on_manual_param_changed)
        self.cmb_lane_ver.currentIndexChanged.connect(self._on_manual_param_changed)

    def _on_auto_params_changed(self, *args):
        """Automatically run when auto-trigger parameters change (if applicable)."""
        if not self._has_ever_run:
            return
        if self._pending_manual:
            return
        if self._running:
            self._debounce.stop()
            return
        self._debounce.start()

    def _on_manual_param_changed(self, *args):
        """Mark state as requiring manual Run after parameters change."""
        if self._pending_manual:
            return
        self._pending_manual = True
        self._debounce.stop()
        self._log("Parameters changed that require manual run. Click 'Run / Update' to apply.")
        self.btn_run.setStyleSheet(self._manual_dirty_style)

    # Run pipeline 
    def _on_run_clicked(self):
        self._run_partition_async()

    def _run_partition_async(self):
        if self._running:
            self._log("[Skip] A run is already in progress.")
            return

        # Apply all manual changes when user clicks Run
        self._pending_manual = False
        self.btn_run.setStyleSheet("")

        params = self._gather_params()
        key = tuple(sorted(params.items()))

        # Cache hit
        if key in self._map_cache and os.path.exists(self._map_cache[key]['html']):
            self._log(f"[Cache hit] {self._map_cache[key]['html']}")
            self._load_html(self._map_cache[key]['html'])
            self._update_stats_panel(self._map_cache[key]['stats'])
            self._has_ever_run = True
            return

        # Run in background thread
        self._log("[Cache miss] running pipeline…")
        self.btn_run.setEnabled(False)
        self._running = True

        self._thread = PipelineThread(params, cache_key=key, parent=self)
        self._thread.log.connect(self._log)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_finished_thread)
        self._thread.start()

    def _on_finished_thread(self, payload: dict):
        """Handle thread completion: update cache, load map, update stats."""
        html = payload['html']
        stats = payload['stats']
        key = payload['cache_key']

        # Cache results
        self._map_cache[key] = {'html': html, 'stats': stats}

        # Display map and stats
        self._load_html(html)
        self._update_stats_panel(stats)

        # Reset state
        self.btn_run.setEnabled(True)
        self._running = False
        self._pending_manual = False
        self.btn_run.setStyleSheet("")
        self._has_ever_run = True
        self._log("Done.")

    #  Parameter collection 
    def _gather_params(self) -> dict:
        """Collect current parameters from the UI."""
        return dict(
            place=self.edit_place.text().strip(),
            dist=int(self.spin_dist.value()),
            k=int(self.spin_k.value()),
            alpha=self.sld_alpha.value() / 100.0,
            beta=self.sld_beta.value() / 100.0,
            gamma=self.sld_gamma.value() / 100.0,
            road_ver=self.cmb_road_ver.currentText().strip() or "all_1",
            lane_ver=self.cmb_lane_ver.currentText().strip() or "v1",
        )

    #  Utility methods
    def _load_html(self, html_path: str):
        """Load the generated HTML map into the web view."""
        abs_path = os.path.abspath(html_path)
        self._log(f"[View] {abs_path}")
        self.web.setUrl(QUrl.fromLocalFile(abs_path))

    def _open_dir(self, path: str):
        """Open the output directory in the OS file browser."""
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
        """Append a message to the run log."""
        self.txt.append(msg)
        self.txt.verticalScrollBar().setValue(self.txt.verticalScrollBar().maximum())

    def _on_error(self, msg: str):
        """Handle errors: log and re-enable Run button."""
        self._log(f"[ERROR] {msg}")
        self.btn_run.setEnabled(True)
        self._running = False

    def _update_stats_panel(self, s: dict):
        """Update the statistics panel with current partitioning results."""
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
