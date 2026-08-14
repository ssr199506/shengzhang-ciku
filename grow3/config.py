"""grow3.config —— 面板抽象：所有信号开关与参数收敛到 PipelineConfig。Step 6 落地。

设计原则（方案书 Step 6）：
- 面板**不**引入企业级抽象（不加依赖注入/插件热加载），就是"一份 config + 按声明组装"。
- 参数名与历史分支 CLI 完全对齐（--min-ent / --cohesion / --indep / --spe-rescue / --rsr-rescue），
  避免记忆负担。
- 默认参数须复现 main 5865（min_ent=0.5 + ent_merge_ratio=0.25，其余闸门关闭）。

本文件 Step 1 先把数据结构中置好（仅数据，无组装逻辑）；Step 6 补 CLI 映射与 gate 组装。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    """一条完整管道的全部旋钮。默认值 = main 5865 基线（仅复合熵门开启）。"""

    # ---- 扫描 / 清洗 ----
    ent_merge_ratio: float = 0.25     # 合并触发比（苟在阈值边缘的寄生对也合并救回）
    ent_punct_exempt: bool = True     # 符号邻居豁免（PUNCT' 特殊汉字邻居参与熵但不作邻居判定）
    no_punct_ent: bool = False        # 关闭标点感知熵（非 CJK 不保留为哨兵）
    no_merge: bool = False            # 关闭合并模式（ratio=0，恒用 min(左熵,右熵)）

    # ---- 过滤门（AND 链）----
    min_ent: float = 0.5              # 复合熵阈值；<=0 表示关闭该门
    min_cohesion: float = 0.0         # 凝固度阈值；<=0 关闭
    min_indep: float = 0.0            # 词本身偏序阈值；<=0 关闭

    # ---- 救援门（条件，依赖过滤前后中间态）----
    spe_rescue: float = 0.0           # SPE 救援阈值；<=0 关闭
    rsr_rescue: float = 0.0           # RSR 救援阈值；<=0 关闭（且与 spe 取 AND）
    rsr_mode: str = "mean"            # RSR 聚合模式：mean / max
    min_super_cnt: int = 2            # 超词最小出现次数（SPE/RSR 遍历门槛；等价 2.4.x MIN_SUPER_CNT=2）

    # ---- 凝固度边界 ----
    cohesion_max_len: int = 8         # 超过此长度的词不参与凝固度计算（N/A 放行）

    # ---- 纯结构实验信号（feat/role-asym，默认全部关闭，不影响既有行为）----
    role_enabled: bool = False        # 计算 role 列（偏序图角色迭代，含 U2 退化）
    role_max_depth: int = -1          # role 迭代深度：1=U2，N=迭代 N 帧，-1=不动点
    role_alpha: float = 0.85          # 阻尼（α<1 保证收敛）
    min_role: float = 0.0             # role 主干度闸门阈值；<=0 关闭，role>=thresh 才留
    role_rescue: float = 0.0          # role 主干度救援阈值；<=0 关闭，从被滤集捞回 role>=thresh
    asym_enabled: bool = False        # 计算 asym 列（条件熵不对称性）
    asym_rescue: float = 0.0          # asym 救援阈值；<=0 关闭，从被滤集捞回 asym>=thresh 的候选
    min_asym: float = 0.0             # asym 过滤门阈值；<=0 关闭，asym>=thresh 才留（低值=碎片）

    # ---- 输入 / 输出 ----
    title_col: int = 0                # 书名列号（0-based）
    intro_col: int = 1                # 简介列号；-1 表示无简介
    top_n: int = 0                    # 输出词数上限；0 = 全部
    maxlen: int = 8                   # 候选词最大长度
    no_cloud: bool = False           # 跳过词云渲染（默认渲染，与历史 main 对齐；产物含书名勿入库）
    standalone: bool = False         # 互动词云单文件内联 HTML（双击即开，无需外部 data.js）
    title_complement: bool = True    # 补集（未收录书名）功能：生成时注入补集 UI 补丁；关闭则 HTML 字节级等同功能前
    bind_thresh: float = 1.0          # 前后集中度闸门；>=1.0 表示关闭（基线）

    def gate_summary(self) -> str:
        """人类可读的闸门开关摘要，供审计/日志使用。"""
        parts = [f"ent>={self.min_ent}"]
        if self.min_cohesion > 0:
            parts.append(f"coh>={self.min_cohesion}")
        if self.min_indep > 0:
            parts.append(f"indep>={self.min_indep}")
        if self.spe_rescue > 0:
            rsr = f"&rsr>={self.rsr_rescue}" if self.rsr_rescue > 0 else ""
            parts.append(f"spe-rescue>={self.spe_rescue}{rsr}")
        if self.min_role > 0:
            parts.append(f"role>={self.min_role}")
        if self.min_asym > 0:
            parts.append(f"asym>={self.min_asym}")
        if self.role_rescue > 0:
            parts.append(f"role-rescue>={self.role_rescue}")
        if self.asym_rescue > 0:
            parts.append(f"asym-rescue>={self.asym_rescue}")
        return " + ".join(parts) if parts else "no-gate"

    def to_dict(self) -> dict:
        """全部旋钮快照，供审计日志 config 字段使用。"""
        return {
            "ent_merge_ratio": self.ent_merge_ratio,
            "min_ent": self.min_ent,
            "min_cohesion": self.min_cohesion,
            "min_indep": self.min_indep,
            "spe_rescue": self.spe_rescue,
            "rsr_rescue": self.rsr_rescue,
            "rsr_mode": self.rsr_mode,
            "min_super_cnt": self.min_super_cnt,
            "cohesion_max_len": self.cohesion_max_len,
            "role_enabled": self.role_enabled,
            "role_max_depth": self.role_max_depth,
            "role_alpha": self.role_alpha,
            "min_role": self.min_role,
            "role_rescue": self.role_rescue,
            "asym_enabled": self.asym_enabled,
            "asym_rescue": self.asym_rescue,
            "min_asym": self.min_asym,
            "bind_thresh": self.bind_thresh,
            "no_punct_ent": self.no_punct_ent,
            "no_merge": self.no_merge,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        """从配置 dict 构造（JSON 配置文件入口）。

        只接受 dataclass 已声明的字段；未知键（拼写错误/多余键）直接报错，
        方便配置文件调试。注意 cli 级键（input/out/audit/no_header/no_dedup）
        不在此列，由 cli 先剥离再调用本方法。
        """
        known = {f for f in cls.__dataclass_fields__}
        unknown = {k for k in d if k not in known and not k.startswith("_")}
        if unknown:
            raise ValueError(
                f"配置文件含未知参数: {sorted(unknown)}\n"
                f"合法参数: {sorted(known)}")
        return cls(**{k: v for k, v in d.items() if k in known})
