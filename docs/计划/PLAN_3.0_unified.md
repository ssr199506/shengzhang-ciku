# 3.0 统一管道重构施工方案书

> 分支名：`3.0-unified`
> 基线：`main`（2.1.11 复合熵定档版）
> 定位：**集所有分支精华之大成，未来接棒成为主分支**
> 状态：✅ 两项前置验证已通过（回归锚点全可复现、IR 共用性实测通过）

---

## 〇、为什么从 main 分出来，而不是从 2.4.2 继续

本项目所有分支（2.1.12~2.4.2）都是**在单一 grow.py 里内联信号与闸门**的演进线，各有各的取舍：

| 分支 | 精华 | 代价 | 是否进 3.0 |
|---|---|---|---|
| main / 2.1.11 | 复合熵（外部邻居） | 000 层 60 真词死于熵门 | ✅ 核心 |
| 2.1.12 punct-empty | PUNCT 视为空 | 一人之下被滤 / 评分降 | ❌ 废弃留档 |
| 2.1.13 matrix | 用户矩阵方案 | 评分 0.735 / 误伤 640+ | ❌ 废弃留档 |
| 2.1.14 indep-ratio | 独立率后置恢复 | 结论不可用 | ❌ 废弃留档 |
| 2.1.15 indep-pre | 独立率前置豁免 | 顺序无关 | ❌ 废弃留档 |
| 2.1.17/2.3.1 | **凝固度 PMI**（内部绑定） | 强搭配碎片漏网 | ✅ |
| 2.1.19/2.4.1 | **SPE 超词位置熵**（结构救援） | 位置多样真词/碎片长得一样 | ✅（只作救援门） |
| 2.3.2/2.1.18 | README 完整生命周期 | 文档 | ✅ 合并入 README |
| 2.3.3 | **indep 词本身偏序** | 词缀碎片(我的/联盟之)仍漏 | ✅（联合闸门） |
| 2.4.2 | **RSR 补集偏序** | 补集常见字陷阱，不作自动闸门 | ✅（只作辅助列/救援 AND 门） |

**从 main 分出的理由**：
1. main 是最干净的 5 字段基线，没有历史包袱；从它分叉，模块化过程不会被任何已有信号的"内联实现"绑架。
2. 所有精华都以"模块"形式**按需接入**，而不是继承某一支的取舍。
3. 未来接棒 main：3.0 的产出与 main 完全兼容（默认参数复现 5865），只是多了模块化能力。

**已完成的验证**（不必重做，施工时直接引用）：
- ✅ 回归锚点：2.3.3=5149 / 2.4.1=5895 / 2.4.2=5889 全部实测复现
- ✅ IR 共用性：从 2.3.3 扫描产物独立重算 SPE，7150 词零误差；SPE/RSR 接入救援门精确复现 5889

---

## 一、目标架构（一次扫描 · 信号只读 · 闸门链 · 面板 · 探针）

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
  signal_ent.py   signal_cohesion  signal_indep  signal_spe.rsr   (将来新信号)
  复合熵(外部)      凝固度(内部)     词本身偏序      超词结构/补集偏序  只需实现
  只读加列        只读加列         只读加列        只读加列        cal(w, ctx) 接口
        └──────────────┴───────────────┼───────────────┴──────────────┘
                                       ▼
                        ┌────────────────────────────────────┐
                        │         gate_chain.py              │
                        │  AND 过滤门:  ent → cohesion → indep│
                        │  条件救援门:  spe_rescue / rsr_rescue│
                        │  (语义: 过滤链 + 带捞回的救援)       │
                        └──────────────┬─────────────────────┘
                                       ▼
                        ┌────────────────────────────────────┐
                        │         probe.py (审计探针)          │
                        │  每级闸门记录: 进/出词数 + 差集清单    │
                        │  → pipeline_audit.log (JSON)        │
                        └──────────────┬─────────────────────┘
                                       ▼
                                 词表 CSV + 词云
