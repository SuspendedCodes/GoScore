"""Sport dispatch: every match has a ``sport`` ("cricket" default, or "football").
The store/server only talk to this module, never to an engine directly."""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from . import engine as C
from . import football as F

SPORTS = ("cricket", "football")


def sport_of(m: Dict[str, Any]) -> str:
    s = m.get("sport")
    return s if s in SPORTS else "cricket"


def engine(m: Dict[str, Any]):
    return F if sport_of(m) == "football" else C


def normalize_setup(m: Dict[str, Any]) -> Dict[str, Any]:
    m["sport"] = sport_of(m)
    return engine(m).normalize_setup(m)


def derive(m: Dict[str, Any]) -> Dict[str, Any]:
    st = engine(m).derive(m)
    st["sport"] = sport_of(m)
    return st


def prepare_event(m: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    e = engine(m)
    return e.prepare_event(m, ev) if hasattr(e, "prepare_event") else ev


def validate_append(m: Dict[str, Any], ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return engine(m).validate_append(m, ev)


def summary(m: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    if sport_of(m) == "football":
        return F.summary(m, st)
    cur = st.get("current") or {}
    return {"id": m["id"], "sport": "cricket", "title": m.get("title"), "teams": {k: v["name"] for k, v in m["teams"].items()},
            "status": st["status"], "score": cur.get("score"), "overs": cur.get("overs"), "result": st["result"].get("text"),
            "updated": m.get("updated"), "format": st["format"]["label"], "date": m.get("date"), "venue": m.get("venue")}
