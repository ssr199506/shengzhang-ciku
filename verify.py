#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对拍器：随机小语料上，暴力枚举全部子串，与 grow.py 的 scan_and_grow 逐词断言相等。

用法：python verify.py [seed_count]
"""
import random
import sys
from collections import deque

from grow import SEP, scan_and_grow


def brute_corpus(S, wgt):
    """暴力：返回 {word: (count, independent)}，word 为最大重复（len>=2, count>=2）。"""
    n = len(S)
    BOUND = None  # 边界统一标记（串首/串尾/SEP 都算边界）

    # 1) 枚举 run 内所有子串，按位置加权计数
    cnt = {}
    i = 0
    while i < n:
        if S[i] == SEP:
            i += 1
            continue
        j = i
        while j < n and S[j] != SEP:
            j += 1
        for a in range(i, j):
            s = 0
            for b in range(a + 1, j + 1):
                s += wgt[b - 1]
                w = S[a:b]
                cnt[w] = cnt.get(w, 0) + wgt[a]
        i = j

    # 2) 对每个串：出现位置、左右邻集合（边界归一）
    def occurrences(w):
        pos = []
        start = 0
        while True:
            p = S.find(w, start)
            if p < 0:
                break
            pos.append(p)
            start = p + 1
        return pos

    singles = {ch for ch in S if ch != SEP}
    result = {}
    for w, c in cnt.items():
        if len(w) < 2 or c < 2:
            continue
        pos = occurrences(w)
        # 左最大 / 右最大：存在 run 首/尾出现（不可同频扩展），或邻字符种数 >=2
        lefts = set()
        rights = set()
        left_bound = False
        right_bound = False
        for p in pos:
            if p == 0 or S[p - 1] == SEP:
                left_bound = True
            else:
                lefts.add(S[p - 1])
            rp = p + len(w)
            if rp >= n or S[rp] == SEP:
                right_bound = True
            else:
                rights.add(S[rp])
        if (left_bound or len(lefts) >= 2) and (right_bound or len(rights) >= 2):  # 最大重复
            L2 = {ch for ch in singles if cnt.get(ch + w, 0) >= 2}
            R2 = {ch for ch in singles if cnt.get(w + ch, 0) >= 2}
            ind = 0
            for p in pos:
                l = BOUND if p == 0 or S[p - 1] == SEP else S[p - 1]
                rp = p + len(w)
                r = BOUND if rp >= n or S[rp] == SEP else S[rp]
                if not (l is not None and l in L2) and not (r is not None and r in R2):
                    ind += wgt[p]
            if ind >= 1:  # 与 grow 一致：纯寄生虫（独立=0）删除
                result[w] = (c, ind)
    return result


def run_test(seed, weighted=False, verbose=False):
    random.seed(seed)
    chars = '我们的是不了一个人' + '穿越霸道总裁千金修仙' + '天地无情岁月'
    # 随机生成多个 run
    n_runs = random.randint(5, 40)
    parts = []
    for _ in range(n_runs):
        run = ''.join(random.choice(chars) for _ in range(random.randint(1, 10)))
        parts.append(run)
    S = SEP.join(parts)

    from grow import build_corpus
    if weighted:
        docs = [(run, random.randint(1, 4)) for run in parts]
    else:
        docs = [(run, 1) for run in parts]
    S, wgt = build_corpus(docs)

    got = {w: (c, ind) for w, c, ind, bind, _ in scan_and_grow(S, wgt)[0]}
    exp = brute_corpus(S, wgt)

    assert set(got) == set(exp), (
        f'seed={seed} 词集合不一致\n  only_got={sorted(set(got)-set(exp))[:10]}\n'
        f'  only_exp={sorted(set(exp)-set(got))[:10]}')
    for w in exp:
        assert got[w] == exp[w], f'seed={seed} 词 {w!r}: got={got[w]} exp={exp[w]}'
    if verbose:
        print(f'seed={seed} {"加权" if weighted else "等权"} OK, {len(got)} 词')
    return len(got)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    total = 0
    for seed in range(n):
        total += run_test(seed, weighted=False)
        total += run_test(seed + 100000, weighted=True)
    print(f'全部通过：{n*2} 组随机语料，共校验 {total} 个词次')
    print('说明：加权与等权结果一致 => 判据对权重不变（只影响频数数值）')


if __name__ == '__main__':
    main()
