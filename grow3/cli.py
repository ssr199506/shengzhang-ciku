"""grow3.cli —— 3.0 统一管道入口。Step 2 接通 scan + ent，Step 6 接通全部信号与 gate 组装。

用法（与历史分支 CLI 对齐）：
    python -m grow3.cli <输入.csv> [--min-ent 0.5] [--cohesion 1.5]
                              [--indep 0.05] [--spe-rescue 0.8]
                              [--rsr-rescue 8] [--rsr-mode mean]
                              [--title-col 2] [--intro-col -1]
                              [--ent-merge-ratio 0.25] [--no-cloud]
                              [--audit out.json]

默认参数须复现 main 5865（--min-ent 0.5 + --ent-merge-ratio 0.25）。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from typing import List, Tuple

from .config import PipelineConfig
from .gates import gate_chain
from .ir import Word
from .output import write_word_csv
from .scan import build_corpus, clean, scan_once
from .signals.ent import cal_ent
from .signals.cohesion import cal_cohesion


def load_csv(path, has_header):
    """读取 CSV，返回 [(title, intro), ...]。与 main 行为一致。"""
    rows = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and has_header:
                continue
            title = r[0].strip()
            intro = r[1].strip() if len(r) > 1 else ''
            rows.append((title, intro))
    return rows


def detect_header(row, title_col, intro_col):
    """表头启发：title_col 位置为已知表头词，或前两列均为纯 ASCII 标识。"""
    TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}
    if title_col < len(row) and row[title_col].strip().lower() in TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="grow3", description="生长词库 3.0 统一管道")
    ap.add_argument("input", help="输入 CSV（title,intro）")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--min-ent", type=float, default=0.5, help="复合熵阈值")
    ap.add_argument("--cohesion", type=float, default=0.0, help="凝固度阈值")
    ap.add_argument("--indep", type=float, default=0.0, help="词本身偏序阈值")
    ap.add_argument("--spe-rescue", type=float, default=0.0, help="SPE 救援阈值")
    ap.add_argument("--rsr-rescue", type=float, default=0.0, help="RSR 救援阈值")
    ap.add_argument("--rsr-mode", choices=["mean", "max"], default="mean")
    ap.add_argument("--ent-merge-ratio", type=float, default=0.25)
    ap.add_argument("--title-col", type=int, default=0)
    ap.add_argument("--intro-col", type=int, default=1)
    ap.add_argument("--no-header", action="store_true")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--bind", type=float, default=1.0, help="前后集中度闸门（默认 1.0=关）")
    ap.add_argument("--no-punct-ent", action="store_true", help="关闭标点感知熵")
    ap.add_argument("--no-merge", action="store_true", help="关闭合并模式（ratio=0）")
    ap.add_argument("--no-cloud", action="store_true", default=True)
    ap.add_argument("--audit", default=None, help="审计日志输出路径")
    return ap


def run_pipeline(prefix, docs, raw_texts, cfg, out_dir):
    """对一条管线（title/intro）跑完整管道，返回最终 Word 列表。"""
    use_punct = not cfg.no_punct_ent if hasattr(cfg, 'no_punct_ent') else True
    ent_merge_ratio = 0.0 if getattr(cfg, 'no_merge', False) else cfg.ent_merge_ratio
    S, wgt = build_corpus([(clean(t, use_punct), w) for t, w in docs])
    if not S:
        return []
    ctx, words = scan_once(S, wgt, ent_merge_ratio, True, cfg.cohesion_max_len)
    ent_map = cal_ent(ctx, ent_merge_ratio)
    for wd in words:
        wd.ent = ent_map.get(wd.word, -1.0)
    if cfg.min_cohesion > 0:
        coh_map = cal_cohesion(ctx, cfg.cohesion_max_len)
        for wd in words:
            wd.cohesion = coh_map.get(wd.word, 0.0)
    kept = gate_chain(words, cfg)
    write_word_csv(kept, os.path.join(out_dir, f'{prefix}_wordfreq.csv'))
    return kept


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    cfg = PipelineConfig(
        ent_merge_ratio=args.ent_merge_ratio,
        min_ent=args.min_ent,
        min_cohesion=args.cohesion,
        min_indep=args.indep,
        spe_rescue=args.spe_rescue,
        rsr_rescue=args.rsr_rescue,
        rsr_mode=args.rsr_mode,
        title_col=args.title_col,
        intro_col=args.intro_col,
        no_cloud=args.no_cloud,
        bind_thresh=args.bind,
    )
    # 兼容未列出的开关
    cfg.no_punct_ent = args.no_punct_ent
    cfg.no_merge = args.no_merge

    os.makedirs(args.out, exist_ok=True)

    with open(args.input, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        raw_rows = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not args.no_header and detect_header(r, args.title_col, args.intro_col):
                continue
            title = r[args.title_col].strip() if 0 <= args.title_col < len(r) else ''
            intro = r[args.intro_col].strip() if 0 <= args.intro_col < len(r) else ''
            raw_rows.append((title, intro))

    if args.no_dedup:
        dedup = [(t, i, 1) for t, i in raw_rows]
    else:
        dedup = [(t, i, w) for (t, i), w in Counter(raw_rows).items()]

    title_docs = [(t, w) for t, i, w in dedup if t]
    intro_docs = [(i, w) for t, i, w in dedup if i]
    title_raw = [t for t, i, w in dedup if t]
    intro_raw = [i for t, i, w in dedup if i]

    kt = run_pipeline('title', title_docs, title_raw, cfg, args.out)
    if args.intro_col >= 0 and intro_docs:
        run_pipeline('intro', intro_docs, intro_raw, cfg, args.out)

    print(f'[grow3] 默认闸门({cfg.gate_summary()}) → 标题词 {len(kt)} 个', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
