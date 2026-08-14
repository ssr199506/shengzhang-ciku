#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tune_diff.py —— Phase 3 一阶差分坐标下降（方案 §3.3）。

借鉴反向传播的「单参数扰动 → 边际贡献」思想，不要求目标可微：

    Δscore(θᵢ) = score(θᵢ 动一步) − score(当前)

- 连续参数"动一步"：先细步（GRID_FINE.step），细步无变化再试粗步（≈4×细步，或范围/10）；
- 离散参数"动一档"：相邻取值（mean↔max、1→2→4→8、False↔True…），与连续参数同一框架。

坐标下降：每轮对 12 个参数各测一次 Δscore，动 |Δ| 最大的那一维（改进方向）；
收敛：连续 3 轮无任何改进（改进 < 0.01 = 评估分辨率）或达到轮数上限。

用法：
    python tune_diff.py --weight A          # 单套权重从 θ₀ 出发
    python tune_diff.py --weight all        # 三套权重各跑
    python tune_diff.py --weight B --start top.json   # 从随机搜索 top 配置重启
    python tune_diff.py --out DIR --max-rounds 30

输出：
    调参产物/grad_<weight>.json   轨迹（每轮 cfg + score）+ 最终 θ
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune_engine import BASE, DISCRETE, GRID_FINE, Engine, fmt

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
RESOLUTION = 0.01          # 评估分辨率（score 最小步长 ≈ 1/37 ≈ 0.027 之下取 0.01）
RSR_BASE_SPE = 0.8         # 动 rsr 时若 spe=0，先顶到 0.8（救援门仅在 spe>0 启用）

PARAMS = ["min_ent", "ent_merge_ratio", "min_cohesion", "min_indep",
          "spe_rescue", "rsr_rescue", "bind_thresh",
          "rsr_mode", "min_super_cnt", "no_punct_ent", "no_merge",
          "cohesion_max_len"]


def steps_of(param):
    """返回 (细步长, 粗步长)。"""
    if param in GRID_FINE:
        _, hi, step = GRID_FINE[param]
        coarse = max(round(step * 4, 4), round(hi / 10, 4))
        return step, coarse
    return None, None


def probes_of(param, value):
    """返回候选扰动值列表：细步 ± / 粗步 ± / 离散相邻档。"""
    if param in DISCRETE:
        lst = DISCRETE[param]
        i = lst.index(value)
        out = []
        if i > 0:
            out.append(lst[i - 1])
        if i < len(lst) - 1:
            out.append(lst[i + 1])
        return out
    step, coarse = steps_of(param)
    _, hi, _ = GRID_FINE[param]
    out = []
    for s in (step, coarse):
        if value - s >= -1e-9:
            out.append(round(value - s, 4))
        if value + s <= hi + 1e-9:
            out.append(round(value + s, 4))
    return out


def fixup(cfg):
    """一致性修正：动 rsr 需 spe 顶起；合并到 BASE 兜底。"""
    if cfg["rsr_rescue"] > 0 and cfg["spe_rescue"] <= 0:
        cfg["spe_rescue"] = RSR_BASE_SPE
    return cfg


class Diver:
    def __init__(self, weight, max_rounds=20, start=None):
        self.weight = weight
        self.max_rounds = max_rounds
        self.engine = Engine()
        self.score_cache = {}

    def _key(self, cfg):
        return tuple(sorted((k, str(v)) for k, v in cfg.items()))

    def score(self, cfg):
        k = self._key(cfg)
        if k not in self.score_cache:
            res = self.engine.evaluate(cfg, weights=(self.weight,))
            self.score_cache[k] = res["score"][self.weight]
        return self.score_cache[k]

    def run(self, start):
        cur = fixup(dict(start))
        cur_score = self.score(cur)
        trace = [{"round": 0, "cfg": dict(cur), "score": round(cur_score, 4)}]
        no_improve = 0
        print(f"[{self.weight}] 起点 score={cur_score:.4f}  cfg="
              f"me{cur['min_ent']:.2g} coh{cur['min_cohesion']:.2g} "
              f"indep{cur['min_indep']:.2g} spe{cur['spe_rescue']:.2g} "
              f"rsr{cur['rsr_rescue']:.2g}")

        for rnd in range(1, self.max_rounds + 1):
            best_delta = -1e9
            best_move = None
            for param in PARAMS:
                for pv in probes_of(param, cur[param]):
                    trial = dict(cur)
                    trial[param] = pv
                    trial = fixup(trial)
                    if trial[param] == cur[param]:
                        continue
                    s = self.score(trial)
                    delta = s - cur_score
                    if delta > best_delta:
                        best_delta = delta
                        best_move = (param, pv)
            if best_move is None or best_delta < RESOLUTION:
                no_improve += 1
                if no_improve >= 3:
                    break
                continue
            param, pv = best_move
            cur[param] = pv
            cur_score = self.score(cur)
            no_improve = 0
            trace.append({"round": rnd, "move": param, "to": pv,
                          "cfg": dict(cur), "score": round(cur_score, 4)})
            print(f"  r{rnd} 动 {param}→{pv!s:<6} score={cur_score:.4f} (Δ+{best_delta:.4f})")

        best = trace[-1]
        print(f"[{self.weight}] 收敛 最终 score={best['score']:.4f}")
        print(f"  最终 θ: " + " ".join(f"{k}={v}" for k, v in best["cfg"].items()
                                        if BASE[k] != v or k in ("min_ent", "min_cohesion", "min_indep")))
        return {"weight": self.weight, "trace": trace, "best": best["cfg"],
                "best_score": best["score"]}


def main():
    ap = argparse.ArgumentParser(description="一阶差分坐标下降")
    ap.add_argument("--weight", default="all", choices=["A", "B", "C", "all"])
    ap.add_argument("--start", default=None, help="起始配置 JSON（随机搜索 top 或手写）")
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    start = BASE
    if args.start:
        with open(args.start, encoding="utf-8") as f:
            start = {**BASE, **json.load(f)}

    weights = ["A", "B", "C"] if args.weight == "all" else [args.weight]
    os.makedirs(args.out, exist_ok=True)
    results = []
    for w in weights:
        print("=" * 60)
        res = Diver(w, args.max_rounds).run(start)
        results.append(res)
        with open(os.path.join(args.out, f"grad_{w}.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    print("=" * 60)
    for r in results:
        b = r["best"]
        print(f"[{r['weight']}] 最优 score={r['best_score']:.4f}  "
              f"me{b['min_ent']} mr{b['ent_merge_ratio']} coh{b['min_cohesion']} "
              f"indep{b['min_indep']} spe{b['spe_rescue']} rsr{b['rsr_rescue']} "
              f"bind{b['bind_thresh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
