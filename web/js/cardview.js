// Scorecard rendering shared by the scorer console and the venue scorecard page.
import { h } from './common.js';

export function battingTable(inn, { showYet = true } = {}) {
  const rows = inn.batters.filter(b => showYet || b.status !== 'yet_to_bat').map(b => h('tr', { class: (b.on_strike ? 'on-strike ' : '') + (b.status === 'out' ? 'out' : '') },
    h('td', {}, b.name + (b.tag || '') + (b.on_strike ? ' *' : ''), h('div', { class: 'mute small' }, b.status_text)),
    h('td', {}, b.status === 'yet_to_bat' ? '' : b.runs), h('td', {}, b.status === 'yet_to_bat' ? '' : b.balls),
    h('td', {}, b.status === 'yet_to_bat' ? '' : b.fours), h('td', {}, b.status === 'yet_to_bat' ? '' : b.sixes),
    h('td', {}, b.status === 'yet_to_bat' ? '' : b.sr.toFixed(1))));
  const ex = inn.extras;
  return h('table', {}, h('thead', {}, h('tr', {}, ['Batter', 'R', 'B', '4s', '6s', 'SR'].map(x => h('th', {}, x)))),
    h('tbody', {}, rows,
      h('tr', {}, h('td', {}, 'Extras', h('div', { class: 'mute small' }, `b ${ex.bye}, lb ${ex.legbye}, w ${ex.wide}, nb ${ex.noball}, p ${ex.penalty}`)), h('td', { colspan: 5 }, ex.total)),
      h('tr', {}, h('td', {}, h('b', {}, 'Total')), h('td', { colspan: 5 }, h('b', {}, `${inn.runs}/${inn.wickets} (${inn.overs} ov)`)))));
}
export function bowlingTable(inn) {
  return h('table', {}, h('thead', {}, h('tr', {}, ['Bowler', 'O', 'M', 'R', 'W', 'Econ', 'Wd', 'Nb'].map(x => h('th', {}, x)))),
    h('tbody', {}, inn.bowlers.map(b => h('tr', { class: b.is_current ? 'on-strike' : '' }, h('td', {}, b.name + (b.tag || '') + (b.is_current ? ' •' : '')),
      h('td', {}, b.overs), h('td', {}, b.maidens), h('td', {}, b.runs), h('td', {}, b.wickets), h('td', {}, b.econ.toFixed(2)), h('td', {}, b.wides), h('td', {}, b.noballs)))));
}
export function fowLine(inn) {
  if (!inn.fow.length) return h('span', { class: 'mute' }, 'No wickets yet');
  return h('span', {}, inn.fow.map(f => `${f.wicket}-${f.score} (${f.name}, ${f.over} ov)`).join(', '));
}
export function inningsCard(state, inn) {
  return h('div', { class: 'card' },
    h('h3', {}, `${inn.batting_name} — ${inn.runs}/${inn.wickets} (${inn.overs} ov)`, inn.kind === 'super_over' ? ' · Super Over' : '',
      inn.status === 'completed' ? h('span', { class: 'mute small' }, ` · ${(inn.end_reason || '').replace('_', ' ')}`) : ''),
    h('div', { style: { overflowX: 'auto' } }, battingTable(inn)),
    h('p', { class: 'small' }, h('b', {}, 'Fall of wickets: '), fowLine(inn)),
    h('div', { style: { overflowX: 'auto' } }, bowlingTable(inn)));
}
