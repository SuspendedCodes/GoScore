import { api, h, $, toast, modal, confirmBox, select, num, uid, Live, setConn, matchIdFromPath, describeEvent, DISMISSALS, ALLOWED_OFF, FREE_HIT_ALLOWED, STRIKER_ONLY, playersOf, pname, pshort, ApiError, ROLE_ONE, roleOf, groupByRole, tagOf, sectionedSelect, ROLE_GROUPS } from './common.js';
import { inningsCard } from './cardview.js';

const id = matchIdFromPath();
let S = null, version = 0, canRedo = false, tab = 'card', evCache = null, openModals = 0;
const mods = { wide: false, noball: false, bye: false, legbye: false };
const FORCE = { consecutive_overs: 'consecutive', bowler_quota: 'quota', midover_change: 'midover', prev_open: 'prev_open', same_team: 'same_team', follow_on: 'follow_on' };
const dismissedPrompts = new Set();

$('#lControl').href = `/control/${id}`; $('#lCard').href = `/scorecard/${id}`; $('#lOv').href = `/overlay/${id}`; $('#lSetup').href = `/setup/${id}`;

const live = new Live(id, 'live', (d) => {
  if (d.version < version) return;
  S = d.state; version = d.version; render();
}, (st) => setConn($('#conn'), st));
api('GET', `/api/matches/${id}/state`).then(d => { canRedo = d.can_redo; }).catch(() => {});

// ------------------------------------------------------------------ posting events
async function post(ev, { quiet = false } = {}) {
  ev.cid = uid(); ev.expected_version = version;
  try {
    const r = await api('POST', `/api/matches/${id}/events`, ev);
    if (r.version) version = Math.max(version, r.version);
    canRedo = false; evCache = null;
    return r;
  } catch (e) {
    const err = e.payload && e.payload.error;
    if (e.status === 422 && err && err.soft && FORCE[err.code]) {
      if (await confirmBox(`${err.message}\n\nThis is a competition rule, not a Law of cricket. Allow it anyway? (it will be logged)`, 'Allow anyway')) {
        return post({ ...ev, cid: undefined, force: [...(ev.force || []), FORCE[err.code]] }, { quiet });
      }
      return null;
    }
    if (e.status === 409) { toast(e.message, 'warn', 6000); await refresh(); return null; }
    if (!quiet) toast(e.message + (err && err.hint ? ' — ' + err.hint : ''), 'bad', 7000);
    return null;
  }
}
async function refresh() { const d = await api('GET', `/api/matches/${id}/state`); S = d.state; version = d.version; canRedo = d.can_redo; render(); }
const inn = () => (S && S.current_innings != null ? S.innings[S.current_innings] : null);
const cur = () => S && S.current;
const live_ok = () => cur() && cur().innings_status === 'in_progress';

