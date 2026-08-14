#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_plan_v2.py —— 《信号判定与定向调参方案》v2 全量执行器 + 自主深化。

与 run_full_union.py（旧 8 层 68 档全网格）的区别：
  - 本脚本只跑 v2 方案认定「与救援门语义相容」的档位（不含任何 role/asym 过滤门）；
  - 层1/3/5/6 是纯分析层（不新增档位），依赖一张「全候选池信号表」；
  - 追加 D1~D4 自主深化层：把二维面加宽加密、扫 role_alpha（方案未覆盖）、消融对照。

层次：
  L1 分离带实测      纯分析  max(应滤∩被滤集) vs min(base∩真词)，判过滤门是否可能干净
  L2 救援二维网格    15 档   asym_rescue{1.5..2.5} × role_rescue{0.6,0.7,0.8}
  L3 碎片混叠定量    纯分析  F3 相对 base 新增词的 role/asym 分布与碎片盒混叠率
  L4 U2 vs 不动点    2 档    role_max_depth 1 / -1
  L5 焊死真词确认    纯分析  真词是否连候选池都进不去（结构性焊死）
  L6 top200 视图     纯分析  base / F3 / L2最佳 的高频前 200 对比
  D1 二维面加宽加密  110 档  asym 1.0~3.5 步0.25 × role 0.50~0.95 步0.05
  D2 深度×最佳点     5 档    role_max_depth 1/2/3/4/-1
  D3 消融与正交      5 档    role-only / asym-only / both / +spe / +rsr
  D4 role_alpha 扫   10 档   alpha 0.50~0.95（方案未覆盖的可疑旋钮）

用法：
    python run_plan_v2.py                 # 全跑（含深化）
    python run_plan_v2.py --only L2 L4    # 只跑指定层
    python run_plan_v2.py --skip-run      # 已有档不重跑，只重算分析
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_full_union import (BASE_CLI, CORPUS, FILT, FRAGS, KEEP, PAST_BASE,  # noqa: E402
                           ROOT, TRUE_000, load_words)

OUT = os.path.join(ROOT, "调参产物", "plan_v2")
POOL_DIR = os.path.join(OUT, "_pool")

TRUE_ALL = sorted(set(KEEP) | set(TRUE_000))          # 52 真词
BAD_ALL = sorted(set(FILT) | set(FRAGS))              # 应过滤/碎片

F3 = ["--role", "--role-max-depth", "-1", "--role-rescue", "0.7",
      "--asym", "--asym-rescue", "2.0"]


# ------------------------------------------------------------------ 档位网格
def rescue(asym, role, depth=-1, alpha=None, extra=None):
    a = ["--asym", "--asym-rescue", f"{asym:.2f}",
         "--role", "--role-max-depth", str(depth), "--role-rescue", f"{role:.2f}"]
    if alpha is not None:
        a += ["--role-alpha", f"{alpha:.2f}"]
    return a + list(extra or [])


def G_L2():
    return [(f"L2_a{a:.2f}_r{r:.2f}", rescue(a, r))
            for a in (1.5, 1.75, 2.0, 2.25, 2.5) for r in (0.6, 0.7, 0.8)]


def G_L4():
    return [("L4_U2(a2.0_r0.7)", rescue(2.0, 0.7, depth=1)),
            ("L4_fix(a2.0_r0.7)", rescue(2.0, 0.7, depth=-1))]


def G_D1():
    aa = [1.0 + 0.25 * i for i in range(11)]           # 1.00~3.50
    rr = [0.50 + 0.05 * i for i in range(10)]          # 0.50~0.95
    return [(f"D1_a{a:.2f}_r{r:.2f}", rescue(a, r)) for a in aa for r in rr]


def G_D2():
    return [(f"D2_depth{d}", rescue(2.0, 0.7, depth=d)) for d in (1, 2, 3, 4, -1)]


