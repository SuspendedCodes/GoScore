// OBS overlay renderer. Data comes from the *published* feed (hold / delay aware).
import { h, Live, matchIdFromPath } from '../common.js';
import { createEngine } from '../layout-engine.js';
import { clockInfo, startingXI, bench, formationRows, pitchPlayers, colorText, pl } from './fbcommon.js';

const id = matchIdFromPath();
const qs = new URLSearchParams(location.search);
// Solo mode: /overlay/<id>?panel=<key> renders ONE graphic, auto-scaled to fill the OBS browser source (any size).
//   panel = bug | tracker | popups | lineups | formation_home | ... (see Production page for the full list)
//   scale = extra multiplier (default 1) · fit=0 turns auto-fit off (then scale is absolute) · align = c|t|b|l|r|tl|tr|bl|br
//   pad = margin in px (default 16) · follow=1 obeys the Production on/off buttons (default: always visible)
//   stat = stat key for panel=stat_single · bg = background colour for testing (e.g. bg=%2300ff00)
const solo = qs.get('panel') || '';
const follow = true; // Match cricket: individual panel URLs always follow Production visibility.
// Dedicated slideshow source: panels only, isolated from scorebug and event pop-ups.
const slideshowOnly = qs.get('slideshow') === '1';
const only = solo ? [solo === 'bug' ? 'bug' : solo === 'tracker' ? 'tracker' : solo === 'popups' ? 'popups' : 'panels'] : (qs.get('only') || 'bug,tracker,popups,panels').split(',');
if (qs.get('preview')) document.body.classList.add('preview');
if (solo) document.body.classList.add('solo');
if (qs.get('bg')) document.body.style.background = qs.get('bg');
const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/static/css/overlay_fb.css'; document.head.append(link);
document.querySelectorAll('link[href$="overlay.css"]').forEach(l => l.remove());   // football brings its own stylesheet
const stage = document.getElementById('stage');
stage.replaceChildren(h('div', { id: 'panels' }), h('div', { id: 'lower' }), h('div', { id: 'bug' }), h('div', { id: 'tracker' }), h('div', { id: 'popup' }));
function fit() {
  if (qs.get('edit') === '1') return;
  if (solo) return layoutSolo();
  const s = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `scale(${s})`;
}
function layoutSolo() {
  const el = solo === 'bug' ? document.getElementById('bug') : solo === 'tracker' ? document.getElementById('tracker') : solo === 'popups' ? document.getElementById('popup') : document.getElementById('pn-' + solo);
  if (!el) return;
  const w = el.offsetWidth, hh = el.offsetHeight; if (!w || !hh) return;
  const m = qs.get('pad') != null ? +qs.get('pad') || 0 : 16, mul = +qs.get('scale') || 1, a = (qs.get('align') || 'c').toLowerCase();
  const s = (qs.get('fit') === '0' ? 1 : Math.min(innerWidth / (w + 2 * m), innerHeight / (hh + 2 * m))) * mul;
  const ox = a.includes('l') ? m * s : a.includes('r') ? innerWidth - (w + m) * s : (innerWidth - w * s) / 2;
  const oy = a.includes('t') ? m * s : a.includes('b') ? innerHeight - (hh + m) * s : (innerHeight - hh * s) / 2;
  stage.style.width = w + 'px'; stage.style.height = hh + 'px';
  stage.style.transform = `translate(${ox}px,${oy}px) scale(${s})`;
}
addEventListener('resize', fit); fit();
// Saved layout boxes (see layout-engine.js). Individual-panel URLs (?panel=) size themselves, so they ignore the layout.
const edit = qs.get('edit') === '1';
const layout = solo ? null : createEngine({ stage, sport: 'football' });
if (layout && !edit) layout.poll();
const managed = (k) => !!(layout && layout.boxes.has(k));
if (solo) setInterval(layoutSolo, 250);
const $ = (s) => document.getElementById(s);

let S = null, G = null, skew = 0, delay = 0, firstPayload = true, popTimer = null;
const seenTl = new Set(); let seenPopup = null; const queue = []; let showing = false;

function loadPayload(payload) {
  S = payload.state; G = payload.graphics; delay = payload.delay || 0; skew = (S.server_time || Date.now()) - Date.now();
  stage.style.setProperty('--ca', S.teams.A.color); stage.style.setProperty('--cb', S.teams.B.color);
  stage.style.setProperty('--ta', S.teams.A.color2 || colorText(S.teams.A.color)); stage.style.setProperty('--tb', S.teams.B.color2 || colorText(S.teams.B.color));
  return payload;
}
function onPayload(payload) {
  loadPayload(payload);
  if (only.includes('bug')) renderBug();
  if (only.includes('tracker')) renderTracker();
  if (only.includes('panels')) { resetSlideshowTimer(); renderPanels(); }
  if (only.includes('popups')) handlePopups();
  firstPayload = false;
}
if (!edit) new Live(id, 'pub', onPayload, () => {}, { releaseWhenHidden: false, stream: false, pollMs: 1500 });
else runEditor();
setInterval(() => { if (S) tickClock(); }, 200);

