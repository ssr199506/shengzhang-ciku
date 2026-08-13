# -*- coding: utf-8 -*-
"""细查 v219 在 spe_rescue=0.4 / spe_affix=0.4 下的救回集与删除集，判断质量。"""
import importlib.util, csv, os, sys
EV = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(EV)
sys.path.insert(0, ROOT)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5; ENT_MR = 0.25
EVAL = r"D:\agent\work\workbuddy\Claw\eval_versions"

def load_grow(p):
    spec = importlib.util.spec_from_file_location("g_"+os.path.basename(p), p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def build_title_docs(g):
    docs=[]
    with open(CSV,encoding="utf-8-sig",newline="") as f:
        for i,r in enumerate(csv.reader(f)):
            if not r: continue
            if i==0 and g.detect_header(r,2,1): continue
            t=r[2].strip() if len(r)>2 else ""
            if t: docs.append(t)
    d={}
    for t in docs:
        if t: d[t]=d.get(t,0)+1
    return [(g.clean(t,True),w) for t,w in d.items() if t]

def run_ref(g, pos_fixed=None, min_coh=0.0):
    docs=build_title_docs(g); S,wgt=g.build_corpus(docs)
    if pos_fixed is not None: cands,_=g.scan_and_grow(S,wgt,ENT_MR,True,pos_fixed_thr=pos_fixed)
    elif hasattr(g,"build_ngram_freq"): cands,_=g.scan_and_grow(S,wgt,ENT_MR,True,cohesion_max_len=8)
    else: cands,_=g.scan_and_grow(S,wgt,ENT_MR,True)
    kept=set()
    for c in cands:
        ent=c[4]
        if not (ent<0 or ent>=MIN_ENT): continue
        if min_coh>0 and len(c[0])>=2 and c[5]<min_coh: continue
        kept.add(c[0])
    return kept, cands

def load_000():
    d={}
    with open(os.path.join(EVAL,"mistake_book.csv"),encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["class"]=="000": d[r["word"]]=r
    return d

def main():
    g211=load_grow(os.path.join(EV,"v211_grow.py"))
    g219=load_grow(os.path.join(ROOT,"grow.py"))
    r211,c211=run_ref(g211)
    docs=build_title_docs(g219); S,wgt=g219.build_corpus(docs)
    all219,_=g219.scan_and_grow(S,wgt,ENT_MR,True)
    m219={c[0]:c for c in all219}
    sr,sa=0.4,0.4
    kept219=set(c[0] for c in all219 if (c[4]<0 or c[4]>=MIN_ENT) or (sr>0 and c[5]>=sr))
    kept219={w for w in kept219 if not (sa>0 and m219[w][5]>=0 and m219[w][5]<=sa)}
    rescue=sorted(kept219-r211, key=lambda w:-m219[w][1])
    removed=sorted(r211-kept219, key=lambda w:-m219[w][1])
    d000=load_000()
    print(f"=== 救援集 (v219新增 vs v211): {len(rescue)} 词 ===")
    print(f"{'词':<10}{'count':>6}{'ent':>7}{'spe':>7} 000层?")
    for w in rescue[:60]:
        c=m219[w]; tag="是" if w in d000 else ""
        print(f"{w:<10}{c[1]:>6}{c[4]:>7.2f}{c[5]:>7.2f} {tag}")
    print(f"\n=== 删除集 (v219删 vs v211): {len(removed)} 词 (spe_affix=0.4触发) ===")
    print(f"{'词':<10}{'count':>6}{'ent':>7}{'spe':>7}")
    for w in removed[:60]:
        c=m219[w]
        print(f"{w:<10}{c[1]:>6}{c[4]:>7.2f}{c[5]:>7.2f}")

if __name__=="__main__":
    main()
