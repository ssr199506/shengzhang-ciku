# dump 解耦升级计划：从"专化快照"到"信号仪表盘"（细化工程版）

> 状态：提案（未实施）。**未经用户批准不动手**。
> 版本：v0.2（2026-08-14），在 v0.1 基础上补齐全部工程细节：信号模块现状盘点、精确数据结构、
> 通用引擎伪代码、dump v2 schema、增量重算与缓存失效、验收方法、参数分类总表、明确"不做"清单。
> 边界声明：**算法本体不做元数据化；gates.py 不改；spe_rsr 与 _super 不合并**（见 §九）。

---

## 〇、结论先行：四个问题的最终答案（细化版）

| 问题 | 答案 | 依据 |
|---|---|---|
| ① 内部解耦？ | **能**：SignalSpec 注册表，列↔模块一一对应 | §三 |
| ② 加模块即加列、轻量更新？ | **能**：`compute_all` 按注册表循环 + `depends_on` 增量重算 | §五.1 |
| ③ 特性映射/复用即生成信号机制？ | **部分能**：管道层全声明式；算法本体不可生成，但共享中间量可复用（`super_index`） | §九.1 |
| ④ 免 dump 实体成仪表盘？ | **能**：`SignalBank` 内存信号库，JSON 退化为可选持久化 | §五.4 |

---

## 一、工程现状盘点（全部硬编码点与异构事实）

### 1.1 信号模块现状（读源码核实，2026-08-14）

| 模块 | 函数签名（异构！） | 产出列 | 消费的配置 | 共享中间量 | 哨兵语义 |
|---|---|---|---|---|---|
| `ent.py` | `cal_ent(ctx, ent_merge_ratio=0.25)` | ent | `ent_merge_ratio` | — | -1.0 豁免 |
| `cohesion.py` | `cal_cohesion(ctx, max_len=8)` | cohesion | `cohesion_max_len` | — | **0.0=N/A**，`len<2` 在闸门豁免 |
| `indep.py` | `cal_indep(ctx, super_min=1)` | indep | （super_min 是死参数） | — | 值∈[0,1] 永不为负，`<0` 分支理论化 |
| `spe_rsr.py` | `cal_spe_rsr(ctx, min_super_cnt=2, rsr_mode='mean')` | **spe, rsr（二元组）** | `min_super_cnt, rsr_mode` | 自建 `_build_super`（**不共享**） | -1.0 豁免/排除 |
| `role.py` | `solve_roles(ctx, max_depth=-1, min_super_cnt=2, alpha=0.85, ...)` | role | `role_max_depth, role_alpha, min_super_cnt` | `build_super_index`（ctx.super_info 缓存） | -1.0 豁免 |
| `asym.py` | `cal_asym(ctx, min_super_cnt=2)` | asym | `min_super_cnt` | `build_super_index`（同上） | -1.0 豁免 |

**三个必须正视的事实**：
1. **签名异构** → 注册表必须用 **adapter 包装**统一为 `(ctx, cfg) -> dict | tuple[dict,...]`，不改模块签名（最小改动红线）。
2. **超词索引有两套**：`_super.py` 的 `build_super_index`（缓存于 `ctx.super_info["_super_index"]`，role/asym 共享）与 `spe_rsr.py` 的 `_build_super`（自建，不缓存）。**合并它们有逐字数字漂移风险 → 列入"不做"**（§九.4）。`depends_on` 只作排序/脏传播的**声明**，不代表框架会去合并实现。
3. **scan 级参数**：`ent_merge_ratio` 和 `cohesion_max_len` 同时被 `scan_once(S, wgt, ent_merge_ratio, True, cohesion_max_len)` 消费（`cli.py:161`）→ 动了它们**候选集就变**，属全量重算，绝不可能是增量。

### 1.2 闸门现状（gates.py 逐行对照）

