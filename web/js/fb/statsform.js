// Manual statistics entry (NO stat scorer): the producer types numbers, they are stored as `stats_set` events
// (an override layer) and shown on the stats graphics whenever the producer chooses.
import { h, select, toast, uid } from '../common.js';

/**
 * statsPanel({ id, getState, presets, post })
 *   post(ev) -> Promise<result|null>   posts an event (the page decides about versions / force handling)
 */
export function statsPanel({ getState, catalog, post }) {
  const root = h('div', {});
  let mode = 'team', ptid = 'A', ppid = '';
  const srcTag = (s) => s === 'auto' ? 'auto (from events)' : s === 'derived' ? 'calculated' : s === 'manual' ? 'typed' : '';
  function build() {
    const S = getState(); if (!S) return;
    const kids = [];
    kids.push(h('div', { class: 'seg' },
      h('button', { type: 'button', class: mode === 'team' ? 'on' : '', onclick: () => { mode = 'team'; build(); } }, 'Team statistics'),
      h('button', { type: 'button', class: mode === 'player' ? 'on' : '', onclick: () => { mode = 'player'; build(); } }, 'Player statistics')));
    kids.push(h('div', { class: 'mut small', style: { margin: '6px 0' } }, 'Type the numbers you want on screen — nothing is counted for you except goals, cards, substitutions and minutes played (taken from the match log). Leave a box empty to show “–” (or the automatic value). Possession: type one team and the other is filled with 100 − it.'));
    if (mode === 'team') kids.push(teamTable(S)); else kids.push(playerTable(S));
    root.replaceChildren(...kids);
  }
  function teamTable(S) {
    const A = S.teams.A, B = S.teams.B, rows = S.stats.rows;
    const inputs = [];
    const tb = h('tbody');
    let group = '';
    for (const def of catalog.team_stats) {
      if (def.group !== group) { group = def.group; tb.append(h('tr', {}, h('th', { colspan: 5, style: { textAlign: 'left', paddingTop: '10px' } }, group))); }
      const r = rows[def.key];
      const cell = (tid) => {
        const val = r['src' + tid] === 'manual' ? r[tid] : '';
        const el = h('input', { type: 'number', step: def.kind === 'dec' ? '0.01' : '1', min: 0, max: def.kind === 'pct' ? 100 : undefined, value: val, placeholder: r[tid] != null ? String(r['d' + tid]).replace('%', '') : '', style: { width: '90px' } });
        el.dataset.team = tid; el.dataset.key = def.key; el.dataset.orig = val === '' ? '' : String(val); el.oninput = () => el.classList.toggle('chg', el.value !== el.dataset.orig);
        inputs.push(el); return el;
      };
      tb.append(h('tr', {}, h('td', {}, def.label + (def.kind === 'pct' ? ' (%)' : '')), h('td', {}, cell('A')), h('td', {}, cell('B')),
        h('td', { class: 'mut small' }, [srcTag(r.srcA), srcTag(r.srcB)].filter(Boolean).filter((x, i, a) => a.indexOf(x) === i).join(' / ')), h('td', {}, '')));
    }
    const save = h('button', { class: 'btn primary', onclick: async () => {
      const values = { A: {}, B: {} }; let n = 0;
      inputs.forEach(el => { if (el.value !== el.dataset.orig) { values[el.dataset.team][el.dataset.key] = el.value === '' ? null : el.value; n++; } });
      if (!n) { toast('Nothing changed', 'warn'); return; }
      const r = await post({ type: 'stats_set', values }); if (r) { toast(`Saved ${n} value${n > 1 ? 's' : ''}`, 'ok'); }
    } }, 'Save statistics');
    const warn = S.stats.warnings.length ? h('div', { class: 'alert warn' }, 'Warning Check: ' + S.stats.warnings.join(' · ')) : null;
    return h('div', {}, warn, h('div', { style: { overflow: 'auto', maxHeight: '60vh' } }, h('table', {}, h('thead', {}, h('tr', {}, [h('th', {}, 'Statistic'), h('th', {}, A.name), h('th', {}, B.name), h('th', {}, 'Source'), h('th', {})])), tb)),
      h('div', { class: 'row', style: { marginTop: '8px' } }, save));
  }
  function playerTable(S) {
    const tsel = select([{ value: 'A', label: S.teams.A.name }, { value: 'B', label: S.teams.B.name }], ptid);
    const players = S.teams[ptid].players.filter(p => p.squad);
    if (!players.some(p => p.id === ppid)) ppid = (players[0] || {}).id || '';
    const psel = select(players.map(p => ({ value: p.id, label: `${p.number ?? ''} ${p.name}`.trim() })), ppid);
    tsel.onchange = () => { ptid = tsel.value; ppid = ''; build(); }; psel.onchange = () => { ppid = psel.value; build(); };
    const p = players.find(x => x.id === ppid);
    const body = h('div', {}); const inputs = [];
    if (p) {
      const tb = h('tbody');
      for (const def of catalog.player_stats) {
        const cur = p.stats[def.key]; const manual = cur && cur.src === 'manual';
        const el = h('input', { type: 'number', step: def.kind === 'dec' ? '0.01' : '1', min: 0, value: manual ? cur.v : '', placeholder: cur ? String(cur.v) : '', style: { width: '90px' } });
        el.dataset.key = def.key; el.dataset.orig = manual ? String(cur.v) : ''; el.oninput = () => el.classList.toggle('chg', el.value !== el.dataset.orig); inputs.push(el);
        tb.append(h('tr', {}, h('td', {}, def.label), h('td', {}, el), h('td', { class: 'mut small' }, cur ? srcTag(cur.src) : '')));
      }
      body.append(h('div', { style: { overflow: 'auto', maxHeight: '55vh' } }, h('table', {}, tb)),
        h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn primary', onclick: async () => {
          const values = {}; let n = 0; inputs.forEach(el => { if (el.value !== el.dataset.orig) { values[el.dataset.key] = el.value === '' ? null : el.value; n++; } });
          if (!n) { toast('Nothing changed', 'warn'); return; }
          const r = await post({ type: 'stats_set', player: p.id, values }); if (r) toast(`Saved ${n} value${n > 1 ? 's' : ''} for ${p.name}`, 'ok');
        } }, 'Save player statistics')));
    }
    return h('div', {}, h('div', { class: 'row' }, tsel, psel), body);
  }
  return { el: root, refresh: build };
}
