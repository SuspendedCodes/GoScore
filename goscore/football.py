"""
GoScore football engine
=======================

Same philosophy as the cricket engine: the ordered event log is the single
source of truth and ``derive(match)`` replays it into a complete scoreboard.
Edit / delete / insert / undo / override are all just "change the log, replay".

Rules enforced come from the IFAB Laws of the Game (Law 3 players & substitutes,
Law 5 referee / cards, Law 7 duration, Law 8 start/restart, Law 10 outcome &
penalty shoot-out, Law 12 sanctions, and the IFAB additional permanent
concussion-substitute protocol).  Hard rules reject the event; *soft* rules are
competition choices (substitution numbers, ...) or "probably a slip" checks and can
be forced with ``"force": [code]`` - every forced rule is audited by the store.

STATS ARE MANUAL: possession, shots, passes ... are typed in by the producer through
``stats_set`` events (an override).  Only things that the log already knows
(goals, cards, substitutions, minutes played) are derived automatically - and even
those can be overridden.  There is deliberately NO stat scorer.

Pure python, standard library only.
"""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

ENGINE_VERSION = "1.0"
SPORT = "football"

PHASES = ["pre", "p1", "break1", "p2", "break2", "et1", "break3", "et2", "pre_so", "so", "ended"]
LIVE = ("p1", "p2", "et1", "et2")
PHASE_LABEL = {
    "pre": "Pre-match", "p1": "First half", "break1": "Half-time", "p2": "Second half",
    "break2": "End of 90 minutes", "et1": "Extra time - first half", "break3": "Extra time - half-time",
    "et2": "Extra time - second half", "pre_so": "Penalty shoot-out pending", "so": "Penalty shoot-out",
    "ended": "Full-time",
}
PHASE_SHORT = {"pre": "KO", "p1": "1H", "break1": "HT", "p2": "2H", "break2": "FT", "et1": "ET1", "break3": "ET HT",
               "et2": "ET2", "pre_so": "PEN", "so": "PEN", "ended": "FT"}
PERIOD_OF_PHASE = {"p1": 1, "p2": 2, "et1": 3, "et2": 4}
NEXT_START = {"pre": 1, "break1": 2, "break2": 3, "break3": 4}
POSITIONS = ("GK", "DF", "MF", "FW")
GOAL_KINDS = {"open": "Open play", "penalty": "Penalty", "free_kick": "Free kick", "own_goal": "Own goal"}
CARD_REASONS = ["Foul", "Dissent", "Time wasting", "Handball", "Persistent offences", "Unsporting behaviour",
                "Simulation", "Delaying restart", "Entering field without permission", "Violent conduct",
                "Serious foul play", "Denying a goalscoring opportunity", "Offensive language", "Spitting",
                "Second yellow", "Other"]
INFO_KEYS = ("attendance", "weather", "motm", "competition", "stage", "kickoff")
SHOOTOUT_RESULTS = {"scored": "Scored", "saved": "Saved", "missed": "Missed", "post": "Hit the woodwork"}
VAR_KINDS = {"goal": "Goal", "penalty": "Penalty decision", "red_card": "Direct red card", "identity": "Mistaken identity"}
VAR_DECISIONS = {"goal_stands": "Goal stands", "goal_disallowed": "Goal disallowed", "penalty_awarded": "Penalty awarded",
                 "penalty_cancelled": "Penalty cancelled", "red_card_given": "Red card given",
                 "red_card_cancelled": "Red card cancelled", "no_change": "Decision stands"}

# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #
DEFAULT_FORMAT = {
    "label": "League match (2 x 45)",
    "half_min": 45, "et_min": 15, "extra_time": False, "shootout": False,
    "on_field": 11, "min_players": 7, "subs_max": 5, "windows_max": 3, "bench_max": 15,
    "et_extra_sub": True, "concussion_subs": True, "return_subs": False,
    "aggregate": None,                       # {"A": n, "B": n} goals from the earlier leg(s)
}
PRESETS = {
    "league": {"label": "League match (2 x 45)"},
    "cup": {"label": "Knockout (extra time + penalties)", "extra_time": True, "shootout": True},
    "cup_pens": {"label": "Knockout (straight to penalties)", "shootout": True},
    "second_leg": {"label": "Second leg (aggregate, ET + penalties)", "extra_time": True, "shootout": True,
                   "aggregate": {"A": 0, "B": 0}},
    "youth": {"label": "Youth (2 x 35, rolling subs)", "half_min": 35, "subs_max": 99, "windows_max": 99,
              "return_subs": True, "concussion_subs": False},
    "seven": {"label": "7-a-side (2 x 25, rolling subs)", "half_min": 25, "on_field": 7, "min_players": 5,
              "subs_max": 99, "windows_max": 99, "return_subs": True, "bench_max": 10},
    "custom": {"label": "Custom"},
}


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def make_format(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    f = copy.deepcopy(DEFAULT_FORMAT)
    cfg = cfg or {}
    preset = cfg.get("preset")
    if preset in PRESETS:
        f.update(copy.deepcopy(PRESETS[preset]))
    for k, v in cfg.items():
        if k in f and k != "label" or k == "label":
            f[k] = v
    for k, lo, hi in (("half_min", 1, 60), ("et_min", 1, 30), ("on_field", 3, 11), ("min_players", 1, 11),
                      ("subs_max", 0, 99), ("windows_max", 0, 99), ("bench_max", 0, 30)):
        f[k] = max(lo, min(hi, _i(f.get(k), DEFAULT_FORMAT[k])))
    for k in ("extra_time", "shootout", "et_extra_sub", "concussion_subs", "return_subs"):
        f[k] = bool(f.get(k))
    agg = f.get("aggregate")
    if isinstance(agg, dict):
        f["aggregate"] = {"A": max(0, _i(agg.get("A"))), "B": max(0, _i(agg.get("B")))}
    else:
        f["aggregate"] = None
    f["label"] = str(f.get("label") or DEFAULT_FORMAT["label"])
    return f


class RuleError(Exception):
    def __init__(self, code: str, message: str, hint: Optional[str] = None, soft: bool = False):
        super().__init__(message)
        self.code, self.message, self.hint, self.soft = code, message, hint, soft

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint, "soft": self.soft}


def new_id(prefix: str = "e") -> str:
    return prefix + uuid.uuid4().hex[:10]


# --------------------------------------------------------------------------- #
# Statistics catalogue (manual entry; a few are auto-derived defaults)
# kind: int | pct | dec ;  auto: derived from the log when not overridden
# --------------------------------------------------------------------------- #
TEAM_STATS: List[Dict[str, Any]] = [
    {"key": "possession", "label": "Possession", "kind": "pct", "group": "General", "main": True},
    {"key": "shots", "label": "Shots", "kind": "int", "group": "Attack", "main": True},
    {"key": "shots_on_target", "label": "Shots on target", "kind": "int", "group": "Attack", "main": True},
    {"key": "shots_off_target", "label": "Shots off target", "kind": "int", "group": "Attack"},
    {"key": "blocked_shots", "label": "Blocked shots", "kind": "int", "group": "Attack"},
    {"key": "big_chances", "label": "Big chances", "kind": "int", "group": "Attack"},
    {"key": "xg", "label": "Expected goals (xG)", "kind": "dec", "group": "Attack"},
    {"key": "xgot", "label": "xG on target (xGOT)", "kind": "dec", "group": "Attack"},
    {"key": "corners", "label": "Corners", "kind": "int", "group": "Attack", "main": True},
    {"key": "offsides", "label": "Offsides", "kind": "int", "group": "Attack", "main": True},
    {"key": "crosses", "label": "Crosses", "kind": "int", "group": "Attack"},
    {"key": "dribbles", "label": "Dribbles won", "kind": "int", "group": "Attack"},
    {"key": "attacks", "label": "Attacks", "kind": "int", "group": "Attack"},
    {"key": "dangerous_attacks", "label": "Dangerous attacks", "kind": "int", "group": "Attack"},
    {"key": "passes", "label": "Passes", "kind": "int", "group": "Passing", "main": True},
    {"key": "passes_completed", "label": "Passes completed", "kind": "int", "group": "Passing", "main": True},
    {"key": "pass_accuracy", "label": "Pass accuracy", "kind": "pct", "group": "Passing", "main": True},
    {"key": "long_passes", "label": "Long passes", "kind": "int", "group": "Passing"},
    {"key": "fouls", "label": "Fouls", "kind": "int", "group": "Discipline", "main": True},
    {"key": "yellow_cards", "label": "Yellow cards", "kind": "int", "group": "Discipline", "main": True, "auto": True},
    {"key": "red_cards", "label": "Red cards", "kind": "int", "group": "Discipline", "main": True, "auto": True},
    {"key": "tackles", "label": "Tackles", "kind": "int", "group": "Defence"},
    {"key": "interceptions", "label": "Interceptions", "kind": "int", "group": "Defence"},
    {"key": "clearances", "label": "Clearances", "kind": "int", "group": "Defence"},
    {"key": "duels_won", "label": "Duels won", "kind": "int", "group": "Defence"},
    {"key": "aerial_duels_won", "label": "Aerial duels won", "kind": "int", "group": "Defence"},
    {"key": "saves", "label": "Saves", "kind": "int", "group": "Goalkeeping", "main": True},
    {"key": "goals", "label": "Goals", "kind": "int", "group": "General", "auto": True},
    {"key": "penalties", "label": "Penalties awarded", "kind": "int", "group": "General", "auto": True},
    {"key": "substitutions", "label": "Substitutions", "kind": "int", "group": "General", "auto": True},
    {"key": "free_kicks", "label": "Free kicks", "kind": "int", "group": "General"},
    {"key": "throw_ins", "label": "Throw-ins", "kind": "int", "group": "General"},
    {"key": "goal_kicks", "label": "Goal kicks", "kind": "int", "group": "General"},
    {"key": "distance_km", "label": "Distance covered (km)", "kind": "dec", "group": "Physical"},
]
PLAYER_STATS: List[Dict[str, Any]] = [
    {"key": "minutes", "label": "Minutes played", "kind": "int", "auto": True},
    {"key": "goals", "label": "Goals", "kind": "int", "auto": True},
    {"key": "assists", "label": "Assists", "kind": "int", "auto": True},
    {"key": "shots", "label": "Shots", "kind": "int"},
    {"key": "shots_on_target", "label": "Shots on target", "kind": "int"},
    {"key": "xg", "label": "xG", "kind": "dec"},
    {"key": "xa", "label": "xA", "kind": "dec"},
    {"key": "key_passes", "label": "Key passes", "kind": "int"},
    {"key": "passes", "label": "Passes", "kind": "int"},
    {"key": "passes_completed", "label": "Passes completed", "kind": "int"},
    {"key": "pass_accuracy", "label": "Pass accuracy", "kind": "pct"},
    {"key": "touches", "label": "Touches", "kind": "int"},
    {"key": "dribbles", "label": "Dribbles won", "kind": "int"},
    {"key": "tackles", "label": "Tackles", "kind": "int"},
    {"key": "interceptions", "label": "Interceptions", "kind": "int"},
    {"key": "clearances", "label": "Clearances", "kind": "int"},
    {"key": "duels_won", "label": "Duels won", "kind": "int"},
    {"key": "fouls_committed", "label": "Fouls committed", "kind": "int"},
    {"key": "fouls_won", "label": "Fouls won", "kind": "int"},
    {"key": "offsides", "label": "Offsides", "kind": "int"},
    {"key": "yellow_cards", "label": "Yellow cards", "kind": "int", "auto": True},
    {"key": "red_cards", "label": "Red cards", "kind": "int", "auto": True},
    {"key": "saves", "label": "Saves (GK)", "kind": "int"},
    {"key": "goals_conceded", "label": "Goals conceded (GK)", "kind": "int"},
    {"key": "distance_km", "label": "Distance (km)", "kind": "dec"},
    {"key": "rating", "label": "Rating", "kind": "dec"},
]
TEAM_STAT_KEYS = {s["key"]: s for s in TEAM_STATS}
PLAYER_STAT_KEYS = {s["key"]: s for s in PLAYER_STATS}
DEFAULT_STAT_ROWS = ["possession", "shots", "shots_on_target", "corners", "fouls", "offsides", "passes_completed",
                     "pass_accuracy", "yellow_cards", "red_cards"]


