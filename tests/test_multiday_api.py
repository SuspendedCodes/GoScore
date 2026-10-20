"""Multi-day cricket through the HTTP API: setup, breaks, feeds, hold, restart persistence."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Api, players, A, B  # noqa: E402


class MultiDayApi(Api):
    def md(self, days=2):
        r = self.call("POST", "/api/matches", {"title": "Two-day match", "format": {"preset": "multi_day", "days": days, "overs_per_day": "90", "new_ball_after": 80},
                                                "teams": {"A": {"name": "India", "short": "IND", "players": players("A", A)},
                                                          "B": {"name": "Australia", "short": "AUS", "players": players("B", B)}},
                                                "toss": {"winner": "A", "decision": "bat"}}, 201)
        return r["id"]

    def test_format_is_normalised(self):
        mid = self.md()
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        f = st["format"]
        self.assertEqual((f["innings_per_side"], f["days"], f["overs_per_day"], f["new_ball_after"], f["overs"]), (2, 2, 90, 80, None))
        self.assertEqual(st["play"]["label"], "DAY 1 · SESSION 1")

    def test_break_flow_feeds_and_outputs(self):
        mid = self.md()
        self.call("POST", f"/api/matches/{mid}/go-live", {})
        self.ev(mid, type="innings_start", innings=0, striker="A1", non_striker="A2", bowler="B8")
        for _ in range(5):
            self.ev(mid, type="ball", innings=0, bat_runs=1)
        self.ev(mid, type="delay", kind="lunch")
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual((st["status"], st["delay"]), ("delayed", "Lunch"))
        self.ev(mid, type="resume")
        self.ev(mid, type="delay", kind="stumps", text="Stumps - Day 1")
        self.ev(mid, type="resume")
        time.sleep(0.4)
        txt = self.call("GET", "/feed/live/text")
        self.assertEqual(txt["day_session"], "DAY 2 · SESSION 1")
        self.assertEqual(txt["overs_today"], "0.0")
        self.assertEqual(txt["overs_left"], "90.0")
        pub = self.call("GET", f"/api/matches/{mid}/published")
        self.assertEqual(pub["state"]["play"]["day"], 2)
        self.assertIn("testsum", pub["graphics"]["panels"])
        raw = self.call("GET", "/feed/live/text/day_session.txt", raw=True).decode()
        self.assertEqual(raw, "DAY 2 · SESSION 1")

    def test_follow_on_is_soft_over_http(self):
        mid = self.md(days=2)
        self.call("POST", f"/api/matches/{mid}/go-live", {})
        self.ev(mid, type="innings_start", innings=0, striker="A1", non_striker="A2", bowler="B8")
        self.ev(mid, type="ball", innings=0, bat_runs=4)
        self.ev(mid, type="innings_end", innings=0, reason="declared")
        self.ev(mid, type="innings_start", innings=1, striker="B1", non_striker="B2", bowler="A8")
        self.ev(mid, type="innings_end", innings=1, reason="declared")
        # lead is 4 (< 100): enforcing the follow-on is refused softly, and allowed when forced
        r = self.call("POST", f"/api/matches/{mid}/events", {"type": "innings_start", "innings": 2, "batting": "B", "striker": "B1", "non_striker": "B2", "bowler": "A8", "cid": "fo1"}, 422)
        self.assertEqual(r["error"]["code"], "follow_on")
        self.assertTrue(r["error"]["soft"])
        self.call("POST", f"/api/matches/{mid}/events", {"type": "innings_start", "innings": 2, "batting": "B", "striker": "B1", "non_striker": "B2", "bowler": "A8", "cid": "fo2", "force": ["follow_on"]})
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertTrue(st["play"]["follow_on"])

    def test_restart_keeps_day_and_session(self):
        mid = self.md()
        self.ev(mid, type="delay", kind="tea")
        self.ev(mid, type="resume")
        self.ev(mid, type="day_set", day=2, session=2, reason="test")
        self.app.store.reload() if hasattr(self.app.store, "reload") else None
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual((st["play"]["day"], st["play"]["session"]), (2, 2))

    def test_undo_a_break(self):
        mid = self.md()
        self.ev(mid, type="delay", kind="lunch")
        self.ev(mid, type="resume")
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["play"]["session"], 2)
        self.call("POST", f"/api/matches/{mid}/undo", {})
        self.call("POST", f"/api/matches/{mid}/undo", {})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["play"]["session"], 1)


if __name__ == "__main__":
    unittest.main()
