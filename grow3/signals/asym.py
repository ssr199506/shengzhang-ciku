"""grow3.signals.asym —— 不对称性判据（= 条件熵增益，复合熵的逆）。纯结构、零字典。

对 w 的每个超词 s（剩余 r），测「谁依赖谁」：
  H(r|w)：给定主干 w，单段剩余 r 的分布熵（左右平均）——与复合熵同源的"外部自由度"视角
  H(w|r)：给定剩余 r，主干 w 的分布熵（左右平均）——r 的主干域多样性
  asym(w) = H(w|r) − H(r|w)

方向（实测 8887 本确定）：**大正 = 补集是虚词 + w 被少数虚词修饰（首富←从/成）**，
即"被虚词修饰的主干"特征——000 层真词（首富/庆余年/康熙/明月/铁血）asym 全部 ≥2.3，
而碎片（联盟之 0.2 / 我的 -2.5 / 聊天 -0.9）都达不到。
→ asym 定位为**救援信号**（从熵门被滤集中捞回 asym 大正的候选），不是过滤信号。

数学上 H(w,r) = H(w|r) + H(r|w)，复合熵只看 H(r|w) 一项，本模块补齐另一半。
无超词 → -1.0（结构豁免）。
"""
from __future__ import annotations

import math
from typing import Dict

from ..ir import ScanContext
from ._super import build_super_index


def _ent(dist: Dict[str, float]) -> float:
    tot = sum(dist.values())
    if tot <= 0:
        return 0.0
    return -sum((v / tot) * math.log2(v / tot) for v in dist.values())


def _side_ent(left: str, right: str, cnt_s: float,
              dist_l: Dict[str, float], dist_r: Dict[str, float]) -> None:
    if left:
        dist_l[left] = dist_l.get(left, 0.0) + cnt_s
    if right:
        dist_r[right] = dist_r.get(right, 0.0) + cnt_s


def cal_asym(ctx: ScanContext, min_super_cnt: int = 2) -> Dict[str, float]:
    """返回 {word: asym}；无超词 → -1.0。"""
    super_info, remain_domain = build_super_index(ctx, min_super_cnt)
    result: Dict[str, float] = {}

    for w, pairs in super_info.items():
        # H(r|w)：单段剩余（左/右）分布熵，左右平均
        dist_l: Dict[str, float] = {}
        dist_r: Dict[str, float] = {}
        for left, right, cnt_s in pairs:
            _side_ent(left, right, cnt_s, dist_l, dist_r)
        ents = [e for e in (_ent(dist_l), _ent(dist_r)) if e >= 0]
        h_r_given_w = sum(ents) / len(ents) if ents else 0.0

        # H(w|r)：对每个单段剩余 r，查其主干域分布熵，按频次加权左右平均
        tot = 0.0
        acc = 0.0
        for left, right, cnt_s in pairs:
            if left:
                d = remain_domain.get(left)
                acc += cnt_s * (_ent(d) if d else 0.0)
                tot += cnt_s
            if right:
                d = remain_domain.get(right)
                acc += cnt_s * (_ent(d) if d else 0.0)
                tot += cnt_s
        h_w_given_r = acc / tot if tot > 0 else 0.0

        result[w] = h_w_given_r - h_r_given_w

    for w in ctx.cand_count:
        result.setdefault(w, -1.0)
    return result
