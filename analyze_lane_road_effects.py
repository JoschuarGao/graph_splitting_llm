#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_lane_road_effects.py
分析“车道数版本(lane)”与“道路种类版本(road)”对 cut_ratio 的影响。
- 支持 CSV 列名含空格（比如 road 列叫 "weight version"）
- 默认固定：k=6 且 alpha=beta=gamma=1（可用 --fix-* 修改；--where 追加过滤）
- 新增：按用户给的版本顺序计算 Spearman 单调趋势，并输出 CSV

示例（指定 road 列为 'weight version'，并给出顺序）：
python analyze_lane_road_effects.py \
  --csv unified/doe_results.csv \
  --outdir fig_multi_city/lane_road_effects \
  --per-city \
  --road-col "weight version" \
  --road-order MinorPlus Equal MajorPlus
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from scipy.stats import kruskal, mannwhitneyu, spearmanr
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.anova import anova_lm

# --------- utils ----------
LANE_CANDIDATES = ["lane_weight_version","lane version","lane_version","lnv","laneWeightVersion"]
ROAD_CANDIDATES = ["road_type_version","road version","road_version","rtv","road_type","roadTypeVersion","weight version"]

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def parse_kv_list(items):
    d={}
    for it in items or []:
        if "=" in it:
            k,v = it.split("=",1)
            d[k.strip()] = v.strip()
    return d

def apply_where(df, where, atol=1e-9):
    if not where: return df
    m = np.ones(len(df), dtype=bool)
    for k,v in where.items():
        if k not in df.columns: continue
        s = df[k]
        if s.dtype.kind in "fc":
            try: val = float(v)
            except: continue
            m &= (np.isfinite(s)) & (np.abs(s - val) <= atol)
        else:
            m &= (s.astype(str) == v)
    return df[m].copy()

def load_df(csv_path):
    df = pd.read_csv(csv_path)
    # 保留原始列名（包括空格），只去掉首尾空白
    df.columns = [c.strip() for c in df.columns]
    for c in ["alpha","beta","gamma","k","dist","cut_ratio"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["cut_ratio"])

def pick_col(df, user_col, candidates):
    if user_col:
        if user_col in df.columns:
            return user_col
        raise SystemExit(f"指定列 '{user_col}' 不在 CSV。可用列：{list(df.columns)}")
    for c in candidates:
        if c in df.columns:
            return c
    return None

def holm_correction(pvals):
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    for rank, idx in enumerate(order):
        adj[idx] = min((m - rank) * pvals[idx], 1.0)
    # 保序
    for i in range(1, m):
        adj[order[i]] = max(adj[order[i]], adj[order[i-1]])
    return adj

# --------- plotting ----------
def boxplot_by_factor(df, factor, outdir, per_city=False, score="cut_ratio"):
    ensure_dir(outdir)
    # 全局
    plt.figure()
    df.boxplot(column=score, by=factor, grid=False)
    plt.title(f"Boxplot of {score} by {factor} – Global")
    plt.suptitle("")
    plt.xlabel(factor); plt.ylabel(score)
    fn = Path(outdir) / f"box_{factor}_global.png"
    plt.tight_layout(); plt.savefig(fn, dpi=160); plt.close()
    # 分城市
    if per_city and "place" in df.columns:
        for city, sub in df.groupby("place"):
            plt.figure()
            sub.boxplot(column=score, by=factor, grid=False)
            plt.title(f"Boxplot of {score} by {factor} – {city}")
            plt.suptitle("")
            plt.xlabel(factor); plt.ylabel(score)
            fn = Path(outdir) / f"box_{factor}_{city.replace(' ','_').replace(',','')}.png"
            plt.tight_layout(); plt.savefig(fn, dpi=160); plt.close()

