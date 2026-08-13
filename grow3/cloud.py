"""grow3.cloud —— 词云渲染层（补全：grow3 与历史 main 一样可产词云 / 互动词云）。

- ``render_cloud``：画词云 PNG（wordcloud 库，固定种子 42 保证布局可复现），返回 layout_
- ``emit_interactive``：包装根目录 ``interactive_cloud.emit_interactive``
  （外壳 HTML + 外部 data.js，或 ``standalone=True`` 单文件内联）

等价来源：exp/legacy/grow_v211_main.py 的 render_cloud + 根目录 interactive_cloud.py。
渲染失败不致命：词云只是显示层，词表 CSV 永远是核心产物。

⚠️ 安全约束：词云 / 互动词云产物含从语料 title 提取的**完整书名**（付费数据衍生内容），
一律只输出到 out 目录；.gitignore 已用 ``*wordcloud*`` 模式锁死，严禁提交入库。
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

from .ir import Word

# 词云画布尺寸（与 interactive_cloud.CLOUD_W/CLOUD_H 一致；import 失败时兜底）
CLOUD_W, CLOUD_H = 1600, 1000


def _pick_font() -> Optional[str]:
    candidates = [
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\msyh.ttf',
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def render_cloud(path: str, candidates: List[Word], top_n: int = 200,
                 maxlen: int = 0, font_path: Optional[str] = None):
    """画词云 PNG，返回布局 layout_（每个词的坐标/字号/颜色/朝向）。

    layout_ 为 5 元组：((word, 归一化频率), font_size, (y, x), orientation, color)。
    orientation: None=横排, Image.ROTATE_90=竖排。删词/空语料时返回 None。
    """
    from wordcloud import WordCloud
    if font_path is None:
        font_path = _pick_font()
    freqs = {}
    for wd in candidates:
        if maxlen and len(wd.word) > maxlen:
            continue
        freqs[wd.word] = wd.count
    if not freqs:
        return None
    top = dict(sorted(freqs.items(), key=lambda x: -x[1])[:top_n])
    wc = WordCloud(font_path=font_path, width=CLOUD_W, height=CLOUD_H,
                   background_color='white', max_words=top_n,
                   collocations=False, repeat=False, prefer_horizontal=0.9,
                   random_state=42)  # 固定种子，使词云布局可复现
    wc.generate_from_frequencies(top)
    wc.to_file(path)
    return wc.layout_


def _to_legacy(candidates: List[Word]) -> list:
    """Word 列表 → 历史 5 元组 (word, count, independent, binding, ent)，
    供 interactive_cloud 复用而不改其内部实现。"""
    return [(w.word, w.count, w.independent, w.binding, w.ent) for w in candidates]


def emit_interactive(prefix: str, out_dir: str, candidates: List[Word],
                     raw_texts: List[str], top_n: int, maxlen: int, layout,
                     standalone: bool = False) -> None:
    """包装 interactive_cloud.emit_interactive（外壳 HTML + data.js / 单文件内联）。"""
    import interactive_cloud
    interactive_cloud.emit_interactive(
        prefix, out_dir, _to_legacy(candidates), raw_texts, top_n, maxlen,
        layout, standalone=standalone)