def fmt_stat(kind: str, v: Any) -> str:
    if v is None:
        return "-"
    if kind == "pct":
        return f"{round(v)}%"
    if kind == "dec":
        return f"{float(v):.2f}".rstrip("0").rstrip(".") if float(v) != int(float(v)) else str(int(float(v)))
    return str(int(round(v)))


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError("not a number")
    if isinstance(v, str):
        v = v.strip().replace("%", "").replace(",", ".")
        if v == "":
            return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("not a number")
    return f


# --------------------------------------------------------------------------- #
# Setup normalisation
# --------------------------------------------------------------------------- #
def _surname(name: str) -> str:
    parts = [x for x in re.split(r"\s+", (name or "").strip()) if x]
    return parts[-1] if parts else (name or "")


def _xy(x, y):
    """Pitch coordinates in % (x = own goal 0 -> opponent goal 100, y = 0..100 across). (None, None) when unset/invalid."""
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        return None, None
    if not (0 <= fx <= 100 and 0 <= fy <= 100):
        return None, None
    return round(fx, 1), round(fy, 1)


def normalize_setup(match: Dict[str, Any]) -> Dict[str, Any]:
    match["sport"] = SPORT
    match.setdefault("events", [])
    match["format"] = make_format(match.get("format"))
    teams = match.setdefault("teams", {})
    for tid, default_name, col, col2 in (("A", "Home", "#1f6feb", "#ffffff"), ("B", "Away", "#d4351c", "#ffffff")):
        t = teams.setdefault(tid, {})
        t.setdefault("name", default_name)
        t.setdefault("short", re.sub(r"[^A-Za-z0-9]", "", t["name"])[:3].upper() or tid)
        t.setdefault("color", col)
        t.setdefault("color2", col2)
        t.setdefault("formation", "4-4-2")
        t.setdefault("coach", "")
        t.setdefault("logo", "")
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
            p.setdefault("short", _surname(p["name"]))
            num = p.get("number")
            p["number"] = _i(num, 0) if num not in (None, "") else None
            if p.get("pos") not in POSITIONS:
                p["pos"] = ""
            p["x"], p["y"] = _xy(p.get("x"), p.get("y"))
            p["captain"] = bool(p.get("captain"))
            if "xi" not in p:
                p["xi"] = idx < match["format"]["on_field"]
            p["xi"] = bool(p["xi"])
            p["squad"] = bool(p.get("squad", True)) or p["xi"]
    match.setdefault("officials", {})
    for k in ("referee", "ar1", "ar2", "fourth", "var", "avar"):
        match["officials"].setdefault(k, "")
    match.setdefault("info", {})
    for k in INFO_KEYS:
        match["info"].setdefault(k, "")
    match.setdefault("form", {"A": "", "B": ""})
    match.setdefault("h2h", {"A": 0, "D": 0, "B": 0})
    return match


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
CLOCK_TYPES = {"period_start", "period_end", "pause", "resume", "clock_set", "added_time", "phase_set"}
STAMPED = {"goal", "card", "sub", "penalty_award", "penalty_miss", "var_check", "var_result", "goal_cancel",
           "card_rescind", "incident", "pos_change", "captain_set"}
POST_MATCH_OK = {"pitch_set", "info", "stats_set", "result", "clear_result", "phase_set", "score_set", "incident", "captain_set",
                 "pos_change", "card", "card_rescind", "goal_cancel", "var_check", "var_result", "note"}


