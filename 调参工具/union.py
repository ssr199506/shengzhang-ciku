# -*- coding: utf-8 -*-
# 全量逐档交并统计：读 13 版词表 -> 算交集/并集/增删/碎片 -> 输出汇总
import csv, os, sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
DIRS = ["base","coh1.0","coh2.0","coh3.5","indep0","indep0.03","indep0.1",
        "ent0.3","ent0.7","mr0.1","mr0.5","mr0.85","spe0.8"]

def load_words(label):
    p = os.path.join(ROOT, label, "title_wordfreq.csv")
    words = {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if i == 0 or not r:          # 跳过表头/空行
                continue
            words[r[0]] = int(r[1])       # 词 -> 频次
    return words

allw = {lab: load_words(lab) for lab in DIRS}
base_w = set(allw["base"])

# 1) 每版词数
print("== 各档词数 ==")
for lab in DIRS:
    print("  %-10s %5d 词" % (lab, len(allw[lab])))

# 2) 共识交集（13 版全部保留）= 最稳定的词
cons = set.intersection(*(set(v) for v in allw.values()))
print("== 交并 ==")
print("  13 版共识交集(全部保留): %d 词" % len(cons))

# 3) 每档相对基准的增/删
print("== 相对基准(base)的增删 ==")
for lab in DIRS[1:]:
    s = set(allw[lab])
    add = s - base_w
    rem = base_w - s
    print("  %-10s +%4d  -%4d" % (lab, len(add), len(rem)))

# 4) 碎片命中（人工标注的句法碎片，检查哪些档把它们放进来/滤掉）
FRAG = ["我的","这个","什么","成了","我是","我在","人在","重生之",
        "我只","联盟之","罗之","之我","世界之","是我","的我","之神"]
print("== 碎片命中（越少越好）==")
for lab in DIRS:
    s = set(allw[lab])
    hit = [w for w in FRAG if w in s]
    print("  %-10s %2d/16 %s" % (lab, len(hit), " ".join(hit)))

# 5) 导出汇总 CSV
with open(os.path.join(ROOT, "union_summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["档名", "词数", "相对基准新增", "相对基准删除", "碎片命中数"])
    for lab in DIRS:
        s = set(allw[lab])
        w.writerow([lab, len(s), len(s - base_w), len(base_w - s),
                    len([x for x in FRAG if x in s])])
print("== 已输出 union_summary.csv ==")
