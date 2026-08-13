"""grow3 —— 3.0 统一管道重构包。

架构（一次扫描 · 信号只读 · 闸门链 · 面板 · 探针）：
    语料 CSV → build_corpus → S, wgt
              → scan_once(S, wgt) → ScanContext（统一 IR）
              → signals/* 只读加列（ent / cohesion / indep / spe_rsr）
              → gates 过滤链 + 救援门
              → probe 审计探针
              → 词表 CSV + 词云

核心不变式：默认参数下，3.0 每条配置组合必须与对应历史分支产词逐字一致。
改的是工程结构，不是算法行为。
"""
__version__ = "3.0.0-unified"
