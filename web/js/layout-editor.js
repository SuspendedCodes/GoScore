// GoScore overlay layout editor - a small slide-editor for the broadcast canvas.
//
// The overlay page has already drawn every graphic from sample matches replayed by the real engines, so each box
// here is the real thing. This module only adds the editing layer: it never touches the graphics' own markup.
// Everything is shown in 1920x1080 canvas units; boxes are placed through the shared layout engine, which scales
// each graphic's content to fit its box.
import { RIGID } from './layout-engine.js';

const NS = 'gs-ed';
const MIN_W = 40, MIN_H = 24, SNAP_PX = 7, HISTORY = 120;
const $el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const r1 = (n) => Math.round(n * 10) / 10;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

const CSS = `
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#0f141b;color:#e6ebf2;font:13px "Segoe UI",Roboto,Arial,sans-serif}
.${NS}-bar{position:fixed;left:0;right:0;top:0;height:46px;display:flex;align-items:center;gap:6px;padding:0 12px;background:#171d26;border-bottom:1px solid #2b3542;z-index:100000;box-sizing:border-box}
.${NS}-bar h1{font-size:15px;margin:0 10px 0 0;font-weight:700;white-space:nowrap}
.${NS}-bar .sep{width:1px;height:24px;background:#2b3542;margin:0 6px}
.${NS}-bar label{display:flex;align-items:center;gap:5px;color:#b8c2d0;cursor:pointer;white-space:nowrap}
.${NS}-bar .grow{flex:1}
.${NS}-btn{background:#232d3a;color:#e6ebf2;border:1px solid #3a4658;border-radius:5px;padding:6px 11px;cursor:pointer;font:inherit}
.${NS}-btn:hover:not(:disabled){background:#2c3a4b}.${NS}-btn:disabled{opacity:.4;cursor:default}
.${NS}-btn.primary{background:#2563eb;border-color:#2563eb;color:#fff}.${NS}-btn.primary:hover:not(:disabled){background:#1d4fd0}
.${NS}-btn.sm{padding:4px 8px}
.${NS}-status{color:#9fb0c3;font-size:12px;min-width:170px;text-align:right}.${NS}-status.ok{color:#7ee2a8}.${NS}-status.bad{color:#ff9b9b}
.${NS}-side{position:fixed;right:0;top:46px;bottom:0;width:300px;background:#171d26;border-left:1px solid #2b3542;z-index:100000;display:flex;flex-direction:column;box-sizing:border-box}
.${NS}-side h2{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#8294aa;margin:0;padding:10px 12px 6px}
.${NS}-layers{flex:1;overflow:auto;border-bottom:1px solid #2b3542;min-height:120px}
.${NS}-row{display:flex;align-items:center;gap:8px;padding:6px 12px;cursor:pointer;border-left:3px solid transparent}
.${NS}-row:hover{background:#1e2733}.${NS}-row.sel{background:#1c3358;border-left-color:#4c8dff}.${NS}-row.off .nm{opacity:.45}
.${NS}-row .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.${NS}-row .tag{font-size:10px;color:#7ee2a8}
.${NS}-row .eye{width:22px;height:20px;padding:0;border:none;background:none;color:#9fb0c3;cursor:pointer;font-size:12px}
.${NS}-props{padding:4px 12px 12px;overflow:auto;max-height:46%}
.${NS}-grid{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:6px 8px;align-items:center;margin-bottom:8px}
.${NS}-grid input{width:100%;box-sizing:border-box;background:#0f141b;border:1px solid #3a4658;color:#e6ebf2;border-radius:4px;padding:4px 6px;font:inherit}
.${NS}-tools{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px}
.${NS}-note{color:#8294aa;font-size:11.5px;line-height:1.45;margin:6px 0 0}
.${NS}-bg{position:fixed;z-index:0;background:repeating-conic-gradient(#222b37 0 25%,#1a222c 0 50%) 0 0/24px 24px;outline:1px solid #3a4658}
#stage{overflow:hidden}
.${NS}-sel{position:fixed;z-index:50000;transform-origin:0 0;pointer-events:none}
.${NS}-box{position:absolute;box-sizing:border-box;border:1px solid rgba(110,170,255,.65);pointer-events:auto;cursor:move}
.${NS}-box:hover{border-color:#8fc0ff;background:rgba(80,140,255,.07)}
.${NS}-box.sel{border:2px solid #4c8dff;background:rgba(76,141,255,.06)}
.${NS}-box .tagname{position:absolute;left:-1px;bottom:100%;background:#4c8dff;color:#fff;font:600 11px "Segoe UI",Arial,sans-serif;padding:1px 6px;white-space:nowrap;pointer-events:none;transform-origin:0 100%}
.${NS}-box:not(.sel) .tagname{display:none}.${NS}-box:hover .tagname{display:block;background:#5a7aa8}
.${NS}-h{position:absolute;background:#fff;border:1px solid #2563eb;box-sizing:border-box;pointer-events:auto}
.${NS}-guide{position:absolute;background:#ff4fa3;pointer-events:none}
.${NS}-marq{position:absolute;border:1px dashed #8fc0ff;background:rgba(80,140,255,.12);pointer-events:none}
.${NS}-dim{position:absolute;background:#0b1220;color:#cfe0ff;font:600 11px "Segoe UI",Arial,sans-serif;padding:2px 6px;border-radius:3px;pointer-events:none;white-space:nowrap;transform-origin:0 0}
.${NS}-safe{position:absolute;border:1px dashed rgba(255,214,102,.55);pointer-events:none;box-sizing:border-box}
.${NS}-third{position:absolute;background:rgba(255,255,255,.18);pointer-events:none}
`;

