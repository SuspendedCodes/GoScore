// production page: graphics (incl. manual statistics pages), OBS scene control.
import { api, h, $, Live, matchIdFromPath, setConn, toast, select, uid } from '../common.js';
import { createObsPanel } from '../obspanel.js';
import { statsPanel } from './statsform.js';

const id = matchIdFromPath();
let G = null, S = null, catalog = null, settings = { obs: {}, auto_director: {} }, version = 0;
const saveSettings = async (patch) => { settings = await api('POST', '/api/settings', patch); };
$('#lScore').textContent = 'Scorer';
const css = document.createElement('style');
css.textContent = `.grp{border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin:6px 0}.grp>h3{margin:0 0 6px;font-size:.95rem;color:var(--mute);text-transform:uppercase;letter-spacing:.06em}
.tg{display:flex;gap:6px;flex-wrap:wrap}.tgl{padding:7px 12px;border:1px solid var(--line);border-radius:99px;cursor:pointer;background:var(--panel2);font-weight:700;user-select:none;font-size:.92rem}.tgl.on{background:var(--ok);border-color:var(--ok);color:#fff}.tgl.hold.on{background:var(--bad);border-color:var(--bad)}.tgl:focus-visible{outline:2px solid var(--acc)}
.chk{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:2px 10px}`;
document.head.append(css);
document.querySelector('.wrap').insertAdjacentHTML('beforeend', '<section class="card" id="statsBox" style="margin-top:12px"></section>');

// ------------------------------------------------------------------ OBS
const panel = createObsPanel({ box: $('#obsBox'), getSettings: () => settings, saveSettings,
  autoEvents: [['goal', 'Goal →'], ['red', 'Red card →'], ['penalty', 'Penalty →'], ['var', 'VAR →'], ['sub', 'Substitution →']] });
const seen = new Set(); let first = true;
function autoDirect() {
  const rows = S.timeline.filter(r => !seen.has(r.id)); rows.forEach(r => seen.add(r.id));
  if (first) { first = false; return; }                   // never fire for events that already existed when the page opened (or undo re-exposed)
  for (const r of rows) {
    if (r.cancelled) continue;
    const k = r.type === 'goal' ? 'goal' : (r.type === 'card' && r.color !== 'yellow') ? 'red' : (r.type === 'penalty' || r.type === 'penalty_miss') ? 'penalty' : (r.type === 'var' && r.status === 'checking') ? 'var' : r.type === 'sub' ? 'sub' : null;
    if (k) { panel.autoFire(k); break; }
  }
}

// ------------------------------------------------------------------ graphics
let gbusy = false;
async function gpatch(p) {
  if (gbusy) return; gbusy = true;
  try { G = await api('POST', `/api/matches/${id}/graphics`, p); if (document.activeElement && document.activeElement.tagName === 'SELECT') document.activeElement.blur(); renderGfx(); } catch (e) { toast(e.message, 'bad'); } finally { gbusy = false; }
}
async function pop(kind, text) { try { await api('POST', `/api/matches/${id}/graphics/trigger`, { kind, text }); } catch (e) { toast(e.message, 'bad'); } }
function tgl(label, on, fn, extra = '') { return h('span', { class: 'tgl ' + (on ? 'on ' : '') + extra, role: 'switch', 'aria-checked': on ? 'true' : 'false', tabindex: 0, onclick: (e) => { fn(); e.currentTarget.blur(); }, onkeydown: (e) => { if (e.key === 'Enter') { e.stopPropagation(); e.preventDefault(); if (!e.repeat) fn(); } } }, (on ? '● ' : '○ ') + label); }
const ttl = { get v() { try { return +(localStorage.getItem('gs_ttl') || 0); } catch { return 0; } }, set v(x) { try { localStorage.setItem('gs_ttl', x); } catch { /* */ } } };
const ttlTimers = {};
async function togglePanel(k) {
  const on = !G.panels[k]; clearTimeout(ttlTimers[k]);
  await gpatch({ panels: { [k]: on } });
  if (on && ttl.v > 0) ttlTimers[k] = setTimeout(() => { gbusy = false; gpatch({ panels: { [k]: false } }); }, ttl.v * 1000);
}
const BIG = [['lineups', 'Line-ups'], ['formation_home', 'Formation (home)'], ['formation_away', 'Formation (away)'], ['subs_bench', 'Substitutes'], ['scorers', 'Goals / scorers'], ['timeline', 'Match events'], ['halftime', 'Half-time'], ['fulltime', 'Full-time'], ['preview', 'Match preview'], ['officials', 'Officials']];
const STATP = [['stats_classic', 'Stats · Classic'], ['stats_bars', 'Stats · Bars'], ['stats_strip', 'Stats · Strip (lower third)']];
const SLIDES = [...BIG.filter(([k]) => !['halftime', 'fulltime'].includes(k)), ...STATP.filter(([k]) => ['stats_classic', 'stats_bars'].includes(k))];
const POPS = [['goal', 'GOAL'], ['card', 'CARDS'], ['sub', 'SUBS'], ['var', 'VAR'], ['penalty', 'PENALTY'], ['period', 'HT / FT / KO'], ['added_time', 'ADDED TIME']];

