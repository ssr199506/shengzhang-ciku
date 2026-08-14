#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_rescue.py —— 救援阈值查表模拟器 + 关键处边界重扫 + 余量审计。

读 dump_signals.py 产出的 title_signals.json，对任意 (asym_rescue, role_rescue)
即时推得 kept = passed_AND ∪ {被滤集: asym>=a ∨ role>=r}，并相对 base 锚点计算指标。

关键处重扫（回应"方案漏掉 2.75、最优解贴边"）：
  1. asym 一维密集扫（role 固定 0.80）：定位 2.5→3.0 断崖与 围棋 掉落点
  2. role 一维密集扫（asym 固定 2.75）：确认平台 + 康熙(r=0.9000)抖动点
  3. 敏感区二维 net 面
  4. 余量审计：每个敏感词对推荐阈(2.75/0.80)的 binding margin
  5. 真实 CLI 验证：F3 / rec(2.75,0.80) / cliff(3.00,0.80) / jitter(2.75,0.90)
     逐词比对模拟器，证明查表机制成立

用法：python sim_rescue.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
SIGNAL_JSON = os.path.join(ROOT, "调参产物", "plan_v2", "_signals", "title_signals.json")
REPORT = os.path.join(ROOT, "调参产物", "plan_v2", "重跑关键处_边界余量审计.md")

from run_full_union import (BASE_CLI, FILT, FRAGS, KEEP, PAST_BASE,  # noqa: E402
                            ROOT as R2, TRUE_000, load_words)

TRUE_ALL = sorted(set(KEEP) | set(TRUE_000))
BAD_ALL = sorted(set(FILT) | set(FRAGS))
SENT = -1.0


def load_signals():
    with open(SIGNAL_JSON, encoding="utf-8") as f:
        d = json.load(f)
    passed = [w for w in d["words"] if w["pass_and"]]
    filtered = [w for w in d["words"] if not w["pass_and"]]
    return d, passed, filtered


def load_base():
    return set(load_words(PAST_BASE))


def kept_set(passed, filtered, a, r):
    """kept(a,r) = passed_AND ∪ {w∈filtered: asym>=a ∨ role>=r}。"""
    ks = set(w["word"] for w in passed)
    for w in filtered:
        if w["asym"] >= a or w["role"] >= r:
            ks.add(w["word"])
    return ks


def metrics(ks, base):
    s = set(ks)
    add = s - base
    rem = base - s
    a000 = add & set(TRUE_000)
    afrg = add & set(FRAGS)
    r000 = rem & set(TRUE_000)
    rfrg = rem & set(FRAGS)
    return {
        "n": len(s),
        "live_000": len(s & set(TRUE_000)),
        "live_frag": len(s & set(FRAGS)),
        "keep": len(s & set(KEEP)),
        "filt": len(s & set(FILT)),
        "net": len(a000) - len(r000) + len(rfrg) - len(afrg),
        "recovered_000": sorted(a000),
        "added_frag": sorted(afrg),
        "lost_000": sorted(r000),
        "removed_frag": sorted(rfrg),
    }


def real_cli_run(label, a, r, out_dir):
    extra = ["--role", "--role-max-depth", "-1", "--role-rescue", f"{r:.2f}",
             "--asym", "--asym-rescue", f"{a:.2f}"]
    d = os.path.join(out_dir, label)
    os.makedirs(d, exist_ok=True)
    env = {**os.environ, "CODEBUDDY_SESSION_ID": "", "CLAUDE_SESSION_ID": ""}
    r = subprocess.run(BASE_CLI + extra + ["--out", d], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, env=env)
    if r.returncode != 0:
        print(f"  [FAIL] {label}: {r.stderr.strip()[-300:]}", file=sys.stderr)
        return None
    return set(load_words(os.path.join(d, "title_wordfreq.csv")))