export function startEditor({ stage, sport, engine, ids, labels }) {
  const present = ids.filter((id) => document.getElementById(id));
  const label = (id) => (labels && labels[id]) || id;
  const model = new Map();      // id -> box shown in the editor (explicit box, or the natural position)
  const explicit = new Set();   // ids that have a saved/edited box
  const hidden = new Set();     // ids hidden in the editor only
  let sel = [];                 // selected ids
  let scale = 1, origin = { x: 0, y: 0 };
  let saved = '{}', history = [], redo = [], status = '';
  const opts = { snap: true, safe: true, thirds: false };

  const style = $el('style'); style.textContent = CSS; document.head.append(style);
  document.body.classList.add('gs-layout-edit');

  // ---- initial boxes: natural (stylesheet) positions first, then the saved layout on top ----
  engine.setLayout({});
  const natural = new Map();
  present.forEach((id) => { const b = engine.naturalBox(id); if (b) natural.set(id, b); });
  const order = present.filter((id) => natural.has(id));
  order.forEach((id) => model.set(id, { ...natural.get(id) }));
  // Start with the always-on graphics only: stacking every panel at once is unreadable. Panels appear when selected or shown from the list.
  order.forEach((id) => { if (!RIGID.has(id)) hidden.add(id); });

  function boxOf(id) { return model.get(id); }
  function toLayout() { const o = {}; explicit.forEach((id) => { const b = model.get(id); if (b) o[id] = { x: r1(b.x), y: r1(b.y), w: r1(b.w), h: r1(b.h), ...(b.z ? { z: b.z } : {}) }; }); return o; }
  function applyAll() { const l = toLayout(); engine.setLayout(l); order.forEach((id) => { const el = document.getElementById(id); if (el) el.style.visibility = hidden.has(id) ? 'hidden' : ''; }); }
  function load(layout) {
    explicit.clear();
    order.forEach((id) => model.set(id, { ...natural.get(id) }));
    for (const [id, b] of Object.entries(layout || {})) if (model.has(id)) { model.set(id, { x: b.x, y: b.y, w: b.w, h: b.h, ...(b.z ? { z: b.z } : {}) }); explicit.add(id); }
    applyAll();
  }

  // ---- history ----
  const snapshot = () => JSON.stringify(toLayout());
  let committed = snapshot();
  function commit() {
    const now = snapshot();
    if (now === committed) return;
    history.push(committed); if (history.length > HISTORY) history.shift();
    redo = []; committed = now; refresh();
  }
  function undo() { if (!history.length) return; redo.push(committed); committed = history.pop(); load(JSON.parse(committed)); refresh(); }
  function redoFn() { if (!redo.length) return; history.push(committed); committed = redo.pop(); load(JSON.parse(committed)); refresh(); }

  // ---- shell ----
  const bar = $el('div', `${NS}-bar`);
  bar.innerHTML = `<h1>Layout editor <span style="font-weight:400;color:#8294aa">· ${sport === 'football' ? 'Football' : 'Cricket'}</span></h1>
    <button class="${NS}-btn sm" data-a="undo" title="Undo (Ctrl+Z)">Undo</button><button class="${NS}-btn sm" data-a="redo" title="Redo (Ctrl+Y)">Redo</button><span class="sep"></span>
    <label><input type="checkbox" data-o="snap" checked> Snap</label><label><input type="checkbox" data-o="safe" checked> Safe area</label><label><input type="checkbox" data-o="thirds"> Thirds</label>
    <span class="grow"></span><span class="${NS}-status" data-s></span>
    <button class="${NS}-btn" data-a="revert" title="Discard unsaved changes">Revert</button><button class="${NS}-btn" data-a="resetall" title="Back to the built-in positions">Reset all</button>
    <button class="${NS}-btn primary" data-a="save">Save layout</button><button class="${NS}-btn" data-a="done">Close editor</button>`;
  const side = $el('aside', `${NS}-side`);
  side.innerHTML = `<h2>Graphics</h2><div style="padding:0 12px 6px;display:flex;gap:6px"><button class="${NS}-btn sm" data-v="all">Show all</button><button class="${NS}-btn sm" data-v="none">Hide all but selected</button></div><div class="${NS}-layers"></div><h2>Selection</h2><div class="${NS}-props"></div>`;
  const bg = $el('div', `${NS}-bg`);
  const layer = $el('div', `${NS}-sel`);
  document.body.append(bg, bar, side, layer);
  stage.style.position = 'absolute';
  const layers = side.querySelector(`.${NS}-layers`), props = side.querySelector(`.${NS}-props`), statusEl = bar.querySelector('[data-s]');

  function say(t, kind) { statusEl.textContent = t; statusEl.className = `${NS}-status ${kind || ''}`; }

  function place() {
    const W = innerWidth - 300 - 32, H = innerHeight - 46 - 32;
    scale = Math.min(W / 1920, H / 1080);
    origin = { x: 16 + (W - 1920 * scale) / 2, y: 46 + 16 + (H - 1080 * scale) / 2 };
    stage.style.transform = `scale(${scale})`; stage.style.left = origin.x + 'px'; stage.style.top = origin.y + 'px'; stage.style.zIndex = 1;
    Object.assign(bg.style, { left: origin.x + 'px', top: origin.y + 'px', width: 1920 * scale + 'px', height: 1080 * scale + 'px' });
    Object.assign(layer.style, { left: origin.x + 'px', top: origin.y + 'px', width: '1920px', height: '1080px', transform: `scale(${scale})` });
    draw();
  }

  // ---- drawing the selection layer ----
  const zOf = (id) => (boxOf(id) && boxOf(id).z) || 0;
  const stacking = () => order.slice().sort((a, b) => zOf(a) - zOf(b) || order.indexOf(a) - order.indexOf(b));
  const px = (n) => n / scale;     // screen pixels -> canvas units
  let guides = [], marquee = null, dimTip = null;

  function draw() {
    layer.replaceChildren();
    if (opts.safe) for (const [m, ] of [[0.05], [0.1]]) { const s = $el('div', `${NS}-safe`); Object.assign(s.style, { left: 1920 * m + 'px', top: 1080 * m + 'px', width: 1920 * (1 - 2 * m) + 'px', height: 1080 * (1 - 2 * m) + 'px', opacity: m === 0.05 ? 1 : .55 }); layer.append(s); }
    if (opts.thirds) for (const f of [1 / 3, 2 / 3]) { const a = $el('div', `${NS}-third`), b = $el('div', `${NS}-third`); Object.assign(a.style, { left: 1920 * f + 'px', top: 0, width: px(1) + 'px', height: '1080px' }); Object.assign(b.style, { top: 1080 * f + 'px', left: 0, height: px(1) + 'px', width: '1920px' }); layer.append(a, b); }
    stacking().forEach((id, i) => {
      if (hidden.has(id)) return;
      const b = boxOf(id), d = $el('div', `${NS}-box${sel.includes(id) ? ' sel' : ''}`);
      Object.assign(d.style, { left: b.x + 'px', top: b.y + 'px', width: b.w + 'px', height: b.h + 'px', zIndex: i + 1, borderWidth: px(sel.includes(id) ? 2 : 1) + 'px' });
      d.dataset.id = id;
      const t = $el('div', 'tagname', label(id)); t.style.transform = `scale(${px(1)})`; d.append(t);
      layer.append(d);
    });
    if (sel.length === 1 && !hidden.has(sel[0])) {
      const b = boxOf(sel[0]), hs = px(9);
      for (const [dir, cx, cy, cur] of [['nw', 0, 0, 'nwse'], ['n', .5, 0, 'ns'], ['ne', 1, 0, 'nesw'], ['e', 1, .5, 'ew'], ['se', 1, 1, 'nwse'], ['s', .5, 1, 'ns'], ['sw', 0, 1, 'nesw'], ['w', 0, .5, 'ew']]) {
        const h = $el('div', `${NS}-h`); h.dataset.dir = dir;
        Object.assign(h.style, { left: b.x + b.w * cx - hs / 2 + 'px', top: b.y + b.h * cy - hs / 2 + 'px', width: hs + 'px', height: hs + 'px', cursor: cur + '-resize', zIndex: 9000, borderWidth: px(1) + 'px' });
        layer.append(h);
      }
    }
    guides.forEach((g) => { const e = $el('div', `${NS}-guide`); Object.assign(e.style, g.v ? { left: g.p - px(.5) + 'px', top: 0, width: px(1) + 'px', height: '1080px' } : { top: g.p - px(.5) + 'px', left: 0, height: px(1) + 'px', width: '1920px' }); e.style.zIndex = 9500; layer.append(e); });
    if (marquee) { const e = $el('div', `${NS}-marq`); Object.assign(e.style, { left: marquee.x + 'px', top: marquee.y + 'px', width: marquee.w + 'px', height: marquee.h + 'px', zIndex: 9600 }); layer.append(e); }
    if (dimTip) { const e = $el('div', `${NS}-dim`, dimTip.text); Object.assign(e.style, { left: dimTip.x + 'px', top: dimTip.y + 'px', zIndex: 9700, transform: `scale(${px(1)})` }); layer.append(e); }
  }

  // ---- side panel ----
  function renderLayers() {
    layers.replaceChildren();
    stacking().reverse().forEach((id) => {
      const row = $el('div', `${NS}-row${sel.includes(id) ? ' sel' : ''}${hidden.has(id) ? ' off' : ''}`);
      row.innerHTML = `<span class="nm"></span>${explicit.has(id) ? '<span class="tag">placed</span>' : ''}<button class="eye" title="Show / hide in the editor only">${hidden.has(id) ? 'Show' : 'Hide'}</button>`;
      row.querySelector('.nm').textContent = label(id);
      row.addEventListener('click', (e) => { if (e.target.closest('.eye')) { hidden.has(id) ? hidden.delete(id) : hidden.add(id); sel = sel.filter((x) => x !== id); applyAll(); refresh(); return; } select(id, e.shiftKey || e.ctrlKey || e.metaKey); });
      layers.append(row);
    });
  }
  function renderProps() {
    props.replaceChildren();
    if (!sel.length) { props.append($el('p', `${NS}-note`, 'Click a graphic to select it. Drag to move, drag a handle to resize. Content always scales to fit inside its box.<br><br>Shift-click or drag on empty space to select several. Arrow keys nudge (Shift = 10 px). Delete puts the graphic back at its built-in position.')); return; }
    const one = sel.length === 1 ? sel[0] : null, b = one && boxOf(one);
    if (one) {
      const g = $el('div', `${NS}-grid`);
      g.innerHTML = ['x', 'y', 'w', 'h'].map((k) => `<label>${k.toUpperCase()}</label><input type="number" step="1" data-k="${k}" value="${Math.round(b[k])}">`).join('');
      g.querySelectorAll('input').forEach((inp) => inp.addEventListener('change', () => { const k = inp.dataset.k, nb = { ...boxOf(one), [k]: +inp.value || 0 }; setBox(one, constrain(one, nb, k === 'w' || k === 'h' ? 'size' : 'move', k)); commit(); }));
      props.append(g);
    } else props.append($el('p', `${NS}-note`, `${sel.length} graphics selected`));
    const tools = $el('div', `${NS}-tools`);
    const T = (t, a, title, dis) => { const bt = $el('button', `${NS}-btn sm`, t); bt.title = title || t; bt.dataset.a = a; if (dis) bt.disabled = true; tools.append(bt); };
    props.append($el('h2', null, 'Align')); T('Left', 'al-l'); T('Centre', 'al-c'); T('Right', 'al-r'); T('Top', 'al-t'); T('Middle', 'al-m'); T('Bottom', 'al-b'); T('Space across', 'dist-h', 'Distribute horizontally', sel.length < 3); T('Space down', 'dist-v', 'Distribute vertically', sel.length < 3);
    props.append(tools);
    const t2 = $el('div', `${NS}-tools`);
    const T2 = (t, a, title) => { const bt = $el('button', `${NS}-btn sm`, t); bt.title = title || t; bt.dataset.a = a; t2.append(bt); };
    props.append($el('h2', null, 'Arrange')); T2('Bring to front', 'z-front'); T2('Forward', 'z-fwd'); T2('Backward', 'z-back'); T2('Send to back', 'z-bottom');
    props.append(t2);
    const t3 = $el('div', `${NS}-tools`); const rs = $el('button', `${NS}-btn sm`, 'Reset to built-in position'); rs.dataset.a = 'reset'; t3.append(rs); props.append(t3);
    if (one) { const el = document.getElementById(one), sc = el && el.dataset.gsScale; if (sc && explicit.has(one)) props.append($el('p', `${NS}-note`, `Content scale in this box: ${Math.round(sc * 100)}%${RIGID.has(one) ? ' (aspect ratio is kept)' : ''}`)); }
    props.querySelectorAll('button[data-a]').forEach((bt) => bt.addEventListener('click', () => action(bt.dataset.a)));
  }
  function refresh() { renderLayers(); renderProps(); draw(); bar.querySelector('[data-a=undo]').disabled = !history.length; bar.querySelector('[data-a=redo]').disabled = !redo.length; dirtyStatus(); }
  function dirtyStatus() { if (status === 'busy') return; const d = snapshot() !== saved; say(d ? 'Unsaved changes' : 'All changes saved', d ? '' : 'ok'); }

  // ---- model operations ----
  function select(id, add) { if (hidden.has(id)) { hidden.delete(id); applyAll(); } if (add) sel = sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]; else sel = [id]; refresh(); }
  function setBox(id, nb) { model.set(id, nb); explicit.add(id); engine.setBox(id, { x: nb.x, y: nb.y, w: nb.w, h: nb.h, ...(nb.z ? { z: nb.z } : {}) }, true); draw(); renderPropsValues(); }
  function renderPropsValues() { if (sel.length !== 1) return; const b = boxOf(sel[0]); props.querySelectorAll('.' + NS + '-grid input').forEach((i) => { if (document.activeElement !== i) i.value = Math.round(b[i.dataset.k]); }); }
  function aspectOf(id) { const a = engine.aspect(id); return a || (boxOf(id).w / boxOf(id).h); }
  // keep a box on the canvas, above the minimum size, and (for rigid graphics) hugging the content's aspect ratio
  function constrain(id, nb, mode, key) {
    let { x, y, w, h } = nb;
    w = clamp(w, MIN_W, 1920); h = clamp(h, MIN_H, 1080);
    if (mode === 'size' && RIGID.has(id)) { const a = aspectOf(id); if (key === 'h') w = h * a; else h = w / a; if (w > 1920) { w = 1920; h = w / a; } if (h > 1080) { h = 1080; w = h * a; } }
    x = clamp(x, 0, 1920 - w); y = clamp(y, 0, 1080 - h);
    return { ...boxOf(id), x: r1(x), y: r1(y), w: r1(w), h: r1(h) };
  }
  function bounds(ids2) { const bs = ids2.map(boxOf); const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y)); return { x, y, w: Math.max(...bs.map((b) => b.x + b.w)) - x, h: Math.max(...bs.map((b) => b.y + b.h)) - y }; }
  function moveBy(ids2, dx, dy) { const bb = bounds(ids2); dx = clamp(dx, -bb.x, 1920 - bb.x - bb.w); dy = clamp(dy, -bb.y, 1080 - bb.y - bb.h); ids2.forEach((id) => { const b = boxOf(id); setBox(id, { ...b, x: r1(b.x + dx), y: r1(b.y + dy) }); }); }

  function action(a) {
    if (!sel.length && !['undo', 'redo'].includes(a)) return;
    const bs = sel.map((id) => [id, boxOf(id)]);
    if (a.startsWith('al-')) {
      const ref = sel.length === 1 ? { x: 0, y: 0, w: 1920, h: 1080 } : bounds(sel);
      for (const [id, b] of bs) {
        let { x, y } = b;
        if (a === 'al-l') x = ref.x; else if (a === 'al-r') x = ref.x + ref.w - b.w; else if (a === 'al-c') x = ref.x + (ref.w - b.w) / 2;
        else if (a === 'al-t') y = ref.y; else if (a === 'al-b') y = ref.y + ref.h - b.h; else if (a === 'al-m') y = ref.y + (ref.h - b.h) / 2;
        setBox(id, { ...b, x: r1(x), y: r1(y) });
      }
    } else if (a === 'dist-h' || a === 'dist-v') {
      const h = a === 'dist-h', k = h ? 'x' : 'y', s = h ? 'w' : 'h';
      const list = bs.slice().sort((p, q) => p[1][k] - q[1][k]);
      const first = list[0][1], last = list[list.length - 1][1];
      const total = list.reduce((t, [, b]) => t + b[s], 0), gap = (last[k] + last[s] - first[k] - total) / (list.length - 1);
      let pos = first[k]; list.forEach(([id, b]) => { setBox(id, { ...b, [k]: r1(pos) }); pos += b[s] + gap; });
    } else if (a.startsWith('z-')) arrange(a);
    else if (a === 'reset') { sel.forEach((id) => { explicit.delete(id); model.set(id, { ...natural.get(id) }); engine.setBox(id, null); }); }
    commit(); refresh();
  }
  function arrange(a) {
    const list = stacking(); const moving = sel.slice();
    let next;
    if (a === 'z-front') next = [...list.filter((i) => !moving.includes(i)), ...list.filter((i) => moving.includes(i))];
    else if (a === 'z-bottom') next = [...list.filter((i) => moving.includes(i)), ...list.filter((i) => !moving.includes(i))];
    else { next = list.slice(); const dir = a === 'z-fwd' ? 1 : -1; const idxs = moving.map((i) => next.indexOf(i)).sort((p, q) => dir * (q - p)); for (const i0 of idxs) { const j = i0 + dir; if (j < 0 || j >= next.length || moving.includes(next[j])) continue; [next[i0], next[j]] = [next[j], next[i0]]; } }
    next.forEach((id, i) => { const want = i + 1, b = boxOf(id); if ((b.z || 0) === want || (!explicit.has(id) && !moving.includes(id) && !(b.z))) return; setBox(id, { ...b, z: want }); });
    // moved boxes get an explicit z only when their position in the stack actually changed
    moving.forEach((id) => { const i = next.indexOf(id); const b = boxOf(id); if ((b.z || 0) !== i + 1) setBox(id, { ...b, z: i + 1 }); });
  }

  // ---- pointer interaction ----
  const toCanvas = (e) => ({ x: (e.clientX - origin.x) / scale, y: (e.clientY - origin.y) / scale });
  let drag = null;

  function snapTargets(exclude) {
    const xs = [0, 960, 1920, 96, 1824, 192, 1728], ys = [0, 540, 1080, 54, 1026, 108, 972];
    order.forEach((id) => { if (exclude.includes(id) || hidden.has(id)) return; const b = boxOf(id); xs.push(b.x, b.x + b.w / 2, b.x + b.w); ys.push(b.y, b.y + b.h / 2, b.y + b.h); });
    return { xs, ys };
  }
  function snapAxis(vals, targets, thr) {      // vals: candidate edges of the moving box; returns {delta, at}
    let best = null;
    for (const v of vals) for (const t of targets) { const d = t - v; if (Math.abs(d) <= thr && (!best || Math.abs(d) < Math.abs(best.delta))) best = { delta: d, at: t }; }
    return best;
  }

  layer.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const p = toCanvas(e), hnd = e.target.closest(`.${NS}-h`), boxEl = e.target.closest(`.${NS}-box`);
    layer.setPointerCapture?.(e.pointerId);
    if (hnd && sel.length === 1) {
      const id = sel[0], b = { ...boxOf(id) };
      drag = { kind: 'resize', id, dir: hnd.dataset.dir, start: p, b0: b, targets: snapTargets([id]), moved: false };
    } else if (boxEl) {
      let id = boxEl.dataset.id;
      if (e.altKey) { const under = document.elementsFromPoint(e.clientX, e.clientY).filter((n) => n.classList && n.classList.contains(`${NS}-box`)).map((n) => n.dataset.id); const i = under.indexOf(sel[0]); id = under[(i + 1) % under.length] || id; }
      if (e.shiftKey || e.ctrlKey || e.metaKey) { select(id, true); drag = null; return; }
      if (!sel.includes(id)) { sel = [id]; refresh(); }
      drag = { kind: 'move', start: p, ids: sel.slice(), orig: sel.map((i) => ({ ...boxOf(i) })), targets: snapTargets(sel), moved: false };
    } else {
      if (!(e.shiftKey)) { sel = []; refresh(); }
      drag = { kind: 'marquee', start: p, base: sel.slice() };
    }
    e.preventDefault();
  });
  layer.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const p = toCanvas(e), dx = p.x - drag.start.x, dy = p.y - drag.start.y, thr = px(SNAP_PX), snap = opts.snap && !e.altKey;
    guides = []; dimTip = null;
    if (drag.kind === 'move') {
      if (!drag.moved && Math.hypot(dx, dy) * scale < 3) return;
      drag.moved = true;
      const o0 = drag.orig, minx = Math.min(...o0.map((b) => b.x)), miny = Math.min(...o0.map((b) => b.y));
      const maxx = Math.max(...o0.map((b) => b.x + b.w)), maxy = Math.max(...o0.map((b) => b.y + b.h));
      let ndx = dx, ndy = dy;
      if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) ndy = 0; else ndx = 0; }
      if (snap) {
        const sx = snapAxis([minx + ndx, (minx + maxx) / 2 + ndx, maxx + ndx], drag.targets.xs, thr), sy = snapAxis([miny + ndy, (miny + maxy) / 2 + ndy, maxy + ndy], drag.targets.ys, thr);
        if (sx) { ndx += sx.delta; guides.push({ v: true, p: sx.at }); } if (sy) { ndy += sy.delta; guides.push({ v: false, p: sy.at }); }
      }
      ndx = clamp(ndx, -minx, 1920 - maxx); ndy = clamp(ndy, -miny, 1080 - maxy);
      drag.ids.forEach((id, i) => { const b = drag.orig[i]; setBox(id, { ...boxOf(id), x: r1(b.x + ndx), y: r1(b.y + ndy) }); });
      const bb = bounds(drag.ids); dimTip = { x: bb.x, y: bb.y + bb.h + px(6), text: `${Math.round(bb.x)}, ${Math.round(bb.y)}` };
    } else if (drag.kind === 'resize') {
      const { id, dir, b0 } = drag, rigid = RIGID.has(id), keep = rigid || e.shiftKey, ratio = rigid ? aspectOf(id) : b0.w / b0.h, fromC = e.altKey;
      let l = b0.x, t = b0.y, r = b0.x + b0.w, bt = b0.y + b0.h;
      const mx = dx * (fromC ? 2 : 1), my = dy * (fromC ? 2 : 1);
      if (dir.includes('w')) l += mx * (fromC ? .5 : 1); if (dir.includes('e')) r += mx * (fromC ? .5 : 1);
      if (dir.includes('n')) t += my * (fromC ? .5 : 1); if (dir.includes('s')) bt += my * (fromC ? .5 : 1);
      if (fromC) { if (dir.includes('w')) r = b0.x + b0.w - (l - b0.x); if (dir.includes('e')) l = b0.x - (r - (b0.x + b0.w)); if (dir.includes('n')) bt = b0.y + b0.h - (t - b0.y); if (dir.includes('s')) t = b0.y - (bt - (b0.y + b0.h)); }
      if (snap && !keep) {
        if (dir.includes('w')) { const s = snapAxis([l], drag.targets.xs, thr); if (s) { l += s.delta; guides.push({ v: true, p: s.at }); } }
        if (dir.includes('e')) { const s = snapAxis([r], drag.targets.xs, thr); if (s) { r += s.delta; guides.push({ v: true, p: s.at }); } }
        if (dir.includes('n')) { const s = snapAxis([t], drag.targets.ys, thr); if (s) { t += s.delta; guides.push({ v: false, p: s.at }); } }
        if (dir.includes('s')) { const s = snapAxis([bt], drag.targets.ys, thr); if (s) { bt += s.delta; guides.push({ v: false, p: s.at }); } }
      }
      l = clamp(l, 0, 1920); r = clamp(r, 0, 1920); t = clamp(t, 0, 1080); bt = clamp(bt, 0, 1080);
      let w = Math.max(MIN_W, r - l), h = Math.max(MIN_H, bt - t);
      if (keep) {   // keep the aspect ratio; the dragged corner/edge decides which side leads
        const horiz = dir === 'e' || dir === 'w', vert = dir === 'n' || dir === 's';
        if (horiz) h = w / ratio; else if (vert) w = h * ratio; else if (w / ratio > h) h = w / ratio; else w = h * ratio;
        w = Math.max(MIN_W, w); h = Math.max(MIN_H, w / ratio);
      }
      // anchor the opposite side
      let nx = dir.includes('w') ? (fromC ? b0.x + b0.w / 2 - w / 2 : b0.x + b0.w - w) : (fromC ? b0.x + b0.w / 2 - w / 2 : b0.x);
      let ny = dir.includes('n') ? (fromC ? b0.y + b0.h / 2 - h / 2 : b0.y + b0.h - h) : (fromC ? b0.y + b0.h / 2 - h / 2 : b0.y);
      if (dir === 'n' || dir === 's') nx = fromC || !keep ? b0.x + (b0.w - w) * (keep ? .5 : 0) : b0.x + (b0.w - w) / 2;
      if (dir === 'e' || dir === 'w') ny = keep ? b0.y + (b0.h - h) / 2 : b0.y;
      if (w > 1920) { w = 1920; if (keep) h = w / ratio; } if (h > 1080) { h = 1080; if (keep) w = h * ratio; }
      nx = clamp(nx, 0, 1920 - w); ny = clamp(ny, 0, 1080 - h);
      drag.moved = true;
      setBox(id, { ...boxOf(id), x: r1(nx), y: r1(ny), w: r1(w), h: r1(h) });
      dimTip = { x: nx, y: ny + h + px(6), text: `${Math.round(w)} × ${Math.round(h)}` };
    } else if (drag.kind === 'marquee') {
      const x = Math.min(p.x, drag.start.x), y = Math.min(p.y, drag.start.y), w = Math.abs(dx), h = Math.abs(dy);
      marquee = { x, y, w, h };
      const hit = order.filter((id) => { if (hidden.has(id)) return false; const b = boxOf(id); return b.x < x + w && b.x + b.w > x && b.y < y + h && b.y + b.h > y; });
      sel = [...new Set([...drag.base, ...hit])];
    }
    draw();
  });
  const finish = () => {
    if (!drag) return;
    const was = drag; drag = null; guides = []; dimTip = null; marquee = null;
    if (was.kind === 'move' || was.kind === 'resize') commit();
    refresh();
  };
  layer.addEventListener('pointerup', finish); layer.addEventListener('pointercancel', finish);

  addEventListener('keydown', (e) => {
    if (e.target.closest && e.target.closest('input,textarea')) { if (e.key === 'Enter') e.target.blur(); return; }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redoFn() : undo(); }
    else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redoFn(); }
    else if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); sel = order.filter((i) => !hidden.has(i)); refresh(); }
    else if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { sel = []; refresh(); }
    else if (sel.length && (e.key === 'Delete' || e.key === 'Backspace')) { e.preventDefault(); action('reset'); }
    else if (sel.length && e.key.startsWith('Arrow')) {
      e.preventDefault(); const st = e.shiftKey ? 10 : 1;
      moveBy(sel, e.key === 'ArrowLeft' ? -st : e.key === 'ArrowRight' ? st : 0, e.key === 'ArrowUp' ? -st : e.key === 'ArrowDown' ? st : 0);
      clearTimeout(finish.t); finish.t = setTimeout(() => { commit(); }, 350);
    }
  });

  side.addEventListener('click', (e) => {
    const v = e.target.dataset && e.target.dataset.v; if (!v) return;
    if (v === 'all') hidden.clear(); else order.forEach((id) => { if (!sel.includes(id)) hidden.add(id); });
    applyAll(); refresh();
  });

  // ---- toolbar ----
  bar.addEventListener('change', (e) => { const o = e.target.dataset && e.target.dataset.o; if (o) { opts[o] = e.target.checked; draw(); } });
  bar.addEventListener('click', (e) => {
    const a = e.target.closest('[data-a]') && e.target.closest('[data-a]').dataset.a;
    if (a === 'undo') undo(); else if (a === 'redo') redoFn(); else if (a === 'save') save();
    else if (a === 'revert') { if (snapshot() === saved || confirm('Discard the changes since the last save?')) { load(JSON.parse(saved)); committed = snapshot(); history = []; redo = []; refresh(); } }
    else if (a === 'resetall') { if (!explicit.size && snapshot() === saved) return; if (confirm('Put every graphic back at its built-in position? (Press Save layout to keep this.)')) { explicit.clear(); order.forEach((id) => model.set(id, { ...natural.get(id) })); engine.setLayout({}); commit(); refresh(); } }
    else if (a === 'done') { if (snapshot() !== saved && !confirm('You have unsaved changes. Close the editor anyway?')) return; const u = new URL(location.href); u.searchParams.delete('edit'); onbeforeunload = null; location.href = u.toString(); }
  });
  async function save() {
    status = 'busy'; say('Saving...');
    try {
      const body = JSON.stringify({ layout: toLayout() });
      const r = await fetch(`/api/layout/${sport}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body });
      if (!r.ok) throw new Error('server answered ' + r.status);
      const d = await r.json();
      saved = JSON.stringify(d.layout || {}); status = '';
      load(d.layout || {}); committed = snapshot(); refresh(); say('Saved. The live overlay picks it up within a few seconds.', 'ok');
    } catch (err) { status = ''; say('Could not save: ' + err.message, 'bad'); }
  }
  onbeforeunload = () => (snapshot() !== saved ? 'Unsaved layout changes' : undefined);
  addEventListener('resize', place);

  // ---- go ----
  fetch(`/api/layout/${sport}`, { cache: 'no-store' }).then((r) => r.json()).then((d) => { load(d.layout || {}); saved = snapshot(); committed = saved; })
    .catch(() => say('Could not read the saved layout - starting from the built-in positions.', 'bad')).then(() => { place(); refresh(); });
  window.__gsEditor = { model, explicit, engine, select, order, setBox, commit, action, get sel() { return sel; } };
}
