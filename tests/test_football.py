import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from goscore import football as F
from goscore import sports as S
from goscore.store import Store, StoreError
import tempfile

T0 = 1_000_000_000_000
MIN = 60_000


def squad(prefix, n=16):
    return [{"name": f"{prefix}{i} Surname{i}", "number": i, "pos": "GK" if i == 1 else ("DF" if i < 6 else "MF" if i < 9 else "FW")} for i in range(1, n + 1)]


class M:
    """Tiny driver: appends events like the store does (stamp, validate) and keeps a manual clock."""
    def __init__(self, fmt=None):
        self.m = {"id": "m", "sport": "football", "title": "t", "format": fmt or {}, "teams": {"A": {"name": "Reds", "players": squad("A")}, "B": {"name": "Blues", "players": squad("B")}}, "events": []}
        F.normalize_setup(self.m)
        self.t = T0
        self.n = 0

    def at(self, minutes, seconds=0):
        self.t = T0 + minutes * MIN + seconds * 1000
        return self

    def add(self, type_, expect_error=None, **kw):
        self.n += 1
        ev = {"id": f"e{self.n}", "type": type_, "ts": self.t, **kw}
        F.prepare_event(self.m, ev)
        err = F.validate_append(self.m, ev)
        if expect_error:
            assert err and err["code"] == expect_error, f"expected {expect_error}, got {err}"
            return err
        assert err is None, f"{type_} rejected: {err}"
        self.m["events"].append(ev)
        return ev

    @property
    def st(self):
        return F.derive(copy.deepcopy(self.m))

    def kickoff(self):
        self.at(0).add("period_start"); return self

    def play_to(self, minute):
        self.at(minute); return self

    def finish_regulation(self):
        self.at(45).add("period_end"); self.at(60).add("period_start"); self.at(105).add("period_end"); return self


class Clock(unittest.TestCase):
    def test_stamp_minutes_and_stoppage(self):
        m = M().kickoff()
        m.at(22, 10); g = m.add("goal", team="A", player="A9")
        self.assertEqual((g["min"], g["extra"], g["label"]), (23, 0, "23'"))
        m.at(46, 5); g = m.add("goal", team="A", player="A9")
        self.assertEqual(g["label"], "45+2'")          # 46:05 into a 45-minute half => 2nd minute of stoppage
        m.at(45); m.add("period_end")
        m.at(60); m.add("period_start")
        m.at(60 + 10, 30); g = m.add("goal", team="B", player="B9")
        self.assertEqual(g["label"], "56'")            # 10:30 into 2nd half = 55:30 -> 56th minute

    def test_first_half_exactly_zero(self):
        m = M().kickoff(); m.at(0, 0); g = m.add("card", team="A", player="A5", color="yellow")
        self.assertEqual(g["label"], "1'")

    def test_pause_resume_and_clock_set(self):
        m = M().kickoff()
        m.at(10).add("pause", reason="injury")
        m.at(14).add("resume")
        m.at(20); self.assertEqual(m.st["clock"]["base_ms"], 10 * MIN)       # 4 minutes stopped do not count
        m.add("clock_set", minute=30, second=0)
        st = m.st; self.assertEqual(st["clock"]["base_ms"], 30 * MIN)
        m.at(21); g = m.add("goal", team="A", player="A9"); self.assertEqual(g["min"], 32)

    def test_clock_set_rejects_before_period(self):
        m = M().kickoff(); m.at(45).add("period_end"); m.at(50).add("period_start")
        m.at(51).add("clock_set", expect_error="bad_clock", minute=10, second=0)

    def test_late_start(self):
        m = M(); m.at(0).add("period_start", ago_ms=30000)
        self.assertEqual(m.st["clock"]["base_ms"], 30000)

    def test_flow_errors(self):
        m = M()
        m.add("period_end", expect_error="not_live")
        m.add("goal", expect_error="goal_not_live", team="A", player="A9")
        m.kickoff()
        m.add("period_start", expect_error="bad_period")
        m.at(20).add("period_end", expect_error="premature")
        m.at(45).add("period_end")
        m.add("goal", expect_error="goal_not_live", team="A", player="A9")

    def test_period_end_force(self):
        m = M().kickoff(); m.at(20)
        e = m.add("period_end", expect_error="premature")
        self.assertTrue(e["soft"])
        m.add("period_end", force=["premature"])
        self.assertEqual(m.st["phase"], "break1")


