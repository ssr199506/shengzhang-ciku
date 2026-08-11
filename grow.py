#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生长词库 · 纯 Python 版
=======================
CSV(title, intro) → 去重加权 → 清洗纯CJK → 单字生长最大重复 → 独立出现次数判据
→ 词云 PNG + 词频表 CSV + 字频表 CSV

title / intro 为两条独立管线：共享全部逻辑，但各自输出、结果不混淆。

判据（独立出现次数 == 0 → 删）：
    对候选词 w，一次出现被更长候选词覆盖 ⟺ 左邻字符 c 满足 count(cw)≥2，
    或右邻字符 c' 满足 count(wc')≥2；run 首尾边界出现天然不算被覆盖。
    独立出现次数(w) = 未被覆盖的出现数（按权重计）；保留 iff ≥ 1。

用法：
    python grow.py <输入.csv> [--out DIR] [--top N] [--maxlen N] [--no-header] [--no-dedup]
"""

import argparse
import csv
import os
import json
import re
import sys
from collections import Counter


SEP = '\x00'  # 清洗后文本中保证不出现的边界字符
CJK_RE = re.compile(r'[\u4e00-\u9fff]+')

CLOUD_W, CLOUD_H = 1600, 1000  # 词云画布尺寸（布局坐标空间，HTML 按此原样摆放）


# ---------------------------------------------------------------- 清洗层
def clean(text):
    """只保留连续 CJK（U+4E00–U+9FFF），非 CJK 字符即 run 边界。"""
    return SEP.join(CJK_RE.findall(text or ''))


def build_corpus(docs):
    """docs: [(清洗后字段串, 权重)] → (拼接串 S, 位置权重数组 wgt)。
    字段内 run 已用 SEP 连接；字段之间也用 SEP 分隔。
    SEP 位置给占位权重（扫描时跳过，永不读取）。"""
    parts = []
    wgt = []
    for field, w in docs:
        if not field:
            continue
        if parts:
            parts.append(SEP)
            wgt.append(1)
        parts.append(field)
        wgt.extend([w] * len(field))
    return ''.join(parts), wgt


# ---------------------------------------------------------------- 生长层 + 判定层
def _wsum(pos_list, wgt):
    """按权重求出现次数。"""
    return sum(wgt[p] for p in pos_list)


def scan_and_grow(S, wgt):
    """核心：单字种子 → 跳跃式 BFS 枚举最大重复 → 独立出现次数判据。

    返回 (candidates, charfreq)
        candidates: [(word, count, independent)]，len(word)>=2 且 independent>=1
        charfreq:   {char: 加权出现次数}
    """
    n = len(S)

    # 单字扫描：pos_single[char]=出现位置；charfreq 按权重累加
    pos_single = {}
    charfreq = {}
    for p, ch in enumerate(S):
        if ch == SEP:
            continue
        pos_single.setdefault(ch, []).append(p)
        charfreq[ch] = charfreq.get(ch, 0) + wgt[p]

    def right_dist(w, pos_list):
        """右邻分布：返回 (groups, boundary)。
        groups: {右邻字符: ([位置], 加权和)}；boundary: 右邻为边界(SEP/串尾)的加权和。"""
        groups = {}
        boundary = 0
        lw = len(w)
        for p in pos_list:
            rp = p + lw
            if rp >= n or S[rp] == SEP:
                boundary += wgt[p]
            else:
                c = S[rp]
                g = groups.get(c)
                if g is None:
                    groups[c] = [[p], wgt[p]]  # [位置列表, 加权和]
                else:
                    g[0].append(p)
                    g[1] += wgt[p]
        return groups, boundary

    # 左最大 / 独立次数判定用：左邻分布
    def left_dist(pos_list):
        groups = {}
        boundary = 0
        for p in pos_list:
            if p == 0 or S[p - 1] == SEP:
                boundary += wgt[p]
            else:
                c = S[p - 1]
                groups[c] = groups.get(c, 0) + wgt[p]
        return groups, boundary

    # BFS 队列：入队 (word, pos_list)，word 的加权 count >= 2
    from collections import deque
    queue = deque()
    seen = set()
    for ch, plist in pos_single.items():
        if _wsum(plist, wgt) >= 2:
            key = (ch, id(plist))
            queue.append((ch, plist))
            seen.add(ch)  # 按串标记；单字本身不会从别处再生成

    candidates = []

    while queue:
        w, lst = queue.popleft()
        # 跳跃：直到右最大（右邻含边界，或右邻字符种数 >=2）
        while True:
            groups, boundary = right_dist(w, lst)
            if boundary > 0 or len(groups) >= 2:
                break  # 右最大
            # 唯一右邻字符 c 且无边界 → 同频右扩，直接跳
            c = next(iter(groups))
            w = w + c
            lst = groups[c][0]

        count_w = _wsum(lst, wgt)

        # 左最大检查：左邻含边界，或左邻字符种数 >=2
        l_groups, l_boundary = left_dist(lst)
        if l_boundary == 0 and len(l_groups) < 2:
            # 所有出现左邻都是同一字符 → 非左最大 → 整棵右扩展子树都非左最大，剪枝
            continue

        # 独立出现次数：出现位置同时满足 左邻∉L2 且 右邻∉R2
        # L2 = {c: count(cw)>=2}, R2 = {c: count(wc)>=2}（边界不算）
        L2 = {c for c, cnt in l_groups.items() if cnt >= 2}
        R2 = {c for c, (pl, wsum) in groups.items() if wsum >= 2}
        independent = 0
        lw = len(w)
        for p in lst:
            if p > 0 and S[p - 1] != SEP and S[p - 1] in L2:
                continue  # 左被覆盖
            rp = p + lw
            if rp < n and S[rp] != SEP and S[rp] in R2:
                continue  # 右被覆盖
            independent += wgt[p]

        if len(w) >= 2 and independent >= 1:
            candidates.append((w, count_w, independent))

        # 继续生长：右邻字符分支（加权 count >= 2 才可能成为词）
        for c, (pl, wsum) in groups.items():
            if wsum >= 2:
                wc = w + c
                if wc not in seen:
                    seen.add(wc)
                    queue.append((wc, pl))

    return candidates, charfreq


# ---------------------------------------------------------------- 输出层
def write_word_csv(path, candidates):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['word', 'count', 'independent', 'len'])
        for w, cnt, ind in sorted(candidates, key=lambda x: (-x[1], x[0])):
            wr.writerow([w, cnt, ind, len(w)])


def write_char_csv(path, charfreq):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f)
        wr.writerow(['char', 'count'])
        for ch, cnt in sorted(charfreq.items(), key=lambda x: (-x[1], x[0])):
            wr.writerow([ch, cnt])


def render_cloud(path, candidates, top_n=200, maxlen=0, font_path=None):
    """画词云 PNG，并返回布局 layout_（每个词的最终坐标/字号/颜色/朝向）。
    layout_ 为 5 元组：((word, 归一化频率), font_size, (y, x), orientation, color)。
    orientation: None=横排, Image.ROTATE_90=竖排。删词/空语料时返回 None。"""
    from wordcloud import WordCloud
    if font_path is None:
        font_path = _pick_font()
    freqs = {}
    for w, cnt, ind in candidates:
        if maxlen and len(w) > maxlen:
            continue
        freqs[w] = cnt
    if not freqs:
        return None
    top = dict(sorted(freqs.items(), key=lambda x: -x[1])[:top_n])
    wc = WordCloud(font_path=font_path, width=CLOUD_W, height=CLOUD_H,
                   background_color='white', max_words=top_n,
                   collocations=False, repeat=False, prefer_horizontal=0.9,
                   random_state=42)  # 固定种子，使词云布局可复现
    wc.generate_from_frequencies(top)
    wc.to_file(path)
    return wc.layout_


def _pick_font():
    candidates = [
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\msyh.ttf',
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def select_cloud_words(candidates, top_n=200, maxlen=0):
    """挑出词云要画的词：按 count 降序、过滤超长、截断 top_n。
    返回 [(word, count)] 有序列表。"""
    freqs = {}
    for w, cnt, ind in candidates:
        if maxlen and len(w) > maxlen:
            continue
        freqs[w] = cnt
    return sorted(freqs.items(), key=lambda x: -x[1])[:top_n]




def build_cloud_html(data):
    """生成自包含互动词云 HTML：词按 layout 绝对定位（与 PNG 同坐标），
    单击选中变色、双击弹出可拖动面板列出匹配文本并高亮词。"""
    payload = json.dumps(data, ensure_ascii=False)
    return _CLOUD_HTML_TEMPLATE.replace('__DATA_JSON__', payload)


_CLOUD_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>生长词库 · 互动词云</title>
<style>
  html,body{margin:0;background:#f4f5f7;font-family:"Microsoft YaHei","微软雅黑","PingFang SC",sans-serif;color:#222;}
  #bar{position:fixed;top:0;left:0;right:0;height:42px;background:#fff;border-bottom:1px solid #e1e4e8;
       display:flex;align-items:center;gap:18px;padding:0 16px;z-index:60;font-size:14px;box-shadow:0 1px 3px rgba(0,0,0,.04);}
  #bar b{font-size:15px;}
  #hint{color:#8a93a0;font-size:12.5px;}
  #stage{position:absolute;top:42px;left:0;right:0;bottom:0;overflow:auto;}
  #canvas{position:relative;width:1600px;height:1000px;background:#fff;margin:18px auto;
          transform-origin:top left;box-shadow:0 2px 14px rgba(0,0,0,.08);}
  .word{position:absolute;white-space:nowrap;cursor:pointer;line-height:1;user-select:none;font-weight:700;
        transition:color .08s, text-shadow .08s;}
  .word:hover{filter:brightness(.82);}
  .word.sel{color:#ff2d55 !important;text-shadow:0 0 3px rgba(255,45,85,.45);}
  .word.v{writing-mode:vertical-rl;}
  #panel{position:fixed;width:380px;max-height:72vh;background:#fff;border:1px solid #cdd3dc;
         border-radius:12px;box-shadow:0 14px 40px rgba(0,0,0,.22);display:none;z-index:120;
         flex-direction:column;overflow:hidden;}
  #panel.show{display:flex;}
  #phead{display:flex;align-items:center;gap:10px;padding:11px 14px;background:#ff2d55;color:#fff;
         cursor:grab;font-weight:700;user-select:none;}
  #phead.drag{cursor:grabbing;}
  #pcnt{font-weight:400;opacity:.92;font-size:12.5px;}
  #pclose{margin-left:auto;cursor:pointer;font-size:20px;line-height:1;padding:0 2px;}
  #pbody{padding:6px 14px 12px;overflow:auto;font-size:13px;line-height:1.75;}
  .row{padding:6px 0;border-bottom:1px dashed #eef0f3;word-break:break-all;}
  .row:last-child{border-bottom:none;}
  .row mark{background:#fff2a8;color:#d12b2b;padding:0 2px;border-radius:3px;font-weight:700;}
  .empty{color:#9aa3af;padding:10px 0;}
</style>
</head>
<body>
<div id="bar">
  <b>生长词库 · 互动词云</b>
  <span id="hint">单击词语 = 选中（变色）&nbsp;·&nbsp; 双击 = 打开匹配清单 &nbsp;·&nbsp; 拖拽面板标题栏可移动</span>
</div>
<div id="stage"><div id="canvas"></div></div>
<div id="panel">
  <div id="phead"><span id="ptitle"></span><span id="pcnt"></span><span id="pclose">&times;</span></div>
  <div id="pbody"></div>
</div>
<script>
const DATA = __DATA_JSON__;
const canvas = document.getElementById('canvas');
const stage = document.getElementById('stage');
const panel = document.getElementById('panel');
const phead = document.getElementById('phead');

function fit(){
  const s = Math.min(1, (stage.clientWidth - 36) / DATA.size[0]);
  canvas.style.transform = 'scale(' + s + ')';
}
window.addEventListener('resize', fit); fit();

function esc(s){ return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function highlight(text, word){
  const w = esc(word);
  return esc(text).split(w).join('<mark>' + w + '</mark>');
}

let selEl = null;
DATA.words.forEach(wd => {
  const el = document.createElement('span');
  el.className = 'word' + (wd.rotate ? ' v' : '');
  el.textContent = wd.word;
  el.style.left = wd.x + 'px';
  el.style.top = wd.y + 'px';
  el.style.fontSize = wd.size + 'px';
  el.style.color = wd.color;
  el.addEventListener('click', e => { e.stopPropagation(); select(el); });
  el.addEventListener('dblclick', e => { e.stopPropagation(); openPanel(wd.word); });
  canvas.appendChild(el);
});
function select(el){
  if (selEl) selEl.classList.remove('sel');
  selEl = el; el.classList.add('sel');
}
function openPanel(word){
  const idxs = DATA.matches[word] || [];
  document.getElementById('ptitle').textContent = word;
  document.getElementById('pcnt').textContent = '匹配 ' + idxs.length + ' 条';
  const body = document.getElementById('pbody');
  body.innerHTML = '';
  if (!idxs.length){ body.innerHTML = '<div class="empty">（无匹配文本）</div>'; }
  else {
    const frag = document.createDocumentFragment();
    idxs.forEach(i => {
      const d = document.createElement('div');
      d.className = 'row';
      d.innerHTML = highlight(DATA.fields[i], word);
      frag.appendChild(d);
    });
    body.appendChild(frag);
  }
  panel.classList.add('show');
  const r = selEl ? selEl.getBoundingClientRect() : {right: 200, top: 120};
  let x = r.right + 10, y = Math.max(54, r.top);
  x = Math.min(x, window.innerWidth - 396);
  y = Math.min(y, window.innerHeight - 120);
  panel.style.left = x + 'px';
  panel.style.top = y + 'px';
}
document.getElementById('pclose').addEventListener('click', () => panel.classList.remove('show'));

let drag = null;
phead.addEventListener('mousedown', e => {
  if (e.target.id === 'pclose') return;
  drag = {dx: e.clientX, dy: e.clientY, lx: panel.offsetLeft, ty: panel.offsetTop};
  phead.classList.add('drag');
});
window.addEventListener('mousemove', e => {
  if (!drag) return;
  let x = drag.lx + e.clientX - drag.dx;
  let y = drag.ty + e.clientY - drag.dy;
  x = Math.max(4, Math.min(x, window.innerWidth - panel.offsetWidth - 4));
  y = Math.max(46, Math.min(y, window.innerHeight - 60));
  panel.style.left = x + 'px';
  panel.style.top = y + 'px';
});
window.addEventListener('mouseup', () => { drag = null; phead.classList.remove('drag'); });

stage.addEventListener('click', () => {
  if (selEl){ selEl.classList.remove('sel'); selEl = null; }
  panel.classList.remove('show');
});
</script>
</body>
</html>
'''


# ---------------------------------------------------------------- 输入层
def load_csv(path, has_header):
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


# ---------------------------------------------------------------- 管线
def process_corpus(prefix, docs, raw_texts, out_dir, top_n, maxlen, font_path):
    S, wgt = build_corpus(docs)
    if not S:
        return
    print(f'[{prefix}] 语料字符数(去重后): {len(S)}  run数: {S.count(SEP)+1 if S else 0}', file=sys.stderr)
    candidates, charfreq = scan_and_grow(S, wgt)
    print(f'[{prefix}] 候选词: {len(candidates)}  去重字符: {len(charfreq)}', file=sys.stderr)
    write_word_csv(os.path.join(out_dir, f'{prefix}_wordfreq.csv'), candidates)
    write_char_csv(os.path.join(out_dir, f'{prefix}_charfreq.csv'), charfreq)
    try:
        layout = render_cloud(os.path.join(out_dir, f'{prefix}_wordcloud.png'),
                              candidates, top_n, maxlen, font_path)
    except Exception as e:
        print(f'[{prefix}] 词云渲染跳过: {e}', file=sys.stderr)
        layout = None
    # 互动词云（插入模块，独立生成 json + html；失败不影响上面的核心产物）
    try:
        if layout is not None:
            cloud_words = select_cloud_words(candidates, top_n, maxlen)
            words_info = []
            placed = set()
            for (wf), fs, (py, px), orient, col in layout:
                w = wf[0]
                words_info.append({'word': w, 'x': int(px), 'y': int(py),
                                    'size': int(fs), 'color': col, 'rotate': bool(orient is not None)})
                placed.add(w)
            matches = {}
            for w, _ in cloud_words:
                if w not in placed:
                    continue
                idxs = [i for i, t in enumerate(raw_texts) if w in t]
                if idxs:
                    matches[w] = idxs
            data = {'size': [CLOUD_W, CLOUD_H], 'fields': raw_texts,
                    'words': words_info, 'matches': matches}
            with open(os.path.join(out_dir, f'{prefix}_wordcloud.json'), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            with open(os.path.join(out_dir, f'{prefix}_wordcloud.html'), 'w', encoding='utf-8') as f:
                f.write(build_cloud_html(data))
            print(f'[{prefix}] 互动词云: {len(words_info)} 词, '
                  f'{sum(len(v) for v in matches.values())} 条匹配', file=sys.stderr)
    except Exception as e:
        print(f'[{prefix}] 互动词云生成跳过: {e}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description='生长词库：纯 Python 版')
    ap.add_argument('input', help='CSV 路径（title, intro 两列）')
    ap.add_argument('--out', default='.', help='输出目录')
    ap.add_argument('--top', type=int, default=200, help='词云词数上限')
    ap.add_argument('--maxlen', type=int, default=0, help='词云最大词长过滤（0=不限，仅显示层）')
    ap.add_argument('--no-header', action='store_true', help='CSV 无表头')
    ap.add_argument('--no-dedup', action='store_true', help='不去重（默认按相同 title,intro 合并加权）')
    ap.add_argument('--title-col', type=int, default=0, help='书名列号（0-based）')
    ap.add_argument('--intro-col', type=int, default=1, help='简介列号（0-based，-1 表示无简介）')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    def cell(r, idx):
        if idx < 0 or idx >= len(r):
            return ''
        return r[idx].strip()

    with open(args.input, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = []
        for i, r in enumerate(reader):
            if not r:
                continue
            if i == 0 and not args.no_header and detect_header(r, args.title_col, args.intro_col):
                continue
            title = cell(r, args.title_col)
            intro = cell(r, args.intro_col)
            rows.append((title, intro))

    if args.no_dedup:
        dedup = [(t, i, 1) for t, i in rows]
    else:
        dedup = [(t, i, w) for (t, i), w in Counter(rows).items()]

    # 两条独立管线：结果不混淆
    title_docs = [(clean(t), w) for t, i, w in dedup if t]
    intro_docs = [(clean(i), w) for t, i, w in dedup if i]
    title_raw = [t for t, i, w in dedup if t]
    intro_raw = [i for t, i, w in dedup if i]

    process_corpus('title', title_docs, title_raw, args.out, args.top, args.maxlen, None)
    process_corpus('intro', intro_docs, intro_raw, args.out, args.top, args.maxlen, None)
    print(f'完成，输出目录: {args.out}')


if __name__ == '__main__':
    main()