| # | 闸门 | kind | 激活条件 | 通过/救援判据（gates.py 原文） | 哨兵处理 |
|---|---|---|---|---|---|
| 1 | ent | and | `min_ent>0` | `w.ent<0 or w.ent>=min_ent` | `<0` 放行 |
| 2 | cohesion | and | `min_cohesion>0` | `len(w.word)<2 or w.cohesion>=min_cohesion` | `len<2` 放行 |
| 3 | indep | and | `min_indep>0` | `w.indep<0 or w.indep>=min_indep` | `<0` 放行 |
| 4 | role（滤） | and | `min_role>0` | `w.role<0 or w.role>=min_role` | `<0` 放行 |
| 5 | asym（滤） | and | `min_asym>0` | `w.asym<0 or w.asym>=min_asym` | `<0` 放行 |
| 6 | asym_rescue | rescue | `asym_rescue>0` | `w.asym>=asym_rescue`；若 `min_role>0` 再 `and w.role>=min_role` | —（-1 自然不过阈） |
| 7 | role_rescue | rescue | `role_rescue>0` | `w.role>=role_rescue` | — |
| 8 | spe_rescue | rescue | `spe_rescue>0` | `w.spe<0 → 排除不救`；`w.spe>=spe_rescue`；若 `rsr_rescue>0` 再 `and w.rsr>=0 and w.rsr>=rsr_rescue` | **排除**（区别于豁免） |

**链序**：1→2→3→4→5（AND 依次取交）→ 6→7→8（救援门**依次消费** filtered，前门捞走的词后门看不到）。
> 数学上救援门并集与顺序无关（前几轮已证明），但为与 gates.py 审计语义一致，`kept_for` 保留链序。

### 1.3 当前 dump 是"专化快照"

`dump_signals.py` 只存 `word/count/role/asym/pass_and`（pass_and 在 0.5/1.5/0.05 固定下算好）：
- AND 门不可查表（无 ent/coh/indep 值）→ 改 min_ent 就得重跑
- spe/rsr 不可查表（无列）→ 改 spe_rescue/rsr_rescue 就得重跑
- **升级目标：dump 存全信号列，所有"纯比较"闸门全部可查表**

---

## 二、目标架构（三层解耦）

```
┌──────────────────────────────────────────────────────┐
│ 信号层 signals/*.py —— 唯一要写代码的部分（cal_xxx 算法本体）  │
│   每个模块 = cal_xxx(ctx, ...) + SPEC 注册声明（adapter 包装） │
└───────────────┬──────────────────────────────────────┘
                │ 注册（import 即自动收集）
┌───────────────▼──────────────────────────────────────┐
│ 注册表 SIGNAL_REGISTRY / GATE_REGISTRY                 │
│   SignalSpec: name/compute(adapter)/columns/sentinel/   │
│               compute_params/depends_on/needs_columns   │
│   GateSpec:   kind/param/cmp/sentinel_policy/extra/order │
└───────────────┬──────────────────────────────────────┘
                │ 驱动
┌───────────────▼──────────────────────────────────────┐
│ 通用引擎（新代码，全部在 调参工具/ 内，grow3/ 一行不改）          │
│   compute_all(ctx,cfg)   —— 按注册表出全信号列（增量可）        │
│   kept_for(words,cols,cfg) —— 镜像 gates.py 语义，任意组合     │
│   plan(cfg_old,cfg_new)  —— 自动判 FULL/INCREMENTAL/QUERY     │
└───────────────┬──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│ 仪表盘层 SignalBank（内存）+ REPL/CLI 交互查询                │
│   sweep / margin_audit / constraint_box / surface      │
│   dump JSON = 可选持久化（不再是必需实体）                    │
└──────────────────────────────────────────────────────┘
```

**红线**：所有新代码放 `调参工具/`，`grow3/` 下的 `ir/gates/cli/config/output` 一律不改。加新信号只动 `signals/*.py`（写算法+SPEC）+ 注册表 import。

---

## 三、SignalSpec 精确定义 + 现有 6 模块注册表

### 3.1 数据结构（放 `调参工具/signal_bank/specs.py`）

```python
@dataclass(frozen=True)
class SignalSpec:
    name: str                            # 唯一列名
    compute: Callable                    # adapter：(ctx, cfg) -> dict | tuple[dict,...]
    columns: tuple[str, ...]             # 产出列（spe_rsr → ("spe","rsr")）
    sentinel: float = -1.0               # N/A 哨兵（cohesion 特例在 GateSpec 处理）
    compute_params: tuple[str, ...] = () # 计算消费的配置键（脏传播用）
    depends_on: tuple[str, ...] = ()     # 依赖的共享中间量/其它列（拓扑+脏传播）
    needs_columns: tuple[str, ...] = ()  # 若本列由其它列推导，声明被依赖列
    higher_is: str = "good"              # 语义方向（仅展示）
    help: str = ""                       # 一句话说明
```

