// Production control: graphics + OBS scene switching. Everything here is a convenience;
// the scorer and the overlay work without it.
import { api, h, $, Live, matchIdFromPath, setConn, toast, select } from './common.js';
import { createObsPanel } from './obspanel.js';

const id = matchIdFromPath();
const PANELS = [['innsum', 'Innings summary'], ['worm', 'Comparison graph'], ['scorecard', 'Scorecard'], ['bowling', 'Bowling'], ['partnership', 'Partnership'], ['fow', 'Fall of wkts'], ['target', 'Target'], ['overs', 'Over by over'],
  ['teams', 'Teams'], ['toss', 'Toss'], ['testsum', 'Match state / day summary'], ['summary', 'Summary'], ['result', 'Result'], ['batter_card', 'Batter card'], ['bowler_card', 'Bowler card'], ['banner', 'Banner']];
let G = null, S = null, settings = { obs: {}, auto_director: {} };
const saveSettings = async (patch) => { settings = await api('POST', '/api/settings', patch); };

// ------------------------------------------------------------------ OBS (shared panel)
const panel = createObsPanel({ box: $('#obsBox'), getSettings: () => settings, saveSettings,
  autoEvents: [['wicket', 'Wicket →'], ['four', 'Four →'], ['six', 'Six →']] });
const seenIds = new Set(); let autoSeen = null;
function autoDirect(S_) {
  const le = S_ && S_.last_event;
  if (!le) return;
  const first = autoSeen === null; autoSeen = true;
  if (seenIds.has(le.id)) return; seenIds.add(le.id);            // undo re-exposes an old event: never re-trigger
  if (first || le.type !== 'ball') return;
  const k = le.wicket ? 'wicket' : le.kind === 'six' ? 'six' : le.kind === 'four' ? 'four' : null;
  if (k) panel.autoFire(k);
}

