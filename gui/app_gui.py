import os
import osmnx as ox
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.osm_loader import load_graph
from core.kahip_runner import run_kahip
from core.results_reader import read_kahip_json, parse_from_json
from gui.visualize import make_map, compute_cut_stats
from core.partition_fallback import spectral_partition, gdfs_from_assignment


class App(tk.Tk):
    def __init__(self):
        """Main Tkinter application window for OSM partition visualization."""
        super().__init__()
        self.title("OSM Partition Visualization (KaHIP + explore)")
        self.geometry("900x560")

        # Variables (bound to form inputs)
        self.var_place = tk.StringVar(value="Karlsruhe, Germany")
        self.var_dist = tk.IntVar(value=20000)
        self.var_k = tk.IntVar(value=4)

        self.var_alpha = tk.DoubleVar(value=1.0)
        self.var_beta = tk.DoubleVar(value=1.0)
        self.var_gamma = tk.DoubleVar(value=1.0)

        self.var_road_json = tk.StringVar(value="")
        self.var_lane_ver = tk.StringVar(value="")
        self.var_use_kahip = tk.BooleanVar(value=True)  # Checked → use KaHIP; unchecked → fallback partition

        self._build_form()
        self._build_log()

        self._running = False

    def _build_form(self):
        """Build input form (parameters, file pickers, run button)."""
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="x")

        style = ttk.Style()
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("CardLabel.TLabel", background="#ffffff")

        # City selection card
        card = ttk.Frame(frm, style="Card.TFrame", padding=12)
        card.pack(fill="x", pady=(0, 10))
        # Outer border
        border = tk.Frame(card, background="#d0d7de", bd=1, relief="solid")
        border.pack(fill="both", expand=True)
        inner = ttk.Frame(border, padding=12, style="Card.TFrame")
        inner.pack(fill="both", expand=True)

        ttk.Label(inner, text="Choose City (Place)", style="CardLabel.TLabel", font=("Arial", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6), columnspan=6
        )

        # City input + buttons
        ttk.Label(inner, text="City name:", style="CardLabel.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 6))
        self.entry_place = ttk.Entry(inner, textvariable=self.var_place, width=46)
        self.entry_place.grid(row=1, column=1, sticky="we", padx=(0, 6), columnspan=3)

        ttk.Button(inner, text="Validate", command=self._validate_place).grid(row=1, column=4, padx=4, sticky="w")
        ttk.Button(inner, text="Clear", command=lambda: self.var_place.set("")).grid(row=1, column=5, padx=4, sticky="w")

        # History of recent city inputs
        ttk.Label(inner, text="History:", style="CardLabel.TLabel").grid(
            row=2, column=0, sticky="e", padx=(0, 6), pady=(8, 0)
        )
        self.combo_history = ttk.Combobox(inner, values=[], state="readonly", width=44)
        self.combo_history.grid(row=2, column=1, sticky="we", padx=(0, 6), pady=(8, 0), columnspan=3)
        self.combo_history.bind(
            "<<ComboboxSelected>>", lambda e: self.var_place.set(self.combo_history.get())
        )
        ttk.Button(inner, text="Example", command=lambda: self.var_place.set("Karlsruhe, Germany")).grid(
            row=2, column=4, padx=4, pady=(8, 0), sticky="w"
        )

        inner.columnconfigure(1, weight=1)  # Allow stretching

        # Basic parameters: dist, k
        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=6)
        ttk.Label(row1, text="dist [m]").pack(side="left")
        ttk.Entry(row1, textvariable=self.var_dist, width=9).pack(side="left", padx=(6, 12))

        ttk.Label(row1, text="k (partitions)").pack(side="left")
        ttk.Spinbox(row1, from_=2, to=20, textvariable=self.var_k, width=6).pack(side="left", padx=(6, 12))

        # Sliders for alpha / beta / gamma
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=6)

        def add_slider(parent, label, var):
            box = ttk.Frame(parent)
            box.pack(fill="x", pady=4)
            ttk.Label(box, text=label, width=10).pack(side="left")
            s = ttk.Scale(box, from_=0.0, to=5.0, orient="horizontal", variable=var)
            s.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Label(box, textvariable=var, width=6).pack(side="left")

        add_slider(row2, "alpha", self.var_alpha)
        add_slider(row2, "beta", self.var_beta)
        add_slider(row2, "gamma", self.var_gamma)

        # Road type weights JSON / lane weight version
        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=6)
        ttk.Label(row3, text="road_type_weights.json").pack(side="left")
        ttk.Entry(row3, textvariable=self.var_road_json, width=50).pack(side="left", padx=6)
        ttk.Button(row3, text="Browse...", command=self._choose_json).pack(side="left", padx=6)

        row3b = ttk.Frame(frm)
        row3b.pack(fill="x", pady=2)
        ttk.Label(row3b, text="lane_weight_version (optional)").pack(side="left")
        ttk.Entry(row3b, textvariable=self.var_lane_ver, width=20).pack(side="left", padx=6)

        # KaHIP toggle + Run button
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=10)
        ttk.Checkbutton(row4, text="Use KaHIP.py for real partition", variable=self.var_use_kahip).pack(side="left")
        self.btn_run = ttk.Button(row4, text="Run / Update", command=self._on_run_clicked)
        self.btn_run.pack(side="left", padx=(12, 0))

    def _build_log(self):
        """Build the run log display."""
        frm = ttk.Frame(self, padding=(12, 0))
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Run Log / Metrics").pack(anchor="w")
        self.txt = tk.Text(frm, height=14)
        self.txt.pack(fill="both", expand=True)
        self._log("Ready. Adjust parameters and click 'Run / Update'.")

    def _validate_place(self):
        """Try geocoding the place; show bounding box if found; add to history."""
        place = self.var_place.get().strip()
        if not place:
            messagebox.showwarning("Warning", "Please enter a city name (e.g., 'Karlsruhe, Germany').")
            return
        try:
            gdf = ox.geocode_to_gdf(place)
            bounds = gdf.total_bounds
            bbox_str = f"minx={bounds[0]:.5f}, miny={bounds[1]:.5f}, maxx={bounds[2]:.5f}, maxy={bounds[3]:.5f}"
            self._log(f"[Valid] {place}\n  BBox: {bbox_str}")

            # Update history (deduplicate, keep latest first)
            vals = list(self.combo_history.cget("values"))
            if place in vals:
                vals.remove(place)
            vals.insert(0, place)
            vals = vals[:10]
            self.combo_history["values"] = vals
            self.combo_history.set(place)

            messagebox.showinfo("Validation success", f"Found: {place}\n{bbox_str}")
        except Exception as e:
            self._log(f"[Invalid] {place} → {e}")
            messagebox.showerror("Validation failed", f"Could not resolve location:\n{e}")

    def _log(self, msg: str):
        """Append a message to the log box."""
        def append_text():
            self.txt.insert("end", msg + "\n")
            self.txt.see("end")
        self.after(0, append_text)

    def _choose_json(self):
        """Open file dialog to choose road_type_weights.json."""
        path = filedialog.askopenfilename(
            title="Choose road_type_weights.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.var_road_json.set(path)

    def _open_dir(self, path: str):
        """Open directory in system file explorer."""
        try:
            import platform, subprocess
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def _on_run_clicked(self):
        """Start pipeline in a background thread."""
        if self._running:
            return
        self._running = True
        self.btn_run.config(state="disabled")
        t = threading.Thread(target=self._run_pipeline, daemon=True)
        t.start()

    def _run_pipeline(self):
        """Run KaHIP or fallback partition, generate map, update log."""
        try:
            place = self.var_place.get().strip()
            dist = int(self.var_dist.get())
            k = int(self.var_k.get())
            alpha = float(self.var_alpha.get())
            beta = float(self.var_beta.get())
            gamma = float(self.var_gamma.get())
            road_js = self.var_road_json.get().strip() or None
            lane_v = self.var_lane_ver.get().strip() or None
            use_kahip = bool(self.var_use_kahip.get())

            self._log(
                f"Params: place='{place}', dist={dist}, k={k}, alpha/beta/gamma=({alpha:.2f},{beta:.2f},{gamma:.2f})"
            )

            # Load OSM graph
            G = load_graph(place, dist=dist)
            self._log(f"- Graph size: nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")

            if use_kahip:
                # Run KaHIP
                self._log("- Running KaHIP.py...")
                params = dict(place=place, k=k, alpha=alpha, beta=beta, gamma=gamma,
                              road_type_weights=road_js, lane_weight_version=lane_v)
                json_path = run_kahip(params)
                self._log(f"- KaHIP output JSON: {json_path}")

                # Parse KaHIP output
                data = read_kahip_json(json_path)
                nodes_gdf, edges_gdf = parse_from_json(G, data)
            else:
                # Fallback partition (for demo)
                self._log("- Using fallback partition (spectral clustering)...")
                assignment = spectral_partition(G, k)
                nodes_gdf, edges_gdf = gdfs_from_assignment(G, assignment)

            # Compute cut stats and create map
            stats = compute_cut_stats(edges_gdf)
            self._log(f"- cut_edge_count={stats['cut_edge_count']}, edges={stats['edges']}, cut_ratio={stats['cut_ratio']:.4f}")

            html = make_map(nodes_gdf, edges_gdf, place, k)
            self._log(f"- Map generated: {html}")
            webbrowser.open(f"file://{os.path.abspath(html)}", new=2)

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Run failed", str(e)))
            self._log(f"[ERROR] {e}")
        finally:
            self._running = False
            self.after(0, lambda: self.btn_run.config(state="normal"))


if __name__ == "__main__":
    app = App()
    app.mainloop()
