import { api, h, $, toast, modal, confirmBox, ago, select } from './common.js';
import { setupForm } from './setupform.js';
import { setupForm as fbSetupForm } from './fb/setupform.js';

let presets = null, info = null;
async function load() {
  try {
    if (!presets) presets = await api('GET', '/api/presets');
    info = await api('GET', '/api/info');
    const d = await api('GET', '/api/matches');
    const settings = await api('GET', '/api/settings');
    render(d, settings);
    $('#conn').className = 'conn ok'; $('#conn').textContent = '● SERVER OK';
  } catch (e) { $('#conn').className = 'conn bad'; $('#conn').textContent = '● SERVER UNREACHABLE'; }
}
function link(text, href, kind = '') { return h('a', { class: 'btn sm ' + kind, href, target: '_blank' }, text); }
function render(d, settings) {
  const list = $('#list'); list.replaceChildren();
  if (!d.matches.length) list.append(h('div', { class: 'card' }, 'No matches yet. Click “New match”.'));
  for (const m of d.matches) {
    const live = m.id === d.live_match_id;
    list.append(h('div', { class: 'card' },
      h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, (m.sport === 'football' ? '' : 'Cricket ') + m.title), live ? h('span', { class: 'badge ok' }, 'ON AIR (live feed)') : null, h('span', { class: 'sp' }), h('span', { class: 'mute small' }, m.format + ' · ' + m.status.replace('_', ' '))),
      h('div', { class: 'mute' }, `${m.teams.A} v ${m.teams.B}`, m.score ? (m.sport === 'football' ? ` · ${m.score} · ${m.phase}` : ` · ${m.score} (${m.overs})`) : '', m.result ? ` · ${m.result}` : ''),
      h('div', { class: 'row', style: { marginTop: '8px' } },
        link('Score', `/score/${m.id}`, 'primary'), link('Production', `/control/${m.id}`), link(m.sport === 'football' ? 'Match page' : 'Scorecard', `/scorecard/${m.id}`), link('Overlay', `/overlay/${m.id}`), link('Setup', `/setup/${m.id}`),
        live ? null : h('button', { class: 'btn sm', onclick: async () => { await api('POST', `/api/matches/${m.id}/go-live`, {}); toast('Live feed now points at this match', 'ok'); load(); } }, 'Make live feed'),
        h('a', { class: 'btn sm', href: `/api/matches/${m.id}/export` }, 'Export'),
        h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox(`Delete “${m.title}”? (a copy is kept in data/deleted)`, 'Delete')) { await api('DELETE', `/api/matches/${m.id}`); load(); } } }, 'Delete'))));
  }
  const base = `http://${info.ips[0] || 'localhost'}:${info.port}`;
  const net = $('#net'); net.replaceChildren(
    h('p', {}, 'OBS Browser Source URLs (1920×1080, “live” always follows the match marked ON AIR):'),
    ...[['Overlay (all graphics)', '/overlay/live'], ['Scorecard / match page', '/scorecard/live'], ['JSON feed', '/feed/live.json'], ['XML feed', '/feed/live.xml'], ['Single text value, e.g. score', '/feed/live/text/score.txt'], ['Football: live clock text', '/feed/live/text/clock.txt']].map(([n, p]) =>
      h('div', { class: 'row' }, h('span', { style: { width: '230px' } }, n), h('code', {}, base + p), h('button', { class: 'btn sm', onclick: () => { navigator.clipboard?.writeText(base + p); toast('Copied', 'ok', 1200); } }, 'Copy'))),
    h('p', { class: 'mute small' }, 'Data files for OBS “Text (read from file)”: ', h('code', {}, info.output_dir + '/live/text/*.txt'), ' (also scoreboard.json / scoreboard.xml / csv/*.csv)'),
    h('div', { class: 'row' }, h('label', { class: 'inline' }, 'Overlay delay (seconds, to match your stream delay): ',
      h('input', { type: 'number', min: 0, max: 30, step: 0.5, value: settings.publish_delay || 0, style: { width: '70px' }, onchange: async (e) => { await api('POST', '/api/settings', { publish_delay: +e.target.value }); toast('Delay saved', 'ok'); } }))),
    info.pin_required ? h('p', { class: 'small' }, 'PIN protection is ON.') : h('p', { class: 'mute small' }, 'Tip: start with --pin 1234 so nobody else on the network can change scores.'));
}
$('#new').onclick = async () => {
  if (!presets) presets = await api('GET', '/api/presets');
  const pick = (sport) => {
    const form = sport === 'football' ? fbSetupForm(presets, null) : setupForm(presets, null);
    modal(sport === 'football' ? 'New football match' : 'New cricket match', form, { wide: true, buttons: [{ label: 'Cancel' }, { label: 'Create match', kind: 'primary', onclick: async () => {
      try { const r = await api('POST', '/api/matches', { ...form.value(), sport }); location.href = `/score/${r.id}`; } catch (e) { toast(e.message, 'bad'); return false; } } }] });
  };
  const m = modal('Which sport?', h('div', { class: 'row' },
    h('button', { class: 'btn primary big3', style: { flex: 1, padding: '24px' }, onclick: () => { m.close(); pick('cricket'); } }, h('img', { class: 'ui-icon', src: '/static/assets/icons/cricket.svg', alt: '' }), 'Cricket'),
    h('button', { class: 'btn primary big3', style: { flex: 1, padding: '24px' }, onclick: () => { m.close(); pick('football'); } }, h('img', { class: 'ui-icon', src: '/static/assets/icons/football.svg', alt: '' }), 'Football')));
};
$('#imp').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try { const doc = JSON.parse(await f.text()); await api('POST', '/api/import', doc); toast('Imported', 'ok'); load(); } catch (err) { toast('Import failed: ' + err.message, 'bad'); }
};
load(); setInterval(load, 5000);
