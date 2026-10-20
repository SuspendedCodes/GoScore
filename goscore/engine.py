"""
GoScore cricket engine  (v2 - rewritten)
=========================================

Event-sourced scoring: the ordered event log is the single source of truth and
``derive(match)`` replays it into a complete scoreboard.  Nothing is ever
stored as a running total, so edits / deletions / insertions / undo are all
just "change the log, replay".

Design rules
------------
* Rules of the game are enforced (Laws of Cricket + ICC limited-overs playing
  conditions).  A ball that breaks a Law is rejected with an explanation.
  Competition-specific restrictions (bowler quota, consecutive overs, ...) are
  *soft*: they are rejected unless the scorer explicitly forces them, and a
  forced rule is recorded in the audit trail.
* The engine never crashes on a bad log.  An event that cannot be applied is
  flagged ``invalid`` (with the reason) and skipped, so the scoreboard stays
  consistent and the scorer can fix the event.
* Manual override is first-class: ``override`` events pin any displayed value
  at a point in the log, later balls build on top of the pinned value.

Pure python, standard library only.
"""
from __future__ import annotations

import copy
import math
import re
import uuid
from typing import Any, Dict, List, Optional

ENGINE_VERSION = "2.0"

# --------------------------------------------------------------------------- #
# Laws / constants
# --------------------------------------------------------------------------- #
DISMISSAL_NAMES = {
    "bowled": "Bowled", "caught": "Caught", "lbw": "LBW", "run_out": "Run out",
    "stumped": "Stumped", "hit_wicket": "Hit wicket", "hit_twice": "Hit the ball twice",
    "obstructing": "Obstructing the field", "timed_out": "Timed out",
    "retired_out": "Retired out",
}
BALL_DISMISSALS = ["bowled", "caught", "lbw", "run_out", "stumped", "hit_wicket",
                   "hit_twice", "obstructing"]

# Wickets credited to the bowler (Law / standard scoring practice).
BOWLER_CREDIT = {"bowled", "caught", "lbw", "stumped", "hit_wicket"}
# Dismissals that can only fall to the striker.
STRIKER_ONLY = {"bowled", "caught", "lbw", "stumped", "hit_wicket", "hit_twice"}
# Ball is dead on the dismissal: no runs from the delivery count (only no-ball /
# wide penalty runs).
NO_RUNS_KINDS = {"bowled", "caught", "lbw", "stumped", "hit_wicket"}
# Law 21.18 (no ball), Law 22.9 (wide); free hit uses the no-ball list.
ALLOWED_OFF = {
    "legal": set(BALL_DISMISSALS),
    "noball": {"run_out", "hit_twice", "obstructing"},
    "wide": {"run_out", "stumped", "hit_wicket", "obstructing"},
}
PLAYER_ROLES = ("batter", "bowler", "allrounder")
FREE_HIT_ALLOWED = {"run_out", "hit_twice", "obstructing"}

# --------------------------------------------------------------------------- #
# Format presets  (all values editable per match - "home rules")
# --------------------------------------------------------------------------- #
BREAK_KINDS = {"drinks": "Drinks", "lunch": "Lunch", "tea": "Tea", "stumps": "Stumps", "rain": "Rain delay",
               "bad_light": "Bad light", "injury": "Injury", "other": "Play suspended"}

PRESETS: Dict[str, Dict[str, Any]] = {
    "t20": {"label": "T20", "overs": 20, "balls_per_over": 6, "innings_per_side": 1,
            "powerplays": [{"name": "Powerplay", "from_over": 1, "to_over": 6}]},
    "t10": {"label": "T10", "overs": 10, "balls_per_over": 6, "innings_per_side": 1,
            "powerplays": []},
    "odi": {"label": "ODI (50 overs)", "overs": 50, "balls_per_over": 6, "innings_per_side": 1,
            "powerplays": [{"name": "Powerplay 1", "from_over": 1, "to_over": 10},
                           {"name": "Powerplay 2", "from_over": 11, "to_over": 40},
                           {"name": "Powerplay 3", "from_over": 41, "to_over": 50}]},
    "list_a_40": {"label": "40 overs", "overs": 40, "balls_per_over": 6, "innings_per_side": 1,
                  "powerplays": []},
    "hundred": {"label": "100 balls", "overs": 20, "balls_per_over": 5, "innings_per_side": 1,
                "max_consecutive_overs": 2, "max_overs_per_bowler": 4,
                "powerplays": [{"name": "Powerplay", "from_over": 1, "to_over": 5}],
                "display": "balls"},
    "custom": {"label": "Custom", "overs": 10, "balls_per_over": 6, "innings_per_side": 1,
               "powerplays": []},
    "multi_day": {"label": "Multi-day (2 innings a side)", "overs": None, "balls_per_over": 6,
                  "innings_per_side": 2, "free_hit": False, "powerplays": [],
                  "max_overs_per_bowler": None, "days": None, "overs_per_day": 90, "new_ball_after": 80},
}

DEFAULT_FORMAT = {
    "preset": "t20", "label": "T20", "overs": 20, "balls_per_over": 6,
    "innings_per_side": 1, "free_hit": True, "wide_penalty": 1, "noball_penalty": 1,
    "max_overs_per_bowler": "auto",          # "auto" = ceil(overs/5); None = unlimited
    "allow_consecutive_overs": False, "max_consecutive_overs": 1,
    "wickets_limit": None,                   # None = players in XI - 1
    "powerplays": [], "display": "overs",
    "super_over": {"enabled": True, "overs": 1, "wickets": 2},
}


def make_format(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(cfg or {})
    preset = cfg.get("preset") or "t20"
    fmt = copy.deepcopy(DEFAULT_FORMAT)
    fmt.update(copy.deepcopy(PRESETS.get(preset, PRESETS["t20"])))
    fmt["preset"] = preset if preset in PRESETS else "custom"
    for k, v in cfg.items():
        if k == "super_over" and isinstance(v, dict):
            fmt["super_over"].update(v)
        elif v is not None or k in ("overs", "max_overs_per_bowler", "wickets_limit"):
            fmt[k] = v
    fmt["balls_per_over"] = max(1, int(fmt.get("balls_per_over") or 6))
    if fmt.get("overs") is not None:
        fmt["overs"] = max(1, int(fmt["overs"]))
    fmt["innings_per_side"] = 2 if int(fmt.get("innings_per_side") or 1) >= 2 else 1
    if fmt["innings_per_side"] == 2:
        # multi-day knobs (all optional): days of play, overs per day (Law 12 minimum 90 in a Test), new ball after N overs (80 in a Test)
        for k, dflt in (("days", None), ("overs_per_day", 90), ("new_ball_after", 80)):
            v = fmt.get(k, dflt)
            try:
                v = int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                v = dflt
            fmt[k] = v if (v is None or v > 0) else None
    fmt["wide_penalty"] = int(fmt.get("wide_penalty", 1) or 0)
    fmt["noball_penalty"] = int(fmt.get("noball_penalty", 1) or 0)
    return fmt


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class RuleError(Exception):
    def __init__(self, code: str, message: str, hint: Optional[str] = None, soft: bool = False):
        super().__init__(message)
        self.code, self.message, self.hint, self.soft = code, message, hint, soft

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint, "soft": self.soft}


def new_id(prefix: str = "e") -> str:
    return prefix + uuid.uuid4().hex[:10]


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _fmt_overs(balls: int, bpo: int) -> str:
    return f"{balls // bpo}.{balls % bpo}"


# --------------------------------------------------------------------------- #
# Setup normalisation
# --------------------------------------------------------------------------- #
def normalize_setup(match: Dict[str, Any]) -> Dict[str, Any]:
    """Fill defaults so the engine can rely on them. Mutates and returns match."""
    match.setdefault("events", [])
    match.setdefault("format", {})
    teams = match.setdefault("teams", {})
    for tid, default_name in (("A", "Team A"), ("B", "Team B")):
        t = teams.setdefault(tid, {})
        t.setdefault("name", default_name)
        t.setdefault("short", re.sub(r"[^A-Za-z0-9]", "", t["name"])[:3].upper() or tid)
        t.setdefault("color", "#1f6feb" if tid == "A" else "#d4351c")
        t.setdefault("players", [])
        used = {p.get("id") for p in t["players"] if p.get("id")}
        n = 0
        for idx, p in enumerate(t["players"]):
            if not p.get("id"):
                while f"{tid}{n + 1}" in used:
                    n += 1
                p["id"] = f"{tid}{n + 1}"
                used.add(p["id"])
            p.setdefault("name", p["id"])
            p.setdefault("short", _short_name(p["name"]))
            if p.get("role") not in PLAYER_ROLES:
                p["role"] = ""            # '' = not set
            p["wk"] = bool(p.get("wk"))               # wicketkeeper (marked † on scorecards)
            p["captain"] = bool(p.get("captain"))     # captain (marked (c))
            if "xi" not in p:
                p["xi"] = idx < 11
    match.setdefault("toss", {})
    return match


