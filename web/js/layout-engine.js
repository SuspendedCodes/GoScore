// Fit-to-box layout runtime, shared by the live overlay (OBS) and the layout editor.
//
// A saved layout is { id: {x, y, w, h, z?} } in 1920x1080 canvas units. Every graphic is drawn *inside its box*:
//
//  * cards (every .pn panel, the lower-third card)  - the card is stretched to the box and the whole content is
//    scaled by the largest factor at which nothing overflows (found by search, so text, tables and pitches all
//    stay inside the box, whatever the data is);
//  * rigid graphics (scorebug, shoot-out tracker, pop-up) - scaled uniformly (aspect kept) to the largest size that
//    fits the box and centred in it.
//
// Elements are never re-parented and their class names are never touched, because the renderers re-create the
// content and re-assign className/transform of #bug on every update. Everything is applied as inline !important
// styles and removed again when a box is cleared, which returns the graphic to its stylesheet position.

export const RIGID = new Set(['bug', 'tracker', 'popup']);
const PROPS = ['position', 'left', 'top', 'right', 'bottom', 'margin', 'padding', 'translate', 'width', 'height', 'max-width', 'max-height',
  'min-width', 'box-sizing', 'transform-origin', 'transform', 'overflow', 'transition-property', 'z-index', 'display'];
const MINS = 0.08, MAXS = 4;

