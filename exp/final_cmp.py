# -*- coding: utf-8 -*-
"""最终四版本对比 + v219 产物生成。
输出：
  exp/v219_out/title_wordfreq_sr0.8.csv  (探索配置：spe_rescue=0.8)
  exp/v219_out/title_wordfreq_sr1.0.csv  (保守配置：spe_rescue=1.0)
控制台：v211/v216/v217/v219(关)/v219(0.8)/v219(1.0) 产词数、对错题集标签集的影响。
"""
import importlib.util, csv, os, sys
from collections import Counter
EV = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(EV)
sys.path.insert(0, ROOT)
CSV = os.path.join(ROOT, "PAID_CORPUS.csv")
MIN_ENT = 0.5; ENT_MR = 0.25; POS_FIXED = 0.80; MIN_COH = 1.5
EVAL = r"SANDBOX\eval_versions"
FRAG = {"我的","我在","我是","我有","这个","成了","一个","不是","你在","他在","是在","开了","出了","什么","就是","还是","可以","没有","我们","他们"}

def lg(p):
    s=importlib.util.spec_from_file_location("g_"+os.path.basename(p),p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def title_docs(g):
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
def cands(g,**kw):
    docs=title_docs(g); S,wgt=g.build_corpus(docs)
    if "pos_fixed" in kw: c,_=g.scan_and_grow(S,wgt,ENT_MR,True,pos_fixed_thr=kw["pos_fixed"])
    elif "min_coh" in kw: c,_=g.scan_and_grow(S,wgt,ENT_MR,True,cohesion_max_len=8)
    else: c,_=g.scan_and_grow(S,wgt,ENT_MR,True)
    return c
def keep(c, sr=0.0, sa=0.0):
    w,cnt,ind,bind,ent,spe=c
    if ent<0 or ent>=MIN_ENT: k=True
    elif sr>0 and spe>=sr: k=True
    else: k=False
    if k and sa>0 and spe>=0 and spe<=sa: k=False
    return k

def main():
    g211=lg(os.path.join(EV,"v211_grow.py")); g216=lg(os.path.join(EV,"v216_grow.py"))
    g217=lg(os.path.join(EV,"v217_grow.py")); g219=lg(os.path.join(ROOT,"grow.py"))
    c211=cands(g211); c216=cands(g216,pos_fixed=POS_FIXED); c217=cands(g217,min_coh=MIN_COH)
    c219=cands(g219)
    r211={c[0] for c in c211 if c[4]<0 or c[4]>=MIN_ENT}
    r216={c[0] for c in c216 if c[4]<0 or c[4]>=MIN_ENT}
    r217={c[0] for c in c217 if (c[4]<0 or c[4]>=MIN_ENT) and c[5]>=MIN_COH}
    # 标签
    true000=set(); frag111=set()
    with open(os.path.join(EVAL,"mistake_book.csv"),encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["class"]=="000" and r.get("217_coh") not in (None,"","None") and float(r["217_coh"])>=6.0: true000.add(r["word"])
            if r["class"]=="111" and r["word"] in FRAG: frag111.add(r["word"])
    print("标签: 000层真词(coh>=6)=%d  共识层高频碎片=%d"%(len(true000),len(frag111)))
    print("\n=== 四版本 + v219变体 产词数对比（title）===")
    print(f"{'版本':<22}{'产词数':>7}{'Δv211':>7}{'救000真词':>9}{'清共识碎片':>9}")
    def row(name, kept, base=r211):
        res=sum(1 for w in true000 if w in kept and w not in base)
        clr=sum(1 for w in frag111 if w not in kept and w in base)
        print(f"{name:<22}{len(kept):>7}{len(kept)-len(base):>+7}{res:>9}{clr:>9}")
        return kept
    k_off={c[0] for c in c219 if keep(c)}
    k08={c[0] for c in c219 if keep(c,sr=0.8)}
    k10={c[0] for c in c219 if keep(c,sr=1.0)}
    row("v211(纯熵基线)", r211)
    row("v216(pos-fixed)", r216)
    row("v217(cohesion)", r217)
    row("v219(SPE关,=v211)", k_off)
    row("v219(SPE救 sr=0.8)", k08)
    row("v219(SPE救 sr=1.0)", k10)
    # 写产物
    out=os.path.join(EV,"v219_out"); os.makedirs(out,exist_ok=True)
    for nm,sr in [("sr0.8",0.8),("sr1.0",1.0)]:
        rows=[(c[0],c[1],c[2],round(c[3],4),len(c[0]),round(c[4],4),round(c[5],4)) for c in c219 if keep(c,sr=sr)]
        rows.sort(key=lambda x:(-x[1],x[0]))
        with open(os.path.join(out,f"title_wordfreq_{nm}.csv"),"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow(["word","count","independent","bind","len","compound_entropy","spe"]); w.writerows(rows)
    print(f"\n产物已写入: {out}/title_wordfreq_sr0.8.csv , title_wordfreq_sr1.0.csv")
    print("\n=== v219(sr=0.8) vs v211 差异 ===")
    print("新增(被救回):", len(k08-r211), " 删除(被词缀过滤, 此处sa=0故为0):", len(r211-k08))
    print("新增词样例(按count):", " ".join(sorted(k08-r211,key=lambda w:-c219[[c[0] for c in c219].index(w)])[:30]) if False else "")
    # 列出新增词
    m219={c[0]:c for c in c219}
    added=sorted(k08-r211,key=lambda w:-m219[w][1])
    print("被救回的 %d 词(词,count,spe):"%len(added))
    print("  "+" | ".join(f"{w}({m219[w][1]},{m219[w][5]:.2f})" for w in added))

if __name__=="__main__":
    main()
