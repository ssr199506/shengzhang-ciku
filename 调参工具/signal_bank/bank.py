# -*- coding: utf-8 -*-
"""signal_bank/bank.py —— 内存信号库 SignalBank（Phase 5 仪表盘底座）。

与计划 §五.4 的 SignalBank 等价，落点为 `signal_bank/bank.py`（避免与本包目录
`signal_bank/` 同名冲突）。

设计要点（红线同前：grow3 一行不改）：
    - 一次扫描 + 信号表常驻内存；任意闸门阈值查询毫秒级（compute_all 已算全 7 列）。
    - 不再依赖 dump 文件：SignalBank(corpus, cfg) 直接吃语料建表。
    - dump JSON 退化为可选持久化：bank.dump(path) / SignalBank.from_dump(path)。
    - set_cfg 接入 Phase 4 的 plan()：FULL 重建 / INCREMENTAL 增量 / QUERY 纯查表。

用法：
    bank = SignalBank("corpus.csv")
    bank.kept_for(asym_rescue=2.60, role_rescue=0.70)     # → {word} 集合
    bank.margin_audit(asym_rescue=2.60, role_rescue=0.70) # → 敏感词余量表
    bank.dump("signals.json")                              # 可选序列化
"""
from __future__ import annotations

import dataclasses
import json
import os
from typing import Dict, List, Optional, Set

from grow3.config import PipelineConfig

from .engine import load_docs, build_scan_ctx, compute_all, kept_for
from .plan import plan, incremental_recompute
from .specs import REGISTRY, GATES, ALL_COLUMNS, SIGNAL_BY_COLUMN, GATE_BY_PARAM


# SignalBank 默认配置：基线 AND 链（ent0.5∧coh1.5∧indep0.05，
# 即 5149 base）叠加在信号参数之上。kept_for 不传闸门时即为该基线。
def bank_default_cfg() -> PipelineConfig:
    return PipelineConfig(
        ent_merge_ratio=0.25, no_punct_ent=False, no_merge=False,
        cohesion_max_len=8, title_col=2, intro_col=-1, no_cloud=True,
        min_ent=0.5, min_cohesion=1.5, min_indep=0.05,
        min_super_cnt=2, rsr_mode="mean", role_max_depth=-1, role_alpha=0.85,
    )


