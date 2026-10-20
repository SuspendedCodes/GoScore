// Match setup form (used for "New match" and "Edit setup").
import { h, select, num, toast, api, ROLE_ONE } from './common.js';

const PRESET_ORDER = ['t20', 't10', 'odi', 'list_a_40', 'hundred', 'custom', 'multi_day'];

function playerRows(tid, players, onPaste) {
  const body = h('tbody');
  const add = (p = {}) => {
    const tr = h('tr', { 'data-id': p.id || '' },
      h('td', {}, h('span', { class: 'mute small' }, p.id || 'new')),
      h('td', {}, h('input', { class: 'pn', value: p.name || '', placeholder: 'Player name', style: { width: '160px' } })),
      h('td', {}, h('input', { class: 'ps', value: p.short || '', placeholder: 'short (auto)', style: { width: '80px' } })),
      h('td', {}, select(Object.entries(ROLE_ONE).map(([v, l]) => ({ value: v, label: v ? l : 'Role…' })), p.role || '', { class: 'pr' })),
      h('td', {}, h('label', { class: 'inline', title: 'Captain (c)' }, h('input', { type: 'checkbox', class: 'pc', checked: !!p.captain, onchange: (e) => { if (e.target.checked) body.querySelectorAll('.pc').forEach(x => { if (x !== e.target) x.checked = false; }); } }), 'C')),
      h('td', {}, h('label', { class: 'inline', title: 'Wicketkeeper †' }, h('input', { type: 'checkbox', class: 'pw', checked: !!p.wk, onchange: (e) => { if (e.target.checked) body.querySelectorAll('.pw').forEach(x => { if (x !== e.target) x.checked = false; }); } }), 'WK')),
      h('td', {}, h('label', { class: 'inline' }, h('input', { type: 'checkbox', class: 'pxi', checked: p.xi !== false }), 'XI')),
      h('td', {}, h('button', { class: 'btn sm ghost', type: 'button', onclick: () => tr.remove() }, 'Missed')));
    body.append(tr);
  };
  players.forEach(add);
  const wrap = h('div', {},
    h('div', { style: { maxHeight: '300px', overflow: 'auto' } }, h('table', {}, h('thead', {}, h('tr', {}, ['ID', 'Name', 'Short', 'Role', 'C', 'WK', '', ''].map(x => h('th', {}, x)))), body)),
    h('div', { class: 'row', style: { marginTop: '6px' } },
      h('button', { class: 'btn sm', type: 'button', onclick: () => add({ xi: body.children.length < 11 }) }, '+ Add player'),
      h('button', { class: 'btn sm', type: 'button', onclick: () => {
        const t = prompt('Paste player names, one per line (first 11 become the XI, the rest the bench).\nOptional role at the end: "Name - bowler", "Name (batter)", "Name, all-rounder" (or bat / bowl / ar). Add (c) for captain and (wk) or † for keeper:');
        if (!t) return;
        const names = t.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        [...body.children].filter(tr => !tr.dataset.id).forEach(tr => tr.remove());
        const have = body.children.length;
        const roleOfText = (x) => /^(bat|batter|batsman)$/i.test(x) ? 'batter' : /^(bowl|bowler)$/i.test(x) ? 'bowler' : /^(ar|all.?rounder)$/i.test(x) ? 'allrounder' : '';
        names.forEach((n, i) => {
          n = n.replace(/^\d+[.)]\s*/, ''); let role = ''; let captain = false, wk = false;
          if (/\((?:[^)]*\b)?(?:c|capt(?:ain)?)\b[^)]*\)/i.test(n)) captain = true;
          if (/\((?:[^)]*\b)?wk\b[^)]*\)|†/i.test(n)) wk = true;
          n = n.replace(/\((?:c|capt(?:ain)?|wk|vc)(?:\s*[,&]\s*(?:c|wk))?\)|†/gi, '').trim();
          const mm = n.match(/^(.*?)\s*(?:[-–,]|\()\s*([A-Za-z -]+?)\)?$/);
          if (mm && roleOfText(mm[2].trim())) { n = mm[1].trim(); role = roleOfText(mm[2].trim()); }
          add({ name: n, role, captain, wk, xi: have + i < 11 });
        });
      } }, 'Paste list…')));
  wrap.read = () => [...body.children].map(tr => ({
    ...(tr.dataset.id ? { id: tr.dataset.id } : {}),
    name: tr.querySelector('.pn').value.trim(), ...(tr.querySelector('.ps').value.trim() ? { short: tr.querySelector('.ps').value.trim() } : {}),
    xi: tr.querySelector('.pxi').checked, role: tr.querySelector('.pr').value, captain: tr.querySelector('.pc').checked, wk: tr.querySelector('.pw').checked,
  })).filter(p => p.name);
  return wrap;
}

