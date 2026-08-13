"""grow3.signals.ent —— 复合熵（横向外部邻居）。Step 2 落地。

完全照抄 main grow.py 的复合熵决策逻辑（2.1.10 按用户最终规则），
但改为**只读 ScanContext** 重算：从 ctx.cand_lst[w] 重新求左右邻分布，
再套用与 main 完全相同的判据树。这样熵计算与扫描天然可分，
且任何一步破坏不变式都能被回归矩阵立刻发现。

判据树（与 main scan_and_grow 第 209-243 行逐字对应）：
  1) 两侧都无汉字邻居 → -1.0 豁免
  2) 仅一侧有汉字邻居 → 只用该侧（含该侧 PUNCT）算熵；若该侧不空 < ENT_MIN_DATA → 豁免
  3) 两侧都有汉字邻居：
     a) 少侧不空 / 多侧不空 < ent_merge_ratio → 合并两侧算总熵
     b) 否则 → min(左熵, 右熵)
"""
from __future__ import annotations

import math
from typing import Dict

from ..ir import ScanContext
from ..scan import SEP, PUNCT, ENT_MIN_DATA

ENT_MERGE_RATIO = 0.25


def _entropy_from_vals(vals):
    total = sum(vals)
    if total == 0:
        return 0.0
    ent = 0.0
    for v in vals:
        p = v / total
        ent -= p * math.log2(p)
    return ent


def cal_ent(ctx: ScanContext, ent_merge_ratio: float = ENT_MERGE_RATIO) -> Dict[str, float]:
    """返回 {word: 复合熵}，-1.0 表示豁免。只读 ctx，逐字复刻 main 逻辑。"""
    S = ctx.S
    wgt = ctx.wgt
    n = len(S)
    result: Dict[str, float] = {}

    def right_dist(w, pos_list):
        groups = {}
        boundary = 0
        punct = 0
        lw = len(w)
        for p in pos_list:
            rp = p + lw
            if rp >= n or S[rp] == SEP:
                boundary += wgt[p]
            elif S[rp] == PUNCT:
                boundary += wgt[p]
                punct += wgt[p]
            else:
                c = S[rp]
                g = groups.get(c)
                if g is None:
                    groups[c] = [[p], wgt[p]]
                else:
                    g[0].append(p)
                    g[1] += wgt[p]
        return groups, boundary, punct

    def left_dist(pos_list):
        groups = {}
        boundary = 0
        punct = 0
        for p in pos_list:
            if p == 0 or S[p - 1] == SEP:
                boundary += wgt[p]
            elif S[p - 1] == PUNCT:
                boundary += wgt[p]
                punct += wgt[p]
            else:
                c = S[p - 1]
                groups[c] = groups.get(c, 0) + wgt[p]
        return groups, boundary, punct

    for w, lst in ctx.cand_lst.items():
        groups, boundary, r_punct = right_dist(w, lst)
        l_groups, l_boundary, l_punct = left_dist(lst)

        l_cjk = list(l_groups.values())
        r_cjk = [wsum for _, (_, wsum) in groups.items()]
        l_han = sum(l_cjk)
        r_han = sum(r_cjk)
        l_full = l_cjk + ([l_punct] if l_punct > 0 else [])
        r_full = r_cjk + ([r_punct] if r_punct > 0 else [])
        l_non = l_han + l_punct
        r_non = r_han + r_punct

        if l_han == 0 and r_han == 0:
            compound_ent = -1.0
        elif l_han == 0:
            compound_ent = -1.0 if r_non < ENT_MIN_DATA else _entropy_from_vals(r_full)
        elif r_han == 0:
            compound_ent = -1.0 if l_non < ENT_MIN_DATA else _entropy_from_vals(l_full)
        elif ent_merge_ratio > 0 and min(l_non, r_non) / max(l_non, r_non) < ent_merge_ratio:
            compound_ent = _entropy_from_vals(l_full + r_full)
        else:
            compound_ent = min(_entropy_from_vals(l_full), _entropy_from_vals(r_full))

        result[w] = compound_ent

    return result