def G_D3():
    return [
        ("D3_roleonly0.7", ["--role", "--role-max-depth", "-1", "--role-rescue", "0.7"]),
        ("D3_asymonly2.0", ["--asym", "--asym-rescue", "2.0"]),
        ("D3_both", rescue(2.0, 0.7)),
        ("D3_both+spe0.8", rescue(2.0, 0.7, extra=["--spe-rescue", "0.8"])),
        ("D3_both+spe0.8+rsr0.5", rescue(2.0, 0.7,
                                         extra=["--spe-rescue", "0.8", "--rsr-rescue", "0.5"])),
    ]


def G_D4():
    return [(f"D4_alpha{al:.2f}", rescue(2.0, 0.7, alpha=al))
            for al in [0.50 + 0.05 * i for i in range(10)]]


GRIDS = {"L2": G_L2, "L4": G_L4, "D1": G_D1, "D2": G_D2, "D3": G_D3, "D4": G_D4}
ANALYSIS = ["L1", "L3", "L5", "L6"]


# ------------------------------------------------------------------ 执行
def run_one(label, extra, skip_run=False, out_root=None):
    d = os.path.join(out_root or OUT, label)
    wf = os.path.join(d, "title_wordfreq.csv")
    if skip_run and os.path.exists(wf):
        return wf
    os.makedirs(d, exist_ok=True)
    r = subprocess.run(BASE_CLI + extra + ["--out", d], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT,
                       env={**os.environ, "CODEBUDDY_SESSION_ID": "", "CLAUDE_SESSION_ID": ""})
    if r.returncode != 0:
        print(f"  [FAIL] {label}: {r.stderr.strip()[-300:]}", file=sys.stderr)
        return None
    return wf


def load_table(path):
    """读带信号列的词表 → {word: {col: val}}。"""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        for row in rd:
            if not row:
                continue
            rec = {}
            for k, v in zip(head[1:], row[1:]):
                try:
                    rec[k] = float(v)
                except ValueError:
                    rec[k] = v
            out[row[0]] = rec
    return out


# ------------------------------------------------------------------ 评估
BASE_SET = None
BASE_FRAG_LIVE = None


def eval_one(label, words):
    """相对 base 锚点的交并指标。"""
    s = set(words)
    add, rem = s - BASE_SET, BASE_SET - s
    a000 = sorted(add & set(TRUE_000))
    afrg = sorted(add & set(FRAGS))
    r000 = sorted(rem & set(TRUE_000))
    rfrg = sorted(rem & set(FRAGS))
    return {
        "case": label, "n": len(s), "add": len(add), "rem": len(rem),
        "live_000": len(s & set(TRUE_000)), "live_frag": len(s & set(FRAGS)),
        "keep": len(s & set(KEEP)), "filt": len(s & set(FILT)),
        "add_000": len(a000), "add_frag": len(afrg),
        "rem_000": len(r000), "rem_frag": len(rfrg),
        "net": len(a000) - len(r000) + len(rfrg) - len(afrg),
        "add_000_w": "+".join(a000), "add_frag_w": "+".join(afrg),
        "rem_000_w": "+".join(r000),
    }


def q(vals, p):
    if not vals:
        return float("nan")
    v = sorted(vals)
    i = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
    return v[i]


SENT = -1.0          # 无超词哨兵（role/asym 同一集合）


def valid(pool, w, sig):
    """有效信号：非 -1 哨兵。哨兵在 gates 里是"结构豁免"，不能当成低分参与分离带。"""
    return w in pool and sig in pool[w] and abs(pool[w][sig] - SENT) > 1e-9


