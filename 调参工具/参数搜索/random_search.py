#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""random_search.py —— Phase 4 全局随机搜索（方案 §3.4）。

在合法参数域内均匀随机采样 N 个 θ，三套权重各评一遍，取每套 top5。
固定 seed 保证可复现。随机 top5 可作为 tune_diff 的重启种子（--start）。

采样网格化：连续参数只取细档网格上的值（mr 等因此是有限集，scan 缓存命中率高）；
离散参数从取值表随机。

用法：
    python random_search.py                # 默认 100 个样本
    python random_search.py -n 50 --seed 7
    python random_search.py --out DIR

输出：
    调参产物/random_top.json   每套权重 top5（含完整 cfg + score），可直接给 tune_diff --start
    调参产物/random_all.csv    全部样本 → 三套 score（供敏感性散点/交叉验证）
"""
import argparse
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune_engine import (BASE, DISCRETE, GRID_FINE, Engine, fine_grid)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = ["A", "B", "C"]

# 连续参数细档全集（采样池）
POOL = {p: fine_grid(p) for p in GRID_FINE}


def sample_cfg(rng):
    """随机生成一个合法配置（网格化采样）。"""
    cfg = dict(BASE)
    for p, vals in POOL.items():
        cfg[p] = rng.choice(vals)
    for p, vals in DISCRETE.items():
        cfg[p] = rng.choice(vals)
    # rsr 须配 spe：随机到 rsr>0 而 spe=0 时，把 spe 顶到 0.8
    if cfg["rsr_rescue"] > 0 and cfg["spe_rescue"] <= 0:
        cfg["spe_rescue"] = 0.8
    return cfg


def main():
    ap = argparse.ArgumentParser(description="全局随机搜索")
    ap.add_argument("-n", type=int, default=100, help="样本数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    eng = Engine()
    samples = []
    seen = set()
    while len(samples) < args.n:
        cfg = sample_cfg(rng)
        k = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        if k in seen:
            continue
        seen.add(k)
        res = eng.evaluate(cfg)
        samples.append({
            "cfg": cfg,
            "n_kept": res["n_kept"],
            "keep_hit": res["keep_hit"], "filt_hit": res["filt_hit"],
            "r000": res["r000"], "frag_hit": res["frag_hit"],
            "collateral": res["collateral"],
            "score": res["score"],
        })
        if (len(samples)) % 20 == 0:
            print(f"  采样 {len(samples)}/{args.n} ...", file=sys.stderr)

    # 全样本 CSV
    with open(os.path.join(args.out, "random_all.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["min_ent", "mr", "coh", "indep", "spe", "rsr", "bind",
                    "rsr_mode", "msc", "no_punct", "no_merge", "len",
                    "n_kept", "keep", "filt", "r000", "frag", "coll",
                    "A", "B", "C"])
        for s in samples:
            c = s["cfg"]
            w.writerow([c["min_ent"], c["ent_merge_ratio"], c["min_cohesion"],
                        c["min_indep"], c["spe_rescue"], c["rsr_rescue"],
                        c["bind_thresh"], c["rsr_mode"], c["min_super_cnt"],
                        c["no_punct_ent"], c["no_merge"], c["cohesion_max_len"],
                        s["n_kept"], s["keep_hit"], s["filt_hit"], s["r000"],
                        s["frag_hit"], s["collateral"],
                        round(s["score"]["A"], 4), round(s["score"]["B"], 4),
                        round(s["score"]["C"], 4)])

    # 每套权重 top5
    top = {}
    for w in WEIGHTS:
        ranked = sorted(samples, key=lambda s: -s["score"][w])[:5]
        top[w] = [{"cfg": r["cfg"], "score": round(r["score"][w], 4),
                   "n_kept": r["n_kept"], "r000": r["r000"],
                   "frag_hit": r["frag_hit"], "collateral": r["collateral"]}
                  for r in ranked]
        print(f"[{w}] top5:")
        for i, t in enumerate(top[w], 1):
            c = t["cfg"]
            print(f"  {i}. score={t['score']:.4f} 词数{t['n_kept']} 000真{t['r000']} "
                  f"碎片{t['frag_hit']} coll{t['collateral']} | "
                  f"me{c['min_ent']} mr{c['ent_merge_ratio']} coh{c['min_cohesion']} "
                  f"indep{c['min_indep']} spe{c['spe_rescue']} rsr{c['rsr_rescue']}")

    with open(os.path.join(args.out, "random_top.json"), "w", encoding="utf-8") as f:
        json.dump(top, f, ensure_ascii=False, indent=2)
    print(f"\n样本明细: {os.path.join(args.out, 'random_all.csv')}")
    print(f"top5: {os.path.join(args.out, 'random_top.json')}")
    print("重启用法: python 调参产物/tune_diff.py --weight A --start <top里的cfg另存为json>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