def interaction_plot(df, lane_col, road_col, outdir, score="cut_ratio", agg="mean"):
    ensure_dir(outdir)
    if agg == "median":
        piv = df.groupby([lane_col, road_col])[score].median().unstack()
    else:
        piv = df.groupby([lane_col, road_col])[score].mean().unstack()
    plt.figure()
    x = np.arange(len(piv.index))
    for col in piv.columns:
        plt.plot(x, piv[col].values, marker="o", label=str(col))
    plt.xticks(x, piv.index, rotation=20)
    plt.xlabel(lane_col); plt.ylabel(f"{score} ({agg})")
    plt.title(f"Interaction plot: {lane_col} × {road_col} ({agg})")
    plt.legend(title=road_col, bbox_to_anchor=(1.02,1), loc="upper left")
    plt.tight_layout()
    fn = Path(outdir) / f"interaction_{lane_col}_{road_col}_{agg}.png"
    plt.savefig(fn, dpi=160); plt.close()

# --------- stats helpers (safe for space-in-name) ----------
def anova_one_factor_safe(df, factor, score="cut_ratio"):
    """对含空格列名安全：临时拷贝为 _FACTOR_TMP 用于公式"""
    tmp = df.copy()
    tmp["_FACTOR_TMP"] = tmp[factor].astype(str)
    model = smf.ols(f"{score} ~ C(_FACTOR_TMP)", data=tmp).fit()
    aov = anova_lm(model, typ=2)
    return model, aov

def tukey_posthoc_safe(df, factor, score="cut_ratio"):
    tmp = df.copy()
    tmp["_FACTOR_TMP"] = tmp[factor].astype(str)
    res = pairwise_tukeyhsd(tmp[score].values, tmp["_FACTOR_TMP"].values)
    return pd.DataFrame(res._results_table.data[1:], columns=res._results_table.data[0])

def kruskal_one_factor(df, factor, score="cut_ratio"):
    groups = [sub[score].dropna().values for _, sub in df.groupby(factor)]
    if len(groups) >= 2:
        H, p = kruskal(*groups)
    else:
        H, p = np.nan, np.nan
    return H, p

def mw_posthoc_holm(df, factor, score="cut_ratio"):
    levels = sorted(df[factor].astype(str).unique())
    rows, pvals = [], []
    for i in range(len(levels)):
        for j in range(i+1, len(levels)):
            a = df[df[factor].astype(str)==levels[i]][score].values
            b = df[df[factor].astype(str)==levels[j]][score].values
            if len(a)==0 or len(b)==0: continue
            U, p = mannwhitneyu(a, b, alternative="two-sided")
            rows.append([levels[i], levels[j], U, p]); pvals.append(p)
    if not rows:
        return pd.DataFrame(columns=["group1","group2","U","p_raw","p_adj"])
    adj = holm_correction(pvals)
    out=[]
    for (g1,g2,U,p), pa in zip(rows, adj):
        out.append([g1,g2,U,p,pa])
    return pd.DataFrame(out, columns=["group1","group2","U","p_raw","p_adj"])

def two_way_type3_with_place_safe(df, lane_col, road_col, score="cut_ratio"):
    tmp = df.copy()
    tmp["_LANE_TMP"] = tmp[lane_col].astype(str)
    tmp["_ROAD_TMP"] = tmp[road_col].astype(str)
    model = smf.ols(f"{score} ~ C(_LANE_TMP) * C(_ROAD_TMP) + C(place)", data=tmp).fit()
    aov = anova_lm(model, typ=3)
    return model, aov

