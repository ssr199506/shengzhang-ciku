#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比 exp/golden 各关键版本输出数据（纯读 CSV，不依赖语料，无敏感风险）。

版本链（按 golden 谱系）：
    raw 7150 ──ent门──► ent 5865 ──coh门──► coh 5156 ──indep门──► indep 5149
    ent 5865 ──spe救援──► spe 5895 ──rsr收紧──► rsr 5889

产出：stdout + exp/golden_diff_report.txt（word 集合差集全量，可 grep 单个词在哪级被滤/被救）。

用法： python exp/compare_golden.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden")
OUT = os.path.join(HERE, "golden_diff_report.txt")

# 版本名 -> golden 文件（按管线顺序）
VERSIONS = [
    ("raw",   "v211_raw_7150.csv"),
    ("ent",   "v211_ent_5865.csv"),
    ("coh",   "v217_cohesion_5156.csv"),
    ("indep", "v233_indep_5149.csv"),
    ("spe",   "v241_spe_5895.csv"),
    ("rsr",   "v242_rsr_5889.csv"),
]


def load(path):
    words = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if row:
                words[row[0]] = int(row[1])
    return words


def main():
    lines = []
    add = lines.append
    add("=" * 62)
    add("关键版本输出数据对比（exp/golden，只读）")
    add("=" * 62)
    add("版本词数：")
    sets = {}
    for name, fn in VERSIONS:
        sets[name] = load(os.path.join(GOLDEN, fn))
        add(f"  {name:6s} {fn:28s} {len(sets[name])} 词")

    # 横向外部链：ent 门（raw→ent）、coh 门（ent→coh）、indep 门（coh→indep）
    add("\n[过滤链] 被各闸门滤除的词（前级保留→本级删）")
    for a, b, label in [("raw", "ent", "复合熵门"), ("ent", "coh", "凝固度门"),
                        ("coh", "indep", "词本身偏序门")]:
        removed = sorted(set(sets[a]) - set(sets[b]))
        add(f"  {a}({len(sets[a])}) → {b}({len(sets[b])})  {label}: 删 {len(removed)} 词")
        for w in removed:
            add(f"      - {w} (count={sets[a][w]})")

    # 纵向救援链：spe 救援（ent→spe）、rsr 收紧（spe→rsr）
    add("\n[救援链] 从被滤集捞回/再收紧的词")
    rescued = sorted(set(sets["spe"]) - set(sets["ent"]))
    add(f"  ent({len(sets['ent'])}) → spe({len(sets['spe'])})  SPE 救援: 捞回 {len(rescued)} 词")
    for w in rescued:
        add(f"      + {w} (count={sets['spe'][w]})")
    tightened = sorted(set(sets["spe"]) - set(sets["rsr"]))
    add(f"  spe({len(sets['spe'])}) → rsr({len(sets['rsr'])})  RSR 收紧: 再删 {len(tightened)} 词")
    for w in tightened:
        add(f"      - {w} (count={sets['spe'][w]})")

    # 与 GOLDEN_MANIFEST 关键不变量对照（硬断言）
    add("\n[不变量校验]")
    checks = [
        ("原始候选集恒 7150", len(sets["raw"]) == 7150),
        ("indep 联合门删 7 词", sorted(set(sets["coh"]) - set(sets["indep"])) ==
         sorted(["界的", "游之", "真不", "我只", "我真不", "我真", "是大"])),
        ("SPE 救援捞回 30（ent→spe）", len(rescued) == 30),
        ("RSR 救援捞回 24（ent→rsr）", len(set(sets["rsr"]) - set(sets["ent"])) == 24),
        ("RSR 收紧挡 6 词（spe→rsr）", len(tightened) == 6),
    ]
    all_ok = True
    for desc, ok in checks:
        add(f"  {'PASS' if ok else 'FAIL'}  {desc}")
        all_ok = all_ok and ok
    add("=" * 62)
    add(f"结果: {'ALL PASS' if all_ok else 'FAILURE'}")

    text = "\n".join(lines) + "\n"
    print(text)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[compare_golden] 报告已保存: {OUT}", file=sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
