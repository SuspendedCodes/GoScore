"""Probe the ORIGINAL poc_core.derive_cricket_state with crafted event logs.
Every finding printed here is observed behaviour of the shipped code, not speculation."""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("poc_core", "" + __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "legacy", "poc_core.py") + "")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

MATCH = {"team_a": "Alpha", "team_b": "Beta", "overs_limit": 2, "balls_per_over": 6}
def start(striker="A1", non="A2", bowler="B1", inn=0, team="Alpha"):
    return {"type": "innings_start", "innings": inn, "batting_team": team, "striker": striker, "non_striker": non, "bowler": bowler}
def ball(**kw):
    kw.setdefault("innings", 0); kw.setdefault("type", "ball"); return kw
def run(evs, match=MATCH):
    return m.derive_cricket_state(match, evs)
def inn0(s): return s["innings"][0]
def banner(t): print("\n=== " + t)

# 1. strike rotation depends on a separate 'ran' field, not on runs scored
banner("1. single off the bat, 'ran' not supplied")
s = run([start(), ball(delivery="legal", bat_runs=1)])
print("striker/non-striker after a single:", inn0(s)["striker"], inn0(s)["non_striker"], "(expected A2 / A1)")

# 2. maidens never computed
banner("2. maiden over")
evs = [start()] + [ball(delivery="legal", bat_runs=0) for _ in range(6)]
s = run(evs); print("B1 figures after 6 dot balls:", inn0(s)["bowlers"]["B1"])

# 3. double count wide + bye
banner("3. wide with extra_type=bye, extra_runs=2")
s = run([start(), ball(delivery="wide", extra_type="bye", extra_runs=2)])
i = inn0(s); print("runs", i["runs"], "extras", i["extras"], "(wide+2 runs = 3 total expected)")

# 4. overthrows not off the bat booked as 'penalty'
banner("4. 1 bye + 1 overthrow (not to bat)")
s = run([start(), ball(delivery="legal", extra_type="bye", extra_runs=1, overthrow_runs=1, ran=1)])
i = inn0(s); print("extras", i["extras"], "(overthrows after a bye are byes, not penalty runs)")

# 5. illegal dismissals accepted
banner("5. caught off a no ball / bowled off a wide")
s = run([start(), ball(delivery="noball", wicket={"kind": "caught", "out_player": "A1", "fielder": "F", "new_batter": "A3"})])
print("wickets after caught off no-ball:", inn0(s)["wickets"], "(must be 0)")
s = run([start(), ball(delivery="wide", wicket={"kind": "bowled", "out_player": "A1", "new_batter": "A3"})])
print("wickets after bowled off wide:", inn0(s)["wickets"], "(must be 0)")

# 6. retired hurt marks batter OUT
banner("6. retired hurt")
s = run([start(), ball(delivery="legal", wicket={"kind": "retired_hurt", "out_player": "A1", "new_batter": "A3"})])
print("A1:", inn0(s)["batters"]["A1"], " legal_balls consumed:", inn0(s)["legal_balls"])

# 7. dismissal text
banner("7. dismissal strings")
for kind, fld in [("run_out", "F1"), ("caught_bowled", None), ("timed_out", None), ("caught", "F2")]:
    s = run([start(), ball(delivery="legal", wicket={"kind": kind, "out_player": "A1", "fielder": fld, "new_batter": "A3"})])
    print(f"{kind:14s} ->", repr(inn0(s)["batters"]["A1"]["how"]))

# 8. this_over empties at end of over
banner("8. 'this_over' right after 6th legal ball")
s = run([start()] + [ball(delivery="legal", bat_runs=1, ran=1) for _ in range(6)])
print("balls in this_over:", len(s["this_over"]), "| overs:", inn0(s)["overs"])

# 9. no tie/margin, hard-coded 10 wickets
banner("9. result line when chase falls 1 short / tie; 4-a-side style all out")
evs = [start(), ball(delivery="legal", bat_runs=1, ran=1)]
evs += [start(striker="B1", non="B2", bowler="A9", inn=1, team="Beta")]
s = run(evs, {**MATCH, "overs_limit": 1})
print("chase result_line mid:", s["result_line"])
evs2 = [start()] + [ball(delivery="legal", bat_runs=1, ran=1) for _ in range(6)]
evs2 += [start(striker="B1", non="B2", bowler="A9", inn=1, team="Beta")] + [ball(innings=1, delivery="legal", bat_runs=1, ran=1) for _ in range(6)]
s = run(evs2, {**MATCH, "overs_limit": 1})
print("tied score 6 v 6, result_line:", s["result_line"])
evs3 = [start()] + [ball(delivery="legal", bat_runs=1, ran=1) for _ in range(6)]
evs3 += [start(striker="B1", non="B2", bowler="A9", inn=1, team="Beta")] + [ball(innings=1, delivery="legal", bat_runs=0) for _ in range(6)]
s = run(evs3, {**MATCH, "overs_limit": 1})
print("fell short by 6, result_line:", s["result_line"])

# 10. balls accepted after innings complete
banner("10. balls after overs limit")
evs = [start()] + [ball(delivery="legal", bat_runs=1, ran=1) for _ in range(14)]
s = run(evs); print("legal balls with limit 2 overs:", inn0(s)["legal_balls"], "overs:", inn0(s)["overs"])

# 11. XML with real names
banner("11. XML export with a real player name")
s = run([start(striker="Virat Kohli", non="R Sharma", bowler="J Bumrah"), ball(delivery="legal", bat_runs=1, ran=1)])
try:
    x = m.state_to_xml(s); print("XML produced, length", len(x))
except Exception as e:
    print("XML export FAILED:", type(e).__name__, e)

# 12. free hit not modelled
banner("12. free hit")
s = run([start(), ball(delivery="noball"), ball(delivery="legal", wicket={"kind": "bowled", "out_player": "A1", "new_batter": "A3"})])
print("bowled on free-hit delivery counted as wicket:", inn0(s)["wickets"] == 1)

# 13. penalty runs only reachable through overthrow field; adjustments only touch team total
banner("13. adjustment event")
s = run([start(), {"type": "adjustment", "innings": 0, "runs_delta": 5, "wickets_delta": 0, "reason": "x"}])
i = inn0(s); print("team runs", i["runs"], "| batters:", {k: v["runs"] for k, v in i["batters"].items()}, "| extras", i["extras"]["total"], "(totals no longer reconcile)")

# 14. bowler quota / consecutive overs
banner("14. same bowler bowls consecutive overs")
evs = [start()] + [ball(delivery="legal", bat_runs=0) for _ in range(12)]
s = run(evs, {**MATCH, "overs_limit": 20}); print("accepted; B1 balls:", inn0(s)["bowlers"]["B1"]["balls"])

# 15. wicket without runs reconcile: out_player not at crease
banner("15. dismissing a player who is not at the crease")
s = run([start(), ball(delivery="legal", wicket={"kind": "bowled", "out_player": "ZZ", "new_batter": "A3"})])
i = inn0(s); print("wickets", i["wickets"], "striker", i["striker"], "(ZZ was never batting; A1 still at crease)")