# --------- Spearman 单调趋势（新增） ----------
def _spearman_trend_tables(df, factor, order_list, outdir, score="cut_ratio"):
    """
    计算 Spearman 单调趋势，并输出两张表：
    1) 全局：先对 (place, factor) 取 cut_ratio 中位数，再算 rho/p
    2) 分城市：每个城市对各 level 的中位数，再算 rho/p
    """
    ensure_dir(outdir)
    if (order_list is None) or (len(order_list) < 2):
        return

    # 统一为字符串
    df = df.dropna(subset=[factor, score]).copy()
    df["__fac__"] = df[factor].astype(str)
    order_map = {lvl: i for i, lvl in enumerate(order_list)}
    df["__code__"] = df["__fac__"].map(order_map)

    # ------- 全局（(place, factor) 中位数） -------
    if "place" in df.columns:
        g = df.groupby(["place","__fac__"], as_index=False)[score].median()
    else:
        g = df.groupby(["__fac__"], as_index=False)[score].median()
    g["__code__"] = g["__fac__"].map(order_map)
    g = g.dropna(subset=["__code__"]).copy()
    if len(g["__code__"].unique()) >= 2:
        rho_g, p_g = spearmanr(g["__code__"].values, g[score].values, nan_policy="omit")
    else:
        rho_g, p_g = np.nan, np.nan
    pd.DataFrame([{
        "factor": factor,
        "levels_order": " > ".join(order_list),
        "rho": rho_g,
        "p_value": p_g,
        "n_points": len(g)
    }]).to_csv(Path(outdir)/f"{factor}_spearman_global.csv", index=False)

    # ------- 分城市 -------
    if "place" in df.columns:
        rows = []
        for city, sub in df.groupby("place"):
            gg = sub.groupby("__fac__", as_index=False)[score].median()
            gg["__code__"] = gg["__fac__"].map(order_map)
            gg = gg.dropna(subset=["__code__"])
            if gg["__code__"].nunique() >= 2:
                rho, p = spearmanr(gg["__code__"].values, gg[score].values, nan_policy="omit")
            else:
                rho, p = np.nan, np.nan
            rows.append({
                "place": city,
                "rho": rho,
                "p_value": p,
                "n_levels": gg["__code__"].nunique()
            })
        pd.DataFrame(rows).to_csv(Path(outdir)/f"{factor}_spearman_by_city.csv", index=False)