class SignalBank:
    """内存信号库：一次扫描 + 信号表常驻，任意阈值查询毫秒级。"""

    def __init__(self, corpus, cfg: Optional[PipelineConfig] = None,
                 registry=REGISTRY, gates=GATES):
        self._corpus = corpus
        self._registry = registry
        self._gates = gates
        self._cfg = cfg if cfg is not None else bank_default_cfg()
        docs = load_docs(corpus, getattr(self._cfg, "title_col", 2),
                         getattr(self._cfg, "intro_col", -1))
        self._n_docs: int = len(docs)
        self._ctx, self._words = build_scan_ctx(docs, self._cfg)
        self._wordnames: List[str] = [w.word for w in self._words]
        self._cols: Dict[str, dict] = compute_all(self._ctx, self._cfg, registry)
        self._available: Set[str] = set(ALL_COLUMNS)

    # ----------------------------------------------------------- 配置变更入口
    def set_cfg(self, cfg_new: PipelineConfig):
        """按 Phase 4 plan() 自动选重算级别。

        FULL        → 从语料重建（候选集变）
        INCREMENTAL → 失效共享缓存 + 仅重算脏列，合并入内存表
        QUERY       → 仅更新阈值，信号列一行不动
        """
        if self._ctx is None:
            raise RuntimeError("本 SignalBank 由 from_dump 只读恢复，无法重算；"
                               "请改用 SignalBank(corpus, cfg) 重建")
        kind, dirty = plan(self._cfg, cfg_new, self._registry)
        if kind == "FULL":
            docs = load_docs(self._corpus,
                             getattr(cfg_new, "title_col", 2),
                             getattr(cfg_new, "intro_col", -1))
            self._ctx, self._words = build_scan_ctx(docs, cfg_new)
            self._wordnames = [w.word for w in self._words]
            self._cols = compute_all(self._ctx, cfg_new, self._registry)
        elif kind == "INCREMENTAL":
            _kind, _d, new_cols = incremental_recompute(
                self._ctx, self._cfg, cfg_new, self._registry)
            # new_cols 只含脏列；合并覆盖进内存表
            for col, vals in new_cols.items():
                self._cols[col] = vals
        # QUERY：不重算
        self._cfg = cfg_new
        return kind

    # ----------------------------------------------------------- 查询接口
    def kept_for(self, **thresholds) -> Set[str]:
        """任意闸门阈值组合，毫秒级返回保留词集合。

        thresholds：gate 参数名（min_ent/min_cohesion/min_indep/min_role/
        min_asym/asym_rescue/role_rescue/spe_rescue/rsr_rescue）显式覆盖当前 cfg。
        """
        cfg = dataclasses.replace(self._cfg, **thresholds) if thresholds else self._cfg
        return kept_for(self._wordnames, self._cols, cfg, self._gates, self._available)

    def columns(self) -> Dict[str, dict]:
        """返回全部信号列 {列名: {word: float}}。"""
        return self._cols

    @property
    def wordnames(self) -> List[str]:
        """候选词名列表（kept_for 的输入）。"""
        return self._wordnames

    @property
    def cfg(self) -> PipelineConfig:
        """当前生效配置。"""
        return self._cfg

    def margin_audit(self, margin_window: float = 0.5, **thresholds) -> List[dict]:
        """敏感词余量表：保留词中，距任一活跃闸门阈值余量 < margin_window 的词。

        返回 [{word, signal, value, threshold, margin}]，按 margin 升序。
        用于"救援门再调一点会掉哪些真词"的体检。
        """
        cfg = dataclasses.replace(self._cfg, **thresholds) if thresholds else self._cfg
        ths = []
        for param, gate in GATE_BY_PARAM.items():
            t = getattr(cfg, param, 0)
            if t > 0:
                ths.append((gate.signal, t))
        if not ths:
            return []
        out = []
        for w in self._wordnames:
            best = None
            for sig, t in ths:
                v = self._cols.get(sig, {}).get(w, SIGNAL_BY_COLUMN[sig].sentinel)
                if 0 <= v:
                    d = v - t
                    if best is None or d < best[1]:
                        best = (sig, d, v, t)
            if best and best[1] < margin_window:
                out.append({"word": w, "signal": best[0], "value": best[2],
                            "threshold": best[3], "margin": best[1]})
        out.sort(key=lambda r: r["margin"])
        return out

    # ----------------------------------------------------------- 可选持久化
    def dump(self, out_path) -> dict:
        """把内存信号表写成 dump v2 schema（可选序列化，跨进程/重启用）。"""
        snapshot = {
            "ent_merge_ratio": getattr(self._cfg, "ent_merge_ratio", 0.25),
            "no_punct_ent": getattr(self._cfg, "no_punct_ent", False),
            "no_merge": getattr(self._cfg, "no_merge", False),
            "cohesion_max_len": getattr(self._cfg, "cohesion_max_len", 8),
            "min_super_cnt": getattr(self._cfg, "min_super_cnt", 2),
            "rsr_mode": getattr(self._cfg, "rsr_mode", "mean"),
            "role_max_depth": getattr(self._cfg, "role_max_depth", -1),
            "role_alpha": getattr(self._cfg, "role_alpha", 0.85),
        }
        import datetime as _dt
        records = []
        for w in self._words:
            rec = {"word": w.word, "count": int(w.count)}
            for col in ALL_COLUMNS:
                rec[col] = round(self._cols.get(col, {}).get(w.word,
                                  SIGNAL_BY_COLUMN[col].sentinel), 6)
            records.append(rec)
        doc = {
            "schema": 2,
            "meta": {
                "corpus": os.path.basename(self._corpus) if self._corpus else "",
                "n_docs": self._n_docs if getattr(self, "_n_docs", None) else 0,
                "n_candidates": len(self._words),
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

    @classmethod
    def from_dump(cls, path, registry=REGISTRY, gates=GATES):
        """从 dump v2 只读恢复（无 ctx，set_cfg 会报错；仅供查询/共享）。"""
        from .dump_v2 import from_json
        words, cols, available, schema = from_json(path)
        # 重建 cfg：快照只含 scan+信号参数（闸门是"纯查表"，不在信号表内）。
        # 以 bank_default_cfg（基线 AND 链）为底，用快照覆盖 scan+信号参数，
        # 这样恢复出的 cfg 与建表时一致（闸门默认 = 基线 AND）。
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)["meta"]["cfg_snapshot"]
        cfg = bank_default_cfg()
        for k, v in snap.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        bank = cls.__new__(cls)
        bank._corpus = None
        bank._cfg = cfg
        bank._registry = registry
        bank._gates = gates
        bank._ctx = None
        bank._words = None
        bank._wordnames = words
        bank._cols = cols
        bank._available = available
        return bank

    # ----------------------------------------------------------- 表示
    def __repr__(self):
        return (f"SignalBank(corpus={os.path.basename(self._corpus) if self._corpus else '—'}, "
                f"n={len(self._wordnames)}, cfg=min_super_cnt={getattr(self._cfg,'min_super_cnt',2)})")


__all__ = ["SignalBank", "bank_default_cfg"]
