#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板最强组合搜索（快查版）：在 grow3 面板上组合 ent/coh/indep/spe/rsr，
评估候选组合的真词召回与碎片控制。

⚠️ 完整联合网格见 exp/tune_combo.py（63 组合 + 敏感性 + 双口径评分）。
本脚本只保留代表性候选行，快速复现结论。

结论（2026-08-13 联合调参）：
- 按金标准词集口径最优 = --min-ent 0.5 --cohesion 1.5 --indep 0.05（不开 SPE）→ 5149 词。
- SPE 救援会捞回金标准要滤的碎片（我只/联盟之/罗之），filt 率下降；但其 000 真词
  spe 与碎片完全重叠（围棋=联盟之=0.971），任何阈值都切不开——按召回选 spe0.8，
  低副作用折中选 spe1.0。
"""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus.csv")
COMMON = ["--title-col", "2", "--intro-col", "-1",
          "--ent-merge-ratio", "0.25", "--no-cloud"]

# ---- 评估集 ----
TRUE_000 = ['庆余年', '康熙', '首富', '刺客', '围棋', '迪迦', '谍战', '舰娘',
            '铁血', '梦幻', '工程', '首辅', '漫画', '港片', '捡属性']
TRUE_010 = ['九星', '人在斗罗', '什么鬼', '仙医', '仙朝', '君临', '妙手',
            '完美世界', '我能', '神诡世界', '重燃', '魔法师', '黑客']
FRAGS = ['我只', '聊天', '我真', '我真不', '联盟之', '诸天之', '罗之', '我的',
         '这个', '是我', '游之', '界的', '真不', '是大', '的我', '之我', '成了', '一个']

CASES = [
    ("ent+coh+indep",           ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05"]),
    ("ent+spe0.8",              ["--min-ent", "0.5", "--spe-rescue", "0.8"]),
    ("ent+coh+indep+spe0.5",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.5"]),
    ("ent+coh+indep+spe0.6",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.6"]),
    ("ent+coh+indep+spe0.7",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.7"]),
    ("ent+coh+indep+spe0.8",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.8"]),
    ("ent+coh+indep+spe0.9",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.9"]),
    ("ent+coh+indep+spe1.0",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "1.0"]),
    ("ent+coh+indep+spe0.8+rsr8", ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05", "--spe-rescue", "0.8", "--rsr-rescue", "8"]),
    ("ent+spe0.8+rsr8",         ["--min-ent", "0.5", "--spe-rescue", "0.8", "--rsr-rescue", "8"]),
]


def load(path):
    return {r[0] for r in csv.reader(open(path, encoding="utf-8-sig", newline="")) if r}


def run(args):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([sys.executable, "-m", "grow3.cli", CORPUS] + COMMON + args + ["--out", td],
                       check=True, stderr=subprocess.DEVNULL)
        return load(os.path.join(td, "title_wordfreq.csv"))


def main():
    print(f"{'组合':<28}{'词数':>6}{'000真词':>8}{'010真词':>8}{'碎片剩':>6}")
    for name, args in CASES:
        w = run(args)
        r000 = len([x for x in TRUE_000 if x in w])
        r010 = len([x for x in TRUE_010 if x in w])
        fr = len([x for x in FRAGS if x in w])
        print(f"{name:<28}{len(w):>6}{r000:>6}/{len(TRUE_000):<2}"
              f"{r010:>6}/{len(TRUE_010):<2}{fr:>6}")
    print("\n按金标准口径最优: --min-ent 0.5 --cohesion 1.5 --indep 0.05（不开 SPE）→ 5149 词")
    print("SPE 救援（如需召回熵门误杀真词）: spe0.8 救10/15 混碎片，spe1.0 救4/15 低副作用")
    print("完整 63 组合网格 + 敏感性见 exp/tune_combo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