# --------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--where", nargs="*", default=None)
    ap.add_argument("--per-city", action="store_true")
    ap.add_argument("--nonparam", action="store_true", help="一因素优先用 Kruskal-Wallis")
    ap.add_argument("--score", default="cut_ratio")
    ap.add_argument("--lane-col", default=None)
    ap.add_argument("--road-col", default=None)  # 可传 "weight version"
    # 固定项
    ap.add_argument("--fix-k", type=int, default=6)
    ap.add_argument("--fix-alpha", type=float, default=1.0)
    ap.add_argument("--fix-beta",  type=float, default=1.0)
    ap.add_argument("--fix-gamma", type=float, default=1.0)
    # 新增：有序顺序（用于 Spearman 单调趋势）
    ap.add_argument("--lane-order", nargs="+", default=None, help="例如：Small Equal Large")
    ap.add_argument("--road-order", nargs="+", default=None, help="例如：MinorPlus Equal MajorPlus")
    args = ap.parse_args()

    outdir = Path(args.outdir); ensure_dir(outdir)
    df = load_df(args.csv)

    # 固定变量过滤
    base = ( (df["k"]==args.fix_k) &
             (np.abs(df["alpha"]-args.fix_alpha) <= 1e-9) &
             (np.abs(df["beta"] -args.fix_beta ) <= 1e-9) &
             (np.abs(df["gamma"]-args.fix_gamma) <= 1e-9) )
    df = df[base].copy()

    # 追加 where
    df = apply_where(df, parse_kv_list(args.where))

    # 侦测列名
    lane_col = pick_col(df, args.lane_col, LANE_CANDIDATES)
    road_col = pick_col(df, args.road_col, ROAD_CANDIDATES)

    print("[info] columns:", list(df.columns))
    print(f"[info] detected lane_col = {lane_col}")
    print(f"[info] detected road_col = {road_col}")

    # ---------- lane ----------
    if lane_col:
        lane_dir = outdir / "lane_effect"; ensure_dir(lane_dir)
        dfl = df.dropna(subset=[lane_col]).copy()
        # 汇总表
        g = dfl.groupby(lane_col)[args.score].agg(["median","mean","count"]).sort_values("median")
        g.to_csv(lane_dir/"summary_global.csv")
        if "place" in dfl.columns:
            gc = dfl.groupby(["place", lane_col])[args.score].median().unstack()
            gc.to_csv(lane_dir/"summary_by_city.csv")
        # 箱线图
        boxplot_by_factor(dfl, lane_col, lane_dir, per_city=args.per_city, score=args.score)
        # 统计检验
        if args.nonparam:
            H, p = kruskal_one_factor(dfl, lane_col, score=args.score)
            pd.DataFrame([{"H":H, "p":p}]).to_csv(lane_dir/"kruskal_summary.csv", index=False)
            mw = mw_posthoc_holm(dfl, lane_col, score=args.score)
            mw.to_csv(lane_dir/"posthoc_mannwhitney_holm.csv", index=False)
        else:
            mdl, aov = anova_one_factor_safe(dfl, lane_col, score=args.score)
            aov.to_csv(lane_dir/"anova_table.csv")
            try:
                tk = tukey_posthoc_safe(dfl, lane_col, score=args.score)
                tk.to_csv(lane_dir/"posthoc_tukey.csv", index=False)
            except Exception as e:
                pd.DataFrame([{"warn":"Tukey failed", "err":repr(e)}]).to_csv(lane_dir/"posthoc_tukey_failed.csv", index=False)
        # Spearman 单调趋势（若给了顺序）
        if args.lane_order:
            _spearman_trend_tables(dfl, lane_col, args.lane_order, lane_dir, score=args.score)
    else:
        print("[info] 未找到 lane 列，跳过 lane 分析。")

    # ---------- road ----------
    if road_col:
        road_dir = outdir / "road_effect"; ensure_dir(road_dir)
        dfr = df.dropna(subset=[road_col]).copy()
        # 汇总表
        g2 = dfr.groupby(road_col)[args.score].agg(["median","mean","count"]).sort_values("median")
        g2.to_csv(road_dir/"summary_global.csv")
        if "place" in dfr.columns:
            gc2 = dfr.groupby(["place", road_col])[args.score].median().unstack()
            gc2.to_csv(road_dir/"summary_by_city.csv")
        # 箱线图
        boxplot_by_factor(dfr, road_col, road_dir, per_city=args.per_city, score=args.score)
        # 统计检验
        if args.nonparam:
            H, p = kruskal_one_factor(dfr, road_col, score=args.score)
            pd.DataFrame([{"H":H, "p":p}]).to_csv(road_dir/"kruskal_summary.csv", index=False)
            mw = mw_posthoc_holm(dfr, road_col, score=args.score)
            mw.to_csv(road_dir/"posthoc_mannwhitney_holm.csv", index=False)
        else:
            mdl, aov = anova_one_factor_safe(dfr, road_col, score=args.score)
            aov.to_csv(road_dir/"anova_table.csv")
            try:
                tk = tukey_posthoc_safe(dfr, road_col, score=args.score)
                tk.to_csv(road_dir/"posthoc_tukey.csv", index=False)
            except Exception as e:
                pd.DataFrame([{"warn":"Tukey failed", "err":repr(e)}]).to_csv(road_dir/"posthoc_tukey_failed.csv", index=False)
        # Spearman 单调趋势（若给了顺序）
        if args.road_order:
            _spearman_trend_tables(dfr, road_col, args.road_order, road_dir, score=args.score)
    else:
        print("[info] 未找到 road 列，跳过 road 分析。")

    # ---------- 二因素交互 ----------
    if lane_col and road_col:
        inter_dir = outdir / "lane_x_road"; ensure_dir(inter_dir)
        df_lr = df.dropna(subset=[lane_col, road_col]).copy()
        mdl2, aov2 = two_way_type3_with_place_safe(df_lr, lane_col, road_col, score=args.score)
        aov2.to_csv(inter_dir/"two_way_type3_anova.csv")
        (inter_dir/"ols_summary.txt").write_text(str(mdl2.summary()), encoding="utf-8")
        interaction_plot(df_lr, lane_col, road_col, inter_dir, score=args.score, agg="mean")
        interaction_plot(df_lr, lane_col, road_col, inter_dir, score=args.score, agg="median")
    else:
        print("[info] 因缺少 lane 或 road，已跳过交互分析。")

    print("[done] outputs in:", outdir)

if __name__ == "__main__":
    main()
