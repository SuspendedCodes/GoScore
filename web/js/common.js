// Shared helpers for all GoScore pages (ES module, no dependencies).
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'hidden') { if (v) el[k] = true; }
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else el.append(c.nodeType ? c : document.createTextNode(String(c)));
  };
  kids.forEach(add);
  return el;
}

// ---------------------------------------------------------------- API
export const pin = {
  get: () => { try { return localStorage.getItem('gs_pin') || ''; } catch { return ''; } },
  set: (v) => { try { localStorage.setItem('gs_pin', v); } catch { /* ignore */ } },
};
export class ApiError extends Error {
  constructor(status, payload) { super((payload && payload.message) || ('HTTP ' + status)); this.status = status; this.payload = payload || {}; }
}
export async function api(method, path, body, _retry = true) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (pin.get()) opt.headers['X-Pin'] = pin.get();
  if (body !== undefined) opt.body = JSON.stringify(body);
  let r;
  const ac = new AbortController(); const to = setTimeout(() => ac.abort(), 8000); opt.signal = ac.signal;
  try { r = await fetch(path, opt); }
  catch (e) { throw new ApiError(0, { message: ac.signal.aborted ? 'The server did not answer in 8 s (too many open tabs? close unused GoScore tabs).' : 'Cannot reach the GoScore server. Is it still running?' }); }
  finally { clearTimeout(to); }
  let data = null;
  try { data = await r.json(); } catch { /* non json */ }
  if (r.status === 401 && _retry) {
    const p = prompt('This server is PIN protected. Enter the PIN:');
    if (p == null) throw new ApiError(401, data);
    pin.set(p);
    return api(method, path, body, false);
  }
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));

export function matchIdFromPath() {
  const p = location.pathname.split('/').filter(Boolean);
  return p[1] || new URLSearchParams(location.search).get('m') || 'live';
}

// ---------------------------------------------------------------- live data (SSE + polling fallback)
export class Live {
  // channel: 'pub' (published/delayed), 'live' (scorer view) or 'both' (ONE connection, onData(payload, 'live'|'pub')).
  // Browsers allow only ~6 connections per host, so pages use a single stream and release it while the tab is hidden.
  constructor(id, channel, onData, onStatus, { releaseWhenHidden = true, stream = true, pollMs = null } = {}) {
    this.useStream = stream; this.pollMs = pollMs;
    this.id = id; this.channel = channel; this.onData = onData; this.onStatus = onStatus || (() => {});
    this.last = Date.now(); this.es = null; this.poll = null; this.dead = false;
    if (this.useStream) this.connect(); else this.startPoll();
    this.watch = setInterval(() => this.check(), 3000);
    if (releaseWhenHidden) {
      this.vis = () => {
        if (!this.useStream) return;
        if (document.hidden) { this.dropStream(); }
        else if (!this.dead && !this.es) { this.connect(); }
      };
      document.addEventListener('visibilitychange', this.vis);
    }
  }
  dropStream() { this.stopPoll(); if (this.es) { this.es.close(); this.es = null; } }
  connect() {
    if (this.dead || this.es) return;
    try {
      const es = new EventSource(`/api/matches/${this.id}/stream?ch=${this.channel}`);
      this.es = es;
      const handler = (kind) => (e) => { this.last = Date.now(); this.onStatus('live'); this.stopPoll(); try { this.onData(JSON.parse(e.data), kind); } catch (err) { console.error(err); } };
      if (this.channel === 'both') { es.addEventListener('live', handler('live')); es.addEventListener('pub', handler('pub')); }
      else es.addEventListener('update', handler(this.channel));
      es.onerror = () => { this.onStatus('reconnecting'); this.startPoll(); };
    } catch (e) { this.startPoll(); }
  }
  check() { if (this.useStream && !document.hidden && Date.now() - this.last > 30000 && this.es && this.es.readyState !== 1) { this.startPoll(); } }
  startPoll() {
    if (this.poll) return;
    const get = async (path) => { const c = new AbortController(); const t = setTimeout(() => c.abort(), 5000); try { return await (await fetch(path, { signal: c.signal })).json(); } finally { clearTimeout(t); } };
    const tick = async () => {
      try {
        this.seen = this.seen || {};
        const emit = (kind, p) => { const { server_time, ...rest } = p.state || {}; const key = JSON.stringify([rest, p.graphics, p.version]); if (this.seen[kind] !== key) { this.seen[kind] = key; this.onData(p, kind); } };
        if (this.channel !== 'pub') { const d = await get(`/api/matches/${this.id}/state`); emit('live', { state: d.state, version: d.version }); }
        if (this.channel !== 'live') { emit('pub', await get(`/api/matches/${this.id}/published`)); }
        this.last = Date.now(); this.onStatus('polling');
      } catch { this.onStatus('offline'); }
    };
    tick(); this.poll = setInterval(tick, this.pollMs || (this.useStream ? 1500 : 1000));
  }
  stopPoll() { if (this.poll) { clearInterval(this.poll); this.poll = null; } }
  close() { this.dead = true; this.dropStream(); clearInterval(this.watch); if (this.vis) document.removeEventListener('visibilitychange', this.vis); }
}