// ------------------------------------------------------------- helpers
const surname = (p) => { const parts = (p.name || '').trim().split(/\s+/); return parts.length > 1 ? parts.slice(1).join(' ') : parts[0]; };
const given = (p) => { const parts = (p.name || '').trim().split(/\s+/); return parts.length > 1 ? parts[0] : ''; };
const nameEl = (p) => h('span', { class: 'pname' }, given(p) ? h('span', { class: 'gn' }, given(p) + ' ') : null, h('span', { class: 'sn' }, surname(p).toUpperCase()));
const BALL_PATH = 'M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm76.52,147.42H170.9l-9.26-12.76,12.63-36.78,15-4.89,26.24,20.13A87.38,87.38,0,0,1,204.52,171.42Zm-164-34.3L66.71,117l15,4.89,12.63,36.78L85.1,171.42H51.48A87.38,87.38,0,0,1,40.47,137.12Zm10-50.64,5.51,18.6L40.71,116.77A87.33,87.33,0,0,1,50.43,86.48ZM109,152,97.54,118.65,128,97.71l30.46,20.94L147,152Zm91.07-46.92,5.51-18.6a87.33,87.33,0,0,1,9.72,30.29Zm-6.2-35.38-9.51,32.08-15.07,4.89L136,83.79V68.21l29.09-20A88.58,88.58,0,0,1,193.86,69.7ZM146.07,41.87,128,54.29,109.93,41.87a88.24,88.24,0,0,1,36.14,0ZM90.91,48.21l29.09,20V83.79L86.72,106.67l-15.07-4.89L62.14,69.7A88.58,88.58,0,0,1,90.91,48.21ZM63.15,187.42H83.52l7.17,20.27A88.4,88.4,0,0,1,63.15,187.42ZM110,214.13,98.12,180.71,107.35,168h41.3l9.23,12.71-11.83,33.42a88,88,0,0,1-36.1,0Zm55.36-6.44,7.17-20.27h20.37A88.4,88.4,0,0,1,165.31,207.69Z';
// football icon: Phosphor Icons "soccer-ball" (MIT licence, phosphoricons.com)
function ballIcon() { const NS = 'http://www.w3.org/2000/svg'; const v = document.createElementNS(NS, 'svg'); v.setAttribute('viewBox', '0 0 256 256'); v.setAttribute('width', '1em'); v.setAttribute('height', '1em'); v.setAttribute('fill', 'currentColor'); v.style.verticalAlign = '-.12em'; const p = document.createElementNS(NS, 'path'); p.setAttribute('d', BALL_PATH); v.append(p); return v; }
const badge = (t) => t.logo ? h('img', { class: 'logo', src: t.logo }) : null;
const sideColor = (tid) => `var(--c${tid.toLowerCase()})`;
const cardSq = (c) => h('span', { class: 'csq ' + c });

