"""Football through the HTTP API: events, feeds, outputs on disk, graphics exclusivity, hold, meta, mixed sports."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Api  # noqa: E402  (re-uses the server harness)


def sq(p):
    return [{"name": f"{p}{i} Surname{i}", "number": i, "pos": "GK" if i == 1 else "MF"} for i in range(1, 15)]


class FootballApi(Api):
    def fb(self, fmt=None):
        r = self.call("POST", "/api/matches", {"sport": "football", "title": "Reds v Blues", "venue": "Home Park", "format": fmt or {"preset": "cup"},
                                               "teams": {"A": {"name": "Reds", "short": "RED", "color": "#c1121f", "players": sq("A")},
                                                         "B": {"name": "Blues", "short": "BLU", "color": "#1d4ed8", "players": sq("B")}},
                                               "officials": {"referee": "Jo Ref"}}, 201)
        return r["id"]

    def ev(self, mid, **e):
        return self.call("POST", f"/api/matches/{mid}/events", e, 200)

    def test_meta_and_sports(self):
        f = self.fb()
        c = self.new_match()
        self.assertEqual(self.call("GET", f"/api/matches/{f}/meta")["sport"], "football")
        self.assertEqual(self.call("GET", f"/api/matches/{c}/meta")["sport"], "cricket")
        lst = {m["id"]: m for m in self.call("GET", "/api/matches")["matches"]}
        self.assertEqual(lst[f]["sport"], "football")
        self.assertEqual(lst[c]["sport"], "cricket")
        info = self.call("GET", "/api/presets")
        self.assertIn("team_stats", info["football"])
        self.assertIn("t20", info["presets"])

    def test_play_and_outputs(self):
        mid = self.fb()
        self.call("POST", f"/api/matches/{mid}/go-live", {})
        self.ev(mid, type="period_start")
        self.ev(mid, type="goal", team="A", player="A9", assist="A8")
        self.ev(mid, type="goal", team="B", player="A9", kind="own_goal")          # A9 own goal -> credited to Blues
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual(st["score"]["text"], "1-1")
        self.assertEqual(st["phase"], "p1")
        self.assertNotIn("event_status", st)
        err = self.call("POST", f"/api/matches/{mid}/events", {"type": "sub", "team": "A", "off": "A9", "on": "A9"}, 422)
        self.assertEqual(err["error"]["code"], "same_player")
        self.ev(mid, type="stats_set", values={"A": {"possession": 61, "shots": 12}, "B": {"shots": 5}})
        time.sleep(0.4)
        pub = self.call("GET", "/feed/live.json")
        self.assertEqual(pub["state"]["score"]["text"], "1-1")
        self.assertIn("stat_key", pub["graphics"])
        txt = self.call("GET", "/feed/live/text")
        self.assertEqual(txt["score"], "1-1")
        self.assertEqual(txt["stat_possession_a"], "61%")
        self.assertEqual(txt["stat_possession_b"], "39%")
        self.assertRegex(txt["clock"], r"^\d\d:\d\d$")
        self.assertIn("RED 1-1 BLU", txt["scoreline"])
        self.assertEqual(txt["referee"], "Jo Ref")
        raw = self.call("GET", "/feed/live/text/clock.txt", raw=True).decode()
        self.assertRegex(raw, r"^\d\d:\d\d$")
        csvs = self.call("GET", "/feed/live/csv/events.csv", raw=True).decode()
        self.assertIn("goal", csvs)
        xml = self.call("GET", "/feed/live.xml", raw=True).decode()
        self.assertIn("<score>", xml)
        base = os.path.join(self.tmp, "out", "live")
        for f in ("scoreboard.json", "scoreboard.xml", "text/score.txt", "text/clock.txt", "csv/stats.csv", "csv/players_a.csv"):
            self.assertTrue(os.path.exists(os.path.join(base, f)), f)
        self.assertEqual(open(os.path.join(base, "text", "score.txt")).read(), "1-1")

    def test_clock_text_file_ticks(self):
        mid = self.fb()
        self.call("POST", f"/api/matches/{mid}/go-live", {})
        self.ev(mid, type="period_start")
        p = os.path.join(self.tmp, "out", "live", "text", "clock.txt")
        time.sleep(0.5)
        a = open(p).read()
        time.sleep(2.3)
        b = open(p).read()
        self.assertNotEqual(a, b)

    def test_graphics_exclusive_groups_and_defaults(self):
        mid = self.fb()
        g = self.call("GET", f"/api/matches/{mid}/graphics")
        self.assertIn("lineups", g["panels"])
        self.assertNotIn("innsum", g["panels"])
        g = self.call("POST", f"/api/matches/{mid}/graphics", {"panels": {"lineups": True}})
        self.assertTrue(g["panels"]["lineups"])
        g = self.call("POST", f"/api/matches/{mid}/graphics", {"panels": {"stats_bars": True}})
        self.assertTrue(g["panels"]["stats_bars"])
        self.assertFalse(g["panels"]["lineups"])
        g = self.call("POST", f"/api/matches/{mid}/graphics", {"panels": {"stat_single": True}, "stat_key": "shots"})
        self.assertTrue(g["panels"]["stats_bars"] and g["panels"]["stat_single"])      # lower third coexists with a big panel
        g = self.call("POST", f"/api/matches/{mid}/graphics", {"panels": {"banner": True}})
        self.assertFalse(g["panels"]["stat_single"])
        g = self.call("POST", f"/api/matches/{mid}/graphics", {"panels": {"nonsense": True}, "bogus": 1})
        self.assertNotIn("nonsense", g["panels"])
        self.assertNotIn("bogus", g)
        c = self.new_match()
        gc = self.call("GET", f"/api/matches/{c}/graphics")
        self.assertIn("innsum", gc["panels"])
        self.assertNotIn("lineups", gc["panels"])

    def test_hold_freezes_football_publish(self):
        mid = self.fb()
        self.ev(mid, type="period_start")
        self.call("POST", f"/api/matches/{mid}/graphics", {"hold": True})
        self.ev(mid, type="goal", team="A", player="A9")
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["score"]["text"], "0-0")
        self.call("POST", f"/api/matches/{mid}/graphics", {"hold": False})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["score"]["text"], "1-0")

    def test_pitch_set_through_api_and_feed(self):
        mid = self.fb()
        self.ev(mid, type="period_start")
        self.ev(mid, type="pitch_set", team="A", positions={"A2": {"x": 33, "y": 44}}, formation="3-5-2")
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual(st["teams"]["A"]["formation"], "3-5-2")
        self.assertEqual(st["teams"]["A"]["players"][1]["x"], 33.0)
        self.call("POST", f"/api/matches/{mid}/events", {"type": "pitch_set", "team": "A", "positions": {"A2": {"x": 999, "y": 1}}}, 422)

    def test_payload_has_delay_and_server_time(self):
        mid = self.fb()
        p = self.call("GET", f"/api/matches/{mid}/published")
        self.assertIn("delay", p)
        self.assertIn("server_time", p["state"])

    def test_idempotent_and_version_conflict(self):
        mid = self.fb()
        self.ev(mid, type="period_start")
        self.call("POST", f"/api/matches/{mid}/events", {"type": "goal", "team": "A", "player": "A9", "cid": "abc"})
        r2 = self.call("POST", f"/api/matches/{mid}/events", {"type": "goal", "team": "A", "player": "A9", "cid": "abc"})
        self.assertTrue(r2.get("duplicate"))
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["score"]["A"], 1)
        self.call("POST", f"/api/matches/{mid}/events", {"type": "goal", "team": "A", "player": "A9", "expected_version": 1}, 409)

    def test_setup_patch_and_export_import(self):
        mid = self.fb()
        self.call("POST", f"/api/matches/{mid}/setup", {"patch": {"venue": "New Ground", "officials": {"referee": "Z"}, "info": {"attendance": "1200"},
                                                                  "teams": {"A": {"formation": "4-3-3"}}}})
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual(st["venue"], "New Ground")
        self.assertEqual(st["officials"]["referee"], "Z")
        self.assertEqual(st["attendance"], "1200")
        self.assertEqual(st["teams"]["A"]["formation"], "4-3-3")
        doc = self.call("GET", f"/api/matches/{mid}/export")
        new = self.call("POST", "/api/import", doc, 201)["id"]
        self.assertEqual(self.call("GET", f"/api/matches/{new}/meta")["sport"], "football")


if __name__ == "__main__":
    unittest.main()
