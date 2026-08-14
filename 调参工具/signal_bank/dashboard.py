#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/dashboard.py —— SignalBank 交互查询仪表盘（Phase 5）。

无 dump 文件依赖：直接吃语料建 SignalBank（一次扫描常驻内存），任意闸门阈值查询
毫秒级。覆盖计划要求的四种视图：sweep / margin_audit / constraint_box / surface，
以及 REPL 交互。

评测口径对齐 run_full_union（与 simulate.py 一致）：
    net = 救回真词(TRUE_000) - 删除真词 + 删除碎片(FRAGS) - 新增碎片

用法：
    python dashboard.py                                  # 进入 REPL（默认语料 corpus.csv）
    python dashboard.py --corpus corpus.csv --repl
    python dashboard.py --asym-rescue 2.6 --role-rescue 0.7   # 一次性：打印 n+指标
    python dashboard.py --sweep asym 2.4 2.8 0.2
    python dashboard.py --sweep grid 2.4 2.8 0.2 0.6 0.8 0.05 --metric net

REPL 命令：
    kept [asym_rescue=.. role_rescue=.. ...]   当前阈值下保留词数 + 指标
    sweep asym  <lo> <hi> <step>               asym_rescue 一维扫描
    sweep role  <lo> <hi> <step>               role_rescue 一维扫描
    sweep grid <alo> <ahi> <astep> <rlo> <rhi> <rstep>   二维网格（net 面）
    margin [asym_rescue=.. role_rescue=..]     敏感词余量表
    box [asym_rescue=.. role_rescue=..]        安全框：a/r 可升/降的边界
    surface <alo> <ahi> <astep> <rlo> <rhi> <rstep> [metric]   帕累托面（打印网格）
    set <gate>=<val> ...                       改当前闸门阈值
    show                                     打印当前闸门阈值
    reload                                   从语料重建 SignalBank
    help / exit
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)                                       # grow3
sys.path.insert(0, os.path.join(ROOT, "调参工具"))              # signal_bank
sys.path.insert(0, os.path.join(ROOT, "调参工具", "全量交并"))   # run_full_union

from grow3.config import PipelineConfig
from signal_bank.bank import SignalBank, bank_default_cfg
from run_full_union import KEEP, FILT, TRUE_000, FRAGS, PAST_BASE, load_words


# ----------------------------------------------------------------- 评测
_T = set(TRUE_000); _F = set(FRAGS); _K = set(KEEP); _FL = set(FILT)
_BASE = set(load_words(PAST_BASE))


def metrics(kept: set) -> dict:
    s = kept
    add = s - _BASE
    rem = _BASE - s
    net = len(add & _T) - len(rem & _T) + len(rem & _F) - len(add & _F)
    return dict(n=len(s), n000=len(s & _T), nfrag=len(s & _F),
                nkeep=len(s & _K), nfilt=len(s & _FL), net=net)


def _fmt_metrics(m: dict) -> str:
    return (f"n={m['n']}  000={m['n000']}/15  frag={m['nfrag']}/18  "
            f"keep={m['nkeep']}/37  filt={m['nfilt']}/25  net={m['net']}")


# ----------------------------------------------------------------- 安全框
def constraint_box(bank: SignalBank, **thresholds) -> list:
    kept = bank.kept_for(**thresholds)
    rows = []
    for sig, param in (("asym", "asym_rescue"), ("role", "role_rescue")):
        th = thresholds.get(param, getattr(bank.cfg, param, 0))
        if th <= 0:
            continue
        col = bank.columns().get(sig, {})
        kept_true = [w for w in kept if (w in _T or w in _K)]
        vals = [col.get(w, -1.0) for w in kept_true if col.get(w, -1.0) >= 0]
        drop_at = min(vals) if vals else None
        filt_frag = [w for w in bank.wordnames
                     if w not in kept and w in _F and col.get(w, -1.0) >= 0]
        fvals = [col[w] for w in filt_frag]
        add_at = max(fvals) if fvals else None
        rows.append(dict(
            signal=sig, threshold=th,
            drop_true_at=drop_at,
            drop_slack=(round(drop_at - th, 4) if drop_at is not None else None),
            add_frag_at=add_at,
            add_slack=(round(th - add_at, 4) if add_at is not None else None),
        ))
    return rows


