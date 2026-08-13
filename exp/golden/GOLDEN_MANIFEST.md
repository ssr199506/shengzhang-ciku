# GOLDEN MANIFEST — 冻结金标准（3.0-unified 回归基线）

> **只读 · 禁改。** 本目录是 3.0-unified 重构的"对的答案"锁。任何一组合不 PASS，
> 即禁止 commit "重构完成"；先 `git bisect` 定位到破坏信号。
>
> 生成方法：用 `git show <分支>:grow.py` 取出各历史真值版本（绝不用当前工作树），
> 各自以"标准语料调用"跑出词表，复制其 `title_wordfreq.csv` 为本目录文件。
> 语料：`PAID_CORPUS.csv`
> 标准调用公共参数：`--title-col 2 --intro-col -1 --ent-merge-ratio 0.25 --no-cloud`
> （书名在 col 2；无简介；合并比 0.25；跳过词云）。

## 基准清单

| 文件 | 行数(词数) | 来源分支 | 产词含义 | 生成命令(后缀公共参数) |
|------|-----------|----------|----------|------------------------|
| `v211_raw_7150.csv` | 7150 | `main` | 熵门前原始候选集（independent≥1, len≥2，未施加任何信号闸门） | `main:grow.py` 不加 `--min-ent`（默认 0.0，不过滤） |
| `v211_ent_5865.csv` | 5865 | `main` | 复合熵闸门基线（me0.5） | `main:grow.py --min-ent 0.5` |
| `v217_cohesion_5156.csv` | 5156 | `2.1.17-cohesion` | 复合熵 + 凝固度(PMI)闸门 | `2.1.17:grow.py --min-ent 0.5 --cohesion 1.5` |
| `v233_indep_5149.csv` | 5149 | `2.3.3-cohesion-poset` | 凝固度 + 词本身偏序 indep 联合闸门 | `2.3.3:grow.py --min-ent 0.5 --cohesion 1.5 --indep 0.05` |
| `v241_spe_5895.csv` | 5895 | `2.4.1-spe` | 复合熵基线 + SPE 纵向救援门（从 main 出，无 cohesion/indep） | `2.4.1:grow.py --min-ent 0.5 --spe-rescue 0.8` |
| `v242_rsr_5889.csv` | 5889 | `2.4.2-poset` | + RSR 补集偏序救援门（spe 与 rsr 取 AND，非并列闸门） | `2.4.2:grow.py --min-ent 0.5 --spe-rescue 0.8 --rsr-rescue 8 --rsr-mode mean` |

## sha256 校验和

```
4ca44cdf06c65bc5788c835b7693c4efc22be482cf5a1cbe25aca1766b97ee4a  v211_raw_7150.csv
f4df50f212ad330cefd7a604a47353efa1f334f53c2d0da351fcab716b2654b1  v211_ent_5865.csv
1e41c165e18a63d5985168ee36dc647c2c127aba25ed1036eaebbe82db2f058f  v217_cohesion_5156.csv
0530fde5bf2b46481ccbae523b9d232e736ec89dabc30c4d87ddb373cd5eae72  v233_indep_5149.csv
1f949768e6c61fc14234fa5ce64d5967d7b608faa22c23e7fd954933ff16e6d7  v241_spe_5895.csv
ef412d65f62d2a026c35d754021331a8882433d5aa616c1271f68797466b2cab  v242_rsr_5889.csv
```

## 验收红线

- `sha256sum -c <(提取上表)` 全过。
- 5 份目标词表行数达标：5865 / 5156 / 5149 / 5895 / 5889（raw 7150 为对照）。
- Step 8 回归矩阵：grow3 复现上述全部组合须逐行精确命中（word 列集合相等 + 计数一致）。

## 关键不变量（供重构核对）

- 原始候选集恒为 **7150**（所有分支共用同一扫描/清洗，与闸门参数无关）。
- 误杀/救援差集：
  - coh1.5 误杀 5865→5156（减 709；凝固度门对短高频寄生词更狠）。
  - indep0.05 联合门 5156→5149（再减 7：界的/游之/真不/我只/我真不/我真/是大；000 层误杀=0）。
  - spe-rescue0.8 救援 5865→5895（捞回 30，从熵门误杀中救回纵向有序词）。
  - rsr-rescue8 救援 5895→5889（与 spe 取 AND 后再捞 24）。
- 信号层次（非并列）：
  - 横向外部：复合熵（me）
  - 横向边界：位置固定度（pos-fixed，2.1.16 未纳入 golden，仅实验）
  - 内部紧密度：凝固度 PMI（coh）
  - 纵向包含秩序：SPE（超词包含子词的纵向有序度）
  - 词本身偏序：indep（候选/位置结构零成本复用）
  - 补集偏序：RSR（仅在 spe 救援成立时作 AND 收紧）
