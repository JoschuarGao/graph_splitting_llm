import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

from KaHIP import process_place, load_weights, load_lane_weights
import os
from datetime import datetime

# 固定地图与划分版本
PLACE = "Karlsruhe"
ROAD_TYPE_VERSION = "all_1"
LANE_WEIGHT_VERSION = "all_1"
ROAD_TYPE_PATH = "road_type_weights.json"
LANE_WEIGHT_PATH = "lane_weight_version.json"

# 加载权重配置
road_type_weights = load_weights(ROAD_TYPE_VERSION, ROAD_TYPE_PATH)
lane_weight_config = load_lane_weights(LANE_WEIGHT_VERSION, LANE_WEIGHT_PATH)

# 图形显示用的 matplotlib 元素
fig, ax = plt.subplots(figsize=(8, 8))
canvas = None

# 当前参数值
params = {
    "k": 3,
    "alpha": 1.0,
    "beta": 1.0,
    "gamma": 0.1
}

# 结果标签
result_label = None

def update_graph():
    ax.clear()

    # 临时路径，仅显示不保存
    temp_csv = os.path.expanduser("~/Desktop/masterarbeit/result/temp_result.csv")
    if os.path.exists(temp_csv):
        os.remove(temp_csv)

    # 调用主划分函数（KaHIP.py 中）
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

    fig.canvas.draw()

    # 读取 CSV 展示指标
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
    if name in ["k"]:
        params[name] = int(val)
    else:
        params[name] = float(val)
    update_graph()

def main():
    global canvas, result_label

    root = tk.Tk()
    root.title("Graph Partition Interactive GUI")

    # Matplotlib 图嵌入
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack()

    # 滑块区域
    control_frame = tk.Frame(root)
    control_frame.pack(pady=10)

    sliders = {
        "k": {"from": 2, "to": 8, "res": 1},
        "alpha": {"from": 0.1, "to": 3.0, "res": 0.1},
        "beta": {"from": 0.1, "to": 3.0, "res": 0.1},
        "gamma": {"from": 0.01, "to": 1.0, "res": 0.01}
    }

    for idx, (name, config) in enumerate(sliders.items()):
        label = tk.Label(control_frame, text=name)
        label.grid(row=idx, column=0, padx=10, sticky="e")

        slider = tk.Scale(control_frame, from_=config["from"], to=config["to"],
                          resolution=config["res"], orient="horizontal",
                          length=300, command=lambda val, n=name: on_slider_change(n, val))
        slider.set(params[name])
        slider.grid(row=idx, column=1, padx=10)

    # 显示结果指标
    result_label = tk.Label(root, text="Cut Ratio: --", font=("Arial", 12), pady=10)
    result_label.pack()

    # 初始图
    update_graph()

    root.mainloop()

if __name__ == "__main__":
    main()
