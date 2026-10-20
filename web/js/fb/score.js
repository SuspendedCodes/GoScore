// scorer console.
import { api, h, $, toast, modal, confirmBox, select, uid, Live, setConn, matchIdFromPath } from '../common.js';
import { clockInfo, pl, pname, opp, sortByPos, bench, statusLabel, PERIOD_NAME } from './fbcommon.js';
import { statsPanel } from './statsform.js';
import { pitchEditor } from './pitched.js';

const id = matchIdFromPath();
let S = null, version = 0, canRedo = false, tab = 'lineups', skew = 0, catalog = null, evCache = null;
const wrap = document.querySelector('.wrap');
wrap.replaceChildren(h('div', { id: 'strip', class: 'card fbstrip' }), h('div', { id: 'alerts' }),
  h('div', { class: 'grid fbmain' }, h('div', { id: 'ctl', class: 'grid', style: { alignContent: 'start' } }), h('div', { id: 'pad' })),
  h('div', { class: 'tabs', id: 'tabs' }), h('div', { id: 'tabbody' }));
$('#lControl').href = `/control/${id}`; $('#lCard').href = `/scorecard/${id}`; $('#lOv').href = `/overlay/${id}`; $('#lSetup').href = `/setup/${id}`;
$('#lCard').textContent = 'Scorecard Match page';
const css = document.createElement('style');
css.textContent = `.fbstrip{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center;padding:12px 18px}
.fbstrip .tm{display:flex;align-items:center;gap:12px;font-size:1.3rem;font-weight:800}.fbstrip .tm.b{justify-content:flex-end}.fbstrip .sw{width:10px;height:44px;border-radius:4px}
.fbstrip .mid{text-align:center}.fbstrip .sc{font-size:3rem;font-weight:900;font-variant-numeric:tabular-nums;line-height:1}.fbstrip .clk{font-size:1.7rem;font-weight:800;font-variant-numeric:tabular-nums}
.fbmain{grid-template-columns:minmax(300px,1fr) minmax(380px,1.4fr);margin-top:12px}@media(max-width:900px){.fbmain{grid-template-columns:1fr}}
.tbtn{display:grid;grid-template-columns:1fr 1fr;gap:10px}.tbtn .col{display:grid;gap:8px;align-content:start}.tbtn .hd{font-weight:800;padding:2px 2px;border-bottom:3px solid var(--c,#888)}
.big3{font-size:1.2rem;padding:16px 8px!important}.goalb{background:var(--ok)!important;border-color:var(--ok)!important;color:#fff!important}.yel{background:#f5c518!important;border-color:#f5c518!important;color:#111!important}.redb{background:#d4351c!important;border-color:#d4351c!important;color:#fff!important}
.cardi{display:inline-block;width:11px;height:15px;border-radius:2px;vertical-align:-2px;margin-right:2px}.cardi.y{background:#f5c518}.cardi.r{background:#d4351c}
.pl{display:flex;gap:6px;align-items:center;padding:4px 6px;border-bottom:1px solid var(--line)}.pl .n{width:28px;text-align:right;font-weight:800}.pl .p{width:28px;color:var(--mute);font-size:.75rem}.pl.off{opacity:.5}.pl .nm{flex:1}
.so{display:flex;gap:4px;flex-wrap:wrap}.so .k{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:.8rem;background:var(--panel2);border:1px solid var(--line)}.so .k.scored{background:var(--ok);color:#fff}.so .k.x{background:var(--bad);color:#fff}
.ev .tl{width:64px;font-weight:800}`;
document.head.append(css);

const live = new Live(id, 'live', (d) => { if (d.version < version) return; S = d.state; version = d.version; skew = (S.server_time || Date.now()) - Date.now(); render(); }, (st) => setConn($('#conn'), st));
api('GET', `/api/matches/${id}/state`).then(d => { canRedo = d.can_redo; }).catch(() => {});
api('GET', '/api/presets').then(p => { catalog = p.football; if (S) render(); });