class Goals(unittest.TestCase):
    def test_score_and_scorers(self):
        m = M().kickoff()
        m.at(10).add("goal", team="A", player="A9", assist="A8")
        m.at(20).add("goal", team="A", player="A9", kind="penalty")
        m.at(30).add("goal", team="B", player="B10")
        st = m.st
        self.assertEqual((st["score"]["A"], st["score"]["B"]), (2, 1))
        self.assertEqual(st["scorers"]["A"][0]["times"], ["11'", "21' (pen)"])
        self.assertEqual(st["teams"]["A"]["players"][8]["goals"], 2)
        self.assertEqual(st["teams"]["A"]["players"][7]["assists"], 1)

    def test_own_goal_credited_to_opponent(self):
        m = M().kickoff()
        m.at(10).add("goal", team="B", player="A3", kind="own_goal")     # A3 (Reds) put it in his own net: Blues credited
        st = m.st
        self.assertEqual((st["score"]["A"], st["score"]["B"]), (0, 1))
        self.assertEqual(st["teams"]["A"]["players"][2]["own_goals"], 1)
        self.assertEqual(st["teams"]["A"]["players"][2]["goals"], 0)
        self.assertEqual(st["scorers"]["B"][0]["times"], ["11' (OG)"])
        m.add("goal", expect_error="player_team", team="B", player="A3", kind="open")     # wrong team's player
        m.add("goal", expect_error="og_assist", team="B", player="A3", kind="own_goal", assist="B8")

    def test_scorer_must_be_on_pitch_soft(self):
        m = M().kickoff()
        e = m.add("goal", expect_error="not_on_pitch", team="A", player="A14")      # bench player
        self.assertTrue(e["soft"])
        m.add("goal", team="A", player="A14", force=["not_on_pitch"])

    def test_assist_same_as_scorer(self):
        m = M().kickoff(); m.add("goal", expect_error="same_player", team="A", player="A9", assist="A9")

    def test_goal_cancel_and_rescind(self):
        m = M().kickoff()
        m.at(10).add("goal", team="A", player="A9", assist="A8")
        m.at(11).add("var_check", kind="goal", team="A")
        self.assertTrue(m.st["var"]["active"])
        m.at(12).add("var_result", decision="goal_disallowed", reason="offside"); m.add("goal_cancel", reason="offside")
        st = m.st
        self.assertEqual(st["score"]["A"], 0); self.assertFalse(st["var"]["active"])
        self.assertEqual(st["teams"]["A"]["players"][8]["goals"], 0); self.assertEqual(st["scorers"]["A"], [])
        m.add("goal_cancel", expect_error="no_goal")

    def test_score_override_pins_then_adds(self):
        m = M().kickoff(); m.at(5).add("goal", team="A", player="A9")
        m.at(6).add("score_set", A=3, B=2, reason="fix")
        self.assertEqual(m.st["score"]["text"], "3-2")
        m.at(7).add("goal", team="B", player="B9")
        self.assertEqual(m.st["score"]["text"], "3-3")
        m.add("score_set", expect_error="bad_score", A=-1, B=0)


class Pitch(unittest.TestCase):
    def test_drag_positions_and_sub_inherits(self):
        m = M().kickoff()
        m.add("pitch_set", team="A", positions={"A9": {"x": 80, "y": 30.5}}, formation="4-3-3")
        a = m.st["teams"]["A"]; self.assertEqual(a["formation"], "4-3-3")
        p9 = next(p for p in a["players"] if p["id"] == "A9"); self.assertEqual((p9["x"], p9["y"]), (80.0, 30.5))
        m.at(60).add("sub", team="A", off="A9", on="A13")
        p13 = next(p for p in m.st["teams"]["A"]["players"] if p["id"] == "A13"); self.assertEqual((p13["x"], p13["y"]), (80.0, 30.5))
        m.add("pitch_set", team="A", positions={"A13": {"x": 60, "y": 70}})
        p13 = next(p for p in m.st["teams"]["A"]["players"] if p["id"] == "A13"); self.assertEqual((p13["x"], p13["y"]), (60.0, 70.0))

    def test_bad_coordinates_rejected(self):
        m = M().kickoff()
        m.add("pitch_set", expect_error="bad_xy", team="A", positions={"A9": {"x": 120, "y": 5}})

    def test_reset_and_undo_friendly(self):
        m = M().kickoff(); m.add("pitch_set", team="B", positions={"B9": {"x": 50, "y": 50}}); m.add("pitch_set", team="B", reset=True)
        self.assertIsNone(next(p for p in m.st["teams"]["B"]["players"] if p["id"] == "B9")["x"])


