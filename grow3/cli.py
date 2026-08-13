"""grow3.cli —— 3.0 统一管道入口。Step 2/6 落地。

用法（与历史分支 CLI 对齐）：
    python -m grow3.cli <输入.csv> [--min-ent 0.5] [--cohesion 1.5]
                              [--indep 0.05] [--spe-rescue 0.8]
                              [--rsr-rescue 8] [--rsr-mode mean]
                              [--title-col 2] [--intro-col -1]
                              [--ent-merge-ratio 0.25] [--no-cloud]
                              [--audit out.json]

默认参数须复现 main 5865。Step 1 仅放空壳；Step 2 接通 scan + ent，
Step 6 接通全部信号与 gate 组装，Step 7 接通 --audit。
"""
from __future__ import annotations

import argparse
import sys


def build_arg_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器（参数名与历史分支完全对齐）。Step 6 落地。"""
    ap = argparse.ArgumentParser(
        prog="grow3", description="生长词库 3.0 统一管道")
    ap.add_argument("input", help="输入 CSV（title,intro）")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--min-ent", type=float, default=0.5, help="复合熵阈值")
    ap.add_argument("--cohesion", type=float, default=0.0, help="凝固度阈值")
    ap.add_argument("--indep", type=float, default=0.0, help="词本身偏序阈值")
    ap.add_argument("--spe-rescue", type=float, default=0.0, help="SPE 救援阈值")
    ap.add_argument("--rsr-rescue", type=float, default=0.0, help="RSR 救援阈值")
    ap.add_argument("--rsr-mode", choices=["mean", "max"], default="mean")
    ap.add_argument("--ent-merge-ratio", type=float, default=0.25)
    ap.add_argument("--title-col", type=int, default=0)
    ap.add_argument("--intro-col", type=int, default=1)
    ap.add_argument("--no-cloud", action="store_true", default=True)
    ap.add_argument("--audit", default=None, help="审计日志输出路径")
    return ap


def main(argv=None) -> int:
    """入口。Step 2/6 落地。当前仅解析参数并打印面板摘要。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    print(f"[grow3] 收到参数: {args}", file=sys.stderr)
    print("[grow3] Step 1 空壳：管道逻辑待 Step 2/6 落地。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
