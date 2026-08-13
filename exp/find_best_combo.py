#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板最强组合搜索：在 grow3 模块化管道上组合 ent/coh/indep/spe/rsr，
用「错题集 000 层真词召回 + 碎片清除」口径评估，找平衡点。

评估集（来自 eval_versions/mistake_book.csv 的 000 层/碎片标注，内嵌硬编码以便独立跑）：
- true000: 000 层 15 个明确真词（庆余年/康熙/首富…，错题集 coh>=6 疑似真词里剔除标签污染噪声）
- frags:   已知强搭配/词缀碎片（我只/聊天/联盟之/罗之…）

用法： python exp/find_best_combo.py   （需本地 corpus.csv）

结论（2026-08-13 实测）：最强组合 = --min-ent 0.5 --cohesion 1.5 --indep 0.05
--spe-rescue 0.8（ent-merge-ratio 0.25）→ 5232 词，000 真词 10/15、碎片 14。
加 --rsr-rescue 8 不划算（丢 1 真词换 2 碎片）；spe 阈值 0.6~0.8 为平台期。
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
    print("\n最强组合: --min-ent 0.5 --cohesion 1.5 --indep 0.05 --spe-rescue 0.8 → 5232 词")
    print("（rsr8 收紧丢 1 真词换 2 碎片不划算；spe 0.6~0.8 平台期，0.8 保守取定）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