// ---------------------------------------------------------------- UI bits
export function toast(msg, kind = 'info', ms = 3500) {
  let box = $('#toasts');
  if (!box) { box = h('div', { id: 'toasts' }); document.body.append(box); }
  const t = h('div', { class: 'toast ' + kind }, msg);
  box.append(t);
  setTimeout(() => t.remove(), ms);
}

export function modal(title, content, { buttons = [], wide = false, onClose } = {}) {
  const back = h('div', { class: 'modal-back' });
  const close = () => { back.remove(); document.body.classList.remove('has-modal'); onClose && onClose(); };
  const foot = h('div', { class: 'modal-foot' }, buttons.map(b => h('button', {
    class: 'btn ' + (b.kind || ''), onclick: async (e) => {
      if (b.onclick) { const r = await b.onclick(e, close); if (r === false) return; }
      if (b.close !== false) close();
    }
  }, b.label)));
  const box = h('div', { class: 'modal' + (wide ? ' wide' : ''), role: 'dialog' },
    h('div', { class: 'modal-head' }, h('b', {}, title), h('button', { class: 'x', onclick: close, 'aria-label': 'Close' }, '×')),
    h('div', { class: 'modal-body' }, content), buttons.length ? foot : null);
  back.append(box);
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(); });
  document.body.append(back);
  document.body.classList.add('has-modal');
  const first = box.querySelector('select,input,textarea,button.primary');
  if (first) setTimeout(() => first.focus(), 30);
  return { close, el: box };
}

export function confirmBox(msg, yes = 'Yes', no = 'Cancel') {
  return new Promise((res) => {
    let done = false;
    const fin = (v) => { if (!done) { done = true; res(v); } };
    modal('Please confirm', h('p', { style: { whiteSpace: 'pre-wrap' } }, msg), {
      buttons: [{ label: no, onclick: () => fin(false) }, { label: yes, kind: 'primary', onclick: () => fin(true) }],
      onClose: () => fin(false),
    });
  });
}

