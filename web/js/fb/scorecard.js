// Public football match page (venue screen / phone). Shows the PUBLISHED state, so it obeys hold & delay.
import { h, $, Live, matchIdFromPath, setConn } from '../common.js';
import { clockInfo, startingXI, bench } from './fbcommon.js';

const id = matchIdFromPath();
let S = null, skew = 0, delay = 0;
new Live(id, 'pub', (p) => {
  S = p.state; delay = p.delay || 0; skew = (S.server_time || Date.now()) - Date.now(); render();
}, (s) => setConn($('#conn'), s));
setInterval(() => { const c = $('#clk'); if (c && S) { const ci = clockInfo(S, Date.now() + skew - delay * 1000); c.textContent = ci.mmss + (ci.over ? ' ' + ci.stoppage : ''); } }, 500);

function render() {
  document.title = (S.title || 'Match') + ' · GoScore'; $('#title').textContent = S.title || 'Match';
  const A = S.teams.A, B = S.teams.B;
  $('#head').replaceChildren(
    h('div', {}, h('div', { class: 'big' }, `${A.short} ${S.score.A} – ${S.score.B} ${B.short}`), h('div', { class: 'ov' }, `${A.name} v ${B.name}`)),
    h('div', {}, h('b', {}, S.phase_label), ' ', h('span', { id: 'clk', class: 'ov' }, '')),
    S.result.final ? h('b', {}, S.result.text) : null,
    S.shootout.started ? h('div', { class: 'mut' }, `Penalties ${S.shootout.goals.A}-${S.shootout.goals.B}`) : null,
    h('div', { class: 'mut' }, [S.competition, S.stage, S.venue, S.date].filter(Boolean).join(' · ')));
  const tl = h('div', { class: 'card' }, h('h3', {}, 'Match events'), ...S.timeline.filter(r => ['goal', 'card', 'sub', 'var', 'period', 'goal_cancel', 'penalty', 'penalty_miss', 'so_kick'].includes(r.type)).slice().reverse().map(r =>
    h('div', { class: 'ev', style: { textDecoration: r.cancelled ? 'line-through' : '' } }, h('span', { style: { width: '60px', fontWeight: 800 } }, r.label || ''), h('div', { class: 'd' }, (r.team ? `[${S.teams[r.team].short}] ` : '') + (r.type === 'sub' ? `${r.on_name} on, ${r.off_name} off` : r.text + (r.card_text ? ' — ' + r.card_text : ''))))));
  const lu = (tid) => h('div', { class: 'card' }, h('h3', {}, `${S.teams[tid].name} · ${S.teams[tid].formation}`), ...startingXI(S, tid).map(p => h('div', {}, `${p.number ?? ''}  ${p.name}${p.captain ? ' (C)' : ''}${p.status === 'off' ? ' ↓' : ''}${p.red ? ' Red card' : p.yellows ? ' Yellow card' : ''}`)),
    h('h3', { style: { marginTop: '8px' } }, 'Substitutes'), ...bench(S, tid).map(p => h('div', { class: 'mut' }, `${p.number ?? ''}  ${p.name}${p.status === 'on' ? ' ↑' : ''}`)), S.teams[tid].coach ? h('div', { class: 'mut', style: { marginTop: '6px' } }, 'Coach: ' + S.teams[tid].coach) : null);
  const rows = Object.values(S.stats.rows).filter(r => r.A != null || r.B != null);
  const st = rows.length ? h('div', { class: 'card' }, h('h3', {}, 'Statistics'), h('table', {}, h('tbody', {}, rows.map(r => h('tr', {}, h('td', { style: { textAlign: 'right' } }, r.dA), h('td', { style: { textAlign: 'center' } }, r.label), h('td', { style: { textAlign: 'left' } }, r.dB)))))) : null;
  $('#body').replaceChildren(tl, h('div', { class: 'grid g2' }, lu('A'), lu('B')), st);
  $('#stamp').textContent = 'updated ' + new Date().toLocaleTimeString();
}
