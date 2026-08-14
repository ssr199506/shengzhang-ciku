#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_signals.py —— 一次全量信号转储（机制 A 载体）。

与 cli.run_pipeline 完全同构地算出候选池每个词的 ent/cohesion/indep/role/asym，
并施加真实 AND 过滤链（ent>=0.5 ∧ cohesion>=1.5 ∧ indep>=0.05）得到：
  - passed_AND: 通过三道过滤门的词（保留集锚点）
  - filtered:    被任意一道门滤掉的词（救援门输入）
两张表都带 role / asym 信号值。之后任意 (asym_rescue, role_rescue) 的救援结果可由
sim_rescue.py 即时推得，无需重跑流水线。

输出：调参产物/plan_v2/_signals/title_signals.json
用法：python dump_signals.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from grow3.config import PipelineConfig                      # noqa: E402
from grow3.scan import build_corpus, clean, scan_once        # noqa: E402
from grow3.signals.ent import cal_ent                        # noqa: E402
from grow3.signals.cohesion import cal_cohesion              # noqa: E402
from grow3.signals.indep import cal_indep                    # noqa: E402
from grow3.signals.role import solve_roles                   # noqa: E402
from grow3.signals.asym import cal_asym                      # noqa: E402

CORPUS = os.path.join(ROOT, "corpus.csv")
OUT_DIR = os.path.join(ROOT, "调参产物", "plan_v2", "_signals")
TITLE_COL, INTRO_COL = 2, -1


def detect_header(row, title_col, intro_col):
    TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}
    if 0 <= title_col < len(row) and row[title_col].strip().lower() in TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


def load_docs():
    with open(CORPUS, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        raw = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and detect_header(r, TITLE_COL, INTRO_COL):
                continue
            title = r[TITLE_COL].strip() if 0 <= TITLE_COL < len(r) else ''
            intro = r[INTRO_COL].strip() if 0 <= INTRO_COL < len(r) else ''
            raw.append((title, intro))
    dedup = Counter(raw)
    title_docs = [(t, w) for (t, i), w in dedup.items() if t]
    return title_docs


def main():
    cfg = PipelineConfig(
        min_ent=0.5, min_cohesion=1.5, min_indep=0.05,
        ent_merge_ratio=0.25, no_punct_ent=False, no_merge=False,
        role_enabled=True, role_max_depth=-1, role_alpha=0.85,
        asym_enabled=True, min_super_cnt=2, cohesion_max_len=8,
        title_col=TITLE_COL, intro_col=INTRO_COL, no_cloud=True,
    )
    docs = load_docs()
    print(f"[dump] 载入 title_docs {len(docs)} 条")

    use_punct = not cfg.no_punct_ent
    S, wgt = build_corpus([(clean(t, use_punct), w) for t, w in docs])
    if not S:
        print("[dump] 语料为空", file=sys.stderr)
        sys.exit(1)
    ctx, words = scan_once(S, wgt, cfg.ent_merge_ratio, True, cfg.cohesion_max_len)
    ent_map = cal_ent(ctx, cfg.ent_merge_ratio)
    coh_map = cal_cohesion(ctx, cfg.cohesion_max_len)
    indep_map = cal_indep(ctx)
    role_map = solve_roles(ctx, cfg.role_max_depth, cfg.min_super_cnt, cfg.role_alpha)
    asym_map = cal_asym(ctx, cfg.min_super_cnt)

    # ---- AND 过滤链（与 gates.gate_chain 完全同构；min_role/min_asym 默认 0 不触发）----
    def pass_and(w):
        e = ent_map.get(w.word, -1.0)
        c = coh_map.get(w.word, 0.0)
        d = indep_map.get(w.word, -1.0)
        if not (e < 0 or e >= cfg.min_ent):
            return False
        if not (len(w.word) < 2 or c >= cfg.min_cohesion):
            return False
        if not (d < 0 or d >= cfg.min_indep):
            return False
        return True

    records = []
    n_pass = 0
    for w in words:
        pa = pass_and(w)
        n_pass += 1 if pa else 0
        records.append({
            "word": w.word,
            "count": int(w.count),
            "role": round(role_map.get(w.word, -1.0), 6),
            "asym": round(asym_map.get(w.word, -1.0), 6),
            "pass_and": pa,
        })
    print(f"[dump] 候选 {len(records)} 词 | 通过AND链 {n_pass} | 被滤 {len(records) - n_pass}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "title_signals.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "params": {"min_ent": 0.5, "min_cohesion": 1.5, "min_indep": 0.05,
                       "ent_merge_ratio": 0.25, "role_alpha": 0.85,
                       "role_max_depth": -1, "min_super_cnt": 2},
            "n_total": len(records),
            "n_pass": n_pass,
            "words": records,
        }, f, ensure_ascii=False)
    print(f"[dump] 已写出 {out}")


if __name__ == "__main__":
    main()
