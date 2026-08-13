"""grow3.signals.ent —— 复合熵（横向外部邻居）。Step 2 落地。

规则（来自 main / 2.1.11 定档）：
- 对候选词 w 的左/右邻居分布分别算熵；
- 判据 = min(左熵, 右熵)，低熵在左/右/两侧等价，两侧只要一边 < 阈值即滤；
- -1.0 表示无真实邻居证据（数据不足），视为豁免放行。

Step 1 仅放空壳。
"""
from __future__ import annotations

from ..ir import ScanContext


def cal_ent(ctx: ScanContext) -> dict:
    """返回 {word: 复合熵}，-1.0 表示豁免。Step 2 落地。"""
    ...
