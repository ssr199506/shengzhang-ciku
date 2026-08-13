"""grow3.signals.cohesion —— 凝固度 PMI（内部紧密度）。Step 3 落地。

规则（来自 2.1.17 / 2.3.1）：
- len<2 或 len>cohesion_max_len(8) → 0.0（N/A 放行）；
- 否则取所有切分点最小 PMI：log2(c_w * N_char / (cl * cr))。

依赖 IR 的 ngram_freq 与 n_char。信号只算值，过滤归闸门。

Step 1 仅放空壳。
"""
from __future__ import annotations

from ..ir import ScanContext


def cal_cohesion(ctx: ScanContext, max_len: int = 8) -> dict:
    """返回 {word: 凝固度 PMI}。Step 3 落地。"""
    ...
