# -*- coding: utf-8 -*-
"""2.3.3 调参与版本对比脚本。

复现目标：
  - 标准配置 me0.5 + mr0.25 + coh1.5 下，v217 基线产词 5156（indep=0 无回归）。
  - 加入词本身偏序独立频次闸门 indep∈{0, 0.03, 0.05, 0.10} 后，看产词数/碎片清理/真词误伤的变化。
  - 探针词验证信号方向：强搭配碎片(我只/聊天/我真/罗之) indep≈0，真词 indep≥0.13。

与 grow.py 完全复用同一套 scan_and_grow（含 indep 计算），仅在本脚本内施加熵门/凝固度门/偏序门，
避免重复扫描。语料列映射对齐 CLI（书名在 col 2，作者 col 5 但 title 产词只看 col 2）。

运行：python exp/cmp_233.py
"""
import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from grow import build_corpus, scan_and_grow, clean, detect_header, ENT_MERGE_RATIO  # noqa: E402

CORPUS = os.path.join(ROOT, "PAID_CORPUS.csv")
BOOK = r"SANDBOX\eval_versions\mistake_book.csv"

TITLE_COL = 2
INTRO_COL = -1
MIN_ENT = 0.5          # 复合熵闸门（标准配置）
ENT_MERGE = 0.25       # 合并触发比（标准配置）
MIN_COH = 1.5          # 凝固度(PMI)闸门（标准配置）
INDEP_SUPER_MIN = 1    # 覆盖者最小加权次数（默认 1 = 任意候选可作覆盖者）


def build_title_docs(path, title_col=TITLE_COL, intro_col=INTRO_COL, use_punct=True):
    """对齐 grow.py main() 的语料读取 + 去重加权逻辑，保证与 CLI 产词数一致。"""
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and detect_header(r, title_col, intro_col):
                continue
            title = r[title_col].strip() if title_col < len(r) else ""
            intro = r[intro_col].strip() if 0 <= intro_col < len(r) else ""
            rows.append((title, intro))
    dedup = [(t, i, w) for (t, i), w in Counter(rows).items()]
    return [(clean(t, use_punct), w) for t, i, w in dedup if t]


def load_book(path):
    book = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            book[row["word"].strip()] = row
    return book


def kept_set(cands, min_ent, min_coh, min_indep):
    """施加 熵门 AND 凝固度门 AND 偏序门，返回保留词集合。对齐 grow.py process_corpus 三个闸门。"""
    out = set()
    for (w, cnt, ind, bind, ent, coh, indep) in cands:
        # 复合熵闸门：c[4]<0(豁免) 或 >=min_ent 才保留
        if not (ent < 0 or ent >= min_ent):
            continue
        # 凝固度闸门（len>=2 才判；单字无内部绑定概念直接放行，但本管线不产单字）
        if len(w) >= 2 and not (coh >= min_coh):
            continue
        # 词本身偏序闸门
        if len(w) >= 2 and not (indep >= min_indep):
            continue
        out.add(w)
    return out


def main():
    docs = build_title_docs(CORPUS)
    S, wgt = build_corpus(docs)
    cands, _ = scan_and_grow(S, wgt, ent_merge_ratio=ENT_MERGE,
                             ent_punct_exempt=True, indep_super_min=INDEP_SUPER_MIN)

    # 候选索引：word -> (indep, coh, ent, count)
    info = {w: (indep, coh, ent, cnt) for (w, cnt, ind, bind, ent, coh, indep) in cands}

    book = load_book(BOOK)
    true000_hf = {w for w, r in book.items() if r["class"] == "000" and int(r["count"]) >= 5}  # 60
    frag111 = {w for w, r in book.items() if r["class"] == "111"}  # 5155
    base_filtered_000 = len(true000_hf)  # 基线即全误杀，固定 60

    print(f"候选总数(7字段, indep已算): {len(cands)}")
    print(f"错题集标签: 高频真词(class000,count>=5)={len(true000_hf)}"
          f"  碎片(class111)={len(frag111)}")

    print("\n=== 2.3.3 调参（title, me0.5+mr0.25+coh1.5）===")
    header = f"{'配置':24} {'产词数':>6} {'Δv217':>7} {'硬碎片残留':>10} {'高频误伤':>8} {'清碎片':>7} {'新增误伤':>8}"
    print(header)
    base = None
    rows = []
    for indep in (0, 0.03, 0.05, 0.10):
        kept = kept_set(cands, MIN_ENT, MIN_COH, indep)
        if indep == 0:
            base = kept
        n = len(kept)
        delta = n - len(base) if base is not None else 0
        frag_kept = len(kept & frag111)
        hard_frag = frag_kept
        freq_miss = len(true000_hf - kept)            # 高频真词误杀数
        clear_frag = len(frag111 - kept)              # 清掉的碎片数
        new_miss = freq_miss - base_filtered_000       # 相对基线新增误伤
        label = "v217(base, indep=0)" if indep == 0 else f"2.3.3 indep={indep}"
        rows.append((label, n, delta, hard_frag, freq_miss, clear_frag, new_miss))
        print(f"{label:24} {n:>6} {delta:>+7} {hard_frag:>10} {freq_miss:>8} {clear_frag:>+7} {new_miss:>+8}")

    # ---- 探针词：验证信号方向 ----
    print("\n=== 探针词 indep / coh（验证信号方向）===")
    probes = ["我只", "聊天", "我真", "罗之", "联盟之", "我的", "这个",
              "世界", "开始", "首富", "庆余年", "长生"]
    print(f"{'词':8} {'indep':>8} {'coh':>8} {'ent':>8} {'count':>7} {'class':>6}")
    for w in probes:
        if w in info:
            indep, coh, ent, cnt = info[w]
            cls = book.get(w, {}).get("class", "-")
            print(f"{w:8} {indep:>8.3f} {coh:>8.2f} {ent:>8.2f} {cnt:>7} {cls:>6}")
        else:
            print(f"{w:8} (不在候选集)")

    # ---- indep=0.05 删除词分类 ----
    print("\n=== indep=0.05 删除的 7 词（应为强搭配碎片，不含真词）===")
    deleted = base - kept_set(cands, MIN_ENT, MIN_COH, 0.05)
    true_del = sorted(deleted & true000_hf)
    frag_del = sorted(deleted & frag111)
    other_del = sorted(deleted - book.keys())
    print(f"  错题集标注真词被删: {true_del}  ← 应为空")
    print(f"  错题集标注碎片被删: {frag_del}")
    print(f"  未标注(其他)被删:   {other_del}")


if __name__ == "__main__":
    main()
