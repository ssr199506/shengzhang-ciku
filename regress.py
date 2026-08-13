#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regress.py —— 3.0-unified 回归矩阵守护脚本（Step 8）。

一条命令验证：
  1) 6 个 golden 配置组合（grow3 vs exp/golden/*）逐词精确命中
     （word 集合相等 + 计数一致，顺序无关）
  2) 金标准文件 sha256 完整性（防金标准被意外改动）
  3) verify_grow3 扫描逻辑 60 组随机对拍（扫描/独立判定不变式）

输出 PASS/FAIL + diff 行数；报告同时打印 stdout 并保存 exp/regress_report.txt。
金标准只读，本脚本绝不会覆盖它。

用法：python regress.py
"""
import csv
import hashlib
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(ROOT, "exp", "golden")
CORPUS = os.path.join(ROOT, "PAID_CORPUS.csv")
COMMON = ["--title-col", "2", "--intro-col", "-1",
          "--ent-merge-ratio", "0.25", "--no-cloud"]

# (name, 额外 CLI 参数, golden 文件名)
MATRIX = [
    ("raw",      ["--min-ent", "0.0"],
        "v211_raw_7150.csv"),
    ("ent",      ["--min-ent", "0.5"],
        "v211_ent_5865.csv"),
    ("cohesion", ["--min-ent", "0.5", "--cohesion", "1.5"],
        "v217_cohesion_5156.csv"),
    ("indep",    ["--min-ent", "0.5", "--cohesion", "1.5", "--indep", "0.05"],
        "v233_indep_5149.csv"),
    ("spe",      ["--min-ent", "0.5", "--spe-rescue", "0.8"],
        "v241_spe_5895.csv"),
    ("rsr",      ["--min-ent", "0.5", "--spe-rescue", "0.8", "--rsr-rescue", "8", "--rsr-mode", "mean"],
        "v242_rsr_5889.csv"),
]

# 金标准 sha256（来自 exp/golden/GOLDEN_MANIFEST.md，只读基线）
EXPECTED_SHA = {
    "v211_raw_7150.csv":   "4ca44cdf06c65bc5788c835b7693c4efc22be482cf5a1cbe25aca1766b97ee4a",
    "v211_ent_5865.csv":   "f4df50f212ad330cefd7a604a47353efa1f334f53c2d0da351fcab716b2654b1",
    "v217_cohesion_5156.csv": "1e41c165e18a63d5985168ee36dc647c2c127aba25ed1036eaebbe82db2f058f",
    "v233_indep_5149.csv": "0530fde5bf2b46481ccbae523b9d232e736ec89dabc30c4d87ddb373cd5eae72",
    "v241_spe_5895.csv":   "1f949768e6c61fc14234fa5ce64d5967d7b608faa22c23e7fd954933ff16e6d7",
    "v242_rsr_5889.csv":   "ef412d65f62d2a026c35d754021331a8882433d5aa616c1271f68797466b2cab",
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_words(path):
    d = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if row:
                d[row[0]] = int(row[1])
    return d


def _run_golden(name, args, golden_file, report):
    """跑一个 golden 组合，对比词集，返回 (passed, line)。"""
    gold_path = os.path.join(GOLDEN_DIR, golden_file)
    with tempfile.TemporaryDirectory() as td:
        cmd = [sys.executable, "-m", "grow3.cli", CORPUS] + COMMON + args + ["--out", td]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            line = f"  [FAIL] {name}: 进程错误 rc={r.returncode}\n{r.stderr[-500:]}"
            report.append(line)
            return False, line
        got = _load_words(os.path.join(td, "title_wordfreq.csv"))
    exp = _load_words(gold_path)
    extra = set(got) - set(exp)
    missing = set(exp) - set(got)
    cnt_mismatch = sum(1 for w in (set(got) & set(exp)) if got[w] != exp[w])
    passed = (len(got) == len(exp)) and not extra and not missing and cnt_mismatch == 0
    if passed:
        line = f"  [PASS] {name}: grow3={len(got)} golden={len(exp)} 完全一致"
    else:
        line = (f"  [FAIL] {name}: grow3={len(got)} golden={len(exp)} "
                f"extra={len(extra)} missing={len(missing)} count_mismatch={cnt_mismatch}")
    report.append(line)
    return passed, line


def _check_sha(report):
    """校验金标准 sha256 完整性，返回 (n_ok, n_total)。"""
    ok = 0
    total = 0
    for fn, exp_sha in EXPECTED_SHA.items():
        total += 1
        p = os.path.join(GOLDEN_DIR, fn)
        if not os.path.exists(p):
            report.append(f"  [FAIL] sha {fn}: 文件缺失")
            continue
        actual = _sha256(p)
        if actual == exp_sha:
            ok += 1
            report.append(f"  [PASS] sha {fn}")
        else:
            report.append(f"  [FAIL] sha {fn}: {actual} != {exp_sha}")
    return ok, total


def main():
    report = []
    report.append("=" * 64)
    report.append("3.0-unified 回归矩阵")
    report.append("=" * 64)

    # 1) 金标准完整性
    report.append("\n[1/3] 金标准 sha256 完整性")
    sha_ok, sha_total = _check_sha(report)

    # 2) golden 配置矩阵
    report.append("\n[2/3] golden 配置矩阵（grow3 vs exp/golden）")
    g_ok = 0
    for name, args, gf in MATRIX:
        passed, _ = _run_golden(name, args, gf, report)
        if passed:
            g_ok += 1
    g_total = len(MATRIX)

    # 3) 扫描逻辑 60 组对拍（verify.py 经 grow.py 兼容层调用 grow3）
    report.append("\n[3/3] verify 扫描逻辑 60 组对拍（grow.py 兼容层 → grow3）")
    try:
        r = subprocess.run([sys.executable, "verify.py", "30"],
                           cwd=ROOT, capture_output=True, text=True)
        verify_ok = (r.returncode == 0)
        for line in r.stdout.strip().splitlines():
            report.append("  " + line)
        if not verify_ok:
            report.append("  " + r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "  [FAIL] verify_grow3 非零退出")
    except Exception as e:  # noqa
        verify_ok = False
        report.append(f"  [FAIL] verify_grow3 异常: {e}")

    # 汇总
    report.append("\n" + "=" * 64)
    report.append(f"汇总: golden {g_ok}/{g_total}  sha {sha_ok}/{sha_total}  "
                  f"scan_verify {'PASS' if verify_ok else 'FAIL'}")
    all_pass = (g_ok == g_total and sha_ok == sha_total and verify_ok)
    report.append("结果: " + ("ALL PASS ✅" if all_pass else "FAILURE ❌"))
    report.append("=" * 64)

    text = "\n".join(report) + "\n"
    print(text)
    out_path = os.path.join(ROOT, "exp", "regress_report.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[regress] 报告已保存: {out_path}", file=sys.stderr)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
