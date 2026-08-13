# 生长词库（grow3 · 3.0-unified）

从 **CSV（title, intro）** 自动抽取中文候选词的工具链：
清洗纯 CJK → 单字 BFS 生长最大重复 → 多信号过滤 → 词频 CSV。

3.0 是一次**模块化重构**：把历史上散落各分支的「扫描 + 信号 + 闸门 + 审计」
收敛成统一管道 `grow3`，**默认参数下与历史分支产词逐字一致**（见下方回归矩阵）。
改的是工程结构，不是算法行为。

---

## 〇、速览

```
CSV(title,intro) ──► 清洗(纯CJK+标点哨兵) ──► build_corpus ──► S, wgt
                                                      │
                                                      ▼
                                              scan_once(S, wgt)
                                         一次扫描 → 统一 IR(ScanContext)
                                                      │
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
   signal_ent    signal_cohesion   signal_indep   signal_spe_rsr   (将来新信号)
   复合熵(外部)     凝固度(内部)      词本身偏序      超词结构/补集偏序   实现
   只读加列        只读加列          只读加列        只读加列        cal(w,ctx) 即可
        └──────────────┴───────────────┼───────────────┴──────────────┘
                                       ▼
                                 gate_chain(过滤+救援)
                                       ▼
                                  probe(审计 JSON)
                                       ▼
                                  词表 CSV (+ 词云)
```

**核心不变式（重构最高原则）**：默认参数下，3.0 每个配置组合必须与对应历史分支
产词逐字一致。任何一步破坏即回滚。

---

## 一、架构：管道-过滤器

```
                        ┌────────────────────────────────────┐
                        │           PipelineConfig            │
                        │  (config.py: 全部开关 + 参数旋钮)    │
                        └──────────────┬─────────────────────┘
                                       │ 驱动
  语料 CSV ──► build_corpus ──► S, wgt
                                       ▼
                        ┌────────────────────────────────────┐
                        │        scan_once(S, wgt)           │
                        │  只做 BFS 生长，产出 ScanContext：  │
                        │    cand_lst{词:位置列表}            │
                        │    cand_count{词:count}             │
                        │    charfreq / ngram_freq / pos_single│
                        └──────────────┬─────────────────────┘
                                       │ 一次扫描的产物 = 统一 IR
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
  signal_ent    signal_cohesion   signal_indep   signal_spe_rsr   (将来新信号)
  复合熵(外部)     凝固度(内部)      词本身偏序      超词结构/补集偏序   实现
  只读加列        只读加列          只读加列        只读加列        cal(w,ctx) 即可
        └──────────────┴───────────────┼───────────────┴──────────────┘
                                       ▼
                        ┌────────────────────────────────────┐
                        │         gate_chain                 │
                        │  AND 过滤门:  ent → cohesion → indep│
                        │  条件救援门:  spe_rescue / rsr_rescue│
                        └──────────────┬─────────────────────┘
                                       ▼
                        ┌────────────────────────────────────┐
                        │         probe (审计探针)            │
                        │  每级闸门: 进/出 + 差集清单 → JSON   │
                        └──────────────┬─────────────────────┘
                                       ▼
                                 词表 CSV + 词云
```

统一 IR（`grow3/ir.py`）：

```python
@dataclass
class ScanContext:
    S: str; wgt: dict; cand_lst: dict; cand_count: dict
    charfreq: dict; ngram_freq: dict; pos_single: dict; n_char: int

@dataclass
class Word:
    word: str; count: int; independent: int; binding: float
    ent: float; cohesion: float; indep: float; spe: float; rsr: float
```

**为什么安全**：扫描与信号天然可分——`cal_*(ctx)` 只读 IR 重算即与历史逐字一致，
新增信号 = 加一个 `signals/*.py` + 一个 `Word` 字段 + 一个 gate，不再改解包。

---

## 二、信号抽象模型（四/五信号）

每个信号只看词的**一个维度**，彼此正交；闸门分两类：AND 过滤链 + 条件救援门。

| 信号 | 维度 | 来源分支 | 为何保留 | 关键参数 |
|------|------|----------|----------|----------|
| 复合熵 ent | 横向**外部**邻居分布 | v1→2.1.11 | 基础：无真实邻居证据则豁免，低熵=依附寄生 | `--min-ent 0.5` |
| 凝固度 coh | 内部字间 PMI | 2.1.17 | 清「之巅/之子」式松散搭配碎片 | `--cohesion 1.5` |
| 词本身偏序 indep | 候选/位置结构复用 | 2.3.3 | 零成本清强搭配碎片(我只/聊天) | `--indep 0.05` |
| SPE 超词位置熵 | 纵向**包含**秩序 | 2.4.1 | 救援门：救回被熵误杀的纵向有序真词 | `--spe-rescue 0.8` |
| RSR 补集偏序 | 补集泛用度 | 2.4.2 | 与 SPE 取 AND，收紧救援 | `--rsr-rescue 8` |