// ------------------------------------------------------------------ posting events
async function post(ev, { insertAfter = null, quiet = false } = {}) {
  try {
    let r;
    if (insertAfter) r = await api('POST', `/api/matches/${id}/insert`, { event: ev, after_id: insertAfter, reason: 'inserted from console' });
    else { ev.cid = ev.cid || uid(); ev.expected_version = version; r = await api('POST', `/api/matches/${id}/events`, ev); }
    if (r.version) version = Math.max(version, r.version);
    canRedo = false; evCache = null;
    return r;
  } catch (e) {
    const err = e.payload && e.payload.error;
    if (e.status === 422 && err && err.soft) {
      if (await confirmBox(`${err.message}\n\n${err.hint ? err.hint + '\n\n' : ''}This is a competition rule / likely slip, not a hard Law. Allow it anyway? (it is logged)`, 'Allow anyway')) {
        return post({ ...ev, cid: undefined, force: [...(ev.force || []), err.code] }, { insertAfter, quiet });
      }
      return null;
    }
    if (e.status === 409) { toast(e.message, 'warn', 6000); await refresh(); return null; }
    if (!quiet) toast(e.message + (err && err.hint ? ' — ' + err.hint : ''), 'bad', 8000);
    return null;
  }
}
async function refresh() { const d = await api('GET', `/api/matches/${id}/state`); S = d.state; version = d.version; canRedo = d.can_redo; render(); }
async function undo() { try { const r = await api('POST', `/api/matches/${id}/undo`, {}); version = r.version; canRedo = true; evCache = null; toast('Undone: ' + r.undone.type, 'ok', 2000); await refresh(); } catch (e) { toast(e.message, 'bad'); } }
async function redo() { try { const r = await api('POST', `/api/matches/${id}/redo`, {}); version = r.version; evCache = null; await refresh(); } catch (e) { toast(e.message, 'bad'); } }
const parseMinute = (s) => { s = String(s || '').trim().replace(/'/g, ''); if (!s) return {}; const m = /^(\d{1,3})(?:\s*\+\s*(\d{1,2}))?$/.exec(s); if (!m) throw new Error('Minute must look like 67 or 45+2'); return { min: +m[1], extra: +(m[2] || 0) }; };
const T = (tid) => S.teams[tid];
const tName = (tid) => (tid ? S.teams[tid].name : '');

// ------------------------------------------------------------------ pickers
function picker(tid, which, { value = '', none = null, label = '' } = {}) {
  const sel = h('select'); const team = T(tid);
  const allow = (p) => which === 'on' ? p.status === 'on' : which === 'bench' ? (p.status === 'bench' || (p.status === 'off' && S.format.return_subs)) : p.squad;
  const groups = [['On the pitch', (p) => p.status === 'on'], ['Bench', (p) => p.status === 'bench'], ['Substituted off', (p) => p.status === 'off'], ['Sent off', (p) => p.status === 'sent_off' || p.status === 'bench_sent_off']];
  if (none) sel.append(h('option', { value: '' }, none));
  const lab = (p) => `${p.number ?? '–'}  ${p.name}${p.pos ? ' · ' + p.pos : ''}${p.captain ? ' (C)' : ''}${p.yellows ? ' Yellow card' : ''}`;
  for (const [title, test] of groups) {
    const ps = sortByPos(team.players.filter(p => allow(p) && test(p))); if (!ps.length) continue;
    const og = h('optgroup', { label: title }); ps.forEach(p => { const o = h('option', { value: p.id }, lab(p)); o.dataset.num = p.number ?? ''; og.append(o); }); sel.append(og);
  }
  if (value && [...sel.options].some(o => o.value === value)) sel.value = value;
  const q = h('input', { class: 'qn', placeholder: '#', inputmode: 'numeric', style: { width: '58px' }, title: 'Type the shirt number', oninput: () => { const o = [...sel.options].find(x => x.dataset.num === q.value.trim()); if (o) { sel.value = o.value; sel.dispatchEvent(new Event('change')); } } });
  const el = h('div', { class: 'row' }, label ? h('span', { style: { width: '70px' } }, label) : null, q, sel); el.sel = sel; el.val = () => sel.value;
  return el;
}
const minuteField = (init = '') => h('input', { placeholder: 'auto (clock)', value: init, size: 9, title: 'Leave empty to use the clock. Type 67 or 45+2 to set the minute yourself.' });
const noteHint = () => h('div', { class: 'mut small' }, S.phase === 'ended' ? 'The match has ended — use Events & corrections → “+ after” to insert a late event.' : '');

// ------------------------------------------------------------------ modals
function goalModal(tid, opts = {}) {
  const kind = select(Object.entries(catalog.goal_kinds).map(([v, l]) => ({ value: v, label: l })), opts.kind || 'open');
  const holder = h('div'), ah = h('div');
  const min = minuteField(opts.minute || '');
  let sc, as;
  const build = () => {
    const og = kind.value === 'own_goal';
    sc = picker(og ? opp(tid) : tid, 'any', { none: 'Unknown / not listed', value: opts.player, label: og ? 'Scored by' : 'Scorer' });
    as = picker(tid, 'any', { none: '— no assist —', label: 'Assist' });
    holder.replaceChildren(h('div', { class: 'mut small' }, og ? `Own goal: pick the ${tName(opp(tid))} player who put it in — the goal is credited to ${tName(tid)} (Law 10).` : ''), sc);
    ah.replaceChildren(og || kind.value === 'penalty' ? '' : as);
  };
  kind.onchange = build; build();
  modal(`Goal — ${tName(tid)}`, h('div', {}, h('label', {}, 'Type'), kind, holder, ah, h('label', {}, 'Minute (optional)'), min, noteHint()), { buttons: [{ label: 'Cancel' }, { label: 'Record goal', kind: 'primary', onclick: async () => {
    let w; try { w = parseMinute(min.value); } catch (e) { toast(e.message, 'bad'); return false; }
    const r = await post({ type: 'goal', team: tid, kind: kind.value, player: sc.val() || null, assist: kind.value === 'open' || kind.value === 'free_kick' ? (as.val() || null) : null, ...w }, { insertAfter: opts.insertAfter });
    if (!r) return false; toast('GOAL recorded', 'ok', 1800);
  } }] });
}
function cardModal(tid, color, opts = {}) {
  const who = picker(tid, 'any', { value: opts.player, label: 'Player' });
  const staff = h('input', { type: 'checkbox' }), sname = h('input', { placeholder: 'Name / role (e.g. Head coach)', style: { display: 'none' } });
  staff.onchange = () => { sname.style.display = staff.checked ? '' : 'none'; who.style.display = staff.checked ? 'none' : ''; };
  const col = select([{ value: 'yellow', label: 'Yellow card' }, { value: 'red', label: 'Red card (straight)' }], color);
  const reason = select([{ value: '', label: 'Reason (optional)' }, ...catalog.card_reasons.map(x => ({ value: x, label: x }))], '');
  const hint = h('div', { class: 'mut small' });
  const upd = () => { const p = pl(S, who.val()); hint.textContent = !staff.checked && col.value === 'yellow' && p && p.yellows ? `${p.name} already has a yellow: this is the SECOND YELLOW → automatic red card, player sent off, cannot be replaced.` : ''; };
  who.sel.onchange = upd; col.onchange = upd; upd();
  const min = minuteField(opts.minute || '');
  modal(`Card — ${tName(tid)}`, h('div', {}, col, who, h('label', { class: 'inline' }, staff, ' Team official / coach (not a player)'), sname, hint, h('label', {}, 'Reason'), reason, h('label', {}, 'Minute (optional)'), min),
    { buttons: [{ label: 'Cancel' }, { label: 'Show card', kind: 'primary', onclick: async () => {
      let w; try { w = parseMinute(min.value); } catch (e) { toast(e.message, 'bad'); return false; }
      const ev = staff.checked ? { type: 'card', team: tid, target: 'staff', staff_name: sname.value, color: col.value, reason: reason.value, ...w }
        : { type: 'card', team: tid, player: who.val(), color: col.value, reason: reason.value, ...w };
      const r = await post(ev, { insertAfter: opts.insertAfter }); if (!r) return false;
    } }] });
}
function subModal(tid, opts = {}) {
  const off = picker(tid, 'on', { value: opts.off, label: 'Off' }), on = picker(tid, 'bench', { label: 'On' });
  const kinds = [{ value: 'normal', label: 'Normal substitution' }];
  if (S.format.concussion_subs) kinds.push({ value: 'concussion', label: 'Concussion substitute (permanent)' }, { value: 'additional', label: 'Additional substitute (opponent used a concussion sub)' });
  if (S.phase === 'pre') kinds.push({ value: 'replacement', label: 'Replace a player sent off before kick-off' });
  const kind = select(kinds, 'normal'); const same = h('input', { type: 'checkbox', checked: !!opts.same });
  const pos = select([{ value: '', label: 'Same position as player off' }, ...['GK', 'DF', 'MF', 'FW'].map(x => ({ value: x, label: 'Plays as ' + x }))], '');
  const t = T(tid).subs; const min = minuteField(opts.minute || '');
  modal(`⇄ Substitution — ${tName(tid)}`, h('div', {}, h('div', { class: 'mut small' }, `Used ${t.used}/${t.max} · opportunities ${t.windows}/${t.windows_max}${t.additional_available > 0 ? ' · additional sub available' : ''}. Substitutions made at half-time or between periods don’t use an opportunity.`),
    kind, off, on, pos, h('label', { class: 'inline' }, same, ' Same stoppage as the previous substitution (uses no extra opportunity)'), h('label', {}, 'Minute (optional)'), min),
    { buttons: [{ label: 'Cancel' }, { label: 'Make substitution', kind: 'primary', onclick: async () => {
      let w; try { w = parseMinute(min.value); } catch (e) { toast(e.message, 'bad'); return false; }
      const r = await post({ type: 'sub', team: tid, off: off.val(), on: on.val(), kind: kind.value, with_prev: same.checked, pos: pos.value || undefined, ...w }, { insertAfter: opts.insertAfter });
      if (!r) return false;
      setTimeout(() => { if (!opts.insertAfter) confirmBox('Another substitution in the same stoppage?', 'Yes, add another', 'No').then(y => { if (y) subModal(tid, { same: true }); }); }, 200);
    } }] });
}
function penaltyModal(tid) {
  const mode = select([{ value: 'award', label: 'Penalty awarded' }, { value: 'saved', label: 'Penalty saved' }, { value: 'missed', label: 'Penalty missed' }, { value: 'post', label: 'Penalty hit the woodwork' }], 'award');
  const who = picker(tid, 'on', { none: 'Taker (optional)', label: 'Taker' }); const why = h('input', { placeholder: 'reason (optional) e.g. handball' });
  modal(`Penalty — ${tName(tid)}`, h('div', {}, h('p', { class: 'mut small' }, 'A scored penalty is recorded as a GOAL (type: Penalty). Use this for the award itself and for penalties that are saved or missed in play.'), mode, who, why),
    { buttons: [{ label: 'Cancel' }, { label: 'Record', kind: 'primary', onclick: async () => {
      const r = mode.value === 'award' ? await post({ type: 'penalty_award', team: tid, reason: why.value }) : await post({ type: 'penalty_miss', team: tid, player: who.val() || null, outcome: mode.value });
      if (!r) return false; } }] });
}
function varModal() {
  const act = S.var.active;
  const kind = select(Object.entries(catalog.var_kinds).map(([v, l]) => ({ value: v, label: l })), 'goal');
  const team = select([{ value: '', label: 'Team (optional)' }, { value: 'A', label: tName('A') }, { value: 'B', label: tName('B') }], '');
  const dec = select(Object.entries(catalog.var_decisions).map(([v, l]) => ({ value: v, label: l })), 'goal_stands');
  const why = h('input', { placeholder: 'reason shown on screen (optional) e.g. offside' }); const apply = h('input', { type: 'checkbox', checked: true });
  const body = act ? h('div', {}, h('div', { class: 'alert warn' }, 'VAR check in progress: ' + S.var.text), h('label', {}, 'Decision'), dec, why,
    h('label', { class: 'inline' }, apply, ' Also apply it: disallow the last goal / rescind the last card automatically'))
    : h('div', {}, h('label', {}, 'What is being checked?'), kind, team);
  modal('VAR', body, { buttons: [{ label: 'Close' }, act ? { label: 'Record decision', kind: 'primary', onclick: async () => {
    const r = await post({ type: 'var_result', decision: dec.value, reason: why.value }); if (!r) return false;
    if (apply.checked && dec.value === 'goal_disallowed') await post({ type: 'goal_cancel', reason: why.value || 'VAR' });
    if (apply.checked && dec.value === 'red_card_cancelled') await post({ type: 'card_rescind' });
    if (apply.checked && dec.value === 'penalty_awarded') await post({ type: 'penalty_award', team: S.var.team || 'A', reason: 'VAR' });
  } } : { label: 'Start VAR check', kind: 'primary', onclick: async () => { const r = await post({ type: 'var_check', kind: kind.value, team: team.value || null }); if (!r) return false; } }] });
}
function addedModal() {
  const cur = S.clock.added_min;
  const n = h('input', { type: 'number', min: 0, max: 30, value: cur || 3, style: { width: '80px' } });
  modal('Added time (from the fourth official’s board)', h('div', {}, h('div', { class: 'row' }, ...[1, 2, 3, 4, 5, 6, 7, 8].map(k => h('button', { class: 'btn', onclick: () => { n.value = k; } }, '+' + k))), h('label', {}, 'Minutes'), n),
    { buttons: [{ label: 'Cancel' }, { label: 'Show added time', kind: 'primary', onclick: async () => { const r = await post({ type: 'added_time', minutes: +n.value }); if (!r) return false; } }] });
}
function incidentModal(kind0 = 'injury') {
  const k = select([{ value: 'injury', label: 'Injury / treatment' }, { value: 'drinks', label: 'Drinks / cooling break' }, { value: 'delay', label: 'Stoppage / delay' }, { value: 'other', label: 'Other note' }], kind0);
  const team = select([{ value: '', label: 'No team' }, { value: 'A', label: tName('A') }, { value: 'B', label: tName('B') }], ''); const txt = h('input', { style: { width: '100%' }, placeholder: 'e.g. Smith receiving treatment' });
  modal('Timeline note', h('div', {}, k, team, h('label', {}, 'Text'), txt), { buttons: [{ label: 'Cancel' }, { label: 'Add', kind: 'primary', onclick: async () => { const r = await post({ type: 'incident', kind: k.value, team: team.value || null, text: txt.value }); if (!r) return false; } }] });
}
function endMatchModal() {
  modal('End / abandon the match', h('div', {}, h('p', {}, 'Use “Abandon” if the referee stops the match before it is completed (weather, crowd trouble, too few players...). The result stays as you set it in Overrides → Result.')),
    { buttons: [{ label: 'Cancel' }, { label: 'Abandon match…', kind: 'danger', onclick: async () => { const why = prompt('Reason (shown on screen):', 'Abandoned'); if (why == null) return false; const r = await post({ type: 'abandon', reason: why }); if (!r) return false; } },
      { label: 'End match now (full-time)', kind: 'primary', onclick: async () => { const r = await post({ type: 'match_end' }); if (!r) return false; } }] });
}

// ------------------------------------------------------------------ rendering
function render() {
  if (!S || !catalog) return;
  document.title = `${S.title} · Scorer`; $('#title').textContent = S.title || 'Match';
  renderStrip(); renderAlerts(); renderCtl(); renderPad(); renderTabs();
}
const swatch = (t) => h('span', { class: 'sw', style: { background: t.color } });
function renderStrip() {
  const A = T('A'), B = T('B'); const el = $('#strip');
  const cards = (t) => (t.red_cards ? h('span', { title: 'red cards' }, ' ', h('span', { class: 'cardi r' }), t.red_cards > 1 ? '×' + t.red_cards : '') : null);
  el.replaceChildren(
    h('div', { class: 'tm' }, swatch(A), h('span', {}, A.name), cards(A)),
    h('div', { class: 'mid' }, h('div', { class: 'sc' }, `${S.score.A} – ${S.score.B}`), h('div', { class: 'clk', id: 'clk' }, '00:00'),
      h('div', { class: 'row', style: { justifyContent: 'center' } }, h('span', { class: 'badge ' + (S.status === 'live' ? 'ok' : 'ov') }, S.phase_label), h('span', { id: 'addb' }),
        S.aggregate.on ? h('span', { class: 'badge ov' }, `AGG ${S.aggregate.A}-${S.aggregate.B}`) : null,
        S.var.active ? h('span', { class: 'badge bad' }, 'VAR: ' + S.var.text) : null, S.shootout.started ? h('span', { class: 'badge ov' }, `PENS ${S.shootout.goals.A}-${S.shootout.goals.B}`) : null),
      S.result.final ? h('div', { style: { fontWeight: 800, marginTop: '4px' } }, S.result.text) : null),
    h('div', { class: 'tm b' }, cards(B), h('span', {}, B.name), swatch(B)));
  tick();
}
function tick() {
  const c = $('#clk'); if (!c || !S) return;
  const ci = clockInfo(S, Date.now() + skew);
  c.textContent = ci.mmss + (ci.over ? '  ' + ci.stoppage : ''); c.style.color = S.clock.running ? '' : 'var(--mute)';
  const ab = $('#addb'); if (ab) ab.replaceChildren(S.clock.added_min ? h('span', { class: 'badge ov' }, `+${S.clock.added_min} added`) : '', !S.clock.running && S.status === 'live' ? h('span', { class: 'badge bad' }, 'CLOCK PAUSED') : '');
}
setInterval(tick, 250);
function renderAlerts() {
  const a = $('#alerts'); a.replaceChildren();
  for (const e of S.integrity.errors.slice(0, 4)) a.append(h('div', { class: 'alert bad' }, `Warning Event #${e.seq} (${e.type}) was not applied: ${e.message}`, h('button', { class: 'btn sm', onclick: () => { tab = 'events'; render(); } }, 'Fix')));
  for (const tid of 'AB') if (T(tid).below_minimum) a.append(h('div', { class: 'alert bad' }, `${T(tid).name} has ${T(tid).on_field} players — fewer than the minimum of ${S.format.min_players}. The match cannot continue (Law 3).`, h('button', { class: 'btn sm danger', onclick: endMatchModal }, 'Abandon…')));
  for (const tid of 'AB') if (T(tid).on_field > S.format.on_field && S.status === 'live') a.append(h('div', { class: 'alert warn' }, `${T(tid).name} has ${T(tid).on_field} players on the pitch (max ${S.format.on_field}) — check the line-up / substitutions.`));
  if (S.stats.warnings.length && tab === 'stats') a.append(h('div', { class: 'alert warn' }, 'Warning Stats: ' + S.stats.warnings.join(' · ')));
}
function bigBtn(label, fn, cls = '') { return h('button', { class: 'btn big3 ' + cls, onclick: fn }, label); }
function renderCtl() {
  const ph = S.phase, box = $('#ctl'); const kids = []; const run = S.clock.running;
  const next = { pre: 'Kick off — start 1st half', break1: 'Start 2nd half', break2: 'Start extra time', break3: 'Start 2nd half of extra time' };
  const start = async (ago) => { const r = await post({ type: 'period_start', ago_ms: ago * 1000 }); return r; };
  const card = h('div', { class: 'card' }, h('h2', {}, 'Match clock'));
  if (next[ph]) {
    const ago = h('input', { type: 'number', min: 0, value: 0, style: { width: '70px' } });
    card.append(bigBtn('▶ ' + next[ph], () => start(+ago.value || 0), 'goalb'), h('div', { class: 'row mut small', style: { marginTop: '6px' } }, 'Whistle was', ago, 'seconds ago (late button press)'));
    if (ph === 'break2') {
      card.append(h('div', { class: 'row', style: { marginTop: '8px' } }, S.can_shootout ? h('button', { class: 'btn', onclick: startShootout }, 'Go straight to penalties') : null, h('button', { class: 'btn', onclick: endMatchModal }, 'End match')));
    }
  } else if (['p1', 'p2', 'et1', 'et2'].includes(ph)) {
    const names = { p1: 'half-time', p2: 'full-time (90 min)', et1: 'end of ET 1st half', et2: 'end of extra time' };
    card.append(h('div', { class: 'row' }, run ? bigBtn('Pause clock', () => post({ type: 'pause', reason: '' })) : bigBtn('Resume clock', () => post({ type: 'resume' }), 'goalb'),
      bigBtn('Added time…', addedModal), bigBtn('End: ' + names[ph], async () => { const r = await post({ type: 'period_end' }); return r; }, 'redb')));
    card.append(h('div', { class: 'mut small', style: { marginTop: '6px' } }, `${PERIOD_NAME[S.clock.period]} · ${S.clock.regular_ms / 60000} min period. If the clock is wrong use Overrides → Set clock.`));
  } else if (ph === 'pre_so' || ph === 'so') {
    card.append(h('div', { class: 'mut' }, 'Penalty shoot-out — see the panel on the right.'));
  } else if (ph === 'ended') {
    card.append(h('div', { class: 'alert info' }, 'Match finished. ' + (S.result.text || ''), h('div', { class: 'mut small' }, 'Made a mistake? Undo, or use Events & corrections / Manual override.')));
  }
  card.append(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn', onclick: undo }, '↶ Undo last'), h('button', { class: 'btn', disabled: !canRedo, onclick: redo }, '↷ Redo'), h('button', { class: 'btn ghost', onclick: endMatchModal }, 'End / abandon…')));
  kids.push(card);
  kids.push(lastEvents());
  box.replaceChildren(...kids);
}
function lastEvents() {
  const rows = S.timeline.slice(-7).reverse();
  return h('div', { class: 'card', style: { padding: 0 } }, rows.length ? rows.map(r => evRow(r)) : h('div', { class: 'mut', style: { padding: '12px' } }, 'No events yet.'));
}
function evIcon(r) {
  if (r.type === 'goal') return h('img', { class: 'ui-icon', src: '/static/assets/icons/football.svg', alt: 'Goal' }); if (r.type === 'goal_cancel') return 'Disallow'; if (r.type === 'card') return h('span', { class: 'cardi ' + (r.color === 'yellow' ? 'y' : 'r') });
  if (r.type === 'card_rescind') return '↩'; if (r.type === 'sub') return '⇄'; if (r.type === 'var') return 'VAR'; if (r.type === 'penalty' || r.type === 'penalty_miss') return 'Penalty'; if (r.type === 'so_kick') return r.result === 'scored' ? '●' : 'Missed'; if (r.type === 'period') return 'End period'; if (r.type === 'added_time') return 'Added time'; return '•';
}
function evRow(r) {
  return h('div', { class: 'ev', style: { textDecoration: r.cancelled ? 'line-through' : '', opacity: r.cancelled ? .55 : 1 } },
    h('span', { class: 'tl' }, r.label || ''), h('span', {}, evIcon(r)), h('div', { class: 'd' }, h('div', {}, (r.team ? `[${T(r.team).short}] ` : '') + (r.type === 'sub' ? `${r.on_name} Switch ${r.off_name}` : r.type === 'card' ? `${r.text} — ${r.card_text || ''}` : r.text), r.type === 'goal' && r.assist_name ? h('span', { class: 'mut' }, ` (assist ${r.assist_name})`) : null, r.type === 'goal' ? h('span', { class: 'mut' }, `  ${r.score.A}-${r.score.B}`) : null)));
}
function renderPad() {
  const pad = $('#pad'); const A = T('A'), B = T('B');
  const so = S.phase === 'pre_so' || S.phase === 'so' || (S.phase === 'break2' && S.can_shootout && S.shootout.started);
  const col = (tid) => h('div', { class: 'col', style: { '--c': T(tid).color } }, h('div', { class: 'hd' }, T(tid).name),
    h('button', { class: 'btn big3 goalb', onclick: () => goalModal(tid) }, 'Goal'), h('button', { class: 'btn big3 yel', onclick: () => cardModal(tid, 'yellow') }, 'Yellow card'), h('button', { class: 'btn big3 redb', onclick: () => cardModal(tid, 'red') }, 'Red card'),
    h('button', { class: 'btn big3', onclick: () => subModal(tid) }, '⇄ Substitution'), h('button', { class: 'btn', onclick: () => penaltyModal(tid) }, 'Penalty…'));
  const kids = [h('div', { class: 'card' }, h('h2', {}, 'Match events'), h('div', { class: 'tbtn' }, col('A'), col('B')),
    h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn', onclick: varModal }, S.var.active ? 'VAR: record decision' : 'VAR check'), h('button', { class: 'btn', onclick: async () => { if (await confirmBox('Disallow the last goal (e.g. offside / foul)? The score reverts.', 'Disallow goal')) post({ type: 'goal_cancel', reason: '' }); } }, 'Disallow last goal'),
      h('button', { class: 'btn', onclick: () => incidentModal() }, 'Notes (injury, drinks…)')))];
  if (so) kids.unshift(shootoutPanel());
  pad.replaceChildren(...kids);
}
function startShootout() {
  const first = select([{ value: 'A', label: tName('A') }, { value: 'B', label: tName('B') }], 'A');
  modal('Penalty shoot-out', h('div', {}, h('p', { class: 'mut small' }, 'Law 10: the referee tosses a coin; the winner chooses to kick first or second. Each team takes 5 kicks alternately; it ends early when one side can no longer catch up; then sudden death in equal rounds. Only players on the pitch at the end of the match can kick, and every eligible player kicks once before anyone repeats.'), h('label', {}, 'Kicks first'), first),
    { buttons: [{ label: 'Cancel' }, { label: 'Start shoot-out', kind: 'primary', onclick: async () => { const r = await post({ type: 'shootout_start', first: first.value }); if (!r) return false; } }] });
}
function shootoutPanel() {
  const so = S.shootout; const card = h('div', { class: 'card' }, h('h2', {}, 'Penalty shoot-out'));
  if (!so.started) { card.append(h('button', { class: 'btn big3 primary', onclick: startShootout }, 'Start shoot-out (coin toss)…')); return card; }
  const row = (tid) => h('div', { class: 'row' }, h('b', { style: { width: '120px' } }, tName(tid)), h('div', { class: 'so' }, so.kicks.filter(k => k.team === tid).map(k => h('span', { class: 'k ' + (k.result === 'scored' ? 'scored' : 'x'), title: k.player_name }, k.result === 'scored' ? '●' : 'Missed'))), h('span', { class: 'sp' }), h('b', { style: { fontSize: '1.4rem' } }, so.goals[tid]));
  card.append(row('A'), row('B'));
  if (so.decided) { card.append(h('div', { class: 'alert info' }, S.result.text || `${tName(so.winner)} win the shoot-out`), h('button', { class: 'btn', onclick: undo }, '↶ Undo last kick')); return card; }
  const tid = so.next; const who = picker(tid, 'on', { none: 'Unknown / not listed', label: 'Kicker' });
  const kick = async (result) => { const r = await post({ type: 'shootout_kick', team: tid, player: who.val() || null, result }); if (r) toast(result === 'scored' ? 'GOAL' : 'No goal', result === 'scored' ? 'ok' : 'warn', 1500); };
  card.append(h('div', { class: 'alert info' }, `Kick ${Math.ceil((so.taken[tid] + 1))} — ${tName(tid)}${so.round > 5 ? ' · SUDDEN DEATH' : ''}`), who,
    h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn big3 goalb', onclick: () => kick('scored') }, '● Scored'), h('button', { class: 'btn big3', onclick: () => kick('saved') }, 'Saved'), h('button', { class: 'btn big3', onclick: () => kick('missed') }, 'Missed'), h('button', { class: 'btn big3', onclick: () => kick('post') }, 'Woodwork'), h('button', { class: 'btn', onclick: undo }, '↶ Undo')));
  return card;
}

// ------------------------------------------------------------------ tabs
let statsUi = null, pitchUi = null;
function renderTabs() {
  const tabs = [['lineups', 'Line-ups & bench'], ['pitch', 'Formation (drag & drop)'], ['events', 'Events & corrections'], ['stats', 'Stats (manual)'], ['override', 'Manual override'], ['match', 'Match actions']];
  $('#tabs').replaceChildren(...tabs.map(([k, l]) => h('button', { class: 'tab' + (tab === k ? ' on' : ''), onclick: () => { tab = k; render(); } }, l)));
  const B = $('#tabbody');
  if (tab === 'stats') {
    if (!statsUi) statsUi = statsPanel({ getState: () => S, catalog, post });
    if (!B.contains(statsUi.el)) { B.replaceChildren(statsUi.el); }
    const active = document.activeElement; if (active && statsUi.el.contains(active) && active.tagName === 'INPUT') return;   // never wipe what is being typed
    statsUi.refresh(); return;
  }
  if (tab === 'pitch') {
    if (!pitchUi) pitchUi = { A: pitchEditor({ getState: () => S, post, tid: 'A' }), B: pitchEditor({ getState: () => S, post, tid: 'B' }) };
    if (!B.contains(pitchUi.A.el)) B.replaceChildren(h('div', { class: 'grid g2' }, ['A', 'B'].map(t => h('div', { class: 'card' }, h('h3', {}, S.teams[t].name), pitchUi[t].el))));
    pitchUi.A.refresh(); pitchUi.B.refresh(); return;
  }
  B.replaceChildren();
  if (tab === 'lineups') renderLineups(B); else if (tab === 'events') renderEvents(B); else if (tab === 'override') renderOverride(B); else renderMatch(B);
}
function plRow(p, tid) {
  const marks = [p.yellows ? h('span', { class: 'cardi y' }) : null, p.red ? h('span', { class: 'cardi r' }) : null, p.goals ? 'Football' + (p.goals > 1 ? '×' + p.goals : '') : null, p.status === 'off' ? '↓' : null, p.status === 'on' && p.replacing ? '↑' : null];
  return h('div', { class: 'pl' + (['off', 'sent_off', 'bench_sent_off'].includes(p.status) ? ' off' : '') }, h('span', { class: 'n' }, p.number ?? ''), h('span', { class: 'p' }, p.pos), h('span', { class: 'nm' }, p.name + (p.captain ? ' (C)' : ''), ' ', ...marks),
    p.status === 'on' ? h('span', { class: 'row' }, h('button', { class: 'btn sm', title: 'Goal', onclick: () => goalModal(tid, { player: p.id }) }, 'Football'), h('button', { class: 'btn sm', title: 'Yellow', onclick: () => cardModal(tid, 'yellow', { player: p.id }) }, 'Yellow card'), h('button', { class: 'btn sm', title: 'Red', onclick: () => cardModal(tid, 'red', { player: p.id }) }, 'Red card'), h('button', { class: 'btn sm', title: 'Substitute off', onclick: () => subModal(tid, { off: p.id }) }, '⇄'))
      : h('span', { class: 'mut small' }, statusLabel(p)));
}
function renderLineups(B) {
  B.append(h('div', { class: 'grid g2' }, ['A', 'B'].map(tid => {
    const t = T(tid); const on = t.players.filter(p => p.started || p.status === 'on').sort((a, b) => (a.slot ?? 99) - (b.slot ?? 99));
    return h('div', { class: 'card' }, h('h3', {}, `${t.name} · ${t.formation} · ${t.on_field} on pitch`), h('div', { class: 'mut small' }, t.subs.used + '/' + t.subs.max + ' subs · ' + t.subs.windows + '/' + t.subs.windows_max + ' opportunities'),
      ...on.map(p => plRow(p, tid)), h('h3', { style: { marginTop: '10px' } }, 'Substitutes'), ...bench(S, tid).map(p => plRow(p, tid)), h('div', { class: 'mut small', style: { marginTop: '6px' } }, t.coach ? 'Coach: ' + t.coach : ''));
  })));
}
async function renderEvents(B) {
  B.append(h('div', { class: 'mute' }, 'Loading…'));
  const evd = await api('GET', `/api/matches/${id}/events`);
  if (tab !== 'events') return;
  const rowOf = Object.fromEntries(S.timeline.map(r => [r.id, r]));
  B.replaceChildren(h('div', { class: 'alert info' }, 'Every action is an event. Edit, delete or insert any of them; everything is recalculated instantly and the audit log keeps the history. Events in red could not be applied.'));
  const list = h('div', { class: 'card', style: { padding: 0 } });
  evd.events.slice().reverse().forEach((ev, ri) => {
    const stt = evd.status[ev.id] || { ok: true }; const r = rowOf[ev.id];
    const insertable = ['goal', 'card', 'sub', 'penalty_award', 'incident'].includes(ev.type);
    list.append(h('div', { class: 'ev' + (stt.ok ? '' : ' invalid') }, h('span', { class: 'mute small', style: { width: '34px' } }, '#' + (evd.events.length - ri)), h('span', { class: 'tl' }, ev.label || ''),
      h('div', { class: 'd' }, h('div', {}, r ? (r.type === 'sub' ? `⇄ [${T(r.team).short}] ${r.on_name} on, ${r.off_name} off` : `${r.type === 'goal' ? '' : r.type === 'card' ? (r.color === 'yellow' ? 'Yellow card ' : 'Red card ') : ''}${r.team ? '[' + T(r.team).short + '] ' : ''}${r.text}`) : describe(ev)),
        h('div', { class: 'meta' }, new Date(ev.ts).toLocaleTimeString(), ev.edited ? ' · edited' : '', ev.inserted ? ' · inserted' : '', ev.force ? ' · forced: ' + ev.force.join(',') : '', !stt.ok ? ' · Warning ' + stt.error.message : '')),
      h('button', { class: 'btn sm', onclick: () => jsonEditModal(ev) }, 'Edit'),
      insertable ? null : null,
      h('button', { class: 'btn sm', title: 'Insert a missed goal / card / sub right after this event', onclick: () => insertMenu(ev) }, '+ after'),
      h('button', { class: 'btn sm danger', onclick: async () => { if (!(await confirmBox('Delete this event? Everything after it is recalculated.', 'Delete'))) return; const x = await api('DELETE', `/api/matches/${id}/events/${ev.id}?reason=deleted%20in%20console`); version = x.version; await refresh(); } }, 'Missed')));
  });
  B.append(list);
}
function describe(ev) {
  const t = ev.type; const f = (k) => ev[k] ?? '';
  if (t === 'period_start') return 'Period start'; if (t === 'period_end') return 'Whistle (end of period)'; if (t === 'pause') return 'Clock paused'; if (t === 'resume') return 'Clock resumed';
  if (t === 'clock_set') return `OVERRIDE clock ${f('minute')}:${String(ev.second || 0).padStart(2, '0')}`; if (t === 'score_set') return `OVERRIDE score ${ev.A}-${ev.B}`; if (t === 'phase_set') return `OVERRIDE phase ${ev.phase}`;
  if (t === 'stats_set') return 'Stats entered (manual)'; if (t === 'info') return `Info: ${ev.key} = ${ev.value}`; if (t === 'added_time') return `Added time ${ev.minutes}`;
  return t;
}
function insertMenu(after) {
  modal('Insert a missed event after this one', h('div', { class: 'row' }, ...[['goal', 'Goal'], ['card', 'Yellow / red card'], ['sub', '⇄ Substitution']].map(([k, l]) => h('button', { class: 'btn big3', onclick: (e) => { document.querySelector('.modal-back')?.remove(); document.body.classList.remove('has-modal');
    const m0 = after.min ? `${after.min}${after.extra ? '+' + after.extra : ''}` : '';
    const tid = 'A'; if (k === 'goal') goalModal(tid, { insertAfter: after.id, minute: m0 }); else if (k === 'card') cardModal(tid, 'yellow', { insertAfter: after.id, minute: m0 }); else subModal(tid, { insertAfter: after.id, minute: m0 }); } }, l))),
    { buttons: [{ label: 'Close' }] });
}
function jsonEditModal(ev) {
  const ta = h('textarea', {}, JSON.stringify(ev, null, 2));
  modal('Edit event (advanced)', h('div', {}, h('p', { class: 'mute small' }, 'Edit the raw event — e.g. change "min"/"extra" to move it to another minute, or "team"/"player" to fix who it was. id/ts are kept.'), ta), { wide: true, buttons: [{ label: 'Cancel' }, { label: 'Save', kind: 'primary', onclick: async () => {
    try { const patch = JSON.parse(ta.value); const r = await api('PUT', `/api/matches/${id}/events/${ev.id}`, { patch, reason: 'raw edit' }); version = r.version; evCache = null; await refresh(); } catch (e) { toast(e.message, 'bad'); return false; } } }] });
}

// ---- manual override tab
function renderOverride(B) {
  const why = h('input', { placeholder: 'Reason (kept in the audit log)', style: { flex: 1, minWidth: '240px' } });
  const num = (v, w = 70) => h('input', { type: 'number', min: 0, value: v, style: { width: w + 'px' } });
  const sA = num(S.score.A), sB = num(S.score.B);
  const ck = S.clock; const cur = clockInfo(S, Date.now() + skew); const [cm, cs] = cur.mmss.split(':');
  const cmI = num(+cm), csI = num(+cs);
  const ph = select(Object.entries(catalog.phases).map(([v, l]) => ({ value: v, label: l })), S.phase);
  const info = { attendance: h('input', { value: S.attendance || '', size: 10 }), weather: h('input', { value: S.weather || '', size: 16 }), motm: h('input', { value: S.motm || '', size: 18, placeholder: 'Man of the match' }) };
  const capT = select([{ value: 'A', label: tName('A') }, { value: 'B', label: tName('B') }], 'A'); const capP = h('div'); const mk = () => { capP.replaceChildren(picker(capT.value, 'any', { label: 'Player' })); }; capT.onchange = mk; mk();
  const pos = select(['GK', 'DF', 'MF', 'FW'].map(x => ({ value: x, label: x })), 'MF');
  const need = () => { const w = why.value.trim(); if (!w) { toast('Please give a reason', 'bad'); return null; } return w; };
  const res = select([{ value: 'A', label: tName('A') + ' won' }, { value: 'B', label: tName('B') + ' won' }, { value: 'draw', label: 'Draw' }, { value: 'none', label: 'No result' }], 'A'); const rk = select([{ value: 'forfeit', label: 'Forfeit / walkover' }, { value: 'abandoned', label: 'Abandoned' }, { value: 'manual', label: 'Decided by committee / other' }], 'forfeit'); const rt = h('input', { placeholder: 'Result text shown on screen', style: { width: '100%' } });
  B.append(h('div', { class: 'alert warn' }, h('b', {}, 'Manual override. '), 'Fix anything the software or the scorer got wrong. Each override is an event in the log: visible, undoable, and recorded in the audit trail. Statistics have their own tab (“Stats (manual)”).'),
    h('div', { class: 'row' }, why),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Score'), h('div', { class: 'row' }, tName('A'), sA, '–', sB, tName('B'), h('button', { class: 'btn primary', onclick: async () => { const w = need(); if (!w) return; const r = await post({ type: 'score_set', A: +sA.value, B: +sB.value, reason: w }); if (r) toast('Score pinned', 'ok'); } }, 'Set score')),
      h('div', { class: 'mut small' }, 'Pins the score at this point; goals recorded afterwards are added on top. Goal scorers list is not changed — edit/insert events if the scorers are wrong.')),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Match clock'), h('div', { class: 'row' }, 'Set to', cmI, ':', csI, 'min:sec of match time', h('button', { class: 'btn primary', onclick: async () => { const w = need(); if (!w) return; const r = await post({ type: 'clock_set', minute: +cmI.value, second: +csI.value, reason: w }); if (r) toast('Clock set', 'ok'); } }, 'Set clock')),
      h('div', { class: 'mut small' }, 'Match time: 2nd half starts at 45:00, extra time at 90:00 (for a 45-minute half). Only while a period is running.')),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Match phase (emergency)'), h('div', { class: 'row' }, ph, h('button', { class: 'btn danger', onclick: async () => { const w = need(); if (!w) return; if (!await confirmBox('Force the match phase? Use this only if the flow got out of step (e.g. pressed the wrong whistle button).', 'Force phase')) return; const r = await post({ type: 'phase_set', phase: ph.value, reason: w }); if (r) toast('Phase set', 'ok'); } }, 'Force phase'))),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Captain & positions'), h('div', { class: 'row' }, capT, capP), h('div', { class: 'row' }, h('button', { class: 'btn', onclick: async () => { const r = await post({ type: 'captain_set', team: capT.value, player: capP.querySelector('select').value }); if (r) toast('Captain set', 'ok'); } }, 'Make captain'), pos, h('button', { class: 'btn', onclick: async () => { const r = await post({ type: 'pos_change', team: capT.value, player: capP.querySelector('select').value, pos: pos.value }); if (r) toast('Position changed', 'ok'); } }, 'Change position (e.g. outfield player in goal)'))),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Match information'), h('div', { class: 'row' }, 'Attendance', info.attendance, 'Weather', info.weather, 'Man of the match', info.motm, h('button', { class: 'btn', onclick: async () => { for (const k of Object.keys(info)) if ((S[k] || '') !== info[k].value) await post({ type: 'info', key: k, value: info[k].value }); toast('Saved', 'ok'); } }, 'Save'))),
    h('div', { class: 'card ovr' }, h('h3', {}, 'Result (walkover / forfeit / abandoned / other)'), h('div', { class: 'row' }, res, rk), rt, h('div', { class: 'row', style: { marginTop: '6px' } }, h('button', { class: 'btn danger', onclick: async () => { const w = need(); if (!w) return; const r = await post({ type: 'result', winner: res.value, kind: rk.value, text: rt.value, reason: w }); if (r) toast('Result set', 'ok'); } }, 'Set result'), h('button', { class: 'btn', onclick: () => post({ type: 'clear_result' }) }, 'Clear manual result'))),
    h('div', { class: 'card' }, h('h3', {}, 'Active overrides'), S.overrides.length ? S.overrides.map(o => h('div', { class: 'ev' }, h('div', { class: 'd' }, o.text), h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox('Remove this override from the log?', 'Remove')) { const x = await api('DELETE', `/api/matches/${id}/events/${o.id}?reason=override%20removed`); version = x.version; await refresh(); } } }, 'Remove'))) : h('div', { class: 'mut' }, 'None.')));
}