// ------------------------------------------------------------------ graphics
let gbusy = false;
async function gpatch(p) {
  if (gbusy) return; gbusy = true;
  try { G = await api('POST', `/api/matches/${id}/graphics`, p); renderGfx(); } catch (e) { toast(e.message, 'bad'); } finally { gbusy = false; }
}
async function pop(kind, text) { try { await api('POST', `/api/matches/${id}/graphics/trigger`, { kind, text }); } catch (e) { toast(e.message, 'bad'); } }
function tgl(label, on, fn, extra = '') { return h('span', { class: 'tgl ' + (on ? 'on ' : '') + extra, role: 'switch', 'aria-checked': on ? 'true' : 'false', tabindex: 0, onclick: (e) => { fn(); e.currentTarget.blur(); }, onkeydown: (e) => { if (e.key === 'Enter') { e.stopPropagation(); e.preventDefault(); if (!e.repeat) fn(); } } }, (on ? '● ' : '○ ') + label); }
function renderGfx() {
  const box = $('#gfxBox'); if (!G) return;
  const inn = S && S.innings[S.current_innings ?? S.innings.length - 1];
  const players = S ? [...(inn ? inn.batters.filter(b => b.status !== 'yet_to_bat').map(b => ({ value: b.id, label: b.name })) : []), ...(inn ? inn.bowlers.map(b => ({ value: b.id, label: b.name })) : [])] : [];
  const cp = select([{ value: '', label: 'Current striker / bowler' }, ...players], G.card_player || ''); cp.onchange = () => gpatch({ card_player: cp.value || null });
    const ban = h('input', { type: 'text', value: G.banner.text || '', placeholder: 'Banner text e.g. Drinks break', size: 28 });
  const pos = select([{ value: 'bottom', label: 'Bottom' }, { value: 'top', label: 'Top' }], G.position); pos.onchange = () => gpatch({ position: pos.value });
  const sc = h('input', { type: 'number', step: '0.05', min: '0.5', max: '1.5', value: G.scale, style: { width: '80px' } }); sc.onchange = () => gpatch({ scale: +sc.value || 1 });
  const targetMode = select([{ value: 'runs', label: 'Runs required' }, { value: 'wickets', label: 'Wickets required' }, { value: 'both', label: 'Both teams’ requirements' }], G.target_display || 'runs'); targetMode.onchange = () => gpatch({ target_display: targetMode.value });
  box.replaceChildren(
    h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Graphics'), h('span', { class: 'sp' }),
      tgl(G.hold ? 'HOLD — overlay frozen (H)' : 'Hold overlay (H)', G.hold, () => gpatch({ hold: !G.hold }), 'hold')),
    h('div', { class: 'mut' }, 'Hold freezes everything the audience sees (overlay, files, feeds) while the scorer keeps scoring — release to catch up instantly.'),
    h('h3', {}, 'Always on'), h('div', { class: 'tg' }, tgl('Scorebug', G.scorebug, () => gpatch({ scorebug: !G.scorebug })), h('span', { class: 'row' }, 'Position', pos, 'Size', sc)),
    h('h3', {}, 'Panels (full-screen / side)'), h('div', { class: 'tg' }, PANELS.filter(([k]) => k !== 'testsum' || (S && S.play)).map(([k, l]) => tgl(l, G.panels[k], () => togglePanel(k)))),
    h('div', { class: 'row' }, h('b', {}, 'Panels show:'), h('div', { class: 'seg' }, [['', 'Live innings'], ...(S ? S.innings.map((x, i) => [i, `Innings ${i + 1} · ${x.batting_short || x.batting_name}`]) : [])].map(([v, l]) => h('button', { type: 'button', class: (G.scorecard_innings ?? '') === v ? 'on' : '', onclick: () => gpatch({ scorecard_innings: v === '' ? null : v }) }, l))),
      h('span', { class: 'mut' }, 'scorecard / bowling / FoW / over-by-over / summary use this; colours follow the innings shown')),
    h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => gpatch({ panels: Object.fromEntries(PANELS.map(([k]) => [k, false])) }) }, 'Hide all panels'), 'Auto-hide panels after', ttlSel(), 'Card player', cp),
    h('h3', {}, 'Automatic pop-ups'), h('div', { class: 'tg' }, [['four', 'FOUR'], ['six', 'SIX'], ['wicket', 'WICKET'], ['milestone', '50 / 100'], ['free_hit', 'FREE HIT']].map(([k, l]) => tgl(l, G.popups_enabled[k], () => gpatch({ popups_enabled: { [k]: !G.popups_enabled[k] } })))),
    h('h3', {}, 'Fire a pop-up now'), h('div', { class: 'tg' }, [['four', 'FOUR'], ['six', 'SIX'], ['wicket', 'WICKET'], ['fifty', 'FIFTY'], ['hundred', 'HUNDRED'], ['freehit', 'FREE HIT']].map(([k, l]) => h('button', { class: 'btn sm', onclick: () => pop(k, '') }, l))),
    h('div', { class: 'row' }, ban, h('button', { class: 'btn sm primary', onclick: () => gpatch({ banner: { text: ban.value }, panels: { banner: !!ban.value } }) }, 'Show banner'), h('button', { class: 'btn sm', onclick: () => gpatch({ panels: { banner: false } }) }, 'Hide'), h('button', { class: 'btn sm', onclick: () => pop('custom', ban.value) }, 'As pop-up')),
    h('h3', {}, 'Target display'),
    h('div', { class: 'row' }, 'Show during a chase', targetMode),
    h('div', { class: 'row' }, 'Over-by-over panel starts at over', h('input', { type: 'number', min: 1, step: 1, placeholder: 'Last 10 overs', value: G.overs_start ?? '', style: { width: '130px' }, onchange: (e) => gpatch({ overs_start: e.target.value.trim() ? Math.max(1, Math.floor(+e.target.value)) : null }) })),
    h('div', { class: 'mut small' }, 'Leave the over number blank to show the last 10 overs. Enter a number to show that over and the next nine.'),
    h('h3', {}, 'Cricket slideshow panel'),
    h('div', { class: 'mut small' }, 'Use a separate OBS Browser Source for rotating cricket graphics. The slideshow only rotates panels enabled above, so it stays separate from scorebug and event pop-ups.'),
    (() => { const cfg = G.slideshow || { enabled: false, interval: 12, slides: ['innsum', 'scorecard', 'bowling', 'teams', 'summary'] }; const enabled = h('input', { type: 'checkbox', checked: !!cfg.enabled }); const interval = h('input', { type: 'number', min: 5, max: 120, step: 1, value: cfg.interval || 12, style: { width: '76px' } }); const u = `${location.origin}/overlay/${id}?only=panels&slideshow=1`; enabled.onchange = () => gpatch({ slideshow: { ...cfg, enabled: enabled.checked, interval: Math.max(5, Math.min(120, +interval.value || 12)) } }); interval.onchange = () => gpatch({ slideshow: { ...cfg, enabled: enabled.checked, interval: Math.max(5, Math.min(120, +interval.value || 12)) } }); return h('div', { class: 'grp' }, h('div', { class: 'row' }, enabled, 'Enable slideshow', 'Change every', interval, 'seconds', h('button', { class: 'btn sm', onclick: async () => { try { await navigator.clipboard.writeText(u); toast('Slideshow URL copied', 'ok'); } catch { toast('Select the URL and press Ctrl+C', 'bad'); } } }, 'Copy slideshow URL'), h('a', { class: 'btn sm', href: u + '&preview=1', target: '_blank' }, 'Preview')), h('div', { class: 'mut small' }, u)); })(),
    h('h3', {}, 'Broadcast delay'), delayRow());
}
const ttl = { get v() { try { return +(localStorage.getItem('gs_ttl') || 0); } catch { return 0; } }, set v(x) { try { localStorage.setItem('gs_ttl', x); } catch { /* */ } } };
const ttlTimers = {};
function ttlSel() { const s = select([{ value: 0, label: 'never' }, { value: 8, label: '8 s' }, { value: 15, label: '15 s' }, { value: 30, label: '30 s' }, { value: 60, label: '60 s' }], ttl.v); s.onchange = () => { ttl.v = +s.value; }; return s; }
async function togglePanel(k) {
  const on = !G.panels[k]; clearTimeout(ttlTimers[k]);
  await gpatch({ panels: { [k]: on } });
  if (on && ttl.v > 0) ttlTimers[k] = setTimeout(() => { gbusy = false; gpatch({ panels: { [k]: false } }); }, ttl.v * 1000);
}
function delayRow() {
  const d = h('input', { type: 'number', min: 0, max: 60, step: 1, value: settings.publish_delay || 0, style: { width: '70px' } });
  return h('div', { class: 'row' }, 'Delay overlay, files & feeds by', d, 'seconds', h('button', { class: 'btn sm', onclick: () => saveSettings({ publish_delay: Math.max(0, +d.value || 0) }).then(() => toast('Delay set to ' + (settings.publish_delay || 0) + ' s')) }, 'Apply'), h('span', { class: 'mut' }, 'Match your stream delay so graphics don’t spoil the video.'));
}