export function createEngine({ stage, sport }) {
  const boxes = new Map();        // id -> {x,y,w,h,z}
  const state = new WeakMap();    // el -> {sig, obs}
  const pending = new Set();
  let raf = 0, enabled = true;

  const get = (id) => document.getElementById(id);
  const put = (el, o) => { for (const k in o) el.style.setProperty(k, o[k], 'important'); };
  const release = (el) => { PROPS.forEach(p => el.style.removeProperty(p)); el.removeAttribute('data-gs'); state.delete(el); };

  function fitCard(el, b) {
    put(el, { position: 'absolute', left: b.x + 'px', top: b.y + 'px', right: 'auto', bottom: 'auto', margin: '0', translate: 'none', 'max-width': 'none',
      'max-height': 'none', 'min-width': '0', 'box-sizing': 'border-box', 'transform-origin': '0 0', overflow: 'hidden', 'transition-property': 'opacity' });
    if (!el.firstElementChild) { put(el, { width: b.w + 'px', height: b.h + 'px', transform: 'none' }); return; }
    const fits = (s) => {
      put(el, { width: (b.w / s) + 'px', height: (b.h / s) + 'px' });
      return el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1;
    };
    let s;
    if (fits(MAXS)) s = MAXS;
    else {
      let lo = MINS, hi = MAXS;
      for (let i = 0; i < 14; i++) { const mid = (lo + hi) / 2; if (fits(mid)) lo = mid; else hi = mid; }
      s = lo;
    }
    fits(s);
    put(el, { transform: `scale(${s})` });
    el.dataset.gsScale = s.toFixed(3);
  }

  function fitRigid(el, b) {
    put(el, { position: 'absolute', left: b.x + 'px', top: b.y + 'px', right: 'auto', bottom: 'auto', margin: '0', padding: '0', translate: 'none', width: 'max-content',
      height: 'auto', 'max-width': 'none', 'max-height': 'none', 'min-width': '0', display: 'block', 'transform-origin': '0 0', 'transition-property': 'opacity' });
    const c = el.firstElementChild;
    if (!c) return;
    const W0 = c.offsetWidth, H0 = c.offsetHeight;
    if (!W0 || !H0) return;
    const s = Math.min(b.w / W0, b.h / H0, 6);
    put(el, { transform: `translate(${(b.w - W0 * s) / 2}px,${(b.h - H0 * s) / 2}px) scale(${s})` });
    el.dataset.gsScale = s.toFixed(3);
  }

  // size signature: a card only needs the (costly) fit search when its size or content changed, not when it is just moved
  function sizeSig(el, id, b) { return [b.w, b.h, RIGID.has(id) ? '' : el.innerHTML].join('|'); }

  function apply(id, force) {
    const el = get(id), b = boxes.get(id);
    if (!el) return;
    if (!b || !enabled) { if (el.dataset.gs) release(el); return; }
    const st = state.get(el) || {};
    const sg = sizeSig(el, id, b);
    if (b.z) put(el, { 'z-index': String(b.z) }); else el.style.removeProperty('z-index');
    if (!force && el.dataset.gs && st.size === sg) {
      if (!RIGID.has(id)) { put(el, { left: b.x + 'px', top: b.y + 'px' }); st.x = b.x; st.y = b.y; return; }
    }
    el.dataset.gs = '1';
    (RIGID.has(id) ? fitRigid : fitCard)(el, b);
    if (!st.obs) {
      st.obs = new MutationObserver(() => schedule(id));
      st.obs.observe(el, { childList: true, subtree: true, characterData: true });
    }
    st.size = sg;
    state.set(el, st);
  }

  function schedule(id) { pending.add(id); if (!raf) raf = requestAnimationFrame(() => { raf = 0; const ids = [...pending]; pending.clear(); ids.forEach(i => apply(i)); }); }

  function setLayout(layout, ids) {
    const next = new Map(Object.entries(layout || {}));
    const all = new Set([...boxes.keys(), ...next.keys()]);
    boxes.clear();
    next.forEach((v, k) => boxes.set(k, v));
    all.forEach(id => apply(id, true));
    void ids;
  }

  function setBox(id, box, force = true) { if (box) boxes.set(id, box); else boxes.delete(id); apply(id, force); }
  function adopt() { boxes.forEach((_, id) => { const el = get(id); if (el && !el.dataset.gs) apply(id, true); }); }

  // panels are created lazily by the renderers: pick them up as soon as they appear
  for (const host of ['panels', 'lower']) {
    const e = document.getElementById(host);
    if (e) new MutationObserver(adopt).observe(e, { childList: true });
  }

  // Natural (un-managed) visual rectangle of a graphic, in canvas units. Used by the editor as the starting box.
  function naturalBox(id) {
    const el = get(id); if (!el) return null;
    const b = boxes.get(id);
    const wasManaged = !!el.dataset.gs;
    if (wasManaged) release(el);
    const prev = el.style.transform;
    el.style.setProperty('transform', 'none', 'important');
    const target = RIGID.has(id) ? (el.firstElementChild || null) : el;
    let out = null;
    if (target) {
      const sr = stage.getBoundingClientRect(), k = (sr.width / 1920) || 1, r = target.getBoundingClientRect();
      if (r.width > 1 && r.height > 1) out = { x: (r.left - sr.left) / k, y: (r.top - sr.top) / k, w: r.width / k, h: r.height / k };
    }
    el.style.removeProperty('transform'); if (prev) el.style.transform = prev;
    if (wasManaged && b) apply(id, true);
    return out;
  }

  // natural aspect (w/h) of a rigid graphic, so the editor can keep its box hugging the content
  function aspect(id) {
    const el = get(id); const c = el && el.firstElementChild;
    if (!c) return null;
    return c.offsetWidth && c.offsetHeight ? c.offsetWidth / c.offsetHeight : null;
  }

  async function poll(everyMs = 4000) {
    let rev = null, dead = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/layout/${sport}`, { cache: 'no-store' });
        if (r.ok) { const d = await r.json(); if (d.rev !== rev) { rev = d.rev; setLayout(d.layout); } }
      } catch (e) { /* server restarting: keep the last layout */ }
      if (!dead) setTimeout(tick, everyMs);
    };
    tick();
    return () => { dead = true; };
  }

  return { boxes, setLayout, setBox, apply, naturalBox, aspect, poll, refitAll: () => boxes.forEach((_, id) => apply(id, true)),
    enable(v) { enabled = v; boxes.forEach((_, id) => apply(id, true)); } };
}
