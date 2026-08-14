"""grow3.cli —— 3.0 统一管道入口。Step 2 接通 scan + ent，Step 6 接通全部信号与 gate 组装。

用法（与历史分支 CLI 对齐）：
    python -m grow3.cli <输入.csv> [--min-ent 0.5] [--cohesion 1.5]
                              [--indep 0.05] [--spe-rescue 0.8]
                              [--rsr-rescue 8] [--rsr-mode mean]
                              [--title-col 2] [--intro-col -1]
                              [--ent-merge-ratio 0.25] [--no-cloud]
                              [--audit out.json]

默认参数须复现 main 5865（--min-ent 0.5 + --ent-merge-ratio 0.25）。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from typing import List, Tuple

from .config import PipelineConfig
from .gates import gate_chain
from .ir import Word
from .output import write_word_csv
from .probe import AuditLog, AuditStage
from .scan import build_corpus, clean, scan_once
from .signals.ent import cal_ent
from .signals.cohesion import cal_cohesion
from .signals.indep import cal_indep
from .signals.spe_rsr import cal_spe_rsr
from .signals.role import solve_roles
from .signals.asym import cal_asym

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（默认 config.json 所在）


def load_csv(path, has_header):
    """读取 CSV，返回 [(title, intro), ...]。与 main 行为一致。"""
    rows = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and has_header:
                continue
            title = r[0].strip()
            intro = r[1].strip() if len(r) > 1 else ''
            rows.append((title, intro))
    return rows


def detect_header(row, title_col, intro_col):
    """表头启发：title_col 位置为已知表头词，或前两列均为纯 ASCII 标识。"""
    TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}
    if title_col < len(row) and row[title_col].strip().lower() in TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="grow3", description="生长词库 3.0 统一管道")
    ap.add_argument("input", nargs="?", default=None,
                    help="输入 CSV（title,intro）；缺省时从配置文件 input 读取")
    ap.add_argument("--config", default=None, help="配置文件路径（JSON）；缺省时自动读仓库根 config.json")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--min-ent", type=float, default=None, help="复合熵阈值")
    ap.add_argument("--cohesion", type=float, default=None, help="凝固度阈值")
    ap.add_argument("--indep", type=float, default=None, help="词本身偏序阈值")
    ap.add_argument("--spe-rescue", type=float, default=None, help="SPE 救援阈值")
    ap.add_argument("--rsr-rescue", type=float, default=None, help="RSR 救援阈值")
    ap.add_argument("--rsr-mode", choices=["mean", "max"], default=None)
    ap.add_argument("--min-super-cnt", type=int, default=None, help="超词最小出现次数（SPE/RSR 遍历门槛）")
    ap.add_argument("--ent-merge-ratio", type=float, default=None)
    ap.add_argument("--title-col", type=int, default=None)
    ap.add_argument("--intro-col", type=int, default=None)
    ap.add_argument("--no-header", action="store_true", default=None)
    ap.add_argument("--no-dedup", action="store_true", default=None)
    ap.add_argument("--bind", type=float, default=None, help="前后集中度闸门（默认 1.0=关）")
    ap.add_argument("--no-punct-ent", action="store_true", default=None, help="关闭标点感知熵")
    ap.add_argument("--no-merge", action="store_true", default=None, help="关闭合并模式（ratio=0）")
    ap.add_argument("--no-cloud", action="store_true", default=None,
                    help="跳过词云渲染（默认渲染；词云产物含书名，请勿入库）")
    ap.add_argument("--top", type=int, default=None, help="词云词数上限")
    ap.add_argument("--maxlen", type=int, default=None, help="词云最大词长过滤（0=不限）")
    ap.add_argument("--standalone", action="store_true", default=None,
                    help="互动词云单文件内联 HTML（无需外部 data.js）")
    ap.add_argument("--title-complement", action="store_true", default=None,
                    help="开启补集（未收录书名）功能：注入补集 UI 补丁（依赖独立模块 title_index 注入数据）")
    ap.add_argument("--role", action="store_true", default=None,
                    help="计算 role 列（偏序图角色迭代，含 U2 退化；实验信号）")
    ap.add_argument("--role-max-depth", type=int, default=None,
                    help="role 迭代深度：1=U2，N=迭代 N 帧，-1=不动点")
    ap.add_argument("--role-alpha", type=float, default=None, help="role 阻尼系数")
    ap.add_argument("--min-role", type=float, default=None, help="role 主干度闸门阈值（<=0 关闭）")
    ap.add_argument("--role-rescue", type=float, default=None,
                    help="role 主干度救援阈值（<=0 关闭；从被滤集捞回 role>=thresh 的候选）")
    ap.add_argument("--asym", action="store_true", default=None,
                    help="计算 asym 列（条件熵不对称性；实验信号）")
    ap.add_argument("--asym-rescue", type=float, default=None,
                    help="asym 救援阈值（<=0 关闭；从被滤集捞回 asym>=thresh 的候选）")
    ap.add_argument("--min-asym", type=float, default=None,
                    help="asym 过滤门阈值（<=0 关闭；asym>=thresh 才留，低值=碎片）")
    ap.add_argument("--audit", default=None, help="审计日志输出路径")
    return ap


# argparse dest -> PipelineConfig 字段名（CLI 参数覆盖配置文件的映射）
_ARG_TO_CFG = {
    "min_ent": "min_ent",
    "cohesion": "min_cohesion",
    "indep": "min_indep",
    "spe_rescue": "spe_rescue",
    "rsr_rescue": "rsr_rescue",
    "rsr_mode": "rsr_mode",
    "min_super_cnt": "min_super_cnt",
    "ent_merge_ratio": "ent_merge_ratio",
    "title_col": "title_col",
    "intro_col": "intro_col",
    "bind": "bind_thresh",
    "no_punct_ent": "no_punct_ent",
    "no_merge": "no_merge",
    "no_cloud": "no_cloud",
    "title_complement": "title_complement",
    "role": "role_enabled",
    "role_max_depth": "role_max_depth",
    "role_alpha": "role_alpha",
    "min_role": "min_role",
    "role_rescue": "role_rescue",
    "asym": "asym_enabled",
    "asym_rescue": "asym_rescue",
    "min_asym": "min_asym",
    "top": "top_n",
    "maxlen": "maxlen",
    "standalone": "standalone",
}
# cli 级键：不进 PipelineConfig，由 main 单独处理
_CLI_KEYS = {"input", "out", "audit", "no_header", "no_dedup"}


def load_json_config(path):
    """读取 JSON 配置文件为 dict。"""
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(prefix, docs, raw_texts, cfg, out_dir, audit=None):
    """对一条管线（title/intro）跑完整管道，返回最终 Word 列表。

    audit 非空时记录每级闸门进/出/差集（Step 7 审计探针）。
    """
    use_punct = not cfg.no_punct_ent
    ent_merge_ratio = 0.0 if cfg.no_merge else cfg.ent_merge_ratio
    S, wgt = build_corpus([(clean(t, use_punct), w) for t, w in docs])
    if not S:
        return []
    ctx, words = scan_once(S, wgt, ent_merge_ratio, True, cfg.cohesion_max_len)
    ent_map = cal_ent(ctx, ent_merge_ratio)
    for wd in words:
        wd.ent = ent_map.get(wd.word, -1.0)
    if cfg.min_cohesion > 0:
        coh_map = cal_cohesion(ctx, cfg.cohesion_max_len)
        for wd in words:
            wd.cohesion = coh_map.get(wd.word, 0.0)
    if cfg.min_indep > 0:
        indep_map = cal_indep(ctx)
        for wd in words:
            wd.indep = indep_map.get(wd.word, -1.0)
    if cfg.spe_rescue > 0 or cfg.rsr_rescue > 0:
        spe_map, rsr_map = cal_spe_rsr(ctx, cfg.min_super_cnt, cfg.rsr_mode)
        for wd in words:
            wd.spe = spe_map.get(wd.word, -1.0)
            wd.rsr = rsr_map.get(wd.word, -1.0)
    if cfg.role_enabled or cfg.min_role > 0 or cfg.role_rescue > 0:
        role_map = solve_roles(ctx, cfg.role_max_depth, cfg.min_super_cnt, cfg.role_alpha)
        for wd in words:
            wd.role = role_map.get(wd.word, -1.0)
    if cfg.asym_enabled or cfg.asym_rescue > 0 or cfg.min_asym > 0:
        asym_map = cal_asym(ctx, cfg.min_super_cnt)
        for wd in words:
            wd.asym = asym_map.get(wd.word, -1.0)
    if audit is not None:
        audit.config = cfg.to_dict()
        audit.stages.append(_stage_header(prefix, len(words)))
    kept = gate_chain(words, cfg, audit)
    if audit is not None:
        audit.final_count = len(kept)
    extra_cols = []
    if cfg.role_enabled or cfg.min_role > 0 or cfg.role_rescue > 0:
        extra_cols.append("role")
    if cfg.asym_enabled or cfg.asym_rescue > 0 or cfg.min_asym > 0:
        extra_cols.append("asym")
    write_word_csv(kept, os.path.join(out_dir, f'{prefix}_wordfreq.csv'),
                   extra_cols=extra_cols or None)

    # ---- 词云渲染（显示层，失败不致命；产物含完整书名，.gitignore 已锁死防入库）----
    if not cfg.no_cloud:
        top_n = cfg.top_n or 200
        try:
            from .cloud import emit_interactive, render_cloud
            layout = render_cloud(os.path.join(out_dir, f'{prefix}_wordcloud.png'),
                                  kept, top_n, cfg.maxlen)
            try:
                emit_interactive(prefix, out_dir, kept, raw_texts, top_n,
                                 cfg.maxlen, layout, standalone=cfg.standalone,
                                 title_complement=cfg.title_complement)
            except Exception as e:
                print(f'[{prefix}] 互动词云跳过: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[{prefix}] 词云渲染跳过: {e}', file=sys.stderr)

    return kept


def _stage_header(prefix: str, n: int) -> AuditStage:
    """审计首条：候选总数（扫描产物），方便串起整条链。"""
    return AuditStage(f"scan({prefix})", n, n, removed=[])


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # ---- 配置合并：CLI 显式参数 > 配置文件(--config) > PipelineConfig 默认 ----
    # 注意：不自动读 config.json——避免污染精确控制 CLI 的回归/调参脚本；
    # 双击场景由 run.bat 显式传 --config config.json。
    cfg_path = args.config
    cfg_map = load_json_config(cfg_path) if cfg_path else {}
    for dest, key in _ARG_TO_CFG.items():
        val = getattr(args, dest)
        if val is not None:
            cfg_map[key] = val
    # cli 级键（不进 PipelineConfig）：先全部 pop 出，再与 CLI 参数合并
    cfg_input = cfg_map.pop("input", None)
    cfg_out = cfg_map.pop("out", None)
    cfg_audit = cfg_map.pop("audit", None)
    cfg_no_header = cfg_map.pop("no_header", False)
    cfg_no_dedup = cfg_map.pop("no_dedup", False)
    input_path = args.input or cfg_input
    out_dir = args.out or cfg_out or "."
    audit_path = args.audit or cfg_audit
    no_header = bool(cfg_no_header)
    no_dedup = bool(cfg_no_dedup)
    if not input_path:
        parser.error("未指定输入 CSV：请提供位置参数，或配置文件 input 字段")
    cfg = PipelineConfig.from_dict(cfg_map)

    os.makedirs(out_dir, exist_ok=True)

    with open(input_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        raw_rows = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not no_header and detect_header(r, cfg.title_col, cfg.intro_col):
                continue
            title = r[cfg.title_col].strip() if 0 <= cfg.title_col < len(r) else ''
            intro = r[cfg.intro_col].strip() if 0 <= cfg.intro_col < len(r) else ''
            raw_rows.append((title, intro))

    if no_dedup:
        dedup = [(t, i, 1) for t, i in raw_rows]
    else:
        dedup = [(t, i, w) for (t, i), w in Counter(raw_rows).items()]

    title_docs = [(t, w) for t, i, w in dedup if t]
    intro_docs = [(i, w) for t, i, w in dedup if i]
    title_raw = [t for t, i, w in dedup if t]
    intro_raw = [i for t, i, w in dedup if i]

    audit = AuditLog() if audit_path else None
    kt = run_pipeline('title', title_docs, title_raw, cfg, out_dir, audit)
    if cfg.intro_col >= 0 and intro_docs:
        run_pipeline('intro', intro_docs, intro_raw, cfg, out_dir)

    if audit_path:
        adir = os.path.dirname(audit_path)
        if adir:
            os.makedirs(adir, exist_ok=True)
        audit.dump(audit_path)
        print(f'[grow3] 审计日志已写出: {audit_path}', file=sys.stderr)
        # 链路摘要：候选N → 各门 → 最终E
        chain = [f"候选{audit.stages[0].before}"]
        for s in audit.stages[1:]:
            if s.removed:
                chain.append(f"{s.gate}→{s.after}(删{len(s.removed)})")
            elif s.rescued:
                chain.append(f"{s.gate}→{s.after}(救{len(s.rescued)})")
            else:
                chain.append(f"{s.gate}→{s.after}")
        print(f'[grow3] 链路: {" → ".join(chain)} → 最终{audit.final_count}', file=sys.stderr)

    print(f'[grow3] 默认闸门({cfg.gate_summary()}) → 标题词 {len(kt)} 个', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
