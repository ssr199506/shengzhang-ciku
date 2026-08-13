"""grow3.gates —— 过滤链 + 救援门（按 PipelineConfig 组装）。Step 3-5 落地。

语义：先跑 AND 过滤链（ent → cohesion → indep），再对"被滤集"跑条件救援门
（spe_rescue / rsr_rescue）。救援门是"条件闸门"，依赖过滤前后中间态，
**绝不能**把救援写成与过滤并列的独立闸门（会破坏语义）。

- ent 门：min_ent<=0 或 ent>=th（或 ent==-1 豁免）
- cohesion 门：min_cohesion<=0 或 coh>=th（或 len<2 豁免）
- indep 联合门：min_indep<=0 或 indep>=th（与 cohesion 取 AND）
- spe_rescue：熵门滤掉的词，若 spe>=th → 捞回
- rsr_rescue：与 spe_rescue 取 AND（spe>=th 且 rsr>=th）→ 捞回

Step 1 仅放空壳。
"""
from __future__ import annotations

from typing import List

from .ir import Word


def gate_chain(words: List[Word], cfg) -> List[Word]:
    """返回最终保留词表。Step 3-5 落地。"""
    ...
