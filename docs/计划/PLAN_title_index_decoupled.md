# 计划书：补集标题索引 · 无耦合实现

日期：2026-08-14
状态：**待用户批准，批准后才动手**

---

## 〇、背景与目标

原功能（词表抽取 + 互动词云搜索框）已运行正常。新增需求：

> 无词可出的标题（候选被滤 / 孤本）不能从最终成果中"消失"——
> 搜索框要能直接搜出这些书名，补集结果排在正式结果之后。

上一版实现把逻辑挂进了核心管道（`scan.py` + `cli.py`），虽未改变原行为
（回归全绿证明），但用户判定**耦合度过高**。本计划书给出**无耦合重写**方案：
核心管道零改动，补集计算作为独立模块，只挂接输出物。

---

## 一、当前工作树审计（动手前必须厘清）

`git status` 现状：

| 文件 | 状态 | 归属 |
|---|---|---|
| `grow3/scan.py` | M | **本次会话**（新增 build_corpus_with_bounds） |
| `grow3/cli.py` | M | **本次会话**（run_pipeline 加 emit_titles） |
| `grow3/cloud.py` | M | **本次会话**（emit_interactive 透传 titles） |
| `interactive_cloud.py` | M | **本次会话**（搜索框双源检索） |
| `grow3/title_index.py` | ?? 新增 | **本次会话** |
| `调参方案_最优参数.md` | M | **历史遗留**（8-13 未提交改动，非本次会话） |
| `0.csv` / `0_books.csv` / `books_clean.txt` | ?? | 大语料产物，用户数据，不动 |

### 回滚动作（第 1 步，待批准）

```
git checkout -- grow3/scan.py grow3/cli.py grow3/cloud.py interactive_cloud.py
rm grow3/title_index.py
```

- `调参方案_最优参数.md`：**不回滚**（历史遗留的合法改动，与本次无关）。
- 三个大语料文件：**不动**（用户数据）。
- 回滚后工作树只剩历史遗留改动 + 未跟踪数据文件，本次会话痕迹清零。

---

## 二、无耦合实现设计

### 核心思路

**补集计算唯一绕不开的依赖**：要知道"每个标题产出了哪些候选词"，
必须拿到"词 → 位置 → 标题"的映射。这个映射只在扫描阶段存在。

上一版在管道内顺手复用 `ctx`（现成中间产物）→ 改管道。
无耦合版改为：**独立模块自己重扫一遍语料**（0.25s，可忽略），
从扫描产物自建映射 → 核心管道彻底零改动。

### 模块职责划分

```
┌─────────────┐    ┌─────────────────────────────┐
│ 核心管道     │    │ title_index 独立模块（新增）  │
│ (零改动)     │    │                             │
│  corpus.csv  │──►│  1. 重扫语料 → cand_lst      │
│  → 词表 CSV  │    │     (词→位置, 自建字段边界)   │
│  → 词云 JSON │    │  2. 读 title_wordfreq.csv   │
└─────────────┘    │     → kept 词集             │
                   │  3. 位置回溯 → 每标题 status  │
                   │  4. 写 complement.csv       │
                   │  5. 注入词云 JSON 的 titles  │
                   └─────────────┬───────────────┘
                                 ▼
                    ┌───────────────────────────┐
                    │ interactive_cloud.py（改） │
                    │  搜索框：先搜正式词(表1)    │
                    │        再搜补集标题(表2)   │
                    └───────────────────────────┘
```

### 新文件：`grow3/title_index.py`（独立 CLI 入口）

```bash
python -m grow3.title_index corpus.csv \
    --wordfreq out/title_wordfreq.csv \
    --cloud out/title_wordcloud.json \
    --out out \
    [--title-col 2] [--no-header]
```

流程：
1. **重扫**：读 CSV → 去重（与 cli 一致）→ clean → `build_corpus` → `scan_once`
   → 拿到 `ctx.cand_lst`（词→位置）；自建字段边界 `bounds`（位置→标题索引）。
   > 注意：这里直接用现有 `build_corpus`（不新增函数），边界在模块内自行计算。