// ------------------------------------------------------------------ one browser source per cricket graphic
const SOLO = [
  ['bug', 'Scorebug', '1200×180'], ['popups', 'Event pop-ups (four / six / wicket / milestones)', '1100×420'],
  ['innsum', 'Innings summary', '1100×650'], ['worm', 'Innings comparison graph', '1100×500'], ['scorecard', 'Batting scorecard', '1100×800'],
  ['bowling', 'Bowling figures', '1100×650'], ['partnership', 'Partnership', '900×420'], ['fow', 'Fall of wickets', '1000×600'],
  ['target', 'Target / required rate', '1000×250'], ['overs', 'Over-by-over', '1100×500'], ['teams', 'Teams / playing XI', '1100×800'],
  ['toss', 'Toss information', '1000×300'], ['testsum', 'Match state / day summary', '1100×650'],
  ['summary', 'Match summary', '1100×650'], ['result', 'Result', '1100×450'], ['batter_card', 'Batter card', '900×260'],
  ['bowler_card', 'Bowler card', '900×260'], ['banner', 'Banner', '1100×160']
];
function soloBox() {
  const box = h('div', { class: 'card', id: 'soloBox' });
  const sc = h('input', { type: 'number', step: '0.05', min: '0.2', max: '3', value: '1', style: { width: '70px' } });
  const al = select([{ value: 'c', label: 'Centre' }, { value: 'tl', label: 'Top left' }, { value: 'tr', label: 'Top right' }, { value: 'bl', label: 'Bottom left' }, { value: 'br', label: 'Bottom right' }, { value: 't', label: 'Top' }, { value: 'b', label: 'Bottom' }], 'c');
  const fit = h('input', { type: 'checkbox', checked: true });
  const url = (k) => { const q = new URLSearchParams({ panel: k, follow: '1' }); if (!fit.checked) q.set('fit', '0'); if (+sc.value && +sc.value !== 1) q.set('scale', sc.value); if (al.value !== 'c') q.set('align', al.value); return `${location.origin}/overlay/${id}?${q}`; };
  const list = h('div', {});
  const draw = () => list.replaceChildren(...SOLO.map(([k, label, size]) => { const u = url(k); return h('div', { class: 'row', style: { borderBottom: '1px solid var(--line,#ddd)', padding: '4px 0' } },
    h('b', { style: { minWidth: '230px' } }, label), h('span', { class: 'mut small', style: { minWidth: '80px' } }, size),
    h('input', { type: 'text', readonly: true, value: u, style: { flex: 1, minWidth: '260px' }, onfocus: (e) => e.target.select() }),
    h('button', { class: 'btn sm', onclick: async () => { try { await navigator.clipboard.writeText(u); toast('Copied', 'ok'); } catch { toast('Select the URL and press Ctrl+C', 'bad'); } } }, 'Copy'),
    h('a', { class: 'btn sm', href: u + '&preview=1', target: '_blank' }, 'Preview')); }));
  [sc, al, fit].forEach(x => x.onchange = draw);
  box.append(h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Individual OBS browser sources'), h('span', { class: 'sp' }), h('a', { class: 'btn sm', href: `/overlay/${id}?edit=1`, target: '_blank' }, 'Arrange overlay layout')),
    h('div', { class: 'mut' }, 'Each URL renders only that graphic and uses the existing published live feed. Add only the sources you need in OBS; each active Browser Source uses one live connection. Auto-fit fills the Browser Source; fit=0 uses the selected scale directly.'),
    h('div', { class: 'row' }, 'Size multiplier', sc, 'Align', al, h('label', {}, fit, ' auto-fit')), h('div', { class: 'mut' }, 'Every individual panel URL always follows its Production ON/OFF state, including the scorebug, player cards and banner.'), list);
  draw(); return box;
}

