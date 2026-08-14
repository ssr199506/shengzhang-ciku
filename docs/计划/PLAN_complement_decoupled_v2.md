# 施工计划：补集功能重建（还原干净底座 + 独立补丁接入）

> 状态：**待用户批准**。批准前不执行任何写操作。
> 原则：最小改动、只改接口不动内部实现、补集与原版解耦、不在被污染的版本上动土。

## 一、目标与验收标准

1. `interactive_cloud.py` 还原到加补集之前的版本（commit `7fc0fc3`，283 行，字节级干净）。
2. 在这个干净底座上接入补集：**补集 = 独立补丁**，通过接口参数注入，**不触碰原版引擎（`_CLOUD_HEAD` / `_CLOUD_ENGINE`）一个字节**。
3. 开关 = `config.json` 的 `title_complement`，由**生成 HTML 的脚本**（`cli.py` → `cloud.py` → `interactive_cloud.py`）读取判断：
   - **OFF** → 生成的 HTML 与 `7fc0fc3` 源码生成物**逐字节相同**；
   - **ON** → 原版 HTML + 追加一段独立补丁 `<script>`，行为 = 当前增强版（补集作为特殊选中词、复用同一 `#panel`）。
4. `grow3/` 核心管道（scan/gates/signals/ir/output）零改动；`regress.py` 全绿。

## 二、现状盘点（已侦察）

| 项 | 现状 |
|---|---|
| 功能前版本 | commit `7fc0fc3`（interactive_cloud.py 283 行，无 titles/补集字样） |
| 当前 HEAD | `6be1c12`（增强版，interactive_cloud.py 348 行，补集逻辑已写进引擎） |
| 补集计算模块 | `grow3/title_index.py`（独立，保留：算 titles / 写 CSV / 注入 data.js，均已实现） |
| 调用链 | `cli.py:167` → `cloud.emit_interactive(...)` → 根 `interactive_cloud.emit_interactive(...)` |
| 开关现状 | config 已有 `title_complement`；run_all.bat 已用它控制 title_index 是否跑 |
| 待清理 | `_pre_cloud_full.py`（上次侦察落盘的临时文件）；`0.csv`/`0_books.csv`/`books_clean.txt`（散落文件，不纳入，不动） |

**关键结论**：补集功能期间对 `interactive_cloud.py` 的 5 次提交（839bd42→6be1c12）全部只改了这一个文件；`grow3/` 下除新增 `title_index.py` 外无改动。还原面 = 只有一个文件。

## 三、还原步骤（干净底座）

1. `git checkout 7fc0fc3 -- interactive_cloud.py` 还原（零人工干预，字节级干净）。
2. 删除侦察残留 `_pre_cloud_full.py`。
3. 验证：`git diff 7fc0fc3 -- interactive_cloud.py` 为空；`git diff 7fc0fc3..HEAD -- grow3/` 只应出现 `title_index.py`（新增），确认核心管道无历史污染。

> 不重写 git 历史（保留 5 个中间提交供审计），工作区还原 + 后续新增提交。

## 四、干净底座上的接入架构

**核心思路：原版引擎（底座）一字不动，补集功能以「第二段独立 `<script>`」的形式作为补丁，通过接口参数在生成时注入。**

- 补丁代码是**固定文本**，运行时读 `window.GROW_DATA.titles`（ON 时 data.js 已被 title_index 注入），**不把具体数据编进 HTML**。
- 补丁在 DOM **捕获阶段**监听搜索框 `input`（`stopImmediatePropagation` 拦截底座监听），完全接管搜索渲染：
  - 渲染 = 普通命中词平铺（同原版视觉）+ 末尾常驻「补集（未收录书名）N」特殊词条；
  - 点击补集词条 → 打开**底座同一个 `#panel`**（复用 `openPanel` / `esc` / `highlight` / 面板定位 / 拖拽 / 关闭，不新建 UI）。
- OFF 时不注入补丁 → HTML 就是原版，行为与功能前完全一致。

### 文件改动清单（全部是「接口 + 拼接」，不碰引擎）

| 文件 | 改动 | 性质 |
|---|---|---|
| `interactive_cloud.py` | ① 还原到 7fc0fc3；② `emit_interactive` / `build_cloud_html` / `build_shell_html` 接口各加 `complement_script=None` 默认参数；③ `emit_interactive` 写 HTML 前加一行：`if complement_script: html += complement_script` | 还原 + 接口 + 尾部拼接 |
| `grow3/title_index.py` | 新增一个导出：补丁 JS 常量 + 取用函数（固定代码，含补集搜索渲染 + 复用面板逻辑） | 加模块（纯新增） |
| `grow3/cloud.py` | `emit_interactive` 接口加 `title_complement=False`；内部 True 时 `from .title_index import complement_script` 并透传 | 接口透传（1~2 行） |
| `grow3/cli.py` | `cli.py:167` emit 调用点加 `title_complement=cfg.title_complement` | 接口透传（1 行） |
| `config.json` / `config.example.json` / `run_all.bat` | **保持现状**（开关已存在，链路已通） | 不改 |

### 开关链路

```
config.title_complement
  └─> cli.py 读入 cfg ──> cloud.emit_interactive(title_complement=...)   ← 生成脚本里判断
        └─> True: 从 title_index 取补丁 JS ──> interactive_cloud 追加第二段 <script>
        └─> False: complement_script=None ──> HTML = 原版（字节级）
```

补集数据侧（已有，不动）：`run_all.bat` 读开关 → True 时跑 `title_index`（重扫语料算 titles → 写 `title_complement.csv` → 注入 data.js）。

## 五、验证方案

1. **字节级验证**：OFF（`title_complement=false`）产物 HTML 与 `7fc0fc3` 源码 `build_shell_html('title')` 生成物**逐字节相等**（`==` 为 True）。
2. **行为验证（Edge CDP）**：
   - ON 空焦点 → 常驻「补集（未收录书名）903」；搜「铁血」→ 点击补集 → `#panel` 显示 `铁血残明 候选被滤 产出词：铁血`（与普通词面板同形）；搜「重生」→ 补集计数 0（保留词书名不再混入）。
   - OFF → 与原版一致：无补集词条、平铺搜索、点击开词匹配面板。
3. **回归**：`regress.py` 全绿（核心管道零改动，必过）。
4. **diff 审计**：`git diff 7fc0fc3 -- interactive_cloud.py` 只显示接口参数 + 一行拼接，无引擎改动。

## 六、提交策略

- 一次提交：还原后的 `interactive_cloud.py`（还原 + 接口 + 拼接）+ 补丁（title_index.py 新增导出）+ `grow3/cloud.py`、`grow3/cli.py` 透传。
- `调参方案_最优参数.md` 保持未提交（此前约定）；散落文件不纳入。

## 七、边界（不做的事）

- 不重写 git 历史，不删中间提交。
- 不改引擎内部逻辑、不引入运行时双逻辑守卫（此前的 `hasTitles` 方案作废）。
- 不动 scan/gates/signals/ir/output 核心管道。
- 不新建 UI 组件（面板复用底座 `#panel`），不发明新交互。
