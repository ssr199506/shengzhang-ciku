#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_full_union.py —— role/asym 全量细化网格 + 过去版本交并分析。

与 run_matrix.py（验收集打分）不同：本脚本**真实跑全量**——每个参数档用 grow3.cli
产出一版完整 title_wordfreq.csv，再与「过去版本 base」逐档求交并，统计每档相对 base
新增/删除的词里，有多少 000 层真词、多少句法碎片，系统衡量 role/asym 两个新模块。

用法：
    python run_full_union.py               # 跑全部档（默认）
    python run_full_union.py --layer A     # 只跑某一层 A~F
    python run_full_union.py --out DIR     # 输出目录（默认 调参产物/fullrun_role）
    python run_full_union.py --skip-run    # 只做交并分析，不重跑已存在的档

档位网格（步长已细化）：
    层A role 过滤门  min_role   0.25~0.85 步长0.05   （13 档）
    层B role 救援门  role_rescue 0.45~0.95 步长0.05 （11 档）
    层C asym 救援门  asym_rescue 0.5~3.0 步长0.25    （11 档）
    层D role 深度    max_depth  1/2/3/4/-1（固定 min_role=0.5） （5 档）
    层E asym救×role净化  asym=2.0 固定，min_role 0~0.6 扫描 （8 档）
    层F 完整管道     ent+coh 基础上 5 种组合（5 档）
    own_base 复现校验（应==5149 与过去 base 一致）

评估集与 tune_engine 对齐（KEEP/FILT/T000/FRAGS），但评估对象是**全量词表**
而非验收集打分。

产物：
    fullrun_role/<label>/title_wordfreq.csv   每档完整词表
    fullrun_role/union_summary.csv           逐档交并汇总
    fullrun_role/交并报告.md                  自动生成的分析报告
