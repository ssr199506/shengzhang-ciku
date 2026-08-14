# -*- coding: utf-8 -*-
"""错题集生成器：三版本输出全集 → 交集/差集 7 类划分 → 每词标注留滤状态。

版本分层（用户定义）：
  v211  main 2.1.11       —— 主分支（纯复合熵，自研基线）
  v216  pos-fixed 2.1.16  —— 位置信息版（自研位置固定度豁免，pf=0.80）
  v217  cohesion 2.1.17   —— 加入外来算法版（GitHub 引入的凝固度 PMI，coh=1.5）

类别含义（留=1 滤=0，按 v211/v216/v217 顺序）：
  111  三版共识保留 —— 大家都认识，识别难度最低 → 标注为「优先级最低」
  110  v211+v216 留、v217 滤 —— 凝固度排除的（多为松散搭配碎片）
  101  v211+v217 留、v216 滤 —— 位置固定度排除的（多为"位置不够固定"的碎片）
  011  v216+v217 留、v211 滤 —— 主分支排除的（复合熵误杀的边界词）
  100  仅 v211 独留 —— 主分支独有判断
  010  仅 v216 独留 —— 位置固定度独门救回的真词
  001  仅 v217 独留 —— 凝固度独门判断

产出：
  mistake_book.csv   —— 全量标注数据集（机器可读，可回灌/二次分析）
  mistake_book.md    —— 分层错题集报告（人可读）
"""
import importlib.util, csv, os, json, collections

EV = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(EV))  # 仓库根
CSV = os.path.join(BASE, "corpus.csv")  # 付费语料，自备并命名为 corpus.csv（不入库）
MIN_ENT = 0.5
ENT_MR = 0.25
POS_FIXED = 0.80
MIN_COH = 1.5

# ---- 分层标签 ----
LAYER = {
    "111": ("共识层", "三版共识保留：识别难度最低，优先级最低（大家都不错）"),
    "110": ("凝固度排除", "v211+v216 保留，仅凝固度版排除：多为松散搭配/低凝固度碎片"),
    "101": ("位置排除", "v211+v217 保留，仅位置版排除：多为位置固定度不足的碎片"),
    "011": ("主分支排除", "v216+v217 保留，仅主分支排除：复合熵单信号误杀的边界词"),
    "100": ("主分支独留", "仅主分支保留：自研单信号独门判断（需人工核）"),
    "010": ("位置独留", "仅位置版保留：位置固定度独门救回的真词（价值最高）"),
    "001": ("凝固度独留", "仅凝固度版保留：外来算法独门判断（需人工核）"),
    "000": ("众矢之的", "三版本一致排除（count≥5）：'共识'不一定对——内含被一致误杀的真词，最高优先复核"),
}


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


def run_version(grow, pos_fixed=None, min_coh=0.0):
    """返回 (保留词{word:指标}, 全候选{word:指标})。全候选用于给被滤词补指标（错题集需要）。"""
    docs = build_title_docs(grow)
    S, wgt = grow.build_corpus(docs)
    if pos_fixed is not None:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, pos_fixed_thr=pos_fixed)
    elif hasattr(grow, "build_ngram_freq"):
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True, cohesion_max_len=8)
    else:
        cands, _ = grow.scan_and_grow(S, wgt, ENT_MR, True)
    kept = {}
    allm = {}
    for c in cands:
        w = c[0]
        ent = c[4]
        m = {"count": c[1], "ind": c[2], "bind": c[3], "ent": round(ent, 3)}
        if len(c) > 5:
            m["coh"] = round(c[5], 3)
        allm[w] = m
        if not (ent < 0 or ent >= MIN_ENT):
            continue
        if min_coh > 0 and len(w) >= 2 and c[5] < min_coh:
            continue
        kept[w] = m
    return kept, allm