### 3.2 现有 6 模块的注册（adapter 统一签名，不改模块）

```python
from grow3.signals.ent import cal_ent
from grow3.signals.cohesion import cal_cohesion
from grow3.signals.indep import cal_indep
from grow3.signals.spe_rsr import cal_spe_rsr
from grow3.signals.role import solve_roles
from grow3.signals.asym import cal_asym

def _cfg_lookup(cfg, key, default):
    return getattr(cfg, key, default)

REGISTRY: list[SignalSpec] = [
    SignalSpec(name="ent",      compute=lambda ctx, cfg: cal_ent(ctx, _cfg_lookup(cfg, "ent_merge_ratio", 0.25)),
               columns=("ent",), compute_params=("ent_merge_ratio",), sentinel=-1.0),
    SignalSpec(name="cohesion", compute=lambda ctx, cfg: cal_cohesion(ctx, _cfg_lookup(cfg, "cohesion_max_len", 8)),
               columns=("cohesion",), compute_params=("cohesion_max_len",), sentinel=0.0),
    SignalSpec(name="indep",    compute=lambda ctx, cfg: cal_indep(ctx),
               columns=("indep",), compute_params=(), sentinel=-1.0),
    SignalSpec(name="spe_rsr",  compute=lambda ctx, cfg: cal_spe_rsr(ctx, _cfg_lookup(cfg, "min_super_cnt", 2),
                                                                     _cfg_lookup(cfg, "rsr_mode", "mean")),
               columns=("spe", "rsr"), compute_params=("min_super_cnt", "rsr_mode"), sentinel=-1.0),
    SignalSpec(name="role",     compute=lambda ctx, cfg: solve_roles(ctx, _cfg_lookup(cfg, "role_max_depth", -1),
                                                                     _cfg_lookup(cfg, "min_super_cnt", 2),
                                                                     _cfg_lookup(cfg, "role_alpha", 0.85)),
               columns=("role",), compute_params=("role_max_depth", "role_alpha", "min_super_cnt"),
               depends_on=("super_index",), sentinel=-1.0),
    SignalSpec(name="asym",     compute=lambda ctx, cfg: cal_asym(ctx, _cfg_lookup(cfg, "min_super_cnt", 2)),
               columns=("asym",), compute_params=("min_super_cnt",),
               depends_on=("super_index",), sentinel=-1.0),
]
```

> 说明：
> - `compute_params` 只登记**信号值真的会变**的参数（`indep` 的 super_min 是死参数 → 不登记）。
> - `ent_merge_ratio`/`cohesion_max_len` 同时是 scan 参数（§一.1.3）→ 在 plan() 里归"全量"，此处登记仅为文档化。
> - `depends_on=("super_index",)` 是**声明**，不触发合并实现（§九.4）；作用见 §五.1 的脏传播。

### 3.3 新增一个信号 = 1 个文件 + 1 行 import

```python
# signals/xyz.py  （唯一写代码的地方）
def cal_xyz(ctx, cfg): ...            # 算法本体（不可省，见 §九.1）

SPEC = SignalSpec(
    name="xyz", compute=lambda ctx, cfg: cal_xyz(ctx, cfg.xyz_param),
    columns=("xyz",), compute_params=("xyz_param",),
    depends_on=("super_index",),       # 白嫖共享超词索引，少写遍历
    needs_columns=("asym",),           # 若想基于 asym 列派生
    gate=GateSpec(kind="rescue", param="xyz_rescue", cmp=">="),
    higher_is="good",
)
```

注册表 `import signals.xyz` 后：dump 自动多一列、模拟器自动支持 `xyz_rescue` 阈值、仪表盘自动可查。**接入成本 = 1 文件 + 1 import，替代现状 7 文件。**

---

## 四、GateSpec 精确定义 + 8 闸门声明

### 4.1 数据结构

