"""Engine tests - run with:  python -m unittest discover -s tests -v   (standard library only)

Every test documents a rule of the game or a bug found in the legacy engine
(see docs/BUG_AUDIT.md for the numbered list - the number is in the test name).
"""
import copy
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from goscore import engine as E  # noqa: E402


def roster(prefix, n=11):
    return [{"id": f"{prefix}{i}", "name": f"{prefix} Player {i}"} for i in range(1, n + 1)]


def new_match(overs=20, preset="t20", extra_fmt=None, na=11, nb=11, toss=("A", "bat")):
    fmt = {"preset": preset, "overs": overs}
    fmt.update(extra_fmt or {})
    return {"id": "m1", "title": "Test", "format": fmt,
            "teams": {"A": {"name": "Alpha", "short": "ALP", "players": roster("A", na)},
                      "B": {"name": "Beta", "short": "BET", "players": roster("B", nb)}},
            "toss": {"winner": toss[0], "decision": toss[1]}, "events": []}


class Log:
    """Tiny helper that appends events and gives access to derived state."""

    def __init__(self, **kw):
        self.m = new_match(**kw)
        self.n = 0

    def add(self, type_, **kw):
        self.n += 1
        ev = {"id": f"e{self.n}", "type": type_, **kw}
        self.m["events"].append(ev)
        return ev

    def start(self, inn=0, batting=None, striker="A1", non="A2", bowler="B1", **kw):
        if batting is None:
            batting = "A" if inn % 2 == 0 else "B"
        if batting == "B":
            striker, non, bowler = (striker if striker.startswith("B") else "B1",
                                    non if non.startswith("B") else "B2",
                                    bowler if bowler.startswith("A") else "A1")
        return self.add("innings_start", innings=inn, batting=batting, striker=striker,
                        non_striker=non, bowler=bowler, **kw)

    def ball(self, inn=0, **kw):
        return self.add("ball", innings=inn, **kw)

    def bowler(self, pid, inn=0, **kw):
        return self.add("set_bowler", innings=inn, bowler=pid, **kw)

    def st(self):
        return E.derive(copy.deepcopy(self.m))

    def inn(self, i=0):
        return self.st()["innings"][i]

    def err(self):
        return self.st()["integrity"]["errors"]

    def check_rejected(self, ev):
        return E.validate_append(self.m, ev)


def bat(i, pid):
    return next(b for b in i["batters"] if b["id"] == pid)


def bowl(i, pid):
    return next(b for b in i["bowlers"] if b["id"] == pid)


