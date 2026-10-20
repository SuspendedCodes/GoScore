"""Two-innings-a-side (Test / multi-day) behaviour: results, follow-on, day/session tracking, lead/trail, performance, robustness."""
import copy
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_engine import Log  # noqa: E402
from goscore import engine as E  # noqa: E402


def play(L, idx, batting, runs, outs, end=None):
    """Score one innings: `runs` runs and `outs` wickets (the 10th wicket only after the runs are in)."""
    bw = "B" if batting == "A" else "A"
    L.add("innings_start", innings=idx, batting=batting, striker=f"{batting}1", non_striker=f"{batting}2", bowler=f"{bw}1")
    nxt, balls, r, out_n, bowler = 3, 0, 0, 0, 1
    while out_n < outs or r < runs:
        thr = runs * (out_n + 1) / (outs + 1) if out_n < outs - 1 else runs
        if out_n < outs and r >= thr:
            wk = {"kind": "bowled"}
            if nxt <= 11 and out_n < 9:
                wk["new_batter"] = f"{batting}{nxt}"
            L.add("ball", innings=idx, wicket=wk)
            out_n += 1
            nxt += 1
        else:
            br = 4 if (runs - r) >= 4 and balls % 5 == 0 else 1
            L.add("ball", innings=idx, bat_runs=br, boundary=(br == 4))
            r += br
        balls += 1
        if L.st()["innings"][idx]["status"] == "completed":
            break
        if balls % 6 == 0:
            bowler = bowler % 5 + 1
            L.add("set_bowler", innings=idx, bowler=f"{bw}{bowler}")
    if L.st()["innings"][idx]["status"] != "completed" and end:
        L.add("innings_end", innings=idx, reason=end)
    return L.st()


def match(plan, **fmt):
    L = Log(preset="multi_day", overs=None, extra_fmt=fmt)
    st = None
    for i, (b, r, o, e) in enumerate(plan):
        st = play(L, i, b, r, o, e)
    return L, st


class Results(unittest.TestCase):
    def test_chase_win_by_wickets(self):
        _, st = match([("A", 200, 10, None), ("B", 150, 10, None), ("A", 100, 3, "declared"), ("B", 151, 3, None)])
        wk = 10 - st["innings"][3]["wickets"]
        self.assertEqual(st["result"]["text"], f"Beta won by {wk} wickets")
        self.assertGreaterEqual(wk, 7)

    def test_innings_win_normal_order(self):                      # was dead code before: never produced a result
        _, st = match([("A", 100, 10, None), ("B", 300, 10, None), ("A", 50, 10, None)])
        self.assertEqual(st["result"]["text"], "Beta won by an innings and 150 runs")
        self.assertTrue(st["result"]["final"])

    def test_innings_win_after_follow_on(self):
        _, st = match([("A", 400, 10, None), ("B", 150, 10, None), ("B", 100, 10, None)])
        self.assertEqual(st["result"]["text"], "Alpha won by an innings and 150 runs")

    def test_follow_on_then_chase(self):
        _, st = match([("A", 400, 10, None), ("B", 150, 10, None), ("B", 300, 10, None), ("A", 51, 0, None)])
        self.assertEqual(st["result"]["text"], "Alpha won by 10 wickets")

    def test_win_by_runs_tie_and_draw(self):
        base = [("A", 200, 10, None), ("B", 150, 10, None), ("A", 100, 3, "declared")]
        self.assertEqual(match(base + [("B", 100, 10, None)])[1]["result"]["text"], "Alpha won by 50 runs")
        self.assertEqual(match(base + [("B", 150, 10, None)])[1]["result"]["text"], "Match tied")
        self.assertEqual(match(base + [("B", 80, 3, "time")])[1]["result"]["text"], "Match drawn")

    def test_level_scores_at_time_is_a_draw_not_a_tie(self):
        base = [("A", 200, 10, None), ("B", 150, 10, None), ("A", 100, 3, "declared")]
        st = match(base + [("B", 150, 4, "time")])[1]
        self.assertEqual(st["result"]["status"], "draw")

    def test_time_expiring_early_is_a_draw_with_first_innings_lead(self):
        _, st = match([("A", 200, 10, None), ("B", 150, 10, None), ("A", 100, 3, "time")])
        self.assertEqual(st["result"]["text"], "Match drawn")
        self.assertEqual(st["result"]["first_innings_lead"], {"team": "A", "runs": 50})

    def test_not_final_while_in_progress(self):
        _, st = match([("A", 200, 10, None), ("B", 90, 4, None)])
        self.assertFalse(st["result"]["final"])
        self.assertEqual(st["status"], "live")


