"""grow3.scan —— 语料构建 + 一次扫描（Step 2 落地）。

把 main 的 ``scan_and_grow`` 从"扫描 + 复合熵内联"拆成：
- ``scan_once(S, wgt)``：只做 BFS 生长，产出统一 IR（ScanContext），**不含任何信号值**；
- 信号值（复合熵等）由 ``signals/*.py`` 只读 IR 计算（见 signals/ent.py）。

关键不变式（方案书 Step 2）：默认参数下产词必须与 main 5865 逐字一致。
改的是工程结构，不是算法行为 —— 本文件的 BFS / 独立判定 / 边界逻辑
逐字照抄 main grow.py 的 scan_and_grow，仅把熵计算外移。
"""
from __future__ import annotations

import math
import re
from collections import deque
from typing import Dict, List, Tuple

from .ir import ScanContext, Word

# ---- 与 main 完全一致的常量 ----
SEP = '\x00'                       # 字段/run 边界（空：不参与熵、不生长）
PUNCT = '\ue000'                   # 标点哨兵：所有非 CJK 抽象成的同一「特殊汉字」
ENT_MERGE_RATIO = 0.25             # 复合熵合并触发比（默认）
ENT_MIN_DATA = 3                   # 单侧不空次数 < 此值 → 数据不足豁免
CJK_RE = re.compile(r'[\u4e00-\u9fff]+')


# ---------------------------------------------------------------- 清洗层
def clean(text: str, use_punct: bool = True) -> str:
    """CJK 逐字保留；非 CJK 抽象为同一个 PUNCT 哨兵（或 SEP 连接，use_punct=False）。"""
    t = text or ''
    if not t:
        return ''
    if use_punct:
        return re.sub(r'[^\u4e00-\u9fff]', PUNCT, t)
    runs = CJK_RE.findall(t)
    return SEP.join(runs)


def build_corpus(docs: List[Tuple[str, float]]):
    """docs: [(清洗后字段串, 权重)] → (拼接串 S, 位置权重数组 wgt)。"""
    parts = []
    wgt = []
    for field, w in docs:
        if not field:
            continue
        if parts:
            parts.append(SEP)
            wgt.append(1)
        parts.append(field)
        wgt.extend([w] * len(field))
    return ''.join(parts), wgt


def _wsum(pos_list, wgt):
    """按权重求出现次数。"""
    return sum(wgt[p] for p in pos_list)


# ---------------------------------------------------------------- 一次扫描
def scan_once(S: str, wgt: dict, ent_merge_ratio: float = ENT_MERGE_RATIO,
              ent_punct_exempt: bool = True) -> Tuple[ScanContext, List[Word]]:
    """单字种子 → 跳跃式 BFS 枚举最大重复 → 独立出现次数判据。

    返回 (ScanContext, words)：
    - ctx 承载跨信号共享的中间量（cand_lst/cand_count/charfreq/pos_single/n_char）；
    - words 是 Word 列表，已填 word/count/independent/binding，ent 暂为 -1.0，
      由 signals/ent.py 后续只读填充。

    ent_punct_exempt 当前恒为 True（PUNCT 恒作抽象邻居参与熵，不可关闭，与 main 一致），
    保留形参以对齐接口。
    """
    n = len(S)

    # 单字扫描：pos_single[char]=位置；charfreq 按权重累加
    pos_single: Dict[str, List[int]] = {}
    charfreq: Dict[str, int] = {}
    for p, ch in enumerate(S):
        if ch == SEP or ch == PUNCT:
            continue
        pos_single.setdefault(ch, []).append(p)
        charfreq[ch] = charfreq.get(ch, 0) + wgt[p]

    def right_dist(w, pos_list):
        """右邻分布：返回 (groups, boundary, punct)。
        groups: {右邻字符: ([位置], 加权和)}，仅真实 CJK 邻居；
        boundary: 右邻为边界(SEP/串尾/标点哨兵)的加权和（生长当墙）；
        punct: 右邻为标点哨兵 PUNCT 的加权和（熵当邻居）。"""
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
        """左邻分布（语义同 right_dist）。"""
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

    # BFS 队列：入队 (word, pos_list)，单字加权 count >= 2
    queue = deque()
    seen = set()
    for ch, plist in pos_single.items():
        if _wsum(plist, wgt) >= 2:
            queue.append((ch, plist))
            seen.add(ch)

    ctx_cand_lst: Dict[str, List[int]] = {}
    ctx_cand_count: Dict[str, int] = {}
    words: List[Word] = []

    while queue:
        w, lst = queue.popleft()
        # 跳跃：直到右最大（右邻含边界，或右邻字符种数 >=2）
        while True:
            groups, boundary, r_punct = right_dist(w, lst)
            if boundary > 0 or len(groups) >= 2:
                break
            c = next(iter(groups))
            w = w + c
            lst = groups[c][0]

        count_w = _wsum(lst, wgt)

        # 左最大检查
        l_groups, l_boundary, l_punct = left_dist(lst)
        if l_boundary == 0 and len(l_groups) < 2:
            continue  # 非左最大 → 剪枝

        # 独立出现次数
        L2 = {c for c, cnt in l_groups.items() if cnt >= 2}
        R2 = {c for c, (pl, wsum) in groups.items() if wsum >= 2}
        independent = 0
        lw = len(w)
        for p in lst:
            if p > 0 and S[p - 1] != SEP and S[p - 1] in L2:
                continue
            rp = p + lw
            if rp < n and S[rp] != SEP and S[rp] in R2:
                continue
            independent += wgt[p]

        # 前后集中度（binding）
        total_l = sum(l_groups.values())
        left_conc = (max(l_groups.values()) / total_l) if total_l > 0 else 0.0
        total_r = sum(w_ for _, w_ in groups.values())
        right_conc = (max(w_ for _, w_ in groups.values()) / total_r) if total_r > 0 else 0.0
        binding = max(left_conc, right_conc)

        if len(w) >= 2 and independent >= 1:
            words.append(Word(word=w, count=count_w, independent=independent, binding=binding))
            ctx_cand_lst[w] = lst
            ctx_cand_count[w] = count_w

        # 继续生长
        for c, (pl, wsum) in groups.items():
            if wsum >= 2:
                wc = w + c
                if wc not in seen:
                    seen.add(wc)
                    queue.append((wc, pl))

    ctx = ScanContext(
        S=S, wgt=wgt,
        cand_lst=ctx_cand_lst,
        cand_count=ctx_cand_count,
        charfreq=charfreq,
        pos_single=pos_single,
        n_char=len(charfreq),
    )
    return ctx, words