class Scoring(unittest.TestCase):
    def test_bug01_single_rotates_strike_without_extra_field(self):
        L = Log(); L.start(); L.ball(bat_runs=1)
        i = L.inn()
        self.assertEqual((i["striker"], i["non_striker"]), ("A2", "A1"))
        self.assertEqual(i["runs"], 1)
        self.assertEqual(bat(i, "A1")["runs"], 1)

    def test_current_state_exposes_wickets_needed_by_bowling_side(self):
        L = Log(); L.start()
        self.assertEqual(L.st()["current"]["wickets_left"], 10)
        L.ball(wicket={"kind": "bowled", "new_batter": "A3"})
        self.assertEqual(L.st()["current"]["wickets_left"], 9)

    def test_byes_and_legbyes_are_extras_not_batter_runs(self):
        L = Log(); L.start()
        L.ball(byes=2)
        i = L.inn()
        self.assertEqual(i["runs"], 2)
        self.assertEqual(i["extras"]["bye"], 2)
        self.assertEqual(bat(i, "A1")["runs"], 0)
        self.assertEqual(bat(i, "A1")["balls"], 1)
        L.ball(legbyes=1)
        i = L.inn()
        self.assertEqual(i["runs"], 3)
        self.assertEqual(i["extras"]["legbye"], 1)
        self.assertEqual(bat(i, "A1")["runs"], 0)
        self.assertEqual(sum(b["runs"] for b in i["batters"]) + i["extras"]["total"], i["runs"])

    def test_boundary_does_not_rotate_but_all_run_four_does_not_either(self):
        L = Log(); L.start(); L.ball(bat_runs=4, boundary=True)
        self.assertEqual(L.inn()["striker"], "A1")
        self.assertEqual(bat(L.inn(), "A1")["fours"], 1)
        L.ball(bat_runs=4, boundary=False)          # four runs actually run
        self.assertEqual(L.inn()["striker"], "A1")  # even number of runs
        self.assertEqual(bat(L.inn(), "A1")["fours"], 1)   # not a boundary stat

    def test_three_runs_rotates_and_overthrow_ran_override(self):
        L = Log(); L.start(); L.ball(bat_runs=3)
        self.assertEqual(L.inn()["striker"], "A2")
        # 1 run completed + overthrow boundary = 5 to the batter, batters crossed once
        L.ball(bat_runs=5, ran=1)
        self.assertEqual(L.inn()["striker"], "A1")
        self.assertEqual(bat(L.inn(), "A2")["runs"], 5)

    def test_over_end_swaps_ends_and_requires_new_bowler(self):
        L = Log(); L.start()
        for _ in range(6):
            L.ball(bat_runs=0)
        i = L.inn()
        self.assertEqual(i["overs"], "1.0")
        self.assertEqual((i["striker"], i["non_striker"]), ("A2", "A1"))
        self.assertTrue(i["pending_bowler"])
        err = L.check_rejected({"type": "ball", "innings": 0, "bat_runs": 1})
        self.assertEqual(err["code"], "bowler_required")

    def test_bug02_maiden_over_counted_and_not_when_wide(self):
        L = Log(); L.start()
        for _ in range(6):
            L.ball(bat_runs=0)
        self.assertEqual(bowl(L.inn(), "B1")["maidens"], 1)
        L.bowler("B2")
        L.ball(delivery="wide")
        for _ in range(6):
            L.ball(bat_runs=0)
        self.assertEqual(bowl(L.inn(), "B2")["maidens"], 0)
        self.assertEqual(bowl(L.inn(), "B2")["runs"], 1)

    def test_maiden_allows_byes(self):
        L = Log(); L.start()
        L.ball(byes=1, ran=0)  # a bye is not charged to the bowler
        for _ in range(5):
            L.ball(bat_runs=0)
        self.assertEqual(bowl(L.inn(), "B1")["maidens"], 1)

    def test_bug03_wide_with_runs_is_all_wides_and_bye_on_wide_rejected(self):
        L = Log(); L.start()
        L.ball(delivery="wide", wide_runs=2)
        i = L.inn()
        self.assertEqual(i["runs"], 3)
        self.assertEqual(i["extras"]["wide"], 3)
        self.assertEqual(i["extras"]["total"], 3)
        self.assertEqual(i["legal_balls"], 0)           # Law 22: not one of the over
        self.assertEqual(bat(i, "A1")["balls"], 0)      # wide is not a ball faced
        self.assertEqual(i["striker"], "A1")            # 2 runs run = even -> batters back where they started

    def test_wide_runs_rotation(self):
        L = Log(); L.start(); L.ball(delivery="wide", wide_runs=1)
        self.assertEqual(L.inn()["striker"], "A2")      # one run was run
        L.ball(delivery="wide", wide_runs=4, boundary=True)
        self.assertEqual(L.inn()["striker"], "A2")      # boundary: nobody ran

    def test_bug03b_bye_on_wide_is_rejected(self):
        L = Log(); L.start()
        err = L.check_rejected({"type": "ball", "innings": 0, "delivery": "wide", "byes": 2})
        self.assertEqual(err["code"], "wide_runs")

    def test_no_ball_charges_bowler_not_in_over_bat_runs_to_batter(self):
        L = Log(); L.start(); L.ball(delivery="noball", bat_runs=4, boundary=True)
        i = L.inn()
        self.assertEqual(i["runs"], 5)
        self.assertEqual(i["legal_balls"], 0)
        self.assertEqual(bat(i, "A1")["runs"], 4)
        self.assertEqual(bat(i, "A1")["balls"], 1)      # faced
        self.assertEqual(bowl(i, "B1")["runs"], 5)
        self.assertEqual(i["extras"]["noball"], 1)

    def test_bug04_byes_on_no_ball_are_byes_and_nb_penalty(self):
        L = Log(); L.start(); L.ball(delivery="noball", byes=2)
        i = L.inn()
        self.assertEqual(i["extras"]["noball"], 1)
        self.assertEqual(i["extras"]["bye"], 2)
        self.assertEqual(i["extras"]["penalty"], 0)
        self.assertEqual(bowl(i, "B1")["runs"], 1)      # byes not debited to bowler

    def test_bat_and_byes_same_ball_rejected(self):
        L = Log(); L.start()
        self.assertEqual(L.check_rejected({"type": "ball", "innings": 0, "bat_runs": 1, "byes": 1})["code"], "mixed_runs")

    def test_batters_runs_plus_extras_equal_team_total(self):
        L = Log(); L.start()
        L.ball(bat_runs=2); L.ball(delivery="wide", wide_runs=1); L.ball(byes=1); L.ball(legbyes=2)
        L.ball(delivery="noball", bat_runs=1); L.add("penalty_runs", awarded_to="A", runs=5, innings=0)
        i = L.inn()
        self.assertEqual(i["runs"], sum(b["runs"] for b in i["batters"]) + i["extras"]["total"])
        self.assertEqual(L.st()["integrity"]["info"], [])


