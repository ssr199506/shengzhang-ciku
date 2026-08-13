#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复合熵调参：--min-ent × --ent-merge-ratio 网格，与基线(out_real)对比。
产出 exp/tune/<name>/title_wordfreq.csv，并按金标准词集量化评估，给出建议参数。

用法： python exp/tune_params.py
"""
import os
import sys
import csv
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
# 语料为付费商用数据，不入库：请将语料命名为 corpus.csv 置于仓库根
CSV = os.path.join(ROOT, "corpus.csv")
TUNE = os.path.join(HERE, "tune")

MIN_ENTS = [0.3, 0.5, 0.7, 0.9, 1.1]
MERGES = [0.10, 0.20, 0.30]

# 金标准词集（用户明确确认过）
SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记",
               "无限恐怖","鬼灭","苟在","之主","之王","世界","长生","凡人","修仙",
               "都市","系统","巅峰","重生之","人在木叶","全职法师","风云","无敌",
               "直播","网游","神豪","荒古","重生","战神","天才","玄幻","末世",
               "奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之",
                 "星空之","火影开","无限之","诸天之","之巅","之神","之子","之魂",
                 "之开","罗之","世主","生仙","人在斗","影开始","局被","后一","的悠"]


def load(out):
    p = os.path.join(out, "title_wordfreq.csv")
    if not os.path.exists(p):
        return None
    return {r["word"]: r for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


def run_one(name, min_ent, merge):
    out = os.path.join(TUNE, name)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    cmd = [sys.executable, os.path.join(ROOT, "grow.py"), CSV,
           "--title-col", "2", "--out", out, "--no-cloud",
           "--min-ent", str(min_ent), "--bind", "1.0",
           "--ent-merge-ratio", str(merge)]
    subprocess.run(cmd, check=True, capture_output=True)
    return load(out)


def main():
    base = load(os.path.join(ROOT, "out_real"))  # 基线词集（用于确定金标准词是否真实存在）
    base_words = set(base)
    keep_gold = [w for w in SHOULD_KEEP if w in base_words]
    filt_gold = [w for w in SHOULD_FILTER if w in base_words]
    print(f"金标准：应保留 {len(keep_gold)} 词 / 应滤除 {len(filt_gold)} 词")
    print(f"基线词数: {len(base_words)}")
    print("=" * 78)

    results = []
    for me in MIN_ENTS:
        for mr in MERGES:
            name = f"me{me}_mr{mr}"
            d = run_one(name, me, mr)
            if d is None:
                print(f"{name:18s} 运行失败"); continue
            kept_set = set(d)
            keep_hit = sum(1 for w in keep_gold if w in kept_set)
            filt_hit = sum(1 for w in filt_gold if w not in kept_set)
            keep_rate = keep_hit / len(keep_gold)
            filt_rate = filt_hit / len(filt_gold)
            score = 0.5 * keep_rate + 0.5 * filt_rate
            removed = len(base_words - kept_set)
            # 被滤词中 count>=5 且非金标准滤除词的（疑似误伤，粗略）
            collateral = [w for w in (base_words - kept_set)
                          if int(base[w].get("count", 0)) >= 5 and w not in set(filt_gold)]
            results.append((name, me, mr, len(kept_set), removed,
                            keep_hit, filt_hit, keep_rate, filt_rate, score,
                            len(collateral), collateral[:8]))
            print(f"{name:18s} 词数{len(kept_set):>5d} 滤{removed:>5d} "
                  f"keep{keep_hit:>2d}/{len(keep_gold)} filt{filt_hit:>2d}/{len(filt_gold)} "
                  f"score={score:.3f} 疑似误伤≥5次:{len(collateral)}")

    print("=" * 78)
    print("按综合分排序 top8（score=0.5*keep保留率 + 0.5*filt滤除率）：")
    for name, me, mr, n, rm, kh, fh, kr, fr, sc, cl, sample in sorted(
            results, key=lambda x: -x[9])[:8]:
        print(f"  {name:18s} score={sc:.3f} (keep {kr:.2f} / filt {fr:.2f}) "
              f"词数{n} 滤{rm} 疑似误伤≥5次:{cl} {sample[:5]}")


if __name__ == "__main__":
    main()