# ------------------------------------------------------------------ 层1 分离带
def layer1(pool, rep):
    """max(应滤∩被滤集G) vs min(base∩真词B∩T) —— 过滤门与救援门能否共用一个阈值。

    口径修正：role/asym 的 -1 是"无超词结构豁免"哨兵，gates.py 里 `w.role<0 or ...`
    表示**放行**而非拒绝，因此哨兵词绝不能当低分算进 min/max，否则分离带被伪造。
    """
    B = BASE_SET & set(pool)                  # base 保留且在候选池内
    G = set(pool) - BASE_SET                  # 被 ent/coh/indep 滤掉的候选
    sent = {w for w in pool if not valid(pool, w, "role")}
    rep += ["## 层1 分离带实测（过滤门可行性）", "",
            f"候选池 {len(pool)} 词 | base∩池 B={len(B)} | 被滤集 G={len(G)}", "",
            "### 1.0 信号覆盖率（先决问题：信号根本管不到多少词）", "",
            f"- 无超词哨兵 role=asym=-1：**{len(sent)}/{len(pool)} = {len(sent)/len(pool):.1%}**"
            f"（role 与 asym 哨兵集完全同一，皆由「无超词」触发）",
            f"- 有效信号词：{len(pool)-len(sent)}（{1-len(sent)/len(pool):.1%}）", "",
            "| 分区 | 词数 | 哨兵数 | 有效信号率 |", "|---|---|---|---|"]
    for nm, s in (("B=base保留", B), ("G=被滤集", G),
                  ("真词∩B", set(TRUE_ALL) & B), ("真词∩G", set(TRUE_ALL) & G),
                  ("应滤∩B", set(BAD_ALL) & B), ("应滤∩G", set(BAD_ALL) & G)):
        ns = len(s & sent)
        rep.append(f"| {nm} | {len(s)} | {ns} | {1-ns/max(1,len(s)):.1%} |")
    rep += ["", "> 哨兵词对救援门**永远不可达**（-1 < 任何正阈值），对过滤门**永远豁免**。"
            "这是 role/asym 两个信号的硬上限，与阈值怎么调无关。", "",
            "### 1.1 分离带（仅有效信号参与）", "",
            "判据：存在 θ 同时干净 ⟺ **max(应滤∩G) < min(真词∩B)**（分离带非空）。", "",
            "| 信号 | max(应滤∩G) 及词 | min(真词∩B) 及词 | 分离带 | 结论 |",
            "|---|---|---|---|---|"]
    verdict = {}
    for sig in ("role", "asym"):
        fg = [(pool[w][sig], w) for w in BAD_ALL if w in G and valid(pool, w, sig)]
        bt = [(pool[w][sig], w) for w in TRUE_ALL if w in B and valid(pool, w, sig)]
        if not fg or not bt:
            continue
        hi, hw = max(fg)
        lo, lw = min(bt)
        band = lo - hi
        verdict[sig] = {"max_FG": hi, "max_FG_w": hw, "min_BT": lo, "min_BT_w": lw,
                        "band": band, "clean_possible": band > 0,
                        "n_FG": len(fg), "n_BT": len(bt)}
        rep.append(f"| {sig} | {hi:.4f} (`{hw}`) | {lo:.4f} (`{lw}`) | {band:+.4f} | "
                   f"{'✅ 可能存在干净过滤门' if band > 0 else '❌ 混叠，过滤门必伤真词'} |")
    rep += ["", "### 1.2 救援可达性（被滤集里的真词能否被同一阈值捞回）", "",
            "| 信号 | 真词∩G 有效 | min(真词∩G) | max(应滤∩G) | 救援窗口 | 纯净可救真词数 |",
            "|---|---|---|---|---|---|"]
    for sig in ("role", "asym"):
        tg = [(pool[w][sig], w) for w in TRUE_ALL if w in G and valid(pool, w, sig)]
        fg = [(pool[w][sig], w) for w in BAD_ALL if w in G and valid(pool, w, sig)]
        if not tg or not fg:
            continue
        lo, lw = min(tg)
        hi, hw = max(fg)
        pure = [w for v, w in tg if v > hi]      # 阈值设在 max(应滤) 之上仍能救回的真词
        verdict.setdefault(sig, {})["pure_rescuable"] = pure
        rep.append(f"| {sig} | {len(tg)}/{len(set(TRUE_ALL)&G)} | {lo:.4f} (`{lw}`) | "
                   f"{hi:.4f} (`{hw}`) | {lo - hi:+.4f} | {len(pure)}（{' '.join(pure) or '—'}）|")
    rep += ["", "> 「纯净可救」= 阈值抬到 max(应滤∩G) 之上时还能捞回的真词数。若为 0，"
            "说明**任何**该信号的救援门都必然连带捞进应滤词——增益与污染同源，不可分。", ""]
    # asym 负值区语义空洞（计划未覆盖）
    realneg = [w for w in pool if valid(pool, w, "asym") and pool[w]["asym"] < 0]
    rep += ["### 1.3 asym 负值区语义空洞（自主发现，方案未覆盖）", "",
            f"- 真实负 asym（非哨兵）仅 **{len(realneg)}** 词：" + " ".join(sorted(realneg)[:40]),
            f"- 其中真词 {len(set(realneg)&set(TRUE_ALL))}（"
            + " ".join(sorted(set(realneg) & set(TRUE_ALL))) + "），应滤/碎片 "
            f"{len(set(realneg)&set(BAD_ALL))}（" + " ".join(sorted(set(realneg) & set(BAD_ALL))) + "）",
            "- gates.py 的 `if w.asym < 0 or w.asym >= cfg.min_asym` 把**真实负值**与"
            "**哨兵 -1** 一起豁免；而 `--min-asym` 的文档语义是「低值=碎片、asym>=thresh 才留」。"
            "→ 过滤门恰恰删不到它最想删的负值碎片，语义空洞。", ""]
    verdict["asym_realneg"] = {"n": len(realneg),
                              "true": sorted(set(realneg) & set(TRUE_ALL)),
                              "bad": sorted(set(realneg) & set(BAD_ALL))}
    return verdict