class Cards(unittest.TestCase):
    def test_second_yellow_is_red_and_cannot_be_replaced(self):
        m = M().kickoff()
        m.at(10).add("card", team="B", player="B5", color="yellow")
        m.at(20).add("card", team="B", player="B5", color="yellow")
        st = m.st; p = st["teams"]["B"]["players"][4]
        self.assertEqual(p["status"], "sent_off"); self.assertEqual(p["dismissal"], "yellow2")
        self.assertEqual(st["teams"]["B"]["on_field"], 10); self.assertEqual(st["teams"]["B"]["red_cards"], 1); self.assertEqual(st["teams"]["B"]["yellow_cards"], 2)
        m.add("card", expect_error="already_sent_off", team="B", player="B5", color="red")
        m.add("sub", expect_error="off_not_on", team="B", off="B5", on="B12")

    def test_straight_red_and_bench_red(self):
        m = M().kickoff()
        m.at(5).add("card", team="A", player="A3", color="red")
        m.at(6).add("card", team="A", player="A14", color="red")          # substitute sent off from bench
        st = m.st
        self.assertEqual(st["teams"]["A"]["on_field"], 10)
        self.assertEqual(st["teams"]["A"]["players"][13]["status"], "bench_sent_off")
        m.add("sub", expect_error="sent_off_sub", team="A", off="A2", on="A14")

    def test_card_rescind_restores(self):
        m = M().kickoff()
        c = m.at(5).add("card", team="A", player="A3", color="red")
        m.at(6).add("card_rescind", ref=c["id"])
        st = m.st; self.assertEqual(st["teams"]["A"]["on_field"], 11); self.assertEqual(st["teams"]["A"]["red_cards"], 0)

    def test_staff_card(self):
        m = M().kickoff(); m.add("card", team="A", target="staff", staff_name="Coach", color="red")
        st = m.st; self.assertEqual(st["teams"]["A"]["on_field"], 11); self.assertEqual(st["teams"]["A"]["red_cards"], 0); self.assertEqual(st["teams"]["A"]["staff_sent_off"], 1)

    def test_below_minimum_flag(self):
        m = M({"min_players": 7}).kickoff()
        for i in range(2, 6):
            m.add("card", team="A", player=f"A{i}", color="red")
        self.assertEqual(m.st["teams"]["A"]["on_field"], 7)
        self.assertFalse(m.st["teams"]["A"]["below_minimum"])              # 7 players is still allowed
        m.add("card", team="A", player="A6", color="red")
        self.assertTrue(m.st["teams"]["A"]["below_minimum"])               # 6 players: the match cannot continue


