"""grow3.signals.cohesion —— 凝固度 PMI（内部紧密度）。Step 3 落地。

逐字照抄 2.1.17 scan_and_grow 的凝固度计算：取所有切分点最小 PMI
    min_split log2(count(w)·N_char / (count左·count右))
值越大说明内部字间绑定越强（越像一个词）；len<2 或 >max_len 时为 N/A(0.0)。

依赖 IR 的 ngram_freq 与 n_char（由 scan_once 用 build_ngram_freq 一次性算出）。
信号只算值，过滤归闸门（见 gates.gate_chain 的 min_cohesion）。
"""
from __future__ import annotations

import math
from typing import Dict

from ..ir import ScanContext


def cal_cohesion(ctx: ScanContext, max_len: int = 8) -> Dict[str, float]:
    """返回 {word: 凝固度 PMI}。N/A（len<2 或超长）为 0.0。只读 ctx。"""
    result: Dict[str, float] = {}
    if ctx.n_char <= 0:
        for w in ctx.cand_lst:
            result[w] = 0.0
        return result

    for w in ctx.cand_lst:
        if len(w) < 2 or len(w) > max_len:
            result[w] = 0.0  # N/A
            continue
        c_w = ctx.ngram_freq.get(w, ctx.cand_count.get(w, 0))
        coh = float('inf')
        for k in range(1, len(w)):
            left = w[:k]
            right = w[k:]
            cl = ctx.ngram_freq.get(left, 0)
            cr = ctx.ngram_freq.get(right, 0)
            if cl == 0 or cr == 0:
                coh = float('-inf')
                break
            pmi = math.log2(c_w * ctx.n_char / (cl * cr))
            if pmi < coh:
                coh = pmi
        if coh != float('inf'):
            result[w] = coh
        else:
            result[w] = 0.0
    return result