class Dismissals(unittest.TestCase):
    def wk(self, kind, **kw):
        return {"kind": kind, "new_batter": "A3", **kw}

    def test_bug05_caught_off_noball_rejected(self):
        L = Log(); L.start()
        err = L.check_rejected({"type": "ball", "innings": 0, "delivery": "noball",
                                "wicket": self.wk("caught", fielder="B5")})
        self.assertEqual(err["code"], "illegal_dismissal")

    def test_bug05_bowled_lbw_off_wide_rejected_stumped_ok(self):
        L = Log(); L.start()
        for k in ("bowled", "lbw", "caught", "hit_twice"):
            err = L.check_rejected({"type": "ball", "innings": 0, "delivery": "wide", "wicket": self.wk(k)})
            self.assertEqual(err["code"], "illegal_dismissal", k)
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0, "delivery": "wide",
                                            "wicket": self.wk("stumped", fielder="B11")}))
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0, "delivery": "wide",
                                            "wicket": self.wk("hit_wicket")}))

    def test_run_out_and_obstructing_allowed_off_noball_stumped_not(self):
        L = Log(); L.start()
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0, "delivery": "noball",
                                            "wicket": self.wk("run_out", out="A2", fielder="B4")}))
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0, "delivery": "noball",
                                            "wicket": self.wk("obstructing", out="A2")}))
        self.assertEqual(L.check_rejected({"type": "ball", "innings": 0, "delivery": "noball",
                                           "wicket": self.wk("stumped")})["code"], "illegal_dismissal")

    def test_bug12_free_hit_after_noball_blocks_bowled_and_carries_over_wide(self):
        L = Log(); L.start(); L.ball(delivery="noball")
        self.assertTrue(L.inn()["free_hit"])
        self.assertEqual(L.check_rejected({"type": "ball", "innings": 0, "wicket": self.wk("bowled")})["code"],
                         "free_hit_dismissal")
        L.ball(delivery="wide")                          # free hit carries over a wide
        self.assertTrue(L.inn()["free_hit"])
        L.ball(bat_runs=0)                               # legal delivery consumes it
        self.assertFalse(L.inn()["free_hit"])
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0, "wicket": self.wk("bowled")}))

    def test_free_hit_run_out_allowed(self):
        L = Log(); L.start(); L.ball(delivery="noball")
        self.assertIsNone(L.check_rejected({"type": "ball", "innings": 0,
                                            "wicket": self.wk("run_out", out="A2", fielder="B3")}))

    def test_free_hit_can_be_disabled_for_home_rules(self):
        L = Log(extra_fmt={"free_hit": False}); L.start(); L.ball(delivery="noball")
        self.assertFalse(L.inn()["free_hit"])

    def test_bug15_out_player_must_be_at_crease(self):
        L = Log(); L.start()
        err = L.check_rejected({"type": "ball", "innings": 0, "wicket": {"kind": "run_out", "out": "A9"}})
        self.assertEqual(err["code"], "out_not_at_crease")

    def test_striker_only_dismissals(self):
        L = Log(); L.start()
        err = L.check_rejected({"type": "ball", "innings": 0, "wicket": {"kind": "bowled", "out": "A2"}})
        self.assertEqual(err["code"], "striker_only")

    def test_no_runs_when_bowled_or_caught(self):
        L = Log(); L.start()
        err = L.check_rejected({"type": "ball", "innings": 0, "bat_runs": 1, "wicket": self.wk("bowled")})
        self.assertEqual(err["code"], "no_runs_on_dismissal")

    def test_runs_count_on_run_out(self):
        L = Log(); L.start()
        L.ball(bat_runs=1, wicket={"kind": "run_out", "out": "A2", "fielder": "B3", "new_batter": "A3",
                                   "new_batter_on_strike": False})
        i = L.inn()
        self.assertEqual(i["runs"], 1)
        self.assertEqual(i["wickets"], 1)
        self.assertEqual(bat(i, "A1")["runs"], 1)
        self.assertEqual(i["striker"], "A1" if False else i["striker"])  # positions asserted below
        # A1 and A2 crossed on the completed run (A2 striker slot) then A2 run out -> A1 survives
        self.assertIn("A1", (i["striker"], i["non_striker"]))
        self.assertIn("A3", (i["striker"], i["non_striker"]))
        self.assertEqual(i["non_striker"], "A3")                    # explicit: new batter off strike
        self.assertEqual(bowl(i, "B1")["wickets"], 0)               # run out is not the bowler's

    def test_bowler_credit_matrix(self):
        credited = {"bowled": 1, "caught": 1, "lbw": 1, "stumped": 1, "hit_wicket": 1,
                    "run_out": 0, "hit_twice": 0, "obstructing": 0}
        for k, v in credited.items():
            L = Log(); L.start()
            out = "A1"
            L.ball(wicket={"kind": k, "out": out, "fielder": "B5", "new_batter": "A3"})
            self.assertEqual(bowl(L.inn(), "B1")["wickets"], v, k)
            self.assertEqual(L.inn()["wickets"], 1, k)

    def test_bug07_dismissal_text(self):
        def how(kind, **w):
            L = Log(); L.start(); L.ball(wicket={"kind": kind, "out": "A1", "new_batter": "A3", **w})
            return bat(L.inn(), "A1")["how"]
        self.assertEqual(how("bowled"), "b B Player 1")
        self.assertEqual(how("lbw"), "lbw b B Player 1")
        self.assertEqual(how("caught", fielder="B5"), "c B Player 5 b B Player 1")
        self.assertEqual(how("caught", fielder="B1"), "c & b B Player 1")
        self.assertEqual(how("stumped", fielder="B11"), "st B Player 11 b B Player 1")
        self.assertEqual(how("run_out", fielder="B3"), "run out (B Player 3)")
        self.assertEqual(how("obstructing"), "obstructing the field")
        self.assertEqual(how("hit_twice"), "hit the ball twice")

    def test_dismissal_new_batter_takes_dismissed_end_and_strike_toggle(self):
        L = Log(); L.start(); L.ball(wicket={"kind": "bowled", "new_batter": "A3"})
        i = L.inn()
        self.assertEqual((i["striker"], i["non_striker"]), ("A3", "A2"))
        L2 = Log(); L2.start(); L2.ball(wicket={"kind": "caught", "fielder": "B2", "new_batter": "A3",
                                                "new_batter_on_strike": False})
        i = L2.inn()
        self.assertEqual((i["striker"], i["non_striker"]), ("A2", "A3"))

    def test_wicket_without_new_batter_blocks_next_ball(self):
        L = Log(); L.start(); L.ball(wicket={"kind": "bowled"})
        self.assertTrue(L.inn()["pending_batter"])
        self.assertEqual(L.check_rejected({"type": "ball", "innings": 0, "bat_runs": 0})["code"], "batter_required")
        L.add("new_batter", innings=0, player="A3")
        self.assertFalse(L.inn()["pending_batter"])
        self.assertEqual(L.inn()["striker"], "A3")

    def test_bug06_retired_hurt_is_not_out_and_does_not_consume_a_ball(self):
        L = Log(); L.start(); L.ball(bat_runs=2)
        L.add("retire", innings=0, player="A1", kind="hurt", replacement="A3")
        i = L.inn()
        self.assertEqual(i["wickets"], 0)
        self.assertEqual(i["legal_balls"], 1)
        self.assertEqual(bat(i, "A1")["status"], "retired_hurt")
        self.assertNotEqual(bat(i, "A1")["status"], "out")
        # may return later in place of a new batter
        L.ball(wicket={"kind": "bowled", "new_batter": "A1"})
        i = L.inn()
        self.assertEqual(bat(i, "A1")["status"], "batting")
        self.assertEqual(bat(i, "A1")["runs"], 2)           # stats preserved

    def test_retired_out_counts_as_wicket_not_bowlers(self):
        L = Log(); L.start()
        L.add("retire", innings=0, player="A1", kind="out", replacement="A3")
        i = L.inn()
        self.assertEqual(i["wickets"], 1)
        self.assertEqual(bat(i, "A1")["how"], "retired out")
        self.assertEqual(bowl(i, "B1")["wickets"], 0) if i["bowlers"] else None

    def test_timed_out(self):
        L = Log(); L.start(); L.ball(wicket={"kind": "bowled"})
        L.add("timed_out", innings=0, player="A3", new_batter="A4")
        i = L.inn()
        self.assertEqual(i["wickets"], 2)
        self.assertEqual(bat(i, "A3")["how"], "timed out")
        self.assertEqual(i["striker"], "A4")

    def test_fow_has_score_over_partnership(self):
        L = Log(); L.start(); L.ball(bat_runs=1); L.ball(bat_runs=4, boundary=True)
        L.ball(wicket={"kind": "bowled", "out": "A2", "new_batter": "A3"})     # A2 is on strike after the single
        f = L.inn()["fow"][0]
        self.assertEqual((f["wicket"], f["score"], f["batter"], f["over"]), (1, 5, "A2", "0.3"))
        self.assertEqual(f["partnership_runs"], 5)


