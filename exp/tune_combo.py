#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组合态联合调参：ent+coh+indep+spe 全网格（一次扫描多配置，秒级）。

质疑背景：之前只扫了 spe，组合态下 coh/indep 沿用历史定档未重调。
本脚本在 grow3 面板上做 **联合网格**（一次 scan_once 复用，逐 cfg 只算所需信号）：

  coh  ∈ {0.0(关), 1.0, 1.5, 2.0}
  indep∈ {0.0(关), 0.03, 0.05, 0.10}
  spe  ∈ {0.0(关), 0.6, 0.8, 1.0}
  固定 me0.5 + mr0.25（历史定档），共 63 组合（去全关）。

评估口径（两套合并）：
  A. tune_params 历史口径：SHOULD_KEEP(40) 保留率 + SHOULD_FILTER(24) 滤除率
     score = 0.5*keep + 0.5*filt（用户历史认可）
  B. 错题集口径：000 层 15 干净真词召回、18 已知碎片残留
  C. 误伤：raw 候选集中 count>=5 且被滤且非碎片/非金标准滤除词的词数

用法： python exp/tune_combo.py
"""
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grow3.config import PipelineConfig
from grow3.gates import gate_chain
from grow3.scan import build_corpus, clean, scan_once
from grow3.signals.ent import cal_ent
from grow3.signals.cohesion import cal_cohesion
from grow3.signals.indep import cal_indep
from grow3.signals.spe_rsr import cal_spe_rsr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus.csv")

# ---- 评估集 ----
SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记",
               "无限恐怖","鬼灭","苟在","之主","之王","世界","长生","凡人","修仙",
               "都市","系统","巅峰","重生之","人在木叶","全职法师","风云","无敌",
               "直播","网游","神豪","荒古","重生","战神","天才","玄幻","末世",
               "奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之",
                 "星空之","火影开","无限之","诸天之","之巅","之神","之子","之魂",
                 "之开","罗之","世主","生仙","人在斗","影开始","局被","后一","的悠"]
TRUE_000 = ['庆余年','康熙','首富','刺客','围棋','迪迦','谍战','舰娘','铁血',
            '梦幻','工程','首辅','漫画','港片','捡属性']
FRAGS = ['我只','聊天','我真','我真不','联盟之','诸天之','罗之','我的','这个',
         '是我','游之','界的','真不','是大','的我','之我','成了','一个']


def load_corpus():
    rows = []
    with open(CORPUS, encoding='utf-8-sig', newline='') as f:
        r = csv.reader(f)
        for i, row in enumerate(r):
            if not row:
                continue
            if i == 0 and row[2].strip().lower() in {'title','书名','名称','name'}:
                continue
            t = row[2].strip()
            if t:
                rows.append(t)
    dedup = Counter(rows)
    docs = [(t, w) for t, w in dedup.items()]
    S, wgt = build_corpus([(clean(t), w) for t, w in docs])
    return S, wgt


def main():
    S, wgt = load_corpus()
    ctx, words = scan_once(S, wgt, 0.25, True, 8)
    ent_map = cal_ent(ctx, 0.25)
    for wd in words:
        wd.ent = ent_map.get(wd.word, -1.0)
    raw = {wd.word for wd in words}
    raw_count = {wd.word: wd.count for wd in words}

    # 预计算所有可能用到的信号（cfg 开关不同，惰性缓存）
    cache = {}

    def sig(name):
        if name not in cache:
            if name == "coh":
                m = cal_cohesion(ctx, 8)
                for wd in words:
                    wd.cohesion = m.get(wd.word, 0.0)
            elif name == "indep":
                m = cal_indep(ctx)
                for wd in words:
                    wd.indep = m.get(wd.word, -1.0)
            elif name == "spe":
                sm, rm = cal_spe_rsr(ctx, 2, 'mean')
                for wd in words:
                    wd.spe = sm.get(wd.word, -1.0)
                    wd.rsr = rm.get(wd.word, -1.0)
            cache[name] = True
        return True

    rows = []
    for coh in [0.0, 1.0, 1.5, 2.0]:
        for indep in [0.0, 0.03, 0.05, 0.10]:
            for spe in [0.0, 0.6, 0.8, 1.0]:
                if coh == 0 and indep == 0 and spe == 0:
                    continue
                if coh > 0: sig("coh")
                if indep > 0: sig("indep")
                if spe > 0: sig("spe")
                cfg = PipelineConfig(min_ent=0.5, ent_merge_ratio=0.25,
                                     min_cohesion=coh, min_indep=indep, spe_rescue=spe)
                kept = gate_chain(words, cfg)
                ks = {w.word for w in kept}
                keep_hit = sum(1 for w in SHOULD_KEEP if w in ks)
                filt_hit = sum(1 for w in SHOULD_FILTER if w not in ks)
                keep_rate = keep_hit / len(SHOULD_KEEP)
                filt_rate = filt_hit / len(SHOULD_FILTER)
                score = 0.5 * keep_rate + 0.5 * filt_rate
                r000 = sum(1 for w in TRUE_000 if w in ks)
                fr = sum(1 for w in FRAGS if w in ks)
                # 误伤：raw count>=5 被滤且非碎片/非金标准滤除
                collateral = sum(1 for w in (raw - ks)
                                 if raw_count[w] >= 5 and w not in set(SHOULD_FILTER)
                                 and w not in set(FRAGS))
                rows.append((f"coh{coh} indep{indep} spe{spe}", len(ks),
                             keep_hit, filt_hit, score, r000, fr, collateral))

    print(f"{'组合':<26}{'词数':>6}{'keep':>6}{'filt':>6}{'score':>7}"
          f"{'000真':>6}{'碎片':>5}{'误伤≥5':>7}")
    for name, n, kh, fh, sc, r0, fr, col in sorted(rows, key=lambda x: -x[4]):
        print(f"{name:<26}{n:>6}{kh:>5}/{len(SHOULD_KEEP):<3}{fh:>5}/{len(SHOULD_FILTER):<3}"
              f"{sc:>7.3f}{r0:>6}{fr:>5}{col:>7}")
    best = max(rows, key=lambda x: x[4])
    print("\n按 score(0.5keep+0.5filt) 最优:", best[0], f"词数{best[1]} score={best[4]:.3f} "
          f"000真{best[5]}/15 碎片{best[6]} 误伤≥5:{best[7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
