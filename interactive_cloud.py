#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
互动词云 · 插入模块（可选）
=========================
由 grow.py 在管线末尾调用，把 wordcloud 的 layout_ 与每个词匹配到的
原始文本索引，导出为自包含的互动词云：

    {prefix}_wordcloud.json   数据（size / fields / words / matches）
    {prefix}_wordcloud.html   自包含网页（词按 layout 绝对定位，与 PNG 同坐标；
                              单击选中变色、双击弹出可拖动面板列出匹配文本并高亮）

grow.py 只需 `from interactive_cloud import emit_interactive` 并在渲染后调用即可，
不依赖本模块也能正常产出 PNG / 词频表 / 字频表。
"""

import json
import os
import sys

CLOUD_W, CLOUD_H = 1600, 1000  # 词云画布尺寸（布局坐标空间，HTML 按此原样摆放）


def select_cloud_words(candidates, top_n=200, maxlen=0):
    """挑出词云要画的词：按 count 降序、过滤超长、截断 top_n。
    返回 [(word, count)] 有序列表。"""
    freqs = {}
    for w, cnt, ind, bind, _ in candidates:
        if maxlen and len(w) > maxlen:
            continue
        freqs[w] = cnt
    return sorted(freqs.items(), key=lambda x: -x[1])[:top_n]


def emit_interactive(prefix, out_dir, candidates, raw_texts, top_n, maxlen, layout,
                     standalone=False, complement_script=None):
    """写出互动词云。

    standalone=True  : 单文件内联 HTML（数据嵌进 HTML，双击即开，便于携带）。
    standalone=False : 外壳 HTML + 外部 data.js（HTML 恒定体积、可复用，数据任意大）。

    数据裁剪：fields 只保留「被任一词匹配引用的文本」并重映射索引（未匹配的原文不进产物，
    避免 payload 暴涨）；至于每词匹配到多少条、面板展示多少条，一律给全量——
    列表里每条小说地位平等、无主次，panel 自带滚动条即可承载，不再人为截断。
    """
    if layout is None:
        return
    cloud_words = select_cloud_words(candidates, top_n, maxlen)
    words_info = []
    placed = set()
    for (wf), fs, (py, px), orient, col in layout:
        w = wf[0]
        words_info.append({
            'word': w, 'x': int(px), 'y': int(py),
            'size': int(fs), 'color': col, 'rotate': bool(orient is not None),
        })
        placed.add(w)
    # 计算匹配：总数 + 截断例子 + 收集被引用文本
    used = set()
    raw_matches = {}
    for w, _ in cloud_words:
        if w not in placed:
            continue
        idxs = [i for i, t in enumerate(raw_texts) if w in t]
        if not idxs:
            continue
        raw_matches[w] = idxs
        used.update(idxs)
    # 只保留被引用文本并重映射索引（其余原始文本不进产物）
    ordered = sorted(used)
    remap = {old: new for new, old in enumerate(ordered)}
    fields = [raw_texts[i] for i in ordered]
    matches = {w: {'count': len(raw_matches[w]),
                   'examples': [remap[i] for i in raw_matches[w]]}
               for w in raw_matches}
    data = {'size': [CLOUD_W, CLOUD_H], 'fields': fields,
            'words': words_info, 'matches': matches}
    # 始终写出 json（供程序消费，与 HTML 同源裁剪）
    with open(os.path.join(out_dir, f'{prefix}_wordcloud.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    if standalone:
        html = build_cloud_html(data, complement_script)
    else:
        with open(os.path.join(out_dir, f'{prefix}_wordcloud.data.js'), 'w', encoding='utf-8') as f:
            f.write('window.GROW_DATA = ' + json.dumps(data, ensure_ascii=False) + ';')
        html = build_shell_html(prefix, complement_script)
    with open(os.path.join(out_dir, f'{prefix}_wordcloud.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    total = sum(m['count'] for m in matches.values())
    print(f'[{prefix}] 互动词云: {len(words_info)} 词, {total} 条匹配', file=sys.stderr)


# ---------------------------------------------------------------- 网页渲染
# 头部（结构 + 样式）：内联版与外壳版共用
_CLOUD_HEAD = r'''<!doctype html>
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
  #hint{color:#8a93a0;font-size:12.5px;flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}
  #search{margin-left:auto;width:190px;padding:6px 10px;border:1px solid #cdd3dc;border-radius:8px;
          font-size:13px;outline:none;flex:none;}
  #search:focus{border-color:#ff2d55;}
  #sres{position:fixed;top:46px;right:12px;width:250px;max-height:70vh;overflow:auto;background:#fff;
        border:1px solid #cdd3dc;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.18);display:none;
        z-index:130;padding:6px 0;font-size:13px;}
  #sres.show{display:block;}
  .sitem{padding:7px 14px;cursor:pointer;display:flex;justify-content:space-between;gap:10px;align-items:center;}
  .sitem:hover{background:#fff2f5;}
  .sitem .c{color:#ff2d55;font-weight:700;font-variant-numeric:tabular-nums;}
  .sempty{padding:9px 14px;color:#9aa3af;}
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
  <input id="search" placeholder="搜索词语…">
</div>
<div id="sres"></div>
<div id="stage"><div id="canvas"></div></div>
<div id="panel">
  <div id="phead"><span id="ptitle"></span><span id="pcnt"></span><span id="pclose">&times;</span></div>
  <div id="pbody"></div>
</div>
'''

# 引擎脚本（渲染 + 交互）：内联版与外壳版共用；数据来源由 __DATA_INIT__ 注入
_CLOUD_ENGINE = r'''<script>
const DATA = __DATA_INIT__;
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
  const m = DATA.matches[word] || {count: 0, examples: []};
  document.getElementById('ptitle').textContent = word;
  document.getElementById('pcnt').textContent = '匹配 ' + m.count + ' 条';
  const body = document.getElementById('pbody');
  body.innerHTML = '';
  if (!m.count){ body.innerHTML = '<div class="empty">（无匹配文本）</div>'; }
  else {
    const frag = document.createDocumentFragment();
    m.examples.forEach(i => {
      const d = document.createElement('div');
      d.className = 'row';
      d.innerHTML = highlight(DATA.fields[i], word);
      frag.appendChild(d);
    });
    body.appendChild(frag);
  }
  panel.classList.add('show');
  const r = selEl ? selEl.getBoundingClientRect() : {right: 200, top: 120};
  let x = r.right + 10;
  x = Math.min(x, window.innerWidth - panel.offsetWidth - 4);
  // 纵向强制居中屏幕中线：点屏幕下方的词时，面板也不会被挤出可视区
  let y = Math.max(46, (window.innerHeight - panel.offsetHeight) / 2);
  panel.style.left = x + 'px';
  panel.style.top = y + 'px';
}
document.getElementById('pclose').addEventListener('click', () => panel.classList.remove('show'));

// ---------------------------------------------------------------- 搜索栏
const search = document.getElementById('search');
const sres = document.getElementById('sres');
search.addEventListener('click', e => e.stopPropagation());
sres.addEventListener('click', e => e.stopPropagation());
search.addEventListener('input', () => {
  const kw = search.value.trim();
  if (!kw){ sres.classList.remove('show'); sres.innerHTML = ''; return; }
  const hits = Object.keys(DATA.matches)
    .filter(w => w.includes(kw))
    .sort((a, b) => DATA.matches[b].count - DATA.matches[a].count);
  if (!hits.length){ sres.innerHTML = '<div class="sempty">无匹配词语</div>'; sres.classList.add('show'); return; }
  const frag = document.createDocumentFragment();
  hits.forEach(w => {
    const d = document.createElement('div');
    d.className = 'sitem';
    d.innerHTML = '<span>' + esc(w) + '</span><span class="c">' + DATA.matches[w].count + '</span>';
    d.addEventListener('click', () => openPanel(w));
    frag.appendChild(d);
  });
  sres.innerHTML = '';
  sres.appendChild(frag);
  sres.classList.add('show');
});

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
  sres.classList.remove('show');
});
</script>
</body>
</html>
'''


def build_cloud_html(data, complement_script=None):
    """内联单文件版：数据直接嵌入 HTML（双击即开、便于携带）。

    complement_script: 可选的第二段 <script>（如补集 UI 补丁），为 None 时等同原版。
    """
    payload = json.dumps(data, ensure_ascii=False)
    html = _CLOUD_HEAD + _CLOUD_ENGINE.replace('__DATA_INIT__', payload)
    return html + (complement_script or '')


def build_shell_html(prefix, complement_script=None):
    """外壳版：数据来自外部 data.js，HTML 自身恒定体积、可复用。

    complement_script: 可选的第二段 <script>（如补集 UI 补丁），为 None 时等同原版。
    """
    src = f'<script src="{prefix}_wordcloud.data.js"></script>'
    html = _CLOUD_HEAD + src + _CLOUD_ENGINE.replace('__DATA_INIT__', 'window.GROW_DATA || {}')
    return html + (complement_script or '')