def _short_name(name: str) -> str:
    parts = [x for x in re.split(r"\s+", (name or "").strip()) if x]
    if len(parts) <= 1:
        return name or ""
    initials = "".join(p[0].upper() for p in parts[:-1])
    return f"{initials} {parts[-1]}"


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class _Replay:
    def __init__(self, match: Dict[str, Any]):
        self.match = match
        self.fmt = make_format(match.get("format"))
        self.bpo = self.fmt["balls_per_over"]
        self.teams = match["teams"]
        self.pl: Dict[str, Dict[str, Any]] = {}
        for tid, t in self.teams.items():
            for p in t["players"]:
                self.pl[p["id"]] = {"team": tid, **p}
        # dynamic XI membership (substitutions change it)
        self.xi = {tid: {p["id"] for p in t["players"] if p.get("xi", True)}
                   for tid, t in self.teams.items()}
        self.subbed_out: set = set()
        self.innings: List[Dict[str, Any]] = []
        self.pending_penalty = {"A": 0, "B": 0}
        self.pending_rev: Dict[int, Dict[str, Any]] = {}
        self.explicit_result: Optional[Dict[str, Any]] = None
        self.info: List[Dict[str, Any]] = []        # delays etc.
        self.delay: Optional[str] = None
        self.delay_kind: Optional[str] = None
        self.advance: Optional[str] = None          # lunch / tea / stumps waiting for "resume" to move the session/day on
        self.day = 1
        self.session = 1
        self.day_base = {"runs": 0, "wickets": 0, "balls": 0}
        self.session_base = {"runs": 0, "wickets": 0, "balls": 0}
        self.new_ball_base = 0                      # total legal balls bowled when the current ball was taken
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.applied_overrides: List[Dict[str, Any]] = []
        self.last_event: Optional[Dict[str, Any]] = None
        self.event_status: Dict[str, Dict[str, Any]] = {}

    # ---- helpers ---------------------------------------------------------- #
    def name(self, pid: Optional[str]) -> str:
        if pid is None:
            return ""
        p = self.pl.get(pid)
        return p["name"] if p else str(pid)

    def tag(self, pid: Optional[str]) -> str:
        p = self.pl.get(pid) if pid else None
        if not p:
            return ""
        return (" (c)" if p.get("captain") else "") + (" †" if p.get("wk") else "")

    def fname(self, pid) -> str:
        """Fielder name for dismissal text; the keeper is written †Name (scorebook convention)."""
        if pid not in self.pl:
            return str(pid)
        return ("†" if self.pl[pid].get("wk") else "") + self.pl[pid]["name"]

    def keeper_of(self, tid) -> Optional[str]:
        ks = [p["id"] for p in self.teams[tid]["players"] if p.get("wk") and p["id"] in self.xi.get(tid, ())]
        return ks[0] if len(ks) == 1 else None

    def short(self, pid: Optional[str]) -> str:
        if pid is None:
            return ""
        p = self.pl.get(pid)
        return (p.get("short") or p["name"]) if p else str(pid)

    def team_of(self, pid: str) -> Optional[str]:
        p = self.pl.get(pid)
        return p["team"] if p else None

    def other(self, tid: str) -> str:
        return "B" if tid == "A" else "A"

    def cur(self) -> Dict[str, Any]:
        if not self.innings:
            raise RuleError("no_innings", "No innings has been started yet.",
                            "Start the first innings (choose openers and opening bowler).")
        return self.innings[-1]

    def get_inn(self, idx: Any) -> Dict[str, Any]:
        i = _i(idx, len(self.innings) - 1)
        if i < 0 or i >= len(self.innings):
            raise RuleError("no_innings", f"Innings {i + 1} has not been started.")
        return self.innings[i]

    def wickets_limit_for(self, tid: str, kind: str, override: Optional[int]) -> int:
        if override is not None:
            return int(override)
        if kind == "super_over":
            return int(self.fmt["super_over"].get("wickets", 2))
        if self.fmt.get("wickets_limit") is not None:
            return int(self.fmt["wickets_limit"])
        return max(1, len(self.xi[tid]) - 1)

    def quota_balls(self) -> Optional[int]:
        q = self.fmt.get("max_overs_per_bowler")
        ov = self.fmt.get("overs")
        if q == "auto":
            if not ov or self.fmt["innings_per_side"] > 1:
                return None
            return math.ceil(ov / 5) * self.bpo
        if q in (None, 0, ""):
            return None
        return int(q) * self.bpo

    def effective_target(self, inn: Dict[str, Any]) -> Optional[int]:
        """Runs required to win for the chasing innings (None if not a chase)."""
        if inn.get("target_revised") is not None:
            return inn["target_revised"]
        if inn["kind"] == "super_over":
            pos = sum(1 for i in self.innings[:inn["index"]] if i["kind"] == "super_over")
            if pos % 2 == 1:          # 2nd innings of a Super Over pair chases the 1st
                return self.innings[inn["index"] - 1]["runs"] + 1
            return None
        if self.fmt["innings_per_side"] == 1:
            if inn["index"] == 1:
                return self.innings[0]["runs"] + 1
            return None
        # multi-innings: only the last (4th) innings chases
        if inn["index"] == 3:
            bt = inn["batting"]
            mine = sum(i["runs"] for i in self.innings[:3] if i["batting"] == bt)
            theirs = sum(i["runs"] for i in self.innings[:3] if i["batting"] != bt)
            return theirs - mine + 1
        return None

    # ---- innings construction -------------------------------------------- #
    def _new_innings(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        idx = len(self.innings)
        kind = ev.get("kind") or "regular"
        batting = ev.get("batting")
        if batting not in ("A", "B"):
            if idx == 0:
                toss = self.match.get("toss") or {}
                if toss.get("winner") in ("A", "B") and toss.get("decision") in ("bat", "bowl"):
                    batting = toss["winner"] if toss["decision"] == "bat" else self.other(toss["winner"])
                else:
                    batting = "A"
            elif kind == "super_over":
                # ICC T20I conditions: the team that batted second in the match bats first in the
                # Super Over; within a pair the other team chases; a repeated pair starts with
                # the team that batted last.
                n_so = sum(1 for i in self.innings if i["kind"] == "super_over")
                batting = self.innings[-1]["batting"] if n_so % 2 == 0 else self.other(self.innings[-1]["batting"])
            else:
                batting = self.other(self.innings[-1]["batting"])
        bowling = self.other(batting)
        ov = ev.get("overs_limit", None)
        if kind == "super_over":
            ov = ov if ov is not None else self.fmt["super_over"].get("overs", 1)
        elif ov is None:
            ov = self.fmt.get("overs")
        wl = self.wickets_limit_for(batting, kind, ev.get("wickets_limit"))
        rev = self.pending_rev.pop(idx, None)
        if rev:
            if rev.get("overs_limit") is not None:
                ov = rev["overs_limit"]
        inn = {
            "index": idx, "kind": kind, "batting": batting, "bowling": bowling,
            "status": "in_progress", "end_reason": None,
            "runs": 0, "wickets": 0, "legal_balls": 0, "balls_faced_total": 0,
            "overs_limit": int(ov) if ov is not None else None,
            "wickets_limit": wl, "target_revised": None, "revision": None,
            "extras": {"wide": 0, "noball": 0, "bye": 0, "legbye": 0, "penalty": 0},
            "batters": {}, "bat_order": [], "bowlers": {}, "bowl_order": [],
            "overs": [], "balls": [], "fow": [], "partnerships": [],
            "partnership": None,
            "striker": None, "non_striker": None, "bowler": None,
            "pending_batter": False, "pending_bowler": False,
            "last_over_bowlers": [], "free_hit": False,
            "declared": False, "overridden": {}, "start_ts": ev.get("ts"),
            "last_wicket": None,
        }
        if rev:
            inn["overs_limit"] = int(ov) if ov is not None else None
            inn["target_revised"] = rev.get("target")
            inn["revision"] = {"method": rev.get("method") or "manual", "note": rev.get("note"),
                               "overs_limit": inn["overs_limit"], "target": inn["target_revised"]}
        return inn

    def _batter(self, inn, pid):
        if pid not in inn["batters"]:
            inn["batters"][pid] = {"id": pid, "name": self.name(pid), "short": self.short(pid),
                                   "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dots": 0,
                                   "status": "batting", "how": None, "bowler": None,
                                   "fielders": [], "kind": None, "out_at": None, "in_at": None}
            inn["bat_order"].append(pid)
        return inn["batters"][pid]

    def _bowler(self, inn, pid):
        if pid not in inn["bowlers"]:
            inn["bowlers"][pid] = {"id": pid, "name": self.name(pid), "short": self.short(pid),
                                   "balls": 0, "runs": 0, "wickets": 0, "maidens": 0,
                                   "wides": 0, "noballs": 0, "dots": 0}
            inn["bowl_order"].append(pid)
        return inn["bowlers"][pid]

    def _check_batter_ok(self, inn, pid, allow_return=True):
        if pid not in self.pl:
            raise RuleError("unknown_player", f"Unknown player '{pid}'.")
        if self.team_of(pid) != inn["batting"]:
            raise RuleError("wrong_team", f"{self.name(pid)} is not in the batting team.")
        if pid not in self.xi[inn["batting"]]:
            raise RuleError("not_in_xi", f"{self.name(pid)} is not in the playing XI.",
                            "Add them via a substitution (impact / concussion) or edit the XI in Setup.")
        if pid in self.subbed_out:
            raise RuleError("subbed_out", f"{self.name(pid)} has been substituted out and cannot take part.")
        if pid in (inn["striker"], inn["non_striker"]):
            raise RuleError("already_batting", f"{self.name(pid)} is already at the crease.")
        b = inn["batters"].get(pid)
        if b and b["status"] == "out":
            raise RuleError("already_out", f"{self.name(pid)} is already out.")
        if b and b["status"] == "retired_hurt" and not allow_return:
            raise RuleError("retired", f"{self.name(pid)} retired hurt.")

    def _check_bowler_ok(self, inn, pid, force: set, new_over: bool):
        if pid not in self.pl:
            raise RuleError("unknown_player", f"Unknown player '{pid}'.")
        if self.team_of(pid) != inn["bowling"]:
            raise RuleError("wrong_team", f"{self.name(pid)} is not in the bowling team.")
        if pid not in self.xi[inn["bowling"]] and pid not in {b for b in inn["bowlers"]}:
            raise RuleError("not_in_xi", f"{self.name(pid)} is not in the playing XI.")
        if pid in self.subbed_out:
            raise RuleError("subbed_out", f"{self.name(pid)} has been substituted out and cannot bowl.")
        b = inn["bowlers"].get(pid)
        if new_over and "consecutive" not in force:
            prev = inn["last_over_bowlers"]
            if prev and pid in prev:
                limit = 1 if not self.fmt.get("allow_consecutive_overs") else int(self.fmt.get("max_consecutive_overs", 1))
                run = self._consecutive_overs(inn, pid)
                if run >= limit:
                    raise RuleError("consecutive_overs",
                                    f"{self.name(pid)} cannot bowl consecutive overs (Law 17).",
                                    "Choose another bowler (or force it if your playing conditions allow).",
                                    soft=True)
        q = self.quota_balls()
        if q is not None and "quota" not in force and b is not None and b["balls"] >= q:
            raise RuleError("bowler_quota",
                            f"{self.name(pid)} has bowled the maximum {q // self.bpo} overs allowed.",
                            "Choose another bowler (or force it if your tournament allows).", soft=True)

    def _consecutive_overs(self, inn, pid) -> int:
        n = 0
        for o in reversed(inn["overs"]):
            if not o["complete"]:
                continue
            if pid in o["bowlers"]:
                n += 1
            else:
                break
        return n

    # ---- partnerships ----------------------------------------------------- #
    def _begin_partnership(self, inn):
        a, b = inn["striker"], inn["non_striker"]
        inn["partnership"] = {"pair": [a, b], "runs": 0, "balls": 0, "extras": 0,
                              "contrib": {p: {"runs": 0, "balls": 0} for p in (a, b) if p},
                              "wicket_no": inn["wickets"] + 1}

    def _close_partnership(self, inn):
        p = inn["partnership"]
        if p and (p["runs"] or p["balls"]):
            inn["partnerships"].append(copy.deepcopy(p))
        inn["partnership"] = None

    # ---- over bookkeeping ------------------------------------------------- #
    def _powerplay_name(self, over_no: int) -> Optional[str]:
        for pp in self.fmt.get("powerplays") or []:
            if pp["from_over"] <= over_no <= pp["to_over"]:
                return pp["name"]
        return None

    def _ensure_over(self, inn, over_idx):
        while len(inn["overs"]) <= over_idx:
            n = len(inn["overs"])
            inn["overs"].append({"n": n + 1, "bowlers": [], "runs": 0, "wickets": 0,
                                 "balls": [], "legal": 0, "complete": False, "maiden": False,
                                 "charged": {}, "powerplay": self._powerplay_name(n + 1)})
        return inn["overs"][over_idx]

    # ---- innings end ------------------------------------------------------ #
    def _end_innings(self, inn, reason: str):
        if inn["status"] == "completed":
            return
        inn["status"] = "completed"
        inn["end_reason"] = reason
        inn["pending_batter"] = False
        inn["pending_bowler"] = False
        inn["free_hit"] = False
        if reason == "declared":
            inn["declared"] = True
        self._close_partnership(inn)

    def _check_end(self, inn):
        if inn["status"] != "in_progress":
            return
        if inn["wickets"] >= inn["wickets_limit"]:
            self._end_innings(inn, "all_out")
            return
        if inn["overs_limit"] is not None and inn["legal_balls"] >= inn["overs_limit"] * self.bpo:
            self._end_innings(inn, "overs_completed")
            return
        tgt = self.effective_target(inn)
        if tgt is not None and inn["runs"] >= tgt:
            self._end_innings(inn, "target_reached")

    # ---- event handlers --------------------------------------------------- #
    def apply(self, ev: Dict[str, Any]):
        t = ev.get("type")
        h = getattr(self, f"_ev_{t}", None)
        if h is None:
            raise RuleError("unknown_event", f"Unknown event type '{t}'.")
        h(ev)

    def _ev_innings_start(self, ev):
        force = set(ev.get("force") or [])
        if self.explicit_result and self.explicit_result.get("final"):
            raise RuleError("match_over", "The match result has been recorded.")
        if self.innings and self.innings[-1]["status"] != "completed" and "prev_open" not in force:
            raise RuleError("prev_open", "The previous innings is still in progress.",
                            "End it first (declare / all out) or force.", soft=True)
        kind = ev.get("kind") or "regular"
        reg = [i for i in self.innings if i["kind"] == "regular"]
        if kind == "regular" and len(reg) >= 2 * self.fmt["innings_per_side"]:
            raise RuleError("too_many_innings", "All scheduled innings have been played.",
                            "Use a Super Over if the match is tied.")
        inn = self._new_innings(ev)
        if inn["kind"] == "regular" and self.fmt["innings_per_side"] == 2:
            mine = [i for i in reg if i["batting"] == inn["batting"]]
            if len(mine) >= self.fmt["innings_per_side"]:
                raise RuleError("team_innings_limit", f"{self.teams[inn['batting']]['name']} have already batted twice.",
                                "Pick the other team, or fix an earlier innings (Corrections).")
            if len(reg) == 2 and inn["batting"] == reg[1]["batting"] and "follow_on" not in force:
                need = follow_on_margin(self.fmt.get("days"))
                lead = reg[0]["runs"] - reg[1]["runs"]
                if lead < need:
                    raise RuleError("follow_on", f"A follow-on needs a first-innings lead of {need}; {self.teams[reg[0]['batting']]['name']} lead by {lead}.",
                                    f"Law 14.1: 200 runs (5+ days), 150 (3-4 days), 100 (2 days), 75 (1 day). Set 'Days' in match setup, or force it if your competition differs.",
                                    soft=True)
        if inn["kind"] == "regular" and self.fmt["innings_per_side"] == 1 and self.innings:
            if inn["batting"] == self.innings[-1]["batting"] and "same_team" not in force:
                raise RuleError("same_team", "The same team cannot bat twice in a row in a one-innings match.",
                                soft=True)
        striker, non = ev.get("striker"), ev.get("non_striker")
        for p in (striker, non):
            if p:
                self._check_batter_ok(inn, p)
        if striker and striker == non:
            raise RuleError("same_batter", "Striker and non-striker must be different players.")
        self.innings.append(inn)
        inn["striker"], inn["non_striker"] = striker, non
        for p, slot in ((striker, "striker"), (non, "non_striker")):
            if p:
                b = self._batter(inn, p)
                b["in_at"] = {"runs": 0, "wickets": 0, "over": "0.0"}
        inn["pending_batter"] = not (striker and non)
        bowler = ev.get("bowler")
        if bowler:
            self._check_bowler_ok(inn, bowler, force, new_over=False)
            inn["bowler"] = bowler
            self._bowler(inn, bowler)
            self._ensure_over(inn, 0)
        else:
            inn["pending_bowler"] = True
        # penalty runs awarded to this team before it batted
        pr = self.pending_penalty.get(inn["batting"], 0)
        if pr:
            inn["extras"]["penalty"] += pr
            inn["runs"] += pr
            self.pending_penalty[inn["batting"]] = 0
        if striker and non:
            self._begin_partnership(inn)
        self._check_end(inn)

    def _ev_set_bowler(self, ev):
        inn = self.get_inn(ev.get("innings"))
        if inn["status"] != "in_progress":
            raise RuleError("innings_over", "This innings is complete.")
        pid = ev.get("bowler")
        force = set(ev.get("force") or [])
        mid_over = inn["legal_balls"] % self.bpo != 0 and inn["bowler"] is not None
        if mid_over and pid != inn["bowler"]:
            reason = ev.get("reason")
            if reason not in ("injury", "illness", "suspension", "other") and "midover" not in force:
                raise RuleError("midover_change",
                                "A bowler cannot be changed during an over except for injury, illness or suspension (Law 17).",
                                "Pick a reason (injury / illness / suspension).", soft=True)
        new_over = not mid_over or inn["bowler"] is None
        self._check_bowler_ok(inn, pid, force, new_over=(inn["legal_balls"] % self.bpo == 0))
        inn["bowler"] = pid
        inn["pending_bowler"] = False
        self._bowler(inn, pid)
        if inn["legal_balls"] % self.bpo == 0:
            self._ensure_over(inn, inn["legal_balls"] // self.bpo)

    def _ev_set_batters(self, ev):
        """Correct who is at the crease (does not count as a wicket)."""
        inn = self.get_inn(ev.get("innings"))
        s = ev.get("striker", inn["striker"])
        n = ev.get("non_striker", inn["non_striker"])
        for p, cur in ((s, inn["striker"]), (n, inn["non_striker"])):
            if p and p != cur:
                self._check_batter_ok(inn, p)
        if s and s == n:
            raise RuleError("same_batter", "Striker and non-striker must be different players.")
        inn["striker"], inn["non_striker"] = s, n
        for p in (s, n):
            if p:
                b = self._batter(inn, p)
                if b["status"] == "retired_hurt":
                    b["status"] = "batting"
                if b["in_at"] is None:
                    b["in_at"] = {"runs": inn["runs"], "wickets": inn["wickets"],
                                  "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        inn["pending_batter"] = not (inn["striker"] and inn["non_striker"]) and inn["status"] == "in_progress"
        if inn["striker"] and inn["non_striker"] and not inn["partnership"]:
            self._begin_partnership(inn)

    def _ev_new_batter(self, ev):
        """Fill the empty crease slot after a wicket / retirement."""
        inn = self.get_inn(ev.get("innings"))
        pid = ev.get("player")
        if inn["status"] != "in_progress":
            raise RuleError("innings_over", "This innings is complete.")
        if not inn["pending_batter"]:
            raise RuleError("no_slot", "There is no vacant batting position to fill.")
        self._check_batter_ok(inn, pid)
        self._place_new_batter(inn, pid, ev.get("on_strike"))

    def _place_new_batter(self, inn, pid, on_strike):
        b = self._batter(inn, pid)
        if b["status"] == "retired_hurt":
            b["status"] = "batting"
        else:
            b["status"] = "batting"
        if b["in_at"] is None:
            b["in_at"] = {"runs": inn["runs"], "wickets": inn["wickets"],
                          "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        if inn["striker"] is None:
            inn["striker"] = pid
        elif inn["non_striker"] is None:
            inn["non_striker"] = pid
        else:  # both occupied (should not happen)
            raise RuleError("no_slot", "Both batting positions are occupied.")
        if on_strike is True and inn["striker"] != pid:
            inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]
        elif on_strike is False and inn["striker"] == pid:
            inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]
        inn["pending_batter"] = not (inn["striker"] and inn["non_striker"])
        if not inn["pending_batter"]:
            self._begin_partnership(inn)

    def _ev_swap_strike(self, ev):
        inn = self.get_inn(ev.get("innings"))
        inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]

    # ---- the ball --------------------------------------------------------- #
    def _ev_ball(self, ev):
        inn = self.get_inn(ev.get("innings"))
        if inn["status"] != "in_progress":
            raise RuleError("innings_over", f"Innings {inn['index'] + 1} is already complete ({inn['end_reason']}).",
                            "Start the next innings, or edit/undo an earlier event if the innings ended by mistake.")
        if inn["pending_batter"]:
            raise RuleError("batter_required", "Select the incoming batter before scoring the next ball.")
        if inn["pending_bowler"] or not inn["bowler"]:
            raise RuleError("bowler_required", "Select the bowler for this over before scoring the next ball.")

        force = set(ev.get("force") or [])
        delivery = ev.get("delivery") or "legal"
        if delivery not in ("legal", "wide", "noball"):
            raise RuleError("bad_delivery", f"Unknown delivery type '{delivery}'.")
        bat = _i(ev.get("bat_runs"))
        byes = _i(ev.get("byes"))
        lbs = _i(ev.get("legbyes"))
        wide_runs = _i(ev.get("wide_runs"))
        boundary = bool(ev.get("boundary"))
        if min(bat, byes, lbs, wide_runs) < 0:
            raise RuleError("negative", "Runs cannot be negative.")
        if delivery == "wide" and (bat or byes or lbs):
            raise RuleError("wide_runs", "Runs run off a wide are scored as wides (Law 22).",
                            "Use 'extra wide runs' instead of bat runs / byes.")
        if delivery != "wide" and wide_runs:
            raise RuleError("wide_runs", "Extra wide runs only apply to a wide delivery.")
        if bat and (byes or lbs):
            raise RuleError("mixed_runs", "Runs cannot be both off the bat and byes/leg-byes on the same ball.")
        if byes and lbs:
            raise RuleError("mixed_runs", "A ball cannot have both byes and leg-byes.")
        tot_run_cat = bat + byes + lbs + wide_runs
        if boundary and tot_run_cat < 4:
            raise RuleError("boundary_runs", "A boundary must be worth at least 4 runs.")

        wk = ev.get("wicket") or None
        striker, non, bowler = inn["striker"], inn["non_striker"], inn["bowler"]
        kind = None
        out_pid = None
        if wk:
            kind = wk.get("kind")
            if kind not in BALL_DISMISSALS:
                raise RuleError("bad_dismissal", f"'{kind}' cannot happen on a delivery.",
                                "Timed out / retired out are recorded separately.")
            if kind not in ALLOWED_OFF[delivery]:
                dn = DISMISSAL_NAMES[kind]
                what = "a wide" if delivery == "wide" else "a no-ball"
                allowed = ", ".join(DISMISSAL_NAMES[k] for k in sorted(ALLOWED_OFF[delivery]))
                law = "Law 22.9" if delivery == "wide" else "Law 21.18"
                raise RuleError("illegal_dismissal", f"{dn} is not possible off {what} ({law}).",
                                f"Possible: {allowed}. If the umpire changed the call, set the delivery to the correct type.")
            if inn["free_hit"] and kind not in FREE_HIT_ALLOWED:
                raise RuleError("free_hit_dismissal",
                                f"{DISMISSAL_NAMES[kind]} is not possible on a free hit.",
                                "On a free hit the batter can only be run out, hit the ball twice or obstruct the field.")
            out_pid = wk.get("out") or striker
            if out_pid not in (striker, non):
                raise RuleError("out_not_at_crease", f"{self.name(out_pid)} is not at the crease.")
            if kind in STRIKER_ONLY and out_pid != striker:
                raise RuleError("striker_only",
                                f"{DISMISSAL_NAMES[kind]} applies to the striker only ({self.name(striker)}).",
                                "For the other batter use Run out / Obstructing the field.")
            if kind in NO_RUNS_KINDS and (bat or byes or lbs or wide_runs):
                raise RuleError("no_runs_on_dismissal",
                                f"No runs are scored off the ball when a batter is out {DISMISSAL_NAMES[kind]} (ball is dead).",
                                "Only the wide / no-ball penalty counts. Remove the runs from this ball.")
            nb = wk.get("new_batter")
            if nb:
                # may be a returning retired-hurt player
                if nb == out_pid:
                    raise RuleError("same_batter", "The incoming batter cannot be the dismissed batter.")
                self._check_batter_ok(inn, nb)

        # soft rule: bowler quota (bowling an extra legal ball beyond quota)
        q = self.quota_balls()
        if q is not None and delivery == "legal" and "quota" not in force:
            if inn["bowlers"].get(bowler, {"balls": 0})["balls"] + 1 > q:
                raise RuleError("bowler_quota", f"{self.name(bowler)} would exceed the maximum {q // self.bpo} overs.",
                                soft=True)

        # ------------------------- validation done, apply ------------------- #
        legal = delivery == "legal"
        over_idx = inn["legal_balls"] // self.bpo
        ov = self._ensure_over(inn, over_idx)
        if bowler not in ov["bowlers"]:
            ov["bowlers"].append(bowler)
        bw = self._bowler(inn, bowler)
        sb = self._batter(inn, striker)
        bat_before = sb["runs"]
        was_free_hit = inn["free_hit"]

        wide_total = (self.fmt["wide_penalty"] + wide_runs) if delivery == "wide" else 0
        nb_total = self.fmt["noball_penalty"] if delivery == "noball" else 0
        if wk and kind in NO_RUNS_KINDS:
            bat = byes = lbs = wide_runs = 0
        total = bat + byes + lbs + wide_total + nb_total

        inn["runs"] += total
        inn["extras"]["wide"] += wide_total
        inn["extras"]["noball"] += nb_total
        inn["extras"]["bye"] += byes
        inn["extras"]["legbye"] += lbs

        charged = bat + wide_total + nb_total          # debited to the bowler
        bw["runs"] += charged
        ov["runs"] += total
        ov["charged"][bowler] = ov["charged"].get(bowler, 0) + charged
        if delivery == "wide":
            bw["wides"] += wide_total
        if delivery == "noball":
            bw["noballs"] += nb_total

        faced = delivery != "wide"
        if faced:
            sb["balls"] += 1
            inn["balls_faced_total"] += 1
            if bat == 0:
                sb["dots"] += 1
        if bat:
            sb["runs"] += bat
            if boundary and bat == 4:
                sb["fours"] += 1
            elif boundary and bat == 6:
                sb["sixes"] += 1
        if legal:
            bw["balls"] += 1
            ov["legal"] += 1
            if charged == 0:
                bw["dots"] += 1
            inn["legal_balls"] += 1

        # partnership
        p = inn["partnership"]
        if p:
            p["runs"] += total
            if faced:
                p["balls"] += 1
            if striker in p["contrib"]:
                p["contrib"][striker]["runs"] += bat
                if faced:
                    p["contrib"][striker]["balls"] += 1
            p["extras"] += total - bat

        # physical runs -> strike rotation (independent of runs credited)
        ran = ev.get("ran")
        if ran is None or ran == "":
            ran = 0 if boundary else (bat + byes + lbs + wide_runs)
        ran = _i(ran)
        if ran % 2 == 1:
            inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]

        label, bkind = self._ball_label(delivery, bat, byes, lbs, wide_runs, boundary, wk, total)

        # wicket
        wrec = None
        if wk:
            wrec = self._apply_wicket(inn, ev, wk, kind, out_pid, bowler, striker)

        # over end
        over_complete = legal and inn["legal_balls"] % self.bpo == 0
        rec = {
            "id": ev.get("id"), "innings": inn["index"], "over": over_idx,
            "ball": (inn["legal_balls"] - 1) % self.bpo + 1 if legal else inn["legal_balls"] % self.bpo,
            "over_str": (f"{over_idx}.{(inn['legal_balls'] - 1) % self.bpo + 1}" if legal
                         else f"{over_idx}.{inn['legal_balls'] % self.bpo}"),
            "delivery": delivery, "label": label, "kind": bkind, "runs": total,
            "bat_runs": bat, "byes": byes, "legbyes": lbs, "wide_total": wide_total,
            "noball_total": nb_total, "boundary": boundary,
            "bowler": bowler, "bowler_name": self.name(bowler),
            "striker": striker, "striker_name": self.name(striker),
            "non_striker": non, "free_hit": was_free_hit,
            "wicket": wrec, "score": f"{inn['runs']}/{inn['wickets']}", "note": ev.get("note"),
            "striker_before": bat_before, "striker_runs": sb["runs"], "striker_balls": sb["balls"],
        }
        inn["balls"].append(rec)
        ov["balls"].append({"label": label, "kind": bkind, "runs": total, "legal": legal,
                            "wicket": bool(wrec), "id": ev.get("id")})
        if wrec:
            ov["wickets"] += 1

        # free hit flag for the NEXT delivery
        if delivery == "noball" and self.fmt.get("free_hit"):
            inn["free_hit"] = True
        elif legal:
            inn["free_hit"] = False

        if over_complete:
            inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]
            ov["complete"] = True
            if len(ov["bowlers"]) == 1 and ov["charged"].get(ov["bowlers"][0], 0) == 0 and ov["legal"] == self.bpo:
                ov["maiden"] = True
                self._bowler(inn, ov["bowlers"][0])["maidens"] += 1
            inn["last_over_bowlers"] = list(ov["bowlers"])
            inn["bowler"] = None
            inn["pending_bowler"] = True
        self._check_end(inn)

    def _ball_label(self, delivery, bat, byes, lbs, wide_runs, boundary, wk, total):
        if delivery == "wide":
            lab = "Wd" + (f"+{wide_runs}" if wide_runs else "")
            kind = "wide"
        elif delivery == "noball":
            if bat:
                lab, kind = f"Nb+{bat}", "noball"
            elif byes:
                lab, kind = f"Nb+{byes}b", "noball"
            elif lbs:
                lab, kind = f"Nb+{lbs}lb", "noball"
            else:
                lab, kind = "Nb", "noball"
        elif byes:
            lab, kind = f"{byes}b", "bye"
        elif lbs:
            lab, kind = f"{lbs}lb", "legbye"
        elif bat == 0:
            lab, kind = "•", "dot"
        else:
            lab = str(bat)
            kind = "six" if boundary and bat == 6 else "four" if boundary and bat == 4 else "runs"
        if wk:
            tail = "W" if total == 0 else f"{total}W"
            lab = tail if delivery == "legal" else f"{lab}+W"
            kind = "wicket"
        return lab, kind

    def _apply_wicket(self, inn, ev, wk, kind, out_pid, bowler, striker):
        ob = self._batter(inn, out_pid)
        ob["status"] = "out"
        ob["kind"] = kind
        ob["bowler"] = bowler if kind in BOWLER_CREDIT else None
        fielders = [f for f in (wk.get("fielder"), wk.get("fielder2")) if f]
        if kind == "stumped" and not fielders:        # a stumping is always by the keeper
            k = self.keeper_of(inn.get("bowling"))
            if k:
                fielders = [k]
        ob["fielders"] = fielders
        ob["how"] = self._how_out(kind, bowler, fielders)
        ob["out_at"] = {"runs": inn["runs"], "wickets": inn["wickets"] + 1,
                        "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        inn["wickets"] += 1
        if kind in BOWLER_CREDIT:
            self._bowler(inn, bowler)["wickets"] += 1
        pr = inn["partnership"]
        inn["fow"].append({"wicket": inn["wickets"], "score": inn["runs"], "batter": out_pid,
                           "name": self.name(out_pid), "kind": kind, "how": ob["how"],
                           "over": _fmt_overs(inn["legal_balls"], self.bpo),
                           "bowler": bowler, "partnership_runs": pr["runs"] if pr else 0,
                           "batter_runs": ob["runs"], "batter_balls": ob["balls"]})
        self._close_partnership(inn)
        wrec = {"kind": kind, "kind_name": DISMISSAL_NAMES[kind], "out": out_pid,
                "out_name": self.name(out_pid), "how": ob["how"], "bowler": bowler,
                "fielders": fielders, "runs": ob["runs"], "balls": ob["balls"]}
        inn["last_wicket"] = {**wrec, "score": f"{inn['runs']}/{inn['wickets']}",
                              "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        # vacate slot
        slot = "striker" if inn["striker"] == out_pid else "non_striker"
        inn[slot] = None
        nb = wk.get("new_batter")
        if inn["wickets"] >= inn["wickets_limit"]:
            inn["pending_batter"] = False
            return wrec
        if nb:
            self._place_new_batter(inn, nb, wk.get("new_batter_on_strike"))
        else:
            inn["pending_batter"] = True
        return wrec

    def _how_out(self, kind, bowler, fielders):
        bn = self.name(bowler)
        fn = [self.fname(f) for f in fielders]
        if kind == "bowled":
            return f"b {bn}"
        if kind == "lbw":
            return f"lbw b {bn}"
        if kind == "caught":
            if fielders and fielders[0] == bowler:
                return f"c & b {bn}"
            return f"c {fn[0]} b {bn}" if fn else f"c b {bn}"
        if kind == "stumped":
            return f"st {fn[0]} b {bn}" if fn else f"st b {bn}"
        if kind == "hit_wicket":
            return f"hit wicket b {bn}"
        if kind == "run_out":
            return f"run out ({'/'.join(fn)})" if fn else "run out"
        if kind == "hit_twice":
            return "hit the ball twice"
        if kind == "obstructing":
            return "obstructing the field"
        if kind == "timed_out":
            return "timed out"
        if kind == "retired_out":
            return "retired out"
        return kind

    # ---- other events ----------------------------------------------------- #
    def _ev_timed_out(self, ev):
        """Law 40: incoming batter is out timed out (no ball faced)."""
        inn = self.get_inn(ev.get("innings"))
        if inn["status"] != "in_progress":
            raise RuleError("innings_over", "This innings is complete.")
        if not inn["pending_batter"]:
            raise RuleError("timed_out_no_slot", "Timed out can only be given to a batter who is due in (wicket just fell).")
        pid = ev.get("player")
        self._check_batter_ok(inn, pid, allow_return=False)
        b = self._batter(inn, pid)
        b["status"], b["kind"], b["how"] = "out", "timed_out", "timed out"
        b["out_at"] = {"runs": inn["runs"], "wickets": inn["wickets"] + 1,
                       "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        inn["wickets"] += 1
        inn["fow"].append({"wicket": inn["wickets"], "score": inn["runs"], "batter": pid,
                           "name": self.name(pid), "kind": "timed_out", "how": "timed out",
                           "over": _fmt_overs(inn["legal_balls"], self.bpo), "bowler": None,
                           "partnership_runs": 0, "batter_runs": 0, "batter_balls": 0})
        inn["last_wicket"] = {"kind": "timed_out", "kind_name": "Timed out", "out": pid,
                              "out_name": self.name(pid), "how": "timed out", "runs": 0, "balls": 0,
                              "score": f"{inn['runs']}/{inn['wickets']}",
                              "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        nb = ev.get("new_batter")
        if inn["wickets"] >= inn["wickets_limit"]:
            self._check_end(inn)
        elif nb:
            self._check_batter_ok(inn, nb)
            self._place_new_batter(inn, nb, ev.get("on_strike"))

    def _ev_retire(self, ev):
        """Batter retires: 'hurt' (not out, may return) or 'out' (counts as a wicket, Law 25)."""
        inn = self.get_inn(ev.get("innings"))
        if inn["status"] != "in_progress":
            raise RuleError("innings_over", "This innings is complete.")
        pid = ev.get("player")
        if pid not in (inn["striker"], inn["non_striker"]):
            raise RuleError("not_at_crease", f"{self.name(pid)} is not at the crease.")
        kind = ev.get("kind") or "hurt"
        b = self._batter(inn, pid)
        if kind == "out":
            b["status"], b["kind"], b["how"] = "out", "retired_out", "retired out"
            b["out_at"] = {"runs": inn["runs"], "wickets": inn["wickets"] + 1,
                           "over": _fmt_overs(inn["legal_balls"], self.bpo)}
            inn["wickets"] += 1
            pr = inn["partnership"]
            inn["fow"].append({"wicket": inn["wickets"], "score": inn["runs"], "batter": pid,
                               "name": self.name(pid), "kind": "retired_out", "how": "retired out",
                               "over": _fmt_overs(inn["legal_balls"], self.bpo), "bowler": None,
                               "partnership_runs": pr["runs"] if pr else 0,
                               "batter_runs": b["runs"], "batter_balls": b["balls"]})
            inn["last_wicket"] = {"kind": "retired_out", "kind_name": "Retired out", "out": pid,
                                  "out_name": self.name(pid), "how": "retired out", "runs": b["runs"],
                                  "balls": b["balls"], "score": f"{inn['runs']}/{inn['wickets']}",
                                  "over": _fmt_overs(inn["legal_balls"], self.bpo)}
        else:
            b["status"], b["how"] = "retired_hurt", "retired hurt"
        self._close_partnership(inn)
        slot = "striker" if inn["striker"] == pid else "non_striker"
        inn[slot] = None
        if inn["wickets"] >= inn["wickets_limit"]:
            self._check_end(inn)
            return
        nb = ev.get("replacement")
        if nb:
            self._check_batter_ok(inn, nb)
            self._place_new_batter(inn, nb, ev.get("on_strike"))
        else:
            inn["pending_batter"] = True

    def _ev_penalty_runs(self, ev):
        """5 penalty runs (Laws 41/42). Added to the AWARDED team's score."""
        runs = _i(ev.get("runs"), 5)
        team = ev.get("awarded_to")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Say which team the penalty runs are awarded to.")
        if runs <= 0:
            raise RuleError("negative", "Penalty runs must be positive.")
        tgt = None
        if ev.get("innings") not in (None, ""):
            tgt = self.get_inn(ev.get("innings"))
            if tgt["batting"] != team:
                raise RuleError("wrong_innings", "That innings was not batted by the awarded team.")
        else:
            mine = [i for i in self.innings if i["batting"] == team]
            if mine:
                tgt = mine[-1]
        if tgt is None:
            self.pending_penalty[team] += runs
            return
        tgt["extras"]["penalty"] += runs
        tgt["runs"] += runs
        if tgt["status"] == "in_progress":
            self._check_end(tgt)

    def _ev_innings_end(self, ev):
        inn = self.get_inn(ev.get("innings"))
        if inn["status"] == "completed":
            raise RuleError("innings_over", "This innings is already complete.")
        reason = ev.get("reason") or "manual"
        self._end_innings(inn, reason if reason in ("declared", "forfeited", "time", "abandoned", "all_out", "overs_completed", "manual") else "manual")

    def _ev_revise(self, ev):
        """Revised overs / target (DLS or other method; the figures come from the umpires/official calculator)."""
        idx = _i(ev.get("innings"), len(self.innings) - 1)
        if idx == len(self.innings):      # revision announced before the innings starts (e.g. rain break)
            ol = ev.get("overs_limit")
            self.pending_rev[idx] = {"overs_limit": None if ol in (None, "") else _i(ol),
                                     "target": None if ev.get("target") in (None, "") else _i(ev["target"]),
                                     "method": ev.get("method"), "note": ev.get("note")}
            return
        inn = self.get_inn(ev.get("innings"))
        if ev.get("overs_limit") not in (None, ""):
            ol = _i(ev["overs_limit"])
            if ol <= 0:
                raise RuleError("bad_overs", "Revised overs must be positive.")
            inn["overs_limit"] = ol
        if ev.get("target") not in (None, ""):
            inn["target_revised"] = _i(ev["target"])
        inn["revision"] = {"method": ev.get("method") or "manual", "note": ev.get("note"),
                           "overs_limit": inn["overs_limit"], "target": inn["target_revised"]}
        # revised overs in the first innings also apply to the second unless told otherwise
        self._check_end(inn)

    def _ev_substitution(self, ev):
        """Impact player / concussion / other replacement of a player in the XI."""
        team, out, inn_ = ev.get("team"), ev.get("out"), ev.get("in")
        if out not in self.pl or inn_ not in self.pl:
            raise RuleError("unknown_player", "Unknown player in substitution.")
        if self.team_of(out) != self.team_of(inn_):
            raise RuleError("wrong_team", "Players must be on the same team.")
        t = self.team_of(out)
        if out not in self.xi[t]:
            raise RuleError("not_in_xi", f"{self.name(out)} is not in the XI.")
        if inn_ in self.xi[t]:
            raise RuleError("already_in_xi", f"{self.name(inn_)} is already in the XI.")
        if inn_ in self.subbed_out:
            raise RuleError("subbed_out", f"{self.name(inn_)} was substituted out earlier.")
        for inn in self.innings:
            if inn["status"] == "in_progress" and out in (inn["striker"], inn["non_striker"], inn["bowler"]):
                raise RuleError("in_play", f"{self.name(out)} is at the crease / bowling: retire them or finish the over first.")
        self.xi[t].discard(out)
        self.xi[t].add(inn_)
        self.subbed_out.add(out)

    def _ev_override(self, ev):
        inn = self.get_inn(ev.get("innings"))
        sets = ev.get("set") or {}
        for path, val in sets.items():
            self._apply_override(inn, path, val)
        self.applied_overrides.append({"id": ev.get("id"), "innings": inn["index"],
                                       "set": sets, "reason": ev.get("reason")})
        if inn["status"] == "in_progress":
            self._check_end(inn)

    def _apply_override(self, inn, path, val):
        def mark():
            inn["overridden"][path] = True
        if path in ("runs", "wickets"):
            inn[path] = _i(val)
        elif path in ("balls", "legal_balls"):
            inn["legal_balls"] = max(0, _i(val))
            path = "balls"
        elif path.startswith("extras."):
            k = path.split(".", 1)[1]
            if k not in inn["extras"]:
                raise RuleError("bad_override", f"Unknown extras field '{k}'.")
            inn["extras"][k] = _i(val)
        elif path == "overs_limit":
            inn["overs_limit"] = None if val in (None, "") else _i(val)
        elif path == "wickets_limit":
            inn["wickets_limit"] = _i(val)
        elif path == "target":
            inn["target_revised"] = None if val in (None, "") else _i(val)
        elif path in ("striker", "non_striker", "bowler"):
            if val and val not in self.pl:
                raise RuleError("unknown_player", f"Unknown player '{val}'.")
            inn[path] = val or None
            if val:
                (self._bowler if path == "bowler" else self._batter)(inn, val)
            if path == "bowler" and val:
                inn["pending_bowler"] = False
            if path != "bowler":
                inn["pending_batter"] = not (inn["striker"] and inn["non_striker"])
        elif path == "free_hit":
            inn["free_hit"] = bool(val)
        elif path.startswith("batter."):
            _, pid, field = path.split(".", 2)
            if pid not in self.pl:
                raise RuleError("unknown_player", f"Unknown player '{pid}'.")
            b = self._batter(inn, pid)
            if field in ("runs", "balls", "fours", "sixes", "dots"):
                b[field] = _i(val)
            elif field in ("status", "how"):
                b[field] = val
            else:
                raise RuleError("bad_override", f"Unknown batter field '{field}'.")
        elif path.startswith("bowler."):
            _, pid, field = path.split(".", 2)
            if pid not in self.pl:
                raise RuleError("unknown_player", f"Unknown player '{pid}'.")
            b = self._bowler(inn, pid)
            if field in ("balls", "runs", "wickets", "maidens", "wides", "noballs", "dots"):
                b[field] = _i(val)
            else:
                raise RuleError("bad_override", f"Unknown bowler field '{field}'.")
        else:
            raise RuleError("bad_override", f"Unknown override target '{path}'.")
        mark()

    def _ev_result(self, ev):
        self.explicit_result = {
            "status": ev.get("status") or "won", "winner": ev.get("winner"),
            "text": ev.get("text"), "final": True, "method": ev.get("method"),
            "note": ev.get("note"),
        }

    def _ev_clear_result(self, ev):
        self.explicit_result = None

    def _ev_toss(self, ev):
        if ev.get("winner") in ("A", "B"):
            self.match.setdefault("toss", {})
            # toss events are informational; setup 'toss' is what decides batting order.
        return

    def _ev_info(self, ev):
        self.info.append({"id": ev.get("id"), "text": ev.get("text"), "ts": ev.get("ts")})

    def totals(self) -> Dict[str, int]:
        reg = [i for i in self.innings if i["kind"] == "regular"]
        return {"runs": sum(i["runs"] for i in reg), "wickets": sum(i["wickets"] for i in reg),
                "balls": sum(i["legal_balls"] for i in reg)}

    def _ev_delay(self, ev):
        kind = ev.get("kind") if ev.get("kind") in BREAK_KINDS else "other"
        self.delay_kind = kind
        self.delay = ev.get("text") or BREAK_KINDS[kind]
        if kind in ("lunch", "tea", "stumps"):
            self.advance = kind

    def _ev_resume(self, ev):
        if self.advance == "stumps":
            self.day += 1
            self.session = 1
            self.day_base = self.totals()
            self.session_base = dict(self.day_base)
        elif self.advance in ("lunch", "tea"):
            self.session += 1
            self.session_base = self.totals()
        self.advance = None
        self.delay = None
        self.delay_kind = None

    def _ev_day_set(self, ev):
        """Manual override of the day / session counters (the scorer pressed the wrong button, or joined mid-match)."""
        d, sn = _i(ev.get("day"), self.day), _i(ev.get("session"), self.session)
        if d < 1 or sn < 1 or d > 30 or sn > 6:
            raise RuleError("bad_day", "Day must be 1-30 and session 1-6.")
        if (d, sn) != (self.day, self.session):
            t = self.totals()
            if d != self.day:
                self.day_base = dict(t)
            self.session_base = dict(t)
        self.day, self.session = d, sn
        self.applied_overrides.append({"id": ev.get("id"), "type": "day_set", "text": f"Day {d}, session {sn}", "reason": ev.get("reason")})

    def _ev_new_ball(self, ev):
        """The fielding captain took the new ball: restart the ball-age counter."""
        self.new_ball_base = self.totals()["balls"]


# --------------------------------------------------------------------------- #
# Result computation
# --------------------------------------------------------------------------- #
def follow_on_margin(days) -> int:
    """MCC Law 14.1 minimum first-innings lead for the follow-on option."""
    if days is None or days >= 5:
        return 200
    return 150 if days >= 3 else (100 if days == 2 else 75)


def _team_total(R: _Replay, tid: str, kinds=("regular",)) -> int:
    return sum(i["runs"] for i in R.innings if i["batting"] == tid and i["kind"] in kinds)


def _first_innings_lead(R: _Replay, reg) -> Optional[Dict[str, Any]]:
    if len(reg) >= 2 and reg[0]["status"] == "completed" and reg[1]["status"] == "completed" and reg[0]["runs"] != reg[1]["runs"]:
        w = reg[0] if reg[0]["runs"] > reg[1]["runs"] else reg[1]
        return {"team": w["batting"], "runs": abs(reg[0]["runs"] - reg[1]["runs"])}
    return None


def _multi_result(R: _Replay, res, reg, names) -> Dict[str, Any]:
    """Two-innings-a-side result (Laws 16 & 21): win by wickets/runs/innings, tie, draw (time expired)."""
    COMPLETE = ("all_out", "declared", "forfeited", "overs_completed", "target_reached")
    done = [i for i in reg if i["status"] == "completed"]
    if reg and reg[-1]["status"] != "completed":
        return res
    if not reg:
        return res
    last = reg[-1]
    res["status"] = "innings_break"
    n = len(reg)
    other = lambda t: "A" if t == "B" else "B"
    if n == 4:
        bat_last = last["batting"]
        tgt = R.effective_target(last)
        if tgt is not None and last["runs"] >= tgt:
            wl = last["wickets_limit"] - last["wickets"]
            res.update(status="won", winner=bat_last, final=True, margin={"wickets": wl},
                       text=f"{names[bat_last]} won by {wl} wicket{'s' if wl != 1 else ''}")
        elif tgt is not None and last["runs"] == tgt - 1 and last["end_reason"] in ("all_out", "overs_completed"):
            res.update(status="tie", final=True, text="Match tied")
        elif tgt is not None and last["end_reason"] in ("all_out", "overs_completed", "declared", "forfeited"):
            m = tgt - 1 - last["runs"]
            w = other(bat_last)
            res.update(status="won", winner=w, final=True, margin={"runs": m}, text=f"{names[w]} won by {m} run{'s' if m != 1 else ''}")
        else:
            res.update(status="draw", final=True, text="Match drawn")
    elif last["end_reason"] == "time":
        res.update(status="draw", final=True, text="Match drawn")           # time expired with the match unfinished
    elif n == 3:
        t = last["batting"]                                                 # this side has now batted twice
        mine = sum(i["runs"] for i in reg if i["batting"] == t)
        theirs = sum(i["runs"] for i in reg if i["batting"] != t)
        if last["end_reason"] in COMPLETE and mine < theirs:
            w = other(t)
            res.update(status="won", winner=w, final=True, margin={"innings": theirs - mine},
                       text=f"{names[w]} won by an innings and {theirs - mine} run{'s' if theirs - mine != 1 else ''}")
    if res.get("final") and res["status"] == "draw":
        lead = _first_innings_lead(R, reg)
        if lead:
            res["first_innings_lead"] = lead
    return res


def _compute_result(R: _Replay) -> Dict[str, Any]:
    names = {t: R.teams[t]["name"] for t in R.teams}
    res = {"status": "not_started", "winner": None, "text": None, "method": None, "margin": None,
           "final": False, "super_over_needed": False}
    if R.explicit_result:
        e = R.explicit_result
        text = e.get("text")
        if not text:
            if e["status"] == "won" and e.get("winner") in names:
                text = f"{names[e['winner']]} won"
            elif e["status"] == "tie":
                text = "Match tied"
            elif e["status"] == "no_result":
                text = "No result"
            elif e["status"] == "abandoned":
                text = "Match abandoned"
            elif e["status"] == "draw":
                text = "Match drawn"
            else:
                text = e["status"].replace("_", " ").title()
        return {"status": e["status"], "winner": e.get("winner"), "text": text,
                "method": e.get("method") or "manual", "margin": None, "final": True,
                "manual": True, "super_over_needed": False, "note": e.get("note")}
    if not R.innings:
        return res
    res["status"] = "in_progress"
    reg = [i for i in R.innings if i["kind"] == "regular"]
    sup = [i for i in R.innings if i["kind"] == "super_over"]
    ips = R.fmt["innings_per_side"]
    # super over decides?
    if sup:
        if len(sup) >= 2 and sup[-1]["status"] == "completed" and sup[-2]["status"] == "completed" and len(sup) % 2 == 0:
            a, b = sup[-2], sup[-1]
            if a["runs"] != b["runs"]:
                w = a if a["runs"] > b["runs"] else b
                res.update(status="won", winner=w["batting"], final=True, method="super_over",
                           text=f"{names[w['batting']]} won the Super Over ({a['runs']} v {b['runs']})")
            else:
                res.update(status="tie", final=False, super_over_needed=True, method="super_over",
                           text="Super Over tied")
        return res
    if ips == 2:
        return _multi_result(R, res, reg, names)
    if len(reg) < 2 * ips:
        if reg and reg[-1]["status"] == "completed":
            res["status"] = "innings_break"
        return res
    last = reg[-1]
    if last["status"] != "completed":
        return res
    ta, tb = _team_total(R, "A"), _team_total(R, "B")
    if ips == 1:
        first, second = reg[0], reg[1]
        tgt = R.effective_target(second)
        s_runs, f_runs = second["runs"], first["runs"]
        method = "DLS" if (second.get("revision") and (second["revision"].get("method") or "").upper() in ("DLS", "D/L", "DL", "VJD")) else None
        if second["runs"] >= tgt:
            wl = second["wickets_limit"] - second["wickets"]
            balls_left = (second["overs_limit"] * R.bpo - second["legal_balls"]) if second["overs_limit"] else 0
            txt = f"{names[second['batting']]} won by {wl} wicket{'s' if wl != 1 else ''}"
            if balls_left > 0:
                txt += f" ({balls_left} ball{'s' if balls_left != 1 else ''} remaining)"
            res.update(status="won", winner=second["batting"], final=True, margin={"wickets": wl, "balls_left": balls_left})
        elif s_runs == tgt - 1:
            res.update(status="tie", final=not R.fmt["super_over"].get("enabled"),
                       text="Match tied", super_over_needed=bool(R.fmt["super_over"].get("enabled")))
            txt = "Match tied"
        else:
            m = tgt - 1 - s_runs
            txt = f"{names[first['batting']]} won by {m} run{'s' if m != 1 else ''}"
            res.update(status="won", winner=first["batting"], final=True, margin={"runs": m})
        if method and res["status"] == "won":
            txt += f" ({method} method)"
        res["text"] = txt
        res["method"] = method
        return res
    return res


# --------------------------------------------------------------------------- #
# State assembly
# --------------------------------------------------------------------------- #
def _rate(runs, balls, bpo):
    return round(runs / (balls / bpo), 2) if balls else 0.0


def _sr(runs, balls):
    return round(runs * 100 / balls, 1) if balls else 0.0


def _innings_view(R: _Replay, inn: Dict[str, Any]) -> Dict[str, Any]:
    bpo = R.bpo
    tid = inn["batting"]
    # batters list
    bl = []
    for pid in inn["bat_order"]:
        b = dict(inn["batters"][pid])
        b["sr"] = _sr(b["runs"], b["balls"])
        b["tag"] = R.tag(pid)
        b["at_crease"] = pid in (inn["striker"], inn["non_striker"])
        b["on_strike"] = pid == inn["striker"] and inn["status"] == "in_progress"
        if b["at_crease"] and b["status"] == "batting":
            b["status_text"] = "not out"
        elif b["status"] == "batting":
            b["status_text"] = "not out"
        elif b["status"] == "out":
            b["status_text"] = b["how"]
        else:
            b["status_text"] = b["how"] or b["status"]
        bl.append(b)
    seen = set(inn["bat_order"])
    yet = [p for p in R.teams[tid]["players"] if p["id"] in R.xi[tid] and p["id"] not in seen]
    for p in yet:
        bl.append({"id": p["id"], "name": p["name"], "tag": R.tag(p["id"]), "short": p.get("short") or p["name"], "runs": 0,
                   "balls": 0, "fours": 0, "sixes": 0, "dots": 0, "sr": 0.0, "status": "yet_to_bat",
                   "status_text": "yet to bat", "how": None, "at_crease": False, "on_strike": False,
                   "kind": None, "fielders": [], "bowler": None, "out_at": None, "in_at": None})
    # bowlers
    bw = []
    for pid in inn["bowl_order"]:
        b = dict(inn["bowlers"][pid])
        b["overs"] = _fmt_overs(b["balls"], bpo)
        b["econ"] = _rate(b["runs"], b["balls"], bpo)
        b["is_current"] = pid == inn["bowler"]
        b["tag"] = R.tag(pid)
        bw.append(b)
    ex = dict(inn["extras"])
    ex["total"] = sum(ex.values())
    total_balls = inn["overs_limit"] * bpo if inn["overs_limit"] is not None else None
    tgt = R.effective_target(inn)
    crr = _rate(inn["runs"], inn["legal_balls"], bpo)
    need = balls_left = rrr = None
    if tgt is not None:
        need = max(0, tgt - inn["runs"])
        if total_balls is not None:
            balls_left = max(0, total_balls - inn["legal_balls"])
            rrr = round(need * bpo / balls_left, 2) if balls_left else (0.0 if need == 0 else None)
    proj = None
    if total_balls and inn["legal_balls"] >= 2 * bpo and inn["status"] == "in_progress" and tgt is None:
        proj = round(inn["runs"] / inn["legal_balls"] * total_balls)
    partnership = None
    p = inn["partnership"]
    if p:
        partnership = {"runs": p["runs"], "balls": p["balls"], "extras": p["extras"], "wicket_no": p["wicket_no"],
                       "pair": [{"id": x, "name": R.name(x), "short": R.short(x),
                                 "runs": p["contrib"].get(x, {}).get("runs", 0),
                                 "balls": p["contrib"].get(x, {}).get("balls", 0)} for x in p["pair"] if x]}
    last_over = inn["overs"][-1] if inn["overs"] else None
    pp = None
    if inn["status"] == "in_progress":
        pp = R._powerplay_name(inn["legal_balls"] // bpo + 1)
    return {
        "index": inn["index"], "kind": inn["kind"], "batting": tid, "bowling": inn["bowling"],
        "batting_name": R.teams[tid]["name"], "batting_short": R.teams[tid]["short"],
        "status": inn["status"], "end_reason": inn["end_reason"],
        "runs": inn["runs"], "wickets": inn["wickets"], "wickets_limit": inn["wickets_limit"],
        "legal_balls": inn["legal_balls"], "overs": _fmt_overs(inn["legal_balls"], bpo),
        "overs_limit": inn["overs_limit"], "balls_limit": total_balls,
        "score": f"{inn['runs']}/{inn['wickets']}", "crr": crr,
        "target": tgt, "need": need, "balls_left": balls_left, "rrr": rrr, "projected": proj,
        "revision": inn["revision"], "extras": ex,
        "batters": bl, "bowlers": bw, "fow": inn["fow"],
        "partnerships": inn["partnerships"], "partnership": partnership,
        "overs_detail": inn["overs"], "balls": inn["balls"],
        "this_over": ({"n": last_over["n"], "balls": last_over["balls"], "runs": last_over["runs"],
                       "complete": last_over["complete"], "maiden": last_over["maiden"],
                       "powerplay": last_over["powerplay"]} if last_over else
                      {"n": 1, "balls": [], "runs": 0, "complete": False, "maiden": False, "powerplay": None}),
        "striker": inn["striker"], "non_striker": inn["non_striker"], "bowler": inn["bowler"],
        "pending_batter": inn["pending_batter"], "pending_bowler": inn["pending_bowler"],
        "free_hit": inn["free_hit"], "powerplay": pp, "last_wicket": inn["last_wicket"],
        "overridden": sorted(inn["overridden"].keys()), "declared": inn["declared"],
    }


def _player_ref(R, inn, pid, kind):
    if not pid:
        return None
    if kind == "bat":
        b = inn["batters"].get(pid)
        if not b:
            return {"id": pid, "name": R.name(pid), "short": R.short(pid), "runs": 0, "balls": 0,
                    "fours": 0, "sixes": 0, "sr": 0.0}
        return {"id": pid, "name": b["name"], "short": b["short"], "runs": b["runs"], "balls": b["balls"],
                "fours": b["fours"], "sixes": b["sixes"], "sr": _sr(b["runs"], b["balls"])}
    b = inn["bowlers"].get(pid)
    if not b:
        return {"id": pid, "name": R.name(pid), "short": R.short(pid), "overs": "0.0", "maidens": 0,
                "runs": 0, "wickets": 0, "econ": 0.0}
    return {"id": pid, "name": b["name"], "short": b["short"], "overs": _fmt_overs(b["balls"], R.bpo),
            "balls": b["balls"], "maidens": b["maidens"], "runs": b["runs"], "wickets": b["wickets"],
            "econ": _rate(b["runs"], b["balls"], R.bpo), "figures": f"{b['wickets']}-{b['runs']}"}


def _reconcile(R: _Replay) -> List[Dict[str, Any]]:
    """Info-level checks: do the parts add up to the totals?"""
    out = []
    for inn in R.innings:
        bat = sum(b["runs"] for b in inn["batters"].values())
        extras = sum(inn["extras"].values())
        if bat + extras != inn["runs"]:
            out.append({"level": "info", "innings": inn["index"],
                        "message": f"Innings {inn['index'] + 1}: team total {inn['runs']} ≠ batters {bat} + extras {extras} = {bat + extras}"
                                   + (" (manual override in effect)" if inn["overridden"] else " — check scoring")})
        bb = sum(b["balls"] for b in inn["bowlers"].values())
        if bb != inn["legal_balls"]:
            out.append({"level": "info", "innings": inn["index"],
                        "message": f"Innings {inn['index'] + 1}: legal balls {inn['legal_balls']} ≠ sum of bowlers' balls {bb}"
                                   + (" (override)" if inn["overridden"] else "")})
        fallen = sum(1 for b in inn["batters"].values() if b["status"] == "out")
        if fallen != inn["wickets"]:
            out.append({"level": "info", "innings": inn["index"],
                        "message": f"Innings {inn['index'] + 1}: wickets {inn['wickets']} ≠ batters out {fallen}"
                                   + (" (override)" if inn["overridden"] else "")})
    return out


def derive(match: Dict[str, Any]) -> Dict[str, Any]:
    """Replay the event log and return the complete scoreboard. Never raises."""
    normalize_setup(match)
    R = _Replay(match)
    R.warnings = []
    seq = 0
    for ev in match["events"]:
        seq += 1
        try:
            R.apply(ev)
            R.event_status[ev.get("id")] = {"ok": True}
            R.last_event = ev
        except RuleError as e:
            R.event_status[ev.get("id")] = {"ok": False, "error": e.to_dict()}
            R.errors.append({"event_id": ev.get("id"), "seq": seq, "type": ev.get("type"), **e.to_dict()})
        except Exception as e:  # pragma: no cover - defensive: never take down the broadcast
            R.event_status[ev.get("id")] = {"ok": False, "error": {"code": "internal", "message": f"{type(e).__name__}: {e}"}}
            R.errors.append({"event_id": ev.get("id"), "seq": seq, "type": ev.get("type"),
                             "code": "internal", "message": f"{type(e).__name__}: {e}"})
    return _assemble(R)


def _assemble(R: _Replay) -> Dict[str, Any]:
    m = R.match
    bpo = R.bpo
    innings = [_innings_view(R, i) for i in R.innings]
    result = _compute_result(R)
    cur_raw = R.innings[-1] if R.innings else None
    cur = innings[-1] if innings else None

    # match status
    if result.get("final"):
        mstatus = "completed" if result["status"] not in ("abandoned", "no_result") else result["status"]
    elif not R.innings:
        mstatus = "not_started"
    elif R.delay:
        mstatus = "delayed"
    elif result["status"] == "innings_break":
        mstatus = "innings_break"
    elif cur and cur["status"] == "completed":
        mstatus = "innings_break" if not result.get("super_over_needed") else "super_over_pending"
    else:
        mstatus = "live"

    current = None
    if cur:
        t = R.teams
        pb = _player_ref(R, cur_raw, cur["striker"], "bat")
        pn = _player_ref(R, cur_raw, cur["non_striker"], "bat")
        pw = _player_ref(R, cur_raw, cur["bowler"], "bowl")
        lb = cur["balls"][-1] if cur["balls"] else None
        lead = _lead(R, cur_raw)
        status_line = _status_line(R, cur, result, mstatus, lead)
        current = {
            "innings_no": cur["index"] + 1, "kind": cur["kind"],
            "batting": {"id": cur["batting"], "name": t[cur["batting"]]["name"],
                        "short": t[cur["batting"]]["short"], "color": t[cur["batting"]]["color"],
                        "logo": t[cur["batting"]].get("logo")},
            "bowling": {"id": cur["bowling"], "name": t[cur["bowling"]]["name"],
                        "short": t[cur["bowling"]]["short"], "color": t[cur["bowling"]]["color"],
                        "logo": t[cur["bowling"]].get("logo")},
            "runs": cur["runs"], "wickets": cur["wickets"], "score": cur["score"], "overs": cur["overs"],
            "overs_limit": cur["overs_limit"], "balls": cur["legal_balls"], "crr": cur["crr"],
            "target": cur["target"], "need": cur["need"], "balls_left": cur["balls_left"],
            "wickets_left": max(0, cur["wickets_limit"] - cur["wickets"]),
            "wickets_limit": cur["wickets_limit"],
            "rrr": cur["rrr"], "projected": cur["projected"],
            "striker": pb, "non_striker": pn, "bowler": pw,
            "this_over": cur["this_over"], "partnership": cur["partnership"],
            "last_ball": ({k: lb[k] for k in ("over_str", "label", "kind", "runs", "bowler_name", "striker_name", "wicket")}
                          if lb else None),
            "last_wicket": cur["last_wicket"], "free_hit": cur["free_hit"],
            "powerplay": cur["powerplay"], "extras": cur["extras"],
            "pending_batter": cur["pending_batter"], "pending_bowler": cur["pending_bowler"],
            "innings_status": cur["status"], "end_reason": cur["end_reason"],
            "status_line": status_line,
            "lead": (lead["diff"] if lead else None), "lead_text": (lead["text"] if lead else None),
        }
    first_inn_summary = None
    if len(innings) >= 1 and R.fmt["innings_per_side"] == 1:
        i0 = innings[0]
        first_inn_summary = {"batting_name": i0["batting_name"], "short": i0["batting_short"],
                             "score": i0["score"], "overs": i0["overs"]}
    state = {
        "engine_version": ENGINE_VERSION,
        "match_id": m.get("id"), "title": m.get("title"), "venue": m.get("venue"), "date": m.get("date"),
        "status": mstatus, "delay": R.delay, "format": R.fmt,
        "teams": {tid: {"id": tid, "name": t["name"], "short": t["short"], "color": t["color"],
                        "logo": t.get("logo"),
                        "players": [{**p, "xi": p["id"] in R.xi[tid], "subbed_out": p["id"] in R.subbed_out}
                                    for p in t["players"]]}
                  for tid, t in R.teams.items()},
        "toss": m.get("toss") or {},
        "innings": innings, "current_innings": (cur["index"] if cur else None),
        "current": current, "first_innings": first_inn_summary, "result": result,
        "info": R.info[-5:],
        "integrity": {"errors": R.errors, "info": _reconcile(R), "overrides": R.applied_overrides,
                      "event_count": len(m["events"])},
        "event_status": R.event_status,
        "last_event": ({"id": R.last_event.get("id"), "type": R.last_event.get("type"), "ts": R.last_event.get("ts"),
                        "kind": (cur["balls"][-1]["kind"] if cur and cur["balls"] and R.last_event.get("type") == "ball" else None),
                        "label": (cur["balls"][-1]["label"] if cur and cur["balls"] and R.last_event.get("type") == "ball" else None),
                        "wicket": (cur["balls"][-1]["wicket"] if cur and cur["balls"] and R.last_event.get("type") == "ball" else None),
                        "milestone": _milestone(cur["balls"][-1]) if cur and cur["balls"] and R.last_event.get("type") == "ball" else None}
                       if R.last_event else None),
        "setup_version": m.get("setup_version", 0),
        "play": _play_block(R, innings, cur_raw, result),
    }
    return state


def _lead(R: _Replay, cur_raw) -> Optional[Dict[str, Any]]:
    """Lead / trail of the side now batting (two-innings matches, from the 2nd innings on, not in the final chase)."""
    if not cur_raw or cur_raw["kind"] != "regular" or cur_raw["index"] < 1 or cur_raw["index"] >= 3:
        return None
    bt = cur_raw["batting"]
    reg = [i for i in R.innings if i["kind"] == "regular" and i["index"] <= cur_raw["index"]]
    mine = sum(i["runs"] for i in reg if i["batting"] == bt)
    theirs = sum(i["runs"] for i in reg if i["batting"] != bt)
    d = mine - theirs
    nm = R.teams[bt]["name"]
    if d > 0:
        txt = f"{nm} lead by {d} run{'s' if d != 1 else ''}"
    elif d < 0:
        txt = f"{nm} trail by {-d} run{'s' if d != -1 else ''}"
    else:
        txt = "Scores level"
    return {"team": bt, "diff": d, "text": txt}


def _team_scores(R: _Replay, views) -> Dict[str, str]:
    out = {}
    for tid in ("A", "B"):
        parts = []
        for v in views:
            if v["kind"] != "regular" or v["batting"] != tid:
                continue
            raw = R.innings[v["index"]]
            sc = str(v["runs"]) if raw["end_reason"] == "all_out" else v["score"]
            parts.append(sc + ("d" if raw["declared"] else "") + ("*" if raw["status"] == "in_progress" else ""))
        out[tid] = " & ".join(parts)
    return out


def _play_block(R: _Replay, views, cur_raw, result) -> Optional[Dict[str, Any]]:
    """Multi-day state: day/session, today's and this session's play, overs left, ball age, lead/trail."""
    f = R.fmt
    if f["innings_per_side"] != 2:
        return None
    bpo = R.bpo
    t = R.totals()
    today = {k: max(0, t[k] - R.day_base[k]) for k in t}
    sess = {k: max(0, t[k] - R.session_base[k]) for k in t}
    for d in (today, sess):
        d["overs"] = _fmt_overs(d["balls"], bpo)
    opd = f.get("overs_per_day")
    left = max(0, opd * bpo - today["balls"]) if opd else None
    nba = f.get("new_ball_after")
    age = max(0, t["balls"] - R.new_ball_base)
    due = max(0, nba * bpo - age) if nba else None
    ld = _lead(R, cur_raw)
    reg = [i for i in R.innings if i["kind"] == "regular"]
    fo = len(reg) >= 3 and reg[2]["batting"] == reg[1]["batting"]
    days = f.get("days")
    return {
        "day": R.day, "session": R.session, "days": days, "last_day": bool(days and R.day >= days),
        "label": f"DAY {R.day} · SESSION {R.session}", "break": R.delay_kind, "break_text": R.delay,
        "today": today, "session_stats": sess, "overs_per_day": opd,
        "overs_left": (_fmt_overs(left, bpo) if left is not None else None), "overs_left_balls": left,
        "ball_age": _fmt_overs(age, bpo), "new_ball_after": nba,
        "new_ball_due": (_fmt_overs(due, bpo) if due is not None else None), "new_ball_available": bool(nba and due == 0),
        "scores": _team_scores(R, views), "lead": ld, "follow_on": fo,
        "follow_on_margin": follow_on_margin(days),
        "first_innings_lead": _first_innings_lead(R, reg),
    }


def _milestone(rec) -> Optional[Dict[str, Any]]:
    b, a = rec.get("striker_before", 0), rec.get("striker_runs", 0)
    for m in (200, 150, 100, 50):
        if b < m <= a:
            return {"runs": m, "player": rec["striker"], "name": rec["striker_name"], "balls": rec.get("striker_balls")}
    return None


def _status_line(R, cur, result, mstatus, lead=None) -> str:
    names = {t: R.teams[t]["name"] for t in R.teams}
    if result.get("final") and result.get("text"):
        return result["text"]
    if mstatus == "delayed":
        return R.delay or "Play suspended"
    tail = (" · " + lead["text"]) if lead else ""
    if cur["status"] == "completed":
        if cur["end_reason"] == "all_out":
            return f"{names[cur['batting']]} all out for {cur['runs']}{tail}"
        if cur["end_reason"] == "declared":
            return f"{names[cur['batting']]} declared at {cur['score']}{tail}"
        return f"Innings break: {names[cur['batting']]} {cur['score']} ({cur['overs']} ov){tail}"
    if cur["target"] is not None and cur["need"] is not None:
        if cur["balls_left"] is not None:
            return (f"{names[cur['batting']]} need {cur['need']} run{'s' if cur['need'] != 1 else ''} "
                    f"from {cur['balls_left']} ball{'s' if cur['balls_left'] != 1 else ''}")
        return f"{names[cur['batting']]} need {cur['need']} run{'s' if cur['need'] != 1 else ''}"
    if lead:
        return lead["text"]
    return f"{names[cur['batting']]} {cur['score']}"


# --------------------------------------------------------------------------- #
# Public helpers used by the server
# --------------------------------------------------------------------------- #
def validate_append(match: Dict[str, Any], event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Try an event on top of the current log. Returns None if OK else the error dict."""
    probe = copy.deepcopy(match)
    probe["events"] = list(match["events"]) + [event]
    R = _Replay(normalize_setup(probe))
    # replay quietly up to the last event
    for ev in probe["events"][:-1]:
        try:
            R.apply(ev)
        except RuleError:
            pass
        except Exception:
            pass
    try:
        R.apply(event)
    except RuleError as e:
        return e.to_dict()
    except Exception as e:  # pragma: no cover
        return {"code": "internal", "message": f"{type(e).__name__}: {e}", "hint": None, "soft": False}
    return None