// ------------------------------------------------------------------ rendering
function render() {
  if (!S) return;
  document.title = `${S.title} · Scorer`;
  $('#title').textContent = S.title || 'Match';
  renderStrip(); renderAlerts(); renderLeft(); renderPad(); renderTabs();
  autoPrompts();
}
function renderStrip() {
  const c = cur(); const el = $('#strip'); el.replaceChildren();
  if (!c) { el.append(h('span', { class: 'mute' }, `${S.teams.A.name} v ${S.teams.B.name} — not started`)); return; }
  el.append(...[
    h('div', {}, h('div', { class: 'mute small' }, c.batting.name + (c.kind === 'super_over' ? ' · SUPER OVER' : '')), h('span', { class: 'big' }, c.score), ' ', h('span', { class: 'ov' }, `(${c.overs}${c.overs_limit ? '/' + c.overs_limit : ''})`)),
    h('div', {}, h('div', { class: 'mute small' }, 'CRR'), h('b', {}, c.crr.toFixed(2))),
    c.target != null ? h('div', {}, h('div', { class: 'mute small' }, `TARGET ${c.target}`), h('b', {}, c.need != null ? `Need ${c.need}` + (c.balls_left != null ? ` off ${c.balls_left}` : '') : ''), c.rrr != null ? h('span', { class: 'mute' }, `  RRR ${c.rrr.toFixed(2)}`) : null) : (c.projected ? h('div', {}, h('div', { class: 'mute small' }, 'PROJECTED'), h('b', {}, c.projected)) : null),
    S.play ? h('div', {}, h('div', { class: 'mute small' }, S.play.label + (S.play.days ? ` of ${S.play.days}` : '')), h('b', {}, `Today ${S.play.today.runs}/${S.play.today.wickets} · ${S.play.today.overs} ov`), S.play.overs_left != null ? h('span', { class: 'mute' }, `  ${S.play.overs_left} left`) : null) : null,
    c.lead_text ? h('div', {}, h('div', { class: 'mute small' }, 'LEAD / TRAIL'), h('b', {}, c.lead_text)) : null,
    c.free_hit ? h('span', { class: 'badge fh' }, 'FREE HIT') : null, c.powerplay ? h('span', { class: 'badge pp' }, c.powerplay) : null,
    inn().overridden.length ? h('span', { class: 'badge ov' }, 'OVERRIDE ACTIVE') : null,
    h('span', { class: 'sp' }), h('div', { class: 'right' }, h('b', {}, c.status_line), S.first_innings && c.innings_no > 1 ? h('div', { class: 'mute small' }, `${S.first_innings.short} ${S.first_innings.score} (${S.first_innings.overs})`) : null)].filter(Boolean));
}
function resumeLabel() {
  const p = S.play; if (!p) return 'Resume play';
  if (p.break === 'stumps') return `Resume — Day ${p.day + 1}`;
  if (p.break === 'lunch' || p.break === 'tea') return `Resume — session ${p.session + 1}`;
  return 'Resume play';
}
function alertBox(kind, ...kids) { return h('div', { class: 'alert ' + kind }, ...kids); }
function renderAlerts() {
  const box = $('#alerts'); box.replaceChildren();
  const c = cur(); const errs = S.integrity.errors;
  if (!c) box.append(alertBox('info', h('b', {}, 'Ready to start. '), 'Check the teams in Setup, then:', h('button', { class: 'btn primary', onclick: () => startInningsModal() }, 'Start first innings')));
  else if (S.status === 'delayed') box.append(alertBox('warn', h('b', {}, 'Paused · ' + S.delay), h('button', { class: 'btn ok', onclick: () => post({ type: 'resume' }) }, resumeLabel())));
  if (c && c.innings_status === 'in_progress') {
    if (c.pending_batter) box.append(alertBox('bad', h('b', {}, 'Choose the incoming batter'), h('button', { class: 'btn primary', onclick: () => batterModal() }, 'Select batter')));
    if (c.pending_bowler) box.append(alertBox('bad', h('b', {}, 'Choose the bowler for this over'), h('button', { class: 'btn primary', onclick: () => bowlerModal() }, 'Select bowler')));
  }
  if (c && c.innings_status === 'completed' && !S.result.final) {
    // A Super Over is a pair of innings. After the first innings of a pair,
    // the result is not tied yet, but the next innings must still be a Super Over.
    const soCount = S.innings.filter(x => x.kind === 'super_over').length;
    const continuingSuperOver = c.kind === 'super_over' && soCount % 2 === 1;
    const so = !!S.result.super_over_needed || continuingSuperOver;
    box.append(alertBox('info', h('b', {}, S.result.super_over_needed ? 'Match tied!' : 'Innings complete.'), ' ' + c.status_line,
      h('button', { class: 'btn primary', onclick: () => startInningsModal(so) }, so ? 'Start Super Over' : `Start innings ${S.innings.length + 1}`),
      h('span', { class: 'mute small' }, 'Scored a ball by mistake / innings ended early? Use Undo or the Events tab.')));
  }
  if (S.result.final) box.append(alertBox('ok info', h('b', {}, 'Result ' + S.result.text), S.result.manual ? h('span', { class: 'badge ov' }, 'manual result') : null));
  if (errs.length) box.append(alertBox('bad', h('b', {}, `Warning ${errs.length} event${errs.length > 1 ? 's are' : ' is'} invalid and being ignored:`), errs[0].message, h('button', { class: 'btn sm', onclick: () => { tab = 'events'; render(); } }, 'Fix in Events tab')));
}
function renderLeft() {
  const L = $('#left'); L.replaceChildren(); const c = cur(); if (!c) return;
  const row = (p, strike) => p ? h('div', { class: 'row', style: { padding: '4px 0' } }, h('b', { style: { fontSize: '1.15rem', minWidth: '160px' } }, p.name + (strike ? ' *' : '')), h('span', { style: { fontSize: '1.3rem', fontWeight: 800 } }, `${p.runs}`), h('span', { class: 'mute' }, `(${p.balls})  4s ${p.fours} · 6s ${p.sixes} · SR ${p.sr.toFixed(0)}`)) : h('div', { class: 'mute', style: { padding: '4px 0' } }, '— vacant —');
  const bw = c.bowler;
  L.append(h('div', { class: 'card' }, h('div', { class: 'row' }, h('h2', { style: { margin: 0 } }, 'At the crease'), h('span', { class: 'sp' }), h('button', { class: 'btn sm', title: 'Swap striker / non-striker', onclick: () => post({ type: 'swap_strike', innings: S.current_innings }) }, '⇄ Swap strike')),
    row(c.striker, true), row(c.non_striker, false),
    c.partnership ? h('div', { class: 'mute small' }, `Partnership ${c.partnership.runs} (${c.partnership.balls} balls)`) : null),
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('h2', { style: { margin: 0 } }, 'Bowler'), h('span', { class: 'sp' }), h('button', { class: 'btn sm', onclick: () => bowlerModal(true) }, 'Change')),
      bw ? h('div', { class: 'row', style: { padding: '4px 0' } }, h('b', { style: { fontSize: '1.15rem', minWidth: '160px' } }, bw.name), h('span', { style: { fontSize: '1.3rem', fontWeight: 800 } }, `${bw.overs}-${bw.maidens}-${bw.runs}-${bw.wickets}`), h('span', { class: 'mute' }, `Econ ${bw.econ.toFixed(2)}`)) : h('div', { class: 'mute' }, '— none selected —')),
    h('div', { class: 'card' }, h('h2', {}, `This over (${c.this_over.n})${c.this_over.complete ? ' · complete' : ''}${c.this_over.maiden ? ' · MAIDEN' : ''}`),
      h('div', { class: 'chips' }, c.this_over.balls.length ? c.this_over.balls.map(b => h('span', { class: 'chip ' + b.kind }, b.label)) : h('span', { class: 'mute' }, 'no balls yet')),
      h('div', { class: 'mute small', style: { marginTop: '6px' } }, `${c.this_over.runs} runs this over`)));
}
function renderPad() {
  const P = $('#pad'); P.replaceChildren(); const c = cur();
  const can = live_ok() && !c.pending_batter && !c.pending_bowler;
  const runBtn = (n) => h('button', { class: 'btn ' + (n === 4 ? 'four' : n === 6 ? 'six' : ''), disabled: !can, onclick: () => fire(n) }, String(n));
  const modBtn = (k, label, key) => h('button', { class: 'btn' + (mods[k] ? ' on' : ''), disabled: !can, onclick: () => toggleMod(k) }, label, h('span', { class: 'kbd' }, key));
  const hint = Object.entries(mods).filter(([, v]) => v).map(([k]) => ({ wide: 'WIDE', noball: 'NO-BALL', bye: 'BYES', legbye: 'LEG-BYES' }[k]));
  P.append(h('div', { class: 'card' },
    h('div', { class: 'row' }, h('h2', { style: { margin: 0 } }, 'Score a ball'), h('span', { class: 'sp' }), hint.length ? h('span', { class: 'badge ov' }, hint.join(' + ') + ' — tap runs (0 to confirm)') : h('span', { class: 'mute small' }, 'keys: 0-6 · W wicket · D wide · N no-ball · B bye · L leg-bye · U undo')),
    h('div', { class: 'keys', style: { marginTop: '8px' } }, [0, 1, 2, 3, 4, 5, 6].map(runBtn)),
    h('div', { class: 'mods' }, modBtn('wide', 'Wide', 'D'), modBtn('noball', 'No ball', 'N'), modBtn('bye', 'Bye', 'B'), modBtn('legbye', 'Leg bye', 'L'),
      h('button', { class: 'btn wkt', disabled: !can, onclick: () => ballModal({}) }, 'WICKET', h('span', { class: 'kbd' }, 'W'))),
    h('div', { class: 'acts' },
      h('button', { class: 'btn', onclick: undo }, '↶ Undo last', h('span', { class: 'kbd' }, 'U')), h('button', { class: 'btn', disabled: !canRedo, onclick: redo }, '↷ Redo'),
      h('button', { class: 'btn', disabled: !can, onclick: () => ballModal({ more: true }) }, 'More… (overthrows, custom)'))));
}
function toggleMod(k) {
  const was = mods[k];
  if (k === 'wide') { mods.wide = !was; if (mods.wide) { mods.noball = false; mods.bye = false; mods.legbye = false; } }
  else if (k === 'noball') { mods.noball = !was; if (mods.noball) mods.wide = false; }
  else if (k === 'bye') { mods.bye = !was; if (mods.bye) { mods.legbye = false; mods.wide = false; } }
  else if (k === 'legbye') { mods.legbye = !was; if (mods.legbye) { mods.bye = false; mods.wide = false; } }
  renderPad();
}
function resetMods() { mods.wide = mods.noball = mods.bye = mods.legbye = false; }
async function fire(n) {
  if (!live_ok()) return;
  const ev = { type: 'ball', innings: S.current_innings, delivery: mods.wide ? 'wide' : mods.noball ? 'noball' : 'legal' };
  if (mods.wide) { ev.wide_runs = n; ev.boundary = n >= 4; }
  else if (mods.bye) { ev.byes = n; ev.boundary = n === 4; }
  else if (mods.legbye) { ev.legbyes = n; ev.boundary = n === 4; }
  else { ev.bat_runs = n; ev.boundary = n === 4 || n === 6; }
  resetMods(); renderPad();
  await post(ev);
}
async function undo() { try { const r = await api('POST', `/api/matches/${id}/undo`, {}); version = r.version; canRedo = true; evCache = null; toast('Undone: ' + describeEvent(r.undone, S), 'ok', 2500); await refresh(); } catch (e) { toast(e.message, 'bad'); } }
async function redo() { try { const r = await api('POST', `/api/matches/${id}/redo`, {}); version = r.version; evCache = null; await refresh(); } catch (e) { toast(e.message, 'bad'); } }

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || document.body.classList.contains('has-modal')) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !document.body.classList.contains('has-modal') && !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) { e.preventDefault(); undo(); }
    return;
  }
  if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || !S) return;
  const k = e.key.toLowerCase();
  if (/^[0-6]$/.test(k)) { e.preventDefault(); fire(+k); }
  else if (k === 'w') ballModal({}); else if (k === 'd') toggleMod('wide'); else if (k === 'n') toggleMod('noball');
  else if (k === 'b') toggleMod('bye'); else if (k === 'l') toggleMod('legbye'); else if (k === 'u') undo();
});

