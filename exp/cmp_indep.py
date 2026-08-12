#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比 独立率保护(0.25) 开启前后：救回哪些词，是否有用。
用法： python exp/cmp_indep.py
"""
import os, csv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BASE = os.path.join(HERE, "indep_base", "title_wordfreq.csv")
PROT = os.path.join(HERE, "indep_025", "title_wordfreq.csv")

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

rescued = prot_w - base_w          # 保护救回的词
killed  = base_w - prot_w          # 理论不应有（保护只增不减）

print("=" * 72)
print("总体规模")
print("=" * 72)
print(f"基线(无保护) title 词数:   {len(base_w)}")
print(f"保护(0.25)  title 词数:   {len(prot_w)}")
print(f"独立率保护救回:            {len(rescued)} 词")
print(f"保护反向删掉(应为0):       {len(killed)} 词")

# 救回词的独立率分布
print("\n" + "=" * 72)
print("救回词的独立率分布")
print("=" * 72)
rows = []
for w in rescued:
    r = prot[w]
    cnt = int(r["count"]); ind = int(r["independent"])
    ratio = ind / cnt if cnt else 0
    rows.append((ratio, w, cnt, ind, float(r["compound_entropy"])))
rows.sort(reverse=True)
buckets = {"≥0.8":0,"0.5–0.8":0,"0.25–0.5":0}
for ratio, w, cnt, ind, ent in rows:
    if ratio >= 0.8: buckets["≥0.8"] += 1
    elif ratio >= 0.5: buckets["0.5–0.8"] += 1
    else: buckets["0.25–0.5"] += 1
print("独立率区间:", buckets)
print("\n救回词清单（按独立率降序）：独立率  词  count  ind  复合熵")
for ratio, w, cnt, ind, ent in rows:
    print(f"  {ratio*100:5.1f}%  {w:10s} {cnt:5d} {ind:5d}  {ent:.3f}")

# 金标准评估
print("\n" + "=" * 72)
print("金标准评估（title 管线）")
print("=" * 72)
keep_in_base = [w for w in SHOULD_KEEP if w in base_w]
filt_in_base = [w for w in SHOULD_FILTER if w not in base_w]
keep_in_prot = [w for w in SHOULD_KEEP if w in prot_w]
filt_in_prot = [w for w in SHOULD_FILTER if w not in prot_w]
base_score = 0.5*len(keep_in_base)/len(SHOULD_KEEP) + 0.5*len(filt_in_base)/len(SHOULD_FILTER)
prot_score = 0.5*len(keep_in_prot)/len(SHOULD_KEEP) + 0.5*len(filt_in_prot)/len(SHOULD_FILTER)
print(f"基线   keep {len(keep_in_base)}/{len(SHOULD_KEEP)}  filt {len(filt_in_base)}/{len(SHOULD_FILTER)}  score={base_score:.3f}")
print(f"保护   keep {len(keep_in_prot)}/{len(SHOULD_KEEP)}  filt {len(filt_in_prot)}/{len(SHOULD_FILTER)}  score={prot_score:.3f}")

rescued_gold_filter = [w for w in rescued if w in SHOULD_FILTER]
rescued_gold_keep   = [w for w in rescued if w in SHOULD_KEEP]
print(f"\n救回词中属于【应滤词(金标准)】的(坏救): {len(rescued_gold_filter)} -> {rescued_gold_filter}")
print(f"救回词中属于【应留词(金标准)】的(好救): {len(rescued_gold_keep)} -> {rescued_gold_keep}")
# 救回但既非应留也非应滤（灰色，需人工判断）
gray = [w for w in rescued if w not in SHOULD_FILTER and w not in SHOULD_KEEP]
print(f"救回的灰色词(非金标准): {len(gray)}")
# 在灰色词里挑出明显寄生模板（之X / X开始 / 我能类）
import re
parasite_pat = re.compile(r'^(.之.?|.+开始|我能|什么鬼|人在斗罗|从.+开始)$')
parasitic_gray = [w for w in gray if parasite_pat.match(w)]
print(f"  其中明显寄生模板(之X/开始/我能类): {len(parasitic_gray)} -> {parasitic_gray[:40]}")
free_gray = [w for w in gray if not parasite_pat.match(w)]
print(f"  其中看起来像自由词: {len(free_gray)} -> {free_gray[:40]}")
