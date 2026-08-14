"""grow3.signals._super —— 公共超词包含结构索引（role / asym 的底层数据，一次遍历共享）。

门槛与 spe_rsr._build_super 保持一致：
  超词 s 需 cnt_s >= min_super_cnt 且 len(s) >= 3；
  子串 sub 需是候选词（len>=2，sub != s），同一超词内去重；
  补集 = s 扣除 sub 的左/右剩余（可为空，单字也计入）。

产出两份结构：
  super_info[w]   = [(左补, 右补, 超词频次), ...]      # w 的每个超词
  remain_domain[r] = {主干 w': 加权频次}                # 补集 r 的主干域（U2/role/asym 的叶子统计）

结果缓存于 ctx.super_info（ScanContext 既有辅助量字段），同一次扫描只遍历一次；
spe_rsr 不经过本工具（其内部自带 _build_super），二者互不干扰。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..ir import ScanContext

_CACHE_KEY = "_super_index"


def build_super_index(ctx: ScanContext, min_super_cnt: int = 2
                      ) -> Tuple[Dict[str, List[Tuple[str, str, float]]],
                                 Dict[str, Dict[str, float]]]:
    """返回 (super_info, remain_domain)。"""
    cached = ctx.super_info.get(_CACHE_KEY)
    if cached is not None:
        return cached
    cand_count = ctx.cand_count
    cand_set = set(cand_count)
    super_info: Dict[str, List[Tuple[str, str, float]]] = {}
    remain_domain: Dict[str, Dict[str, float]] = {}
    for s, cnt_s in cand_count.items():
        if cnt_s < min_super_cnt or len(s) < 3:
            continue                     # 频次不足/太短无法容纳更长子串 → 不作超词
        seen = set()
        L = len(s)
        for a in range(L):
            for b in range(a + 1, L + 1):
                sub = s[a:b]
                if sub in cand_set and len(sub) >= 2 and sub != s and sub not in seen:
                    seen.add(sub)
                    left = s[:a]
                    right = s[b:]
                    super_info.setdefault(sub, []).append((left, right, cnt_s))
                    if left:
                        d = remain_domain.setdefault(left, {})
                        d[sub] = d.get(sub, 0) + cnt_s
                    if right:
                        d = remain_domain.setdefault(right, {})
                        d[sub] = d.get(sub, 0) + cnt_s
    idx = (super_info, remain_domain)
    ctx.super_info[_CACHE_KEY] = idx
    return idx