class FollowOn(unittest.TestCase):
    def two(self, a, b, days):
        L = Log(preset="multi_day", overs=None, extra_fmt={"days": days})
        play(L, 0, "A", a, 10)
        play(L, 1, "B", b, 10)
        return L

    def start3(self, L, batting, **kw):
        L.add("innings_start", innings=2, batting=batting, striker=f"{batting}1", non_striker=f"{batting}2",
              bowler=("A1" if batting == "B" else "B1"), **kw)
        return L.st()

    def test_follow_on_thresholds_by_match_length(self):
        for days, need in ((5, 200), (3, 150), (4, 150), (2, 100), (1, 75)):
            ok = self.start3(self.two(need + 50, 50, days), "B")      # lead = need exactly
            self.assertEqual(ok["integrity"]["errors"], [], f"{days} days lead {need}")
            bad = self.start3(self.two(need + 49, 50, days), "B")     # lead = need-1
            self.assertEqual([e["code"] for e in bad["integrity"]["errors"]], ["follow_on"], f"{days} days lead {need - 1}")
            self.assertTrue(bad["integrity"]["errors"][0]["soft"])

    def test_follow_on_can_be_forced(self):
        L = self.two(120, 50, 2)
        L.add("innings_start", innings=2, batting="B", striker="B1", non_striker="B2", bowler="A1")
        self.assertEqual(L.st()["integrity"]["errors"][0]["code"], "follow_on")
        L.m["events"].pop()
        self.assertEqual(self.start3(L, "B", force=["follow_on"])["integrity"]["errors"], [])

    def test_normal_third_innings_has_no_follow_on_check(self):
        st = self.start3(self.two(100, 90, 2), "A")
        self.assertEqual(st["integrity"]["errors"], [])

    def test_side_cannot_bat_three_times(self):
        L = self.two(400, 100, 3)
        self.start3(L, "B")
        self.assertEqual(L.st()["integrity"]["errors"], [])
        L.add("innings_end", innings=2, reason="declared")
        L.add("innings_start", innings=3, batting="B", striker="B1", non_striker="B2", bowler="A1")
        self.assertEqual([e["code"] for e in L.st()["integrity"]["errors"]], ["team_innings_limit"])

    def test_play_block_flags_follow_on(self):
        L = self.two(400, 100, 3)
        self.start3(L, "B")
        self.assertTrue(L.st()["play"]["follow_on"])