class _Replay:
    def __init__(self, match: Dict[str, Any]):
        self.m = match
        self.fmt = match["format"]
        self.half = self.fmt["half_min"] * 60000
        self.et = self.fmt["et_min"] * 60000
        self.phase = "pre"
        self.period = 0
        self.clock = {"running": False, "base_ms": 0, "since": None}
        self.period_len: Dict[int, int] = {}
        self.added: Dict[int, int] = {}
        self.goals: List[Dict[str, Any]] = []
        self.adj = {"A": 0, "B": 0}
        self.cards: List[Dict[str, Any]] = []
        self.staff_cards: List[Dict[str, Any]] = []
        self.subs: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.so_kicks: List[Dict[str, Any]] = []
        self.so_first: Optional[str] = None
        self.so_done = False
        self.so_winner: Optional[str] = None
        self.result_ev: Optional[Dict[str, Any]] = None
        self.abandoned: Optional[Dict[str, Any]] = None
        self.var = {"active": False, "kind": None, "since_id": None, "team": None, "text": ""}
        self.var_history: List[Dict[str, Any]] = []
        self.penalties_awarded = {"A": 0, "B": 0}
        self.penalty_misses: List[Dict[str, Any]] = []
        self.stat_over = {"A": {}, "B": {}}
        self.pstat_over: Dict[str, Dict[str, Any]] = {}
        self.info = dict(match.get("info") or {})
        self.overrides: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.event_status: Dict[str, Any] = {}
        self.last_event: Optional[Dict[str, Any]] = None
        self.sub_state = {t: {"used": 0, "windows": 0, "concussion": 0, "additional_owed": 0, "additional_used": 0,
                              "last_window_key": None, "free": 0} for t in "AB"}
        self.window_counter = 0
        self.P: Dict[str, Dict[str, Dict[str, Any]]] = {"A": {}, "B": {}}
        self.pid_team: Dict[str, str] = {}
        self.formation = {t: match["teams"][t]["formation"] for t in "AB"}
        for tid in "AB":
            for p in match["teams"][tid]["players"]:
                self.P[tid][p["id"]] = {
                    "id": p["id"], "team": tid, "name": p["name"], "short": p["short"], "number": p["number"],
                    "pos": p["pos"], "captain": p["captain"], "slot": None, "squad": p["squad"], "x": p.get("x"), "y": p.get("y"),
                    "status": "on" if p["xi"] else ("bench" if p["squad"] else "out_of_squad"),
                    "started": p["xi"], "on_abs": 0 if p["xi"] else None, "off_abs": None,
                    "yellows": 0, "red": False, "goals": 0, "own_goals": 0, "assists": 0, "replaced_by": None,
                    "replacing": None, "dismissal": None,
                }
                self.pid_team[p["id"]] = tid
            slot = 0
            for p in match["teams"][tid]["players"]:
                if p["xi"]:
                    self.P[tid][p["id"]]["slot"] = slot
                    slot += 1

    # ---- clock ----------------------------------------------------------------- #
    def p_len(self, period: int) -> int:
        return self.half if period in (1, 2) else self.et

    def p_off(self, period: int) -> int:
        return {1: 0, 2: self.half, 3: 2 * self.half, 4: 2 * self.half + self.et}.get(period, 0)

    def elapsed(self, ts: int) -> int:
        c = self.clock
        if c["running"] and c["since"] is not None:
            return c["base_ms"] + max(0, ts - c["since"])
        return c["base_ms"]

    def stamp(self, ts: int) -> Dict[str, Any]:
        p = self.period
        if p == 0:
            return {"period": 0, "min": 0, "extra": 0, "abs": 0, "label": ""}
        if p == 5:
            return {"period": 5, "min": 0, "extra": 0, "abs": 0, "label": "PEN"}
        e = self.elapsed(ts)
        reg = self.p_len(p)
        off_min = self.p_off(p) // 60000
        if e >= reg:
            base = off_min + reg // 60000
            extra = (e - reg) // 60000 + 1
            return {"period": p, "min": base, "extra": extra, "abs": base + extra, "label": f"{base}+{extra}'"}
        m = off_min + e // 60000 + 1
        return {"period": p, "min": m, "extra": 0, "abs": m, "label": f"{m}'"}

    def when(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        """Time stamp of an event: explicit (stamped / typed) values win over the clock."""
        if ev.get("min") not in (None, "") or ev.get("period") not in (None, ""):
            mn, ex = _i(ev.get("min")), _i(ev.get("extra"))
            per = _i(ev.get("period"), self.period)
            lab = (f"{mn}+{ex}'" if ex else f"{mn}'") if mn else (ev.get("label") or "")
            if per == 5:
                lab = "PEN"
            return {"period": per, "min": mn, "extra": ex, "abs": _i(ev.get("abs"), mn + ex), "label": lab}
        return self.stamp(_i(ev.get("ts")))

    # ---- helpers -------------------------------------------------------------- #
    def score(self) -> Dict[str, int]:
        s = {"A": self.adj["A"], "B": self.adj["B"]}
        for g in self.goals:
            if not g["cancelled"]:
                s[g["team"]] += 1
        s["A"], s["B"] = max(0, s["A"]), max(0, s["B"])
        return s

    def total(self) -> Dict[str, int]:
        s = self.score()
        agg = self.fmt.get("aggregate") or {"A": 0, "B": 0}
        return {"A": s["A"] + agg["A"], "B": s["B"] + agg["B"]}

    def level(self) -> bool:
        t = self.total()
        return t["A"] == t["B"]

    def on_field(self, tid: str) -> List[Dict[str, Any]]:
        return [p for p in self.P[tid].values() if p["status"] == "on"]

    def player(self, pid: Any, team: Optional[str] = None, required=False, code="unknown_player") -> Optional[Dict[str, Any]]:
        if not pid:
            if required:
                raise RuleError(code, "Choose a player.")
            return None
        t = self.pid_team.get(pid)
        if not t or (team and t != team):
            raise RuleError("player_team", "That player is not in the selected team.", "Pick the player from the correct squad.")
        return self.P[t][pid]

    def add_tl(self, ev: Dict[str, Any], etype: str, team: Optional[str], text: str, w: Dict[str, Any], **extra):
        row = {"id": ev.get("id"), "type": etype, "team": team, "text": text, "label": w["label"], "min": w["min"],
               "extra": w["extra"], "abs": w["abs"], "period": w["period"], "cancelled": False}
        row.update(extra)
        self.timeline.append(row)
        return row

    def tl_by_id(self, eid: Any) -> Optional[Dict[str, Any]]:
        for r in self.timeline:
            if r["id"] == eid:
                return r
        return None

    def _name(self, p: Optional[Dict[str, Any]], fallback: str = "") -> str:
        return p["name"] if p else fallback

    def apply(self, ev: Dict[str, Any]):
        t = ev.get("type")
        h = getattr(self, f"_ev_{t}", None)
        if h is None:
            raise RuleError("unknown_event", f"Unknown event type '{t}'.")
        if self.phase == "ended" and t not in POST_MATCH_OK:
            raise RuleError("match_over", "The match has ended.",
                            "Use Undo, or Corrections → insert the event before the final whistle.")
        h(ev)

    # ---- clock & phase events ------------------------------------------------------ #
    def _ev_period_start(self, ev):
        force = set(ev.get("force") or [])
        want = NEXT_START.get(self.phase)
        per = _i(ev.get("period"), want or 0)
        if want is None or per != want:
            raise RuleError("bad_period", f"Cannot start that period now ({PHASE_LABEL.get(self.phase)}).",
                            "Use 'Set phase' in Overrides if the match state is wrong.")
        if per == 3:
            if not self.fmt["extra_time"] and "no_et" not in force:
                raise RuleError("no_et", "Extra time is not part of this competition's format.",
                                "Enable extra time in the match setup, or force.", soft=True)
            if not self.level() and "et_not_needed" not in force:
                raise RuleError("et_not_needed", "The scores are not level, so extra time is not needed.", soft=True)
        ts = _i(ev.get("ts"))
        ago = max(0, _i(ev.get("ago_ms")))
        self.period = per
        self.phase = {1: "p1", 2: "p2", 3: "et1", 4: "et2"}[per]
        self.clock = {"running": True, "base_ms": ago, "since": ts}
        self.added[per] = 0
        w = {"period": per, "min": 0, "extra": 0, "abs": 0, "label": ""}
        name = {1: "Kick-off", 2: "Second half begins", 3: "Extra time begins", 4: "Extra time - second half begins"}[per]
        self.add_tl(ev, "period", None, name, w, marker="start")

    def _ev_period_end(self, ev):
        force = set(ev.get("force") or [])
        if self.phase not in LIVE:
            raise RuleError("not_live", "No period is in progress.")
        ts = _i(ev.get("ts"))
        e = self.elapsed(ts)
        reg = self.p_len(self.period)
        if e < reg - 60000 and "premature" not in force:
            raise RuleError("premature", f"The clock shows {e // 60000}:{(e // 1000) % 60:02d}, but the period is {reg // 60000} minutes.",
                            "If the clock was started late use Overrides → Set clock first; if the referee ended it early (e.g. abandoned), force it.",
                            soft=True)
        per = self.period
        self.period_len[per] = e
        self.clock = {"running": False, "base_ms": e, "since": None}
        w = self.stamp(ts)
        if per == 1:
            self.phase = "break1"
            self.add_tl(ev, "period", None, "Half-time", w, marker="ht")
        elif per == 3:
            self.phase = "break3"
            self.add_tl(ev, "period", None, "End of first half of extra time", w, marker="et_ht")
        else:
            self._after_regulation(ev, w, per)

    def _after_regulation(self, ev, w, per):
        """End of the 2nd half (per=2) or of extra time (per=4): what happens next?"""
        decided = not self.level()
        if decided:
            self._finish(ev, w, per)
        elif per == 2 and self.fmt["extra_time"]:
            self.phase = "break2"
            self.add_tl(ev, "period", None, "End of normal time - extra time to be played", w, marker="nt")
        elif self.fmt["shootout"]:
            self.phase = "pre_so"
            self.period = 5 if per == 4 else self.period
            self.add_tl(ev, "period", None, "Level - penalty shoot-out to follow" if per == 4 else
                        "Level after 90 minutes - penalty shoot-out to follow", w, marker="nt")
        else:
            self._finish(ev, w, per)

    def _finish(self, ev, w, per):
        self.phase = "ended"
        self.clock = {"running": False, "base_ms": self.clock["base_ms"], "since": None}
        self.add_tl(ev, "period", None, "Full-time" if per == 2 else "Full-time (after extra time)", w, marker="ft")

    def _ev_pause(self, ev):
        if self.phase not in LIVE:
            raise RuleError("not_live", "The clock is not running a period.")
        if not self.clock["running"]:
            raise RuleError("already_paused", "The clock is already paused.")
        ts = _i(ev.get("ts"))
        e = self.elapsed(ts)
        self.clock = {"running": False, "base_ms": e, "since": None}
        self.add_tl(ev, "clock", None, "Play stopped" + (f" - {ev['reason']}" if ev.get("reason") else ""), self.stamp(ts), marker="pause")

    def _ev_resume(self, ev):
        if self.phase not in LIVE:
            raise RuleError("not_live", "No period is in progress.")
        if self.clock["running"]:
            raise RuleError("already_running", "The clock is already running.")
        self.clock = {"running": True, "base_ms": self.clock["base_ms"], "since": _i(ev.get("ts"))}
        self.add_tl(ev, "clock", None, "Play resumed", self.stamp(_i(ev.get("ts"))), marker="resume")

    def _ev_clock_set(self, ev):
        """Manual override: set the clock to a match time (minutes + seconds), e.g. 67:30."""
        if self.phase not in LIVE:
            raise RuleError("not_live", "The clock can only be set while a period is in progress.",
                            "Use Overrides → Set phase first if the phase is wrong.")
        mm = _i(ev.get("minute"), -1)
        ss = _i(ev.get("second"), 0)
        if "match_ms" in ev and ev.get("match_ms") is not None:
            tot = _i(ev["match_ms"], -1)
        else:
            tot = mm * 60000 + ss * 1000 if mm >= 0 else -1
        if tot < 0 or not 0 <= ss < 60:
            raise RuleError("bad_clock", "Enter a valid time (minutes 0+, seconds 0-59).")
        e = tot - self.p_off(self.period)
        if e < 0:
            raise RuleError("bad_clock", f"That time is before the start of this period ({self.p_off(self.period) // 60000}:00).")
        if e > self.p_len(self.period) + 60 * 60000:
            raise RuleError("bad_clock", "That time is unreasonably far past the end of this period.")
        self.clock = {"running": self.clock["running"], "base_ms": e, "since": _i(ev.get("ts")) if self.clock["running"] else None}
        self.overrides.append({"id": ev.get("id"), "type": "clock_set", "text": f"Clock set to {tot // 60000}:{(tot // 1000) % 60:02d}"})

    def _ev_added_time(self, ev):
        if self.phase not in LIVE:
            raise RuleError("not_live", "Added time is announced during a period.")
        m = _i(ev.get("minutes"), -1)
        if not 0 <= m <= 30:
            raise RuleError("bad_added", "Added time must be 0-30 minutes.")
        self.added[self.period] = m
        self.add_tl(ev, "added_time", None, f"{m} minute{'s' if m != 1 else ''} of added time", self.stamp(_i(ev.get("ts"))),
                    minutes=m)

    def _ev_phase_set(self, ev):
        """Emergency override of the match phase (and optionally the clock)."""
        ph = ev.get("phase")
        if ph not in PHASES:
            raise RuleError("bad_phase", "Unknown phase.")
        self.phase = ph
        if ph in LIVE:
            self.period = PERIOD_OF_PHASE[ph]
            e = _i(ev.get("elapsed_ms"), self.clock["base_ms"])
            run = bool(ev.get("running", False))
            self.clock = {"running": run, "base_ms": e, "since": _i(ev.get("ts")) if run else None}
        else:
            self.clock = {"running": False, "base_ms": self.clock["base_ms"], "since": None}
            if ph in ("pre_so", "so"):
                self.period = 5
            elif ph == "pre":
                self.period = 0
        self.overrides.append({"id": ev.get("id"), "type": "phase_set", "text": f"Phase forced to: {PHASE_LABEL[ph]}"})

    def _ev_info(self, ev):
        k = ev.get("key")
        if k not in INFO_KEYS and k not in ("referee", "ar1", "ar2", "fourth", "var", "avar"):
            raise RuleError("bad_info", "Unknown info field.")
        if k in INFO_KEYS:
            self.info[k] = ev.get("value")
        else:
            self.m.setdefault("officials", {})  # officials are setup data; info events only cover INFO_KEYS
            raise RuleError("bad_info", "Edit officials in the match setup.")

    def _ev_note(self, ev):
        pass

    def _ev_incident(self, ev):
        """Generic timeline item: injury, drinks break, delay, pitch invasion, ..."""
        w = self.when(ev)
        txt = str(ev.get("text") or "").strip()
        if not txt:
            raise RuleError("empty", "Write what happened.")
        team = ev.get("team") if ev.get("team") in ("A", "B") else None
        self.add_tl(ev, "incident", team, txt, w, kind=ev.get("kind") or "other")

    # ---- goals ------------------------------------------------------------------ #
    def _check_on_pitch(self, p, force, what):
        if p and p["status"] != "on" and "not_on_pitch" not in force:
            why = {"bench": "is on the bench (not yet on the pitch)", "off": "has been substituted off",
                   "sent_off": "has been sent off", "out_of_squad": "is not in the match squad",
                   "bench_sent_off": "was sent off from the bench"}.get(p["status"], "is not on the pitch")
            raise RuleError("not_on_pitch", f"{p['name']} {why} - cannot be the {what}.",
                            "Fix the earlier substitution/card, or force if the earlier record is wrong.", soft=True)

    def _ev_goal(self, ev):
        force = set(ev.get("force") or [])
        if self.phase not in LIVE:
            raise RuleError("goal_not_live", "A goal can only be scored while a period is in progress.",
                            "Penalty shoot-out kicks use the shoot-out panel. If you pressed End half too early, Undo.")
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team that is credited with the goal.")
        kind = ev.get("kind") or "open"
        if kind not in GOAL_KINDS:
            raise RuleError("bad_kind", "Unknown goal type.")
        og = kind == "own_goal"
        other = "B" if team == "A" else "A"
        scorer_team = other if og else team          # own goal: the scorer plays for the OTHER team, credit goes to `team`
        scorer = self.player(ev.get("player"), scorer_team)
        assist = None
        if ev.get("assist"):
            if og:
                raise RuleError("og_assist", "An own goal has no assist.")
            assist = self.player(ev.get("assist"), team)
            if scorer and assist["id"] == scorer["id"]:
                raise RuleError("same_player", "The scorer and the assist must be different players.")
            self._check_on_pitch(assist, force, "assist provider")
        if scorer is None and not ev.get("player_name") and "no_scorer" not in force and self.pid_team:
            pass   # unknown scorers are allowed (stats/lineups may be incomplete); shown as "Unknown"
        self._check_on_pitch(scorer, force, "scorer")
        w = self.when(ev)
        g = {"id": ev.get("id"), "team": team, "kind": kind, "player": scorer["id"] if scorer else None,
             "player_name": scorer["name"] if scorer else (ev.get("player_name") or ""),
             "assist": assist["id"] if assist else None, "assist_name": assist["name"] if assist else "",
             "cancelled": False, "label": w["label"], "min": w["min"], "extra": w["extra"], "abs": w["abs"], "period": w["period"]}
        self.goals.append(g)
        if scorer:
            if og:
                scorer["own_goals"] += 1
            else:
                scorer["goals"] += 1
        if assist:
            assist["assists"] += 1
        nm = g["player_name"] or "Unknown scorer"
        if og:
            nm += " (own goal)"
        elif kind == "penalty":
            nm += " (pen)"
        row = self.add_tl(ev, "goal", team, nm, w, kind=kind, player=g["player"], assist=g["assist"],
                          assist_name=g["assist_name"], score=dict(self.score()))
        row["score"] = dict(self.score())

    def _ev_goal_cancel(self, ev):
        ref = ev.get("ref")
        g = None
        if ref:
            g = next((x for x in self.goals if x["id"] == ref), None)
            if not g:
                raise RuleError("no_goal", "That goal does not exist in the log.")
        else:
            g = next((x for x in reversed(self.goals) if not x["cancelled"]), None)
            if not g:
                raise RuleError("no_goal", "There is no goal to disallow.")
        if g["cancelled"]:
            raise RuleError("already_cancelled", "That goal is already disallowed.")
        g["cancelled"] = True
        g["cancel_reason"] = ev.get("reason") or ""
        for pid, key in ((g["player"], "own_goals" if g["kind"] == "own_goal" else "goals"), (g["assist"], "assists")):
            if pid:
                self.P[self.pid_team[pid]][pid][key] = max(0, self.P[self.pid_team[pid]][pid][key] - 1)
        row = self.tl_by_id(g["id"])
        if row:
            row["cancelled"] = True
            row["cancel_reason"] = g["cancel_reason"]
        w = self.when(ev)
        self.add_tl(ev, "goal_cancel", g["team"], f"Goal disallowed{' - ' + ev['reason'] if ev.get('reason') else ''}", w, ref=g["id"],
                    player_name=g["player_name"])

    def _ev_score_set(self, ev):
        """Manual override: pin the score. Goals recorded afterwards are added on top."""
        a, b = _i(ev.get("A"), -1), _i(ev.get("B"), -1)
        if a < 0 or b < 0 or a > 99 or b > 99:
            raise RuleError("bad_score", "Enter whole-number scores between 0 and 99.")
        cur = {"A": 0, "B": 0}
        for g in self.goals:
            if not g["cancelled"]:
                cur[g["team"]] += 1
        self.adj = {"A": a - cur["A"], "B": b - cur["B"]}
        self.overrides.append({"id": ev.get("id"), "type": "score_set", "text": f"Score pinned to {a}-{b}"})

    # ---- penalties in play ----------------------------------------------------------- #
    def _ev_penalty_award(self, ev):
        if self.phase not in LIVE:
            raise RuleError("not_live", "A penalty kick is awarded during play.")
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team awarded the penalty.")
        self.penalties_awarded[team] += 1
        self.add_tl(ev, "penalty", team, "Penalty awarded" + (f" - {ev['reason']}" if ev.get("reason") else ""), self.when(ev))

    def _ev_penalty_miss(self, ev):
        if self.phase not in LIVE:
            raise RuleError("not_live", "A penalty kick is taken during play.")
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team taking the penalty.")
        p = self.player(ev.get("player"), team)
        out = ev.get("outcome") or "saved"
        if out not in ("saved", "missed", "post"):
            raise RuleError("bad_outcome", "Penalty outcome must be saved / missed / hit the woodwork.")
        w = self.when(ev)
        nm = p["name"] if p else (ev.get("player_name") or "Penalty")
        self.penalty_misses.append({"team": team, "player": p["id"] if p else None})
        self.add_tl(ev, "penalty_miss", team, f"{nm} - penalty {SHOOTOUT_RESULTS.get(out if out != 'post' else 'post').lower()}", w,
                    outcome=out, player=p["id"] if p else None)

    # ---- cards ---------------------------------------------------------------------- #
    def _ev_card(self, ev):
        force = set(ev.get("force") or [])
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team of the person shown the card.")
        color = ev.get("color")
        if color not in ("yellow", "red"):
            raise RuleError("bad_color", "A card is yellow or red.")
        w = self.when(ev)
        reason = ev.get("reason") or ""
        if ev.get("target") == "staff" or (ev.get("staff_name") and not ev.get("player")):
            nm = str(ev.get("staff_name") or "Team official").strip()
            row = {"id": ev.get("id"), "team": team, "name": nm, "color": color, "label": w["label"], "cancelled": False}
            self.staff_cards.append(row)
            self.add_tl(ev, "card", team, f"{nm} (team official)", w, color=color, staff=True, reason=reason)
            return
        p = self.player(ev.get("player"), team, required=True)
        assert p
        if p["status"] == "sent_off" or p["status"] == "bench_sent_off":
            raise RuleError("already_sent_off", f"{p['name']} has already been sent off - a player cannot be shown another card.",
                            "Check the player, or delete the earlier card.")
        if p["status"] == "out_of_squad":
            raise RuleError("not_in_squad", f"{p['name']} is not in the match squad.")
        # cautions/dismissals are possible for named substitutes and substituted players too (Law 12)
        kind = color
        if color == "yellow" and p["yellows"] >= 1:
            kind = "yellow2"
        p_before = p["status"]
        row = {"id": ev.get("id"), "team": team, "player": p["id"], "color": color, "kind": kind, "reason": reason,
               "label": w["label"], "abs": w["abs"], "cancelled": False, "prev_status": p_before}
        self.cards.append(row)
        sent = kind in ("red", "yellow2")
        if color == "yellow":
            p["yellows"] += 1
        if sent:
            p["red"] = True
            p["dismissal"] = kind
            p["status"] = "bench_sent_off" if p_before == "bench" else ("sent_off" if p_before == "on" else p_before)
            if p_before == "on":
                p["off_abs"] = w["abs"]
            else:
                p["status"] = p["status"] if p_before in ("bench",) else p_before
                if p_before == "off":
                    p["status"] = "off"           # already substituted off: stays 'off' but flagged red
        txt = {"yellow": "Yellow card", "yellow2": "Second yellow - sent off", "red": "Red card"}[kind]
        self.add_tl(ev, "card", team, f"{p['name']}", w, color="yellow" if kind == "yellow" else ("yellow2" if kind == "yellow2" else "red"),
                    kind=kind, player=p["id"], reason=reason, card_text=txt)

    def _ev_card_rescind(self, ev):
        ref = ev.get("ref")
        c = next((x for x in self.cards if x["id"] == ref), None) if ref else next((x for x in reversed(self.cards) if not x["cancelled"]), None)
        s = None
        if not c:
            s = next((x for x in self.staff_cards if x["id"] == ref), None) if ref else None
            if not s:
                raise RuleError("no_card", "There is no card to rescind.")
        if (c or s)["cancelled"]:
            raise RuleError("already_cancelled", "That card is already rescinded.")
        w = self.when(ev)
        if s:
            s["cancelled"] = True
            row = self.tl_by_id(s["id"])
            if row:
                row["cancelled"] = True
            self.add_tl(ev, "card_rescind", s["team"], f"{s['name']} card rescinded", w, ref=s["id"])
            return
        c["cancelled"] = True
        p = self.P[c["team"]][c["player"]]
        if c["color"] == "yellow":
            p["yellows"] = max(0, p["yellows"] - 1)
        if c["kind"] in ("red", "yellow2"):
            p["red"] = any(x for x in self.cards if x["player"] == p["id"] and not x["cancelled"] and x["kind"] in ("red", "yellow2"))
            if not p["red"]:
                p["dismissal"] = None
                if p["status"] in ("sent_off", "bench_sent_off"):
                    p["status"] = c["prev_status"] if c["prev_status"] in ("on", "bench") else "on"
                    p["off_abs"] = None
        row = self.tl_by_id(c["id"])
        if row:
            row["cancelled"] = True
        self.add_tl(ev, "card_rescind", c["team"], f"{p['name']} - card rescinded", w, ref=c["id"], player=p["id"])

    # ---- substitutions ------------------------------------------------------------------ #
    def _ev_sub(self, ev):
        force = set(ev.get("force") or [])
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team making the substitution.")
        off = self.player(ev.get("off"), team, required=True, code="no_off")
        on = self.player(ev.get("on"), team, required=True, code="no_on")
        assert off and on
        if off["id"] == on["id"]:
            raise RuleError("same_player", "The player coming on and the player going off must be different.")
        kind = ev.get("kind") or "normal"
        if kind not in ("normal", "concussion", "additional", "replacement"):
            raise RuleError("bad_kind", "Unknown substitution type.")
        if self.phase in ("so", "pre_so") and "so_sub" not in force:
            raise RuleError("so_sub", "During the shoot-out only an injured goalkeeper may be replaced.",
                            "Force it if this is a goalkeeper replacement.", soft=True)
        w = self.when(ev)
        st = self.sub_state[team]
        if kind == "replacement":
            # Law 3: a player sent off after the team list is handed in but BEFORE kick-off may be replaced by a named
            # substitute; that does not use up one of the team's substitutions.
            if self.phase != "pre" or off["status"] != "sent_off":
                raise RuleError("bad_replacement", "A sent-off player can only be replaced if the card was shown before kick-off.")
        else:
            if off["status"] != "on":
                why = {"off": "has already been substituted", "sent_off": "has been sent off and cannot be replaced",
                       "bench": "has not entered the pitch yet", "bench_sent_off": "was sent off from the bench"}.get(off["status"], "is not on the pitch")
                raise RuleError("off_not_on", f"{off['name']} {why}.", "Choose a player who is currently on the pitch.")
        if on["status"] == "off" and not self.fmt["return_subs"] and "return" not in force:
            raise RuleError("return", f"{on['name']} was already substituted and cannot return.",
                            "Law 3: a substituted player may not take any further part (return substitutions only in youth/veterans/grassroots, "
                            "or when the competition approves). Force it only if that applies.", soft=True)
        if on["status"] in ("sent_off", "bench_sent_off"):
            raise RuleError("sent_off_sub", f"{on['name']} has been sent off and cannot play.")
        if on["status"] == "on":
            raise RuleError("on_already", f"{on['name']} is already on the pitch.")
        if on["status"] == "out_of_squad":
            raise RuleError("not_in_squad", f"{on['name']} is not a named substitute.", "Add the player to the match squad in setup.")
        if on["status"] not in ("bench", "off"):
            raise RuleError("on_bad", f"{on['name']} cannot come on.")
        # --- competition limits (soft) ---
        in_break = self.phase in ("pre", "break1", "break2", "break3", "pre_so")
        in_et = self.period in (3, 4) or self.phase in ("break3",)
        counts_total = kind == "normal"
        counts_window = kind == "normal" and not in_break
        if kind == "concussion":
            if not self.fmt["concussion_subs"] and "concussion" not in force:
                raise RuleError("concussion", "Concussion substitutes are not enabled for this competition.", soft=True)
            if st["concussion"] >= 1 and "concussion" not in force:
                raise RuleError("concussion", f"{self.m['teams'][team]['name']} has already used its concussion substitute (max 1 per match).", soft=True)
        if kind == "additional":
            if st["additional_owed"] - st["additional_used"] <= 0 and "additional" not in force:
                raise RuleError("additional", "An additional substitute is only available after the opponent used a concussion substitute.", soft=True)
        if counts_total:
            mx = self.fmt["subs_max"] + (1 if (self.fmt["et_extra_sub"] and in_et and self.fmt["extra_time"]) else 0)
            if st["used"] >= mx and "subs_max" not in force:
                raise RuleError("subs_max", f"{self.m['teams'][team]['name']} has already made {st['used']} of {mx} permitted substitutions.",
                                "Competition rule - force it if your competition allows more.", soft=True)
        window_key = None
        if counts_window:
            same = bool(ev.get("with_prev")) and st["last_window_key"] is not None and st.get("last_window_phase") == self.phase
            if not same:
                mxw = self.fmt["windows_max"] + (1 if (self.fmt["et_extra_sub"] and in_et and self.fmt["extra_time"]) else 0)
                if st["windows"] >= mxw and "windows_max" not in force:
                    raise RuleError("windows_max", f"{self.m['teams'][team]['name']} has already used {st['windows']} of {mxw} substitution opportunities.",
                                    "Substitutions at half-time don't use an opportunity. Tick 'same stoppage' if this is part of the same stoppage, or force.",
                                    soft=True)
        # --- apply ---
        if counts_window:
            if not (bool(ev.get("with_prev")) and st["last_window_key"] is not None and st.get("last_window_phase") == self.phase):
                st["windows"] += 1
                self.window_counter += 1
                st["last_window_key"] = self.window_counter
                st["last_window_phase"] = self.phase
        if kind == "normal":
            st["used"] += 1
        elif kind == "concussion":
            st["concussion"] += 1
            self.sub_state["B" if team == "A" else "A"]["additional_owed"] += 1
        elif kind == "additional":
            st["additional_used"] += 1
        slot = off["slot"]
        if kind != "replacement":
            off["status"] = "off"
            off["off_abs"] = w["abs"]
            off["replaced_by"] = on["id"]
        else:
            off["replaced_by"] = on["id"]
        on["status"] = "on"
        on["on_abs"] = w["abs"]
        on["replacing"] = off["id"]
        on["slot"] = slot
        if ev.get("x") is not None and ev.get("y") is not None:
            on["x"], on["y"] = _xy(ev.get("x"), ev.get("y"))
        elif kind != "replacement" or off["status"] == "sent_off":
            on["x"], on["y"] = off.get("x"), off.get("y")        # the substitute takes the position of the player he replaces
        if not on["pos"] or ev.get("pos") in POSITIONS:
            on["pos"] = ev.get("pos") if ev.get("pos") in POSITIONS else off["pos"]
        if off["captain"]:
            off["captain"] = False                  # armband passes (shown only if scorer re-assigns with captain_set)
        rec = {"id": ev.get("id"), "team": team, "off": off["id"], "on": on["id"], "kind": kind, "label": w["label"], "abs": w["abs"],
               "phase": self.phase}
        self.subs.append(rec)
        self.add_tl(ev, "sub", team, f"{on['name']} on, {off['name']} off", w, off=off["id"], on=on["id"], kind=kind,
                    off_name=off["name"], on_name=on["name"], off_number=off["number"], on_number=on["number"])

    def _ev_pos_change(self, ev):
        team = ev.get("team")
        p = self.player(ev.get("player"), team, required=True)
        assert p
        if ev.get("pos") not in POSITIONS:
            raise RuleError("bad_pos", "Position must be GK, DF, MF or FW.")
        p["pos"] = ev["pos"]
        self.overrides.append({"id": ev.get("id"), "type": "pos_change", "text": f"{p['name']} now plays {ev['pos']}"})

    def _ev_pitch_set(self, ev):
        """Drag-and-drop pitch layout: {team, positions:{pid:{x,y}|null}, formation?, reset?}. Never counts as a match event."""
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose a team.")
        if ev.get("reset"):
            for q in self.P[team].values():
                q["x"] = q["y"] = None
        for pid, pos in (ev.get("positions") or {}).items():
            p = self.player(pid, team, required=True)
            assert p
            if pos is None:
                p["x"] = p["y"] = None
                continue
            x, y = _xy((pos or {}).get("x"), (pos or {}).get("y"))
            if x is None:
                raise RuleError("bad_xy", f"Position for {p['name']} must be x and y between 0 and 100.")
            p["x"], p["y"] = x, y
        f = (ev.get("formation") or "").strip()
        if f:
            self.formation[team] = f[:20]

    def _ev_captain_set(self, ev):
        team = ev.get("team")
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose a team.")
        p = self.player(ev.get("player"), team, required=True)
        for q in self.P[team].values():
            q["captain"] = False
        assert p
        p["captain"] = True
        self.overrides.append({"id": ev.get("id"), "type": "captain_set", "text": f"{p['name']} is captain"})

    # ---- VAR ------------------------------------------------------------------------------ #
    def _ev_var_check(self, ev):
        kind = ev.get("kind") or "goal"
        if kind not in VAR_KINDS:
            raise RuleError("bad_var", "Unknown VAR check type.")
        team = ev.get("team") if ev.get("team") in ("A", "B") else None
        self.var = {"active": True, "kind": kind, "since_id": ev.get("id"), "team": team, "text": VAR_KINDS[kind]}
        self.add_tl(ev, "var", team, f"VAR check - {VAR_KINDS[kind]}", self.when(ev), status="checking", kind=kind)

    def _ev_var_result(self, ev):
        d = ev.get("decision")
        if d not in VAR_DECISIONS:
            raise RuleError("bad_var", "Choose the VAR decision.")
        was = self.var.get("kind")
        self.var = {"active": False, "kind": was, "since_id": None, "team": self.var.get("team"), "text": ""}
        w = self.when(ev)
        self.var_history.append({"id": ev.get("id"), "decision": d})
        self.add_tl(ev, "var", self.var.get("team"), f"VAR - {VAR_DECISIONS[d]}" + (f" ({ev['reason']})" if ev.get("reason") else ""), w,
                    status="result", decision=d, kind=was)

    # ---- manual stats --------------------------------------------------------------------- #
    def _ev_stats_set(self, ev):
        """Manual stat entry. Shapes accepted:
           {"team": "A", "key": "shots", "value": 7}            one number
           {"values": {"A": {"shots": 7}, "B": {...}}}           many team numbers
           {"player": "A9", "values": {"shots": 3}}              player numbers
           A value of null / "" clears the manual number (back to the automatic one, if there is one)."""
        n = 0
        def put(store: Dict[str, Any], key: str, val: Any, catalog: Dict[str, Any], who: str):
            nonlocal n
            if key not in catalog:
                raise RuleError("unknown_stat", f"Unknown statistic '{key}'.")
            try:
                f = _num(val)
            except (ValueError, TypeError):
                raise RuleError("bad_stat", f"{catalog[key]['label']} for {who}: '{val}' is not a number.")
            if f is None:
                store.pop(key, None)
            else:
                if f < 0:
                    raise RuleError("bad_stat", f"{catalog[key]['label']} for {who} cannot be negative.")
                if catalog[key]["kind"] == "pct" and f > 100:
                    raise RuleError("bad_stat", f"{catalog[key]['label']} for {who} cannot be above 100%.")
                if catalog[key]["kind"] == "int":
                    f = int(round(f))
                store[key] = f
            n += 1
        if ev.get("player"):
            pid = ev["player"]
            if pid not in self.pid_team:
                raise RuleError("unknown_player", "Unknown player.")
            vals = ev.get("values") or ({ev["key"]: ev.get("value")} if ev.get("key") else {})
            for k, v in vals.items():
                put(self.pstat_over.setdefault(pid, {}), k, v, PLAYER_STAT_KEYS, self.P[self.pid_team[pid]][pid]["name"])
        elif ev.get("key"):
            t = ev.get("team")
            if t not in ("A", "B"):
                raise RuleError("bad_team", "Choose a team.")
            put(self.stat_over[t], ev["key"], ev.get("value"), TEAM_STAT_KEYS, self.m["teams"][t]["name"])
        else:
            vals = ev.get("values") or {}
            for t, kv in vals.items():
                if t not in ("A", "B") or not isinstance(kv, dict):
                    raise RuleError("bad_team", "Stats must be grouped under team 'A' and 'B'.")
                for k, v in kv.items():
                    put(self.stat_over[t], k, v, TEAM_STAT_KEYS, self.m["teams"][t]["name"])
        if n == 0:
            raise RuleError("empty", "No statistic was given.")
        self.overrides.append({"id": ev.get("id"), "type": "stats_set", "text": f"Stats updated ({n} value{'s' if n != 1 else ''})"})

    # ---- result ---------------------------------------------------------------------------- #
    def _ev_result(self, ev):
        """Manual result (walkover / forfeit / abandoned / decided by the committee)."""
        w = ev.get("winner")
        if w not in ("A", "B", "draw", "none"):
            raise RuleError("bad_result", "Winner must be A, B, draw or none.")
        self.result_ev = {"winner": w, "text": (ev.get("text") or "").strip(), "kind": ev.get("kind") or "manual",
                          "score": ev.get("score")}
        self.phase = "ended"
        self.clock = {"running": False, "base_ms": self.clock["base_ms"], "since": None}
        self.overrides.append({"id": ev.get("id"), "type": "result", "text": "Result entered manually"})

    def _ev_clear_result(self, ev):
        self.result_ev = None
        if self.phase == "ended" and not self.abandoned:
            # re-open: go back to the phase the log would be in without the manual result
            self.phase = "break2" if self.period == 4 or self.period == 2 else self.phase
        self.overrides.append({"id": ev.get("id"), "type": "clear_result", "text": "Manual result removed"})

    def _ev_abandon(self, ev):
        why = (ev.get("reason") or "").strip() or "Match abandoned"
        w = self.stamp(_i(ev.get("ts")))
        self.abandoned = {"reason": why, "label": w["label"]}
        self.clock = {"running": False, "base_ms": self.elapsed(_i(ev.get("ts"))), "since": None}
        self.phase = "ended"
        self.add_tl(ev, "period", None, f"Match abandoned - {why}", w, marker="abandon")

    def _ev_match_end(self, ev):
        """Referee ended the match without the normal flow (e.g. draw accepted, cup tie decided elsewhere)."""
        if self.phase in LIVE:
            e = self.elapsed(_i(ev.get("ts")))
            self.period_len[self.period] = e
            self.clock = {"running": False, "base_ms": e, "since": None}
        self._finish(ev, self.stamp(_i(ev.get("ts"))), 2)

    # ---- shoot-out -------------------------------------------------------------------------- #
    def so_status(self) -> Dict[str, Any]:
        k = self.so_kicks
        taken = {"A": 0, "B": 0}
        goals = {"A": 0, "B": 0}
        for x in k:
            taken[x["team"]] += 1
            goals[x["team"]] += 1 if x["result"] == "scored" else 0
        decided, winner = False, None
        a, b = goals["A"], goals["B"]
        ta, tb = taken["A"], taken["B"]
        if ta >= 5 and tb >= 5:
            if ta == tb and a != b:
                decided, winner = True, ("A" if a > b else "B")
        else:
            if a > b + (5 - tb):
                decided, winner = True, "A"
            elif b > a + (5 - ta):
                decided, winner = True, "B"
        nxt = None
        if self.so_first and not decided:
            other = "B" if self.so_first == "A" else "A"
            nxt = self.so_first if ta == tb else ("A" if ta < tb else "B")
            del other
        return {"taken": taken, "goals": goals, "decided": decided, "winner": winner, "next": nxt,
                "round": max(ta, tb) + 1 if not decided else max(ta, tb)}

    def _ev_shootout_start(self, ev):
        if self.phase not in ("pre_so", "break2", "break4"):
            if self.phase == "so":
                raise RuleError("so_running", "The shoot-out has already started.")
            raise RuleError("so_not_now", "A shoot-out is only held after the match (and extra time) ends level.",
                            "If the match is level at the end, press End half to reach the shoot-out stage.")
        if not self.fmt["shootout"] and "no_so" not in set(ev.get("force") or []):
            raise RuleError("no_so", "A penalty shoot-out is not part of this competition's format.", "Enable it in the setup, or force.", soft=True)
        if not self.level() and "so_not_needed" not in set(ev.get("force") or []):
            raise RuleError("so_not_needed", "The match is not level.", soft=True)
        first = ev.get("first")
        if first not in ("A", "B"):
            raise RuleError("so_first", "Choose which team kicks first (decided by the coin toss).")
        self.so_first = first
        self.phase = "so"
        self.period = 5
        self.clock = {"running": False, "base_ms": self.clock["base_ms"], "since": None}
        self.add_tl(ev, "period", None, f"Penalty shoot-out - {self.m['teams'][first]['name']} kick first",
                    {"label": "PEN", "min": 0, "extra": 0, "abs": 0, "period": 5}, marker="so_start")

    def _eligible(self, tid: str) -> List[str]:
        """Players on the pitch at the end of the match (incl. temporarily off). Counting for equal numbers is the referee's job."""
        return [p["id"] for p in self.P[tid].values() if p["status"] == "on"]

    def _ev_shootout_kick(self, ev):
        force = set(ev.get("force") or [])
        if self.phase != "so":
            raise RuleError("so_not_running", "The shoot-out has not started.", "Press 'Start shoot-out' first.")
        stt = self.so_status()
        if stt["decided"]:
            raise RuleError("so_decided", "The shoot-out is already decided.", "Undo the last kick if it was entered wrongly.")
        team = ev.get("team") or stt["next"]
        if team not in ("A", "B"):
            raise RuleError("bad_team", "Choose the team.")
        if team != stt["next"] and "so_order" not in force:
            raise RuleError("so_order", f"It is {self.m['teams'][stt['next']]['name']}'s turn - kicks alternate.", soft=True)
        res = ev.get("result")
        if res not in SHOOTOUT_RESULTS:
            raise RuleError("bad_result", "Kick result must be scored / saved / missed / hit the woodwork.")
        p = self.player(ev.get("player"), team)
        if p:
            if p["status"] != "on" and "not_on_pitch" not in force:
                raise RuleError("not_on_pitch", f"{p['name']} was not on the pitch at the end of the match, so cannot take a kick.",
                                "Law 10: only players on the field (or temporarily off) at the end of the match are eligible.", soft=True)
            mine = [k["player"] for k in self.so_kicks if k["team"] == team and k["player"]]
            elig = set(self._eligible(team)) | set(mine)
            cycle_done = [x for x in mine]
            # every eligible player must kick once before anyone kicks again
            n_elig = len(elig)
            this_cycle = mine[(len(mine) // n_elig) * n_elig:] if n_elig else []
            if p["id"] in this_cycle and "so_repeat" not in force:
                raise RuleError("so_repeat", f"{p['name']} has already kicked - every eligible player kicks once before anyone kicks again.",
                                soft=True)
        n = len([k for k in self.so_kicks if k["team"] == team]) + 1
        k = {"id": ev.get("id"), "team": team, "player": p["id"] if p else None,
             "player_name": p["name"] if p else (ev.get("player_name") or ""), "result": res, "n": n,
             "number": p["number"] if p else None}
        self.so_kicks.append(k)
        st2 = self.so_status()
        self.add_tl(ev, "so_kick", team, f"{k['player_name'] or 'Kicker'} - {SHOOTOUT_RESULTS[res].lower()}",
                    {"label": "PEN", "min": 0, "extra": 0, "abs": 0, "period": 5}, result=res, n=n,
                    score={"A": st2["goals"]["A"], "B": st2["goals"]["B"]})
        if st2["decided"]:
            self.so_winner = st2["winner"]
            self.phase = "ended"
            self.so_done = True


# --------------------------------------------------------------------------- #
# Derived view
# --------------------------------------------------------------------------- #
def _result(R: _Replay) -> Dict[str, Any]:
    tm = R.m["teams"]
    sc = R.score()
    if R.result_ev:
        r = R.result_ev
        w = r["winner"]
        txt = r["text"]
        if not txt:
            txt = {"A": f"{tm['A']['name']} won", "B": f"{tm['B']['name']} won", "draw": "Match drawn", "none": "No result"}[w]
        return {"final": True, "winner": None if w in ("draw", "none") else w, "kind": r["kind"], "text": txt, "manual": True,
                "decided_by": r["kind"]}
    if R.abandoned:
        return {"final": True, "winner": None, "kind": "abandoned",
                "text": f"Match abandoned ({R.abandoned['reason']}) at {R.abandoned['label']}", "decided_by": "abandoned"}
    if R.phase != "ended":
        return {"final": False, "winner": None, "kind": None, "text": "", "decided_by": None}
    tot = R.total()
    agg = R.fmt.get("aggregate")
    went_et = 3 in R.period_len or 4 in R.period_len
    suffix = " after extra time" if went_et else ""
    if R.so_done and R.so_winner:
        s = R.so_status()["goals"]
        w = R.so_winner
        lo = "B" if w == "A" else "A"
        return {"final": True, "winner": w, "kind": "penalties",
                "text": f"{tm[w]['name']} won {s[w]}-{s[lo]} on penalties ({tot['A']}-{tot['B']} after {'extra time' if went_et else '90 minutes'})".replace("(0-0", "(0-0")
                if not agg else f"{tm[w]['name']} won {s[w]}-{s[lo]} on penalties (aggregate {tot['A']}-{tot['B']})",
                "decided_by": "penalties"}
    if tot["A"] != tot["B"]:
        w = "A" if tot["A"] > tot["B"] else "B"
        lo = "B" if w == "A" else "A"
        if agg:
            return {"final": True, "winner": w, "kind": "aggregate",
                    "text": f"{tm[w]['name']} won {sc[w]}-{sc[lo]}{suffix} ({tot[w]}-{tot[lo]} on aggregate)", "decided_by": "aggregate"}
        return {"final": True, "winner": w, "kind": "win", "text": f"{tm[w]['name']} won {sc[w]}-{sc[lo]}{suffix}", "decided_by": "regulation"}
    return {"final": True, "winner": None, "kind": "draw", "text": f"Match drawn {sc['A']}-{sc['B']}{suffix}", "decided_by": "draw"}


def _clock_view(R: _Replay) -> Dict[str, Any]:
    p = R.period if R.period in (1, 2, 3, 4) else (max(R.period_len) if R.period_len else 0)
    c = R.clock
    return {"period": R.period, "last_period": p, "running": bool(c["running"]), "base_ms": int(c["base_ms"]), "since": c["since"],
            "offset_ms": R.p_off(p) if p else 0, "regular_ms": R.p_len(p) if p else R.half, "added_min": R.added.get(p, 0) if p else 0,
            "half_min": R.fmt["half_min"], "et_min": R.fmt["et_min"]}


def _player_stats(R: _Replay, end_abs: int) -> Dict[str, Dict[str, Any]]:
    out = {}
    for tid in "AB":
        for pid, p in R.P[tid].items():
            if p["on_abs"] is None and p["status"] != "on":
                mins = 0
            else:
                start = p["on_abs"] or 0
                stop = p["off_abs"] if p["off_abs"] is not None else end_abs
                mins = max(0, stop - start)
            auto = {"minutes": mins if (p["on_abs"] is not None or p["status"] == "on") else None,
                    "goals": p["goals"], "assists": p["assists"], "yellow_cards": p["yellows"], "red_cards": 1 if p["red"] else 0}
            vals = {}
            for s in PLAYER_STATS:
                k = s["key"]
                v = R.pstat_over.get(pid, {}).get(k)
                src = "manual" if v is not None else None
                if v is None and s.get("auto"):
                    v = auto.get(k)
                    src = "auto" if v is not None else None
                if v is None and k == "pass_accuracy":
                    ps, pc = R.pstat_over.get(pid, {}).get("passes"), R.pstat_over.get(pid, {}).get("passes_completed")
                    if ps and pc is not None:
                        v, src = round(100 * pc / ps), "derived"
                if v is not None:
                    vals[k] = {"v": v, "d": fmt_stat(s["kind"], v), "src": src}
            out[pid] = vals
    return out


def _team_stats(R: _Replay) -> Dict[str, Any]:
    sc = R.score()
    auto = {}
    for tid in "AB":
        ys = sum(1 for c in R.cards if c["team"] == tid and not c["cancelled"] and c["color"] == "yellow")
        rs = sum(1 for c in R.cards if c["team"] == tid and not c["cancelled"] and c["kind"] in ("red", "yellow2"))
        auto[tid] = {"goals": sc[tid], "yellow_cards": ys, "red_cards": rs, "penalties": R.penalties_awarded[tid],
                     "substitutions": sum(1 for s in R.subs if s["team"] == tid)}
    vals: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for s in TEAM_STATS:
        k = s["key"]
        row = {"key": k, "label": s["label"], "kind": s["kind"], "group": s["group"], "main": bool(s.get("main")), "A": None, "B": None,
               "srcA": None, "srcB": None}
        for tid in "AB":
            v = R.stat_over[tid].get(k)
            if v is not None:
                row[tid], row["src" + tid] = v, "manual"
            elif s.get("auto"):
                row[tid], row["src" + tid] = auto[tid][k], "auto"
        vals[k] = row
    # derived fallbacks
    pa, pb = vals["possession"]["A"], vals["possession"]["B"]
    if pa is not None and pb is None:
        vals["possession"]["B"], vals["possession"]["srcB"] = round(100 - pa, 1), "derived"
    if pb is not None and pa is None:
        vals["possession"]["A"], vals["possession"]["srcA"] = round(100 - pb, 1), "derived"
    for tid in "AB":
        if vals["pass_accuracy"][tid] is None:
            ps, pc = vals["passes"][tid], vals["passes_completed"][tid]
            if ps and pc is not None:
                vals["pass_accuracy"][tid], vals["pass_accuracy"]["src" + tid] = round(100 * pc / ps), "derived"
    # sanity warnings (never block - these are manual numbers, the producer is in charge)
    nm = {t: R.m["teams"][t]["name"] for t in "AB"}
    for tid in "AB":
        if (vals["shots_on_target"][tid] or 0) > (vals["shots"][tid] or 0) and vals["shots"][tid] is not None:
            warnings.append(f"{nm[tid]}: shots on target ({vals['shots_on_target'][tid]}) is more than shots ({vals['shots'][tid]})")
        if (vals["passes_completed"][tid] or 0) > (vals["passes"][tid] or 0) and vals["passes"][tid] is not None:
            warnings.append(f"{nm[tid]}: passes completed ({vals['passes_completed'][tid]}) is more than passes ({vals['passes'][tid]})")
        g = vals["goals"][tid]
        if g is not None and vals["shots_on_target"][tid] is not None and vals["shots_on_target"][tid] < g - sum(1 for x in R.goals if x["team"] == tid and x["kind"] == "own_goal" and not x["cancelled"]):
            warnings.append(f"{nm[tid]}: fewer shots on target ({vals['shots_on_target'][tid]}) than goals scored ({g})")
    if R.stat_over["A"].get("possession") is not None and R.stat_over["B"].get("possession") is not None:
        t = R.stat_over["A"]["possession"] + R.stat_over["B"]["possession"]
        if abs(t - 100) > 1:
            warnings.append(f"Possession adds up to {t:g}% (should be 100%)")
    for k, row in vals.items():
        row["dA"], row["dB"] = fmt_stat(row["kind"], row["A"]), fmt_stat(row["kind"], row["B"])
    return {"rows": vals, "warnings": warnings, "order": [s["key"] for s in TEAM_STATS], "default_rows": DEFAULT_STAT_ROWS}


def _player_view(R: _Replay, tid: str, pstats) -> List[Dict[str, Any]]:
    out = []
    for p in R.m["teams"][tid]["players"]:
        r = R.P[tid][p["id"]]
        out.append({"id": r["id"], "name": r["name"], "short": r["short"], "number": r["number"], "pos": r["pos"],
                    "captain": r["captain"], "status": r["status"], "started": r["started"], "slot": r["slot"], "x": r["x"], "y": r["y"],
                    "yellows": r["yellows"], "red": r["red"], "dismissal": r["dismissal"], "goals": r["goals"],
                    "own_goals": r["own_goals"], "assists": r["assists"], "on_abs": r["on_abs"], "off_abs": r["off_abs"],
                    "replaced_by": r["replaced_by"], "replacing": r["replacing"], "squad": r["squad"], "stats": pstats.get(r["id"], {})})
    return out


def derive(match: Dict[str, Any]) -> Dict[str, Any]:
    """Replay the event log and return the complete scoreboard. Never raises."""
    normalize_setup(match)
    R = _Replay(match)
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
            R.errors.append({"event_id": ev.get("id"), "seq": seq, "type": ev.get("type"), "code": "internal",
                             "message": f"{type(e).__name__}: {e}"})
    return _assemble(R)


def _assemble(R: _Replay) -> Dict[str, Any]:
    m = R.m
    sc = R.score()
    tot = R.total()
    agg = R.fmt.get("aggregate")
    result = _result(R)
    status = {"pre": "not_started", "ended": "completed"}.get(R.phase, "live" if R.phase in LIVE or R.phase == "so" else "break")
    # end minute for minutes-played
    end_abs = 0
    if R.period in (1, 2, 3, 4) or R.period_len:
        p = R.period if R.period in (1, 2, 3, 4) else max(R.period_len)
        if R.phase in LIVE:
            end_abs = 0   # live: minutes are computed by the clients from the clock; keep last event minute
        end_abs = (R.p_off(p) + R.period_len.get(p, R.clock["base_ms"])) // 60000 if p else 0
        if R.phase in LIVE:
            end_abs = (R.p_off(p) + R.clock["base_ms"]) // 60000 + 1
    pst = _player_stats(R, end_abs)
    teams = {}
    for tid in "AB":
        t = m["teams"][tid]
        pv = _player_view(R, tid, pst)
        on = [p for p in pv if p["status"] == "on"]
        n_on = len(on)
        reds_staff = [c for c in R.staff_cards if c["team"] == tid and c["color"] == "red" and not c["cancelled"]]
        ss = R.sub_state[tid]
        mx = R.fmt["subs_max"] + (1 if (R.fmt["et_extra_sub"] and R.fmt["extra_time"] and R.period in (3, 4)) else 0)
        teams[tid] = {"id": tid, "name": t["name"], "short": t["short"], "color": t["color"], "color2": t["color2"], "logo": t["logo"],
                      "formation": R.formation[tid], "coach": t["coach"], "players": pv, "on_field": n_on,
                      "red_cards": sum(1 for c in R.cards if c["team"] == tid and not c["cancelled"] and c["kind"] in ("red", "yellow2")),
                      "yellow_cards": sum(1 for c in R.cards if c["team"] == tid and not c["cancelled"] and c["color"] == "yellow"),
                      "staff_sent_off": len(reds_staff),
                      "subs": {"used": ss["used"], "max": mx, "windows": ss["windows"], "windows_max": R.fmt["windows_max"],
                               "concussion_used": ss["concussion"],
                               "additional_available": ss["additional_owed"] - ss["additional_used"]},
                      "below_minimum": n_on < R.fmt["min_players"] and R.phase in LIVE}
    goals = {"A": [], "B": []}
    for g in R.goals:
        goals[g["team"]].append(g)
    # scorer lines, grouped by player
    scorers = {"A": [], "B": []}
    for tid in "AB":
        order: List[str] = []
        grp: Dict[str, Dict[str, Any]] = {}
        for g in goals[tid]:
            if g["cancelled"]:
                continue
            key = g["player"] or ("n:" + (g["player_name"] or "?"))
            if key not in grp:
                grp[key] = {"player": g["player"], "name": g["player_name"] or "Unknown", "times": [], "number":
                            (R.P[R.pid_team[g["player"]]][g["player"]]["number"] if g["player"] else None)}
                order.append(key)
            tag = "(OG)" if g["kind"] == "own_goal" else ("(pen)" if g["kind"] == "penalty" else "")
            grp[key]["times"].append((g["label"] + (" " + tag if tag else "")).strip())
        scorers[tid] = [grp[k] for k in order]
    so = R.so_status()
    shootout = {"active": R.phase == "so", "started": R.so_first is not None, "first": R.so_first, "kicks": R.so_kicks,
                "goals": so["goals"], "taken": so["taken"], "decided": so["decided"], "winner": so["winner"],
                "next": so["next"], "round": so["round"], "pending": R.phase in ("pre_so", "break2") and R.fmt["shootout"],
                "eligible": {t: R._eligible(t) for t in "AB"}}
    last_goal = next((r for r in reversed(R.timeline) if r["type"] == "goal" and not r["cancelled"]), None)
    cur_clock = _clock_view(R)
    can_et = R.phase == "break2" and R.fmt["extra_time"]
    can_so = R.phase in ("pre_so", "break2") and R.fmt["shootout"]
    state = {
        "sport": SPORT, "engine": ENGINE_VERSION, "id": m.get("id"), "title": m.get("title"), "venue": m.get("venue"),
        "date": m.get("date"), "competition": R.info.get("competition"), "stage": R.info.get("stage"),
        "kickoff": R.info.get("kickoff"), "attendance": R.info.get("attendance"), "weather": R.info.get("weather"), "motm": R.info.get("motm"),
        "officials": m["officials"], "form": m["form"], "h2h": m["h2h"],
        "format": R.fmt, "teams": teams,
        "status": status, "phase": R.phase, "phase_label": PHASE_LABEL[R.phase], "phase_short": PHASE_SHORT[R.phase],
        "clock": cur_clock,
        "score": {"A": sc["A"], "B": sc["B"], "text": f"{sc['A']}-{sc['B']}"},
        "aggregate": {"on": bool(agg), "A": tot["A"], "B": tot["B"], "first_leg": agg},
        "level": R.level(), "goals": goals, "scorers": scorers, "last_goal": last_goal,
        "timeline": R.timeline, "cards": R.cards, "staff_cards": R.staff_cards, "subs_log": R.subs,
        "shootout": shootout, "var": R.var, "added": R.added,
        "can_et": can_et, "can_shootout": can_so, "result": result,
        "stats": _team_stats(R),
        "overrides": R.overrides, "integrity": {"errors": R.errors},
        "event_status": R.event_status,
        "extra_time_played": 3 in R.period_len or R.phase in ("et1", "break3", "et2"),
        "last_event": ({"id": R.last_event.get("id"), "type": R.last_event.get("type")} if R.last_event else None),
        "event_count": len(m["events"]),
    }
    return state


# --------------------------------------------------------------------------- #
# Append-time helpers
# --------------------------------------------------------------------------- #
def _replay_all(match: Dict[str, Any], events: List[Dict[str, Any]]) -> _Replay:
    probe = normalize_setup(copy.deepcopy(match))
    probe["events"] = list(events)
    R = _Replay(probe)
    for ev in events:
        try:
            R.apply(ev)
        except Exception:
            pass
    return R


def prepare_event(match: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp the match minute (period/min/extra/label) from the clock at the moment the event is appended,
    so later edits / inserts never change when something happened."""
    if event.get("type") in STAMPED and event.get("min") in (None, "") and event.get("period") in (None, ""):
        R = _replay_all(match, match["events"])
        s = R.stamp(_i(event.get("ts")))
        event.update({"period": s["period"], "min": s["min"], "extra": s["extra"], "abs": s["abs"], "label": s["label"]})
    return event


def validate_append(match: Dict[str, Any], event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    probe = normalize_setup(copy.deepcopy(match))
    probe["events"] = list(match["events"]) + [event]
    R = _Replay(probe)
    for ev in probe["events"][:-1]:
        try:
            R.apply(ev)
        except Exception:
            pass
    try:
        R.apply(event)
    except RuleError as e:
        return e.to_dict()
    except Exception as e:  # pragma: no cover
        return {"code": "internal", "message": f"{type(e).__name__}: {e}", "hint": None, "soft": False}
    return None


def summary(match: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": match["id"], "sport": SPORT, "title": match.get("title"),
            "teams": {k: v["name"] for k, v in match["teams"].items()}, "status": st["status"], "score": st["score"]["text"],
            "phase": st["phase_label"], "result": st["result"].get("text"), "updated": match.get("updated"),
            "format": st["format"]["label"], "date": match.get("date"), "venue": match.get("venue")}


# --------------------------------------------------------------------------- #
# Clock text (used for the OBS text files; the overlay does the same maths in JS)
# --------------------------------------------------------------------------- #
def clock_texts(state: Dict[str, Any], now_ms: int) -> Dict[str, str]:
    c = state["clock"]
    ph = state["phase"]
    p = c["last_period"] if c["last_period"] else 0
    if ph == "pre" or p == 0:
        return {"clock": "00:00", "clock_min": "", "clock_split": "", "added": ""}
    e = c["base_ms"] + (max(0, now_ms - c["since"]) if c["running"] and c["since"] is not None else 0)
    tot = c["offset_ms"] + e
    reg = c["regular_ms"]
    mmss = f"{tot // 60000:02d}:{(tot // 1000) % 60:02d}"
    if e >= reg:
        base = (c["offset_ms"] + reg) // 60000
        ex = (e - reg) // 60000 + 1
        split, mn = f"{base}+{ex}", f"{base}+{ex}'"
    else:
        m = (c["offset_ms"] + e) // 60000 + 1
        split, mn = str(m), f"{m}'"
    added = f"+{c['added_min']}" if c["added_min"] else ""
    return {"clock": mmss, "clock_min": mn, "clock_split": split, "added": added}
