#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tune_engine.py —— 调参评估引擎（Phase 1-4 共用核心）。

设计：
- 一次 scan 复用：scan 结果按「影响 scan 的键」缓存
  (no_punct_ent, ent_merge_ratio 有效值, cohesion_max_len)，换阈值不重扫。
- 信号惰性缓存：ent/coh/indep/spe/rsr 按需计算、按键缓存。
- gate + bind 补丁 + 5 指标 + 三套权重 score。

成本模型（corpus.csv 实测）：scan_once≈0.25s，全信号≈0.1s，gate 重跑≈0。
纯阈值参数（min_ent/min_cohesion/min_indep/spe/rsr/bind）只走 gate ≈ 免费。

⚠️ bind 门说明：grow3 的 gate_chain 未实现 bind_thresh（config 里有字段但门没接上），
本引擎按 tune_bind.py 的语义补丁：binding <= bind_thresh 才保留（<1.0 才激活）。
若调参推荐 bind<1.0，需回补 grow3.gates。

⚠️ collateral 口径修正：被滤 && count>=5 && ∉FILT∪FRAG∪KEEP∪T000。
（旧口径未排除 KEEP/T000，会把「该保留却滤掉」的金标准词重复计罚。）

用法（被其它脚本 import，也可独立自检）：
    python tune_engine.py            # 跑基线 5149 配置，打印全部指标
