"""
OSM Partition Viewer
"""

import os, sys, json, yaml
from pathlib import Path

#from PyQt5.QtWidgets import (
#    QApplication, QMainWindow, QWidget,QtCore, QtWidgets,
#    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
#    QSlider, QSpinBox, QTextEdit, QGroupBox, QFormLayout, QComboBox
#)
#from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer, QThread
#from PyQt5.QtWebEngineWidgets import QWebEngineView

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication


# Project imports
from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR

from tools.llm_rag.rag.retriever import Retriever
from tools.llm_rag.rag.generator import generate_answer


# Fixed configuration file names 
ROAD_TYPE_FILE = "road_type_weights.json"
LANE_WEIGHT_FILE = "lane_weight_version.json"


# ==== Q&A 线程与 Tab ====
class QAWorker(QtCore.QThread):
    resultReady = QtCore.pyqtSignal(dict)

    def __init__(self, retriever: Retriever, question: str, rules: str, top_k: int):
        super().__init__()
        self.retriever = retriever
        self.question = question
        self.rules = rules
        self.top_k = top_k

    def run(self):
        try:
            hits = self.retriever.search(self.question, top_k=self.top_k)
            # 统一 contexts 为纯文本列表
            contexts = []
            for h in hits:
                if isinstance(h, dict):
                    contexts.append(h.get("text", ""))
                elif isinstance(h, (list, tuple)) and len(h) >= 1:
                    contexts.append(h[0])
                else:
                    contexts.append(str(h))
            answer = generate_answer(self.question, contexts)
            res = {"question": self.question, "answer": answer, "hits": hits}
        except Exception as e:
            res = {"error": str(e)}
        self.resultReady.emit(res)


class QATab(QtWidgets.QWidget):
    def __init__(self, parent=None, config_path="config.yaml"):
        super().__init__(parent)

        # 读配置（容错）
        cfg = {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

        top_k = int(cfg.get("retrieval", {}).get("top_k", 5))
        rules_path = cfg.get("rules_path", "")
        self.rules = ""
        if rules_path and os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                self.rules = f.read()

        # 初始化 RAG 检索器（按你的 Retriever 构造签名来）
        self.retriever = Retriever(
            vectors_path=cfg.get("index", {}).get("vectors", "tools/llm_rag/data/index/vectors.npy"),
            texts_path=cfg.get("index", {}).get("texts",   "tools/llm_rag/data/index/texts.txt"),
        )
        self.top_k = top_k

        # 界面
        self.chat = QtWidgets.QTextEdit(self); self.chat.setReadOnly(True)
        self.input = QtWidgets.QLineEdit(self)
        self.sendBtn = QtWidgets.QPushButton("Send", self)
        self.status = QtWidgets.QLabel("Ready", self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.chat)
        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.input); hl.addWidget(self.sendBtn)
        layout.addLayout(hl)
        layout.addWidget(self.status)

        self.sendBtn.clicked.connect(self.on_send)
        self.input.returnPressed.connect(self.on_send)
        self._append_system("Q&A ready. Ask me anything!")

    def _append_user(self, text): self.chat.append(f"<p><b>You:</b> {text}</p>")
    def _append_assistant(self, text): self.chat.append(f"<p><b>Assistant:</b> {text}</p>")
    def _append_system(self, text): self.chat.append(f"<p style='color:gray'><i>{text}</i></p>")

    def on_send(self):
        q = self.input.text().strip()
        if not q: return
        self._append_user(q)
        self.input.clear()
        self.status.setText("Thinking…")
        self.sendBtn.setEnabled(False)

        self.worker = QAWorker(self.retriever, q, self.rules, self.top_k)
        self.worker.resultReady.connect(self.on_result)
        self.worker.finished.connect(lambda: self.sendBtn.setEnabled(True))
        self.worker.start()

    def on_result(self, res: dict):
        if "error" in res:
            self._append_system("Error: " + res["error"])
            self.status.setText("Error")
            return
        self._append_assistant(res["answer"])
        # 展示命中片段（可选）
        hits = res.get("hits", [])
        if hits:
            self.chat.append("<details><summary>Retrieved context</summary>")
            for i, h in enumerate(hits, 1):
                if isinstance(h, dict):
                    txt = h.get("text", "")
                    sc = h.get("score", None)
                elif isinstance(h, (list, tuple)) and len(h) >= 1:
                    txt, sc = h[0], (h[1] if len(h) > 1 else None)
                else:
                    txt, sc = str(h), None
                score_str = f"(score={sc:.4f})" if isinstance(sc, (int, float)) else ""
                self.chat.append(f"<p><b>#{i}</b> {score_str}<br>{txt[:500]}</p>")
            self.chat.append("</details>")
        self.status.setText("Ready")


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


            #print(edges_gdf.columns)
            #import osmnx as ox
            #G_updated = ox.graph_from_gdfs(nodes_gdf,edges_gdf)
            #ox.settings.all_oneway=True
            #ox.settings.useful_tags_way.append("part_u")
            #ox.settings.useful_tags_way.append("part_v")
            #ox.settings.useful_tags_way.append("is_cut")
            #ox.settings.useful_tags_way.append("part")
            #ox.io.save_graph_xml(G_updated,filepath='/home/yushugao/test.osm')



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
            html = make_map(nodes_gdf, edges_gdf, p['place'], p['k'], dist=p['dist'])

            self.log.emit(f"- HTML map: {html}")

            # Signal completion
            self.finished.emit({'html': html, 'stats': stats, 'cache_key': self.cache_key})
        except Exception as e:
            self.error.emit(str(e))