def _print_box(rows):
    if not rows:
        print("  （无活跃救援门；box 仅对 asym_rescue/role_rescue 有效）")
        return
    print(f"  {'门':<6}{'阈值':>8}{'掉真词@':>10}{'可升余量':>10}{'加碎片@':>10}{'可降余量':>10}")
    for r in rows:
        da = f"{r['drop_true_at']:.4f}" if r['drop_true_at'] is not None else "—"
        ds = f"{r['drop_slack']:+.4f}" if r['drop_slack'] is not None else "—"
        aa = f"{r['add_frag_at']:.4f}" if r['add_frag_at'] is not None else "—"
        asl = f"{r['add_slack']:+.4f}" if r['add_slack'] is not None else "—"
        print(f"  {r['signal']:<6}{r['threshold']:>8.3f}{da:>10}{ds:>10}{aa:>10}{asl:>10}")


# ----------------------------------------------------------------- 网格
def _grid(lo, hi, step):
    out, v = [], round(float(lo), 4)
    while v <= hi + 1e-9:
        out.append(round(v, 4))
        v = round(v + step, 4)
    return out


def do_sweep(bank, axis, lo, hi, step, extra=None):
    """一维扫描：固定 extra 闸门，扫 axis 救援门。"""
    extra = extra or {}
    grid = _grid(lo, hi, step)
    param = "asym_rescue" if axis == "asym" else "role_rescue"
    print(f"  sweep {axis}_rescue ∈ [{lo},{hi}] step {step}（其余闸门 {extra or '基线'}）")
    print(f"  {'阈值':>8}  {'n':>6}  {'000':>5}  {'frag':>5}  {'keep':>5}  {'filt':>5}  {'net':>5}")
    for v in grid:
        th = {param: v, **extra}
        m = metrics(bank.kept_for(**th))
        print(f"  {v:>8.3f}  {m['n']:>6}  {m['n000']:>5}  {m['nfrag']:>5}  "
              f"{m['nkeep']:>5}  {m['nfilt']:>5}  {m['net']:>5}")


def do_surface(bank, alo, ahi, astep, rlo, rhi, rstep, metric="net", extra=None):
    """二维网格：asym_rescue × role_rescue 的 metric 面。"""
    extra = extra or {}
    ag = _grid(alo, ahi, astep)
    rg = _grid(rlo, rhi, rstep)
    print(f"  surface({metric})：行=role_rescue, 列=asym_rescue")
    hdr = "  role\\asym " + "".join(f"{a:>8.2f}" for a in ag)
    print(hdr)
    for r in rg:
        row = []
        for a in ag:
            m = metrics(bank.kept_for(asym_rescue=a, role_rescue=r, **extra))
            row.append(f"{m[metric]:>8}")
        print(f"  {r:>8.2f} " + "".join(row))


