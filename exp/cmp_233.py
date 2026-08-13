# -*- coding: utf-8 -*-
"""2.3.3-cohesion-poset 对比：在 2.3.1 凝固度(v217=5156) 基础上加「词本身偏序」独立频次门。
输出：
  - 校验：indep=0 应精确复现 v217=5156（无回归）
  - 调参：indep ∈ {0.03,0.05,0.10} 的产词数 / 清碎片 / 误伤真词
  - 定位：与 v211(5865)/v216(5877)/v217(5156)/2.4.1(5895)/2.4.2(5889) 同表对比
生产指标对齐 README「三版本最终验收评估」：
  硬碎片残留 = 错题集 class=111 仍被保留的词数
  高频误伤   = 错题集 class=000 且 count>=5 被滤除的词数
"""
import importlib.util, csv, os, sys
from collections import Counter

EV = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EV)
sys.path.insert(0, ROOT)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5; ENT_MR = 0.25; POS_FIXED = 0.80; MIN_COH = 1.5
EVAL = r"SANDBOX\eval_versions"
PROBE = ["我只", "聊天", "我真", "罗之", "联盟之", "我的", "这个", "世界", "开始", "首富", "庆余年", "长生"]


def lg(p):
    s = importlib.util.spec_from_file_location("g233", p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def title_docs(g):
    docs = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if not r:
                continue
            if i == 0 and g.detect_header(r, 2, 1):
                continue
            t = r[2].strip() if len(r) > 2 else ""
            if t:
                docs.append(t)
    d = {}
    for t in docs:
        d[t] = d.get(t, 0) + 1
    return [(g.clean(t, True), w) for t, w in d.items() if t]


def load_book():
    true000_hf = set()   # class=000 且 count>=5（高频真词，误伤对象）
    frag111 = set()      # class=111（碎片，残留对象）
    rows = {}
    with open(os.path.join(EVAL, "mistake_book.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            w = r["word"].strip()
            try:
                cnt = int(r["count"])
            except (ValueError, TypeError):
                cnt = 0
            rows[w] = r
            if r["class"] == "000" and cnt >= 5:
                true000_hf.add(w)
            if r["class"] == "111":
                frag111.add(w)
    return true000_hf, frag111, rows


def kept_set(g, cands, min_coh, min_indep, min_ent=MIN_ENT):
    out = set()
    for c in cands:
        w = c[0]
        if len(w) < 2:
            out.add(w); continue
        ok_ent = (min_ent <= 0) or (c[4] < 0 or c[4] >= min_ent)   # 复合熵门（-1 豁免）
        ok_coh = (min_coh <= 0) or (c[5] >= min_coh)
        ok_ind = (min_indep <= 0) or (c[6] >= min_indep)
        if ok_ent and ok_coh and ok_ind:
            out.add(w)
    return out


def main():
    g = lg(os.path.join(ROOT, "grow.py"))
    docs = title_docs(g)
    S, wgt = g.build_corpus(docs)
    cands = g.scan_and_grow(S, wgt, ENT_MR, True, cohesion_max_len=8)[0]
    print(f"候选总数(7字段, indep已算): {len(cands)}")

    true000_hf, frag111, rows = load_book()
    print(f"错题集标签: 高频真词(class000,count>=5)={len(true000_hf)}  碎片(class111)={len(frag111)}")

    # 各配置
    configs = {
        "v217(base, indep=0)": (MIN_COH, 0.0),
        "2.3.3 indep=0.03":    (MIN_COH, 0.03),
        "2.3.3 indep=0.05":    (MIN_COH, 0.05),
        "2.3.3 indep=0.10":    (MIN_COH, 0.10),
    }
    kept = {}
    for name, (mc, mi) in configs.items():
        kept[name] = kept_set(g, cands, mc, mi)

    base = kept["v217(base, indep=0)"]
    print("\n=== 2.3.3 调参（title, me0.5+mr0.25+coh1.5）===")
    print(f"{'配置':<22}{'产词数':>7}{'Δv217':>7}{'硬碎片残留':>10}{'高频误伤':>9}{'清碎片':>7}{'新增误伤':>8}")
    for name, (mc, mi) in configs.items():
        k = kept[name]
        residual = len(k & frag111)
        falsekill = len(true000_hf - k)
        clr = len(base & frag111) - len(k & frag111)
        newfk = len(true000_hf - k) - len(true000_hf - base)
        d = len(k) - len(base)
        print(f"{name:<22}{len(k):>7}{d:>+7}{residual:>10}{falsekill:>9}{clr:>+7}{newfk:>+8}")

    # 探针词 indep 值
    cm = {c[0]: c for c in cands}
    print("\n=== 探针词 indep / coh（验证信号方向）===")
    for w in PROBE:
        if w in cm:
            c = cm[w]
            tag = rows.get(w, {}).get("class", "?")
            print(f"  {w:<6} indep={c[6]:.3f}  coh={c[5]:.2f}  ent={c[4]:.2f}  count={c[1]:>4}  class={tag}")
        else:
            print(f"  {w:<6} (不在候选)")

    # indep=0.05 相对 base 删除的词中，是否有真词
    dropped = base - kept["2.3.3 indep=0.05"]
    print(f"\n=== indep=0.05 删除的 {len(dropped)} 词（应为强搭配碎片，不含真词）===")
    true_dropped = [w for w in dropped if rows.get(w, {}).get("class") == "000"]
    frag_dropped = [w for w in dropped if rows.get(w, {}).get("class") == "111"]
    other_dropped = [w for w in dropped if w not in true_dropped and w not in frag_dropped]
    print(f"  错题集标注真词被删: {true_dropped}  ← 应为空")
    print(f"  错题集标注碎片被删: {frag_dropped}")
    print(f"  未标注(其他)被删:   {other_dropped[:40]}")


if __name__ == "__main__":
    main()
