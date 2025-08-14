import os, sys, webbrowser
from pathlib import Path

# Add project root to Python path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.config import OUTPUT_DIR

# Try to import tkinterweb for embedded HTML map view
try:
    from tkinterweb import HtmlFrame
    HAS_HTML = True
except Exception:
    HtmlFrame = None
    HAS_HTML = False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSM Partition Viewer (KaHIP + Folium)")
        self.geometry("900x560")

        # Parameter variables
        self.var_place = tk.StringVar(value="Karlsruhe, Germany")
        self.var_dist  = tk.IntVar(value=5000)
        self.var_k     = tk.IntVar(value=4)
        self.var_alpha = tk.DoubleVar(value=1.0)
        self.var_beta  = tk.DoubleVar(value=1.0)
        self.var_gamma = tk.DoubleVar(value=1.0)
        self.var_road_json = tk.StringVar(value="")
        self.var_road_ver  = tk.StringVar(value="all_1")
        self.var_lane_ver  = tk.StringVar(value="v1")

        # Cache for map results and debounce control
        self._map_cache = {}
        self._debounce_id = None
        self._running = False

        # Build UI
        self._build_form()
        self._build_view()

        # Initial log messages
        self._log(f"Python: {sys.executable}")
        self._log(f"tkinterweb: {'OK' if HAS_HTML else 'MISSING (will open in browser)'}")

    def _build_form(self):
        """Build the top parameter input panel."""
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="x")

        # Row 1: Place / dist / k
        row1 = ttk.Frame(frm); row1.pack(fill="x", pady=6)
        ttk.Label(row1, text="Place").pack(side="left")
        ttk.Entry(row1, textvariable=self.var_place, width=42).pack(side="left", padx=6)

        ttk.Label(row1, text="dist [m]").pack(side="left", padx=(12, 0))
        ttk.Entry(row1, textvariable=self.var_dist, width=9).pack(side="left", padx=4)

        ttk.Label(row1, text="k").pack(side="left", padx=(12, 0))
        sp_k = ttk.Spinbox(row1, from_=2, to=20, textvariable=self.var_k, width=6)
        sp_k.pack(side="left", padx=4)
        sp_k.configure(command=self._on_param_changed)
        sp_k.bind("<KeyRelease>", lambda e: self._on_param_changed())

        # Row 2: alpha / beta / gamma sliders
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=6)
        def add_slider(parent, label, var):
            box = ttk.Frame(parent); box.pack(fill="x", pady=4)
            ttk.Label(box, text=label, width=10).pack(side="left")
            s = ttk.Scale(box, from_=0.0, to=5.0, orient="horizontal", variable=var)
            s.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Label(box, textvariable=var, width=6).pack(side="left")
            s.configure(command=lambda _=None: self._on_param_changed())

        add_slider(row2, "alpha", self.var_alpha)
        add_slider(row2, "beta",  self.var_beta)
        add_slider(row2, "gamma", self.var_gamma)

        # Row 3a: road_type_version
        row3a = ttk.Frame(frm); row3a.pack(fill="x", pady=6)
        ttk.Label(row3a, text="road_type_version").pack(side="left")
        ttk.Entry(row3a, textvariable=self.var_road_ver, width=20).pack(side="left", padx=6)

        # Row 3b: road_type_weights.json + lane version
        row3 = ttk.Frame(frm); row3.pack(fill="x", pady=6)
        ttk.Label(row3, text="road_type_weights.json").pack(side="left")
        ttk.Entry(row3, textvariable=self.var_road_json, width=50).pack(side="left", padx=6)
        ttk.Button(row3, text="Browse…", command=self._choose_json).pack(side="left", padx=6)

        row3b = ttk.Frame(frm); row3b.pack(fill="x", pady=2)
        ttk.Label(row3b, text="lane_weight_version").pack(side="left")
        ttk.Entry(row3b, textvariable=self.var_lane_ver, width=20).pack(side="left", padx=6)

        # Row 4: Run button
        row4 = ttk.Frame(frm); row4.pack(fill="x", pady=10)
        self.btn_run = ttk.Button(row4, text="Run / Update", command=self._on_run_clicked)
        self.btn_run.pack(side="left", padx=(12, 0))

        # Row 5: Open output directory
        row5 = ttk.Frame(frm); row5.pack(fill="x", pady=10)
        ttk.Button(row5, text="Open output folder", command=lambda: self._open_dir(OUTPUT_DIR)).pack(side="left", padx=8)

    def _build_view(self):
        """Build the notebook view with 'Map' and 'Run Log / Metrics' tabs."""
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Map tab
        self.tab_map = ttk.Frame(self.nb)
        self.nb.add(self.tab_map, text="Map")
        if HAS_HTML:
            self.map_frame = HtmlFrame(self.tab_map)
            self.map_frame.pack(fill="both", expand=True)
            self._log("Map panel ready. Result will display here.")
        else:
            self.map_frame = None
            ttk.Label(
                self.tab_map,
                text="tkinterweb not installed – falling back to opening maps in your default browser.",
                foreground="#a00"
            ).pack(pady=12)

        # Log tab
        tab_log = ttk.Frame(self.nb)
        self.nb.add(tab_log, text="Run Log / Metrics")
        self.txt = tk.Text(tab_log, height=14)
        self.txt.pack(fill="both", expand=True)

        self._log("Ready. Adjust parameters to update map.")

    def _on_param_changed(self):
        """Debounce: schedule an update when parameters change."""
        if self._debounce_id:
            try:
                self.after_cancel(self._debounce_id)
            except:
                pass
        self._debounce_id = self.after(500, self._update_map_from_params)

    def _update_map_from_params(self):
        """Update map if parameters have changed, using cache if available."""
        params_key = (
            self.var_place.get().strip(),
            int(self.var_dist.get()),
            int(self.var_k.get()),
            float(self.var_alpha.get()),
            float(self.var_beta.get()),
            float(self.var_gamma.get()),
            self.var_road_ver.get().strip(),
            self.var_lane_ver.get().strip()
        )
        if params_key in self._map_cache and os.path.exists(self._map_cache[params_key]):
            self._log(f"[Cache hit] {params_key}")
            self._show_map(self._map_cache[params_key])
        else:
            self._log(f"[Cache miss] {params_key}")
            if self._running:
                return
            self._running = True
            self.btn_run.config(state="disabled")
            t = threading.Thread(target=lambda: self._run_pipeline_and_cache(params_key), daemon=True)
            t.start()

    def _run_pipeline_and_cache(self, params_key):
        """Run the partitioning pipeline and store the HTML result in cache."""
        try:
            html = self._run_pipeline_core()
            self._map_cache[params_key] = html
            self.after(0, lambda: self._show_map(html))
        finally:
            self._running = False
            self.after(0, lambda: self.btn_run.config(state="normal"))

    def _run_pipeline_core(self):
        """Core logic: load graph, run KaHIP, parse results, compute stats, generate map."""
        place = self.var_place.get().strip()
        dist  = int(self.var_dist.get())
        k     = int(self.var_k.get())
        alpha = float(self.var_alpha.get())
        beta  = float(self.var_beta.get())
        gamma = float(self.var_gamma.get())
        road_js = self.var_road_json.get().strip() or None
        lane_v  = self.var_lane_ver.get().strip() or None

        if road_js and not os.path.isfile(road_js):
            self._log(f"[WARN] road_type_weights.json not found: {road_js}")
            self.after(0, lambda: messagebox.showwarning("Missing file", f"{road_js}"))
            road_js = None

        self._log(f"Params: place='{place}', dist={dist}, k={k}, α/β/γ=({alpha:.2f},{beta:.2f},{gamma:.2f})")

        G = load_graph(place, dist=dist)
        self._log(f"- Graph size: nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

        self._log("- Running KaHIP.py partitioning...")
        json_path = run_kahip(
            place=place, k=k, dist=dist,
            alpha=alpha, beta=beta, gamma=gamma,
            road_type_version=(self.var_road_ver.get().strip() or "all_1"),
            road_type_path=(road_js or "road_type_weights.json"),
            lane_weight_version=(lane_v or "v1"),
        )
        self._log(f"- KaHIP JSON: {json_path}")

        data = read_kahip_json(json_path)
        nodes_gdf, edges_gdf = parse_from_json(G, data)

        stats = compute_cut_stats(edges_gdf)
        self._log(f"- cut_edge_count={stats['cut_edge_count']}, edges={stats['edges']}, cut_ratio={stats['cut_ratio']:.4f}")

        html = make_map(nodes_gdf, edges_gdf, place, k)
        self._log(f"- HTML map: {html}")
        return html

    def _show_map(self, html_path: str):
        """Display the HTML map either in embedded view or browser."""
        abs_path = os.path.abspath(html_path)
        exists = os.path.exists(abs_path)
        self._log(f"[Embed] Load: {abs_path}  (exists={exists})")
        if HAS_HTML and self.map_frame is not None and exists:
            try:
                self.map_frame.load_file(abs_path)
                self._log("[Embed] load_file OK")
                self.nb.select(self.tab_map)
                return
            except Exception as e:
                self._log(f"[WARN] load_file failed: {e}")
        webbrowser.open_new_tab(abs_path)
        self._log(f"[Browser] {abs_path}")

    def _log(self, msg: str):
        """Append a log message to the log tab."""
        self.after(0, lambda: (self.txt.insert("end", msg + "\n"), self.txt.see("end")))

    def _choose_json(self):
        """Open file dialog to choose road_type_weights.json."""
        path = filedialog.askopenfilename(
            title="Choose road_type_weights.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.var_road_json.set(path)

    def _open_dir(self, path: str):
        """Open the specified directory in the system file browser."""
        try:
            import platform, subprocess
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    def _on_run_clicked(self):
        """Handler for 'Run / Update' button click."""
        self._update_map_from_params()


if __name__ == "__main__":
    app = App()
    app.mainloop()
