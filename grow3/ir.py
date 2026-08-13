"""grow3.ir —— 统一中间表示（Intermediate Representation）。

一次扫描（scan_once）的产物即统一 IR：

    ScanContext  承载跨信号共享的全局中间量
                 （语料字符串、位置权重、候选位置表、字频、ngram 频次、单字种子）
    Word         候选词的命名行结构，替代历史版本里散乱的 5/7 字段元组

设计要点（来自方案书 Step 2 验证结论）：
- 扫描与信号天然可分：SPE 从 2.3.3 扫描产物（cand_count）重算零误差，
  说明 IR 定义正确，信号模块只需实现 cal(word, ctx) 接口即可。
- 信号模块只读 ScanContext，各自产出一列数值，绝不互相依赖。
- 新信号 = 在 Word 上加一个字段 + 一个 cal_xxx(ctx) 函数 + 一个 gate，
  不再需要改任何解包/下游（这是 2.3.3 那次改 60+ 行的痛点）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Union


@dataclass
class ScanContext:
    """一次扫描产出的统一中间表示（IR）。

    所有信号模块（ent / cohesion / indep / spe_rsr）只读这份结构，
    各自 ``cal(word, ctx) -> float``（或 ``-1.0`` 表示 N/A/豁免）。
    """

    # 语料字符串（含 SEP 段分隔哨兵与 PUNCT' 特殊汉字邻居哨兵）
    S: str = ""
    # 位置 -> 权重（去重加权；未去重时权重均为 1.0）
    wgt: Dict[int, float] = field(default_factory=dict)
    # 词 -> 出现位置列表（indep 覆盖判定需要）
    cand_lst: Dict[str, List[int]] = field(default_factory=dict)
    # 词 -> 加权 count（SPE/RSR 需要）
    cand_count: Dict[str, float] = field(default_factory=dict)
    # 字 -> 频次
    charfreq: Dict[str, int] = field(default_factory=dict)
    # n-gram -> 频次（凝固度 PMI 需要）
    ngram_freq: Dict[str, int] = field(default_factory=dict)
    # 单字 -> 位置列表（BFS 生长种子）
    pos_single: Dict[str, List[int]] = field(default_factory=dict)
    # 去重字符数（凝固度 PMI 分母 N_char）
    n_char: int = 0

    # ---- 以下为可选辅助量，由信号在闸门前统一填充，避免重复遍历 ----
    # 超词遍历中间量（spe/rsr 同一次超词遍历同时算出）：
    #   super_info[sub] = {
    #       'spe_bucket': [前缀计数, 中缀计数, 后缀计数],
    #       'rsr': [(left, right, cnt_s), ...],
    #       'super_set': set(包含 sub 的超词),
    #   }
    super_info: Dict[str, dict] = field(default_factory=dict)


@dataclass
class Word:
    """候选词命名行结构。后续新信号直接加字段，不再改解包。

    字段顺序与历史 write_word_csv 输出对齐（word,count,independent,binding,len,ent…），
    但扩展字段（cohesion/indep/spe/rsr）放在尾部，保证下游解包向后兼容。
    """

    word: str
    count: int
    independent: int
    binding: float
    # ---- 信号列（默认 -1.0 / 0.0 表示尚未计算或 N/A 豁免）----
    ent: float = -1.0          # 复合熵（横向外部邻居）
    cohesion: float = 0.0      # 凝固度 PMI（内部紧密度）
    indep: float = -1.0        # 词本身偏序（候选/位置结构复用）
    spe: float = -1.0          # 超词位置熵（纵向包含秩序）
    rsr: float = -1.0          # 补集偏序

    @property
    def length(self) -> int:
        return len(self.word)
