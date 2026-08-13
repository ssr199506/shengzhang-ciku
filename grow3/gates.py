"""grow3.gates —— 过滤链 + 救援门（按 PipelineConfig 组装）。Step 2 起逐步落地。

语义（方案书 Step 5）：
- 先跑 AND 过滤链：ent → cohesion → indep（逐层取交集，每级记录审计）。
- 再对"被滤集"跑**条件救援门**：spe_rescue / rsr_rescue（依赖过滤前后中间态）。
- 救援门是"条件闸门"，**绝不能**与过滤并列独立（会破坏语义）。

各门开关由 cfg 阈值控制；阈值 <=0 表示该门关闭（放行全部）。
Step 2 只开 ent 门（min_ent=0.5），其余阈值默认 0 → 放行，行为等价于 main 5865。

审计（Step 7）：传入 audit: AuditLog 时，每级闸门记录 before/after/removed/rescued，
供 `cli --audit` 输出 JSON，定位"单个词在哪级被滤/被救"。
"""
from __future__ import annotations

from typing import List, Optional

from .config import PipelineConfig
from .ir import Word
from .probe import AuditLog, AuditStage


def gate_chain(words: List[Word], cfg: PipelineConfig,
               audit: Optional[AuditLog] = None) -> List[Word]:
    """返回最终保留词表；audit 非空时写各级审计。"""
    cur: List[Word] = list(words)     # 当前 AND 链保留集
    filtered: List[Word] = []         # 被任一 AND 门滤掉的词（救援门输入）

    # ---- 复合熵门 ----
    if cfg.min_ent > 0:
        passed, removed = [], []
        for w in cur:
            if w.ent < 0 or w.ent >= cfg.min_ent:
                passed.append(w)
            else:
                removed.append(w)
        if audit is not None:
            audit.stages.append(AuditStage(
                "ent", len(cur), len(passed), removed=[w.word for w in removed]))
        filtered.extend(removed)
        cur = passed

    # ---- 凝固度门（与 ent 取 AND）----
    if cfg.min_cohesion > 0:
        passed, removed = [], []
        for w in cur:
            if len(w.word) < 2 or w.cohesion >= cfg.min_cohesion:
                passed.append(w)
            else:
                removed.append(w)
        if audit is not None:
            audit.stages.append(AuditStage(
                "cohesion", len(cur), len(passed), removed=[w.word for w in removed]))
        filtered.extend(removed)
        cur = passed

    # ---- 词本身偏序门（与凝固度取 AND）----
    if cfg.min_indep > 0:
        passed, removed = [], []
        for w in cur:
            if w.indep < 0 or w.indep >= cfg.min_indep:
                passed.append(w)
            else:
                removed.append(w)
        if audit is not None:
            audit.stages.append(AuditStage(
                "indep", len(cur), len(passed), removed=[w.word for w in removed]))
        filtered.extend(removed)
        cur = passed

    # ---- 条件救援门（从被滤集中捞回）----
    if cfg.spe_rescue > 0:
        rescued, still = [], []
        for w in filtered:
            if w.spe < 0:
                still.append(w)            # 无超词→结构豁免但不救（无法判位置多样）
                continue
            ok = w.spe >= cfg.spe_rescue
            if cfg.rsr_rescue > 0:
                ok = ok and (w.rsr >= 0 and w.rsr >= cfg.rsr_rescue)
            (rescued if ok else still).append(w)
        if audit is not None:
            audit.stages.append(AuditStage(
                "spe_rescue", len(filtered), len(rescued),
                rescued=[w.word for w in rescued]))
        cur = cur + rescued

    return cur
