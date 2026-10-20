# Sunday runbook — GoScore + OBS (match day Sun 11 Oct 2026)

**Do the rehearsal (section 4) on Saturday night.** The OBS control code was tested against a mock OBS, not your real one.

## 1. What runs where
* **Scoring laptop/phone** → `http://<server-ip>:8000/score/<match>` (the scorer). Tablet or phone works.
* **Broadcast PC (OBS)** → runs `python run.py` (or the scorer's PC does; OBS just needs the URL).
* **Production page** → `http://<server-ip>:8000/control/<match>` (whoever drives cameras/graphics). It also connects to OBS.
* One computer can do all of it; put scorer and production on different devices if you can.

Start the server: `python run.py` (Windows: double-click `run.bat`). It prints the LAN URLs. Optional PIN: `python run.py --pin 4821` (protects *changes only*; overlays still load).

## 2. One-time OBS setup
1. **Tools → WebSocket Server Settings**: enable, port 4455, set a password. (OBS 28+ has it built in.)
2. Create scenes, e.g. `CAM1 Wide`, `Bowler End`, `Batter End`, `Pitch`, `Replay`, `Scorecard`, `Break`, `Result`. (Order = keys 1–9 on the Production page.)
3. Add **one** Browser source named `GoScore Overlay` to **every** scene (or put it in a nested scene "Overlay" and add that to each):
   * URL: `http://<server-ip>:8000/overlay/live`  (`live` follows whichever match is marked LIVE)
   * Width **1920**, Height **1080**, FPS 30
   * Untick *Shutdown source when not visible* and *Refresh browser when scene becomes active*
   * Leave custom CSS empty. Background is transparent.
4. (Optional) In a Scorecard scene use a second Browser source: `/scorecard/live`, or `/overlay/live?only=panels`.
5. Text-from-file alternative (works with no browser source at all): *Text (GDI+/FreeType) → Read from file* → `…/output/live/text/scoreline.txt` etc. Files available: `scoreline, score, overs, striker, non_striker, bowler, this_over, last_ball, need, target, crr, rrr, status_line, partnership, last_wicket, toss, result, free_hit, powerplay, banner …`.

## 3. Data for vMix / other tools
| What | URL / file |
|---|---|
| Full JSON | `/feed/live.json` · `output/live/scoreboard.json` |
| XML | `/feed/live.xml` · `output/live/scoreboard.xml` |
| One value as text | `/feed/live/text/score.txt` |
| CSV (batting, bowling, FoW, ball-by-ball) | `/feed/live/csv/batting.csv` … |
Files are rewritten only when something changes, atomically (no half-written files).

## 4. Saturday rehearsal (30 min)
1. Create the match (index → New match): teams, XI, toss, format.
2. Open Production page → connect OBS → click each scene; confirm red tally follows OBS and you can switch from OBS itself.
3. Score a dummy innings: singles, a four, a wide, a no-ball then a free hit, a wicket, an over change. Watch the overlay.
4. Practise: **Undo**, **Edit a past ball**, **Manual override**, **Hold (H)**.
5. Set **Broadcast delay** to match your stream delay (e.g. 8 s). Check overlay lags that long.
6. Kill the scorer's Wi-Fi for 20 s and restore it: the page should reconnect by itself.
7. Delete the dummy match (or just create a fresh one for Sunday).

## 5. Match-day checklist
- [ ] Server running; scorer page shows green LIVE.
- [ ] Match marked LIVE (Production page tag is green). Overlay URL uses `/overlay/live`.
- [ ] OBS connected (green) and scenes listed; panic scene chosen.
- [ ] Toss + XI correct (Setup ⚙); correct overs/format.
- [ ] Delay set; test overlay once.
- [ ] Backup: second device has the scorer page open (read-only use until needed).

## 6. During play
**Scorer:** keys `0–6` runs, `D` wide, `N` no-ball, `B` bye, `L` leg-bye (press modifier first, then runs), `W` wicket, `U`/Ctrl+Z undo. Prompts appear for incoming batter and next bowler. In the wicket window answer *who faces the next ball*.
**Production:** `1–9` scenes, `Space` take (studio mode), `Esc` panic scene, `⌫` back to previous scene, `H` hold overlay. Pop-ups for FOUR/SIX/WICKET/50/100/FREE HIT are automatic; toggle them or fire manually.

## 6b. Showing the 1st innings during the 2nd
Production → **Panels show: Innings 1** → switch on *Scorecard* and *Bowling* (or *Innings summary*). The panels keep Innings 1's team colours and say "1ST INNINGS"; the scorebug stays on the live chase. Set **Auto-hide panels after** to 15–30 s so you don't have to remember to remove them. Return to **Live innings** afterwards.

## 6c. Players: roles, captain, keeper
Setup → set each player's **Role**, tick **C** (captain) and **WK** (keeper). Pick lists then show *Bowlers / All-rounders / Batters* sections; the wicket window has a **WK †** button, and a stumping defaults to the keeper. Scorecards show `(c)` and `†` and `c †Name b Bowler`.

## 7. When things go wrong
| Problem | Do this |
|---|---|
| Scorer mis-tapped | `U` (undo). Older ball: Events & corrections → ✎ Edit. |
| Missed a ball / extra | Events → Insert after / Delete. |
| Score is wrong and you can't see why | Manual override tab: pin runs/wickets/balls (reason required). |
| App blocks something real (soft rule) | **Allow anyway**. |
| Don't want viewers to see a correction | `H` Hold, fix, `H` release. |
| OBS control disconnected | Page auto-reconnects every 2 s. Use OBS hotkeys / mouse meanwhile; overlay is unaffected. |
| Overlay blank | Right-click source → Refresh. Check the URL opens in a browser. |
| Server crashed | Restart `run.py` — matches reload from disk; every change is journalled. Last 100 backups under the match's backups list. |
| Wrong result text | Match actions → Manual result. |
| Rain | Match actions → Rain delay / Revise (enter DLS figures you calculated). |

## 8. After the match
Index page → Export JSON (full match + log). Data is in `data/`; OBS files in `output/`.

## Limits to know
No DLS calculator (enter figures manually). Football not built. Defaults for powerplay/bowler quota are standard — check your competition's playing conditions and edit on the Setup page.

## Many browser tabs
Fixed in v2.1: scorer / production / scorecard pages now poll (1 s) instead of holding connections open, so any number of tabs is fine (tested with 12). Only the OBS overlay keeps a live stream. The Production overlay preview is off by default (button to show it). If a click ever doesn't get an answer within 8 s you'll see a message instead of a silent freeze.

## Football match day
1. Setup: paste lineups (XI + subs), formation, officials, info. 2. Go live, add overlay as Browser Source. 3. Kick-off: "Start 1st half" (clock follows server). 4. Producer: type stats in Production -> stats box; click a stat page to show it. 5. If wrong: Events tab to fix, or Manual override. Clock text file updates every second for OBS text sources.

## 5. Two-day (Test-style) match checklist
1. Setup: format **Multi-day**, Days = 2, Overs per day = 90, New ball after = 80 (or whatever your conditions say).
2. Scorebug now shows LEAD/TRAIL, DAY n/N, session and overs left. Production -> *Match state / day summary* shows a full-screen summary.
3. Each break: Match actions -> **Break / stumps / rain...** -> pick Lunch / Tea / Stumps -> later **Resume**. (Resume is what moves to the next session/day.)
4. New ball taken: Match actions -> **New ball taken**.
5. Follow-on: when starting the 3rd innings the scorer shows the margin; **Enforce follow-on** if it applies.
6. Day 2 close: if time runs out, Break dialog -> **Close of play - match drawn**. Declaring, all out or a chase finishing give the result automatically.
7. If anything looks wrong, Day & session... and Manual override fix it without breaking the scores. Undo works on breaks too.
