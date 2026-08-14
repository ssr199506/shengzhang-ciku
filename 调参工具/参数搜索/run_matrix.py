#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_matrix.py —— 纯结构信号（role / asym）测试矩阵自动化执行。

结合 tune_engine 评估引擎机械跑 4 层矩阵（单信号标定 / 两两联合 /
完整管道 / 正交表），输出逐格 CSV + 自动汇总报告。

用法：
    python run_matrix.py               # 跑全部 4 层（默认）
    python run_matrix.py --layer 2     # 只跑层 2
    python run_matrix.py --out DIR     # 输出目录（默认 调参产物/matrix）
    python run_matrix.py --fast        # role 用 max_depth=1(U2) 代替不动点，提速

层定义（详见同目录《矩阵测试说明.md》）：
    层1 单信号标定：role 过滤 / asym 救援 / spe 救援对照 各自阈值扫描
    层2 两两联合：ent×asym 互补链、role×coh 2D 决策面、ent×role 正交双滤、
                   asym×role 救援+净化、asym×coh 内外对称、role_rescue vs spe_rescue
    层3 完整管道 A~E
    层4 正交表：ent × coh × min_role × asym_rescue 全 16 组合

产物：
    matrix/layer1.csv ... layer4.csv   每格一行（指标 + 三套 score + 关键词存活）
    matrix/report.md                   自动汇总报告（最佳格 + 关键对比）
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune_engine import Engine, fmt

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrix")

# 层1/2 隔离基线：关闭 coh/indep/spe/rsr，让 role/asym 的效应显性
ISO = {"min_cohesion": 0.0, "min_indep": 0.0, "spe_rescue": 0.0, "rsr_rescue": 0.0}

# 关键词存活追踪（决策面/净化是否奏效的直观证据）
TARGETS = ["首富", "庆余年", "康熙", "明月", "铁血", "完美世界", "神诡世界",
           "重生", "世界", "历史", "天道",
           "在三国", "家的", "聊天", "联盟之", "我的", "我终", "真没", "无限之"]


# ---------------------------------------------------------------- 各层配置
def L1():
    """单信号标定。"""
    cfgs = [("base-ent", {**ISO})]
    cfgs += [(f"role滤@{r}", {**ISO, "role_enabled": True, "min_role": r})
             for r in [0.3, 0.5, 0.7, 0.9]]
    cfgs += [(f"asym救@{a}", {**ISO, "asym_enabled": True, "asym_rescue": a})
             for a in [1.0, 1.5, 2.0, 2.5]]
    cfgs += [(f"spe救对照@{s}", {**ISO, "spe_rescue": s})
             for s in [0.5, 0.8, 1.0]]
    return cfgs


def L2():
    """两两联合。"""
    cfgs = []
    # ent × asym 互补链（ent 越严，asym 救得越多/越脏？）
    cfgs += [(f"ent{e:.1g}xasym{a:.1g}", {**ISO, "min_ent": e,
             "asym_enabled": True, "asym_rescue": a})
             for e in [0.4, 0.5, 0.6] for a in [1.5, 2.0, 2.5]]
    # role × coh 2D 决策面（内紧∧外主）
    cfgs += [(f"role{r:.1g}xcoh{c:.1g}", {**ISO, "role_enabled": True,
             "min_role": r, "min_cohesion": c})
             for r in [0.3, 0.5, 0.7] for c in [1.0, 1.5]]
    # ent × role 正交双滤
    cfgs += [(f"ent{e:.1g}xrole{r:.1g}", {**ISO, "min_ent": e,
             "role_enabled": True, "min_role": r})
             for e in [0.4, 0.5, 0.6] for r in [0.3, 0.5, 0.7]]
    # asym × role 救援+净化（min_role 同时作过滤门与救援净化门槛）
    cfgs += [(f"asym2.0净role{r:.1g}", {**ISO, "asym_enabled": True,
             "asym_rescue": 2.0, "role_enabled": True, "min_role": r})
             for r in [0.3, 0.5]]
    # asym × coh 内外对称（救援集用凝固度净化）
    cfgs += [(f"asym2.0净coh{c:.1g}", {**ISO, "asym_enabled": True,
             "asym_rescue": 2.0, "min_cohesion": c})
             for c in [1.0, 1.5]]
    # role_rescue vs spe_rescue 取代对比
    cfgs += [(f"role救@{r}", {**ISO, "role_enabled": True, "role_rescue": r})
             for r in [0.7, 0.9]]
    cfgs += [("spe救对照0.8", {**ISO, "spe_rescue": 0.8})]
    return cfgs


def L3():
    """完整管道 A~E。"""
    E = ("E-ent-only", {**ISO, "min_ent": 0.5})
    A = ("A-ent+asym救+role净", {**ISO, "min_ent": 0.5, "asym_enabled": True,
         "asym_rescue": 2.0, "role_enabled": True, "min_role": 0.5})
    B = ("B-ent+spe救+role净", {**ISO, "min_ent": 0.5, "spe_rescue": 0.8,
         "role_enabled": True, "min_role": 0.5})
    C = ("C-ent+role救", {**ISO, "min_ent": 0.5, "role_enabled": True,
         "role_rescue": 0.7})
    D = ("D-ent+coh1.0+role滤+asym救", {**ISO, "min_ent": 0.5, "min_cohesion": 1.0,
         "role_enabled": True, "min_role": 0.5,
         "asym_enabled": True, "asym_rescue": 2.0})
    return [E, A, B, C, D]


