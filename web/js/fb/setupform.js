// match setup form ("New match" and "Edit setup").
import { h, select, num, toast, api } from '../common.js';

export const FORMATIONS = ['4-4-2', '4-3-3', '4-2-3-1', '3-5-2', '3-4-3', '4-1-4-1', '4-4-1-1', '4-3-2-1', '5-3-2', '5-4-1', '3-4-2-1', '4-5-1', '3-2-1', '2-3-1', '2-2-2', '3-3', '1-2-1'];
const POS = ['GK', 'DF', 'MF', 'FW'];
const POS_WORD = { gk: 'GK', g: 'GK', keeper: 'GK', goalkeeper: 'GK', df: 'DF', d: 'DF', def: 'DF', defender: 'DF', mf: 'MF', m: 'MF', mid: 'MF', midfielder: 'MF', fw: 'FW', f: 'FW', st: 'FW', fwd: 'FW', forward: 'FW', striker: 'FW', att: 'FW' };

function squadTable(tid, players, onField) {
  const body = h('tbody');
  const row = (p = {}) => {
    const status = p.xi === false ? (p.squad === false ? 'out' : 'sub') : 'xi';
    const tr = h('tr', { 'data-id': p.id || '' },
      h('td', {}, h('input', { class: 'pnum', type: 'number', min: 0, max: 99, value: p.number ?? '', style: { width: '56px' } })),
      h('td', {}, h('input', { class: 'pn', value: p.name || '', placeholder: 'Player name', style: { width: '170px' } })),
      h('td', {}, h('input', { class: 'ps', value: p.short || '', placeholder: 'on-screen name (auto)', style: { width: '120px' } })),
      h('td', {}, select([{ value: '', label: 'Pos…' }, ...POS.map(x => ({ value: x, label: x }))], p.pos || '', { class: 'ppos' })),
      h('td', {}, h('label', { class: 'inline', title: 'Captain' }, h('input', { type: 'checkbox', class: 'pc', checked: !!p.captain, onchange: (e) => { if (e.target.checked) body.querySelectorAll('.pc').forEach(x => { if (x !== e.target) x.checked = false; }); } }), 'C')),
      h('td', {}, select([{ value: 'xi', label: 'Starting XI' }, { value: 'sub', label: 'Substitute' }, { value: 'out', label: 'Not in squad' }], status, { class: 'pst' })),
      h('td', {}, h('button', { class: 'btn sm ghost', type: 'button', title: 'Move up', onclick: () => { if (tr.previousElementSibling) body.insertBefore(tr, tr.previousElementSibling); } }, '↑'),
        h('button', { class: 'btn sm ghost', type: 'button', title: 'Move down', onclick: () => { if (tr.nextElementSibling) body.insertBefore(tr.nextElementSibling, tr); } }, '↓'),
        h('button', { class: 'btn sm ghost', type: 'button', onclick: () => tr.remove() }, 'Missed')));
    body.append(tr);
  };
  players.forEach(row);
  const wrap = h('div', {},
    h('div', { class: 'mut small' }, 'Order matters for the formation graphic: the starting XI is drawn in the order listed (goalkeeper first, then defenders, midfielders, forwards). Use “Sort XI by position” to do it for you.'),
    h('div', { style: { maxHeight: '340px', overflow: 'auto' } }, h('table', {}, h('thead', {}, h('tr', {}, ['#', 'Name', 'Short', 'Pos', 'C', 'Role in match', ''].map(x => h('th', {}, x)))), body)),
    h('div', { class: 'row', style: { marginTop: '6px' } },
      h('button', { class: 'btn sm', type: 'button', onclick: () => row({ xi: [...body.children].filter(t => t.querySelector('.pst').value === 'xi').length < onField() }) }, '+ Add player'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => {
        const t = prompt('Paste the squad, one player per line (first players become the XI, the rest the bench).\nFormat: "9 Harry Kane FW (c)" - number first, position (GK/DF/MF/FW) and (c) for captain are optional.');
        if (!t) return;
        [...body.children].filter(tr => !tr.dataset.id).forEach(tr => tr.remove());
        const have = body.children.length;
        t.split(/\r?\n/).map(s => s.trim()).filter(Boolean).forEach((line, i) => {
          let captain = false, number = '', pos = '';
          if (/\((?:c|capt(?:ain)?)\)/i.test(line)) { captain = true; line = line.replace(/\((?:c|capt(?:ain)?)\)/ig, '').trim(); }
          const mn = line.match(/^#?(\d{1,2})[.)\-\s]+(.*)$/); if (mn) { number = mn[1]; line = mn[2].trim(); }
          const mp = line.match(/^(.*?)[\s,\-–(]+([A-Za-z]+)\)?$/); if (mp && POS_WORD[mp[2].toLowerCase()]) { pos = POS_WORD[mp[2].toLowerCase()]; line = mp[1].trim(); }
          row({ name: line, number: number === '' ? null : +number, pos, captain, xi: have + i < onField() });
        });
      } }, 'Paste list…'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => {
        const order = { GK: 0, DF: 1, MF: 2, FW: 3, '': 4 };
        const rows = [...body.children]; const xi = rows.filter(t => t.querySelector('.pst').value === 'xi');
        const rest = rows.filter(t => !xi.includes(t));
        xi.sort((a, b) => order[a.querySelector('.ppos').value] - order[b.querySelector('.ppos').value]);
        [...xi, ...rest].forEach(t => body.append(t));
      } }, 'Sort XI by position')));
  wrap.read = () => [...body.children].map(tr => {
    const st = tr.querySelector('.pst').value; const n = tr.querySelector('.pnum').value;
    return {
      ...(tr.dataset.id ? { id: tr.dataset.id } : {}), name: tr.querySelector('.pn').value.trim(),
      ...(tr.querySelector('.ps').value.trim() ? { short: tr.querySelector('.ps').value.trim() } : {}),
      number: n === '' ? null : +n, pos: tr.querySelector('.ppos').value, captain: tr.querySelector('.pc').checked,
      xi: st === 'xi', squad: st !== 'out',
    };
  }).filter(p => p.name);
  return wrap;
}

