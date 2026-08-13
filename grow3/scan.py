"""grow3.scan —— 语料构建 + 一次扫描（Step 2 落地）。

Step 2 目标：把 main 的 ``scan_and_grow`` 从"扫描 + 复合熵内联"拆成
``scan_once``（只产出 ScanContext IR）+ 各 ``signals/*.py``（只读计算）。

本文件 Step 1 仅放空壳，Step 2 填入真实逻辑。
"""
from __future__ import annotations

from typing import List, Tuple

from .ir import ScanContext, Word


def build_corpus(docs: List[Tuple[str, str]]):
    """语料构建：标题/简介 → 清洗纯 CJK → 拼接为带哨兵的语料字符串 S 与位置权重 wgt。

    Step 2 落地。当前为空壳。
    """
    ...


def scan_once(S: str, wgt: dict, ent_merge_ratio: float = 0.25,
              ent_punct_exempt: bool = True) -> ScanContext:
    """一次扫描：单字 BFS 生长最大重复候选词，产出统一 IR（ScanContext）。

    注意：扫描阶段**只生长 + 收集跨信号共享的中间量**，绝不施加任何信号闸门。
    信号闸门统一在 gates.py 里按 config 组装。cand_lst 在扫描阶段即收集好，
    便于后续 indep 覆盖判定（main 原版没有，这里提前加）。

    Step 2 落地。当前为空壳。
    """
    ...