闸门语义（非并列）：
- **AND 过滤链**：`ent → cohesion → indep`，多字候选需逐层通过（单字无内部绑定概念→放行）。
- **条件救援门**：仅从「被 AND 链滤掉」的词里捞回——`spe_rescue` 认位置多样的真构词件；
  `rsr_rescue` 与 `spe` 取 **AND**（非并列），补集泛用度高才留。
- SPE/RSR 的 `spe<0`/`rsr<0`（无合格超词）视为结构豁免，**不**参与救援（无法判位置多样）。

> **未移植（明确弃用）**：2.4.1/2.4.2 的 `spe_affix` / `rsr_affix` **词缀过滤门**——
> 历史上均因灾难性误杀被弃用（spe_affix=0.4 砍 1417 词含 大佬/网游/法师 等真标题词；
> rsr_affix=2 误杀 32 个真词）。grow3 只保留其正向成果（救援门 + RSR 辅助列），
> 不再暴露两个已证失败的过滤开关。

---

## 三、废弃实验（记录在案）

| 实验 | 区间 | 结论 |
|------|------|------|
| 位置固定度 pos-fixed | 2.1.12~2.1.16 | 与 indep/cohesion 高度重合，未纳入 golden（仅实验） |
| AMI 双信号初版 | 2.1.18 前后 | 概念验证，凝固度 PMI 吸收其思想后弃用 |
| 句法停用词表 | 2.2 立项 | 需外部词典、与「无词典纯统计」定位冲突，弃用 |
| 纯寄生阈值调参 | 2.1.x 多轮 | 被复合熵+凝固度联合门取代 |

> 凡未进入 golden 矩阵的探索，均视为「方向验证」而非「发布行为」，不保证向后兼容。

---

## 四、版本谱系

```
v1        独立出现次数判据（基础）
  └─ 复合熵(横向外部邻居) 取代「搜索栏硬规则」
2.1.11    复合熵定档（--min-ent 0.5 + --ent-merge-ratio 0.25）→ 5865  ⭐ main 基线
2.1.17    凝固度 PMI 门（--cohesion 1.5）→ 5156
2.3.3     词本身偏序 indep 联合门（--indep 0.05）→ 5149
2.4.1     SPE 纵向救援门（--spe-rescue 0.8）→ 5895
2.4.2     补集偏序 RSR（--spe-rescue 0.8 --rsr-rescue 8）→ 5889
3.0-unified  模块化重构：扫描/信号/闸门/审计分离，行为等价上述各组合
```

真值源码（金标准生成用）：`exp/legacy/grow_v211_main.py`（2.1.11 main 留档）。

---

## 五、3.0 与 main 的关系

- **默认参数完全兼容**：`grow3` 默认 `--min-ent 0.5 --ent-merge-ratio 0.25`，产词 = main 5865。
- **多了模块化**：扫描一次 → IR → 信号只读加列 → 闸门组装 → 审计；新信号即插即用。
- **根入口兼容层**：`grow.py` 是 `grow3` 的薄封装，`verify.py`/`tune_bind.py`/`probe_words.py`
  等历史工具无需改动即可运行在 grow3 上（已由暴力对拍验证）。
- **接棒 main**：Step 9 后 `3.0-unified` 与 main 行为等价，可随时 merge 到 main。

---

## 六、使用

> **语料版权**：输入语料 `corpus.csv` 为付费商用数据，**不入库**，需自备并命名为
> `corpus.csv` 置于仓库根（.gitignore 已锁死）。本仓库只含统计词表/代码，不含语料原文；
> 运行产生的词云产物含从书名提取的完整标题，同样**严禁入库**（.gitignore 已双重防护）。

```bash
# 与 2.1.11 等价（默认 → 5865；默认渲染词云，--no-cloud 关闭）
python -m grow3.cli corpus.csv --title-col 2 --intro-col -1 --ent-merge-ratio 0.25 --no-cloud

# 等价 2.3.3（→ 5149）
python -m grow3.cli corpus.csv --title-col 2 --intro-col -1 --ent-merge-ratio 0.25 \
    --no-cloud --min-ent 0.5 --cohesion 1.5 --indep 0.05

# 等价 2.4.2（→ 5889）
python -m grow3.cli corpus.csv --title-col 2 --intro-col -1 --ent-merge-ratio 0.25 \
    --no-cloud --min-ent 0.5 --spe-rescue 0.8 --rsr-rescue 8 --rsr-mode mean

# 渲染词云 + 互动词云（默认行为；--top/--maxlen 控制词数与词长过滤）
python -m grow3.cli corpus.csv --title-col 2 --intro-col -1 --out out

# 审计：输出每级闸门进/出 + 差集清单 JSON
python -m grow3.cli corpus.csv ... --audit out.json
```

