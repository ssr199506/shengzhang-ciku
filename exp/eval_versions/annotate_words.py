# -*- coding: utf-8 -*-
"""把错题集标注合并回原词表：生成 title_wordfreq_annotated.csv。
原表 4 列（word,count,independent,len）+ 错题集标注列（v211/v216/v217/class/layer/熵/凝固度）。
未匹配的词（三版全滤且 count<5 的低频碎片）标注 class=000-filtered。
"""
import csv, os, sys

EV = os.path.dirname(os.path.abspath(__file__))
BASE = r"PROJECT_ROOT"
SRC = os.path.join(BASE, "out_real", "title_wordfreq.csv")
MB = os.path.join(EV, "mistake_book.csv")
DST = os.path.join(BASE, "out_real", "title_wordfreq_annotated.csv")

# 读错题集标注
annot = {}
with open(MB, encoding="utf-8-sig") as f:
    rd = csv.DictReader(f)
    for r in rd:
        annot[r["word"]] = r

rows = []
with open(SRC, encoding="utf-8-sig") as f:
    rd = csv.DictReader(f)
    fieldnames = rd.fieldnames + ["v211", "v216", "v217", "class", "layer",
                                  "211_ent", "216_ent", "217_ent", "217_coh", "note"]
    for r in rd:
        w = r["word"]
        if w in annot:
            a = annot[w]
            r["v211"] = a["v211"]
            r["v216"] = a["v216"]
            r["v217"] = a["v217"]
            r["class"] = a["class"]
            r["layer"] = a["layer"]
            r["211_ent"] = a.get("211_ent", "")
            r["216_ent"] = a.get("216_ent", "")
            r["217_ent"] = a.get("217_ent", "")
            r["217_coh"] = a.get("217_coh", "")
            r["note"] = a.get("note", "")
        else:
            r["v211"] = r["v216"] = r["v217"] = "0"
            r["class"] = "000f"
            r["layer"] = "全滤(低频)"
            r["211_ent"] = r["216_ent"] = r["217_ent"] = r["217_coh"] = ""
            r["note"] = "三版本全滤且 count<5（未入错题集册）"
        rows.append(r)

with open(DST, "w", encoding="utf-8-sig", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=fieldnames)
    wr.writeheader()
    wr.writerows(rows)

print(f"合并完成：{len(rows)} 词 → {DST}")
print(f"  匹配到错题集标注: {sum(1 for r in rows if r['class'] != '000f')}")
print(f"  三版全滤低频: {sum(1 for r in rows if r['class'] == '000f')}")
