#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sens_single.py —— Phase 1 单参数敏感性（控制变量法，粗跑 + 精跑）。

方法（方案 §3.1）：
- 每次只动一个参数，其余锁 θ₀。
- 粗跑：大步长全空间扫 → 看单调段 / 拐点 / 平台交界 = 可疑区间。
- 精跑：对可疑区间细化步长重扫，锁定精确阈值。
  （区间 = 粗峰值 ± 1~2 个粗步长，防大步长跨过窄峰。）

用法：
    python sens_single.py                       # 全参数粗跑（12 个参数）
    python sens_single.py --param min_ent       # 只看某参数粗跑
    python sens_single.py --param min_ent --lo 0.3 --hi 0.8   # 该区间精跑（细档）
    python sens_single.py --out DIR             # 输出目录（默认 调参产物/sens）

输出（每参数一个 CSV + summary.csv）：
    sens/<param>.csv   参数值 → 全部指标 + 三套 score
    sens/summary.csv   参数、最优值、max score、敏感性(Δ=score跨度)、单调段
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune_engine import (BASE, DISCRETE, GRID_COARSE, GRID_FINE, Engine, fmt)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sens")

# rsr 必须配 spe 才有意义（救援门仅在 spe_rescue>0 时启用）：
# 扫 rsr_rescue 时把基准 spe 顶到 0.8（救援最强档），其余参数锁 θ₀。
RSR_BASE_SPE = 0.8


def coarse_vals(param):
    """粗跑取值：连续参数用 GRID_COARSE，离散参数用 DISCRETE。"""
    if param in GRID_COARSE:
        return GRID_COARSE[param]
    if param in DISCRETE:
        return DISCRETE[param]
    raise SystemExit(f"未知参数: {param}")


def fine_vals(param, lo, hi):
    """精跑取值：连续参数在 [lo,hi] 内按细档步长；离散参数原样返回。"""
    if param in GRID_FINE:
        kind, _, step = GRID_FINE[param]
        n = int(round((hi - lo) / step))
        return [round(lo + i * step, 4) for i in range(n + 1)] + ([hi] if abs(n * step - (hi - lo)) > 1e-9 else [])
    if param in DISCRETE:
        return DISCRETE[param]
    raise SystemExit(f"未知参数: {param}")


def run_single(eng, param, vals, out_path, verbose=True):
    """扫一个参数：逐个 evaluate，写 CSV，返回 (rows, best)。"""
    rows = []
    for v in vals:
        cfg = {param: v}
        if param == "rsr_rescue":
            cfg["spe_rescue"] = RSR_BASE_SPE   # rsr 与 spe 取 AND，需把 spe 顶起来
        res = eng.evaluate(cfg)
        row = {
            "param_value": v,
            "n_kept": res["n_kept"],
            "keep_hit": res["keep_hit"], "filt_hit": res["filt_hit"],
            "r000": res["r000"], "frag_hit": res["frag_hit"],
            "collateral": res["collateral"],
            "score_A": round(res["score"]["A"], 4),
            "score_B": round(res["score"]["B"], 4),
            "score_C": round(res["score"]["C"], 4),
        }
        rows.append(row)
        if verbose:
            print(f"  {param}={v!s:<7} {fmt(res)}")

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # 最优（按三套权重分别取）与敏感性
    bestA = max(rows, key=lambda r: r["score_A"])
    bestB = max(rows, key=lambda r: r["score_B"])
    bestC = max(rows, key=lambda r: r["score_C"])
    sens = lambda k: max(r[k] for r in rows) - min(r[k] for r in rows)
    return rows, {
        "param": param,
        "best_A": bestA["param_value"], "max_A": bestA["score_A"],
        "best_B": bestB["param_value"], "max_B": bestB["score_B"],
        "best_C": bestC["param_value"], "max_C": bestC["score_C"],
        "sens_A": round(sens("score_A"), 4),
        "sens_B": round(sens("score_B"), 4),
        "sens_C": round(sens("score_C"), 4),
    }


def main():
    ap = argparse.ArgumentParser(description="单参数敏感性（粗跑/精跑）")
    ap.add_argument("--param", default=None, help="指定参数；缺省跑全部 12 个粗跑")
    ap.add_argument("--lo", type=float, default=None, help="精跑下界")
    ap.add_argument("--hi", type=float, default=None, help="精跑上界")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    eng = Engine()

    if args.param:
        # 精跑：--lo/--hi 都给了 → 细档；否则粗跑该参数
        if args.lo is not None and args.hi is not None:
            vals = fine_vals(args.param, args.lo, args.hi)
            mode = f"精跑 [{args.lo},{args.hi}]"
        else:
            vals = coarse_vals(args.param)
            mode = "粗跑"
        print(f"== {args.param} {mode}（其余锁 θ₀）==")
        rows, summ = run_single(eng, args.param, vals,
                                os.path.join(args.out, f"{args.param}.csv"))
        print(f"\n最优: {args.param}={summ['best_A']} score_A={summ['max_A']:.4f} "
              f"敏感性ΔA={summ['sens_A']}")
        print(f"CSV: {os.path.join(args.out, args.param + '.csv')}")
        return 0

    # 全参数粗跑
    summary = []
    for param in list(GRID_COARSE.keys()) + list(DISCRETE.keys()):
        print(f"== {param} 粗跑（其余锁 θ₀）==")
        rows, summ = run_single(eng, param, coarse_vals(param),
                                os.path.join(args.out, f"{param}.csv"))
        summary.append(summ)

    # summary.csv + 敏感性排序（按 score_A）
    with open(os.path.join(args.out, "summary.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    print("\n===== 敏感性排序（score_A 跨度，越大越敏感）=====")
    for s in sorted(summary, key=lambda x: -x["sens_A"]):
        print(f"  {s['param']:<20} ΔA={s['sens_A']:<7} 最优={s['best_A']!s:<6} "
              f"scoreA={s['max_A']:.4f}")
    print(f"\nsummary: {os.path.join(args.out, 'summary.csv')}")
    print("提示：对 ΔA 较大的参数，用 --param X --lo L --hi H 精跑可疑区间。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