class DaysAndSessions(unittest.TestCase):
    def test_default_is_day1_session1(self):
        L = Log(preset="multi_day", overs=None)
        pl = L.st()["play"]
        self.assertEqual((pl["day"], pl["session"], pl["label"]), (1, 1, "DAY 1 · SESSION 1"))

    def test_limited_overs_have_no_play_block(self):
        self.assertIsNone(Log(overs=20).st()["play"])

    def test_lunch_tea_stumps_advance_on_resume(self):
        L = Log(preset="multi_day", overs=None, extra_fmt={"days": 2})
        play(L, 0, "A", 30, 1, None)
        L.add("delay", kind="lunch")
        st = L.st()
        self.assertEqual(st["status"], "delayed")
        self.assertEqual(st["play"]["session"], 1)                         # not until play resumes
        L.add("resume")
        self.assertEqual(L.st()["play"]["session"], 2)
        L.add("delay", kind="tea")
        L.add("resume")
        self.assertEqual(L.st()["play"]["session"], 3)
        L.add("delay", kind="stumps")
        L.add("resume")
        pl = L.st()["play"]
        self.assertEqual((pl["day"], pl["session"]), (2, 1))
        self.assertTrue(pl["last_day"])
        self.assertEqual(pl["today"]["balls"], 0)                          # today's counters restart

    def test_rain_and_drinks_do_not_move_the_session(self):
        L = Log(preset="multi_day", overs=None)
        for k in ("drinks", "rain", "bad_light", "injury", "other"):
            L.add("delay", kind=k)
            L.add("resume")
        self.assertEqual(L.st()["play"]["session"], 1)

    def test_rain_during_lunch_still_advances_the_session(self):
        L = Log(preset="multi_day", overs=None)
        L.add("delay", kind="lunch")
        L.add("delay", kind="rain")
        L.add("resume")
        self.assertEqual(L.st()["play"]["session"], 2)

    def test_today_and_session_totals_and_overs_left(self):
        L = Log(preset="multi_day", overs=None, extra_fmt={"days": 2, "overs_per_day": 90})
        play(L, 0, "A", 60, 2, None)                                       # innings still open
        self.assertEqual(L.st()["play"]["today"]["runs"], 60)
        L.add("delay", kind="lunch")
        L.add("resume")
        nb = 0
        for _ in range(6):
            if L.st()["current"]["pending_bowler"]:
                nb += 1
                L.add("set_bowler", innings=0, bowler=f"B{2 + nb % 3}")
            L.add("ball", innings=0, bat_runs=1)
        pl = L.st()["play"]
        self.assertEqual(L.st()["integrity"]["errors"], [])
        self.assertEqual(pl["session_stats"]["runs"], 6)
        self.assertEqual(pl["today"]["runs"], 66)
        self.assertEqual(pl["overs_left_balls"], 90 * 6 - pl["today"]["balls"])

    def test_day_set_override_and_validation(self):
        L = Log(preset="multi_day", overs=None)
        L.add("day_set", day=2, session=3)
        self.assertEqual((L.st()["play"]["day"], L.st()["play"]["session"]), (2, 3))
        L.add("day_set", day=0, session=1)
        self.assertEqual(L.st()["integrity"]["errors"][-1]["code"], "bad_day")

    def test_new_ball_resets_ball_age(self):
        L = Log(preset="multi_day", overs=None, extra_fmt={"new_ball_after": 80})
        play(L, 0, "A", 60, 2, None)
        self.assertNotEqual(L.st()["play"]["ball_age"], "0.0")
        L.add("new_ball")
        self.assertEqual(L.st()["play"]["ball_age"], "0.0")
        self.assertFalse(L.st()["play"]["new_ball_available"])

    def test_new_ball_becomes_available(self):
        L = Log(preset="multi_day", overs=None, extra_fmt={"new_ball_after": 1})
        L.add("innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B1")
        for _ in range(6):
            L.add("ball", innings=0, bat_runs=0)
        self.assertTrue(L.st()["play"]["new_ball_available"])

    def test_removing_a_break_event_rederives_the_session(self):        # the event log is the truth
        L = Log(preset="multi_day", overs=None)
        L.add("delay", kind="lunch")
        L.add("resume")
        L.m["events"].pop()
        L.m["events"].pop()
        self.assertEqual(L.st()["play"]["session"], 1)


class LeadTrail(unittest.TestCase):
    def test_lead_and_trail_through_the_match(self):
        L = Log(preset="multi_day", overs=None)
        play(L, 0, "A", 200, 10)
        self.assertIsNone(L.st()["current"]["lead"])                       # nothing to compare in the first innings
        play(L, 1, "B", 80, 3, None)
        c = L.st()["current"]
        self.assertEqual((c["lead"], c["lead_text"]), (-120, "Beta trail by 120 runs"))
        self.assertEqual(c["status_line"], "Beta trail by 120 runs")
        L.add("ball", innings=1, bat_runs=1)
        self.assertEqual(L.st()["current"]["lead"], -119)

    def test_lead_in_third_innings_and_target_in_fourth(self):
        L = Log(preset="multi_day", overs=None)
        play(L, 0, "A", 200, 10)
        play(L, 1, "B", 150, 10)
        st = play(L, 2, "A", 40, 1, None)
        self.assertEqual(st["current"]["lead_text"], "Alpha lead by 90 runs")
        L.add("innings_end", innings=2, reason="declared")
        st = play(L, 3, "B", 10, 0, None)
        c = st["current"]
        self.assertIsNone(c["lead"])
        self.assertEqual(c["target"], 91)                                  # 240 - 150 + 1
        self.assertEqual(c["need"], 81)

    def test_scores_strings(self):
        L = Log(preset="multi_day", overs=None)
        play(L, 0, "A", 200, 10)
        play(L, 1, "B", 150, 10)
        st = play(L, 2, "A", 60, 2, "declared")
        self.assertEqual(st["play"]["scores"], {"A": "200 & 60/2d", "B": "150"})


