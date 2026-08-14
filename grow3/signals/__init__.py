"""grow3.signals —— 信号模块集合。

每个信号模块实现统一接口：
    cal(ctx: ScanContext) -> Dict[word, float]
其中 -1.0 表示 N/A / 豁免（如复合熵无真实邻居证据、indep 候选数不足等）。

信号只读 ScanContext，各自产出一列数值，互不依赖。新信号 = 加一个模块 +
在 Word 上加一个字段 + 在 gates 注册一个 gate。
"""
from __future__ import annotations

from . import ent, cohesion, indep, spe_rsr, role, asym

# 信号注册表：名称 -> (模块, 计算函数名, 对应的 Word 字段)
SIGNAL_REGISTRY = {
    "ent": (ent, "cal_ent", "ent"),
    "cohesion": (cohesion, "cal_cohesion", "cohesion"),
    "indep": (indep, "cal_indep", "indep"),
    "spe": (spe_rsr, "cal_spe", "spe"),
    "rsr": (spe_rsr, "cal_rsr", "rsr"),
    "role": (role, "solve_roles", "role"),
    "asym": (asym, "cal_asym", "asym"),
}
