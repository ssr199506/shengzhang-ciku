"""
cmp_242.py — 2.4.2 补集偏序(RSR)版 与 现有重大版本 对比
=================================================================
对齐 final_cmp.py 的口径，额外加入 RSR 专项诊断（救援/过滤两条路线）。

版本：
  v211       = exp/v211_grow.py (纯熵基线, =main)
  v216       = exp/v216_grow.py (位置固定度豁免)
  v217       = exp/v217_grow.py (凝固度过滤)
  2.4.1      = 当前 grow.py, --spe-rescue=0.8  (SPE 救援定档)
  2.4.2      = 当前 grow.py, --spe-rescue=0.8 --rsr-rescue=8  (SPE+RSR 救援)
  (abandon)  = 当前 grow.py, --rsr-affix=2  (补集偏序词缀过滤, 已弃用)

关键结论（数据驱动，详见 stdout）：
  - RSR 救援(AND 门)仅边际改善：噪声 18→14，但丢 2 个 000 标签；
    终极陷阱「真没/我终」因补集含超常见字(我/的) rsr>180，无法被滤。
  - RSR 词缀过滤(affix)是灾难：删 363 词含 ~100 真标题词(指南/历史/天道/刘备…)，弃用。
  - RSR 定位：可信度辅助列(rsr)，不作自动闸门。
"""
import importlib.util, csv, os, sys

ROOT = "."
sys.path.insert(0, ROOT)
EVAL = r"SANDBOX\eval_versions"
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5
ENT_MR = 0.25
OUT = os.path.join(ROOT, "exp", "v242_out")
os.makedirs(OUT, exist_ok=True)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(docs):
    S, wgt = G.build_corpus([(G.clean(t, True), w) for t, w in docs if t])
    return S, wgt


def load_docs():
    global G
    G = load_module("g", os.path.join(ROOT, "grow.py"))  # 当前=2.4.x
    docs = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if not r:
                continue
            if i == 0 and G.detect_header(r, 2, 1):
                continue
            t = r[2].strip() if len(r) > 2 else ""
            if t:
                docs.append((t, 1))
    return docs


def cand_tuple(mod, S, wgt, spe_rescue=0.0, rsr_rescue=0.0, rsr_affix=0.0):
    c, _ = mod.scan_and_grow(S, wgt, ENT_MR, True)
    # 模拟 process_corpus 闸门（熵门 + SPE救援 + RSR救援 + RSR-affix）
    kept = []
    for x in c:
        ent = x[4]
        if ent < 0 or ent >= MIN_ENT:
            kept.append(x)
        elif spe_rescue > 0:
            ok = x[5] >= spe_rescue
            if rsr_rescue > 0 and ok:
                ok = x[6] >= rsr_rescue
            if ok:
                kept.append(x)
    if rsr_affix > 0:
        weld = 0.3
        kept = [x for x in kept
                if not (x[5] >= 0 and x[5] <= weld and x[6] >= 0 and x[6] <= rsr_affix)]
    return c, kept


