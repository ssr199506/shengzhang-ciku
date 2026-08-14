#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/verify_plan.py —— plan() 增量重算验收（Phase 4 硬门）。

验证升级计划 §七 Phase 4 验收 + §五.3 参数分类总表：
    改 role_alpha      → INCREMENTAL, dirty={role}，仅重算 role 列，且合并后与全量一致
    改 min_super_cnt   → INCREMENTAL, dirty={spe,rsr,role,asym}，清超词缓存+重算 4 列，
                         且证明"不清缓存"会拿到旧索引导致错值（_invalidate_super 不可或缺）
    改 min_ent         → QUERY, dirty=None，信号列一行不动
    改 ent_merge_ratio → FULL（候选集变）
    改 asym_rescue/role_rescue（纯闸门）→ QUERY
    改 rsr_mode        → INCREMENTAL, dirty={rsr}

方法：从 corpus.csv 建一次 ScanContext（候选集），用 compute_all 全量与增量结果比对。
同一 ctx 下，min_super_cnt/role_alpha 等"信号参数"不动候选集，仅影响列值，故可干净对照。

用法：python verify_plan.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)                          # grow3
sys.path.insert(0, os.path.join(ROOT, "调参工具"))   # signal_bank / run_full_union

from grow3.config import PipelineConfig
from signal_bank.engine import load_docs, build_scan_ctx, compute_all, _invalidate_super
from signal_bank.specs import REGISTRY, ALL_COLUMNS
from signal_bank.plan import plan

CORPUS = os.path.join(ROOT, "corpus.csv")

# 基线扫描级参数（与 dump_v2.py _default_cfg 一致），决定候选集
_SCAN = dict(ent_merge_ratio=0.25, no_punct_ent=False, no_merge=False,
             cohesion_max_len=8, title_col=2, intro_col=-1, no_cloud=True)


def cfg(**over):
    d = dict(min_super_cnt=2, rsr_mode="mean", role_max_depth=-1, role_alpha=0.85,
             min_ent=0.0, min_cohesion=0.0, min_indep=0.0,
             min_role=0.0, min_asym=0.0,
             asym_rescue=0.0, role_rescue=0.0, spe_rescue=0.0, rsr_rescue=0.0)
    d.update(_SCAN)
    d.update(over)
    return PipelineConfig(**d)


def main():
    print(f"[verify_plan] 载入语料 {os.path.basename(CORPUS)} ...")
    docs = load_docs(CORPUS, 2, -1)
    ctx, words = build_scan_ctx(docs, cfg())
    print(f"[verify_plan] ctx 就绪：候选 {len(words)} 词")

    fails = 0

    def check(name, cond, extra=""):
        nonlocal fails
        if cond:
            print(f"  [PASS] {name}")
        else:
            fails += 1
            print(f"  [FAIL] {name}  {extra}")

    # ---- 场景 A：改 role_alpha → 只重算 role 列 ----
    cold = cfg(); cnew = cfg(role_alpha=0.95)
    kind, dirty = plan(cold, cnew)
    check("A1 role_alpha 分类=INCREMENTAL", kind == "INCREMENTAL", (kind, dirty))
    check("A2 role_alpha 脏集={role}", dirty == {"role"}, str(dirty))
    ctx.super_info.pop("_super_index", None)
    old = compute_all(ctx, cold)
    inc = compute_all(ctx, cnew, dirty=dirty)
    merged = {**old, **inc}
    new_full = compute_all(ctx, cnew)
    ok = all(merged[c] == new_full[c] for c in ALL_COLUMNS)
    check("A3 增量合并==全量重算", ok)
    check("A4 inc 只含 role 列", set(inc.keys()) == {"role"}, str(set(inc.keys())))

    # ---- 场景 B：改 min_super_cnt → 清缓存+重算 4 列（并证明不清缓存会错）----
    cold = cfg(); cnew = cfg(min_super_cnt=3)
    kind, dirty = plan(cold, cnew)
    check("B1 min_super_cnt 分类=INCREMENTAL", kind == "INCREMENTAL", (kind, dirty))
    check("B2 脏集={spe,rsr,role,asym}", dirty == {"spe", "rsr", "role", "asym"}, str(dirty))
    ctx.super_info.pop("_super_index", None)
    old = compute_all(ctx, cold)                 # 缓存建立为 cnt=2
    stale = compute_all(ctx, cnew)               # 不清缓存 → 误用 cnt=2（错误结果）
    ctx.super_info.pop("_super_index", None)
    _invalidate_super(ctx, cold, cnew)           # 清缓存（cnt 变了）
    inc = compute_all(ctx, cnew, dirty=dirty)    # 正确增量：重建 cnt=3
    merged = {**old, **inc}
    new_full = compute_all(ctx, cnew)            # 缓存此刻为 cnt=3
    ok = all(merged[c] == new_full[c] for c in ALL_COLUMNS)
    check("B3 增量合并==全量重算", ok)
    check("B4 inc 只含 4 超词列",
          set(inc.keys()) == {"spe", "rsr", "role", "asym"}, str(set(inc.keys())))
    # 关键：不清缓存的 stale 在 role/asym 上必须与正确值不同（证明缓存确实会漂移）
    stale_wrong = (stale["role"] != new_full["role"]) or (stale["asym"] != new_full["asym"])
    check("B5 不清缓存→role/asym 静默错值（证明 _invalidate_super 不可或缺）",
          stale_wrong, "stale 与正确值一致，未复现漂移")

    # ---- 场景 C：改 min_ent → QUERY，信号列一行不动 ----
    cold = cfg(min_ent=0.5); cnew = cfg(min_ent=0.6)
    kind, dirty = plan(cold, cnew)
    check("C1 min_ent 分类=QUERY", kind == "QUERY", (kind, dirty))
    check("C2 min_ent dirty=None", dirty is None, str(dirty))
    inc = compute_all(ctx, cnew, dirty=dirty) if dirty is not None else {}
    check("C3 QUERY 不重算任何列", inc == {}, str(set(inc.keys())))
    ctx.super_info.pop("_super_index", None)
    fa = compute_all(ctx, cold); fb = compute_all(ctx, cnew)
    unchanged = all(fa[c] == fb[c] for c in ALL_COLUMNS)
    check("C4 改闸门阈值后信号列逐列不变", unchanged)

    # ---- 场景 D：改 ent_merge_ratio → FULL（候选集变）----
    cold = cfg(); cnew = cfg(ent_merge_ratio=0.30)
    kind, dirty = plan(cold, cnew)
    check("D1 ent_merge_ratio 分类=FULL", kind == "FULL", (kind, dirty))
    check("D2 FULL dirty=None", dirty is None)

    # ---- 场景 E：纯闸门/其它信号参数分类 ----
    check("E1 asym_rescue+role_rescue → QUERY",
          plan(cfg(), cfg(asym_rescue=2.6, role_rescue=0.7)) == ("QUERY", None))
    k, d = plan(cfg(), cfg(rsr_mode="max"))
    check("E2 rsr_mode → INCREMENTAL,{spe,rsr}", (k, d) == ("INCREMENTAL", {"spe", "rsr"}), (k, d))
    k, d = plan(cfg(), cfg(role_max_depth=1))
    check("E3 role_max_depth → INCREMENTAL,{role}", (k, d) == ("INCREMENTAL", {"role"}), (k, d))

    print(f"\n[verify_plan] 结果：{'❌ '+str(fails)+' 项失败' if fails else '✅ 全部通过'} "
          f"（共 18 检查项）")
    # 注意：上面 check 调用次数 = A(4) + B(5) + C(4) + D(2) + E(3) = 18
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