// ------------------------------------------------------------------ prompts
function autoPrompts() {
  const c = cur(); if (!c || c.innings_status !== 'in_progress' || document.body.classList.contains('has-modal')) return;
  const key = (t) => `${version}:${t}`;
  if (c.pending_batter && !dismissedPrompts.has('b' + c.wickets + ':' + S.current_innings)) { dismissedPrompts.add('b' + c.wickets + ':' + S.current_innings); batterModal(); }
  else if (c.pending_bowler && !dismissedPrompts.has('o' + c.balls + ':' + S.current_innings)) { dismissedPrompts.add('o' + c.balls + ':' + S.current_innings); bowlerModal(); }
}
function pickModal(title, items, onPick, extra, order) {
  let m;
  const btn = (it) => h('button', { class: 'btn' + (it.warn ? ' ghost' : ''), title: it.note || '', onclick: async () => { m.close(); await onPick(it.value); } },
    h('div', {}, it.label), it.note ? h('div', { class: 'mute small' }, it.note) : null);
  const groups = order ? groupByRole(items, (x) => x.role, order) : [{ title: null, items }];
  m = modal(title, h('div', {}, extra || null, groups.map(g => h('div', {}, g.title ? h('h4', { style: { margin: '10px 0 4px' } }, g.title) : null, h('div', { class: 'pickgrid' }, g.items.map(btn))))), { buttons: [{ label: 'Cancel' }] });
  return m;
}
function batterModal(opts = {}) {
  const i = inn(); if (!i) return;
  const items = i.batters.filter(b => (b.status === 'yet_to_bat' || b.status === 'retired_hurt') && !b.at_crease).map(b => ({ value: b.id, label: b.name + (b.tag || ''), note: b.status === 'retired_hurt' ? `returning · ${b.runs}(${b.balls})` : '', role: roleOf(S, b.id) }));
  if (!items.length) { toast('No batters left to come in. If the innings is over, end it (Match tab).', 'warn'); return; }
  pickModal('Incoming batter', items, (pid) => post({ type: 'new_batter', innings: S.current_innings, player: pid }), null, ['batter', 'allrounder', 'bowler', '']);
}
function bowlerModal(change = false) {
  const i = inn(); if (!i) return;
  const bowlTid = i.bowling;
  const lastOver = (i.overs_detail.length ? (i.overs_detail[i.overs_detail.length - 1].complete ? i.overs_detail[i.overs_detail.length - 1] : (i.overs_detail.length > 1 ? i.overs_detail[i.overs_detail.length - 2] : null)) : null);
  const items = playersOf(S, bowlTid).map(p => {
    const b = i.bowlers.find(x => x.id === p.id);
    const notes = [];
    if (b) notes.push(`${b.overs} ov · ${b.wickets}/${b.runs}`);
    if (lastOver && lastOver.bowlers.includes(p.id)) notes.push('bowled last over');
    return { value: p.id, label: p.name + tagOf(p), note: notes.join(' · '), warn: !!(lastOver && lastOver.bowlers.includes(p.id)), role: p.role || '' };
  });
  const midOver = i.legal_balls % S.format.balls_per_over !== 0 && i.bowler;
  const reasonSel = midOver ? select([{ value: 'injury', label: 'Injury' }, { value: 'illness', label: 'Illness' }, { value: 'suspension', label: 'Suspension' }], 'injury') : null;
  pickModal(change ? 'Change bowler' : 'Bowler for the next over', items,
    (pid) => post({ type: 'set_bowler', innings: S.current_innings, bowler: pid, ...(midOver ? { reason: reasonSel.value } : {}) }),
    midOver ? h('div', { class: 'alert warn' }, 'Mid-over change — only allowed for ', reasonSel) : null, ['bowler', 'allrounder', 'batter', '']);
}

// ------------------------------------------------------------------ start innings
function startInningsModal(superOver = false) {
  const idx = S.innings.length;
  const last = S.innings[idx - 1];
  const toss = S.toss || {};
  let batting = 'A';
  if (superOver) { const nSO = S.innings.filter(x => x.kind === 'super_over').length; batting = nSO % 2 === 0 ? last.batting : last.bowling; }
  else if (idx === 0) { batting = toss.winner ? (toss.decision === 'bat' ? toss.winner : (toss.winner === 'A' ? 'B' : 'A')) : 'A'; }
  else batting = last.bowling;
  const tSel = select([{ value: 'A', label: S.teams.A.name }, { value: 'B', label: S.teams.B.name }], batting);
  const mk = (tid) => playersOf(S, tid).map(p => ({ value: p.id, label: p.name + tagOf(p), role: p.role || '' }));
  const s1 = h('select'), s2 = h('select'), bw = h('select');
  const fillSel = (el, items, order) => { const n = sectionedSelect(items, ROLE_GROUPS(order).filter(() => items.some(i => i.role))); el.replaceChildren(...n.childNodes); };
  const fill = () => {
    const bt = tSel.value, bo = bt === 'A' ? 'B' : 'A';
    fillSel(s1, mk(bt), ['batter', 'allrounder', 'bowler', '']); fillSel(s2, mk(bt), ['batter', 'allrounder', 'bowler', '']); fillSel(bw, mk(bo), ['bowler', 'allrounder', 'batter', '']);
    // sensible defaults: first two batters open, first bowler listed bowls
    s1.selectedIndex = 0; s2.selectedIndex = Math.min(1, s2.options.length - 1); bw.selectedIndex = 0;
  };
  tSel.onchange = fill; fill();
  let foBox = null;
  if (!superOver && idx === 2 && S.play) {
    const fi = S.innings[0], se = S.innings[1]; const lead = fi.runs - se.runs, need = S.play.follow_on_margin;
    const mkFo = () => { tSel.value = se.batting; fill(); };
    foBox = h('div', { class: 'alert ' + (lead >= need ? 'info' : 'warn') },
      h('b', {}, `${fi.batting_name} lead by ${lead}. `), lead >= need ? `A follow-on is allowed (lead of ${need}+). ` : `A follow-on needs a lead of ${need} (Law 14.1, ${S.play.days ? S.play.days + '-day' : 'days not set'} match). `,
      lead > 0 ? h('button', { class: 'btn sm', onclick: () => mkFo() }, `Enforce follow-on (${se.batting_name} bat again)`) : null);
  }
  const ovs = h('input', { type: 'number', min: 1, value: superOver ? 1 : (S.format.overs || ''), style: { width: '80px' } });
  modal(superOver ? 'Start Super Over' : `Start innings ${idx + 1}`, h('div', {}, !superOver && idx === 0 && !toss.winner ? h('div', { class: 'alert warn' }, 'No toss recorded — pick the batting team manually (or set the toss in Setup).') : null,
    foBox, h('label', {}, 'Batting team'), tSel, h('label', {}, 'Striker'), s1, h('label', {}, 'Non-striker'), s2, h('label', {}, 'Opening bowler'), bw,
    h('label', {}, 'Overs in this innings'), ovs), { buttons: [{ label: 'Cancel' }, { label: 'Start', kind: 'primary', onclick: async () => {
      if (s1.value === s2.value) { toast('Striker and non-striker must be different', 'bad'); return false; }
      const r = await post({ type: 'innings_start', innings: idx, kind: superOver ? 'super_over' : 'regular', batting: tSel.value, striker: s1.value, non_striker: s2.value, bowler: bw.value, overs_limit: num(ovs.value, null) || undefined });
      if (!r) return false; } }] });
}