// ---- match actions
function renderMatch(B) {
  const act = (label, fn, kind = '') => h('button', { class: 'btn ' + kind, onclick: fn }, label);
  B.append(h('div', { class: 'togg' }, act('Backups / restore…', backupsModal), act('Raw event log (JSON)…', rawModal), act('Edit teams & setup', () => { location.href = `/setup/${id}`; }), h('a', { class: 'btn', href: `/api/matches/${id}/export` }, '⬇ Download match file'), act('Audit log…', auditModal), act('Timeline note…', () => incidentModal())));
}
async function backupsModal() {
  const d = await api('GET', `/api/matches/${id}/backups`);
  modal('Automatic backups', h('div', {}, h('p', { class: 'mute small' }, 'A backup is saved after every change (last 100 kept). Restoring creates a new version — nothing is lost.'),
    d.backups.map(b => h('div', { class: 'ev' }, h('div', { class: 'd' }, `Version ${b.version} · ${new Date(b.mtime).toLocaleTimeString()}`), h('button', { class: 'btn sm', onclick: async () => { if (await confirmBox(`Restore version ${b.version}?`, 'Restore')) { await api('POST', `/api/matches/${id}/restore`, { version: b.version }); await refresh(); } } }, 'Restore')))), { buttons: [{ label: 'Close' }] });
}
async function rawModal() {
  const d = await api('GET', `/api/matches/${id}/events`); const ta = h('textarea', { style: { minHeight: '320px' } }, JSON.stringify(d.events, null, 1));
  modal('Raw event log', h('div', {}, h('div', { class: 'alert bad' }, 'Danger zone: replaces the whole event log. Bad edits are flagged, never crash the scoreboard, and the previous state stays in backups.'), ta), { wide: true, buttons: [{ label: 'Cancel' }, { label: 'Replace log', kind: 'danger', onclick: async () => { try { const r = await api('POST', `/api/matches/${id}/replace-events`, { events: JSON.parse(ta.value), reason: 'raw editor' }); version = r.version; await refresh(); } catch (e) { toast(e.message, 'bad'); return false; } } }] });
}
async function auditModal() {
  const d = await api('GET', `/api/matches/${id}/audit`);
  modal('Audit log', h('div', {}, d.audit.slice().reverse().map(a => h('div', { class: 'ev' }, h('div', { class: 'd' }, h('b', {}, a.action), h('div', { class: 'meta' }, new Date(a.ts).toLocaleString(), a.detail && a.detail.reason ? ' · ' + a.detail.reason : ''))))), { wide: true, buttons: [{ label: 'Close' }] });
}
addEventListener('keydown', (e) => {
  if (document.body.classList.contains('has-modal') || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
});
