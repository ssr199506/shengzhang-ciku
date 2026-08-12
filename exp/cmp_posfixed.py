#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比 位置固定度豁免(2.1.16, --pos-fixed 0.85) 开启前后。
基线 = 同管线 --pos-fixed 0（纯 main 行为）。
用法： python exp/cmp_posfixed.py
"""
import os, csv

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base_pf0", "title_wordfreq.csv")
PROT = os.path.join(HERE, "posfixed_085", "title_wordfreq.csv")

SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记",
               "无限恐怖","鬼灭","苟在","之主","之王","世界","长生","凡人","修仙",
               "都市","系统","巅峰","重生之","人在木叶","全职法师","风云","无敌",
               "直播","网游","神豪","荒古","重生","战神","天才","玄幻","末世",
               "奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之",
                 "星空之","火影开","无限之","诸天之","之巅","之神","之子","之魂",
                 "之开","罗之","世主","生仙","人在斗","影开始","局被","后一","的悠"]


def load(p):
    return {r["word"]: r for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


base = load(BASE)
prot = load(PROT)
base_w = set(base)
prot_w = set(prot)

rescued = prot_w - base_w
killed = base_w - prot_w

print("=" * 72)
print("总体规模 (title 管线, me0.5 + mr0.25)")
print("=" * 72)
print(f"基线(--pos-fixed 0) 词数:   {len(base_w)}")
print(f"豁免(--pos-fixed 0.85) 词数: {len(prot_w)}")
print(f"位置固定度救回:             {len(rescued)} 词")
print(f"豁免反向删掉(应为0):        {len(killed)} 词")

print("\n" + "=" * 72)
print("金标准评估")
print("=" * 72)
kb = sum(w in base_w for w in SHOULD_KEEP); fb = sum(w not in base_w for w in SHOULD_FILTER)
kp = sum(w in prot_w for w in SHOULD_KEEP); fp = sum(w not in prot_w for w in SHOULD_FILTER)
sb = 0.5*kb/len(SHOULD_KEEP) + 0.5*fb/len(SHOULD_FILTER)
sp = 0.5*kp/len(SHOULD_KEEP) + 0.5*fp/len(SHOULD_FILTER)
print(f"基线   keep {kb}/{len(SHOULD_KEEP)}  filt {fb}/{len(SHOULD_FILTER)}  score={sb:.3f}")
print(f"豁免   keep {kp}/{len(SHOULD_KEEP)}  filt {fp}/{len(SHOULD_FILTER)}  score={sp:.3f}")

rescued_keep = [w for w in rescued if w in SHOULD_KEEP]
rescued_filt = [w for w in rescued if w in SHOULD_FILTER]
gray = [w for w in rescued if w not in SHOULD_KEEP and w not in SHOULD_FILTER]
print(f"\n救回词中【应留词(金标准)】(好救): {len(rescued_keep)} -> {rescued_keep}")
print(f"救回词中【应滤词(金标准)】(坏救): {len(rescued_filt)} -> {rescued_filt}")
print(f"救回的灰色词(非金标准): {len(gray)}")

print("\n" + "=" * 72)
print("关键个案核查")
print("=" * 72)
for w in ["什么鬼","一人之下","我能","首富","聊天","联盟之","苟在","诸天之"]:
    in_b = w in base_w; in_p = w in prot_w
    row = prot.get(w) or base.get(w)
    ent = row["compound_entropy"] if row else "—"
    print(f"  {w:8s} 基线={'保留' if in_b else '滤除':<4s}  豁免={'保留' if in_p else '滤除':<4s}  复合熵={ent}")