// ------------------------------------------------------------------ ball / wicket form (new, more, edit, insert)
function ballModal({ more = false, edit = null, rec = null, insertAfter = null } = {}) {
  const c = cur(); const i = inn();
  const ev0 = edit || {};
  const striker = rec ? rec.striker : c.striker?.id, non = rec ? rec.non_striker : c.non_striker?.id;
  const bowlTid = i.bowling, batTid = i.batting;
  const free = rec ? rec.free_hit : c.free_hit;
  const wk0 = ev0.wicket || null;
  const st = { delivery: ev0.delivery || (mods.wide ? 'wide' : mods.noball ? 'noball' : 'legal'), kind: wk0 ? wk0.kind : null };
  const wantWicket = !more && !edit ? true : !!wk0;
  const nameOf = (pid) => pname(S, pid);

  const delSeg = h('div', { class: 'seg' });
  const kindSeg = h('div', { class: 'seg', style: { flexWrap: 'wrap' } });
  const bat = h('input', { type: 'number', min: 0, value: ev0.bat_runs ?? 0 });
  const byes = h('input', { type: 'number', min: 0, value: ev0.byes ?? 0 });
  const lbs = h('input', { type: 'number', min: 0, value: ev0.legbyes ?? 0 });
  const wide = h('input', { type: 'number', min: 0, value: ev0.wide_runs ?? 0 });
  const bnd = h('input', { type: 'checkbox', checked: !!ev0.boundary });
  const ran = h('input', { type: 'number', min: 0, placeholder: 'auto', value: ev0.ran ?? '' });
  const wkOn = h('input', { type: 'checkbox', checked: wantWicket });
  const outSel = select([{ value: striker, label: `${nameOf(striker)} (striker)` }, { value: non, label: `${nameOf(non)} (non-striker)` }], wk0?.out || striker);
  const fPl = playersOf(S, bowlTid);
  const keeper = fPl.find(p => p.wk);
  const fl = [{ value: '', label: '— none —', _top: true }, ...fPl.map(p => ({ value: p.id, label: p.name + tagOf(p), wk: p.wk, role: p.role || '' })), { value: '__sub', label: 'Substitute fielder (type name)…', _bot: true }];
  const fsel = (v) => sectionedSelect(fl, [{ title: null, test: (it) => it._top }, { title: 'Wicketkeeper †', test: (it) => it.wk }, ...(fl.some(i => i.role) ? ROLE_GROUPS(['allrounder', 'bowler', 'batter', '']) : [{ title: 'Fielders', test: (it) => !it._bot }]), { title: null, test: (it) => it._bot }], v);
  const f1 = fsel(wk0?.fielder || ''); const f2 = fsel(wk0?.fielder2 || '');
  const cb = keeper ? h('button', { type: 'button', class: 'btn sm', title: 'Caught behind / stumped: set the fielder to the wicketkeeper', onclick: () => { f1.value = keeper.id; f1.dispatchEvent(new Event('change')); } }, 'WK † ' + keeper.name) : null;
  const f1t = h('input', { placeholder: 'sub fielder name', hidden: true }), f2t = h('input', { placeholder: 'sub fielder name', hidden: true });
  f1.onchange = () => { f1t.hidden = f1.value !== '__sub'; }; f2.onchange = () => { f2t.hidden = f2.value !== '__sub'; };
  const willEnd = i.wickets + 1 >= i.wickets_limit;
  const nbItems = i.batters.filter(b => (b.status === 'yet_to_bat' || b.status === 'retired_hurt') && !b.at_crease).map(b => ({ value: b.id, label: b.name + (b.status === 'retired_hurt' ? ' (returning)' : '') }));
  const nbSel = select([{ value: '', label: '— choose later —' }, ...nbItems], wk0?.new_batter || (nbItems[0] ? nbItems[0].value : ''));
  const faceNew = h('input', { type: 'radio', name: 'face', checked: wk0 ? wk0.new_batter_on_strike !== false : true });
  const faceOld = h('input', { type: 'radio', name: 'face', checked: wk0 ? wk0.new_batter_on_strike === false : false });
  const crossed = h('input', { type: 'checkbox' });
  const note = h('input', { placeholder: 'note (optional)', value: ev0.note || '', style: { width: '100%' } });
  const msg = h('div', { class: 'alert warn', hidden: true });
  const wkBox = h('div', { class: 'card', style: { marginTop: '8px' } });

  const allowedKinds = () => {
    let a = ALLOWED_OFF[st.delivery].slice();
    if (free) a = a.filter(k => FREE_HIT_ALLOWED.includes(k));
    return a;
  };
  const refreshDefaults = () => {
    if (!st.kind) return;
    if (st.kind === 'stumped' && keeper && !f1.value) f1.value = keeper.id;     // a stumping is always by the keeper
    if (st.kind === 'run_out') faceNew.checked = outSel.value !== striker ? true : false, faceOld.checked = !faceNew.checked;
    else if (st.kind === 'caught') { faceNew.checked = !crossed.checked; faceOld.checked = crossed.checked; }
    else { faceNew.checked = true; faceOld.checked = false; }
  };
  const draw = () => {
    delSeg.replaceChildren(...[['legal', 'Legal'], ['wide', 'Wide'], ['noball', 'No-ball']].map(([k, l]) => h('button', { type: 'button', class: st.delivery === k ? 'on' : '', onclick: () => { st.delivery = k; if (st.kind && !allowedKinds().includes(st.kind)) st.kind = null; draw(); } }, l)));
    const allowed = allowedKinds();
    kindSeg.replaceChildren(...Object.entries(DISMISSALS).map(([k, l]) => h('button', { type: 'button', class: st.kind === k ? 'on' : '', disabled: !allowed.includes(k), title: allowed.includes(k) ? '' : 'Not possible on this delivery (Laws 21/22 / free hit)', onclick: () => { st.kind = k; refreshDefaults(); draw(); } }, l)));
    const noRuns = st.kind && ['bowled', 'caught', 'lbw', 'stumped', 'hit_wicket'].includes(st.kind);
    for (const el of [bat, byes, lbs]) el.disabled = !!(wkOn.checked && noRuns) || st.delivery === 'wide';
    wide.disabled = st.delivery !== 'wide' || !!(wkOn.checked && noRuns);
    if (st.kind && STRIKER_ONLY.includes(st.kind)) outSel.value = striker;
    outSel.disabled = !!(st.kind && STRIKER_ONLY.includes(st.kind));
    wkBox.hidden = !wkOn.checked;
    const m = [];
    if (free) m.push('FREE HIT — only run out / hit the ball twice / obstructing the field are possible.');
    if (st.delivery === 'noball') m.push('No-ball: a batter can only be run out, hit the ball twice or obstruct the field (Law 21).');
    if (st.delivery === 'wide') m.push('Wide: a batter can only be stumped, run out, hit wicket or obstruct the field (Law 22). Runs run are wides.');
    if (wkOn.checked && noRuns) m.push('Ball is dead on this dismissal — no runs are scored (only the wide/no-ball penalty).');
    msg.hidden = !m.length; msg.replaceChildren(...m.map(t => h('div', {}, t)));
  };
  [wkOn, crossed, outSel].forEach(e => e.addEventListener('change', () => { refreshDefaults(); draw(); }));
  bat.addEventListener('input', () => { if (+bat.value === 4 || +bat.value === 6) bnd.checked = true; });
  wkBox.append(h('label', {}, 'How out'), kindSeg, h('label', {}, 'Who is out'), outSel,
    h('div', { class: 'row' }, h('div', {}, h('label', {}, 'Fielder / keeper'), h('div', { class: 'row', style: { margin: 0 } }, f1, cb), f1t), h('div', {}, h('label', {}, 'Second fielder (run out)'), f2, f2t)),
    willEnd ? h('div', { class: 'alert info', style: { marginTop: '8px' } }, 'This is the last wicket — the innings will end.') : h('div', {}, h('label', {}, 'Incoming batter'), nbSel,
      h('label', {}, 'Who faces the next ball?'), h('div', { class: 'row' }, h('label', { class: 'inline' }, faceNew, 'New batter'), h('label', { class: 'inline' }, faceOld, 'Surviving batter'),
        h('label', { class: 'inline' }, crossed, 'batters had crossed (caught)')), h('div', { class: 'mute small' }, 'Check with the umpire: for a run out, whoever is at the striker’s end faces. If it is the last ball of the over the ends change automatically.')));
  const body = h('div', {}, msg, h('label', {}, 'Delivery'), delSeg,
    h('div', { class: 'row', style: { marginTop: '6px' } }, h('div', {}, h('label', {}, 'Runs off the bat'), bat), h('div', {}, h('label', {}, 'Byes'), byes), h('div', {}, h('label', {}, 'Leg byes'), lbs), h('div', {}, h('label', {}, 'Extra wide runs'), wide),
      h('label', { class: 'inline' }, bnd, 'boundary hit (4/6)')),
    h('div', { class: 'row' }, h('label', { class: 'inline' }, 'Runs physically run (changes strike): ', ran), h('span', { class: 'mute small' }, 'leave blank = auto (boundary → none). Use for overthrows.')),
    h('div', { style: { marginTop: '10px' } }, h('label', { class: 'inline' }, wkOn, h('b', {}, ' Wicket falls on this ball'))), wkBox, h('label', {}, 'Note'), note);
  draw();
  const title = edit ? 'Edit ball' : insertAfter ? 'Insert ball' : (more ? 'Custom ball' : 'Wicket');
  modal(title, body, { wide: true, buttons: [{ label: 'Cancel' }, { label: edit ? 'Save changes' : insertAfter ? 'Insert' : 'Record', kind: 'primary', onclick: async () => {
    const e = { type: 'ball', innings: edit ? edit.innings : (insertAfter ? insertAfter.innings : S.current_innings), delivery: st.delivery };
    const noRuns = wkOn.checked && st.kind && ['bowled', 'caught', 'lbw', 'stumped', 'hit_wicket'].includes(st.kind);
    if (!noRuns && st.delivery !== 'wide') { e.bat_runs = num(bat.value); e.byes = num(byes.value); e.legbyes = num(lbs.value); }
    if (st.delivery === 'wide' && !noRuns) e.wide_runs = num(wide.value);
    e.boundary = bnd.checked && !noRuns;
    if (ran.value !== '') e.ran = num(ran.value); else if (edit) e.ran = null;
    if (note.value) e.note = note.value;
    if (wkOn.checked) {
      if (!st.kind) { toast('Choose how the batter was out', 'bad'); return false; }
      const fv = (sel, t) => sel.value === '__sub' ? (t.value.trim() ? 'sub: ' + t.value.trim() : '') : sel.value;
      e.wicket = { kind: st.kind, out: outSel.value, fielder: fv(f1, f1t) || undefined, fielder2: fv(f2, f2t) || undefined };
      if (!willEnd) { if (nbSel.value) e.wicket.new_batter = nbSel.value; e.wicket.new_batter_on_strike = faceNew.checked; }
      if (crossed.checked && ran.value === '') e.ran = 1;
    } else if (edit) e.wicket = null;
    if (edit) {
      try { const r = await api('PUT', `/api/matches/${id}/events/${edit.id}`, { patch: e, reason: 'edited in scorer console' }); version = r.version; evCache = null; toast(r.errors.length ? `Saved — ${r.errors.length} later event(s) now invalid, check Events tab` : 'Saved', r.errors.length ? 'warn' : 'ok'); await refresh(); }
      catch (err) { toast(err.message, 'bad'); return false; }
      return;
    }
    if (insertAfter) {
      try { const r = await api('POST', `/api/matches/${id}/insert`, { event: e, after_id: insertAfter.id, reason: 'inserted missed ball' }); version = r.version; evCache = null; toast(r.errors.length ? `Inserted — ${r.errors.length} later event(s) now invalid` : 'Inserted', r.errors.length ? 'warn' : 'ok'); await refresh(); }
      catch (err) { toast(err.message, 'bad'); return false; }
      return;
    }
    const r = await post(e); if (!r) return false; resetMods(); renderPad();
  } }] });
}

