#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前后集中度(bind)阈值调参器
==========================
基线 = 不改判据时（bind_thresh=1.0，即只过 independent>=1）的候选词全集。
只扫描一遍语料得到含 binding 的候选词，再按不同阈值过滤，
把各阈值相对基线的「被剔除词」逐字列出来，辅助挑选最优阈值。

用法：
    python tune_bind.py <输入.csv> [--out DIR] [--prefix title|intro]
                        [--title-col 0] [--intro-col 1] [--no-header]

输出（默认 <out>/tune/）：
    bind_1.00.txt            基线候选词清单（word\\tcount\\tindependent\\tbind），可 diff
    bind_<阈值>.txt          该阈值下保留的候选词清单
    removed_<阈值>.txt       该阈值被剔除的词（word\\tcount\\tindependent\\tbind，按 count 降序）
    report.txt               汇总表：每个阈值保留/剔除数量
"""
import argparse
import csv
import os
import sys
from collections import Counter

import grow


def load_rows(path, title_col, intro_col, no_header):
    rows = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not no_header and grow.detect_header(r, title_col, intro_col):
                continue
            t = r[title_col].strip() if title_col < len(r) else ''
            intro = r[intro_col].strip() if (intro_col >= 0 and intro_col < len(r)) else ''
            rows.append((t, intro))
    return rows


def main():
    ap = argparse.ArgumentParser(description='前后集中度(bind)阈值调参器')
    ap.add_argument('input', help='CSV 路径（title, intro 两列）')
    ap.add_argument('--out', default='out_real', help='输出目录')
    ap.add_argument('--prefix', default='title', choices=['title', 'intro'], help='对哪条管线调参')
    ap.add_argument('--title-col', type=int, default=0)
    ap.add_argument('--intro-col', type=int, default=1)
    ap.add_argument('--no-header', action='store_true')
    args = ap.parse_args()

    rows = load_rows(args.input, args.title_col, args.intro_col, args.no_header)
    dedup = [(t, i, w) for (t, i), w in Counter(rows).items()]
    if args.prefix == 'title':
        docs = [(grow.clean(t), w) for t, i, w in dedup if t]
    else:
        docs = [(grow.clean(i), w) for t, i, w in dedup if i]

    S, wgt = grow.build_corpus(docs)
    if not S:
        print('语料为空', file=sys.stderr)
        return
    # 全量候选词（含 binding），不做阈值过滤
    candidates, _ = grow.scan_and_grow(S, wgt)

    baseline = sorted(candidates, key=lambda x: (-x[1], x[0]))
    base_words = {c[0] for c in baseline}
    by_word = {c[0]: c for c in baseline}

    out_dir = os.path.join(args.out, 'tune')
    os.makedirs(out_dir, exist_ok=True)

    thresholds = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5,
                  0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05, 0.0]

    def dump(path, items):
        with open(path, 'w', encoding='utf-8') as f:
            for w, cnt, ind, bind in items:
                f.write('%s\t%d\t%d\t%.4f\n' % (w, cnt, ind, bind))

    # 基线清单（供 diff 比较）
    dump(os.path.join(out_dir, 'bind_1.00.txt'), baseline)

    report = []
    report.append('prefix=%s  候选词总数(基线)=%d\n' % (args.prefix, len(baseline)))
    report.append('%-7s %8s %8s %8s\n' % ('bind', 'kept', 'removed', 'rem%'))
    report.append('-' * 36 + '\n')

    for th in thresholds:
        kept = [c for c in baseline if c[3] <= th]
        kept_words = {c[0] for c in kept}
        removed = sorted((by_word[w] for w in (base_words - kept_words)),
                         key=lambda x: (-x[1], x[0]))
        dump(os.path.join(out_dir, 'bind_%.2f.txt' % th), kept)
        dump(os.path.join(out_dir, 'removed_%.2f.txt' % th), removed)
        rem = len(removed)
        report.append('%-7.2f %8d %8d %7.1f%%\n' % (th, len(kept), rem, 100.0 * rem / len(baseline)))

    with open(os.path.join(out_dir, 'report.txt'), 'w', encoding='utf-8') as f:
        f.write(''.join(report))
    print(''.join(report))
    print('明细已写入: %s' % out_dir)


if __name__ == '__main__':
    main()
