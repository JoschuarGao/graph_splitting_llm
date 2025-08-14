import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

from KaHIP import process_place, load_weights, load_lane_weights
import os
from datetime import datetime

# Fixed map and partition versions
PLACE = "Karlsruhe"
ROAD_TYPE_VERSION = "all_1"
LANE_WEIGHT_VERSION = "all_1"
ROAD_TYPE_PATH = "road_type_weights.json"
LANE_WEIGHT_PATH = "lane_weight_version.json"

# Load weight configuration
road_type_weights = load_weights(ROAD_TYPE_VERSION, ROAD_TYPE_PATH)
lane_weight_config = load_lane_weights(LANE_WEIGHT_VERSION, LANE_WEIGHT_PATH)

# Matplotlib figure elements for display
fig, ax = plt.subplots(figsize=(8, 8))
canvas = None

# Current parameter values
params = {
    "k": 3,
    "alpha": 1.0,
    "beta": 1.0,
    "gamma": 0.1
}

# Label to display results
result_label = None


def update_graph():
    """
    Update the graph visualization and statistics display.
    This function calls the main partitioning function and refreshes the plot and metrics.
    """
    ax.clear()

    # Temporary CSV path for results (used only for display, not for saving permanently)
    temp_csv = os.path.expanduser("~/Desktop/masterarbeit/result/temp_result.csv")
    if os.path.exists(temp_csv):
        os.remove(temp_csv)

    # Call the main partitioning function from KaHIP.py
    process_place(
        place=PLACE,
        road_type_weights=road_type_weights,
        version=ROAD_TYPE_VERSION,
        k=params["k"],
        cache_dir="./cached_maps",
        dist=3000,
        csv_path=temp_csv,
        lane_weight_config=lane_weight_config,
        lane_weight_version=LANE_WEIGHT_VERSION,
        alpha=params["alpha"],
        beta=params["beta"],
        gamma=params["gamma"]
    )

    # Redraw the Matplotlib figure
    fig.canvas.draw()

    # Read the CSV file to display metrics
    if os.path.exists(temp_csv):
        with open(temp_csv, "r") as f:
            lines = f.readlines()
            if len(lines) >= 2:
                data = lines[-1].strip().split(",")
                cut_count = data[4]
                cut_weight = data[5]
                total_weight = data[6]
                cut_ratio = data[-1]
                result_text = f"Cut Edges: {cut_count}, Weight Sum: {cut_weight}, Total: {total_weight}, Ratio: {cut_ratio}"
                result_label.config(text=result_text)


def on_slider_change(name, val):
    """
    Handle slider value changes and update parameters accordingly.
    """
    if name in ["k"]:
        params[name] = int(val)
    else:
        params[name] = float(val)
    update_graph()


def main():
    """
    Create the main Tkinter window, embed the Matplotlib plot,
    and add interactive sliders for adjusting partition parameters.
    """
    global canvas, result_label

    root = tk.Tk()
    root.title("Graph Partition Interactive GUI")

    # Embed Matplotlib figure into Tkinter window
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack()

    # Sliders frame
    control_frame = tk.Frame(root)
    control_frame.pack(pady=10)

    # Slider configuration: min, max, resolution
    sliders = {
        "k": {"from": 2, "to": 8, "res": 1},
        "alpha": {"from": 0.1, "to": 3.0, "res": 0.1},
        "beta": {"from": 0.1, "to": 3.0, "res": 0.1},
        "gamma": {"from": 0.01, "to": 1.0, "res": 0.01}
    }

    # Create sliders dynamically
    for idx, (name, config) in enumerate(sliders.items()):
        label = tk.Label(control_frame, text=name)
        label.grid(row=idx, column=0, padx=10, sticky="e")

        slider = tk.Scale(control_frame, from_=config["from"], to=config["to"],
                          resolution=config["res"], orient="horizontal",
                          length=300, command=lambda val, n=name: on_slider_change(n, val))
        slider.set(params[name])
        slider.grid(row=idx, column=1, padx=10)

    # Label to display computed metrics
    result_label = tk.Label(root, text="Cut Ratio: --", font=("Arial", 12), pady=10)
    result_label.pack()

    # Initial graph update
    update_graph()

    root.mainloop()


if __name__ == "__main__":
    main()
