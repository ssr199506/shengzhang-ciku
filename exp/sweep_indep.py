#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立率保护阈值扫描：对每个阈值跑一次，算救回数 + 金标准 score，确认是否有用。"""
import os, sys, csv, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
GROW = os.path.join(ROOT, "grow.py")

SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记",
               "无限恐怖","鬼灭","苟在","之主","之王","世界","长生","凡人","修仙",
               "都市","系统","巅峰","重生之","人在木叶","全职法师","风云","无敌",
               "直播","网游","神豪","荒古","重生","战神","天才","玄幻","末世",
               "奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之",
                 "星空之","火影开","无限之","诸天之","之巅","之神","之子","之魂",
                 "之开","罗之","世主","生仙","人在斗","影开始","局被","后一","的悠"]


def load(p):
    return {r["word"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


def run(th):
    out = os.path.join(HERE, f"indep_sweep_{th}")
    subprocess.run([sys.executable, GROW, CSV, "--title-col", "2", "--out", out,
                    "--no-cloud", "--min-ent", "0.5", "--ent-merge-ratio", "0.25",
                    "--indep-ratio", str(th)], check=True, capture_output=True)
    return load(os.path.join(out, "title_wordfreq.csv"))


base = run(0.0)   # 无保护 = 基线
print(f"基线(无保护) 词数={len(base)}")
print(f"{'阈值':>6} {'词数':>6} {'救回':>6} {'keep':>5} {'filt':>5} {'score':>6}  救回的应滤词")
for th in [0.25, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 1.0]:
    prot = run(th)
    rescued = prot - base
    keep = sum(1 for w in SHOULD_KEEP if w in prot)
    filt = sum(1 for w in SHOULD_FILTER if w not in prot)
    score = 0.5*keep/len(SHOULD_KEEP) + 0.5*filt/len(SHOULD_FILTER)
    bad = [w for w in rescued if w in SHOULD_FILTER]
    print(f"{th:>6.2f} {len(prot):>6d} {len(rescued):>6d} {keep:>2d}/{len(SHOULD_KEEP)} {filt:>2d}/{len(SHOULD_FILTER)} {score:>6.3f}  {bad}")
