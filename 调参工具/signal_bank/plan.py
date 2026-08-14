# -*- coding: utf-8 -*-
"""signal_bank/plan.py —— 自动重跑检测（Phase 4）。

把"调参时哪类参数需要重跑"机器化：给定旧配置与新配置，判定信号计算需要的
重算级别：

    FULL         候选集/语料会变 → 必须重建 ScanContext（一次全扫描）
    INCREMENTAL 只脏了某些信号列（信号消费参数变）→ 仅重算脏列 + 失效共享缓存
    QUERY       只改了闸门阈值（纯查表）→ 信号列一行不动，仅 kept_for 复用

这是"解耦"的核心支点：调参工具不再靠人记忆"动 role_alpha 只需重算 role 列"，
而由 plan() 自动给出。配合 engine.compute_all(dirty=...) + _invalidate_super
实现增量重算，配合 engine.kept_for 实现纯查表。

配置形态兼容 PipelineConfig 与 dict（由 specs._cfg 统一取值）。
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Optional, Set, Tuple

from .specs import REGISTRY, _cfg


# 候选集/语料类参数：动了就重建 ctx（全量重算，绝不可能是增量）
SCAN_KEYS = {"ent_merge_ratio", "no_punct_ent", "no_merge", "cohesion_max_len"}
CORPUS_KEYS = {"input", "title_col", "intro_col", "no_header", "no_dedup"}

# 完全无效果、忽略（不触发任何重算）
IGNORE_KEYS = {"bind_thresh", "no_cloud", "top_n", "maxlen",
               "standalone", "title_complement"}


def _keys(cfg) -> Set[str]:
    """返回 cfg 的字段名集合（兼容 PipelineConfig 与 dict）。"""
    if isinstance(cfg, dict):
        return set(cfg.keys())
    return {f.name for f in dataclasses.fields(cfg)}


def _changed(cfg_old, cfg_new, key) -> bool:
    """新配置含该键且取值与旧配置不同 → 视为变化。

    dict 形态下缺键视为"未变化"；PipelineConfig 形态下字段恒在。
    """
    if key not in _keys(cfg_new):
        return False
    return _cfg(cfg_new, key, None) != _cfg(cfg_old, key, None)


def plan(cfg_old, cfg_new, registry=REGISTRY) -> Tuple[str, Optional[Set[str]]]:
    """返回 (kind, dirty)。

    kind:
        "FULL"        语料或扫描级参数变了，候选集变 → 调用方应重建 ctx
        "INCREMENTAL" 信号消费参数变了 → dirty 给出需重算的列
        "QUERY"       只改了闸门阈值（纯查表）→ 信号列不动，dirty=None
    dirty:
        INCREMENTAL 时为脏列集合；否则 None
    """
    # 1) 语料/扫描参数变了 → 候选集变了 → 全量
    full_keys = SCAN_KEYS | CORPUS_KEYS
    if any(_changed(cfg_old, cfg_new, k) for k in full_keys):
        return "FULL", None

    # 2) 信号消费参数变了 → 脏列传播（增量）
    dirty: Set[str] = set()
    for spec in registry:
        if any(_changed(cfg_old, cfg_new, p) for p in spec.compute_params):
            dirty |= set(spec.columns)

    if not dirty:
        return "QUERY", None
    return "INCREMENTAL", dirty


def incremental_recompute(ctx, cfg_old, cfg_new, registry=REGISTRY) -> Tuple[str, Optional[Set[str]], Dict[str, dict]]:
    """按 plan() 结论做增量重算，返回 (kind, dirty, new_cols)。

    - FULL：抛错（本函数不重建 ctx；重建由调用方/SignalBank 负责）。
    - QUERY：new_cols = {}（信号列一行不动）。
    - INCREMENTAL：失效共享超词缓存（如 min_super_cnt 变）+ 仅重算脏列；
      new_cols 只含脏列，调用方用 `old_cols | new_cols` 合并即可。

    new_cols: {列名: {word: float}}
    """
    kind, dirty = plan(cfg_old, cfg_new, registry)
    if kind == "FULL":
        raise ValueError("FULL 需由调用方重建 ctx；incremental_recompute 不重建")
    if kind == "QUERY":
        return kind, dirty, {}

    # INCREMENTAL：先失效共享缓存（min_super_cnt 变时必须），再只算脏列
    from .engine import _invalidate_super, compute_all
    _invalidate_super(ctx, cfg_old, cfg_new)
    new_cols = compute_all(ctx, cfg_new, registry, dirty=dirty)
    return kind, dirty, new_cols


__all__ = ["plan", "incremental_recompute", "SCAN_KEYS", "CORPUS_KEYS",
           "IGNORE_KEYS"]