def main():
    d, passed, filtered = load_signals()
    base = load_base()
    rep = []

    # ---- 0. 同构校验 ----
    passed_set = set(w["word"] for w in passed)
    rep.append("# 重跑关键处：边界重扫 + 余量审计")
    rep.append("")
    rep.append(f"信号转储：候选 {d['n_total']} 词 | 通过AND链 {d['n_pass']} | 被滤 {d['n_total']-d['n_pass']}")
    rep.append(f"base 锚点（PAST_BASE）：{len(base)} 词")
    rep.append(f"passed_AND 与 base 差集：{len(passed_set ^ base)} 词"
               f"（0=模拟器锚点与真实 CLI 完全一致）")
    rep.append("")

    # ---- 1. asym 一维密集扫（role=0.80）----
    rep.append("## 1. asym 断崖定位（role 固定 0.80）")
    rep.append("")
    rep.append("| asym_rescue | n | 000/15 | 碎片/18 | keep/37 | filt/25 | net | 救回真词 |")
    rep.append("|---|---|---|---|---|---|---|---|")
    a_grid = [2.00, 2.25, 2.40, 2.50, 2.60, 2.70, 2.75, 2.78, 2.80, 2.82, 2.85, 2.90, 3.00, 3.25, 3.50]
    r_fixed = 0.80
    for a in a_grid:
        m = metrics(kept_set(passed, filtered, a, r_fixed), base)
        rep.append(f"| {a:.2f} | {m['n']} | {m['live_000']} | {m['live_frag']} | "
                   f"{m['keep']} | {m['filt']} | {m['net']} | {' '.join(m['recovered_000']) or '—'} |")
    rep.append("")
    rep.append("> 关注：围棋(asym≈2.839) 在哪格首次掉落；2.75 相对 2.50 多救回哪些真词。")
    rep.append("")

    # ---- 2. role 一维密集扫（asym=2.75）----
    rep.append("## 2. role 平台与抖动点（asym 固定 2.75）")
    rep.append("")
    rep.append("| role_rescue | n | 000/15 | 碎片/18 | keep/37 | filt/25 | net | 救回真词 |")
    rep.append("|---|---|---|---|---|---|---|---|")
    a_fixed = 2.75
    r_grid = [0.60, 0.70, 0.75, 0.78, 0.80, 0.82, 0.85, 0.90, 0.95]
    for r in r_grid:
        m = metrics(kept_set(passed, filtered, a_fixed, r), base)
        rep.append(f"| {r:.2f} | {m['n']} | {m['live_000']} | {m['live_frag']} | "
                   f"{m['keep']} | {m['filt']} | {m['net']} | {' '.join(m['recovered_000']) or '—'} |")
    rep.append("")
    rep.append("> 关注：康熙(role=0.9000) 在哪格首次进/出；r=0.90 浮点抖动风险。")
    rep.append("")

    # ---- 3. 敏感区二维 net 面 ----
    rep.append("## 3. 敏感区二维 net 面")
    rep.append("")
    a2 = [2.50, 2.60, 2.70, 2.75, 2.80, 2.85, 2.90, 3.00]
    r2 = [0.75, 0.80, 0.85, 0.90, 0.95]
    rep.append("| asym\\role | " + " | ".join(f"{r:.2f}" for r in r2) + " |")
    rep.append("|---" * (len(r2) + 1) + "|")
    for a in a2:
        line = [f"| **{a:.2f}**"]
        for r in r2:
            m = metrics(kept_set(passed, filtered, a, r), base)
            line.append(f"| {m['net']}({m['live_000']}/15,{m['live_frag']}/18)")
        rep.append("".join(line) + " |")
    rep.append("")
    rep.append("> 单元格式 net(000/15, 碎片/18)。识别 Pareto 前沿与断崖边缘。")
    rep.append("")

    # ---- 4. 余量审计 ----
    rep.append("## 4. 余量审计：敏感词 × 推荐阈(2.75, 0.80)")
    rep.append("")
    rep.append("推荐配置 a=2.75 / r=0.80。下表给出每个敏感词的信号值与到阈值的余量"
               "（binding = 实际生效的救援信号）。")
    rep.append("")
    rep.append("| 词 | 群体 | 状态 | role | asym | binding | margin=阈−信号 |")
    rep.append("|---|---|---|---|---|---|---|")
    a_rec, r_rec = 2.75, 0.80
    pset = set(w["word"] for w in passed)
    fmap = {w["word"]: w for w in filtered}
    for w in sorted(TRUE_ALL + BAD_ALL):
        if w not in pset and w not in fmap:
            rep.append(f"| {w} | ? | 不在池 | — | — | — | — |")
            continue
        if w in pset:
            rep.append(f"| {w} | {'真词' if w in TRUE_ALL else '应滤'} | base已留 | "
                       f"{[x['role'] for x in passed if x['word']==w][0]:.3f} | "
                       f"{[x['asym'] for x in passed if x['word']==w][0]:.3f} | — | — |")
            continue
        wd = fmap[w]
        role, asym = wd["role"], wd["asym"]
        if asym >= a_rec or role >= r_rec:
            if asym >= a_rec and role >= r_rec:
                binding = "asym&role"
                margin = min(asym - a_rec, role - r_rec)
            elif asym >= a_rec:
                binding = "asym"
                margin = asym - a_rec
            else:
                binding = "role"
                margin = role - r_rec
            status = "救援留"
        else:
            binding = "—"
            margin = min(a_rec - asym, r_rec - role)
            status = "被滤删"
        grp = "真词" if w in TRUE_ALL else "应滤/碎片"
        rs = f"{role:.3f}" if role > SENT else "哨兵"
        as_ = f"{asym:.3f}" if asym > SENT else "哨兵"
        rep.append(f"| {w} | {grp} | {status} | {rs} | {as_} | {binding} | {margin:+.3f} |")
    rep.append("")

    # ---- 5. 真实 CLI 验证 ----
    rep.append("## 5. 查表机制验证（模拟器 vs 真实 CLI，逐词比对）")
    rep.append("")
    verify = [("F3(2.00,0.70)", 2.00, 0.70),
              ("rec(2.75,0.80)", 2.75, 0.80),
              ("cliff(3.00,0.80)", 3.00, 0.80),
              ("jitter(2.75,0.90)", 2.75, 0.90)]
    vdir = os.path.join(ROOT, "调参产物", "plan_v2", "_verify")
    rows = ["| 配置 | 模拟n | 真实n | 对称差词数 | 一致? | 差集样例 |", "|---|---|---|---|---|---|"]
    all_ok = True
    for label, a, r in verify:
        sim = kept_set(passed, filtered, a, r)
        real = real_cli_run(label, a, r, vdir)
        if real is None:
            rows.append(f"| {label} | {len(sim)} | — | — | CLI失败 | — |")
            all_ok = False
            continue
        diff = sim ^ real
        ok = (not diff)
        all_ok = all_ok and ok
        sample = " ".join(sorted(diff)[:8]) if diff else "—"
        rows.append(f"| {label} | {len(sim)} | {len(real)} | {len(diff)} | "
                    f"{'✅' if ok else '❌'} | {sample} |")
        rep_later = (f"  - {label}: 模拟 {len(sim)} 词 / 真实 {len(real)} 词 / 对称差 {len(diff)}")
        print(rep_later, file=sys.stderr)
    rep += rows
    rep.append("")
    rep.append(f"> **结论**：{'全部一致 → 救援阈值调参可安全降级为查表模拟，零重跑。' if all_ok else '存在不一致，需排查（见差集）。'}")
    rep.append("")
    rep.append("## 6. 收口")
    rec = metrics(kept_set(passed, filtered, 2.75, 0.80), base)
    rep.append("")
    rep.append(f"- 推荐配置 (a2.75, r0.80, depth-1)：n={rec['n']}, 000={rec['live_000']}/15, "
               f"碎片={rec['live_frag']}/18, keep={rec['keep']}/37, filt={rec['filt']}/25, net={rec['net']}")
    rep.append(f"- 救回真词：{' '.join(rec['recovered_000'])}")
    rep.append(f"- 新增碎片：{' '.join(rec['added_frag'])} | 漏删应滤：{' '.join(rec['filt_words']) if 'filt_words' in rec else '—'}")
    rep.append("")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print(f"\n报告已写出: {REPORT}", file=sys.stderr)


if __name__ == "__main__":
    main()
