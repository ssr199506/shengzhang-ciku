#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_bank/verify_random.py —— kept_for 随机验收（Phase 3 硬门）。

证明：任意闸门阈值组合下，通用模拟 kept_for（基于 dump v2 信号表）与真实
grow3.cli 管道 gate_chain 输出**逐词对称差=0**（压线词除外，单列复核）。

方法：
    1. 载入 dump v2（全 7 列，scan 参数固定）。
    2. 随机 20 组闸门阈值（9 个闸门各自 0 或随机取值；固定 seed 复现）。
    3. 强制补充覆盖组：asym_rescue+min_role 组合、spe_rescue+rsr_rescue 组合、
       多门混合，确保 gates.py 全部 extra 分支被命中。
    4. 每组：kept_for（模拟）vs 真实 CLI 跑全量（gate_chain）。
    5. 压线词定义：某词信号值距任一活跃阈值 < 1e-5（覆盖 6 位舍入误差 5e-7）
       → 列入"压线复核表"，不计入失败。
    6. 判定：非压线对称差全空 → 通过。

用法：python verify_random.py [--dump PATH] [--n 20] [--seed 20260814]
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import os
import random
import subprocess
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from grow3.config import PipelineConfig
from signal_bank.engine import kept_for
from signal_bank.dump_v2 import from_json
from signal_bank.specs import ALL_COLUMNS, GATE_BY_PARAM

CORPUS = os.path.join(ROOT, "corpus.csv")
DEFAULT_DUMP = os.path.join(ROOT, "调参产物", "plan_v2", "_signals", "title_signals_v2.json")

# dump 产出的固定 scan 参数（随机组只动 9 个闸门阈值，scan 参数保持与 dump 一致）。
# 注意：所有闸门阈值必须默认 0（关闭），否则 dataclasses.replace 会保留基类默认值
# （如 min_ent=0.5），导致"覆盖组显式设 0"时模拟器与 CLI 默认不一致 → 假差异。
SCAN_CFG = PipelineConfig(
    ent_merge_ratio=0.25, no_punct_ent=False, no_merge=False,
    cohesion_max_len=8, min_super_cnt=2, rsr_mode="mean",
    role_max_depth=-1, role_alpha=0.85,
    min_ent=0.0, min_cohesion=0.0, min_indep=0.0,
    min_role=0.0, min_asym=0.0,
    asym_rescue=0.0, role_rescue=0.0, spe_rescue=0.0, rsr_rescue=0.0,
    title_col=2, intro_col=-1, no_cloud=True,
)

# 9 个闸门阈值及其随机取值区间
GATE_RANGES = {
    "min_ent": (0.3, 0.8),
    "min_cohesion": (1.0, 4.0),
    "min_indep": (0.1, 0.6),
    "min_role": (0.3, 0.95),
    "min_asym": (0.5, 3.0),
    "asym_rescue": (1.5, 3.5),
    "role_rescue": (0.5, 0.95),
    "spe_rescue": (0.5, 1.5),
    "rsr_rescue": (1.0, 50.0),
}
MARGIN = 1e-5          # 压线窗口


def random_overrides(rng):
    ov = {}
    for g, (lo, hi) in GATE_RANGES.items():
        if rng.random() < 0.5:
            ov[g] = round(rng.uniform(lo, hi), 4)
    return ov


def ensure_coverage(groups, rng):
    """补充强制覆盖组，确保 gates.py 全部 extra 分支被命中。"""
    # asym_rescue 的 extra：min_role>0 时追加 role>=min_role
    groups.append({**{g: 0 for g in GATE_RANGES},
                   "asym_rescue": 2.6, "min_role": 0.5})
    # spe_rescue 的 extra：rsr_rescue>0 时追加 rsr>=0 and rsr>=rsr_rescue
    groups.append({**{g: 0 for g in GATE_RANGES},
                   "spe_rescue": 0.9, "rsr_rescue": 8.0})
    # 多门混合：role 滤 + asym 滤 + asym 救
    groups.append({**{g: 0 for g in GATE_RANGES},
                   "min_role": 0.6, "min_asym": 1.5, "asym_rescue": 2.8})
    return groups