// ------------------------------------------------------------------ tabs
function renderTabs() {
  const tabs = [['card', 'Scorecard'], ['events', 'Events & corrections'], ['override', 'Manual override'], ['match', 'Match actions']];
  const T = $('#tabs'); T.replaceChildren(...tabs.map(([k, l]) => h('button', { class: 'tab' + (tab === k ? ' on' : ''), onclick: () => { tab = k; render(); } }, l)));
  const B = $('#tabbody'); B.replaceChildren();
  if (tab === 'card') { const inns = S.innings.slice().reverse(); B.append(...(inns.length ? inns.map(i => inningsCard(S, i)) : [h('div', { class: 'mute' }, 'Nothing to show yet.')]).map(x => h('div', { style: { marginBottom: '12px' } }, x))); }
  else if (tab === 'events') renderEvents(B);
  else if (tab === 'override') renderOverride(B);
  else renderMatch(B);
}

async function renderEvents(B) {
  B.append(h('div', { class: 'mute' }, 'Loading…'));
  const [evd, full] = await Promise.all([api('GET', `/api/matches/${id}/events`), api('GET', `/api/matches/${id}/state?view=full`)]);
  if (tab !== 'events') return;
  const recs = {}; full.state.innings.forEach(i => i.balls.forEach(b => { recs[b.id] = b; }));
  B.replaceChildren(h('div', { class: 'alert info' }, 'Every action is an event. You can edit, delete or insert any of them; everything after is recalculated instantly and the audit log records who changed what. Events flagged red could not be applied (they are ignored until fixed).'));
  const list = h('div', { class: 'card', style: { padding: 0 } });
  evd.events.slice().reverse().forEach((ev, ri) => {
    const stt = evd.status[ev.id] || { ok: true };
    const rec = recs[ev.id];
    list.append(h('div', { class: 'ev' + (stt.ok ? '' : ' invalid') },
      h('span', { class: 'mute small', style: { width: '34px' } }, '#' + (evd.events.length - ri)),
      h('div', { class: 'd' }, h('div', {}, describeEvent(ev, full.state, rec)), h('div', { class: 'meta' }, new Date(ev.ts).toLocaleTimeString(), ev.edited ? ' · edited' : '', ev.inserted ? ' · inserted' : '', ev.force ? ' · forced rule: ' + ev.force.join(',') : '', !stt.ok ? ' · Warning ' + stt.error.message : '')),
      ev.type === 'ball' && rec ? h('button', { class: 'btn sm', onclick: () => ballModal({ edit: ev, rec }) }, 'Edit') : h('button', { class: 'btn sm', onclick: () => jsonEditModal(ev) }, 'Edit'),
      ev.type === 'ball' ? h('button', { class: 'btn sm', title: 'Insert a missed ball after this one', onclick: () => ballModal({ insertAfter: ev, more: true, rec }) }, '+ after') : null,
      h('button', { class: 'btn sm danger', onclick: async () => { if (!(await confirmBox('Delete this event? Everything after it is recalculated.', 'Delete'))) return; const r = await api('DELETE', `/api/matches/${id}/events/${ev.id}?reason=deleted%20in%20console`); version = r.version; await refresh(); } }, 'Missed')));
  });
  B.append(list);
}
function jsonEditModal(ev) {
  const ta = h('textarea', {}, JSON.stringify(ev, null, 2));
  modal('Edit event (advanced)', h('div', {}, h('p', { class: 'mute small' }, 'Edit the raw event. id/ts are kept.'), ta), { wide: true, buttons: [{ label: 'Cancel' }, { label: 'Save', kind: 'primary', onclick: async () => {
    try { const patch = JSON.parse(ta.value); const r = await api('PUT', `/api/matches/${id}/events/${ev.id}`, { patch, reason: 'raw edit' }); version = r.version; evCache = null; await refresh(); }
    catch (e) { toast(e.message, 'bad'); return false; } } }] });
}