#  Main Window 
"""class MainWindow(QMainWindow):
    
    #Main application window for the OSM Partition Viewer.
    #Provides controls for setting parameters, running KaHIP,
    #and displaying the resulting map and statistics.

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSM Partition Viewer")
        self.resize(1200, 800)
        # 1) 整体用 Tab 容器
        self.tabs = QtWidgets.QTabWidget(self)
        self.setCentralWidget(self.tabs)
        #2) 原有 Partition Viewer 页面打包到一个 QWidget
        viewer_page = QtWidgets.QWidget(self)
        self._init_viewer_ui(viewer_page)  # 把你现有的大段 UI 初始化逻辑搬进这个函数
        self.tabs.addTab(viewer_page, "Partition")

        # 3) 新增 Q&A Tab
        self.qa_tab = QATab(self, config_path="config.yaml")
        self.tabs.addTab(self.qa_tab, "Q&A")



        # Store current alpha, beta, gamma values
        self.params = {"alpha": 1.00, "beta": 1.00, "gamma": 1.00}
        # Integer-to-float scale factor (100 means each slider step = 0.01)
        self._scale = 100  

        # State variables
        self._map_cache = {}
        self._running = False
        self._has_ever_run = False   # Must click Run for the first time
        # Track whether some manual-only params changed and require a manual run
        self._pending_manual = False
        self._manual_dirty_style = "background:#ffe9a8;"


        # Debounce timer for slider-driven auto recomputation
        self._debounce_auto = QTimer(self)
        self._debounce_auto.setSingleShot(True)
        self._debounce_auto.setInterval(200)     # 200 ms debounce
        self._debounce_auto.timeout.connect(self.on_params_finalized)

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
        def add_param_slider(caption: str, key: str, init_float: float = 1.00):
            
            #Build a row: [caption label] [slider] [value label].
            #Returns the slider and its value label.
            
            box = QHBoxLayout(); left.addLayout(box)
            box.addWidget(QLabel(caption))

            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, int(5.00 * self._scale))                 # 0.00 ~ 5.00
            s.setValue(int(init_float * self._scale))              # default = 1.00
            s.setSingleStep(1)                                     # 0.01 per tick
            s.setPageStep(10)                                      # 0.10 per page step
            box.addWidget(s, 1)

            val_label = QLabel(f"{init_float:.2f}")
            val_label.setMinimumWidth(48)
            val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            box.addWidget(val_label)

            # Update numeric label live, store param, and start debounce
            s.valueChanged.connect(lambda v: self._on_slider_change(v, key, val_label))
            return s, val_label

        self.sld_alpha, self.lbl_alpha_val = add_param_slider("alpha", "alpha", 1.00)
        self.sld_beta,  self.lbl_beta_val  = add_param_slider("beta",  "beta",  1.00)
        self.sld_gamma, self.lbl_gamma_val = add_param_slider("gamma", "gamma", 1.00)

        # Version selectors (dropdown)
        row3 = QHBoxLayout(); left.addLayout(row3)
        row3.addWidget(QLabel("road_type_version"))
        self.cmb_road_ver = QComboBox(); row3.addWidget(self.cmb_road_ver, 1)

        row3b = QHBoxLayout(); left.addLayout(row3b)
        row3b.addWidget(QLabel("lane_weight_version"))
        self.cmb_lane_ver = QComboBox(); row3b.addWidget(self.cmb_lane_ver, 1)

        # Reload version lists button
        #row_reload = QHBoxLayout(); left.addLayout(row_reload)
        #self.btn_reload_versions = QPushButton("Reload versions")
        #row_reload.addWidget(self.btn_reload_versions)
        #self.btn_reload_versions.clicked.connect(self._load_version_lists)

        # Run button
        self.btn_run = QPushButton("Run "); left.addWidget(self.btn_run)
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
        self._load_version_lists(default_road="all_1", default_lane="v1") """
