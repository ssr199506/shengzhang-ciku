"""grow3.gates —— 过滤链 + 救援门（按 PipelineConfig 组装）。Step 2 起逐步落地。

语义（方案书 Step 5）：
- 先跑 AND 过滤链：ent → cohesion → indep（逐层取交集）。
- 再对"被滤集"跑**条件救援门**：spe_rescue / rsr_rescue（依赖过滤前后中间态）。
- 救援门是"条件闸门"，**绝不能**与过滤并列独立（会破坏语义）。

各门开关由 cfg 阈值控制；阈值 <=0 表示该门关闭（放行全部）。
Step 2 只开 ent 门（min_ent=0.5），其余阈值默认 0 → 放行，行为等价于 main 5865。
后续 Step 3/4/5 接入信号并抬阈后，本函数无需改结构即可生效。
"""
from __future__ import annotations

from typing import List, Tuple

from .config import PipelineConfig
from .ir import Word


def gate_chain(words: List[Word], cfg: PipelineConfig) -> List[Word]:
    """返回最终保留词表。"""
    # ---- AND 过滤链 ----
    kept: List[Word] = []
    filtered: List[Word] = []
    for w in words:
        ok = True
        # 复合熵门
        if cfg.min_ent > 0:
            if not (w.ent < 0 or w.ent >= cfg.min_ent):
                ok = False
        # 凝固度门（与 ent 取 AND）
        if ok and cfg.min_cohesion > 0:
            if not (len(w.word) < 2 or w.cohesion >= cfg.min_cohesion):
                ok = False
        # 词本身偏序门（与凝固度取 AND）
        if ok and cfg.min_indep > 0:
            if not (w.indep < 0 or w.indep >= cfg.min_indep):
                ok = False
        if ok:
            kept.append(w)
        else:
            filtered.append(w)

    # ---- 条件救援门（从被滤集中捞回）----
    if cfg.spe_rescue > 0:
        rescued: List[Word] = []
        still_filtered: List[Word] = []
        for w in filtered:
            if w.spe < 0:
                still_filtered.append(w)
                continue
            ok_rescue = w.spe >= cfg.spe_rescue
            if cfg.rsr_rescue > 0:
                ok_rescue = ok_rescue and (w.rsr >= 0 and w.rsr >= cfg.rsr_rescue)
            if ok_rescue:
                rescued.append(w)
            else:
                still_filtered.append(w)
        kept = kept + rescued
        filtered = still_filtered

    return kept
