"""Broadcast data: XML feed + flat files for OBS 'Text (read from file)' sources.

Everything here is derived from the *published* state (what the audience may see).
Files are only rewritten when their content changed, atomically.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from typing import Any, Dict, List
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from .store import atomic_write
from . import football as FB
import time as _time

ITEM_TAGS = {"innings": "inning", "batters": "batter", "bowlers": "bowler", "fow": "wicket",
             "partnerships": "partnership", "balls": "ball", "overs_detail": "over", "players": "player",
             "errors": "error", "info": "note", "overrides": "override", "pair": "batter",
             "fielders": "fielder", "powerplays": "powerplay", "events": "event"}


def _tag(key: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))
    if not t or not re.match(r"[A-Za-z_]", t[0]):
        t = "f_" + t
    return t


def _to_xml(parent: Element, key: str, val: Any) -> None:
    if isinstance(val, dict):
        node = SubElement(parent, _tag(key))
        for k, v in val.items():
            _to_xml(node, k, v)
    elif isinstance(val, (list, tuple)):
        node = SubElement(parent, _tag(key))
        item = ITEM_TAGS.get(key, "item")
        for v in val:
            _to_xml(node, item, v)
    else:
        node = SubElement(parent, _tag(key))
        if isinstance(val, bool):
            node.text = "true" if val else "false"
        elif val is not None:
            node.text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(val))


def state_to_xml(state: Dict[str, Any], root: str = "match") -> str:
    r = Element(root)
    for k, v in state.items():
        _to_xml(r, k, v)
    return minidom.parseString(tostring(r, encoding="utf-8")).toprettyxml(indent="  ")


# --------------------------------------------------------------------------- #
def _ball_labels(this_over: Dict[str, Any]) -> str:
    return " ".join(b["label"] for b in (this_over or {}).get("balls", []))


def _bat_str(p, star=False):
    if not p:
        return ""
    return f"{p['short']}{'*' if star else ''} {p['runs']} ({p['balls']})"


def text_fields(state: Dict[str, Any], graphics: Dict[str, Any] | None = None, delay_s: float = 0) -> Dict[str, str]:
    if state.get("sport") == "football":
        return fb_text_fields(state, graphics, delay_s)
    c = state.get("current")
    res = state.get("result") or {}
    f: Dict[str, str] = {
        "match_title": state.get("title") or "",
        "match_status": state.get("status") or "",
        "result": res.get("text") or "",
        "team_a": state["teams"]["A"]["name"], "team_b": state["teams"]["B"]["name"],
        "team_a_short": state["teams"]["A"]["short"], "team_b_short": state["teams"]["B"]["short"],
        "venue": state.get("venue") or "",
        "delay": state.get("delay") or "",
    }
    toss = state.get("toss") or {}
    if toss.get("winner") in ("A", "B"):
        f["toss"] = f"{state['teams'][toss['winner']]['name']} won the toss and chose to {toss.get('decision', 'bat')}"
    else:
        f["toss"] = ""
    pl = state.get("play") or {}
    f["day"] = str(pl.get("day", "")) if pl else ""
    f["session"] = str(pl.get("session", "")) if pl else ""
    f["day_session"] = pl.get("label", "") if pl else ""
    f["overs_today"] = (pl.get("today") or {}).get("overs", "") if pl else ""
    f["runs_today"] = (str((pl.get("today") or {}).get("runs", "")) if pl else "")
    f["wickets_today"] = (str((pl.get("today") or {}).get("wickets", "")) if pl else "")
    f["overs_left"] = (pl.get("overs_left") or "") if pl else ""
    f["ball_age"] = pl.get("ball_age", "") if pl else ""
    f["new_ball_due"] = ("DUE" if pl.get("new_ball_available") else (pl.get("new_ball_due") or "")) if pl else ""
    f["team_a_score"] = (pl.get("scores") or {}).get("A", "") if pl else ""
    f["team_b_score"] = (pl.get("scores") or {}).get("B", "") if pl else ""
    f["lead_trail"] = ((state.get("current") or {}).get("lead_text") or "") if pl else ""
    fi = state.get("first_innings")
    f["first_innings"] = f"{fi['short']} {fi['score']} ({fi['overs']})" if fi else ""
    if graphics:
        f["banner"] = (graphics.get("banner") or {}).get("text", "") if (graphics.get("panels") or {}).get("banner") else ""
    if not c:
        for k in ("score", "runs", "wickets", "overs", "scoreline", "team_batting", "team_batting_short",
                  "team_bowling", "striker", "non_striker", "bowler", "crr", "rrr", "target", "need",
                  "status_line", "this_over", "last_ball", "partnership", "last_wicket", "free_hit",
                  "powerplay", "innings_no"):
            f[k] = ""
        return f
    f.update({
        "score": c["score"], "runs": str(c["runs"]), "wickets": str(c["wickets"]), "overs": c["overs"],
        "scoreline": f"{c['batting']['short']} {c['score']} ({c['overs']})",
        "team_batting": c["batting"]["name"], "team_batting_short": c["batting"]["short"],
        "team_bowling": c["bowling"]["name"],
        "striker": _bat_str(c["striker"], True), "non_striker": _bat_str(c["non_striker"]),
        "bowler": (f"{c['bowler']['short']} {c['bowler']['overs']}-{c['bowler']['maidens']}-{c['bowler']['runs']}-{c['bowler']['wickets']}"
                   if c["bowler"] else ""),
        "crr": f"{c['crr']:.2f}", "rrr": (f"{c['rrr']:.2f}" if c["rrr"] is not None else ""),
        "target": str(c["target"]) if c["target"] is not None else "",
        "need": (f"Need {c['need']} from {c['balls_left']}" if c["target"] is not None and c["balls_left"] is not None else ""),
        "status_line": c["status_line"], "this_over": _ball_labels(c["this_over"]),
        "last_ball": (f"{c['last_ball']['over_str']} {c['last_ball']['label']}" if c["last_ball"] else ""),
        "partnership": (f"Partnership {c['partnership']['runs']} ({c['partnership']['balls']})" if c["partnership"] else ""),
        "last_wicket": ((lambda w: f"{w['out_name']} {w['how']} {w['runs']} ({w['balls']}) - {w['score']}")(c["last_wicket"])
                        if c["last_wicket"] else ""),
        "free_hit": "FREE HIT" if c["free_hit"] else "", "powerplay": c["powerplay"] or "",
        "innings_no": str(c["innings_no"]),
    })
    return f


def csv_files(state: Dict[str, Any]) -> Dict[str, str]:
    if state.get("sport") == "football":
        return fb_csv_files(state)
    out: Dict[str, str] = {}
    cur = state["innings"][-1] if state.get("innings") else None
    if not cur:
        return out

    def mk(rows, header):
        s = io.StringIO()
        w = csv.writer(s, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
        return s.getvalue()
    out["batting.csv"] = mk([[b["name"], b["status_text"], b["runs"], b["balls"], b["fours"], b["sixes"], b["sr"]]
                             for b in cur["batters"]], ["name", "status", "runs", "balls", "fours", "sixes", "sr"])
    out["bowling.csv"] = mk([[b["name"], b["overs"], b["maidens"], b["runs"], b["wickets"], b["econ"], b["wides"], b["noballs"]]
                             for b in cur["bowlers"]], ["name", "overs", "maidens", "runs", "wickets", "econ", "wides", "noballs"])
    out["fall_of_wickets.csv"] = mk([[w["wicket"], w["score"], w["name"], w["over"], w["how"]] for w in cur["fow"]],
                                    ["wicket", "score", "batter", "over", "how"])
    out["ball_by_ball.csv"] = mk([[b["over_str"], b["bowler_name"], b["striker_name"], b["label"], b["runs"], b["score"]]
                                  for b in cur.get("balls", [])], ["over", "bowler", "batter", "ball", "runs", "score"])
    return out


def _join(parts, sep=" "):
    return sep.join(str(x) for x in parts if x not in (None, ""))


def fb_text_fields(state: Dict[str, Any], graphics: Dict[str, Any] | None = None, delay_s: float = 0) -> Dict[str, str]:
    A, B = state["teams"]["A"], state["teams"]["B"]
    sc = state["score"]
    ck = FB.clock_texts(state, int(_time.time() * 1000 - delay_s * 1000))
    f: Dict[str, str] = {
        "match_title": state.get("title") or "", "match_status": state.get("status") or "", "phase": state.get("phase_label") or "",
        "phase_short": state.get("phase_short") or "", "result": (state.get("result") or {}).get("text") or "",
        "team_a": A["name"], "team_b": B["name"], "team_a_short": A["short"], "team_b_short": B["short"],
        "score_a": str(sc["A"]), "score_b": str(sc["B"]), "score": sc["text"],
        "scoreline": f"{A['short']} {sc['A']}-{sc['B']} {B['short']}",
        "venue": state.get("venue") or "", "competition": state.get("competition") or "", "stage": state.get("stage") or "",
        "kickoff": state.get("kickoff") or "", "attendance": str(state.get("attendance") or ""), "weather": state.get("weather") or "",
        "referee": (state.get("officials") or {}).get("referee") or "", "motm": state.get("motm") or "",
        "formation_a": A["formation"], "formation_b": B["formation"], "coach_a": A["coach"], "coach_b": B["coach"],
        "red_cards_a": str(A["red_cards"]), "red_cards_b": str(B["red_cards"]),
        "yellow_cards_a": str(A["yellow_cards"]), "yellow_cards_b": str(B["yellow_cards"]),
    }
    f.update(ck)
    f["scoreline_clock"] = _join([f["scoreline"], ck["clock_min"]], "  ")
    agg = state.get("aggregate") or {}
    f["aggregate"] = f"Agg {agg['A']}-{agg['B']}" if agg.get("on") else ""
    for tid in "AB":
        f[f"scorers_{tid.lower()}"] = "\n".join(f"{x['name']} {', '.join(x['times'])}" for x in state["scorers"][tid])
    tl = [r for r in state["timeline"] if not r.get("cancelled")]
    def last(t):
        r = next((x for x in reversed(tl) if x["type"] == t), None)
        return r
    g = last("goal")
    f["last_goal"] = f"{g['label']} {state['teams'][g['team']]['short']} {g['text']}" if g else ""
    c = last("card")
    f["last_card"] = (f"{c['label']} {c.get('card_text', '')} {c['text']}" if c else "")
    s_ = last("sub")
    f["last_sub"] = f"{s_['label']} {state['teams'][s_['team']]['short']}: {s_['on_name']} on, {s_['off_name']} off" if s_ else ""
    f["var"] = ("VAR CHECK - " + state["var"]["text"]) if state["var"]["active"] else ""
    so = state["shootout"]
    f["shootout_score"] = f"{so['goals']['A']}-{so['goals']['B']}" if so["started"] else ""
    for tid in "AB":
        f[f"shootout_{tid.lower()}"] = " ".join({"scored": "O", "saved": "X", "missed": "X", "post": "X"}[k["result"]] for k in so["kicks"] if k["team"] == tid)
    f["added_time"] = ck["added"]
    f["banner"] = (graphics.get("banner") or {}).get("text", "") if graphics and (graphics.get("panels") or {}).get("banner") else ""
    for k, row in state["stats"]["rows"].items():
        if row["A"] is None and row["B"] is None:
            continue
        f[f"stat_{k}_a"], f[f"stat_{k}_b"] = row["dA"], row["dB"]
        f[f"stat_{k}"] = f"{row['dA']} - {row['dB']}"
    for tid in "AB":
        lines = []
        for p in state["teams"][tid]["players"]:
            if p["started"]:
                lines.append(f"{p['number'] if p['number'] is not None else ''} {p['name']}".strip())
        f[f"lineup_{tid.lower()}"] = "\n".join(lines)
    return f


def fb_csv_files(state: Dict[str, Any]) -> Dict[str, str]:
    def mk(rows, header):
        s = io.StringIO()
        w = csv.writer(s, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
        return s.getvalue()
    out: Dict[str, str] = {}
    out["events.csv"] = mk([[r["label"], state["teams"][r["team"]]["short"] if r.get("team") else "", r["type"], r.get("card_text") or r.get("kind") or "",
                             r["text"], "cancelled" if r.get("cancelled") else ""] for r in state["timeline"]],
                           ["minute", "team", "type", "detail", "text", "note"])
    out["stats.csv"] = mk([[r["label"], r["dA"], r["dB"], r["srcA"] or "", r["srcB"] or ""] for r in state["stats"]["rows"].values()
                           if r["A"] is not None or r["B"] is not None], ["stat", state["teams"]["A"]["short"], state["teams"]["B"]["short"], "A_source", "B_source"])
    for tid in "AB":
        out[f"players_{tid.lower()}.csv"] = mk([[p["number"], p["name"], p["pos"], p["status"], "Y" if p["started"] else "", p["goals"], p["assists"],
                                                p["yellows"], 1 if p["red"] else 0, (p["stats"].get("minutes") or {}).get("v", "")]
                                               for p in state["teams"][tid]["players"]],
                                              ["number", "name", "pos", "status", "starter", "goals", "assists", "yellows", "red", "minutes"])
    out["shootout.csv"] = mk([[k["n"], state["teams"][k["team"]]["short"], k["player_name"], k["result"]] for k in state["shootout"]["kicks"]],
                             ["kick_no", "team", "player", "result"])
    return out


class OutputWriter:
    def __init__(self, base_dir: str):
        self.base = os.path.abspath(base_dir)
        self._last: Dict[str, str] = {}

    def _w(self, path: str, text: str):
        if self._last.get(path) == text:
            return
        atomic_write(path, text)
        self._last[path] = text

    def write(self, match_id: str, state: Dict[str, Any], graphics: Dict[str, Any], is_live: bool, delay_s: float = 0):
        targets = [os.path.join(self.base, match_id)]
        if is_live:
            targets.append(os.path.join(self.base, "live"))
        full_json = json.dumps({"state": state, "graphics": graphics}, ensure_ascii=False, indent=1)
        xml = state_to_xml(state)
        tf = text_fields(state, graphics, delay_s)
        csvs = csv_files(state)
        for d in targets:
            self._w(os.path.join(d, "scoreboard.json"), full_json)
            self._w(os.path.join(d, "scoreboard.xml"), xml)
            for k, v in tf.items():
                self._w(os.path.join(d, "text", k + ".txt"), v)
            for k, v in csvs.items():
                self._w(os.path.join(d, "csv", k), v)