def labels():
    true000 = set()
    with open(os.path.join(EVAL, "mistake_book.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["class"] == "000" and r.get("217_coh") not in (None, "", "None") and float(r["217_coh"]) >= 6.0:
                true000.add(r["word"])
    clean_true = {"首富", "谍战", "康熙", "围棋", "捡属性", "梦幻", "庆余年",
                  "舰娘", "铁血", "神诡", "明月", "唐门", "贴身"}
    return true000, clean_true


def main():
    global G
    docs = load_docs()
    S, wgt = build(docs)

    # 基准三版本
    v211 = load_module("v211", os.path.join(ROOT, "exp", "v211_grow.py"))
    v216 = load_module("v216", os.path.join(ROOT, "exp", "v216_grow.py"))
    v217 = load_module("v217", os.path.join(ROOT, "exp", "v217_grow.py"))
    G = load_module("g", os.path.join(ROOT, "grow.py"))  # 当前=2.4.x

    true000, clean_true = labels()

    results = {}
    MIN_COH = 1.5
    # v211/v216/v217 只用候选集（它们无 rsr 列，取前6元）
    for tag, mod in [("v211", v211), ("v216", v216), ("v217", v217)]:
        c, _ = mod.scan_and_grow(S, wgt, ENT_MR, True)
        if tag == "v217":
            # v217 = 凝固度过滤: 熵门 + 凝固度 c[5]>=MIN_COH
            base = {x[0] for x in c if (x[4] < 0 or x[4] >= MIN_ENT) and x[5] >= MIN_COH}
        else:
            base = {x[0] for x in c if x[4] < 0 or x[4] >= MIN_ENT}
        results[tag] = (len(base), base)
    # 2.4.1 / 2.4.2 / affix
    c_g, _ = G.scan_and_grow(S, wgt, ENT_MR, True)
    base_all = {x[0] for x in c_g if x[4] < 0 or x[4] >= MIN_ENT}
    results["2.4.1"] = (len(base_all), base_all)
    # 救援侧 2.4.2 (spe>=0.8 & rsr>=8)
    _, kept_r = cand_tuple(G, S, wgt, spe_rescue=0.8, rsr_rescue=8)
    results["2.4.2"] = (len(kept_r), {x[0] for x in kept_r})
    # affix 路线（仅诊断，不计入主表）
    _, kept_a = cand_tuple(G, S, wgt, rsr_affix=2)
    affix_set = {x[0] for x in kept_a}

    # 救援集专项（2.4.1 vs 2.4.2）
    rescue_241 = [x for x in c_g if x[5] >= 0.8 and x[0] not in base_all]
    rescue_242 = [x for x in kept_r if x[0] not in base_all]

    def stat(rescue):
        return (len(rescue),
                sum(1 for x in rescue if x[0] in true000),
                sum(1 for x in rescue if x[0] in clean_true),
                len(rescue) - sum(1 for x in rescue if x[0] in true000))

    print("=" * 78)
    print(" 2.4.2 补集偏序(RSR) 对比报告  (title, MIN_ENT=%s)" % MIN_ENT)
    print("=" * 78)
    print("\n--- 产词数对比 ---")
    print(f"{'版本':10s} {'产词数':>7s} {'Δv211':>7s}")
    base_n = results["v211"][0]
    for tag in ["v211", "v216", "v217", "2.4.1", "2.4.2"]:
        n = results[tag][0]
        print(f"{tag:10s} {n:>7d} {n-base_n:>+7d}")

    print("\n--- 救援集专项 (spe>=0.8) ---")
    print(f"{'配置':10s} {'救回':>5s} {'000标签':>7s} {'净干净':>6s} {'噪声(估)':>8s}")
    for tag, rs in [("2.4.1(纯SPE)", rescue_241), ("2.4.2(SPE+RSR)", rescue_242)]:
        a, b, cc, d = stat(rs)
        print(f"{tag:12s} {a:>5d} {b:>7d} {cc:>6d} {d:>8d}")

    print("\n--- RSR 词缀过滤(affix) 路线诊断（已弃用）---")
    print(f" 熵门基线 {len(base_all)} → rsr_affix=2 删 {len(base_all)-len(affix_set)} 词")
    known_real = ["指南", "有点", "历史", "天道", "刘备", "侦探", "律师", "星球",
                  "主宰", "王座", "暴君", "维度", "魔神", "魔女", "生涯", "神探",
                  "万年", "生存", "鉴宝", "随身", "女主", "刷新", "天灾", "一品",
                  "日志", "真实", "天子", "二代", "阴影", "道君", "港岛", "莽荒"]
    hit = [w for w in known_real if w not in affix_set and w in base_all]
    print(f" 误杀已知真标题词 {len(hit)} 个: " + " | ".join(hit[:20]))

    print("\n--- 000 层标签召回（27 词，coh>=6）---")
    for tag in ["v211", "v216", "v217", "2.4.1", "2.4.2"]:
        s = results[tag][1]
        rec = sum(1 for w in true000 if w in s)
        print(f"  {tag:8s}: 召回 {rec}/27")

    # 写产物
    def write_csv(path, kept):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["word", "count", "independent", "bind", "len",
                        "compound_entropy", "spe", "rsr"])
            for x in sorted(kept, key=lambda x: -x[1]):
                w.writerow([x[0], x[1], round(x[2], 4), round(x[3], 4),
                            len(x[0]), round(x[4], 4), round(x[5], 4), round(x[6], 4)])

    write_csv(os.path.join(OUT, "title_wordfreq_241.csv"),
              [x for x in c_g if x[0] in results["2.4.1"][1]])
    write_csv(os.path.join(OUT, "title_wordfreq_242.csv"), kept_r)
    print(f"\n产物已写: {OUT}/title_wordfreq_241.csv, title_wordfreq_242.csv")


if __name__ == "__main__":
    main()
