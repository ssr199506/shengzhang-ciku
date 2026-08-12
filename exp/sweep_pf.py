#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""位置固定度豁免(2.1.16) 全参数扫描：逐档记录相对基线的【新增词】与【减少词】。
基线 = --pos-fixed 0, --min-ent 0.5, --ent-merge-ratio 0.25 (纯 main 行为)
用法： python exp/sweep_pf.py
"""
import os, csv, subprocess, sys, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
OUT = os.path.join(HERE, "sweep_pf")
os.makedirs(OUT, exist_ok=True)

SHOULD_KEEP = ["吞噬星空","一人之下","长生修仙","万族","斗破苍穹","诛仙","史记",
               "无限恐怖","鬼灭","苟在","之主","之王","世界","长生","凡人","修仙",
               "都市","系统","巅峰","重生之","人在木叶","全职法师","风云","无敌",
               "直播","网游","神豪","荒古","重生","战神","天才","玄幻","末世",
               "奶爸","神医","纨绔","重活"]
SHOULD_FILTER = ["我能","剑修","剑客","真不是","真没","你管","我只","联盟之",
                 "星空之","火影开","无限之","诸天之","之巅","之神","之子","之魂",
                 "之开","罗之","世主","生仙","人在斗","影开始","局被","后一","的悠"]

WATCH = ["什么鬼","一人之下","我能","首富","人在斗罗","人在斗","联盟之","诸天之",
         "聊天","从零","苟在","王者","万族","斗破苍穹","庆余年","完美世界","重燃"]

def run(pf, me, mr, tag):
    d = os.path.join(OUT, tag)
    cmd = [sys.executable, os.path.join(ROOT, "grow.py"), CSV,
           "--title-col", "2", "--out", d, "--no-cloud",
           "--min-ent", str(me), "--ent-merge-ratio", str(mr), "--pos-fixed", str(pf)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return os.path.join(d, "title_wordfreq.csv")

def load(p):
    return {r["word"]: r for r in csv.DictReader(open(p, encoding="utf-8-sig"))}

def detail(row):
    if not row: return "—"
    return "cnt=%s ind=%s bind=%s 熵=%s" % (row['count'], row['independent'], row['bind'], row['compound_entropy'])

PF_AXIS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
ME0, MR0 = 0.5, 0.25

base_csv = run(0.0, ME0, MR0, "base")
base = load(base_csv)
base_w = set(base)

print("生成主扫描输出...", file=sys.stderr)
results = {}
for pf in PF_AXIS:
    tag = "pf%.2f" % pf
    csvp = run(pf, ME0, MR0, tag)
    results[pf] = load(csvp)

print("生成交互网格输出...", file=sys.stderr)
GRID_PF = [0.80, 0.85, 0.90]
GRID_ME = [0.3, 0.5, 0.7]
GRID_MR = [0.20, 0.25, 0.30]
grid = {}
for pf, me, mr in itertools.product(GRID_PF, GRID_ME, GRID_MR):
    tag = "g_pf%.2f_me%g_mr%.2f" % (pf, me, mr)
    csvp = run(pf, me, mr, tag)
    grid[(pf, me, mr)] = load(csvp)

lines = []
def L(s=""): lines.append(s)

L("# 位置固定度豁免（2.1.16）全参数扫描报告")
L()
L("基线(--pos-fixed 0, --min-ent %.1f, --ent-merge-ratio %.2f) 词数：**%d**" % (ME0, MR0, len(base_w)))
L("金标准：应留 %d 词 / 应滤 %d 词" % (len(SHOULD_KEEP), len(SHOULD_FILTER)))
L("评分 score = 0.5·keep率 + 0.5·filt率（越高越好）")
L()

L("## 一、pos-fixed 主扫描（min-ent=0.5, merge-ratio=0.25）")
L()
L("| pos-fixed | 词数 | vs基线± | 新增(救回) | 减少(新滤) | keep | filt | score | 坏救(应滤被救) |")
L("|---|---|---|---|---|---|---|---|---|")
for pf in PF_AXIS:
    d = results[pf]; w = set(d)
    added = w - base_w; removed = base_w - w
    kb = sum(x in w for x in SHOULD_KEEP); fb = sum(x not in w for x in SHOULD_FILTER)
    score = 0.5*kb/len(SHOULD_KEEP) + 0.5*fb/len(SHOULD_FILTER)
    bad = [x for x in added if x in SHOULD_FILTER]
    L("| %.2f | %d | %+d | %d | %d | %d/%d | %d/%d | %.3f | %d |" % (
        pf, len(w), len(w)-len(base_w), len(added), len(removed),
        kb, len(SHOULD_KEEP), fb, len(SHOULD_FILTER), score, len(bad)))
L()
L("说明：新增=基线滤除、本档保留；减少=基线保留、本档滤除（减少词不一定坏，可能是修掉基线误留的寄生词）。")
L()

L("## 二、重点关注词 · 各档归属（✅保留 / ❌滤除）")
L()
hdr = "| 词 | 基线 | " + " | ".join("%.2f" % pf for pf in PF_AXIS) + " |"
L(hdr)
L("|" + "---|"*(len(PF_AXIS)+2))
for w in WATCH:
    base_mark = "✅" if w in base_w else "❌"
    marks = []
    for pf in PF_AXIS:
        marks.append("✅" if w in results[pf] else "❌")
    L("| %s | %s | %s |" % (w, base_mark, " | ".join(marks)))
L()

L("## 三、逐档【新增词】与【减少词】明细")
L()
for pf in PF_AXIS:
    d = results[pf]; w = set(d)
    added = sorted(w - base_w, key=lambda x: -int(d[x]['count']))
    removed = sorted(base_w - w, key=lambda x: -int(base[x]['count']))
    L("### pos-fixed = %.2f   （词数 %d，新增 %d，减少 %d）" % (pf, len(w), len(added), len(removed)))
    L()
    if added:
        L("**新增 %d 词**（基线滤→本档保）：" % len(added))
        for x in added:
            L("- 新增 `%s`  %s" % (x, detail(d[x])))
    else:
        L("**新增 0 词**")
    L()
    if removed:
        L("**减少 %d 词**（基线保→本档滤）：" % len(removed))
        for x in removed:
            L("- 减少 `%s`  %s" % (x, detail(base[x])))
    else:
        L("**减少 0 词**")
    L()

L("## 四、交互网格：pos-fixed × min-ent × merge-ratio（标题行汇总）")
L()
L("| pos-fixed | min-ent | merge-ratio | 词数 | keep | filt | score | 新增 | 减少 |")
L("|---|---|---|---|---|---|---|---|---|")
for (pf, me, mr), d in grid.items():
    w = set(d)
    added = len(w - base_w); removed = len(base_w - w)
    kb = sum(x in w for x in SHOULD_KEEP); fb = sum(x not in w for x in SHOULD_FILTER)
    score = 0.5*kb/len(SHOULD_KEEP) + 0.5*fb/len(SHOULD_FILTER)
    L("| %.2f | %g | %.2f | %d | %d/%d | %d/%d | %.3f | %d | %d |" % (
        pf, me, mr, len(w), kb, len(SHOULD_KEEP), fb, len(SHOULD_FILTER), score, added, removed))
L()

L("## 五、交互网格中重点词归属（pf 固定看 me/mr 影响）")
L()
for pf in GRID_PF:
    L("### pos-fixed = %.2f" % pf)
    L()
    hdr = "| 词 | " + " | ".join("me%g/mr%.2f" % (me, mr) for me, mr in itertools.product(GRID_ME, GRID_MR)) + " |"
    L(hdr)
    L("|" + "---|"*(len(GRID_ME)*len(GRID_MR)+1))
    for w in WATCH:
        marks = []
        for me, mr in itertools.product(GRID_ME, GRID_MR):
            d = grid[(pf, me, mr)]
            marks.append("✅" if w in d else "❌")
        L("| %s | %s |" % (w, " | ".join(marks)))
    L()

md = "\n".join(lines)
print(md)

out_md = os.path.join(OUT, "report.md")
with open(out_md, "w", encoding="utf-8") as f:
    f.write(md)
print("\n[REPORT] 已写 %s" % out_md, file=sys.stderr)