function setupPreview() {
  const on = (() => { try { return localStorage.getItem('gs_prev') === '1'; } catch { return false; } })();
  const wrap = $('#prevWrap'), btn = $('#prevBtn');
  const apply = (v) => { wrap.style.display = v ? '' : 'none'; btn.textContent = v ? 'Hide preview' : 'Show preview'; $('#prev').src = v ? `/overlay/${id}?preview=1` : 'about:blank'; try { localStorage.setItem('gs_prev', v ? '1' : '0'); } catch { /* */ } };
  btn.onclick = () => apply(wrap.style.display === 'none'); apply(on);
}

// ------------------------------------------------------------------ keys
addEventListener('keydown', (e) => {
  if (e.repeat) return;
  const t = e.target.tagName; if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key.toLowerCase() === 'h' && G) gpatch({ hold: !G.hold });
});

// ------------------------------------------------------------------ boot
(async function boot() {
  try { settings = await api('GET', '/api/settings'); } catch { /* */ }
  const info = await api('GET', '/api/info').catch(() => null);
  const resolved = id === 'live' ? (settings.live_match_id || '') : id;
  $('#lScore').href = '/score/' + id; $('#lOv').href = '/overlay/' + id; $('#lOv').title = 'Use this URL (1920×1080) as the OBS Browser Source';
  setupPreview();
  $('#gfxBox').after(soloBox());
  new Live(id, 'both', (p, kind) => {            // ONE connection for everything (browsers limit connections per host)
    if (kind === 'pub') { G = p.graphics; if (!S) S = p.state; renderGfx(); }
    else { S = p.state; $('#title').textContent = 'Production · ' + (S.title || ''); autoDirect(S); renderGfx(); }
  }, (s) => setConn($('#conn'), s), { stream: false });
  try {
    const d = await api('GET', '/api/matches');
    const lt = $('#liveTag'); const isLive = d.live_match_id === resolved;
    lt.className = 'conn ' + (isLive ? 'ok' : 'warn'); lt.textContent = isLive ? '● This is the LIVE match (output files)' : '○ Not the live match';
    if (!isLive && resolved) { lt.style.cursor = 'pointer'; lt.title = 'Click to make live'; lt.onclick = async () => { await api('POST', `/api/matches/${resolved}/go-live`); location.reload(); }; }
  } catch { /* */ }
  panel.start();
})();