"""
import argparse
import csv
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 仓库根
TOOL = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "调参产物", "fullrun_role")
PAST_BASE = os.path.join(ROOT, "调参产物", "fullrun", "base", "title_wordfreq.csv")

CORPUS = os.path.join(ROOT, "corpus.csv")

# ---- 与 tune_engine 对齐的评估集 ----
KEEP = ["吞噬星空", "一人之下", "长生修仙", "万族", "斗破苍穹", "诛仙", "史记",
        "无限恐怖", "鬼灭", "苟在", "之主", "之王", "世界", "长生", "凡人", "修仙",
        "都市", "系统", "巅峰", "重生之", "人在木叶", "全职法师", "风云", "无敌",
        "直播", "网游", "神豪", "荒古", "重生", "战神", "天才", "玄幻", "末世",
        "奶爸", "神医", "纨绔", "重活"]
FILT = ["我能", "剑修", "剑客", "真不是", "真没", "你管", "我只", "联盟之",
        "星空之", "火影开", "无限之", "诸天之", "之巅", "之神", "之子", "之魂",
        "之开", "罗之", "世主", "生仙", "人在斗", "影开始", "局被", "后一", "的悠"]
TRUE_000 = ['庆余年', '康熙', '首富', '刺客', '围棋', '迪迦', '谍战', '舰娘',
            '铁血', '梦幻', '工程', '首辅', '漫画', '港片', '捡属性']
FRAGS = ['我只', '聊天', '我真', '我真不', '联盟之', '诸天之', '罗之', '我的', '这个',
         '是我', '游之', '界的', '真不', '是大', '的我', '之我', '成了', '一个']

# ---- 基准 CLI 前缀（复现过去版本 fullrun/base 的默认参数）----
BASE_CLI = [sys.executable, "-m", "grow3.cli", CORPUS,
            "--title-col", "2", "--intro-col", "-1",
            "--ent-merge-ratio", "0.25", "--min-ent", "0.5",
            "--cohesion", "1.5", "--indep", "0.05",
            "--no-cloud"]


# ---------------------------------------------------------------- 档位网格
def L_A():
    """role 过滤门 min_role 细化扫描（0.25~0.85 步长 0.05）。"""
    return [(f"role滤{r:.2f}", ["--role", "--role-max-depth", "-1", "--min-role", f"{r:.2f}"])
            for r in [i * 0.05 for i in range(5, 18)]]


def L_B():
    """role 救援门 role_rescue 细化扫描（0.45~0.95 步长 0.05）。"""
    return [(f"role救{r:.2f}", ["--role", "--role-max-depth", "-1", "--role-rescue", f"{r:.2f}"])
            for r in [i * 0.05 for i in range(9, 20)]]


def L_C():
    """asym 救援门 asym_rescue 细化扫描（0.5~3.0 步长 0.25）。"""
    return [(f"asym救{a:.2f}", ["--asym", "--asym-rescue", f"{a:.2f}"])
            for a in [i * 0.25 for i in range(2, 13)]]


def L_D():
    """role 迭代深度扫描（U2 / 迭代 N 帧 / 不动点），固定 min_role=0.5 过滤。"""
    depth_spec = [(1, "U2"), (2, "d2"), (3, "d3"), (4, "d4"), (-1, "fix")]
    return [(f"role深{tag}(min_role0.5)",
             ["--role", "--role-max-depth", str(d), "--min-role", "0.5"])
            for d, tag in depth_spec]


def L_E():
    """asym 救援(2.0) × role 净化阈值扫描（min_role 0~0.6）。"""
    return [(f"asym2.0净role{r:.2f}",
             ["--asym", "--asym-rescue", "2.0", "--role", "--role-max-depth", "-1",
              "--min-role", f"{r:.2f}"])
            for r in [0.0, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6]]


def L_F():
    """完整管道（ent+coh 基础上 5 种组合）。"""
    return [
        ("F1-ent+coh+asym2.0+role滤0.5",
         ["--role", "--role-max-depth", "-1", "--min-role", "0.5",
          "--asym", "--asym-rescue", "2.0"]),
        ("F2-ent+coh+asym2.0+role滤0.6",
         ["--role", "--role-max-depth", "-1", "--min-role", "0.6",
          "--asym", "--asym-rescue", "2.0"]),
        ("F3-ent+coh+role救0.7+asym2.0",
         ["--role", "--role-max-depth", "-1", "--role-rescue", "0.7",
          "--asym", "--asym-rescue", "2.0"]),
        ("F4-ent+coh+role救0.8+asym2.0",
         ["--role", "--role-max-depth", "-1", "--role-rescue", "0.8",
          "--asym", "--asym-rescue", "2.0"]),
        ("F5-ent+coh+role救0.7",
         ["--role", "--role-max-depth", "-1", "--role-rescue", "0.7"]),
    ]


def L_G():
    """asym 过滤门 min_asym 扫描（0.0~2.5 步长 0.25）。"""
    return [(f"asym滤{a:.2f}", ["--asym", "--min-asym", f"{a:.2f}"])
            for a in [i * 0.25 for i in range(1, 11)]]


def L_H():
    """补测：SPE 正交 / asym滤+asym救 组合 / role救+asym滤 混合。"""
    return [
        ("H1-ent+coh+spe0.8+role救0.7+asym2.0",
         ["--spe-rescue", "0.8", "--role", "--role-max-depth", "-1",
          "--role-rescue", "0.7", "--asym", "--asym-rescue", "2.0"]),
        ("H2-ent+coh+asym滤1.0+asym救2.0",
         ["--asym", "--min-asym", "1.0", "--asym-rescue", "2.0"]),
        ("H3-ent+coh+asym滤1.5+asym救2.0",
         ["--asym", "--min-asym", "1.5", "--asym-rescue", "2.0"]),
        ("H4-ent+coh+role救0.7+asym滤1.0",
         ["--role", "--role-max-depth", "-1", "--role-rescue", "0.7",
          "--asym", "--min-asym", "1.0"]),
    ]


LAYERS = {"A": L_A, "B": L_B, "C": L_C, "D": L_D, "E": L_E, "F": L_F,
          "G": L_G, "H": L_H}


# ---------------------------------------------------------------- 执行
def run_one(label, extra, out_dir, skip_run):
    d = os.path.join(out_dir, label)
    wf = os.path.join(d, "title_wordfreq.csv")
    if skip_run and os.path.exists(wf):
        return True
    os.makedirs(d, exist_ok=True)
    cmd = BASE_CLI + extra + ["--out", d]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT,
                       env={**os.environ, "CODEBUDDY_SESSION_ID": "",
                            "CLAUDE_SESSION_ID": ""})
    if r.returncode != 0:
        print(f"  [FAIL] {label}: {r.stderr.strip()[-200:]}", file=sys.stderr)
        return False
    n = (sum(1 for _ in open(wf, encoding="utf-8-sig")) - 1) if os.path.exists(wf) else -1
    print(f"  {label:<30} {n} 词")
    return True


def load_words(path):
    words = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if i == 0 or not r:
                continue
            words[r[0]] = int(r[1])
    return words


def layer_label(lname):
    return {"A": "role过滤门min_role", "B": "role救援门role_rescue",
            "C": "asym救援门asym_rescue", "D": "role迭代深度",
            "E": "asym救×role净化", "F": "完整管道",
            "G": "asym过滤门min_asym", "H": "补测组合"}[lname]


def main():
    ap = argparse.ArgumentParser(description="role/asym 全量细化网格 + 过去版本交并")
    ap.add_argument("--layer", default=None, choices=list(LAYERS.keys()),
                    help="只跑某一层；缺省跑全部")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录")
    ap.add_argument("--skip-run", action="store_true", help="不重跑已存在的档，只做交并")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    layers = [args.layer] if args.layer else list(LAYERS.keys())

    # 过去版本 base（交并锚点）
    past = load_words(PAST_BASE)
    print(f"过去版本 base: {len(past)} 词 ({PAST_BASE})")

    # 1) own_base 复现校验（==5149，且与 past 交并一致）
    print("\n===== 复现校验 own_base =====")
    run_one("own_base", [], args.out, args.skip_run)
    own = load_words(os.path.join(args.out, "own_base", "title_wordfreq.csv"))
    print(f"own_base: {len(own)} 词 | 与过去 base 交集 {len(set(own) & set(past))} "
          f"| 差异 {len(set(own) ^ set(past))} 词")

    # 2) 跑各层档位
    for lname in layers:
        print(f"\n===== 层 {lname}（{layer_label(lname)}）=====")
        for label, extra in LAYERS[lname]():
            run_one(label, extra, args.out, args.skip_run)

    # 3) 交并分析：扫描 out 下所有已生成的词表档（支持多次分片跑后汇总）
    all_wf = {}
    for d in sorted(os.listdir(args.out)):
        wf = os.path.join(args.out, d, "title_wordfreq.csv")
        if os.path.isfile(wf):
            all_wf[d] = load_words(wf)

    # 锚 = 过去版本 base
    base_set = set(past)
    s000, sfrag, sfilt, skeep = set(TRUE_000), set(FRAGS), set(FILT), set(KEEP)
    rows = []
    for label, wset in all_wf.items():
        s = set(wset)
        add = s - base_set
        rem = base_set - s
        add_000 = sorted(add & s000)
        add_frag = sorted(add & sfrag)
        rem_000 = sorted(rem & s000)
        rem_frag = sorted(rem & sfrag)
        net = (len(add_000) - len(rem_000)          # 真词净增
               + len(rem_frag) - len(add_frag))     # 碎片净减
        rows.append({
            "case": label,
            "n_kept": len(s),
            "add": len(add), "rem": len(rem),
            "add_000": len(add_000), "add_frag": len(add_frag),
            "rem_000": len(rem_000), "rem_frag": len(rem_frag),
            "keep_hit": len(s & skeep), "filt_hit": len(s & sfilt),
            "net": net,
            "add_000_words": "+".join(add_000),
            "add_frag_words": "+".join(add_frag),
            "rem_000_words": "+".join(rem_000),
        })
    rows.sort(key=lambda r: (-r["net"], r["n_kept"]))

    with open(os.path.join(args.out, "union_summary.csv"), "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in rows[0].keys()])
        w.writeheader()
        w.writerows(rows)

    # 4) 报告
    rep = ["# role/asym 全量细化网格 + 过去版本交并报告", "",
           f"锚点: 过去版本 base（{len(past)} 词）| 复现 own_base（{len(own)} 词，"
           f"差异 {len(set(own) ^ set(past))}）",
           f"档位: 层 {' '.join(layers)} | 每档真实跑全量 cli | 共 {len(rows)} 档", "",
           "## 1. 交并汇总（按 net 排序）", "",
           "net = 000真词净增 + 碎片净减（越大越好）；add=相对base新增 / rem=删除", "",
           "| 档位 | 词数 | 增 | 删 | +000真 | +碎片 | -000真 | -碎片 | keep | filt | net |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rep.append(f"| {r['case']} | {r['n_kept']} | {r['add']} | {r['rem']} | "
                   f"{r['add_000']} | {r['add_frag']} | {r['rem_000']} | {r['rem_frag']} | "
                   f"{r['keep_hit']} | {r['filt_hit']} | {r['net']} |")
    rep += ["", "## 2. 各层单旋钮曲线", ""]
    # 每层档位名前缀（生成顺序与层定义一致）
    lname_prefix = {
        "A": "role滤", "B": "role救", "C": "asym救", "D": "role深",
        "E": "asym2.0净", "F": "F", "G": "asym滤", "H": "H",
    }
    for lname in layers:
        pfx = lname_prefix[lname]
        lrows = [r for r in rows if r["case"].startswith(pfx)]
        rep += [f"### {lname} {layer_label(lname)}", "",
                "| 档位 | 词数 | 000真词存活(15) | 碎片存活(18) | keep(37) | net |",
                "|---|---|---|---|---|---|"]
        for r in lrows:
            live_000 = r["add_000"] - r["rem_000"]     # base 000=0
            live_frag = 4 + r["add_frag"] - r["rem_frag"]  # base 残留 4 碎片
            rep.append(f"| {r['case']} | {r['n_kept']} | {live_000} | {live_frag} | "
                       f"{r['keep_hit']} | {r['net']} |")
        rep += [""]
    rep += ["## 3. 最佳档（net 前 5）", ""]
    for r in rows[:5]:
        rep.append(f"- **{r['case']}** net={r['net']} 词数={r['n_kept']} "
                   f"新增真词={r['add_000_words'] or '—'} 新增碎片={r['add_frag_words'] or '—'} "
                   f"删除真词={r['rem_000_words'] or '—'}")
    rep += ["", "## 4. 共识交集（全部档 + 过去 base 都保留）", ""]
    inter = base_set.intersection(*(set(load_words(os.path.join(args.out, k, "title_wordfreq.csv")))
                                    for k in all_wf))
    rep += [f"- {len(inter)} 词", "",
            "## 5. 观察与结论", ""]
    best = rows[0]
    rep.append(f"- 最佳档 `{best['case']}`：net={best['net']}，把 base 的 000 层真词从 "
               f"{sum(1 for t in TRUE_000 if t in base_set)}/15 提升到 "
               f"{sum(1 for t in TRUE_000 if t in set(load_words(os.path.join(args.out, best['case'], 'title_wordfreq.csv'))))}/15。")
    rep.append("- （详细结论待人工根据上方表格补充）")

    rep_path = os.path.join(args.out, "交并报告.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print(f"\n汇总: {os.path.join(args.out, 'union_summary.csv')}")
    print(f"报告: {rep_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
