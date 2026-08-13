"""grow.py —— 3.0-unified 兼容层（薄封装 grow3）。

历史工具（verify.py / tune_bind.py / exp/probe_words.py）与文档均以 `grow.scan_and_grow`
等历史 API 调用本模块；此处把它们委托给 grow3，使「3.0 成为 main」——
根入口即是 grow3，而非另起一份独立实现。行为应与 2.1.11 baseline 逐词一致
（已由 verify.py 暴力对拍 + exp/golden 回归矩阵守护）。

查阅 2.1.11 真值源码见 exp/legacy/grow_v211_main.py（留档，不删）。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from grow3.scan import SEP, build_corpus, scan_once
from grow3.signals.ent import cal_ent


def scan_and_grow(S: str, wgt: dict, ent_merge_ratio: float = 0.25,
                  ent_punct_exempt: bool = True, min_super_cnt: int = 2
                  ) -> Tuple[List[tuple], Dict[str, int]]:
    """兼容历史签名：返回 (candidates, charfreq)。

    candidates: [(word, count, independent, binding, compound_entropy), ...]
    charfreq:   {char: 加权频次}
    """
    ctx, words = scan_once(S, wgt, ent_merge_ratio, ent_punct_exempt, 8)
    ent_map = cal_ent(ctx, ent_merge_ratio)
    candidates = [
        (wd.word, wd.count, wd.independent, wd.binding,
         ent_map.get(wd.word, -1.0))
        for wd in words
    ]
    return candidates, ctx.charfreq
