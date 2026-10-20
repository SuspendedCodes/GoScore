// Minimal obs-websocket v5 client (browser). No dependencies.
// SHA-256 is implemented in plain JS because crypto.subtle only exists on secure origins
// and the control page is normally opened over plain http on the LAN.

const K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);

export function sha256(bytes) {            // Uint8Array -> Uint8Array(32)
  const l = bytes.length, bitLen = l * 8;
  const padded = new Uint8Array(((l + 9 + 63) >> 6) << 6);
  padded.set(bytes); padded[l] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000));
  dv.setUint32(padded.length - 4, bitLen >>> 0);
  const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const w = new Uint32Array(64);
  const rr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let o = 0; o < padded.length; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rr(w[i-15], 7) ^ rr(w[i-15], 18) ^ (w[i-15] >>> 3);
      const s1 = rr(w[i-2], 17) ^ rr(w[i-2], 19) ^ (w[i-2] >>> 10);
      w[i] = (w[i-16] + s0 + w[i-7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = H;
    for (let i = 0; i < 64; i++) {
      const S1 = rr(e, 6) ^ rr(e, 11) ^ rr(e, 25), ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = rr(a, 2) ^ rr(a, 13) ^ rr(a, 22), mj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + mj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += hh;
  }
  const out = new Uint8Array(32); const od = new DataView(out.buffer);
  H.forEach((v, i) => od.setUint32(i * 4, v));
  return out;
}
const enc = (s) => new TextEncoder().encode(s);
const b64 = (u8) => { let s = ''; u8.forEach(b => s += String.fromCharCode(b)); return btoa(s); };
const unb64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
export function obsAuth(password, salt, challenge) {
  const secret = b64(sha256(enc(password + salt)));
  return b64(sha256(enc(secret + challenge)));
}

// Events: Scenes(4) | Transitions(16) | Outputs(64) | Ui(1024) | General(1)
const SUBS = 4 | 16 | 64 | 1024 | 1;

export class Obs {
  constructor(onEvent) {
    this.onEvent = onEvent || (() => {});
    this.ws = null; this.pending = new Map(); this.rid = 0;
    this.status = 'off'; this.cfg = null; this.timer = null; this.wantOn = false; this.err = '';
  }
  setStatus(s, err = '') { this.status = s; this.err = err; this.onEvent({ type: '_status', status: s, error: err }); }
  connect(cfg) {
    this.cfg = cfg; this.wantOn = true; this.close(true);
    this.setStatus('connecting');
    let ws;
    try { ws = new WebSocket(`ws://${cfg.host || 'localhost'}:${cfg.port || 4455}`); }
    catch (e) { this.setStatus('error', String(e)); return this.retry(); }
    this.ws = ws; let identified = false;
    ws.onmessage = async (m) => {
      let d; try { d = JSON.parse(m.data); } catch { return; }
      if (d.op === 0) {
        const idd = { rpcVersion: 1, eventSubscriptions: SUBS };
        const a = d.d.authentication;
        if (a) {
          if (!cfg.password) { this.wantOn = false; this.setStatus('error', 'OBS needs a password'); return ws.close(); }
          idd.authentication = obsAuth(cfg.password, a.salt, a.challenge);
        }
        ws.send(JSON.stringify({ op: 1, d: idd }));
      } else if (d.op === 2) { identified = true; this.setStatus('connected'); this.onEvent({ type: '_identified' }); }
      else if (d.op === 5) this.onEvent({ type: d.d.eventType, data: d.d.eventData || {} });
      else if (d.op === 7) {
        const p = this.pending.get(d.d.requestId); if (!p) return;
        this.pending.delete(d.d.requestId); clearTimeout(p.t);
        if (d.d.requestStatus.result) p.res(d.d.responseData || {}); else p.rej(new Error(d.d.requestStatus.comment || ('OBS error ' + d.d.requestStatus.code)));
      }
    };
    ws.onclose = (e) => {
      this.pending.forEach(p => { clearTimeout(p.t); p.rej(new Error('OBS disconnected')); }); this.pending.clear();
      if (this.ws !== ws) return; this.ws = null;
      if (e.code === 4009) { this.wantOn = false; return this.setStatus('error', 'Wrong OBS password'); }
      this.setStatus(this.wantOn ? 'reconnecting' : 'off', identified ? 'connection lost' : this.err);
      this.retry();
    };
    ws.onerror = () => { this.err = 'cannot reach OBS at ' + (cfg.host || 'localhost') + ':' + (cfg.port || 4455); };
  }
  retry() { clearTimeout(this.timer); if (this.wantOn) this.timer = setTimeout(() => this.wantOn && this.connect(this.cfg), 2000); }
  close(keepWant) { clearTimeout(this.timer); if (!keepWant) this.wantOn = false; const w = this.ws; this.ws = null; if (w) { try { w.close(); } catch { /* */ } } if (!keepWant) this.setStatus('off'); }
  get ready() { return this.status === 'connected' && this.ws && this.ws.readyState === 1; }
  req(type, data) {
    return new Promise((res, rej) => {
      if (!this.ready) return rej(new Error('OBS not connected'));
      const id = 'r' + (++this.rid);
      const t = setTimeout(() => { this.pending.delete(id); rej(new Error('OBS did not answer')); }, 5000);
      this.pending.set(id, { res, rej, t });
      this.ws.send(JSON.stringify({ op: 6, d: { requestType: type, requestId: id, requestData: data || {} } }));
    });
  }
}
