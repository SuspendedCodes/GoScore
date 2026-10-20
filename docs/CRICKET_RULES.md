# Cricket rules implemented (and how to change them)

All values below are per-match **home rules**: edit on the Setup page (⚙) before or during a match.

## Formats
| Preset | Overs | Balls/over | Notes |
|---|---|---|---|
| T20 | 20 | 6 | Powerplay overs 1–6 |
| T10 | 10 | 6 | no powerplay label |
| ODI | 50 | 6 | PP 1–10, 11–40, 41–50 |
| 40 overs | 40 | 6 | |
| 100 balls | 20 sets | 5 | bowler 4 sets max, up to 2 consecutive, powerplay 1–5, shown in balls |
| Custom | any | any | any overs, balls/over, squad size |
| Multi-day | unlimited | 6 | 2 innings a side, no free hit, no quota |

Custom squad sizes are supported: all out = players in XI − 1 (override with `wickets_limit`).

## Laws applied
* **Legal delivery** counts toward the over; **wide** and **no-ball** do not and are re-bowled. Penalty = 1 (configurable, e.g. 2 for some leagues).
* **Wide**: all runs are wides. No bat runs, no byes/leg-byes on a wide.
* **No-ball**: 1 penalty + runs off the bat to the batter + byes/leg-byes as byes/leg-byes. Bat runs and byes cannot be on the same ball.
* **Dismissals by delivery type**
  * Legal: bowled, caught, lbw, run out, stumped, hit wicket, hit the ball twice, obstructing the field.
  * No-ball: run out, hit the ball twice, obstructing only.
  * Wide: run out, stumped, hit wicket, obstructing.
  * Free hit: run out, hit twice, obstructing only.
* **Striker-only**: bowled, caught, lbw, stumped, hit wicket, hit twice. Run out / obstructing may be either batter.
* **No runs** are recorded on bowled / caught / lbw / stumped / hit wicket. Runs completed before a run-out count.
* **Bowler credited** only for bowled, caught, lbw, stumped, hit wicket.
* **Free hit** follows a no-ball and carries over a wide or another no-ball.
* **Strike**: odd runs run swap ends; a boundary doesn't (unless you override `ran`); ends swap at the end of an over. After a catch where the batters crossed, the Laws don't say who is on strike — so the wicket window **asks** "who faces the next ball?".
* **Maiden**: no runs off the bat, wides or no-balls charged to the bowler in a completed over; byes/leg-byes allowed.
* **Over end** requires choosing the next bowler.
* **Soft rules** (rejected with the reason; the scorer can *Allow anyway*, which is logged): bowler's over quota, bowling consecutive overs, changing bowler mid-over, starting a new innings with the previous one still open, same team batting twice in one innings.
* **Retired**: *hurt* = not out and may resume; *out* = counted as a wicket (not the bowler's). **Timed out**, **substitution** (impact/concussion) supported.
* **Penalty runs** (5) go to the awarded side's innings; if that side hasn't batted yet they wait and are added when it does.
* **Innings ends** at overs limit, all out, target reached, declared/closed, or manually.
* **Results**: won by N wickets (with balls remaining), won by N runs, tie, super-over result, "(DLS)" tag; or set manually.
* **Super Over**: 1 over, 2 wickets; the side that batted second bats first.
* **DLS / revised target**: enter revised overs and target (calculated elsewhere) with *Revise*; it can be set before the innings begins. Shown with a DLS tag.

## Multi-day / Test (2 innings a side)
Choose the *Multi-day* preset (or "2 innings a side") in Setup; set **Days of play**, **Overs per day** (default 90) and **New ball after** (default 80 overs). Clear a box to hide that item on the overlay.
* **Days & sessions**: three sessions a day. *Break -> Lunch / Tea* then **Resume** advances the session; *Break -> Stumps* then **Resume** advances the day. Rain, bad light, drinks, injury and other stoppages do **not** change the session. If the day/session ever drifts, use *Match actions -> Day & session...* (logged as an override).
* **Follow-on** (MCC Law 14.1; soft rule - *Allow anyway* is available): lead of 200+ in a 5-day match, 150+ in 3-4 days, 100+ in a 2-day match, 75+ in a 1-day match. A side can never bat a third time (hard rule).
* **Results**: win by wickets, win by runs, win by an innings and N runs, tie (only if the 4th innings ends all out / overs complete with scores level), draw. A draw is set automatically when time expires in the last innings, or via *Close of play - match drawn* on the final day. If the match is drawn after only one completed innings each, a first-innings lead is shown.
* **Overlay**: LEAD BY / TRAIL BY / SCORES LEVEL block, DAY n/N and session tag, overs left today, NEW BALL DUE / NEW BALL IN n (last 10 overs), FOLLOWING ON; optional *Match state / day summary* panel.
* **Events**: `delay{kind: drinks|lunch|tea|stumps|rain|bad_light|injury|other}`, `resume`, `day_set{day,session}`, `new_ball`.
* **Sources**: MCC Law 14.1 thresholds and the usual Test day structure (3 x 2 h sessions, lunch 40 min, tea 20 min, 90 overs minimum a day, new ball available after 80 overs) were checked online. Check your own competition's playing conditions; they win.

## Event schema (for developers)
`ball`: `delivery(legal|wide|noball), bat_runs, boundary, byes, legbyes, wide_runs, ran, wicket{kind,out,fielder,fielder2,new_batter,new_batter_on_strike}, note, force`.
Others: `innings_start, set_bowler, set_batters, new_batter, swap_strike, retire, timed_out, penalty_runs, innings_end, revise, substitution, override, result, clear_result, toss, info, delay, resume`.
API: `POST /api/matches/{id}/events` with a client `cid` (idempotent) and optional `expected_version` (409 if stale).

## Sources / assumptions
Laws of Cricket (MCC) 2017 Code (Laws 18–21, 24–27, 31, 33–41, 42 as relevant), ICC playing-condition norms for T20/ODI powerplay and bowler quotas. These are written from knowledge of the Laws, not live-checked online; **the competition's own playing conditions win** — edit the defaults to match.
