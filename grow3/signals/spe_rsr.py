"""grow3.signals.spe_rsr —— 超词结构 SPE + 补集偏序 RSR（一次超词遍历同时算）。Step 5 落地。

规则（来自 2.4.1 / 2.4.2）：
- 对每个超词 s（count>=2, len>=3），遍历所有子串 sub（len>=2）：
    spe_super[sub] 位置桶累加（前缀0/中缀1/后缀2）
    rsr_info[sub].append((left, right, cnt_s))
    contain_cnt[补集].add(s)
- SPE = 超词位置熵（纵向包含秩序）；RSR = 补集偏序。

关键：从 IR（cand_count）重算零误差，证明扫描与信号天然可分。
RSR 明确不作自动过滤闸门，只作救援 AND 条件 / 辅助列（2.4.2 结论）。

Step 1 仅放空壳。
"""
from __future__ import annotations

from ..ir import ScanContext


def cal_spe(ctx: ScanContext) -> dict:
    """返回 {word: SPE}。Step 5 落地。"""
    ...


def cal_rsr(ctx: ScanContext, mode: str = "mean") -> dict:
    """返回 {word: RSR}。mode ∈ {mean, max}。Step 5 落地。"""
    ...