"""
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grow3.config import PipelineConfig
from grow3.gates import gate_chain
from grow3.scan import build_corpus, clean, scan_once
from grow3.signals.ent import cal_ent
from grow3.signals.cohesion import cal_cohesion
from grow3.signals.indep import cal_indep
from grow3.signals.spe_rsr import cal_spe_rsr
from grow3.signals.role import solve_roles
from grow3.signals.asym import cal_asym

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus.csv")
TITLE_COL = 2

# ---------------- 评估集（与 exp/tune_combo.py、find_best_combo.py 对齐）----------------
KEEP = ["吞噬星空", "一人之下", "长生修仙", "万族", "斗破苍穹", "诛仙", "史记",
        "无限恐怖", "鬼灭", "苟在", "之主", "之王", "世界", "长生", "凡人", "修仙",
        "都市", "系统", "巅峰", "重生之", "人在木叶", "全职法师", "风云", "无敌",
        "直播", "网游", "神豪", "荒古", "重生", "战神", "天才", "玄幻", "末世",
        "奶爸", "神医", "纨绔", "重活"]
FILT = ["我能", "剑修", "剑客", "真不是", "真没", "你管", "我只", "联盟之",
        "星空之", "火影开", "无限之", "诸天之", "之巅", "之神", "之子", "之魂",
        "之开", "罗之", "世主", "生仙", "人在斗", "影开始", "局被", "后一", "的悠"]
TRUE_000 = ['庆余年', '康熙', '首富', '刺客', '围棋', '迪迦', '谍战', '舰娘',
            '铁血', '梦幻', '工程', '首辅', '漫画', '港片', '捡属性']
FRAGS = ['我只', '聊天', '我真', '我真不', '联盟之', '诸天之', '罗之', '我的', '这个',
         '是我', '游之', '界的', '真不', '是大', '的我', '之我', '成了', '一个']

# 三套权重（方案 §1.3）：分数越高越好，loss = 1 - score
WEIGHTS = {
    "A": {"keep": 0.35, "filt": 0.35, "recall": 0.10, "frag": 0.10, "coll": 0.10},
    "B": {"keep": 0.25, "filt": 0.25, "recall": 0.25, "frag": 0.15, "coll": 0.10},
    "C": {"keep": 0.15, "filt": 0.15, "recall": 0.45, "frag": 0.15, "coll": 0.10},
}

# 基准点 θ₀（方案 §3.1）——阈值参数开关与扫描坐标分开表示
BASE = {
    "min_ent": 0.5, "ent_merge_ratio": 0.25, "min_cohesion": 1.5,
    "min_indep": 0.05, "spe_rescue": 0.0, "rsr_rescue": 0.0,
    "bind_thresh": 1.0, "rsr_mode": "mean", "min_super_cnt": 2,
    "no_punct_ent": False, "no_merge": False, "cohesion_max_len": 8,
    # 纯结构实验信号（默认全关，不影响既有评估）
    "role_enabled": False, "role_max_depth": -1, "role_alpha": 0.85,
    "min_role": 0.0, "role_rescue": 0.0, "asym_enabled": False, "asym_rescue": 0.0,
    "min_asym": 0.0,
}

# 各参数扫描取值（coarse = 粗跑大步长；fine = 精跑细步长）。连续参数在 GRID_FINE 里
# 给「细档全集」，粗跑/精跑区间由调用方据此切片。
GRID_COARSE = {
    "min_ent":        [0.0, 0.5, 1.0, 1.5, 2.0],
    "ent_merge_ratio": [0.0, 0.25, 0.5, 0.75, 0.9],
    "min_cohesion":   [0.0, 2.0, 4.0, 6.0, 8.0, 10.0],
    "min_indep":      [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "spe_rescue":     [0.0, 0.5, 1.0, 1.5, 2.0],
    "rsr_rescue":     [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
    "bind_thresh":    [0.5, 0.7, 0.9, 1.0],
    "min_role":       [0.0, 0.3, 0.5, 0.7, 0.9],
    "role_rescue":    [0.0, 0.5, 0.7, 0.9],
    "asym_rescue":    [0.0, 1.0, 1.5, 2.0, 2.5],
    "min_asym":       [0.0, 0.5, 1.0, 1.5, 2.0],
}
# 精跑细档：数字 = 上限值，步长见名称
GRID_FINE = {
    "min_ent":         ("lin", 2.0, 0.05),     # 0.0~2.0 步长 0.05
    "ent_merge_ratio": ("lin", 0.9, 0.05),     # 0.0~0.9 步长 0.05
    "min_cohesion":    ("lin", 10.0, 0.5),     # 0.0~10.0 步长 0.5
    "min_indep":       ("lin", 1.0, 0.05),     # 0.0~1.0 步长 0.05
    "spe_rescue":      ("lin", 2.0, 0.05),
    "rsr_rescue":      ("lin", 50.0, 5.0),
    "bind_thresh":     ("lin", 1.0, 0.05),
    "min_role":        ("lin", 1.0, 0.05),
    "role_rescue":     ("lin", 1.0, 0.05),
    "asym_rescue":     ("lin", 3.0, 0.1),
    "min_asym":        ("lin", 3.0, 0.1),
}
# 离散参数取值
DISCRETE = {
    "rsr_mode": ["mean", "max"],
    "min_super_cnt": [1, 2, 4, 8],
    "no_punct_ent": [False, True],
    "no_merge": [False, True],
    "cohesion_max_len": [4, 6, 8, 12],
}

# 需重 scan 的参数（scan_once 依赖键）——成本提示用
SCAN_DEP_PARAMS = ("no_punct_ent", "ent_merge_ratio", "no_merge", "cohesion_max_len")


def fine_grid(param):
    """返回参数的细档值列表（粗精两阶段里精跑用）。"""
    kind, hi, step = GRID_FINE[param]
    n = int(round(hi / step))
    return [round(i * step, 4) for i in range(n + 1)]


class Engine:
    """一次语料加载 + scan 复用 + 信号缓存 + evaluate。"""

    def __init__(self, corpus=CORPUS, title_col=TITLE_COL):
        rows = []
        with open(corpus, encoding='utf-8-sig', newline='') as f:
            r = csv.reader(f)
            for i, row in enumerate(r):
                if not row:
                    continue
                if i == 0 and row[2].strip().lower() in {'title', '书名', '名称', 'name'}:
                    continue
                t = row[2].strip()
                if t:
                    rows.append(t)
        dedup = Counter(rows)
        self._docs_punct = [(clean(t, True), w) for t, w in dedup.items()]
        self._docs_nopunct = [(clean(t, False), w) for t, w in dedup.items()]
        self._scan_cache = {}
        self._sig_cache = {}

    # ---- 内部：scan / 信号 缓存 ----
    def _scan_key(self, cfg):
        use_punct = not bool(cfg.get("no_punct_ent", False))
        mr = 0.0 if cfg.get("no_merge", False) else cfg.get("ent_merge_ratio", 0.25)
        mlen = cfg.get("cohesion_max_len", 8)
        return (use_punct, mr, mlen)

    def scan(self, cfg):
        """取 (ctx, words)。同键复用，不重复 scan。"""
        k = self._scan_key(cfg)
        if k not in self._scan_cache:
            use_punct, mr, mlen = k
            docs = self._docs_punct if use_punct else self._docs_nopunct
            S, wgt = build_corpus(docs)
            ctx, words = scan_once(S, wgt, mr, True, mlen)
            self._scan_cache[k] = (ctx, words)
        return self._scan_cache[k]

    def _sig(self, name, cfg):
        """按需计算信号并写回 words，同键复用。"""
        key = (self._scan_key(cfg), name,
               cfg.get("ent_merge_ratio", 0.25) if name == "ent" else None,
               cfg.get("cohesion_max_len", 8) if name == "coh" else None,
               cfg.get("min_super_cnt", 2) if name in ("spe", "rsr", "role", "asym") else None,
               cfg.get("rsr_mode", "mean") if name in ("spe", "rsr") else None,
               cfg.get("role_max_depth", -1) if name == "role" else None,
               cfg.get("role_alpha", 0.85) if name == "role" else None)
        if key in self._sig_cache:
            return self._sig_cache[key]
        ctx, words = self.scan(cfg)
        if name == "ent":
            mr = 0.0 if cfg.get("no_merge", False) else cfg.get("ent_merge_ratio", 0.25)
            m = cal_ent(ctx, mr)
            for wd in words:
                wd.ent = m.get(wd.word, -1.0)
        elif name == "coh":
            m = cal_cohesion(ctx, cfg.get("cohesion_max_len", 8))
            for wd in words:
                wd.cohesion = m.get(wd.word, 0.0)
        elif name == "indep":
            m = cal_indep(ctx)
            for wd in words:
                wd.indep = m.get(wd.word, -1.0)
        elif name in ("spe", "rsr"):
            sm, rm = cal_spe_rsr(ctx, cfg.get("min_super_cnt", 2), cfg.get("rsr_mode", "mean"))
            for wd in words:
                wd.spe = sm.get(wd.word, -1.0)
                wd.rsr = rm.get(wd.word, -1.0)
        elif name == "role":
            m = solve_roles(ctx, cfg.get("role_max_depth", -1),
                            cfg.get("min_super_cnt", 2), cfg.get("role_alpha", 0.85))
            for wd in words:
                wd.role = m.get(wd.word, -1.0)
        elif name == "asym":
            m = cal_asym(ctx, cfg.get("min_super_cnt", 2))
            for wd in words:
                wd.asym = m.get(wd.word, -1.0)
        self._sig_cache[key] = True
        return True

    # ---- 对外：评估一个配置 ----
    def evaluate(self, cfg, weights=("A", "B", "C")):
        """cfg: dict（键名同 PipelineConfig）。返回全部指标 + 三套权重 score。

        指标定义（方案 §1.2，collateral 口径已修正排除金标准集）：
            keep_rate / filt_rate / recall_000 / frag_rate / collateral_norm
        """
        cfg = {**BASE, **cfg}
        _, words = self.scan(cfg)

        # 按需信号
        if cfg["min_ent"] > 0:
            self._sig("ent", cfg)
        if cfg["min_cohesion"] > 0:
            self._sig("coh", cfg)
        if cfg["min_indep"] > 0:
            self._sig("indep", cfg)
        if cfg["spe_rescue"] > 0 or cfg["rsr_rescue"] > 0:
            self._sig("spe", cfg)
        if cfg["role_enabled"] or cfg["min_role"] > 0 or cfg["role_rescue"] > 0:
            self._sig("role", cfg)
        if cfg["asym_enabled"] or cfg["asym_rescue"] > 0 or cfg["min_asym"] > 0:
            self._sig("asym", cfg)

        kept = gate_chain(words, PipelineConfig.from_dict(cfg))
        if cfg["bind_thresh"] < 1.0:
            kept = [w for w in kept if w.binding <= cfg["bind_thresh"]]

        ks = {w.word for w in kept}
        raw = {w.word for w in words}
        raw_count = {w.word: w.count for w in words}

        keep_hit = len(ks & set(KEEP))
        keep_rate = keep_hit / len(KEEP)
        filt_hit = len(ks & set(FILT))          # 残留应滤词（越低越好）
        filt_rate = (len(FILT) - filt_hit) / len(FILT)
        r000 = len(ks & set(TRUE_000))
        recall_000 = r000 / len(TRUE_000)
        frag_hit = len(ks & set(FRAGS))
        frag_rate = frag_hit / len(FRAGS)

        # collateral：被滤 && count>=5 && 不在任何金标准集（修正口径）
        golden = set(FILT) | set(FRAGS) | set(KEEP) | set(TRUE_000)
        coll = [w for w in (raw - ks)
                if raw_count[w] >= 5 and w not in golden]
        n_cand_hi = sum(1 for w in raw if raw_count[w] >= 5)
        coll_norm = len(coll) / n_cand_hi if n_cand_hi else 0.0

        res = {
            "n_kept": len(ks),
            "keep_hit": keep_hit, "keep_rate": keep_rate,
            "filt_hit": filt_hit, "filt_rate": filt_rate,
            "r000": r000, "recall_000": recall_000,
            "frag_hit": frag_hit, "frag_rate": frag_rate,
            "collateral": len(coll), "coll_norm": coll_norm,
            "n_cand_hi": n_cand_hi,
            "cfg": cfg,
            "kept": ks,
            "word_count": raw_count,
        }
        scores = {}
        for w in weights:
            W = WEIGHTS[w]
            scores[w] = (W["keep"] * keep_rate + W["filt"] * filt_rate
                         + W["recall"] * recall_000
                         - W["frag"] * frag_rate - W["coll"] * coll_norm)
        res["score"] = scores
        return res


def fmt(res):
    """一行人类可读摘要（敏感性与差分报告行）。"""
    c = res["cfg"]
    tag = (f"me{c['min_ent']:.2g} mr{c['ent_merge_ratio']:.2g} "
           f"coh{c['min_cohesion']:.2g} indep{c['min_indep']:.2g} "
           f"spe{c['spe_rescue']:.2g} rsr{c['rsr_rescue']:.2g} "
           f"role{c['min_role']:.2g}/{c['role_rescue']:.2g} "
           f"asym{c['asym_rescue']:.2g} bind{c['bind_thresh']:.2g}")
    sc = " ".join(f"{k}={res['score'][k]:.3f}" for k in res["score"])
    return (f"{res['n_kept']:>5} keep{res['keep_hit']:>2}/{len(KEEP)} "
            f"filt{res['filt_hit']:>2}/{len(FILT)} "
            f"000{res['r000']:>2}/15 frag{res['frag_hit']:>2}/18 "
            f"coll{res['collateral']:>3} | {sc}")


def main():
    eng = Engine()
    print("基线 θ₀ =", BASE)
    print("指标口径: KEEP %d / FILT %d / T000 %d / FRAG %d"
          % (len(KEEP), len(FILT), len(TRUE_000), len(FRAGS)))
    res = eng.evaluate({})
    print(fmt(res))
    print("\n明细:")
    for k in ("n_kept", "keep_rate", "filt_rate", "recall_000", "frag_rate",
              "collateral", "coll_norm", "n_cand_hi", "score"):
        print(f"  {k} = {res[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
