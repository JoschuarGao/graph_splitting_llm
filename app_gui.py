import os,sys,webbrowser
from pathlib import Path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.append(ROOT)

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR

try:
    from tkinterweb import HtmlFrame   # pip install tkinterweb
    HAS_HTML = True
except Exception:
    HtmlFrame = None
    HAS_HTML = False

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSM 分区可视化(KaHIP + explore)")
        self.geometry("900x560")

        # 变量
        self.var_place = tk.StringVar(value="Karlsruhe, Germany")
        self.var_dist = tk.IntVar(value=20000)
        self.var_k = tk.IntVar(value=4)

        self.var_alpha = tk.DoubleVar(value=1.0)
        self.var_beta  = tk.DoubleVar(value=1.0)
        self.var_gamma = tk.DoubleVar(value=1.0)

        self.var_road_json = tk.StringVar(value="")
        self.var_road_ver  = tk.StringVar(value="all_1")   # 路型权重“版本”
        self.var_lane_ver  = tk.StringVar(value="v1")      # 给车道权重版本一个有效默认值


        self._build_form()
        self._build_view()

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

        row3a = ttk.Frame(frm); row3a.pack(fill="x", pady=6)
        ttk.Label(row3a, text="road_type_version").pack(side="left")
        ttk.Entry(row3a, textvariable=self.var_road_ver, width=20).pack(side="left", padx=6)

        # 行3：权重 json / 车道版本（按你的 KaHIP.py 需要）
        row3 = ttk.Frame(frm); row3.pack(fill="x", pady=6)
        ttk.Label(row3, text="road_type_weights.json").pack(side="left")
        ttk.Entry(row3, textvariable=self.var_road_json, width=50).pack(side="left", padx=6)
        ttk.Button(row3, text="选择...", command=self._choose_json).pack(side="left", padx=6)

        row3b = ttk.Frame(frm); row3b.pack(fill="x", pady=2)
        ttk.Label(row3b, text="lane_weight_version").pack(side="left")
        ttk.Entry(row3b, textvariable=self.var_lane_ver, width=20).pack(side="left", padx=6)

        row4 = ttk.Frame(frm); row4.pack(fill="x", pady=10)
        self.btn_run = ttk.Button(row4, text="运行 / 更新", command=self._on_run_clicked)
        self.btn_run.pack(side="left", padx=(12,0))

        # 行5：按钮
        row5 = ttk.Frame(frm); row5.pack(fill="x", pady=10)

        ttk.Button(row5, text="打开输出文件夹", command=lambda: self._open_dir(OUTPUT_DIR)).pack(side="left", padx=8)

    def _build_view(self):
        # 一个 Notebook：页签1显示地图，页签2显示日志
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0,12))

        # 地图页
        self.tab_map = ttk.Frame(self.nb)
        self.nb.add(self.tab_map, text="Map")
        if HAS_HTML:
            self.map_frame = HtmlFrame(self.tab_map)
            self.map_frame.pack(fill="both", expand=True)
            self._log("地图面板已就绪。运行后会在此显示。")
        else:
            self.map_frame = None
            ttk.Label(
                self.tab_map,
                text="tkinterweb not installed,无法在窗口内嵌地图。\n已自动回退为在默认浏览器中打开。",
                foreground="#a00"
            ).pack(pady=12)

        # 日志页
        tab_log = ttk.Frame(self.nb)
        self.nb.add(tab_log, text="运行日志 / 指标")
        self.txt = tk.Text(tab_log, height=14)
        self.txt.pack(fill="both", expand=True)

        # 初始提示
        self._log("准备就绪。调整参数后点击『运行 / 更新』。")

    def _show_map(self, html_path: str):
        """把生成的 HTML 地图嵌到 GUI；若不支持则用系统浏览器打开。"""
        abs_path = os.path.abspath(html_path)
        exists = os.path.exists(abs_path)
        self._log(f"[内嵌地图] 准备加载: {abs_path}  (exists={exists})")

        if HAS_HTML and self.map_frame is not None and exists:
            try:
                # 关键：优先用 load_file 读取本地 HTML
                self.map_frame.load_file(abs_path)
                self._log("[内嵌地图] load_file OK")
                if hasattr(self, "nb") and hasattr(self, "tab_map"):
                    self.nb.select(self.tab_map)
                    return
            except Exception as e:
                self._log(f"[WARN] load_file 失败: {e}")

        # 回退：用系统浏览器打开
        webbrowser.open_new_tab(abs_path)
        self._log(f"[外部浏览器] {abs_path}")



    def _log(self, msg: str):
        self.after(0, lambda: (self.txt.insert("end", msg + "\n"), self.txt.see("end")))


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

        if hasattr(self, "nb"):
            self.nb.select(self.nb.tabs()[-1])  # 选中最后一个页签（日志）
            self._log("开始计算…（首次加载路网可能需要几十秒，建议先把 dist 调小测试）")

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

            if road_js and not os.path.isfile(road_js):
                self._log(f"[WARN] road_type_weights.json 不存在：{road_js}")
                self.after(0, lambda: messagebox.showwarning("文件不存在", f"{road_js}"))
                road_js = None

            self._log(f"参数：place='{place}', dist={dist}, k={k}, α/β/γ=({alpha:.2f},{beta:.2f},{gamma:.2f})")

            G = load_graph(place, dist=dist)
            self._log(f"- 图规模：nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

            # 仅 KaHIP 分支
            self._log("- 调用 KaHIP.py 计算真实分区...")
            json_path = run_kahip(
                place=place, k=k, dist=dist,
                alpha=alpha, beta=beta, gamma=gamma,
                road_type_version=(self.var_road_ver.get().strip() or "all_1"),
                road_type_path=(road_js or "road_type_weights.json"),
                lane_weight_version=(lane_v or "v1"),
)

            self._log(f"- KaHIP 输出 JSON：{json_path}")

            data = read_kahip_json(json_path)
            nodes_gdf, edges_gdf = parse_from_json(G, data)

            stats = compute_cut_stats(edges_gdf)
            # 确保键名与 compute_cut_stats 返回一致
            self._log(f"- cut_edge_count={stats['cut_edge_count']}, edges={stats['edges']}, cut_ratio={stats['cut_ratio']:.4f}")


            html = make_map(nodes_gdf, edges_gdf, place, k)
            self._log(f"- graph generated: {html}")
            self._show_map(html)


        except Exception as e:
            import traceback
            msg = f"{e}"
            self._log("[ERROR] " + msg)
            # 也把完整堆栈写到日志里，方便排查
            self._log(traceback.format_exc())

            # 关键：把 msg 绑定到 lambda 的默认参数，避免 e 丢失
            self.after(0, lambda m=msg: messagebox.showerror("fail running", m))

        finally:
            self._running = False
            self.after(0, lambda: self.btn_run.config(state="normal"))

if __name__ == "__main__":
    app = App()
    app.mainloop()
 