function chk(items, selected, onChange, max) {
  const set = new Set(selected);
  return h('div', { class: 'chk' }, items.map(([k, l]) => h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: set.has(k), onchange: (e) => { if (e.target.checked) set.add(k); else set.delete(k); let arr = items.map(x => x[0]).filter(x => set.has(x)); if (max && arr.length > max) { toast(`Max ${max}`, 'warn'); e.target.checked = false; set.delete(k); return; } onChange(arr); } }), l)));
}
function renderGfx() {
  const box = $('#gfxBox'); if (!G || !catalog) return;
  const active = document.activeElement; if (active && box.contains(active) && ['INPUT', 'SELECT'].includes(active.tagName)) return;   // do not wipe what is being edited
  const ts = catalog.team_stats.map(s => [s.key, s.label]);
  const cp = G.card_player || { team: 'A', id: '' }; const T = S ? S.teams : null;
  const pteam = select([{ value: 'A', label: T ? T.A.name : 'Home' }, { value: 'B', label: T ? T.B.name : 'Away' }], cp.team);
  const plist = T ? T[cp.team].players.filter(p => p.squad).map(p => ({ value: p.id, label: `${p.number ?? ''} ${p.name}`.trim() })) : [];
  const psel = select([{ value: '', label: '— choose player —' }, ...plist], cp.id || '');
  pteam.onchange = () => gpatch({ card_player: { team: pteam.value, id: '' } }); psel.onchange = () => gpatch({ card_player: { team: pteam.value, id: psel.value }, panels: { player_card: !!psel.value } });
  const ban = h('input', { type: 'text', value: G.banner.text || '', placeholder: 'Banner text e.g. Drinks break', size: 28 });
  const pos = select([{ value: 'top-left', label: 'Top left' }, { value: 'top-right', label: 'Top right' }, { value: 'bottom', label: 'Bottom centre' }], G.position); pos.onchange = () => gpatch({ position: pos.value });
  const sc = h('input', { type: 'number', step: '0.05', min: '0.5', max: '1.5', value: G.scale, style: { width: '80px' } }); sc.onchange = () => gpatch({ scale: +sc.value || 1 });
  const lt = select([{ value: 'both', label: 'Both teams' }, { value: 'A', label: 'Home only' }, { value: 'B', label: 'Away only' }], G.lineup_team); lt.onchange = () => gpatch({ lineup_team: lt.value });
  const stitle = h('input', { type: 'text', value: G.stats_title || '', size: 24 }); stitle.onchange = () => gpatch({ stats_title: stitle.value });
  const hasData = (k) => S && S.stats.rows[k] && (S.stats.rows[k].A != null || S.stats.rows[k].B != null);
  box.replaceChildren(
    h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Overlay Graphics'), h('span', { class: 'sp' }), tgl(G.hold ? 'HOLD — overlay frozen (H)' : 'Hold overlay (H)', G.hold, () => gpatch({ hold: !G.hold }), 'hold')),
    h('div', { class: 'mut' }, 'Hold freezes everything the audience sees (overlay, files, feeds) while the scorer keeps scoring — release to catch up instantly. Big panels and lower-thirds are exclusive: showing one hides the previous one.'),
    h('div', { class: 'grp' }, h('h3', {}, 'Always on'), h('div', { class: 'tg' }, tgl('Scorebug', G.scorebug, () => gpatch({ scorebug: !G.scorebug })), tgl('Shoot-out tracker (auto)', G.shootout_auto, () => gpatch({ shootout_auto: !G.shootout_auto })), tgl('Shoot-out tracker (force)', G.panels.shootout, () => gpatch({ panels: { shootout: !G.panels.shootout } })), h('span', { class: 'row' }, 'Position', pos, 'Size', sc))),
    h('div', { class: 'grp' }, h('h3', {}, 'Big panels'), h('div', { class: 'tg' }, BIG.map(([k, l]) => tgl(l, G.panels[k], () => togglePanel(k)))), h('div', { class: 'row' }, 'Line-ups show', lt, h('button', { class: 'btn sm', onclick: () => gpatch({ panels: Object.fromEntries([...BIG, ...STATP.slice(0, 2)].map(([k]) => [k, false])) }) }, 'Hide big panel'), 'Auto-hide after', ttlSel())),
    h('div', { class: 'grp' }, h('h3', {}, 'Panel slideshow'), h('div', { class: 'mut' }, 'Automatically rotate selected football graphics in the main overlay. This does not change your manual panel buttons or OBS scenes.'),
      h('div', { class: 'row' }, tgl('Enable slideshow', !!(G.slideshow && G.slideshow.enabled), () => gpatch({ slideshow: { ...(G.slideshow || {}), enabled: !(G.slideshow && G.slideshow.enabled) } })), 'Change every', h('input', { type: 'number', min: 5, max: 120, step: 1, value: (G.slideshow && G.slideshow.interval) || 12, style: { width: '76px' }, onchange: (e) => gpatch({ slideshow: { ...(G.slideshow || {}), interval: Math.max(5, Math.min(120, +e.target.value || 12)) } }) }), 'seconds',
        h('button', { class: 'btn sm', onclick: () => gpatch({ slideshow: { ...(G.slideshow || {}), slides: SLIDES.map(([k]) => k) } }) }, 'Select all'), h('button', { class: 'btn sm', onclick: () => gpatch({ slideshow: { ...(G.slideshow || {}), slides: [] } }) }, 'Clear')),
      h('div', { class: 'mut' }, 'Use this as a separate OBS Browser Source. When the slideshow is enabled, the combined overlay hides big panels so they cannot collide with goal/card/penalty pop-ups.'),
      (() => { const u = `${location.origin}/overlay/${id}?only=panels&slideshow=1`; return h('div', { class: 'row' }, h('input', { type: 'text', readonly: true, value: u, style: { flex: 1, minWidth: '260px' }, onfocus: (e) => e.target.select() }), h('button', { class: 'btn sm', onclick: async () => { try { await navigator.clipboard.writeText(u); toast('Slideshow URL copied', 'ok'); } catch { toast('Select the URL and press Ctrl+C', 'bad'); } } }, 'Copy slideshow URL'), h('a', { class: 'btn sm', href: u + '&preview=1', target: '_blank' }, 'Preview')); })(),
      chk(SLIDES, (G.slideshow && G.slideshow.slides) || [], (a) => gpatch({ slideshow: { ...(G.slideshow || {}), slides: a } }))) ,
    h('div', { class: 'grp' }, h('h3', {}, 'Statistics — consolidated pages (values typed in the Statistics box below)'), h('div', { class: 'tg' }, STATP.map(([k, l]) => tgl(l, G.panels[k], () => togglePanel(k)))),
      h('div', { class: 'row' }, 'Title', stitle), h('details', {}, h('summary', {}, `Rows on Classic / Bars pages (${(G.stat_rows || []).length} selected)`), chk(ts, G.stat_rows || [], (a) => gpatch({ stat_rows: a })), h('button', { class: 'btn sm', onclick: () => gpatch({ stat_rows: catalog.default_rows }) }, 'Reset to default')),
      h('details', {}, h('summary', {}, `Columns on the Strip (${(G.stat_keys_strip || []).length}, max 6)`), chk(ts, G.stat_keys_strip || [], (a) => gpatch({ stat_keys_strip: a }), 6))),
    h('div', { class: 'grp' }, h('h3', {}, 'Statistics — individual pages (one stat at a time, lower third)'), h('div', { class: 'tg' }, ts.map(([k, l]) => { const on = G.panels.stat_single && G.stat_key === k;
      return h('span', { class: 'tgl ' + (on ? 'on' : '') + (hasData(k) ? '' : ' nodata'), style: hasData(k) ? {} : { opacity: .45 }, title: hasData(k) ? '' : 'no value entered yet', onclick: () => gpatch(on ? { panels: { stat_single: false } } : { stat_key: k, panels: { stat_single: true } }) }, (on ? '● ' : '○ ') + l); }))),
    h('div', { class: 'grp' }, h('h3', {}, 'Player card (individual player statistics)'), h('div', { class: 'row' }, pteam, psel, tgl('Show card', G.panels.player_card, () => gpatch({ panels: { player_card: !G.panels.player_card } }))),
      h('details', {}, h('summary', {}, 'Which numbers on the card'), chk(catalog.player_stats.map(s => [s.key, s.label]), G.player_stat_keys || [], (a) => gpatch({ player_stat_keys: a }), 6))),
    h('div', { class: 'grp' }, h('h3', {}, 'Banner / lower third text'), h('div', { class: 'row' }, ban, h('button', { class: 'btn sm primary', onclick: () => gpatch({ banner: { text: ban.value }, panels: { banner: !!ban.value } }) }, 'Show banner'), h('button', { class: 'btn sm', onclick: () => gpatch({ panels: { banner: false } }) }, 'Hide'), h('button', { class: 'btn sm', onclick: () => pop('custom', ban.value) }, 'As pop-up'))),
    h('div', { class: 'grp' }, h('h3', {}, 'Automatic pop-ups (when the scorer records them)'), h('div', { class: 'tg' }, POPS.map(([k, l]) => tgl(l, G.popups_enabled[k], () => gpatch({ popups_enabled: { [k]: !G.popups_enabled[k] } }))))),
    h('div', { class: 'grp' }, h('h3', {}, 'Fire a pop-up now'), h('div', { class: 'tg' }, [['kickoff', 'Kick-off'], ['halftime', 'Half-time'], ['fulltime', 'Full-time'], ['goal', 'Goal'], ['yellow', 'Yellow'], ['red', 'Red'], ['sub', 'Sub'], ['var', 'VAR check'], ['penalty', 'Penalty'], ['added', 'Added time']].map(([k, l]) => h('button', { class: 'btn sm', onclick: () => pop(k, '') }, l)))),
    h('div', { class: 'grp' }, h('h3', {}, 'Broadcast delay'), delayRow()));
}
function ttlSel() { const s = select([{ value: 0, label: 'never' }, { value: 8, label: '8 s' }, { value: 15, label: '15 s' }, { value: 30, label: '30 s' }, { value: 60, label: '60 s' }], ttl.v); s.onchange = () => { ttl.v = +s.value; }; return s; }
function delayRow() {
  const d = h('input', { type: 'number', min: 0, max: 60, step: 1, value: settings.publish_delay || 0, style: { width: '70px' } });
  return h('div', { class: 'row' }, 'Delay overlay, files & feeds by', d, 'seconds', h('button', { class: 'btn sm', onclick: () => saveSettings({ publish_delay: Math.max(0, +d.value || 0) }).then(() => toast('Delay set to ' + (settings.publish_delay || 0) + ' s')) }, 'Apply'), h('span', { class: 'mut' }, 'Match your stream delay. The match clock on the overlay is delayed by the same amount.'));
}