参数（与历史 CLI 对齐）：`--min-ent / --cohesion / --indep / --spe-rescue /
--rsr-rescue / --rsr-mode / --min-super-cnt / --ent-merge-ratio / --title-col /
--intro-col / --no-cloud / --top / --maxlen / --audit`。

### ★ 面板最强组合（2026-08-13 联合调参）

**结论按口径分两说**（63 组合联合网格 `exp/tune_combo.py` 实测）：

**① 按金标准词集口径（keep 保留率 + filt 滤除率，score=0.5keep+0.5filt）：**
最优 = **`--min-ent 0.5 --cohesion 1.5 --indep 0.05`（不开 SPE），score 0.966 = 2.3.3 定档 5149**。
SPE 救援是**负贡献**——它把金标准明确要滤的碎片（我只/联盟之/罗之 等）捞回，filt 从 24/25 掉到 16/25。

**② 若目标是把"死在熵门的真词"救回：** 只能开 SPE，且**任何阈值都必然混碎片**——
000 真词与碎片的 spe 值完全重叠（铁证：围棋 = 联盟之 = **0.971**；庆余年 0.985 vs 罗之 0.988），
`spe` 阈值数学上切不开。按召回量取 `spe0.8`（救 10/15 但放回 9 碎片），
低副作用折中取 `spe1.0`（救 4/15：谍战/舰娘/铁血/梦幻，只多放回 2 碎片）。

| 组合 | 词数 | score | 000真词 | filt残留 |
|---|---:|---:|---:|---:|
| **coh1.5+indep0.05**（无 SPE） | 5149 | **0.966** | 0/15 | 1 |
| coh1.5+indep0.05+spe1.0 | 5173 | 0.926 | 4/15 | 3 |
| coh1.5+indep0.05+spe0.8 | 5232 | 0.786 | 10/15 | 9 |
| 仅 ent+spe0.8（2.4.1） | 5895 | — | 10/15 | 17 |

敏感性（组合态实测）：`min-ent` 0.5 稳定（0.4/0.6 无增益）；`min-super-cnt` 1/2/4 无影响；
`rsr-mode` mean/max 无差异；`rsr-rescue` 收紧丢真词不划算。`keep` 词集在所有组合均无损
（唯一"丢失"的荒古根本不在候选集）。

**工程建议**：默认用 **coh1.5 + indep0.05（5149）**——最干净且金标准口径最优；
若确要召回庆余年/康熙/首富 这类熵门误杀真词，改用 `spe0.8` 并接受碎片混入。
010 层位置独留真词（完美世界/重燃 等）所有组合均救不回（需位置固定度信号，未纳入 grow3）。
调参脚本：`exp/tune_combo.py`（63 组合网格）+ `exp/find_best_combo.py`（候选快查）。

---

## 七、回归守护

```bash
python regress.py     # 金标准 sha + 6 组合 golden 矩阵 + verify 60 组对拍
```

`exp/golden/` 是**只读**金标准（6 份 CSV + `GOLDEN_MANIFEST.md`）。回归矩阵：

| 配置 | 预期 | golden 文件 |
|---|---:|---|
| 默认(me0.5+mr0.25) | 5865 | v211_ent_5865.csv |
| +coh1.5 | 5156 | v217_cohesion_5156.csv |
| +coh1.5+indep0.05 | 5149 | v233_indep_5149.csv |
| +spe-rescue0.8 | 5895 | v241_spe_5895.csv |
| +spe-rescue0.8+rsr8 | 5889 | v242_rsr_5889.csv |

**验收红线**：任何一组合不 PASS，禁止 commit「重构完成」；先定位破坏的信号。

---

## 八、目录结构

```
grow3/            重构包
  ir.py           ScanContext / Word（统一 IR）
  scan.py         清洗 + build_corpus + 一次扫描 scan_once
  signals/        ent / cohesion / indep / spe_rsr（只读加列）
  gates.py        过滤链 + 救援门 + 审计分级
  config.py       PipelineConfig（全部旋钮）
  probe.py        AuditLog / AuditStage（JSON 审计）
  output.py       词表写出（utf-8-sig + CRLF，与 main 字节对齐）
  cli.py          统一入口
grow.py           兼容层（薄封装 grow3，历史工具免改）
verify.py         扫描逻辑暴力对拍（60 组随机语料）
regress.py        回归矩阵守护
exp/
  golden/         只读金标准 + manifest
  legacy/         grow_v211_main.py（2.1.11 真值留档）
```

---

## 九、项目纪律（防 git 事故）

1. 绝不在工作树放 `.git` 的副本；高危操作前先 commit。
2. 长命令拆分执行，避免超时中断。
3. `.git` 失效第一反应 = 查回收站，不判死刑。
4. 每完成一步 commit 一次，message 写明「等价验证：XXX=YYY」。
5. 从回收站恢复的文件若报 Permission denied / 文件「被删」，先
   `attrib -H -R <路径> /S /D` 清除 Windows 隐藏属性再操作。
