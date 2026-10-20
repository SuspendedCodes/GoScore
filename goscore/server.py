"""GoScore HTTP server - standard library only (no pip install needed).

 * REST API for scoring / overrides / setup
 * Server-Sent Events for live scorer screens and OBS overlays (with polling fallback)
 * Broadcast feeds: JSON, XML, flat text/CSV files (also written to disk on every change)
 * Hold ("freeze") and publish-delay so the audience never sees a mistake before it is fixed
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import queue
import re
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import engine as E
from . import football as FB
from . import sports as S
from .outputs import OutputWriter, state_to_xml, text_fields, csv_files
from .store import Store, StoreError, atomic_write, now_ms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

DEFAULT_GRAPHICS = {
    "scorebug": True,
    "panels": {"innsum": False, "worm": False, "scorecard": False, "bowling": False, "partnership": False, "fow": False, "target": False,
               "teams": False, "toss": False, "result": False, "overs": False, "batter_card": False,
               "bowler_card": False, "banner": False, "summary": False, "testsum": False},
    "card_player": None,
    "scorecard_innings": None,
    "target_display": "runs",          # runs | wickets | both
    "overs_start": None,               # 1-based over number; None means most recent 10
    "slideshow": {"enabled": False, "interval": 12, "slides": ["innsum", "scorecard", "bowling", "teams", "summary"]},

    "banner": {"text": ""},
    "popups_enabled": {"four": True, "six": True, "wicket": True, "milestone": True, "free_hit": True},
    "position": "bottom",           # bottom | bottom-left | top
    "scale": 1.0,
    "hold": False,
    "popup": None,                  # {"id","kind","text","ts"}  (manual trigger)
    "version": 0,
}


FOOTBALL_PANELS = ["lineups", "formation_home", "formation_away", "subs_bench", "scorers", "timeline", "halftime", "fulltime",
                   "preview", "officials", "stats_classic", "stats_bars", "stats_strip", "stat_single", "player_card",
                   "shootout", "banner"]
# full-screen / big panels: only one at a time (server enforced) ; lower-third group likewise
EXCLUSIVE_GROUPS = [
    ["lineups", "formation_home", "formation_away", "subs_bench", "scorers", "timeline", "halftime", "fulltime", "preview",
     "officials", "stats_classic", "stats_bars"],
    ["stat_single", "stats_strip", "player_card", "banner"],
]
FOOTBALL_GRAPHICS = {
    "scorebug": True,
    "panels": {k: False for k in FOOTBALL_PANELS},
    "banner": {"text": ""},
    "card_player": None,                 # {"team": "A", "id": "A9"}
    "stat_key": "possession",            # single-stat page
    "stat_rows": list(FB.DEFAULT_STAT_ROWS),   # rows on the consolidated pages (order = display order)
    "stat_keys_strip": ["possession", "shots", "shots_on_target", "corners", "fouls"],
    "player_stat_keys": ["goals", "assists", "shots", "passes_completed", "tackles"],
    "stats_title": "Match statistics",
    "lineup_team": "both",               # both | A | B
    "slideshow": {"enabled": False, "interval": 12, "slides": ["lineups", "formation_home", "formation_away", "stats_classic", "timeline"]},
    "popups_enabled": {"goal": True, "card": True, "sub": True, "var": True, "penalty": True, "period": True, "added_time": True},
    "shootout_auto": True,               # show the shoot-out tracker automatically while a shoot-out is in progress
    "position": "top-left",              # top-left | top-right | bottom
    "scale": 1.0,
    "hold": False,
    "popup": None,
    "version": 0,
}


def default_graphics(sport: str) -> Dict[str, Any]:
    return copy.deepcopy(FOOTBALL_GRAPHICS if sport == "football" else DEFAULT_GRAPHICS)


def light(state: Dict[str, Any]) -> Dict[str, Any]:
    s = copy.deepcopy(state)
    if s.get("sport") == "football":
        s.pop("event_status", None)
        s["server_time"] = now_ms()
        return s
    for i in s.get("innings", []):
        i.pop("balls", None)
    s.pop("event_status", None)
    s["server_time"] = now_ms()
    return s


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.subs: Dict[str, List[queue.Queue]] = {}

    def subscribe(self, ch: str, q: Optional[queue.Queue] = None, tag: Optional[str] = None) -> queue.Queue:
        q = q or queue.Queue(maxsize=50)
        with self.lock:
            self.subs.setdefault(ch, []).append((q, tag))
        return q

    def unsubscribe(self, ch: str, q: queue.Queue):
        with self.lock:
            self.subs[ch] = [t for t in self.subs.get(ch, []) if t[0] is not q]

    def emit(self, ch: str, event: str, data: str):
        with self.lock:
            targets = list(self.subs.get(ch, []))
        for q, tag in targets:
            event = tag or event
            try:
                q.put_nowait((event, data))
            except queue.Full:       # slow client: drop its backlog, it will resync on next message
                try:
                    while True:
                        q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait((event, data))
                except queue.Full:
                    pass


class App:
    def __init__(self, data_dir: str, out_dir: str, pin: Optional[str] = None):
        self.store = Store(data_dir)
        self.out = OutputWriter(out_dir)
        self.hub = Hub()
        self.pin = pin or None
        self.gdir = os.path.join(os.path.abspath(data_dir), "graphics")
        os.makedirs(self.gdir, exist_ok=True)
        self.graphics: Dict[str, Dict[str, Any]] = {}
        self.published: Dict[str, Dict[str, Any]] = {}
        self.pending: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self.plock = threading.RLock()
        self.stop = threading.Event()
        for mid in list(self.store.matches):
            self._load_graphics(mid)
            self._publish_now(mid, immediate=True)
        threading.Thread(target=self._delay_loop, daemon=True).start()
        threading.Thread(target=self._clock_loop, daemon=True).start()

    # ---- graphics -------------------------------------------------------- #
    def _load_graphics(self, mid):
        g = default_graphics(S.sport_of(self.store.get(mid)))
        p = os.path.join(self.gdir, mid + ".json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    saved = json.load(f)
                g["panels"].update(saved.pop("panels", {}))
                g["popups_enabled"].update(saved.pop("popups_enabled", {}))
                g["banner"].update(saved.pop("banner", {}))
                saved = {k: v for k, v in saved.items() if k in g}
                g.update(saved)
            except Exception:
                pass
        g["popup"] = None
        self.graphics[mid] = g
        return g

    def get_graphics(self, mid):
        return self.graphics.get(mid) or self._load_graphics(mid)

    def patch_graphics(self, mid: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self.plock:
            g = self.get_graphics(mid)
            was_hold = g["hold"]
            fb = self.store.get(mid).get("sport") == "football"
            for k, v in patch.items():
                if k in ("panels", "popups_enabled", "banner") and isinstance(v, dict):
                    if k == "panels" and fb:
                        for pk, pv in v.items():
                            if pk not in g["panels"]:
                                continue
                            g["panels"][pk] = bool(pv)
                            if pv:                      # exclusive groups: turning one on turns its rivals off
                                for grp in EXCLUSIVE_GROUPS:
                                    if pk in grp:
                                        for other in grp:
                                            if other != pk:
                                                g["panels"][other] = False
                    else:
                        g[k].update(v)
                elif k in g and k not in ("version", "popup"):
                    g[k] = v
            g["version"] += 1
            self._save_graphics(mid)
            if was_hold and not g["hold"]:
                self._publish_now(mid, immediate=True)
            else:
                self._emit_pub(mid)
            return g

    def trigger_popup(self, mid: str, kind: str, text: str = "") -> Dict[str, Any]:
        with self.plock:
            g = self.get_graphics(mid)
            g["popup"] = {"id": E.new_id("p"), "kind": kind, "text": text, "ts": now_ms()}
            g["version"] += 1
            self._emit_pub(mid)
            return g

    def _save_graphics(self, mid):
        g = copy.deepcopy(self.graphics[mid])
        g["popup"] = None
        try:
            atomic_write(os.path.join(self.gdir, mid + ".json"), json.dumps(g))
        except Exception:
            pass

    # ---- state publishing ----------------------------------------------- #
    def state(self, mid: str) -> Dict[str, Any]:
        with self.store.lock:
            return S.derive(copy.deepcopy(self.store.get(mid)))

    def on_change(self, mid: str):
        """Called after every successful mutation."""
        st = self.state(mid)
        v = self.store.get(mid)["version"]
        self.hub.emit(f"live:{mid}", "update", json.dumps({"state": light(st), "version": v}))
        self._publish_now(mid, state=st)

    def _publish_now(self, mid: str, state=None, immediate=False):
        with self.plock:
            g = self.get_graphics(mid)
            st = state or self.state(mid)
            ls = light(st)
            delay = float(self.store.settings.get("publish_delay") or 0)
            if g["hold"]:
                self.pending[mid] = (time.time(), ls)
                self._emit_pub(mid)           # graphics may have changed; state stays frozen
                return
            if delay > 0 and not immediate and mid in self.published:
                self.pending[mid] = (time.time() + delay, ls)
                return
            self.pending.pop(mid, None)
            self.published[mid] = ls
        self._write_outputs(mid)
        self._emit_pub(mid)

    def _delay_loop(self):
        while not self.stop.wait(0.2):
            due: List[str] = []
            with self.plock:
                now = time.time()
                for mid, (t, ls) in list(self.pending.items()):
                    g = self.graphics.get(mid)
                    if g and g["hold"]:
                        continue
                    if t <= now:
                        self.published[mid] = ls
                        del self.pending[mid]
                        due.append(mid)
            for mid in due:
                try:
                    self._write_outputs(mid)
                    self._emit_pub(mid)
                except Exception:
                    pass

    def _clock_loop(self):
        """Football: rewrite clock.txt & friends once a second while a clock is running (OBS text sources read files)."""
        while not self.stop.wait(1.0):
            try:
                with self.plock:
                    mids = [m for m, st in self.published.items() if st.get("sport") == "football" and st["clock"]["running"]]
                for mid in mids:
                    self._write_outputs(mid)
            except Exception:
                pass

    def _emit_pub(self, mid: str):
        payload = json.dumps(self.pub_payload(mid))
        self.hub.emit(f"pub:{mid}", "update", payload)
        if self.store.settings.get("live_match_id") == mid:
            self.hub.emit("pub:live", "update", payload)

    def pub_payload(self, mid: str) -> Dict[str, Any]:
        st = self.published.get(mid)
        if st is None:
            st = light(self.state(mid))
        g = self.get_graphics(mid)
        return {"state": {**st, "server_time": now_ms()}, "graphics": g,
                "delay": float(self.store.settings.get("publish_delay") or 0)}

    def _write_outputs(self, mid: str):
        st = self.published.get(mid)
        if not st:
            return
        try:
            self.out.write(mid, st, self.get_graphics(mid), self.store.settings.get("live_match_id") == mid,
                           float(self.store.settings.get("publish_delay") or 0))
        except Exception as e:  # never let a disk problem stop scoring
            print(f"[outputs] write failed: {e}")

    def resolve(self, mid: str) -> str:
        if mid == "live":
            lid = self.store.settings.get("live_match_id")
            if not lid or lid not in self.store.matches:
                raise StoreError(404, {"message": "No live match selected"})
            return lid
        return mid

    def set_live(self, mid: str):
        self.store.get(mid)
        self.store.settings["live_match_id"] = mid
        self.store.save_settings()
        self._write_outputs(mid)
        self.hub.emit("pub:live", "update", json.dumps(self.pub_payload(mid)))


def local_ips() -> List[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "GoScore/2.0"
    protocol_version = "HTTP/1.1"
    app: App = None  # type: ignore

    def log_message(self, fmt, *args):
        if os.environ.get("GOSCORE_LOG"):
            super().log_message(fmt, *args)

    # ---- low-level helpers --------------------------------------------- #
    def _send(self, status: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, status: int, payload: Dict[str, Any]):
        self._json(payload, status)

    def _body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        if n > 8 * 1024 * 1024:
            raise StoreError(413, {"message": "Request body is too large (maximum 8 MB)."})
        raw = self.rfile.read(n)
        try:
            v = json.loads(raw.decode("utf-8"))
            return v if isinstance(v, (dict, list)) else {}
        except Exception:
            raise StoreError(400, {"message": "Invalid JSON body"})

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_HEAD(self):
        self.do_GET()

    def _check_pin(self):
        if self.app.pin and self.headers.get("X-Pin") != self.app.pin:
            raise StoreError(401, {"message": "PIN required (or wrong PIN).", "code": "pin"})

    # ---- dispatch ---------------------------------------------------------- #
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if path.startswith("/api/") or path.startswith("/feed/"):
                if method != "GET":
                    self._check_pin()
                return self._api(method, path, q)
            if method == "GET":
                return self._static(path)
            self._err(405, {"message": "Method not allowed"})
        except StoreError as e:
            self._err(e.status, e.payload)
        except OSError:                  # client went away (reload / closed tab): not an error
            pass
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._err(500, {"message": f"Server error: {type(e).__name__}: {e}"})
            except Exception:
                pass

    # ---- static -------------------------------------------------------------- #
    PAGES = {"": "index.html", "score": "score.html", "control": "control.html", "overlay": "overlay.html",
             "scorecard": "scorecard.html", "setup": "setup.html"}

    def _static(self, path: str):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "uploads" and parts[1] == "logos" and re.fullmatch(r"[a-f0-9]{24}\.(?:png|jpg|gif|webp)", parts[2]):
            full = os.path.join(self.app.store.dir, "logos", parts[2])
            if not os.path.isfile(full):
                return self._err(404, {"message": "Not found"})
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype, {"X-Content-Type-Options": "nosniff"})
            return
        if not parts:
            rel = "index.html"
        elif parts[0] in self.PAGES and len(parts) <= 2:
            rel = self.PAGES[parts[0]]
        elif parts[0] == "static":
            rel = "/".join(parts[1:])
        else:
            rel = "/".join(parts)
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._err(404, {"message": "Not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- SSE ------------------------------------------------------------------- #
    def _sse(self, mid_raw: str, ch: str):
        mid = self.app.resolve(mid_raw)
        pkey = f"pub:{mid_raw if mid_raw == 'live' else mid}"
        lkey = f"live:{mid}"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=50)
        keys = []
        if ch == "both":
            self.app.hub.subscribe(lkey, q, "live"); self.app.hub.subscribe(pkey, q, "pub"); keys = [lkey, pkey]
        elif ch == "live":
            self.app.hub.subscribe(lkey, q); keys = [lkey]
        else:
            self.app.hub.subscribe(pkey, q); keys = [pkey]
        try:
            if ch in ("live", "both"):
                st = self.app.state(mid)
                self._sse_write("live" if ch == "both" else "update",
                                json.dumps({"state": light(st), "version": self.app.store.get(mid)["version"]}))
            if ch in ("pub", "both"):
                self._sse_write("pub" if ch == "both" else "update", json.dumps(self.app.pub_payload(mid)))
            while not self.app.stop.is_set():
                try:
                    ev, data = q.get(timeout=10)
                    self._sse_write(ev, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except OSError:
            pass
        finally:
            for k in keys:
                self.app.hub.unsubscribe(k, q)
        self.close_connection = True

    def _sse_write(self, event: str, data: str):
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    # ---- API ------------------------------------------------------------------ #
    def _api(self, method: str, path: str, q: Dict[str, str]):
        app, store = self.app, self.app.store
        seg = [s for s in path.split("/") if s]

        # ---- feeds
        if seg[0] == "feed":
            return self._feed(seg, q)

        # seg[0] == 'api'
        if seg == ["api", "info"]:
            from . import __version__
            return self._json({"name": "GoScore", "sports": list(S.SPORTS), "version": __version__, "engine": E.ENGINE_VERSION, "ips": local_ips(),
                               "port": self.server.server_address[1], "pin_required": bool(app.pin),
                               "live_match_id": store.settings.get("live_match_id"),
                               "output_dir": app.out.base})
        if seg == ["api", "health"]:
            return self._json({"ok": True, "time": now_ms()})
        # Shared overlay geometry is persisted by the local GoScore server so the
        # layout editor and /overlay/live (including OBS Browser Sources) use one layout.
        if len(seg) == 3 and seg[:2] == ["api", "layout"] and seg[2] in ("cricket", "football"):
            layout_path = os.path.join(store.dir, "overlay_layouts.json")
            layouts = {}
            try:
                with open(layout_path, "r", encoding="utf-8") as fh:
                    layouts = json.load(fh)
                if not isinstance(layouts, dict): layouts = {}
            except (OSError, ValueError):
                layouts = {}
            sport = seg[2]
            if method == "GET":
                return self._json({"sport": sport, "layout": layouts.get(sport, {})})
            if method in ("PUT", "POST"):
                body = self._body()
                candidate = body.get("layout", {}) if isinstance(body, dict) else {}
                if not isinstance(candidate, dict) or len(candidate) > 100:
                    return self._err(400, {"message": "Invalid overlay layout."})
                clean = {}
                for key, val in candidate.items():
                    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) or not isinstance(val, dict):
                        continue
                    try:
                        x, y = float(val.get("x", 0)), float(val.get("y", 0))
                        w, h = float(val.get("w", 0)), float(val.get("h", 0))
                    except (TypeError, ValueError):
                        continue
                    if all(map(lambda n: n == n and abs(n) < 10000, (x,y,w,h))) and 40 <= w <= 1920 and 24 <= h <= 1080:
                        clean[key] = {"x": max(0, min(1920-w, x)), "y": max(0, min(1080-h, y)), "w": w, "h": h}
                layouts[sport] = clean
                os.makedirs(store.dir, exist_ok=True)
                tmp = layout_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(layouts, fh, separators=(",", ":"))
                os.replace(tmp, layout_path)
                return self._json({"ok": True, "sport": sport, "layout": clean})
            return self._err(405, {"message": "Method not allowed"})
        if seg == ["api", "logos"] and method == "POST":
            body = self._body()
            data = body.get("data", "") if isinstance(body, dict) else ""
            match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", data or "")
            if not match:
                return self._err(400, {"message": "Unsupported image. Choose a PNG, JPEG, GIF, or WebP file."})
            ext = {"jpeg": "jpg"}.get(match.group(1), match.group(1))
            try:
                image_bytes = base64.b64decode(match.group(2), validate=True)
            except (ValueError, base64.binascii.Error):
                return self._err(400, {"message": "Invalid image data."})
            if not image_bytes or len(image_bytes) > 2 * 1024 * 1024:
                return self._err(413, {"message": "Logo image must be between 1 byte and 2 MB."})
            # Check the file signature rather than trusting the browser-supplied MIME type.
            signatures = {"png": image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
                          "jpg": image_bytes.startswith(b"\xff\xd8\xff"),
                          "gif": image_bytes.startswith((b"GIF87a", b"GIF89a")),
                          "webp": len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP"}
            if not signatures.get(ext, False):
                return self._err(400, {"message": "The selected file does not match its image type."})
            logo_dir = os.path.join(store.dir, "logos")
            os.makedirs(logo_dir, exist_ok=True)
            name = hashlib.sha256(image_bytes).hexdigest()[:24] + "." + ext
            with open(os.path.join(logo_dir, name), "wb") as image_file:
                image_file.write(image_bytes)
            return self._json({"url": "/uploads/logos/" + name})
        if seg == ["api", "presets"]:
            return self._json({"presets": E.PRESETS, "defaults": E.DEFAULT_FORMAT,
                               "dismissals": E.DISMISSAL_NAMES, "allowed_off": {k: sorted(v) for k, v in E.ALLOWED_OFF.items()},
                               "football": {"presets": FB.PRESETS, "defaults": FB.DEFAULT_FORMAT, "team_stats": FB.TEAM_STATS,
                                            "player_stats": FB.PLAYER_STATS, "default_rows": FB.DEFAULT_STAT_ROWS,
                                            "card_reasons": FB.CARD_REASONS, "goal_kinds": FB.GOAL_KINDS,
                                            "var_kinds": FB.VAR_KINDS, "var_decisions": FB.VAR_DECISIONS,
                                            "phases": FB.PHASE_LABEL}})
        if seg == ["api", "settings"]:
            if method == "GET":
                return self._json(store.settings)
            b = self._body()
            for k in ("publish_delay", "obs", "auto_director", "live_match_id"):
                if k in b:
                    store.settings[k] = b[k]
            store.save_settings()
            if "live_match_id" in b and b["live_match_id"]:
                app.set_live(b["live_match_id"])
            elif "publish_delay" in b:
                for mid in list(store.matches):
                    app._publish_now(mid, immediate=True)
            return self._json(store.settings)
        if seg == ["api", "matches"]:
            if method == "GET":
                return self._json({"matches": store.list(), "live_match_id": store.settings.get("live_match_id")})
            m = store.create(self._body())
            app._load_graphics(m["id"])
            app.on_change(m["id"])
            return self._json({"id": m["id"]}, 201)
        if seg == ["api", "import"] and method == "POST":
            m = store.import_match(self._body())
            app._load_graphics(m["id"])
            app.on_change(m["id"])
            return self._json({"id": m["id"]}, 201)

        if len(seg) >= 3 and seg[1] == "matches":
            mid = app.resolve(seg[2])
            rest = seg[3:]
            return self._match_api(method, mid, rest, q, seg[2])
        self._err(404, {"message": "Unknown API route"})

    def _match_api(self, method, mid, rest, q, raw_id):
        app, store = self.app, self.app.store
        if not rest:
            if method == "GET":
                with store.lock:
                    return self._json(store.get(mid))
            if method == "DELETE":
                store.delete_match(mid)
                return self._json({"ok": True})
        if rest == ["meta"] and method == "GET":
            m = store.get(mid)
            return self._json({"id": mid, "sport": S.sport_of(m), "title": m.get("title")})
        if rest == ["state"] and method == "GET":
            st = app.state(mid)
            body = st if q.get("view") == "full" else light(st)
            return self._json({"state": body, "version": store.get(mid)["version"],
                               "can_redo": bool(store.redo.get(mid))})
        if rest == ["stream"] and method == "GET":
            return self._sse(raw_id, q.get("ch", "pub"))
        if rest == ["published"] and method == "GET":
            return self._json(app.pub_payload(mid))
        if rest == ["setup"] and method == "POST":
            b = self._body()
            store.update_setup(mid, b.get("patch", b), b.get("reason"))
            app.on_change(mid)
            return self._json({"ok": True, "version": store.get(mid)["version"]})
        if rest == ["events"]:
            if method == "GET":
                st = app.state(mid)
                with store.lock:
                    evs = copy.deepcopy(store.get(mid)["events"])
                return self._json({"events": evs, "status": st["event_status"],
                                   "version": store.get(mid)["version"], "can_redo": bool(store.redo.get(mid))})
            b = self._body()
            cid = b.pop("cid", None)
            ver = b.pop("expected_version", None)
            r = store.add_event(mid, b, cid=cid, expected_version=ver)
            if not r.get("duplicate"):
                app.on_change(mid)
            return self._json(r)
        if len(rest) == 2 and rest[0] == "events":
            eid = rest[1]
            if method == "PUT":
                b = self._body()
                r = store.edit_event(mid, eid, b.get("patch", {}), b.get("reason"), bool(b.get("strict")))
            elif method == "DELETE":
                r = store.delete_event(mid, eid, q.get("reason"))
            else:
                return self._err(405, {"message": "Method not allowed"})
            app.on_change(mid)
            return self._json(r)
        if rest == ["insert"] and method == "POST":
            b = self._body()
            r = store.insert_event(mid, b.get("event", {}), b.get("after_id"), b.get("before_id"), b.get("reason"))
            app.on_change(mid)
            return self._json(r)
        if rest == ["undo"] and method == "POST":
            b = self._body()
            r = store.undo(mid, b.get("expected_version"))
            app.on_change(mid)
            return self._json(r)
        if rest == ["redo"] and method == "POST":
            b = self._body()
            r = store.redo_last(mid, b.get("expected_version"))
            app.on_change(mid)
            return self._json(r)
        if rest == ["replace-events"] and method == "POST":
            b = self._body()
            r = store.replace_events(mid, b.get("events"), b.get("reason"))
            app.on_change(mid)
            return self._json(r)
        if rest == ["backups"] and method == "GET":
            return self._json({"backups": store.backups(mid)})
        if rest == ["restore"] and method == "POST":
            b = self._body()
            store.restore_backup(mid, int(b.get("version")))
            app.on_change(mid)
            return self._json({"ok": True})
        if rest == ["export"] and method == "GET":
            with store.lock:
                doc = copy.deepcopy(store.get(mid))
            return self._send(200, json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"),
                              "application/json; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="goscore-{mid}.json"'})
        if rest == ["audit"] and method == "GET":
            return self._json({"audit": store.get(mid).get("audit", [])})
        if rest == ["go-live"] and method == "POST":
            app.set_live(mid)
            return self._json({"ok": True})
        if rest == ["graphics"]:
            if method == "GET":
                return self._json(app.get_graphics(mid))
            return self._json(app.patch_graphics(mid, self._body()))
        if rest == ["graphics", "trigger"] and method == "POST":
            b = self._body()
            return self._json(app.trigger_popup(mid, b.get("kind", "custom"), b.get("text", "")))
        self._err(404, {"message": "Unknown match route"})

    # ---- feeds --------------------------------------------------------------- #
    def _feed(self, seg: List[str], q: Dict[str, str]):
        app = self.app
        if len(seg) < 2:
            return self._err(404, {"message": "Not found"})
        name = seg[1]
        ext = None
        if name.endswith(".json") or name.endswith(".xml"):
            name, ext = name.rsplit(".", 1)
        mid = app.resolve(name)
        st = app.published.get(mid) or light(app.state(mid))
        if ext == "json" and len(seg) == 2:
            full = q.get("view") == "full"
            body = app.state(mid) if full else st
            return self._json({"state": body, "graphics": app.get_graphics(mid)})
        if ext == "xml" and len(seg) == 2:
            return self._send(200, state_to_xml(st).encode("utf-8"), "application/xml; charset=utf-8")
        if len(seg) == 4 and seg[2] == "text" and seg[3].endswith(".txt"):
            tf = text_fields(st, app.get_graphics(mid))
            key = seg[3][:-4]
            if key not in tf:
                return self._err(404, {"message": "Unknown field"})
            return self._send(200, tf[key].encode("utf-8"), "text/plain; charset=utf-8")
        if len(seg) == 3 and seg[2] == "text":
            return self._json(text_fields(st, app.get_graphics(mid)))
        if len(seg) == 4 and seg[2] == "csv":
            files = csv_files(app.state(mid))
            if seg[3] not in files:
                return self._err(404, {"message": "Unknown file"})
            return self._send(200, files[seg[3]].encode("utf-8"), "text/csv; charset=utf-8")
        self._err(404, {"message": "Unknown feed"})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], OSError):   # aborted/reset connections are normal (tabs closing, OBS refresh)
            return
        super().handle_error(request, client_address)


def make_server(host: str, port: int, data_dir: str, out_dir: str, pin: Optional[str] = None) -> Tuple[Server, App]:
    app = App(data_dir, out_dir, pin)
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = Server((host, port), handler)
    return srv, app
