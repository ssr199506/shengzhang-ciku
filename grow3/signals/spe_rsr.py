"""grow3.signals.spe_rsr —— 超词位置熵(SPE) + 补集偏序(RSR)（Step 5 落地，等价 2.4.1/2.4.2）。

两信号共用一次「超词包含结构」遍历，互不依赖但同源：

  Super(w) = {更长候选词 s | w 是 s 的子串}（s 需 cnt>=min_super_cnt 且 len(s)>=3）。

  SPE（第四信号·结构维度，看「在包含结构里的角色」）：
    对每个超词 s，w 在 s 中的相对位置分三类 前缀(0)/中缀(1)/后缀(2)，
    按超词语料频次 count(s) 加权累加到各位置桶；位置熵 = 各位置桶权重分布的熵。
      spe<0 (无合格超词)   → 多半是完整独立词 → 结构豁免(留)
      spe≈0 (有超词恒一位) → 焊死单一位(词缀碎片) → 滤
      spe高 (有超词且多样) → 不同构词位自由拼装(真构词件) → 留

  RSR（第五信号·互补偏序，补集泛用度）：
    w 在 s 中的补集 = 扣掉 w 剩余(左补 s[:a]/右补 s[b:]，可空)；
    补集 r 自身也处于偏序，泛用度 U(r)=把 r 当补集的不同超词数(越虚越高)；
    RSR(w) = Σ count(s)·combine(U(左补),U(右补)) / Σ count(s)，combine=mean|max。
      rsr<0 (无合格超词)   → 结构豁免(留)
      rsr高 (补集泛用度高) → 主干(首富:补集从/成) → 留
      rsr低 (补集专用实词) → 附件(联盟之:补集王者) → 滤

逐字照抄 grow_242.py 第 257–321 行（含 grow_241 的 SPE 公式）；
去重 key=sub（同一超词内每子串只计一次），保证数字与历史分支逐字一致。

救援门语义（见 gates.gate_chain）：spe_rescue 从熵门漏杀中捞回 spe>=ε；
rsr_rescue 与 spe 取 AND（非并列闸门）。golden: v241=5895 / v242=5889。
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from ..ir import ScanContext


def _build_super(ctx: ScanContext, min_super_cnt: int, rsr_mode: str
                 ) -> Tuple[Dict[str, List[float]], Dict[str, list], Dict[str, set]]:
    """一次遍历建超词包含结构，返回 (spe_super, rsr_info, contain_cnt)。

    spe_super[w] = [前缀权, 中缀权, 后缀权]
    rsr_info[w]  = [(左补, 右补, 超词频次), ...]
    contain_cnt[r] = set(把 r 当补集的超词 s)（补集泛用度 U(r)=len(contain_cnt[r])）
    """
    cand_count = ctx.cand_count
    cand_set = set(cand_count)
    spe_super: Dict[str, List[float]] = {}
    contain_cnt: Dict[str, set] = {}
    rsr_info: Dict[str, list] = {}
    for s, cnt_s in cand_count.items():
        if cnt_s < min_super_cnt or len(s) < 3:
            continue                     # 频次不足/太短无法容纳更长子串 → 不作超词
        seen = set()
        L = len(s)
        for a in range(L):
            for b in range(a + 1, L + 1):    # 含单字(补集常为单字)，但子串需多字才入候选
                sub = s[a:b]
                if sub in cand_set and len(sub) >= 2 and sub != s and sub not in seen:
                    seen.add(sub)
                    pos = 0 if a == 0 else (2 if b == L else 1)
                    bucket = spe_super.setdefault(sub, [0, 0, 0])
                    bucket[pos] += cnt_s
                    left = s[:a]
                    right = s[b:]
                    rsr_info.setdefault(sub, []).append((left, right, cnt_s))
                    if left:
                        contain_cnt.setdefault(left, set()).add(s)
                    if right:
                        contain_cnt.setdefault(right, set()).add(s)
    return spe_super, rsr_info, contain_cnt


def _spe_of(word: str, spe_super: Dict[str, List[float]]) -> float:
    bucket = spe_super.get(word)
    tot = (bucket[0] + bucket[1] + bucket[2]) if bucket else 0
    if tot == 0:
        return -1.0                      # 无合格超词 → 结构豁免
    probs = [x / tot for x in bucket if x > 0]
    return -sum(p * math.log2(p) for p in probs) if len(probs) > 1 else 0.0


def _rsr_of(word: str, rsr_info: Dict[str, list], contain_cnt: Dict[str, set], rsr_mode: str) -> float:
    pairs = rsr_info.get(word)
    if not pairs:
        return -1.0                      # 无合格超词 → 结构豁免
    tot = 0.0
    acc = 0.0
    for left, right, cnt_s in pairs:
        vals: List[int] = []
        if left:
            vals.append(len(contain_cnt.get(left, ())))   # .get(..,()) → 空元组，len=0
        if right:
            vals.append(len(contain_cnt.get(right, ())))
        u = (max(vals) if rsr_mode == 'max'
             else (sum(vals) / len(vals) if vals else 0))
        tot += cnt_s
        acc += cnt_s * u
    return acc / tot if tot > 0 else -1.0


def cal_spe_rsr(ctx: ScanContext, min_super_cnt: int = 2, rsr_mode: str = 'mean'
                 ) -> Tuple[Dict[str, float], Dict[str, float]]:
    """联合计算 SPE 与 RSR（一次遍历），返回 (spe_map, rsr_map)。"""
    spe_super, rsr_info, contain_cnt = _build_super(ctx, min_super_cnt, rsr_mode)
    spe_map = {w: _spe_of(w, spe_super) for w in ctx.cand_count}
    rsr_map = {w: _rsr_of(w, rsr_info, contain_cnt, rsr_mode) for w in ctx.cand_count}
    return spe_map, rsr_map


def cal_spe(ctx: ScanContext, min_super_cnt: int = 2) -> Dict[str, float]:
    """返回 {word: SPE}，等价 2.4.1。"""
    return cal_spe_rsr(ctx, min_super_cnt, 'mean')[0]


def cal_rsr(ctx: ScanContext, min_super_cnt: int = 2, rsr_mode: str = 'mean') -> Dict[str, float]:
    """返回 {word: RSR}，等价 2.4.2（combine 模式由 rsr_mode 决定）。"""
    return cal_spe_rsr(ctx, min_super_cnt, rsr_mode)[1]