// ---- manual override tab
function renderOverride(B) {
  const idxSel = select(S.innings.map((i) => ({ value: i.index, label: `Innings ${i.index + 1} — ${i.batting_name}` })), S.current_innings ?? 0);
  if (!S.innings.length) { B.append(h('div', { class: 'mute' }, 'Start an innings first.')); return; }
  const box = h('div');
  const build = () => {
    const i = S.innings[+idxSel.value]; box.replaceChildren();
    const changed = {}; const inputs = [];
    const numField = (label, key, value) => { const el = h('input', { type: 'number', value }); el.dataset.key = key; el.dataset.orig = value; el.oninput = () => el.classList.toggle('chg', el.value !== el.dataset.orig); inputs.push(el); return h('div', {}, h('label', {}, label), el); };
    const selField = (label, key, items, value) => { const el = select(items, value || ''); el.dataset.key = key; el.dataset.orig = value || ''; el.onchange = () => el.classList.toggle('chg', el.value !== el.dataset.orig); inputs.push(el); return h('div', {}, h('label', {}, label), el); };
    const bt = playersOf(S, i.batting, { xiOnly: false }).map(p => ({ value: p.id, label: p.name })); const bo = playersOf(S, i.bowling, { xiOnly: false }).map(p => ({ value: p.id, label: p.name }));
    box.append(
      h('div', { class: 'alert warn' }, h('b', {}, 'Manual override. '), 'Values you change are pinned at this point in the match; later balls build on top of them. Use it when the scorer or software got something wrong and it is quicker to set the right value than to replay events. Everything is logged and can be removed again below.'),
      h('div', { class: 'card ovr' }, h('h3', {}, 'Team / innings'), h('div', { class: 'row' }, numField('Runs', 'runs', i.runs), numField('Wickets', 'wickets', i.wickets), numField('Legal balls bowled', 'balls', i.legal_balls),
        numField('Overs limit', 'overs_limit', i.overs_limit ?? ''), numField('Target (runs to win)', 'target', i.target ?? ''), numField('Wickets to be all out', 'wickets_limit', i.wickets_limit)),
        h('div', { class: 'row' }, ['wide', 'noball', 'bye', 'legbye', 'penalty'].map(k => numField('Extras: ' + k, 'extras.' + k, i.extras[k]))),
        h('div', { class: 'row' }, selField('Striker', 'striker', [{ value: '', label: '—' }, ...bt], i.striker), selField('Non-striker', 'non_striker', [{ value: '', label: '—' }, ...bt], i.non_striker), selField('Bowler', 'bowler', [{ value: '', label: '—' }, ...bo], i.bowler))),
      h('div', { class: 'card ovr', style: { marginTop: '10px', overflowX: 'auto' } }, h('h3', {}, 'Batters'), h('table', {}, h('thead', {}, h('tr', {}, ['Batter', 'Runs', 'Balls', '4s', '6s'].map(x => h('th', {}, x)))),
        h('tbody', {}, i.batters.filter(b => b.status !== 'yet_to_bat').map(b => h('tr', {}, h('td', {}, b.name), ...['runs', 'balls', 'fours', 'sixes'].map(f => { const el = h('input', { type: 'number', value: b[f] }); el.dataset.key = `batter.${b.id}.${f}`; el.dataset.orig = b[f]; el.oninput = () => el.classList.toggle('chg', el.value !== el.dataset.orig); inputs.push(el); return h('td', {}, el); })))))),
      h('div', { class: 'card ovr', style: { marginTop: '10px', overflowX: 'auto' } }, h('h3', {}, 'Bowlers (balls = legal balls bowled)'), h('table', {}, h('thead', {}, h('tr', {}, ['Bowler', 'Balls', 'Runs', 'Wkts', 'Maidens', 'Wides', 'No-balls'].map(x => h('th', {}, x)))),
        h('tbody', {}, i.bowlers.map(b => h('tr', {}, h('td', {}, b.name), ...['balls', 'runs', 'wickets', 'maidens', 'wides', 'noballs'].map(f => { const el = h('input', { type: 'number', value: b[f] }); el.dataset.key = `bowler.${b.id}.${f}`; el.dataset.orig = b[f]; el.oninput = () => el.classList.toggle('chg', el.value !== el.dataset.orig); inputs.push(el); return h('td', {}, el); })))))),
      h('div', { class: 'row', style: { marginTop: '10px' } }, h('input', { id: 'why', placeholder: 'Reason (required, e.g. “scorer missed 2 overs, from paper book”)', style: { flex: 1, minWidth: '260px' } }),
        h('button', { class: 'btn primary', onclick: async () => {
          const set = {}; inputs.forEach(el => { if (el.value !== el.dataset.orig) { let v = el.value; if (el.type === 'number') v = v === '' ? null : +v; set[el.dataset.key] = v; } });
          if (!Object.keys(set).length) { toast('Nothing changed', 'warn'); return; }
          const why = $('#why').value.trim(); if (!why) { toast('Please give a reason', 'bad'); return; }
          const r = await post({ type: 'override', innings: i.index, set, reason: why }); if (r) toast('Override applied', 'ok');
        } }, 'Apply override')),
      overrideList());
  };
  idxSel.onchange = build; B.append(h('div', { class: 'row' }, h('b', {}, 'Innings:'), idxSel), box); build();
}
function overrideList() {
  const ovs = S.integrity.overrides; const info = S.integrity.info;
  return h('div', { class: 'card', style: { marginTop: '12px' } }, h('h3', {}, 'Active overrides'),
    ovs.length ? ovs.map(o => h('div', { class: 'ev' }, h('div', { class: 'd' }, `Innings ${o.innings + 1}: ` + Object.entries(o.set).map(([k, v]) => `${k} = ${v}`).join(', '), h('div', { class: 'meta' }, o.reason || '')),
      h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox('Remove this override? The scoreboard returns to what the events say.', 'Remove')) { const r = await api('DELETE', `/api/matches/${id}/events/${o.id}?reason=override%20removed`); version = r.version; await refresh(); } } }, 'Remove'))) : h('div', { class: 'mute' }, 'None.'),
    info.length ? h('div', { class: 'mute small', style: { marginTop: '8px' } }, 'Consistency notes: ' + info.map(x => x.message).join(' · ')) : null);
}

