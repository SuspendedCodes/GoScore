"""
POC Core — GoScore scoring engines + derived state + broadcast serialization.

Proves the hardest/most failure-prone part of GoScore in isolation:
  1. Football event log -> derived scoreboard (goals, cards, subs, penalty shootout)
  2. Cricket ball-by-ball event log -> derived innings state (runs, wickets, overs,
     extras, run-rate, striker rotation, over completion)
  3. Broadcast serialization: same derived state -> JSON and XML (consistent shapes)

Pure functions only (no DB, no framework) so it can be unit-tested directly and
reused by the real app in Phase 2.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


# --------------------------------------------------------------------------- #
# FOOTBALL
# --------------------------------------------------------------------------- #
# Event types: goal, own_goal, yellow_card, red_card, substitution,
#              period_start, period_end, penalty (shootout attempt)
# Each event: {type, team ("home"/"away"), player, minute, meta{...}}

FOOTBALL_PERIODS = [
    "first_half", "second_half",
    "et_first_half", "et_second_half",
    "penalties",
]


def derive_football_state(match: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    home = {"score": 0, "yellow_cards": 0, "red_cards": 0, "subs_used": 0,
            "goals": [], "shootout_scored": 0, "shootout_taken": 0}
    away = {"score": 0, "yellow_cards": 0, "red_cards": 0, "subs_used": 0,
            "goals": [], "shootout_scored": 0, "shootout_taken": 0}

    def side(team: str):
        return home if team == "home" else away

    def opp(team: str):
        return away if team == "home" else home

    current_period = None
    status = "scheduled"
    timeline = []

    for ev in events:
        t = ev.get("type")
        team = ev.get("team")
        player = ev.get("player")
        minute = ev.get("minute")

        if t == "period_start":
            current_period = ev.get("meta", {}).get("period")
            status = "live"
        elif t == "period_end":
            current_period = None
        elif t == "goal":
            s = side(team)
            s["score"] += 1
            s["goals"].append({"player": player, "minute": minute})
            timeline.append({"minute": minute, "team": team, "type": "goal", "player": player})
        elif t == "own_goal":
            # counts for the opponent
            o = opp(team)
            o["score"] += 1
            o["goals"].append({"player": player, "minute": minute, "own_goal": True})
            timeline.append({"minute": minute, "team": team, "type": "own_goal", "player": player})
        elif t == "yellow_card":
            side(team)["yellow_cards"] += 1
            timeline.append({"minute": minute, "team": team, "type": "yellow_card", "player": player})
        elif t == "red_card":
            side(team)["red_cards"] += 1
            timeline.append({"minute": minute, "team": team, "type": "red_card", "player": player})
        elif t == "substitution":
            side(team)["subs_used"] += 1
            timeline.append({"minute": minute, "team": team, "type": "substitution", "player": player,
                             "meta": ev.get("meta", {})})
        elif t == "penalty":
            s = side(team)
            s["shootout_taken"] += 1
            if ev.get("meta", {}).get("scored"):
                s["shootout_scored"] += 1
            timeline.append({"minute": minute, "team": team, "type": "penalty",
                             "scored": ev.get("meta", {}).get("scored", False)})

    return {
        "sport": "football",
        "status": status,
        "current_period": current_period,
        "home": {"name": match.get("home_name", "Home"), **home},
        "away": {"name": match.get("away_name", "Away"), **away},
        "score_line": f"{home['score']} - {away['score']}",
        "shootout_line": f"{home['shootout_scored']} - {away['shootout_scored']}"
        if (home["shootout_taken"] or away["shootout_taken"]) else None,
        "timeline": timeline,
    }


# --------------------------------------------------------------------------- #
# CRICKET (limited overs) — full engine (event replay is the source of truth)
# --------------------------------------------------------------------------- #
# Event types (all carry "innings"):
#   innings_start {innings, batting_team, striker, non_striker, bowler}
#   set_batters   {innings, striker, non_striker}
#   set_bowler    {innings, bowler}
#   ball          {innings, delivery(legal|wide|noball), bat_runs, boundary,
#                  extra_type(bye|legbye|None), extra_runs, overthrow_runs,
#                  overthrow_to_bat, ran, wicket:{kind,out_player,fielder,new_batter}}
#   adjustment    {innings, runs_delta, wickets_delta, reason}
#   overs_revision{innings, new_overs_limit, new_target, reason}
#   delay         {reason, note}
BOWLER_CREDIT = {"bowled", "caught", "caught_bowled", "lbw", "stumped", "hit_wicket"}
DISMISSAL_LABELS = {
    "bowled": "b", "caught": "c", "caught_bowled": "c&b", "lbw": "lbw",
    "run_out": "run out", "stumped": "st", "hit_wicket": "hit wicket",
    "obstructing": "obstructing the field", "hit_twice": "hit the ball twice",
    "timed_out": "timed out", "retired_out": "retired out", "retired_hurt": "retired hurt",
}


def _new_batter():
    return {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "out": False, "how": None}


def _new_bowler():
    return {"balls": 0, "runs": 0, "wickets": 0, "maidens": 0, "wides": 0, "noballs": 0}


def _new_inn(index, batting_team, overs_limit):
    return {
        "index": index, "batting_team": batting_team,
        "runs": 0, "wickets": 0, "legal_balls": 0,
        "extras": {"wide": 0, "noball": 0, "bye": 0, "legbye": 0, "penalty": 0, "total": 0},
        "batters": {}, "order": [], "bowlers": {}, "bowl_order": [],
        "striker": None, "non_striker": None, "bowler": None,
        "overs_limit": overs_limit, "target": None,
        "fall_of_wickets": [], "timeline": [], "over_runs": 0,
    }


def derive_cricket_state(match, events):
    bpo = int(match.get("balls_per_over", 6) or 6)
    default_overs = int(match.get("overs_limit", 20) or 20)
    team_a = match.get("team_a", "Team A")
    team_b = match.get("team_b", "Team B")

    innings = {}
    order_of_innings = []

    def get_inn(i):
        if i not in innings:
            default_team = team_a if i % 2 == 0 else team_b
            innings[i] = _new_inn(i, default_team, default_overs)
            order_of_innings.append(i)
        return innings[i]

    def bat(inn, name):
        if not name:
            return None
        if name not in inn["batters"]:
            inn["batters"][name] = _new_batter()
            inn["order"].append(name)
        return inn["batters"][name]

    def bowl(inn, name):
        if not name:
            return None
        if name not in inn["bowlers"]:
            inn["bowlers"][name] = _new_bowler()
            inn["bowl_order"].append(name)
        return inn["bowlers"][name]

    current_innings = 0
    any_ball = False

    for ev in events:
        t = ev.get("type")
        i = ev.get("innings", 0) or 0

        if t == "innings_start":
            inn = get_inn(i)
            current_innings = i
            if ev.get("batting_team"):
                inn["batting_team"] = ev["batting_team"]
            inn["striker"] = ev.get("striker")
            inn["non_striker"] = ev.get("non_striker")
            inn["bowler"] = ev.get("bowler")
            bat(inn, inn["striker"]); bat(inn, inn["non_striker"]); bowl(inn, inn["bowler"])
        elif t == "set_batters":
            inn = get_inn(i)
            if ev.get("striker") is not None:
                inn["striker"] = ev["striker"]; bat(inn, ev["striker"])
            if ev.get("non_striker") is not None:
                inn["non_striker"] = ev["non_striker"]; bat(inn, ev["non_striker"])
        elif t == "set_bowler":
            inn = get_inn(i)
            inn["bowler"] = ev.get("bowler"); bowl(inn, inn["bowler"])
            inn["over_runs"] = 0
        elif t == "overs_revision":
            inn = get_inn(i)
            if ev.get("new_overs_limit") is not None:
                inn["overs_limit"] = int(ev["new_overs_limit"])
            if ev.get("new_target") is not None:
                inn["target"] = int(ev["new_target"])
        elif t == "adjustment":
            inn = get_inn(i)
            inn["runs"] += int(ev.get("runs_delta", 0) or 0)
            inn["wickets"] += int(ev.get("wickets_delta", 0) or 0)
        elif t == "ball":
            any_ball = True
            inn = get_inn(i)
            current_innings = i
            delivery = ev.get("delivery", "legal")
            bat_runs = int(ev.get("bat_runs", 0) or 0)
            boundary = bool(ev.get("boundary", False))
            etype = ev.get("extra_type")
            eruns = int(ev.get("extra_runs", 0) or 0)
            ot = int(ev.get("overthrow_runs", 0) or 0)
            ot_bat = bool(ev.get("overthrow_to_bat", False))
            ran = int(ev.get("ran", 0) or 0)
            wicket = ev.get("wicket")
            striker = inn["striker"]
            bowler = inn["bowler"]
            team_add = 0

            if delivery == "wide":
                inn["extras"]["wide"] += 1 + eruns
                inn["extras"]["total"] += 1 + eruns
                team_add += 1 + eruns
                if bowler:
                    bowl(inn, bowler)["wides"] += 1
            elif delivery == "noball":
                inn["extras"]["noball"] += 1
                inn["extras"]["total"] += 1
                team_add += 1
                if bowler:
                    bowl(inn, bowler)["noballs"] += 1

            # runs off the bat (legal or no-ball)
            if delivery in ("legal", "noball") and bat_runs:
                team_add += bat_runs
                b = bat(inn, striker)
                if b:
                    b["runs"] += bat_runs
                    if boundary and bat_runs == 4:
                        b["fours"] += 1
                    elif boundary and bat_runs == 6:
                        b["sixes"] += 1

            # byes / leg-byes (legal or no-ball)
            if etype in ("bye", "legbye") and eruns:
                inn["extras"][etype] += eruns
                inn["extras"]["total"] += eruns
                team_add += eruns

            # overthrows
            if ot:
                team_add += ot
                if ot_bat and striker:
                    bat(inn, striker)["runs"] += ot
                else:
                    inn["extras"]["penalty"] += ot
                    inn["extras"]["total"] += ot

            inn["runs"] += team_add
            inn["over_runs"] += team_add

            # balls faced (not on wides)
            if striker and delivery != "wide":
                bat(inn, striker)["balls"] += 1

            is_legal = delivery == "legal"
            if is_legal:
                inn["legal_balls"] += 1

            # bowler figures
            if bowler:
                bw = bowl(inn, bowler)
                if is_legal:
                    bw["balls"] += 1
                conceded = bat_runs
                if delivery == "wide":
                    conceded += 1 + eruns
                elif delivery == "noball":
                    conceded += 1
                if ot and ot_bat:
                    conceded += ot
                bw["runs"] += conceded

            # strike rotation on odd running
            if ran % 2 == 1:
                inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]

            # wicket
            if wicket:
                kind = wicket.get("kind")
                out_player = wicket.get("out_player") or inn["striker"]
                new_batter = wicket.get("new_batter")
                if kind != "retired_hurt":
                    inn["wickets"] += 1
                    inn["fall_of_wickets"].append({
                        "score": inn["runs"], "wicket": inn["wickets"],
                        "batter": out_player, "kind": kind,
                    })
                if kind in BOWLER_CREDIT and bowler:
                    bowl(inn, bowler)["wickets"] += 1
                bo = bat(inn, out_player)
                if bo:
                    bo["out"] = True
                    label = DISMISSAL_LABELS.get(kind, kind)
                    fld = wicket.get("fielder")
                    bo["how"] = f"{label}{' ' + fld if fld and kind in ('caught','run_out','stumped') else ''} b {bowler}" if bowler else label
                # place incoming batter at the out player's end
                if inn["striker"] == out_player:
                    inn["striker"] = new_batter
                elif inn["non_striker"] == out_player:
                    inn["non_striker"] = new_batter
                if new_batter:
                    bat(inn, new_batter)

            # over completion -> swap strike, reset over runs
            if is_legal and inn["legal_balls"] > 0 and inn["legal_balls"] % bpo == 0:
                inn["striker"], inn["non_striker"] = inn["non_striker"], inn["striker"]

            inn["timeline"].append(_ball_commentary(inn, bpo, ev, team_add))

    # ---- assemble output ----
    def over_str(inn):
        return f"{inn['legal_balls'] // bpo}.{inn['legal_balls'] % bpo}"

    def run_rate(inn):
        if inn["legal_balls"] == 0:
            return 0.0
        return round(inn["runs"] / (inn["legal_balls"] / bpo), 2)

    max_idx = max(order_of_innings) if order_of_innings else 0
    inn_list = []
    for idx in range(0, max(max_idx + 1, 2)):
        inn = get_inn(idx)
        inn_list.append({
            "index": idx, "batting_team": inn["batting_team"],
            "runs": inn["runs"], "wickets": inn["wickets"],
            "overs": over_str(inn), "legal_balls": inn["legal_balls"],
            "overs_limit": inn["overs_limit"], "run_rate": run_rate(inn),
            "extras": inn["extras"], "batters": inn["batters"], "order": inn["order"],
            "bowlers": inn["bowlers"], "bowl_order": inn["bowl_order"],
            "fall_of_wickets": inn["fall_of_wickets"], "timeline": inn["timeline"],
            "striker": inn["striker"], "non_striker": inn["non_striker"], "bowler": inn["bowler"],
            "target": inn["target"],
        })

    cur = inn_list[current_innings]
    status = "live" if any_ball else "scheduled"

    # target for chasing innings
    target = cur["target"]
    if target is None and current_innings >= 1:
        prev = inn_list[current_innings - 1]
        target = prev["runs"] + 1
    result_line = None
    if current_innings >= 1 and target is not None:
        need = target - cur["runs"]
        balls_left = cur["overs_limit"] * bpo - cur["legal_balls"]
        if need <= 0:
            result_line = f"{cur['batting_team']} won"
        elif balls_left <= 0 or cur["wickets"] >= 10:
            result_line = "Innings complete"
        else:
            result_line = f"{cur['batting_team']} need {need} run{'s' if need != 1 else ''} from {balls_left} ball{'s' if balls_left != 1 else ''}"

    # this over (balls of current over)
    cur_inn_state = get_inn(current_innings)
    balls_this_over = [x for x in cur_inn_state["timeline"] if x.get("over_no") == (cur["legal_balls"] // bpo)][-bpo - 4:]

    return {
        "sport": "cricket",
        "status": status,
        "balls_per_over": bpo,
        "current_innings": current_innings,
        "target": target,
        "result_line": result_line,
        "innings": inn_list,
        "this_over": balls_this_over,
        "live": {
            "batting_team": cur["batting_team"],
            "score_line": f"{cur['runs']}/{cur['wickets']}",
            "overs": cur["overs"], "overs_limit": cur["overs_limit"],
            "run_rate": cur["run_rate"],
            "striker": cur["striker"], "non_striker": cur["non_striker"], "bowler": cur["bowler"],
            "target": target,
        },
    }


def _ball_commentary(inn, bpo, ev, team_add):
    delivery = ev.get("delivery", "legal")
    bat_runs = int(ev.get("bat_runs", 0) or 0)
    etype = ev.get("extra_type")
    eruns = int(ev.get("extra_runs", 0) or 0)
    ot = int(ev.get("overthrow_runs", 0) or 0)
    wicket = ev.get("wicket")
    over_no = (inn["legal_balls"] - 1) // bpo if delivery == "legal" else inn["legal_balls"] // bpo
    ball_no = ((inn["legal_balls"] - 1) % bpo) + 1 if delivery == "legal" else (inn["legal_balls"] % bpo)

    label = str(bat_runs)
    if delivery == "wide":
        label = "wd" + (f"+{eruns}" if eruns else "")
    elif delivery == "noball":
        label = "nb" + (f"+{bat_runs}" if bat_runs else "") + (f"+{eruns}{(etype or '')[:1]}" if eruns else "")
    elif etype in ("bye", "legbye"):
        label = f"{eruns}{'b' if etype == 'bye' else 'lb'}"
    if ot:
        label += f"+{ot}ot"
    if wicket:
        label = "W"
    return {
        "over_no": over_no, "ball_no": ball_no,
        "over_str": f"{over_no}.{ball_no}",
        "label": label, "runs": team_add,
        "bowler": inn["bowler"],
        "wicket": bool(wicket),
        "wicket_kind": (wicket or {}).get("kind"),
        "out_player": (wicket or {}).get("out_player"),
        "delivery": delivery,
    }


def build_cricket_commentary(match, events):
    """Human-readable ball-by-ball commentary (list of lines)."""
    state = derive_cricket_state({
        "team_a": match.get("home_name"), "team_b": match.get("away_name"),
        "overs_limit": match.get("config", {}).get("overs_limit", 20),
        "balls_per_over": match.get("config", {}).get("balls_per_over", 6),
    }, events)
    lines = []
    lines.append(f"{match.get('home_name')} vs {match.get('away_name')}  |  {match.get('round','')}  |  Match #{match.get('serial','')}")
    lines.append("=" * 64)
    for inn in state["innings"]:
        if inn["legal_balls"] == 0 and inn["runs"] == 0 and not inn["order"]:
            continue
        lines.append("")
        lines.append(f"INNINGS {inn['index'] + 1}: {inn['batting_team']}  —  {inn['runs']}/{inn['wickets']} ({inn['overs']} ov, RR {inn['run_rate']})")
        ex = inn["extras"]
        lines.append(f"Extras: {ex['total']} (b {ex['bye']}, lb {ex['legbye']}, w {ex['wide']}, nb {ex['noball']}, p {ex['penalty']})")
        lines.append("-" * 64)
    lines.append("")
    lines.append("BALL-BY-BALL")
    lines.append("-" * 64)
    for inn in state["innings"]:
        for b in inn["timeline"]:
            w = f"  WICKET ({b['wicket_kind']}: {b['out_player']})" if b["wicket"] else ""
            lines.append(f"Inn{inn['index'] + 1} {b['over_str']:>5}  {b['label']:<8} b:{b['bowler'] or '-'}{w}")
    return lines

# --------------------------------------------------------------------------- #
# Broadcast serialization (JSON is the dict itself; XML below)
# --------------------------------------------------------------------------- #
def _dict_to_xml(tag: str, d: Any, parent: Element) -> None:
    if isinstance(d, dict):
        node = SubElement(parent, tag)
        for k, v in d.items():
            _dict_to_xml(str(k), v, node)
    elif isinstance(d, list):
        node = SubElement(parent, tag)
        for item in d:
            _dict_to_xml("item", item, node)
    else:
        node = SubElement(parent, tag)
        node.text = "" if d is None else str(d)


def state_to_xml(state: Dict[str, Any], root_tag: str = "match") -> str:
    root = Element(root_tag)
    for k, v in state.items():
        _dict_to_xml(str(k), v, root)
    rough = tostring(root, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ")
