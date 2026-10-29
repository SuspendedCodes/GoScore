// OBS overlay renderer. Data comes from the *published* feed (hold / delay aware).
import { h, Live, matchIdFromPath, groupByRole, tagOf } from './common.js';
import { createEngine } from './layout-engine.js';

const id = matchIdFromPath();
const qs = new URLSearchParams(location.search);
// Individual graphics use the same published feed as the normal overlay. Browser Sources use short polling requests
// rather than one long-lived SSE connection each, avoiding Chromium per-host connection limits in OBS.
const solo = qs.get('panel') || '';
// Individual panel URLs always follow Production visibility; no URL parameter can force a disabled panel on.
const follow = true;
const slideshowOnly = qs.get('slideshow') === '1';
let activeSlide = ''; let slideshowTimer = null; let slideshowSignature = '';
const only = solo ? [solo === 'bug' ? 'bug' : solo === 'popups' ? 'popups' : 'panels'] : (qs.get('only') || 'bug,popups,panels').split(',');
if (qs.get('preview')) document.body.classList.add('preview');
if (solo) document.body.classList.add('solo');
if (qs.get('bg')) document.body.style.background = qs.get('bg');
const stage = document.getElementById('stage');
function layoutSolo() {
  const el = solo === 'bug' ? document.getElementById('bug') : solo === 'popups' ? document.getElementById('popup') : ['batter_card', 'bowler_card'].includes(solo) ? document.getElementById('l-card') : document.getElementById('p-' + solo);
  if (!el) return;
  // Measure the untransformed graphic, not the 1920x1080 stage or its full-width
  // wrappers. offsetWidth/offsetHeight are intentionally used here because they do
  // not include the previous stage transform and therefore remain stable on resize.
  const w = Math.max(el.offsetWidth, el.scrollWidth), hh = Math.max(el.offsetHeight, el.scrollHeight);
  if (!w || !hh) return;
  const m = qs.get('pad') != null ? Math.max(0, +qs.get('pad') || 0) : 16;
  const mul = Math.max(0.2, Math.min(3, +qs.get('scale') || 1));
  const a = (qs.get('align') || 'c').toLowerCase();
  // Auto-fit is a shrink-to-fit operation: never enlarge a panel just because the
  // OBS Browser Source is 1920x1080. This keeps each graphic at its designed CSS
  // size on a 1080p canvas and only scales it down when the viewport is smaller.
  const fitScale = qs.get('fit') === '0' ? 1 : Math.min(1, innerWidth / (w + 2 * m), innerHeight / (hh + 2 * m));
  const sc = fitScale * mul;
  const ox = a.includes('l') ? m * sc : a.includes('r') ? innerWidth - (w + m) * sc : (innerWidth - w * sc) / 2;
  const oy = a.includes('t') ? m * sc : a.includes('b') ? innerHeight - (hh + m) * sc : (innerHeight - hh * sc) / 2;
  stage.style.width = w + 'px'; stage.style.height = hh + 'px';
  stage.style.transform = `translate(${ox}px,${oy}px) scale(${sc})`;
}
function fit() { if (qs.get('edit') === '1') return; if (solo) { layoutSolo(); return; } const sc = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `scale(${sc})`; }
addEventListener('resize', fit); fit();
// Saved layout boxes (see layout-engine.js). Individual-panel URLs (?panel=) size themselves, so they ignore the layout.
const edit = qs.get('edit') === '1';
const layout = solo ? null : createEngine({ stage, sport: 'cricket' });
if (layout && !edit) layout.poll();
const managed = (k) => !!(layout && layout.boxes.has(k));

let P = null, seenEvent = null, seenPopup = null, firstPayload = true, popTimer = null;
const $ = (s) => document.getElementById(s);
const nameOfTeam = (S, tid) => S.teams[tid];
// Reuse loaded logo nodes across scorebug refreshes. Recreating an <img> on every
// score update causes visible decode/repaint flicker in OBS Browser Sources.
const logoNodes = new Map();
function logoNode(url) {
  if (!url) return null;
  let node = logoNodes.get(url);
  if (!node) { node = document.createElement('img'); node.alt = ''; node.decoding = 'async'; node.src = url; logoNodes.set(url, node); }
  return node;
}

function onPayload(payload) {
  P = payload; const S = payload.state, G = payload.graphics;
  if (slideshowOnly) syncSlideshow(G);
  const c = S.current;
  document.documentElement.style.setProperty('--c', c ? c.batting.color : S.teams.A.color);
  stage.style.setProperty('--c', c ? c.batting.color : S.teams.A.color);
  stage.style.setProperty('--c2', c ? c.bowling.color : S.teams.B.color);
  if (only.includes('bug')) renderBug(S, G);
  if (only.includes('panels')) renderPanels(S, G);
  if (only.includes('popups')) handlePopups(S, G);
  if (solo) requestAnimationFrame(layoutSolo);
  firstPayload = false;
}
if (!edit) new Live(id, 'pub', onPayload, () => {}, { releaseWhenHidden: false, stream: false, pollMs: 1500 });
else runEditor();

