#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：打印指定词在 title 语料中的左右邻居分布 + 复合熵，验证 2.1.7 豁免逻辑。"""
import sys, csv, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grow

# 语料为付费商用数据，不入库：请将语料命名为 corpus.csv 置于仓库根
CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus.csv")

TITLE_COL = 2
rows = list(csv.reader(open(CSV, encoding="utf-8-sig", newline="")))
rows = [r for r in rows if r and r[TITLE_COL].strip()]
# 复制 main 的 dedup + clean
from collections import Counter
dedup = Counter([(r[TITLE_COL].strip(), "") for r in rows])
title_docs = [(grow.clean(t, True), w) for (t, _), w in dedup.items() if t]
S, wgt = grow.build_corpus(title_docs)

# 直接复用内部分布函数：通过 monkey 取 left_dist/right_dist
# scan_and_grow 内部有 left_dist/right_dist；我们手动重算子集分布
import re
PUNCT = grow.PUNCT
SEP = grow.SEP

def neighbors(w):
    # 在所有 run 中找 w 出现位置的左右字符
    left = Counter(); right = Counter()
    # 用 S 字符串搜索
    i = 0
    nl = len(S)
    while True:
        j = S.find(w, i)
        if j < 0: break
        # 左
        lc = S[j-1] if j-1 >= 0 else SEP  # 首字符视作 SEP
        rc = S[j+len(w)] if j+len(w) < nl else SEP
        left[lc] += 1
        right[rc] += 1
        i = j + 1
    return left, right

words = ["一个人","一生","万族","三国战","三清","万里","万妖之祖","一世之尊",
         "长生修仙","吞噬星空","之主","之王","重生之","世界","长生"]
print(f"S len={len(S)}, runs={S.count(SEP)+1}")
for w in words:
    if w not in S:
        print(f"\n[{w}] 不在 title 语料中"); continue
    L, R = neighbors(w)
    # 分类
    def cls(c): return "PUNCT" if c==PUNCT else ("SEP" if c==SEP else c)
    Lc = {cls(k): v for k,v in L.items()}
    Rc = {cls(k): v for k,v in R.items()}
    realL = {k:v for k,v in Lc.items() if k not in ("PUNCT","SEP")}
    realR = {k:v for k,v in Rc.items() if k not in ("PUNCT","SEP")}
    exempt = (not realL) and (not realR)
    print(f"\n[{w}] total={sum(L.values())} | exempt(纯独立)={exempt}")
    print(f"   left : {dict(sorted(Lc.items(), key=lambda x:-x[1]))}")
    print(f"   right: {dict(sorted(Rc.items(), key=lambda x:-x[1]))}")