```python
@dataclass(frozen=True)
class GateSpec:
    signal: str                      # 绑定的信号列名（asym_rescue → "asym"）
    kind: str                        # "and" | "rescue"
    param: str                       # 配置键（阈值）
    cmp: str = ">="                  # 当前全部 >=
    sentinel_policy: str = "exempt"  # and门: exempt(哨兵放行); rescue门: exclude(哨兵排除) / none
    extra: tuple = ()                # 组合条件 [(列名, 配置键, 比较符), ...]，仅当该配置>0时生效
    order: int = 0                   # 链序
```

### 4.2 8 个闸门的声明（gates.py 每行 → 一行声明）

```python
GATES: list[GateSpec] = [
    GateSpec("ent",     "and",   "min_ent",      sentinel_policy="exempt",            order=1),
    GateSpec("cohesion","and",   "min_cohesion", sentinel_policy="exempt",            order=2),
    GateSpec("indep",   "and",   "min_indep",    sentinel_policy="exempt",            order=3),
    GateSpec("role",    "and",   "min_role",     sentinel_policy="exempt",            order=4),
    GateSpec("asym",    "and",   "min_asym",     sentinel_policy="exempt",            order=5),
    GateSpec("asym",    "rescue","asym_rescue",  sentinel_policy="none",
             extra=(("role", "min_role", ">="),),                                     order=6),
    GateSpec("role",    "rescue","role_rescue",  sentinel_policy="none",              order=7),
    GateSpec("spe",     "rescue","spe_rescue",   sentinel_policy="exclude",
             extra=(("rsr", "rsr_rescue", ">="),),                                    order=8),
]
```

> 语义对照：
> - **exempt**：`v < sentinel → 放行`（AND 门）；rescue 门哨兵自然小于正阈值，无需特判。
> - **exclude**（仅 spe_rescue）：`v < sentinel → 排除不救`（对应 gates.py 的 `if w.spe < 0: still`）。
> - **cohesion 的 `len<2` 豁免**：不属于信号值语义，放 `kept_for` 里硬编码这条（§五.2），不进声明。
> - **extra**：`asym_rescue` 在 `min_role>0` 时追加 `role>=min_role`；`spe_rescue` 在 `rsr_rescue>0` 时追加 `rsr>=0 and rsr>=rsr_rescue`。

---

## 五、通用引擎（全部新代码，放 调参工具/signal_bank/）

### 5.1 compute_all —— 按注册表出全信号列（含增量）

```python
def compute_all(ctx, cfg, registry, dirty=None):
    """dirty=None 全算；dirty=列名集合 只重算受影响列（增量）。"""
    # 拓扑序：needs_columns / depends_on 涉及的列先算（本项目现有依赖简单，无需通用图算法，
    # 用一个固定序 + 断言校验即可；若未来依赖复杂再升级通用拓扑排序）
    cols = {}
    for spec in registry:
        if dirty is not None and not (set(spec.columns) & dirty):
            continue
        out = spec.compute(ctx, cfg)
        if len(spec.columns) == 1:
            out = (out,)
        for col, val in zip(spec.columns, out):
            cols[col] = val
    return cols
```

**脏传播**：`dirty` 由 `plan()` 产出。增量重算时，若脏集含 `role/asym`，**必须同步失效 `ctx.super_info["_super_index"]` 缓存**（缓存 key 不含 min_super_cnt，见 §一.1 事实 2）：

```python
def _invalidate_super(ctx, cfg_old, cfg_new):
    if cfg_old.min_super_cnt != cfg_new.min_super_cnt:
        ctx.super_info.pop("_super_index", None)   # 否则 role/asym 吃到旧索引
```

### 5.2 kept_for —— 通用模拟（镜像 gates.py 语义）