// ------------------------------------------------------------- scorebug
function chip(b) { return h('span', { class: 'chip ' + b.kind }, b.label); }
function renderBug(S, G) {
  const bug = $('bug'); const c = S.current;
  const visible = G.scorebug || (solo === 'bug' && !follow);
  bug.className = 'pos-' + (G.position || 'bottom') + (visible ? '' : ' off');
  if (!managed('bug')) bug.style.transform = visible && !solo && !edit ? `scale(${G.scale || 1})` : '';
  if (!c) {
    bug.replaceChildren(h('div', { class: 'bug' }, h('div', { class: 'b-main' }, h('div', { class: 'b-team' }, h('div', { class: 'bar' }), h('span', { class: 'nm' }, S.teams.A.short)),
      h('div', { class: 'b-score' }, h('span', { class: 'sc', style: { fontSize: '40px' } }, 'v')), h('div', { class: 'b-team', style: { background: S.teams.B.color } }, h('div', { class: 'bar' }), h('span', { class: 'nm' }, S.teams.B.short)),
      h('div', { class: 'b-bowl' }, h('div', { style: { fontSize: '30px', fontWeight: 700 } }, S.title || 'Match starting soon'))), h('div', { class: 'b-status' }, h('span', {}, S.venue || ''))));
    return;
  }
  const st = c.striker, ns = c.non_striker, bw = c.bowler;
  // Keep the name slot in the layout, but make it invisible when no player is selected.
  // This avoids broadcast-unfriendly dash placeholders between wickets/overs.
  const playerName = (p, cls) => h('span', { class: p ? '' : 'empty-player-name' }, p ? p.short + (cls ? '' : ' *') : '');
  const line = (p, cls) => h('div', { class: 'p-line ' + (cls || '') }, playerName(p, cls), h('span', { class: 'r num' }, p ? [p.runs, h('span', { class: 'b' }, ` (${p.balls})`)] : ''));
  const pl = S.play;
  const leadBox = () => { const d = c.lead; const opp = S.teams[c.bowling.id]; const oppSc = pl && pl.scores ? pl.scores[c.bowling.id] : '';
    return h('div', { class: 'b-right' }, h('div', { class: 'sm' }, d == null ? 'CRR' : d > 0 ? 'LEAD BY' : d < 0 ? 'TRAIL BY' : 'SCORES'), h('div', { class: 'big num' }, d == null ? c.crr.toFixed(2) : d === 0 ? 'LEVEL' : Math.abs(d)),
      oppSc ? h('div', { class: 'sm num' }, `${opp.short} ${oppSc}`) : null); };
  const mode = G.target_display || 'runs';
  const needRuns = c.need != null ? (c.need > 0 ? `NEED ${c.need} RUNS` : 'TARGET MET') : '';
  const needWickets = c.need === 0 ? 'TARGET MET' : c.innings_status !== 'in_progress' ? 'CHASE ENDED' : (c.wickets_left != null ? `BOWLERS NEED ${c.wickets_left} WICKETS` : '');
  const targetLines = mode === 'both' ? [needRuns, needWickets] : mode === 'wickets' ? [needWickets] : [needRuns];
  const right = pl && c.target == null ? leadBox() : c.target != null
    ? h('div', { class: 'b-right' }, h('div', { class: 'sm' }, 'TARGET ' + c.target), h('div', { class: 'big num' }, ...targetLines.map((txt) => h('div', { class: 'target-line' }, txt))), c.balls_left != null ? h('div', { class: 'sm num' }, `FROM ${c.balls_left} BALLS`) : null)
    : h('div', { class: 'b-right' }, h('div', { class: 'sm' }, 'CRR'), h('div', { class: 'big num' }, c.crr.toFixed(2)), c.projected ? h('div', { class: 'sm num' }, 'PROJ ' + c.projected) : null);
  const delayTxt = S.delay;
  bug.replaceChildren(h('div', { class: 'bug' },
    h('div', { class: 'b-main' },
      h('div', { class: 'b-team' }, h('div', { class: 'bar' }), c.batting.logo ? logoNode(c.batting.logo) : null, h('span', { class: 'nm' }, c.batting.short)),
      h('div', { class: 'b-score' }, h('span', { class: 'sc num' }, c.score), h('span', { class: 'ov num' }, `${c.overs}${c.overs_limit ? '/' + c.overs_limit : ''}`)),
      h('div', { class: 'b-players' }, line(st), line(ns, 'ns')),
      h('div', { class: 'b-bowl' }, h('div', { class: 'p-line' }, h('span', { class: bw ? '' : 'empty-player-name' }, bw ? bw.short : ''), h('span', { class: 'r num' }, bw ? `${bw.wickets}-${bw.runs}` : ''), h('span', { class: 'b num', style: { opacity: .7, fontWeight: 500 } }, bw ? `${bw.overs} ov` : '')),
        h('div', { class: 'chips' }, c.this_over.balls.slice(-8).map(chip))),
      right),
    h('div', { class: 'b-status' }, h('span', {}, delayTxt ? 'DELAY · ' + delayTxt : c.status_line), h('span', { class: 'sp' }),
      c.free_hit ? h('span', { class: 'tag fh' }, 'FREE HIT') : null, c.powerplay ? h('span', { class: 'tag pp' }, c.powerplay.toUpperCase()) : null,
      pl ? testTags(pl) : null,
      pl ? null : c.target == null ? null : h('span', { class: 'stat num' }, c.rrr != null ? `RRR ${c.rrr.toFixed(2)}  ·  ` : '', `CRR ${c.crr.toFixed(2)}`),
      c.kind === 'super_over' ? h('span', { class: 'tag pp' }, 'SUPER OVER') : null)));
}