class Subs(unittest.TestCase):
    def test_basic_and_slot_inherit(self):
        m = M().kickoff(); m.at(60).add("sub", team="A", off="A9", on="A13")
        st = m.st; a = st["teams"]["A"]["players"]
        self.assertEqual(a[8]["status"], "off"); self.assertEqual(a[12]["status"], "on"); self.assertEqual(a[12]["slot"], a[8]["slot"])
        self.assertEqual(st["teams"]["A"]["subs"]["used"], 1); self.assertEqual(st["teams"]["A"]["on_field"], 11)

    def test_cannot_return_unless_allowed(self):
        m = M().kickoff(); m.at(30).add("sub", team="A", off="A9", on="A13")
        e = m.at(31).add("sub", expect_error="return", team="A", off="A10", on="A9"); self.assertTrue(e["soft"])
        y = M({"preset": "youth"}).kickoff(); y.at(30).add("sub", team="A", off="A9", on="A13"); y.at(31).add("sub", team="A", off="A10", on="A9")

    def test_on_must_be_bench_and_off_on_pitch(self):
        m = M().kickoff()
        m.add("sub", expect_error="on_already", team="A", off="A9", on="A10")
        m.add("sub", expect_error="off_not_on", team="A", off="A13", on="A14")
        m.add("sub", expect_error="same_player", team="A", off="A9", on="A9")

    def test_max_subs_soft_and_windows(self):
        m = M({"subs_max": 3, "windows_max": 2}).kickoff()
        m.at(50).add("sub", team="A", off="A2", on="A12")
        m.at(60).add("sub", team="A", off="A3", on="A13")
        e = m.at(70).add("sub", expect_error="windows_max", team="A", off="A4", on="A14"); self.assertTrue(e["soft"])
        m.add("sub", team="A", off="A4", on="A14", with_prev=True, force=[])    # same stoppage as previous? previous window was 60'
        self.assertEqual(m.st["teams"]["A"]["subs"]["used"], 3)
        m.at(80).add("sub", expect_error="subs_max", team="A", off="A5", on="A15")

    def test_halftime_subs_do_not_use_window(self):
        m = M({"windows_max": 1}).kickoff(); m.at(45).add("period_end")
        m.at(46).add("sub", team="A", off="A2", on="A12")
        m.at(47).add("sub", team="A", off="A3", on="A13")
        self.assertEqual(m.st["teams"]["A"]["subs"]["windows"], 0)
        m.at(60).add("period_start"); m.at(70).add("sub", team="A", off="A4", on="A14")
        self.assertEqual(m.st["teams"]["A"]["subs"]["windows"], 1)

    def test_concussion_and_additional(self):
        m = M({"subs_max": 0}).kickoff()
        m.at(20).add("sub", team="A", off="A9", on="A13", kind="concussion")
        st = m.st; self.assertEqual(st["teams"]["A"]["subs"]["used"], 0); self.assertEqual(st["teams"]["B"]["subs"]["additional_available"], 1)
        m.add("sub", expect_error="concussion", team="A", off="A8", on="A14", kind="concussion")
        m.add("sub", team="B", off="B9", on="B13", kind="additional")
        m.add("sub", expect_error="additional", team="B", off="B8", on="B14", kind="additional")

    def test_pre_match_replacement(self):
        m = M()
        m.add("card", team="A", player="A5", color="red")
        m.add("sub", team="A", off="A5", on="A12", kind="replacement")
        st = m.st; self.assertEqual(st["teams"]["A"]["on_field"], 11); self.assertEqual(st["teams"]["A"]["subs"]["used"], 0)

    def test_extra_time_extra_sub(self):
        m = M({"preset": "cup", "subs_max": 1, "windows_max": 1}).kickoff()
        m.at(50).add("sub", team="A", off="A2", on="A12")
        m.at(60).add("sub", expect_error="subs_max", team="A", off="A3", on="A13")
        m.finish_regulation(); m.at(110).add("period_start")
        m.at(120).add("sub", team="A", off="A3", on="A13")            # +1 in extra time (Law 3)


