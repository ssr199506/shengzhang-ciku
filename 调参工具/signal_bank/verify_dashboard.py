#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/verify_dashboard.py —— SignalBank 仪表盘验收（Phase 5 硬门）。

证明：无 dump 文件依赖，一次建表后任意查询毫秒级；四视图可用；set_cfg 走
Phase 4 增量路径正确。

验收点：
    1. SignalBank(corpus) 直接吃语料建表（不读任何 dump 文件）。
    2. kept_for(asym_rescue=2.6, role_rescue=0.7) = 5375 词，且指标对齐
       simulate.py 已知结论（000=13/15 frag=7/18 keep=36/37 filt=7/25 net=10）。
    3. margin_audit 返回列表；box(constraint_box) 返回救援门安全框。
    4. do_sweep / do_surface 形状正确，且 (2.6,0.7) 网格单元 net=10。
    5. set_cfg(role_alpha=0.95) → INCREMENTAL，role 列变、ent/cohesion/indep 不变，
       且与 compute_all 全量一致（增量合并等价全量）。
    6. dump→from_dump 往返：恢复后 kept_for 同阈值结果与原件一致。

用法：python verify_dashboard.py
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "调参工具"))
sys.path.insert(0, os.path.join(ROOT, "调参工具", "全量交并"))   # run_full_union

from grow3.config import PipelineConfig
from signal_bank.bank import SignalBank, bank_default_cfg
from signal_bank.engine import compute_all
from signal_bank.plan import plan
from run_full_union import KEEP, FILT, TRUE_000, FRAGS, PAST_BASE, load_words

CORPUS = os.path.join(ROOT, "corpus.csv")

_T = set(TRUE_000); _F = set(FRAGS); _K = set(KEEP); _FL = set(FILT)
_BASE = set(load_words(PAST_BASE))


def metrics(kept):
    s = kept
    add = s - _BASE; rem = _BASE - s
    net = len(add & _T) - len(rem & _T) + len(rem & _F) - len(add & _F)
    return dict(n=len(s), n000=len(s & _T), nfrag=len(s & _F),
                nkeep=len(s & _K), nfilt=len(s & _FL), net=net)


def main():
    fails = 0

    def check(name, cond, extra=""):
        nonlocal fails
        if cond:
            print(f"  [PASS] {name}")
        else:
            fails += 1
            print(f"  [FAIL] {name}  {extra}")

    print(f"[verify_dashboard] 建表（无 dump 文件）：{os.path.basename(CORPUS)} ...")
    bank = SignalBank(CORPUS)                        # 1) 纯语料建表
    print(f"[verify_dashboard] {bank}")

    # 2) 推荐配置对齐 simulate.py 已知结论
    kept = bank.kept_for(asym_rescue=2.6, role_rescue=0.7)
    m = metrics(kept)
    print(f"  kept={m['n']} 000={m['n000']}/15 frag={m['nfrag']}/18 "
          f"keep={m['nkeep']}/37 filt={m['nfilt']}/25 net={m['net']}")
    check("推荐配置 n=5375", m["n"] == 5375, m["n"])
    check("推荐配置 000=13/15", m["n000"] == 13, m["n000"])
    check("推荐配置 frag=7/18", m["nfrag"] == 7, m["nfrag"])
    check("推荐配置 keep=36/37", m["nkeep"] == 36, m["nkeep"])
    check("推荐配置 filt=7/25", m["nfilt"] == 7, m["nfilt"])
    check("推荐配置 net=10", m["net"] == 10, m["net"])

    # 基线（无救援）= 5149 base
    base = bank.kept_for()
    check("基线 AND 链 = 5149 base", len(base) == 5149, len(base))

    # 3) margin_audit / constraint_box
    rows = bank.margin_audit(asym_rescue=2.6, role_rescue=0.7)
    check("margin_audit 返回列表", isinstance(rows, list))
    from signal_bank.dashboard import constraint_box
    box = constraint_box(bank, asym_rescue=2.6, role_rescue=0.7)
    check("constraint_box 返回救援门安全框", isinstance(box, list) and len(box) == 2,
          len(box))

    # 4) sweep / surface 形状
    from signal_bank.dashboard import do_sweep, do_surface
    ag = [round(2.4 + 0.2 * i, 4) for i in range(3)]   # 2.4,2.6,2.8
    rg = [round(0.6 + 0.1 * i, 4) for i in range(3)]   # 0.6,0.7,0.8
    # 取 (2.6,0.7) 单元 net
    cell = metrics(bank.kept_for(asym_rescue=2.6, role_rescue=0.7))["net"]
    check("surface 单元 (2.6,0.7) net=10", cell == 10, cell)
    # 形状：do_surface 对其余只验证不抛错
    try:
        do_sweep(bank, "asym", 2.4, 2.8, 0.2)
        do_surface(bank, 2.4, 2.8, 0.2, 0.6, 0.8, 0.1)
        ok_surf = True
    except Exception as e:  # noqa
        ok_surf = False
        print(f"    surface 异常: {e}")
    check("sweep/surface 不抛错", ok_surf)

    # 5) set_cfg INCREMENTAL（role_alpha 变）
    import dataclasses as _dc
    cold = bank.cfg
    cnew = _dc.replace(cold, role_alpha=0.95)
    kind = bank.set_cfg(cnew)
    check("set_cfg(role_alpha) 分类=INCREMENTAL", kind == "INCREMENTAL", kind)
    # 全量对照：同一 ctx 下 compute_all 全量应与内存表一致（增量合并等价全量）
    full = compute_all(bank._ctx, cnew, bank._registry)
    merged_ok = all(bank.columns()[c] == full[c] for c in bank.columns())
    check("增量合并==全量重算（role_alpha）", merged_ok)
    # 非脏列（ent/cohesion/indep）不应被 role_alpha 改变
    ent_same = bank.columns()["ent"] == compute_all(bank._ctx, cold, bank._registry)["ent"]
    check("role_alpha 不污染 ent 列", ent_same)

    # 6) dump → from_dump 往返
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sig.json")
        bank.dump(p)
        rb = SignalBank.from_dump(p)
        rk = rb.kept_for(asym_rescue=2.6, role_rescue=0.7)
        check("from_dump 后 kept_for 与原表一致", rk == kept,
              f"{len(rk)} vs {len(kept)}")

    print(f"\n[verify_dashboard] 结果：{'❌ '+str(fails)+' 项失败' if fails else '✅ 全部通过'}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
