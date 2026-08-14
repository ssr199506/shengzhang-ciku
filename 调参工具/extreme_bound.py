#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extreme_bound.py —— Phase 2 极端参数边界测试（方案 §3.2）。

对每个参数取极值（其余锁 θ₀），单独观察：
  1) 词数坍缩到多少（全滤阈值有多狠）；
  2) 是否出现异常（词数异常/分数为负/空表）；
  3) 极值下比 θ₀ 多删了哪些词（removed diff，按 count 降序，人工目检哪类先牺牲）。

目的：圈定**合法参数域**（后续差分搜索的硬边界），找出"危险区"。

用法：
    python extreme_bound.py                 # 全部极值
    python extreme_bound.py --out DIR       # 输出目录（默认 调参产物/extreme）

输出：
    extreme/extreme_report.csv   每个极值 → n_kept / 指标 / 异常标记
    extreme/removed_<param>.csv  该极值比 θ₀ 多删的词（word,count）
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune_engine import BASE, Engine, fmt

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extreme")

# 每个参数的"极端值"（取范围最狠的一端）
EXTREMES = [
    ("min_ent", 2.0),            # 熵门顶满 → 基本全滤
    ("min_cohesion", 10.0),      # 凝固度顶满 → 只留极高凝固词
    ("min_indep", 1.0),          # 偏序顶满 → 只留完全不包裹词
    ("spe_rescue", 2.0),         # SPE 救援顶满 → 只救位置多样极高词
    ("rsr_rescue", 50.0),        # RSR 顶满（须配 spe0.8）
    ("ent_merge_ratio", 0.9),    # 合并触发比顶满 → 几乎不合并
    ("bind_thresh", 0.5),        # 前后集中度门激活
    ("no_punct_ent", True),      # 关闭标点感知熵
    ("no_merge", True),          # 关闭合并模式
    ("cohesion_max_len", 4),     # 凝固度只算短词
]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="极端参数边界测试")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    eng = Engine()
    base = eng.evaluate({})
    base_kept = base["kept"]
    base_count = base["word_count"]

    rows = []
    print(f"{'极值':<26}{'词数':>6} {'keep':>4}{'filt':>4}{'000':>3}{'frag':>4}"
          f"{'coll':>5}  {'scoreA':>7}  异常标记")
    for param, val in EXTREMES:
        cfg = {param: val}
        if param == "rsr_rescue":
            cfg["spe_rescue"] = 0.8
        try:
            res = eng.evaluate(cfg)
        except Exception as e:  # noqa
            print(f"  {param}={val!s:<18} 异常崩溃: {e}")
            rows.append({"param": param, "value": val, "n_kept": "CRASH", "note": str(e)})
            continue

        # 异常标记：词数坍缩比例 / 分数
        shrunk = res["n_kept"] / base["n_kept"]
        flag = ""
        if res["n_kept"] == 0:
            flag = "⚠️ 空表"
        elif shrunk < 0.3:
            flag = f"⚠️ 坍缩{shrunk:.0%}"
        elif shrunk < 0.7:
            flag = f"坍缩{shrunk:.0%}"
        elif shrunk > 1.15:
            flag = f"膨胀{shrunk:.0%}"

        # removed diff：极值 kept − 基线 kept 被删的词（含 count）
        removed = sorted((w for w in base_kept if w not in res["kept"]),
                         key=lambda x: -base_count.get(x, 0))
        with open(os.path.join(args.out, f"removed_{param}.csv"), "w",
                  encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["word", "count"])
            for word in removed[:200]:
                w.writerow([word, ""])
        n_removed = len(removed)

        print(f"  {param}={val!s:<18}{res['n_kept']:>6} "
              f"{res['keep_hit']:>4}{res['filt_hit']:>4}{res['r000']:>3}"
              f"{res['frag_hit']:>4}{res['collateral']:>5}"
              f"{res['score']['A']:>8.4f}  {flag:>10} 删{n_removed}")
        rows.append({
            "param": param, "value": val, "n_kept": res["n_kept"],
            "keep_hit": res["keep_hit"], "filt_hit": res["filt_hit"],
            "r000": res["r000"], "frag_hit": res["frag_hit"],
            "collateral": res["collateral"],
            "score_A": round(res["score"]["A"], 4),
            "n_removed": n_removed, "flag": flag,
        })

    with open(os.path.join(args.out, "extreme_report.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n报告: {os.path.join(args.out, 'extreme_report.csv')}")
    print("removed_*.csv 是被删词清单（前 200），人工目检哪类词先牺牲。")
    print("判断：flag 为 ⚠️ 的值所在参数 → 合法域该端是危险区，差分搜索时 clamp 在这里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