# ------------------------------------------------------------------ 层3 碎片混叠
def layer3(pool, f3_words, rep):
    """F3 相对 base 新增词的 role/asym 分布，与已知碎片盒的混叠率。"""
    add = sorted(set(f3_words) - BASE_SET)
    frg = [w for w in FRAGS if w in pool]
    tru = [w for w in TRUE_ALL if w in pool]
    rep += ["## 层3 碎片混叠定量", "",
            f"F3 相对 base 新增 **{len(add)}** 词；已知碎片池内 {len(frg)}，真词池内 {len(tru)}。", "",
            "| 群体 | n | role p10 | role 中位 | role p90 | asym p10 | asym 中位 | asym p90 |",
            "|---|---|---|---|---|---|---|---|"]
    groups = [("F3新增", add), ("已知碎片", frg), ("已知真词", tru)]
    for name, ws in groups:
        rl = [pool[w]["role"] for w in ws if w in pool]
        ay = [pool[w]["asym"] for w in ws if w in pool]
        if not rl:
            continue
        rep.append(f"| {name} | {len(rl)} | {q(rl,.1):.3f} | {q(rl,.5):.3f} | {q(rl,.9):.3f} | "
                   f"{q(ay,.1):.2f} | {q(ay,.5):.2f} | {q(ay,.9):.2f} |")
    # 碎片盒混叠率
    rl = [pool[w]["role"] for w in frg if w in pool]
    ay = [pool[w]["asym"] for w in frg if w in pool]
    box = (min(rl), max(rl), min(ay), max(ay)) if rl else None
    if box:
        inside = [w for w in add if w in pool
                  and box[0] <= pool[w]["role"] <= box[1] and box[2] <= pool[w]["asym"] <= box[3]]
        rep += ["", f"碎片盒 role∈[{box[0]:.3f},{box[1]:.3f}] asym∈[{box[2]:.2f},{box[3]:.2f}]；"
                f"新增词落在盒内 **{len(inside)}/{len(add)} = {len(inside)/max(1,len(add)):.1%}**"
                "（信号层面与碎片不可分的比例）。", ""]
    hi_role = sorted((w for w in add if w in pool), key=lambda w: -pool[w]["role"])[:20]
    hi_asym = sorted((w for w in add if w in pool), key=lambda w: -pool[w]["asym"])[:20]
    rep += ["新增词 role Top20：" + " ".join(f"{w}({pool[w]['role']:.2f})" for w in hi_role), "",
            "新增词 asym Top20：" + " ".join(f"{w}({pool[w]['asym']:.1f})" for w in hi_asym), ""]
    return {"n_add": len(add), "alias_rate": (len(inside) / max(1, len(add))) if box else None}


