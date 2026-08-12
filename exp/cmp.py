#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验对比器：读取 exp/<name>/title_wordfreq.csv，产出调参报告。
  - 配置概览（各配置词数、相对 baseline 的过滤量）
  - 探针词矩阵（每个配置下 ✓保留/✗过滤，括号标注 compound_entropy）
  - 指定阈值配置的质量检查：被滤词中熵最低 topN（最寄生）、保留词中熵最高 topN
  - baseline 的复合熵直方图（选阈值用）

用法：
    python exp/cmp.py                # 默认对 me_0.5 做质量检查
    python exp/cmp.py me_1.0         # 改对 me_1.0 做质量检查
    python exp/cmp.py --probe 之下,界的,重生之   # 自定义探针词（逗号分隔）
"""
import os
import sys
import csv
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = HERE

PROBES = [
    # 寄生/词缀型（期望被滤）
    "之主", "之王", "之巅", "之神", "之子", "之魂", "界王", "界主",
    "我能", "我真不", "苟在", "剑修", "剑客", "说好", "重生", "重活",
    # 自由词（期望保留）
    "重生之", "开局", "世界", "长生", "一人之下", "都市", "系统", "巅峰",
    "风云", "无敌", "直播", "网游", "神豪", "荒古",
    # 常见单/双字
    "之", "界", "王", "神", "仙", "道",
]

ORDER = ["baseline", "punct_off", "me_0.3", "me_0.5", "me_0.8",
         "me_1.0", "me_1.5", "me_2.0", "bind_0.7", "bind_0.5"]


def load_title(name):
    p = os.path.join(EXP, name, "title_wordfreq.csv")
    if not os.path.exists(p):
        return None
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    h = rows[0]
    idx = {x: i for i, x in enumerate(h)}
    words = {}
    for r in rows[1:]:
        if not r:
            continue
        w = r[idx["word"]]
        words[w] = {
            "ent": float(r[idx["compound_entropy"]]),
            "cnt": int(r[idx["count"]]),
            "bind": float(r[idx["bind"]]),
            "ind": int(r[idx["independent"]]),
        }
    return words


def discover():
    found = []
    for d in sorted(os.listdir(EXP)):
        if os.path.isdir(os.path.join(EXP, d)) and glob.glob(os.path.join(EXP, d, "*_wordfreq.csv")):
            found.append(d)
    # 按 ORDER 优先排序，其余按名
    return sorted(found, key=lambda x: (ORDER.index(x) if x in ORDER else 999, x))


def fmt_ent(e):
    if e == -1.0:
        return "-1.0"
    return f"{e:.2f}"


def main():
    args = sys.argv[1:]
    quality_cfg = "me_0.5"
    probes = PROBES
    if args and not args[0].startswith("--"):
        quality_cfg = args[0]
    for a in args:
        if a.startswith("--probe="):
            probes = [x for x in a.split("=", 1)[1].split(",") if x]

    configs = discover()
    data = {c: load_title(c) for c in configs}
    baseline = data.get("baseline") or next((data[c] for c in configs if data[c]), {})
    base_name = "baseline" if "baseline" in data else (configs[0] if configs else "?")

    # ---------- 配置概览 ----------
    print("=" * 70)
    print("配置概览（title，词数 / 相对 baseline 过滤量）")
    print("=" * 70)
    print(f"{'config':12s} {'words':>7s} {'removed':>9s}")
    base_n = len(baseline)
    for c in configs:
        d = data[c]
        if d is None:
            print(f"{c:12s}   (缺失)")
            continue
        rem = len(baseline) - len(d) if c != base_name else 0
        rem_s = f"-{rem}" if rem else "-"
        print(f"{c:12s} {len(d):>7d} {rem_s:>9s}")

    # ---------- 探针词矩阵 ----------
    print("\n" + "=" * 70)
    print("探针词矩阵（✓保留 / ✗过滤；括号=compound_entropy，取自未过滤基线）")
    print("=" * 70)
    header = "word".ljust(10) + "".join(c[:9].rjust(10) for c in configs)
    print(header)
    for w in probes:
        # 取该词在各配置中的熵：优先该配置自身（punct_off 等），否则退化到 baseline
        cells = []
        for c in configs:
            d = data[c]
            if d is None:
                cells.append("  ?".rjust(10))
                continue
            kept = w in d
            # 熵：该配置若有则用之，否则用 baseline 的（标点感知组熵一致）
            e = d.get(w, {}).get("ent")
            if e is None:
                e = baseline.get(w, {}).get("ent")
            es = fmt_ent(e) if e is not None else "?"
            cells.append(f"{es}{'✓' if kept else '✗'}".rjust(10))
        print(w.ljust(10) + "".join(cells))

    # ---------- 质量检查（指定阈值配置） ----------
    if quality_cfg in data and data[quality_cfg] is not None:
        dq = data[quality_cfg]
        print("\n" + "=" * 70)
        print(f"质量检查 @ {quality_cfg}（被滤/保留相对 {base_name}）")
        print("=" * 70)
        removed = [(w, baseline[w]["ent"], baseline[w]["cnt"])
                   for w in baseline if w not in dq]
        removed.sort(key=lambda x: (x[1], -x[2]))
        print(f"-- 被滤词中 熵最低 top15（最像寄生/词缀）--")
        print(" | ".join(f"{w} {fmt_ent(e)}(n{c})" for w, e, c in removed[:15]))
        kept = [(w, baseline[w]["ent"], baseline[w]["cnt"])
                for w in dq if w in baseline]
        kept.sort(key=lambda x: -x[1])
        print(f"-- 保留词中 熵最高 top15（最自由，确认未误伤）--")
        print(" | ".join(f"{w} {fmt_ent(e)}(n{c})" for w, e, c in kept[:15]))

    # ---------- 熵直方图（baseline） ----------
    print("\n" + "=" * 70)
    print(f"复合熵直方图 @ {base_name}（选阈值参考；-1.0 单独计）")
    print("=" * 70)
    buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8),
               (0.8, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99)]
    neg = sum(1 for v in baseline.values() if v["ent"] == -1.0)
    print(f"[-1.0 豁免] {neg}")
    for lo, hi in buckets:
        n = sum(1 for v in baseline.values() if lo <= v["ent"] < hi)
        bar = "#" * (n // 20)
        print(f"[{lo:.1f},{hi if hi < 90 else '∞':>3}] {n:>5d} {bar}")


if __name__ == "__main__":
    main()
