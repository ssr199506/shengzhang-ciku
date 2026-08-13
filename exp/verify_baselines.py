# -*- coding: utf-8 -*-
"""校验三版本基准产词数：复刻 mistake_book.run_version 的保留/过滤决策。
期望：v211=5865, v216=5877, v217=5156（与错题集一致）。
"""
import importlib.util, csv, os, sys

EV = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EV)
sys.path.insert(0, ROOT)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5
ENT_MR = 0.25
POS_FIXED = 0.80
MIN_COH = 1.5


def load_grow(path):
    spec = importlib.util.spec_from_file_location("grow_" + os.path.basename(path), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_title_docs(grow):
    docs = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        for i, r in enumerate(rd):
            if not r:
                continue
            if i == 0 and grow.detect_header(r, 2, 1):
                continue
            t = r[2].strip() if len(r) > 2 else ""
            if t:
                docs.append(t)
    dedup = {}
    for t in docs:
        if t:
            dedup[t] = dedup.get(t, 0) + 1
    return [(grow.clean(t, True), w) for t, w in dedup.items() if t]


def run_version(grow, pos_fixed=None, min_coh=0.0):
    docs = build_title_docs(grow)
    S, wgt = grow.build_corpus(docs)
    if pos_fixed is not None:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, pos_fixed_thr=pos_fixed)
    elif hasattr(grow, "build_ngram_freq"):
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, cohesion_max_len=8)
    else:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True)
    kept = {}
    for c in cands:
        ent = c[4]
        if not (ent < 0 or ent >= MIN_ENT):
            continue
        if min_coh > 0 and len(c[0]) >= 2 and c[5] < min_coh:
            continue
        kept[c[0]] = True
    return set(kept)


def main():
    v211 = load_grow(os.path.join(EV, "v211_grow.py"))
    v216 = load_grow(os.path.join(EV, "v216_grow.py"))
    v217 = load_grow(os.path.join(EV, "v217_grow.py"))
    r211 = run_version(v211)
    r216 = run_version(v216, pos_fixed=POS_FIXED)
    r217 = run_version(v217, min_coh=MIN_COH)
    print(f"v211(纯熵)   = {len(r211)}  (期望 5865)")
    print(f"v216(pos-fx) = {len(r216)}  (期望 5877)")
    print(f"v217(coh)    = {len(r217)}  (期望 5156)")
    print("ok" if len(r211) == 5865 and len(r216) == 5877 and len(r217) == 5156 else "MISMATCH!")


if __name__ == "__main__":
    main()