// Test / multi-day extras in the status row: day & session, follow-on, overs left, new ball
function testTags(pl) {
  const out = [h('span', { class: 'tag pp' }, `DAY ${pl.day}${pl.days ? '/' + pl.days : ''} · S${pl.session}`)];
  if (pl.follow_on) out.push(h('span', { class: 'tag pp' }, 'FOLLOWING ON'));
  if (pl.overs_left != null) out.push(h('span', { class: 'stat num' }, `${pl.overs_left} OV LEFT`));
  if (pl.new_ball_available) out.push(h('span', { class: 'tag nb' }, 'NEW BALL DUE'));
  else if (pl.new_ball_due != null && pl.new_ball_after && pl.today && parseFloat(pl.new_ball_due) <= 10) out.push(h('span', { class: 'stat num' }, `NEW BALL IN ${pl.new_ball_due}`));
  return h('span', { class: 'row-tags' }, ...out);
}

// ------------------------------------------------------------- popups
function showPop(kind, head, body, sub, ms = 4500) {
  const el = $('popup'); clearTimeout(popTimer);
  const pop = h('div', { class: 'pop ' + kind }, h('div', { class: 'hd' }, head), body || sub ? h('div', { class: 'bd' }, body, sub ? h('div', { class: 'sub' }, sub) : null) : null);
  el.replaceChildren(pop); requestAnimationFrame(() => requestAnimationFrame(() => pop.classList.add('in')));
  if (Number.isFinite(ms)) popTimer = setTimeout(() => { pop.classList.remove('in'); setTimeout(() => { if (el.firstChild === pop) el.replaceChildren(); }, 500); }, ms);
}
function handlePopups(S, G) {
  const en = G.popups_enabled || {}; const now = S.server_time;
  // If Production disables a category while its animation is on screen, remove it immediately.
  const activePop = $('popup').firstElementChild;
  if (activePop) {
    const activeClass = [...activePop.classList].find(k => ['four', 'six', 'wicket', 'milestone', 'freehit'].includes(k));
    const activeKey = ({ four: 'four', six: 'six', wicket: 'wicket', milestone: 'milestone', freehit: 'free_hit' })[activeClass];
    if (activeKey && !en[activeKey]) { clearTimeout(popTimer); $('popup').replaceChildren(); }
  }
  const le = S.last_event; const c = S.current;
  if (G.popup && G.popup.id !== seenPopup) {
    const first = seenPopup === null && firstPayload;
    seenPopup = G.popup.id;
    // Manual pop-ups obey the same Production event switches as automatic pop-ups.
    // A disabled event is consumed but never displayed later if its switch is re-enabled.
    const manualKey = { four: 'four', six: 'six', wicket: 'wicket', fifty: 'milestone', hundred: 'milestone', freehit: 'free_hit' }[G.popup.kind];
    const manualAllowed = !manualKey || !!en[manualKey];
    if (manualAllowed && !first && now - G.popup.ts < 8000) { const k = G.popup.kind; const map = { four: ['FOUR!', 'four'], six: ['SIX!', 'six'], wicket: ['WICKET!', 'wicket'], fifty: ['FIFTY!', 'milestone'], hundred: ['HUNDRED!', 'milestone'], freehit: ['FREE HIT', 'freehit'] }; const [head, cls] = map[k] || [G.popup.text || '', 'custom']; showPop(cls, head, k === 'custom' ? null : G.popup.text, null); }
  }
  if (le && le.id !== seenEvent) {
    const first = firstPayload && seenEvent === null; seenEvent = le.id;
    if (first || now - le.ts > 8000 || le.type !== 'ball') return;
    const lb = c && c.last_ball;
    if (le.wicket && en.wicket) {
      const w = le.wicket; showPop('wicket', 'WICKET!', `${w.out_name}  ${w.runs} (${w.balls})`, `${w.how}  ·  ${c.score}`, 6500);
    } else if (le.milestone && en.milestone) {
      const m = le.milestone; showPop('milestone', m.runs === 50 ? 'FIFTY!' : m.runs === 100 ? 'HUNDRED!' : `${m.runs}!`, `${m.name}  ${m.runs} (${m.balls})`, null, 5500);
    } else if (le.kind === 'six' && en.six) showPop('six', 'SIX!', lb ? lb.striker_name : '', null, 3800);
    else if (le.kind === 'four' && en.four) showPop('four', 'FOUR!', lb ? lb.striker_name : '', null, 3800);
    else if (le.label && le.label.startsWith('Nb') && en.free_hit && c && c.free_hit) showPop('freehit', 'FREE HIT', 'No-ball — next delivery is a free hit', null, 4500);
  }
}