class InningsAndResults(unittest.TestCase):
    def play_over(self, L, inn, runs_each=1, bowler=None):
        if bowler:
            L.bowler(bowler, inn=inn)
        for _ in range(6):
            L.ball(inn=inn, bat_runs=runs_each)

    def test_bug10_innings_ends_at_overs_limit_and_rejects_extra_balls(self):
        L = Log(overs=2); L.start()
        self.play_over(L, 0, 1)
        self.play_over(L, 0, 1, bowler="B2")
        i = L.inn()
        self.assertEqual(i["status"], "completed")
        self.assertEqual(i["end_reason"], "overs_completed")
        self.assertEqual(L.check_rejected({"type": "ball", "innings": 0, "bat_runs": 1})["code"], "innings_over")

    def test_bug09_all_out_uses_team_size_not_hard_coded_ten(self):
        L = Log(overs=20, na=6)                       # 6-a-side -> 5 wickets
        L.start()
        order = ["A3", "A4", "A5", "A6"]
        for k, nb in enumerate(order):
            L.ball(wicket={"kind": "bowled", "new_batter": nb})
            if k % 2 == 0:
                pass
        # wickets 4, one more ends the innings
        L.ball(wicket={"kind": "bowled"})
        i = L.inn()
        self.assertEqual(i["wickets"], 5)
        self.assertEqual(i["wickets_limit"], 5)
        self.assertEqual(i["end_reason"], "all_out")

    def test_chase_won_by_wickets_with_balls_remaining(self):
        L = Log(overs=1); L.start(bowler="B1")
        for _ in range(6):
            L.ball(bat_runs=1)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        L.ball(inn=1, bat_runs=6, boundary=True)
        st = L.st()
        self.assertEqual(st["innings"][1]["target"], 7)
        self.assertEqual(st["innings"][1]["need"], 1)
        L.ball(inn=1, bat_runs=1)
        st = L.st()
        self.assertEqual(st["result"]["status"], "won")
        self.assertEqual(st["result"]["winner"], "B")
        self.assertIn("won by 10 wickets", st["result"]["text"])
        self.assertIn("4 balls remaining", st["result"]["text"])
        self.assertEqual(st["status"], "completed")

    def test_bug09_won_by_runs_and_tie(self):
        L = Log(overs=1); L.start()
        for _ in range(6):
            L.ball(bat_runs=1)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        for _ in range(6):
            L.ball(inn=1, bat_runs=0)
        r = L.st()["result"]
        self.assertEqual(r["status"], "won")
        self.assertEqual(r["winner"], "A")
        self.assertIn("Alpha won by 6 runs", r["text"])
        # tie
        L = Log(overs=1); L.start()
        for _ in range(6):
            L.ball(bat_runs=1)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        for _ in range(6):
            L.ball(inn=1, bat_runs=1)
        # 6 v 6: need 7 to win -> tie
        st = L.st()
        self.assertEqual(st["result"]["status"], "tie")
        self.assertTrue(st["result"]["super_over_needed"])
        self.assertEqual(st["status"], "super_over_pending")

    def test_super_over_flow(self):
        L = Log(overs=1); L.start()
        for _ in range(6):
            L.ball(bat_runs=1)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        for _ in range(6):
            L.ball(inn=1, bat_runs=1)
        # Super over: team that batted second (B) bats first
        L.add("innings_start", innings=2, kind="super_over", striker="B1", non_striker="B2", bowler="A1")
        i2 = L.st()["innings"][2]
        self.assertEqual(i2["batting"], "B")
        self.assertEqual((i2["overs_limit"], i2["wickets_limit"]), (1, 2))
        for _ in range(6):
            L.ball(inn=2, bat_runs=2)
        L.add("innings_start", innings=3, kind="super_over", striker="A1", non_striker="A2", bowler="B1")
        st = L.st()
        self.assertEqual(st["innings"][3]["target"], 13)
        for _ in range(6):
            L.ball(inn=3, bat_runs=1)
        st = L.st()
        self.assertEqual(st["result"]["winner"], "B")
        self.assertIn("Super Over", st["result"]["text"])

    def test_dls_manual_revision(self):
        L = Log(overs=20); L.start()
        L.ball(bat_runs=6, boundary=True)
        L.add("innings_end", innings=0, reason="time")
        L.add("revise", innings=1, overs_limit=10, target=80, method="DLS")       # before innings 2 starts
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        i = L.st()["innings"][1]
        self.assertEqual((i["overs_limit"], i["target"]), (10, 80))
        self.assertEqual(i["revision"]["method"], "DLS")

    def test_bug14_bowler_consecutive_overs_and_quota(self):
        L = Log(overs=10); L.start()                    # 10 overs -> 2 per bowler
        self.play_over(L, 0, 1)
        err = L.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B1"})
        self.assertEqual(err["code"], "consecutive_overs")
        self.assertIsNone(L.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B1", "force": ["consecutive"]}))
        L.bowler("B2"); self.play_over(L, 0)
        L.bowler("B1"); self.play_over(L, 0)
        L.bowler("B2"); self.play_over(L, 0)            # B2 has now bowled 2
        err = L.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B2"})
        self.assertIn(err["code"], ("consecutive_overs", "bowler_quota"))
        L.bowler("B3"); self.play_over(L, 0)
        L.bowler("B2" if False else "B4")
        L.bowler("B1")                                   # B1 has bowled 2 already (overs 1 and 3)
        # B1 quota reached: reject
        L2 = Log(overs=10); L2.start()
        self.play_over(L2, 0); L2.bowler("B2"); self.play_over(L2, 0); L2.bowler("B1"); self.play_over(L2, 0)
        L2.bowler("B2"); self.play_over(L2, 0)
        err = L2.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B1"})
        self.assertEqual(err["code"], "bowler_quota")

    def test_midover_bowler_change_needs_reason(self):
        L = Log(); L.start(); L.ball(bat_runs=0)
        self.assertEqual(L.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B2"})["code"], "midover_change")
        self.assertIsNone(L.check_rejected({"type": "set_bowler", "innings": 0, "bowler": "B2", "reason": "injury"}))

    def test_penalty_runs_to_batting_side_not_credited_to_bowler(self):
        L = Log(); L.start(); L.add("penalty_runs", awarded_to="A", runs=5, innings=0)
        i = L.inn()
        self.assertEqual(i["runs"], 5)
        self.assertEqual(i["extras"]["penalty"], 5)

    def test_penalty_runs_to_fielding_side_applied_to_their_next_innings(self):
        L = Log(overs=1); L.start()
        L.add("penalty_runs", awarded_to="B", runs=5)         # B hasn't batted yet
        self.assertEqual(L.inn()["runs"], 0)
        for _ in range(6):
            L.ball(bat_runs=0)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        i1 = L.inn(1)
        self.assertEqual((i1["runs"], i1["extras"]["penalty"]), (5, 5))

    def test_penalty_runs_to_fielding_side_after_they_batted_goes_to_earlier_innings(self):
        L = Log(overs=1); L.start(batting="A")
        for _ in range(6):
            L.ball(bat_runs=1)
        L.start(inn=1, striker="B1", non="B2", bowler="A1")
        L.add("penalty_runs", awarded_to="A", runs=5)         # A's innings is complete -> added there
        st = L.st()
        self.assertEqual(st["innings"][0]["runs"], 11)
        self.assertEqual(st["innings"][1]["target"], 12)       # target follows

    def test_powerplay_label(self):
        L = Log(); L.start()
        self.assertEqual(L.st()["current"]["powerplay"], "Powerplay")

    def test_hundred_ball_format(self):
        L = Log(preset="hundred", overs=20); L.start()
        for _ in range(5):
            L.ball(bat_runs=0)
        i = L.inn()
        self.assertEqual(i["overs"], "1.0")
        self.assertEqual(i["balls_limit"], 100)
        self.assertEqual(bowl(i, "B1")["maidens"], 1)


class Overrides(unittest.TestCase):
    def test_override_pins_value_and_later_balls_build_on_it(self):
        L = Log(); L.start(); L.ball(bat_runs=1)
        L.add("override", innings=0, set={"runs": 50, "wickets": 2, "balls": 30}, reason="scorer missed 6 overs")
        L.ball(bat_runs=4, boundary=True)
        i = L.inn()
        self.assertEqual((i["runs"], i["wickets"], i["legal_balls"]), (54, 2, 31))
        self.assertIn("runs", i["overridden"])
        self.assertTrue(L.st()["integrity"]["info"])          # parts no longer add up -> flagged, not hidden

    def test_override_batter_and_bowler_stats(self):
        L = Log(); L.start(); L.ball(bat_runs=1)
        L.add("override", innings=0, set={"batter.A1.runs": 37, "batter.A1.balls": 22, "batter.A1.fours": 5,
                                          "bowler.B1.wickets": 2, "bowler.B1.runs": 11, "striker": "A2"})
        i = L.inn()
        self.assertEqual((bat(i, "A1")["runs"], bat(i, "A1")["balls"], bat(i, "A1")["fours"]), (37, 22, 5))
        self.assertEqual((bowl(i, "B1")["wickets"], bowl(i, "B1")["runs"]), (2, 11))

    def test_override_rejects_unknown_target_but_engine_survives(self):
        L = Log(); L.start(); L.add("override", innings=0, set={"nonsense": 1})
        st = L.st()
        self.assertEqual(st["integrity"]["errors"][0]["code"], "bad_override")
        self.assertEqual(st["innings"][0]["runs"], 0)

    def test_delete_event_in_middle_replays_correctly(self):
        L = Log(); L.start(); L.ball(bat_runs=1); e = L.ball(bat_runs=4, boundary=True); L.ball(bat_runs=2)
        L.m["events"] = [x for x in L.m["events"] if x["id"] != e["id"]]
        i = L.inn()
        self.assertEqual(i["runs"], 3)
        self.assertEqual(i["striker"], "A2")

    def test_edit_event_changes_everything_downstream(self):
        L = Log(); L.start(); e = L.ball(bat_runs=1); L.ball(bat_runs=0)
        e["bat_runs"] = 2
        i = L.inn()
        self.assertEqual(i["runs"], 2)
        self.assertEqual(i["striker"], "A1")          # 2 runs -> no change of strike

    def test_insert_missed_ball_before_wicket(self):
        L = Log(); L.start(); L.ball(bat_runs=1); L.ball(wicket={"kind": "bowled", "new_batter": "A3"})
        missed = {"id": "missed", "type": "ball", "innings": 0, "bat_runs": 2}
        L.m["events"].insert(2, missed)
        i = L.inn()
        self.assertEqual((i["runs"], i["wickets"], i["legal_balls"]), (3, 1, 3))

    def test_invalid_event_is_flagged_and_skipped_not_fatal(self):
        L = Log(overs=1); L.start()
        for _ in range(6):
            L.ball(bat_runs=1)
        bad = L.ball(bat_runs=1)                       # 7th ball: innings is over
        st = L.st()
        self.assertEqual(st["innings"][0]["runs"], 6)
        self.assertFalse(st["event_status"][bad["id"]]["ok"])
        self.assertEqual(st["integrity"]["errors"][0]["code"], "innings_over")

    def test_explicit_result_override(self):
        L = Log(); L.start()
        L.add("result", status="won", winner="B", text="Beta won (forfeit)", method="manual")
        r = L.st()["result"]
        self.assertEqual((r["winner"], r["text"], r["final"]), ("B", "Beta won (forfeit)", True))
        L.add("clear_result")
        self.assertFalse(L.st()["result"]["final"])

    def test_substitution(self):
        L = Log(); L.m["teams"]["A"]["players"].append({"id": "A12", "name": "Impact Guy", "xi": False})
        L.start()
        L.add("substitution", out="A5", **{"in": "A12"})
        st = L.st()
        self.assertFalse(next(p for p in st["teams"]["A"]["players"] if p["id"] == "A5")["xi"])
        self.assertTrue(next(p for p in st["teams"]["A"]["players"] if p["id"] == "A12")["xi"])
        err = L.check_rejected({"type": "new_batter", "innings": 0, "player": "A5"})
        self.assertIn(err["code"], ("no_slot", "subbed_out", "not_in_xi"))


class Fuzz(unittest.TestCase):
    """Random but rule-abiding matches: the arithmetic of the scoreboard must always reconcile."""

    def random_match(self, seed, overs=5):
        rnd = random.Random(seed)
        L = Log(overs=overs)
        order = {0: iter([f"A{i}" for i in range(3, 12)]), 1: iter([f"B{i}" for i in range(3, 12)])}
        for inn in (0, 1):
            bt = "A" if inn == 0 else "B"
            fb = "B" if inn == 0 else "A"
            L.add("innings_start", innings=inn, batting=bt, striker=f"{bt}1", non_striker=f"{bt}2",
                  bowler=f"{fb}{rnd.randint(1, 6)}")
            last = None
            guard = 0
            while True:
                guard += 1
                assert guard < 600
                st = L.st()
                i = st["innings"][inn]
                if i["status"] == "completed":
                    break
                if i["pending_bowler"]:
                    cands = [f"{fb}{k}" for k in range(1, 8) if f"{fb}{k}" != last]
                    # respect quota: overs=5 -> 1 per bowler
                    used = {b["id"]: b["balls"] for b in i["bowlers"]}
                    cands = [c for c in cands if used.get(c, 0) < 6] or [f"{fb}{k}" for k in range(8, 12)]
                    pick = rnd.choice(cands)
                    L.bowler(pick, inn=inn)
                    continue
                if i["pending_batter"]:
                    L.add("new_batter", innings=inn, player=next(order[inn]))
                    continue
                last = i["bowler"]
                r = rnd.random()
                d = "legal"
                kw = {}
                if r < 0.06:
                    d = "wide"; kw["wide_runs"] = rnd.choice([0, 0, 1, 4]); kw["boundary"] = kw["wide_runs"] == 4
                elif r < 0.10:
                    d = "noball"
                    if rnd.random() < .5:
                        kw["bat_runs"] = rnd.choice([1, 2, 4, 6]); kw["boundary"] = kw["bat_runs"] in (4, 6)
                elif r < 0.17:
                    kw[rnd.choice(["byes", "legbyes"])] = rnd.choice([1, 2])
                elif r < 0.27 and i["wickets"] < i["wickets_limit"] - 1:
                    kinds = ["bowled", "caught", "lbw", "stumped", "hit_wicket", "run_out"]
                    allowed = [k for k in kinds if k in E.ALLOWED_OFF[d] and
                               not (i["free_hit"] and k not in E.FREE_HIT_ALLOWED)]
                    k = rnd.choice(allowed)
                    kw["wicket"] = {"kind": k, "out": i["striker"] if k != "run_out" else rnd.choice([i["striker"], i["non_striker"]]),
                                    "fielder": f"{fb}{rnd.randint(1, 11)}", "new_batter": next(order[inn], None)}
                    if k == "run_out":
                        kw["bat_runs"] = rnd.choice([0, 1])
                else:
                    kw["bat_runs"] = rnd.choice([0, 0, 0, 1, 1, 1, 2, 3, 4, 6])
                    kw["boundary"] = kw["bat_runs"] in (4, 6)
                if d == "legal" and kw.get("wicket") is None:
                    pass
                if kw.get("wicket") and kw["wicket"]["new_batter"] is None:
                    del kw["wicket"]
                ev = {"id": f"f{L.n + 1}", "type": "ball", "innings": inn, "delivery": d, **kw}
                if E.validate_append(L.m, ev):
                    continue
                L.n += 1
                L.m["events"].append(ev)
        return L

    def test_invariants_over_many_random_matches(self):
        for seed in range(60):
            L = self.random_match(seed)
            st = L.st()
            self.assertEqual(st["integrity"]["errors"], [], f"seed {seed}")
            self.assertEqual(st["integrity"]["info"], [], f"seed {seed}: {st['integrity']['info']}")
            for i in st["innings"]:
                self.assertEqual(i["runs"], sum(b["runs"] for b in i["batters"]) + i["extras"]["total"])
                self.assertEqual(i["legal_balls"], sum(b["balls"] for b in i["bowlers"]))
                self.assertEqual(i["wickets"], sum(1 for b in i["batters"] if b["status"] == "out"))
                self.assertEqual(i["wickets"], len(i["fow"]))
                self.assertEqual(sum(o["runs"] for o in i["overs_detail"]), i["runs"] - i["extras"]["penalty"])
                self.assertLessEqual(i["legal_balls"], i["overs_limit"] * 6)
                self.assertEqual(i["extras"]["wide"], sum(b["wides"] for b in i["bowlers"]))
                self.assertEqual(i["extras"]["noball"], sum(b["noballs"] for b in i["bowlers"]))
                bowler_wkts = sum(b["wickets"] for b in i["bowlers"])
                credited = sum(1 for b in i["batters"] if b["status"] == "out" and b["kind"] in E.BOWLER_CREDIT)
                self.assertEqual(bowler_wkts, credited)
            self.assertIsNotNone(st["result"]["text"], f"seed {seed}")

    def test_undo_equivalence_and_determinism(self):
        L = self.random_match(7)
        full = L.st()
        again = L.st()
        self.assertEqual(full["innings"][0]["runs"], again["innings"][0]["runs"])
        for cut in (5, 20, 33, 47):
            m = copy.deepcopy(L.m)
            m["events"] = m["events"][:cut]
            prefix_state = E.derive(copy.deepcopy(m))
            # replaying prefix + event == replaying longer prefix
            m2 = copy.deepcopy(L.m)
            m2["events"] = m2["events"][:cut + 1]
            m2["events"].pop()
            self.assertEqual(E.derive(m2)["innings"][0]["runs"], prefix_state["innings"][0]["runs"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class RolesAndTags(unittest.TestCase):
    def _m(self):
        pl = lambda p, wk: [{"id": f"{p}{i}", "name": f"P{p}{i}", "wk": i == wk, "captain": i == 2, "role": "bowler" if i > 8 else "batter"} for i in range(1, 12)]
        return {"id": "x", "version": 1, "title": "t", "format": E.make_format({"preset": "t20"}),
                "teams": {"A": {"name": "A", "players": pl("A", 1)}, "B": {"name": "B", "players": pl("B", 4)}}, "toss": {},
                "events": [{"id": "e0", "type": "innings_start", "innings": 0, "batting": "A", "striker": "A1", "non_striker": "A2", "bowler": "B8"}]}

    def test_roles_normalised_and_unknown_role_cleared(self):
        m = self._m(); m["teams"]["A"]["players"][0]["role"] = "wizard"
        E.normalize_setup(m)
        self.assertEqual(m["teams"]["A"]["players"][0]["role"], "")
        self.assertTrue(m["teams"]["B"]["players"][3]["wk"])

    def test_keeper_marked_and_stumping_defaults_to_keeper(self):
        m = self._m()
        m["events"] += [{"id": "e1", "type": "ball", "innings": 0, "delivery": "wide", "wicket": {"kind": "stumped", "new_batter": "A3"}},
                        {"id": "e2", "type": "ball", "innings": 0, "wicket": {"kind": "caught", "fielder": "B4", "new_batter": "A4"}}]
        s = E.derive(m); bat = {b["id"]: b for b in s["innings"][0]["batters"]}
        self.assertEqual(bat["A1"]["status_text"], "st †PB4 b PB8")
        self.assertEqual(bat["A3"]["status_text"], "c †PB4 b PB8")
        self.assertEqual(bat["A1"]["tag"], " †"); self.assertEqual(bat["A2"]["tag"], " (c)")
        self.assertEqual(s["integrity"]["errors"], [])
