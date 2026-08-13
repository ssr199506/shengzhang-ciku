#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对拍器（grow3 版）：随机小语料上暴力枚举全部子串，与 grow3.scan.scan_once 逐词断言相等。

与 verify.py 方法论完全一致，仅把被对拍对象从 legacy grow.scan_and_grow 换成
grow3.scan.scan_once —— 验证「3.0 重构未改变扫描/独立判定行为」这一核心不变式。

复用 verify.py 的 brute_corpus（同一份暴力参考实现，避免两边各写一份导致漂移）。

用法：python verify_grow3.py [seed_count]
"""
import random
import sys

from verify import SEP, brute_corpus

from grow3.scan import build_corpus, scan_once


def run_test(seed, weighted=False, verbose=False):
    random.seed(seed)
    chars = '我们的是不了一个人' + '穿越霸道总裁千金修仙' + '天地无情岁月'
    n_runs = random.randint(5, 40)
    parts = []
    for _ in range(n_runs):
        run = ''.join(random.choice(chars) for _ in range(random.randint(1, 10)))
        parts.append(run)
    S = SEP.join(parts)

    if weighted:
        docs = [(run, random.randint(1, 4)) for run in parts]
    else:
        docs = [(run, 1) for run in parts]
    S, wgt = build_corpus(docs)

    ctx, words = scan_once(S, wgt)
    got = {wd.word: (wd.count, wd.independent) for wd in words}
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
    print(f'grow3 全部通过：{n*2} 组随机语料，共校验 {total} 个词次')
    print('说明：加权与等权结果一致 => 判据对权重不变（只影响频数数值）')


if __name__ == '__main__':
    main()