export function select(options, value, attrs = {}) {
  const s = h('select', attrs);
  for (const o of options) {
    const opt = h('option', { value: o.value }, o.label);
    if (o.disabled) opt.disabled = true;
    s.append(opt);
  }
  if (value !== undefined && value !== null) s.value = value;
  return s;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const num = (v, d = 0) => (v === '' || v == null || isNaN(+v) ? d : +v);
export const ago = (ts) => { const s = Math.round((Date.now() - ts) / 1000); return s < 60 ? s + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : new Date(ts).toLocaleTimeString(); };

export function setConn(el, status) {
  const map = { live: ['ok', 'LIVE'], polling: ['warn', 'POLLING'], reconnecting: ['warn', 'RECONNECTING'], offline: ['bad', 'OFFLINE'] };
  const [cls, txt] = map[status] || ['warn', status];
  el.className = 'conn ' + cls; el.textContent = '● ' + txt;
}

// ---------------------------------------------------------------- cricket helpers
export const DISMISSALS = {
  bowled: 'Bowled', caught: 'Caught', lbw: 'LBW', run_out: 'Run out', stumped: 'Stumped',
  hit_wicket: 'Hit wicket', hit_twice: 'Hit the ball twice', obstructing: 'Obstructing the field',
};
export const ALLOWED_OFF = {
  legal: Object.keys(DISMISSALS),
  noball: ['run_out', 'hit_twice', 'obstructing'],
  wide: ['run_out', 'stumped', 'hit_wicket', 'obstructing'],
};
export const FREE_HIT_ALLOWED = ['run_out', 'hit_twice', 'obstructing'];
export const STRIKER_ONLY = ['bowled', 'caught', 'lbw', 'stumped', 'hit_wicket', 'hit_twice'];

export function playersOf(state, tid, { xiOnly = true } = {}) {
  return (state.teams[tid].players || []).filter(p => !xiOnly || (p.xi && !p.subbed_out));
}
export const pname = (state, pid) => {
  for (const t of Object.values(state.teams)) { const p = t.players.find(x => x.id === pid); if (p) return p.name; }
  return pid || '';
};
export const pshort = (state, pid) => {
  for (const t of Object.values(state.teams)) { const p = t.players.find(x => x.id === pid); if (p) return p.short || p.name; }
  return pid || '';
};

export function describeEvent(ev, state, rec) {
  const n = (id) => pname(state, id);
  switch (ev.type) {
    case 'innings_start': return `Innings ${(ev.innings ?? 0) + 1} starts${ev.kind === 'super_over' ? ' (Super Over)' : ''}: openers ${n(ev.striker)} & ${n(ev.non_striker)}, bowler ${n(ev.bowler)}`;
    case 'set_bowler': return `Bowler: ${n(ev.bowler)}${ev.reason ? ' (' + ev.reason + ')' : ''}`;
    case 'new_batter': return `New batter: ${n(ev.player)}`;
    case 'set_batters': return `Crease set: ${n(ev.striker)} / ${n(ev.non_striker)}`;
    case 'swap_strike': return 'Strike swapped (manual)';
    case 'retire': return `${n(ev.player)} retired ${ev.kind === 'out' ? 'OUT' : 'hurt'}${ev.replacement ? ' → ' + n(ev.replacement) : ''}`;
    case 'timed_out': return `${n(ev.player)} timed out`;
    case 'penalty_runs': return `${ev.runs || 5} penalty runs to ${state.teams[ev.awarded_to]?.name || ev.awarded_to}`;
    case 'innings_end': return `Innings ${(ev.innings ?? 0) + 1} ended (${ev.reason || 'manual'})`;
    case 'revise': return `Revised: ${ev.overs_limit ? ev.overs_limit + ' overs' : ''} ${ev.target ? 'target ' + ev.target : ''} (${ev.method || 'manual'})`;
    case 'substitution': return `Substitution: ${n(ev.in)} in for ${n(ev.out)}`;
    case 'override': return `OVERRIDE: ${Object.entries(ev.set || {}).map(([k, v]) => `${k}=${v}`).join(', ')}${ev.reason ? ' — ' + ev.reason : ''}`;
    case 'result': return `RESULT set: ${ev.text || ev.status}`;
    case 'clear_result': return 'Result cleared';
    case 'delay': return `${({ drinks: 'Drinks', lunch: 'Lunch', tea: 'Tea', stumps: 'Stumps', rain: 'Rain', bad_light: 'Bad light', injury: 'Injury' })[ev.kind] || 'Play suspended'}${ev.text ? ': ' + ev.text : ''}`;
    case 'day_set': return `OVERRIDE: day ${ev.day}, session ${ev.session}`;
    case 'new_ball': return 'New ball taken';
    case 'resume': return 'Play resumed';
    case 'info': return `Note: ${ev.text}`;
    case 'ball': {
      const pos = rec ? `${rec.over_str} ` : '';
      const who = rec ? `${rec.bowler_name} to ${rec.striker_name}: ` : '';
      let what;
      const parts = [];
      if (ev.delivery === 'wide') parts.push('Wide' + (ev.wide_runs ? ` +${ev.wide_runs}` : ''));
      else if (ev.delivery === 'noball') parts.push('No ball');
      if (ev.bat_runs) parts.push(ev.bat_runs + (ev.boundary ? (ev.bat_runs === 6 ? ' SIX' : ' FOUR') : ' run' + (ev.bat_runs > 1 ? 's' : '')));
      if (ev.byes) parts.push(ev.byes + ' bye' + (ev.byes > 1 ? 's' : ''));
      if (ev.legbyes) parts.push(ev.legbyes + ' leg-bye' + (ev.legbyes > 1 ? 's' : ''));
      if (!parts.length) parts.push('no run');
      what = parts.join(' + ');
      if (ev.wicket) what += ` — WICKET: ${ev.wicket.kind.replace('_', ' ')} (${n(ev.wicket.out || rec?.striker)})`;
      return pos + who + what;
    }
    default: return ev.type;
  }
}

// ---------------------------------------------------------------- player roles (batter / bowler / all-rounder)
export const ROLES = { batter: 'Batters', allrounder: 'All-rounders', bowler: 'Bowlers', '': 'Others' };
export const ROLE_ONE = { batter: 'Batter', allrounder: 'All-rounder', bowler: 'Bowler', '': '—' };
export const roleOf = (state, pid) => { for (const t of Object.values(state.teams)) { const p = t.players.find(x => x.id === pid); if (p) return p.role || ''; } return ''; };
/** Group items by role in the given order. If nobody has a role set, returns one headingless group. */
export function groupByRole(items, role, order) {
  if (!items.some(i => role(i))) return [{ title: null, items }];
  return order.map(r => ({ title: ROLES[r], items: items.filter(i => (role(i) || '') === r) })).filter(g => g.items.length);
}
export const tagOf = (p) => (p && p.captain ? ' (c)' : '') + (p && p.wk ? ' †' : '');
/** <select> with sections. items: {value,label,role?}; groups: [{title, test(item)}] first match wins. */
export function sectionedSelect(items, groups, value, attrs = {}) {
  const s = h('select', attrs); const used = new Set();
  const opt = (it) => h('option', { value: it.value }, it.label);
  for (const g of groups) {
    const mine = items.filter(it => !used.has(it) && g.test(it)); if (!mine.length) continue;
    mine.forEach(it => used.add(it));
    if (g.title) { const og = h('optgroup', { label: g.title }); mine.forEach(it => og.append(opt(it))); s.append(og); } else mine.forEach(it => s.append(opt(it)));
  }
  items.filter(it => !used.has(it)).forEach(it => s.append(opt(it)));
  if (value !== undefined && value !== null) s.value = value;
  return s;
}
export const ROLE_GROUPS = (order) => order.map(r => ({ title: ROLES[r], test: (it) => (it.role || '') === r }));
