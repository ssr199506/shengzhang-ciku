# 调参工具（复制自沙箱 生长词库_2026-08-11）

> 本目录是 2026-08-13 全量调参的**核心代码 + 使用说明 + 结果存档**。
> 原项目有继续优化的余地（尤其 175 个隐性残片 → 黑名单），以后接着改时从这里开始。
> 2026-08-14 更新：新增 role/asym 纯结构信号的全量测试矩阵与交并流程（见下文）。
> 2026-08-14 整理：目录已按功能簇分组 —— `参数搜索/`（搜索/敏感性）、`全量交并/`（交并/方案执行）、
> `signal_bank/`（信号仪表盘）；本文件为总索引，各簇内有自己的代码+数据+报告。

## 核心结论（一句话版）

- **最优配置**：`ent_merge_ratio=0.4`，其余保持默认（min_ent=0.5 / cohesion=1.5 / indep=0.05 / spe=0 / rsr=0）。
  比原默认（0.25）**白赚 236 个真词**（5385 vs 5149），碎片/隐性残片零增长。
- **SPE/RSR 救援必须关**：spe 开 0.2~0.8 碎片全中 16/16（开关式效应），rsr 是半吊子净化器，均不如关闭。
  （role/asym 实测后确认：SPE 与它们**冲突不可叠加**，`F3+spe0.8` 碎片 3→16，SPE/RSR 退役。）
- **碎片是系统盲区**：175 个隐性残片（2字词末字∈{的之是不没…}）穿过所有信号门，调参调不平，需输出层黑名单。
- mr 是**台阶函数**（离散合并批次），0.34~0.40 平台等价，碎片切换点在 mr=0.44。
- **role/asym 新增（2026-08-14）**：默认 `role_rescue=0.7 + asym_rescue=2.0`，000 层真词
  0/15→13/15、keep 无损、碎片 +3（结构性代价）。详见 `全量交并/矩阵测试说明.md` 与 `全量交并/细化交并报告.md`。
- **推荐配置已更新（2026-08-14 晚）**：高原中间点 `asym_rescue=2.60 + role_rescue=0.70 + role_max_depth=-1`
  （鲁棒优先，n=5375 / 000=13/15 / net=10），见 `全量交并/信号判定与定向调参方案.md` 决策点。

## 目录结构

```
调参工具/
├── README.md                  # 本索引
├── dump_解耦升级计划.md       # signal_bank 仪表盘升级计划（Phase 0-5）
├── signal_bank/               # 信号仪表盘包：内存信号库 + 通用模拟 + dump v2 + 增量重算
│                               （specs 注册表 / engine / dump_v2 / simulate / verify_random /
│                                plan / bank / dashboard + 各验收脚本）
├── 参数搜索/                   # 参数搜索/敏感性工具族（tune_engine 共享引擎 + 5 个工具 + 数据 + 报告）
└── 全量交并/                   # 全量交并/方案执行工具族（run_full_union + run_plan_v2 + sim_rescue +
                                # dump_signals + union + plan_v2 产物 + 报告）
```

## 参数搜索/（搜索与敏感性）

| 脚本 | 作用 | 用法（在 参数搜索/ 目录下） |
|---|---|---|
| `tune_engine.py` | 评估引擎（三套权重 score + 5 指标，含 role/asym） | `python -c "from tune_engine import Engine; e=Engine(); print(e.evaluate({}))"` |
| `sens_single.py` | 单参数敏感性粗/精跑 | `python sens_single.py` / `--param min_cohesion --lo 0 --hi 4` |
| `extreme_bound.py` | 极端边界测试（危险区） | `python extreme_bound.py` |
| `tune_diff.py` | 一阶差分坐标下降（三套权重） | `python tune_diff.py --weight A/C/all` |
| `random_search.py` | 固定 seed 随机搜索 | `python random_search.py -n 100` |
| `run_matrix.py` | **role/asym 测试矩阵**（4 层验收集打分） | `python run_matrix.py [--layer 1-4] [--fast]` |

文档：`调参方案_最优参数.md`（方法论）、`调参操作手册.md`（保姆级）、`42档深度分析.md`、
`最优参数报告.md`、`矩阵测试说明.md`、`phase0_基线.md`。
数据：`grad_A/B/C.json`（差分下降轨迹）、`random_top.json`/`random_all.csv`（随机搜索）、
`start_A/C.json`（重启种子）、`extreme_report.txt`（极端边界报告）。

## 全量交并/（交并与方案执行）

| 脚本 | 作用 | 用法（在 全量交并/ 目录下） |
|---|---|---|
| `run_full_union.py` | **role/asym 全量细化网格 × 过去版本交并**（6+2 层 68 档） | `python run_full_union.py [--layer A-H] [--skip-run]` |
| `run_plan_v2.py` | **v2 方案全量执行**（148 档，含自主深化层） | `python run_plan_v2.py [--only L1] [--skip-run]` |
| `sim_rescue.py` | 查表模拟 + 边界重扫 + 余量审计 | `python sim_rescue.py` |
| `dump_signals.py` | 信号转储（v1） | `python dump_signals.py` |
| `union.py` | 多版词表交并统计（**legacy**，被 run_full_union 取代） | `python union.py`（需各版词表在子目录） |

文档：`信号判定与定向调参方案.md`（决策点已落答案）、`全量逐档交并计划.md`、`细化交并报告.md`、`运行日志.md`。
产物：`plan_v2/`（v2 执行报告、自主深化洞察、union_summary_v2.csv、_signals/）。

## signal_bank/（dump 解耦升级，2026-08-14）

内存信号库 + 通用模拟 + 增量重算 + 仪表盘，`grow3/` 零改动、无 dump 文件依赖：

| 模块 | 作用 |
|---|---|
| `specs.py` | 信号/闸门注册表（6 信号 8 闸门全声明式） |
| `engine.py` | compute_all（全信号列/增量）+ kept_for（镜像 gates.py） |
| `dump_v2.py` | 全信号列转储（schema=2，兼容 v1） |
| `simulate.py` | 即时阈值模拟（推荐配置 → n=5375/net=10） |
| `plan.py` | 自动重跑检测 FULL/INCREMENTAL/QUERY |
| `bank.py` + `dashboard.py` | SignalBank 内存仪表盘（sweep/margin/box/surface 四视图） |

验收：`verify_plan.py` 18/18、`verify_dashboard.py` 全过、`verify_random.py` 23/23（随机 0 差异）。
计划文档：`dump_解耦升级计划.md`（本目录根）。

## 与沙箱的差异说明

- 沙箱 `调参产物/fullrun*`（13+29+7+9 版全量词表，约 8MB）**未复制**，属中间产物，
  需要时用 `全量交并/全量逐档交并计划.md` 里的命令重新生成即可。
- `union.py` 的 DIRS 列表对应沙箱目录名，重新生成词表后按需调整。
- role/asym 的全量产物 `调参产物/fullrun_role/`（68 档 + 交并报告）同样在沙箱，未复制；
  用 `全量交并/run_full_union.py` 重新生成（约 40 秒）。
- `参数搜索/` 与 `全量交并/` 各自在目录内运行；`signal_bank/` 三套验收脚本自带
  sys.path 引导，可在仓库根或 `调参工具/` 下直接运行。
