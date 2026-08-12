#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验运行器：对每个参数配置，独立生成一份产物到 exp/<name>/，互不覆盖。
所有运行均带 --no-cloud 以加速（只产 CSV，不渲染词云）。

用法：
    python exp/run.py            # 跑全部配置
    python exp/run.py me_0.5     # 只跑某个配置（清空其目录后重跑）
"""
import os
import sys
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
EXP = HERE
TITLE_COL = "2"

# 配置矩阵：(名称, [额外参数])
# 标注约定：
#   baseline   —— 标点感知 + 不过滤（新基线，调参参照）
#   punct_off  —— 关闭标点感知 + 不过滤（等价于 2.1.4 基线）
#   me_*       —— 仅调 --min-ent（标点感知）
#   bind_*     —— 仅调 --bind（集中度）
CONFIGS = [
    ("baseline",  ["--min-ent", "0",   "--bind", "1.0"]),
    ("punct_off", ["--no-punct-ent", "--min-ent", "0", "--bind", "1.0"]),
    ("me_0.3",    ["--min-ent", "0.3"]),
    ("me_0.5",    ["--min-ent", "0.5"]),
    ("me_0.8",    ["--min-ent", "0.8"]),
    ("me_1.0",    ["--min-ent", "1.0"]),
    ("me_1.5",    ["--min-ent", "1.5"]),
    ("me_2.0",    ["--min-ent", "2.0"]),
    ("bind_0.7",  ["--bind", "0.7"]),
    ("bind_0.5",  ["--bind", "0.5"]),
]


def run_one(name, extra):
    out = os.path.join(EXP, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    cmd = [sys.executable, os.path.join(ROOT, "grow.py"), CSV,
           "--title-col", TITLE_COL, "--out", out, "--no-cloud"] + extra
    t0 = time.time()
    print(f">>> [{name}] {' '.join(extra)}", flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"    done in {time.time()-t0:.1f}s -> {out}", flush=True)


def main():
    only = sys.argv[1:] if len(sys.argv) > 1 else []
    cfgs = [(n, e) for n, e in CONFIGS if (not only or n in only)]
    if not cfgs:
        print("无匹配配置。可用：", ", ".join(n for n, _ in CONFIGS))
        return
    for name, extra in cfgs:
        run_one(name, extra)
    print("\n全部完成。对比：python exp/cmp.py")


if __name__ == "__main__":
    main()
