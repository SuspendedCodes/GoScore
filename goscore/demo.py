"""Sample matches for the overlay layout editor.

The editor must show every graphic exactly as it looks during a real match, so the samples are NOT
hand-written placeholder text: each one is an ordinary match (setup + event log) that is replayed by the
real engine, and the overlay renders the resulting state with its normal renderers.

Cricket kinds:  limited (T20 chase in progress), test (day 2 of a Test), final (the chase completed)
Football kinds: live (68th minute, second half), shootout (penalty shoot-out in progress)
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

MIN = 60_000

# --------------------------------------------------------------------------- cricket
_A = [("Rohan Verma", "batter", True, True), ("Daniel Hughes", "batter", False, False), ("Kabir Sethi", "batter", False, False),
      ("Mitchell Foster", "allrounder", False, False), ("Aiden Cole", "batter", False, False), ("Samir Qureshi", "allrounder", False, False),
      ("Liam Bennett", "bowler", False, False), ("Tariq Hassan", "bowler", False, False), ("Noah Fletcher", "bowler", False, False),
      ("Dev Malhotra", "bowler", False, False), ("Callum Reid", "bowler", False, False), ("Owen Ashby", "batter", False, False),
      ("Yusuf Rahman", "bowler", False, False)]
_B = [("Jack Whitmore", "batter", False, False), ("Imran Siddiqui", "batter", False, False), ("Ethan Marsh", "batter", False, False),
      ("Vikram Rao", "batter", True, True), ("Harry Lowe", "allrounder", False, False), ("Zaid Khan", "allrounder", False, False),
      ("Oliver Grant", "bowler", False, False), ("Nikhil Joshi", "bowler", False, False), ("Reece Dalton", "bowler", False, False),
      ("Farhan Ali", "bowler", False, False), ("Tom Garrick", "bowler", False, False), ("Sean Ritchie", "batter", False, False),
      ("Amit Desai", "bowler", False, False)]


def _roster(prefix: str, rows) -> List[Dict[str, Any]]:
    out = []
    for i, (name, role, wk, cap) in enumerate(rows, 1):
        out.append({"id": f"{prefix}{i}", "name": name, "role": role, "wk": wk, "captain": cap, "xi": i <= 11})
    return out


class _Log:
    def __init__(self, m: Dict[str, Any], t0: int, step: int = 4000):
        self.m, self.n, self.t, self.step = m, 0, t0, step

    def add(self, type_: str, **kw):
        self.n += 1
        self.t += self.step
        ev = {"id": f"d{self.n}", "type": type_, "ts": self.t, **kw}
        self.m["events"].append(ev)
        return ev


# ball patterns: (bat_runs, boundary) tuples or dicts of extra keywords
_FAST = [dict(bat_runs=1), dict(bat_runs=0), dict(bat_runs=4, boundary=True), dict(bat_runs=1), dict(bat_runs=2), dict(bat_runs=0),
         dict(bat_runs=6, boundary=True), dict(bat_runs=1), dict(bat_runs=0), dict(bat_runs=1), dict(legbyes=1), dict(bat_runs=2),
         dict(bat_runs=4, boundary=True), dict(bat_runs=0), dict(bat_runs=1), dict(byes=1), dict(bat_runs=1), dict(bat_runs=0)]
_SLOW = [dict(bat_runs=0), dict(bat_runs=1), dict(bat_runs=0), dict(bat_runs=0), dict(bat_runs=2), dict(bat_runs=0), dict(bat_runs=1),
         dict(bat_runs=4, boundary=True), dict(bat_runs=0), dict(bat_runs=1), dict(bat_runs=0), dict(bat_runs=0), dict(bat_runs=1),
         dict(legbyes=1), dict(bat_runs=0), dict(bat_runs=2)]
_DISMISS = ["caught", "bowled", "lbw", "run_out", "caught", "stumped", "bowled", "caught", "lbw"]


class _Inn:
    """Plays deliveries into one innings, handling bowler changes at each over and incoming batters."""

    def __init__(self, L: _Log, idx: int, batting: str, first_bowler: int = 7):
        self.L, self.idx, self.bat = L, idx, batting
        self.bowl = "B" if batting == "A" else "A"
        self.bw = [f"{self.bowl}{first_bowler + i}" for i in range(5)]
        self.bw = [b for b in self.bw if int(b[1:]) <= 11]
        self.nxt, self.legal, self.over, self.wk, self.k, self.seq = 3, 0, 0, 0, 0, 0
        L.add("innings_start", innings=idx, batting=batting, striker=f"{batting}1", non_striker=f"{batting}2", bowler=self.bw[0])

    def ball(self, spec: Dict[str, Any]):
        self.L.add("ball", innings=self.idx, **spec)
        if spec.get("delivery") in ("wide", "noball"):
            return
        self.legal += 1
        if self.legal % 6 == 0:
            self.over += 1
            self.pending_bowler = True

    pending_bowler = False

    def _bowler(self):
        if self.pending_bowler:
            self.pending_bowler = False
            self.L.add("set_bowler", innings=self.idx, bowler=self.bw[self.over % len(self.bw)])

    def play(self, count: int, wicket_at: List[int], pattern):
        """Play until `count` legal balls have been bowled in total."""
        extras_at = {17: dict(delivery="wide"), 41: dict(delivery="noball", bat_runs=1), 73: dict(delivery="wide", wide_runs=1)}
        while self.legal < count:
            self._bowler()
            self.seq += 1
            if self.seq in extras_at and self.legal % 6 != 5:
                self.ball(extras_at[self.seq])
                continue
            if (self.legal + 1) in wicket_at:
                kind = _DISMISS[self.wk % len(_DISMISS)]
                w = {"kind": kind, "new_batter": f"{self.bat}{self.nxt}"}
                if kind in ("caught", "run_out", "stumped"):
                    w["fielder"] = f"{self.bowl}4" if kind == "stumped" else f"{self.bowl}{5 + self.wk % 4}"
                self.nxt += 1
                self.wk += 1
                self.ball({"wicket": w})
            else:
                self.ball(pattern[self.k % len(pattern)])
                self.k += 1

    def specs(self, specs: List[Dict[str, Any]]):
        for sp in specs:
            self._bowler()
            self.ball(sp)


def _cricket_setup(title: str, preset: str, **fmt) -> Dict[str, Any]:
    f = {"preset": preset}
    f.update(fmt)
    return {"id": "demo", "sport": "cricket", "title": title, "venue": "Riverside Oval", "date": "2026-10-28", "format": f,
            "teams": {"A": {"name": "Harbour Hawks", "short": "HAW", "color": "#0b7285", "players": _roster("A", _A)},
                      "B": {"name": "Ridgeway Rovers", "short": "RDG", "color": "#c2255c", "players": _roster("B", _B)}},
            "toss": {"winner": "A", "decision": "bat"}, "events": []}


def cricket_match(kind: str, now: int) -> Dict[str, Any]:
    if kind == "test":
        m = _cricket_setup("First Test, Day 2", "multi_day", overs=None, days=5)
        L = _Log(m, now - 40 * 3600_000)
        i0 = _Inn(L, 0, "A")
        i0.play(468, [60, 130, 190, 240, 300, 360, 410], _SLOW)
        L.add("innings_end", innings=0, reason="declared")
        L.add("delay", kind="stumps")
        L.add("resume")
        i1 = _Inn(L, 1, "B")
        i1.play(190, [40, 120], _SLOW)
        L.add("delay", kind="lunch")
        L.add("resume")
        i1.specs((_SLOW * 2)[:14])
        return m
    m = _cricket_setup("Harbour Hawks v Ridgeway Rovers", "t20")
    L = _Log(m, now - 3 * 3600_000)
    i0 = _Inn(L, 0, "A")
    i0.play(120, [14, 33, 52, 71, 95, 111], _FAST)
    i1 = _Inn(L, 1, "B")
    if kind == "final":
        i1.play(104, [22, 48, 70, 91], _FAST + _FAST[:6] + [dict(bat_runs=4, boundary=True)] * 3)
        return m
    i1.play(86, [11, 29, 44, 58, 77], _FAST)
    i1.specs([dict(bat_runs=1), dict(bat_runs=4, boundary=True), dict(delivery="wide"), dict(bat_runs=0)])
    return m


# --------------------------------------------------------------------------- football
_HOME = ["Marco Bellini", "Luca Ferrante", "Diego Navarro", "Pablo Ibarra", "Stefan Kovac", "Mateo Rinaldi", "Jonas Lindqvist",
         "Andre Moreau", "Rafael Duarte", "Tomas Brandt", "Felix Aaltonen", "Giorgio Conte", "Hugo Lefevre", "Nico Santoro",
         "Elias Berg", "Victor Salgado", "Ivan Petrov", "Oskar Dahl"]
_AWAY = ["Kenji Mori", "Samuel Okafor", "Ryan Callahan", "Mehdi Haddad", "Bruno Teixeira", "Anton Volkov", "Patrick Doyle",
         "Yannick Meier", "Leo Castellanos", "Dario Vukovic", "Emil Hartmann", "Tobias Krause", "Marcus Hale", "Idris Bello",
         "Pierre Dumont", "Jamal Reed", "Sven Ostrom", "Kai Nakamura"]
_POS = ["GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "FW", "FW", "FW"]


def _squad(names: List[str]) -> List[Dict[str, Any]]:
    out = []
    for i, n in enumerate(names, 1):
        out.append({"name": n, "number": i if i != 12 else 14, "pos": _POS[i - 1] if i <= 11 else ("GK" if i == 12 else "MF" if i < 16 else "FW"),
                    "captain": i == 8})
    return out


def football_match(kind: str, now: int) -> Dict[str, Any]:
    shoot = kind == "shootout"
    m = {"id": "demo", "sport": "football", "title": "Northgate United v Eastport Athletic", "venue": "Northgate Park", "date": "2026-10-28",
         "format": {"shootout": True, "extra_time": False},
         "teams": {"A": {"name": "Northgate United", "short": "NGU", "color": "#1d4ed8", "color2": "#ffffff", "formation": "4-3-3",
                         "coach": "Paolo Ricci", "players": _squad(_HOME)},
                   "B": {"name": "Eastport Athletic", "short": "EPA", "color": "#c92a2a", "color2": "#ffffff", "formation": "4-2-3-1",
                         "coach": "Graham Elliot", "players": _squad(_AWAY)}},
         "officials": {"referee": "Daniel Moretti", "ar1": "Peter Hallam", "ar2": "Sven Larsen", "fourth": "Claude Rousseau",
                       "var": "Hans Berger", "avar": "Ola Nystrom"},
         "info": {"competition": "League Cup", "stage": "Semi-final", "kickoff": "19:45", "weather": "Clear, 14°C", "attendance": "21,480"},
         "form": {"A": "W W D W L", "B": "L W W D W"}, "h2h": {"A": 4, "D": 2, "B": 3}, "events": []}
    n = [0]

    def add(ts, type_, **kw):
        n[0] += 1
        m["events"].append({"id": f"f{n[0]}", "type": type_, "ts": int(ts), **kw})

    if shoot:
        k1 = now - 150 * MIN
        add(k1, "period_start")
        add(k1 + 17 * MIN, "goal", team="A", player="A9", assist="A8")
        add(k1 + 33 * MIN, "goal", team="B", player="B10")
        add(k1 + 46 * MIN, "period_end")
        k2 = k1 + 61 * MIN
        add(k2, "period_start")
        add(k2 + 46 * MIN, "period_end")
        add(k2 + 55 * MIN, "shootout_start", first="A")
        seq = [("A", "A9", "scored"), ("B", "B10", "scored"), ("A", "A8", "scored"), ("B", "B9", "saved"), ("A", "A10", "missed"), ("B", "B8", "scored")]
        for i, (t, p, r) in enumerate(seq):
            add(k2 + (56 + i) * MIN, "shootout_kick", team=t, player=p, result=r)
        return m
    k1 = now - int(84.4 * MIN)
    add(k1, "period_start")
    add(k1 + 12 * MIN + 10_000, "goal", team="A", player="A9", assist="A8")
    add(k1 + 27 * MIN, "card", team="B", player="B5", color="yellow")
    add(k1 + 38 * MIN + 40_000, "goal", team="B", player="B10")
    add(k1 + 46 * MIN, "period_end")
    k2 = k1 + 61 * MIN
    add(k2, "period_start")
    add(k2 + 7 * MIN, "sub", team="A", off="A7", on="A13")
    add(k2 + 14 * MIN, "goal", team="A", player="A9", kind="penalty")
    add(k2 + 18 * MIN, "card", team="A", player="A5", color="yellow")
    add(k2 + 20 * MIN, "sub", team="B", off="B9", on="B13")
    add(k2 + 21 * MIN, "stats_set", values={
        "A": {"possession": 54, "shots": 12, "shots_on_target": 6, "corners": 5, "fouls": 9, "offsides": 2, "passes_completed": 312, "pass_accuracy": 86},
        "B": {"possession": 46, "shots": 8, "shots_on_target": 3, "corners": 3, "fouls": 11, "offsides": 1, "passes_completed": 262, "pass_accuracy": 82}})
    add(k2 + 21 * MIN + 500, "stats_set", player="A9", values={"shots": 4, "passes_completed": 21, "tackles": 1})
    return m


def build(sport: str, kind: str, now: int) -> Dict[str, Any]:
    return copy.deepcopy(football_match(kind, now) if sport == "football" else cricket_match(kind, now))


KINDS = {"cricket": ("limited", "test", "final"), "football": ("live", "shootout")}
