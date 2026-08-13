#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生长词库 · 纯 Python 版
=======================
CSV(title, intro) → 去重加权 → 清洗纯CJK → 单字生长最大重复 → 独立出现次数判据
→ 词云 PNG + 词频表 CSV + 字频表 CSV

title / intro 为两条独立管线：共享全部逻辑，但各自输出、结果不混淆。

判据（独立出现次数 == 0 → 删）：
    对候选词 w，一次出现被更长候选词覆盖 ⟺ 左邻字符 c 满足 count(cw)≥2，
    或右邻字符 c' 满足 count(wc')≥2；run 首尾边界出现天然不算被覆盖。
    独立出现次数(w) = 未被覆盖的出现数（按权重计）；保留 iff ≥ 1。

用法：
    python grow.py <输入.csv> [--out DIR] [--top N] [--maxlen N] [--no-header] [--no-dedup]
"""

import argparse
import csv
import os
import re
import sys
import math
from collections import Counter

from interactive_cloud import CLOUD_W, CLOUD_H, emit_interactive


SEP = '\x00'      # 字段/run 边界（空：不参与熵、不生长）
PUNCT = '\ue000'  # 标点哨兵：所有非 CJK 字符抽象成的同一个「特殊汉字」；参与熵计算，但不作为词生长原料、不进入候选词/词云（显示引擎不输出它）
ENT_MERGE_RATIO = 0.25  # 复合熵「合并」触发比：两侧都有汉字邻居时，少侧不空/多侧不空 < 此值 → 合并两侧算总熵（0.20→0.25 调参优化：filt 率不变、误伤更少）
ENT_MIN_DATA = 3        # 只用单侧算熵时，该侧不空次数 < 此值 → 数据不足，不足以为据 → 豁免保留
CJK_RE = re.compile(r'[\u4e00-\u9fff]+')


# ---------------------------------------------------------------- 清洗层
def clean(text, use_punct=True):
    """CJK 汉字逐字保留；非 CJK 字符（标点/空白/数字/字母）抽象为同一个「特殊汉字」PUNCT。

    use_punct=True （默认）：每个非 CJK 字符 → 一个 PUNCT 哨兵（逐字符保留；
        "LPL史记" → "PUNCT PUNCT PUNCT 史记"，统计邻居时只取紧邻那一个，抽象层次等价）。
        PUNCT 参与熵计算（：×2+，×1+6×4 → PUNCT×7），但不作为词生长原料、不进入候选词/词云。
    use_punct=False（--no-punct-ent）：非 CJK 整体丢弃，run 间用 SEP 连接（等价 2.1.4 行为）。
    字段间连接由 build_corpus 用 SEP 完成（SEP=空，不参与熵）。"""
    t = text or ''
    if not t:
        return ''
    if use_punct:
        return re.sub(r'[^\u4e00-\u9fff]', PUNCT, t)
    runs = CJK_RE.findall(t)
    return SEP.join(runs)


def build_corpus(docs):
    """docs: [(清洗后字段串, 权重)] → (拼接串 S, 位置权重数组 wgt)。
    字段内 run 已用 SEP 连接；字段之间也用 SEP 分隔。
    SEP 位置给占位权重（扫描时跳过，永不读取）。"""
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


# ---------------------------------------------------------------- 凝固度支撑
def build_ngram_freq(S, wgt, max_len=8):
    """对语料做一次性加权 n-gram 频次统计（仅 CJK run 内，PUNCT/SEP 当墙）。

    返回 (freq, N_char)：
      freq[sub] = 子串 sub 在语料中的加权出现次数（按 run 权重累计）；
      N_char   = 全部 CJK 字符的加权总数（PMI 概率归一化用的语料规模）。

    用途：凝固度（内部字间互信息 PMI）需要「词本身」及「各切分半段」的出现频次，
          本函数一次性给出，供 scan_and_grow 对每个候选词查表即可。"""
    freq = {}
    N_char = 0
    n = len(S)
    i = 0
    while i < n:
        ch = S[i]
        if ch == SEP or ch == PUNCT:
            i += 1
            continue
        # 取一段连续 CJK run（到 SEP/PUNCT 为止）
        j = i
        while j < n and S[j] != SEP and S[j] != PUNCT:
            j += 1
        run = S[i:j]
        w_run = wgt[i]           # run 内权重一致（build_corpus 保证）
        L = len(run)
        N_char += w_run * L
        top = min(L, max_len)
        for a in range(L):
            for b in range(a + 1, min(L, a + top) + 1):
                sub = run[a:b]
                freq[sub] = freq.get(sub, 0) + w_run
        i = j
    return freq, N_char



# ---------------------------------------------------------------- 生长层 + 判定层
def _wsum(pos_list, wgt):
    """按权重求出现次数。"""
    return sum(wgt[p] for p in pos_list)


def scan_and_grow(S, wgt, ent_merge_ratio=ENT_MERGE_RATIO, ent_punct_exempt=True,
                  cohesion_max_len=8, indep_super_min=1):
    """核心：单字种子 → 跳跃式 BFS 枚举最大重复 → 独立出现次数判据。

    标点哨兵 PUNCT 在 S 中作为邻居参与熵计算，但对生长/独立判定当墙（与 SEP 同视），
    且不进入候选词、字频表、词云。

    返回 (candidates, charfreq)
        candidates: [(word, count, independent, binding, compound_ent, cohesion, indep)]，
                    len(word)>=2 且 independent>=1
          cohesion = 该词内部字间互信息（凝固度）最小值：min_split log2(count(w)·N / (count左·count右))；
                    纯 CJK 词内部绑定越强值越大；len<2 或 >cohesion_max_len 时为 N/A(0.0)。
          indep   = 词本身偏序独立频次占比：(count(w)-covered(w))/count(w)∈[0,1]；
                    covered = 被更长候选词(超词)完整包裹的加权出现次数；强搭配碎片≈0，真词≥0.13，
                    词缀碎片(我的/联盟之)因超词稀疏仍偏高（留补集偏序版 2.4.2 处理）。
        charfreq:   {char: 加权出现次数}（不含 PUNCT/SEP）
    """
    n = len(S)
    # 凝固度支撑：一次性加权 n-gram 频次表（仅 CJK run）
    ngram_freq, N_char = build_ngram_freq(S, wgt, cohesion_max_len)

    # 单字扫描：pos_single[char]=出现位置；charfreq 按权重累加
    pos_single = {}
    charfreq = {}
    for p, ch in enumerate(S):
        if ch == SEP or ch == PUNCT:
            continue
        pos_single.setdefault(ch, []).append(p)
        charfreq[ch] = charfreq.get(ch, 0) + wgt[p]

    def right_dist(w, pos_list):
        """右邻分布：返回 (groups, boundary, punct)。
        groups: {右邻字符: ([位置], 加权和)}，仅真实 CJK 邻居；
        boundary: 右邻为边界(SEP/串尾/标点哨兵)的加权和（生长当墙，不扩展、不计入独立/熵）；
        punct: 右邻为标点哨兵 PUNCT 的加权和（作为熵的“邻居信号”，但不生长）。"""
        groups = {}
        boundary = 0
        punct = 0
        lw = len(w)
        for p in pos_list:
            rp = p + lw
            if rp >= n or S[rp] == SEP:
                boundary += wgt[p]
            elif S[rp] == PUNCT:
                boundary += wgt[p]   # 生长当墙
                punct += wgt[p]      # 熵当邻居
            else:
                c = S[rp]
                g = groups.get(c)
                if g is None:
                    groups[c] = [[p], wgt[p]]  # [位置列表, 加权和]
                else:
                    g[0].append(p)
                    g[1] += wgt[p]
        return groups, boundary, punct

    # 左最大 / 独立次数判定用：左邻分布（语义同 right_dist）
    def left_dist(pos_list):
        groups = {}
        boundary = 0
        punct = 0
        for p in pos_list:
            if p == 0 or S[p - 1] == SEP:
                boundary += wgt[p]
            elif S[p - 1] == PUNCT:
                boundary += wgt[p]   # 生长当墙
                punct += wgt[p]      # 熵当邻居
            else:
                c = S[p - 1]
                groups[c] = groups.get(c, 0) + wgt[p]
        return groups, boundary, punct

    # BFS 队列：入队 (word, pos_list)，word 的加权 count >= 2
    from collections import deque

    def _entropy_from_vals(vals):
        """从频次列表计算熵（以 2 为底）"""
        total = sum(vals)
        if total == 0:
            return 0.0
        ent = 0.0
        for v in vals:
            p = v / total
            ent -= p * math.log2(p)
        return ent

    queue = deque()
    seen = set()
    for ch, plist in pos_single.items():
        if _wsum(plist, wgt) >= 2:
            key = (ch, id(plist))
            queue.append((ch, plist))
            seen.add(ch)  # 按串标记；单字本身不会从别处再生成

    candidates = []
    cand_lst = {}   # {word: 位置列表}，供 indep 偏序计算（超词包裹检测）零成本复用

    while queue:
        w, lst = queue.popleft()
        # 跳跃：直到右最大（右邻含边界，或右邻字符种数 >=2）
        while True:
            groups, boundary, r_punct = right_dist(w, lst)
            if boundary > 0 or len(groups) >= 2:
                break  # 右最大
            # 唯一右邻字符 c 且无边界 → 同频右扩，直接跳
            c = next(iter(groups))
            w = w + c
            lst = groups[c][0]

        count_w = _wsum(lst, wgt)

        # 左最大检查：左邻含边界，或左邻字符种数 >=2
        l_groups, l_boundary, l_punct = left_dist(lst)
        if l_boundary == 0 and len(l_groups) < 2:
            # 所有出现左邻都是同一字符 → 非左最大 → 整棵右扩展子树都非左最大，剪枝
            continue

        # 独立出现次数：出现位置同时满足 左邻∉L2 且 右邻∉R2
        # L2 = {c: count(cw)>=2}, R2 = {c: count(wc)>=2}（边界不算）
        L2 = {c for c, cnt in l_groups.items() if cnt >= 2}
        R2 = {c for c, (pl, wsum) in groups.items() if wsum >= 2}
        independent = 0
        lw = len(w)
        for p in lst:
            if p > 0 and S[p - 1] != SEP and S[p - 1] in L2:
                continue  # 左被覆盖
            rp = p + lw
            if rp < n and S[rp] != SEP and S[rp] in R2:
                continue  # 右被覆盖
            independent += wgt[p]

        # 前后集中度（binding）：左右首字符分布中最大单字占比，排除边界哨兵。
        # 高集中度 ⇒ 该词几乎只寄生在某固定邻接字之后/之前 ⇒ 大概率非独立词。
        total_l = sum(l_groups.values())
        left_conc = (max(l_groups.values()) / total_l) if total_l > 0 else 0.0
        total_r = sum(w_ for _, w_ in groups.values())
        right_conc = (max(w_ for _, w_ in groups.values()) / total_r) if total_r > 0 else 0.0
        binding = max(left_conc, right_conc)

        # ---- 复合熵（2.1.10 按用户最终规则）----
        # 邻居三态：
        #   汉字(CJK) —— 有效邻居：既是「是否有邻居」的判定依据，也计入熵分布。
        #   PUNCT —— 所有非 CJK 字符抽象成的同一个「特殊汉字」邻居（：/，/数字/字母…逐字符计数，
        #            累计进同一类型），参与熵分布计算；但【不作为「是否有邻居」的判定依据】；
        #            输出时 PUNCT 不是合法结果 → 切掉（显示引擎不输出特殊字符）。
        #   空(SEP/开头/结尾) —— 空集、无，不计入。
        # 判定流程：
        #   1) 两侧都无汉字邻居 → -1.0 豁免（纯独立标题，如长生修仙）。
        #   2) 仅一侧有汉字邻居 → 忽略无汉字侧，只用该侧邻居分布（含该侧PUNCT）算熵；
        #      但若该侧不空数据 < ENT_MIN_DATA（太少，不足为据）→ 豁免保留
        #      （如斗破苍穹 右仅"之"×1、无限恐怖 右仅"之"×2 —— 不能回答"归属于谁"就不滤）。
        #   3) 两侧都有汉字邻居：
        #      a) 少侧不空次数 / 多侧不空次数 < 10%（不空=汉字次数+PUNCT次数）→
        #         两侧邻居分布合并算总熵（救回一侧几乎全空的独立词，如苟在）；
        #      b) 否则 → min(左熵, 右熵) 作判据（低熵在左/在右等价，两侧只要有一边低→依附）。
        l_cjk = list(l_groups.values())                        # 左汉字邻居权重
        r_cjk = [wsum for _, (_, wsum) in groups.items()]       # 右汉字邻居权重
        l_han = sum(l_cjk)
        r_han = sum(r_cjk)
        l_full = l_cjk + ([l_punct] if l_punct > 0 else [])     # 左邻居分布（含PUNCT）
        r_full = r_cjk + ([r_punct] if r_punct > 0 else [])     # 右邻居分布（含PUNCT）
        l_non = l_han + l_punct      # 左不空次数（去掉开头/结尾空之后）
        r_non = r_han + r_punct      # 右不空次数
        if l_han == 0 and r_han == 0:
            compound_ent = -1.0          # 两侧都无汉字邻居 → 豁免
        elif l_han == 0:
            # 忽略左侧，只用右侧；但右侧不空数据 < ENT_MIN_DATA（太少，不足为据）→ 豁免
            compound_ent = -1.0 if r_non < ENT_MIN_DATA else _entropy_from_vals(r_full)
        elif r_han == 0:
            compound_ent = -1.0 if l_non < ENT_MIN_DATA else _entropy_from_vals(l_full)
        elif ent_merge_ratio > 0 and min(l_non, r_non) / max(l_non, r_non) < ent_merge_ratio:
            compound_ent = _entropy_from_vals(l_full + r_full)   # 一侧不空太少 → 合并
        else:
            compound_ent = min(_entropy_from_vals(l_full), _entropy_from_vals(r_full))

        # ---- 凝固度（cohesion）：词「内部」字间互信息，与上面「外部」邻居熵正交。
        # 取所有切分点的最小 PMI：值越大说明内部字间绑定越强（越像一个词）；
        # 值低/负说明两半段近似独立共现（如"之"+"巅"、"我"+"能"），更像松散搭配/词缀碎片。
        # 例：之巅/之神/之子 内部无关联 → PMI 低；什么鬼/一人之下 强绑定 → PMI 高。
        cohesion = 0.0   # N/A 默认（len<2 或超长词直接放行，交由熵判据）
        if len(w) >= 2 and len(w) <= cohesion_max_len and N_char > 0:
            c_w = ngram_freq.get(w, count_w)
            coh = float('inf')
            for i in range(1, len(w)):
                left, right = w[:i], w[i:]
                cl = ngram_freq.get(left, 0)
                cr = ngram_freq.get(right, 0)
                if cl > 0 and cr > 0:
                    pmi = math.log2(c_w * N_char / (cl * cr))
                    if pmi < coh:
                        coh = pmi
                else:
                    coh = float('-inf')   # 半段缺失（理论上不会发生）→ 视为不凝固
                    break
            if coh != float('inf'):
                cohesion = coh

        if len(w) >= 2 and independent >= 1:
            candidates.append((w, count_w, independent, binding, compound_ent, cohesion))
            cand_lst[w] = lst   # 记录位置，供 indep 偏序计算

        # 继续生长：右邻字符分支（加权 count >= 2 才可能成为词）
        for c, (pl, wsum) in groups.items():
            if wsum >= 2:
                wc = w + c
                if wc not in seen:
                    seen.add(wc)
                    queue.append((wc, pl))

    # ---- 词本身偏序（indep）：独立频次占比 ----
    # 候选词 w 的某次出现被"覆盖" = 存在【更长】候选词 s 将其完整包裹（sp<=p 且 sp+ls>=p+lw 且 ls>lw）。
    # indep(w) = (count(w) - covered_weight(w)) / count(w) ∈ [0,1]
    #   强搭配碎片(我只/聊天/我真/罗之)≈0；真词通常 ≥0.13；
    #   词缀碎片(我的/联盟之)因超词稀疏仍偏高（留补集偏序版 2.4.2 处理）。
    # 复用 cand_lst 与语料 S，零额外扫描成本。indep_super_min：仅 count>=该值的候选可作覆盖者。
    pos_start = {}   # 起始位置 → 候选词列表（倒排索引，O(1) 查某位置起点的候选）
    for w, lst in cand_lst.items():
        for p in lst:
            pos_start.setdefault(p, []).append(w)
    covered_occ = set()   # 去重：(word, position) 被更长候选覆盖
    for s, slst in cand_lst.items():
        if _wsum(slst, wgt) < indep_super_min:
            continue
        ls = len(s)
        for sp in slst:
            # 枚举 s 本次出现 [sp, sp+ls) 内部所有候选起点，标记被包裹的子候选
            for p in range(sp, sp + ls):
                for w in pos_start.get(p, ()):
                    lw = len(w)
                    if lw < ls and p + lw <= sp + ls:
                        covered_occ.add((w, p))
    covered_w = {}   # 每词被覆盖的加权次数
    for (w, p) in covered_occ:
        covered_w[w] = covered_w.get(w, 0) + wgt[p]
    enriched = []
    for (w, count_w, independent, binding, compound_ent, cohesion) in candidates:
        cov = covered_w.get(w, 0)
        indep_ratio = (count_w - cov) / count_w if count_w > 0 else 0.0
        enriched.append((w, count_w, independent, binding, compound_ent, cohesion, indep_ratio))
    candidates = enriched

    return candidates, charfreq


# ---------------------------------------------------------------- 输出层
def write_word_csv(path, candidates):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['word', 'count', 'independent', 'bind', 'len', 'compound_entropy', 'cohesion', 'indep'])
        for w, cnt, ind, bind, ent, coh, indep in sorted(candidates, key=lambda x: (-x[1], x[0])):
            wr.writerow([w, cnt, ind, round(bind, 4), len(w), round(ent, 4), round(coh, 4), round(indep, 4)])


def write_char_csv(path, charfreq):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['char', 'count'])
        for ch, cnt in sorted(charfreq.items(), key=lambda x: (-x[1], x[0])):
            wr.writerow([ch, cnt])


def render_cloud(path, candidates, top_n=200, maxlen=0, font_path=None):
    """画词云 PNG，并返回布局 layout_（每个词的最终坐标/字号/颜色/朝向）。
    layout_ 为 5 元组：((word, 归一化频率), font_size, (y, x), orientation, color)。
    orientation: None=横排, Image.ROTATE_90=竖排。删词/空语料时返回 None。"""
    from wordcloud import WordCloud
    if font_path is None:
        font_path = _pick_font()
    freqs = {}
    for w, cnt, ind, bind, _, _, _ in candidates:
        if maxlen and len(w) > maxlen:
            continue
        freqs[w] = cnt
    if not freqs:
        return None
    top = dict(sorted(freqs.items(), key=lambda x: -x[1])[:top_n])
    wc = WordCloud(font_path=font_path, width=CLOUD_W, height=CLOUD_H,
                   background_color='white', max_words=top_n,
                   collocations=False, repeat=False, prefer_horizontal=0.9,
                   random_state=42)  # 固定种子，使词云布局可复现
    wc.generate_from_frequencies(top)
    wc.to_file(path)
    return wc.layout_


def _pick_font():
    candidates = [
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\msyh.ttf',
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- 输入层
def load_csv(path, has_header):
    rows = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and has_header:
                continue
            title = r[0].strip()
            intro = r[1].strip() if len(r) > 1 else ''
            rows.append((title, intro))
    return rows


def detect_header(row, title_col, intro_col):
    """表头启发：title_col 位置为已知表头词，或前两列均为纯 ASCII 标识。"""
    TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}
    if title_col < len(row) and row[title_col].strip().lower() in TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


# ---------------------------------------------------------------- 管线
def process_corpus(prefix, docs, raw_texts, out_dir, top_n, maxlen, font_path, standalone=False, bind_thresh=1.0, min_ent=0.0, no_cloud=False, ent_merge_ratio=ENT_MERGE_RATIO, ent_punct_exempt=True, min_cohesion=0.0, min_indep=0.0, indep_super_min=1):
    S, wgt = build_corpus(docs)
    if not S:
        return
    print(f'[{prefix}] 语料字符数(去重后): {len(S)}  run数: {S.count(SEP)+1 if S else 0}', file=sys.stderr)
    candidates, charfreq = scan_and_grow(S, wgt, ent_merge_ratio, ent_punct_exempt, indep_super_min=indep_super_min)
    # 前后集中度闸门（bind）：binding > 阈值的词视为寄生词剔除；默认 1.0 = 不过滤（基线）
    if bind_thresh < 1.0:
        candidates = [c for c in candidates if c[3] <= bind_thresh]
    # 复合熵闸门（与 --bind 取 AND）：c[4] 为 compound_entropy；-1.0 表示无真实邻居证据，豁免
    if min_ent > 0:
        before = len(candidates)
        candidates = [c for c in candidates if c[4] < 0 or c[4] >= min_ent]
        print(f'[{prefix}] 熵过滤: {before} → {len(candidates)} 词 (阈值 {min_ent})', file=sys.stderr)
    # 凝固度 / 词本身偏序 联合闸门（与熵取 AND）：cohesion 在 c[5]、indep 在 c[6]。
    # 单字无内部绑定概念 → 直接放行；其余要求 凝固度>=阈值 且 独立频次占比>=阈值，二者取 AND。
    # indep 补充捕捉"内部 PMI 够高、但本质是强搭配碎片(我只/聊天/我真/罗之)"的漏网词：
    #   这类词被更长真词完整包裹 → indep≈0 → 被剔；真词 indep≥0.13 不受影响。
    if min_cohesion > 0 or min_indep > 0:
        before = len(candidates)
        def _pass(c):
            if len(c[0]) < 2:
                return True
            ok_coh = (min_cohesion <= 0) or (c[5] >= min_cohesion)
            ok_ind = (min_indep <= 0) or (c[6] >= min_indep)
            return ok_coh and ok_ind
        candidates = [c for c in candidates if _pass(c)]
        print(f'[{prefix}] 凝固度/偏序门: {before} → {len(candidates)} 词 (coh {min_cohesion}, indep {min_indep})', file=sys.stderr)
    print(f'[{prefix}] 候选词: {len(candidates)}  去重字符: {len(charfreq)}', file=sys.stderr)
    write_word_csv(os.path.join(out_dir, f'{prefix}_wordfreq.csv'), candidates)
    write_char_csv(os.path.join(out_dir, f'{prefix}_charfreq.csv'), charfreq)
    layout = None
    if not no_cloud:
        try:
            layout = render_cloud(os.path.join(out_dir, f'{prefix}_wordcloud.png'),
                                  candidates, top_n, maxlen, font_path)
        except Exception as e:
            print(f'[{prefix}] 词云渲染跳过: {e}', file=sys.stderr)
            layout = None
        # 互动词云（插入模块，独立生成 json + html；失败不影响上面的核心产物）
        try:
            emit_interactive(prefix, out_dir, candidates, raw_texts, top_n, maxlen, layout, standalone=standalone)
        except Exception as e:
            print(f'[{prefix}] 互动词云生成跳过: {e}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description='生长词库：纯 Python 版')
    ap.add_argument('input', help='CSV 路径（title, intro 两列）')
    ap.add_argument('--out', default='.', help='输出目录')
    ap.add_argument('--top', type=int, default=200, help='词云词数上限')
    ap.add_argument('--maxlen', type=int, default=0, help='词云最大词长过滤（0=不限，仅显示层）')
    ap.add_argument('--no-header', action='store_true', help='CSV 无表头')
    ap.add_argument('--no-dedup', action='store_true', help='不去重（默认按相同 title,intro 合并加权）')
    ap.add_argument('--title-col', type=int, default=0, help='书名列号（0-based）')
    ap.add_argument('--intro-col', type=int, default=1, help='简介列号（0-based，-1 表示无简介）')
    ap.add_argument('--standalone', action='store_true',
                    help='互动词云生成单文件内联 HTML（默认生成外壳 HTML + 外部 data.js，体积恒定可复用）')
    ap.add_argument('--bind', type=float, default=1.0,
                    help='前后集中度闸门阈值（binding）：binding 大于该值的词视为寄生词剔除；默认 1.0=不过滤（基线）')
    ap.add_argument('--min-ent', type=float, default=0.0,
                    help='复合熵阈值：compound_entropy >= 阈值才保留（-1.0 豁免恒保留）。判据=min(左熵,右熵)，两侧只要有一边低于阈值即滤除；默认 0.0=不过滤（基线），推荐 0.5（用户定）')
    ap.add_argument('--no-punct-ent', action='store_true',
                    help='关闭标点感知熵：非CJK不保留为哨兵（等价于 2.1.4 行为），便于与标点感知版对照调参')
    ap.add_argument('--no-merge', action='store_true',
                    help='关闭合并模式（等价 ratio=0）：两侧都有汉字邻居时恒用 min(左熵,右熵) 判据，不做“少侧不空/多侧不空<10%→合并”')
    ap.add_argument('--no-punct-exempt', action='store_true',
                    help='(2.1.10 起废弃/无实际作用) PUNCT 恒作为抽象「特定汉字」邻居参与熵分布，但不作为「是否有邻居」的判定依据——该行为不可关闭，仅保留此开关兼容旧命令')
    ap.add_argument('--ent-merge-ratio', type=float, default=ENT_MERGE_RATIO,
                    help='合并触发比：两侧都有汉字邻居时，少侧不空次数/多侧不空次数 低于此值（默认 0.25，不空=汉字邻居次数+PUNCT次数）→ 两侧邻居分布合并算总熵；否则用 min(左熵,右熵)')
    ap.add_argument('--cohesion', type=float, default=0.0,
                    help='凝固度(PMI)闸门阈值（0=关闭）：候选词内部字间互信息最小值 >= 阈值才保留，否则视为松散搭配/词缀碎片滤除（如之巅/我能）；与熵闸门取 AND。仅对 len>=2 词生效，单字/超长词直接放行')
    ap.add_argument('--indep', type=float, default=0.0,
                    help='词本身偏序独立频次占比闸门（0=关闭）：indep=(count-被更长候选包裹次数)/count >= 阈值才保留；捕捉"内部PMI够高但本质是强搭配碎片(我只/聊天/我真/罗之)"的漏网词——它们被更长真词完整包裹→indep≈0→被剔；真词 indep≥0.13 不受影响。与凝固度取 AND')
    ap.add_argument('--indep-super-min', type=int, default=1,
                    help='indep 覆盖者(超词)最小加权次数：count 低于此值的候选词不作包裹判定，避免极稀疏超词误伤。默认 1（任意候选均可作覆盖者）')
    ap.add_argument('--no-cloud', action='store_true',
                    help='跳过词云/PNG/互动HTML渲染（仅生成 CSV），用于批量调参加速')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    def cell(r, idx):
        if idx < 0 or idx >= len(r):
            return ''
        return r[idx].strip()

    with open(args.input, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not args.no_header and detect_header(r, args.title_col, args.intro_col):
                continue
            title = cell(r, args.title_col)
            intro = cell(r, args.intro_col)
            rows.append((title, intro))

    if args.no_dedup:
        dedup = [(t, i, 1) for t, i in rows]
    else:
        dedup = [(t, i, w) for (t, i), w in Counter(rows).items()]

    # 两条独立管线：结果不混淆
    use_punct = not args.no_punct_ent
    ent_merge_ratio = 0.0 if args.no_merge else args.ent_merge_ratio
    title_docs = [(clean(t, use_punct), w) for t, i, w in dedup if t]
    intro_docs = [(clean(i, use_punct), w) for t, i, w in dedup if i]
    title_raw = [t for t, i, w in dedup if t]
    intro_raw = [i for t, i, w in dedup if i]

    process_corpus('title', title_docs, title_raw, args.out, args.top, args.maxlen, None, standalone=args.standalone, bind_thresh=args.bind, min_ent=args.min_ent, no_cloud=args.no_cloud, ent_merge_ratio=ent_merge_ratio, ent_punct_exempt=not args.no_punct_exempt, min_cohesion=args.cohesion, min_indep=args.indep, indep_super_min=args.indep_super_min)
    process_corpus('intro', intro_docs, intro_raw, args.out, args.top, args.maxlen, None, standalone=args.standalone, bind_thresh=args.bind, min_ent=args.min_ent, no_cloud=args.no_cloud, ent_merge_ratio=ent_merge_ratio, ent_punct_exempt=not args.no_punct_exempt, min_cohesion=args.cohesion, min_indep=args.indep, indep_super_min=args.indep_super_min)
    print(f'完成，输出目录: {args.out}')


if __name__ == '__main__':
    main()