class Flow(unittest.TestCase):
    def test_regulation_win_ends(self):
        m = M().kickoff(); m.at(10).add("goal", team="A", player="A9"); m.at(45).add("period_end"); m.at(60).add("period_start"); m.at(105).add("period_end")
        st = m.st; self.assertEqual(st["phase"], "ended"); self.assertEqual(st["result"]["winner"], "A"); self.assertIn("won 1-0", st["result"]["text"])
        m.add("goal", expect_error="match_over", team="B", player="B9")

    def test_draw_no_et(self):
        m = M().kickoff(); m.finish_regulation(); st = m.st
        self.assertEqual(st["phase"], "ended"); self.assertEqual(st["result"]["kind"], "draw")

    def test_cup_goes_to_extra_time_then_pens(self):
        m = M({"preset": "cup"}).kickoff(); m.finish_regulation()
        self.assertEqual(m.st["phase"], "break2"); self.assertTrue(m.st["can_et"])
        m.at(110).add("period_start")                              # extra time 1st half
        self.assertEqual(m.st["phase"], "et1")
        m.at(112); g = m.add("goal", team="A", player="A9"); self.assertEqual(g["label"], "93'")   # 2:00 into extra time = 3rd minute of it
        m.at(125).add("period_end"); self.assertEqual(m.st["phase"], "break3")
        m.at(126).add("period_start"); m.at(141).add("goal", team="B", player="B9"); m.at(141).add("period_end")
        st = m.st; self.assertEqual(st["phase"], "pre_so")
        self.assertEqual(st["score"]["text"], "1-1")

    def test_et_not_needed_soft(self):
        m = M({"preset": "cup"}).kickoff(); m.at(5).add("goal", team="A", player="A9"); m.at(45).add("period_end"); m.at(60).add("period_start")
        m.at(105).add("period_end"); self.assertEqual(m.st["phase"], "ended")

    def test_aggregate(self):
        m = M({"preset": "second_leg", "aggregate": {"A": 0, "B": 1}}).kickoff()
        m.at(10).add("goal", team="A", player="A9"); m.finish_regulation()
        self.assertEqual(m.st["phase"], "break2")                  # 1-0 on the night, 1-1 on aggregate
        m.at(110).add("period_start"); m.at(112).add("goal", team="A", player="A9"); m.at(125).add("period_end"); m.at(126).add("period_start"); m.at(141).add("period_end")
        st = m.st; self.assertEqual(st["phase"], "ended"); self.assertEqual(st["result"]["kind"], "aggregate"); self.assertIn("on aggregate", st["result"]["text"])

    def test_added_time_and_abandon(self):
        m = M().kickoff(); m.at(44).add("added_time", minutes=4)
        self.assertEqual(m.st["clock"]["added_min"], 4)
        m.add("added_time", expect_error="bad_added", minutes=45)
        m.at(60).add("abandon", reason="Floodlight failure")
        st = m.st; self.assertEqual(st["phase"], "ended"); self.assertEqual(st["result"]["kind"], "abandoned")

    def test_manual_result_and_clear(self):
        m = M(); m.add("result", winner="B", kind="forfeit", text="Reds forfeited")
        self.assertEqual(m.st["result"]["text"], "Reds forfeited"); self.assertEqual(m.st["phase"], "ended")

    def test_phase_override(self):
        m = M().kickoff(); m.at(1).add("phase_set", phase="p2", elapsed_ms=0, running=True)
        self.assertEqual(m.st["phase"], "p2"); self.assertEqual(m.st["clock"]["period"], 2)


class Shootout(unittest.TestCase):
    def setup_so(self, **fmt):
        m = M({"preset": "cup_pens", **fmt}).kickoff(); m.finish_regulation()
        self.assertEqual(m.st["phase"], "pre_so")
        m.at(110).add("shootout_start", first="A")
        return m

    def kicks(self, m, results):
        a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        ka = kb = 0
        for i, r in enumerate(results):
            tid = "A" if i % 2 == 0 else "B"
            n = (ka if tid == "A" else kb); pid = f"{tid}{a[n % 11]}"
            m.add("shootout_kick", team=tid, player=pid, result=r)
            if tid == "A": ka += 1
            else: kb += 1

    def test_normal_five_each(self):
        m = self.setup_so()
        self.kicks(m, ["scored", "scored", "saved", "scored", "scored", "missed", "scored", "scored", "scored", "missed"])
        st = m.st; self.assertTrue(st["shootout"]["decided"]); self.assertEqual(st["shootout"]["winner"], "A"); self.assertEqual(st["phase"], "ended")
        self.assertEqual((st["shootout"]["goals"]["A"], st["shootout"]["goals"]["B"]), (4, 3)); self.assertIn("on penalties", st["result"]["text"])

    def test_early_finish(self):
        m = self.setup_so()
        self.kicks(m, ["scored", "missed", "scored", "missed", "scored", "missed"])     # A 3, B 0 after 3 each: B max 2 more -> over
        st = m.st; self.assertTrue(st["shootout"]["decided"]); self.assertEqual(st["shootout"]["winner"], "A")
        self.assertEqual(st["shootout"]["taken"], {"A": 3, "B": 3})
        m.add("shootout_kick", expect_error="match_over", team="A", player="A9", result="scored")

    def test_sudden_death(self):
        m = self.setup_so()
        self.kicks(m, ["scored"] * 10)                       # 5-5
        self.assertFalse(m.st["shootout"]["decided"])
        m.add("shootout_kick", team="A", player="A6", result="scored"); self.assertFalse(m.st["shootout"]["decided"])   # not decided until B has kicked
        m.add("shootout_kick", team="B", player="B6", result="saved")
        st = m.st; self.assertTrue(st["shootout"]["decided"]); self.assertEqual(st["shootout"]["winner"], "A")

    def test_alternate_order_enforced(self):
        m = self.setup_so()
        m.add("shootout_kick", expect_error="so_order", team="B", player="B2", result="scored")
        m.add("shootout_kick", team="A", player="A2", result="scored")
        m.add("shootout_kick", expect_error="bad_result", team="B", player="B2", result="banana")

    def test_each_player_once_per_cycle(self):
        m = self.setup_so()
        m.add("shootout_kick", team="A", player="A2", result="scored"); m.add("shootout_kick", team="B", player="B2", result="scored")
        e = m.add("shootout_kick", expect_error="so_repeat", team="A", player="A2", result="scored"); self.assertTrue(e["soft"])

    def test_only_players_on_pitch_at_end(self):
        m = M({"preset": "cup_pens"}).kickoff(); m.at(30).add("card", team="A", player="A9", color="red"); m.finish_regulation(); m.at(110).add("shootout_start", first="B")
        m.add("shootout_kick", team="B", player="B2", result="scored")
        m.add("shootout_kick", expect_error="not_on_pitch", team="A", player="A9", result="scored")

    def test_start_requires_level_and_flow(self):
        m = M({"preset": "cup_pens"}).kickoff(); m.add("shootout_start", expect_error="so_not_now", first="A")


