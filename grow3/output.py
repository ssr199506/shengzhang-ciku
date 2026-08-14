"""grow3.output —— 词表 CSV 写出（与 main write_word_csv 字节级一致）。

格式严格对齐 main grow.py：
- 编码 utf-8-sig（含 BOM），csv.writer（CRLF 行尾）；
- 表头：word,count,independent,bind,len,compound_entropy；
- 排序：(-count, word)；
- bind / ent 四舍五入保留 4 位（round，与 main 一致）。
"""
from __future__ import annotations

import csv
import os
from typing import List

from .ir import Word


def write_word_csv(word_list: List[Word], path: str,
                   extra_cols: List[str] | None = None) -> None:
    """写出词频表。word_list 为已施加闸门后的最终词表。

    extra_cols：非空时在表头与每行末尾追加这些 Word 字段列（实验信号调试用）。
    缺省为 None → 输出与 main 字节级一致，不破坏既有验收。
    """
    extra = extra_cols or []
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['word', 'count', 'independent', 'bind', 'len',
                     'compound_entropy'] + extra)
        for w in sorted(word_list, key=lambda x: (-x.count, x.word)):
            row = [
                w.word,
                w.count,
                w.independent,
                round(w.binding, 4),
                len(w.word),
                round(w.ent, 4),
            ]
            for col in extra:
                row.append(round(getattr(w, col, -1.0), 4))
            wr.writerow(row)
