#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凝固度(2.1.17-cohesion) 双信号评估：
   复现 title 管线(起点CSV --title-col 2, 标点熵开)，跑一次 scan_and_grow 拿到
   (word, count, independent, bind, ent, cohesion) 全量候选，再对 --cohesion 各阈值
   套用「熵闸门 AND 凝固度闸门」复算留存集，对比金标准词集打分。

   用法: python exp/cmp_cohesion.py [--min-ent 0.5] [--cohesion 0.0 0.5 1.0 ...]
"""
import os, sys, csv, math, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grow

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(os.path.dirname(HERE),
                   "PAID_CORPUS.csv")

# 金标准（与 cmp_posfixed 一致）：应留 37 / 应滤 25
SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记","无限恐怖",
    "鬼灭","苟在","之主","之王","世界","长生","凡人","修仙","都市","系统","巅峰","重生之",
    "人在木叶","全职法师","风云","无敌","直播","网游","神豪","荒古","重生","战神","天才",
    "玄幻","末世","奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之","星空之",
    "火影开","无限之","诸天之","之巅","之神","之子","之魂","之开","罗之","世主","生仙",
    "人在斗","影开始","局被","后一","的悠"]

WATCH = ["之巅","之神","之子","我只","诸天之","联盟之","聊天","人在斗","我能","什么鬼",
    "一人之下","吞噬星空","完美世界","重燃","首富","明月","康熙","从零","长生修仙","剑修"]


def build_title():
    docs = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        rows = []
        for i, r in enumerate(rd):
            if not r:
                continue
            if i == 0 and grow.detect_header(r, 2, 1):
                continue
            title = r[2].strip() if len(r) > 2 else ""
            rows.append(title)
    dedup = {}
    for t in rows:
        if t:
            dedup[t] = dedup.get(t, 0) + 1
    return [(grow.clean(t, True), w) for t, w in dedup.items() if t]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ent", type=float, default=0.5)
    ap.add_argument("--ent-merge-ratio", type=float, default=0.25)
    ap.add_argument("--cohesion", type=float, nargs="*",
                    default=[0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0])
    args = ap.parse_args()

    docs = build_title()
    S, wgt = grow.build_corpus(docs)
    cands, _ = grow.scan_and_grow(S, wgt, args.ent_merge_ratio, True)

    def apply(min_ent, min_coh):
        out = []
        for c in cands:
            _, cnt, ind, bind, ent, coh = c
            if ind < 1 or len(c[0]) < 2:
                if len(c[0]) < 2:
                    continue  # 单字不入候选（scan 已保证，这里双保险）
            if min_ent > 0 and not (ent < 0 or ent >= min_ent):
                continue
            if min_coh > 0 and len(c[0]) >= 2 and coh < min_coh:
                continue
            out.append(c)
        return out

    print(f"全量候选词(去重, ind>=1, len>=2): {len(cands)}   min_ent={args.min_ent}\n")
    # 校准：打印 WATCH 词的 (熵, 凝固度)
    wc = {c[0]: c for c in cands}
    print("=== 关键词 校准 (count, 独立率, 熵, 凝固度) ===")
    for w in WATCH:
        if w in wc:
            _, cnt, ind, bind, ent, coh = wc[w]
            print(f"  {w:8s} cnt={cnt:>5} ind={ind:>5} ({100*ind/cnt:4.1f}%) 熵={ent:5.2f} 凝聚={coh:6.2f}")
    print()

    print("=== 凝固度阈值扫描 (熵闸门固定 me=%.2f) ===" % args.min_ent)
    print(f"{'coh_thr':>8} {'保留':>6} {'keep':>6} {'filt':>6} {'score':>6}  漏滤(应滤却留)/漏留")
    base_kept = set(c[0] for c in apply(args.min_ent, 0.0))
    for thr in args.cohesion:
        kept = apply(args.min_ent, thr)
        ks = set(c[0] for c in kept)
        kb = sum(w in ks for w in SHOULD_KEEP)
        fb = sum(w not in ks for w in SHOULD_FILTER)
        score = 0.5 * kb / len(SHOULD_KEEP) + 0.5 * fb / len(SHOULD_FILTER)
        leaked = [w for w in SHOULD_FILTER if w in ks]
        print(f"{thr:>8.2f} {len(kept):>6} {kb:>4}/{len(SHOULD_KEEP)} {fb:>4}/{len(SHOULD_FILTER)} {score:>6.3f}  "
              f"漏滤={leaked}")
    print()
    # 与基线(纯熵, me0.5)对比的增量词（coh=1.0 为例）
    for demo in [1.0]:
        ks = set(c[0] for c in apply(args.min_ent, demo))
        added = ks - base_kept
        removed = base_kept - ks
        print(f"--- coh={demo} 相对 纯熵基线(me0.5) 的增量 ---")
        print(f"  新增({len(added)}): " + ", ".join(sorted(added, key=lambda x:-wc[x][1])[:30]))
        print(f"  减少({len(removed)}): " + ", ".join(sorted(removed, key=lambda x:-wc[x][1])[:30]))


if __name__ == "__main__":
    main()