# ------------------------------------------------------------------ 层4 深度差异
def layer4(pool, rows_by_case, rep, skip_run):
    a = load_words(run_one("L4_U2(a2.0_r0.7)", rescue(2.0, 0.7, depth=1), skip_run))
    b = load_words(run_one("L4_fix(a2.0_r0.7)", rescue(2.0, 0.7, depth=-1), skip_run))
    sa, sb = set(a), set(b)
    only_u2, only_fix = sorted(sa - sb), sorted(sb - sa)
    rep += ["## 层4 U2(depth=1) vs 不动点(depth=-1)", "",
            f"U2 {len(sa)} 词 | 不动点 {len(sb)} 词 | 对称差 {len(sa ^ sb)} 词", "",
            f"- 仅 U2 有（{len(only_u2)}）：" + (" ".join(only_u2[:40]) or "—"),
            f"- 仅不动点有（{len(only_fix)}）：" + (" ".join(only_fix[:40]) or "—"), ""]
    diff = sorted(sa ^ sb)
    hit_t = [w for w in diff if w in set(TRUE_ALL)]
    hit_f = [w for w in diff if w in set(FRAGS) | set(FILT)]
    rep += [f"- 差异词命中真词集：{len(hit_t)}（{' '.join(hit_t) or '—'}）",
            f"- 差异词命中应滤/碎片集：{len(hit_f)}（{' '.join(hit_f) or '—'}）", ""]
    for lab, s in (("L4_U2(a2.0_r0.7)", sa), ("L4_fix(a2.0_r0.7)", sb)):
        r = rows_by_case.get(lab)
        if r:
            rep.append(f"- `{lab}`：词数 {r['n']}，000真词 {r['live_000']}/15，"
                       f"碎片 {r['live_frag']}/18，keep {r['keep']}/37，net {r['net']}")
    rep += [""]
    return {"sym_diff": len(sa ^ sb), "diff_true": hit_t, "diff_bad": hit_f}


# ------------------------------------------------------------------ 层5 焊死真词
def layer5(pool, best_words, rep):
    miss_pool = [w for w in TRUE_ALL if w not in pool]
    in_pool_miss = [w for w in TRUE_ALL if w in pool and w not in best_words]
    rep += ["## 层5 焊死真词确认（结构上限在哪）", "",
            f"- **候选池都没有**（分词阶段就焊死，任何闸门都救不回）：{len(miss_pool)} 词 → "
            + (" ".join(miss_pool) or "—"),
            f"- 在池内但最佳档仍未收（信号不够）：{len(in_pool_miss)} 词", ""]
    if in_pool_miss:
        rep += ["| 词 | count | ent | cohesion | indep | role | asym |", "|---|---|---|---|---|---|---|"]
        for w in in_pool_miss:
            p = pool[w]
            rep.append(f"| {w} | {int(p.get('count',0))} | {p.get('compound_entropy',float('nan')):.3f} | "
                       f"{p.get('bind',float('nan')):.4f} | {p.get('independent',float('nan')):.0f} | "
                       f"{p.get('role',float('nan')):.4f} | {p.get('asym',float('nan')):.3f} |")
        rep += [""]
    if miss_pool:
        rep += ["> 焊死词的共同点需人工核：多为长书名/生僻字，未被切出候选，属**分词层**问题，"
                "不在闸门调参可达范围内。", ""]
    return {"welded": miss_pool, "signal_short": in_pool_miss}


# ------------------------------------------------------------------ 层6 top200
def layer6(cases, rep):
    rep += ["## 层6 高频 top200 视图（词云实际可见区）", "",
            "| 档位 | top200 中真词 | top200 中碎片 | top200 中应滤 |", "|---|---|---|---|"]
    for lab, path in cases:
        rows = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for r in rd:
                if r:
                    rows.append((r[0], int(r[1])))
        top = [w for w, _ in sorted(rows, key=lambda x: -x[1])[:200]]
        s = set(top)
        rep.append(f"| {lab} | {len(s & set(TRUE_ALL))} | {len(s & set(FRAGS))} | "
                   f"{len(s & set(FILT))} |")
    rep += [""]


# ------------------------------------------------------------------ 二维面
def surface(rows_by_case, prefix, aa, rr, metric, rep, title):
    rep += [f"### {title}（指标 {metric}）", "",
            "| asym\\role | " + " | ".join(f"{r:.2f}" for r in rr) + " |",
            "|---" * (len(rr) + 1) + "|"]
    for a in aa:
        line = [f"| **{a:.2f}** "]
        for r in rr:
            row = rows_by_case.get(f"{prefix}_a{a:.2f}_r{r:.2f}")
            line.append(f"| {row[metric]}" if row else "| —")
        rep.append("".join(line) + " |")
    rep += [""]