def cfg_to_cli(ov):
    """把闸门覆盖字典翻译成 CLI 参数。

    关键点：PipelineConfig 默认 min_ent=0.5（基线即开熵门），其余闸门默认 0。
    所以"关闭某门"必须显式传 0，否则 CLI 会按默认保留 ent>=0.5 过滤，
    与模拟器（gates 全 0）不一致。→ 所有闸门阈值一律显式发出（0 或值）。
    """
    args = [sys.executable, "-m", "grow3.cli", CORPUS,
            "--title-col", "2", "--intro-col", "-1",
            "--ent-merge-ratio", "0.25",
            "--min-super-cnt", "2", "--rsr-mode", "mean",
            "--role-max-depth", "-1", "--role-alpha", "0.85",
            "--no-cloud",
            "--min-ent", str(ov.get("min_ent", 0.0)),
            "--cohesion", str(ov.get("min_cohesion", 0.0)),
            "--indep", str(ov.get("min_indep", 0.0)),
            "--min-role", str(ov.get("min_role", 0.0)),
            "--min-asym", str(ov.get("min_asym", 0.0)),
            "--asym-rescue", str(ov.get("asym_rescue", 0.0)),
            "--role-rescue", str(ov.get("role_rescue", 0.0)),
            "--spe-rescue", str(ov.get("spe_rescue", 0.0)),
            "--rsr-rescue", str(ov.get("rsr_rescue", 0.0))]
    # 信号计算开关：仅当对应门活跃时打开（否则多余计算，但无害）
    role_active = ov.get("min_role", 0) > 0 or ov.get("role_rescue", 0) > 0
    asym_active = ov.get("min_asym", 0) > 0 or ov.get("asym_rescue", 0) > 0
    if role_active:
        args += ["--role"]
    if asym_active:
        args += ["--asym"]
    return args


def cli_kept(ov, tmp):
    args = cfg_to_cli(ov) + ["--out", tmp]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT,
                       env={**os.environ, "CODEBUDDY_SESSION_ID": "",
                            "CLAUDE_SESSION_ID": ""})
    if r.returncode != 0:
        raise RuntimeError(f"CLI 失败: {ov}\n{r.stderr.strip()[-300:]}")
    wf = os.path.join(tmp, "title_wordfreq.csv")
    kept = {}
    with open(wf, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0 or not row:
                continue
            kept[row[0]] = int(row[1])
    return set(kept)


def active_thresholds(ov):
    """返回 [(列名, 阈值)] 列表，供压线判定。"""
    out = []
    for param, gate in GATE_BY_PARAM.items():
        if ov.get(param, 0) > 0:
            out.append((gate.signal, ov[param]))
    return out


def margin_words(words, cols, ov):
    """压线词：信号值距任一活跃阈值 < MARGIN 的词。"""
    ths = active_thresholds(ov)
    if not ths:
        return set()
    res = set()
    for w in words:
        for sig, th in ths:
            v = cols.get(sig, {}).get(w, -1.0)
            if 0 <= v and abs(v - th) < MARGIN:
                res.add(w)
                break
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DEFAULT_DUMP)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260814)
    args = ap.parse_args()

    words, cols, available, schema = from_json(args.dump)
    print(f"[verify] dump schema={schema} n={len(words)} 列={sorted(available)}")

    rng = random.Random(args.seed)
    groups = [random_overrides(rng) for _ in range(args.n)]
    groups = ensure_coverage(groups, rng)
    print(f"[verify] 共 {len(groups)} 组（{args.n} 随机 + 覆盖组）")

    failed = 0
    total_margin = 0
    margin_review = Counter()          # 压线复核表：词 -> 出现次数
    with tempfile.TemporaryDirectory() as tmp:
        for i, ov in enumerate(groups):
            cfg = dataclasses.replace(SCAN_CFG, **ov)
            sim = kept_for(words, cols, cfg, available=available)
            cli = cli_kept(ov, os.path.join(tmp, f"g{i}"))
            sym = sim ^ cli
            mw = margin_words(words, cols, ov)
            real_diff = sym - mw
            if real_diff:
                failed += 1
                print(f"  [FAIL] 组{i} ov={ov} 非压线差 {len(real_diff)} 词: "
                      f"{sorted(real_diff)[:10]}")
            else:
                if mw:
                    total_margin += len(mw)
                    margin_review.update(mw)
                    shown = " ".join(sorted(mw)[:8])
                    more = f" +{len(mw)-8}词" if len(mw) > 8 else ""
                    print(f"  [PASS] 组{i} sim={len(sim)} cli={len(cli)} 对称差={len(sym)} "
                          f"(压线{len(mw)}词: {shown}{more})")
                else:
                    print(f"  [PASS] 组{i} sim={len(sim)} cli={len(cli)} 对称差={len(sym)} (clean)")

    if margin_review:
        print(f"\n[verify] 压线复核表（信号值距活跃阈值<{MARGIN}，人工核对；"
              f"不计入失败）:")
        for w, n in margin_review.most_common():
            print(f"  {w}  x{n}")

    print(f"\n[verify] 结果：{len(groups)-failed}/{len(groups)} 通过；"
          f"压线词合计 {total_margin} 次（不计入失败）")
    if failed:
        print("[verify] ❌ 存在系统性差异，须排查 kept_for")
        sys.exit(1)
    print("[verify] ✅ 全部通过：kept_for 与 gate_chain 逐词一致（压线词除外）")


if __name__ == "__main__":
    main()