```

**核心不变式（重构的最高原则）**：
> 默认参数下，3.0 的每条配置组合必须与对应历史分支产词**逐字一致**。
> 改的是工程结构，不是算法行为。任何一步破坏了这个不变式，立刻回滚该步。

---

## 二、统一 IR 定义（Step 2 落地）

```python
@dataclass
class ScanContext:
    S: str                          # 语料字符串（含 SEP/PUNCT 哨兵）
    wgt: dict                       # 位置 -> 权重
    cand_lst: dict                  # 词 -> 出现位置列表  (indep 需要)
    cand_count: dict                # 词 -> 加权 count   (SPE/RSR 需要)
    charfreq: dict                  # 字 -> 频次
    ngram_freq: dict                # n-gram -> 频次      (凝固度需要)
    pos_single: dict                # 单字 -> 位置列表    (BFS 种子)

# 信号模块统一接口：cal(word, ctx) -> float（或 -1.0 表示 N/A/豁免）
# 候选词行（命名结构，替代 7 字段元组）：
@dataclass
class Word:
    word: str
    count: int
    independent: int
    binding: float
    ent: float       # 复合熵
    cohesion: float  # 凝固度
    indep: float     # 词本身偏序
    spe: float       # 超词位置熵
    rsr: float       # 补集偏序
    # 后续新信号直接加字段，不再改解包