// ---- match actions
function renderMatch(B) {
  const c = cur(); const i = inn();
  const act = (label, fn, kind = '') => h('button', { class: 'btn ' + kind, onclick: fn }, label);
  B.append(h('div', { class: 'togg' },
    act('Retire batter…', retireModal), act('Penalty runs (5)…', penaltyModal), act('Substitution…', subModal), act('Revise overs / target (DLS)…', reviseModal),
    act('End innings / declare…', endModal), act(S.play ? 'Break / stumps / rain…' : 'Rain / delay…', delayModal), ...(S.play ? [act('Day & session…', daySessionModal), act('New ball taken', newBallAction)] : []), act('Set crease manually…', creaseModal), act('Set result manually…', resultModal),
    act('Clear manual result', () => post({ type: 'clear_result' })), act('Backups / restore…', backupsModal), act('Raw event log (JSON)…', rawModal), act('Edit teams & setup', () => { location.href = `/setup/${id}`; }),
    h('a', { class: 'btn', href: `/api/matches/${id}/export` }, '⬇ Download match file'), act('Audit log…', auditModal)));
}
function retireModal() {
  const c = cur(); if (!c || !c.striker) return;
  const who = select([{ value: c.striker.id, label: c.striker.name + ' (striker)' }, ...(c.non_striker ? [{ value: c.non_striker.id, label: c.non_striker.name }] : [])], c.striker.id);
  const kind = select([{ value: 'hurt', label: 'Retired hurt/ill (NOT out, may return)' }, { value: 'out', label: 'Retired out (counts as a wicket, Law 25)' }], 'hurt');
  const i = inn(); const rep = select([{ value: '', label: '— choose later —' }, ...i.batters.filter(b => b.status === 'yet_to_bat' || b.status === 'retired_hurt').filter(b => !b.at_crease).map(b => ({ value: b.id, label: b.name }))], '');
  modal('Retire batter', h('div', {}, h('label', {}, 'Batter'), who, h('label', {}, 'Type'), kind, h('label', {}, 'Replacement'), rep), { buttons: [{ label: 'Cancel' }, { label: 'Record', kind: 'primary', onclick: async () => { const r = await post({ type: 'retire', innings: S.current_innings, player: who.value, kind: kind.value, replacement: rep.value || undefined }); if (!r) return false; } }] });
}
function penaltyModal() {
  const team = select([{ value: 'A', label: S.teams.A.name }, { value: 'B', label: S.teams.B.name }], cur() ? cur().batting.id : 'A'); const runs = h('input', { type: 'number', value: 5, min: 1, style: { width: '70px' } });
  modal('Penalty runs', h('div', {}, h('p', { class: 'mute small' }, 'Penalty runs go to the team they are AWARDED to. If that team has already batted they are added to that innings; if not, to its next innings. They are not charged to the bowler.'), h('label', {}, 'Awarded to'), team, h('label', {}, 'Runs'), runs), { buttons: [{ label: 'Cancel' }, { label: 'Record', kind: 'primary', onclick: async () => { const r = await post({ type: 'penalty_runs', awarded_to: team.value, runs: num(runs.value, 5) }); if (!r) return false; } }] });
}
function subModal() {
  const tid = select([{ value: 'A', label: S.teams.A.name }, { value: 'B', label: S.teams.B.name }], 'A');
  const out = h('select'), inn_ = h('select');
  const fill = () => { const t = S.teams[tid.value].players; out.replaceChildren(...t.filter(p => p.xi).map(p => h('option', { value: p.id }, p.name))); inn_.replaceChildren(...t.filter(p => !p.xi && !p.subbed_out).map(p => h('option', { value: p.id }, p.name))); };
  tid.onchange = fill; fill();
  modal('Substitution (impact / concussion / other)', h('div', {}, h('p', { class: 'mute small' }, 'The player coming off cannot take further part. Add bench players in Setup first. The player must not be at the crease or bowling.'), h('label', {}, 'Team'), tid, h('label', {}, 'Player leaving'), out, h('label', {}, 'Player coming in'), inn_), { buttons: [{ label: 'Cancel' }, { label: 'Substitute', kind: 'primary', onclick: async () => { const r = await post({ type: 'substitution', team: tid.value, out: out.value, in: inn_.value }); if (!r) return false; } }] });
}
function reviseModal() {
  const idx = S.innings.length && S.innings[S.innings.length - 1].status === 'in_progress' ? S.current_innings : S.innings.length;
  const ov = h('input', { type: 'number', min: 1, placeholder: 'unchanged', style: { width: '110px' } }); const tg = h('input', { type: 'number', min: 1, placeholder: 'unchanged', style: { width: '110px' } });
  const target = idx < S.innings.length ? S.innings[idx] : null;
  const method = select([{ value: 'DLS', label: 'DLS (Duckworth-Lewis-Stern)' }, { value: 'VJD', label: 'VJD' }, { value: 'manual', label: 'Other / manual' }], 'DLS');
  const inningsSel = select([...S.innings.map(i => ({ value: i.index, label: `Innings ${i.index + 1} (${i.batting_name})` })), { value: S.innings.length, label: `Innings ${S.innings.length + 1} (not yet started)` }], idx);
  modal('Revised overs / target', h('div', {}, h('p', { class: 'mute small' }, 'Enter the figures the umpires give you from the official DLS calculator — GoScore does not calculate DLS itself. “Target” = runs the chasing team must SCORE TO WIN.'), h('label', {}, 'Applies to'), inningsSel, h('label', {}, 'Revised overs'), ov, h('label', {}, 'Revised target (runs to win)'), tg, h('label', {}, 'Method'), method), { buttons: [{ label: 'Cancel' }, { label: 'Apply', kind: 'primary', onclick: async () => { if (!ov.value && !tg.value) { toast('Enter overs and/or target', 'bad'); return false; } const r = await post({ type: 'revise', innings: +inningsSel.value, overs_limit: ov.value ? +ov.value : undefined, target: tg.value ? +tg.value : undefined, method: method.value }); if (!r) return false; } }] });
}
function endModal() {
  const reason = select([{ value: 'declared', label: 'Declared' }, { value: 'time', label: 'Time / weather (innings closed)' }, { value: 'forfeited', label: 'Forfeited' }, { value: 'all_out', label: 'All out (e.g. no batters available)' }, { value: 'manual', label: 'Other' }], 'declared');
  modal('End innings', h('div', {}, h('label', {}, 'Reason'), reason), { buttons: [{ label: 'Cancel' }, { label: 'End innings', kind: 'danger', onclick: async () => { const r = await post({ type: 'innings_end', innings: S.current_innings, reason: reason.value }); if (!r) return false; } }] });
}
const BREAKS = [['drinks', 'Drinks'], ['lunch', 'Lunch'], ['tea', 'Tea'], ['stumps', 'Stumps (close of play)'], ['rain', 'Rain delay'], ['bad_light', 'Bad light'], ['injury', 'Injury'], ['other', 'Other']];
function delayModal() {
  const multi = !!S.play;
  const kinds = multi ? BREAKS : [['rain', 'Rain delay'], ['bad_light', 'Bad light'], ['injury', 'Injury'], ['other', 'Other']];
  const kind = select(kinds.map(([v, l]) => ({ value: v, label: l })), multi ? 'drinks' : 'rain');
  const t = h('input', { value: '', placeholder: 'optional message (default: the break name)', style: { width: '100%' } });
  const note = h('div', { class: 'mute small' }, multi ? 'Lunch / tea start the next session and stumps starts the next day when you press Resume. Rain, bad light, drinks and injury do not change the session.' : '');
  const lastDay = multi && S.play.last_day;
  modal('Play suspended / break', h('div', {}, h('label', {}, 'Reason'), kind, h('label', {}, 'Message shown on the overlay'), t, note,
    lastDay ? h('div', { class: 'alert warn' }, `Day ${S.play.day} is the final day. If play is over for good, use “Close of play — match drawn” below instead of Stumps.`) : null),
    { buttons: [{ label: 'Cancel' }, ...(lastDay ? [{ label: 'Close of play — match drawn', kind: 'danger', onclick: async () => { const r = await post({ type: 'result', status: 'draw', text: 'Match drawn', reason: 'time expired' }); if (!r) return false; } }] : []),
      { label: 'Suspend play', kind: 'primary', onclick: async () => { const r = await post({ type: 'delay', kind: kind.value, text: t.value.trim() || undefined }); if (!r) return false; } }] });
}
function daySessionModal() {
  const p = S.play;
  const d = h('input', { type: 'number', min: 1, max: 30, value: p.day, style: { width: '70px' } }), sn = h('input', { type: 'number', min: 1, max: 6, value: p.session, style: { width: '70px' } });
  modal('Set day & session', h('div', {}, h('p', { class: 'mute small' }, 'Corrects the counters if a break button was pressed by mistake. “Today” / “this session” totals restart from now.'), h('label', {}, 'Day'), d, h('label', {}, 'Session'), sn),
    { buttons: [{ label: 'Cancel' }, { label: 'Set', kind: 'primary', onclick: async () => { const r = await post({ type: 'day_set', day: +d.value, session: +sn.value, reason: 'manual correction' }); if (!r) return false; } }] });
}
async function newBallAction() { if (await confirmBox('Record that the fielding side has taken the new ball? Ball age restarts from 0.', 'New ball taken')) { const r = await post({ type: 'new_ball' }); if (r) toast('New ball recorded', 'ok'); } }
function creaseModal() {
  const i = inn(); if (!i) return;
  const bt = [{ value: '', label: '—' }, ...playersOf(S, i.batting).map(p => ({ value: p.id, label: p.name }))];
  const s = select(bt, i.striker || ''), n = select(bt, i.non_striker || '');
  modal('Set who is at the crease', h('div', {}, h('p', { class: 'mute small' }, 'Corrects the on-field pair without recording a wicket or a ball.'), h('label', {}, 'Striker'), s, h('label', {}, 'Non-striker'), n), { buttons: [{ label: 'Cancel' }, { label: 'Set', kind: 'primary', onclick: async () => { const r = await post({ type: 'set_batters', innings: S.current_innings, striker: s.value || null, non_striker: n.value || null }); if (!r) return false; } }] });
}
function resultModal() {
  const st = select([{ value: 'won', label: 'Won' }, { value: 'tie', label: 'Tied' }, { value: 'no_result', label: 'No result' }, { value: 'abandoned', label: 'Abandoned' }, { value: 'draw', label: 'Draw' }], 'won');
  const w = select([{ value: 'A', label: S.teams.A.name }, { value: 'B', label: S.teams.B.name }], 'A'); const t = h('input', { placeholder: 'e.g. Eagles won by 5 runs (DLS)', style: { width: '100%' } });
  modal('Set result manually', h('div', {}, h('p', { class: 'mute small' }, 'Overrides the calculated result (forfeit, DLS dispute, abandoned...). Clear it from Match actions to go back to the calculated result.'), h('label', {}, 'Outcome'), st, h('label', {}, 'Winner (if won)'), w, h('label', {}, 'Text shown on screen (optional)'), t), { buttons: [{ label: 'Cancel' }, { label: 'Set result', kind: 'primary', onclick: async () => { const r = await post({ type: 'result', status: st.value, winner: st.value === 'won' ? w.value : null, text: t.value || undefined, method: 'manual' }); if (!r) return false; } }] });
}
async function backupsModal() {
  const d = await api('GET', `/api/matches/${id}/backups`);
  modal('Automatic backups', h('div', {}, h('p', { class: 'mute small' }, 'A backup is saved after every change (last 100 kept). Restoring creates a new version — nothing is lost.'),
    d.backups.map(b => h('div', { class: 'ev' }, h('div', { class: 'd' }, `Version ${b.version} · ${new Date(b.mtime).toLocaleTimeString()}`), h('button', { class: 'btn sm', onclick: async () => { if (await confirmBox(`Restore version ${b.version}?`, 'Restore')) { await api('POST', `/api/matches/${id}/restore`, { version: b.version }); await refresh(); toast('Restored', 'ok'); } } }, 'Restore')))), { wide: true, buttons: [{ label: 'Close' }] });
}
async function rawModal() {
  const d = await api('GET', `/api/matches/${id}/events`); const ta = h('textarea', { style: { minHeight: '320px' } }, JSON.stringify(d.events, null, 1));
  modal('Raw event log', h('div', {}, h('div', { class: 'alert bad' }, 'Danger zone: replaces the whole event log. Bad edits are flagged, never crash the scoreboard, and the previous state stays in backups.'), ta), { wide: true, buttons: [{ label: 'Cancel' }, { label: 'Apply', kind: 'danger', onclick: async () => { try { const r = await api('POST', `/api/matches/${id}/replace-events`, { events: JSON.parse(ta.value), reason: 'raw editor' }); version = r.version; await refresh(); toast(r.errors.length ? r.errors.length + ' invalid events' : 'Applied', r.errors.length ? 'warn' : 'ok'); } catch (e) { toast(e.message, 'bad'); return false; } } }] });
}
async function auditModal() {
  const d = await api('GET', `/api/matches/${id}/audit`);
  modal('Audit log', h('div', {}, d.audit.slice().reverse().map(a => h('div', { class: 'ev' }, h('div', { class: 'd' }, h('b', {}, a.action), h('div', { class: 'meta' }, new Date(a.ts).toLocaleString(), a.detail && a.detail.reason ? ' · ' + a.detail.reason : ''))))), { wide: true, buttons: [{ label: 'Close' }] });
}
