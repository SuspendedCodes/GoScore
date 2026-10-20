"""Crash-safe JSON storage for matches.

* every mutation is written atomically (tmp file + os.replace)
* a rolling backup is kept (every mutation of the last 100, as separate files)
* an append-only journal records every action (forensics: "what happened to my score?")
* idempotency: a client id (cid) seen before is ignored, so a double-click or a retry
  after a network blip can never score a ball twice.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from . import engine as E
from . import sports as S

BACKUP_KEEP = 100


def now_ms() -> int:
    return int(time.time() * 1000)


def atomic_write(path: str, text: str, retries: int = 8) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    last = None
    for i in range(retries):          # Windows: target may be briefly locked by OBS
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.05 * (i + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last  # type: ignore[misc]


class StoreError(Exception):
    def __init__(self, status: int, payload: Dict[str, Any]):
        super().__init__(payload.get("message", "error"))
        self.status, self.payload = status, payload


class Store:
    def __init__(self, data_dir: str):
        self.dir = os.path.abspath(data_dir)
        self.mdir = os.path.join(self.dir, "matches")
        self.bdir = os.path.join(self.dir, "backups")
        self.jdir = os.path.join(self.dir, "journal")
        for d in (self.mdir, self.bdir, self.jdir):
            os.makedirs(d, exist_ok=True)
        self.lock = threading.RLock()
        self.matches: Dict[str, Dict[str, Any]] = {}
        self.redo: Dict[str, List[Dict[str, Any]]] = {}
        self.settings_path = os.path.join(self.dir, "settings.json")
        self.settings = {"live_match_id": None, "publish_delay": 0, "obs": {}, "auto_director": {}}
        self._load()

    # ---- persistence ------------------------------------------------------- #
    def _load(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, encoding="utf-8") as f:
                    self.settings.update(json.load(f))
            except Exception:
                pass
        for fn in sorted(os.listdir(self.mdir)):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(self.mdir, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    m = json.load(f)
            except Exception:
                m = self._recover(fn[:-5])
                if m is None:
                    continue
            S.normalize_setup(m)
            self.matches[m["id"]] = m
            self.redo[m["id"]] = m.pop("redo_stack", [])

    def _recover(self, mid: str) -> Optional[Dict[str, Any]]:
        d = os.path.join(self.bdir, mid)
        if not os.path.isdir(d):
            return None
        for fn in sorted(os.listdir(d), reverse=True):
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
        return None

    def save_settings(self):
        atomic_write(self.settings_path, json.dumps(self.settings, indent=2))

    def _persist(self, m: Dict[str, Any], action: str, detail: Any = None):
        m["updated"] = now_ms()
        doc = dict(m)
        doc["redo_stack"] = self.redo.get(m["id"], [])
        text = json.dumps(doc, ensure_ascii=False)
        atomic_write(os.path.join(self.mdir, m["id"] + ".json"), text)
        try:
            bd = os.path.join(self.bdir, m["id"])
            atomic_write(os.path.join(bd, f"{m['version']:07d}.json"), text)
            files = sorted(os.listdir(bd))
            for old in files[:-BACKUP_KEEP]:
                os.remove(os.path.join(bd, old))
            with open(os.path.join(self.jdir, m["id"] + ".ndjson"), "a", encoding="utf-8") as j:
                j.write(json.dumps({"ts": now_ms(), "v": m["version"], "action": action, "detail": detail},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass   # backups are best-effort, the main write already succeeded

    # ---- helpers ------------------------------------------------------------ #
    def get(self, mid: str) -> Dict[str, Any]:
        m = self.matches.get(mid)
        if not m:
            raise StoreError(404, {"message": "Match not found"})
        return m

    def _audit(self, m, action, detail=None):
        m.setdefault("audit", []).append({"ts": now_ms(), "action": action, "detail": detail})
        m["audit"] = m["audit"][-500:]

    def summary(self, m) -> Dict[str, Any]:
        return S.summary(m, S.derive(copy.deepcopy(m)))

    def list(self) -> List[Dict[str, Any]]:
        with self.lock:
            out = [self.summary(m) for m in self.matches.values()]
        return sorted(out, key=lambda x: x.get("updated") or 0, reverse=True)

    # ---- mutations ----------------------------------------------------------- #
    def create(self, setup: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            mid = setup.get("id") or E.new_id("m")
            m = {"id": mid, "sport": setup.get("sport") if setup.get("sport") in S.SPORTS else "cricket", "title": setup.get("title") or "Match", "venue": setup.get("venue"),
                 "date": setup.get("date"), "format": setup.get("format") or {},
                 "teams": setup.get("teams") or {}, "toss": setup.get("toss") or {},
                 "events": [], "audit": [], "version": 0, "officials": setup.get("officials") or {}, "info": setup.get("info") or {},
                 "form": setup.get("form") or {"A": "", "B": ""}, "h2h": setup.get("h2h") or {"A": 0, "D": 0, "B": 0}, "setup_version": 0, "created": now_ms(),
                 "recent_cids": []}
            S.normalize_setup(m)
            self._audit(m, "create")
            m["version"] = 1
            self.matches[mid] = m
            self.redo[mid] = []
            self._persist(m, "create")
            if not self.settings.get("live_match_id"):
                self.settings["live_match_id"] = mid
                self.save_settings()
            return m

    def update_setup(self, mid: str, patch: Dict[str, Any], reason: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            before = {k: copy.deepcopy(m.get(k)) for k in ("title", "venue", "date", "format", "teams", "toss")}
            for k in ("title", "venue", "date", "toss", "officials", "info", "form", "h2h"):
                if k in patch:
                    if isinstance(m.get(k), dict) and isinstance(patch[k], dict) and k in ("officials", "info", "form", "h2h"):
                        m[k].update(patch[k])
                    else:
                        m[k] = patch[k]
            if "format" in patch:
                m["format"] = patch["format"]
            if "teams" in patch:
                for tid, t in patch["teams"].items():
                    if tid in ("A", "B"):
                        cur = m["teams"].setdefault(tid, {})
                        for kk, vv in t.items():
                            cur[kk] = vv
            S.normalize_setup(m)
            m["version"] += 1
            m["setup_version"] = m.get("setup_version", 0) + 1
            self._audit(m, "setup", {"reason": reason, "keys": list(patch.keys())})
            self._persist(m, "setup", {"patch_keys": list(patch.keys()), "reason": reason})
            return m

    def _check_cid(self, m, cid):
        if cid and cid in m.get("recent_cids", []):
            return True
        if cid:
            m.setdefault("recent_cids", []).append(cid)
            m["recent_cids"] = m["recent_cids"][-200:]
        return False

    def _bump(self, m, expected_version):
        if expected_version is not None and int(expected_version) != m["version"]:
            raise StoreError(409, {"message": "This match was changed on another device. Refreshed - please check and retry.",
                                   "code": "version_conflict", "version": m["version"]})

    def add_event(self, mid: str, event: Dict[str, Any], cid: Optional[str] = None,
                  expected_version: Optional[int] = None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            if self._check_cid(m, cid):
                return {"duplicate": True, "version": m["version"]}
            self._bump(m, expected_version)
            ev = {k: v for k, v in event.items() if k not in ("seq",)}
            ev["id"] = E.new_id("e")
            ev["ts"] = now_ms()
            S.prepare_event(m, ev)
            err = S.validate_append(m, ev)
            if err:
                if cid:
                    m["recent_cids"].remove(cid)
                raise StoreError(422, {"message": err["message"], "error": err})
            m["events"].append(ev)
            self.redo[mid] = []
            m["version"] += 1
            self._persist(m, "event", {"id": ev["id"], "type": ev["type"]})
            return {"event": ev, "version": m["version"]}

    def undo(self, mid: str, expected_version=None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            self._bump(m, expected_version)
            if not m["events"]:
                raise StoreError(422, {"message": "Nothing to undo."})
            ev = m["events"].pop()
            self.redo.setdefault(mid, []).append(ev)
            m["version"] += 1
            self._audit(m, "undo", {"event": ev.get("id"), "type": ev.get("type")})
            self._persist(m, "undo", ev.get("id"))
            return {"undone": ev, "version": m["version"]}

    def redo_last(self, mid: str, expected_version=None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            self._bump(m, expected_version)
            stack = self.redo.get(mid) or []
            if not stack:
                raise StoreError(422, {"message": "Nothing to redo."})
            ev = stack.pop()
            err = S.validate_append(m, ev)
            if err:
                raise StoreError(422, {"message": "Cannot redo: " + err["message"], "error": err})
            m["events"].append(ev)
            m["version"] += 1
            self._audit(m, "redo", {"event": ev.get("id")})
            self._persist(m, "redo", ev.get("id"))
            return {"redone": ev, "version": m["version"]}

    def _find(self, m, eid) -> int:
        for i, e in enumerate(m["events"]):
            if e.get("id") == eid:
                return i
        raise StoreError(404, {"message": "Event not found"})

    def edit_event(self, mid: str, eid: str, patch: Dict[str, Any], reason: Optional[str] = None,
                   strict: bool = False) -> Dict[str, Any]:
        """Edit any field of any event. Later events that stop making sense are flagged, not lost."""
        with self.lock:
            m = self.get(mid)
            i = self._find(m, eid)
            old = copy.deepcopy(m["events"][i])
            new = {**old, **{k: v for k, v in patch.items() if k not in ("id", "ts")}}
            for k, v in list(new.items()):
                if v is None and k in patch and k not in ("wicket",):
                    pass
            if patch.get("wicket", "keep") is None:
                new.pop("wicket", None)
            new["edited"] = True
            m["events"][i] = new
            errs = [e for e in S.derive(copy.deepcopy(m))["integrity"]["errors"]]
            if strict and errs:
                m["events"][i] = old
                raise StoreError(422, {"message": "Edit would invalidate later events: " + errs[0]["message"],
                                       "errors": errs})
            m["version"] += 1
            self._audit(m, "edit_event", {"event": eid, "before": old, "after": new, "reason": reason})
            self._persist(m, "edit_event", {"event": eid})
            self.redo[mid] = []
            return {"version": m["version"], "errors": errs}

    def delete_event(self, mid: str, eid: str, reason: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            i = self._find(m, eid)
            ev = m["events"].pop(i)
            m["version"] += 1
            self._audit(m, "delete_event", {"event": ev, "reason": reason})
            self._persist(m, "delete_event", eid)
            self.redo[mid] = []
            errs = S.derive(copy.deepcopy(m))["integrity"]["errors"]
            return {"version": m["version"], "errors": errs, "deleted": ev}

    def insert_event(self, mid: str, event: Dict[str, Any], after_id: Optional[str] = None,
                     before_id: Optional[str] = None, reason: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            m = self.get(mid)
            ev = {k: v for k, v in event.items() if k not in ("seq",)}
            ev["id"] = E.new_id("e")
            ev["ts"] = now_ms()
            ev["inserted"] = True
            if after_id:
                idx = self._find(m, after_id) + 1
            elif before_id:
                idx = self._find(m, before_id)
            else:
                idx = len(m["events"])
            m["events"].insert(idx, ev)
            errs = S.derive(copy.deepcopy(m))["integrity"]["errors"]
            m["version"] += 1
            self._audit(m, "insert_event", {"event": ev, "at": idx, "reason": reason})
            self._persist(m, "insert_event", ev["id"])
            self.redo[mid] = []
            return {"event": ev, "version": m["version"], "errors": errs}

    def replace_events(self, mid: str, events: List[Dict[str, Any]], reason: Optional[str] = None) -> Dict[str, Any]:
        """Advanced: replace the whole log (raw JSON editor / restore)."""
        with self.lock:
            m = self.get(mid)
            if not isinstance(events, list) or not all(isinstance(e, dict) and e.get("type") for e in events):
                raise StoreError(422, {"message": "Events must be a list of objects with a 'type'."})
            seen = set()
            for e in events:
                if not e.get("id") or e["id"] in seen:
                    e["id"] = E.new_id("e")
                seen.add(e["id"])
                e.setdefault("ts", now_ms())
            old = m["events"]
            m["events"] = events
            m["version"] += 1
            self._audit(m, "replace_events", {"count_before": len(old), "count_after": len(events), "reason": reason})
            self._persist(m, "replace_events")
            self.redo[mid] = []
            return {"version": m["version"], "errors": S.derive(copy.deepcopy(m))["integrity"]["errors"]}

    def restore_backup(self, mid: str, version: int) -> Dict[str, Any]:
        with self.lock:
            p = os.path.join(self.bdir, mid, f"{int(version):07d}.json")
            if not os.path.exists(p):
                raise StoreError(404, {"message": "Backup not found"})
            with open(p, encoding="utf-8") as f:
                old = json.load(f)
            m = self.get(mid)
            keep_v = m["version"]
            old["audit"] = m.get("audit", []) + [{"ts": now_ms(), "action": "restore_backup", "detail": {"from": version}}]
            old["version"] = keep_v + 1
            old.pop("redo_stack", None)
            self.matches[mid] = old
            self.redo[mid] = []
            self._persist(old, "restore_backup", version)
            return old

    def backups(self, mid: str) -> List[Dict[str, Any]]:
        d = os.path.join(self.bdir, mid)
        out = []
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d), reverse=True)[:60]:
                p = os.path.join(d, fn)
                out.append({"version": int(fn.split(".")[0]), "mtime": int(os.path.getmtime(p) * 1000),
                            "size": os.path.getsize(p)})
        return out

    def import_match(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            doc.pop("redo_stack", None)
            if not doc.get("id") or doc["id"] in self.matches:
                doc["id"] = E.new_id("m")
            doc.setdefault("version", 1)
            S.normalize_setup(doc)
            self.matches[doc["id"]] = doc
            self.redo[doc["id"]] = []
            self._persist(doc, "import")
            return doc

    def delete_match(self, mid: str):
        with self.lock:
            self.get(mid)
            p = os.path.join(self.mdir, mid + ".json")
            arch = os.path.join(self.dir, "deleted")
            os.makedirs(arch, exist_ok=True)
            if os.path.exists(p):
                os.replace(p, os.path.join(arch, f"{mid}-{now_ms()}.json"))
            self.matches.pop(mid, None)
            if self.settings.get("live_match_id") == mid:
                self.settings["live_match_id"] = None
                self.save_settings()