// ------------------------------------------------------------------ manual statistics box
let statsUi = null;
async function postStats(ev) {
  try { ev.cid = uid(); const r = await api('POST', `/api/matches/${id}/events`, ev); if (r.version) version = r.version; return r; }
  catch (e) { toast(e.message, 'bad', 7000); return null; }
}
function renderStats() {
  const box = $('#statsBox'); if (!S || !catalog) return;
  if (!statsUi) {
    statsUi = statsPanel({ getState: () => S, catalog, post: postStats });
    box.replaceChildren(h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Match statistics — enter values here'), h('span', { class: 'mut' }, 'Possession, shots, passes, fouls … are entered by you (override). Saved numbers appear on the stats pages immediately (subject to Hold / delay).')), statsUi.el);
    statsUi.refresh(); return;
  }
  const a = document.activeElement; if (a && statsUi.el.contains(a) && a.tagName === 'INPUT') return;   // never wipe what is being typed
  statsUi.refresh();
}

// ------------------------------------------------------------------ one browser source per graphic
const SOLO = [['bug', 'Scorebug', '800×80'], ['tracker', 'Shoot-out tracker', '520×330'], ['popups', 'Event pop-ups (goal / card / sub …)', '1100×420'],
  ['lineups', 'Starting line-ups', '1560×990'], ['formation_home', 'Formation — home', '1180×710'], ['formation_away', 'Formation — away', '1180×740'], ['subs_bench', 'Substitutes', '1560×500'],
  ['scorers', 'Goals / scorers', '1180×400'], ['timeline', 'Match events timeline', '1100×200–700'], ['halftime', 'Half-time card', '1180×510'], ['fulltime', 'Full-time card', '1180×560'], ['preview', 'Match preview', '1180×560'],
  ['officials', 'Match officials', '760×410'], ['stats_classic', 'Stats — Classic', '1100×870'], ['stats_bars', 'Stats — Bars', '1100×800'], ['stats_strip', 'Stats — Strip', '1500×106'],
  ['stat_single', 'Single stat (lower third)', '1240×190'], ['player_card', 'Player stat card', '1100×130'], ['banner', 'Banner', '900×100']];
function soloBox() {
  const box = h('div', { class: 'card', id: 'soloBox' });
  const sc = h('input', { type: 'number', step: '0.05', min: '0.2', max: '3', value: '1', style: { width: '70px' } });
  const al = select([{ value: 'c', label: 'Centre' }, { value: 'tl', label: 'Top left' }, { value: 'tr', label: 'Top right' }, { value: 'bl', label: 'Bottom left' }, { value: 'br', label: 'Bottom right' }, { value: 't', label: 'Top' }, { value: 'b', label: 'Bottom' }], 'c');
  const fo = h('input', { type: 'checkbox' }); const fit = h('input', { type: 'checkbox', checked: true });
  const url = (k) => { const q = new URLSearchParams({ panel: k, follow: '1' }); if (!fit.checked) q.set('fit', '0'); if (+sc.value && +sc.value !== 1) q.set('scale', sc.value); if (al.value !== 'c') q.set('align', al.value); if (fo.checked) q.set('follow', '1'); return `${location.origin}/overlay/${id}?${q}`; };
  const list = h('div', {});
  const draw = () => list.replaceChildren(...SOLO.map(([k, l, sz]) => { const u = url(k); return h('div', { class: 'row', style: { borderBottom: '1px solid var(--line,#ddd)', padding: '4px 0' } },
    h('b', { style: { minWidth: '230px' } }, l), h('span', { class: 'mut small', style: { minWidth: '80px' } }, sz), h('input', { type: 'text', readonly: true, value: u, style: { flex: 1, minWidth: '260px' }, onfocus: (e) => e.target.select() }),
    h('button', { class: 'btn sm', onclick: async () => { try { await navigator.clipboard.writeText(u); toast('Copied', 'ok'); } catch { toast('Select the URL and press Ctrl+C', 'bad'); } } }, 'Copy'), h('a', { class: 'btn sm', href: u + '&preview=1', target: '_blank' }, 'Preview')); }));
  [sc, al, fo, fit].forEach(x => x.onchange = draw);
  box.append(h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Panels — one OBS browser source per graphic'), h('span', { class: 'sp' }), h('a', { class: 'btn sm', href: `/overlay/${id}?edit=1`, target: '_blank' }, 'Arrange overlay layout')),
    h('div', { class: 'mut' }, 'Add each URL as its own Browser Source and give it ANY width × height you like — the graphic is scaled to fill it (the “suggested size” just matches its shape, so there are no empty margins). Resize the source in OBS and it re-fits instantly.'),
    h('div', { class: 'row' }, 'Size multiplier', sc, 'Align', al, h('label', {}, fit, ' auto-fit'), h('label', { title: 'Off = always visible (toggle it with the OBS eye icon). On = also obeys the Production buttons above.' }, fo, ' follow Production buttons')), list);
  draw(); return box;
}

// ------------------------------------------------------------------ preview + keys
function setupPreview() {
  const on = (() => { try { return localStorage.getItem('gs_prev') === '1'; } catch { return false; } })();
  const wrap = $('#prevWrap'), btn = $('#prevBtn');
  const apply = (v) => { wrap.style.display = v ? '' : 'none'; btn.textContent = v ? 'Hide preview' : 'Show preview'; $('#prev').src = v ? `/overlay/${id}?preview=1` : 'about:blank'; try { localStorage.setItem('gs_prev', v ? '1' : '0'); } catch { /* */ } };
  btn.onclick = () => apply(wrap.style.display === 'none'); apply(on);
}
addEventListener('keydown', (e) => {
  if (e.repeat) return;
  const t = e.target.tagName; if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key.toLowerCase() === 'h' && G) gpatch({ hold: !G.hold });
});