export function setupForm(presets, m) {
  m = m || { title: '', format: { preset: 't20' }, teams: { A: { name: 'Team A', players: [] }, B: { name: 'Team B', players: [] } }, toss: {} };
  const f = m.format || {};
  const base = presets.presets[f.preset || 't20'] || presets.presets.t20;
  const val = (k, d) => (f[k] !== undefined && f[k] !== null ? f[k] : (base[k] !== undefined ? base[k] : presets.defaults[k] ?? d));

  const title = h('input', { value: m.title || '', placeholder: 'e.g. Finals — Eagles v Lions', style: { width: '100%' } });
  const venue = h('input', { value: m.venue || '', placeholder: 'Venue (optional)' });
  const date = h('input', { type: 'date', value: m.date || '' });
  const preset = select(PRESET_ORDER.map(k => ({ value: k, label: presets.presets[k].label })), f.preset || 't20');
  const overs = h('input', { type: 'number', min: 1, value: val('overs', 20) });
  const bpo = h('input', { type: 'number', min: 1, max: 10, value: val('balls_per_over', 6) });
  const free = h('input', { type: 'checkbox', checked: val('free_hit', true) !== false });
  const quota = h('input', { value: f.max_overs_per_bowler === undefined ? 'auto' : (f.max_overs_per_bowler === null ? 'none' : f.max_overs_per_bowler), style: { width: '80px' } });
  const wl = h('input', { value: f.wickets_limit == null ? 'auto' : f.wickets_limit, style: { width: '80px' } });
  const consec = h('input', { type: 'checkbox', checked: !!f.allow_consecutive_overs });
  const so = h('input', { type: 'checkbox', checked: (f.super_over?.enabled ?? true) !== false });
  const wpen = h('input', { type: 'number', min: 0, max: 5, value: val('wide_penalty', 1) });
  const npen = h('input', { type: 'number', min: 0, max: 5, value: val('noball_penalty', 1) });
  const ppInput = h('input', { style: { width: '100%' }, placeholder: 'Powerplay:1-6; Powerplay 2:7-15', value: (val('powerplays', []) || []).map(p => `${p.name}:${p.from_over}-${p.to_over}`).join('; ') });
  const ips = select([{ value: 1, label: '1 innings a side (limited overs)' }, { value: 2, label: '2 innings a side (multi-day)' }], f.innings_per_side || base.innings_per_side || 1);
  const dflt = (v, d) => (v === undefined || v === null ? d : v);
  const days = h('input', { type: 'number', min: 1, max: 30, value: dflt(f.days, ''), style: { width: '70px' }, placeholder: 'e.g. 2' });
  const opd = h('input', { type: 'number', min: 1, max: 200, value: dflt(f.overs_per_day, 90), style: { width: '70px' } });
  const nba = h('input', { type: 'number', min: 1, max: 200, value: dflt(f.new_ball_after, 80), style: { width: '70px' } });
  const mdRow = h('div', { class: 'row' }, h('b', {}, 'Multi-day:'), h('label', { class: 'inline', title: 'Used for the follow-on rule (Law 14.1: 200 runs / 5+ days, 150 / 3-4 days, 100 / 2 days, 75 / 1 day)' }, 'Days of play ', days),
    h('label', { class: 'inline' }, 'Overs per day ', opd), h('label', { class: 'inline' }, 'New ball after (overs) ', nba), h('span', { class: 'mute small' }, 'Shown on the scorebug as OVERS LEFT and NEW BALL. Clear a box to hide it.'));
  const showMd = () => { mdRow.style.display = +ips.value === 2 ? '' : 'none'; };
  const display = select([{ value: 'overs', label: 'Show overs (12.3)' }, { value: 'balls', label: 'Show balls (e.g. 100-ball)' }], f.display || base.display || 'overs');

  preset.addEventListener('change', () => {
    const b = presets.presets[preset.value];
    overs.value = b.overs ?? ''; bpo.value = b.balls_per_over; free.checked = b.free_hit !== false;
    ips.value = b.innings_per_side || 1; display.value = b.display || 'overs'; showMd();
    quota.value = b.max_overs_per_bowler === undefined ? 'auto' : (b.max_overs_per_bowler === null ? 'none' : b.max_overs_per_bowler);
    ppInput.value = (b.powerplays || []).map(p => `${p.name}:${p.from_over}-${p.to_over}`).join('; ');
  });

  ips.addEventListener('change', showMd); showMd();

  const teamBox = (tid, color) => {
    const t = m.teams[tid] || { name: 'Team ' + tid, players: [] };
    const name = h('input', { value: t.name || '', placeholder: 'Team name' });
    const short = h('input', { value: t.short || '', placeholder: 'ABC', style: { width: '70px' }, maxlength: 5 });
    const col = h('input', { type: 'color', value: t.color || color });
    let logoPending = false;
    const logo = h('input', { value: t.logo || '', placeholder: 'Logo image URL or local image (optional)', style: { width: '100%' } });
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
    const pl = playerRows(tid, t.players || []);
    const el = h('div', { class: 'card' }, h('h3', {}, 'Team ' + tid),
      h('div', { class: 'row' }, name, short, col), h('label', {}, 'Logo'), logo, h('div', { class: 'row' }, logoPick, logoFile), h('label', {}, 'Players (XI = batting & bowling pool; bench = impact/substitutes)'), pl);
    el.read = () => { if (logoPending) throw new Error('Wait for the logo upload to finish before saving.'); return ({ name: name.value.trim() || 'Team ' + tid, short: short.value.trim().toUpperCase() || undefined, color: col.value, logo: logo.value.trim() || undefined, players: pl.read() }); };
    return el;
  };
  const tA = teamBox('A', '#1f6feb'), tB = teamBox('B', '#d4351c');
  const toss = m.toss || {};
  const tw = select([{ value: '', label: '— not yet —' }, { value: 'A', label: 'Team A' }, { value: 'B', label: 'Team B' }], toss.winner || '');
  const td = select([{ value: 'bat', label: 'chose to bat' }, { value: 'bowl', label: 'chose to bowl' }], toss.decision || 'bat');

  const el = h('div', {},
    h('label', {}, 'Match title'), title,
    h('div', { class: 'row' }, h('div', {}, h('label', {}, 'Venue'), venue), h('div', {}, h('label', {}, 'Date'), date)),
    h('div', { class: 'card', style: { marginTop: '10px' } }, h('h3', {}, 'Format'),
      h('div', { class: 'row' }, preset, h('label', { class: 'inline' }, 'Overs ', overs), h('label', { class: 'inline' }, 'Balls/over ', bpo), ips),
      mdRow,
      h('div', { class: 'row', style: { marginTop: '8px' } },
        h('label', { class: 'inline' }, free, 'Free hit after no-ball'), h('label', { class: 'inline' }, so, 'Super Over if tied'),
        h('label', { class: 'inline' }, consec, 'Allow consecutive overs (e.g. 100-ball)')),
      h('div', { class: 'row', style: { marginTop: '8px' } },
        h('label', { class: 'inline' }, 'Max overs per bowler ', quota), h('label', { class: 'inline' }, 'Wickets to be all out ', wl),
        h('label', { class: 'inline' }, 'Wide penalty ', wpen), h('label', { class: 'inline' }, 'No-ball penalty ', npen), display),
      h('label', {}, 'Powerplay phases (name:from-to; …)'), ppInput,
      h('p', { class: 'mute small' }, 'Check your competition’s playing conditions for these. "auto" quota = one-fifth of the overs (rounded up). "auto" wickets = players in the XI − 1.')),
    h('div', { class: 'grid g2', style: { marginTop: '10px' } }, tA, tB),
    h('div', { class: 'row', style: { marginTop: '10px' } }, h('b', {}, 'Toss:'), tw, td));

  el.value = () => {
    const parsePP = ppInput.value.split(';').map(s => s.trim()).filter(Boolean).map(s => {
      const mm = s.match(/^(.*?):\s*(\d+)\s*-\s*(\d+)$/); return mm ? { name: mm[1].trim() || 'Powerplay', from_over: +mm[2], to_over: +mm[3] } : null;
    }).filter(Boolean);
    const q = quota.value.trim().toLowerCase();
    const w = wl.value.trim().toLowerCase();
    return {
      title: title.value.trim() || 'Match', venue: venue.value.trim() || null, date: date.value || null,
      format: {
        preset: preset.value, overs: ips.value == 2 ? null : num(overs.value, 20), balls_per_over: num(bpo.value, 6), free_hit: free.checked,
        innings_per_side: +ips.value, ...(+ips.value === 2 ? { days: num(days.value, null) || null, overs_per_day: num(opd.value, null) || null, new_ball_after: num(nba.value, null) || null } : {}), allow_consecutive_overs: consec.checked, display: display.value,
        max_overs_per_bowler: q === 'auto' || q === '' ? 'auto' : (q === 'none' || q === '0' ? null : num(q)),
        wickets_limit: w === 'auto' || w === '' ? null : num(w), wide_penalty: num(wpen.value, 1), noball_penalty: num(npen.value, 1),
        powerplays: parsePP, super_over: { enabled: so.checked, overs: 1, wickets: 2 },
      },
      teams: { A: tA.read(), B: tB.read() }, toss: tw.value ? { winner: tw.value, decision: td.value } : {},
    };
  };
  return el;
}