# ----------------------------------------------------------------- REPL
def repl(bank: SignalBank):
    print(f"[dashboard] SignalBank 就绪：{bank}")
    print("[dashboard] 输入 help 看命令；exit 退出。当前基线 AND 链 = ent0.5∧coh1.5∧indep0.05")

    def parse_th(tokens):
        th = {}
        for t in tokens:
            if "=" in t:
                k, v = t.split("=", 1)
                th[k.strip()] = float(v)
        return th

    while True:
        try:
            line = input("signal> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd, args = parts[0], parts[1:]

        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            print(__doc__.split("REPL 命令：")[-1].strip())
        elif cmd == "show":
            c = bank.cfg
            print(f"  min_ent={c.min_ent} min_cohesion={c.min_cohesion} min_indep={c.min_indep} "
                  f"min_role={c.min_role} min_asym={c.min_asym} "
                  f"asym_rescue={c.asym_rescue} role_rescue={c.role_rescue} "
                  f"spe_rescue={c.spe_rescue} rsr_rescue={c.rsr_rescue}")
        elif cmd == "set":
            th = parse_th(args)
            if th:
                bank.set_cfg(dataclasses.replace(bank.cfg, **th))
                print(f"  set: {th}")
        elif cmd == "reload":
            bank = SignalBank(CORPUS, bank_default_cfg())
            print(f"  reloaded: {bank}")
        elif cmd == "kept":
            th = parse_th(args)
            kept = bank.kept_for(**th)
            print(f"  kept {len(kept)} 词 | {_fmt_metrics(metrics(kept))}")
        elif cmd == "margin":
            th = parse_th(args)
            rows = bank.margin_audit(**th)
            print(f"  敏感词（余量<0.5）共 {len(rows)} 个：")
            for r in rows[:30]:
                print(f"    {r['word']}: {r['signal']}={r['value']:.4f} "
                      f"阈{r['threshold']:.3f} 余量{r['margin']:+.4f}")
        elif cmd == "box":
            th = parse_th(args)
            _print_box(constraint_box(bank, **th))
        elif cmd == "sweep":
            if not args or args[0] == "grid":
                if args and args[0] == "grid":
                    lo, hi, st, rlo, rhi, rst = args[1:7]
                    do_surface(bank, float(lo), float(hi), float(st),
                               float(rlo), float(rhi), float(rst))
                else:
                    print("  sweep grid <alo> <ahi> <astep> <rlo> <rhi> <rstep>")
            else:
                axis = args[0]
                lo, hi, st = args[1:4]
                do_sweep(bank, axis, float(lo), float(hi), float(st))
        elif cmd == "surface":
            lo, hi, st, rlo, rhi, rst = args[:6]
            metric = args[6] if len(args) > 6 else "net"
            do_surface(bank, float(lo), float(hi), float(st),
                       float(rlo), float(rhi), float(rst), metric)
        else:
            print(f"  未知命令 {cmd}；输入 help")


# ----------------------------------------------------------------- 入口
CORPUS = os.path.join(ROOT, "corpus.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--asym-rescue", type=float, default=None)
    ap.add_argument("--role-rescue", type=float, default=None)
    ap.add_argument("--min-ent", type=float, default=None)
    ap.add_argument("--cohesion", type=float, default=None)
    ap.add_argument("--indep", type=float, default=None)
    ap.add_argument("--min-role", type=float, default=None)
    ap.add_argument("--min-asym", type=float, default=None)
    ap.add_argument("--spe-rescue", type=float, default=None)
    ap.add_argument("--rsr-rescue", type=float, default=None)
    ap.add_argument("--sweep", nargs="*", default=None,
                    help="asym <lo> <hi> <step> | role ... | grid <alo> <ahi> <astep> <rlo> <rhi> <rstep>")
    ap.add_argument("--metric", default="net")
    ap.add_argument("--repl", action="store_true")
    args = ap.parse_args()

    cfg = bank_default_cfg()
    overrides = {}
    for a in ("asym_rescue", "role_rescue", "min_ent", "cohesion", "indep",
              "min_role", "min_asym", "spe_rescue", "rsr_rescue"):
        v = getattr(args, a.replace("-", "_"), None) if a != "cohesion" else args.cohesion
        if a == "cohesion":
            v = args.cohesion
        if v is not None:
            overrides[a if a != "cohesion" else "min_cohesion"] = v
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)

    bank = SignalBank(args.corpus, cfg)
    print(f"[dashboard] {bank}")

    if args.sweep:
        sw = args.sweep
        if sw[0] == "grid":
            do_surface(bank, float(sw[1]), float(sw[2]), float(sw[3]),
                       float(sw[4]), float(sw[5]), float(sw[6]), args.metric)
        else:
            axis = sw[0]
            do_sweep(bank, axis, float(sw[1]), float(sw[2]), float(sw[3]))
        return

    if args.repl or not overrides:
        # 一次性也至少打印当前配置结果
        if overrides:
            kept = bank.kept_for()
            print(f"[dashboard] kept {len(kept)} 词 | {_fmt_metrics(metrics(kept))}")
        repl(bank)
    else:
        kept = bank.kept_for()
        print(f"[dashboard] kept {len(kept)} 词 | {_fmt_metrics(metrics(kept))}")


if __name__ == "__main__":
    main()
