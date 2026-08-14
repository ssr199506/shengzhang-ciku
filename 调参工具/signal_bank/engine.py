# -*- coding: utf-8 -*-
"""signal_bank/engine.py —— 通用引擎（Phase 2/3 共用）。

复用 grow3 的扫描与信号算法（只读，不修改 grow3/），提供：
    load_docs       从 CSV 载入 (title, weight) 文档列表
    build_scan_ctx  一次扫描 → (ScanContext, words)
    compute_all     按注册表算全部信号列（支持增量：dirty 指定重算列）
    kept_for        Phase 3：镜像 gates.py 的通用模拟（任意阈值组合）

全部新代码；grow3/ 一行不改。
"""
from __future__ import annotations

import csv
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set

from grow3.config import PipelineConfig
from grow3.scan import build_corpus, clean, scan_once

from .specs import REGISTRY, GATES, ALL_COLUMNS, SIGNAL_BY_COLUMN, _cfg


# ----------------------------------------------------------------- 语料载入
_TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}


def detect_header(row, title_col, intro_col):
    """表头启发式（与 cli.py 同构）。"""
    if 0 <= title_col < len(row) and row[title_col].strip().lower() in _TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


def load_docs(corpus_path, title_col=0, intro_col=-1, no_header=False, no_dedup=False):
    """返回 title_docs: List[(title_str, weight_float)]。

    与 cli.main / dump_signals.load_docs 同构：去重并按权重累计；只取有书名的行。
    """
    with open(corpus_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        raw = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not no_header and detect_header(r, title_col, intro_col):
                continue
            title = r[title_col].strip() if 0 <= title_col < len(r) else ''
            intro = r[intro_col].strip() if 0 <= intro_col < len(r) else ''
            raw.append((title, intro))
    dedup = Counter(raw)
    title_docs = [(t, w) for (t, i), w in dedup.items() if t]
    return title_docs


# ----------------------------------------------------------------- 扫描
def build_scan_ctx(title_docs, cfg):
    """复用 grow3.scan 生成 (ScanContext, words)。

    cfg 仅消费 scan 级参数：ent_merge_ratio / no_merge / no_punct_ent / cohesion_max_len。
    其余信号参数不影响候选集（信号在 compute_all 里按列算）。
    """
    use_punct = not _cfg(cfg, "no_punct_ent", False)
    ent_merge_ratio = 0.0 if _cfg(cfg, "no_merge", False) else _cfg(cfg, "ent_merge_ratio", 0.25)
    S, wgt = build_corpus([(clean(t, use_punct), w) for t, w in title_docs])
    if not S:
        raise ValueError("语料为空")
    ctx, words = scan_once(S, wgt, ent_merge_ratio, True, _cfg(cfg, "cohesion_max_len", 8))
    return ctx, words


# ----------------------------------------------------------------- 全信号列计算
def compute_all(ctx, cfg, registry=REGISTRY, dirty: Optional[Set[str]] = None) -> Dict[str, dict]:
    """按注册表算全部信号列。

    dirty=None     全算
    dirty=列名集合  只重算与脏集相交的模块（增量），其余列保持调用方已有值
                    （调用方应把旧 cols 与新结果做合并：old | new）

    返回 cols: {列名: {word: float}}
    """
    cols: Dict[str, dict] = {}
    for spec in registry:
        if dirty is not None and not (set(spec.columns) & dirty):
            continue
        out = spec.compute(ctx, cfg)
        if len(spec.columns) == 1:
            out = (out,)
        for col, val in zip(spec.columns, out):
            cols[col] = val
    return cols


def _invalidate_super(ctx, cfg_old, cfg_new):
    """增量重算时若 min_super_cnt 变了，必须清掉超词索引缓存。

    build_super_index 的缓存在 ctx.super_info["_super_index"]，键不含 min_super_cnt
    （见 盘点.md §1 事实 2）。否则 role/asym 会吃到旧索引 → 静默错值。
    """
    if _cfg(cfg_old, "min_super_cnt", 2) != _cfg(cfg_new, "min_super_cnt", 2):
        ctx.super_info.pop("_super_index", None)


# ----------------------------------------------------------------- 通用模拟（Phase 3 使用）
def _gate_val(w, sig, cols, available):
    """取词 w 在列 sig 的信号值；缺列按哨兵回退（available 不含则抛错）。"""
    if sig not in available:
        raise ValueError(f"列 '{sig}' 不在可用信号集中 {sorted(available)}（dump 缺列或该信号未算）")
    col = cols.get(sig, {})
    return col.get(w, SIGNAL_BY_COLUMN[sig].sentinel)


def kept_for(words: Iterable[str], cols: Dict[str, dict], cfg,
             gates=GATES, available: Optional[Set[str]] = None) -> Set[str]:
    """镜像 gates.gate_chain 的通用模拟：返回保留词集合。

    words     候选词名列表（scan 产出的 words 的 .word）
    cols      {列名: {word: float}}（compute_all 产出，或 dump 载入）
    cfg       PipelineConfig 或 dict（提供各闸门阈值）
    available 本表实际含的列（用于缺列安全校验）；None = 信任全部 ALL_COLUMNS

    与 gates.py 对照要求：同一 (cfg, 词集) 下输出须逐词一致（Phase 3 验收硬门）。
    """
    if available is None:
        available = set(ALL_COLUMNS)
    words = list(words)
    val = lambda w, sig: _gate_val(w, sig, cols, available)

    # ---- AND 链：按 order 依次取交；哨兵 exempt 放行 ----
    passed, filtered = [], []
    for w in words:
        ok = True
        for g in (g for g in gates if g.kind == "and"):
            th = _cfg(cfg, g.param, 0)
            if th <= 0:
                continue
            v = val(w, g.signal)
            # cohesion 的 len<2 豁免（gates.py 硬编码，非数值哨兵，优先判定）
            if g.signal == "cohesion":
                if len(w) < 2:
                    continue
                if not (v >= th):
                    ok = False
                    break
                continue
            # 数值哨兵豁免：ent/indep/role/asym 的 -1 哨兵（v<0 → 放行）
            # 与 gates.py 的 `w.x < 0 or w.x >= th` 逐字一致
            if g.sentinel_policy == "exempt" and v < 0:
                continue
            if not (v >= th):
                ok = False
                break
        (passed if ok else filtered).append(w)

    kept = set(passed)

    # ---- 救援链：按 order 依次消费 filtered ----
    for g in (g for g in gates if g.kind == "rescue"):
        th = _cfg(cfg, g.param, 0)
        if th <= 0:
            continue
        rescued = []
        for w in filtered:
            v = val(w, g.signal)
            # 哨兵排除（spe_rescue 的 -1 哨兵，v<0 → 不救）；与 gates.py `if w.spe < 0` 一致
            if g.sentinel_policy == "exclude" and v < 0:
                continue
            if not (v >= th):
                continue
            extra_ok = True
            for s2, p2, _cmp in g.extra:
                t2 = _cfg(cfg, p2, 0)
                if t2 <= 0:
                    continue
                v2 = val(w, s2)
                if s2 == "rsr" and v2 < 0:      # gates.py: rsr 需 >=0
                    extra_ok = False
                    break
                if not (v2 >= t2):
                    extra_ok = False
                    break
            if extra_ok:
                rescued.append(w)
        kept |= set(rescued)
        filtered = [w for w in filtered if w not in set(rescued)]
    return kept


__all__ = ["load_docs", "build_scan_ctx", "compute_all", "_invalidate_super",
           "kept_for"]