def L4():
    """正交表：ent × coh × min_role × asym_rescue 全 16 组合。"""
    cfgs = []
    for e in [0.4, 0.5]:
        for c in [0.0, 1.0]:
            for r in [0.0, 0.5]:
                for a in [0.0, 2.0]:
                    cfg = {**ISO, "min_ent": e, "min_cohesion": c}
                    if r > 0:
                        cfg["role_enabled"] = True
                        cfg["min_role"] = r
                    if a > 0:
                        cfg["asym_enabled"] = True
                        cfg["asym_rescue"] = a
                    cfgs.append((f"ent{e:.1g}coh{c:.1g}role{r:.1g}asym{a:.1g}", cfg))
    return cfgs


LAYERS = {"1": L1, "2": L2, "3": L3, "4": L4}


# ---------------------------------------------------------------- 执行
def _kept_targets(kept_set):
    return [t for t in TARGETS if t in kept_set]


def run_layer(eng, layer_name, cfgs, out_path, fast):
    rows = []
    for label, cfg in cfgs:
        cfg = dict(cfg)
        if fast and any(k in cfg for k in ("role_enabled", "min_role", "role_rescue")):
            cfg.setdefault("role_max_depth", 1)   # U2 代替不动点
        res = eng.evaluate(cfg)
        row = {
            "case": label,
            "n_kept": res["n_kept"],
            "keep": res["keep_hit"], "filt": res["filt_hit"],
            "r000": res["r000"], "frag": res["frag_hit"],
            "coll": res["collateral"],
            "score_A": round(res["score"]["A"], 4),
            "score_B": round(res["score"]["B"], 4),
            "score_C": round(res["score"]["C"], 4),
            "kept_targets": "+".join(_kept_targets(res["kept"])),
        }
        rows.append(row)
        print(f"  {label:<24} {fmt(res)}")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


def best_row(rows, key):
    return max(rows, key=lambda r: r[key])


def main():
    ap = argparse.ArgumentParser(description="role/asym 测试矩阵自动化")
    ap.add_argument("--layer", default=None, choices=["1", "2", "3", "4"],
                    help="只跑某一层；缺省跑全部")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录")
    ap.add_argument("--fast", action="store_true", help="role 用 U2(max_depth=1) 代替不动点")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    eng = Engine()
    layers = [args.layer] if args.layer else list(LAYERS.keys())

    all_rows = {}
    for lname in layers:
        print(f"\n===== 层 {lname} =====")
        rows = run_layer(eng, lname, LAYERS[lname](),
                         os.path.join(args.out, f"layer{lname}.csv"), args.fast)
        all_rows[lname] = rows

    # ---- 自动汇总报告 ----
    rep = ["# role/asym 测试矩阵报告",
           "",
           f"运行: 层 {' '.join(layers)} | role 模式: {'U2(max_depth=1)' if args.fast else '不动点'}",
           "评估口径: 同 tune_engine（keep/filt/000/frag/coll，分数越高越好）",
           ""]
    for lname in layers:
        rows = all_rows[lname]
        rep += [f"## 层 {lname}",
                "",
                f"共 {len(rows)} 格。三套权重最佳格：",
                "",
                "| 权重 | 最佳格 | score | n_kept | keep | filt | 000 | frag | coll |",
                "|---|---|---|---|---|---|---|---|---|"]
        for wk in ("A", "B", "C"):
            b = best_row(rows, f"score_{wk}")
            rep.append(f"| {wk} | {b['case']} | {b[f'score_{wk}']:.4f} | "
                       f"{b['n_kept']} | {b['keep']} | {b['filt']} | "
                       f"{b['r000']} | {b['frag']} | {b['coll']} |")
        rep += ["", "**关键词存活**（层 2/3 决策面与净化的直观证据）：", ""]
        for row in rows:
            if row["kept_targets"]:
                rep.append(f"- `{row['case']}` → 存活: {row['kept_targets']}")
        rep += [""]

    # 关键对比（层 1：role滤 vs asym救 vs spe救 的 r000 与 filt）
    if "1" in all_rows:
        rows = all_rows["1"]
        rep += ["## 层 1 关键对比（谁在捞回 000 层、谁在漏 filt）", "",
                "| 案例 | n_kept | filt | 000 | frag | coll | score_A |", "|---|---|---|---|---|---|---|"]
        for name in ("base-ent", "role滤@0.5", "asym救@2.0", "spe救对照@0.8"):
            for r in rows:
                if r["case"] == name:
                    rep.append(f"| {name} | {r['n_kept']} | {r['filt']} | {r['r000']} | "
                               f"{r['frag']} | {r['coll']} | {r['score_A']} |")
        rep += [""]
    # 层 3 管道对比
    if "3" in all_rows:
        rep += ["## 层 3 管道 A~E 对比", "",
                "| 管道 | n_kept | filt | 000 | frag | coll | score_A |", "|---|---|---|---|---|---|---|"]
        for r in all_rows["3"]:
            rep.append(f"| {r['case']} | {r['n_kept']} | {r['filt']} | {r['r000']} | "
                       f"{r['frag']} | {r['coll']} | {r['score_A']} |")
        rep += [""]

    rep_path = os.path.join(args.out, "report.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print(f"\n报告: {rep_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
