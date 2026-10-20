// Public full scorecard (for a venue screen / phone). Shows the PUBLISHED state, so it obeys hold & delay.
import { h, $, Live, matchIdFromPath, setConn } from './common.js';
import { inningsCard } from './cardview.js';
const id = matchIdFromPath();
new Live(id, 'pub', (p) => {
  const S = p.state; document.title = (S.title || 'Scorecard') + ' · GoScore'; $('#title').textContent = S.title || 'Scorecard';
  const c = S.current;
  $('#head').replaceChildren(
    h('div', {}, h('div', { class: 'big' }, c ? `${c.batting.short} ${c.score}` : `${S.teams.A.short} v ${S.teams.B.short}`), h('div', { class: 'ov' }, c ? `${c.overs} overs` : S.venue || '')),
    h('div', {}, S.result && S.result.text ? h('b', {}, S.result.text) : (c ? c.status_line : S.status.replace('_', ' '))),
    S.toss && S.toss.winner ? h('div', { class: 'mut' }, `${S.teams[S.toss.winner].name} won the toss, chose to ${S.toss.decision}`) : null);
  $('#body').replaceChildren(...[...S.innings].reverse().map(i => inningsCard(S, i)));
  $('#stamp').textContent = 'updated ' + new Date().toLocaleTimeString();
}, (s) => setConn($('#conn'), s));