// ------------------------------------------------------------- scorebug
function renderBug() {
  const bug = $('bug');
  const visible = G.scorebug || (solo && !follow);
  bug.className = 'pos-' + (G.position || 'top-left') + (visible ? '' : ' off');
  if (!managed('bug')) bug.style.transform = visible && !solo && !edit ? `scale(${G.scale || 1})` : '';
  const A = S.teams.A, B = S.teams.B;
  const reds = (t) => t.red_cards ? h('span', { class: 'reds' }, Array.from({ length: Math.min(t.red_cards, 4) }, () => cardSq('r'))) : null;
  const team = (t, tid) => h('div', { class: 'fb-team ' + tid.toLowerCase(), style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, badge(t), h('span', { class: 'sh' }, t.short), reds(t));
  const extra = [];
  if (S.var.active) extra.push(h('span', { class: 'tag var' }, 'VAR CHECK · ' + S.var.text.toUpperCase()));
  if (S.aggregate.on) extra.push(h('span', { class: 'tag' }, `AGG ${S.aggregate.A}-${S.aggregate.B}`));
  if (S.shootout.started) extra.push(h('span', { class: 'tag pen' }, `PENS ${S.shootout.goals.A}-${S.shootout.goals.B}`));
  if (S.result.final && !S.shootout.started) extra.push(h('span', { class: 'tag' }, S.result.kind === 'draw' ? 'DRAW' : 'FINAL'));
  const sub = S.status === 'completed' ? S.phase_label.toUpperCase() : null;
  bug.replaceChildren(h('div', { class: 'fbug' },
    h('div', { class: 'row1' }, team(A, 'A'), h('div', { class: 'fb-sc num' }, h('span', {}, S.score.A), h('i', {}, '–'), h('span', {}, S.score.B)), team(B, 'B'),
      h('div', { class: 'fb-clock' }, h('div', { class: 'ck num', id: 'ck' }, '00:00'), h('div', { class: 'ph', id: 'ph' }, S.phase_short)), h('div', { class: 'fb-add', id: 'add' })),
    extra.length || sub ? h('div', { class: 'row2' }, ...extra, sub ? h('span', { class: 'tag' }, sub) : null) : null));
  tickClock();
}
function tickClock() {
  const ck = $('ck'); if (!ck) return;
  const ci = clockInfo(S, Date.now() + skew - delay * 1000);
  const ph = S.phase;
  if (ph === 'pre') ck.textContent = S.kickoff || 'KO';
  else if (ph === 'break1' || ph === 'break3' || ph === 'break2' || ph === 'pre_so' || ph === 'ended' || ph === 'so') ck.textContent = ph === 'break1' ? 'HT' : ph === 'break3' ? 'ET HT' : (ph === 'ended' ? 'FT' : (ph === 'so' || ph === 'pre_so' ? 'PEN' : 'FT'));
  else ck.textContent = ci.over ? ci.base : ci.mmss;
  ck.classList.toggle('paused', !S.clock.running && ['p1', 'p2', 'et1', 'et2'].includes(ph));
  const add = $('add'); const live = ['p1', 'p2', 'et1', 'et2'].includes(ph);
  const txt = live && ci.over ? ci.stoppage : '';
  const ab = live && S.clock.added_min ? '+' + S.clock.added_min : '';
  add.textContent = ci.over && live ? `${ci.stoppage}` : ab; add.classList.toggle('on', !!(ci.over && live) || !!ab); add.classList.toggle('over', !!(ci.over && live));
  const phEl = $('ph'); if (phEl && live) phEl.textContent = ({ p1: '1ST HALF', p2: '2ND HALF', et1: 'ET 1', et2: 'ET 2' })[ph];
  void txt;
}

// ------------------------------------------------------------- shoot-out tracker
function renderTracker() {
  const el = $('tracker'); const so = S.shootout;
  const on = G.panels.shootout || (G.shootout_auto && so.started && S.phase === 'so') || (solo && !follow && so.started);
  if (!on || !so.started) { el.className = ''; el.replaceChildren(); return; }
  const slots = Math.max(5, ...['A', 'B'].map(t => so.kicks.filter(k => k.team === t).length));
  const row = (tid) => { const t = S.teams[tid]; const ks = so.kicks.filter(k => k.team === tid);
    return h('div', { class: 'tr', style: { '--t': t.color } }, h('span', { class: 'tn' }, t.short), h('div', { class: 'dots' }, Array.from({ length: slots }, (_, i) => { const k = ks[i]; return h('span', { class: 'dot ' + (k ? (k.result === 'scored' ? 'g' : 'x') : '') }, k ? (k.result === 'scored' ? '\u2713' : '\u2715') : ''); })), h('span', { class: 'ts num' }, so.goals[tid])); };
  el.className = 'show'; el.replaceChildren(h('div', { class: 'fb-so' }, h('div', { class: 'hd' }, 'PENALTY SHOOT-OUT'), row('A'), row('B'), so.decided ? h('div', { class: 'win' }, S.teams[so.winner].name.toUpperCase() + ' WIN') : null));
}

// ------------------------------------------------------------- popups
const KIND_STYLE = { goal: 'goal', yellow: 'yellow', red: 'red', sub: 'sub', var: 'var', penalty: 'pen', period: 'per', added: 'add', custom: 'cus' };
function showPop(kind, node, ms = 6000) {
  const el = $('popup'); clearTimeout(popTimer);
  const pop = h('div', { class: 'fpop ' + (KIND_STYLE[kind] || 'cus') }, node);
  el.replaceChildren(pop); requestAnimationFrame(() => requestAnimationFrame(() => pop.classList.add('in')));
  if (Number.isFinite(ms)) popTimer = setTimeout(() => { pop.classList.remove('in'); setTimeout(() => { if (el.firstChild === pop) el.replaceChildren(); showing = false; next(); }, 450); }, ms);
}
function next() { if (showing || !queue.length) return; showing = true; const q = queue.shift(); showPop(q.kind, q.node, q.ms); }
function enqueue(kind, node, ms, priority) { if (priority) queue.unshift({ kind, node, ms }); else queue.push({ kind, node, ms }); while (queue.length > 3) queue.shift(); next(); }
const scoreLine = () => h('div', { class: 'sl num' }, `${S.teams.A.short}  ${S.score.A} – ${S.score.B}  ${S.teams.B.short}`);
function popFor(r) {
  const en = G.popups_enabled || {}; const t = r.team ? S.teams[r.team] : null;
  const head = (txt, sub) => h('div', { class: 'hd' }, h('span', { class: 'big' }, txt), sub ? h('span', { class: 'min' }, sub) : null);
  const st = t ? { '--t': t.color, '--tx': t.color2 || colorText(t.color) } : {};
  if (r.type === 'goal' && en.goal) return ['goal', h('div', { class: 'body', style: st }, head(r.kind === 'own_goal' ? 'OWN GOAL' : r.kind === 'penalty' ? 'PENALTY — GOAL!' : 'GOAL!', r.label),
    h('div', { class: 'who' }, h('b', {}, (r.text || '').replace(/ \((pen|own goal)\)$/, '').toUpperCase()), ' ', h('span', { class: 'tm' }, t.name)), r.assist_name ? h('div', { class: 'ast' }, 'Assist: ' + r.assist_name) : null, scoreLine()), 7000, true];
  if (r.type === 'card' && en.card) { const yellow = r.color === 'yellow'; const two = r.color === 'yellow2';
    return [yellow ? 'yellow' : 'red', h('div', { class: 'body', style: st }, h('div', { class: 'hd card' }, cardSq(yellow ? 'y' : 'r'), h('span', { class: 'big' }, two ? 'SECOND YELLOW — RED' : yellow ? 'YELLOW CARD' : 'RED CARD'), h('span', { class: 'min' }, r.label)),
      h('div', { class: 'who' }, h('b', {}, (r.text || '').toUpperCase()), ' ', h('span', { class: 'tm' }, t.name)), r.reason ? h('div', { class: 'ast' }, r.reason) : null), 5500, !yellow]; }
  if (r.type === 'sub' && en.sub) return ['sub', h('div', { class: 'body', style: st }, head('SUBSTITUTION', r.label), h('div', { class: 'swap' }, h('div', { class: 'on' }, h('i', {}, '▲'), h('span', {}, r.on_number != null ? r.on_number + '  ' : ''), r.on_name), h('div', { class: 'off' }, h('i', {}, '▼'), h('span', {}, r.off_number != null ? r.off_number + '  ' : ''), r.off_name)), h('div', { class: 'ast' }, t.name)), 5500];
  if (r.type === 'var' && en.var) return ['var', h('div', { class: 'body' }, head('VAR', r.label), h('div', { class: 'who' }, r.text.replace(/^VAR\s*-?\s*/i, '').toUpperCase())), 5000];
  if (r.type === 'goal_cancel' && en.var) return ['var', h('div', { class: 'body' }, head('GOAL DISALLOWED', r.label), h('div', { class: 'who' }, (r.player_name || '').toUpperCase()), scoreLine()), 5500, true];
  if ((r.type === 'penalty' || r.type === 'penalty_miss') && en.penalty) return ['penalty', h('div', { class: 'body', style: st }, head(r.type === 'penalty' ? 'PENALTY!' : 'PENALTY ' + (r.outcome === 'saved' ? 'SAVED' : r.outcome === 'post' ? 'OFF THE WOODWORK' : 'MISSED'), r.label), h('div', { class: 'who' }, (r.text || '').toUpperCase()), h('div', { class: 'ast' }, t ? t.name : '')), 5000];
  if (r.type === 'period' && en.period && ['start', 'ht', 'ft', 'nt', 'et_ht', 'so_start', 'abandon'].includes(r.marker)) {
    const label = { start: r.text.toUpperCase(), ht: 'HALF-TIME', ft: 'FULL-TIME', nt: 'FULL-TIME', et_ht: 'HALF-TIME — EXTRA TIME', so_start: 'PENALTY SHOOT-OUT', abandon: 'MATCH ABANDONED' }[r.marker];
    return ['period', h('div', { class: 'body' }, head(label), r.marker === 'start' ? null : scoreLine(), r.marker === 'abandon' ? h('div', { class: 'ast' }, r.text) : null), 6000];
  }
  if (r.type === 'added_time' && en.added_time) return ['added', h('div', { class: 'body board' }, h('div', { class: 'plus num' }, '+' + r.minutes), h('div', { class: 'lbl' }, 'MINUTE' + (r.minutes === 1 ? '' : 'S') + ' ADDED TIME')), 6000];
  return null;
}
function handlePopups() {
  const rows = S.timeline.filter(r => !seenTl.has(r.id));
  rows.forEach(r => seenTl.add(r.id));
  if (!firstPayload) rows.forEach(r => { if (r.cancelled) return; const p = popFor(r); if (p) enqueue(p[0], p[1], p[2], p[3]); });
  const gp = G.popup;
  if (gp && gp.id !== seenPopup) {
    const first = seenPopup === null && firstPayload; seenPopup = gp.id;
    if (!first && S.server_time - gp.ts < 8000) {
      const kinds = { goal: 'GOAL!', yellow: 'YELLOW CARD', red: 'RED CARD', sub: 'SUBSTITUTION', var: 'VAR CHECK', penalty: 'PENALTY', halftime: 'HALF-TIME', fulltime: 'FULL-TIME', kickoff: 'KICK-OFF', added: 'ADDED TIME' };
      enqueue(gp.kind === 'yellow' ? 'yellow' : gp.kind === 'red' ? 'red' : gp.kind === 'var' ? 'var' : gp.kind === 'goal' ? 'goal' : 'custom',
        h('div', { class: 'body' }, h('div', { class: 'hd' }, h('span', { class: 'big' }, kinds[gp.kind] || (gp.text || '').toUpperCase())), gp.text && kinds[gp.kind] ? h('div', { class: 'who' }, gp.text) : null,
          ['halftime', 'fulltime', 'goal'].includes(gp.kind) ? scoreLine() : null), 5500, true);
    }
  } else if (gp && seenPopup === null) seenPopup = gp.id;
}

// ------------------------------------------------------------- panels
const PANEL_DEFS = {};
const hashes = {};
let slideIndex = 0, slideTimer = null, slideTimerConfig = '';
const SK = () => qs.get('stat') || G.stat_key;
function panelEl(key, cls) { let el = document.getElementById('pn-' + key); if (!el) { el = h('div', { id: 'pn-' + key, class: 'pn ' + cls }); (['stat_single', 'stats_strip', 'player_card', 'banner'].includes(key) ? $('lower') : $('panels')).append(el); } return el; }
function renderPanels(keys) {
  const cfg = G && G.slideshow || {};
  const slides = (cfg.slides || []).filter(k => PANEL_DEFS[k] && !['stats_strip', 'stat_single', 'player_card', 'banner'].includes(k));
  // When slideshow mode is enabled, keep the rotating panels off the combined overlay.
  // They are rendered by the dedicated ?only=panels&slideshow=1 Browser Source instead.
  if (cfg.enabled && !slideshowOnly && !solo) {
    for (const key of Object.keys(PANEL_DEFS)) { const el = document.getElementById('pn-' + key); if (el) { el.classList.remove('show'); el.replaceChildren(); } }
    return;
  }
  const activeSlide = cfg.enabled && slides.length ? slides[slideIndex % slides.length] : null;
  for (const [key, def] of Object.entries(PANEL_DEFS)) {
    if (solo && key !== solo) continue;
    if (keys && !keys.includes(key)) continue;
    const el = panelEl(key, def.cls);
    const inSlideshow = !!activeSlide && slides.includes(key);
    const on = solo && !follow ? true : (inSlideshow ? key === activeSlide : (!cfg.enabled || !slides.length) && !!G.panels[key]);
    if (on) { const hsh = JSON.stringify([key, def.dep(), G.stat_rows, SK(), G.stats_title, G.lineup_team, G.card_player, G.banner, G.stat_keys_strip, G.player_stat_keys]); if (hashes[key] !== hsh) { hashes[key] = hsh; el.replaceChildren(def.render()); } }
    el.classList.toggle('show', on);
    if (!on) hashes[key] = null;
  }
}
function resetSlideshowTimer() {
  const cfg = G && G.slideshow || {};
  const slides = (cfg.slides || []).filter(k => PANEL_DEFS[k] && !['stats_strip', 'stat_single', 'player_card', 'banner'].includes(k));
  const interval = Math.max(5, Math.min(120, Number(cfg.interval) || 12));
  const signature = JSON.stringify([!!cfg.enabled, slides, interval]);
  if (signature === slideTimerConfig) return;
  slideTimerConfig = signature;
  clearInterval(slideTimer); slideTimer = null;
  if (!cfg.enabled || slides.length < 2) { slideIndex = 0; renderPanels(); return; }
  slideIndex %= slides.length;
  slideTimer = setInterval(() => { if (!G || !G.slideshow || !G.slideshow.enabled) return; slideIndex = (slideIndex + 1) % slides.length; renderPanels(); fit(); }, interval * 1000);
}
const full = (S_) => S_; void full;
const head2 = (title, sub) => h('div', { class: 'ph' }, h('span', {}, title), sub ? h('span', { class: 'sub' }, sub) : null);
const teamHead = (t, tid, right) => h('div', { class: 'th ' + (right ? 'r' : ''), style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, badge(t), h('span', { class: 'tn' }, t.name));

function xiList(tid) {
  const t = S.teams[tid];
  return h('div', { class: 'lu', style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, h('div', { class: 'th' }, badge(t), h('span', { class: 'tn' }, t.name), h('span', { class: 'fm' }, t.formation)),
    ...startingXI(S, tid).map(p => h('div', { class: 'pr' }, h('span', { class: 'no num' }, p.number ?? ''), nameEl(p), p.captain ? h('span', { class: 'cp' }, 'C') : null, h('span', { class: 'ps' }, p.pos), p.red ? cardSq('r') : p.yellows ? cardSq('y') : null, p.status === 'off' ? h('i', { class: 'dn' }, '▼') : null)),
    h('div', { class: 'sb' }, 'SUBSTITUTES'), ...bench(S, tid).map(p => h('div', { class: 'pr s' }, h('span', { class: 'no num' }, p.number ?? ''), nameEl(p), h('span', { class: 'ps' }, p.pos), p.status === 'on' ? h('i', { class: 'up' }, '▲') : null)),
    t.coach ? h('div', { class: 'coach' }, 'HEAD COACH ', h('b', {}, t.coach.toUpperCase())) : null);
}
PANEL_DEFS.lineups = { cls: 'p-lineups', dep: () => [S.teams.A.players, S.teams.B.players, S.teams.A.formation, S.teams.B.formation], render: () => {
  const w = G.lineup_team || 'both';
  return h('div', {}, head2('STARTING LINE-UPS', [S.competition, S.stage].filter(Boolean).join(' · ')), h('div', { class: 'cols' + (w === 'both' ? '' : ' one') }, ...(w === 'B' ? [] : [xiList('A')]), ...(w === 'A' ? [] : [xiList('B')])));
} };
function pitch(tid) {
  const t = S.teams[tid];
  const dots = pitchPlayers(S, tid).map(({ p, x, y }) => h('div', { class: 'dot2', style: { left: x + '%', top: y + '%' } }, h('div', { class: 'disc' }, p.number ?? ''), h('div', { class: 'nm' }, surname(p).toUpperCase()),
    p.yellows ? cardSq('y') : null, !p.started ? h('i', { class: 'up' }, '▲') : null));
  return h('div', { class: 'pitchwrap', style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, h('div', { class: 'ph' }, h('span', {}, t.name.toUpperCase()), h('span', { class: 'sub' }, t.formation + (t.coach ? '  ·  ' + t.coach : ''))),
    h('div', { class: 'pitch' }, h('div', { class: 'ln mid' }), h('div', { class: 'ln circ' }), h('div', { class: 'ln boxl' }), h('div', { class: 'ln boxr' }), ...dots));
}
PANEL_DEFS.formation_home = { cls: 'p-form', dep: () => [S.teams.A.players, S.teams.A.formation], render: () => pitch('A') };
PANEL_DEFS.formation_away = { cls: 'p-form', dep: () => [S.teams.B.players, S.teams.B.formation], render: () => pitch('B') };
PANEL_DEFS.subs_bench = { cls: 'p-lineups', dep: () => [S.teams.A.players, S.teams.B.players], render: () => h('div', {}, head2('SUBSTITUTES'), h('div', { class: 'cols' }, ...['A', 'B'].map(tid => { const t = S.teams[tid];
  return h('div', { class: 'lu', style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, h('div', { class: 'th' }, badge(t), h('span', { class: 'tn' }, t.name)), ...bench(S, tid).map(p => h('div', { class: 'pr' }, h('span', { class: 'no num' }, p.number ?? ''), nameEl(p), h('span', { class: 'ps' }, p.pos), p.status === 'on' ? h('i', { class: 'up' }, '▲') : null))); }))) };
const scorersCol = (tid, right) => h('div', { class: 'sc-col ' + (right ? 'r' : '') }, ...(S.scorers[tid].length ? S.scorers[tid].map(x => h('div', { class: 'sr' }, h('b', {}, x.name.toUpperCase()), h('span', { class: 'tm num' }, x.times.join(', ')))) : [h('div', { class: 'sr none' }, '—')]));
function resultCard(title) {
  const A = S.teams.A, B = S.teams.B;
  const rows = ['possession', 'shots', 'shots_on_target', 'corners'].map(k => S.stats.rows[k]).filter(r => r && (r.A != null || r.B != null));
  return h('div', {}, head2(title, [S.competition, S.venue].filter(Boolean).join(' · ')),
    h('div', { class: 'rc' }, teamHead(A, 'A'), h('div', { class: 'big num' }, `${S.score.A} – ${S.score.B}`), teamHead(B, 'B', true)),
    S.shootout.started ? h('div', { class: 'note' }, `${S.teams[S.shootout.winner || 'A'].short} won ${Math.max(S.shootout.goals.A, S.shootout.goals.B)}-${Math.min(S.shootout.goals.A, S.shootout.goals.B)} on penalties`) : (S.aggregate.on ? h('div', { class: 'note' }, `Aggregate ${S.aggregate.A} – ${S.aggregate.B}`) : null),
    h('div', { class: 'scs' }, scorersCol('A'), h('div', { class: 'ball' }, ballIcon()), scorersCol('B', true)),
    rows.length ? h('div', { class: 'mini' }, ...rows.map(r => h('div', { class: 'mr' }, h('b', { class: 'num' }, r.dA), h('span', {}, r.label.toUpperCase()), h('b', { class: 'num' }, r.dB)))) : null,
    S.result.final ? h('div', { class: 'note' }, S.result.text) : null, S.motm && title.startsWith('FULL') ? h('div', { class: 'note' }, 'MAN OF THE MATCH  ', h('b', {}, S.motm.toUpperCase())) : null);
}
PANEL_DEFS.halftime = { cls: 'p-card', dep: () => [S.score, S.scorers, S.stats.rows], render: () => resultCard('HALF-TIME') };
PANEL_DEFS.fulltime = { cls: 'p-card', dep: () => [S.score, S.scorers, S.stats.rows, S.result, S.motm, S.shootout.goals], render: () => resultCard('FULL-TIME') };
PANEL_DEFS.scorers = { cls: 'p-card', dep: () => [S.score, S.scorers], render: () => h('div', {}, head2('GOALS'), h('div', { class: 'rc' }, teamHead(S.teams.A, 'A'), h('div', { class: 'big num' }, `${S.score.A} – ${S.score.B}`), teamHead(S.teams.B, 'B', true)), h('div', { class: 'scs' }, scorersCol('A'), h('div', { class: 'ball' }, ballIcon()), scorersCol('B', true))) };
PANEL_DEFS.timeline = { cls: 'p-time', dep: () => S.timeline.length + ':' + S.timeline.filter(r => r.cancelled).length, render: () => {
  const rows = S.timeline.filter(r => ['goal', 'card', 'sub', 'goal_cancel', 'var', 'penalty_miss'].includes(r.type)).slice(-12);
  return h('div', {}, head2('MATCH EVENTS', `${S.teams.A.short} ${S.score.A} – ${S.score.B} ${S.teams.B.short}`), h('div', { class: 'tlist' }, rows.length ? rows.map(r => h('div', { class: 'te ' + (r.team || '') + (r.cancelled ? ' x' : ''), style: { '--t': r.team ? S.teams[r.team].color : '#667' } },
    h('span', { class: 'tm num' }, r.label), h('span', { class: 'ic' }, r.type === 'goal' ? ballIcon() : r.type === 'card' ? cardSq(r.color === 'yellow' ? 'y' : 'r') : r.type === 'sub' ? '⇄' : r.type === 'var' ? 'VAR' : r.type === 'goal_cancel' ? 'Disallow' : '•'),
    h('span', { class: 'tx' }, r.type === 'sub' ? [h('b', {}, r.on_name), ' ▲  ', r.off_name, ' ▼'] : r.type === 'card' ? r.text : r.text), h('span', { class: 'tmn' }, r.team ? S.teams[r.team].short : ''))) : [h('div', { class: 'none' }, 'No events yet')])); } };
const form = (s) => (s || '').split(/[\s,-]+/).filter(Boolean).slice(-5);
PANEL_DEFS.preview = { cls: 'p-card', dep: () => [S.form, S.h2h, S.officials, S.kickoff], render: () => {
  const A = S.teams.A, B = S.teams.B, o = S.officials || {};
  return h('div', {}, head2([S.competition, S.stage].filter(Boolean).join(' · ') || 'MATCH PREVIEW', S.date || ''), h('div', { class: 'rc' }, teamHead(A, 'A'), h('div', { class: 'big vs' }, 'v'), teamHead(B, 'B', true)),
    h('div', { class: 'note' }, [S.venue, S.kickoff ? 'KO ' + S.kickoff : '', S.weather].filter(Boolean).join('  ·  ')),
    h('div', { class: 'forms' }, h('div', { class: 'fm' }, form(S.form.A).map(x => h('span', { class: 'fc ' + x.toUpperCase() }, x.toUpperCase()))), h('div', { class: 'lbl' }, 'RECENT FORM'), h('div', { class: 'fm' }, form(S.form.B).map(x => h('span', { class: 'fc ' + x.toUpperCase() }, x.toUpperCase())))),
    (S.h2h.A || S.h2h.D || S.h2h.B) ? h('div', { class: 'h2h' }, h('div', {}, h('b', { class: 'num' }, S.h2h.A), h('span', {}, 'WINS')), h('div', {}, h('b', { class: 'num' }, S.h2h.D), h('span', {}, 'DRAWS')), h('div', {}, h('b', { class: 'num' }, S.h2h.B), h('span', {}, 'WINS')), h('div', { class: 'lbl' }, 'HEAD TO HEAD')) : null,
    o.referee ? h('div', { class: 'note' }, 'REFEREE  ', h('b', {}, o.referee.toUpperCase())) : null); } };
PANEL_DEFS.officials = { cls: 'p-card narrow', dep: () => S.officials, render: () => { const o = S.officials || {}; const rows = [['REFEREE', o.referee], ['ASSISTANT REFEREE', o.ar1], ['ASSISTANT REFEREE', o.ar2], ['FOURTH OFFICIAL', o.fourth], ['VAR', o.var], ['ASSISTANT VAR', o.avar]].filter(r => r[1]);
  return h('div', {}, head2('MATCH OFFICIALS'), h('div', { class: 'offs' }, rows.map(([l, n]) => h('div', { class: 'of' }, h('span', {}, l), h('b', {}, n.toUpperCase()))))); } };

// ---- statistics ---------------------------------------------------------------
const statRows = (keys) => keys.map(k => S.stats.rows[k]).filter(Boolean);
const frac = (r) => { if (r.kind === 'pct') return [Math.min(100, r.A || 0) / 100, Math.min(100, r.B || 0) / 100]; const m = Math.max(r.A || 0, r.B || 0); return m > 0 ? [(r.A || 0) / m, (r.B || 0) / m] : [0, 0]; };
const sh = (r) => { const a = r.A || 0, b = r.B || 0, t = a + b; return t > 0 ? [a / t, b / t] : [.5, .5]; };
const lead = (r) => (r.A == null || r.B == null || r.A === r.B ? '' : r.A > r.B ? 'a' : 'b');
function statsHead(title) {
  const A = S.teams.A, B = S.teams.B;
  return h('div', { class: 'sh2' }, h('div', { class: 'sa', style: { '--t': A.color, '--tx': A.color2 || colorText(A.color) } }, badge(A), h('span', {}, A.name.toUpperCase())), h('div', { class: 'sm' }, h('div', { class: 'tt' }, (G.stats_title || title).toUpperCase()), h('div', { class: 'sc num' }, `${S.score.A} – ${S.score.B}`)), h('div', { class: 'sb2', style: { '--t': B.color, '--tx': B.color2 || colorText(B.color) } }, h('span', {}, B.name.toUpperCase()), badge(B)));
}
// variant 1 - classic: value | label | value with thin centre-out bars
PANEL_DEFS.stats_classic = { cls: 'p-stats classic', dep: () => S.stats.rows, render: () => {
  const rows = statRows(G.stat_rows || []);
  return h('div', {}, statsHead('Match statistics'), h('div', { class: 'srows' }, rows.map(r => { const [fa, fb] = frac(r); const l = lead(r);
    return h('div', { class: 'srow' }, h('div', { class: 'l' }, h('b', { class: 'num ' + (l === 'a' ? 'lead' : '') }, r.dA), h('span', { class: 'lab' }, r.label.toUpperCase()), h('b', { class: 'num ' + (l === 'b' ? 'lead' : '') }, r.dB)),
      h('div', { class: 'bars' }, h('div', { class: 'half a' }, h('i', { style: { width: (fa * 100) + '%' } })), h('div', { class: 'half b' }, h('i', { style: { width: (fb * 100) + '%' } })))); })));
} };
// variant 2 - bars: share-of-total split bar with pill values
PANEL_DEFS.stats_bars = { cls: 'p-stats bars', dep: () => S.stats.rows, render: () => {
  const rows = statRows(G.stat_rows || []);
  return h('div', {}, statsHead('Team comparison'), h('div', { class: 'srows' }, rows.map(r => { const [pa, pb] = sh(r);
    return h('div', { class: 'brow' }, h('div', { class: 'lab' }, r.label.toUpperCase()), h('div', { class: 'split' }, h('span', { class: 'pill a num' }, r.dA), h('div', { class: 'track' }, h('i', { class: 'fa', style: { flex: pa } }), h('i', { class: 'fb', style: { flex: pb } })), h('span', { class: 'pill b num' }, r.dB))); })));
} };
// variant 3 - strip: compact lower-third with several columns
PANEL_DEFS.stats_strip = { cls: 'p-strip', dep: () => S.stats.rows, render: () => {
  const A = S.teams.A, B = S.teams.B; const rows = statRows(G.stat_keys_strip || []);
  const pos = S.stats.rows.possession;
  return h('div', { class: 'strip' }, h('div', { class: 'tm', style: { '--t': A.color, '--tx': A.color2 || colorText(A.color) } }, badge(A), h('b', {}, A.short), h('span', { class: 'num' }, S.score.A)),
    h('div', { class: 'cells' }, ...rows.map(r => h('div', { class: 'cell' }, h('div', { class: 'vals num' }, h('b', { class: lead(r) === 'a' ? 'lead' : '' }, r.dA), h('b', { class: lead(r) === 'b' ? 'lead' : '' }, r.dB)), h('div', { class: 'lab' }, r.label.toUpperCase())))),
    h('div', { class: 'tm r', style: { '--t': B.color, '--tx': B.color2 || colorText(B.color) } }, h('span', { class: 'num' }, S.score.B), h('b', {}, B.short), badge(B)),
    pos && pos.A != null && !(G.stat_keys_strip || []).includes('possession') ? h('div', { class: 'pbar' }, h('i', { class: 'fa', style: { flex: pos.A } }), h('i', { class: 'fb', style: { flex: pos.B ?? (100 - pos.A) } })) : null);
} };
// single statistic page
PANEL_DEFS.stat_single = { cls: 'p-single', dep: () => S.stats.rows, render: () => {
  const r = S.stats.rows[SK()] || { label: SK(), A: null, B: null, dA: '-', dB: '-', kind: 'int' }; const A = S.teams.A, B = S.teams.B;
  const [pa, pb] = r.kind === 'pct' && r.key === 'possession' ? [(r.A || 0) / 100, (r.B || 0) / 100] : sh(r);
  const donut = r.key === 'possession' && r.A != null;
  return h('div', { class: 'single' }, h('div', { class: 'ss a', style: { '--t': A.color, '--tx': A.color2 || colorText(A.color) } }, badge(A), h('span', { class: 'n' }, A.short), h('b', { class: 'v num' }, r.dA)),
    h('div', { class: 'mid' }, h('div', { class: 'lab' }, r.label.toUpperCase()), donut ? h('div', { class: 'donut', style: { background: `conic-gradient(var(--ca) 0 ${pa * 100}%, var(--cb) ${pa * 100}% 100%)` } }, h('div', { class: 'hole' }, h('span', { class: 'num' }, Math.round(pa * 100) + '%'))) : h('div', { class: 'track' }, h('i', { class: 'fa', style: { flex: Math.max(pa, .001) } }), h('i', { class: 'fb', style: { flex: Math.max(pb, .001) } }))),
    h('div', { class: 'ss b', style: { '--t': B.color, '--tx': B.color2 || colorText(B.color) } }, h('b', { class: 'v num' }, r.dB), h('span', { class: 'n' }, B.short), badge(B)));
} };
// player card (manual player stats)
PANEL_DEFS.player_card = { cls: 'p-pcard', dep: () => [S.teams.A.players, S.teams.B.players], render: () => {
  const cp = G.card_player; const p = cp ? pl(S, cp.id) : null; if (!p) return h('div', { class: 'pc' }, h('div', { class: 'who' }, 'Choose a player in Production'));
  const t = S.teams[p.team || cp.team] || S.teams[cp.team]; const keys = G.player_stat_keys || [];
  const lab = { minutes: 'MIN', goals: 'GOALS', assists: 'ASSISTS', shots: 'SHOTS', shots_on_target: 'ON TARGET', passes: 'PASSES', passes_completed: 'PASSES OK', pass_accuracy: 'PASS ACC', tackles: 'TACKLES', interceptions: 'INTERCEPT.', saves: 'SAVES', rating: 'RATING', distance_km: 'KM', xg: 'xG', xa: 'xA', key_passes: 'KEY PASSES', touches: 'TOUCHES', dribbles: 'DRIBBLES', duels_won: 'DUELS', clearances: 'CLEAR.', fouls_committed: 'FOULS', fouls_won: 'FOULS WON', offsides: 'OFFSIDES', yellow_cards: 'YELLOW', red_cards: 'RED', goals_conceded: 'CONC.' };
  return h('div', { class: 'pc', style: { '--t': t.color, '--tx': t.color2 || colorText(t.color) } }, h('div', { class: 'no num' }, p.number ?? ''), h('div', { class: 'id' }, h('div', { class: 'nm' }, nameEl(p)), h('div', { class: 'tp' }, `${t.name.toUpperCase()}  ·  ${p.pos || ''}${p.captain ? '  ·  CAPTAIN' : ''}`)),
    h('div', { class: 'stats' }, keys.filter(k => p.stats[k]).map(k => h('div', { class: 'st' }, h('b', { class: 'num' }, p.stats[k].d), h('span', {}, lab[k] || k.toUpperCase())))));
} };
PANEL_DEFS.banner = { cls: 'p-banner', dep: () => G.banner, render: () => h('div', { class: 'bn' }, h('span', {}, (G.banner.text || '').toUpperCase())) };

// ------------------------------------------------------------- layout editor
// Real panels, rendered from sample matches replayed by the real engines (goscore/demo.py): a second-half match for
// everything except the shoot-out tracker, which needs a match that is in a shoot-out.
async function runEditor() {
  const d = await (await fetch('/api/layout/football/demo', { cache: 'no-store' })).json();
  const live = d.sets.live, so = d.sets.shootout;
  onPayload(live);
  loadPayload(so); renderTracker(); loadPayload(live);
  const row = [...live.state.timeline].reverse().find((r) => r.type === 'goal' && !r.cancelled);
  const pop = row && popFor(row);
  if (pop) showPop(pop[0], pop[1], Infinity);
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const { startEditor } = await import('../layout-editor.js');
  startEditor({ stage, sport: 'football', engine: layout, ids: d.ids, labels: FOOTBALL_LABELS });
}
const FOOTBALL_LABELS = { bug: 'Scorebug', tracker: 'Shoot-out tracker', popup: 'Event pop-up', 'pn-lineups': 'Line-ups', 'pn-formation_home': 'Formation (home)',
  'pn-formation_away': 'Formation (away)', 'pn-subs_bench': 'Substitutes', 'pn-halftime': 'Half-time card', 'pn-fulltime': 'Full-time card', 'pn-scorers': 'Goals',
  'pn-timeline': 'Match events', 'pn-preview': 'Match preview', 'pn-officials': 'Match officials', 'pn-stats_classic': 'Statistics (classic)', 'pn-stats_bars': 'Statistics (bars)',
  'pn-stats_strip': 'Statistics (strip)', 'pn-stat_single': 'Single statistic', 'pn-player_card': 'Player card', 'pn-banner': 'Banner' };