class Stats(unittest.TestCase):
    def test_manual_stats_and_derivations(self):
        m = M().kickoff()
        m.at(10).add("goal", team="A", player="A9"); m.at(11).add("card", team="B", player="B4", color="yellow")
        m.add("stats_set", values={"A": {"possession": 58, "shots": 9, "shots_on_target": 4, "passes": 400, "passes_completed": 340}, "B": {"shots": 3}})
        st = m.st; r = st["stats"]["rows"]
        self.assertEqual((r["possession"]["A"], r["possession"]["B"]), (58, 42.0)); self.assertEqual(r["possession"]["srcB"], "derived")
        self.assertEqual(r["pass_accuracy"]["A"], 85); self.assertEqual(r["pass_accuracy"]["srcA"], "derived")
        self.assertEqual((r["goals"]["A"], r["goals"]["srcA"]), (1, "auto")); self.assertEqual(r["yellow_cards"]["B"], 1)
        self.assertEqual(r["fouls"]["A"], None)
        self.assertEqual(r["possession"]["dA"], "58%")

    def test_manual_overrides_auto_and_clears(self):
        m = M().kickoff(); m.add("card", team="B", player="B4", color="yellow")
        m.add("stats_set", team="B", key="yellow_cards", value=3)
        self.assertEqual(m.st["stats"]["rows"]["yellow_cards"]["B"], 3)
        m.add("stats_set", team="B", key="yellow_cards", value=None)
        self.assertEqual(m.st["stats"]["rows"]["yellow_cards"]["B"], 1)

    def test_validation(self):
        m = M().kickoff()
        m.add("stats_set", expect_error="unknown_stat", team="A", key="vibes", value=3)
        m.add("stats_set", expect_error="bad_stat", team="A", key="shots", value="lots")
        m.add("stats_set", expect_error="bad_stat", team="A", key="shots", value=-1)
        m.add("stats_set", expect_error="bad_stat", team="A", key="possession", value=140)
        m.add("stats_set", expect_error="empty", values={})
        m.add("stats_set", expect_error="unknown_player", player="ZZ", values={"shots": 1})

    def test_warnings_not_errors(self):
        m = M().kickoff(); m.add("stats_set", values={"A": {"shots": 2, "shots_on_target": 5, "possession": 70}, "B": {"possession": 40}})
        w = m.st["stats"]["warnings"]; self.assertTrue(any("shots on target" in x for x in w)); self.assertTrue(any("Possession adds up" in x for x in w))

    def test_player_stats(self):
        m = M().kickoff(); m.at(30).add("goal", team="A", player="A9"); m.at(60).add("sub", team="A", off="A9", on="A13")
        m.add("stats_set", player="A9", values={"shots": 5, "passes": 20, "passes_completed": 15, "rating": 7.4})
        p = m.st["teams"]["A"]["players"][8]["stats"]
        self.assertEqual(p["shots"]["d"], "5"); self.assertEqual(p["pass_accuracy"]["d"], "75%"); self.assertEqual(p["rating"]["d"], "7.4")
        self.assertEqual(p["goals"]["v"], 1); self.assertEqual(p["minutes"]["v"], 61)

    def test_percent_and_comma_input(self):
        m = M().kickoff(); m.add("stats_set", team="A", key="possession", value="55,5%")
        self.assertEqual(m.st["stats"]["rows"]["possession"]["A"], 55.5)


