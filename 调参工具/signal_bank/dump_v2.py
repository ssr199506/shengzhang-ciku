#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/dump_v2.py —— 全信号列转储（dump 解耦升级 Phase 2）。

与 dump_signals.py 的区别：
    - 产出全部 7 列（ent/cohesion/indep/spe/rsr/role/asym），而非仅 role/asym
    - schema=2，含 meta（语料/候选数/配置快照/列清单/时间）
    - 不再存 pass_and：由 AND 闸门声明 + 列值即时推导（这才是"AND 门可查表"的关键）
    - 向后兼容：from_json 读 schema==1 时缺列填哨兵（救援族可查，AND/spe 需 v2）

用法：
    python dump_v2.py [--corpus corpus.csv] [--title-col 2] [--intro-col -1]
                      [--out 调参产物/plan_v2/_signals/title_signals_v2.json]
                      [--config config.json]   # 可选：读配置决定扫描级参数
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from grow3.config import PipelineConfig
from .engine import load_docs, build_scan_ctx, compute_all
from .specs import ALL_COLUMNS, SIGNAL_BY_COLUMN


def _default_cfg() -> PipelineConfig:
    """默认转储配置：算全信号列所需的 scan 级参数（匹配基线 0.25/8 + 超词参数）。"""
    return PipelineConfig(
        ent_merge_ratio=0.25, no_punct_ent=False, no_merge=False,
        cohesion_max_len=8, min_super_cnt=2, rsr_mode="mean",
        role_max_depth=-1, role_alpha=0.85,
        title_col=2, intro_col=-1, no_cloud=True,
    )


def dump(corpus_path, cfg, out_path):
    title_docs = load_docs(corpus_path, _cfg_col(cfg, "title_col", 2),
                           _cfg_col(cfg, "intro_col", -1))
    ctx, words = build_scan_ctx(title_docs, cfg)
    cols = compute_all(ctx, cfg)                 # 全 7 列

    records = []
    for w in words:
        rec = {"word": w.word, "count": int(w.count)}
        for col in ALL_COLUMNS:
            sentinel = SIGNAL_BY_COLUMN[col].sentinel
            rec[col] = round(cols.get(col, {}).get(w.word, sentinel), 6)
        records.append(rec)

    snapshot = {
        "ent_merge_ratio": _cfg_col(cfg, "ent_merge_ratio", 0.25),
        "no_punct_ent": _cfg_col(cfg, "no_punct_ent", False),
        "no_merge": _cfg_col(cfg, "no_merge", False),
        "cohesion_max_len": _cfg_col(cfg, "cohesion_max_len", 8),
        "min_super_cnt": _cfg_col(cfg, "min_super_cnt", 2),
        "rsr_mode": _cfg_col(cfg, "rsr_mode", "mean"),
        "role_max_depth": _cfg_col(cfg, "role_max_depth", -1),
        "role_alpha": _cfg_col(cfg, "role_alpha", 0.85),
    }
    doc = {
        "schema": 2,
        "meta": {
            "corpus": os.path.basename(corpus_path),
            "n_docs": len(title_docs),
            "n_candidates": len(words),
            "cfg_snapshot": snapshot,
            "columns": list(ALL_COLUMNS),
            "created": _dt.datetime.now().isoformat(timespec="seconds"),
        },
        "words": records,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return doc


def _cfg_col(cfg, key, default):
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def from_json(path):
    """载入 dump（v1/v2 兼容）。返回 (words_list, cols_dict, available_set, schema)。

    v1：schema==1（word/count/role/asym/pass_and）→ 只含 role/asym 两列，缺列回退哨兵。
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    schema = doc.get("schema", 1)
    if schema >= 2:
        cols = {c: {} for c in doc["meta"]["columns"]}
        for rec in doc["words"]:
            for c in doc["meta"]["columns"]:
                cols[c][rec["word"]] = rec.get(c, SIGNAL_BY_COLUMN[c].sentinel)
        available = set(doc["meta"]["columns"])
    else:
        cols = {"role": {}, "asym": {}}
        for rec in doc["words"]:
            cols["role"][rec["word"]] = rec.get("role", -1.0)
            cols["asym"][rec["word"]] = rec.get("asym", -1.0)
        available = {"role", "asym"}
    words = [rec["word"] for rec in doc["words"]]
    return words, cols, available, schema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(ROOT, "corpus.csv"))
    ap.add_argument("--title-col", type=int, default=2)
    ap.add_argument("--intro-col", type=int, default=-1)
    ap.add_argument("--out", default=os.path.join(ROOT, "调参产物", "plan_v2",
                                                  "_signals", "title_signals_v2.json"))
    ap.add_argument("--config", default=None, help="可选：读 config.json 决定扫描级参数")
    args = ap.parse_args()

    cfg = _default_cfg()
    if args.config:
        cfg = PipelineConfig.from_dict(json.load(open(args.config, encoding="utf-8")))
    # CLI 覆盖列号
    cfg.title_col = args.title_col
    cfg.intro_col = args.intro_col

    doc = dump(args.corpus, cfg, args.out)
    print(f"[dump_v2] 候选 {doc['meta']['n_candidates']} 词 | 列 {doc['meta']['columns']}")
    print(f"[dump_v2] 已写出 {args.out} (schema=2)")


if __name__ == "__main__":
    main()