```python
def kept_for(words, cols, cfg, gates):
    def val(w, sig):          # 无列 → 视为哨兵（兼容 v1 dump 缺列）
        return cols[sig].get(w, -1.0)

    # ---- AND 链（按 order 依次取交；哨兵 exempt 放行）----
    passed, filtered = [], []
    for w in words:
        ok = True
        for g in (g for g in gates if g.kind == "and"):
            if getattr(cfg, g.param, 0) <= 0:
                continue
            v = val(w, g.signal)
            if g.sentinel_policy == "exempt" and v < (g.sentinel if hasattr(g,'sentinel') else -1.0):
                continue                    # 哨兵放行
            if g.signal == "cohesion" and len(w.word) < 2:   # gates.py 硬编码的 len<2 豁免
                continue
            if not (v >= getattr(cfg, g.param)):
                ok = False; break
        (passed if ok else filtered).append(w)

    kept = set(passed)

    # ---- 救援链（按 order 依次消费 filtered）----
    for g in (g for g in gates if g.kind == "rescue"):
        th = getattr(cfg, g.param, 0)
        if th <= 0:
            continue
        rescued = []
        for w in filtered:
            v = val(w, g.signal)
            if g.sentinel_policy == "exclude" and v < g.sentinel:
                continue                    # 哨兵排除（spe_rescue）
            if not (v >= th):
                continue
            extra_ok = True
            for s2, p2, _cmp in g.extra:
                t2 = getattr(cfg, p2, 0)
                if t2 <= 0:
                    continue
                v2 = val(w, s2)
                if s2 == "rsr" and v2 < 0:  # gates.py: rsr 需 >=0
                    extra_ok = False; break
                if not (v2 >= t2):
                    extra_ok = False; break
            if extra_ok:
                rescued.append(w)
        kept |= set(rescued)
        filtered = [w for w in filtered if w not in set(rescued)]
    return kept
```

> 与 gates.py 的对照要求：**同一组 (cfg, 词集) 下，`kept_for` 与 `gate_chain` 输出逐词一致**——这是 Phase 3 的验收硬门（§八）。

### 5.3 plan —— 自动重跑检测（把"红灯/绿灯"机器化）

```python
SCAN_KEYS = {"ent_merge_ratio", "no_punct_ent", "no_merge", "cohesion_max_len"}
CORPUS_KEYS = {"input", "title_col", "intro_col", "no_header", "no_dedup"}

def plan(cfg_old, cfg_new, registry):
    if any(k in cfg_new and cfg_new[k] != cfg_old.get(k) for k in SCAN_KEYS | CORPUS_KEYS):
        return "FULL", None                # 候选集/语料变 → 全量重算（重建 ctx）
    dirty = set()
    for spec in registry:
        if any(cfg_new.get(p) != cfg_old.get(p) for p in spec.compute_params):
            dirty |= set(spec.columns)
    return ("QUERY", None) if not dirty else ("INCREMENTAL", dirty)
```

**参数分类总表（全部 config 字段 → 类别）**：

| 类别 | 参数 | 动作 |
|---|---|---|
| 语料/输入 | input、title_col、intro_col、no_header、no_dedup | **FULL**（重建 ctx） |
| 扫描 | ent_merge_ratio、no_punct_ent、no_merge、cohesion_max_len | **FULL**（候选集变） |
| 信号（增量） | min_super_cnt（脏：spe/rsr/role/asym + 清 super 缓存）、rsr_mode（脏：rsr）、role_max_depth（脏：role）、role_alpha（脏：role） | **INCREMENTAL** |
| 闸门（纯查表） | min_ent、min_cohesion、min_indep、min_role、min_asym、asym_rescue、role_rescue、spe_rescue、rsr_rescue | **QUERY**（列不动） |
| 无效果 | bind_thresh（gates 无此门）、no_cloud、top_n、maxlen、standalone、title_complement | 忽略 |

### 5.4 SignalBank —— 内存信号库（仪表盘底座，dump 变可选）

```python
class SignalBank:
    """一次扫描 + 信号表常驻内存；任何闸门阈值查询毫秒级。"""
    def __init__(self, corpus, cfg, registry=REGISTRY, gates=GATES):
        self._ctx, self._words = scan(corpus, cfg)      # 复用 grow3.scan
        self._cols = compute_all(self._ctx, cfg, registry)
        self._cfg = cfg

    def set_cfg(self, cfg_new):                          # 变更入口
        kind, dirty = plan(self._cfg, cfg_new, REGISTRY)
        if kind == "FULL": self.__init__(self._corpus, cfg_new)   # 重建
        elif kind == "INCREMENTAL":
            _invalidate_super(self._ctx, self._cfg, cfg_new)
            self._cols |= compute_all(self._ctx, cfg_new, REGISTRY, dirty=dirty)
        self._cfg = cfg_new                              # QUERY 只走这里

    def kept_for(self, **thresholds) -> set[str]:        # 任意组合，毫秒级
        return kept_for(self._words, self._cols, merged_cfg(self._cfg, thresholds), GATES)

    def columns(self) -> dict: ...
    def margin_audit(self, **thresholds) -> list[dict]:  # 敏感词余量表
    def constraint_box(self, **thresholds) -> dict:      # 安全框：a/r 可升上限
    def surface(self, a_grid, r_grid, metric="net") -> list[list]:  # 帕累托面
    def to_json(self, path=None) / @classmethod from_json:  # dump 退化为可选序列化
```

