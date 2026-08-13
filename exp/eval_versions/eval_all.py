# -*- coding: utf-8 -*-
"""三版本最终验收评估（生产视角：统计网站标题取名高频词）
对 main(2.1.11)/2.1.16-pos-fixed/2.1.17-cohesion 用同一语料同一金标准打分，
并补充生产维度指标：硬碎片残留、边界词缀去向、高频误伤、top词质。
"""
import importlib.util, csv, os, sys, json

EV = os.path.dirname(os.path.abspath(__file__))
CSV = r"PROJECT_ROOT\PAID_CORPUS.csv"

# ---- 旧金标准（照抄 cmp_cohesion.py，供参考但将被批判性使用）----
SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记","无限恐怖",
    "鬼灭","苟在","之主","之王","世界","长生","凡人","修仙","都市","系统","巅峰","重生之",
    "人在木叶","全职法师","风云","无敌","直播","网游","神豪","荒古","重生","战神","天才",
    "玄幻","末世","奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之","星空之",
    "火影开","无限之","诸天之","之巅","之神","之子","之魂","之开","罗之","世主","生仙",
    "人在斗","影开始","局被","后一","的悠"]

# ---- 生产视角分类（客观规则，不照搬旧表）----
# 硬碎片：无论何种生产口径都基本无取名价值的寄生碎片
HARD_FRAGMENTS = set(SHOULD_FILTER)
# 边界词缀模式：高频词缀（之主/之王/重生之…）有"模式统计"价值，单独报告不罚分
BOUNDARY = ["之主","之王","重生之","我能","什么鬼","人在斗罗","完美世界","重燃","首富","从零"]


def load_grow(path):
    spec = importlib.util.spec_from_file_location("grow", path)
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


def run_version(grow, ent_mr, min_ent, pos_fixed=None, min_coh=0.0):
    docs = build_title_docs(grow)
    S, wgt = grow.build_corpus(docs)
    if pos_fixed is not None:
        cands, _ = grow.scan_and_grow(S, wgt, ent_mr, True, pos_fixed_thr=pos_fixed)
    elif hasattr(grow, "build_ngram_freq"):
        cands, _ = grow.scan_and_grow(S, wgt, ent_mr, True, cohesion_max_len=8)
    else:
        cands, _ = grow.scan_and_grow(S, wgt, ent_mr, True)
    kept = []
    for c in cands:
        ent = c[4]
        if not (ent < 0 or ent >= min_ent):
            continue
        if min_coh > 0 and len(c[0]) >= 2 and c[5] < min_coh:
            continue
        kept.append(c)
    kept_words = {c[0]: c for c in kept}
    return kept_words, cands


def score_old(kept_words):
    keep_hit = sum(1 for w in SHOULD_KEEP if w in kept_words)
    filt_hit = sum(1 for w in SHOULD_FILTER if w not in kept_words)
    keep_rate = keep_hit / len(SHOULD_KEEP)
    filt_rate = filt_hit / len(SHOULD_FILTER)
    return keep_hit, filt_hit, 0.5 * keep_rate + 0.5 * filt_rate


def is_hard_fragment(w):
    if w in HARD_FRAGMENTS:
        return True
    if len(w) == 2:
        if w[0] == "之" or w[1] == "之":
            return True
        if w[0] == "我":
            return True
    return False


def analyze(name, kept_words, cands):
    total = len(kept_words)
    frags = [w for w in kept_words if is_hard_fragment(w)]
    frags_sorted = sorted(frags, key=lambda x: -kept_words[x][1])
    # 按 count 排序 top 列表
    top = sorted(kept_words.items(), key=lambda kv: -kv[1][1])[:50]
    top_words = [w for w, _ in top]
    # 高频误伤：全候选中 count>=5 但被过滤掉的词
    kept_set = set(kept_words)
    overkill = sorted([(c[0], c[1]) for c in cands if c[0] not in kept_set and c[1] >= 5],
                      key=lambda x: -x[1])
    # 边界词去向
    bound = {w: (w in kept_words) for w in BOUNDARY}
    k, f, sc = score_old(kept_words)
    return {
        "name": name, "total": total, "frag_count": len(frags),
        "frag_top20": frags_sorted[:20],
        "top50": top_words,
        "overkill_highfreq": overkill,
        "boundary": bound,
        "old_keep": k, "old_filt": f, "old_score": round(sc, 4),
    }


def main():
    v211 = load_grow(os.path.join(EV, "v211_grow.py"))
    v216 = load_grow(os.path.join(EV, "v216_grow.py"))
    v217 = load_grow(os.path.join(EV, "v217_grow.py"))

    r211 = run_version(v211, 0.25, 0.5)
    r216 = run_version(v216, 0.25, 0.5, pos_fixed=0.80)
    r217 = run_version(v217, 0.25, 0.5, min_coh=1.5)

    out = {
        "v211_main": analyze("main 2.1.11", *r211),
        "v216_posfixed": analyze("pos-fixed 2.1.16", *r216),
        "v217_cohesion": analyze("cohesion 2.1.17", *r217),
    }
    with open(os.path.join(EV, "eval_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # 摘要打印
    print("=" * 70)
    print(f"{'指标':<24}{'v211 main':<16}{'v216 posfixed':<16}{'v217 cohesion':<16}")
    print("-" * 70)
    for key, label in [("total", "输出总词数"), ("frag_count", "硬碎片残留数"),
                       ("old_keep", "旧金标准 keep/37"), ("old_filt", "旧金标准 filt/25"),
                       ("old_score", "旧金标准 score")]:
        a, b, c = out["v211_main"][key], out["v216_posfixed"][key], out["v217_cohesion"][key]
        if key == "old_keep":
            a, b, c = f"{a}/37", f"{b}/37", f"{c}/37"
        if key == "old_filt":
            a, b, c = f"{a}/25", f"{b}/25", f"{c}/25"
        print(f"{label:<24}{str(a):<16}{str(b):<16}{str(c):<16}")
    print("=" * 70)
    for vkey in ["v211_main", "v216_posfixed", "v217_cohesion"]:
        r = out[vkey]
        print(f"\n### {r['name']} 边界词去向:")
        print("  " + " ".join(f"{w}:{'留' if v else '滤'}" for w, v in r["boundary"].items()))
        print(f"  高频误伤(count>=5被滤) {len(r['overkill_highfreq'])} 个，top10: "
              + ", ".join(f"{w}({n})" for w, n in r["overkill_highfreq"][:10]))
        print(f"  top30 高频词: " + ", ".join(r["top50"][:30]))


if __name__ == "__main__":
    main()
