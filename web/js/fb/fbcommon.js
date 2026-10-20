// helpers shared by the scorer, overlay, scorecard and production pages.
export const POS_ORDER = { GK: 0, DF: 1, MF: 2, FW: 3, '': 4 };
export const PERIOD_NAME = { 1: '1st half', 2: '2nd half', 3: 'ET 1st half', 4: 'ET 2nd half' };

/** Clock maths. `now` = server-corrected "now" in ms (for the overlay: minus the publish delay). */
export function clockInfo(S, now) {
  const c = S.clock, ph = S.phase;
  const p = c.last_period || 0;
  if (ph === 'pre' || !p) return { mmss: '00:00', min: '', split: '', over: false, stoppage: '', added: '', elapsed: 0, running: false };
  const e = c.base_ms + (c.running && c.since != null ? Math.max(0, now - c.since) : 0);
  const tot = c.offset_ms + e, reg = c.regular_ms;
  const pad = (n) => String(n).padStart(2, '0');
  const mmss = `${pad(Math.floor(tot / 60000))}:${pad(Math.floor(tot / 1000) % 60)}`;
  let split, min, over = false, stoppage = '';
  if (e >= reg) {
    const base = (c.offset_ms + reg) / 60000, ex = Math.floor((e - reg) / 60000) + 1;
    split = `${base}+${ex}`; min = `${base}+${ex}'`; over = true;
    const se = e - reg; stoppage = `+${pad(Math.floor(se / 60000))}:${pad(Math.floor(se / 1000) % 60)}`;
  } else { const m = Math.floor((c.offset_ms + e) / 60000) + 1; split = String(m); min = m + "'"; }
  return { mmss, min, split, over, stoppage, added: c.added_min ? '+' + c.added_min : '', elapsed: e, running: !!c.running,
    base: over ? `${(c.offset_ms + reg) / 60000}:00` : mmss };
}
export const teamOf = (S, tid) => S.teams[tid];
export const pl = (S, pid) => { for (const t of Object.values(S.teams)) { const p = t.players.find(x => x.id === pid); if (p) return p; } return null; };
export const pname = (S, pid) => (pl(S, pid) || {}).name || '';
export const pshort = (S, pid) => (pl(S, pid) || {}).short || (pl(S, pid) || {}).name || '';
export const pnum = (p) => (p && p.number != null ? p.number : '');
export const opp = (t) => (t === 'A' ? 'B' : 'A');
export function sortByPos(players) { return players.slice().sort((a, b) => (POS_ORDER[a.pos] - POS_ORDER[b.pos]) || ((a.number ?? 999) - (b.number ?? 999))); }
/** XI as they were at kick-off, in slot order, plus what became of them. */
export function startingXI(S, tid) { return S.teams[tid].players.filter(p => p.started).sort((a, b) => (a.slot ?? 99) - (b.slot ?? 99)); }
export function currentXI(S, tid) {
  // slot -> current occupant (substitutes take the slot of the player they replaced)
  const bySlot = new Map();
  for (const p of S.teams[tid].players) if (p.status === 'on' && p.slot != null) bySlot.set(p.slot, p);
  return bySlot;
}
export function bench(S, tid) { return S.teams[tid].players.filter(p => !p.started && p.squad); }
export const statusLabel = (p) => ({ on: 'On pitch', bench: 'Bench', off: 'Substituted off', sent_off: 'Sent off', bench_sent_off: 'Sent off (bench)', out_of_squad: 'Not in squad' }[p.status] || p.status);

/** Formation rows from "4-3-3": returns [[slotIdx...], ...] with the keeper row first. */
export function formationRows(formation, n = 11) {
  const nums = String(formation || '').split(/[-\s]/).map(Number).filter(x => x > 0);
  let sum = nums.reduce((a, b) => a + b, 0);
  if (!nums.length || sum !== n - 1) { const d = n - 1; const a = Math.ceil(d / 3); const b = Math.ceil((d - a) / 2); nums.length = 0; nums.push(a, b, d - a - b); }
  const rows = [[0]]; let i = 1;
  for (const k of nums) { rows.push(Array.from({ length: k }, () => i++)); }
  return rows;
}
export const fmtScore = (S) => `${S.score.A} - ${S.score.B}`;
export function evText(S, ev) {
  // describe an event row from state.timeline
  return `${ev.label} ${ev.text}`;
}
export function colorText(hex) {   // readable text colour on a team colour
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || ''); if (!m) return '#fff';
  const n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#111' : '#fff';
}

// ---- pitch layout (shared by the drag-and-drop editor and the overlay) -------------------------------------------
export const FORMATIONS = ['4-4-2', '4-3-3', '4-2-3-1', '4-1-4-1', '4-5-1', '3-5-2', '3-4-3', '5-3-2', '5-4-1', '4-3-2-1', '3-4-2-1', '4-4-1-1', '4-1-2-1-2', '3-3-1-3', '3-2-4-1', '2-3-1', '3-2-1', '2-3-2', '3-3-2', '3-2-3'];
/** Default coordinates by slot index for a formation: x 0 (own goal) -> 100 (opponent goal), y 0..100 across. */
export function autoLayout(formation, n = 11) {
  const rows = formationRows(formation, n); const out = [];
  rows.forEach((row, ri) => row.forEach((slot, ci) => { out[slot] = { x: 7 + ri * (86 / Math.max(rows.length - 1, 1)), y: (100 / (row.length + 1)) * (ci + 1) }; }));
  return out;
}
/** Current XI on the pitch with coordinates: explicit (dragged) position, else the formation default for the slot. */
export function pitchPlayers(S, tid) {
  const t = S.teams[tid]; const n = Math.max(t.players.filter(p => p.started).length, 1); const auto = autoLayout(t.formation, n);
  return t.players.filter(p => p.status === 'on' && p.slot != null).sort((a, b) => a.slot - b.slot).map(p => {
    const a = auto[p.slot] || { x: 50, y: 50 };
    return { p, x: p.x != null ? p.x : a.x, y: p.y != null ? p.y : a.y };
  });
}
