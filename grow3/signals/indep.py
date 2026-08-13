"""grow3.signals.indep —— 词本身偏序：独立频次占比（Step 4 落地，等价 2.3.3）。

定义 w 的「偏序独立频次」= 不被任何更长候选词覆盖的出现次数（按权重）：
    covered(w) = Σ 被更长候选 s 包裹的 w 出现权重；
    indep_ratio(w) = (count_w - covered(w)) / count_w  ∈ [0,1]。

强搭配碎片（我只/聊天/我真/罗之）几乎总嵌在更长候选里 → indep≈0；
真词（世界/开始）大量独立出现 → indep 高（≥0.13）；
词缀型碎片（我的/联盟之）超词稀疏未被候选 → indep 仍高（补集偏序留待下版）。

覆盖判定逐字照抄 grow_233.py 第 324–356 行：
- 对每个超词 s 的每次出现 [p, p+len(s))，遍历其内部每个起点 q 落在该次出现内的子候选 sub；
- 去重 key=(sub, q)：同一 sub 的同一位置出现只计一次覆盖权重（否则数字对不上）；
- 保证与历史分支产词逐字一致。

2.3.3 的 indep_super_min 形参当时未实际生效（覆盖判定遍历全部候选超词），
此处保留为 super_min 以备未来按超词频次裁剪，默认 1 不改变历史行为。
"""
from __future__ import annotations

from typing import Dict

from ..ir import ScanContext


def cal_indep(ctx: ScanContext, super_min: int = 1) -> Dict[str, float]:
    """返回 {word: indep_ratio}，indep_ratio ∈ [0,1]；无更长词包裹时 = 1.0。

    super_min 仅作为保留形参；2.3.3 语义下恒取全部候选超词（=1 即不过滤）。
    """
    cand_lst = ctx.cand_lst
    wgt = ctx.wgt
    cand_count = ctx.cand_count

    # 位置 -> [(子候选词, 词长), ...]（倒排，O(1) 查某起点出现的候选）
    pos_start: Dict[int, list] = {}
    for w, lst in cand_lst.items():
        for p in lst:
            pos_start.setdefault(p, []).append((w, len(w)))

    # 覆盖累计：对每个超词 s 的每次出现，内部起点 q 落在其内、
    # 且 q+len(sub) <= p+len(s) 的子候选 sub 视为被本次出现覆盖。
    covered: Dict[str, float] = {}
    covered_occ = set()
    for s, lst_s in cand_lst.items():
        Ls = len(s)
        for p in lst_s:
            for q in range(p, p + Ls):
                for sub, sublen in pos_start.get(q, []):
                    if sub == s:
                        continue
                    if q + sublen <= p + Ls:
                        key = (sub, q)
                        if key not in covered_occ:
                            covered_occ.add(key)
                            covered[sub] = covered.get(sub, 0) + wgt[q]

    result: Dict[str, float] = {}
    for w, count_w in cand_count.items():
        cov = covered.get(w, 0.0)
        indep_ratio = (count_w - cov) / count_w if count_w > 0 else 0.0
        result[w] = indep_ratio
    return result