# ------------------------------------------------------------------ main
def main():
    global BASE_SET
    ap = argparse.ArgumentParser(description="v2 方案全量执行器 + 自主深化")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只跑指定层：L1 L2 L3 L4 L5 L6 D1 D2 D3 D4")
    ap.add_argument("--skip-run", action="store_true")
    args = ap.parse_args()
    todo = args.only or ["L1", "L2", "L3", "L4", "L5", "L6", "D1", "D2", "D3", "D4"]
    os.makedirs(OUT, exist_ok=True)

    past = load_words(PAST_BASE)
    BASE_SET = set(past)
    print(f"锚点 base: {len(BASE_SET)} 词")

    # 全候选池（关掉 ent/coh/indep，只算信号）——层1/3/5 的公共底表
    print("== 生成全候选池信号表 ==")
    pool_wf = run_one("_pool", ["--min-ent", "0", "--cohesion", "0", "--indep", "0",
                                "--role", "--role-max-depth", "-1", "--asym"], args.skip_run)
    pool = load_table(pool_wf)
    print(f"候选池 {len(pool)} 词 | base⊆池? {len(BASE_SET - set(pool))} 词不在池内")

    # F3 参考档
    f3_wf = run_one("F3_ref(a2.0_r0.7)", F3, args.skip_run)
    f3_words = load_words(f3_wf)

    # 跑档
    rows = []
    for layer in [t for t in todo if t in GRIDS]:
        grid = GRIDS[layer]()
        print(f"== {layer}：{len(grid)} 档 ==")
        for i, (label, extra) in enumerate(grid, 1):
            wf = run_one(label, extra, args.skip_run)
            if not wf:
                continue
            r = eval_one(label, load_words(wf))
            r["layer"] = layer
            rows.append(r)
            if i % 10 == 0 or len(grid) < 16:
                print(f"  [{i}/{len(grid)}] {label:<24} n={r['n']} 000={r['live_000']} "
                      f"frag={r['live_frag']} net={r['net']}")

    # 补入参考档
    for lab, ws in (("base(锚点)", past), ("F3_ref(a2.0_r0.7)", f3_words)):
        r = eval_one(lab, ws)
        r["layer"] = "ref"
        rows.append(r)

    rows_by_case = {r["case"]: r for r in rows}
    with open(os.path.join(OUT, "union_summary_v2.csv"), "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (-r["net"], r["n"])))

    # ---- 报告 ----
    rep = ["# v2 方案全量执行报告（信号判定与定向调参）", "",
           f"语料 8887 书 | 锚点 base {len(BASE_SET)} 词 | 候选池 {len(pool)} 词 | "
           f"执行层 {' '.join(todo)} | 实跑档 {len([r for r in rows if r['layer']!='ref'])}", "",
           "指标：live_000=15 个 base 漏收真词的存活数（越大越好）；live_frag=18 个已知碎片"
           "存活数（越小越好）；net=真词净增+碎片净减。", ""]
    ana = {}
    if "L1" in todo:
        ana["L1"] = layer1(pool, rep)
    if "L2" in todo:
        rep += ["## 层2 救援二维网格（15 档）", ""]
        surface(rows_by_case, "L2", (1.5, 1.75, 2.0, 2.25, 2.5), (0.6, 0.7, 0.8),
                "net", rep, "net 面")
        surface(rows_by_case, "L2", (1.5, 1.75, 2.0, 2.25, 2.5), (0.6, 0.7, 0.8),
                "live_000", rep, "真词存活面")
        surface(rows_by_case, "L2", (1.5, 1.75, 2.0, 2.25, 2.5), (0.6, 0.7, 0.8),
                "n", rep, "词数面")
        l2 = sorted([r for r in rows if r["layer"] == "L2"], key=lambda r: (-r["net"], r["n"]))
        rep += ["层2 排名（净收益优先，同分取词数少）：", ""]
        for r in l2[:6]:
            rep.append(f"- `{r['case']}` net={r['net']} n={r['n']} 000={r['live_000']}/15 "
                       f"frag={r['live_frag']}/18 keep={r['keep']}/37 新增真词={r['add_000_w'] or '—'}")
        rep += [""]
    if "L3" in todo:
        ana["L3"] = layer3(pool, f3_words, rep)
    if "L4" in todo:
        ana["L4"] = layer4(pool, rows_by_case, rep, args.skip_run)
    best = max((r for r in rows if r["layer"] != "ref"), key=lambda r: (r["net"], -r["n"]),
               default=None) if len(rows) > 2 else None
    if "L5" in todo:
        bw = load_words(os.path.join(OUT, best["case"], "title_wordfreq.csv")) if best else f3_words
        ana["L5"] = layer5(pool, set(bw), rep)
    if "L6" in todo:
        cases = [("base(锚点)", PAST_BASE), ("F3_ref", f3_wf)]
        if best:
            cases.append((best["case"], os.path.join(OUT, best["case"], "title_wordfreq.csv")))
        layer6(cases, rep)
    if "D1" in todo:
        aa = [1.0 + 0.25 * i for i in range(11)]
        rr = [0.50 + 0.05 * i for i in range(10)]
        rep += ["## D1 二维面加宽加密（110 档，自主深化）", ""]
        surface(rows_by_case, "D1", aa, rr, "net", rep, "net 面")
        surface(rows_by_case, "D1", aa, rr, "live_000", rep, "真词存活面")
        surface(rows_by_case, "D1", aa, rr, "live_frag", rep, "碎片存活面")
        surface(rows_by_case, "D1", aa, rr, "n", rep, "词数面")
        d1 = sorted([r for r in rows if r["layer"] == "D1"], key=lambda r: (-r["net"], r["n"]))
        rep += ["D1 Top10：", ""]
        for r in d1[:10]:
            rep.append(f"- `{r['case']}` net={r['net']} n={r['n']} 000={r['live_000']} "
                       f"frag={r['live_frag']} keep={r['keep']}")
        rep += [""]
    for layer, title in (("D2", "D2 role 迭代深度 × 最佳救援点"),
                         ("D3", "D3 消融与正交（谁贡献了增量）"),
                         ("D4", "D4 role_alpha 阻尼扫描（方案未覆盖）")):
        if layer in todo:
            rep += [f"## {title}", "",
                    "| 档位 | 词数 | 000真词/15 | 碎片/18 | keep/37 | filt/25 | net | 新增真词 |",
                    "|---|---|---|---|---|---|---|---|"]
            for r in [x for x in rows if x["layer"] == layer]:
                rep.append(f"| {r['case']} | {r['n']} | {r['live_000']} | {r['live_frag']} | "
                           f"{r['keep']} | {r['filt']} | {r['net']} | {r['add_000_w'] or '—'} |")
            rep += [""]
    rep += ["## 全局排名 Top15（全部实跑档）", "",
            "| 档位 | 层 | 词数 | 000/15 | 碎片/18 | keep/37 | filt/25 | net |",
            "|---|---|---|---|---|---|---|---|"]
    for r in sorted([x for x in rows if x["layer"] != "ref"],
                    key=lambda r: (-r["net"], r["n"]))[:15]:
        rep.append(f"| {r['case']} | {r['layer']} | {r['n']} | {r['live_000']} | {r['live_frag']} | "
                   f"{r['keep']} | {r['filt']} | {r['net']} |")
    rep += ["", "## 参考档", ""]
    for lab in ("base(锚点)", "F3_ref(a2.0_r0.7)"):
        r = rows_by_case[lab]
        rep.append(f"- `{lab}`：n={r['n']} 000={r['live_000']}/15 碎片={r['live_frag']}/18 "
                   f"keep={r['keep']}/37 filt={r['filt']}/25")
    rep += [""]

    with open(os.path.join(OUT, "v2执行报告.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(ana, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告: {os.path.join(OUT, 'v2执行报告.md')}")
    print(f"汇总: {os.path.join(OUT, 'union_summary_v2.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
