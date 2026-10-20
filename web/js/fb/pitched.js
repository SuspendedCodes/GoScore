// Drag-and-drop pitch editor: arrange the XI by hand, pick a formation, save it as one event (pitch_set).
// What you see here is exactly what the formation overlay shows (same coordinates, same aspect ratio).
import { h, toast, select } from '../common.js';
import { FORMATIONS, autoLayout, pitchPlayers, colorText } from './fbcommon.js';

const CSS = `
.pe{display:grid;gap:8px}.pe .pitch{position:relative;width:100%;aspect-ratio:1180/640;background:repeating-linear-gradient(90deg,#1f7a3d 0 7.6%,#228443 7.6% 15.2%);border-radius:10px;border:2px solid #0b3d1c;touch-action:none;user-select:none;overflow:hidden}
.pe .ln{position:absolute;border:2px solid rgba(255,255,255,.55);pointer-events:none}.pe .mid{left:50%;top:0;bottom:0;border-width:0 0 0 2px}.pe .circ{left:50%;top:50%;width:13%;aspect-ratio:1;border-radius:50%;translate:-50% -50%}
.pe .boxl{left:0;top:25%;height:50%;width:15%;border-left:none}.pe .boxr{right:0;top:25%;height:50%;width:15%;border-right:none}
.pe .pd{position:absolute;translate:-50% -50%;width:92px;text-align:center;cursor:grab;touch-action:none}.pe .pd.drag{cursor:grabbing;z-index:5}
.pe .pd .d{width:44px;height:44px;margin:0 auto;border-radius:50%;background:var(--t);color:var(--tx);border:3px solid #fff;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;box-shadow:0 3px 8px rgba(0,0,0,.45)}
.pe .pd.sub .d{border-color:#51cf66}.pe .pd .n{font-size:12px;font-weight:800;color:#fff;text-shadow:0 1px 3px #000;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pe .dirhint{font-size:.78rem;opacity:.7}`;
let cssDone = false;

export function pitchEditor({ getState, post, tid }) {
  if (!cssDone) { document.head.append(h('style', {}, CSS)); cssDone = true; }
  const el = h('div', { class: 'pe' });
  let local = null;                // {pid: {x,y}} while dragging / before saving
  let fm = null;                   // formation chosen but not saved
  let dirty = false;
  const pitch = h('div', { class: 'pitch' }, h('div', { class: 'ln mid' }), h('div', { class: 'ln circ' }), h('div', { class: 'ln boxl' }), h('div', { class: 'ln boxr' }));
  const fsel = select([...FORMATIONS.map(f => ({ value: f, label: f })), { value: '__custom', label: 'custom…' }], '4-4-2');
  const save = h('button', { class: 'btn primary', onclick: doSave }, 'Save layout');
  const reset = h('button', { class: 'btn', title: 'Forget dragged positions and use the formation default', onclick: async () => { const r = await post({ type: 'pitch_set', team: tid, reset: true }); if (r) { local = null; fm = null; dirty = false; toast('Layout reset', 'ok'); } } }, 'Reset to formation');
  const info = h('span', { class: 'mut small' });
  el.append(h('div', { class: 'row' }, h('b', {}, 'Formation'), fsel, save, reset, info), pitch,
    h('div', { class: 'dirhint' }, 'Drag players to where they play. Saved layouts go straight to the formation overlay. Substitutes take the position of the player they replace — then drag them wherever you like and save again.'));
  fsel.onchange = () => {
    let v = fsel.value;
    if (v === '__custom') { v = (prompt('Formation, e.g. 4-2-3-1', '4-4-2') || '').trim(); if (!/^\d(-\d){1,5}$/.test(v)) { toast('Use a format like 4-2-3-1', 'bad'); refresh(true); return; } }
    fm = v;
    const S = getState(); const n = Math.max(S.teams[tid].players.filter(p => p.started).length, 1); const auto = autoLayout(v, n);
    local = {}; for (const pp of S.teams[tid].players) if (pp.status === 'on' && pp.slot != null && auto[pp.slot]) local[pp.id] = { x: auto[pp.slot].x, y: auto[pp.slot].y };
    dirty = true; draw();
  };
  async function doSave() {
    const S = getState(); const positions = {};
    for (const q of pitchPlayers(S, tid)) { const l = local && local[q.p.id]; positions[q.p.id] = { x: +(l ? l.x : q.x).toFixed(1), y: +(l ? l.y : q.y).toFixed(1) }; }
    const ev = { type: 'pitch_set', team: tid, positions }; if (fm) ev.formation = fm;
    const r = await post(ev); if (r) { local = null; fm = null; dirty = false; toast('Layout saved', 'ok'); }
  }
  function draw() {
    const S = getState(); const t = S.teams[tid];
    pitch.querySelectorAll('.pd').forEach(n => n.remove());
    el.style.setProperty('--t', t.color); el.style.setProperty('--tx', t.color2 || colorText(t.color));
    for (const q of pitchPlayers(S, tid)) {
      const l = local && local[q.p.id]; const x = l ? l.x : q.x, y = l ? l.y : q.y;
      const nm = h('div', { class: 'n' }, (q.p.short || q.p.name).toUpperCase());
      const d = h('div', { class: 'pd' + (!q.p.started ? ' sub' : ''), style: { left: x + '%', top: y + '%', '--t': t.color, '--tx': t.color2 || colorText(t.color) }, title: q.p.name }, h('div', { class: 'd' }, q.p.number ?? ''), nm);
      d.addEventListener('pointerdown', (e) => {
        e.preventDefault(); d.setPointerCapture(e.pointerId); d.classList.add('drag');
        const mv = (ev) => { const r = pitch.getBoundingClientRect(); const nx = Math.min(97, Math.max(3, (ev.clientX - r.left) / r.width * 100)), ny = Math.min(95, Math.max(5, (ev.clientY - r.top) / r.height * 100));
          local = local || {}; local[q.p.id] = { x: nx, y: ny }; dirty = true; d.style.left = nx + '%'; d.style.top = ny + '%'; info.textContent = 'unsaved changes'; };
        const up = () => { d.classList.remove('drag'); d.removeEventListener('pointermove', mv); d.removeEventListener('pointerup', up); d.removeEventListener('pointercancel', up); };
        d.addEventListener('pointermove', mv); d.addEventListener('pointerup', up); d.addEventListener('pointercancel', up);
      });
      pitch.append(d);
    }
    info.textContent = dirty ? 'unsaved changes' : '';
    const f = fm || t.formation; if (![...fsel.options].some(o => o.value === f)) fsel.insertBefore(new Option(f, f), fsel.options[fsel.options.length - 1]); fsel.value = f;
  }
  function refresh(force) { if (dirty && !force) { info.textContent = 'unsaved changes'; return; } draw(); }   // never redraw under the hand while editing
  return { el, refresh, isDirty: () => dirty };
}
