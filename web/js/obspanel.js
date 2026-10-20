// OBS camera / scene control panel, shared by the cricket and football Production pages.
// Everything here is a convenience: scoring and the overlay work without OBS.
import { h, $, toast, select } from './common.js';
import { Obs } from './obs.js';

/**
 * createObsPanel({ box, getSettings, saveSettings, autoEvents })
 *   box           element the panel is drawn into (it needs no particular children)
 *   getSettings() current settings object ({obs:{}, auto_director:{}, ...})
 *   saveSettings(patch) -> Promise  (POST /api/settings and update the caller's copy)
 *   autoEvents    [[key, label], ...]  events that may switch scene, e.g. [['wicket','Wicket →'], ...]
 * returns { obs, render, start(), autoFire(key) }
 */
export function createObsPanel({ box, getSettings, saveSettings, autoEvents = [] }) {
  let scenes = [], program = '', preview = '', studio = false, lastScene = '', streaming = null, autoTimer = null;
  const store = { get pw() { try { return localStorage.getItem('gs_obs_pw') || ''; } catch { return ''; } }, set pw(v) { try { localStorage.setItem('gs_obs_pw', v); } catch { /* */ } } };
  const O = () => getSettings().obs || {};

  const obs = new Obs(async (ev) => {
    if (ev.type === '_status') { render(); return; }
    if (ev.type === '_identified') { await refresh(); return; }
    if (ev.type === 'CurrentProgramSceneChanged') { if (program && program !== ev.data.sceneName) lastScene = program; program = ev.data.sceneName; }
    else if (ev.type === 'CurrentPreviewSceneChanged') preview = ev.data.sceneName;
    else if (ev.type === 'StudioModeStateChanged') studio = ev.data.studioModeEnabled;
    else if (ev.type === 'SceneListChanged') { await refresh(); return; }
    else if (ev.type === 'StreamStateChanged') streaming = ev.data.outputActive;
    render();
  });
  async function refresh() {
    try {
      const l = await obs.req('GetSceneList');
      scenes = (l.scenes || []).map(s => s.sceneName).reverse();    // OBS returns bottom-up
      program = l.currentProgramSceneName || ''; preview = l.currentPreviewSceneName || '';
      try { studio = (await obs.req('GetStudioModeEnabled')).studioModeEnabled; } catch { studio = false; }
      try { streaming = (await obs.req('GetStreamStatus')).outputActive; } catch { streaming = null; }
    } catch (e) { toast(e.message, 'bad'); }
    render();
  }
  async function goScene(name, direct) {
    if (!name) return;
    try {
      if (studio && !direct) await obs.req('SetCurrentPreviewScene', { sceneName: name });
      else await obs.req('SetCurrentProgramScene', { sceneName: name });
    } catch (e) { toast('OBS: ' + e.message, 'bad'); }
  }
  async function take() { if (!studio) return; try { await obs.req('TriggerStudioModeTransition'); } catch (e) { toast('OBS: ' + e.message, 'bad'); } }
  async function panic() { if (O().panic) { try { await obs.req('SetCurrentProgramScene', { sceneName: O().panic }); } catch (e) { toast('OBS: ' + e.message, 'bad'); } } else toast('Choose a panic scene first', 'warn'); }
  async function back() { if (lastScene) goScene(lastScene, true); }
  async function setTransition() {
    try { if (O().transition) await obs.req('SetCurrentSceneTransition', { transitionName: O().transition });
      if (O().duration != null) await obs.req('SetCurrentSceneTransitionDuration', { transitionDuration: +O().duration }); } catch (e) { toast('OBS: ' + e.message, 'bad'); }
  }

  function render() {
    const o = O(); const st = obs.status;
    const LBL = { connected: 'OBS CONNECTED', connecting: 'CONNECTING…', reconnecting: 'RECONNECTING…', error: 'OBS ERROR', off: 'OBS NOT CONNECTED' };
    // While trying to connect, only refresh the status text: never rebuild the form, or what you are typing is wiped every 2 s.
    if (st !== 'connected' && $('#oh', box) && $('#obsStatus', box)) {
      $('#obsStatus', box).className = 'conn ' + ({ connecting: 'warn', reconnecting: 'warn', error: 'bad', off: 'warn' }[st]); $('#obsStatus', box).textContent = '● ' + LBL[st];
      $('#obsErr', box).textContent = obs.err && st !== 'connected' ? 'Warning ' + obs.err : '';
      $('#obsGo', box).textContent = (st === 'off' || st === 'error') ? 'Connect' : 'Apply & reconnect'; $('#obsStop', box).hidden = (st === 'off' || st === 'error');
      return;
    }
    const cls = { connected: 'ok', connecting: 'warn', reconnecting: 'warn', error: 'bad', off: 'warn' }[st];
    const host = h('input', { type: 'text', value: o.host || 'localhost', size: 14, id: 'oh' });
    const port = h('input', { type: 'number', value: o.port || 4455, style: { width: '80px' }, id: 'op' });
    const pw = h('input', { type: 'password', value: store.pw, placeholder: 'password', size: 12, id: 'opw' });
    const conn = () => { store.pw = pw.value; saveSettings({ obs: { ...O(), host: host.value, port: +port.value, auto: true } }).then(() => obs.connect({ host: host.value, port: +port.value, password: pw.value })); };
    const kids = [h('div', { class: 'row' }, h('b', { style: { fontSize: '1.1rem' } }, 'Production Camera / scene control'), h('span', { id: 'obsStatus', class: 'conn ' + cls }, '● ' + LBL[st]),
      streaming != null && st === 'connected' ? h('span', { class: 'conn ' + (streaming ? 'ok' : 'warn') }, streaming ? '● STREAMING' : '○ not streaming') : null),
    h('div', { id: 'obsErr', class: 'mut' }, obs.err && st !== 'connected' ? 'Warning ' + obs.err : '')];
    if (st === 'connected') {
      kids.push(h('div', { class: 'row mut' }, studio ? 'Studio mode: click = PREVIEW (green), TAKE = on air. Shift+click = straight to air.' : 'Click a scene = straight to air (red).', h('span', { class: 'sp' }), h('span', {}, 'keys ', h('span', { class: 'kbd' }, '1-9'), ' ', h('span', { class: 'kbd' }, 'Space'), ' take ', h('span', { class: 'kbd' }, 'Esc'), ' panic ', h('span', { class: 'kbd' }, '⌫'), ' back')));
      kids.push(h('div', { class: 'scenes' }, scenes.map((s, i) => h('button', { class: 'btn scn' + (s === program ? ' pgm' : s === preview && studio ? ' pvw' : ''), onclick: (e) => goScene(s, e.shiftKey) },
        h('span', { class: 'k' }, i < 9 ? i + 1 : ''), s, s === program ? h('span', { class: 't' }, 'ON AIR') : (s === preview && studio ? h('span', { class: 't' }, 'PREVIEW') : null)))));
      kids.push(h('div', { class: 'row' },
        studio ? h('button', { class: 'btn ok big2', onclick: take }, 'TAKE ▶ (Space)') : null,
        h('button', { class: 'btn danger big2', onclick: panic }, 'Warning PANIC' + (o.panic ? ' → ' + o.panic : '')),
        h('button', { class: 'btn', onclick: back, disabled: !lastScene }, '↩ Back' + (lastScene ? ' to ' + lastScene : '')),
        h('button', { class: 'btn', onclick: async () => { try { await obs.req('SetStudioModeEnabled', { studioModeEnabled: !studio }); } catch (e) { toast(e.message, 'bad'); } } }, studio ? 'Studio mode: ON' : 'Studio mode: off')));
      const panicSel = select([{ value: '', label: '— none —' }, ...scenes.map(s => ({ value: s, label: s }))], o.panic || '');
      panicSel.onchange = () => saveSettings({ obs: { ...O(), panic: panicSel.value } }).then(render);
      kids.push(h('div', { class: 'row' }, h('span', {}, 'Panic scene:'), panicSel));
      kids.push(h('details', {}, h('summary', {}, 'Transition & auto-director'), transitionAndAuto()));
      kids.push(h('div', { class: 'row' }, h('button', { class: 'btn sm ghost', onclick: () => obs.close() }, 'Disconnect')));
    } else {
      kids.push(h('div', { class: 'row' }, 'OBS address', host, ':', port, pw, h('button', { id: 'obsGo', class: 'btn primary', onclick: conn }, st === 'off' || st === 'error' ? 'Connect' : 'Apply & reconnect'),
        h('button', { id: 'obsStop', class: 'btn danger', hidden: st === 'off' || st === 'error', onclick: async () => { obs.close(); await saveSettings({ obs: { ...O(), auto: false } }); } }, '■ Stop trying')));
      kids.push(h('div', { class: 'mut' }, 'In OBS: Tools → WebSocket Server Settings → enable, note the port & password. If OBS is on another computer use its IP address. Nothing else on this page needs OBS.'));
    }
    box.replaceChildren(...kids.filter(Boolean));
  }
  function transitionAndAuto() {
    const o = O(); const a = getSettings().auto_director || {};
    const wrap = h('div', {});
    const tr = h('input', { type: 'text', value: o.transition || '', placeholder: 'transition name e.g. Fade', size: 16 });
    const du = h('input', { type: 'number', value: o.duration ?? 300, style: { width: '80px' } });
    wrap.append(h('div', { class: 'row' }, 'Transition', tr, du, 'ms', h('button', { class: 'btn sm', onclick: () => saveSettings({ obs: { ...O(), transition: tr.value, duration: +du.value } }).then(setTransition) }, 'Apply')));
    const opts = [{ value: '', label: '— no change —' }, ...scenes.map(s => ({ value: s, label: s }))];
    const mk = (k, label) => { const s = select(opts, a[k] || ''); s.onchange = () => saveAuto({ [k]: s.value }); return h('div', { class: 'row' }, h('span', { style: { width: '90px' } }, label), s); };
    const en = h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: !!a.enabled, onchange: (e) => saveAuto({ enabled: e.target.checked }) }), ' Auto-director ON (switches scene on events, then returns). ', h('b', {}, 'Off by default — test it first.'));
    const secs = h('input', { type: 'number', value: a.seconds ?? 6, style: { width: '70px' } }); secs.onchange = () => saveAuto({ seconds: +secs.value });
    wrap.append(h('h3', {}, 'Auto-director'), en, ...autoEvents.map(([k, l]) => mk(k, l)), h('div', { class: 'row' }, 'Stay for', secs, 'seconds, then return to the previous scene'));
    return wrap;
  }
  async function saveAuto(p) { await saveSettings({ auto_director: { ...(getSettings().auto_director || {}), ...p } }); }

  /** Called by the page when a new event of kind `key` appears (the page decides what is "new"). */
  function autoFire(key) {
    const a = getSettings().auto_director || {};
    const sc = a.enabled && obs.ready && a[key]; if (!sc || sc === program) return;
    const ret = program; clearTimeout(autoTimer);
    obs.req('SetCurrentProgramScene', { sceneName: sc }).catch(() => {});
    autoTimer = setTimeout(() => { if (program === sc && ret) obs.req('SetCurrentProgramScene', { sceneName: ret }).catch(() => {}); }, (a.seconds || 6) * 1000);
  }

  addEventListener('keydown', (e) => {
    if (e.repeat) return;
    const t = e.target.tagName; if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[1-9]$/.test(e.key) && obs.ready) { const s = scenes[+e.key - 1]; if (s) { e.preventDefault(); goScene(s, e.shiftKey); } }
    else if (e.key === ' ') { e.preventDefault(); take(); }
    else if (e.key === 'Escape') { panic(); }
    else if (e.key === 'Backspace') { e.preventDefault(); back(); }
  });

  return {
    obs, render,
    start() { render(); const o = O(); if (o.host && o.auto) obs.connect({ host: o.host, port: o.port || 4455, password: store.pw }); },
  };
}