**仪表盘形态**：`python 调参工具/signal_bank/dashboard.py`（REPL 交互）或脚本式调用——
```python
bank = SignalBank("corpus.csv", DEFAULT_CFG)
bank.kept_for(asym_rescue=2.60, role_rescue=0.70)     # → 5375 词，毫秒
bank.margin_audit(asym_rescue=2.60, role_rescue=0.70) # → 康熙 0.200 / 围棋 0.239
bank.surface([2.4,2.6,2.8], [0.6,0.7,0.8], "net")     # → 3×3 net 面
```
> **dump JSON 不再是必需实体**：`SignalBank` 对象本身就是"表"。JSON 只在跨进程/重启恢复/与他人共享时用 `to_json/from_json`。

---

## 六、dump v2 schema（精确 JSON，向后兼容 v1）

```json
{
  "schema": 2,
  "meta": {
    "corpus": "corpus.csv",
    "n_docs": 8886,
    "n_candidates": 7150,
    "cfg_snapshot": {
      "min_ent": 0.5, "min_cohesion": 1.5, "min_indep": 0.05,
      "min_super_cnt": 2, "role_max_depth": -1, "role_alpha": 0.85
    },
    "columns": ["count", "ent", "cohesion", "indep", "spe", "rsr", "role", "asym"],
    "created": "2026-08-14T21:..."
  },
  "words": [
    {"word": "庆余年", "count": 90, "ent": 4.102, "cohesion": 1.812,
     "indep": 0.310, "spe": 2.55, "rsr": 1.21, "role": 0.784, "asym": 6.534},
    ...
  ]
}
```

- **v1 兼容**：`from_json` 读到 `schema==1`（word/count/role/asym/pass_and）时，缺列填 `None`（kept_for 里 `val()` 回退哨兵）→ 旧 dump 仍可用于救援族查询，但 AND 门/spe 查询需 v2。
- 每列精度统一 `round(..., 6)`（与现 dump 一致）。
- `pass_and` 不再需要——由 AND 门声明 + 列值即时推导（这才是"AND 门可查表"的关键）。

---

## 七、Phase 0–5 实施步骤（每步产出 + 验收）

| Phase | 内容 | 产出 | 验收标准 |
|---|---|---|---|
| **0** | 盘点现状 | `调参工具/signal_bank/盘点.md`：全部硬编码点清单（已在本计划 §一完成，落档即可） | 清单完整，无遗漏闸门/参数 |
| **1** | 建 `specs.py`：SignalSpec/GateSpec + 注册表 + 6 模块 adapter 声明 | `specs.py` + `registry.py` | 注册表可描述全部现状；不改 grow3 |
| **2** | dump v2：`compute_all` + schema v2 序列化 | `dump_v2.py`；产出全信号列 JSON | 8 列全；schema=2；v1 可读 |
| **3** | 通用模拟 `kept_for` + 随机 0 差异验收 | `simulate.py` + `verify_random.py` | **随机 20 组全参数阈值 vs 真实 CLI，对称差=0（压线词除外，单独列出复核）** |
| **4** | `plan()` 自动重跑检测 + 增量重算 + 缓存失效 | `plan.py`（含 `_invalidate_super`） | 改 role_alpha → 只重算 role 列；改 min_super_cnt → 清缓存+重算 4 列；改 min_ent → 0 重算 |
| **5** | `SignalBank` + `dashboard.py` 交互查询 | `signal_bank.py` + `dashboard.py` | REPL 覆盖 sweep/margin/box/surface；无 dump 文件依赖 |

