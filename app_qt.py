# app_qt.py
import os, sys, threading
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QTextEdit
)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QObject
from PyQt5.QtWebEngineWidgets import QWebEngineView

PYQT_MAJOR = 5


from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR

#  Worker 
class PipelineWorker(QObject):
    finished  = pyqtSignal(str)     # html_path
    log       = pyqtSignal(str)     # 日志
    error     = pyqtSignal(str)

    def __init__(self, params: dict):
        super().__init__()
        self.params = params

    def run(self):
        try:
            p = self.params
            self.log.emit(f"Params: place='{p['place']}', dist={p['dist']}, k={p['k']}, "
                          f"α/β/γ=({p['alpha']:.2f},{p['beta']:.2f},{p['gamma']:.2f}), "
                          f"road_type_ver={p['road_ver']}, lane_ver={p['lane_ver']}")
            # 1) 加载/下载图
            G = load_graph(p['place'], dist=p['dist'])
            self.log.emit(f"- Graph size: nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

            # 2) 调 KaHIP
            self.log.emit("- Running KaHIP partitioning…")
            json_path = run_kahip(
                place=p['place'], k=p['k'], dist=p['dist'],
                alpha=p['alpha'], beta=p['beta'], gamma=p['gamma'],
                road_type_version=p['road_ver'],
                road_type_path=(p['road_json'] or "road_type_weights.json"),
                lane_weight_version=(p['lane_ver'] or "v1"),
            )
            self.log.emit(f"- KaHIP JSON: {json_path}")

            # 3) 解析 + 统计
            data = read_kahip_json(json_path)
            nodes_gdf, edges_gdf = parse_from_json(G, data)
            stats = compute_cut_stats(edges_gdf)
            self.log.emit(f"- cut_edge_count={stats['cut_edge_count']}, edges={stats['edges']}, "
                          f"cut_ratio={stats['cut_ratio']:.4f}")

            # 4) 生成 Folium 地图（HTML）
            html = make_map(nodes_gdf, edges_gdf, p['place'], p['k'])
            self.log.emit(f"- HTML map: {html}")
            self.finished.emit(html)
        except Exception as e:
            self.error.emit(str(e))


# 主窗口 
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSM Partition Viewer (PyQt + QWebEngine)")
        self.resize(1200, 800)

        self._map_cache = {}

        central = QWidget(self); self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # 左侧：参数 & 日志
        left = QVBoxLayout(); root.addLayout(left, 0)

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

        # alpha/beta/gamma 滑块（0~5）
        def add_slider(caption, init=100):
            box = QHBoxLayout(); left.addLayout(box)
            box.addWidget(QLabel(caption))
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0, 500); s.setValue(init)
            box.addWidget(s, 1)
            return s
        self.sld_alpha = add_slider("alpha", 100)
        self.sld_beta  = add_slider("beta",  100)
        self.sld_gamma = add_slider("gamma", 100)

        # road_type_version / lane_weight_version
        row3 = QHBoxLayout(); left.addLayout(row3)
        row3.addWidget(QLabel("road_type_version"))
        self.edit_road_ver = QLineEdit("all_1"); row3.addWidget(self.edit_road_ver)

        row3b = QHBoxLayout(); left.addLayout(row3b)
        row3b.addWidget(QLabel("lane_weight_version"))
        self.edit_lane_ver = QLineEdit("v1"); row3b.addWidget(self.edit_lane_ver)

        # road_type_weights.json 选择
        row4 = QHBoxLayout(); left.addLayout(row4)
        row4.addWidget(QLabel("road_type_weights.json"))
        self.edit_road_json = QLineEdit(""); row4.addWidget(self.edit_road_json, 1)
        btn_browse = QPushButton("Browse…"); row4.addWidget(btn_browse)
        btn_browse.clicked.connect(self._choose_json)

        # Run / Update
        self.btn_run = QPushButton("Run / Update"); left.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self._on_run_clicked)

        # 打开输出目录
        self.btn_open = QPushButton("Open output folder"); left.addWidget(self.btn_open)
        self.btn_open.clicked.connect(lambda: self._open_dir(OUTPUT_DIR))

        # 日志
        left.addWidget(QLabel("Run Log / Metrics"))
        self.txt = QTextEdit(); self.txt.setReadOnly(True); left.addWidget(self.txt, 1)

        # 右侧：地图（QWebEngineView）
        self.web = QWebEngineView(self); root.addWidget(self.web, 1)

    # 事件处理 
    def _on_run_clicked(self):
        params = self._gather_params()
        key = tuple(params.items())
        if key in self._map_cache and os.path.exists(self._map_cache[key]):
            self._log(f"[Cache hit] {self._map_cache[key]}")
            self._load_html(self._map_cache[key])
            return

        self._log("[Cache miss] running pipeline…")
        self.btn_run.setEnabled(False)
        worker = PipelineWorker(params)
        t = threading.Thread(target=worker.run, daemon=True)

        # 连接信号 -> 槽
        worker.log.connect(self._log)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda html: self._on_finished(key, html))

        # 把 worker 保持为属性，避免被 GC
        self._worker = worker
        t.start()

    def _on_finished(self, key, html):
        self._map_cache[key] = html
        self._load_html(html)
        self.btn_run.setEnabled(True)

    # 工具 
    def _gather_params(self) -> dict:
        road_json = self.edit_road_json.text().strip()
        if road_json and not os.path.isfile(road_json):
            self._log(f"[WARN] road_type_weights.json not found: {road_json}")
            road_json = None

        return dict(
            place=self.edit_place.text().strip(),
            dist=int(self.spin_dist.value()),
            k=int(self.spin_k.value()),
            alpha=self.sld_alpha.value() / 100.0,   # 0~5
            beta=self.sld_beta.value() / 100.0,
            gamma=self.sld_gamma.value() / 100.0,
            road_ver=self.edit_road_ver.text().strip() or "all_1",
            lane_ver=self.edit_lane_ver.text().strip() or "v1",
            road_json=road_json,
        )

    def _load_html(self, html_path: str):
        abs_path = os.path.abspath(html_path)
        self._log(f"[View] {abs_path}")
        self.web.setUrl(QUrl.fromLocalFile(abs_path))

    def _choose_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose road_type_weights.json",
                                              filter="JSON files (*.json);;All files (*.*)")
        if path:
            self.edit_road_json.setText(path)

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


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
