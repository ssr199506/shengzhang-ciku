# -*- coding: utf-8 -*-
"""signal_bank/specs.py —— 信号/闸门注册表（Phase 1）。

设计红线（见 升级计划 §九）：
- grow3/ 一行不改；本文件用 adapter 把异构信号函数统一为 (ctx, cfg) 签名。
- 算法本体（cal_ent/cal_cohesion/.../solve_roles/cal_asym）不在本文件实现，只"接线"。
- 注册表是声明式：列↔模块一一对应；加一个新信号 = 1 个模块文件 + 1 行 import。

数据结构：
    SignalSpec  描述一个信号模块（算什么列、消费哪些参数、依赖哪些共享中间量）
    GateSpec    描述一个闸门（绑定哪一列、and/rescue、阈值配置键、哨兵策略、组合条件）

全部事实读 grow3 源码核实（2026-08-14，见同目录 盘点.md）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Tuple

# grow3 信号模块（只 import，不修改）
from grow3.config import PipelineConfig
from grow3.signals.ent import cal_ent
from grow3.signals.cohesion import cal_cohesion
from grow3.signals.indep import cal_indep
from grow3.signals.spe_rsr import cal_spe_rsr
from grow3.signals.role import solve_roles
from grow3.signals.asym import cal_asym


# ----------------------------------------------------------------- 配置键取值
def _cfg(cfg, key, default):
    """从 PipelineConfig 取字段；兼容 dict 形式（cfg 快照/测试用）。"""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


# ----------------------------------------------------------------- 信号规格
@dataclass(frozen=True)
class SignalSpec:
    """一个信号模块的声明。

    compute 字段是 adapter：(ctx, cfg) -> dict | tuple[dict, ...]
        - 单产出列：返回 dict（{word: value}）
        - 多产出列（如 spe_rsr 产出 spe+rsr）：返回 (dict, dict)；columns 声明两列名
    其余字段用于文档化 + 增量重算的"脏传播"判定。
    """

    name: str                                   # 唯一模块名
    compute: Callable                           # adapter：(ctx, cfg) -> dict | tuple[dict,...]
    columns: Tuple[str, ...]                    # 产出列名（spe_rsr -> ("spe","rsr")）
    sentinel: float = -1.0                       # N/A 哨兵（cohesion 特例 0.0）
    compute_params: Tuple[str, ...] = ()         # 计算消费的配置键（脏传播用）
    depends_on: Tuple[str, ...] = ()             # 依赖的共享中间量/其它列（拓扑+脏传播声明）
    needs_columns: Tuple[str, ...] = ()          # 若本列由其它列推导，声明被依赖列
    higher_is: str = "good"                      # 语义方向（仅展示）
    help: str = ""                               # 一句话说明


# ----------------------------------------------------------------- 闸门规格
@dataclass(frozen=True)
class GateSpec:
    """一个闸门的声明，镜像 gates.py 的一行语义。

    sentinel_policy:
        exempt   AND 门：v < sentinel → 放行（ent/indep/role/asym 的 -1 哨兵）
        exclude  rescue 门：v < sentinel → 排除不救（spe_rescue 的 -1 哨兵）
        none     无特殊处理（rescue 门哨兵自然不过正阈值）
    extra: 组合条件 [(列名, 配置键, 比较符)]. 仅当该配置键 >0 时附加生效。
    """

    signal: str
    kind: str                                   # "and" | "rescue"
    param: str                                  # 阈值配置键
    cmp: str = ">="                             # 当前全部 >=
    sentinel_policy: str = "exempt"             # and: exempt / rescue: exclude | none
    extra: Tuple[Tuple[str, str, str], ...] = ()  # 组合条件 ((signal_col, cfg_key, op), ...)
    order: int = 0                              # 链序


# ----------------------------------------------------------------- 现有 6 信号注册
# adapter 统一为 (ctx, cfg)；不改 grow3 模块签名（最小改动红线）。
REGISTRY: list = [
    SignalSpec(
        name="ent",
        compute=lambda ctx, cfg: cal_ent(ctx, _cfg(cfg, "ent_merge_ratio", 0.25)),
        columns=("ent",),
        compute_params=("ent_merge_ratio",),
        sentinel=-1.0,
        higher_is="good",
        help="复合熵（横向外部邻居），高=边界清晰=真词",
    ),
    SignalSpec(
        name="cohesion",
        compute=lambda ctx, cfg: cal_cohesion(ctx, _cfg(cfg, "cohesion_max_len", 8)),
        columns=("cohesion",),
        compute_params=("cohesion_max_len",),
        sentinel=0.0,
        higher_is="good",
        help="凝固度 PMI（内部紧密度），高=内部凝固；N/A 时为 0.0",
    ),
    SignalSpec(
        name="indep",
        compute=lambda ctx, cfg: cal_indep(ctx),
        columns=("indep",),
        compute_params=(),                      # super_min 是死参数，不登记
        sentinel=-1.0,
        higher_is="good",
        help="词本身偏序（候选/位置结构复用），值∈[0,1]",
    ),
    SignalSpec(
        name="spe_rsr",
        compute=lambda ctx, cfg: cal_spe_rsr(
            ctx, _cfg(cfg, "min_super_cnt", 2), _cfg(cfg, "rsr_mode", "mean")),
        columns=("spe", "rsr"),
        compute_params=("min_super_cnt", "rsr_mode"),
        sentinel=-1.0,
        higher_is="good",
        help="超词位置熵 + 补集偏序（二元组）；-1=无超词",
    ),
    SignalSpec(
        name="role",
        compute=lambda ctx, cfg: solve_roles(
            ctx, _cfg(cfg, "role_max_depth", -1),
            _cfg(cfg, "min_super_cnt", 2), _cfg(cfg, "role_alpha", 0.85)),
        columns=("role",),
        compute_params=("role_max_depth", "role_alpha", "min_super_cnt"),
        depends_on=("super_index",),
        sentinel=-1.0,
        higher_is="good",
        help="偏序图角色迭代主干度（0~1），高=被虚词修饰的主干；-1=无超词",
    ),
    SignalSpec(
        name="asym",
        compute=lambda ctx, cfg: cal_asym(ctx, _cfg(cfg, "min_super_cnt", 2)),
        columns=("asym",),
        compute_params=("min_super_cnt",),
        depends_on=("super_index",),
        sentinel=-1.0,
        higher_is="good",
        help="条件熵不对称性 H(w|r)-H(r|w)，正大=被虚词修饰的主干；-1=无超词",
    ),
]

# 模块名 -> SignalSpec（快速查表）
SIGNAL_BY_NAME = {s.name: s for s in REGISTRY}
# 列名 -> SignalSpec（多产出列模块一个列对应同一 spec）
SIGNAL_BY_COLUMN = {col: s for s in REGISTRY for col in s.columns}
ALL_COLUMNS = tuple(col for s in REGISTRY for col in s.columns)   # ("ent","cohesion","indep","spe","rsr","role","asym")


# ----------------------------------------------------------------- 8 闸门注册
# gates.py 每行 → 一行 GateSpec 声明（逐字对照见 盘点.md）。
GATES: list = [
    GateSpec("ent", "and", "min_ent", sentinel_policy="exempt", order=1),
    GateSpec("cohesion", "and", "min_cohesion", sentinel_policy="exempt", order=2),
    GateSpec("indep", "and", "min_indep", sentinel_policy="exempt", order=3),
    GateSpec("role", "and", "min_role", sentinel_policy="exempt", order=4),
    GateSpec("asym", "and", "min_asym", sentinel_policy="exempt", order=5),
    GateSpec("asym", "rescue", "asym_rescue", sentinel_policy="none",
             extra=(("role", "min_role", ">="),), order=6),
    GateSpec("role", "rescue", "role_rescue", sentinel_policy="none", order=7),
    GateSpec("spe", "rescue", "spe_rescue", sentinel_policy="exclude",
             extra=(("rsr", "rsr_rescue", ">="),), order=8),
]

GATE_BY_PARAM = {g.param: g for g in GATES}


def available_signals(cfg) -> tuple:
    """返回在给定 cfg 下**确实被算出**的列（供 v1 dump 缺列时判定可查表范围）。

    沿用 run_pipeline 的开关逻辑：
        role 列：role_enabled or min_role>0 or role_rescue>0
        asym 列：asym_enabled or asym_rescue>0 or min_asym>0
        spe/rsr 列：spe_rescue>0 or rsr_rescue>0
        ent/cohesion/indep：仅在对应 AND 门>0 时由 run_pipeline 计算
    注意：dump v2 永远算全列，本函数只用于"旧/部分 dump"的资格检查。
    """
    cols = []
    if _cfg(cfg, "min_ent", 0) > 0:
        cols.append("ent")
    if _cfg(cfg, "min_cohesion", 0) > 0:
        cols.append("cohesion")
    if _cfg(cfg, "min_indep", 0) > 0:
        cols.append("indep")
    if (_cfg(cfg, "spe_rescue", 0) > 0 or _cfg(cfg, "rsr_rescue", 0) > 0):
        cols.append("spe"); cols.append("rsr")
    if (_cfg(cfg, "role_enabled", False) or _cfg(cfg, "min_role", 0) > 0
            or _cfg(cfg, "role_rescue", 0) > 0):
        cols.append("role")
    if (_cfg(cfg, "asym_enabled", False) or _cfg(cfg, "asym_rescue", 0) > 0
            or _cfg(cfg, "min_asym", 0) > 0):
        cols.append("asym")
    return tuple(cols)


__all__ = ["SignalSpec", "GateSpec", "REGISTRY", "GATES", "SIGNAL_BY_NAME",
           "SIGNAL_BY_COLUMN", "ALL_COLUMNS", "GATE_BY_PARAM", "available_signals",
           "PipelineConfig"]
