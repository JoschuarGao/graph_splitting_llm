import os
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from core.visualize import make_map, compute_cut_stats
from core.partition_fallback import spectral_partition, gdfs_from_assignment
from core.config import OUTPUT_DIR

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSM 分区可视化（KaHIP + explore）")
        self.geometry("900x560")

        # 变量
        self.var_place = tk.StringVar(value="Karlsruhe, Germany")
        self.var_dist = tk.IntVar(value=20000)
        self.var_k = tk.IntVar(value=4)

        self.var_alpha = tk.DoubleVar(value=1.0)
        self.var_beta  = tk.DoubleVar(value=1.0)
        self.var_gamma = tk.DoubleVar(value=1.0)

        self.var_road_json = tk.StringVar(value="")
        self.var_lane_ver  = tk.StringVar(value="")
        self.var_use_kahip = tk.BooleanVar(value=True)  # 勾选 → 调 KaHIP；不勾选 → 后备分区

        self._build_form()
        self._build_log()

        self._running = False

    def _build_form(self):
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="x")

        # 行1：地点、半径、k
        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=6)
        ttk.Label(row1, text="Place").pack(side="left")
        ttk.Entry(row1, textvariable=self.var_place, width=42).pack(side="left", padx=6)

        ttk.Label(row1, text="dist [m]").pack(side="left", padx=(12, 0))
        ttk.Entry(row1, textvariable=self.var_dist, width=9).pack(side="left", padx=4)

        ttk.Label(row1, text="k").pack(side="left", padx=(12, 0))
        ttk.Spinbox(row1, from_=2, to=20, textvariable=self.var_k, width=6).pack(side="left", padx=4)

        # 行2：alpha/beta/gamma 滑块
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=6)
        def add_slider(parent, label, var):
            box = ttk.Frame(parent); box.pack(fill="x", pady=4)
            ttk.Label(box, text=label, width=10).pack(side="left")
            s = ttk.Scale(box, from_=0.0, to=5.0, orient="horizontal", variable=var)
            s.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Label(box, textvariable=var, width=6).pack(side="left")
        add_slider(row2, "alpha", self.var_alpha)
        add_slider(row2, "beta",  self.var_beta)
        add_slider(row2, "gamma", self.var_gamma)

        # 行3：权重 json / 车道版本（按你的 KaHIP.py 需要）
        row3 = ttk.Frame(frm); row3.pack(fill="x", pady=6)
        ttk.Label(row3, text="road_type_weights.json").pack(side="left")
        ttk.Entry(row3, textvariable=self.var_road_json, width=50).pack(side="left", padx=6)
        ttk.Button(row3, text="选择...", command=self._choose_json).pack(side="left", padx=6)

        row3b = ttk.Frame(frm); row3b.pack(fill="x", pady=2)
        ttk.Label(row3b, text="lane_weight_version（可选）").pack(side="left")
        ttk.Entry(row3b, textvariable=self.var_lane_ver, width=20).pack(side="left", padx=6)

        # 行4：选择是否调用 KaHIP（否则用后备分区）
        row4 = ttk.Frame(frm); row4.pack(fill="x", pady=6)
        ttk.Checkbutton(row4, text="使用 KaHIP.py 计算真实分区", variable=self.var_use_kahip).pack(side="left")

        # 行5：按钮
        row5 = ttk.Frame(frm); row5.pack(fill="x", pady=10)
        self.btn_run = ttk.Button(row5, text="运行 / 更新", command=self._on_run_clicked)
        self.btn_run.pack(side="left")

        ttk.Button(row5, text="打开输出文件夹", command=lambda: self._open_dir(OUTPUT_DIR)).pack(side="left", padx=8)

    def _build_log(self):
        frm = ttk.Frame(self, padding=(12,0))
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="运行日志 / 指标").pack(anchor="w")
        self.txt = tk.Text(frm, height=14)
        self.txt.pack(fill="both", expand=True)
        self._log("准备就绪。调整参数后点击『运行 / 更新』。")

    def _log(self, msg: str):
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.update_idletasks()

    def _choose_json(self):
        path = filedialog.askopenfilename(
            title="选择 road_type_weights.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path: self.var_road_json.set(path)

    def _open_dir(self, path: str):
        try:
            import platform, subprocess
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _on_run_clicked(self):
        if self._running: return
        self._running = True
        self.btn_run.config(state="disabled")
        t = threading.Thread(target=self._run_pipeline, daemon=True)
        t.start()

    def _run_pipeline(self):
        try:
            place   = self.var_place.get().strip()
            dist    = int(self.var_dist.get())
            k       = int(self.var_k.get())
            alpha   = float(self.var_alpha.get())
            beta    = float(self.var_beta.get())
            gamma   = float(self.var_gamma.get())
            road_js = self.var_road_json.get().strip() or None
            lane_v  = self.var_lane_ver.get().strip() or None
            use_kahip = bool(self.var_use_kahip.get())

            self._log(f"参数：place='{place}', dist={dist}, k={k}, α/β/γ=({alpha:.2f},{beta:.2f},{gamma:.2f})")
            # 1) 加载路网
            from core.osm_loader import load_graph
            G = load_graph(place, dist=dist)
            self._log(f"- 图规模：nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

            if use_kahip:
                # 2) 调 KaHIP.py
                self._log("- 调用 KaHIP.py 计算真实分区...")
                params = dict(place=place, k=k, alpha=alpha, beta=beta, gamma=gamma,
                              road_type_weights=road_js, lane_weight_version=lane_v)
                json_path = run_kahip(params)
                self._log(f"- KaHIP 输出 JSON：{json_path}")

                # 3) 读取 KaHIP 输出
                data = read_kahip_json(json_path)
                nodes_gdf, edges_gdf = parse_from_json(G, data)
            else:
                # 2*) 后备分区方案（演示用）
                self._log("- 使用后备分区（谱聚类/最近中心）...")
                assignment = spectral_partition(G, k)
                nodes_gdf, edges_gdf = gdfs_from_assignment(G, assignment)

            # 4) 统计 + 绘图
            from core.visualize import make_map, compute_cut_stats
            stats = compute_cut_stats(edges_gdf)
            self._log(f"- cut_edge_count={stats['cut_edge_count']}, edges={stats['edges']}, cut_ratio={stats['cut_ratio']:.4f}")

            html = make_map(nodes_gdf, edges_gdf, place, k)
            self._log(f"- 生成地图：{html}")
            webbrowser.open(f"file://{os.path.abspath(html)}", new=2)

        except Exception as e:
            messagebox.showerror("运行失败", str(e))
            self._log(f"[ERROR] {e}")
        finally:
            self._running = False
            self.btn_run.config(state="normal")