// ------------------------------------------------------------------ boot
(async function boot() {
  try { settings = await api('GET', '/api/settings'); } catch { /* */ }
  try { catalog = (await api('GET', '/api/presets')).football; } catch { /* */ }
  const resolved = id === 'live' ? (settings.live_match_id || '') : id;
  $('#lScore').href = '/score/' + id; $('#lOv').href = '/overlay/' + id; $('#lOv').title = 'Use this URL (1920×1080) as the OBS Browser Source';
  setupPreview();
  $('#gfxBox').after(soloBox());
  new Live(id, 'both', (p, kind) => {            // ONE connection for everything (browsers limit connections per host)
    if (kind === 'pub') { G = p.graphics; if (!S) S = p.state; renderGfx(); }
    else { S = p.state; $('#title').textContent = 'Production · ' + (S.title || ''); autoDirect(); renderGfx(); renderStats(); }
  }, (s) => setConn($('#conn'), s), { stream: false });
  try {
    const d = await api('GET', '/api/matches');
    const lt = $('#liveTag'); const isLive = d.live_match_id === resolved;
    lt.className = 'conn ' + (isLive ? 'ok' : 'warn'); lt.textContent = isLive ? '● This is the LIVE match (output files)' : '○ Not the live match';
    if (!isLive && resolved) { lt.style.cursor = 'pointer'; lt.title = 'Click to make live'; lt.onclick = async () => { await api('POST', `/api/matches/${resolved}/go-live`); location.reload(); }; }
  } catch { /* */ }
  panel.start();
})();
