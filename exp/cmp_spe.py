# -*- coding: utf-8 -*-
"""SPE(v2.1.19) 区分力诊断 + 调参 + 四版本对比。
- 加载错题集标签（000层疑似真词 coh>=6 / 共识层高频句法碎片）作为评估金标准代理。
- 对 v219 在 (spe_rescue, spe_affix) 网格上评估：
    救回多少 000层真词、清掉多少共识层高频碎片、净产词数 vs v211。
- 输出四版本对比：v211/v216/v217/v219 的保留词数与对错题集各层的影响。
"""
import importlib.util, csv, os, sys, math
from collections import Counter, defaultdict

EV = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EV)
EVAL = r"SANDBOX\eval_versions"
sys.path.insert(0, ROOT)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5
ENT_MR = 0.25
POS_FIXED = 0.80
MIN_COH = 1.5

# 共识层高频句法碎片（111层里的共同盲区，应被清掉）
FRAG_LEXICON = {"我的", "我在", "我是", "我有", "这个", "成了", "一个", "不是",
                "你在", "他在", "是在", "开了", "出了", "什么", "就是", "还是",
                "可以", "没有", "我们", "他们"}


def load_grow(path):
    spec = importlib.util.spec_from_file_location("g_" + os.path.basename(path), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_title_docs(grow):
    docs = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if not r:
                continue
            if i == 0 and grow.detect_header(r, 2, 1):
                continue
            t = r[2].strip() if len(r) > 2 else ""
            if t:
                docs.append(t)
    ded = {}
    for t in docs:
        if t:
            ded[t] = ded.get(t, 0) + 1
    return [(grow.clean(t, True), w) for t, w in ded.items() if t]


def run_ref(grow, pos_fixed=None, min_coh=0.0):
    docs = build_title_docs(grow)
    S, wgt = grow.build_corpus(docs)
    if pos_fixed is not None:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, pos_fixed_thr=pos_fixed)
    elif hasattr(grow, "build_ngram_freq"):
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, cohesion_max_len=8)
    else:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True)
    kept = set()
    for c in cands:
        ent = c[4]
        if not (ent < 0 or ent >= MIN_ENT):
            continue
        if min_coh > 0 and len(c[0]) >= 2 and c[5] < min_coh:
            continue
        kept.add(c[0])
    return kept, cands


def v219_all_candidates(grow):
    """返回 v219 全候选（含 spe 第6列），仅算一次。"""
    docs = build_title_docs(grow)
    S, wgt = grow.build_corpus(docs)
    cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True)
    return cands


def decide_v219(c, spe_rescue, spe_affix):
    w, cnt, ind, bind, ent, spe = c
    if ent < 0 or ent >= MIN_ENT:
        keep = True
    elif spe_rescue > 0 and spe >= spe_rescue:
        keep = True
    else:
        keep = False
    if keep and spe_affix > 0 and spe >= 0 and spe <= spe_affix:
        keep = False
    return keep


def load_labels():
    """从 mistake_book.csv 取标签词集。"""
    true000, frag111 = set(), set()
    with open(os.path.join(EVAL, "mistake_book.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["class"] == "000":
                coh = r.get("217_coh")
                if coh not in (None, "", "None") and float(coh) >= 6.0:
                    true000.add(r["word"])
            if r["class"] == "111" and r["word"] in FRAG_LEXICON:
                frag111.add(r["word"])
    return true000, frag111


def main():
    g211 = load_grow(os.path.join(EV, "v211_grow.py"))
    g216 = load_grow(os.path.join(EV, "v216_grow.py"))
    g217 = load_grow(os.path.join(EV, "v217_grow.py"))
    g219 = load_grow(os.path.join(ROOT, "grow.py"))   # 当前分支 = v219
    print("加载/计算各版本候选...", flush=True)
    r211, _ = run_ref(g211)
    r216, _ = run_ref(g216, pos_fixed=POS_FIXED)
    r217, _ = run_ref(g217, min_coh=MIN_COH)
    all219 = v219_all_candidates(g219)
    true000, frag111 = load_labels()
    print(f"标签: 000层真词(coh>=6)={len(true000)}  共识层高频碎片={len(frag111)}")
    print(f"参考产词数: v211={len(r211)} v216={len(r216)} v217={len(r217)}")

    print("\n=== SPE 调参网格 ===")
    print(f"{'spe_rescue':>10} {'spe_affix':>10} {'v219数':>7} {'Δv211':>6} {'救000真词':>9} {'清共识碎片':>9} {'净救-净清':>8}")
    best = None
    for sr in [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]:
        for sa in [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]:
            if sr == 0.0 and sa == 0.0:
                continue
            kept = set()
            for c in all219:
                if decide_v219(c, sr, sa):
                    kept.add(c[0])
            rescued = sum(1 for w in true000 if w in kept and w not in r211)
            cleared = sum(1 for w in frag111 if w not in kept and w in r211)
            n = len(kept)
            d = n - len(r211)
            score = rescued - cleared   # 净正向变化（救真词 - 清碎片，粗略）
            print(f"{sr:>10} {sa:>10} {n:>7} {d:>+6} {rescued:>9} {cleared:>9} {score:>+8}")
            if best is None or score > best[0]:
                best = (score, sr, sa, n, d, rescued, cleared)
    print(f"\n粗略最优(净救-净清最大): spe_rescue={best[1]} spe_affix={best[2]} -> n={best[3]} Δ={best[4]} 救{best[5]} 清{best[6]}")

    # 固定一组做四版本详细对比（用粗略最优）
    sr, sa = best[1], best[2]
    print(f"\n=== 选用 spe_rescue={sr} spe_affix={sa} 的四版本对比 ===")
    kept219 = set(c[0] for c in all219 if decide_v219(c, sr, sa))
    # 对错题集全量做分层影响
    labeled = defaultdict(lambda: {"v211": 0, "v216": 0, "v217": 0, "v219": 0, "n": 0})
    with open(os.path.join(EVAL, "mistake_book.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cls = r["class"]
            w = r["word"]
            d = labeled[cls]
            d["n"] += 1
            d["v211"] += (w in r211)
            d["v216"] += (w in r216)
            d["v217"] += (w in r217)
            d["v219"] += (w in kept219)
    print(f"{'层':<14}{'n':>5}{'v211':>6}{'v216':>6}{'v217':>6}{'v219':>6}")
    for cls in ["111", "010", "110", "101", "011", "001", "100", "000"]:
        d = labeled[cls]
        if d["n"]:
            print(f"{cls:<14}{d['n']:>5}{d['v211']:>6}{d['v216']:>6}{d['v217']:>6}{d['v219']:>6}")
    print(f"\n产词数: v211={len(r211)} v216={len(r216)} v217={len(r217)} v219={len(kept219)}")
    print(f"v219 vs v211: 新增 {len(kept219 - r211)}  删除 {len(r211 - kept219)}")


if __name__ == "__main__":
    main()
