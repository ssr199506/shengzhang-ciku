"""grow3.title_index —— 标题索引（补集）独立模块，无耦合接入核心管道。

在核心管道产出 ``{prefix}_wordfreq.csv`` 与词云后运行（两步法，见 run_all.bat）：

    python -m grow3.title_index <input.csv> --wordfreq <out/title_wordfreq.csv> \
           --out <out> [--prefix title] [--title-col 2] [--intro-col -1] [--no-cloud]

计算「标题覆盖」：
  1. 重扫语料（clean + build_corpus + 记录字段边界 + scan_once），拿「词→位置→标题」映射；
  2. 读 wordfreq.csv 得 kept 词集；
  3. 对每个标题标 status：kept / cand_lost / lone；
  4. 写 ``{prefix}_complement.csv``（补集书名清单，含 status 与产出候选词）；
  5. 把 titles 注入词云产物（.json / .data.js / 内联 .html），搜索框即可双表检索。

核心管道（scan / cli / cloud / gates / signals / ...）零改动；本模块仅复用
scan.build_corpus 的拼接语义、clean、scan_once，以及 interactive_cloud 显示层不依赖。
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from .scan import clean, scan_once

SEP = '\x00'
ENT_MERGE_RATIO = 0.25
COHESION_MAX_LEN = 8


# ---------------------------------------------------------------- 语料重扫（自带边界）
def _build_corpus_with_bounds(titles: List[Tuple[str, float]]):
    """与 scan.build_corpus 语义一致，但额外返回每个字段在 S 中的 [start,end) 区间。

    不修改 scan.build_corpus；本函数独立实现拼接，仅用于标题反查。
    bounds 存原始标题 t（与最终循环用的标题一致），清洗串仅用于定位区间。
    """
    parts = []
    wgt = []
    bounds: List[Tuple[int, int, str]] = []
    for t, w in titles:
        field = clean(t, True)
        if not field:
            continue
        if parts:
            parts.append(SEP)
            wgt.append(1)
        start = sum(len(p) for p in parts)
        parts.append(field)
        end = start + len(field)
        wgt.extend([w] * len(field))
        bounds.append((start, end, t))
    return ''.join(parts), wgt, bounds


def _detect_header(row, title_col, intro_col):
    TITLE_HEADERS = {'title', '书名', '名称', 'name', 'book', 'bookname'}
    if title_col < len(row) and row[title_col].strip().lower() in TITLE_HEADERS:
        return True
    a = row[0].strip().lower() if len(row) > 0 else ''
    b = row[1].strip().lower() if len(row) > 1 else ''
    return a.isascii() and a.isalpha() and b.isascii() and b.isalpha()


def load_titles(path, title_col, intro_col, has_header):
    """读输入 CSV，返回去重后的 [(title, weight)]，与 cli.main 口径一致。"""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        raw = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and has_header and _detect_header(r, title_col, intro_col):
                continue
            title = r[title_col].strip() if 0 <= title_col < len(r) else ''
            raw.append(title)
    return [(t, w) for (t, w) in Counter([t for t in raw if t]).items()]


def load_kept(wordfreq_path: str) -> set:
    """读 wordfreq.csv 的 word 列，得到最终保留词集。"""
    kept = set()
    with open(wordfreq_path, 'r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            kept.add(r['word'].strip())
    return kept


# ---------------------------------------------------------------- 标题索引计算
def build_title_index(titles: List[Tuple[str, float]], kept: set):
    """返回全量标题索引 [{text,status,words}]，并附带补集。

    status:
      kept      —— 该标题产出的候选词中至少有一个被保留；
      cand_lost —— 有候选词但全被闸门滤除（补集）；
      lone      —— 无任何候选词（扫描门槛外的孤本，补集）。
    words: kept=保留词集 / cand_lost=被滤候选集 / lone=[]
    """
    docs = [(clean(t, True), w) for t, w in titles if t]
    S, wgt, bounds = _build_corpus_with_bounds(titles)
    if not S:
        return [{'text': t, 'status': 'lone', 'words': []} for t, _ in titles]
    ctx, _ = scan_once(S, wgt, ENT_MERGE_RATIO, True, COHESION_MAX_LEN)
    cand_lst = ctx.cand_lst

    starts = [b[0] for b in bounds]

    def title_of(pos: int) -> str:
        idx = bisect.bisect_right(starts, pos) - 1
        return bounds[idx][2]

    # 标题 → 其产出的全部候选词
    title_cands: Dict[str, set] = defaultdict(set)
    for word, poslist in cand_lst.items():
        for p in poslist:
            title_cands[title_of(p)].add(word)

    out = []
    for t, _ in titles:
        cands = title_cands.get(t, set())
        kept_cands = cands & kept
        if kept_cands:
            out.append({'text': t, 'status': 'kept', 'words': sorted(kept_cands)})
        elif cands:
            out.append({'text': t, 'status': 'cand_lost', 'words': sorted(cands)})
        else:
            out.append({'text': t, 'status': 'lone', 'words': []})
    return out


def complement_of(titles) -> List[dict]:
    """从全量标题索引中筛出补集（cand_lost + lone）。"""
    return [t for t in titles if t["status"] != "kept"]


def write_complement_csv(path, titles):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['title', 'status', 'candidates'])
        for t in titles:
            if t['status'] != 'kept':
                wr.writerow([t['text'], t['status'], ','.join(t['words'])])


# ---------------------------------------------------------------- 注入词云产物
def _inject_inline(html: str, titles) -> str:
    """standalone HTML：const DATA = {...}; 内联 JSON 注入 titles（括号平衡解析）。"""
    marker = 'const DATA = '
    i = html.index(marker) + len(marker)
    depth = 0
    instr = None
    j = i
    while j < len(html):
        c = html[j]
        if instr:
            if c == '\\':
                j += 2
                continue
            if c == instr:
                instr = None
        elif c in '"\'`':
            instr = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    obj = json.loads(html[i:j])
    obj['titles'] = titles
    return html[:i] + json.dumps(obj, ensure_ascii=False) + html[j:]


def inject_titles(out_dir: str, prefix: str, titles) -> bool:
    """把 titles 注入词云三种产物之一或全部；返回是否至少注入一处。"""
    did = False
    jp = os.path.join(out_dir, f'{prefix}_wordcloud.json')
    if os.path.exists(jp):
        d = json.load(open(jp, encoding='utf-8'))
        d['titles'] = titles
        json.dump(d, open(jp, 'w', encoding='utf-8'), ensure_ascii=False)
        did = True
    dp = os.path.join(out_dir, f'{prefix}_wordcloud.data.js')
    if os.path.exists(dp):
        s = open(dp, encoding='utf-8').read()
        m = re.match(r'^window\.GROW_DATA\s*=\s*', s)
        obj = json.loads(s[m.end():].rstrip().rstrip(';'))
        obj['titles'] = titles
        open(dp, 'w', encoding='utf-8').write(
            'window.GROW_DATA = ' + json.dumps(obj, ensure_ascii=False) + ';')
        did = True
    hp = os.path.join(out_dir, f'{prefix}_wordcloud.html')
    if os.path.exists(hp):
        s = open(hp, encoding='utf-8').read()
        if 'const DATA = ' in s and 'data.js' not in s:
            open(hp, 'w', encoding='utf-8').write(_inject_inline(s, titles))
            did = True
    return did


# ---------------------------------------------------------------- 补集 UI 补丁（独立第二段 <script>）
# 固定代码，运行时读 window.GROW_DATA.titles；不依赖具体数据、不触碰原版引擎。
# 通过「捕获阶段监听搜索框 input + stopImmediatePropagation」接管原版搜索渲染：
#   渲染 = 普通命中词平铺（同原版视觉）+ 末尾常驻「补集（未收录书名）」特殊词条；
#   点击补集词条 → 打开原版同一个 #panel（复用 openPanel/esc/highlight/定位/拖拽/关闭），
#   仅把面板正文换成补集书名清单（.row 同形 + 状态标签 + 候选词）。
# OFF 时不注入本段，原版 HTML 字节级不变。
COMPLEMENT_UI_CSS = """
.sitem.comp{background:#fdf0f4;border-top:1px solid #f3d6df;}
.sitem.comp:hover{background:#fbe6ed;}
.sitem.comp .c{color:#c8324f;border-color:#f0c3cf;}
.row .b{display:inline-block;font-size:11px;color:#8a93a0;border:1px solid #d8dde4;
        border-radius:6px;padding:1px 6px;margin-left:8px;vertical-align:baseline;}
.row .b.candlost{color:#c8730a;border-color:#f0d9b5;background:#fdf8ef;}
.row .b.lone{color:#9aa3af;border-color:#e1e4e8;}
.row .sub{font-size:11px;color:#9aa3af;margin-top:3px;}
"""

COMPLEMENT_UI_JS = r'''
(function(){
  if(!window.GROW_DATA || !Array.isArray(window.GROW_DATA.titles)) return;
  var DATA = window.GROW_DATA;
  var compAll = DATA.titles.filter(function(t){ return t.status !== 'kept'; });

  function buildCompItem(kw, count){
    var d = document.createElement('div'); d.className = 'sitem comp';
    d.innerHTML = '<span>补集（未收录书名）</span><span class="c">' + count + '</span>';
    d.addEventListener('click', function(){ openComp(kw); });
    return d;
  }

  function openComp(kw){
    var list = kw
      ? compAll.filter(function(t){ return t.text.indexOf(kw) >= 0; })
      : compAll;
    document.getElementById('ptitle').textContent = '补集（未收录书名）';
    document.getElementById('pcnt').textContent = '共 ' + list.length + ' 本';
    var body = document.getElementById('pbody'); body.innerHTML = '';
    if(!list.length){ body.innerHTML = '<div class="empty">（无词表外书籍）</div>'; }
    else {
      var frag = document.createDocumentFragment();
      list.forEach(function(t){
        var d = document.createElement('div'); d.className = 'row';
        var badge = t.status === 'cand_lost' ? '候选被滤' : '孤本';
        var h = highlight(t.text, kw)
              + '<span class="b ' + (t.status === 'cand_lost' ? 'candlost' : 'lone') + '">' + badge + '</span>';
        if(t.words && t.words.length){
          h += '<div class="sub">产出词：' + t.words.map(esc).join('、') + '</div>';
        }
        d.innerHTML = h; frag.appendChild(d);
      });
      body.appendChild(frag);
    }
    panel.classList.add('show');
    var r = (typeof selEl !== 'undefined' && selEl)
            ? selEl.getBoundingClientRect() : {right: 200, top: 120};
    var x = Math.min(r.right + 10, window.innerWidth - panel.offsetWidth - 4);
    var y = Math.max(46, (window.innerHeight - panel.offsetHeight) / 2);
    panel.style.left = x + 'px'; panel.style.top = y + 'px';
  }

  function renderSearch(rawKw){
    var kw = (rawKw || '').trim();
    if(!kw){
      sres.innerHTML = ''; sres.appendChild(buildCompItem('', compAll.length));
      sres.classList.add('show'); return;
    }
    var hits = Object.keys(DATA.matches)
      .filter(function(w){ return w.indexOf(kw) >= 0; })
      .sort(function(a, b){ return DATA.matches[b].count - DATA.matches[a].count; });
    var compHit = compAll.filter(function(t){ return t.text.indexOf(kw) >= 0; });
    if(!hits.length && !compHit.length){
      sres.innerHTML = '<div class="sempty">无匹配词语 / 书籍</div>';
      sres.classList.add('show'); return;
    }
    var frag = document.createDocumentFragment();
    hits.forEach(function(w){
      var d = document.createElement('div'); d.className = 'sitem';
      d.innerHTML = '<span>' + esc(w) + '</span><span class="c">' + DATA.matches[w].count + '</span>';
      d.addEventListener('click', function(){ openPanel(w); });
      frag.appendChild(d);
    });
    if(compHit.length){ frag.appendChild(buildCompItem(kw, compHit.length)); }
    sres.innerHTML = ''; sres.appendChild(frag); sres.classList.add('show');
  }

  // 捕获阶段接管搜索：先于原版（target 阶段）监听执行，渲染后阻止其执行
  document.addEventListener('input', function(e){
    if(e.target && e.target.id === 'search'){
      e.stopImmediatePropagation();
      renderSearch(e.target.value);
    }
  }, true);
})();
'''


def complement_script() -> str:
    """返回补集 UI 补丁（<style> + <script>），ON 时由生成脚本注入 HTML 末尾。"""
    return '<style>' + COMPLEMENT_UI_CSS.strip() + '</style>\n<script>' + COMPLEMENT_UI_JS.strip() + '</script>'


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="grow3.title_index",
                                 description="标题索引（补集）独立模块")
    ap.add_argument("input", nargs="?", default=None, help="输入 CSV（同核心管道）")
    ap.add_argument("--config", default=None, help="配置文件路径（JSON）；缺省时自动读仓库根 config.json")
    ap.add_argument("--wordfreq", default=None, help="核心管道产出的 wordfreq.csv（缺省时按 out/prefix 推断）")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--prefix", default="title", help="产物前缀（默认 title）")
    ap.add_argument("--title-col", type=int, default=None)
    ap.add_argument("--intro-col", type=int, default=None)
    ap.add_argument("--no-header", action="store_true")
    ap.add_argument("--no-cloud", action="store_true", help="只写 complement.csv，不注入词云")
    args = ap.parse_args(argv)

    # ---- 配置合并：CLI 显式位置参数/选项 > 配置文件 ----
    cfg_map = {}
    if args.config:
        with open(args.config, encoding='utf-8') as f:
            cfg_map = json.load(f)
    input_path = args.input or cfg_map.get('input')
    if not input_path:
        ap.error("未指定输入 CSV：请提供位置参数，或配置文件 input 字段")
    title_col = args.title_col if args.title_col is not None else cfg_map.get('title_col', 2)
    intro_col = args.intro_col if args.intro_col is not None else cfg_map.get('intro_col', -1)
    out_dir = args.out or cfg_map.get('out') or '.'
    wordfreq_path = args.wordfreq or os.path.join(out_dir, f'{args.prefix}_wordfreq.csv')

    titles = load_titles(input_path, title_col, intro_col, not args.no_header)
    kept = load_kept(wordfreq_path)
    idx = build_title_index(titles, kept)

    complement_path = os.path.join(out_dir, f'{args.prefix}_complement.csv')
    write_complement_csv(complement_path, idx)

    from collections import Counter
    dist = Counter(t['status'] for t in idx)
    print(f'[title_index] 标题 {len(idx)} 个 → '
          f'kept {dist.get("kept",0)} / cand_lost {dist.get("cand_lost",0)} '
          f'/ lone {dist.get("lone",0)}；补集 {len(idx)-dist.get("kept",0)} 条',
          file=sys.stderr)

    if not args.no_cloud:
        if inject_titles(out_dir, args.prefix, idx):
            print(f'[title_index] 已注入词云 titles（{len(idx)} 条）', file=sys.stderr)
        else:
            print('[title_index] 未找到词云产物，跳过注入', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
