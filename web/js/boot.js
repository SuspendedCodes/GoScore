// Page loader: every match page (/score, /control, /overlay, /scorecard, /setup) is shared by the sports.
// It asks the server which sport the match is and loads the matching module.
const page = document.querySelector('script[data-page]').dataset.page;
const parts = location.pathname.split('/').filter(Boolean);
const id = parts[1] || new URLSearchParams(location.search).get('m') || 'live';
let sport = 'cricket';
for (let i = 0; i < 20; i++) {          // OBS may start before the server: keep trying for a while
  try {
    const r = await fetch(`/api/matches/${id}/meta`, { cache: 'no-store' });
    if (r.ok) { sport = (await r.json()).sport || 'cricket'; break; }
    if (r.status === 404) break;
  } catch { /* server not up yet */ }
  await new Promise(res => setTimeout(res, 1000));
}
// ?sport=cricket|football picks the module directly (used by the layout editor when no match exists yet)
const forced = new URLSearchParams(location.search).get('sport');
if (forced === 'cricket' || forced === 'football') sport = forced;
document.documentElement.dataset.sport = sport;
await import(sport === 'football' ? `/static/js/fb/${page}.js` : `/static/js/${page}.js`);
