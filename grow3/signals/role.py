"""grow3.signals.role —— 偏序图角色迭代（含 U2 退化）。纯结构信号：虚词身份由偏序图涌现，零字典。

抽象（演进文档 11.3/11.4）：
  虚词 = 偏序图中几乎只作「附件」的节点（只修饰、从不被当作主体承载别的词）；
  role(w) ∈ [0,1] = 主干度：1=主干/真词，0=附件/虚词；无超词 → -1.0（结构豁免）。

骨架（对每个候选词，聚合其超词的「剩余虚度」）：
    evidence(w) = Σ_{s⊃w} cnt_s · VIRT(剩余 r) / Σ_{s⊃w} cnt_s
    VIRT(单段 r) = 1 − role(r)          # 剩余越虚 → w 越像主干
    VIRT(双段 l,r) = min(1−role(l), 1−role(r))   # 两段都得虚才可信（中缀主干）
    role ← (1−α)·role + α·evidence      # 阻尼迭代，α<1 保证收敛

初始帧（第 0 帧 = U2）：
    role⁰(r) = K / (|A(r)| + K)，A(r) = 补集 r 的主干域
    主干域大 → r 是通用虚词（从/之）→ role⁰ 低；主干域小 → r 是专用实词 → role⁰ 高。
    这是 RSR 的 U(r) 改为「主干域规模」后的归一化形态（避开补集常见字陷阱）。

深度语义（与用户确认）：
    max_depth=1  → 只输出第 0 帧 = U2
    max_depth=N  → 从 U2 出发迭代 N−1 轮（穿透 N 层偏序）
    max_depth=-1 → 迭代到不动点 = role∞
"""
from __future__ import annotations

from typing import Dict

from ..ir import ScanContext
from ._super import build_super_index

_DEFAULT_K = 10.0


def solve_roles(ctx: ScanContext, max_depth: int = -1, min_super_cnt: int = 2,
                alpha: float = 0.85, tol: float = 1e-4, K: float = _DEFAULT_K
                ) -> Dict[str, float]:
    """返回 {word: role}；无超词的候选词 → -1.0（豁免）。

    max_depth：1=U2，N=迭代 N 帧，-1=不动点。
    """
    super_info, remain_domain = build_super_index(ctx, min_super_cnt)
    cand_count = ctx.cand_count

    # ---- 第 0 帧 = U2：给每个补集 r 一个初始主干度（主干域越大 → 越虚 → 主干度越低）----
    role: Dict[str, float] = {}
    for r, domain in remain_domain.items():
        role[r] = K / (len(domain) + K)

    def virt(r: str) -> float:
        return 1.0 - role.get(r, 0.5)     # 剩余虚度；r 无先验按中性 0.5

    def evidence(w: str, pairs) -> float:
        tot = 0.0
        acc = 0.0
        for left, right, cnt_s in pairs:
            if left and right:
                v = min(virt(left), virt(right))
            elif left:
                v = virt(left)
            elif right:
                v = virt(right)
            else:
                v = 0.5
            tot += cnt_s
            acc += cnt_s * v
        return acc / tot if tot > 0 else 0.5

    # 参与迭代的候选词 = 有超词者；第 0 帧 = U2（直接用补集初始角色聚合一次，非均匀初值）
    actives = [w for w in cand_count if super_info.get(w)]
    for w in actives:
        role[w] = evidence(w, super_info[w])

    # max_depth=1 → 只输出第 0 帧（纯 U2），不进迭代
    if max_depth == 1:
        return {w: role.get(w, -1.0) for w in cand_count}

    max_rounds = -1 if max_depth < 0 else max(0, max_depth - 1)
    it = 0
    while True:
        diff = 0.0
        for w in actives:
            e = evidence(w, super_info[w])
            nv = (1.0 - alpha) * role[w] + alpha * e
            d = nv - role[w]
            if d < 0:
                d = -d
            if d > diff:
                diff = d
            role[w] = nv
        it += 1
        if max_rounds >= 0:
            if it >= max_rounds:
                break
        elif diff < tol:
            break

    return {w: role.get(w, -1.0) for w in cand_count}