def main():
    v211 = load_grow(os.path.join(EV, "v211_grow.py"))
    v216 = load_grow(os.path.join(EV, "v216_grow.py"))
    v217 = load_grow(os.path.join(EV, "v217_grow.py"))

    r211, a211 = run_version(v211)
    r216, a216 = run_version(v216, pos_fixed=POS_FIXED)
    r217, a217 = run_version(v217, min_coh=MIN_COH)

    s211, s216, s217 = set(r211), set(r216), set(r217)
    all_words = s211 | s216 | s217

    # 三版全滤层（000）：三个版本都不保留，但 count>=5 的高频候选（有价值的"众矢之的"）
    cand_all = set(a211) | set(a216) | set(a217)
    filtered_all = cand_all - all_words
    rows_000 = []
    for w in filtered_all:
        src = a211.get(w) or a216.get(w) or a217.get(w)
        if src["count"] < 5:
            continue
        m = {"word": w, "count": src["count"], "v211": 0, "v216": 0, "v217": 0,
             "class": "000", "layer": "众矢之的",
             "note": "三版本一致排除：熵/位置/凝固度都认为该滤，优先级最高（难度最大）"}
        for tag, allm in (("211", a211), ("216", a216), ("217", a217)):
            src2 = allm.get(w)
            if src2:
                for k, v in src2.items():
                    if k in ("count", "ind", "bind", "ent", "coh"):
                        m[f"{tag}_{k}"] = v
        rows_000.append(m)

    # ---- 每词标注：三版本留/滤 + 合并指标 + 类别 ----
    # 指标优先取保留版；被某版滤掉的词从全候选补指标（-1 表示该版未产出/无此指标）
    rows = []
    for w in all_words:
        bit = "".join("1" if x else "0" for x in (w in s211, w in s216, w in s217))
        m = {"word": w, "count": 0}
        for tag, kept, allm in (("211", r211, a211), ("216", r216, a216), ("217", r217, a217)):
            src = kept.get(w) or allm.get(w) or {}
            m[f"v{tag}"] = 1 if w in kept else 0
            for k, v in src.items():
                if k in ("count", "ind", "bind", "ent", "coh"):
                    m[f"{tag}_{k}"] = v
        m["count"] = max(m.get("211_count", 0), m.get("216_count", 0), m.get("217_count", 0))
        m["class"] = bit
        m["layer"], m["note"] = LAYER[bit]
        rows.append(m)
    rows.extend(rows_000)

    # 排序：count 降序（高频优先看）
    rows.sort(key=lambda r: -r["count"])

    # ---- CSV 全量标注 ----
    cols = ["word", "count", "v211", "v216", "v217", "class", "layer",
            "211_ent", "216_ent", "217_ent", "217_coh", "211_ind", "note"]
    with open(os.path.join(EV, "mistake_book.csv"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow(r)

    # ---- 分层统计 ----
    by_class = collections.Counter(r["class"] for r in rows)
    by_layer = collections.Counter(r["layer"] for r in rows)

    # ---- MD 报告 ----
    lines = []
    A = lines.append
    A("# 三版本输出错题集（交集/差集分层标注）\n")
    A(f"> 生成时间：2026-08-13 · 语料：起点标题（~1.5 万条去重）· 参数：me{MIN_ENT}+mr{ENT_MR}，v216 pf{POS_FIXED}，v217 coh{MIN_COH}\n")
    A("> 留=1 滤=0，类别按 v211/v216/v217 顺序编码。`layer` 即'优先级/难度'标注——**共识层（111）识别难度最低、优先级最低**。\n")
    A("> **怎么读这张错题集**：① 三类都留的（111）是'送分题'，优先级最低；② 三类都滤的（不在本表）是'众矢之的'；③ 真正有价值的是**有分歧的层**——某个算法独留/独滤的词，正是它区别于其他算法的能力边界。\n")
    A("> **列说明**：`熵(v211)`=纯复合熵；`熵(v216)`=位置固定度豁免后的熵（-1 表示双侧豁免）；`凝固度(v217)`=外来 PMI（min-PMI）。被某版滤掉的词其指标仍列出（来自全候选），方便判断'该滤掉的是不是真词'。\n")
    A("\n## 一、分层总览\n")
    A("| 类别 | 层名 | 词数 | 含义 |")
    A("|---|---|---|---|")
    for bit in ["111", "110", "101", "011", "100", "010", "001", "000"]:
        name, note = LAYER[bit]
        A(f"| {bit} | **{name}** | {by_class.get(bit, 0)} | {note} |")
    A("")
    A(f"**三版本输出词数**：v211={len(s211)} · v216={len(s216)} · v217={len(s217)} · 全并集={len(all_words)} · 全候选={len(cand_all)}（余下为三版全滤且 count<5 的低频碎片，未入册）\n")

    # 每层详情
    for bit in ["111", "010", "110", "101", "011", "001", "100", "000"]:
        name, _ = LAYER[bit]
        grp = [r for r in rows if r["class"] == bit]
        if not grp:
            continue
        A(f"\n## 二、{name}（{bit}，{len(grp)} 词）\n")
        # 111 层特殊：共识层里也有共同盲区（高频句法碎片：我的/这个/成了/一个…）
        if bit == "111":
            A("> **⚠️ 共识层≠无错**：三版一致保留的 top 高频里仍有共同盲区——`我的/我在/我是/我有/这个/成了/一个`"
              " 这类句法碎片 count 极高、凝固度也高，熵/位置/凝固度三个信号全部滤不掉（需第四维度'句法停用词表'）。"
              " 它们才是污染 top 高频榜的真凶。\n")
        # 110 层特殊：标注"疑似被凝固度误杀的真词"（coh>=1.5 的，内部绑定其实很强）
        if bit == "110":
            sus = [r for r in grp if r.get("217_coh") is not None and float(r["217_coh"]) >= MIN_COH]
            if sus:
                sus.sort(key=lambda r: -r["count"])
                A(f"> **⚠️ 疑似误杀真词 {len(sus)} 个**：内部凝固度≥{MIN_COH}（绑定强），却被 v217 滤掉。"
                  f"这些词是凝固度闸门过严的疑点，需人工复核。Top："
                  + "、".join(f"{r['word']}(coh{r['217_coh']})" for r in sus[:12]) + "\n")
        # 000 层特殊：三版全滤的"共识"也不总是对的——按凝固度分"疑似误杀真词/真碎片"
        if bit == "000":
            sus = [r for r in grp if r.get("217_coh") is not None and float(r["217_coh"]) >= 6.0]
            if sus:
                sus.sort(key=lambda r: -r["count"])
                A(f"> **⚠️ 疑似被三版一致误杀的真词 {len(sus)} 个**：凝固度≥6.0（内部绑定很强，长得像词），"
                  f"却被熵+位置+凝固度一致排除。**'三版共识'≠'正确'**——这类词是下一步最该复核的："
                  + "、".join(f"{r['word']}({r['count']})" for r in sus[:15]) + "\n")
        # 每层给 count>=5 的完整表 + count<5 的 top 抽样
        hi = [r for r in grp if r["count"] >= 5]
        lo = [r for r in grp if r["count"] < 5]
        hi.sort(key=lambda r: -r["count"])
        lo.sort(key=lambda r: -r["count"])
        show = hi[:60] + lo[:25]
        A("| 词 | count | v211 | v216 | v217 | 熵(v211) | 熵(v216) | 熵(v217) | 凝固度(v217) |")
        A("|---|---|---|---|---|---|---|---|---|")
        for r in show:
            A(f"| {r['word']} | {r['count']} | {r['v211']} | {r['v216']} | {r['v217']} "
              f"| {r.get('211_ent','-')} | {r.get('216_ent','-')} | {r.get('217_ent','-')} | {r.get('217_coh','-')} |")
        if len(hi) > 60:
            A(f"\n…（count≥5 共 {len(hi)} 词，仅示 top60；count<5 共 {len(lo)} 词，仅示 top25）")
        elif len(grp) > len(show):
            A(f"\n…（count<5 共 {len(lo)} 词，仅示 top25）")

    with open(os.path.join(EV, "mistake_book.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # ---- 控制台摘要 ----
    print("=" * 66)
    print(f"{'类别':<6}{'层名':<12}{'词数':>6}")
    print("-" * 66)
    for bit in ["111", "110", "101", "011", "100", "010", "001", "000"]:
        name, _ = LAYER[bit]
        print(f"{bit:<6}{name:<12}{by_class.get(bit, 0):>6}")
    print("-" * 66)
    print(f"{'并集':<6}{'三版本任一保留':<12}{len(all_words):>6}")
    print(f"{'候选':<6}{'三版本全候选':<12}{len(cand_all):>6}")
    print(f"\n输出：mistake_book.csv（全量标注 {len(rows)} 词）、mistake_book.md（分层报告）")


if __name__ == "__main__":
    main()
