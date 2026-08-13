"""grow3.signals.indep —— 词本身偏序（候选/位置结构零成本复用）。Step 4 落地。

规则（来自 2.3.3）：
- 建 pos_start（位置 → 候选词倒排）；
- 对每个超词 s 的每次出现，标记内部子候选被覆盖（covered_occ 去重，key=(sub,q)）；
- indep = (count_w - covered) / count_w；
- 覆盖判定完全照抄 2.3.3 去重逻辑，否则数字对不上。

Step 1 仅放空壳。
"""
from __future__ import annotations

from ..ir import ScanContext


def cal_indep(ctx: ScanContext, super_min: int = 1) -> dict:
    """返回 {word: indep 偏序值}，-1.0 表示豁免。Step 4 落地。"""
    ...