// ------------------------------------------------------------- panels
const PANELS = ['testsum', 'innsum', 'worm', 'scorecard', 'bowling', 'partnership', 'fow', 'target', 'teams', 'toss', 'result', 'overs', 'banner', 'summary'];
function ensure(idn, parent = 'panels') { let e = $(idn); if (!e) { e = h('div', { class: 'pn', id: idn }); $(parent).append(e); } return e; }
function head(title, right) { return h('div', { class: 'ph' }, h('span', {}, title), right ? h('span', { class: 'mut num' }, right) : null); }
const ORD = ['1ST', '2ND', '3RD', '4TH', '5TH', '6TH'];
const innLabel = (inn) => inn.kind === 'super_over' ? 'SUPER OVER' : ORD[inn.index] + ' INNINGS';
function innFor(S, G) { const i = G.scorecard_innings != null ? G.scorecard_innings : S.current_innings; return i != null ? S.innings[i] : null; }

function syncSlideshow(G) {
  const cfg = G.slideshow || {};
  const slides = (cfg.slides || ['innsum', 'scorecard', 'bowling', 'teams', 'summary']).filter(k => G.panels && G.panels[k]);
  const signature = JSON.stringify([!!cfg.enabled, Math.max(5, Math.min(120, +cfg.interval || 12)), slides]);
  if (signature === slideshowSignature) return;
  slideshowSignature = signature; clearInterval(slideshowTimer); slideshowTimer = null;
  activeSlide = slides[0] || '';
  if (cfg.enabled && slides.length > 1) slideshowTimer = setInterval(() => { const i = slides.indexOf(activeSlide); activeSlide = slides[(i + 1) % slides.length]; if (P) renderPanels(P.state, P.graphics); }, Math.max(5, Math.min(120, +cfg.interval || 12)) * 1000);
}
// replaceChildren() would print the text "null" for an absent optional block, so drop those first
const fill = (el, ...kids) => el.replaceChildren(...kids.filter((k) => k != null && k !== false));
function renderPanels(S, G, only) {
  const allow = (n) => !only || only(n);
  const P_ = G.panels || {};
  const slideMode = slideshowOnly && !!(G.slideshow && G.slideshow.enabled);
  if (slideMode && !activeSlide) activeSlide = ((G.slideshow && G.slideshow.slides) || []).find(k => P_[k]) || '';  const inn = innFor(S, G); const c = S.current;
  const soloReady = { testsum: !!S.play, scorecard: !!inn, bowling: !!inn, partnership: !!c, fow: !!inn,
    target: !!(c && c.target != null), overs: !!inn, innsum: !!inn, worm: S.innings.length > 0 };
  const set = (name, on, build) => { if (!allow(name)) return; const el = ensure('p-' + name);
    const ready = soloReady[name] !== false;
    const visible = solo ? (solo === name && ready && (follow ? !!on : true)) : slideMode ? (name === activeSlide && ready && !!on) : slideshowOnly ? false : !!on;
    el.classList.toggle('show', visible); if (visible) { build(el); } };
  set('testsum', P_.testsum && S.play, (el) => {
    const pl = S.play; const rows = ['A', 'B'].map(t => h('tr', {}, h('td', {}, S.teams[t].name), h('td', { class: 'num' }, pl.scores[t] || '—')));
    const cell = (l, v) => h('div', { class: 'cell' }, h('b', { class: 'num' }, v), h('span', {}, l));
    const ld = pl.lead; const fil = pl.first_innings_lead;
    fill(el, head(pl.break ? `${pl.label} · ${(S.delay || '').toUpperCase()}` : pl.label, S.format.label),
      h('div', { class: 'pb' }, h('table', {}, h('tbody', {}, rows)),
        h('div', { class: 'big' }, S.result.final ? S.result.text : c && c.status_line ? c.status_line : ''),
        h('div', { class: 'cells' }, cell('TODAY', `${pl.today.runs}/${pl.today.wickets}`), cell('OVERS TODAY', pl.today.overs), cell('THIS SESSION', `${pl.session_stats.runs}/${pl.session_stats.wickets}`),
          pl.overs_left != null ? cell('OVERS LEFT', pl.overs_left) : null, pl.new_ball_after ? cell(pl.new_ball_available ? 'NEW BALL' : 'NEW BALL IN', pl.new_ball_available ? 'DUE' : pl.new_ball_due) : null),
        fil && !S.result.final && ld == null ? h('div', { class: 'mut' }, `${S.teams[fil.team].name} lead on first innings by ${fil.runs}`) : null));
  });
  set('scorecard', P_.scorecard && inn, (el) => {
    const rows = inn.batters.filter(b => b.status !== 'yet_to_bat').map(b => h('tr', { class: b.on_strike ? 'strike' : (b.status === 'out' ? 'dim' : '') }, h('td', {}, b.name + (b.tag || '') + (b.on_strike ? ' *' : ''), h('span', { class: 'how' }, b.status_text)), h('td', { class: 'num' }, b.runs), h('td', { class: 'num' }, b.balls), h('td', { class: 'num' }, b.fours), h('td', { class: 'num' }, b.sixes), h('td', { class: 'num' }, b.sr.toFixed(1))));
    const yet = inn.batters.filter(b => b.status === 'yet_to_bat').map(b => b.short).join(', ');
    fill(el, head(`${inn.batting_name.toUpperCase()} · ${innLabel(inn)}`, `${inn.runs}/${inn.wickets}  (${inn.overs} ov)`), h('div', { class: 'pb' }, h('table', {}, h('thead', {}, h('tr', {}, ['Batter', 'R', 'B', '4s', '6s', 'SR'].map(x => h('th', {}, x)))), h('tbody', {}, rows,
      h('tr', { class: 'tot' }, h('td', {}, 'Extras'), h('td', { colspan: 5, class: 'num' }, `${inn.extras.total}  (b ${inn.extras.bye}, lb ${inn.extras.legbye}, w ${inn.extras.wide}, nb ${inn.extras.noball}, p ${inn.extras.penalty})`)))), yet ? h('div', { class: 'mut', style: { fontSize: '22px', marginTop: '8px' } }, 'Yet to bat: ' + yet) : null));
  });
  set('bowling', P_.bowling && inn, (el) => {
    fill(el, head(`${S.teams[inn.bowling].name.toUpperCase()} BOWLING`, innLabel(inn)), h('div', { class: 'pb' }, h('table', {}, h('thead', {}, h('tr', {}, ['Bowler', 'O', 'M', 'R', 'W', 'Econ'].map(x => h('th', {}, x)))), h('tbody', {}, inn.bowlers.map(b => h('tr', { class: b.is_current ? 'strike' : '' }, h('td', {}, b.name + (b.tag || '')), h('td', { class: 'num' }, b.overs), h('td', { class: 'num' }, b.maidens), h('td', { class: 'num' }, b.runs), h('td', { class: 'num' }, b.wickets), h('td', { class: 'num' }, b.econ.toFixed(2))))))));
  });
  set('partnership', P_.partnership && c, (el) => {
    const p = c.partnership; const prev = inn ? inn.partnerships.slice(-3).reverse() : [];
    fill(el, head('PARTNERSHIP', p ? `${p.runs} runs · ${p.balls} balls` : ''), h('div', { class: 'pb' }, p ? p.pair.map(x => h('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: '30px', fontWeight: 800 } }, h('span', {}, x.name), h('span', { class: 'num' }, `${x.runs} (${x.balls})`))) : h('div', { class: 'mut' }, 'New partnership'),
      p ? h('div', { class: 'mut', style: { fontSize: '22px' } }, `Extras ${p.extras}  ·  wicket ${p.wicket_no}`) : null,
      prev.length ? h('div', { style: { marginTop: '10px', fontSize: '22px' }, class: 'mut' }, 'Previous: ' + prev.map(x => `${x.runs} (${x.balls})`).join(' · ')) : null));
  });
  set('fow', P_.fow && inn, (el) => {
    fill(el, head(`FALL OF WICKETS · ${innLabel(inn)}`, inn.batting_name), h('div', { class: 'pb' }, inn.fow.length ? inn.fow.map(f => h('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: '24px', padding: '2px 0' } }, h('span', {}, `${f.wicket}-${f.score}`), h('span', {}, f.name), h('span', { class: 'mut num' }, `${f.over} ov`))) : h('div', { class: 'mut' }, 'No wickets yet')));
  });
  set('target', P_.target && c && c.target != null, (el) => {
    const mode = G.target_display || 'runs';
    const info = [];
    if (mode !== 'wickets') info.push(h('span', { class: 'num' }, c.need > 0 ? `${c.need} runs required` : 'Target met'));
    if (mode !== 'runs') info.push(h('span', { class: 'num' }, c.need === 0 ? 'Target met' : c.innings_status !== 'in_progress' ? 'Chase ended' : `Bowling side needs ${c.wickets_left ?? '—'} wickets`));
    if (c.balls_left != null) info.push(h('span', { class: 'num' }, `${c.balls_left} balls left`));
    if (mode !== 'wickets' && c.rrr != null) info.push(h('span', { class: 'num' }, `Req ${c.rrr.toFixed(2)}`));
    if (mode !== 'wickets') info.push(h('span', { class: 'num' }, `CRR ${c.crr.toFixed(2)}`));
    fill(el, head('CHASE REQUIREMENTS', `Target ${c.target}`), h('div', { class: 'pb target-requirements' }, ...info));
  });
  set('teams', P_.teams, (el) => {
    const col = (t) => h('div', {}, h('h4', {}, t.name), groupByRole(t.players.filter(p => p.xi), (p) => p.role, ['batter', 'allrounder', 'bowler', '']).map(g => h('div', {}, g.title ? h('div', { class: 'mut', style: { fontSize: '20px', margin: '8px 0 2px', letterSpacing: '.08em', textTransform: 'uppercase' } }, g.title) : null, g.items.map(p => h('div', {}, p.name + tagOf(p))))), t.players.some(p => !p.xi && !p.subbed_out) ? h('div', { class: 'mut', style: { marginTop: '8px', fontSize: '20px' } }, 'Bench: ' + t.players.filter(p => !p.xi && !p.subbed_out).map(p => p.short || p.name).join(', ')) : null);
    fill(el, head('TEAMS', S.title), h('div', { class: 'pb two' }, col(S.teams.A), col(S.teams.B)));
  });
  set('toss', P_.toss, (el) => {
    const t = S.toss || {}; const txt = t.winner ? `${S.teams[t.winner].name} won the toss and chose to ${t.decision === 'bowl' ? 'bowl' : 'bat'} first` : 'Toss to come';
    fill(el, head('TOSS', S.format.label), h('div', { class: 'pb', style: { fontSize: '42px', fontWeight: 800, textAlign: 'center', padding: '30px' } }, txt));
  });
  const summaryBuild = (title) => (el) => {
    const res = S.result;
    fill(el, head(title, S.title), h('div', { class: 'pb res' }, ...S.innings.filter(i => i.kind === 'regular' || true).map(i => h('div', { class: 'line' }, h('span', {}, i.batting_name + (i.kind === 'super_over' ? ' (Super Over)' : '')), h('b', { class: 'num' }, `${i.runs}/${i.wickets}  (${i.overs})`))),
      h('div', { class: 'big' }, res.text || S.status.replace('_', ' ').toUpperCase())));
  };
  set('result', P_.result, summaryBuild('RESULT'));
  set('summary', P_.summary, summaryBuild('MATCH SUMMARY'));
  set('overs', P_.overs && inn, (el) => {
    fill(el, head(`OVER BY OVER · ${innLabel(inn)}`, inn.batting_name), h('div', { class: 'pb' }, (G.overs_start != null && Number.isFinite(+G.overs_start) && +G.overs_start >= 1 ? inn.overs_detail.filter(o => o.n >= +G.overs_start && o.n < +G.overs_start + 10) : inn.overs_detail.slice(-10)).slice().reverse().map(o => h('div', { class: 'ov-row' }, h('span', { class: 'n' }, 'Over ' + o.n), h('div', { class: 'chips' }, o.balls.map(chip)), h('span', { class: 't num' }, o.runs)))));
  });
  set('innsum', P_.innsum && inn, (el) => {
    const bat = inn.batters.filter(b => b.status !== 'yet_to_bat').sort((a, b) => b.runs - a.runs || a.balls - b.balls).slice(0, 3);
    const bow = inn.bowlers.slice().sort((a, b) => b.wickets - a.wickets || a.runs - b.runs).slice(0, 3);
    const row = (l, r) => h('div', { style: { display: 'flex', justifyContent: 'space-between', gap: '20px', fontSize: '28px', fontWeight: 700, padding: '3px 0' } }, h('span', {}, l), h('span', { class: 'num' }, r));
    const nxt = S.innings[inn.index + 1], chase = S.current && S.current.target != null && inn.index === 0 ? S.current : null;
    fill(el, head(`${inn.batting_name.toUpperCase()} · ${innLabel(inn)}`, `${inn.runs}/${inn.wickets}  (${inn.overs} ov)`),
      h('div', { class: 'pb two' }, h('div', {}, h('h4', {}, 'TOP BATTERS'), bat.map(b => row(b.name + (b.status === 'out' ? '' : '*'), `${b.runs} (${b.balls})`))),
        h('div', {}, h('h4', {}, 'TOP BOWLERS'), bow.map(b => row(b.name, `${b.wickets}-${b.runs} (${b.overs})`)))),
      chase ? h('div', { class: 'pb', style: { fontWeight: 800, fontSize: '30px', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,.15)' } }, `${chase.batting.name} need ${chase.need} from ${chase.balls_left ?? '—'} balls`) : null);
  });
  set('worm', P_.worm && S.innings.length, (el) => {
    const W = 900, H = 360, L = 56, B = 40, T = 16, R = 16;
    const series = S.innings.filter(i => i.kind === 'regular').map(i => { let t = 0; const pts = [[0, 0]]; i.overs_detail.forEach(o => { t += o.runs; pts.push([o.n, t]); }); return { i, pts, col: S.teams[i.batting].color }; });
    const maxX = Math.max(S.format.overs || 0, ...series.map(s => s.pts[s.pts.length - 1][0]), 1), maxY = Math.max(10, ...series.map(s => s.pts[s.pts.length - 1][1]));
    const x = (v) => L + (W - L - R) * v / maxX, y = (v) => H - B - (H - B - T) * v / (Math.ceil(maxY / 20) * 20);
    const yMax = Math.ceil(maxY / 20) * 20; const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', W); svg.setAttribute('height', H);
    const add = (tag, a, txt) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; svg.append(e); return e; };
    for (let v = 0; v <= yMax; v += yMax / 4) { add('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: 'rgba(255,255,255,.15)' }); add('text', { x: L - 8, y: y(v) + 7, fill: '#aab', 'font-size': 20, 'text-anchor': 'end' }, Math.round(v)); }
    for (let v = 0; v <= maxX; v += Math.max(1, Math.round(maxX / 10))) add('text', { x: x(v), y: H - 12, fill: '#aab', 'font-size': 20, 'text-anchor': 'middle' }, v);
    series.forEach(sr => { add('polyline', { points: sr.pts.map(p => `${x(p[0])},${y(p[1])}`).join(' '), fill: 'none', stroke: sr.col, 'stroke-width': 5, 'stroke-linejoin': 'round' });
      sr.i.fow.forEach(f => { const [fo, fb] = String(f.over).split('.').map(Number); const ov = fo + (fb || 0) / (S.format.balls_per_over || 6); const near = sr.pts.reduce((a, p) => Math.abs(p[0] - ov) < Math.abs(a[0] - ov) ? p : a, sr.pts[0]); add('circle', { cx: x(ov), cy: y(f.score), r: 7, fill: '#fff', stroke: sr.col, 'stroke-width': 3 }); }); });
    fill(el, head('INNINGS COMPARISON', 'runs by over'), h('div', { class: 'pb' }, svg, h('div', { style: { display: 'flex', gap: '30px', fontSize: '24px', fontWeight: 800 } }, series.map(sr => h('span', { style: { color: sr.col } }, `${sr.i.batting_name} ${sr.i.runs}/${sr.i.wickets}`)), h('span', { class: 'mut', style: { fontWeight: 500 } }, 'Wicket markers'))));
  });
  set('banner', P_.banner && (G.banner || {}).text, (el) => { fill(el, h('div', { class: 'pb' }, G.banner.text)); });
  // colour every panel by the team whose innings it shows (so an old innings never looks like the live one)
  if (allow('l-card') && inn) { const bc = S.teams[inn.batting].color, wc = S.teams[inn.bowling].color;
    for (const [k, col] of [['scorecard', bc], ['bowling', wc], ['partnership', bc], ['fow', bc], ['overs', bc], ['innsum', bc], ['worm', bc]]) { const e = $('p-' + k); if (e) e.style.setProperty('--c', col); } }
  // lower third card (batter / bowler)
  if (!allow('l-card')) return;
  const lower = ensure('l-card', 'lower');
  let which = solo
    ? (!follow ? (solo === 'batter_card' ? 'bat' : solo === 'bowler_card' ? 'bowl' : null)
      : (solo === 'batter_card' ? (P_.batter_card ? 'bat' : null) : solo === 'bowler_card' ? (P_.bowler_card ? 'bowl' : null) : null))
    : (P_.batter_card ? 'bat' : P_.bowler_card ? 'bowl' : null);
  if (which && inn) {
    let pid = G.card_player || (which === 'bat' ? inn.striker : inn.bowler);
    const bat = inn.batters.find(b => b.id === pid), bowl = inn.bowlers.find(b => b.id === pid);
    const tm = (pid || '')[0]; 
    if (which === 'bat' || (bat && !bowl)) {
      const b = bat || inn.batters.find(x => x.id === inn.striker);
      if (b) { lower.classList.add('show'); fill(lower, head('BATTING', b.status_text), h('div', { class: 'pb card' }, h('div', { class: 'nm' }, b.name), h('div', { style: { display: 'flex', alignItems: 'baseline', gap: '24px' } }, h('div', { class: 'big num' }, b.runs), h('div', { style: { fontSize: '40px', opacity: .8 }, class: 'num' }, `(${b.balls})`)), h('div', { class: 'st' }, h('div', {}, h('b', { class: 'num' }, b.fours), 'FOURS'), h('div', {}, h('b', { class: 'num' }, b.sixes), 'SIXES'), h('div', {}, h('b', { class: 'num' }, b.sr.toFixed(1)), 'STRIKE RATE')))); }
      else lower.classList.remove('show');
    } else {
      const b = bowl || inn.bowlers.find(x => x.id === inn.bowler);
      if (b) { lower.classList.add('show'); fill(lower, head('BOWLING', ''), h('div', { class: 'pb card' }, h('div', { class: 'nm' }, b.name), h('div', { style: { display: 'flex', alignItems: 'baseline', gap: '24px' } }, h('div', { class: 'big num' }, `${b.wickets}-${b.runs}`), h('div', { style: { fontSize: '40px', opacity: .8 }, class: 'num' }, `(${b.overs})`)), h('div', { class: 'st' }, h('div', {}, h('b', { class: 'num' }, b.maidens), 'MAIDENS'), h('div', {}, h('b', { class: 'num' }, b.econ.toFixed(2)), 'ECONOMY'), h('div', {}, h('b', { class: 'num' }, b.dots), 'DOTS')))); }
      else lower.classList.remove('show');
    }
  } else lower.classList.remove('show');
}

// ------------------------------------------------------------- layout editor
// The editor renders the real panels from sample matches that were replayed by the real engines (see goscore/demo.py),
// so what is dragged around is exactly what appears on air. Three samples are needed: a T20 chase in progress for most
// graphics, a Test match for the multi-day summary, and a finished match for the result / summary panels.
async function runEditor() {
  const d = await (await fetch('/api/layout/cricket/demo', { cache: 'no-store' })).json();
  const main = d.sets.limited, test = d.sets.test, fin = d.sets.final;
  const draw = (pl, only) => {
    const S = pl.state, G = pl.graphics, c = S.current;
    stage.style.setProperty('--c', c ? c.batting.color : S.teams.A.color); stage.style.setProperty('--c2', c ? c.bowling.color : S.teams.B.color);
    return [S, G, only];
  };
  P = main;
  { const [S, G] = draw(main); renderBug(S, G); renderPanels(S, G, (n) => !['testsum', 'result', 'summary'].includes(n)); }
  { const [S, G] = draw(test); renderPanels(S, G, (n) => n === 'testsum'); }
  { const [S, G] = draw(fin); renderPanels(S, G, (n) => n === 'result' || n === 'summary'); }
  draw(main);
  const S = main.state, inn = S.innings[S.current_innings], f = inn.fow[inn.fow.length - 1];
  if (f) { const b = inn.batters.find((x) => x.name === f.name) || {}; showPop('wicket', 'WICKET!', `${f.name}  ${b.runs} (${b.balls})`, `${b.status_text}  \u00b7  ${S.current.score}`, Infinity); }
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const { startEditor } = await import('./layout-editor.js');
  startEditor({ stage, sport: 'cricket', engine: layout, ids: d.ids, labels: CRICKET_LABELS });
}
const CRICKET_LABELS = { bug: 'Scorebug', popup: 'Event pop-up', 'l-card': 'Player card (lower third)', 'p-testsum': 'Match summary (Test)', 'p-innsum': 'Innings summary',
  'p-scorecard': 'Scorecard', 'p-bowling': 'Bowling', 'p-partnership': 'Partnership', 'p-fow': 'Fall of wickets', 'p-overs': 'Over by over', 'p-worm': 'Innings comparison',
  'p-target': 'Chase requirements', 'p-teams': 'Teams', 'p-toss': 'Toss', 'p-result': 'Result', 'p-banner': 'Banner', 'p-summary': 'Match summary' };
