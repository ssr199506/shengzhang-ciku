#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/simulate.py —— 基于 dump v2 的即时阈值模拟（Phase 3 工具）。

对任意闸门阈值组合，毫秒级算出保留词集 + 评估指标（对齐 run_full_union 评测口径），
无需重跑流水线。这是"查表机制"的日常载体。

用法：
    python simulate.py --asym-rescue 2.6 --role-rescue 0.7
    python simulate.py --min-ent 0.5 --min-cohesion 1.5 --min-indep 0.05 \
                       --asym-rescue 2.6 --role-rescue 0.7 --min-role 0.5 --spe-rescue 0.9
    python simulate.py --asym-rescue 2.6 --role-rescue 0.7 --audit   # 附敏感词余量表
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)                                       # grow3
sys.path.insert(0, os.path.join(ROOT, "调参工具"))              # signal_bank
sys.path.insert(0, os.path.join(ROOT, "调参工具", "全量交并"))   # run_full_union

from grow3.config import PipelineConfig
import dataclasses
from signal_bank.engine import kept_for
from signal_bank.dump_v2 import from_json

DEFAULT_DUMP = os.path.join(ROOT, "调参产物", "plan_v2", "_signals", "title_signals_v2.json")

# 评测集（与 run_full_union 对齐）
from run_full_union import KEEP, FILT, TRUE_000, FRAGS, PAST_BASE, load_words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DEFAULT_DUMP)
    # 闸门阈值（任意组合）。AND 链默认 = 项目基线（ent0.5∧coh1.5∧indep0.05，
    # 即 5149 base）；救援门默认 0（关闭）。这样 `--asym-rescue 2.6 --role-rescue 0.7`
    # 直接复现调参推荐的"救援叠加在基线之上"语义。
    ap.add_argument("--min-ent", type=float, default=0.5)
    ap.add_argument("--cohesion", type=float, default=1.5)
    ap.add_argument("--indep", type=float, default=0.05)
    ap.add_argument("--min-role", type=float, default=0.0)
    ap.add_argument("--min-asym", type=float, default=0.0)
    ap.add_argument("--asym-rescue", type=float, default=0.0)
    ap.add_argument("--role-rescue", type=float, default=0.0)
    ap.add_argument("--spe-rescue", type=float, default=0.0)
    ap.add_argument("--rsr-rescue", type=float, default=0.0)
    ap.add_argument("--no-base", action="store_true",
                    help="关闭基线 AND 链（纯救援语义：救援从空被滤集=保留全部候选）")
    ap.add_argument("--audit", action="store_true", help="附敏感词余量表")
    args = ap.parse_args()

    words, cols, available, _ = from_json(args.dump)
    cfg = PipelineConfig(
        min_ent=0.0 if args.no_base else args.min_ent,
        min_cohesion=0.0 if args.no_base else args.cohesion,
        min_indep=0.0 if args.no_base else args.indep,
        min_role=args.min_role, min_asym=args.min_asym,
        asym_rescue=args.asym_rescue, role_rescue=args.role_rescue,
        spe_rescue=args.spe_rescue, rsr_rescue=args.rsr_rescue,
    )
    kept = kept_for(words, cols, cfg, available=available)

    base = set(load_words(PAST_BASE))
    s = kept
    add = s - base
    rem = base - s
    T = set(TRUE_000); F = set(FRAGS); K = set(KEEP); FL = set(FILT)
    net = len(add & T) - len(rem & T) + len(rem & F) - len(add & F)
    n000 = len(s & T); nfrag = len(s & F); nkeep = len(s & K); nfilt = len(s & FL)
    print(f"n={len(s)}  000={n000}/15  frag={nfrag}/18  keep={nkeep}/37  filt={nfilt}/25  net={net}")
    print(f"救回真词: {' '.join(sorted(add & T)) or '—'}")
    print(f"删除真词: {' '.join(sorted(rem & T)) or '—'}")
    print(f"新增碎片: {' '.join(sorted(add & F)) or '—'}")
    print(f"删除碎片: {' '.join(sorted(rem & F)) or '—'}")

    if args.audit:
        print("\n敏感词余量表（信号值 - 活跃阈值）:")
        th = {"asym": args.asym_rescue, "role": args.role_rescue,
              "spe": args.spe_rescue, "rsr": args.rsr_rescue}
        for w in sorted(s):
            mv = None
            for sig in ("asym", "role"):
                v = cols.get(sig, {}).get(w, -1.0)
                t = th[sig]
                if t > 0 and v >= 0:
                    d = v - t
                    if mv is None or d < mv[1]:
                        mv = (sig, d)
            if mv and mv[1] < 0.5:
                print(f"  {w}: {mv[0]}={cols.get(mv[0],{}).get(w,-1.0):.4f} 余量 {mv[1]:+.4f}")


if __name__ == "__main__":
    main()