**Phase 3 的随机验收设计**：
- 采样空间 = 9 个闸门阈值 × 随机取值（AND 门 0 或 [0.3, 0.7] 内随机、救援门 [1.5, 3.5]/[0.5, 0.95] 内随机），固定 seed 保证复现。
- 每组：`kept_for`（基于 dump v2）vs 真实 CLI `gate_chain`，逐词求对称差。
- 压线词定义：某词信号值距任一活跃阈值 <1e-6 → 列入"压线复核表"（人工核对，不算失败）。
- 判定：20 组全部对称差=0（压线词除外）→ 验收通过。

---

## 八、成功标准（打勾项）

- [ ] 现有 7 列全部由注册表驱动，dump 无硬编码列
- [ ] 模拟器随机 20 组（AND+救援）阈值 vs 真实 CLI 对称差 = 0（压线词除外，浮点复核）
- [ ] 新信号接入 = 1 文件 + 1 import；dump/模拟/仪表盘自动接管
- [ ] 改"信号消费参数"只重算受影响列（增量）；改"闸门阈值"纯查表
- [ ] regress ALL PASS（grow3 零改动）
- [ ] 仪表盘无文件实体：一次加载，任意查询毫秒级

---

## 九、明确"不做"清单（诚实边界，用户已确认：不能做到的就不做）

1. **算法本体元数据化——不做**。`cal_ent/cal_cohesion/.../solve_roles/cal_asym` 的数学（复合熵、PMI、位置偏序、图迭代、条件熵）**不可能从元数据"推导"生成**，必须人工实现。注册表只把"接线"（分派/依赖/哨兵/阈值/闸门/列/IO）声明化。
2. **"从特性自动推导信号"的魔法——不做**。不存在"输入模块特性就自动写出 cal_xxx"的机制。能做的只是：`needs_columns` 让新信号**基于已有列派生**（复用），`depends_on: ("super_index",)` 让新信号**复用共享遍历**（少写代码）。
3. **gates.py 改表驱动——不做（默认）**。gate_chain 保持手写稳定，模拟器镜像其语义。合并到单源是"远期可选"，本计划不承诺。
4. **合并 `_super.build_super_index` 与 `spe_rsr._build_super`——不做**。两套超词遍历数字必须逐字不变，合并有漂移风险。`depends_on` 只是声明，不驱动合并。
5. **改现有信号模块签名——不做**。用注册期 adapter 适配，模块文件零改动。
6. **引入第三方框架/ORM/依赖——不做**。纯 dataclass + dict + 标准库。

---

## 十、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| kept_for 与 gates.py 语义漂移（漏某个豁免/组合） | 查表结果错误 | Phase 3 随机 0 差异硬门；把 gates.py 每行映射成测试用例（对照表 §一.2） |
| ctx.super_info 缓存失效（min_super_cnt 变） | role/asym 吃到旧索引，静默错值 | `_invalidate_super` 强制进 plan() 增量路径；验收用例"改 min_super_cnt 后重算 4 列与全量一致" |
| v1 dump 缺列被误当哨兵 | AND 门/spe 查询给出错结果 | `val()` 回退哨兵 + `meta.columns` 缺失时禁查相关闸门（显式报错） |
| 增量重算把死参数/scan 参数误归增量 | 候选集漂移 | plan() 分类总表（§五.3）把 scan/语料键全归 FULL |
| 随机验收样本没覆盖到某个 extra 组合 | 漏测 | 采样空间显式含 min_role>0 / rsr_rescue>0 的组合（asym_rescue 的 extra、spe_rescue 的 extra） |
| 收益不达预期（复杂度有下限） | 白做 | 本项目已有 6 信号 7 列 8 闸门，已跨过"注册表净收益"门槛；Phase 1 后先做一次成本/收益复评 |

---

## 十一、交付顺序（若批准）

1. 落档本计划到 `调参工具/dump_解耦升级计划.md`（已在此）。
2. Phase 0：把 §一盘点整理成 `signal_bank/盘点.md`（10 分钟内）。
3. Phase 1：specs.py + 注册表（约 150 行）。
4. 每 Phase 一个提交（工作区 role-asym 分支），全部通过后再统一同步 history。