class Robustness(unittest.TestCase):
    def test_long_two_day_match_is_fast(self):
        """~2,000 balls + breaks: every API call replays the log a few times, so derive must stay fast."""
        L = Log(preset="multi_day", overs=None, extra_fmt={"days": 2})
        rnd = random.Random(7)
        for idx, bt in enumerate("ABAB"):
            bw = "B" if bt == "A" else "A"
            L.add("innings_start", innings=idx, batting=bt, striker=f"{bt}1", non_striker=f"{bt}2", bowler=f"{bw}1")
            nxt = 3
            bowler = 1
            for b in range(1, 520):
                if rnd.random() < 0.012 and nxt <= 10:
                    L.add("ball", innings=idx, wicket={"kind": "bowled", "new_batter": f"{bt}{nxt}"})
                    nxt += 1
                else:
                    L.add("ball", innings=idx, bat_runs=rnd.choice([0, 0, 0, 1, 1, 2, 4]))
                if b % 6 == 0:
                    bowler = bowler % 5 + 1
                    L.add("set_bowler", innings=idx, bowler=f"{bw}{bowler}")
                if b % 200 == 0:
                    L.add("delay", kind="drinks")
                    L.add("resume")
            L.add("innings_end", innings=idx, reason="declared")
        n = len(L.m["events"])
        t = time.time()
        for _ in range(5):
            st = E.derive(copy.deepcopy(L.m))
        per = (time.time() - t) / 5
        self.assertGreater(n, 1800)
        self.assertLess(per, 0.25, f"derive of {n} events took {per:.3f}s")
        self.assertIn("play", st)

    def test_fuzz_never_crashes_and_stays_consistent(self):
        """Random (often invalid) event streams must never raise; totals equal batters + extras unless overridden."""
        rnd = random.Random(11)
        kinds = ["ball"] * 5 + ["set_bowler", "delay", "resume", "new_ball", "day_set", "innings_end", "innings_start", "swap_strike", "result", "clear_result"]
        for trial in range(120):
            L = Log(preset="multi_day", overs=None, extra_fmt={"days": rnd.choice([None, 2, 3])})
            for _ in range(rnd.randint(5, 150)):
                k = rnd.choice(kinds)
                idx = rnd.choice([0, 0, 1, 2, 3, 9])
                if k == "ball":
                    ev = {"innings": idx, "bat_runs": rnd.choice([0, 1, 4, 6, 9]), "delivery": rnd.choice(["legal", "legal", "wide", "noball", "bogus"])}
                    if rnd.random() < 0.1:
                        ev["wicket"] = {"kind": rnd.choice(["bowled", "caught", "run_out", "lbw", "zzz"]), "new_batter": rnd.choice(["A3", "B3", None, "Q9"])}
                    L.add("ball", **ev)
                elif k == "set_bowler":
                    L.add(k, innings=idx, bowler=rnd.choice(["A1", "B1", "B2", "A4", "X"]))
                elif k == "delay":
                    L.add(k, kind=rnd.choice(["lunch", "tea", "stumps", "rain", "zzz", None]))
                elif k == "day_set":
                    L.add(k, day=rnd.choice([0, 1, 2, 99]), session=rnd.choice([0, 1, 3, 9]))
                elif k == "innings_end":
                    L.add(k, innings=idx, reason=rnd.choice(["declared", "time", "all_out", "zzz"]))
                elif k == "innings_start":
                    b = rnd.choice(["A", "B"])
                    L.add(k, innings=idx, batting=b, striker=f"{b}1", non_striker=f"{b}2", bowler=("B1" if b == "A" else "A1"),
                          force=rnd.choice([[], ["follow_on"], ["prev_open"]]))
                elif k == "result":
                    L.add(k, status=rnd.choice(["draw", "won", "tie", "zzz"]), winner=rnd.choice(["A", "B", None]))
                else:
                    L.add(k)
            st = L.st()                                                    # must not raise
            self.assertIn("play", st)
            for inn in st["innings"]:
                bat = sum(b["runs"] for b in inn["batters"] if b["status"] != "yet_to_bat")
                if not inn["overridden"]:
                    self.assertEqual(bat + inn["extras"]["total"], inn["runs"], f"trial {trial}")
            self.assertGreaterEqual(st["play"]["day"], 1)
            self.assertGreaterEqual(st["play"]["today"]["runs"], 0)


if __name__ == "__main__":
    unittest.main()