```

**为什么这是安全的**：Step 2 已验证——SPE 从 2.3.3 扫描产物（cand_count）重算零误差，说明**扫描与信号天然可分**，IR 定义正确。

---

## 三、分步施工（每步含 目标 / 施工要点 / 注意事项 / 验收 / 回滚）

### Step 0：冻结金标准（先锁死"对的答案"）

**目标**：把历史版本的正确产出存为只读基准，后续重构用它比对，杜绝"用新探针验证新代码"的循环论证。

**施工要点**：
1. 建目录 `exp/golden/`，放 5 份基准 CSV：
   - `v211_ent.csv`（main，me0.5+mr0.25）→ 5865 词
   - `v217_cohesion.csv`（2.1.17，+coh1.5）→ 5156 词
   - `v233_indep.csv`（2.3.3，+indep0.05）→ 5149 词
   - `v241_spe.csv`（2.4.1，+spe-rescue0.8）→ 5895 词
   - `v242_rsr.csv`（2.4.2，+rsr-rescue8）→ 5889 词
2. 生成方法：用各分支 grow.py 的 `scan_and_grow` 直接 dump 词表（不带闸门）+ 分别记录闸门后词表。**两份都要存**（带/不带闸门）。
3. 对每份文件做 `sha256`，把哈希写进 `exp/golden/GOLDEN_MANIFEST.md`。

**注意事项**：
- 只读：`chmod 444` 或明确注释"禁止修改"。
- 不要用当前工作树生成，必须用 `git show <分支>:grow.py` 提取的版本生成，确保是历史真值。
- intro 管线同 title 管线各存一份（如果后续要支持）。

**验收**：`sha256 -c GOLDEN_MANIFEST.md` 全部通过；5 份词表行数 = 5865/5156/5149/5895/5889。

**回滚**：不需要回滚（只新增文件）。

---

### Step 1：从 main 开分支 + 搭包结构

**目标**：干净的 3.0 分支起点。

**施工要点**：
1. `git checkout main && git checkout -b 3.0-unified`
2. 建立包结构：
   ```
   grow3/
     __init__.py
     scan.py          # build_corpus + scan_once（Step 3 拆分）
     ir.py            # ScanContext / Word 定义
     signals/
       __init__.py
       ent.py         # 复合熵
       cohesion.py    # 凝固度
       indep.py       # 词本身偏序
       spe_rsr.py     # SPE + RSR（同一超词遍历）
     gates.py         # 闸门链 + 救援门
     config.py        # PipelineConfig + CLI 解析
     probe.py         # 审计探针
     cli.py           # 入口
   ```
3. 保留原 `grow.py` 不动（作为行为参照物，重构完成后删除或归档）。

**注意事项**：
- 此时 `grow3/` 里先放空壳 + `ir.py`，不要急着写逻辑。
- **绝对不要**在本分支 stash / 跨分支带未提交改动切换（本项目血的教训）。要切分支先 commit 或放弃。

**验收**：`python -c "import grow3.ir"` 无报错；`git status` 干净。

**回滚**：`git checkout main && git branch -D 3.0-unified`（尚未提交任何东西时直接删分支）。

---

### Step 2：实现 IR 与扫描器（纯拆分，行为零变化）

**目标**：把 main 的 `scan_and_grow` 从"扫描 + 复合熵内联"拆成 `scan_once`（只产出 IR）+ `signals/ent.py`（只读计算）。

**施工要点**：
1. 先把 main 版 `scan_and_grow` 原样拷进 `grow3/scan.py` 的 `scan_once`，**暂时保留内联的复合熵**，同时把 `cand_lst` 收集进 IR。
2. 写 `ir.py` 的 `ScanContext` / `Word`。
3. 写 `signals/ent.py`：把 main 里复合熵的 `right_dist/left_dist/_entropy_from_vals` 逻辑独立成函数，签名 `cal_ent(ctx) -> {word: ent}`。
4. `cli.py` 先用最简参数（me/mr），跑通 title 管线，产出词表。

**注意事项**：
- **这一步的目标是"能跑"不是"拆完"**——scan_once 里暂时内联复合熵也没关系，先保证 pipeline 通。
- ent 计算依赖的 `l_groups/groups` 等中间量**不要**塞进 IR（那是词级临时量，不是全局中间结构）。IR 只放跨信号共享的东西（位置/字频/超词）。
- 保持 `cand_lst[w] = lst` 与 main 一致（main 没有这个收集，是 2.3.3 加的，这里提前加上，便于后续 indep）。

**验收**：
- 默认参数（me0.5+mr0.25）产词 = **5865**，与 golden/v211_ent.csv 逐行一致（用 diff 比对 word 列）。
- `verify.py` 60 组随机语料全过。

**回滚**：`git revert` 本步 commit，或 `git reset --hard <上一步commit>`（本步无未提交 WIP）。

---

### Step 3：接入凝固度信号（等价 2.1.17）

**目标**：新增 `signals/cohesion.py`，产 `Word.cohesion`，并实现凝固度闸门。

**施工要点**：
1. 从 2.3.3 分支提取凝固度算法（`ngram_freq` 已在 IR 里？若没有，在 scan_once 里补收集）。
2. `cal_cohesion(ctx) -> {word: coh}`，规则：
   - `len<2` 或 `len>cohesion_max_len(8)` → 0.0（N/A 放行）
   - 否则取所有切分点最小 PMI：`log2(c_w * N_char / (cl * cr))`
3. `gates.py` 实现 `cohesion_gate(threshold)`：`len<2 或 coh>=threshold` 放行。
4. CLI 加 `--cohesion 1.5`。

**注意事项**：
- 凝固度依赖 `N_char`（去重字符数）——在 build_corpus 阶段就算好存 IR。
- **不要**把 2.1.17 的过滤逻辑写在信号里；信号只算值，过滤归闸门。

**验收**：`--cohesion 1.5`（me0.5+mr0.25）产词 = **5156**，与 golden/v217_cohesion.csv 一致。

**回滚**：同 Step 2。

---

### Step 4：接入 indep 信号（等价 2.3.3）

**目标**：新增 `signals/indep.py`，产 `Word.indep`，并把凝固度门升级为**联合闸门**（coh AND indep）。

**施工要点**：
1. 从 2.3.3 提取 indep 算法：
   - 建 `pos_start`（位置 → 候选词倒排）
   - 对每个超词 s 的每次出现，标记内部子候选被覆盖（`covered_occ` 去重）
   - `indep = (count_w - covered) / count_w`
2. `gates.py` 联合闸门：`ok_coh AND ok_ind`（`min_cohesion<=0 或 coh>=th`）AND（`min_indep<=0 或 indep>=th`）。
3. CLI 加 `--indep 0.05`。

**注意事项**：
- 覆盖判定要**完全照抄** 2.3.3 的去重逻辑（`key=(sub,q)`），否则数字对不上。
- 超词阈值 `indep_super_min` 保持默认 1。

**验收**：`--cohesion 1.5 --indep 0.05` 产词 = **5149**；删掉的 7 词 = {界的/游之/真不/我只/我真不/我真/是大}；000 层误杀 = 0。

**回滚**：同 Step 2。

---

### Step 5：接入 SPE/RSR 信号（等价 2.4.1 / 2.4.2）

**目标**：新增 `signals/spe_rsr.py`（一次超词遍历同时算 SPE + RSR），产 `Word.spe` / `Word.rsr`，实现**救援门**。

**施工要点**：
1. 超词遍历（已验证可从 IR 复算零误差）：
   ```python
   # 对每个超词 s（count>=2, len>=3），遍历所有子串 sub（len>=2）
   #   spe_super[sub] 位置桶累加（前缀0/中缀1/后缀2）
   #   rsr_info[sub].append((left, right, cnt_s))
   #   contain_cnt[补集].add(s)
   ```
2. `cal_spe_rsr(ctx) -> ({word: spe}, {word: rsr})`。
3. `gates.py` 救援门（语义不同于过滤门！）：
   - **spe_rescue**：熵门滤掉的词，若 `spe>=th`（默认 0.8）→ 捞回。
   - **rsr_rescue**：与 spe_rescue **取 AND**：`spe>=0.8 且 rsr>=8` → 捞回。
4. CLI 加 `--spe-rescue 0.8` / `--rsr-rescue 8` / `--rsr-mode mean`。

**注意事项**：
- **救援门是"条件闸门"，依赖过滤前后中间态**——在 gate_chain 里实现顺序：先跑 AND 过滤链，再对"被滤集"跑救援。**绝不能**把救援写成与过滤并列的独立闸门（会破坏语义）。
- rsr 默认 `mode='mean'`（2.4.2 定档），`max` 模式留作参数但默认 mean。
- RSR 明确**不作自动过滤闸门**（2.4.2 结论），只作救援 AND 条件 / 辅助列。

**验收**：
- `--spe-rescue 0.8` 产词 = **5895**（2.4.1）
- `--spe-rescue 0.8 --rsr-rescue 8` 产词 = **5889**（2.4.2）
- 救援捞回词数与 golden 一致（2.4.1 捞 30，2.4.2 捞 24）

**回滚**：同 Step 2。

---

### Step 6：面板抽象（config + 全部旋钮/开关）

**目标**：所有信号开关与参数收敛到一个 `PipelineConfig`，CLI 一键统辖；任意勾选组合可跑。

**施工要点**：
1. `config.py` 定义 `PipelineConfig`（dataclass），字段：
   ```
   # 扫描
   ent_merge_ratio, ent_punct_exempt
   # 过滤门（AND 链）
   min_ent, min_cohesion, min_indep
   # 救援门（条件）
   spe_rescue, rsr_rescue, rsr_mode, min_super_cnt
   # 输出
   top_n, maxlen, no_cloud, bind_thresh
   ```
2. CLI：`--min-ent / --cohesion / --indep / --spe-rescue / --rsr-rescue` 全部映射到 config。
3. `cli.py` 按 config 组装 gate_chain（过滤链 + 救援）。
4. 输出 audit：每条配置跑完，打印 `候选N → 熵门a → 凝固度b → indep c → 救援d → 最终E`。

**注意事项**：
- 面板**不**引入企业级抽象（不加依赖注入/插件热加载），就是"一份 config + 按声明组装"。
- 参数名与历史分支 CLI 完全对齐（`--min-ent` 不是 `--ent`），避免记忆负担。

**验收**：分别用 config 复现 5 个 golden 组合，全部精确命中；`--help` 列出全部参数。

**回滚**：同 Step 2。

---

### Step 7：审计探针（"哪个环节滤掉了什么"）

**目标**：每级闸门记录 进/出 数 + 差集，输出 JSON 审计日志。

**施工要点**：
1. `probe.py` 定义 `AuditLog`：
   ```json
   {
     "config": {...},
     "stages": [
       {"gate": "ent", "before": 7150, "after": 5865,
        "removed": ["词1", ...], "removed_count": 1285},
       {"gate": "cohesion", "before": 5865, "after": 5156, ...},
       ...
       {"gate": "spe_rescue", "before": 5156, "after": 5186,
        "rescued": ["词X", ...], "rescued_count": 30}
     ],
     "final_count": 5186
   }
   ```
2. `cli.py` 加 `--audit <path>` 选项，默认打印摘要到 stderr。

**注意事项**：
- 差集列表**全量**输出（本词库最大 7150 词，JSON 完全存得下），方便 grep 单个词在哪级被滤。
- audit 必须包含**救援门**的 `rescued` 列表（这是 2.4.x 的关键信息，历史上靠手数）。

**验收**：跑 `--audit out.json`，用 python json.load 验证结构；抽查 `我只` 的滤除链完整。

**回滚**：同 Step 2。

---

### Step 8：回归矩阵自动化（守护脚本）

**目标**：一条命令验证全部历史配置组合 + verify 60 组。

**施工要点**：
1. `regress.py`：
   ```
   读取 exp/golden/GOLDEN_MANIFEST.md
   对每个 golden 组合: 跑 pipeline → 对比 word 集 → 输出 PASS/FAIL + diff 行数
   额外: 跑 verify.py 60 组
   汇总: "N/M PASS"
   ```
2. 对比逻辑：word 集合 `set(词表)` 精确相等（顺序无关，词云顺序不影响）。

**注意事项**：
- **金标准必须是只读的**，regress 永远不覆盖它。
- diff 报告要输出到 stdout + 保存 `exp/regress_report.txt`。

**验收**：`python regress.py` 全部 PASS（5/5 golden + verify 60 组）。

**回滚**：同 Step 2。

---

### Step 9：清理与文档（接棒主分支前）

**目标**：删除旧 grow.py（或归档到 exp/legacy/），写 README，准备成为 main。

**施工要点**：
1. 旧 `grow.py` 移到 `exp/legacy/grow_v211_main.py`（留档，不删源码）。
2. README.md 重写：
   - 架构图（第二节的图）
   - 每个信号：定义 / 来源分支 / 为何保留 / 参数
   - 每个废弃实验：为何废弃（2.1.12~2.1.15 记录在案）
   - 3.0 与 main 的关系：默认参数完全兼容，多了模块化
3. 更新 `verify.py` 指向 `grow3`。

**注意事项**：
- README 保留历史谱系章节（git 里本来就有，3.0 只新增"模块化重构"章节）。
- 确认 `interactive_cloud.py` 等依赖仍在包内可导入。

**验收**：README 结构完整；`python cli.py --help` / `python regress.py` 全绿；从干净 clone 能直接跑通。

**回滚**：commit 前确认无未提交改动；commit 后可 revert。

---

## 四、回归矩阵总表（Step 8 的目标状态）

| 配置组合 | 预期产词 | 对应 golden | 验证命令 |
|---|---:|---|---|
| 默认（me0.5+mr0.25） | 5865 | v211_ent.csv | `cli.py ... ` |
| +coh1.5 | 5156 | v217_cohesion.csv | `--cohesion 1.5` |
| +coh1.5+indep0.05 | 5149 | v233_indep.csv | `--indep 0.05` |
| +spe-rescue0.8 | 5895 | v241_spe.csv | `--spe-rescue 0.8` |
| +spe-rescue0.8+rsr8 | 5889 | v242_rsr.csv | `--rsr-rescue 8` |

**验收红线**：任何一组合不 PASS，即禁止 commit "重构完成"；先 git bisect 定位到破坏信号。

---

## 五、项目纪律（防再次踩 git 事故）

1. **绝不在工作树放 `.git` 的副本**（`.git.bak` 等），也绝不 stash 含 `.git` 副本的目录。
2. **高危操作（切分支、stash）前先 commit**；要保存 WIP 用临时分支 commit，不用 `git stash -u`。
3. 长命令（如全量扫描）**拆分执行**，避免超时中断。
4. **`.git` 失效第一反应 = 查回收站**（`recycle_v3.ps1`），不判死刑。
5. 每完成一步，commit 一次，commit message 写明"等价验证：XXX=YYY"。

---

## 六、3.0 的未来（接棒 main 的路线）

1. **第一步接棒**：Step 9 完成后，`3.0-unified` 与 main 行为等价（默认参数 5865 一致），可随时 merge 到 main。
2. **新增信号路径**：未来第 6 信号 = 写一个 `cal_xxx(ctx)` + 一个 gate，注册进 config——**不再需要改任何解包/下游**（这是 2.3.3 那次改 60+ 行的痛点）。
3. **000 层救援（2.3.4 方向）**：ent 门救援是天然的下一刀，3.0 的救援门框架直接支持。
4. **补集偏序深化（2.4.2 遗留）**：解决"补集常见字陷阱"后，rsr 可升级为自动闸门。

---

*本方案基于：✅ 回归锚点全复现（Step 0 之前必须再做一遍确认）✅ IR 共用性实测通过（Step 2 引用）✅ 用户已备份 `.git.7z`（安全网）*