class StoreIntegration(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.s = Store(self.d.name)
        self.mid = self.s.create({"sport": "football", "title": "x", "teams": {"A": {"name": "Reds", "players": squad("A")}, "B": {"name": "Blues", "players": squad("B")}}, "format": {"preset": "cup"}})["id"]

    def tearDown(self):
        self.d.cleanup()

    def test_create_is_football_and_stamped(self):
        m = self.s.get(self.mid); self.assertEqual(m["sport"], "football")
        self.s.add_event(self.mid, {"type": "period_start"})
        r = self.s.add_event(self.mid, {"type": "goal", "team": "A", "player": "A9"})
        self.assertIn("label", r["event"]); self.assertEqual(r["event"]["period"], 1)
        st = S.derive(copy.deepcopy(self.s.get(self.mid))); self.assertEqual(st["score"]["A"], 1)

    def test_rule_error_is_422(self):
        with self.assertRaises(StoreError) as c:
            self.s.add_event(self.mid, {"type": "goal", "team": "A", "player": "A9"})
        self.assertEqual(c.exception.status, 422)

    def test_undo_redo_edit_delete_insert(self):
        self.s.add_event(self.mid, {"type": "period_start"})
        g = self.s.add_event(self.mid, {"type": "goal", "team": "A", "player": "A9"})["event"]
        self.s.undo(self.mid); self.assertEqual(S.derive(copy.deepcopy(self.s.get(self.mid)))["score"]["A"], 0)
        self.s.redo_last(self.mid); self.assertEqual(S.derive(copy.deepcopy(self.s.get(self.mid)))["score"]["A"], 1)
        self.s.edit_event(self.mid, g["id"], {"team": "B", "player": "B9"}); st = S.derive(copy.deepcopy(self.s.get(self.mid)))
        self.assertEqual((st["score"]["A"], st["score"]["B"]), (0, 1))
        self.s.edit_event(self.mid, g["id"], {"min": 77, "extra": 0}); st = S.derive(copy.deepcopy(self.s.get(self.mid)))
        self.assertEqual(st["goals"]["B"][0]["label"], "77'")
        self.s.insert_event(self.mid, {"type": "goal", "team": "A", "player": "A9", "min": 12, "extra": 0}, after_id=g["id"])
        self.assertEqual(S.derive(copy.deepcopy(self.s.get(self.mid)))["score"]["text"], "1-1")
        self.s.delete_event(self.mid, g["id"]); self.assertEqual(S.derive(copy.deepcopy(self.s.get(self.mid)))["score"]["text"], "1-0")

    def test_bad_log_never_crashes(self):
        self.s.replace_events(self.mid, [{"type": "goal", "team": "A", "player": "A9"}, {"type": "nonsense"}, {"type": "period_start"}, {"type": "sub", "team": "Z"}])
        st = S.derive(copy.deepcopy(self.s.get(self.mid))); self.assertEqual(len(st["integrity"]["errors"]), 3); self.assertEqual(st["phase"], "p1")

    def test_summary_and_list(self):
        l = self.s.list(); self.assertEqual(l[0]["sport"], "football"); self.assertEqual(l[0]["score"], "0-0")

    def test_roundtrip_reload(self):
        self.s.add_event(self.mid, {"type": "period_start"}); self.s.add_event(self.mid, {"type": "goal", "team": "A", "player": "A9"})
        s2 = Store(self.d.name); self.assertEqual(s2.get(self.mid)["sport"], "football"); self.assertEqual(S.derive(copy.deepcopy(s2.get(self.mid)))["score"]["A"], 1)

    def test_cricket_default_sport(self):
        mid = self.s.create({"title": "c", "teams": {"A": {"name": "A", "players": []}, "B": {"name": "B", "players": []}}, "format": {"preset": "t20"}})["id"]
        self.assertEqual(self.s.get(mid)["sport"], "cricket"); self.assertEqual(S.derive(copy.deepcopy(self.s.get(mid)))["sport"], "cricket")


if __name__ == "__main__":
    unittest.main()