export function setupForm(presets, m) {
  const fb = presets.football;
  m = m || { sport: 'football', title: '', format: { preset: 'league' }, teams: { A: { name: 'Home', players: [] }, B: { name: 'Away', players: [] } }, officials: {}, info: {}, form: {}, h2h: {} };
  const f = m.format || {};
  const base = fb.presets[f.preset || 'league'] || fb.presets.league;
  const val = (k) => (f[k] !== undefined && f[k] !== null ? f[k] : (base[k] !== undefined ? base[k] : fb.defaults[k]));
  const inp = (v, o = {}) => h('input', { value: v ?? '', ...o });
  const title = inp(m.title, { placeholder: 'e.g. Final — Reds v Blues', style: { width: '100%' } });
  const venue = inp(m.venue, { placeholder: 'Stadium' }), date = inp(m.date, { type: 'date' });
  const info = m.info || {};
  const comp = inp(info.competition, { placeholder: 'Competition e.g. Premier League' }), stage = inp(info.stage, { placeholder: 'Stage e.g. Matchday 12' });
  const ko = inp(info.kickoff, { placeholder: 'Kick-off e.g. 19:30' }), att = inp(info.attendance, { placeholder: 'Attendance' }), wx = inp(info.weather, { placeholder: 'Weather e.g. 24°C, clear' });
  const preset = select(Object.keys(fb.presets).map(k => ({ value: k, label: fb.presets[k].label })), f.preset || 'league');
  const half = inp(val('half_min'), { type: 'number', min: 1, max: 60, style: { width: '70px' } });
  const et = inp(val('et_min'), { type: 'number', min: 1, max: 30, style: { width: '70px' } });
  const exT = h('input', { type: 'checkbox', checked: !!val('extra_time') }), so = h('input', { type: 'checkbox', checked: !!val('shootout') });
  const onf = inp(val('on_field'), { type: 'number', min: 3, max: 11, style: { width: '70px' } });
  const minp = inp(val('min_players'), { type: 'number', min: 1, max: 11, style: { width: '70px' } });
  const subs = inp(val('subs_max'), { type: 'number', min: 0, max: 99, style: { width: '70px' } });
  const wins = inp(val('windows_max'), { type: 'number', min: 0, max: 99, style: { width: '70px' } });
  const ret = h('input', { type: 'checkbox', checked: !!val('return_subs') }), conc = h('input', { type: 'checkbox', checked: val('concussion_subs') !== false });
  const etSub = h('input', { type: 'checkbox', checked: val('et_extra_sub') !== false });
  const agg0 = val('aggregate');
  const aggOn = h('input', { type: 'checkbox', checked: !!agg0 }), aggA = inp(agg0 ? agg0.A : 0, { type: 'number', min: 0, style: { width: '60px' } }), aggB = inp(agg0 ? agg0.B : 0, { type: 'number', min: 0, style: { width: '60px' } });
  preset.onchange = () => {
    const b = fb.presets[preset.value] || {}; const g = (k) => (b[k] !== undefined ? b[k] : fb.defaults[k]);
    half.value = g('half_min'); et.value = g('et_min'); exT.checked = !!g('extra_time'); so.checked = !!g('shootout'); onf.value = g('on_field'); minp.value = g('min_players');
    subs.value = g('subs_max'); wins.value = g('windows_max'); ret.checked = !!g('return_subs'); conc.checked = g('concussion_subs') !== false; etSub.checked = g('et_extra_sub') !== false;
    aggOn.checked = !!g('aggregate');
  };
  const dl = h('datalist', { id: 'formations' }, FORMATIONS.map(x => h('option', { value: x })));
  const team = (tid, label) => {
    const t = (m.teams || {})[tid] || { name: label, players: [] };
    const name = inp(t.name, { placeholder: label + ' team name' }), short = inp(t.short, { placeholder: 'ABC', size: 5, maxlength: 4 });
    const c1 = inp(t.color || (tid === 'A' ? '#1f6feb' : '#d4351c'), { type: 'color' }), c2 = inp(t.color2 || '#ffffff', { type: 'color' });
    const formation = inp(t.formation || '4-4-2', { list: 'formations', size: 8 }), coach = inp(t.coach, { placeholder: 'Head coach' });
    let logoPending = false;
    const logo = inp(t.logo, { placeholder: 'Badge image URL or local image (optional)', style: { width: '260px' } });
    const logoFile = h('input', { type: 'file', accept: 'image/*', style: { display: 'none' }, onchange: (e) => {
      const file = e.target.files && e.target.files[0]; if (!file) return;
      if (!file.type.startsWith('image/')) { toast('Choose an image file.', 'error'); e.target.value = ''; return; }
      if (file.size > 2 * 1024 * 1024) { toast('Logo image must be 2 MB or smaller.', 'error'); e.target.value = ''; return; }
      logoPending = true;
      const reader = new FileReader();
      reader.onload = async () => {
        if (typeof reader.result !== 'string') { logoPending = false; return; }
        try { const result = await api('POST', '/api/logos', { data: reader.result }); logo.value = result.url; toast('Logo uploaded. Save the setup to apply it.', 'success'); }
        catch (err) { toast('Could not upload logo: ' + err.message, 'error'); }
        finally { logoPending = false; }
      };
      reader.onerror = () => { logoPending = false; toast('Could not read that image file.', 'error'); };
      reader.readAsDataURL(file);
    } });
    const logoPick = h('button', { class: 'btn sm ghost', type: 'button', onclick: () => logoFile.click() }, 'Choose local image…');
    const squad = squadTable(tid, t.players || [], () => +onf.value || 11);
    const box = h('div', { class: 'card' }, h('h3', {}, label + ' team'),
      h('div', { class: 'row' }, name, 'short', short, 'colour', c1, 'text', c2, 'formation', formation), h('div', { class: 'row' }, coach, logo), h('div', { class: 'row' }, logoPick, logoFile), squad);
    box.read = () => { if (logoPending) throw new Error('Wait for the logo upload to finish before saving.'); return ({ name: name.value.trim() || label, short: short.value.trim().toUpperCase() || undefined, color: c1.value, color2: c2.value, formation: formation.value.trim() || '4-4-2', coach: coach.value.trim(), logo: logo.value.trim(), players: squad.read() }); };
    return box;
  };
  const tA = team('A', 'Home'), tB = team('B', 'Away');
  const off = m.officials || {};
  const O = { referee: inp(off.referee, { placeholder: 'Referee' }), ar1: inp(off.ar1, { placeholder: 'Assistant referee 1' }), ar2: inp(off.ar2, { placeholder: 'Assistant referee 2' }), fourth: inp(off.fourth, { placeholder: 'Fourth official' }), var: inp(off.var, { placeholder: 'VAR' }), avar: inp(off.avar, { placeholder: 'Assistant VAR' }) };
  const form = m.form || {}, h2 = m.h2h || {};
  const fA = inp(form.A, { placeholder: 'W W D L W', size: 10 }), fB = inp(form.B, { placeholder: 'L W W D W', size: 10 });
  const hA = inp(h2.A ?? 0, { type: 'number', min: 0, style: { width: '60px' } }), hD = inp(h2.D ?? 0, { type: 'number', min: 0, style: { width: '60px' } }), hB = inp(h2.B ?? 0, { type: 'number', min: 0, style: { width: '60px' } });
  const root = h('div', {}, dl,
    h('div', { class: 'card' }, h('h3', {}, 'Match'), title,
      h('div', { class: 'row' }, venue, date, ko), h('div', { class: 'row' }, comp, stage), h('div', { class: 'row' }, att, wx)),
    h('div', { class: 'card' }, h('h3', {}, 'Format & rules'),
      h('div', { class: 'row' }, 'Preset', preset, 'Half length', half, 'min', 'Players on pitch', onf, 'Abandon if fewer than', minp),
      h('div', { class: 'row' }, h('label', { class: 'inline' }, exT, ' Extra time if level'), 'ET period', et, 'min', h('label', { class: 'inline' }, so, ' Penalty shoot-out if still level')),
      h('div', { class: 'row' }, 'Substitutions max', subs, 'Opportunities', wins, h('label', { class: 'inline' }, etSub, ' +1 sub in extra time'), h('label', { class: 'inline' }, conc, ' Concussion subs'), h('label', { class: 'inline' }, ret, ' Return substitutions (youth / grassroots)')),
      h('div', { class: 'row' }, h('label', { class: 'inline' }, aggOn, ' Two-legged tie — goals from earlier leg(s): '), aggA, '–', aggB, h('span', { class: 'mut small' }, '(home – away of THIS match)')),
      h('div', { class: 'mut small' }, 'Substitution limits and extra time are competition rules: the scorer can still override them with “Allow anyway”. Match laws (a sent-off player cannot be replaced, etc.) are always enforced.')),
    tA, tB,
    h('div', { class: 'card' }, h('h3', {}, 'Match officials'), h('div', { class: 'row' }, O.referee, O.ar1, O.ar2), h('div', { class: 'row' }, O.fourth, O.var, O.avar)),
    h('div', { class: 'card' }, h('h3', {}, 'Preview data (for the pre-match graphic)'),
      h('div', { class: 'row' }, 'Recent form (home)', fA, 'away', fB), h('div', { class: 'row' }, 'Head-to-head wins: home', hA, 'draws', hD, 'away', hB)));
  root.value = () => ({
    sport: 'football', title: title.value.trim() || 'Match', venue: venue.value.trim(), date: date.value,
    format: {
      preset: preset.value, label: fb.presets[preset.value].label, half_min: num(half.value, 45), et_min: num(et.value, 15), extra_time: exT.checked, shootout: so.checked,
      on_field: num(onf.value, 11), min_players: num(minp.value, 7), subs_max: num(subs.value, 5), windows_max: num(wins.value, 3), et_extra_sub: etSub.checked,
      concussion_subs: conc.checked, return_subs: ret.checked, aggregate: aggOn.checked ? { A: num(aggA.value), B: num(aggB.value) } : null,
    },
    teams: { A: tA.read(), B: tB.read() },
    officials: Object.fromEntries(Object.entries(O).map(([k, v]) => [k, v.value.trim()])),
    info: { competition: comp.value.trim(), stage: stage.value.trim(), kickoff: ko.value.trim(), attendance: att.value.trim(), weather: wx.value.trim() },
    form: { A: fA.value.trim(), B: fB.value.trim() }, h2h: { A: num(hA.value), D: num(hD.value), B: num(hB.value) },
  });
  return root;
}