2. **读词表**：`--wordfreq` 指定的 `title_wordfreq.csv` → kept 词集。
3. **回溯**：对每个标题，用 `bounds` 反查其候选词；候选词 ∩ kept = 保留词。
   → status：`kept`（有保留词）/ `cand_lost`（有候选全被滤）/ `lone`（无候选）。
4. **写补集**：`{prefix}_complement.csv`（title, status, cand_words）。
5. **注入词云**：读取 `title_wordcloud.json`，在 `data` 中写入 `titles` 数组，
   覆盖写回（原子写）。词云 HTML/data.js 依赖的 JSON 直接得到 titles。

### 改动文件：`interactive_cloud.py`（输出界面层，保留双源检索）

- `data` 已含 `titles`（由独立模块注入，本文件不负责计算）。
- 搜索 JS：`wordHits`（正式词，count 降序）在前，`titleHits`（补集标题）分组在后。
- 新增 `openTitle(t)` 面板：显示书名 + 状态 + 候选词。
- 样式：`.ssep` 分组分隔条 / `.st` 状态徽标 / `.dim` 辅助文字。
- **向后兼容**：`titles` 为空数组时行为与旧版完全一致（搜索框只出正式词）。

### 零改动清单（铁律）

- `grow3/scan.py` — 不动（不含本次新增函数）
- `grow3/cli.py` — 不动
- `grow3/cloud.py` — 不动
- `grow3/gates.py` / `signals/*` / `config.py` / `ir.py` / `probe.py` / `output.py` — 不动
- `verify.py` / `regress.py` / `exp/*` — 不动

---

## 三、交互方式（用户可见行为）

1. 正常运行原管道：`python -m grow3.cli corpus.csv ... --out out`（产物与改动前逐字一致）。
2. 追加一步：`python -m grow3.title_index corpus.csv --wordfreq out/title_wordfreq.csv --cloud out/title_wordcloud.json --out out`
   → 产出 `title_complement.csv` + 词云 JSON 注入 titles。
3. 打开词云 HTML：搜索框搜「铁血残明」能命中补集标题（候选被滤）；
   搜「重生」正式词在前、补集标题分组在后；点开补集项显示书名/状态/候选词。

> 可选：写一个 `run_all.bat` 把两步串起来（管道 → 独立模块），
> 双击即出完整成果。是否要写，待用户决定。

---

## 四、验证方案

| 验证项 | 方法 | 通过标准 |
|---|---|---|
| 回滚干净 | `git status` | 4 个代码文件 + title_index.py 痕迹清零 |
| 核心零改动 | 回滚后 `git diff HEAD` | 只剩历史遗留 + 未跟踪 |
| 词表不变 | `python regress.py` | ALL PASS（回归红线） |
| 补集正确 | 独立模块输出 vs 已实测基线 | complement 903 条（候选被滤 262 + 孤本 641） |
| 搜索框可用 | Edge CDP 实测 | 4 组搜索 + 面板点击通过（复用上次脚本方案） |
| 向后兼容 | titles 为空时打开词云 | 搜索框行为与旧版一致 |

---

## 五、工作量与风险

- 改动：1 个新文件（title_index.py 独立模块，约 120 行）+ 1 个输出界面文件（interactive_cloud.py）。
- 成本：每次跑补集重扫语料 ~0.25s（corpus.csv 量级）；大语料（0.csv 33MB）约数秒，可接受。
- 风险：低。核心管道零改动，回归矩阵兜底；独立模块的扫描复用现有 `scan_once`（本身已被 verify 60 组对拍验证）。

---

## 六、待用户确认

1. 回滚范围：只回滚本次 4 个代码文件 + 删除 `grow3/title_index.py`，保留调参方案改动与大语料 —— 确认？
2. 词云 JSON 注入 vs 独立输出 titles 文件：**注入 JSON**（搜索框 data 直接用）——确认？
3. 是否需要 `run_all.bat` 两步串联 —— 需要 / 不需要？
4. 批准后按「一、回滚 → 二、实现 → 四、验证 → commit」顺序执行。

---

*批准后由我在本仓库执行；每步 commit 一次，message 注明验证结果。*
