# 调参工具（复制自沙箱 生长词库_2026-08-11）

> 本目录是 2026-08-13 全量调参的**核心代码 + 使用说明 + 结果存档**。
> 原项目有继续优化的余地（尤其 175 个隐性残片 → 黑名单），以后接着改时从这里开始。
> 2026-08-14 更新：新增 role/asym 纯结构信号的全量测试矩阵与交并流程（见下文）。

## 核心结论（一句话版）

- **最优配置**：`ent_merge_ratio=0.4`，其余保持默认（min_ent=0.5 / cohesion=1.5 / indep=0.05 / spe=0 / rsr=0）。
  比原默认（0.25）**白赚 236 个真词**（5385 vs 5149），碎片/隐性残片零增长。
- **SPE/RSR 救援必须关**：spe 开 0.2~0.8 碎片全中 16/16（开关式效应），rsr 是半吊子净化器，均不如关闭。
  （role/asym 实测后确认：SPE 与它们**冲突不可叠加**，`F3+spe0.8` 碎片 3→16，SPE/RSR 退役。）
- **碎片是系统盲区**：175 个隐性残片（2字词末字∈{的之是不没…}）穿过所有信号门，调参调不平，需输出层黑名单。
- mr 是**台阶函数**（离散合并批次），0.34~0.40 平台等价，碎片切换点在 mr=0.44。
- **role/asym 新增（2026-08-14）**：默认 `role_rescue=0.7 + asym_rescue=2.0`，000 层真词
  0/15→13/15、keep 无损、碎片 +3（结构性代价）。详见 `矩阵测试说明.md` 与 `交并报告.md`。

## 脚本（全部可独立运行，依赖本项目根 grow3/ + corpus.csv）

| 脚本 | 作用 | 用法 |
|---|---|---|
| `tune_engine.py` | 评估引擎（三套权重 score + 5 指标，含 role/asym） | `python -c "from tune_engine import Engine; e=Engine(); print(e.evaluate({}))"` |
| `sens_single.py` | 单参数敏感性粗/精跑 | `python sens_single.py` / `--param min_cohesion --lo 0 --hi 4` |
| `extreme_bound.py` | 极端边界测试（危险区） | `python extreme_bound.py` |
| `tune_diff.py` | 一阶差分坐标下降（三套权重） | `python tune_diff.py --weight A/C/all` |
| `random_search.py` | 固定 seed 随机搜索 | `python random_search.py -n 100` |
| `union.py` | 多版词表交并统计 | `python union.py`（需各版词表在子目录） |
| `run_matrix.py` | **role/asym 测试矩阵**（4 层验收集打分） | `python run_matrix.py [--layer 1-4] [--fast]` |
| `run_full_union.py` | **role/asym 全量细化网格 × 过去版本交并**（6+2 层 68 档） | `python run_full_union.py [--layer A-H] [--skip-run]` |

## 文档（从计划到结论）

| 文档 | 内容 |
|---|---|
| `调参方案_最优参数.md` | 最初的反向传播启发调参方案（目标/评估/方法学） |
| `调参操作手册.md` | 保姆级分步操作手册（给免费模型照抄） |
| `全量逐档交并计划.md` | 全量逐档控制变量 + 交并计划 |
| `42档深度分析.md` | **最终深度分析**（帕累托前沿/mr0.4 支配 base/敏感性排序/spe 成色） |
| `细化交并报告.md` | 42 档细化曲线（严格单调无窄峰 + spe 开关式） |
| `最优参数报告.md` | 三套权重最优 θ + 提升表 + 诚实结论 |
| `矩阵测试说明.md` | **role/asym 测试矩阵 + 全量交并流程的完整说明**（层定义/口径/结论） |
| `运行日志.md` | 每步真实输出记录 |
| `phase0_基线.md` | 基线 5149 词记录 |

## 结果数据

- `grad_A/B/C.json`：三套权重差分坐标下降的最终 θ 与轨迹
- `random_top.json` / `random_all.csv`：随机搜索 top5 与全部样本
- `start_A/C.json`：随机 top 种子（重启验证用）
- `extreme_report.txt`：极端边界危险区报告
- `矩阵测试说明.md`：role/asym 全量交并报告（`调参产物/fullrun_role/交并报告.md` 的说明入口）

## 与沙箱的差异说明

- 沙箱 `调参产物/fullrun*`（13+29+7+9 版全量词表，约 8MB）**未复制**，属中间产物，
  需要时用 `全量逐档交并计划.md` 里的命令重新生成即可。
- `union.py` 的 DIRS 列表对应沙箱目录名，重新生成词表后按需调整。
- role/asym 的全量产物 `调参产物/fullrun_role/`（68 档 + 交并报告）同样在沙箱，未复制；
  用 `run_full_union.py` 重新生成（约 40 秒）。