class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window for the OSM Partition Viewer.
    Provides controls for setting parameters, running KaHIP,
    and displaying the resulting map and statistics.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSM Partition Viewer")
        self.resize(1200, 800)

        # ==== 参数与状态 ====
        self.params = {"alpha": 1.00, "beta": 1.00, "gamma": 1.00}
        self._scale = 100
        self._map_cache = {}
        self._running = False
        self._has_ever_run = False
        self._pending_manual = False
        self._manual_dirty_style = "background:#ffe9a8;"

        # debounce
        self._debounce_auto = QTimer(self)
        self._debounce_auto.setSingleShot(True)
        self._debounce_auto.setInterval(200)
        self._debounce_auto.timeout.connect(self.on_params_finalized)

        # ==== 用 Tab 做中央控件 ====
        self.tabs = QtWidgets.QTabWidget(self)
        self.setCentralWidget(self.tabs)

        # Partition 页面
        viewer_page = QtWidgets.QWidget(self)
        self._init_viewer_ui(viewer_page)  # ⬅️ 把原来的 Partition 界面塞进这个函数
        self.tabs.addTab(viewer_page, "Partition")

        # Q&A 页面
        self.qa_tab = QATab(self, config_path="config.yaml")
        self.tabs.addTab(self.qa_tab, "Q&A")

    # =============== 把原来“Layout setup … _load_version_lists”那一大段搬到这里 ===============
    def _init_viewer_ui(self, parent_widget: QtWidgets.QWidget):
        """Build the Partition Viewer UI inside the given parent widget."""
        root = QtWidgets.QHBoxLayout(parent_widget)

        # Left column (controls and logs)
        left = QtWidgets.QVBoxLayout()
        root.addLayout(left, 0)

        # Place / dist / k inputs
        row1 = QtWidgets.QHBoxLayout(); left.addLayout(row1)
        row1.addWidget(QtWidgets.QLabel("Place"))
        self.edit_place = QtWidgets.QLineEdit("Karlsruhe, Germany"); row1.addWidget(self.edit_place, 1)

        row2 = QtWidgets.QHBoxLayout(); left.addLayout(row2)
        row2.addWidget(QtWidgets.QLabel("dist [m]"))
        self.spin_dist = QtWidgets.QSpinBox(); self.spin_dist.setRange(100, 50000); self.spin_dist.setValue(5000)
        row2.addWidget(self.spin_dist)
        row2.addWidget(QtWidgets.QLabel("k"))
        self.spin_k = QtWidgets.QSpinBox(); self.spin_k.setRange(2, 64); self.spin_k.setValue(4)
        row2.addWidget(self.spin_k)

        # Alpha / beta / gamma sliders (0–5)
        def add_param_slider(caption: str, key: str, init_float: float = 1.00):
            box = QtWidgets.QHBoxLayout(); left.addLayout(box)
            box.addWidget(QtWidgets.QLabel(caption))

            s = QtWidgets.QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, int(5.00 * self._scale))
            s.setValue(int(init_float * self._scale))
            s.setSingleStep(1)
            s.setPageStep(10)
            box.addWidget(s, 1)

            val_label = QtWidgets.QLabel(f"{init_float:.2f}")
            val_label.setMinimumWidth(48)
            val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            box.addWidget(val_label)

            s.valueChanged.connect(lambda v: self._on_slider_change(v, key, val_label))
            return s, val_label

        self.sld_alpha, self.lbl_alpha_val = add_param_slider("alpha", "alpha", 1.00)
        self.sld_beta,  self.lbl_beta_val  = add_param_slider("beta",  "beta",  1.00)
        self.sld_gamma, self.lbl_gamma_val = add_param_slider("gamma", "gamma", 1.00)

        # Version selectors (dropdown)
        row3 = QtWidgets.QHBoxLayout(); left.addLayout(row3)
        row3.addWidget(QtWidgets.QLabel("road_type_version"))
        self.cmb_road_ver = QtWidgets.QComboBox(); row3.addWidget(self.cmb_road_ver, 1)

        row3b = QtWidgets.QHBoxLayout(); left.addLayout(row3b)
        row3b.addWidget(QtWidgets.QLabel("lane_weight_version"))
        self.cmb_lane_ver = QtWidgets.QComboBox(); row3b.addWidget(self.cmb_lane_ver, 1)

        # Run button
        self.btn_run = QtWidgets.QPushButton("Run "); left.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self._on_run_clicked)

        # Open output folder
        self.btn_open = QtWidgets.QPushButton("Open output folder"); left.addWidget(self.btn_open)
        self.btn_open.clicked.connect(lambda: self._open_dir(OUTPUT_DIR))

        # Top summary
        self.top_summary = QtWidgets.QLabel("—")
        self.top_summary.setStyleSheet("color:#222; font-weight:600;")
        left.addWidget(self.top_summary)

        # Statistics box
        self.stats_box = QtWidgets.QGroupBox("Partition Statistics")
        stats_layout = QtWidgets.QFormLayout(self.stats_box)
        self.lbl_edges = QtWidgets.QLabel("-")
        self.lbl_cut_cnt = QtWidgets.QLabel("-")
        self.lbl_total_w = QtWidgets.QLabel("-")
        self.lbl_cut_w = QtWidgets.QLabel("-")
        self.lbl_cut_ratio = QtWidgets.QLabel("-")
        self.lbl_w_ratio = QtWidgets.QLabel("-")
        stats_layout.addRow("Edges", self.lbl_edges)
        stats_layout.addRow("Cut edges", self.lbl_cut_cnt)
        stats_layout.addRow("Total weight", self.lbl_total_w)
        stats_layout.addRow("Cut weight sum", self.lbl_cut_w)
        stats_layout.addRow("Cut ratio", self.lbl_cut_ratio)
        stats_layout.addRow("Weight ratio", self.lbl_w_ratio)
        left.addWidget(self.stats_box)

        # Run log
        left.addWidget(QtWidgets.QLabel("Run Log / Metrics"))
        self.txt = QtWidgets.QTextEdit(); self.txt.setReadOnly(True); left.addWidget(self.txt, 1)

        # Right column (map display)
        self.web = QWebEngineView(parent_widget)
        root.addWidget(self.web, 1)

        # 绑定参数变化
        self._wire_param_changes()
        # 初始加载版本列表
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

    def _on_slider_change(self, v: int, key: str, value_label: QtWidgets.QLabel):
        """
        Live-update numeric label and store parameter when a slider moves.
        Also start/restart the debounce timer for potential auto-run.
        """
        val = v / self._scale
        value_label.setText(f"{val:.2f}")
        self.params[key] = val
        self._debounce_auto.start()


    def _on_auto_params_changed(self, *args):
        """Automatically run when auto-trigger parameters change (if applicable)."""
        if not self._has_ever_run:
            return
        if self._pending_manual:
            return
        if self._running:
            self._debounce_auto.stop()
            return
        self._debounce_auto.start()

    def _on_manual_param_changed(self, *args):
        """Mark state as requiring manual Run after parameters change."""
        if self._pending_manual:
            return
        self._pending_manual = True
        self._debounce_auto.stop()
        self._log("Parameters changed that require manual run. Click 'Run' to apply.")
        self.btn_run.setStyleSheet(self._manual_dirty_style)

    # Run pipeline 
    def _on_run_clicked(self):
        self._run_partition_async()

    def on_params_finalized(self):
        """
        Called once after sliders stop moving (debounced).
        Only runs if we've done at least one manual run, there are no pending
        manual-only changes, and no run is currently in progress.
        """
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
            alpha=self.sld_alpha.value() / self._scale,
            beta=self.sld_beta.value() / self._scale,
            gamma=self.sld_gamma.value() / self._scale,
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
